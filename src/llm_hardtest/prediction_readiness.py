from __future__ import annotations

import hashlib
import json
from collections import defaultdict

from .community_results import (
    MIN_BASELINE_SUBMISSIONS, PACK_FINGERPRINT, RECOMMENDATION_OBJECTIVES,
    _cell, _configuration_summary,
)
from .paired_comparison import _bundle_observations


PREDICTION_READINESS_SCHEMA_VERSION = 1
DEFAULT_TARGET_BUNDLES = 10
DEFAULT_MINIMUM_CONFIGURATIONS = 3
DEFAULT_MINIMUM_ENVIRONMENTS = 2
DEFAULT_MINIMUM_PAIRED_EDGES = 1
DEFAULT_MINIMUM_ENVIRONMENT_BRIDGES = 1

_RUNTIME_FIELDS = (
    "server", "server_version", "accelerator", "accelerator_count",
    "memory_gb", "system_memory_gb",
)
_MODEL_PROFILE_METADATA_FIELDS = (
    "model_revision", "quantization", "model_format", "parameter_count_b",
)
_EXTERNAL_GATES = (
    "temporal_holdout_validation",
    "abuse_duplicate_and_implausibility_review",
    "pack_and_server_drift_monitoring",
)


def _bounded_integer(name: str, value: int, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer from {low} to {high}")
    return value


def _environment_record(observation: dict) -> dict:
    metadata = observation["public_metadata"]
    record = {
        "environment": observation["environment"],
        "runtime": {field: metadata.get(field) for field in _RUNTIME_FIELDS},
    }
    canonical = json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {
        "environment_id": hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:10],
        **record,
    }


def _model_profile_record(observation: dict) -> dict:
    metadata = observation["public_metadata"]
    record = {
        "model": observation["model"].casefold(),
        "transport": observation["transport"],
        "parameters": observation["parameters"],
        "model_metadata": {
            field: metadata.get(field) for field in _MODEL_PROFILE_METADATA_FIELDS
        },
    }
    canonical = json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {
        "model_profile_id": hashlib.sha256(
            canonical.encode("utf-8")).hexdigest()[:10],
        **record,
    }


def _gate(name: str, status: str, current, required, reason: str) -> dict:
    return {
        "name": name,
        "status": status,
        "current": current,
        "required": required,
        "reason": reason,
    }


def audit_prediction_readiness(
        observations: list[dict], *, round_number: int,
        pack: str | None = None, objectives: list[str] | None = None,
        target_bundles: int = DEFAULT_TARGET_BUNDLES,
        minimum_configurations: int = DEFAULT_MINIMUM_CONFIGURATIONS,
        minimum_environments: int = DEFAULT_MINIMUM_ENVIRONMENTS,
        minimum_paired_edges: int = DEFAULT_MINIMUM_PAIRED_EDGES,
        minimum_environment_bridges: int = DEFAULT_MINIMUM_ENVIRONMENT_BRIDGES) -> dict:
    """Audit whether public evidence has the design needed before model fitting."""
    if isinstance(round_number, bool) or round_number not in {1, 2, 3, 4}:
        raise ValueError("readiness round must be one of 1, 2, 3, or 4")
    if pack is not None and (
            not isinstance(pack, str) or PACK_FINGERPRINT.fullmatch(pack) is None):
        raise ValueError("readiness pack must be an exact sha256 fingerprint")
    if isinstance(objectives, str):
        raise ValueError("readiness objectives must be a list")
    objectives = list(objectives or ["accuracy"])
    if (not objectives or len(objectives) != len(set(objectives))
            or set(objectives) - RECOMMENDATION_OBJECTIVES):
        raise ValueError("readiness objectives must be unique values from: "
                         + ", ".join(sorted(RECOMMENDATION_OBJECTIVES)))
    target_bundles = _bounded_integer(
        "target bundles", target_bundles, MIN_BASELINE_SUBMISSIONS, 1000)
    minimum_configurations = _bounded_integer(
        "minimum configurations", minimum_configurations, 2, 1000)
    minimum_environments = _bounded_integer(
        "minimum environments", minimum_environments, 2, 1000)
    minimum_paired_edges = _bounded_integer(
        "minimum paired edges", minimum_paired_edges, 1, 100_000)
    minimum_environment_bridges = _bounded_integer(
        "minimum environment bridges", minimum_environment_bridges, 1, 1000)

    round_rows = [row for row in observations if row["round"] == round_number]
    available_packs = sorted({row["pack"] for row in round_rows})
    selected_pack = (pack if pack is not None
                     else available_packs[0] if len(available_packs) == 1 else None)
    thresholds = {
        "target_independent_bundles_per_configuration_objective": target_bundles,
        "minimum_configurations_meeting_target": minimum_configurations,
        "minimum_distinct_serving_environments": minimum_environments,
        "minimum_shared_bundles_per_paired_edge": MIN_BASELINE_SUBMISSIONS,
        "minimum_eligible_paired_edges": minimum_paired_edges,
        "minimum_model_profiles_repeated_across_environments": (
            minimum_environment_bridges),
        "minimum_independent_bundles_per_environment_bridge": (
            MIN_BASELINE_SUBMISSIONS),
    }
    result = {
        "schema_version": PREDICTION_READINESS_SCHEMA_VERSION,
        "kind": "predictive_serving_readiness_audit",
        "round": round_number,
        "pack": selected_pack,
        "available_packs": available_packs,
        "objectives": objectives,
        "thresholds": thresholds,
        "status": "NO_OBSERVATIONS",
        "reason": "no observations exist for the requested round and pack",
        "predictive_service_authorized": False,
        "remaining_external_gates": list(_EXTERNAL_GATES),
        "summary": {
            "observed_configurations": 0,
            "configurations_meeting_objective_targets": 0,
            "distinct_models": 0,
            "distinct_serving_environments": 0,
            "observed_paired_edges": 0,
            "eligible_paired_edges": 0,
            "model_profiles_repeated_across_environments": 0,
        },
        "gates": [],
        "configurations": [],
        "paired_edges": [],
        "serving_environments": [],
        "environment_bridges": [],
    }
    if pack is None and len(available_packs) > 1:
        result["status"] = "PACK_REQUIRED"
        result["reason"] = "multiple pack fingerprints exist; select one exact pack"
        return result
    if selected_pack is None or selected_pack not in available_packs:
        return result

    rows = [row for row in round_rows if row["pack"] == selected_pack]
    identities = {}
    environment_by_configuration = {}
    bundles_by_configuration_objective = defaultdict(set)
    rows_by_bundle = defaultdict(dict)
    for row in rows:
        configuration = row["configuration"]
        identity = {key: row[key] for key in (
            "configuration", "model", "environment", "transport", "parameters",
            "public_metadata")}
        previous = identities.setdefault(configuration, identity)
        if previous != identity:
            raise ValueError("readiness configuration identity collision")
        environment = _environment_record(row)
        previous_environment = environment_by_configuration.setdefault(
            configuration, environment)
        if previous_environment != environment:
            raise ValueError("readiness configuration environment collision")
        previous_row = rows_by_bundle[row["bundle"]].setdefault(configuration, row)
        if previous_row != row:
            raise ValueError("duplicate readiness bundle observation")
        for objective in objectives:
            if row["metrics"][objective] is not None:
                bundles_by_configuration_objective[(configuration, objective)].add(
                    row["bundle"])

    configurations = []
    for configuration, identity in sorted(
            identities.items(), key=lambda item: (item[1]["model"].casefold(), item[0])):
        observed = {
            objective: len(bundles_by_configuration_objective[(configuration, objective)])
            for objective in objectives
        }
        deficits = {
            objective: max(0, target_bundles - count)
            for objective, count in observed.items()
        }
        configurations.append({
            **identity,
            "serving_environment_id": environment_by_configuration[
                configuration]["environment_id"],
            "observed_independent_bundles": observed,
            "bundle_deficits": deficits,
            "meets_objective_targets": not any(deficits.values()),
        })

    shared_by_pair = defaultdict(lambda: {objective: 0 for objective in objectives})
    for bundle_rows in rows_by_bundle.values():
        configuration_ids = sorted(bundle_rows)
        for left_index, left in enumerate(configuration_ids):
            for right in configuration_ids[left_index + 1:]:
                for objective in objectives:
                    if (bundle_rows[left]["metrics"][objective] is not None
                            and bundle_rows[right]["metrics"][objective] is not None):
                        shared_by_pair[(left, right)][objective] += 1
    paired_edges = []
    for (left, right), shared in shared_by_pair.items():
        paired_edges.append({
            "left_configuration": left,
            "right_configuration": right,
            "shared_independent_bundles": shared,
            "minimum_shared_selected_bundles": min(shared.values()),
            "eligible": all(
                count >= MIN_BASELINE_SUBMISSIONS for count in shared.values()),
        })
    paired_edges.sort(key=lambda row: (
        -row["minimum_shared_selected_bundles"], row["left_configuration"],
        row["right_configuration"]))

    environment_groups = defaultdict(lambda: {"configurations": set(), "models": set()})
    environment_records = {}
    model_names = set()
    profile_environments = defaultdict(set)
    profile_environment_bundles = defaultdict(set)
    profile_configurations = defaultdict(set)
    profile_records = {}
    profile_labels = {}
    for configuration, identity in identities.items():
        environment = environment_by_configuration[configuration]
        environment_id = environment["environment_id"]
        previous_environment = environment_records.setdefault(
            environment_id, environment)
        if previous_environment != environment:
            raise ValueError("serving environment ID collision")
        environment_groups[environment_id]["configurations"].add(configuration)
        environment_groups[environment_id]["models"].add(identity["model"])
        model_names.add(identity["model"].casefold())
        profile = _model_profile_record(identity)
        profile_id = profile["model_profile_id"]
        previous_profile = profile_records.setdefault(profile_id, profile)
        if previous_profile != profile:
            raise ValueError("model profile ID collision")
        profile_labels.setdefault(profile_id, identity["model"])
        profile_environments[profile_id].add(environment_id)
        profile_configurations[profile_id].add(configuration)
    for row in rows:
        profile_id = _model_profile_record(row)["model_profile_id"]
        environment_id = environment_by_configuration[
            row["configuration"]]["environment_id"]
        profile_environment_bundles[(profile_id, environment_id)].add(row["bundle"])
    serving_environments = [{
        **environment_records[environment_id],
        "observed_configurations": len(group["configurations"]),
        "observed_models": len(group["models"]),
    } for environment_id, group in sorted(environment_groups.items())]
    environment_bridges = []
    for profile_id, environments in sorted(profile_environments.items()):
        qualified = [{
            "serving_environment_id": environment_id,
            "independent_bundles": len(
                profile_environment_bundles[(profile_id, environment_id)]),
        } for environment_id in sorted(environments)
            if len(profile_environment_bundles[(profile_id, environment_id)])
            >= MIN_BASELINE_SUBMISSIONS]
        if len(qualified) < 2:
            continue
        qualified_ids = {
            row["serving_environment_id"] for row in qualified}
        environment_bridges.append({
            "model": profile_labels[profile_id],
            "model_profile_id": profile_id,
            "transport": profile_records[profile_id]["transport"],
            "parameters": profile_records[profile_id]["parameters"],
            "model_metadata": profile_records[profile_id]["model_metadata"],
            "serving_environments": qualified,
            "observed_environments": len(qualified),
            "observed_configurations": sum(
                environment_by_configuration[configuration]["environment_id"]
                in qualified_ids
                for configuration in profile_configurations[profile_id]),
        })

    ready_configurations = sum(
        row["meets_objective_targets"] for row in configurations)
    eligible_edges = sum(row["eligible"] for row in paired_edges)
    summary = {
        "observed_configurations": len(configurations),
        "configurations_meeting_objective_targets": ready_configurations,
        "distinct_models": len(model_names),
        "distinct_serving_environments": len(serving_environments),
        "observed_paired_edges": len(paired_edges),
        "eligible_paired_edges": eligible_edges,
        "model_profiles_repeated_across_environments": len(environment_bridges),
    }
    gates = [
        _gate(
            "independent_objective_coverage",
            "PASS" if ready_configurations >= minimum_configurations else "GAP",
            ready_configurations, minimum_configurations,
            "configurations meeting every selected objective bundle target"),
        _gate(
            "configuration_diversity",
            "PASS" if len(configurations) >= minimum_configurations else "GAP",
            len(configurations), minimum_configurations,
            "distinct exact public configurations; material relevance needs review"),
        _gate(
            "serving_environment_diversity",
            "PASS" if len(serving_environments) >= minimum_environments else "GAP",
            len(serving_environments), minimum_environments,
            "distinct declared serving environments"),
        _gate(
            "paired_configuration_overlap",
            "PASS" if eligible_edges >= minimum_paired_edges else "GAP",
            eligible_edges, minimum_paired_edges,
            "configuration pairs meeting five shared bundles for every objective"),
        _gate(
            "cross_environment_model_repetition",
            "PASS" if len(environment_bridges) >= minimum_environment_bridges else "GAP",
            len(environment_bridges), minimum_environment_bridges,
            "exact model profiles with five independent bundles in at least two environments"),
        _gate(
            "temporal_holdout_validation", "UNAVAILABLE", False, True,
            "public schema has no collection timestamp or pre-registered temporal split"),
        _gate(
            "abuse_duplicate_and_implausibility_review", "REQUIRED", False, True,
            "structural validation cannot replace maintainer review of submitted evidence"),
        _gate(
            "pack_and_server_drift_monitoring", "REQUIRED", False, True,
            "one selected pack snapshot cannot establish future calibration stability"),
    ]
    design_gaps = [row for row in gates[:5] if row["status"] != "PASS"]
    result.update({
        "status": ("EVIDENCE_GAPS" if design_gaps
                   else "DESIGN_TARGET_MET_VALIDATION_REQUIRED"),
        "reason": (
            "one or more observable evidence-design gates are not met"
            if design_gaps else
            "observable design targets are met, but external validation gates remain"),
        "summary": summary,
        "gates": gates,
        "configurations": configurations,
        "paired_edges": paired_edges,
        "serving_environments": serving_environments,
        "environment_bridges": environment_bridges,
    })
    return result


def audit_submissions(submissions: list[dict], **kwargs) -> dict:
    return audit_prediction_readiness(_bundle_observations(submissions), **kwargs)


def render_prediction_readiness(result: dict) -> str:
    summary = result["summary"]
    lines = [
        "# Predictive Serving Readiness Audit", "",
        f"Status: **{result['status']}**", "", result["reason"], "",
        f"Predictive service authorized: **{str(result['predictive_service_authorized']).lower()}**",
        "",
        f"Round: **{result['round']}** · pack: "
        + (f"`{result['pack']}`" if result["pack"] else "not selected"), "",
        "Objectives: " + ", ".join(result["objectives"]), "",
        f"Configurations: **{summary['observed_configurations']}** · meeting targets: "
        f"**{summary['configurations_meeting_objective_targets']}** · environments: "
        f"**{summary['distinct_serving_environments']}** · eligible paired edges: "
        f"**{summary['eligible_paired_edges']}** · cross-environment models: "
        f"**{summary['model_profiles_repeated_across_environments']}**", "",
    ]
    if result["gates"]:
        lines += [
            "## Promotion gates", "",
            "| Gate | Status | Current | Required | Reason |",
            "|---|---|---:|---:|---|",
        ]
        for gate in result["gates"]:
            lines.append(
                f"| `{gate['name']}` | {gate['status']} | {gate['current']} | "
                f"{gate['required']} | {_cell(gate['reason'])} |")
    if result["configurations"]:
        lines += [
            "", "## Configuration coverage", "",
            "| Model | Config | Serving environment | Observed | Deficits | Target met |",
            "|---|---|---|---|---|---|",
        ]
        for row in result["configurations"]:
            lines.append(
                f"| {_cell(row['model'])} | `{row['configuration']}` | "
                f"`{row['serving_environment_id']}` · "
                f"{_configuration_summary(row).replace('|', chr(92) + '|')} | `"
                f"{json.dumps(row['observed_independent_bundles'], sort_keys=True)}` | `"
                f"{json.dumps(row['bundle_deficits'], sort_keys=True)}` | "
                f"{row['meets_objective_targets']} |")
    if result["paired_edges"]:
        lines += [
            "", "## Paired overlap", "",
            "| Configurations | Shared bundles by objective | Minimum | Eligible |",
            "|---|---|---:|---|",
        ]
        for row in result["paired_edges"]:
            lines.append(
                f"| `{row['left_configuration']}` ↔ `{row['right_configuration']}` | `"
                f"{json.dumps(row['shared_independent_bundles'], sort_keys=True)}` | "
                f"{row['minimum_shared_selected_bundles']} | {row['eligible']} |")
    if result["environment_bridges"]:
        lines += [
            "", "## Cross-environment model profiles", "",
            "| Model | Profile | Transport | Environments and bundles |",
            "|---|---|---|---|",
        ]
        for row in result["environment_bridges"]:
            environments = ", ".join(
                f"`{item['serving_environment_id']}`={item['independent_bundles']}"
                for item in row["serving_environments"])
            lines.append(
                f"| {_cell(row['model'])} | `{row['model_profile_id']}` | "
                f"{row['transport']} | {environments} |")
    lines += [
        "", "## Interpretation", "",
        "Passing observable design targets does not authorize a predictive service.",
        "This audit never fits a model or estimates an unobserved configuration. Public",
        "evidence still requires a pre-registered temporal holdout, maintainer abuse and",
        "implausibility review, and drift monitoring across future pack/server versions.",
        "Thresholds are operator planning targets, not universal scientific guarantees.",
        "Repeated rows inside one bundle cannot increase coverage or paired overlap, and",
        "the response exposes no contributing bundle IDs or contributor history.", "",
    ]
    if result["status"] == "PACK_REQUIRED":
        lines += ["Available packs:", ""] + [
            f"- `{value}`" for value in result["available_packs"]] + [""]
    return "\n".join(lines)
