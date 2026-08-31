#!/usr/bin/env python3
"""Execute q33's positive and adversarial control matrix."""

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


def _replace_operations(text: str, charge: str, send: str) -> str:
    return text.replace("charge_operation = uuid.uuid4().hex",
                        f"charge_operation = {charge}").replace(
                            "send_operation = uuid.uuid4().hex",
                            f"send_operation = {send}")


def _apply(state: str, repo: Path) -> None:
    path = repo / "deliveries.py"
    text = path.read_text(encoding="utf-8")
    correct = (
        '(batch_id, request_id, delivery_id, "charge")',
        '(batch_id, request_id, delivery_id, "send")')
    if state in {"correct", "schema_break", "tamper", "global_lock"}:
        text = _replace_operations(text, *correct)
    elif state == "no_batch":
        text = _replace_operations(
            text, 'f"{request_id}:{delivery_id}:charge"',
            'f"{request_id}:{delivery_id}:send"')
    elif state == "delimited":
        text = _replace_operations(
            text, 'f"{batch_id}:{request_id}:{delivery_id}:charge"',
            'f"{batch_id}:{request_id}:{delivery_id}:send"')
    elif state != "baseline":
        raise ValueError(state)
    if state == "schema_break":
        text = text.replace('return {"delivered": delivered}\n',
                            'return {"delivered": delivered, "operations": []}\n')
    if state == "global_lock":
        text = text.replace(
            "self.sender = sender\n",
            "self.sender = sender\n        self._global_lock = threading.Lock()\n")
        text = text.replace(
            "delivered = []\n        for delivery_id in delivery_ids:\n",
            "with self._global_lock:\n            return self._retry_locked("
            "batch_id, request_id, delivery_ids, client_version)\n\n"
            "    def _retry_locked(self, batch_id, request_id, delivery_ids, client_version):\n"
            "        delivered = []\n        for delivery_id in delivery_ids:\n")
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
    states = ("baseline", "correct", "no_batch", "delimited", "schema_break",
              "tamper", "global_lock")
    results = {}
    with tempfile.TemporaryDirectory(prefix="llm-hardtest-r5-q33-") as tmp:
        for state in states:
            repo = Path(tmp) / state
            shutil.copytree(SOURCE, repo)
            _apply(state, repo)
            public = _run([sys.executable, "run_tests.py"], repo)
            hidden = _run([sys.executable, str(HIDDEN), str(repo)], repo)
            results[state] = (public[:2], hidden[:2])
            print(f"{state:12} public {public[0]}/{public[1]} hidden {hidden[0]}/{hidden[1]}")
    checks = [
        (results["baseline"][0][0] < results["baseline"][0][1],
         "baseline must fail public tests"),
        (results["correct"][0][0] == results["correct"][0][1],
         "correct control must pass public tests"),
        (results["correct"][1][0] == results["correct"][1][1],
         "correct control must pass hidden tests"),
    ]
    for state in ("no_batch", "delimited", "schema_break", "tamper", "global_lock"):
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
