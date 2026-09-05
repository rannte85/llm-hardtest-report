from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from .backends import CodexBackend, _stop_process
from .common import save_json
from .isolation import make_isolation


class Round4AgentError(RuntimeError):
    """A repository-agent attempt is infrastructure-invalid."""


class Round4Agent:
    """Provider-neutral interface used by the canonical Round 4 runner."""

    name = "unknown"

    def __init__(self, model: dict, state_dir: Path, metadata_path: Path):
        self.model = model
        self.state_dir = state_dir.resolve()
        self.metadata_path = metadata_path.resolve()
        self.state_dir.mkdir(parents=True, exist_ok=False)
        self._metadata = {
            "schema_version": 1,
            "agent_backend": self.name,
            "requested_model": model["model"],
            "state_scope": "attempt",
            "turns": [],
        }
        self.isolation = None
        self._save_metadata()

    def configure_isolation(self, isolation) -> None:
        self.isolation = isolation
        self._metadata["round4_isolation"] = isolation.provenance
        self._save_metadata()

    def _preflight_isolation(self, workdir: Path) -> None:
        if self.isolation is None:
            raise Round4AgentError("agent isolation was not configured")
        result = self.isolation.preflight(workdir)
        self._metadata["round4_isolation"] = self.isolation.provenance
        self._metadata["isolation_preflight"] = result
        self._save_metadata()

    def _save_metadata(self) -> None:
        save_json(self.metadata_path, self._metadata)

    def preflight(self, workdir: Path) -> dict:
        raise NotImplementedError

    def turn(self, prompt: str, workdir: Path, evidence_dir: Path, turn: int,
             timeout: int, session_id: str | None = None) -> dict:
        raise NotImplementedError

    def audit(self, transcript: str) -> dict:
        result = self.isolation.audit(transcript) if self.isolation else {
            "status": "pass", "boundary_violation": False}
        self._metadata["audit"] = result
        self._save_metadata()
        return result

    def _record_turn(self, result: dict) -> None:
        self._metadata["turns"].append({
            key: result.get(key) for key in (
                "turn", "returncode", "timed_out", "session_id", "wall",
                "tokens", "termination_reason", "observed_model",
                "model_identity_verified")
        })
        self._save_metadata()

    @property
    def provenance(self) -> dict:
        return {
            "agent_backend": self.name,
            "requested_model": self.model["model"],
            "state_scope": "attempt",
            "round4_isolation": (
                self.isolation.provenance if self.isolation else None),
        }


class CodexRound4Agent(Round4Agent):
    name = "codex_cli"

    def __init__(self, model: dict, state_dir: Path, metadata_path: Path):
        super().__init__(model, state_dir, metadata_path)
        self.backend = CodexBackend(model, self.state_dir)

    def preflight(self, workdir: Path) -> dict:
        self._preflight_isolation(workdir)
        self.backend.agent_command_prefix = self.isolation.command_prefix
        self.backend.agent_env_overrides = self.isolation.env
        executable = shutil.which("codex")
        if not executable:
            raise Round4AgentError("codex_cli selected but codex is not on PATH")
        result = {"status": "pass", "executable": Path(executable).name}
        self._metadata["preflight"] = result
        self._save_metadata()
        return result

    def turn(self, prompt: str, workdir: Path, evidence_dir: Path, turn: int,
             timeout: int, session_id: str | None = None) -> dict:
        private_evidence = self.state_dir / "evidence"
        result = self.backend.agent_turn(
            prompt, workdir, private_evidence, turn, timeout,
            "workspace-write", session_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        for name in (f"transcript_turn{turn}.txt", f"last_message_turn{turn}.txt"):
            source = private_evidence / name
            target = evidence_dir / name
            if target.exists():
                raise Round4AgentError(
                    f"refusing to overwrite agent evidence for turn {turn}")
            if source.exists():
                shutil.copyfile(source, target)
        result["turn"] = turn
        result["rc"] = result["returncode"]
        result["last_message"] = result["content"]
        observed_models = sorted(set(re.findall(
            r"(?mi)^\s*model:\s*([^\s]+)\s*$",
            result.get("transcript", ""))))
        mismatches = [value for value in observed_models
                      if value != self.model["model"]]
        result["observed_model"] = (
            observed_models[0] if len(observed_models) == 1 else None)
        result["model_identity_verified"] = (
            False if mismatches else True if observed_models else None)
        self._record_turn(result)
        failure = None
        if result.get("timed_out"):
            failure = f"codex timed out after {timeout}s"
        elif result.get("protocol_aborted"):
            failure = "codex aborted an unsupported-tool loop"
        elif result.get("returncode"):
            failure = f"codex exited {result['returncode']}"
        elif not str(result.get("content", "")).strip():
            failure = "codex completed without a final text response"
        elif mismatches:
            failure = "codex observed model mismatch: " + ", ".join(mismatches)
        audit = self.audit(result.get("transcript", ""))
        if audit.get("boundary_violation"):
            failure = "codex boundary audit failed"
        if failure:
            raise Round4AgentError(failure)
        return result


def _jsonl_events(transcript: str) -> list[dict]:
    events = []
    for line in (transcript or "").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _nested_values(value, names: set[str]):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in names and isinstance(child, str):
                yield child
            yield from _nested_values(child, names)
    elif isinstance(value, list):
        for child in value:
            yield from _nested_values(child, names)


def _opencode_usage(events: list[dict]) -> tuple[int | None, dict]:
    usage = {}
    for event in events:
        if event.get("type") != "step_finish" or not isinstance(event.get("part"), dict):
            continue
        part = event["part"]
        candidate = part.get("tokens")
        if isinstance(candidate, dict):
            usage = candidate
    if not usage:
        return None, {}
    total = usage.get("total")
    if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
        return total, usage
    values = [usage.get(key) for key in ("input", "output", "reasoning")]
    if all(isinstance(value, int) and not isinstance(value, bool) and value >= 0
           for value in values if value is not None):
        measured = [value for value in values if value is not None]
        return sum(measured) if measured else None, usage
    return None, usage


class OpenCodeRound4Agent(Round4Agent):
    """OpenCode CLI adapter for Chat-Completions-compatible local servers."""

    name = "opencode_cli"
    provider_id = "llm-hardtest"

    def _env(self) -> dict:
        env = dict(os.environ)
        home = self.state_dir / "home"
        config = self.state_dir / "xdg-config"
        data = self.state_dir / "xdg-data"
        cache = self.state_dir / "xdg-cache"
        for path in (home, config, data, cache):
            path.mkdir(parents=True, exist_ok=True)
        key_env = self.model.get("api_key_env", "LLM_HARDTEST_API_KEY")
        env.setdefault(key_env, "local-dummy")
        env.update({
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(config),
            "XDG_DATA_HOME": str(data),
            "XDG_CACHE_HOME": str(cache),
        })
        provider = {
            "npm": "@ai-sdk/openai-compatible",
            "name": "LLM Hardtest OpenAI-compatible",
            "options": {
                "baseURL": self.model.get("base_url", "http://127.0.0.1:8000/v1"),
                "apiKey": "{env:%s}" % key_env,
            },
            "models": {
                self.model["model"]: {
                    "name": self.model.get("label", self.model["model"]),
                    "limit": {
                        "context": int(self.model.get("context_window", 131072)),
                        "output": int(self.model.get("max_tokens", 16000)),
                    },
                }
            },
        }
        env["OPENCODE_CONFIG_CONTENT"] = json.dumps(
            {"provider": {self.provider_id: provider}}, separators=(",", ":"))
        if self.isolation is not None:
            env.update(self.isolation.env)
        return env

    def preflight(self, workdir: Path) -> dict:
        self._preflight_isolation(workdir)
        executable = shutil.which("opencode")
        if not executable:
            raise Round4AgentError(
                "opencode_cli selected but opencode is not on PATH")
        try:
            probe = subprocess.run(
                list(self.isolation.command_prefix)
                + [executable, "run", "--help"], text=True, capture_output=True,
                env=self._env(), timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Round4AgentError(f"opencode capability probe failed: {exc}") from exc
        help_text = (probe.stdout or "") + (probe.stderr or "")
        required = ("--model", "--format", "--session", "--dir")
        missing = [flag for flag in required if flag not in help_text]
        if probe.returncode or missing:
            detail = "missing " + ", ".join(missing) if missing else f"exit {probe.returncode}"
            raise Round4AgentError(f"incompatible opencode CLI: {detail}")
        auto_flag = ("--dangerously-skip-permissions"
                     if "--dangerously-skip-permissions" in help_text else
                     "--auto" if "--auto" in help_text else None)
        if not auto_flag:
            raise Round4AgentError(
                "incompatible opencode CLI: no non-interactive permission flag")
        self.auto_flag = auto_flag
        result = {
            "status": "pass", "executable": Path(executable).name,
            "permission_flag": auto_flag,
        }
        self._metadata["preflight"] = result
        self._save_metadata()
        return result

    def turn(self, prompt: str, workdir: Path, evidence_dir: Path, turn: int,
             timeout: int, session_id: str | None = None) -> dict:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        transcript_path = evidence_dir / f"transcript_turn{turn}.txt"
        last_path = evidence_dir / f"last_message_turn{turn}.txt"
        if transcript_path.exists() or last_path.exists():
            raise Round4AgentError(f"refusing to overwrite agent evidence for turn {turn}")
        executable = shutil.which("opencode")
        if not executable or not hasattr(self, "auto_flag"):
            raise Round4AgentError("opencode preflight was not completed")
        model_name = f"{self.provider_id}/{self.model['model']}"
        command = list(self.isolation.command_prefix) + [
            executable, "run", "--format", "json", "--model", model_name,
            "--dir", str(workdir), self.auto_flag,
        ]
        if session_id:
            command += ["--session", session_id]
        command.append(prompt)
        started = time.time()
        timed_out = False
        with transcript_path.open("w", encoding="utf-8", errors="replace") as stream:
            proc = subprocess.Popen(
                command, cwd=workdir, env=self._env(), stdout=stream,
                stderr=subprocess.STDOUT, text=True,
                start_new_session=(os.name == "posix"))
            try:
                returncode = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                returncode = _stop_process(proc, hard=True)
                stream.write(f"\n[harness] TIMEOUT: killed after {timeout}s\n")
        transcript = transcript_path.read_text(encoding="utf-8", errors="replace")
        events = _jsonl_events(transcript)
        sessions = {event.get("sessionID") for event in events
                    if isinstance(event.get("sessionID"), str)}
        actual_session = next(iter(sessions), session_id)
        texts = [event.get("part", {}).get("text") for event in events
                 if event.get("type") == "text"
                 and isinstance(event.get("part"), dict)
                 and isinstance(event["part"].get("text"), str)]
        content = texts[-1] if texts else ""
        if content:
            last_path.write_text(content, encoding="utf-8")
        identity_events = [event for event in events
                           if event.get("type") in {"step_start", "step_finish", "text"}]
        observed = sorted(set(_nested_values(
            identity_events, {"modelID", "model_id"})))
        tokens, raw_usage = _opencode_usage(events)
        accepted = {self.model["model"], model_name}
        mismatches = [value for value in observed if value not in accepted]
        identity_verified = False if mismatches else True if observed else None
        failure = None
        if len(sessions) > 1 or (session_id and sessions and sessions != {session_id}):
            failure = "opencode continuation returned the wrong session"
        elif mismatches:
            failure = "opencode observed model mismatch: " + ", ".join(mismatches)
        elif timed_out:
            failure = f"opencode timed out after {timeout}s"
        elif returncode:
            failure = f"opencode exited {returncode}"
        elif any(event.get("type") == "error" for event in events):
            failure = "opencode emitted an error event"
        elif not actual_session:
            failure = "opencode output did not identify a session"
        elif not content.strip():
            failure = "opencode completed without a final text response"
        result = {
            "turn": turn,
            "content": content,
            "last_message": content,
            "transcript": transcript,
            "session_id": actual_session,
            "wall": round(time.time() - started, 3),
            "tokens": tokens,
            "raw_usage": raw_usage,
            "timed_out": timed_out,
            "protocol_aborted": False,
            "termination_reason": (
                "timeout" if timed_out else "agent_error" if failure else None),
            "returncode": returncode,
            "rc": returncode,
            "sandbox": "workspace-write",
            "observed_model": observed[0] if len(observed) == 1 else None,
            "model_identity_verified": identity_verified,
        }
        self._record_turn(result)
        audit = self.audit(transcript)
        if audit.get("boundary_violation"):
            failure = "opencode boundary audit failed"
        if failure:
            raise Round4AgentError(failure)
        return result


_PI_THINKING_LEVELS = {"off", "minimal", "low", "medium", "high", "xhigh", "max"}
_PI_USAGE_FIELDS = ("input", "output", "cacheRead", "cacheWrite", "reasoning",
                    "totalTokens")


def _pi_usage(messages: list[dict]) -> tuple[int | None, dict]:
    totals: dict[str, int] = {}
    for message in messages:
        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue
        for field in _PI_USAGE_FIELDS:
            value = usage.get(field)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                totals[field] = totals.get(field, 0) + value
    return totals.get("totalTokens"), totals


class PiRound4Agent(Round4Agent):
    """pi CLI adapter for Chat-Completions-compatible servers."""

    name = "pi_cli"
    provider_id = "llm-hardtest"

    def _env(self) -> dict:
        env = dict(os.environ)
        home = self.state_dir / "home"
        agent_dir = self.state_dir / "pi-agent"
        sessions = self.state_dir / "pi-sessions"
        for path in (home, agent_dir, sessions):
            path.mkdir(parents=True, exist_ok=True)
        key_env = self.model.get("api_key_env", "LLM_HARDTEST_API_KEY")
        env.setdefault(key_env, "local-dummy")
        env.update({
            "HOME": str(home),
            # Isolate the campaign from the user's global pi providers and packages.
            "PI_CODING_AGENT_DIR": str(agent_dir),
            # Suppress startup catalog refreshes so attempts stay deterministic.
            "PI_OFFLINE": "1",
        })
        save_json(agent_dir / "models.json", {"providers": {self.provider_id: {
            "baseUrl": self.model.get("base_url", "http://127.0.0.1:8000/v1"),
            "api": "openai-completions",
            "apiKey": "${%s}" % key_env,
            "models": [{
                "id": self.model["model"],
                "name": self.model.get("label", self.model["model"]),
                "contextWindow": int(self.model.get("context_window", 131072)),
                "maxTokens": int(self.model.get("max_tokens", 16000)),
            }],
        }}})
        if self.isolation is not None:
            env.update(self.isolation.env)
        return env

    def preflight(self, workdir: Path) -> dict:
        self._preflight_isolation(workdir)
        executable = shutil.which("pi")
        if not executable:
            raise Round4AgentError("pi_cli selected but pi is not on PATH")
        env = self._env()
        prefix = list(self.isolation.command_prefix)
        try:
            probe = subprocess.run(prefix + [executable, "--help"], text=True,
                                   capture_output=True, env=env, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Round4AgentError(f"pi capability probe failed: {exc}") from exc
        help_text = (probe.stdout or "") + (probe.stderr or "")
        required = (
            "--print", "--mode", "--model", "--session-id", "--session-dir",
            "--no-context-files",
        )
        missing = [flag for flag in required if flag not in help_text]
        if probe.returncode or missing:
            detail = ("missing " + ", ".join(missing) if missing
                      else f"exit {probe.returncode}")
            raise Round4AgentError(f"incompatible pi CLI: {detail}")
        try:
            listing = subprocess.run(prefix + [executable, "--list-models"],
                                     text=True, capture_output=True, env=env,
                                     timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Round4AgentError(f"pi model catalog probe failed: {exc}") from exc
        catalog = (listing.stdout or "") + (listing.stderr or "")
        registered = any(
            len(parts) >= 2 and parts[0] == self.provider_id
            and parts[1] == self.model["model"]
            for parts in (line.split() for line in catalog.splitlines()))
        if listing.returncode or not registered:
            raise Round4AgentError(
                "pi did not register "
                f'{self.provider_id}/{self.model["model"]}')
        self._preflighted = True
        result = {"status": "pass", "executable": Path(executable).name,
                  "provider": self.provider_id}
        self._metadata["preflight"] = result
        self._save_metadata()
        return result

    def turn(self, prompt: str, workdir: Path, evidence_dir: Path, turn: int,
             timeout: int, session_id: str | None = None) -> dict:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        transcript_path = evidence_dir / f"transcript_turn{turn}.txt"
        last_path = evidence_dir / f"last_message_turn{turn}.txt"
        if transcript_path.exists() or last_path.exists():
            raise Round4AgentError(f"refusing to overwrite agent evidence for turn {turn}")
        executable = shutil.which("pi")
        if not executable or not getattr(self, "_preflighted", False):
            raise Round4AgentError("pi preflight was not completed")
        # pi creates --session-id when missing, so the harness owns the identifier.
        requested_session = session_id or str(uuid.uuid4())
        model_name = f"{self.provider_id}/{self.model['model']}"
        command = list(self.isolation.command_prefix) + [
            executable, "--print", "--mode", "json", "--model", model_name,
            "--session-id", requested_session,
            "--session-dir", str(self.state_dir / "pi-sessions"),
            # Exclude ambient extensions, skills, and templates from the attempt.
            "--no-extensions", "--no-skills", "--no-prompt-templates", "--no-approve",
            "--no-context-files",
        ]
        thinking = self.model.get("reasoning_effort")
        if thinking in _PI_THINKING_LEVELS:
            command += ["--thinking", thinking]
        command += ["--", prompt]
        started = time.time()
        timed_out = False
        with transcript_path.open("w", encoding="utf-8", errors="replace") as stream:
            proc = subprocess.Popen(
                command, cwd=workdir, env=self._env(), stdout=stream,
                stderr=subprocess.STDOUT, text=True, stdin=subprocess.DEVNULL,
                start_new_session=(os.name == "posix"))
            try:
                returncode = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                returncode = _stop_process(proc, hard=True)
                stream.write(f"\n[harness] TIMEOUT: killed after {timeout}s\n")
        transcript = transcript_path.read_text(encoding="utf-8", errors="replace")
        events = _jsonl_events(transcript)
        sessions = {event.get("id") for event in events
                    if event.get("type") == "session"
                    and isinstance(event.get("id"), str)}
        replies = [event["message"] for event in events
                   if event.get("type") == "turn_end"
                   and isinstance(event.get("message"), dict)]
        final_reply = replies[-1] if replies else {}
        texts = [part["text"] for part in (final_reply.get("content") or [])
                 if isinstance(part, dict) and part.get("type") == "text"
                 and isinstance(part.get("text"), str)]
        content = "\n".join(texts)
        stop_reason = final_reply.get("stopReason")
        if content:
            last_path.write_text(content, encoding="utf-8")
        observed = sorted({message["model"] for message in replies
                           if isinstance(message.get("model"), str)})
        tokens, raw_usage = _pi_usage(replies)
        accepted = {self.model["model"], model_name}
        mismatches = [value for value in observed if value not in accepted]
        identity_verified = False if mismatches else True if observed else None
        failure = None
        if sessions and sessions != {requested_session}:
            failure = "pi continuation returned the wrong session"
        elif mismatches:
            failure = "pi observed model mismatch: " + ", ".join(mismatches)
        elif timed_out:
            failure = f"pi timed out after {timeout}s"
        elif returncode:
            failure = f"pi exited {returncode}"
        elif stop_reason in {"error", "aborted"}:
            failure = f"pi turn ended with stopReason {stop_reason}"
        elif any(event.get("type") == "error" for event in events):
            failure = "pi emitted an error event"
        elif not sessions:
            failure = "pi output did not identify a session"
        elif not content.strip():
            failure = "pi completed without a final text response"
        result = {
            "turn": turn,
            "content": content,
            "last_message": content,
            "transcript": transcript,
            "session_id": requested_session,
            "wall": round(time.time() - started, 3),
            "tokens": tokens,
            "raw_usage": raw_usage,
            "timed_out": timed_out,
            "protocol_aborted": stop_reason == "aborted",
            "termination_reason": (
                "timeout" if timed_out else "agent_error" if failure else None),
            "returncode": returncode,
            "rc": returncode,
            "sandbox": "workspace-write",
            "observed_model": observed[0] if len(observed) == 1 else None,
            "model_identity_verified": identity_verified,
        }
        self._record_turn(result)
        audit = self.audit(transcript)
        if audit.get("boundary_violation"):
            failure = "pi boundary audit failed"
        if failure:
            raise Round4AgentError(failure)
        return result


def make_round4_agent(model: dict, state_dir: Path, metadata_path: Path,
                      protected_paths: list[Path] | None = None) -> Round4Agent:
    name = model.get("agent_backend", "codex_cli")
    if name == "codex_cli":
        agent = CodexRound4Agent(model, state_dir, metadata_path)
    elif name == "opencode_cli":
        agent = OpenCodeRound4Agent(model, state_dir, metadata_path)
    elif name == "pi_cli":
        agent = PiRound4Agent(model, state_dir, metadata_path)
    else:
        raise Round4AgentError(f"unknown Round 4 agent backend {name!r}")
    isolation = make_isolation(
        model.get("round4_isolation"), state_dir,
        protected_paths or [], [],
        model.get("base_url", "http://127.0.0.1:8000/v1"))
    agent.configure_isolation(isolation)
    return agent
