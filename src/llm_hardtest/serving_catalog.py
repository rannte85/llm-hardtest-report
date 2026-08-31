from __future__ import annotations

from collections import defaultdict

from .community_results import (
    MIN_BASELINE_SUBMISSIONS, PACK_FINGERPRINT, _candidate_metrics, _cell,
    aggregate_submissions,
)


CATALOG_SCHEMA_VERSION = 1
FACET_FIELDS = (
    "model", "os", "architecture", "transport", "accelerator", "server",
    "quantization", "model_format",
)
OPTIONAL_FACETS = {"accelerator", "server", "quantization", "model_format"}


def _validate_filters(round_number: int | None, pack: str | None) -> None:
    if round_number is not None and (
            isinstance(round_number, bool) or round_number not in {1, 2, 3, 4}):
        raise ValueError("catalog round must be one of 1, 2, 3, or 4")
    if pack is not None and (
            not isinstance(pack, str) or PACK_FINGERPRINT.fullmatch(pack) is None):
        raise ValueError("catalog pack must be an exact sha256 fingerprint")


def _facet_value(row: dict, field: str):
    if field == "model":
        return row["model"]
    if field in {"os", "architecture"}:
        return row["environment"][field]
    if field == "transport":
        return row["transport"]
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
        identity = value.casefold()
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
        result.append({
            "value": sorted(group["spellings"], key=lambda item: (item.casefold(), item))[0],
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
    missing_metadata = {}
    for field in FACET_FIELDS:
        facets[field], missing = _facet_rows(rows, field)
        if missing is not None:
            missing_metadata[field] = missing
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
        "missing_metadata": missing_metadata,
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
            "| Model | Config | Environment | Server | Quantization | Round / pack | Bundles | Ready objectives |",
            "|---|---|---|---|---|---|---:|---|",
        ]
        for configuration in catalog["configurations"]:
            environment = configuration["environment"]
            metadata = configuration["public_metadata"]
            for index, observation in enumerate(configuration["observations"]):
                ready = ", ".join(
                    key for key, value in observation["readiness"].items() if value) or "none"
                lines.append(
                    f"| {_cell(configuration['model']) if index == 0 else '↳'} | "
                    f"`{configuration['configuration']}` | "
                    f"{_cell(environment['os'])}/{_cell(environment['architecture'])} · "
                    f"{_cell(metadata.get('accelerator', 'unspecified'))} | "
                    f"{_cell(metadata.get('server', 'unspecified'))} | "
                    f"{_cell(metadata.get('quantization', 'unspecified'))} | "
                    f"{observation['round']} / `{observation['pack']}` | "
                    f"{observation['independent_bundles']} | {ready} |")
    else:
        lines += ["No observed configuration matches the catalog filter.", ""]
    lines += [
        "", "## Use", "",
        "Copy exact values from this catalog into `results recommend` constraints such",
        "as `--model`, `--server`, `--accelerator`, and `--quantization`. Readiness means",
        "the observation has the five independent bundles required by the descriptive",
        "recommender; it is not a prediction for an untested setup. Missing metadata is",
        "shown as unspecified and never satisfies a requested constraint.", "",
    ]
    return "\n".join(lines)
