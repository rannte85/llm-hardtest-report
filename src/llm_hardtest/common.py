from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path


def repo_root() -> Path:
    """Return the directory that contains bundled benchmark rounds.

    Editable installs use the repository-level ``rounds/`` tree. Built wheels
    carry the same data inside the package so installed commands remain usable.
    """
    source_root = Path(__file__).resolve().parents[2]
    if (source_root / "rounds").is_dir():
        return source_root
    package_root = Path(__file__).resolve().parent
    if (package_root / "rounds").is_dir():
        return package_root
    raise RuntimeError("benchmark data is missing; reinstall llm-hardtest-report")


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
    return matches[-1].strip() if matches else ""


def norm_answer(value: str) -> str:
    return re.sub(r"[\s,%]", "", str(value).strip().lower())


def answer_matches(actual: str, expected: str) -> bool:
    a, e = norm_answer(actual), norm_answer(expected)
    return bool(a) and a == e
