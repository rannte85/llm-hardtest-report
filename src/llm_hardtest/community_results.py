from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from .github_submit import submission_relative_path
from .public_results import load_public_bundle


MIN_BASELINE_RUNS = 5


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
        "runs": 0, "passed": 0, "total": 0, "incomplete": 0,
        "infrastructure_errors": 0,
    })
    for payload in submissions:
        for model in payload["models"]:
            configuration = _configuration_id(payload, model)
            for round_number, metrics in model["rounds"].items():
                pack = payload["benchmark"]["packs"][round_number]
                key = (int(round_number), pack, model["public_name"], configuration)
                group = groups[key]
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
        "| Round | Pack | Public model | Config | Runs | Observed score | Completion | Baseline |",
        "|---:|---|---|---|---:|---:|---:|---|",
    ]
    for row in rows:
        total = row["total"]
        passed = row["passed"]
        attempted = total + row["incomplete"] + row["infrastructure_errors"]
        score = f"{passed:g}/{total:g}" if total else "n/a"
        completion = f"{(100 * total / attempted):.1f}%" if attempted else "n/a"
        baseline = (f"{(100 * passed / total):.1f}% observed"
                    if row["runs"] >= MIN_BASELINE_RUNS and total else
                    f"withheld (<{MIN_BASELINE_RUNS} runs)")
        lines.append(
            f"| {row['round']} | `{row['pack'][7:19]}` | {_cell(row['model'])} | "
            f"`{row['configuration']}` | {row['runs']} | {score} | {completion} | {baseline} |")
    lines += [
        "",
        f"Baselines appear only after at least {MIN_BASELINE_RUNS} independently submitted runs",
        "share the exact public configuration and pack. They are descriptive observations,",
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
