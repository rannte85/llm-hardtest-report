#!/usr/bin/env python3
"""Execute q35's positive and adversarial control matrix."""

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


HEADER = '''"""Snapshot cache implementation used by a deterministic control."""

from __future__ import annotations

import threading


'''


def _implementation(state: str) -> str:
    if state == "serialize":
        return HEADER + '''class SnapshotCache:
    def __init__(self, initial=None):
        self._values = dict(initial or {})
        self._lock = threading.RLock()

    def get(self, key):
        with self._lock:
            return self._values.get(key)

    def refresh(self, key, loader):
        with self._lock:
            value = loader()
            self._values[key] = value
            return value
'''
    if state == "value_cas":
        return HEADER + '''_MISSING = object()


class SnapshotCache:
    def __init__(self, initial=None):
        self._values = dict(initial or {})
        self._lock = threading.RLock()

    def get(self, key):
        with self._lock:
            return self._values.get(key)

    def refresh(self, key, loader):
        with self._lock:
            previous = self._values.get(key, _MISSING)
        value = loader()
        with self._lock:
            if self._values.get(key, _MISSING) == previous:
                self._values[key] = value
            return self._values.get(key)
'''
    if state == "global_epoch":
        return HEADER + '''class SnapshotCache:
    def __init__(self, initial=None):
        self._values = dict(initial or {})
        self._lock = threading.RLock()
        self._next_epoch = 0
        self._committed_epoch = 0

    def get(self, key):
        with self._lock:
            return self._values.get(key)

    def refresh(self, key, loader):
        with self._lock:
            self._next_epoch += 1
            epoch = self._next_epoch
        value = loader()
        with self._lock:
            if epoch > self._committed_epoch:
                self._values[key] = value
                self._committed_epoch = epoch
            return self._values.get(key)
'''

    reserve = (
        "            epoch = self._next_epoch.get(key, 0) + 1\n"
        "            self._next_epoch[key] = epoch\n")
    if state == "latest_issued":
        reserve += "            self._latest_issued[key] = epoch\n"
        condition = "epoch == self._latest_issued.get(key)"
    else:
        condition = "epoch > self._committed_epoch.get(key, 0)"
    failure = ""
    if state == "failure_clears":
        failure = (
            "        except BaseException:\n"
            "            with self._lock:\n"
            "                self._values.pop(key, None)\n"
            "            raise\n")
    else:
        failure = "        except BaseException:\n            raise\n"
    return_value = "value" if state == "stale_return" else "self._values.get(key)"
    latest_field = "        self._latest_issued = {}\n" if state == "latest_issued" else ""
    return HEADER + f'''class SnapshotCache:
    def __init__(self, initial=None):
        self._values = dict(initial or {{}})
        self._lock = threading.RLock()
        self._next_epoch = {{}}
        self._committed_epoch = {{}}
{latest_field}
    def get(self, key):
        with self._lock:
            return self._values.get(key)

    def refresh(self, key, loader):
        with self._lock:
{reserve}        try:
            value = loader()
{failure}        with self._lock:
            if {condition}:
                self._values[key] = value
                self._committed_epoch[key] = epoch
            return {return_value}
'''


def _apply(state: str, repo: Path) -> None:
    if state == "baseline":
        return
    if state not in {
            "correct", "latest_issued", "value_cas", "global_epoch", "serialize",
            "failure_clears", "stale_return", "tamper"}:
        raise ValueError(state)
    implementation = "correct" if state == "tamper" else state
    (repo / "snapshot_cache.py").write_text(
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
    states = ("baseline", "correct", "latest_issued", "value_cas", "global_epoch",
              "serialize", "failure_clears", "stale_return", "tamper")
    results = {}
    with tempfile.TemporaryDirectory(prefix="llm-hardtest-r5-q35-") as tmp:
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
