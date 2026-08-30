"""Bounded worker pool.

Jobs are plain callables tagged with a store key.  A worker snapshots the key,
runs the callable, and publishes the result.  Failures go through
:class:`~taskhub.retry.RetryPolicy`; a retried job is put back on the same
queue, so the same job object can be executed more than once.
"""

import itertools
import queue
import threading
import time

from .retry import RetryPolicy
from .tracepoints import trace

__all__ = ["Job", "WorkerPool"]

_job_ids = itertools.count(1)


class Job:
    __slots__ = ("job_id", "key", "fn", "attempts")

    def __init__(self, key, fn, job_id=None):
        self.job_id = job_id if job_id is not None else next(_job_ids)
        self.key = key
        self.fn = fn
        self.attempts = 0

    def __repr__(self):
        return "Job(id=%d, key=%r, attempts=%d)" % (
            self.job_id,
            self.key,
            self.attempts,
        )


class WorkerPool:
    def __init__(self, store, retry=None, size=4, name="pool"):
        if size < 1:
            raise ValueError("size must be >= 1")
        self.store = store
        self.retry = retry if retry is not None else RetryPolicy()
        self.size = size
        self.name = name
        self.metrics = store.metrics

        self._queue = queue.Queue()
        self._threads = []
        self._stopping = threading.Event()
        self._cv = threading.Condition()
        self._pending = 0
        self._inflight = 0
        self._completed = set()
        self._completed_lock = threading.Lock()
        self._started = False

    # ------------------------------------------------------------ lifecycle

    def start(self):
        if self._started:
            return self
        self._started = True
        for index in range(self.size):
            thread = threading.Thread(
                target=self._loop,
                name="%s-%d" % (self.name, index),
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)
        return self

    def shutdown(self, wait=True, cancel=False, timeout=5.0):
        if cancel:
            self.cancel_pending()
        self._stopping.set()
        if wait:
            deadline = time.monotonic() + timeout
            for thread in self._threads:
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    thread.join(remaining)
        self._threads = []
        self._started = False

    # --------------------------------------------------------------- submit

    def submit(self, job):
        with self._cv:
            self._pending += 1
            self._cv.notify_all()
        self._queue.put(job)
        return job.job_id

    def cancel_pending(self):
        """Drop every queued-but-not-started job and record the cancellation."""
        drained = []
        while True:
            try:
                drained.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if drained:
            with self._cv:
                self._pending -= len(drained)
                self._cv.notify_all()
            self.store.mark_cancelled([job.job_id for job in drained])
        return len(drained)

    def drain(self, timeout=5.0):
        """Block until nothing is queued or running.  ``False`` on timeout."""
        deadline = time.monotonic() + timeout
        with self._cv:
            while self._pending or self._inflight:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cv.wait(remaining)
        return True

    @property
    def inflight(self):
        with self._cv:
            return self._inflight

    @property
    def pending(self):
        with self._cv:
            return self._pending

    # ------------------------------------------------------------- internals

    def _loop(self):
        while not self._stopping.is_set():
            try:
                job = self._queue.get(timeout=0.02)
            except queue.Empty:
                continue
            with self._cv:
                self._pending -= 1
                self._inflight += 1
                self._cv.notify_all()
            try:
                self._run(job)
            finally:
                with self._cv:
                    self._inflight -= 1
                    self._cv.notify_all()

    def _run(self, job):
        trace("worker.before_run", job_id=job.job_id, key=job.key)
        snapshot = self.store.begin(job.key)
        try:
            value = job.fn()
        except Exception as exc:  # noqa: BLE001 - retry policy decides
            job.attempts += 1
            if self.retry.should_retry(job.attempts, exc):
                self.metrics.incr("retries")
                delay = self.retry.next_delay(job.attempts)
                if delay > 0:
                    time.sleep(delay)
                self.submit(job)
                return False
            self.metrics.incr("jobs_failed")
            self.store.record_failure(job.job_id, exc)
            return False

        # A retried job can reach this point twice if an earlier attempt was
        # slow to unwind; only the first completion is allowed to publish.
        if not self._claim_completion(job.job_id):
            self.metrics.incr("duplicate_completions")
            return False

        self.store.commit(snapshot, value)
        self.metrics.incr("jobs_done")
        return True

    def _claim_completion(self, job_id):
        with self._completed_lock:
            if job_id in self._completed:
                return False
            self._completed.add(job_id)
            return True
