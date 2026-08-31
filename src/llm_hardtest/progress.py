from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return (f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours
            else f"{minutes:02d}:{seconds:02d}")


@dataclass
class TerminalDashboard:
    """Dependency-free progress display with a line-oriented log fallback."""

    campaign: str
    total: int
    run_dir: Path
    mode: str = "auto"
    stream: TextIO = field(default_factory=lambda: sys.stdout)
    started: float = field(default_factory=time.monotonic)
    completed: int = 0
    passed: int = 0
    failed: int = 0
    review: int = 0
    invalid: int = 0
    skipped: int = 0
    current: str = "Preparing campaign"
    latest: str = "Validating execution plan"
    _rendered_lines: int = 0
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _stop_event: threading.Event = field(default_factory=threading.Event,
                                         init=False, repr=False)
    _refresh_thread: threading.Thread | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.mode not in {"auto", "dashboard", "plain"}:
            raise ValueError("progress mode must be auto, dashboard, or plain")
        self.enabled = self.mode == "dashboard" or (
            self.mode == "auto"
            and os.environ.get("TERM", "") != "dumb"
            and bool(getattr(self.stream, "isatty", lambda: False)())
        )
        if self.enabled:
            self._refresh_thread = threading.Thread(
                target=self._refresh_loop, name="llm-hardtest-dashboard", daemon=True)
            self._refresh_thread.start()

    def _refresh_loop(self) -> None:
        while not self._stop_event.wait(1.0):
            self.render()

    def start(self, model: str, round_no: int, attempt: int, attempts: int,
              item: str) -> None:
        with self._lock:
            self.current = (f"{model} | Round {round_no} | attempt {attempt}/{attempts} | "
                            f"{item}")
            self.latest = "Running"
        self.render()

    def record(self, status: str, model: str, round_no: int, attempt: int,
               attempts: int, item: str, wall: float | None = None) -> None:
        status = status.upper()
        if status not in {"PASS", "FAIL", "REVIEW", "INVALID"}:
            raise ValueError(f"unsupported progress status {status!r}")
        with self._lock:
            self.completed += 1
            if status == "PASS":
                self.passed += 1
            elif status == "FAIL":
                self.failed += 1
            elif status == "REVIEW":
                self.review += 1
            else:
                self.invalid += 1
            self.current = (f"{model} | Round {round_no} | attempt {attempt}/{attempts} | "
                            f"{item}")
            timing = f" in {wall:.1f}s" if isinstance(wall, (int, float)) else ""
            self.latest = f"{item}: {status}{timing}"
        if self.enabled:
            self.render()
        else:
            print(f"    r{round_no} {item}: {status}", file=self.stream, flush=True)

    def skip(self, count: int, description: str) -> None:
        with self._lock:
            self.completed += max(0, count)
            self.skipped += max(0, count)
            self.current = description
            self.latest = f"Resumed {count} completed item{'s' if count != 1 else ''}"
        if self.enabled:
            self.render()
        else:
            print(f"[resume] {description}", file=self.stream, flush=True)

    def message(self, text: str) -> None:
        with self._lock:
            self.latest = text
        if self.enabled:
            self.render()
        else:
            print(text, file=self.stream, flush=True)

    def complete_plan(self) -> None:
        """Mark traversal of a dry-run plan complete without inventing results."""
        with self._lock:
            self.completed = self.total
            self.current = "Dry-run plan complete"
            self.latest = "No model was called"
        self.render()

    def finish(self, success: bool = True, message: str | None = None) -> None:
        if self.enabled:
            self._stop_event.set()
            if (self._refresh_thread is not None
                    and self._refresh_thread is not threading.current_thread()):
                self._refresh_thread.join(timeout=2.0)
        with self._lock:
            self.current = "Campaign complete" if success else "Campaign stopped"
            self.latest = message or ("Report generated" if success else "See the error below")
        if self.enabled:
            self.render()
            self.stream.write("\n")
            self.stream.flush()

    def render(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            elapsed = time.monotonic() - self.started
            percent = (100 * self.completed / self.total) if self.total else 100.0
            rate = self.completed / elapsed if elapsed > 0 else 0
            remaining = max(0, self.total - self.completed)
            eta = remaining / rate if rate > 0 and self.completed else None
            columns = max(20, shutil.get_terminal_size((80, 24)).columns)
            width = min(32, max(10, columns - 49))
            filled = min(width, round(width * min(percent, 100) / 100))
            bar = "#" * filled + "-" * (width - filled)
            lines = [
                f"LLM Hardtest | {self.campaign}",
                f"[{bar}] {self.completed}/{self.total} ({percent:5.1f}%)",
                f"Elapsed {_duration(elapsed)} | ETA {_duration(eta)}",
                self.current,
                (f"PASS {self.passed} | FAIL {self.failed} | REVIEW {self.review} | "
                 f"INVALID {self.invalid} | RESUMED {self.skipped}"),
                self.latest,
                f"Output: {self.run_dir}",
            ]
            lines = [line[:columns - 1] for line in lines]
            if self._rendered_lines:
                self.stream.write(f"\x1b[{self._rendered_lines}F")
            for line in lines:
                self.stream.write("\x1b[2K" + line + "\n")
            self.stream.flush()
            self._rendered_lines = len(lines)
