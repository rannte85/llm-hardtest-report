from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from .github_submit import submission_relative_path
from .public_pilots import load_public_pilot_bundle
from .public_results import load_public_bundle


MIN_BASELINE_SUBMISSIONS = 5


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
        "infrastructure_errors": 0,
    })
    for payload in submissions:
        bundle_groups = set()
        for model in payload["models"]:
            configuration = _configuration_id(payload, model)
            for round_number, metrics in model["rounds"].items():
                pack = payload["benchmark"]["packs"][round_number]
                key = (int(round_number), pack, model["public_name"], configuration)
                group = groups[key]
                if key not in bundle_groups:
                    group["submissions"] += 1
                    bundle_groups.add(key)
                group["runs"] += 1
                for field in ("passed", "total", "incomplete", "infrastructure_errors"):
                    value = metrics.get(field)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        group[field] += value
    rows = []
    for (round_number, pack, model_name, configuration), totals in sorted(
            groups.items(), key=lambda item: (item[0][0], item[0][2].lower(), item[0][3])):
        rows.append({
            "round": round_number,
            "pack": pack,
            "model": model_name,
            "configuration": configuration,
            **totals,
        })
    return rows


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


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
        "| Round | Pack | Public model | Config | Bundles | Observed score | Completion | Baseline |",
        "|---:|---|---|---|---:|---:|---:|---|",
    ]
    for row in rows:
        total = row["total"]
        passed = row["passed"]
        attempted = total + row["incomplete"] + row["infrastructure_errors"]
        score = f"{passed:g}/{total:g}" if total else "n/a"
        completion = f"{(100 * total / attempted):.1f}%" if attempted else "n/a"
        baseline = (f"{(100 * passed / total):.1f}% observed"
                    if row["submissions"] >= MIN_BASELINE_SUBMISSIONS and total else
                    f"withheld (<{MIN_BASELINE_SUBMISSIONS} bundles)")
        lines.append(
            f"| {row['round']} | `{row['pack'][7:19]}` | {_cell(row['model'])} | "
            f"`{row['configuration']}` | {row['submissions']} | {score} | {completion} | {baseline} |")
    lines += [
        "",
        f"Baselines appear only after at least {MIN_BASELINE_SUBMISSIONS} distinct accepted bundles",
        "share the exact public configuration and pack. Duplicate model entries inside one",
        "bundle cannot raise this threshold. The values are descriptive observations,",
        "not predictions for an unseen model or a different runtime configuration.",
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
        bundle_groups = set()
        for model in payload["models"]:
            configuration = _configuration_id(payload, model)
            key = (payload["pilot"]["id"], payload["pilot"]["pack"],
                   model["public_name"], configuration)
            group = groups[key]
            if key not in bundle_groups:
                group["submissions"] += 1
                bundle_groups.add(key)
            for attempt in model["attempts"]:
                group["attempts"] += 1
                group["complete"] += attempt["status"] == "COMPLETE"
                group["public_passed"] += attempt["public"]["passed"]
                group["public_total"] += attempt["public"]["total"]
                group["hidden_passed"] += attempt["hidden"]["passed"]
                group["hidden_total"] += attempt["hidden"]["total"]
                group["evidence_revision"] += attempt["evidence_revision_observed"]
                group["release_ready"] += attempt["release_ready"]
                group["report_accurate"] += attempt["report_accurate"]
                group["authority_violations"] += not attempt["no_edit_before_approval"]
                group["protocol_error_attempts"] += not attempt["tool_protocol_clean"]
                group["unsupported_tool_calls"] += attempt["unsupported_tool_calls"]
    rows = []
    for (pilot, pack, model, configuration), totals in sorted(
            groups.items(), key=lambda item: (item[0][0], item[0][2].lower(), item[0][3])):
        rows.append({"pilot": pilot, "pack": pack, "model": model,
                     "configuration": configuration, **totals})
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
        baseline = ("observed" if row["submissions"] >= MIN_BASELINE_SUBMISSIONS
                    else f"withheld (<{MIN_BASELINE_SUBMISSIONS} bundles)")
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
        f"Baselines are labeled observed only after at least {MIN_BASELINE_SUBMISSIONS} distinct",
        "accepted bundles share the exact public configuration and pack. Duplicate model",
        "entries within one bundle cannot raise the threshold. A 0/0 score is unobserved,",
        "not a failure.",
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
