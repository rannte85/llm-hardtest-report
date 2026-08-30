from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from .backends import Backend
from .common import answer_matches, answer_text, load_json, repo_root, save_json


SUFFIX = "\n\nEnd with exactly one final line in this format: ANSWER: <value>"


def run(round_no: int, model: dict, backend: Backend, attempt: int,
        out_dir: Path, timeout: int, question_filter: set[int] | None = None,
        progress: Callable[[dict], None] | None = None) -> dict:
    questions = load_json(repo_root() / "rounds" /
                          f"round{round_no}" / "questions.json")
    if question_filter:
        questions = [q for q in questions if int(q["id"]) in question_filter]
    results = []
    for q in questions:
        if progress:
            progress({"event": "start", "item": f'q{q["id"]}'})
        started = time.time()
        try:
            response = backend.complete([{"role": "user", "content": q["q"] + SUFFIX}], timeout)
            extracted = answer_text(response["content"])
            correct = answer_matches(extracted, q["ans"])
            row = {"id": q["id"], "type": q.get("type"), "expected": q["ans"],
                   "extracted": extracted, "correct": correct, "content": response["content"],
                   **{k: v for k, v in response.items() if k != "content"}}
        except Exception as exc:  # keep the campaign resumable
            row = {"id": q["id"], "type": q.get("type"), "correct": None,
                   "valid": False,
                   "error": str(exc), "wall": round(time.time() - started, 3)}
        results.append(row)
        mark = "INVALID" if row.get("valid") is False else ("PASS" if row["correct"] else "FAIL")
        if progress:
            progress({"event": "complete", "item": f'q{q["id"]}', "status": mark,
                      "wall": row.get("wall")})
        else:
            print(f'    r{round_no} q{q["id"]}: {mark}')
    valid = [row for row in results if row.get("valid") is not False]
    payload = {
        "round": round_no, "model": model["key"], "model_id": model["model"],
        "attempt": attempt, "score": sum(bool(x["correct"]) for x in valid),
        "total": len(valid), "planned": len(results),
        "infrastructure_errors": len(results) - len(valid),
        "wall": round(sum(x.get("wall", 0) for x in results), 3),
        "completion_tokens": sum(x.get("completion_tokens") or 0 for x in results),
        "results": results,
    }
    save_json(out_dir / "result.json", payload)
    return payload
