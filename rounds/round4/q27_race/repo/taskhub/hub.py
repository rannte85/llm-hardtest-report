"""Facade tying the store, the retry policy and the worker pool together."""

from .metrics import Metrics
from .retry import RetryPolicy
from .store import ResultStore
from .worker import Job, WorkerPool

__all__ = ["TaskHub"]


class TaskHub:
    def __init__(self, workers=4, retry=None, store=None, name="hub"):
        self.metrics = Metrics()
        self.store = store if store is not None else ResultStore(self.metrics)
        self.retry = retry if retry is not None else RetryPolicy()
        self.pool = WorkerPool(
            self.store, retry=self.retry, size=workers, name=name
        )

    # ------------------------------------------------------------ lifecycle

    def start(self):
        self.pool.start()
        return self

    def shutdown(self, wait=True, cancel=False, timeout=5.0):
        self.pool.shutdown(wait=wait, cancel=cancel, timeout=timeout)

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc, tb):
        self.shutdown(cancel=True)
        return False

    # ---------------------------------------------------------------- work

    def submit(self, key, fn):
        return self.pool.submit(Job(key, fn))

    def drain(self, timeout=5.0):
        return self.pool.drain(timeout)

    def cancel_pending(self):
        return self.pool.cancel_pending()

    # --------------------------------------------------------------- state

    def invalidate(self, key):
        return self.store.invalidate(key)

    def get(self, key, default=None):
        return self.store.get(key, default)

    def entry(self, key):
        return self.store.entry(key)

    def generation(self, key):
        return self.store.generation(key)

    def keys(self):
        return self.store.keys()

    def stats(self):
        return self.store.stats()

    def stale_entries(self):
        """Keys whose published entry does not belong to the live generation.

        This must always be empty -- see the invariant in ``docs/DESIGN.md``.
        """
        return self.store.stale_entries()
