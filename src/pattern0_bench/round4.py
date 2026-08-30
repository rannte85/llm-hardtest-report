from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

from .common import repo_root, save_json


CANONICAL_TASKS = [
    "q26_hidden_tests", "q27_race", "q28_false_hypothesis",
    "q29_multiturn", "q30v2_policy_conflict", "q31_approval_followup",
]


def run(model: dict, attempts: int, out_dir: Path, timeout: int,
        tasks: list[str] | None = None, dry_run: bool = False) -> int:
    base = repo_root() / "rounds" / "round4"
    sys.path.insert(0, str(base))
    previous_omlx_key = os.environ.get("OMLX_API_KEY")
    try:
        runner = importlib.import_module("v4_runner")
        grader = importlib.import_module("v4_grade")
        provider = "openai" if model.get("codex_provider") == "openai" else "omlx"
        runner.MODELS.clear()
        runner.MODELS[model["key"]] = {
            "model": model["model"], "provider": provider,
            "reasoning": model.get("reasoning_effort"),
            "context_window": model.get("context_window", 131072),
            "label": model.get("label", model["model"]),
        }
        runner.OMLX_BASE_URL = model.get("base_url", "http://127.0.0.1:8000/v1")
        source_key = model.get("api_key_env", "OMLX_API_KEY")
        os.environ["OMLX_API_KEY"] = os.environ.get(source_key, "local-dummy")
        runner.CODEX_HOME_LOCAL = str(out_dir.parent.parent / "_codex")
        runner.DEFAULT_SCRATCH = str(out_dir.parent.parent / "_work")
        home = Path(runner.CODEX_HOME_LOCAL) / model["key"]
        home.mkdir(parents=True, exist_ok=True)
        auth_path = home / "auth.json"
        save_json(auth_path, {"OPENAI_API_KEY": "local-dummy"})
        auth_path.chmod(0o600)
        selected = tasks or CANONICAL_TASKS
        unknown = [task for task in selected if task not in grader.available_tasks()]
        if unknown:
            raise ValueError(f"unknown round-4 tasks: {unknown}")
        args = ["--model", model["key"], "--tasks", ",".join(selected),
                "--attempts", str(attempts), "--timeout", str(timeout),
                "--out", str(out_dir)]
        if dry_run:
            args.append("--dry-run")
        return int(runner.main(args) or 0)
    finally:
        if previous_omlx_key is None:
            os.environ.pop("OMLX_API_KEY", None)
        else:
            os.environ["OMLX_API_KEY"] = previous_omlx_key
        if str(base) in sys.path:
            sys.path.remove(str(base))
