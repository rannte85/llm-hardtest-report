from __future__ import annotations

import json
from collections import defaultdict

from .community_results import (
    MIN_BASELINE_SUBMISSIONS, PACK_FINGERPRINT, _candidate_metrics, _cell,
    aggregate_submissions,
)


CATALOG_SCHEMA_VERSION = 3
FACET_FIELDS = (
    "configuration", "model", "os", "architecture", "python", "transport",
    "serving_scope", "serving_os", "serving_architecture",
    "reasoning_effort", "context_window", "max_tokens", "temperature", "top_p",
    "top_k", "min_p", "model_revision", "quantization", "model_format",
    "parameter_count_b", "server", "server_version", "accelerator",
    "accelerator_count", "memory_gb", "system_memory_gb",
)
PARAMETER_FACETS = {
    "reasoning_effort", "context_window", "max_tokens", "temperature", "top_p",
    "top_k", "min_p",
}
METADATA_FACETS = {
    "model_revision", "quantization", "model_format", "parameter_count_b", "server",
    "server_version", "accelerator", "accelerator_count", "memory_gb",
    "system_memory_gb",
}
OPTIONAL_FACETS = PARAMETER_FACETS | METADATA_FACETS | {
    "serving_os", "serving_architecture",
}


def _validate_filters(round_number: int | None, pack: str | None) -> None:
    if round_number is not None and (
            isinstance(round_number, bool) or round_number not in {1, 2, 3, 4}):
        raise ValueError("catalog round must be one of 1, 2, 3, or 4")
    if pack is not None and (
            not isinstance(pack, str) or PACK_FINGERPRINT.fullmatch(pack) is None):
        raise ValueError("catalog pack must be an exact sha256 fingerprint")


def _facet_value(row: dict, field: str):
    if field == "configuration":
        return row["configuration"]
    if field == "model":
        return row["model"]
    if field in {"os", "architecture", "python"}:
        return row["environment"][field]
    if field.startswith("serving_"):
        return row["serving_environment"].get(field.removeprefix("serving_"))
    if field == "transport":
        return row["transport"]
    if field in PARAMETER_FACETS:
        return row["parameters"].get(field)
    return row["public_metadata"].get(field)


def _observation(row: dict) -> dict:
    metrics = _candidate_metrics(row)
    accuracy_ready = metrics["accuracy_lower95"] is not None
    readiness = {
        "accuracy": accuracy_ready,
        "completion": accuracy_ready and metrics["completion_lower95"] is not None,
        "latency": (
            accuracy_ready
            and metrics["bundle_mean_item_latency_p90_seconds"] is not None),
        "throughput": (
            accuracy_ready
            and metrics["bundle_mean_completion_tokens_per_second_p50"] is not None),
    }
    return {
        "round": row["round"],
        "pack": row["pack"],
        "independent_bundles": row["observed_submissions"],
        "readiness": readiness,
        "metrics": metrics,
    }


def _facet_rows(rows: list[dict], field: str) -> tuple[list[dict], dict | None]:
    values = defaultdict(lambda: {
        "spellings": set(), "configurations": set(), "observations": 0,
        "max_independent_bundles": 0, "recommendation_ready_observations": 0,
    })
    missing_configurations = set()
    missing_observations = 0
    for row in rows:
        value = _facet_value(row, field)
        if value is None:
            missing_configurations.add(row["configuration"])
            missing_observations += 1
            continue
        identity = (("text", value.casefold()) if isinstance(value, str)
                    else ("number", float(value)))
        group = values[identity]
        group["spellings"].add(value)
        group["configurations"].add(row["configuration"])
        group["observations"] += 1
        group["max_independent_bundles"] = max(
            group["max_independent_bundles"], row["observed_submissions"])
        if row["bundle_pass_rate_interval95"] is not None:
            group["recommendation_ready_observations"] += 1
    result = []
    for identity, group in sorted(values.items()):
        representative = (
            sorted(group["spellings"], key=lambda item: (item.casefold(), item))[0]
            if identity[0] == "text" else float(identity[1]))
        result.append({
            "value": representative,
            "configurations": len(group["configurations"]),
            "observations": group["observations"],
            "max_independent_bundles": group["max_independent_bundles"],
            "recommendation_ready_observations": group[
                "recommendation_ready_observations"],
        })
    missing = None
    if field in OPTIONAL_FACETS:
        missing = {
            "configurations": len(missing_configurations),
            "observations": missing_observations,
        }
    return result, missing


def build_catalog(aggregate_rows: list[dict], *, round_number: int | None = None,
                  pack: str | None = None) -> dict:
    """Describe the exact observed serving space without exposing bundle identities."""
    _validate_filters(round_number, pack)
    source_observations = len(aggregate_rows)
    rows = [
        row for row in aggregate_rows
        if (round_number is None or row["round"] == round_number)
        and (pack is None or row["pack"] == pack)
    ]
    rows.sort(key=lambda row: (
        row["model"].casefold(), row["configuration"], row["round"], row["pack"]))
    configurations = {}
    for row in rows:
        identity = {
            "configuration": row["configuration"],
            "model": row["model"],
            "environment": row["environment"],
            "serving_environment": row["serving_environment"],
            "transport": row["transport"],
            "parameters": row["parameters"],
            "public_metadata": row["public_metadata"],
        }
        current = configurations.setdefault(
            row["configuration"], {**identity, "observations": []})
        if {key: current[key] for key in identity} != identity:
            raise ValueError("catalog configuration identity collision")
        current["observations"].append(_observation(row))

    facets = {}
    missing_coordinates = {}
    for field in FACET_FIELDS:
        facets[field], missing = _facet_rows(rows, field)
        if missing is not None:
            missing_coordinates[field] = missing
    status = "OBSERVED"
    if not rows:
        status = "EMPTY" if source_observations == 0 else "NO_MATCH"
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "kind": "observed_serving_catalog",
        "filters": {"round": round_number, "pack": pack},
        "status": status,
        "minimum_independent_bundles": MIN_BASELINE_SUBMISSIONS,
        "summary": {
            "configurations": len(configurations),
            "observations": len(rows),
            "models": len({row["model"].casefold() for row in rows}),
            "rounds": sorted({row["round"] for row in rows}),
            "packs": sorted({row["pack"] for row in rows}),
            "recommendation_ready_observations": sum(
                row["bundle_pass_rate_interval95"] is not None for row in rows),
        },
        "facets": facets,
        "missing_coordinates": missing_coordinates,
        "configurations": sorted(
            configurations.values(),
            key=lambda row: (row["model"].casefold(), row["configuration"])),
    }


def catalog_submissions(submissions: list[dict], *, round_number: int | None = None,
                        pack: str | None = None) -> dict:
    """Build a serving catalog from validated canonical public bundles."""
    return build_catalog(
        aggregate_submissions(submissions), round_number=round_number, pack=pack)


def render_catalog(catalog: dict) -> str:
    """Render a compact discovery report for humans selecting query constraints."""
    summary = catalog["summary"]
    filters = catalog["filters"]
    lines = [
        "# Observed Serving Catalog", "",
        f"Status: **{catalog['status']}**", "",
        f"Configurations: **{summary['configurations']}** · observations: "
        f"**{summary['observations']}** · recommendation-ready: "
        f"**{summary['recommendation_ready_observations']}**", "",
        "Filter: round=" + (str(filters["round"]) if filters["round"] else "all")
        + " · pack=" + (f"`{filters['pack']}`" if filters["pack"] else "all"), "",
    ]
    if catalog["configurations"]:
        lines += [
            "| Model | Config | Runner | Serving environment | Server / build | Generation settings | Round / pack | Bundles | Ready objectives |",
            "|---|---|---|---|---|---|---|---:|---|",
        ]
        for configuration in catalog["configurations"]:
            environment = configuration["environment"]
            serving_environment = configuration["serving_environment"]
            metadata = configuration["public_metadata"]
            for index, observation in enumerate(configuration["observations"]):
                ready = ", ".join(
                    key for key, value in observation["readiness"].items() if value) or "none"
                server = metadata.get("server", "unspecified")
                if "server_version" in metadata:
                    server += "@" + metadata["server_version"]
                build = "/".join(filter(None, (
                    metadata.get("quantization"), metadata.get("model_format"))))
                serving = server + (f" · {build}" if build else "")
                lines.append(
                    f"| {_cell(configuration['model']) if index == 0 else '↳'} | "
                    f"`{configuration['configuration']}` | "
                    f"{_cell(environment['os'])}/{_cell(environment['architecture'])}/"
                    f"py{_cell(environment['python'])} | "
                    f"{_cell(serving_environment['scope'])}/"
                    f"{_cell(serving_environment.get('os') or 'unspecified')}/"
                    f"{_cell(serving_environment.get('architecture') or 'unspecified')} · "
                    f"{_cell(metadata.get('accelerator', 'unspecified'))} | "
                    f"{_cell(serving)} | "
                    f"{_cell(json.dumps(configuration['parameters'], sort_keys=True))} | "
                    f"{observation['round']} / `{observation['pack']}` | "
                    f"{observation['independent_bundles']} | {ready} |")
    else:
        lines += ["No observed configuration matches the catalog filter.", ""]
    lines += [
        "", "## Use", "",
        "Copy exact values from this catalog into `results recommend` constraints such",
        "as `--configuration`, `--model`, `--server-version`, `--context-window`, and",
        "`--quantization`. Readiness means",
        "the observation has the five independent bundles required by the descriptive",
        "recommender; it is not a prediction for an untested setup. A missing coordinate",
        "is shown as unspecified and never satisfies a requested constraint.", "",
    ]
    return "\n".join(lines)
