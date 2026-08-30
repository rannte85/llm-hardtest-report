from __future__ import annotations

import shutil
from pathlib import Path
from urllib.parse import urlparse

from .backends import make_backend
from .common import save_json, slug, stamp
from . import round12, round3, round4
from .report import generate


def validate_config(config: dict, check_runtime: bool = True) -> None:
    """Validate a campaign before any run artifacts are created.

    ``check_runtime`` is disabled while generating a configuration so a user can
    prepare it on a machine where Codex will be installed later. Actual runs keep
    the runtime check enabled and fail before partially executing a campaign.
    """
    if not config.get("models"):
        raise ValueError("config.models must contain at least one model")
    keys = [m.get("key") for m in config["models"]]
    if any(not key for key in keys) or len(keys) != len(set(keys)):
        raise ValueError("every model requires a unique non-empty key")
    normalized_keys = [slug(str(key)) for key in keys]
    if any(str(key) != normalized for key, normalized in zip(keys, normalized_keys)):
        raise ValueError("model keys must use only letters, numbers, dot, underscore, or hyphen")
    if len(normalized_keys) != len(set(normalized_keys)):
        raise ValueError("model keys must remain unique after filesystem normalization")
    if int(config.get("repetitions", 0)) < 1:
        raise ValueError("repetitions must be at least 1")
    if int(config.get("timeout_seconds", 3600)) < 1:
        raise ValueError("timeout_seconds must be at least 1")
    raw_rounds = config.get("rounds", [])
    try:
        rounds = [int(value) for value in raw_rounds]
    except (TypeError, ValueError) as exc:
        raise ValueError("rounds must contain integers from 1 to 4") from exc
    if not rounds or any(value not in (1, 2, 3, 4) for value in rounds):
        raise ValueError("rounds must be a non-empty subset of [1,2,3,4]")
    if len(rounds) != len(set(rounds)):
        raise ValueError("rounds must not contain duplicates")
    for model in config["models"]:
        if not model.get("model"):
            raise ValueError(f'{model.get("key", "model")}: model is required')
        if model.get("transport") not in ("openai_compat", "codex_cli"):
            raise ValueError(f'{model.get("key")}: unsupported transport')
        if (model.get("transport") == "openai_compat"
                or model.get("codex_provider", "custom") == "custom"):
            base_url = model.get("base_url", "http://127.0.0.1:8000/v1")
            parsed = urlparse(base_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError(f'{model["key"]}: base_url must be an http(s) URL')
    if check_runtime and 4 in rounds and not shutil.which("codex"):
        raise ValueError("round 4 requires the codex CLI on PATH")


def run(config: dict, runs_root: Path, resume: Path | None = None,
        dry_run: bool = False) -> Path:
    validate_config(config)
    run_dir = resume or (runs_root / (config.get("name", "campaign") + "-" + stamp()))
    run_dir.mkdir(parents=True, exist_ok=True)
    snapshot = run_dir / "config.json"
    if snapshot.exists():
        existing = __import__("json").load(snapshot.open(encoding="utf-8"))
        if existing != config:
            raise ValueError("resume config does not match the saved config.json")
    else:
        save_json(snapshot, config)
    repetitions = int(config["repetitions"])
    timeout = int(config.get("timeout_seconds", 3600))
    for model in config["models"]:
        model["key"] = slug(model["key"])
        model_root = run_dir / model["key"]
        backend = make_backend(model, run_dir / "_state")
        for round_no in [int(x) for x in config["rounds"] if int(x) in (1, 2, 3)]:
            for attempt in range(1, repetitions + 1):
                out = model_root / f"round{round_no}" / f"attempt-{attempt}"
                if (out / "result.json").exists():
                    print(f"[resume] {model['key']} round {round_no} attempt {attempt}")
                    continue
                print(f"[run] {model['key']} round {round_no} attempt {attempt}/{repetitions}")
                if dry_run:
                    continue
                out.mkdir(parents=True, exist_ok=True)
                if round_no in (1, 2):
                    round12.run(round_no, model, backend, attempt, out, timeout)
                else:
                    round3.run(model, backend, attempt, out, timeout)
        if 4 in [int(x) for x in config["rounds"]]:
            out = model_root / "round4"
            if (out / "run.json").exists():
                print(f"[resume] {model['key']} round 4")
            else:
                print(f"[run] {model['key']} round 4 x{repetitions}")
                if not dry_run:
                    out.mkdir(parents=True, exist_ok=True)
                    code = round4.run(model, repetitions, out, timeout,
                                      config.get("round4_tasks"))
                    if code:
                        raise RuntimeError(f"round 4 failed with exit code {code}")
    if not dry_run:
        generate(run_dir)
    return run_dir
