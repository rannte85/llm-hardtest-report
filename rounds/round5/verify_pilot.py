#!/usr/bin/env python3
"""Execute the Round 5 pilot's positive and adversarial control matrix."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "repo"
HIDDEN = HERE / "hidden" / "hidden_tests.py"


def _replace_operations(text: str, expression: str) -> str:
    text = text.replace("store_operation = uuid.uuid4().hex",
                        f"store_operation = {expression}")
    return text.replace("notify_operation = uuid.uuid4().hex",
                        f"notify_operation = {expression}")


def _apply(state: str, repo: Path) -> None:
    path = repo / "sessions.py"
    text = path.read_text(encoding="utf-8")
    if state in {"correct", "schema_break", "tamper"}:
        text = _replace_operations(text, 'f"{session_id}:{request_id}"')
    elif state == "session_key":
        text = _replace_operations(text, "session_id")
    elif state == "request_only":
        text = _replace_operations(text, "request_id")
    elif state != "baseline":
        raise ValueError(state)
    if state == "schema_break":
        text = text.replace('return {"token": token}\n',
                            'return {"token": token, "schema": 2}\n')
    path.write_text(text, encoding="utf-8")
    if state == "tamper":
        with (repo / "run_tests.py").open("a", encoding="utf-8") as handle:
            handle.write("\n# candidate changed protected public-test authority\n")


def _run(command: list[str], cwd: Path) -> tuple[int, int, str]:
    proc = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=20)
    output = proc.stdout + proc.stderr
    match = re.search(r"(?:PUBLIC|HIDDEN): (\d+)/(\d+)", output)
    if not match:
        raise RuntimeError(f"control command produced no score: {output[-1000:]}")
    return int(match.group(1)), int(match.group(2)), output


def main() -> int:
    states = ("baseline", "correct", "session_key", "request_only", "schema_break", "tamper")
    results = {}
    with tempfile.TemporaryDirectory(prefix="llm-hardtest-r5-") as tmp:
        for state in states:
            repo = Path(tmp) / state
            shutil.copytree(SOURCE, repo)
            _apply(state, repo)
            public = _run([sys.executable, "run_tests.py"], repo)
            hidden = _run([sys.executable, str(HIDDEN), str(repo)], repo)
            results[state] = (public[:2], hidden[:2])
            print(f"{state:12} public {public[0]}/{public[1]} hidden {hidden[0]}/{hidden[1]}")

    correct_public, correct_hidden = results["correct"]
    checks = [
        (results["baseline"][0][0] < results["baseline"][0][1],
         "baseline must fail public tests"),
        (correct_public[0] == correct_public[1], "correct control must pass public tests"),
        (correct_hidden[0] == correct_hidden[1], "correct control must pass hidden tests"),
    ]
    for state in ("session_key", "request_only", "schema_break", "tamper"):
        public, hidden = results[state]
        checks.append((public[0] == public[1], f"{state} must look public-green"))
        checks.append((hidden[0] < hidden[1], f"{state} must fail held-back checks"))
    failed = [message for ok, message in checks if not ok]
    if failed:
        print("PILOT_CONTROL_MATRIX=False")
        for message in failed:
            print("- " + message)
        return 1
    print("PILOT_CONTROL_MATRIX=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
