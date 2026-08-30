"""Acceptance tests for eligibility (R1, R3, R5, R14)."""

from scheduler import Job, SchedulerConfig, schedule

WIDE = SchedulerConfig(max_concurrency=8, max_per_tenant=8)


def test_release_time_gates_the_start():
    """R3 — not before ``not_before``, but exactly at it is fine."""
    jobs = [
        Job("future", priority=5, enqueued_at=1, not_before=11),
        Job("now", priority=5, enqueued_at=2, not_before=10),
        Job("past", priority=5, enqueued_at=3, not_before=4),
    ]
    got = schedule(jobs, now=10, config=WIDE)
    assert "future" not in got, got
    assert sorted(got) == ["now", "past"], got


def test_only_pending_jobs_are_started():
    """R1 + R14 — running and terminal jobs are never returned."""
    jobs = [
        Job("run", priority=5, enqueued_at=1, state="running"),
        Job("fin", priority=5, enqueued_at=2, state="done"),
        Job("bad", priority=5, enqueued_at=3, state="failed"),
        Job("gone", priority=5, enqueued_at=4, state="cancelled"),
        Job("go", priority=5, enqueued_at=5),
    ]
    got = schedule(jobs, now=10, config=WIDE)
    assert got == ["go"], got


def test_dependency_must_be_done_first():
    """R5 — every predecessor has to be ``done``."""
    jobs = [
        Job("head", priority=5, enqueued_at=1, state="done"),
        Job("mid", priority=5, enqueued_at=2, depends_on=["head"]),
        Job("tail", priority=5, enqueued_at=3, depends_on=["head", "mid"]),
    ]
    got = schedule(jobs, now=10, config=WIDE)
    assert got == ["mid"], got


def test_unknown_dependency_is_never_satisfied():
    """R5 — an id nobody in the queue carries blocks forever."""
    jobs = [
        Job("orphan", priority=5, enqueued_at=1, depends_on=["nope"]),
        Job("free", priority=5, enqueued_at=2),
    ]
    got = schedule(jobs, now=99, config=WIDE)
    assert got == ["free"], got


def test_failed_dependency_blocks_its_dependent():
    """R5 — a predecessor that ended badly is not ``done``."""
    jobs = [
        Job("upstream", priority=5, enqueued_at=1, state="failed"),
        Job("downstream", priority=5, enqueued_at=2, depends_on=["upstream"]),
        Job("unrelated", priority=5, enqueued_at=3),
    ]
    got = schedule(jobs, now=10, config=WIDE)
    assert got == ["unrelated"], got
