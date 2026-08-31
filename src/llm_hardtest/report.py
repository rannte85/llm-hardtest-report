from __future__ import annotations

import json
import html
import statistics
import time
from pathlib import Path

from .common import load_json, save_json


def _ratio(passed: int, total: int) -> str:
    return f"{passed}/{total}" if total else "n/a"


def _mean(values):
    values = [v for v in values if isinstance(v, (int, float))]
    return round(statistics.mean(values), 2) if values else None


def _md_text(value) -> str:
    """Keep user-provided labels from changing generated Markdown structure."""
    return html.escape(str(value)).replace("|", "\\|").replace("\n", " ")


def collect(run_dir: Path) -> dict:
    config = load_json(run_dir / "config.json")
    models = []
    for model in config["models"]:
        key = model["key"]
        entry = {"key": key, "label": model.get("label", model["model"]), "rounds": {}}
        for round_no in (1, 2, 3):
            rows = []
            for path in sorted((run_dir / key / f"round{round_no}").glob("attempt-*/result.json")):
                rows.append(load_json(path))
            if rows:
                entry["rounds"][str(round_no)] = {
                    "attempts": len(rows), "passed": sum(r.get("score", 0) for r in rows),
                    "total": sum(r.get("total", 0) for r in rows),
                    "mean_wall_seconds": _mean([r.get("wall") for r in rows]),
                    "manual_review": sum(r.get("manual_review", 0) for r in rows),
                    "infrastructure_errors": sum(r.get("infrastructure_errors", 0) for r in rows),
                }
        v4 = run_dir / key / "round4" / "run.json"
        if v4.exists():
            payload = load_json(v4)
            grades = payload.get("grades", [])
            task_rows = []
            for grade in grades:
                flags = grade.get("flags", {})
                public = grade.get("public", {})
                hidden = grade.get("hidden", {})
                task_rows.append({
                    "task": grade.get("task", grade.get("qid", "unknown")),
                    "attempt": grade.get("run_meta", {}).get("attempt"),
                    "public_passed": public.get("passed"),
                    "public_total": public.get("total"),
                    "hidden_passed": hidden.get("passed"),
                    "hidden_total": hidden.get("total"),
                    "auto_score": grade.get("score_auto"),
                    "release_ready": bool(flags.get("attempt_pass")),
                    "handoff_utility": flags.get("manager_utility_pass"),
                    "false_green": bool(flags.get("false_green")),
                    "tampering": bool(flags.get("test_tampering")),
                    "timed_out": bool(flags.get("model_timed_out")),
                    "wall_seconds": grade.get("run_meta", {}).get("wall"),
                    "tokens": grade.get("run_meta", {}).get("tokens"),
                })
            entry["rounds"]["4"] = {
                "attempts": len(grades),
                "planned_attempts": int(payload.get("attempts", 0)) * len(payload.get("tasks", [])),
                "infrastructure_errors": len(payload.get("errors", [])),
                "release_ready": sum(bool(g.get("flags", {}).get("attempt_pass")) for g in grades),
                "handoff_utility": sum(bool(g.get("flags", {}).get("manager_utility_pass")) for g in grades),
                "handoff_applicable": sum(g.get("flags", {}).get("manager_utility_pass") is not None for g in grades),
                "false_green": sum(bool(g.get("flags", {}).get("false_green")) for g in grades),
                "tampering": sum(bool(g.get("flags", {}).get("test_tampering")) for g in grades),
                "mean_auto_score": _mean([g.get("score_auto") for g in grades]),
                "auto_score_max": 65,
                "mean_wall_seconds": _mean([g.get("run_meta", {}).get("wall") for g in grades]),
                "tasks": task_rows,
            }
        models.append(entry)
    return {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "run_id": run_dir.name, "config": config, "models": models}


def render(summary: dict) -> str:
    lines = [
        "# LLM Hardtest — Comprehensive Report", "",
        f'**Run:** `{summary["run_id"]}`  ',
        f'**Generated:** {summary["generated_at"]}  ',
        "**Interpretation rule:** product correctness, release readiness, handoff utility, "
        "manual-review items, and throughput are separate axes.", "",
        "## Executive Matrix", "",
        "| Model | Round 1 | Round 2 | Round 3 auto | Round 3 review | Round 4 release | Round 4 handoff | False-green |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model in summary["models"]:
        rounds = model["rounds"]
        r1, r2, r3, r4 = (rounds.get(str(n), {}) for n in (1, 2, 3, 4))
        lines.append("| {label} | {r1} | {r2} | {r3} | {review} | {release} | {handoff} | {fg} |".format(
            label=_md_text(model["label"]),
            r1=_ratio(r1.get("passed", 0), r1.get("total", 0)),
            r2=_ratio(r2.get("passed", 0), r2.get("total", 0)),
            r3=_ratio(r3.get("passed", 0), r3.get("total", 0)),
            review=r3.get("manual_review", 0) or "—",
            release=_ratio(r4.get("release_ready", 0), r4.get("attempts", 0)),
            handoff=_ratio(r4.get("handoff_utility", 0), r4.get("handoff_applicable", 0)),
            fg=r4.get("false_green", 0) if r4 else "—"))
    lines += ["", "## Model Details", ""]
    for model in summary["models"]:
        lines += [f'### {_md_text(model["label"])}', ""]
        for number, data in sorted(model["rounds"].items()):
            if number in ("1", "2", "3"):
                lines.append(f'- Round {number}: {_ratio(data["passed"], data["total"])}; '
                             f'{data["attempts"]} attempts; mean wall {data["mean_wall_seconds"]}s; '
                             f'manual-review items {data.get("manual_review", 0)}; '
                             f'infrastructure errors {data.get("infrastructure_errors", 0)}.')
            else:
                lines.append(f'- Round 4: release {_ratio(data["release_ready"], data["attempts"])}; '
                             f'handoff {_ratio(data["handoff_utility"], data["handoff_applicable"])}; '
                             f'false-green {data["false_green"]}; tampering {data["tampering"]}; '
                             f'mean auto {data["mean_auto_score"]}/{data["auto_score_max"]}; '
                             f'infrastructure errors {data.get("infrastructure_errors", 0)}.')
        lines.append("")
        r4 = model["rounds"].get("4")
        if r4 and r4.get("tasks"):
            lines += ["| Task | Attempt | Public | Hidden | Auto /65 | Release | Handoff | False-green | Tampering | Wall |",
                      "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
            for row in r4["tasks"]:
                handoff = row["handoff_utility"]
                lines.append("| {task} | {attempt} | {public} | {hidden} | {auto} | {release} | {handoff} | {fg} | {tamper} | {wall}s |".format(
                    task=row["task"], attempt=row["attempt"] or "—",
                    public=_ratio(row["public_passed"] or 0, row["public_total"] or 0),
                    hidden=_ratio(row["hidden_passed"] or 0, row["hidden_total"] or 0),
                    auto=row["auto_score"] if row["auto_score"] is not None else "—",
                    release="PASS" if row["release_ready"] else "FAIL",
                    handoff="PASS" if handoff is True else ("FAIL" if handoff is False else "n/a"),
                    fg="yes" if row["false_green"] else "no",
                    tamper="yes" if row["tampering"] else "no",
                    wall=row["wall_seconds"] if row["wall_seconds"] is not None else "—"))
            lines.append("")
    lines += [
        "## Reading the Results", "",
        "- Round 1 and Round 2 are exact-answer reasoning tests.",
        "- Round 3 Q21–Q24 are automatically graded. Q25 is a long-horizon semantic task and is explicitly queued for manual or external-judge review; it is never silently counted as a pass.",
        "- Round 4 `release` means the submitted repository is immediately releasable under the hidden suite and integrity gates.",
        "- Round 4 `handoff` means a policy-conflict candidate patch moved the ticket forward safely with an accurate blocker. It does not prove full manager capability.",
        "- Infrastructure-invalid attempts must be quarantined rather than counted as model failures.", "",
        "## Reproducibility", "",
        f'- Repetitions per task: {summary["config"]["repetitions"]}',
        f'- Selected rounds: {summary["config"]["rounds"]}',
        f'- Configuration snapshot: `config.json` in this run directory.',
        "- Raw responses, transcripts, working repositories, and grades remain under each model/round directory.", "",
    ]
    return "\n".join(lines)


def generate(run_dir: Path) -> tuple[Path, Path]:
    summary = collect(run_dir)
    json_path, md_path = run_dir / "summary.json", run_dir / "REPORT.md"
    save_json(json_path, summary)
    md_path.write_text(render(summary), encoding="utf-8")
    return md_path, json_path
