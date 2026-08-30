from __future__ import annotations

import json
import os
import re
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
        self.state_dir = state_dir

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
        return {
            "content": content,
            "wall": round(time.time() - started, 3),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "finish_reason": choice.get("finish_reason"),
            "raw_usage": usage,
        }


class CodexBackend(Backend):
    """Run Codex CLI with isolated state for text and repository-agent tasks."""

    def _env(self) -> dict:
        env = dict(os.environ)
        if self.model.get("codex_provider", "custom") == "openai":
            return env
        home = self.state_dir / "codex-homes" / self.model["key"]
        home.mkdir(parents=True, exist_ok=True)
        provider = "pattern0_compat"
        base = self.model.get("base_url", "http://127.0.0.1:8000/v1")
        key_env = self.model.get("api_key_env", "PATTERN0_API_KEY")
        config = (
            f'model_provider = "{provider}"\n'
            f'model = {json.dumps(self.model["model"])}\n'
            f'model_context_window = {int(self.model.get("context_window", 131072))}\n'
            'approval_policy = "never"\n\n'
            f'[model_providers.{provider}]\n'
            'name = "Pattern0 OpenAI-compatible"\n'
            f'base_url = {json.dumps(base)}\n'
            f'env_key = {json.dumps(key_env)}\n'
            'wire_api = "responses"\n')
        (home / "config.toml").write_text(config, encoding="utf-8")
        save_json(home / "auth.json", {"OPENAI_API_KEY": os.environ.get(key_env, "local-dummy")})
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
        if proc.returncode != 0 and not content:
            raise BackendError(f"codex exited {proc.returncode}: {transcript[-500:]}")
        return {
            "content": content,
            "wall": round(time.time() - started, 3),
            "prompt_tokens": None,
            "completion_tokens": int(tokens[-1].replace(",", "")) if tokens else None,
            "finish_reason": "stop" if proc.returncode == 0 else f"exit-{proc.returncode}",
            "transcript": transcript,
        }


def make_backend(model: dict, state_dir: Path) -> Backend:
    transport = model.get("transport", "openai_compat")
    if transport == "openai_compat":
        return OpenAICompatBackend(model, state_dir)
    if transport == "codex_cli":
        return CodexBackend(model, state_dir)
    raise BackendError(f"unknown transport {transport!r}")
