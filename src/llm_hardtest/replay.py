from __future__ import annotations

import copy
from pathlib import Path

from .common import load_json
from .inspection import inspect_run


def make_replay_config(run_dir: Path, include_review: bool = False) -> dict | None:
    """Build a fresh, focused campaign config from unresolved saved evidence."""
    original = load_json(run_dir / "config.json")
    inspection = inspect_run(run_dir)
    statuses = {"FAIL", "INCOMPLETE", "INVALID"}
    if include_review:
        statuses.add("REVIEW")
    selected: dict[str, dict[str, set]] = {}
    for item in inspection["items"]:
        if item["status"] not in statuses or item.get("item_id") is None:
            continue
        model_filters = selected.setdefault(item["model"], {})
        model_filters.setdefault(str(item["round"]), set()).add(item["item_id"])
    if not selected:
        return None

    replay = copy.deepcopy(original)
    replay["name"] = str(original.get("name", "campaign")) + "-replay"
    replay["repetitions"] = 1
    replay["replay"] = {
        "parent_run_id": run_dir.name,
        "selection": "unresolved-with-review" if include_review else "failed-only",
    }
    models = []
    campaign_rounds = set()
    for model in replay["models"]:
        filters = selected.get(model["key"])
        if not filters:
            continue
        ordered = {}
        for round_text, values in sorted(filters.items(), key=lambda pair: int(pair[0])):
            ordered[round_text] = sorted(values, key=lambda value: (str(type(value)), value))
            campaign_rounds.add(int(round_text))
        model["rounds"] = sorted(int(number) for number in ordered)
        model["item_filters"] = ordered
        models.append(model)
    replay["models"] = models
    replay["rounds"] = sorted(campaign_rounds)
    return replay
