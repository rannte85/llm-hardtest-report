from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable

from .backends import Backend
from .common import load_json, repo_root, save_json


ROOT = repo_root()
BASE = ROOT / "rounds" / "round3"
JOBS = {'A': (4,4,9,[]), 'B': (3,7,3,[]), 'C': (3,10,4,['B']),
        'D': (2,12,9,['C']), 'E': (5,17,6,[]), 'F': (6,20,5,['A'])}


def _set(value: str) -> set[str]:
    return {x.strip().upper() for x in re.split(r'[,\s/&]+', value or "") if x.strip()}


def _simulate(value: str):
    seq = [x.strip().upper() for x in re.split(r'[,\s>→-]+', value or "") if x.strip()]
    now, reward, done = 0, 0, set()
    for key in seq:
        if key not in JOBS or key in done:
            return None
        duration, deadline, points, deps = JOBS[key]
        if not all(dep in done for dep in deps):
            return None
        now += duration
        if now > deadline:
            return None
        done.add(key); reward += points
    return reward


def _fields(text: str) -> dict:
    idx = text.rfind("=== ANSWER ===")
    segment = text[idx:] if idx >= 0 else text[-3000:]
    return {m.group(1): m.group(2).strip()
            for m in re.finditer(r'^([A-Z][A-Z0-9_]+):\s*(.+)$', segment, re.M)}


def _grade(qid: int, f: dict) -> dict:
    if qid == 21:
        checks = {
            "CLAIM_VALID": f.get("CLAIM_VALID", "").upper().startswith("NO"),
            "GREEDY_REWARD": re.sub(r'\D', '', f.get("GREEDY_REWARD", "")) == "20",
            "GREEDY_ORDER": _set(f.get("GREEDY_ORDER", "")) == {'A','E','F'} and _simulate(f.get("GREEDY_ORDER", "")) is not None,
            "OPTIMAL_REWARD": re.sub(r'\D', '', f.get("OPTIMAL_REWARD", "")) == "31",
            "OPTIMAL_ORDER": _simulate(f.get("OPTIMAL_ORDER", "")) == 31,
        }
    elif qid == 22:
        line = re.sub(r'\D', '', f.get("ROOT_CAUSE_LINE", "") or "0")
        symptom = re.sub(r'\D', '', f.get("SYMPTOM_LINE", "") or "0")
        checks = {
            "ROOT_CAUSE_FILE": "cache" in f.get("ROOT_CAUSE_FILE", "").lower(),
            "ROOT_CAUSE_FUNCTION": "update" in f.get("ROOT_CAUSE_FUNCTION", "").lower(),
            "ROOT_CAUSE_LINE": line.isdigit() and 19 <= int(line) <= 27,
            "SYMPTOM_FILE": "metrics" in f.get("SYMPTOM_FILE", "").lower(),
            "SYMPTOM_LINE": symptom.isdigit() and 6 <= int(symptom) <= 10,
            "WORKER_FIX_SUFFICIENT": f.get("WORKER_FIX_SUFFICIENT", "").upper().startswith("NO"),
        }
    elif qid == 23:
        first_r11 = f.get("CONFLICT_PAIR", "").strip().upper().startswith("R11")
        checks = {
            "HAS_CONTRADICTION": f.get("HAS_CONTRADICTION", "").upper().startswith("YES"),
            "CONFLICT_PAIR": _set(f.get("CONFLICT_PAIR", "")) == {'R4','R11'},
            "FIRST_UNDER_FIRST_RULE": f.get("FIRST_UNDER_FIRST_RULE", "").strip().upper()[:1] == ('A' if first_r11 else 'B'),
            "FIRST_UNDER_SECOND_RULE": f.get("FIRST_UNDER_SECOND_RULE", "").strip().upper()[:1] == ('B' if first_r11 else 'A'),
        }
    elif qid == 24:
        checks = {
            "FIX_FUNCTION": "normalize" in f.get("FIX_FUNCTION", "").lower(),
            "TESTS_AFTER_FIX": "15" in f.get("TESTS_AFTER_FIX", ""),
            "SPAN_FIX_REGRESSIONS": _set(f.get("SPAN_FIX_REGRESSIONS", "")) == {'T09','T11'},
        }
    else:
        return {}
    return {"fields": f, "checks": checks, "correct": all(checks.values())}


def _prompt(spec: dict, q: dict) -> str:
    text = q["prompt"]
    for rel in q.get("artifacts", []):
        path = BASE / rel
        lines = path.read_text(encoding="utf-8").splitlines()
        text += "\n\n--- FILE: " + path.name + " ---\n"
        text += "\n".join(f"{i+1:>3}| {line}" for i, line in enumerate(lines))
    return text + spec["answer_block_instruction"] + q.get("answer_example", "")


def run(model: dict, backend: Backend, attempt: int, out_dir: Path, timeout: int,
        progress: Callable[[dict], None] | None = None) -> dict:
    spec = load_json(BASE / "problems_v3.json")
    results = []
    for q in spec["questions"]:
        if progress:
            progress({"event": "start", "item": f'q{q["id"]}'})
        started = time.time()
        try:
            if q.get("multi_turn"):
                messages, turns = [], []
                for index, turn in enumerate(q["turns"], 1):
                    messages.append({"role": "user", "content": turn})
                    response = backend.complete(messages, timeout)
                    messages.append({"role": "assistant", "content": response["content"]})
                    turns.append({"turn": index, **response})
                row = {"id": q["id"], "name": q["name"], "manual_review_required": True,
                       "correct": None, "turns": turns,
                       "wall": round(time.time() - started, 3),
                       "completion_tokens": sum(x.get("completion_tokens") or 0 for x in turns)}
            else:
                response = backend.complete([{"role": "user", "content": _prompt(spec, q)}], timeout)
                grade = _grade(q["id"], _fields(response["content"]))
                row = {"id": q["id"], "name": q["name"], **grade, **response}
        except Exception as exc:
            row = {"id": q["id"], "name": q["name"], "correct": None,
                   "valid": False, "error": str(exc),
                   "wall": round(time.time() - started, 3)}
        results.append(row)
        mark = ("INVALID" if row.get("valid") is False else
                ("REVIEW" if row.get("correct") is None else
                 ("PASS" if row["correct"] else "FAIL")))
        if progress:
            progress({"event": "complete", "item": f'q{q["id"]}', "status": mark,
                      "wall": row.get("wall")})
        else:
            print(f'    r3 q{q["id"]}: {mark}')
    valid = [x for x in results if x.get("valid") is not False]
    auto = [x for x in valid if x.get("correct") is not None]
    payload = {"round": 3, "model": model["key"], "model_id": model["model"],
               "attempt": attempt, "score": sum(x["correct"] for x in auto),
               "total": len(auto), "planned": len(results),
               "infrastructure_errors": len(results) - len(valid),
               "manual_review": sum(x.get("correct") is None for x in valid),
               "wall": round(sum(x.get("wall", 0) for x in results), 3), "results": results}
    save_json(out_dir / "result.json", payload)
    return payload
