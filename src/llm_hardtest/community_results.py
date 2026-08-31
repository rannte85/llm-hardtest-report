from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path

from .calibration import (
    _configuration_item_coverage, _discriminative_item_panel, _estimate_interval,
    _item_metrics, _item_relationships, _item_repeat_separation,
    _pairwise_stability, _panel_holdout_validation,
)
from .github_submit import submission_relative_path
from .public_pilots import load_public_pilot_bundle
from .public_results import load_public_bundle, normalized_serving_environment


MIN_BASELINE_SUBMISSIONS = 5
RECOMMENDATION_SCHEMA_VERSION = 3
RECOMMENDATION_OBJECTIVES = {"accuracy", "completion", "latency", "throughput"}
RECOMMENDATION_TEXT_CONSTRAINTS = {
    "configuration", "model", "os", "architecture", "python", "transport",
    "serving_scope", "serving_os", "serving_architecture",
    "reasoning_effort", "model_revision", "quantization", "model_format",
    "server", "server_version", "accelerator",
}
RECOMMENDATION_NUMERIC_CONSTRAINTS = {
    "context_window", "max_tokens", "temperature", "top_p", "top_k", "min_p",
    "parameter_count_b", "accelerator_count", "memory_gb", "system_memory_gb",
}
RECOMMENDATION_MAX_CONSTRAINTS = {
    "max_memory_gb", "max_system_memory_gb", "max_parameter_count_b",
}
RECOMMENDATION_CONSTRAINTS = (
    RECOMMENDATION_TEXT_CONSTRAINTS | RECOMMENDATION_NUMERIC_CONSTRAINTS
    | RECOMMENDATION_MAX_CONSTRAINTS)
PARAMETER_CONSTRAINTS = {
    "reasoning_effort", "context_window", "max_tokens", "temperature", "top_p",
    "top_k", "min_p",
}
PACK_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")
CONFIGURATION_ID = re.compile(r"^[0-9a-f]{10}$")


def _cluster_interval(rates: list[float]) -> dict | None:
    """Wilson-style 95% interval across independent bundle rates, never attempts."""
    if len(rates) < MIN_BASELINE_SUBMISSIONS:
        return None
    z = 1.96
    sample_size = len(rates)
    estimate = statistics.mean(rates)
    denominator = 1 + z ** 2 / sample_size
    center = (estimate + z ** 2 / (2 * sample_size)) / denominator
    margin = (z / denominator * math.sqrt(
        estimate * (1 - estimate) / sample_size
        + z ** 2 / (4 * sample_size ** 2)))
    return {
        "estimate": round(estimate, 6),
        "low": round(max(0.0, center - margin), 6),
        "high": round(min(1.0, center + margin), 6),
        "observed_submissions": sample_size,
        "method": "bundle_cluster_wilson_95",
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 3)


def load_submission_directory(directory: Path) -> list[dict]:
    """Validate canonical public JSON files and their content-derived filenames."""
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError(
            f"submission directory does not exist as a regular directory: {directory}")
    submissions = []
    seen = set()
    for path in sorted(directory.iterdir()):
        if path.name == ".gitkeep":
            continue
        if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".json":
            raise ValueError(f"unexpected submission entry: {path.name}")
        payload = load_public_bundle(path)
        expected = Path(submission_relative_path(payload)).name
        if path.name != expected:
            raise ValueError(f"submission filename does not match bundle ID: {path.name}")
        if payload["bundle_id"] in seen:
            raise ValueError(f"duplicate public bundle: {payload['bundle_id']}")
        seen.add(payload["bundle_id"])
        submissions.append(payload)
    return submissions


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _configuration_id(payload: dict, model: dict) -> str:
    identity = {
        "runner_environment": payload["environment"],
        "serving_environment": normalized_serving_environment(payload, model),
        "public_name": model["public_name"],
        "transport": model["transport"],
        "parameters": model["parameters"],
        "public_metadata": model["public_metadata"],
    }
    return hashlib.sha256(_canonical(identity)).hexdigest()[:10]


def aggregate_submissions(submissions: list[dict]) -> list[dict]:
    """Group only identical public configurations, rounds, and pack fingerprints."""
    groups = defaultdict(lambda: {
        "submissions": 0, "runs": 0, "passed": 0, "total": 0, "incomplete": 0,
        "manual_review": 0, "infrastructure_errors": 0,
    })
    configurations = {}
    for payload in submissions:
        bundle_groups = defaultdict(lambda: {
            "runs": 0, "passed": 0, "total": 0, "incomplete": 0,
            "manual_review": 0, "infrastructure_errors": 0,
            "_item_walls": [], "_token_rates": [],
        })
        for model in payload["models"]:
            configuration = _configuration_id(payload, model)
            identity = {
                "environment": payload["environment"],
                "serving_environment": normalized_serving_environment(payload, model),
                "model": model["public_name"],
                "transport": model["transport"],
                "parameters": model["parameters"],
                "public_metadata": model["public_metadata"],
            }
            previous_identity = configurations.setdefault(configuration, identity)
            if previous_identity != identity:
                raise ValueError("public configuration ID collision")
            for round_number, metrics in model["rounds"].items():
                pack = payload["benchmark"]["packs"][round_number]
                key = (int(round_number), pack, model["public_name"], configuration)
                local = bundle_groups[key]
                local["runs"] += 1
                score_fields = (("release_ready", "attempts") if round_number == "4"
                                else ("passed", "total"))
                for target, source in zip(("passed", "total"), score_fields):
                    value = metrics.get(source)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        local[target] += value
                for field in ("incomplete", "manual_review", "infrastructure_errors"):
                    value = metrics.get(field)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        local[field] += value
                for item in metrics.get("items", []):
                    wall, tokens = item.get("wall_seconds"), item.get("tokens")
                    if isinstance(wall, (int, float)) and not isinstance(wall, bool):
                        local["_item_walls"].append(float(wall))
                        if (wall > 0 and isinstance(tokens, int)
                                and not isinstance(tokens, bool)):
                            local["_token_rates"].append(tokens / wall)
        for key, local in bundle_groups.items():
            group = groups[key]
            group["submissions"] += 1
            for field, value in local.items():
                if not field.startswith("_"):
                    group[field] += value
            if local["total"] > 0:
                group.setdefault("_bundle_pass_rates", []).append(
                    local["passed"] / local["total"])
            attempted = (local["total"] + local["incomplete"]
                         + local["manual_review"] + local["infrastructure_errors"])
            if attempted > 0:
                group.setdefault("_bundle_completion_rates", []).append(
                    local["total"] / attempted)
            if local["_item_walls"]:
                group.setdefault("_bundle_mean_walls", []).append(
                    statistics.mean(local["_item_walls"]))
            if local["_token_rates"]:
                group.setdefault("_bundle_mean_token_rates", []).append(
                    statistics.mean(local["_token_rates"]))
    rows = []
    for (round_number, pack, model_name, configuration), totals in sorted(
            groups.items(), key=lambda item: (item[0][0], item[0][2].lower(), item[0][3])):
        rates = totals.get("_bundle_pass_rates", [])
        rows.append({
            "round": round_number,
            "pack": pack,
            "model": model_name,
            "configuration": configuration,
            **configurations[configuration],
            **{key: value for key, value in totals.items() if not key.startswith("_")},
            "observed_submissions": len(rates),
            "bundle_pass_rate_interval95": _cluster_interval(rates),
            "bundle_completion_rate_observed_submissions": len(
                totals.get("_bundle_completion_rates", [])),
            "bundle_completion_rate_interval95": _cluster_interval(
                totals.get("_bundle_completion_rates", [])),
            "bundle_item_wall_p50_seconds": _percentile(
                totals.get("_bundle_mean_walls", []), 0.5),
            "bundle_item_wall_p90_seconds": _percentile(
                totals.get("_bundle_mean_walls", []), 0.9),
            "bundle_item_wall_observed_submissions": len(
                totals.get("_bundle_mean_walls", [])),
            "bundle_tokens_per_second_p50": _percentile(
                totals.get("_bundle_mean_token_rates", []), 0.5),
            "bundle_token_rate_observed_submissions": len(
                totals.get("_bundle_mean_token_rates", [])),
        })
    return rows


def _constraint_value(row: dict, key: str):
    if key == "configuration":
        return row.get("configuration")
    if key == "model":
        return row.get("model")
    if key in {"os", "architecture", "python"}:
        return row["environment"].get(key)
    if key in {"serving_scope", "serving_os", "serving_architecture"}:
        return row["serving_environment"].get(key.removeprefix("serving_"))
    if key == "transport":
        return row.get("transport")
    if key in PARAMETER_CONSTRAINTS:
        return row["parameters"].get(key)
    if key in RECOMMENDATION_MAX_CONSTRAINTS:
        return row["public_metadata"].get(key.removeprefix("max_"))
    return row["public_metadata"].get(key)


def _matches_constraints(row: dict, constraints: dict) -> bool:
    for key, expected in constraints.items():
        actual = _constraint_value(row, key)
        if actual is None:
            return False
        if key in RECOMMENDATION_MAX_CONSTRAINTS:
            if (isinstance(actual, bool) or not isinstance(actual, (int, float))
                    or actual > expected):
                return False
        elif isinstance(expected, str):
            if not isinstance(actual, str) or actual.casefold() != expected.casefold():
                return False
        elif actual != expected:
            return False
    return True


def _candidate_metrics(row: dict) -> dict:
    accuracy = row["bundle_pass_rate_interval95"]
    completion = row["bundle_completion_rate_interval95"]
    latency_bundles = row["bundle_item_wall_observed_submissions"]
    throughput_bundles = row["bundle_token_rate_observed_submissions"]
    return {
        "accuracy_lower95": accuracy["low"] if accuracy else None,
        "accuracy_observed": accuracy["estimate"] if accuracy else None,
        "completion_lower95": completion["low"] if completion else None,
        "completion_observed": completion["estimate"] if completion else None,
        "bundle_mean_item_latency_p90_seconds": (
            row["bundle_item_wall_p90_seconds"]
            if latency_bundles >= MIN_BASELINE_SUBMISSIONS else None),
        "latency_observed_bundles": latency_bundles,
        "bundle_mean_completion_tokens_per_second_p50": (
            row["bundle_tokens_per_second_p50"]
            if throughput_bundles >= MIN_BASELINE_SUBMISSIONS else None),
        "throughput_observed_bundles": throughput_bundles,
    }


def _objective_value(candidate: dict, objective: str) -> float | None:
    field = {
        "accuracy": "accuracy_lower95",
        "completion": "completion_lower95",
        "latency": "bundle_mean_item_latency_p90_seconds",
        "throughput": "bundle_mean_completion_tokens_per_second_p50",
    }[objective]
    value = candidate["metrics"][field]
    return None if value is None else float(value)


def _dominates(left: dict, right: dict, objectives: list[str]) -> bool:
    comparisons = []
    for objective in objectives:
        left_value = _objective_value(left, objective)
        right_value = _objective_value(right, objective)
        if left_value is None or right_value is None:
            return False
        if objective == "latency":
            comparisons.append((left_value <= right_value, left_value < right_value))
        else:
            comparisons.append((left_value >= right_value, left_value > right_value))
    return all(no_worse for no_worse, _ in comparisons) and any(
        better for _, better in comparisons)


def _recommend_aggregate_rows(aggregate_rows: list[dict], *, round_number: int,
                              pack: str | None = None,
                              constraints: dict | None = None,
                              objectives: list[str] | None = None,
                              accuracy_floor: float | None = None) -> dict:
    """Return a gated Pareto shortlist from normalized aggregate rows."""
    if isinstance(round_number, bool) or round_number not in {1, 2, 3, 4}:
        raise ValueError("recommendation round must be one of 1, 2, 3, or 4")
    if constraints is not None and not isinstance(constraints, dict):
        raise ValueError("recommendation constraints must be an object")
    constraints = dict(constraints or {})
    if any(not isinstance(key, str) for key in constraints):
        raise ValueError("recommendation constraint keys must be strings")
    unknown_constraints = set(constraints) - RECOMMENDATION_CONSTRAINTS
    if unknown_constraints:
        raise ValueError(
            "unknown recommendation constraint(s): "
            + ", ".join(sorted(unknown_constraints)))
    for key in RECOMMENDATION_MAX_CONSTRAINTS:
        if key not in constraints:
            continue
        value = constraints[key]
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value <= 0):
            raise ValueError(f"recommendation constraint {key} must be positive")
    for key in RECOMMENDATION_NUMERIC_CONSTRAINTS:
        if key not in constraints:
            continue
        value = constraints[key]
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value)):
            raise ValueError(f"recommendation constraint {key} must be finite numeric")
    for key in RECOMMENDATION_TEXT_CONSTRAINTS:
        if key not in constraints:
            continue
        value = constraints[key]
        if (not isinstance(value, str) or not value.strip() or len(value) > 160
                or any(ord(char) < 32 for char in value)):
            raise ValueError(f"recommendation constraint {key} must be safe text")
    if ("configuration" in constraints
            and CONFIGURATION_ID.fullmatch(constraints["configuration"]) is None):
        raise ValueError(
            "recommendation constraint configuration must be an exact 10-character ID")
    if ("python" in constraints
            and re.fullmatch(r"[0-9]+\.[0-9]+", constraints["python"]) is None):
        raise ValueError(
            "recommendation constraint python must be a major.minor version")
    if ("transport" in constraints
            and constraints["transport"] not in {"openai_compat", "codex_cli"}):
        raise ValueError("recommendation constraint transport is unsupported")
    if ("serving_scope" in constraints and constraints["serving_scope"] not in {
            "same_host", "remote", "unreported"}):
        raise ValueError("recommendation constraint serving_scope is unsupported")
    if ("serving_os" in constraints and constraints["serving_os"] not in {
            "Linux", "Darwin", "Windows", "Other"}):
        raise ValueError("recommendation constraint serving_os is unsupported")
    if ("serving_architecture" in constraints
            and len(constraints["serving_architecture"]) > 32):
        raise ValueError(
            "recommendation constraint serving_architecture must be at most 32 characters")
    if isinstance(objectives, str):
        raise ValueError("recommendation objectives must be a list")
    objectives = list(objectives or ["accuracy"])
    if (not objectives or len(objectives) != len(set(objectives))
            or set(objectives) - RECOMMENDATION_OBJECTIVES):
        raise ValueError("recommendation objectives must be unique values from: "
                         + ", ".join(sorted(RECOMMENDATION_OBJECTIVES)))
    if (accuracy_floor is not None
            and (isinstance(accuracy_floor, bool)
                 or not isinstance(accuracy_floor, (int, float))
                 or not math.isfinite(accuracy_floor)
                 or not 0 <= accuracy_floor <= 1)):
        raise ValueError("accuracy floor must be between 0 and 1")
    if pack is not None and (
            not isinstance(pack, str) or PACK_FINGERPRINT.fullmatch(pack) is None):
        raise ValueError("recommendation pack must be an exact sha256 fingerprint")

    rows = [row for row in aggregate_rows if row["round"] == round_number]
    available_packs = sorted({row["pack"] for row in rows})
    if pack is None:
        selected_pack = available_packs[0] if len(available_packs) == 1 else None
    else:
        selected_pack = pack
    result = {
        "schema_version": RECOMMENDATION_SCHEMA_VERSION,
        "kind": "descriptive_serving_candidates",
        "round": round_number,
        "pack": selected_pack,
        "available_packs": available_packs,
        "constraints": constraints,
        "objectives": objectives,
        "accuracy_floor": accuracy_floor,
        "minimum_independent_bundles": MIN_BASELINE_SUBMISSIONS,
        "status": "INSUFFICIENT_EVIDENCE",
        "reason": "no observations match the requested round and pack",
        "matched_configurations": 0,
        "eligible_configurations": 0,
        "candidates": [],
        "excluded": {"constraints": 0, "insufficient_bundles": 0,
                     "missing_objective": 0, "accuracy_floor": 0,
                     "dominated": 0},
    }
    if pack is None and len(available_packs) > 1:
        result["status"] = "PACK_REQUIRED"
        result["reason"] = "multiple pack fingerprints exist; select one exact pack"
        return result
    if selected_pack is None or selected_pack not in available_packs:
        return result
    rows = [row for row in rows if row["pack"] == selected_pack]
    matched = []
    for row in rows:
        if not _matches_constraints(row, constraints):
            result["excluded"]["constraints"] += 1
            continue
        matched.append(row)
    result["matched_configurations"] = len(matched)
    eligible = []
    for row in matched:
        if row["bundle_pass_rate_interval95"] is None:
            result["excluded"]["insufficient_bundles"] += 1
            continue
        candidate = {
            "configuration": row["configuration"],
            "model": row["model"],
            "environment": row["environment"],
            "serving_environment": row["serving_environment"],
            "transport": row["transport"],
            "parameters": row["parameters"],
            "public_metadata": row["public_metadata"],
            "independent_bundles": row["observed_submissions"],
            "metrics": _candidate_metrics(row),
        }
        if any(_objective_value(candidate, objective) is None
               for objective in objectives):
            result["excluded"]["missing_objective"] += 1
            continue
        if (accuracy_floor is not None
                and candidate["metrics"]["accuracy_lower95"] < accuracy_floor):
            result["excluded"]["accuracy_floor"] += 1
            continue
        eligible.append(candidate)
    result["eligible_configurations"] = len(eligible)
    candidates = []
    for candidate in eligible:
        if any(_dominates(other, candidate, objectives)
               for other in eligible if other is not candidate):
            result["excluded"]["dominated"] += 1
        else:
            candidates.append(candidate)
    result["candidates"] = sorted(
        candidates, key=lambda row: (row["model"].casefold(), row["configuration"]))
    if not matched:
        result["status"] = "NO_MATCH"
        result["reason"] = "no exact public configuration matches every constraint"
    elif not eligible:
        result["reason"] = (
            "matching configurations do not meet the independent-bundle, objective, "
            "and conservative accuracy gates")
    elif len(eligible) == 1:
        result["status"] = "SINGLE_ELIGIBLE_CONFIGURATION"
        result["reason"] = "one eligible observed configuration exists; no comparison is possible"
    else:
        result["status"] = "DESCRIPTIVE_CANDIDATES"
        result["reason"] = (
            "non-dominated observed configurations; this is not a prediction for "
            "untested hardware or settings")
    return result


def recommend_configurations(submissions: list[dict], *, round_number: int,
                             pack: str | None = None,
                             constraints: dict | None = None,
                             objectives: list[str] | None = None,
                             accuracy_floor: float | None = None) -> dict:
    """Return a gated Pareto shortlist from validated public bundles."""
    return _recommend_aggregate_rows(
        aggregate_submissions(submissions), round_number=round_number, pack=pack,
        constraints=constraints, objectives=objectives,
        accuracy_floor=accuracy_floor)


def _configuration_summary(candidate: dict) -> str:
    environment = candidate["environment"]
    serving_environment = candidate["serving_environment"]
    metadata = candidate["public_metadata"]
    parameters = candidate["parameters"]
    serving_coordinates = "/".join(filter(None, (
        serving_environment.get("os"), serving_environment.get("architecture"))))
    parts = [
        f"runner={environment['os']}/{environment['architecture']}/py{environment['python']}",
        "serving=" + serving_environment["scope"]
        + (f"/{serving_coordinates}" if serving_coordinates else ""),
        candidate["transport"],
    ]
    for key, label in (
            ("model_revision", "revision"), ("quantization", "quant"),
            ("model_format", "format"), ("parameter_count_b", "parameters B"),
            ("server", "server"), ("server_version", "server version"),
            ("accelerator", "accelerator"), ("accelerator_count", "accelerators"),
            ("memory_gb", "memory GB"), ("system_memory_gb", "system GB")):
        if key in metadata:
            parts.append(f"{label}={metadata[key]}")
    for key, label in (("reasoning_effort", "reasoning"),
                       ("context_window", "context"),
                       ("max_tokens", "max tokens"),
                       ("temperature", "temperature"), ("top_p", "top p"),
                       ("top_k", "top k"), ("min_p", "min p")):
        if key in parameters:
            parts.append(f"{label}={parameters[key]}")
    return "; ".join(parts)


def render_recommendation(result: dict) -> str:
    """Render a deterministic, caveated serving-candidate report."""
    lines = [
        "# Descriptive Serving Candidates", "",
        f"Status: **{result['status']}**", "", result["reason"], "",
        f"Round: **{result['round']}** · pack: "
        + (f"`{result['pack']}`" if result["pack"] else "not selected"),
        "",
        "Objectives: " + ", ".join(result["objectives"]),
        "",
        f"Matched configurations: **{result['matched_configurations']}** · "
        f"eligible: **{result['eligible_configurations']}** · "
        f"Pareto candidates: **{len(result['candidates'])}**", "",
    ]
    if result["constraints"]:
        lines += ["Constraints: `" + json.dumps(
            result["constraints"], sort_keys=True, ensure_ascii=False) + "`", ""]
    if result["candidates"]:
        lines += [
            "| Model | Config | Observed setup | Bundles | Accuracy lower / observed | Completion lower / observed | Bundle-mean item latency p90 | Bundle-mean completion tok/s p50 |",
            "|---|---|---|---:|---:|---:|---:|---:|",
        ]
        for row in result["candidates"]:
            metrics = row["metrics"]
            lines.append(
                f"| {_cell(row['model'])} | `{row['configuration']}` | "
                f"{_cell(_configuration_summary(row))} | "
                f"{row['independent_bundles']} | "
                f"{_percent(metrics['accuracy_lower95'])} / "
                f"{_percent(metrics['accuracy_observed'])} | "
                f"{_percent(metrics['completion_lower95'])} / "
                f"{_percent(metrics['completion_observed'])} | "
                f"{metrics['bundle_mean_item_latency_p90_seconds'] if metrics['bundle_mean_item_latency_p90_seconds'] is not None else 'n/a'} "
                f"(n={metrics['latency_observed_bundles']}) | "
                f"{metrics['bundle_mean_completion_tokens_per_second_p50'] if metrics['bundle_mean_completion_tokens_per_second_p50'] is not None else 'n/a'} "
                f"(n={metrics['throughput_observed_bundles']}) |")
    lines += [
        "", "## Interpretation", "",
        "Candidates are filtered from validated voluntary submissions for one exact pack.",
        "Accuracy and completion objectives use conservative bundle-cluster interval",
        "lower bounds. Latency and throughput require five observed bundles and summarize",
        "the distribution of each bundle's mean item measurement. A declared",
        "hardware capacity is an observation filter, not proof that the model requires or",
        "will fit that capacity. Missing metadata never satisfies a requested constraint.",
        "No candidate is a prediction for an untested model, runtime, or environment.", "",
    ]
    if result["status"] == "PACK_REQUIRED":
        lines += ["Available packs:", ""] + [
            f"- `{pack}`" for pack in result["available_packs"]] + [""]
    return "\n".join(lines)


def aggregate_item_diagnostics(submissions: list[dict]) -> list[dict]:
    """Recompute status-only item signal from schema-v2 community observations."""
    groups = defaultdict(lambda: {
        "matrix": defaultdict(dict), "models": {}, "clusters": {}, "bundles": set(),
    })
    for payload in submissions:
        if payload.get("schema_version", 1) < 2:
            continue
        bundle_id = payload["bundle_id"]
        for model in payload["models"]:
            configuration = _configuration_id(payload, model)
            for round_number, metrics in model["rounds"].items():
                pack = payload["benchmark"]["packs"][round_number]
                group = groups[(int(round_number), pack)]
                for item in metrics.get("items", []):
                    respondent = (bundle_id, configuration, item["attempt"])
                    previous = group["matrix"][respondent].get(item["item"])
                    if previous is not None and previous != item["status"]:
                        raise ValueError(
                            "one public bundle has conflicting duplicate item outcomes")
                    group["matrix"][respondent][item["item"]] = item["status"]
                    group["models"][respondent] = configuration
                    group["clusters"][respondent] = bundle_id
                    group["bundles"].add(bundle_id)
    rows = []
    for (round_number, pack), group in sorted(groups.items()):
        if not group["matrix"]:
            continue
        relationships = _item_relationships(group["matrix"], group["clusters"])
        coverage = _configuration_item_coverage(
            group["matrix"], group["models"],
            {identity: identity for identity in set(group["models"].values())},
            group["clusters"])
        rows.append({
            "round": round_number,
            "pack": pack,
            "bundles": len(group["bundles"]),
            "respondents": len(group["matrix"]),
            "configurations": len(set(group["models"].values())),
            "pairwise": _pairwise_stability(group["matrix"], group["models"]),
            "items": _item_metrics(group["matrix"], group["clusters"]),
            "item_relationships": relationships,
            "item_repeat_separation": _item_repeat_separation(
                group["matrix"], group["models"], group["clusters"]),
            "configuration_item_coverage": coverage,
            "discriminative_item_panel": _discriminative_item_panel(
                coverage, relationships),
            "panel_holdout_validation": _panel_holdout_validation(
                group["matrix"], group["models"],
                {identity: identity for identity in set(group["models"].values())},
                clusters=group["clusters"]),
        })
    return rows


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}%"


def render_index(submissions: list[dict]) -> str:
    lines = [
        "# Community Result Index",
        "",
        "Built only from validated, voluntary public submissions. Raw prompts and model",
        "outputs are not collected. Configuration IDs separate environment, transport,",
        "parameters, and declared metadata; pack fingerprints separate benchmark versions.",
        "",
    ]
    if not submissions:
        lines += [
            "No validated community results have been merged yet.",
            "",
            "This file will contain descriptive examples after voluntary submissions are accepted.",
            "It will not present sparse community data as a prediction for untested models.",
            "",
        ]
        return "\n".join(lines)
    rows = aggregate_submissions(submissions)
    lines += [
        f"Validated bundles: **{len(submissions)}**. Comparable model/round groups: **{len(rows)}**.",
        "",
        "| Round | Pack | Public model | Config | Bundles | Observed score | Completion | Serving observations | Baseline |",
        "|---:|---|---|---|---:|---:|---:|---|---|",
    ]
    for row in rows:
        total = row["total"]
        passed = row["passed"]
        attempted = (total + row["incomplete"] + row["manual_review"]
                     + row["infrastructure_errors"])
        score = f"{passed:g}/{total:g}" if total else "n/a"
        completion = f"{(100 * total / attempted):.1f}%" if attempted else "n/a"
        interval = row["bundle_pass_rate_interval95"]
        baseline = (
            f"{100 * interval['estimate']:.1f}% observed "
            f"[{100 * interval['low']:.1f}–{100 * interval['high']:.1f}%], "
            f"n={interval['observed_submissions']} bundles"
            if interval else
            f"withheld (<{MIN_BASELINE_SUBMISSIONS} observed bundles)")
        wall50, wall90 = (row["bundle_item_wall_p50_seconds"],
                          row["bundle_item_wall_p90_seconds"])
        token_rate = row["bundle_tokens_per_second_p50"]
        performance = (
            f"bundle p50/p90 item latency {wall50:g}/{wall90:g}s"
            if wall50 is not None and wall90 is not None else "latency n/a")
        if token_rate is not None:
            performance += f"; p50 {token_rate:g} completion tok/s"
        lines.append(
            f"| {row['round']} | `{row['pack'][7:19]}` | {_cell(row['model'])} | "
            f"`{row['configuration']}` | {row['submissions']} | {score} | {completion} | "
            f"{performance} | {baseline} |")
    diagnostics = aggregate_item_diagnostics(submissions)
    if diagnostics:
        lines += ["", "## Community Item Diagnostics", ""]
        for group in diagnostics:
            pairwise = group["pairwise"]
            lines += [
                f"### Round {group['round']} · pack `{group['pack'][7:19]}`",
                "",
                f"Bundles: **{group['bundles']}** · respondents: **{group['respondents']}** · "
                f"configurations: **{group['configurations']}**",
                "",
                f"Between-config disagreement: **{_percent(pairwise['between_configuration_disagreement'])}** · "
                f"within-config disagreement: **{_percent(pairwise['within_configuration_disagreement'])}** · "
                f"net separation: **{_percent(pairwise['net_separation'])}**",
                "",
                "| Item | Scored | Independent bundles | Pass raw | Bundle pass [95%] | Balance raw / bundle | Corrected discrimination (raw) | Bundle-clustered corrected [95%] | Observed | Robust | Incomplete | Review | Invalid | Missing |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---:|---:|---:|",
            ]
            for item in group["items"]:
                discrimination = item["corrected_item_total_correlation"]
                clustered = item["clustered_corrected_discrimination"]
                lines.append(
                    f"| `{_cell(item['item'])}` | {item['scored']} | "
                    f"{item['independent_units']} | "
                    f"{_percent(item['pass_rate'])} | "
                    f"{_estimate_interval(item['clustered_pass_rate'], item['pass_rate_interval95'], percent=True)} | "
                    f"{_percent(item['difficulty_balance'])} / "
                    f"{_percent(item['clustered_difficulty_balance'])} | "
                    f"{discrimination if discrimination is not None else 'n/a'} | "
                    f"{_estimate_interval(clustered, item['discrimination_interval95'])} | "
                    f"{item['classification']} | {item['robust_classification']} | "
                    f"{item['incomplete']} | {item['review']} | "
                    f"{item['invalid']} | {item['missing']} |")
            relationships = [
                row for row in group["item_relationships"]
                if row["classification"] in {
                    "REDUNDANCY_CANDIDATE", "OPPOSING_CANDIDATE", "RELATED"}
                or row["robust_classification"] in {
                    "ROBUST_REDUNDANCY_CANDIDATE",
                    "ROBUST_OPPOSING_CANDIDATE"}
            ]
            lines += [
                "", "#### Community item dependency candidates", "",
                "| Items | Common | Independent bundles | Agreement raw / bundle | Phi raw | Bundle phi [95%] | Observed | Robust |",
                "|---|---:|---:|---:|---:|---:|---|---|",
            ]
            for row in relationships[:20]:
                lines.append(
                    f"| `{_cell(row['left'])}` ↔ `{_cell(row['right'])}` | "
                    f"{row['common_scored']} | {row['independent_units']} | "
                    f"{_percent(row['outcome_agreement'])} / "
                    f"{_percent(row['clustered_outcome_agreement'])} | "
                    f"{row['phi_correlation'] if row['phi_correlation'] is not None else 'n/a'} | "
                    f"{_estimate_interval(row['clustered_phi_correlation'], row['correlation_interval95'])} | "
                    f"{row['classification']} | {row['robust_classification']} |")
            if not relationships:
                lines.append("| none | 0 | 0 | n/a | n/a | n/a | n/a | n/a |")
            if len(relationships) > 20:
                lines += ["", "Only the first 20 ranked candidates are shown; validated "
                          "machine-readable diagnostics retain every item pair."]
            lines += [
                "", "#### Community repeat-adjusted item separation", "",
                "| Item | Configs / repeated / robust | Independent bundles | Between separation | Repeat instability | Net separation | Robust net [95%] | Observed | Robust |",
                "|---|---:|---:|---:|---:|---:|---:|---|---|",
            ]
            for row in group["item_repeat_separation"]:
                lines.append(
                    f"| `{_cell(row['item'])}` | {row['configurations']}/"
                    f"{row['repeat_configurations']}/{row['robust_configurations']} | "
                    f"{row['independent_units']} | "
                    f"{_percent(row['between_configuration_separation'])} | "
                    f"{_percent(row['within_configuration_instability'])} | "
                    f"{_percent(row['net_repeat_adjusted_separation'])} | "
                    f"{_estimate_interval(row['robust_net_repeat_adjusted_separation'], row['net_separation_interval95'], percent=True)} | "
                    f"{row['classification']} | {row['robust_classification']} |")
            coverage = group["configuration_item_coverage"]
            details = [(pair, item) for pair in coverage["comparisons"]
                       for item in pair["items"]
                       if item["classification"] in {"LEFT_HIGHER", "RIGHT_HIGHER"}]
            lines += [
                "", "#### Community pair-specific item coverage", "",
                f"Eligible configuration pairs: **{coverage['eligible_configuration_pairs']}** · "
                f"decisive item splits: **{len(details)}**", "",
                "| Config pair | Item | Independent bundles | Pass-rate difference [simultaneous interval] | Result |",
                "|---|---|---:|---:|---|",
            ]
            for pair, item in details[:20]:
                lines.append(
                    f"| `{pair['left']}` ↔ `{pair['right']}` | `{_cell(item['item'])}` | "
                    f"{item['left_independent_units']}/{item['right_independent_units']} | "
                    f"{_estimate_interval(item['pass_rate_difference'], item['simultaneous_interval'], percent=True)} | "
                    f"{item['classification']} |")
            if not details:
                lines.append("| none | none | 0/0 | n/a | n/a |")
            panel = group["discriminative_item_panel"]
            lines += [
                "", "#### Community discriminative item panel", "",
                f"Status: **{panel['status']}** · selected: "
                f"**{len(panel['selected_items'])}/{panel['candidate_items']}** · "
                f"directions covered: **{panel['covered_directional_targets']}/"
                f"{panel['directional_targets']}**", "",
                "| Item | Newly covered configuration directions | Minimum simultaneous margin | Robust dependency degree | Dependency with earlier selection |",
                "|---|---|---:|---:|---|",
            ]
            for row in panel["selected_items"]:
                lines.append(
                    f"| `{_cell(row['item'])}` | "
                    f"{', '.join(f'`{_cell(value)}`' for value in row['new_directional_targets'])} | "
                    f"{_percent(row['minimum_simultaneous_margin'])} | "
                    f"{row['robust_dependency_degree']} | "
                    f"{', '.join(f'`{_cell(value)}`' for value in row['robustly_dependent_with_selected']) or 'none'} |")
            if not panel["selected_items"]:
                lines.append("| none | none | n/a | 0 | none |")
            holdout = group["panel_holdout_validation"]
            lines += [
                "", "#### Community out-of-fold panel validation", "",
                f"Status: **{holdout['status']}** · folds evaluated: "
                f"**{holdout['folds_evaluated']}/2** · confirmed/weak/reversed: "
                f"**{holdout['confirmed_direction_evaluations']}/"
                f"{holdout['weak_direction_evaluations']}/"
                f"{holdout['reversed_direction_evaluations']}** · confirmation: "
                f"**{_percent(holdout['direction_confirmation_rate'])}** · "
                f"selection Jaccard: "
                f"**{holdout['selection_jaccard'] if holdout['selection_jaccard'] is not None else 'n/a'}**",
                "",
                "| Fold | Item | Direction | Independent bundles | Holdout difference | Holm p | Result |",
                "|---:|---|---|---:|---:|---:|---|",
            ]
            for fold in holdout["folds"]:
                if not fold["holdout_evaluations"]:
                    lines.append(
                        f"| {fold['fold']} | none | none | 0/0 | n/a | n/a | INSUFFICIENT |")
                for row in fold["holdout_evaluations"]:
                    lines.append(
                        f"| {fold['fold']} | `{_cell(row['item'])}` | "
                        f"`{_cell(row['directional_target'])}` | "
                        f"{row['higher_holdout_units']}/{row['lower_holdout_units']} | "
                        f"{_percent(row['holdout_pass_rate_difference'])} | "
                        f"{row['permutation_p_holm'] if row['permutation_p_holm'] is not None else 'n/a'} | "
                        f"{row['classification']} |")
    lines += [
        "",
        f"Baselines appear only after at least {MIN_BASELINE_SUBMISSIONS} distinct accepted bundles",
        "with observed scores share the exact public configuration and pack. Each bundle",
        "contributes one rate regardless of its attempt count; duplicate model entries cannot",
        "raise the threshold. Brackets are Wilson-style 95% intervals across bundle rates,",
        "not item-level certainty. Item robust signals also use bundles as equal-weight",
        "clusters and require at least ten independent bundles; repeated attempts cannot",
        "unlock them. Dependency diagnostics use the same bundle clustering and treat",
        "high positive or negative phi relationships as content-review candidates, never",
        "automatic deletion decisions. Repeat-adjusted item diagnostics also require two",
        "configurations with repeated bundle evidence and subtract within-configuration",
        "instability from between-configuration separation. Values are descriptive",
        "observations. Pair-specific coverage uses simultaneous maximum-error intervals",
        "within each configuration pair and Bonferroni allocation across pairs; one bundle",
        "is resampled once even if it contains both configurations. Values are not predictions",
        "for an unseen model or a different runtime configuration. The discriminative panel",
        "is a deterministic greedy review aid over already-decisive directions. It penalizes",
        "robust empirical dependencies but is not a globally minimal set or an automatic pack",
        "change. Community out-of-fold validation keeps every shared contribution in one",
        "fold and requires five independent bundles per configuration on both training and",
        "holdout sides. Held-out directions also require a Holm-adjusted two-sided",
        "permutation p-value below 0.05. `INSUFFICIENT` never means that a panel replicated.",
        "",
    ]
    return "\n".join(lines)


def build_index(directory: Path, output: Path, *, check: bool = False) -> tuple[int, int]:
    submissions = load_submission_directory(directory)
    document = render_index(submissions)
    if check:
        if not output.is_file() or output.read_text(encoding="utf-8") != document:
            raise ValueError(f"community result index is stale; rebuild {output}")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(document, encoding="utf-8")
    return len(submissions), len(aggregate_submissions(submissions))


def load_pilot_submission_directory(directory: Path) -> list[dict]:
    """Validate sanitized Round 5 JSON submissions and content-derived names."""
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError(
            f"pilot submission directory does not exist as a regular directory: {directory}")
    submissions = []
    seen = set()
    for path in sorted(directory.iterdir()):
        if path.name == ".gitkeep":
            continue
        if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".json":
            raise ValueError(f"unexpected pilot submission entry: {path.name}")
        payload = load_public_pilot_bundle(path)
        expected = Path(submission_relative_path(payload)).name
        if path.name != expected:
            raise ValueError(f"pilot filename does not match bundle ID: {path.name}")
        if payload["bundle_id"] in seen:
            raise ValueError(f"duplicate public pilot bundle: {payload['bundle_id']}")
        seen.add(payload["bundle_id"])
        submissions.append(payload)
    return submissions


def aggregate_pilot_submissions(submissions: list[dict]) -> list[dict]:
    """Group identical public Round 5 configurations and pack fingerprints."""
    groups = defaultdict(lambda: {
        "submissions": 0, "attempts": 0, "complete": 0,
        "public_passed": 0, "public_total": 0,
        "hidden_passed": 0, "hidden_total": 0,
        "evidence_revision": 0, "release_ready": 0, "report_accurate": 0,
        "authority_violations": 0, "protocol_error_attempts": 0,
        "unsupported_tool_calls": 0,
    })
    for payload in submissions:
        bundle_groups = defaultdict(lambda: {
            "attempts": 0, "complete": 0,
            "public_passed": 0, "public_total": 0,
            "hidden_passed": 0, "hidden_total": 0,
            "evidence_revision": 0, "release_ready": 0, "report_accurate": 0,
            "authority_violations": 0, "protocol_error_attempts": 0,
            "unsupported_tool_calls": 0,
        })
        for model in payload["models"]:
            configuration = _configuration_id(payload, model)
            key = (payload["pilot"]["id"], payload["pilot"]["pack"],
                   model["public_name"], configuration)
            local = bundle_groups[key]
            for attempt in model["attempts"]:
                local["attempts"] += 1
                local["complete"] += attempt["status"] == "COMPLETE"
                local["public_passed"] += attempt["public"]["passed"]
                local["public_total"] += attempt["public"]["total"]
                local["hidden_passed"] += attempt["hidden"]["passed"]
                local["hidden_total"] += attempt["hidden"]["total"]
                local["evidence_revision"] += attempt["evidence_revision_observed"]
                local["release_ready"] += attempt["release_ready"]
                local["report_accurate"] += attempt["report_accurate"]
                local["authority_violations"] += not attempt["no_edit_before_approval"]
                local["protocol_error_attempts"] += not attempt["tool_protocol_clean"]
                local["unsupported_tool_calls"] += attempt["unsupported_tool_calls"]
        for key, local in bundle_groups.items():
            group = groups[key]
            group["submissions"] += 1
            for field, value in local.items():
                group[field] += value
            group.setdefault("_bundle_release_rates", []).append(
                local["release_ready"] / local["attempts"])
    rows = []
    for (pilot, pack, model, configuration), totals in sorted(
            groups.items(), key=lambda item: (item[0][0], item[0][2].lower(), item[0][3])):
        rates = totals.get("_bundle_release_rates", [])
        rows.append({
            "pilot": pilot, "pack": pack, "model": model,
            "configuration": configuration,
            **{key: value for key, value in totals.items() if not key.startswith("_")},
            "release_ready_interval95": _cluster_interval(rates),
        })
    return rows


def _ratio(passed: int, total: int) -> str:
    return f"{passed}/{total}" if total else "n/a"


def render_pilot_index(submissions: list[dict]) -> str:
    lines = [
        "# Community Round 5 Pilot Index",
        "",
        "Built only from validated, voluntary summaries. Raw transcripts, patches, prompts,",
        "credentials, and local paths are not collected. These are descriptive observations,",
        "not independently reproducible proof or predictions for unseen configurations.",
        "",
    ]
    if not submissions:
        lines += [
            "No validated community Round 5 pilot summaries have been merged yet.",
            "",
            "Observed baselines appear only after five distinct accepted bundles share the",
            "exact public configuration and pack fingerprint.",
            "",
        ]
        return "\n".join(lines)
    rows = aggregate_pilot_submissions(submissions)
    lines += [
        f"Validated bundles: **{len(submissions)}**. Comparable pilot groups: **{len(rows)}**.",
        "",
        "| Pilot | Pack | Public model | Config | Bundles | Attempts | Complete | Public | Hidden | Revision | Release | Report | Authority violations | Protocol errors | Baseline |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        attempts = row["attempts"]
        interval = row["release_ready_interval95"]
        baseline = (
            f"release {100 * interval['estimate']:.1f}% "
            f"[{100 * interval['low']:.1f}–{100 * interval['high']:.1f}%], "
            f"n={interval['observed_submissions']} bundles"
            if interval else
            f"withheld (<{MIN_BASELINE_SUBMISSIONS} bundles)")
        lines.append(
            f"| {_cell(row['pilot'])} | `{row['pack'][7:19]}` | {_cell(row['model'])} | "
            f"`{row['configuration']}` | {row['submissions']} | {attempts} | "
            f"{row['complete']}/{attempts} | "
            f"{_ratio(row['public_passed'], row['public_total'])} | "
            f"{_ratio(row['hidden_passed'], row['hidden_total'])} | "
            f"{row['evidence_revision']}/{attempts} | {row['release_ready']}/{attempts} | "
            f"{row['report_accurate']}/{attempts} | {row['authority_violations']} | "
            f"{row['protocol_error_attempts']} ({row['unsupported_tool_calls']} calls) | "
            f"{baseline} |")
    lines += [
        "",
        f"Release-ready baselines appear only after at least {MIN_BASELINE_SUBMISSIONS} distinct",
        "accepted bundles share the exact public configuration and pack. Each bundle",
        "contributes one release-ready rate regardless of its attempt count; duplicate model",
        "entries cannot raise the threshold. Brackets are Wilson-style 95% intervals",
        "across bundle rates. A 0/0 test score is unobserved, not a failure.",
        "",
    ]
    return "\n".join(lines)


def build_pilot_index(directory: Path, output: Path, *, check: bool = False) -> tuple[int, int]:
    submissions = load_pilot_submission_directory(directory)
    document = render_pilot_index(submissions)
    if check:
        if not output.is_file() or output.read_text(encoding="utf-8") != document:
            raise ValueError(f"community pilot index is stale; rebuild {output}")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(document, encoding="utf-8")
    return len(submissions), len(aggregate_pilot_submissions(submissions))
