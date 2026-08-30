"""Acceptance tests for capacity and fairness (R4, R6, R8, R12)."""

from scheduler import Job, SchedulerConfig, schedule


def test_global_ceiling_limits_the_tick():
    """R4 — never more ids than the ceiling allows."""
    jobs = [Job("j%d" % i, priority=5, enqueued_at=i) for i in range(1, 6)]
    got = schedule(jobs, now=10, config=SchedulerConfig(max_concurrency=2, max_per_tenant=5))
    assert got == ["j1", "j2"], got


def test_running_work_counts_against_the_ceiling():
    """R4 — in-flight jobs eat the budget."""
    jobs = [
        Job("r1", priority=5, enqueued_at=0, tenant="ops", state="running"),
        Job("r2", priority=5, enqueued_at=0, tenant="ops", state="running"),
        Job("p1", priority=5, enqueued_at=1),
        Job("p2", priority=5, enqueued_at=2),
        Job("p3", priority=5, enqueued_at=3),
    ]
    got = schedule(jobs, now=10, config=SchedulerConfig(max_concurrency=3, max_per_tenant=3))
    assert got == ["p1"], got


def test_per_tenant_cap_is_enforced():
    """R6 — one tenant cannot take the whole tick."""
    jobs = [
        Job("acme-1", priority=5, enqueued_at=1, tenant="acme"),
        Job("acme-2", priority=5, enqueued_at=2, tenant="acme"),
        Job("acme-3", priority=5, enqueued_at=3, tenant="acme"),
        Job("acme-4", priority=5, enqueued_at=4, tenant="acme"),
        Job("globex-1", priority=5, enqueued_at=5, tenant="globex"),
    ]
    got = schedule(jobs, now=10, config=SchedulerConfig(max_concurrency=8, max_per_tenant=2))
    assert got == ["acme-1", "acme-2", "globex-1"], got


def test_tenant_at_cap_is_skipped_not_blocking():
    """R6 + R12 — a capped tenant is passed over, the tick keeps filling."""
    jobs = [
        Job("acme-1", priority=5, enqueued_at=1, tenant="acme"),
        Job("acme-2", priority=5, enqueued_at=2, tenant="acme"),
        Job("acme-3", priority=5, enqueued_at=3, tenant="acme"),
        Job("globex-1", priority=5, enqueued_at=4, tenant="globex"),
        Job("initech-1", priority=5, enqueued_at=5, tenant="initech"),
    ]
    got = schedule(jobs, now=10, config=SchedulerConfig(max_concurrency=3, max_per_tenant=1))
    assert got == ["acme-1", "globex-1", "initech-1"], got


def test_paused_queue_starts_nothing():
    """R8 — a pause beats everything else."""
    jobs = [
        Job("urgent", priority=0, enqueued_at=1),
        Job("also-urgent", priority=0, enqueued_at=2),
    ]
    config = SchedulerConfig(max_concurrency=8, max_per_tenant=8, paused=True)
    got = schedule(jobs, now=10, config=config)
    assert got == [], got
