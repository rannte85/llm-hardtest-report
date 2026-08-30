from taskhub.retry import PermanentError, RetryPolicy
from taskhub.store import ResultStore
from taskhub.worker import Job, WorkerPool

from tests.support import spin


def test_pool_runs_every_job():
    store = ResultStore()
    pool = WorkerPool(store, size=3).start()
    try:
        for n in range(12):
            pool.submit(Job("k%d" % n, (lambda n=n: (spin(), n)[1])))
        assert pool.drain(5.0) is True
        assert [store.get("k%d" % n) for n in range(12)] == list(range(12))
    finally:
        pool.shutdown()


def test_failing_job_is_retried_then_recorded():
    store = ResultStore()
    calls = []
    pool = WorkerPool(
        store, retry=RetryPolicy(max_attempts=3, base_delay=0.0), size=2
    ).start()

    def always_fails():
        calls.append(1)
        raise RuntimeError("boom")

    try:
        pool.submit(Job("bad", always_fails))
        assert pool.drain(5.0) is True
        assert len(calls) == 3
        assert store.stats()["retries"] == 2
        assert store.stats()["jobs_failed"] == 1
        assert store.get("bad") is None
    finally:
        pool.shutdown()


def test_permanent_error_is_not_retried():
    store = ResultStore()
    calls = []
    pool = WorkerPool(store, retry=RetryPolicy(max_attempts=5), size=1).start()

    def hard_fail():
        calls.append(1)
        raise PermanentError("nope")

    try:
        pool.submit(Job("bad", hard_fail))
        assert pool.drain(5.0) is True
        assert len(calls) == 1
    finally:
        pool.shutdown()


def test_cancel_pending_drops_queued_jobs():
    store = ResultStore()
    pool = WorkerPool(store, size=2)  # deliberately not started yet
    ids = [pool.submit(Job("q%d" % n, lambda: 1)) for n in range(6)]
    assert pool.cancel_pending() == 6
    pool.start()
    try:
        assert pool.drain(3.0) is True
        assert all(store.is_cancelled(i) for i in ids)
        assert [store.get("q%d" % n) for n in range(6)] == [None] * 6
    finally:
        pool.shutdown()


def test_duplicate_completion_is_claimed_once():
    store = ResultStore()
    pool = WorkerPool(store, size=1)
    job = Job("dup", lambda: "v")
    assert pool._claim_completion(job.job_id) is True
    assert pool._claim_completion(job.job_id) is False
