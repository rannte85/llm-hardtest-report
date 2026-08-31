from __future__ import annotations

import json

from .community_results import (
    MIN_BASELINE_SUBMISSIONS, _cell, _configuration_summary,
    _matches_constraints, _recommend_aggregate_rows, aggregate_submissions,
)


COLLECTION_PLAN_SCHEMA_VERSION = 2


def _objective_counts(row: dict) -> dict[str, int]:
    return {
        "accuracy": row["observed_submissions"],
        "completion": row["bundle_completion_rate_observed_submissions"],
        "latency": row["bundle_item_wall_observed_submissions"],
        "throughput": row["bundle_token_rate_observed_submissions"],
    }


def build_collection_plan(aggregate_rows: list[dict], *, round_number: int,
                          pack: str | None = None,
                          constraints: dict | None = None,
                          objectives: list[str] | None = None,
                          target_bundles: int = MIN_BASELINE_SUBMISSIONS) -> dict:
    """Plan independent complete bundles needed for observed configurations."""
    if (isinstance(target_bundles, bool) or not isinstance(target_bundles, int)
            or not MIN_BASELINE_SUBMISSIONS <= target_bundles <= 1000):
        raise ValueError(
            f"target bundles must be an integer from {MIN_BASELINE_SUBMISSIONS} to 1000")

    # The recommender owns the public round, pack, constraint, and objective contract.
    # Reusing it prevents the collection planner from accepting a divergent query.
    query = _recommend_aggregate_rows(
        aggregate_rows, round_number=round_number, pack=pack,
        constraints=constraints, objectives=objectives)
    constraints = query["constraints"]
    objectives = query["objectives"]
    selected_pack = query["pack"]
    result = {
        "schema_version": COLLECTION_PLAN_SCHEMA_VERSION,
        "kind": "independent_bundle_collection_plan",
        "round": round_number,
        "pack": selected_pack,
        "available_packs": query["available_packs"],
        "constraints": constraints,
        "objectives": objectives,
        "minimum_recommendation_bundles": MIN_BASELINE_SUBMISSIONS,
        "target_independent_bundles": target_bundles,
        "status": "NO_OBSERVATIONS",
        "reason": "no observations exist for the requested round and pack",
        "summary": {
            "matched_configurations": 0,
            "ready_configurations": 0,
            "configurations_needing_collection": 0,
            "minimum_additional_complete_bundles": 0,
        },
        "configurations": [],
    }
    if query["status"] == "PACK_REQUIRED":
        result["status"] = "PACK_REQUIRED"
        result["reason"] = query["reason"]
        return result
    if selected_pack is None or selected_pack not in query["available_packs"]:
        return result

    rows = [
        row for row in aggregate_rows
        if row["round"] == round_number and row["pack"] == selected_pack
        and _matches_constraints(row, constraints)
    ]
    rows.sort(key=lambda row: (row["model"].casefold(), row["configuration"]))
    if not rows:
        result["status"] = "NO_MATCH"
        result["reason"] = "no exact public configuration matches every constraint"
        return result

    planned = []
    for row in rows:
        observed = _objective_counts(row)
        selected_observed = {key: observed[key] for key in objectives}
        deficits = {
            key: max(0, target_bundles - selected_observed[key])
            for key in objectives
        }
        accuracy_prerequisite = {
            "observed_independent_bundles": observed["accuracy"],
            "minimum_required_bundles": MIN_BASELINE_SUBMISSIONS,
            "deficit": max(0, MIN_BASELINE_SUBMISSIONS - observed["accuracy"]),
        }
        additional = max(
            [*deficits.values(), accuracy_prerequisite["deficit"]], default=0)
        planned.append({
            "configuration": row["configuration"],
            "model": row["model"],
            "environment": row["environment"],
            "serving_environment": row["serving_environment"],
            "transport": row["transport"],
            "parameters": row["parameters"],
            "public_metadata": row["public_metadata"],
            "observed_independent_bundles": selected_observed,
            "bundle_deficits": deficits,
            "accuracy_prerequisite": accuracy_prerequisite,
            "minimum_additional_complete_bundles": additional,
            "ready": additional == 0,
        })
    ready = sum(row["ready"] for row in planned)
    additional = sum(
        row["minimum_additional_complete_bundles"] for row in planned)
    result["summary"] = {
        "matched_configurations": len(planned),
        "ready_configurations": ready,
        "configurations_needing_collection": len(planned) - ready,
        "minimum_additional_complete_bundles": additional,
    }
    result["configurations"] = sorted(
        planned,
        key=lambda row: (-row["minimum_additional_complete_bundles"],
                         row["model"].casefold(), row["configuration"]))
    if ready == len(planned):
        result["status"] = "TARGET_MET"
        result["reason"] = (
            "every matching configuration meets the target for every selected objective")
    else:
        result["status"] = "COLLECTION_NEEDED"
        result["reason"] = (
            "collect complete independent bundles for the listed exact configurations")
    return result


def plan_submissions(submissions: list[dict], **kwargs) -> dict:
    """Build a collection plan from validated canonical public bundles."""
    return build_collection_plan(aggregate_submissions(submissions), **kwargs)


def render_collection_plan(result: dict) -> str:
    """Render a deterministic, privacy-preserving acquisition plan."""
    summary = result["summary"]
    lines = [
        "# Independent Bundle Collection Plan", "",
        f"Status: **{result['status']}**", "", result["reason"], "",
        f"Round: **{result['round']}** · pack: "
        + (f"`{result['pack']}`" if result["pack"] else "not selected"), "",
        "Objectives: " + ", ".join(result["objectives"]), "",
        f"Target: **{result['target_independent_bundles']}** independent bundles per "
        "configuration and selected objective", "",
        f"Matched: **{summary['matched_configurations']}** · ready: "
        f"**{summary['ready_configurations']}** · needing collection: "
        f"**{summary['configurations_needing_collection']}** · minimum additional "
        f"complete bundles: **{summary['minimum_additional_complete_bundles']}**", "",
    ]
    if result["constraints"]:
        lines += ["Constraints: `" + json.dumps(
            result["constraints"], sort_keys=True, ensure_ascii=False) + "`", ""]
    if result["configurations"]:
        lines += [
            "| Model | Config | Observed setup | Observed by objective | Deficit by objective | Accuracy prerequisite | Additional complete bundles |",
            "|---|---|---|---|---|---|---:|",
        ]
        for row in result["configurations"]:
            lines.append(
                f"| {_cell(row['model'])} | `{row['configuration']}` | "
                f"{_configuration_summary(row).replace('|', chr(92) + '|')} | `"
                f"{json.dumps(row['observed_independent_bundles'], sort_keys=True)}` | `"
                f"{json.dumps(row['bundle_deficits'], sort_keys=True)}` | "
                f"{row['accuracy_prerequisite']['observed_independent_bundles']}/"
                f"{row['accuracy_prerequisite']['minimum_required_bundles']} "
                f"(deficit {row['accuracy_prerequisite']['deficit']}) | "
                f"{row['minimum_additional_complete_bundles']} |")
    lines += [
        "", "## Interpretation", "",
        "The total is a lower bound: it assumes each new independent bundle reports",
        "every selected objective for exactly one listed configuration. Partial bundles",
        "may reduce only some deficits. Repeated runs inside one bundle do not increase",
        "the count. Every plan also enforces the recommender's five-scored-bundle",
        "accuracy prerequisite, even when accuracy is not a selected target objective.",
        "This plan exposes no contributor or bundle IDs,",
        "does not schedule submissions, and does not predict untested configurations.", "",
    ]
    if result["status"] == "PACK_REQUIRED":
        lines += ["Available packs:", ""] + [
            f"- `{value}`" for value in result["available_packs"]] + [""]
    return "\n".join(lines)
