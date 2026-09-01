#!/usr/bin/env python3
"""Execute q36's positive and adversarial control matrix."""

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


CORRECT = '''"""Incremental, bounded, and reentrancy-safe JSONL event stream."""

from __future__ import annotations

import json
import threading
from collections import deque


class JsonlEventStream:
    def __init__(self, on_event, on_error=None, max_frame_bytes=65536):
        if isinstance(max_frame_bytes, bool) or not isinstance(max_frame_bytes, int) or max_frame_bytes < 1:
            raise ValueError("max_frame_bytes must be a positive integer")
        self._on_event = on_event
        self._on_error = on_error or (lambda error: None)
        self._max_frame_bytes = max_frame_bytes
        self._buffer = bytearray()
        self._discarding = False
        self._queue = deque()
        self._draining = False
        self._closed = False
        self._lock = threading.RLock()

    def _error(self, error):
        self._queue.append((self._on_error, error))

    def _frame(self, raw):
        if raw.endswith(b"\\r"):
            raw = raw[:-1]
        if not raw.strip():
            return
        try:
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("JSONL event must be an object")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            self._error(error)
        else:
            self._queue.append((self._on_event, value))

    def _start_drain(self):
        if self._draining or not self._queue:
            return False
        self._draining = True
        return True

    def _drain(self):
        try:
            while True:
                with self._lock:
                    if not self._queue:
                        self._draining = False
                        return
                    callback, value = self._queue.popleft()
                callback(value)
        except BaseException:
            with self._lock:
                self._draining = False
            raise

    def feed(self, chunk):
        data = bytes(chunk)
        with self._lock:
            if self._closed:
                raise RuntimeError("stream is closed")
            start = 0
            while start < len(data):
                newline = data.find(b"\\n", start)
                end = len(data) if newline < 0 else newline
                if self._discarding:
                    if newline < 0:
                        start = len(data)
                        continue
                    self._discarding = False
                    start = newline + 1
                    continue
                self._buffer.extend(data[start:end])
                frame_bytes = (len(self._buffer) - 1
                               if self._buffer.endswith(b"\\r")
                               else len(self._buffer))
                if frame_bytes > self._max_frame_bytes:
                    self._buffer.clear()
                    self._error(ValueError("JSONL frame exceeds max_frame_bytes"))
                    self._discarding = newline < 0
                elif newline >= 0:
                    self._frame(bytes(self._buffer))
                    self._buffer.clear()
                if newline < 0:
                    start = len(data)
                else:
                    start = newline + 1
            should_drain = self._start_drain()
        if should_drain:
            self._drain()

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._discarding:
                self._discarding = False
                self._buffer.clear()
            elif self._buffer:
                self._frame(bytes(self._buffer))
                self._buffer.clear()
            should_drain = self._start_drain()
        if should_drain:
            self._drain()
'''


TEXT_BUFFER = '''"""Incorrect text-first JSONL stream control."""

from __future__ import annotations

import json


class JsonlEventStream:
    def __init__(self, on_event, on_error=None, max_frame_bytes=65536):
        self._on_event = on_event
        self._on_error = on_error or (lambda error: None)
        self._max_frame_bytes = max_frame_bytes
        self._buffer = ""
        self._closed = False

    def _frame(self, line):
        if not line.strip():
            return
        try:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("JSONL event must be an object")
        except Exception as error:
            self._on_error(error)
        else:
            self._on_event(value)

    def feed(self, chunk):
        if self._closed:
            raise RuntimeError("stream is closed")
        self._buffer += bytes(chunk).decode("utf-8"DECODE_MODE)
        while "\\n" in self._buffer:
            line, self._buffer = self._buffer.split("\\n", 1)
            self._frame(line.rstrip("\\r"))

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._buffer:
            self._frame(self._buffer)
            self._buffer = ""
'''


def _implementation(state: str) -> str:
    if state == "concat_text":
        return TEXT_BUFFER.replace("DECODE_MODE", "")
    if state == "decode_replace":
        return TEXT_BUFFER.replace("DECODE_MODE", ', errors="replace"')
    source = CORRECT
    if state == "char_limit":
        source = source.replace(
            "frame_bytes = (len(self._buffer) - 1\n"
            "                               if self._buffer.endswith(b\"\\r\")\n"
            "                               else len(self._buffer))",
            'frame_bytes = len(self._buffer.decode("utf-8", errors="ignore"))')
    elif state == "abort_on_error":
        source = source.replace("            self._error(error)\n", "            raise\n")
    elif state == "no_close_flush":
        source = source.replace(
            "            elif self._buffer:\n"
            "                self._frame(bytes(self._buffer))\n"
            "                self._buffer.clear()\n",
            "            elif self._buffer:\n"
            "                self._buffer.clear()\n")
    elif state == "accept_scalar":
        source = source.replace(
            "            if not isinstance(value, dict):\n"
            "                raise ValueError(\"JSONL event must be an object\")\n", "")
    elif state == "callback_inline":
        source = source.replace(
            "        self._queue.append((self._on_error, error))",
            "        self._on_error(error)")
        source = source.replace(
            "            self._queue.append((self._on_event, value))",
            "            self._on_event(value)")
    return source


def _apply(state: str, repo: Path) -> None:
    if state == "baseline":
        return
    if state not in {
            "correct", "concat_text", "decode_replace", "callback_inline",
            "char_limit", "abort_on_error", "no_close_flush", "accept_scalar",
            "tamper"}:
        raise ValueError(state)
    implementation = "correct" if state == "tamper" else state
    (repo / "jsonl_stream.py").write_text(
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
    states = ("baseline", "correct", "concat_text", "decode_replace",
              "callback_inline", "char_limit", "abort_on_error", "no_close_flush",
              "accept_scalar", "tamper")
    results = {}
    with tempfile.TemporaryDirectory(prefix="llm-hardtest-r5-q36-") as tmp:
        for state in states:
            repo = Path(tmp) / state
            shutil.copytree(SOURCE, repo)
            _apply(state, repo)
            public = _run([sys.executable, "run_tests.py"], repo)
            hidden = _run([sys.executable, str(HIDDEN), str(repo)], repo)
            results[state] = (public[:2], hidden[:2])
            print(f"{state:16} public {public[0]}/{public[1]} "
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
