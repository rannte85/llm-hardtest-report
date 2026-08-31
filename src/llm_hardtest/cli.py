from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from .backends import BackendError, CodexBackend, OpenAICompatBackend
from .common import load_json, repo_root, save_json, slug
from .orchestrator import _model_rounds, run, validate_config
from .report import generate
from .results import output_limited
from .inspection import inspect_run, render_inspection


def _ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(prompt + suffix + ": ").strip()
    return value or (default or "")


SERVER_PRESETS = {
    "custom": "http://127.0.0.1:8000/v1",
    "ollama": "http://127.0.0.1:11434/v1",
    "lmstudio": "http://127.0.0.1:1234/v1",
    "llamacpp": "http://127.0.0.1:8080/v1",
    "vllm": "http://127.0.0.1:8000/v1",
    "mlxlm": "http://127.0.0.1:8080/v1",
}


def _api_headers(api_key_env: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key_env and os.environ.get(api_key_env):
        headers["Authorization"] = "Bearer " + os.environ[api_key_env]
    return headers


def discover_models(base_url: str, api_key_env: str | None = None,
                    timeout: int = 10) -> list[str]:
    request = urllib.request.Request(
        base_url.rstrip("/") + "/models", headers=_api_headers(api_key_env)
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        raise ValueError("/models response does not contain a data list")
    return [str(item["id"]) for item in models
            if isinstance(item, dict) and item.get("id")]


def _probe_codex(model: dict, timeout: int) -> None:
    probe = dict(model)
    probe["transport"] = "codex_cli"
    probe.setdefault("codex_provider", "custom")
    with tempfile.TemporaryDirectory(prefix="llm-hardtest-doctor-") as tmp:
        result = CodexBackend(probe, Path(tmp)).complete(
            [{"role": "user", "content": "Reply with OK."}], timeout)
        if not result["content"].strip():
            raise BackendError("Codex returned no text")


def doctor_config(config: dict, timeout: int = 30) -> int:
    """Probe model discovery and the APIs needed by each selected model."""
    validate_config(config)
    campaign_rounds = [int(value) for value in config["rounds"]]
    failures = []
    for model in config["models"]:
        key = model["key"]
        selected = _model_rounds(model, campaign_rounds)
        if model.get("codex_provider") == "openai":
            proc = subprocess.run(["codex", "login", "status"], text=True,
                                  capture_output=True, timeout=timeout)
            if proc.returncode:
                failures.append(f"{key}: Codex is not signed in")
            else:
                try:
                    _probe_codex(model, timeout)
                    print(f"PASS {key}: signed-in Codex returned text from {model['model']}")
                except Exception as exc:
                    failures.append(f"{key}: {exc}")
            continue
        try:
            served = discover_models(model.get("base_url", "http://127.0.0.1:8000/v1"),
                                     model.get("api_key_env"), timeout)
            if model["model"] not in served:
                raise ValueError(f'model {model["model"]!r} not found; served: {served}')
            print(f"PASS {key}: /models lists {model['model']}")
            if any(number in (1, 2, 3) for number in selected):
                if model.get("transport") == "openai_compat":
                    result = OpenAICompatBackend(model, Path(".")).complete(
                        [{"role": "user", "content": "Reply with OK."}], timeout)
                    if output_limited(result.get("finish_reason")):
                        raise BackendError(
                            "Chat Completions reached its output limit during a short probe"
                            + (" and returned no final text"
                               if not result["content"].strip() else ""))
                    if not result["content"].strip():
                        raise BackendError("Chat Completions returned no text")
                    print(f"PASS {key}: /chat/completions returned text")
                else:
                    _probe_codex(model, timeout)
                    print(f"PASS {key}: Codex completed through /responses")
            if 4 in selected and model.get("transport") != "codex_cli":
                _probe_codex(model, timeout)
                print(f"PASS {key}: Codex and /responses are available for Round 4")
        except Exception as exc:
            failures.append(f"{key}: {exc}")
    if failures:
        print("DOCTOR FAILED", file=sys.stderr)
        for failure in failures:
            print("- " + failure, file=sys.stderr)
        return 1
    print("DOCTOR PASSED")
    return 0


def init_config(path: Path) -> None:
    count = int(_ask("How many model configurations", "2"))
    repetitions = int(_ask("Independent repetitions per task", "5"))
    rounds = [int(x) for x in _ask("Campaign rounds (comma-separated)", "1,2,3").split(",")]
    models = []
    for index in range(1, count + 1):
        print(f"\nModel {index}/{count}")
        preset = _ask(
            "Server preset: custom, ollama, lmstudio, llamacpp, vllm, mlxlm, openai",
            "custom").lower()
        if preset not in {*SERVER_PRESETS, "openai"}:
            raise ValueError(f"unknown server preset {preset!r}")
        if preset == "openai":
            model_id = _ask("Codex model ID")
            transport, base_url, api_key_env = "codex_cli", None, None
        else:
            base_url = _ask("OpenAI-compatible /v1 base URL", SERVER_PRESETS[preset])
            api_key_env = _ask("API-key environment variable", "LLM_HARDTEST_API_KEY")
            try:
                available = discover_models(base_url, api_key_env)
                print("Available models: " + (", ".join(available) or "(none)"))
            except Exception as exc:
                available = []
                print(f"Could not discover models yet: {exc}")
            model_id = _ask("Model ID", available[0] if available else None)
            transport = _ask("Transport: openai_compat or codex_cli", "openai_compat")
        key = slug(_ask("Short key", model_id))
        model_rounds = [int(x) for x in _ask(
            "Rounds for this model (comma-separated)",
            ",".join(map(str, rounds))).split(",")]
        model = {"key": key, "label": _ask("Display label", model_id),
                 "model": model_id, "transport": transport,
                 "rounds": model_rounds,
                 "reasoning_effort": _ask("Reasoning effort (blank if unsupported)", "") or None,
                 "context_window": int(_ask("Context window", "131072")),
                 "max_tokens": int(_ask("Maximum output tokens", "16000"))}
        if preset != "openai":
            model["base_url"] = base_url
            model["api_key_env"] = api_key_env
            if transport == "codex_cli":
                model["codex_provider"] = "custom"
        else:
            model["codex_provider"] = "openai"
        models.append(model)
    config = {"name": _ask("Campaign name", "llm-hardtest"), "repetitions": repetitions,
              "rounds": rounds, "timeout_seconds": int(_ask("Timeout per model call", "3600")),
              "round4_tasks": ["q26_hidden_tests", "q27_race", "q28_false_hypothesis",
                               "q29_multiturn", "q30v2_policy_conflict", "q31_approval_followup"],
              "models": models}
    validate_config(config, check_runtime=False)
    save_json(path, config)
    print(f"Saved {path}")


def selftest() -> int:
    root = repo_root()
    failures = []
    for rel in ("rounds/round1/questions.json", "rounds/round2/questions.json",
                "rounds/round3/problems_v3.json"):
        try:
            load_json(root / rel)
        except Exception as exc:
            failures.append(f"{rel}: {exc}")
    cmd = [sys.executable, str(root / "rounds/round4/_harness_selftest/selftest.py")]
    proc = subprocess.run(cmd, cwd=root / "rounds/round4", text=True,
                          capture_output=True, timeout=300)
    if proc.returncode:
        failures.append("round-4 selftest failed:\n" + proc.stdout[-1000:] + proc.stderr[-1000:])
    korean_hits = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix == ".zip" or ".git" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if any("\uac00" <= char <= "\ud7a3" for char in text):
            korean_hits.append(str(path.relative_to(root)))
    if korean_hits:
        failures.append("Korean text remains in: " + ", ".join(korean_hits[:50]))
    if failures:
        print("SELFTEST FAILED")
        print("\n\n".join(failures))
        return 1
    print("SELFTEST PASSED: datasets parse, English-only check passed, round-4 harness is healthy")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog=Path(sys.argv[0]).name,
        description="Run LLM Hardtest rounds 1–4 and generate a report",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_init = sub.add_parser("init", help="interactively create a campaign config")
    p_init.add_argument("--output", default="benchmark.json")
    p_run = sub.add_parser("run", help="run or resume a campaign")
    p_run.add_argument("--config", required=True)
    p_run.add_argument("--runs-dir", default="runs")
    p_run.add_argument("--resume")
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument(
        "--progress", choices=("auto", "dashboard", "plain"), default="auto",
        help="progress display: live dashboard on a TTY, force dashboard, or plain logs",
    )
    p_report = sub.add_parser("report", help="regenerate a completed campaign report")
    p_report.add_argument("run_dir")
    p_inspect = sub.add_parser("inspect", help="show unresolved campaign items")
    p_inspect.add_argument("run_dir")
    p_inspect.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    p_validate = sub.add_parser("validate", help="validate config syntax and local executables")
    p_validate.add_argument("--config", required=True)
    p_doctor = sub.add_parser("doctor", help="probe configured servers, models, and APIs")
    p_doctor.add_argument("--config", required=True)
    p_doctor.add_argument("--timeout", type=int, default=30)
    p_discover = sub.add_parser("discover", help="list model IDs exposed by a server")
    p_discover.add_argument("--base-url", required=True)
    p_discover.add_argument("--api-key-env")
    sub.add_parser("selftest", help="validate datasets and graders without calling a model")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            init_config(Path(args.output)); return 0
        if args.command == "run":
            config = load_json(Path(args.config))
            run_dir = run(config, Path(args.runs_dir), Path(args.resume) if args.resume else None,
                          args.dry_run, args.progress)
            print(f"Campaign directory: {run_dir}")
            if not args.dry_run:
                print(f"Report: {run_dir / 'REPORT.md'}")
            return 0
        if args.command == "report":
            md, js = generate(Path(args.run_dir)); print(md); print(js); return 0
        if args.command == "inspect":
            summary = inspect_run(Path(args.run_dir))
            print(json.dumps(summary, indent=2) if args.json else render_inspection(summary))
            return 0
        if args.command == "validate":
            validate_config(load_json(Path(args.config)))
            print(f"VALID: {args.config} (run doctor for live API checks)")
            return 0
        if args.command == "doctor":
            return doctor_config(load_json(Path(args.config)), args.timeout)
        if args.command == "discover":
            for model_id in discover_models(args.base_url, args.api_key_env):
                print(model_id)
            return 0
        return selftest()
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError,
            subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
