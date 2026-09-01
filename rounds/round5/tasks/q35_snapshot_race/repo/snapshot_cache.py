"""Small in-memory catalog snapshot cache."""

from __future__ import annotations


class SnapshotCache:
    def __init__(self, initial=None):
        self._values = dict(initial or {})

    def get(self, key):
        return self._values.get(key)

    def refresh(self, key, loader):
        """Load and publish one snapshot."""
        value = loader()
        self._values[key] = value
        return value
