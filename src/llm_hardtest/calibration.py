from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from collections import defaultdict
from itertools import combinations
from pathlib import Path

from .common import load_json, slug
from .results import item_status


SCORED = {"PASS", "FAIL"}
MIN_ITEM_OBSERVATIONS = 5
MIN_PAIR_ITEMS = 2


def _model_identity(model: dict) -> str:
    public = {key: value for key, value in model.items()
              if key not in {"key", "label", "public_name", "item_filters"}}
    encoded = json.dumps(public, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_model_root(run_dir: Path, key: object) -> Path:
    if (not isinstance(key, str) or key in {"", ".", ".."}
            or slug(key) != key or Path(key).name != key):
        raise ValueError(f"unsafe model key in saved config: {key!r}")
    root = (run_dir / key).resolve()
    try:
        root.relative_to(run_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"model path escapes run directory: {key!r}") from exc
    return root


def _safe_evidence_file(path: Path, run_dir: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(run_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"evidence file escapes run directory: {path}") from exc
    if not resolved.is_file():
        raise ValueError(f"missing evidence file: {path}")
    return resolved


def _record(matrix: dict, respondent: tuple, item: str, status: str) -> None:
    if status not in {"PASS", "FAIL", "INCOMPLETE", "REVIEW", "INVALID"}:
        raise ValueError(f"unsupported item status: {status}")
    previous = matrix[respondent].get(item)
    if previous is not None and previous != status:
        raise ValueError(f"duplicate conflicting result for {item}")
    matrix[respondent][item] = status


def collect_observations(run_dirs: list[Path]) -> dict[tuple[int, str], dict]:
    """Collect status-only observations without copying prompts or model responses."""
    canonical_runs = [path.resolve() for path in run_dirs]
    if len(canonical_runs) != len(set(canonical_runs)):
        raise ValueError("the same run directory cannot be analyzed more than once")
    groups = defaultdict(lambda: {"matrix": defaultdict(dict), "models": {}})
    for run_index, run_dir in enumerate(run_dirs, 1):
        config_path = run_dir / "config.json"
        summary_path = run_dir / "summary.json"
        if not config_path.is_file() or not summary_path.is_file():
            raise ValueError(f"analysis requires config.json and summary.json: {run_dir}")
        config = load_json(_safe_evidence_file(config_path, run_dir))
        summary = load_json(_safe_evidence_file(summary_path, run_dir))
        packs = summary.get("packs")
        if not isinstance(packs, dict):
            raise ValueError(f"saved summary has no pack fingerprints: {run_dir}")
        if any(not isinstance(value, str)
               or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None
               for value in packs.values()):
            raise ValueError(f"saved summary has invalid pack fingerprints: {run_dir}")
        for model_index, model in enumerate(config.get("models", []), 1):
            if not isinstance(model, dict):
                raise ValueError(f"invalid saved model config in {run_dir}")
            key = model.get("key")
            model_root = _safe_model_root(run_dir, key)
            identity = _model_identity(model)
            for round_number in (1, 2, 3):
                round_text = str(round_number)
                paths = sorted((model_root / f"round{round_number}").glob(
                    "attempt-*/result.json"))
                if paths and round_text not in packs:
                    raise ValueError(
                        f"round {round_number} results lack a saved pack fingerprint")
                for path in paths:
                    payload = load_json(_safe_evidence_file(path, run_dir))
                    attempt = payload.get("attempt") or path.parent.name.removeprefix("attempt-")
                    respondent = (run_index, model_index, str(attempt))
                    group = groups[(round_number, packs[round_text])]
                    group["models"][respondent] = identity
                    for row in payload.get("results", []):
                        if not isinstance(row, dict) or row.get("id") is None:
                            raise ValueError(f"invalid item row in {path}")
                        _record(group["matrix"], respondent, f"q{row['id']}",
                                item_status(row))
            round4_path = model_root / "round4" / "run.json"
            if not round4_path.is_file():
                continue
            if "4" not in packs:
                raise ValueError("round 4 results lack a saved pack fingerprint")
            payload = load_json(_safe_evidence_file(round4_path, run_dir))
            group = groups[(4, packs["4"])]
            graded = set()
            for grade in payload.get("grades", []):
                item = grade.get("task", grade.get("qid"))
                attempt = (grade.get("run_meta") or {}).get("attempt")
                if not isinstance(item, str) or attempt is None:
                    raise ValueError(f"invalid Round 4 grade in {round4_path}")
                respondent = (run_index, model_index, str(attempt))
                group["models"][respondent] = identity
                flags = grade.get("flags") or {}
                status = ("INVALID" if flags.get("model_timed_out") else
                          "PASS" if flags.get("attempt_pass") else "FAIL")
                _record(group["matrix"], respondent, item, status)
                graded.add((item, str(attempt)))
            for error in payload.get("errors", []):
                item, attempt = error.get("task"), error.get("attempt")
                if not isinstance(item, str) or attempt is None:
                    continue
                if (item, str(attempt)) in graded:
                    continue
                respondent = (run_index, model_index, str(attempt))
                group["models"][respondent] = identity
                _record(group["matrix"], respondent, item, "INVALID")
    if not groups:
        raise ValueError("no item-level results were found in the selected runs")
    return groups


def _correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    mean_x, mean_y = statistics.mean(xs), statistics.mean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator = math.sqrt(
        sum((x - mean_x) ** 2 for x in xs)
        * sum((y - mean_y) ** 2 for y in ys))
    return numerator / denominator if denominator else None


def _item_metrics(matrix: dict) -> list[dict]:
    item_ids = sorted({item for rows in matrix.values() for item in rows})
    metrics = []
    for item in item_ids:
        counts = {status: 0 for status in
                  ("PASS", "FAIL", "INCOMPLETE", "REVIEW", "INVALID", "MISSING")}
        xs, rest_scores = [], []
        for rows in matrix.values():
            status = rows.get(item, "MISSING")
            counts[status] += 1
            if status not in SCORED:
                continue
            rest = [1.0 if value == "PASS" else 0.0
                    for other, value in rows.items()
                    if other != item and value in SCORED]
            if rest:
                xs.append(1.0 if status == "PASS" else 0.0)
                rest_scores.append(statistics.mean(rest))
        scored = counts["PASS"] + counts["FAIL"]
        pass_rate = counts["PASS"] / scored if scored else None
        discrimination = _correlation(xs, rest_scores)
        information = 4 * pass_rate * (1 - pass_rate) if pass_rate is not None else None
        if scored < MIN_ITEM_OBSERVATIONS:
            classification = "INSUFFICIENT"
        elif pass_rate >= 0.95:
            classification = "CEILING"
        elif pass_rate <= 0.05:
            classification = "FLOOR"
        elif discrimination is None:
            classification = "LOW_INFORMATION"
        elif discrimination < 0:
            classification = "NEGATIVE"
        elif discrimination < 0.15:
            classification = "WEAK"
        else:
            classification = "USEFUL"
        metrics.append({
            "item": item,
            "scored": scored,
            "pass": counts["PASS"],
            "fail": counts["FAIL"],
            "incomplete": counts["INCOMPLETE"],
            "review": counts["REVIEW"],
            "invalid": counts["INVALID"],
            "missing": counts["MISSING"],
            "pass_rate": round(pass_rate, 6) if pass_rate is not None else None,
            "difficulty_balance": round(information, 6) if information is not None else None,
            "corrected_item_total_correlation": (
                round(discrimination, 6) if discrimination is not None else None),
            "classification": classification,
        })
    def ranking(row: dict) -> tuple:
        discrimination = row["corrected_item_total_correlation"]
        information = row["difficulty_balance"]
        return (discrimination is None,
                -discrimination if discrimination is not None else 0,
                -information if information is not None else 0,
                row["item"])

    return sorted(metrics, key=ranking)


def _pairwise_stability(matrix: dict, models: dict) -> dict:
    buckets = {"between": [], "within": []}
    for left, right in combinations(sorted(matrix), 2):
        common = [item for item in set(matrix[left]) & set(matrix[right])
                  if matrix[left][item] in SCORED and matrix[right][item] in SCORED]
        if len(common) < MIN_PAIR_ITEMS:
            continue
        disagreement = sum(matrix[left][item] != matrix[right][item]
                           for item in common) / len(common)
        bucket = "within" if models[left] == models[right] else "between"
        buckets[bucket].append(disagreement)
    between = statistics.mean(buckets["between"]) if buckets["between"] else None
    within = statistics.mean(buckets["within"]) if buckets["within"] else None
    return {
        "between_configuration_pairs": len(buckets["between"]),
        "between_configuration_disagreement": (
            round(between, 6) if between is not None else None),
        "within_configuration_pairs": len(buckets["within"]),
        "within_configuration_disagreement": (
            round(within, 6) if within is not None else None),
        "net_separation": (round(between - within, 6)
                           if between is not None and within is not None else None),
    }


def analyze_runs(run_dirs: list[Path]) -> dict:
    groups = collect_observations(run_dirs)
    analyses = []
    for (round_number, pack), group in sorted(groups.items()):
        matrix = group["matrix"]
        analyses.append({
            "round": round_number,
            "pack": pack,
            "respondents": len(matrix),
            "model_configurations": len(set(group["models"].values())),
            "pairwise": _pairwise_stability(matrix, group["models"]),
            "items": _item_metrics(matrix),
        })
    return {"schema_version": 1, "source_runs": len(run_dirs), "groups": analyses}


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}%"


def render_analysis(analysis: dict) -> str:
    lines = [
        "# LLM Hardtest Calibration Analysis", "",
        f"Analyzed local run directories: **{analysis['source_runs']}**. Raw prompts, model",
        "responses, paths, model identifiers, and credentials are not copied into this report.",
        "Results are separated by exact benchmark pack fingerprint.", "",
    ]
    for group in analysis["groups"]:
        pairwise = group["pairwise"]
        lines += [
            f"## Round {group['round']} — `{group['pack']}`", "",
            f"Respondents: **{group['respondents']}**; distinct model configurations: "
            f"**{group['model_configurations']}**.", "",
            f"- Between-configuration disagreement: "
            f"{_percent(pairwise['between_configuration_disagreement'])} "
            f"across {pairwise['between_configuration_pairs']} comparable pair(s).",
            f"- Within-configuration repeat disagreement: "
            f"{_percent(pairwise['within_configuration_disagreement'])} "
            f"across {pairwise['within_configuration_pairs']} comparable pair(s).",
            f"- Net separation (between minus within): {_percent(pairwise['net_separation'])}.", "",
            "| Item | Scored | Pass rate | Difficulty balance | Corrected discrimination | "
            "Incomplete | Review | Invalid | Missing | Signal |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
        for item in group["items"]:
            discrimination = item["corrected_item_total_correlation"]
            lines.append(
                f"| {item['item']} | {item['scored']} | {_percent(item['pass_rate'])} | "
                f"{item['difficulty_balance'] if item['difficulty_balance'] is not None else 'n/a'} | "
                f"{discrimination if discrimination is not None else 'n/a'} | "
                f"{item['incomplete']} | {item['review']} | {item['invalid']} | "
                f"{item['missing']} | {item['classification']} |")
        lines += ["",]
    lines += [
        "## Interpretation", "",
        f"- Item classifications require at least {MIN_ITEM_OBSERVATIONS} scored observations.",
        "- Difficulty balance is `4p(1-p)`: 1.0 at a 50% pass rate and 0.0 at",
        "  unanimous pass/fail. It is not an item-response-theory information estimate.",
        "- `CEILING` and `FLOOR` items add little separation in the observed sample.",
        "- `NEGATIVE` discrimination is a review trigger for ambiguity, grading defects,",
        "  multidimensional skills, or sampling noise; it is not automatic proof of a bad item.",
        f"- Pair comparisons require at least {MIN_PAIR_ITEMS} commonly scored items.",
        "- Between-configuration disagreement measures observed separation. Within-configuration",
        "  disagreement measures repeat instability. Net separation requires both.",
        "- These descriptive diagnostics are not an IRT fit, causal attribution, or a score",
        "  prediction for an untested model.", "",
    ]
    return "\n".join(lines)


def write_analysis(run_dirs: list[Path], output: Path) -> tuple[Path, Path, dict]:
    if output.suffix.lower() != ".md":
        raise ValueError("analysis output must use a .md extension")
    analysis = analyze_runs(run_dirs)
    json_path = output.with_suffix(".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_analysis(analysis), encoding="utf-8")
    json_path.write_text(json.dumps(analysis, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    return output, json_path, analysis
