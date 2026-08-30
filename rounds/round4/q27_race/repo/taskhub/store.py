"""Versioned result store.

Every key owns

  * a monotonically increasing ``generation`` counter, bumped by
    :meth:`ResultStore.invalidate`, and
  * at most one committed :class:`Entry`.

A producer publishes a value in two steps.  It first takes a
:class:`Snapshot` of the key (:meth:`ResultStore.begin`), then does whatever
slow work it needs to do, then publishes with :meth:`ResultStore.commit`.
The snapshot exists so that the store can tell *which* version of the world the
value was derived from -- see ``docs/DESIGN.md``.
"""

import contextlib
import threading

from .metrics import Metrics
from .tracepoints import trace

__all__ = ["Entry", "Snapshot", "ResultStore"]


class Entry:
    """A published value together with the generation it belongs to."""

    __slots__ = ("value", "generation")

    def __init__(self, value, generation):
        self.value = value
        self.generation = generation

    def __eq__(self, other):
        return (
            isinstance(other, Entry)
            and other.value == self.value
            and other.generation == self.generation
        )

    def __repr__(self):
        return "Entry(value=%r, generation=%d)" % (self.value, self.generation)


class Snapshot:
    """The generation a producer observed before it started computing."""

    __slots__ = ("key", "generation")

    def __init__(self, key, generation):
        self.key = key
        self.generation = generation

    def __repr__(self):
        return "Snapshot(key=%r, generation=%d)" % (self.key, self.generation)


class ResultStore:
    def __init__(self, metrics=None):
        # RLock so that compound operations can nest simple ones.
        self._lock = threading.RLock()
        self._entries = {}
        self._generations = {}
        self._cancelled = set()
        self._failures = {}
        self.metrics = metrics if metrics is not None else Metrics()

    # ------------------------------------------------------------------ read

    def generation(self, key):
        with self._lock:
            return self._generations.get(key, 0)

    def entry(self, key):
        with self._lock:
            return self._entries.get(key)

    def get(self, key, default=None):
        with self._lock:
            found = self._entries.get(key)
        if found is None:
            self.metrics.incr("misses")
            return default
        self.metrics.incr("hits")
        return found.value

    def keys(self):
        with self._lock:
            return sorted(set(self._entries) | set(self._generations))

    def stale_entries(self):
        """Published entries that do not belong to their key's live generation.

        Collected atomically so that a concurrent invalidation cannot make a
        perfectly fresh entry look stale.  Must always come back empty -- this
        is invariant G from ``docs/DESIGN.md``.
        """
        bad = []
        with self._lock:
            for key, entry in self._entries.items():
                live = self._generations.get(key, 0)
                if entry.generation != live:
                    bad.append((key, entry.generation, live, entry.value))
        bad.sort(key=lambda row: str(row[0]))
        return bad

    def stats(self):
        with self._lock:
            counters = self.metrics.snapshot()
            counters["entries"] = len(self._entries)
            counters["cancelled"] = len(self._cancelled)
            counters["failed_jobs"] = len(self._failures)
            return counters

    # ----------------------------------------------------------------- write

    def begin(self, key):
        """Snapshot ``key`` before producing a value for it."""
        with self._lock:
            generation = self._generations.get(key, 0)
        trace("store.after_snapshot", key=key, generation=generation)
        return Snapshot(key, generation)

    def commit(self, snapshot, value):
        """Publish ``value`` for ``snapshot.key``.

        Returns ``True`` when the value became visible.
        """
        trace(
            "store.before_commit",
            key=snapshot.key,
            generation=snapshot.generation,
        )
        with self._lock:
            self._entries[snapshot.key] = Entry(value, snapshot.generation)
            self.metrics.incr("commits")
            return True

    def invalidate(self, key):
        """Bump ``key``'s generation and drop any published value."""
        with self._lock:
            generation = self._generations.get(key, 0) + 1
            self._generations[key] = generation
            self._entries.pop(key, None)
            self.metrics.incr("invalidations")
        trace("store.after_invalidate", key=key, generation=generation)
        return generation

    def mark_cancelled(self, job_ids):
        with self._lock:
            for job_id in job_ids:
                self._cancelled.add(job_id)
                self.metrics.incr("cancelled")
            return len(self._cancelled)

    def is_cancelled(self, job_id):
        with self._lock:
            return job_id in self._cancelled

    def record_failure(self, job_id, exc):
        with self._lock:
            self._failures[job_id] = repr(exc)
            self.metrics.incr("failures")

    def failures(self):
        with self._lock:
            return dict(self._failures)

    def clear(self):
        with self._lock:
            self._entries.clear()
            self._generations.clear()
            self._cancelled.clear()
            self._failures.clear()
        self.metrics.reset()

    # ----------------------------------------------------------- compound op

    @contextlib.contextmanager
    def transaction(self):
        """Hold the store lock across several store calls.

        Intended for *short* compound read-modify-write sequences.  Every other
        reader and writer of the store -- including cancellation bookkeeping and
        invalidation -- is blocked for as long as the transaction is open, so
        never wrap slow or user supplied code in one.
        """
        with self._lock:
            yield self
