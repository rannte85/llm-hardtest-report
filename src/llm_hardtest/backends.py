from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from .common import save_json


class BackendError(RuntimeError):
    """A provider or agent process could not produce a usable completion."""

    pass


class Backend:
    """Small transport interface shared by all benchmark rounds."""

    def __init__(self, model: dict, state_dir: Path):
        self.model = model
        self.state_dir = state_dir.resolve()

    def complete(self, messages: list[dict], timeout: int) -> dict:
        raise NotImplementedError


class OpenAICompatBackend(Backend):
    """Call the OpenAI-compatible Chat Completions API using the stdlib."""

    def complete(self, messages: list[dict], timeout: int) -> dict:
        base = self.model.get("base_url", "http://127.0.0.1:8000/v1").rstrip("/")
        payload = {
            "model": self.model["model"],
            "messages": messages,
            "max_tokens": int(self.model.get("max_tokens", 16000)),
        }
        for key in ("temperature", "top_p", "top_k", "min_p", "reasoning_effort"):
            if self.model.get(key) is not None:
                payload[key] = self.model[key]
        headers = {"Content-Type": "application/json"}
        env_name = self.model.get("api_key_env")
        if env_name and os.environ.get(env_name):
            headers["Authorization"] = "Bearer " + os.environ[env_name]
        request = urllib.request.Request(
            base + "/chat/completions",
            data=json.dumps(payload).encode(), headers=headers, method="POST")
        started = time.time()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = json.load(response)
        except urllib.error.HTTPError as exc:
            # Provider bodies usually contain the actionable incompatibility reason.
            body = exc.read(4096).decode("utf-8", errors="replace")
            raise BackendError(
                f"OpenAI-compatible request returned HTTP {exc.code}: {body}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise BackendError(f"OpenAI-compatible request failed: {exc}") from exc
        if raw.get("error"):
            raise BackendError(str(raw["error"]))
        choices = raw.get("choices")
        if not isinstance(choices, list) or not choices:
            raise BackendError("OpenAI-compatible response has no choices")
        choice = choices[0]
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            # Some compatible servers use typed content parts instead of one string.
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        if not isinstance(content, str):
            raise BackendError("OpenAI-compatible response has no text message content")
        usage = raw.get("usage") or {}
        diagnostics = {
            "choice_fields": sorted(str(key) for key in choice),
            "message_fields": sorted(str(key) for key in message),
            "content_type": type(message.get("content")).__name__,
            "reasoning_content_present": bool(message.get("reasoning_content")),
        }
        return {
            "content": content,
            "wall": round(time.time() - started, 3),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "finish_reason": choice.get("finish_reason"),
            "raw_usage": usage,
            "provider_diagnostics": diagnostics,
        }


class CodexBackend(Backend):
    """Run Codex CLI with isolated state for text and repository-agent tasks."""

    def _env(self) -> dict:
        env = dict(os.environ)
        if self.model.get("codex_provider", "custom") == "openai":
            return env
        home = self.state_dir / "codex-homes" / self.model["key"]
        home.mkdir(parents=True, exist_ok=True)
        provider = "llm_hardtest_compat"
        base = self.model.get("base_url", "http://127.0.0.1:8000/v1")
        key_env = self.model.get("api_key_env", "LLM_HARDTEST_API_KEY")
        config = (
            f'model_provider = "{provider}"\n'
            f'model = {json.dumps(self.model["model"])}\n'
            f'model_context_window = {int(self.model.get("context_window", 131072))}\n'
            'approval_policy = "never"\n\n'
            f'[model_providers.{provider}]\n'
            'name = "LLM Hardtest OpenAI-compatible"\n'
            f'base_url = {json.dumps(base)}\n'
            f'env_key = {json.dumps(key_env)}\n'
            'wire_api = "responses"\n')
        config_path = home / "config.toml"
        config_path.write_text(config, encoding="utf-8")
        config_path.chmod(0o600)
        # Codex auth discovery expects the file to exist for a custom provider,
        # but the actual provider credential is supplied only through env_key.
        auth_path = home / "auth.json"
        save_json(auth_path, {"OPENAI_API_KEY": "local-dummy"})
        auth_path.chmod(0o600)
        env["CODEX_HOME"] = str(home)
        env.setdefault(key_env, "local-dummy")
        return env

    def complete(self, messages: list[dict], timeout: int) -> dict:
        prompt_parts = []
        for message in messages:
            prompt_parts.append(f'[{message.get("role", "user").upper()}]\n{message.get("content", "")}')
        prompt = "\n\n".join(prompt_parts)
        work = self.state_dir / "codex-text-work"
        work.mkdir(parents=True, exist_ok=True)
        last = self.state_dir / f'last-{self.model["key"]}-{time.time_ns()}.txt'
        cmd = ["codex", "exec", "-m", self.model["model"], "-C", str(work),
               "-s", "read-only", "--skip-git-repo-check", "--ephemeral",
               "-c", 'approval_policy="never"', "-o", str(last)]
        effort = self.model.get("reasoning_effort")
        if effort:
            cmd += ["-c", f'model_reasoning_effort="{effort}"']
        if self.model.get("codex_provider", "custom") == "openai":
            cmd.append("--ignore-user-config")
        else:
            cmd.append("--strict-config")
        cmd.append(prompt)
        started = time.time()
        try:
            proc = subprocess.run(cmd, text=True, capture_output=True,
                                  env=self._env(), timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise BackendError(f"codex timed out after {timeout}s") from exc
        transcript = (proc.stdout or "") + (proc.stderr or "")
        content = last.read_text(encoding="utf-8", errors="replace") if last.exists() else ""
        tokens = re.findall(r"tokens used[:\s]*\n?\s*([\d,]+)", transcript, re.I)
        if proc.returncode != 0:
            raise BackendError(f"codex exited {proc.returncode}: {transcript[-500:]}")
        if not content.strip():
            raise BackendError("codex completed without a final text response")
        return {
            "content": content,
            "wall": round(time.time() - started, 3),
            "prompt_tokens": None,
            "completion_tokens": int(tokens[-1].replace(",", "")) if tokens else None,
            "finish_reason": "stop" if proc.returncode == 0 else f"exit-{proc.returncode}",
            "transcript": transcript,
        }

    def _agent_env(self) -> dict:
        env = self._env()
        env["RUST_LOG"] = env.get("RUST_LOG", "error")
        return env

    def _session_id(self, transcript: str, env: dict, workdir: Path,
                    started: float) -> str | None:
        for pattern in (
                r"session id:\s*([0-9a-fA-F-]{32,40})",
                r'"session_id"\s*:\s*"([0-9a-fA-F-]{32,40})"',
                r'"thread[_.]id"\s*:\s*"([0-9a-fA-F-]{32,40})"'):
            match = re.search(pattern, transcript or "", re.I)
            if match:
                return match.group(1)
        home = Path(env["CODEX_HOME"]) if env.get("CODEX_HOME") else Path.home() / ".codex"
        session_root = home / "sessions"
        if not session_root.is_dir():
            return None
        candidates = []
        for path in session_root.rglob("*"):
            if not path.is_file():
                continue
            match = re.search(
                r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                r"[0-9a-f]{4}-[0-9a-f]{12})", path.name)
            if not match or path.stat().st_mtime < started - 2:
                continue
            try:
                header = path.read_text(encoding="utf-8", errors="replace")[:200_000]
            except OSError:
                continue
            if str(workdir) in header:
                candidates.append((path.stat().st_mtime, match.group(1)))
        return max(candidates)[1] if candidates else None

    def agent_turn(self, prompt: str, workdir: Path, evidence_dir: Path,
                   turn: int, timeout: int, sandbox: str,
                   session_id: str | None = None) -> dict:
        """Run or resume one persistent Codex agent turn with explicit invariants."""
        if sandbox not in {"read-only", "workspace-write"}:
            raise ValueError("agent sandbox must be read-only or workspace-write")
        evidence_dir.mkdir(parents=True, exist_ok=True)
        transcript_path = evidence_dir / f"transcript_turn{turn}.txt"
        last_path = evidence_dir / f"last_message_turn{turn}.txt"
        if transcript_path.exists() or last_path.exists():
            raise ValueError(f"refusing to overwrite agent evidence for turn {turn}")
        if session_id is None:
            command = [
                "codex", "exec", "-m", self.model["model"], "-C", str(workdir),
                "-s", sandbox, "--skip-git-repo-check",
                "-c", 'approval_policy="never"', "--disable", "multi_agent",
                "-o", str(last_path),
            ]
        else:
            command = [
                "codex", "exec", "resume", session_id, "-m", self.model["model"],
                "--skip-git-repo-check", "-c", 'approval_policy="never"',
                "-c", f'sandbox_mode="{sandbox}"', "--disable", "multi_agent",
                "-o", str(last_path),
            ]
        effort = self.model.get("reasoning_effort")
        if effort:
            command += ["-c", f'model_reasoning_effort="{effort}"']
        if self.model.get("codex_provider", "custom") == "openai":
            command.append("--ignore-user-config")
        else:
            command.append("--strict-config")
        command.append(prompt)
        env = self._agent_env()
        started = time.time()
        with transcript_path.open("w", encoding="utf-8", errors="replace") as stream:
            proc = subprocess.Popen(
                command, cwd=workdir, env=env, stdout=stream,
                stderr=subprocess.STDOUT, text=True, start_new_session=(os.name == "posix"))
            timed_out = False
            try:
                returncode = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                if os.name == "posix":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:  # pragma: no cover - Windows runner behavior
                    proc.kill()
                returncode = proc.wait(timeout=30)
                stream.write(f"\n[harness] TIMEOUT: killed after {timeout}s\n")
        transcript = transcript_path.read_text(encoding="utf-8", errors="replace")
        content = (last_path.read_text(encoding="utf-8", errors="replace")
                   if last_path.exists() else "")
        tokens = re.findall(r"tokens used[:\s]*\n?\s*([\d,]+)", transcript, re.I)
        actual_session = session_id or self._session_id(
            transcript, env, workdir, started)
        return {
            "content": content,
            "transcript": transcript,
            "session_id": actual_session,
            "wall": round(time.time() - started, 3),
            "tokens": int(tokens[-1].replace(",", "")) if tokens else None,
            "timed_out": timed_out,
            "returncode": returncode,
            "sandbox": sandbox,
        }


def make_backend(model: dict, state_dir: Path) -> Backend:
    transport = model.get("transport", "openai_compat")
    if transport == "openai_compat":
        return OpenAICompatBackend(model, state_dir)
    if transport == "codex_cli":
        return CodexBackend(model, state_dir)
    raise BackendError(f"unknown transport {transport!r}")
