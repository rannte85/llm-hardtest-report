from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict

from .calibration import BOOTSTRAP_SAMPLES, _HashSampler, _percentile
from .community_results import (
    CONFIGURATION_ID, MIN_BASELINE_SUBMISSIONS, PACK_FINGERPRINT,
    RECOMMENDATION_OBJECTIVES, _cell, _configuration_id,
)
from .public_results import normalized_serving_environment


PAIRED_COMPARISON_SCHEMA_VERSION = 5
SIGN_FLIP_EXACT_LIMIT = 65_536
SIGN_FLIP_MONTE_CARLO_SAMPLES = 20_000
SIGN_FLIP_ABSOLUTE_TOLERANCE = 1e-12
FAMILYWISE_ALPHA = 0.05
MIN_EXPECTED_BOOTSTRAP_TAIL_DRAWS = 100


def _bundle_observations(submissions: list[dict]) -> list[dict]:
    """Collapse repeated rows inside each public bundle to one configuration unit."""
    groups = defaultdict(lambda: {
        "passed": 0.0, "total": 0.0, "incomplete": 0.0,
        "manual_review": 0.0, "infrastructure_errors": 0.0,
        "walls": [], "token_rates": [],
    })
    identities = {}
    for payload in submissions:
        for model in payload["models"]:
            configuration = _configuration_id(payload, model)
            identity = {
                "configuration": configuration,
                "model": model["public_name"],
                "environment": payload["environment"],
                "serving_environment": normalized_serving_environment(payload, model),
                "transport": model["transport"],
                "parameters": model["parameters"],
                "public_metadata": model["public_metadata"],
            }
            previous = identities.setdefault(configuration, identity)
            if previous != identity:
                raise ValueError("public configuration ID collision")
            for round_text, metrics in model["rounds"].items():
                round_number = int(round_text)
                pack = payload["benchmark"]["packs"][round_text]
                group = groups[(payload["bundle_id"], round_number, pack, configuration)]
                score_fields = (("release_ready", "attempts")
                                if round_text == "4" else ("passed", "total"))
                for target, source in zip(("passed", "total"), score_fields):
                    value = metrics.get(source)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        group[target] += float(value)
                for field in ("incomplete", "manual_review", "infrastructure_errors"):
                    value = metrics.get(field)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        group[field] += float(value)
                for item in metrics.get("items", []):
                    wall, tokens = item.get("wall_seconds"), item.get("tokens")
                    if isinstance(wall, (int, float)) and not isinstance(wall, bool):
                        group["walls"].append(float(wall))
                        if (wall > 0 and isinstance(tokens, int)
                                and not isinstance(tokens, bool)):
                            group["token_rates"].append(tokens / wall)
    observations = []
    for (bundle, round_number, pack, configuration), group in sorted(groups.items()):
        attempted = (group["total"] + group["incomplete"]
                     + group["manual_review"] + group["infrastructure_errors"])
        observations.append({
            "bundle": bundle,
            "round": round_number,
            "pack": pack,
            **identities[configuration],
            "metrics": {
                "accuracy": (group["passed"] / group["total"]
                             if group["total"] > 0 else None),
                "completion": (group["total"] / attempted if attempted > 0 else None),
                "latency": (statistics.mean(group["walls"])
                            if group["walls"] else None),
                "throughput": (statistics.mean(group["token_rates"])
                               if group["token_rates"] else None),
            },
        })
    return observations


def _sign_flip_test(effects: list[float], seed: str) -> dict:
    observed = abs(statistics.mean(effects))
    assignments = 2 ** len(effects)
    tolerance = SIGN_FLIP_ABSOLUTE_TOLERANCE
    extreme = 0
    if assignments <= SIGN_FLIP_EXACT_LIMIT:
        evaluated = assignments
        for mask in range(assignments):
            value = statistics.mean(
                effect if mask & (1 << index) else -effect
                for index, effect in enumerate(effects))
            extreme += abs(value) + tolerance >= observed
        p_value = extreme / evaluated
        method = "exact_paired_sign_flip_two_sided"
    else:
        evaluated = SIGN_FLIP_MONTE_CARLO_SAMPLES
        generator = _HashSampler(seed)
        for _ in range(evaluated):
            value = statistics.mean(
                effect if generator.choice([False, True]) else -effect
                for effect in effects)
            extreme += abs(value) + tolerance >= observed
        p_value = (extreme + 1) / (evaluated + 1)
        method = "deterministic_monte_carlo_paired_sign_flip_two_sided"
    return {
        "p_value": min(1.0, math.ceil(p_value * 100_000_000) / 100_000_000),
        "method": method,
        "assignments": assignments,
        "evaluated_permutations": evaluated,
        "extreme_permutations": extreme,
    }


def _bootstrap_sample_count(family_size: int) -> int:
    if family_size <= 0:
        return 0
    return max(
        BOOTSTRAP_SAMPLES,
        math.ceil(
            2 * family_size * MIN_EXPECTED_BOOTSTRAP_TAIL_DRAWS
            / FAMILYWISE_ALPHA),
    )


def _minimum_nonzero_pairs_for_holm(family_size: int) -> int:
    """Return the exact-test resolution needed at Holm's strictest rank."""
    if family_size <= 0:
        return 0
    nonzero_pairs = 0
    while min(1.0, 2.0 ** (1 - nonzero_pairs)) * family_size \
            >= FAMILYWISE_ALPHA:
        nonzero_pairs += 1
    return nonzero_pairs


def _inference_resolution(effects: list[float], family_size: int) -> dict:
    """Audit the best attainable exact sign-flip resolution without claiming power."""
    # A single sign reversal must move the mean beyond the test's absolute tolerance;
    # ignoring smaller effects is conservative when several could accumulate.
    nonzero_tolerance = SIGN_FLIP_ABSOLUTE_TOLERANCE * len(effects) / 2
    nonzero_pairs = sum(abs(effect) > nonzero_tolerance for effect in effects)
    raw_floor = min(1.0, 2.0 ** (1 - nonzero_pairs))
    holm_floor = min(1.0, raw_floor * family_size)
    required = _minimum_nonzero_pairs_for_holm(family_size)
    additional = max(0, required - nonzero_pairs)
    return {
        "status": ("RESOLUTION_AVAILABLE" if additional == 0
                   else "DISCRETE_P_LIMIT"),
        "nonzero_effect_tolerance": nonzero_tolerance,
        "nonzero_paired_bundles": nonzero_pairs,
        "best_case_raw_p_floor": raw_floor,
        "strictest_holm_multiplier": family_size,
        "best_case_strictest_holm_p_floor": holm_floor,
        "minimum_nonzero_pairs_for_strictest_holm": required,
        "additional_nonzero_pairs_for_strictest_holm": additional,
        "interpretation": (
            "best-case discrete resolution only; additional pairs assume independent "
            "non-zero effects and do not guarantee significance or practical importance"),
    }


def _paired_intervals(effects: list[float], seed: str,
                      family_size: int, samples: int) -> tuple[dict, dict]:
    """Return pointwise and Bonferroni-simultaneous paired intervals."""
    generator = _HashSampler(seed)
    draws = [statistics.mean(
        generator.choice(effects) for _ in effects)
        for _ in range(samples)]
    pointwise = {
        "low": round(_percentile(draws, 0.025), 6),
        "high": round(_percentile(draws, 0.975), 6),
        "method": "paired_bundle_cluster_bootstrap_95",
        "samples": samples,
    }
    tail_probability = FAMILYWISE_ALPHA / (2 * family_size)
    simultaneous = {
        "low": round(_percentile(draws, tail_probability), 6),
        "high": round(_percentile(draws, 1 - tail_probability), 6),
        "confidence": round(1 - FAMILYWISE_ALPHA / family_size, 8),
        "method": "paired_bundle_cluster_bootstrap_bonferroni_simultaneous",
        "samples": samples,
        "family_size": family_size,
        "expected_tail_draws": round(samples * tail_probability, 6),
    }
    return pointwise, simultaneous


def _holm_adjust(rows: list[dict]) -> None:
    tested = [row for row in rows if row["p_raw"] is not None]
    previous = 0.0
    for rank, row in enumerate(sorted(
            tested, key=lambda value: (value["p_raw"], value["objective"])), 1):
        adjusted = min(1.0, row["p_raw"] * (len(tested) - rank + 1))
        previous = max(previous, adjusted)
        row["p_holm"] = round(previous, 8)


def _minimum_effects(objectives: list[str], values: dict | None) -> dict[str, float]:
    """Validate objective-specific practical-effect floors."""
    if values is None:
        values = {}
    if not isinstance(values, dict) or any(not isinstance(key, str) for key in values):
        raise ValueError("comparison minimum effects must be an object")
    unknown = set(values) - set(objectives)
    if unknown:
        raise ValueError(
            "minimum effect supplied for unselected objective(s): "
            + ", ".join(sorted(unknown)))
    normalized = {}
    for objective in objectives:
        value = values.get(objective, 0.0)
        try:
            numeric = float(value)
        except (OverflowError, TypeError, ValueError):
            numeric = math.nan
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(numeric) or numeric < 0):
            raise ValueError(
                f"minimum {objective} effect must be a finite non-negative number")
        if objective in {"accuracy", "completion"} and numeric > 1:
            raise ValueError(f"minimum {objective} effect cannot exceed 1")
        normalized[objective] = numeric
    return normalized


def compare_paired_observations(observations: list[dict], *, round_number: int,
                                left_configuration: str,
                                right_configuration: str,
                                pack: str | None = None,
                                objectives: list[str] | None = None,
                                minimum_effects: dict | None = None) -> dict:
    """Compare two exact configurations only within shared independent bundles."""
    if isinstance(round_number, bool) or round_number not in {1, 2, 3, 4}:
        raise ValueError("comparison round must be one of 1, 2, 3, or 4")
    for label, value in (("left", left_configuration),
                         ("right", right_configuration)):
        if not isinstance(value, str) or CONFIGURATION_ID.fullmatch(value) is None:
            raise ValueError(f"{label} configuration must be an exact 10-character ID")
    if left_configuration == right_configuration:
        raise ValueError("paired comparison requires two distinct configurations")
    if pack is not None and (
            not isinstance(pack, str) or PACK_FINGERPRINT.fullmatch(pack) is None):
        raise ValueError("comparison pack must be an exact sha256 fingerprint")
    if isinstance(objectives, str):
        raise ValueError("comparison objectives must be a list")
    objectives = list(objectives or ["accuracy"])
    if (not objectives or len(objectives) != len(set(objectives))
            or set(objectives) - RECOMMENDATION_OBJECTIVES):
        raise ValueError("comparison objectives must be unique values from: "
                         + ", ".join(sorted(RECOMMENDATION_OBJECTIVES)))
    minimum_effects = _minimum_effects(objectives, minimum_effects)

    round_rows = [row for row in observations if row["round"] == round_number]
    available_packs = sorted({row["pack"] for row in round_rows})
    selected_pack = (pack if pack is not None
                     else available_packs[0] if len(available_packs) == 1 else None)
    result = {
        "schema_version": PAIRED_COMPARISON_SCHEMA_VERSION,
        "kind": "paired_serving_configuration_comparison",
        "round": round_number,
        "pack": selected_pack,
        "available_packs": available_packs,
        "left_configuration": left_configuration,
        "right_configuration": right_configuration,
        "objectives": objectives,
        "minimum_practical_effects": minimum_effects,
        "minimum_paired_bundles": MIN_BASELINE_SUBMISSIONS,
        "multiplicity_method": (
            "holm_p_values_and_bonferroni_simultaneous_intervals_across_"
            "tested_objectives"),
        "familywise_alpha": FAMILYWISE_ALPHA,
        "bootstrap_sample_policy": "max(2000,4000*tested_objectives)",
        "bootstrap_samples": 0,
        "simultaneous_confidence": None,
        "minimum_nonzero_pairs_for_strictest_holm": 0,
        "resolution_limited_objectives": 0,
        "status": "NO_OBSERVATIONS",
        "reason": "no observations exist for the requested round and pack",
        "left": None,
        "right": None,
        "shared_configuration_bundles": 0,
        "tested_objectives": 0,
        "objectives_result": [],
    }
    if pack is None and len(available_packs) > 1:
        result["status"] = "PACK_REQUIRED"
        result["reason"] = "multiple pack fingerprints exist; select one exact pack"
        return result
    if selected_pack is None or selected_pack not in available_packs:
        return result
    rows = [row for row in round_rows if row["pack"] == selected_pack]
    identities = {}
    for row in rows:
        identity = {key: row[key] for key in (
            "configuration", "model", "environment", "serving_environment",
            "transport", "parameters",
            "public_metadata")}
        previous = identities.setdefault(row["configuration"], identity)
        if previous != identity:
            raise ValueError("paired comparison configuration identity collision")
    if left_configuration not in identities or right_configuration not in identities:
        result["status"] = "NO_MATCH"
        result["reason"] = "one or both exact configurations are not observed on the selected pack"
        return result
    result["left"] = identities[left_configuration]
    result["right"] = identities[right_configuration]
    by_bundle = defaultdict(dict)
    for row in rows:
        if row["configuration"] in {left_configuration, right_configuration}:
            previous = by_bundle[row["bundle"]].setdefault(row["configuration"], row)
            if previous != row:
                raise ValueError("duplicate paired bundle observation")
    shared = [pair for pair in by_bundle.values() if len(pair) == 2]
    result["shared_configuration_bundles"] = len(shared)

    objective_rows = []
    effects_by_objective = {}
    for objective in objectives:
        pairs = [
            (pair[left_configuration]["metrics"][objective],
             pair[right_configuration]["metrics"][objective])
            for pair in shared
            if (pair[left_configuration]["metrics"][objective] is not None
                and pair[right_configuration]["metrics"][objective] is not None)
        ]
        left_values = [float(left) for left, _ in pairs]
        right_values = [float(right) for _, right in pairs]
        if objective == "latency":
            effects = [right - left for left, right in pairs]
            effect_definition = "right_minus_left_seconds_positive_favors_left"
            unit = "seconds"
        else:
            effects = [left - right for left, right in pairs]
            effect_definition = "left_minus_right_positive_favors_left"
            unit = "rate" if objective in {"accuracy", "completion"} else "tokens_per_second"
        row = {
            "objective": objective,
            "unit": unit,
            "effect_definition": effect_definition,
            "paired_bundles": len(pairs),
            "left_mean": round(statistics.mean(left_values), 6) if left_values else None,
            "right_mean": round(statistics.mean(right_values), 6) if right_values else None,
            "left_advantage": round(statistics.mean(effects), 6) if effects else None,
            "minimum_practical_effect": minimum_effects[objective],
            "interval95": None,
            "simultaneous_interval": None,
            "inference_resolution": None,
            "p_raw": None,
            "p_holm": None,
            "test": None,
            "practical_threshold_met": None,
            "classification": "INSUFFICIENT",
        }
        if len(effects) >= MIN_BASELINE_SUBMISSIONS:
            effects_by_objective[objective] = effects
            row["classification"] = "PENDING"
        objective_rows.append(row)
    tested_objectives = len(effects_by_objective)
    bootstrap_samples = _bootstrap_sample_count(tested_objectives)
    result["tested_objectives"] = tested_objectives
    result["bootstrap_samples"] = bootstrap_samples
    result["simultaneous_confidence"] = (
        round(1 - FAMILYWISE_ALPHA / tested_objectives, 8)
        if tested_objectives else None)
    result["minimum_nonzero_pairs_for_strictest_holm"] = (
        _minimum_nonzero_pairs_for_holm(tested_objectives))
    configuration_pair = ":".join(sorted(
        (left_configuration, right_configuration)))
    for row in objective_rows:
        effects = effects_by_objective.get(row["objective"])
        if effects is None:
            continue
        seed = (f"paired:{selected_pack}:{round_number}:"
                f"{configuration_pair}:{row['objective']}")
        row["interval95"], row["simultaneous_interval"] = _paired_intervals(
            effects, seed, tested_objectives, bootstrap_samples)
        row["inference_resolution"] = _inference_resolution(
            effects, tested_objectives)
        row["test"] = _sign_flip_test(effects, seed)
        row["p_raw"] = row["test"]["p_value"]
    result["resolution_limited_objectives"] = sum(
        row["inference_resolution"] is not None
        and row["inference_resolution"]["status"] == "DISCRETE_P_LIMIT"
        for row in objective_rows)
    _holm_adjust(objective_rows)
    for row in objective_rows:
        if row["classification"] == "INSUFFICIENT":
            continue
        interval = row["interval95"]
        simultaneous_interval = row["simultaneous_interval"]
        threshold = row["minimum_practical_effect"]
        left_threshold_met = (
            interval["low"] > 0 if threshold == 0
            else simultaneous_interval["low"] > threshold)
        right_threshold_met = (
            interval["high"] < 0 if threshold == 0
            else simultaneous_interval["high"] < -threshold)
        if row["p_holm"] < FAMILYWISE_ALPHA and left_threshold_met:
            row["practical_threshold_met"] = True
            row["classification"] = "LEFT_BETTER"
        elif row["p_holm"] < FAMILYWISE_ALPHA and right_threshold_met:
            row["practical_threshold_met"] = True
            row["classification"] = "RIGHT_BETTER"
        elif row["p_holm"] < FAMILYWISE_ALPHA and interval["low"] > 0:
            row["practical_threshold_met"] = False
            row["classification"] = "LEFT_SMALL_EFFECT"
        elif row["p_holm"] < FAMILYWISE_ALPHA and interval["high"] < 0:
            row["practical_threshold_met"] = False
            row["classification"] = "RIGHT_SMALL_EFFECT"
        else:
            row["practical_threshold_met"] = False
            row["classification"] = "INCONCLUSIVE"
    result["objectives_result"] = objective_rows
    directions = {row["classification"] for row in objective_rows}
    decisive = directions & {"LEFT_BETTER", "RIGHT_BETTER"}
    statistical_only = directions & {"LEFT_SMALL_EFFECT", "RIGHT_SMALL_EFFECT"}
    if not result["tested_objectives"]:
        result["status"] = "INSUFFICIENT_EVIDENCE"
        result["reason"] = "no objective has five paired independent bundles"
    elif decisive == {"LEFT_BETTER"}:
        result["status"] = "LEFT_DIRECTIONAL_EVIDENCE"
        result["reason"] = "familywise-controlled paired evidence favors the left configuration"
    elif decisive == {"RIGHT_BETTER"}:
        result["status"] = "RIGHT_DIRECTIONAL_EVIDENCE"
        result["reason"] = "familywise-controlled paired evidence favors the right configuration"
    elif len(decisive) == 2:
        result["status"] = "MIXED_DIRECTIONAL_EVIDENCE"
        result["reason"] = "familywise-controlled paired objectives favor different configurations"
    elif statistical_only:
        result["status"] = "STATISTICAL_ONLY_EVIDENCE"
        result["reason"] = (
            "a Holm-controlled direction exists but its simultaneous interval does "
            "not clear the declared minimum practical effect")
    elif (result["tested_objectives"] > 0
          and result["resolution_limited_objectives"]
          == result["tested_objectives"]):
        result["status"] = "RESOLUTION_LIMITED"
        result["reason"] = (
            "every tested objective is below the conservative discrete p-value "
            "resolution needed at Holm's strictest rank")
    else:
        result["status"] = "INCONCLUSIVE"
        result["reason"] = "paired evidence is available but no selected objective is decisive"
    return result


def compare_submissions(submissions: list[dict], **kwargs) -> dict:
    return compare_paired_observations(_bundle_observations(submissions), **kwargs)


def render_paired_comparison(result: dict) -> str:
    lines = [
        "# Paired Serving Configuration Comparison", "",
        f"Status: **{result['status']}**", "", result["reason"], "",
        f"Round: **{result['round']}** · pack: "
        + (f"`{result['pack']}`" if result["pack"] else "not selected"), "",
        f"Left: `{result['left_configuration']}` · right: "
        f"`{result['right_configuration']}`", "",
        f"Shared configuration bundles: **{result['shared_configuration_bundles']}** · "
        f"tested objectives: **{result['tested_objectives']}**", "",
        f"Family-wise alpha: **{result['familywise_alpha']}** · simultaneous confidence: "
        f"**{result['simultaneous_confidence'] if result['simultaneous_confidence'] is not None else 'n/a'}** · "
        f"bootstrap samples: **{result['bootstrap_samples']}**", "",
        f"Strictest-rank Holm resolution: **{result['minimum_nonzero_pairs_for_strictest_holm']} "
        f"non-zero pairs** · resolution-limited objectives: "
        f"**{result['resolution_limited_objectives']}**", "",
    ]
    if result["left"] and result["right"]:
        lines += [
            f"Left model: **{_cell(result['left']['model'])}** · right model: "
            f"**{_cell(result['right']['model'])}**", "",
        ]
    if result["objectives_result"]:
        lines += [
            "| Objective | Paired bundles | Left mean | Right mean | Left advantage | Minimum practical effect | 95% interval | Simultaneous interval | Raw p | Holm p | Resolution | Result |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
        ]
        for row in result["objectives_result"]:
            interval = row["interval95"]
            rendered_interval = (f"[{interval['low']}, {interval['high']}]"
                                 if interval else "n/a")
            simultaneous = row["simultaneous_interval"]
            rendered_simultaneous = (
                f"[{simultaneous['low']}, {simultaneous['high']}]"
                if simultaneous else "n/a")
            resolution = row["inference_resolution"]
            rendered_resolution = (
                f"{resolution['status']} (+{resolution['additional_nonzero_pairs_for_strictest_holm']})"
                if resolution else "n/a")
            lines.append(
                f"| {row['objective']} | {row['paired_bundles']} | "
                f"{row['left_mean'] if row['left_mean'] is not None else 'n/a'} | "
                f"{row['right_mean'] if row['right_mean'] is not None else 'n/a'} | "
                f"{row['left_advantage'] if row['left_advantage'] is not None else 'n/a'} "
                f"{row['unit']} | {row['minimum_practical_effect']} {row['unit']} | "
                f"{rendered_interval} | {rendered_simultaneous} | "
                f"{row['p_raw'] if row['p_raw'] is not None else 'n/a'} | "
                f"{row['p_holm'] if row['p_holm'] is not None else 'n/a'} | "
                f"{rendered_resolution} | "
                f"{row['classification']} |")
    lines += [
        "", "## Interpretation", "",
        "Only bundles containing both exact configurations contribute to an objective.",
        "Repeated runs inside one bundle are collapsed before pairing. Positive left",
        "advantage always favors the left configuration; latency uses right minus left",
        "seconds so lower latency remains better. Directional claims require both a",
        "Bonferroni simultaneous paired-cluster bootstrap interval clearing the declared",
        "non-zero objective-specific minimum practical effect and Holm-adjusted p < 0.05.",
        "A zero floor retains the Holm-controlled historical non-zero rule.",
        "The resolution audit reports the best exact sign-flip p-value attainable from",
        "pairs beyond its disclosed numerical effect tolerance at Holm's strictest rank.",
        "Its additional-pair count",
        "is a conservative design floor, not a power calculation or a promise of significance.",
        "Bootstrap samples scale with the tested-objective family to retain at least",
        "100 expected draws in each adjusted tail. `LEFT_SMALL_EFFECT` and",
        "`RIGHT_SMALL_EFFECT` retain a statistical direction without promoting a change",
        "that misses the declared operational floor. This is not a",
        "prediction for an untested model, pack, environment, or serving setting.", "",
    ]
    if result["status"] == "PACK_REQUIRED":
        lines += ["Available packs:", ""] + [
            f"- `{value}`" for value in result["available_packs"]] + [""]
    return "\n".join(lines)
