from __future__ import annotations

import shutil
import re
from pathlib import Path
from urllib.parse import urlparse

from .backends import make_backend
from .common import load_json, repo_root, save_json, slug, stamp
from . import round12, round3, round4
from .progress import TerminalDashboard
from .report import generate


def _safe_component(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    text = str(value).strip()
    windows_reserved = {"CON", "PRN", "AUX", "NUL"}
    windows_reserved.update(f"{prefix}{number}" for prefix in ("COM", "LPT")
                            for number in range(1, 10))
    stem = text.split(".", 1)[0].upper()
    if (not text or text in {".", ".."} or text.endswith((".", " "))
            or stem in windows_reserved or slug(text) != text):
        raise ValueError(
            f"{field} must use only letters, numbers, dot, underscore, or hyphen "
            "and cannot be a dot path or reserved filename"
        )
    return text


def _model_rounds(model: dict, campaign_rounds: list[int]) -> list[int]:
    raw = model.get("rounds", campaign_rounds)
    if not isinstance(raw, list):
        raise ValueError(f'{model.get("key", "model")}: rounds must be a JSON list')
    try:
        selected = [int(value) for value in raw]
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{model.get("key", "model")}: rounds must contain integers') from exc
    if not selected or any(value not in campaign_rounds for value in selected):
        raise ValueError(
            f'{model.get("key", "model")}: model rounds must be a non-empty subset '
            "of campaign rounds"
        )
    if len(selected) != len(set(selected)):
        raise ValueError(f'{model.get("key", "model")}: model rounds contain duplicates')
    return selected


def _item_filter(model: dict, round_no: int):
    filters = model.get("item_filters", {})
    return filters.get(str(round_no)) if isinstance(filters, dict) else None


def validate_config(config: dict, check_runtime: bool = True) -> None:
    """Validate a campaign before any run artifacts are created.

    ``check_runtime`` is disabled while generating a configuration so a user can
    prepare it on a machine where Codex will be installed later. Actual runs keep
    the runtime check enabled and fail before partially executing a campaign.
    """
    if not isinstance(config, dict):
        raise ValueError("configuration must be a JSON object")
    if not isinstance(config.get("models"), list) or not config["models"]:
        raise ValueError("config.models must contain at least one model")
    if any(not isinstance(model, dict) for model in config["models"]):
        raise ValueError("every config.models item must be a JSON object")
    keys = [m.get("key") for m in config["models"]]
    if any(not key for key in keys) or len(keys) != len(set(keys)):
        raise ValueError("every model requires a unique non-empty key")
    normalized_keys = [_safe_component(key, "model key") for key in keys]
    if len(normalized_keys) != len(set(normalized_keys)):
        raise ValueError("model keys must remain unique after filesystem normalization")
    if isinstance(config.get("repetitions"), bool):
        raise ValueError("repetitions must be an integer of at least 1")
    try:
        repetitions = int(config.get("repetitions", 0))
        timeout = int(config.get("timeout_seconds", 3600))
    except (TypeError, ValueError) as exc:
        raise ValueError("repetitions and timeout_seconds must be integers") from exc
    if repetitions < 1:
        raise ValueError("repetitions must be at least 1")
    if isinstance(config.get("timeout_seconds", 3600), bool) or timeout < 1:
        raise ValueError("timeout_seconds must be at least 1")
    raw_rounds = config.get("rounds", [])
    if not isinstance(raw_rounds, list):
        raise ValueError("rounds must be a JSON list")
    try:
        rounds = [int(value) for value in raw_rounds]
    except (TypeError, ValueError) as exc:
        raise ValueError("rounds must contain integers from 1 to 4") from exc
    if not rounds or any(value not in (1, 2, 3, 4) for value in rounds):
        raise ValueError("rounds must be a non-empty subset of [1,2,3,4]")
    if len(rounds) != len(set(rounds)):
        raise ValueError("rounds must not contain duplicates")
    _safe_component(config.get("name", "campaign"), "campaign name")
    for model in config["models"]:
        if not isinstance(model.get("model"), str) or not model["model"].strip():
            raise ValueError(f'{model.get("key", "model")}: model is required')
        if model.get("transport") not in ("openai_compat", "codex_cli"):
            raise ValueError(f'{model.get("key")}: unsupported transport')
        if model.get("codex_provider", "custom") not in ("custom", "openai"):
            raise ValueError(f'{model.get("key")}: unsupported codex_provider')
        if (model.get("transport") == "openai_compat"
                or model.get("codex_provider", "custom") == "custom"):
            base_url = model.get("base_url", "http://127.0.0.1:8000/v1")
            if not isinstance(base_url, str):
                raise ValueError(f'{model["key"]}: base_url must be a string')
            parsed = urlparse(base_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError(f'{model["key"]}: base_url must be an http(s) URL')
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError(
                    f'{model["key"]}: base_url cannot contain credentials, query, or fragment'
                )
        api_key_env = model.get("api_key_env")
        if api_key_env is not None and (
                not isinstance(api_key_env, str)
                or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", api_key_env) is None):
            raise ValueError(f'{model["key"]}: api_key_env must be a portable variable name')
        for field in ("context_window", "max_tokens"):
            if field in model:
                value = model[field]
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise ValueError(f'{model["key"]}: {field} must be a positive integer')
        _model_rounds(model, rounds)
        filters = model.get("item_filters")
        if filters is not None:
            if not isinstance(filters, dict):
                raise ValueError(f'{model["key"]}: item_filters must be a JSON object')
            selected_rounds = set(_model_rounds(model, rounds))
            for round_text, values in filters.items():
                try:
                    round_no = int(round_text)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f'{model["key"]}: invalid item-filter round') from exc
                if not isinstance(round_text, str) or round_text != str(round_no):
                    raise ValueError(
                        f'{model["key"]}: item-filter round keys must be canonical strings')
                if round_no not in selected_rounds or not isinstance(values, list) or not values:
                    raise ValueError(
                        f'{model["key"]}: item filter must be non-empty and target a selected round')
                if len(values) != len({str(value) for value in values}):
                    raise ValueError(f'{model["key"]}: item filter contains duplicates')
                if round_no in (1, 2, 3):
                    available = _round_item_ids(round_no)
                    if any(isinstance(value, bool) or not isinstance(value, int)
                           or value not in available for value in values):
                        raise ValueError(f'{model["key"]}: unknown round {round_no} item')
                elif any(not isinstance(value, str) or value not in round4.CANONICAL_TASKS
                         for value in values):
                    raise ValueError(f'{model["key"]}: unknown round 4 task')
    tasks = config.get("round4_tasks")
    if tasks is not None:
        if (not isinstance(tasks, list) or not tasks
                or any(not isinstance(task, str) for task in tasks)):
            raise ValueError("round4_tasks must be a non-empty JSON list of task names")
        if len(tasks) != len(set(tasks)):
            raise ValueError("round4_tasks must not contain duplicates")
        unknown = sorted(set(tasks) - set(round4.CANONICAL_TASKS))
        if unknown:
            raise ValueError(f"unknown round4_tasks: {unknown}")
    needs_codex = any(4 in _model_rounds(model, rounds) for model in config["models"])
    needs_codex = needs_codex or any(
        model.get("transport") == "codex_cli" for model in config["models"]
    )
    if check_runtime and needs_codex and not shutil.which("codex"):
        raise ValueError("selected Codex transport or round 4 requires the codex CLI on PATH")


def _round_item_ids(round_no: int) -> set[int]:
    root = repo_root() / "rounds"
    if round_no in (1, 2):
        return {int(item["id"]) for item in
                load_json(root / f"round{round_no}" / "questions.json")}
    if round_no == 3:
        return {int(item["id"]) for item in
                load_json(root / "round3" / "problems_v3.json")["questions"]}
    raise ValueError(f"unsupported round {round_no}")


def _round_units(round_no: int) -> int:
    return len(_round_item_ids(round_no))


def _campaign_units(config: dict) -> int:
    repetitions = int(config["repetitions"])
    campaign_rounds = [int(value) for value in config["rounds"]]
    tasks = config.get("round4_tasks") or round4.CANONICAL_TASKS
    total = 0
    for model in config["models"]:
        for round_no in _model_rounds(model, campaign_rounds):
            selected = _item_filter(model, round_no)
            units = len(selected) if selected is not None else (
                len(tasks) if round_no == 4 else _round_units(round_no))
            total += repetitions * units
    return total


def _progress_callback(dashboard: TerminalDashboard, model: dict, round_no: int,
                       attempt: int, attempts: int):
    def update(event: dict) -> None:
        item = str(event.get("item", "item"))
        event_attempt = int(event.get("attempt", attempt))
        if event.get("event") == "start":
            dashboard.start(model["key"], round_no, event_attempt, attempts, item)
        else:
            dashboard.record(str(event["status"]), model["key"], round_no,
                             event_attempt, attempts, item, event.get("wall"))
    return update


def _execute(config: dict, run_dir: Path, dry_run: bool,
             dashboard: TerminalDashboard) -> None:
    repetitions = int(config["repetitions"])
    timeout = int(config.get("timeout_seconds", 3600))
    for model in config["models"]:
        model["key"] = slug(model["key"])
        model_root = run_dir / model["key"]
        backend = make_backend(model, run_dir / "_state")
        selected_rounds = _model_rounds(model, [int(x) for x in config["rounds"]])
        for round_no in [number for number in selected_rounds if number in (1, 2, 3)]:
            for attempt in range(1, repetitions + 1):
                out = model_root / f"round{round_no}" / f"attempt-{attempt}"
                result_path = out / "result.json"
                if result_path.exists():
                    saved_result = load_json(result_path)
                    if not (saved_result.get("infrastructure_errors")
                            or saved_result.get("incomplete")):
                        dashboard.skip(
                            int(saved_result.get("planned", _round_units(round_no))),
                            f"{model['key']} round {round_no} attempt {attempt}")
                        continue
                    dashboard.message(
                        f"[retry] {model['key']} round {round_no} attempt {attempt} "
                        "has incomplete or infrastructure-invalid items")
                dashboard.message(
                    f"[run] {model['key']} round {round_no} attempt {attempt}/{repetitions}")
                if dry_run:
                    continue
                out.mkdir(parents=True, exist_ok=True)
                progress = _progress_callback(
                    dashboard, model, round_no, attempt, repetitions)
                if round_no in (1, 2):
                    round12.run(round_no, model, backend, attempt, out, timeout,
                                question_filter=(set(_item_filter(model, round_no))
                                                 if _item_filter(model, round_no) else None),
                                progress=progress)
                else:
                    round3.run(
                        model, backend, attempt, out, timeout,
                        question_filter=(set(_item_filter(model, round_no))
                                         if _item_filter(model, round_no) else None),
                        progress=progress)
        if 4 in selected_rounds:
            out = model_root / "round4"
            if (out / "run.json").exists():
                saved = load_json(out / "run.json")
                if not saved.get("errors"):
                    dashboard.skip(
                        int(saved.get("attempts", repetitions))
                        * len(saved.get("tasks", config.get("round4_tasks")
                                       or round4.CANONICAL_TASKS)),
                        f"{model['key']} round 4")
                    continue
                dashboard.message(f"[retry] {model['key']} round 4 has infrastructure errors")
            if not (out / "run.json").exists() or saved.get("errors"):
                dashboard.message(f"[run] {model['key']} round 4 x{repetitions}")
                if not dry_run:
                    out.mkdir(parents=True, exist_ok=True)
                    progress = _progress_callback(dashboard, model, 4, 1, repetitions)
                    code = round4.run(
                        model, repetitions, out, timeout,
                        _item_filter(model, 4) or config.get("round4_tasks"),
                        progress=progress)
                    if code:
                        raise RuntimeError(f"round 4 failed with exit code {code}")


def run(config: dict, runs_root: Path, resume: Path | None = None,
        dry_run: bool = False, progress_mode: str = "auto") -> Path:
    validate_config(config)
    run_dir = resume or (runs_root / (_safe_component(config.get("name", "campaign"), "campaign name")
                                      + "-" + stamp()))
    run_dir.mkdir(parents=True, exist_ok=True)
    snapshot = run_dir / "config.json"
    if snapshot.exists():
        existing = load_json(snapshot)
        if existing != config:
            raise ValueError("resume config does not match the saved config.json")
    else:
        save_json(snapshot, config)
    dashboard = TerminalDashboard(
        config.get("name", "campaign"), _campaign_units(config), run_dir,
        mode=progress_mode)
    try:
        _execute(config, run_dir, dry_run, dashboard)
        if not dry_run:
            generate(run_dir)
    except BaseException:
        dashboard.finish(False)
        raise
    if dry_run:
        dashboard.complete_plan()
    dashboard.finish(True, "Dry-run plan complete" if dry_run else "Report generated")
    return run_dir
