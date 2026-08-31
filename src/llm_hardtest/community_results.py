from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

from .calibration import (
    _configuration_item_coverage, _estimate_interval, _item_metrics, _item_relationships,
    _item_repeat_separation, _pairwise_stability,
)
from .github_submit import submission_relative_path
from .public_pilots import load_public_pilot_bundle
from .public_results import load_public_bundle


MIN_BASELINE_SUBMISSIONS = 5


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
    if not directory.is_dir():
        raise ValueError(f"submission directory does not exist: {directory}")
    submissions = []
    seen = set()
    for path in sorted(directory.iterdir()):
        if path.name == ".gitkeep":
            continue
        if not path.is_file() or path.suffix.lower() != ".json":
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
        "environment": payload["environment"],
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
    for payload in submissions:
        bundle_groups = defaultdict(lambda: {
            "runs": 0, "passed": 0, "total": 0, "incomplete": 0,
            "manual_review": 0, "infrastructure_errors": 0,
            "_item_walls": [], "_token_rates": [],
        })
        for model in payload["models"]:
            configuration = _configuration_id(payload, model)
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
            **{key: value for key, value in totals.items() if not key.startswith("_")},
            "observed_submissions": len(rates),
            "bundle_pass_rate_interval95": _cluster_interval(rates),
            "bundle_item_wall_p50_seconds": _percentile(
                totals.get("_bundle_mean_walls", []), 0.5),
            "bundle_item_wall_p90_seconds": _percentile(
                totals.get("_bundle_mean_walls", []), 0.9),
            "bundle_tokens_per_second_p50": _percentile(
                totals.get("_bundle_mean_token_rates", []), 0.5),
        })
    return rows


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
        rows.append({
            "round": round_number,
            "pack": pack,
            "bundles": len(group["bundles"]),
            "respondents": len(group["matrix"]),
            "configurations": len(set(group["models"].values())),
            "pairwise": _pairwise_stability(group["matrix"], group["models"]),
            "items": _item_metrics(group["matrix"], group["clusters"]),
            "item_relationships": _item_relationships(
                group["matrix"], group["clusters"]),
            "item_repeat_separation": _item_repeat_separation(
                group["matrix"], group["models"], group["clusters"]),
            "configuration_item_coverage": _configuration_item_coverage(
                group["matrix"], group["models"],
                {identity: identity for identity in set(group["models"].values())},
                group["clusters"]),
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
        "for an unseen model or a different runtime configuration.",
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
    if not directory.is_dir():
        raise ValueError(f"pilot submission directory does not exist: {directory}")
    submissions = []
    seen = set()
    for path in sorted(directory.iterdir()):
        if path.name == ".gitkeep":
            continue
        if not path.is_file() or path.suffix.lower() != ".json":
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
