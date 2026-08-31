from __future__ import annotations

import copy
import re
from collections import defaultdict
from pathlib import Path

from .calibration import (
    _model_identity, _safe_evidence_file, analyze_runs, collect_observations,
)
from .common import load_json, repo_root, save_json, slug
from .orchestrator import validate_config
from .packs import validate_pack


def _runtime_item(round_number: int, item: str):
    if round_number in {1, 2, 3}:
        match = re.fullmatch(r"q([0-9]+)", item)
        if match is None:
            raise ValueError(
                f"panel item {item!r} is not runnable in round {round_number}")
        return int(match.group(1))
    if round_number == 4 and isinstance(item, str) and item:
        return item
    raise ValueError(f"panel item {item!r} is not runnable in round {round_number}")


def _unique_key(preferred: object, used: set[str]) -> str:
    base = slug(str(preferred or "model"))
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def build_panel_config(run_dirs: list[Path], *, max_items: int | None = None,
                       repetitions: int = 5,
                       allow_partial: bool = False) -> tuple[dict, dict]:
    """Build a fresh focused config from locally revalidated panel evidence."""
    if (isinstance(repetitions, bool) or not isinstance(repetitions, int)
            or repetitions < 1):
        raise ValueError("panel repetitions must be a positive integer")
    analysis = analyze_runs(run_dirs, max_items)
    evidence = collect_observations(run_dirs)
    selected_groups = []
    for group in analysis["groups"]:
        panel = group["discriminative_item_panel"]
        selected = [row["item"] for row in panel["selected_items"]]
        if not selected:
            continue
        if panel["status"] == "PARTIAL" and not allow_partial:
            raise ValueError(
                "panel budget leaves uncovered directions; rerun without a limit or "
                "pass --allow-partial")
        selected_groups.append((group, panel, selected))
    if not selected_groups:
        raise ValueError("no confirmed discriminative panel items are available")

    packs_by_round = defaultdict(set)
    for group, _, _ in selected_groups:
        packs_by_round[group["round"]].add(group["pack"])
    ambiguous = sorted(round_number for round_number, packs in packs_by_round.items()
                       if len(packs) != 1)
    if ambiguous:
        raise ValueError(
            "panel evidence contains multiple pack fingerprints for round(s): "
            + ", ".join(map(str, ambiguous)))
    for round_number, fingerprints in packs_by_round.items():
        observed = next(iter(fingerprints))
        current = validate_pack(
            repo_root() / "rounds" / f"round{round_number}")["fingerprint"]
        if observed != current:
            raise ValueError(
                f"round {round_number} panel pack does not match the installed pack")

    representatives = {}
    representative_order = []
    timeout_values = []
    for run_dir in run_dirs:
        config_path = _safe_evidence_file(run_dir / "config.json", run_dir)
        source = load_json(config_path)
        timeout = source.get("timeout_seconds", 3600)
        if (not isinstance(timeout, bool)
                and isinstance(timeout, (int, float)) and timeout >= 1):
            timeout_values.append(int(timeout))
        for model in source.get("models", []):
            if not isinstance(model, dict):
                continue
            identity = _model_identity(model)
            if identity not in representatives:
                representatives[identity] = model
                representative_order.append(identity)

    filters = defaultdict(lambda: defaultdict(set))
    panels = []
    for group, panel, selected in selected_groups:
        round_number, pack = group["round"], group["pack"]
        active_identities = set(evidence[(round_number, pack)]["models"].values())
        runtime_items = {_runtime_item(round_number, item) for item in selected}
        for identity in active_identities:
            filters[identity][str(round_number)].update(runtime_items)
        panels.append({
            "round": round_number,
            "pack": pack,
            "status": panel["status"],
            "selected_items": selected,
            "uncovered_directional_targets": panel["uncovered_directional_targets"],
        })

    models = []
    used_keys = set()
    for identity in representative_order:
        if identity not in filters:
            continue
        model = copy.deepcopy(representatives[identity])
        model.pop("item_filters", None)
        model["key"] = _unique_key(model.get("key") or model.get("model"), used_keys)
        ordered_filters = {
            round_text: sorted(values, key=lambda value: (str(type(value)), value))
            for round_text, values in sorted(
                filters[identity].items(), key=lambda pair: int(pair[0]))
        }
        model["rounds"] = [int(value) for value in ordered_filters]
        model["item_filters"] = ordered_filters
        models.append(model)
    if not models:
        raise ValueError("panel configurations could not be mapped to source models")

    rounds = sorted(packs_by_round)
    config = {
        "name": "llm-hardtest-panel",
        "repetitions": repetitions,
        "rounds": rounds,
        "timeout_seconds": max(timeout_values, default=3600),
        "models": models,
        "panel_focus": {
            "schema_version": 1,
            "analysis_schema_version": analysis["schema_version"],
            "selection_method": "deterministic_greedy_directional_set_cover",
            "source_run_count": len(run_dirs),
            "max_items_per_group": max_items,
            "partial_allowed": allow_partial,
            "groups": sorted(panels, key=lambda row: (row["round"], row["pack"])),
        },
    }
    if 4 in rounds:
        config["round4_tasks"] = sorted({
            item for model in models
            for item in model["item_filters"].get("4", [])})
    validate_config(config, check_runtime=False)
    return config, analysis


def write_panel_config(run_dirs: list[Path], output: Path, *,
                       max_items: int | None = None, repetitions: int = 5,
                       allow_partial: bool = False) -> tuple[Path, dict, dict]:
    if output.suffix.lower() != ".json":
        raise ValueError("panel config output must use a .json extension")
    if output.exists() or output.is_symlink():
        raise ValueError(f"refusing to overwrite existing panel config: {output}")
    config, analysis = build_panel_config(
        run_dirs, max_items=max_items, repetitions=repetitions,
        allow_partial=allow_partial)
    save_json(output, config)
    return output, config, analysis
