from __future__ import annotations

from pathlib import Path

from .common import load_json, slug
from .results import item_status


UNRESOLVED = {"FAIL", "INCOMPLETE", "REVIEW", "INVALID"}


def inspect_run(run_dir: Path) -> dict:
    """Return unresolved evidence from a campaign without changing any artifact."""
    config_path = run_dir / "config.json"
    if not config_path.is_file():
        raise ValueError(f"run directory has no config.json: {run_dir}")
    config = load_json(config_path)
    items = []
    for model in config.get("models", []):
        key = model.get("key", "model")
        if (not isinstance(key, str) or key in {"", ".", ".."}
                or slug(key) != key or Path(key).name != key):
            raise ValueError(f"unsafe model key in saved config: {key!r}")
        model_root = (run_dir / key).resolve()
        try:
            model_root.relative_to(run_dir.resolve())
        except ValueError as exc:
            raise ValueError(f"model path escapes run directory: {key!r}") from exc
        for round_no in (1, 2, 3):
            pattern = model_root / f"round{round_no}"
            for path in sorted(pattern.glob("attempt-*/result.json")):
                payload = load_json(path)
                attempt = int(payload.get("attempt") or path.parent.name.split("-")[-1])
                for row in payload.get("results", []):
                    status = item_status(row)
                    if status not in UNRESOLVED:
                        continue
                    items.append({
                        "model": key,
                        "round": round_no,
                        "attempt": attempt,
                        "item": f'q{row.get("id", "?")}',
                        "item_id": row.get("id"),
                        "status": status,
                        "expected": row.get("expected"),
                        "extracted": row.get("extracted"),
                        "finish_reason": row.get("finish_reason"),
                        "error": row.get("error"),
                        "wall_seconds": row.get("wall"),
                    })
        v4_path = model_root / "round4" / "run.json"
        if not v4_path.is_file():
            continue
        payload = load_json(v4_path)
        graded = set()
        for grade in payload.get("grades", []):
            flags = grade.get("flags", {})
            if flags.get("attempt_pass"):
                continue
            meta = grade.get("run_meta", {})
            graded.add((grade.get("task", grade.get("qid")), meta.get("attempt")))
            items.append({
                "model": key,
                "round": 4,
                "attempt": meta.get("attempt"),
                "item": grade.get("task", grade.get("qid", "unknown")),
                "item_id": grade.get("task", grade.get("qid")),
                "status": "INVALID" if flags.get("model_timed_out") else "FAIL",
                "expected": None,
                "extracted": None,
                "finish_reason": "timeout" if flags.get("model_timed_out") else None,
                "error": None,
                "wall_seconds": meta.get("wall"),
            })
        for error in payload.get("errors", []):
            if (error.get("task"), error.get("attempt")) in graded:
                continue
            items.append({
                "model": key,
                "round": 4,
                "attempt": error.get("attempt"),
                "item": error.get("task", "unknown"),
                "item_id": error.get("task"),
                "status": "INVALID",
                "expected": None,
                "extracted": None,
                "finish_reason": None,
                "error": error.get("error"),
                "wall_seconds": None,
            })
    counts = {status: sum(item["status"] == status for item in items)
              for status in sorted(UNRESOLVED)}
    return {"run_id": run_dir.name, "unresolved": len(items),
            "counts": counts, "items": items}


def render_inspection(summary: dict) -> str:
    """Render a stable, line-oriented unresolved-item table for terminals."""
    if not summary["items"]:
        return f'{summary["run_id"]}: no unresolved items'
    lines = [
        f'{summary["run_id"]}: {summary["unresolved"]} unresolved item(s)',
        "MODEL\tROUND\tATTEMPT\tITEM\tSTATUS\tDETAIL",
    ]
    for item in summary["items"]:
        detail = item.get("error") or item.get("finish_reason") or ""
        if item.get("extracted") not in (None, ""):
            detail = f'extracted={item["extracted"]}'
        detail = str(detail).replace("\t", " ").replace("\n", " ")
        lines.append(
            f'{item["model"]}\t{item["round"]}\t{item.get("attempt") or "-"}\t'
            f'{item["item"]}\t{item["status"]}\t{detail}'
        )
    return "\n".join(lines)
