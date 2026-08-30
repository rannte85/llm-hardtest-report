from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_json(path: Path):
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(value, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-")
    return value or "model"


def stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def answer_text(text: str) -> str:
    matches = re.findall(r"ANSWER:\s*(.+)", text or "", re.I)
    return matches[-1].strip() if matches else (text or "").strip()[-200:]


def norm_answer(value: str) -> str:
    return re.sub(r"[\s,%]", "", str(value).strip().lower())


def answer_matches(actual: str, expected: str) -> bool:
    a, e = norm_answer(actual), norm_answer(expected)
    return a == e or (len(e) >= 2 and e in a)
