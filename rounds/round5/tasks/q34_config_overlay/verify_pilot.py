#!/usr/bin/env python3
"""Execute q34's positive and adversarial control matrix."""

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


def _implementation(state: str) -> str:
    result = "base" if state == "mutate_base" else "copy.deepcopy(base)"
    depth = ", _depth=0" if state == "nested_null" else ""
    recurse = ", _depth + 1" if state == "nested_null" else ""
    if state == "null_fallback":
        null_branch = "        if value is None:\n            continue\n"
    elif state == "nested_null":
        null_branch = (
            "        if value is None:\n"
            "            if _depth == 0:\n"
            "                result.pop(key, None)\n"
            "            continue\n")
    else:
        null_branch = (
            "        if value is None:\n"
            "            result.pop(key, None)\n"
            "            continue\n")
    list_branch = ""
    if state == "list_append":
        list_branch = (
            "        if isinstance(value, list) and isinstance(result.get(key), list):\n"
            "            result[key] = copy.deepcopy(result[key] + value)\n"
            "            continue\n")
    assignment = "value" if state == "alias_overlay" else "copy.deepcopy(value)"
    return (
        '"""Layered configuration merge implementation used by a control."""\n\n'
        "from __future__ import annotations\n\nimport copy\n\n\n"
        f"def merge_config(base, overlay{depth}):\n"
        "    \"\"\"Return a merged configuration without changing either input.\"\"\"\n"
        f"    result = {result}\n"
        "    for key, value in overlay.items():\n"
        + null_branch + list_branch
        + "        if isinstance(value, dict):\n"
        "            inherited = result.get(key)\n"
        "            seed = inherited if isinstance(inherited, dict) else {}\n"
        f"            result[key] = merge_config(seed, value{recurse})\n"
        "        else:\n"
        f"            result[key] = {assignment}\n"
        "    return result\n")


def _apply(state: str, repo: Path) -> None:
    if state == "baseline":
        return
    if state not in {
            "correct", "null_fallback", "nested_null", "list_append",
            "mutate_base", "alias_overlay", "tamper"}:
        raise ValueError(state)
    implementation = "correct" if state == "tamper" else state
    (repo / "config_merge.py").write_text(
        _implementation(implementation), encoding="utf-8")
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
    states = ("baseline", "correct", "null_fallback", "nested_null", "list_append",
              "mutate_base", "alias_overlay", "tamper")
    results = {}
    with tempfile.TemporaryDirectory(prefix="llm-hardtest-r5-q34-") as tmp:
        for state in states:
            repo = Path(tmp) / state
            shutil.copytree(SOURCE, repo)
            _apply(state, repo)
            public = _run([sys.executable, "run_tests.py"], repo)
            hidden = _run([sys.executable, str(HIDDEN), str(repo)], repo)
            results[state] = (public[:2], hidden[:2])
            print(f"{state:14} public {public[0]}/{public[1]} "
                  f"hidden {hidden[0]}/{hidden[1]}")
    checks = [
        (results["baseline"][0][0] < results["baseline"][0][1],
         "baseline must fail public tests"),
        (results["correct"][0][0] == results["correct"][0][1],
         "correct control must pass public tests"),
        (results["correct"][1][0] == results["correct"][1][1],
         "correct control must pass hidden tests"),
    ]
    for state in states[2:]:
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
