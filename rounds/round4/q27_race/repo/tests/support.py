"""Shared helpers for the test suite."""

import threading
import time


def spin(iterations=300):
    """A tiny amount of real CPU work, so jobs are not instantaneous."""
    total = 0
    for i in range(iterations):
        total += i * i
    return total


def wait_until(predicate, timeout=5.0, interval=0.002):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def run_off_thread(fn):
    """Start ``fn`` on its own thread and hand back the thread."""
    thread = threading.Thread(target=fn, daemon=True)
    thread.start()
    return thread


class Flag:
    def __init__(self):
        self.event = threading.Event()

    def set(self):
        self.event.set()

    def wait(self, timeout=5.0):
        return self.event.wait(timeout)

    def is_set(self):
        return self.event.is_set()
