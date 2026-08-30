"""Tiny thread-safe counter bag."""

import threading

__all__ = ["Metrics"]


class Metrics:
    def __init__(self):
        self._lock = threading.Lock()
        self._counters = {}

    def incr(self, name, amount=1):
        with self._lock:
            value = self._counters.get(name, 0) + amount
            self._counters[name] = value
            return value

    def get(self, name):
        with self._lock:
            return self._counters.get(name, 0)

    def snapshot(self):
        with self._lock:
            return dict(self._counters)

    def reset(self):
        with self._lock:
            self._counters.clear()

    def __repr__(self):
        return "Metrics(%r)" % (self.snapshot(),)
