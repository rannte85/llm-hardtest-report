#!/usr/bin/env python3
"""Execute q42's positive and adversarial shared-cache matrix."""

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
CORRECT = (HERE / "_control_complete.py").read_text(encoding="utf-8")


def _implementation(state: str) -> str:
    source = CORRECT
    if state == "conflicting_request_header":
        source = source.replace(
            "if lower in normalized and normalized[lower] != clean:",
            "if False and lower in normalized and normalized[lower] != clean:")
    elif state == "cookie_cached":
        source = source.replace(
            '_SENSITIVE = {"authorization", "cookie", "range", "if-none-match",',
            '_SENSITIVE = {"authorization", "range", "if-none-match",')
    elif state == "range_cached":
        source = source.replace(
            '_SENSITIVE = {"authorization", "cookie", "range", "if-none-match",',
            '_SENSITIVE = {"authorization", "cookie", "if-none-match",')
    elif state == "set_cookie_cached":
        source = source.replace(
            'if forbidden or "set-cookie" in fields or max_age is None:',
            "if forbidden or max_age is None:")
    elif state == "vary_star_cached":
        source = source.replace(
            'if name == "*":\n                return None',
            'if name == "*":\n                continue')
    elif state == "conflicting_max_age_allowed":
        source = source.replace(
            "if len(set(selected)) > 1:",
            "if False and len(set(selected)) > 1:")
    elif state == "age_ignored":
        source = source.replace("return int(values[0])", "return 0")
    elif state == "ignore_304_vary":
        source = source.replace(
            "for name, values in update.items():\n"
            "            if name not in _HOP_BY_HOP:\n"
            "                merged[name] = list(values)",
            "for name, values in update.items():\n"
            "            if name not in _HOP_BY_HOP and name != 'vary':\n"
            "                merged[name] = list(values)")
    elif state == "stale_unbounded":
        source = source.replace(
            "and self._current_age(entry, now)\n"
            "                        < entry.max_age + entry.stale_if_error):",
            "and self._current_age(entry, now) >= 0):")
    elif state == "global_singleflight":
        source = source.replace(
            "flight_key = (url, tuple(sorted(request.items())))",
            "flight_key = (url,)")
    elif state == "failed_flight_poison":
        source = source.replace(
            "                self._flights.pop(flight_key, None)\n"
            "            raise",
            "            raise", 1)
    return source


def _apply(state: str, repo: Path) -> None:
    if state == "baseline":
        return
    valid = {
        "correct", "conflicting_request_header", "cookie_cached", "range_cached",
        "set_cookie_cached", "vary_star_cached", "conflicting_max_age_allowed",
        "age_ignored", "ignore_304_vary", "stale_unbounded",
        "global_singleflight", "failed_flight_poison", "tamper",
    }
    if state not in valid:
        raise ValueError(state)
    implementation = "correct" if state == "tamper" else state
    (repo / "shared_cache.py").write_text(
        _implementation(implementation), encoding="utf-8")
    if state == "tamper":
        with (repo / "run_tests.py").open("a", encoding="utf-8") as handle:
            handle.write("\n# candidate changed protected public-test authority\n")


def _run(command: list[str], cwd: Path) -> tuple[int, int, str]:
    proc = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=20)
    output = proc.stdout + proc.stderr
    match = re.search(r"(?:PUBLIC|HIDDEN): (\d+)/(\d+)", output)
    if not match:
        raise RuntimeError(f"control command produced no score: {output[-2000:]}")
    return int(match.group(1)), int(match.group(2)), output


def main() -> int:
    states = (
        "baseline", "correct", "conflicting_request_header", "cookie_cached",
        "range_cached", "set_cookie_cached", "vary_star_cached",
        "conflicting_max_age_allowed", "age_ignored", "ignore_304_vary",
        "stale_unbounded", "global_singleflight", "failed_flight_poison", "tamper",
    )
    results = {}
    diagnostics = []
    with tempfile.TemporaryDirectory(prefix="llm-hardtest-r5-q42-") as tmp:
        for state in states:
            repo = Path(tmp) / state
            shutil.copytree(SOURCE, repo)
            _apply(state, repo)
            public = _run([sys.executable, "run_tests.py"], repo)
            hidden = _run([sys.executable, str(HIDDEN), str(repo)], repo)
            results[state] = (public[:2], hidden[:2])
            if state != "baseline" and public[0] != public[1]:
                diagnostics.append(
                    f"{state} unexpected public failure:\n{public[2][-2000:]}")
            if state == "correct" and hidden[0] != hidden[1]:
                diagnostics.append(
                    f"correct unexpected hidden failure:\n{hidden[2][-2000:]}")
            print(f"{state:32} public {public[0]}/{public[1]} "
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
        for diagnostic in diagnostics:
            print(diagnostic)
        return 1
    print("PILOT_CONTROL_MATRIX=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
