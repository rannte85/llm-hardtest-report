from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .common import load_json, repo_root, save_json, slug
from .orchestrator import run, validate_config
from .report import generate


def _ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(prompt + suffix + ": ").strip()
    return value or (default or "")


def init_config(path: Path) -> None:
    count = int(_ask("How many model configurations", "2"))
    repetitions = int(_ask("Independent repetitions per task", "5"))
    rounds = [int(x) for x in _ask("Rounds to run (comma-separated)", "1,2,3,4").split(",")]
    models = []
    for index in range(1, count + 1):
        print(f"\nModel {index}/{count}")
        model_id = _ask("Model ID")
        key = slug(_ask("Short key", model_id))
        transport = _ask("Transport: openai_compat or codex_cli", "openai_compat")
        model = {"key": key, "label": _ask("Display label", model_id),
                 "model": model_id, "transport": transport,
                 "reasoning_effort": _ask("Reasoning effort (blank if unsupported)", "") or None,
                 "context_window": int(_ask("Context window", "131072")),
                 "max_tokens": int(_ask("Maximum output tokens", "16000"))}
        if transport == "openai_compat" or _ask("Codex provider: custom or openai", "custom") == "custom":
            model["base_url"] = _ask("OpenAI-compatible /v1 base URL", "http://127.0.0.1:8000/v1")
            model["api_key_env"] = _ask("API-key environment variable", "PATTERN0_API_KEY")
            if transport == "codex_cli":
                model["codex_provider"] = "custom"
        else:
            model["codex_provider"] = "openai"
        models.append(model)
    config = {"name": _ask("Campaign name", "pattern0"), "repetitions": repetitions,
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
        description="Run LLM Hardtest Report (Pattern0 rounds 1–4) and generate a report",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_init = sub.add_parser("init", help="interactively create a campaign config")
    p_init.add_argument("--output", default="benchmark.json")
    p_run = sub.add_parser("run", help="run or resume a campaign")
    p_run.add_argument("--config", required=True)
    p_run.add_argument("--runs-dir", default="runs")
    p_run.add_argument("--resume")
    p_run.add_argument("--dry-run", action="store_true")
    p_report = sub.add_parser("report", help="regenerate a completed campaign report")
    p_report.add_argument("run_dir")
    p_validate = sub.add_parser("validate", help="validate a config and local runtime")
    p_validate.add_argument("--config", required=True)
    sub.add_parser("selftest", help="validate datasets and graders without calling a model")
    args = parser.parse_args(argv)
    if args.command == "init":
        init_config(Path(args.output)); return 0
    if args.command == "run":
        config = load_json(Path(args.config))
        run_dir = run(config, Path(args.runs_dir), Path(args.resume) if args.resume else None,
                      args.dry_run)
        print(f"Campaign directory: {run_dir}")
        if not args.dry_run:
            print(f"Report: {run_dir / 'REPORT.md'}")
        return 0
    if args.command == "report":
        md, js = generate(Path(args.run_dir)); print(md); print(js); return 0
    if args.command == "validate":
        validate_config(load_json(Path(args.config)))
        print(f"VALID: {args.config}")
        return 0
    return selftest()
