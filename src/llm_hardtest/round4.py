from __future__ import annotations

import contextlib
import importlib
import os
import sys
from pathlib import Path
from typing import Callable

from .common import repo_root, save_json
from .round4_agents import make_round4_agent


CANONICAL_TASKS = [
    "q26_hidden_tests", "q27_race", "q28_false_hypothesis",
    "q29_multiturn", "q30v2_policy_conflict", "q31_approval_followup",
]


def run(model: dict, attempts: int, out_dir: Path, timeout: int,
        tasks: list[str] | None = None, dry_run: bool = False,
        progress: Callable[[dict], None] | None = None) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
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
            "agent_backend": model.get("agent_backend", "codex_cli"),
        }
        runner.OMLX_BASE_URL = model.get("base_url", "http://127.0.0.1:8000/v1")
        source_key = model.get("api_key_env", "OMLX_API_KEY")
        os.environ["OMLX_API_KEY"] = os.environ.get(source_key, "local-dummy")
        runner.CODEX_HOME_LOCAL = str(out_dir.parent.parent / "_codex")
        runner.AGENT_STATE_ROOT = str(out_dir.parent.parent / "_agent_state")
        runner.DEFAULT_SCRATCH = str(out_dir.parent.parent / "_work")
        if model.get("agent_backend", "codex_cli") == "codex_cli":
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
        def agent_factory(_model_key, _task_key, _attempt, _workdir,
                          state_dir, metadata_path):
            current_attempt = Path(metadata_path).parent.resolve()
            run_root = out_dir.parent.parent.resolve()
            benchmark_assets = [repo_root() / "rounds"]
            global_state = [path for path in (
                Path.home() / ".codex",
                Path.home() / ".config" / "opencode",
                Path.home() / ".local" / "share" / "opencode",
                Path.home() / "Library" / "Application Support" / "opencode",
                Path.home() / "Library" / "Caches" / "opencode",
            ) if path.exists()]
            prior_attempts = []
            for candidate in run_root.rglob("attempt*"):
                if candidate.is_dir() and candidate.resolve() != current_attempt:
                    prior_attempts.append(candidate)
            completed = [path for path in run_root.rglob("repo_after")
                         if path.is_dir()]
            protected = {
                "held_back_checks": benchmark_assets,
                "reference_solutions": benchmark_assets,
                "canonical_task_repositories": benchmark_assets,
                "prior_attempts": prior_attempts,
                "completed_repositories": completed,
                "agent_global_sessions": global_state,
                "agent_global_configuration_caches": global_state,
            }
            return make_round4_agent(
                model, Path(state_dir), Path(metadata_path), protected)

        if progress and not dry_run:
            log_path = out_dir / "harness.log"
            with log_path.open("a", encoding="utf-8") as log:
                with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                    return int(runner.main(
                        args, progress_callback=progress,
                        agent_factory=agent_factory) or 0)

        return int(runner.main(
            args, progress_callback=progress, agent_factory=agent_factory) or 0)
    finally:
        if previous_omlx_key is None:
            os.environ.pop("OMLX_API_KEY", None)
        else:
            os.environ["OMLX_API_KEY"] = previous_omlx_key
        if str(base) in sys.path:
            sys.path.remove(str(base))
