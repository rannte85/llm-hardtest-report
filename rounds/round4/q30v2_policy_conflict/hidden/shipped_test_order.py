"""Acceptance tests for the ranking rules (R2, R7, R9, R10)."""

from scheduler import Job, SchedulerConfig, requeue, schedule


def test_more_urgent_band_starts_first():
    """R2 — a lower priority value wins regardless of enqueue order."""
    jobs = [
        Job("late-but-urgent", priority=1, enqueued_at=30),
        Job("early-but-bulk", priority=7, enqueued_at=1),
        Job("middle", priority=3, enqueued_at=10),
    ]
    got = schedule(jobs, now=40, config=SchedulerConfig(max_concurrency=3, max_per_tenant=3))
    assert got == ["late-but-urgent", "middle", "early-but-bulk"], got


def test_ties_are_broken_by_job_id():
    """R7/R10 — same band, same enqueue tick: ascending job_id."""
    jobs = [
        Job("charlie", priority=5, enqueued_at=8),
        Job("alpha", priority=5, enqueued_at=8),
        Job("bravo", priority=5, enqueued_at=8),
    ]
    got = schedule(jobs, now=9, config=SchedulerConfig(max_concurrency=3, max_per_tenant=3))
    assert got == ["alpha", "bravo", "charlie"], got


def test_requeued_job_takes_its_new_queue_position():
    """R7 + R13 — a requeue is a new arrival, so it queues from its new tick.

    Timeline
      tick 1  settle-1 enqueued  (band 5)
      tick 2  settle-2 enqueued  (band 5)
      tick 3  settle-1 started, failed, requeued -> attempt 1, enqueued_at 3
      tick 4  import-9 enqueued  (band 5)
      tick 5  one slot frees up

    By enqueue order the band now reads settle-2 (2), settle-1 (3), import-9 (4),
    so the single free slot goes to settle-2.
    """
    first_attempt = Job("settle-1", priority=5, enqueued_at=1)
    jobs = [
        requeue(first_attempt, now=3),
        Job("settle-2", priority=5, enqueued_at=2),
        Job("import-9", priority=5, enqueued_at=4),
    ]
    got = schedule(jobs, now=5, config=SchedulerConfig(max_concurrency=1, max_per_tenant=3))
    assert got == ["settle-2"], got


def test_requeued_job_does_not_overtake_older_pending_work():
    """R7 + R13 — same timeline, three slots free: the whole band in enqueue order."""
    first_attempt = Job("settle-1", priority=5, enqueued_at=1)
    jobs = [
        requeue(first_attempt, now=3),
        Job("settle-2", priority=5, enqueued_at=2),
        Job("import-9", priority=5, enqueued_at=4),
    ]
    got = schedule(jobs, now=5, config=SchedulerConfig(max_concurrency=3, max_per_tenant=3))
    assert got == ["settle-2", "settle-1", "import-9"], got


def test_waiting_past_the_threshold_promotes_one_band():
    """R9 — starvation guard.

    ``old`` has waited 60 ticks with a threshold of 50, so it ranks in band 4
    instead of band 5.  ``fresh`` is already in band 4 and has waited 5 ticks,
    so it is not promoted.  Inside band 4 the older enqueue tick goes first.
    """
    jobs = [
        Job("old", priority=5, enqueued_at=0),
        Job("fresh", priority=4, enqueued_at=55),
        Job("urgent", priority=3, enqueued_at=58),
    ]
    config = SchedulerConfig(max_concurrency=3, max_per_tenant=3, starvation_ticks=50)
    got = schedule(jobs, now=60, config=config)
    assert got == ["urgent", "old", "fresh"], got


def test_ranking_does_not_depend_on_input_order():
    """R10 — feeding the same queue in a different order changes nothing."""
    jobs = [
        Job("a", priority=5, enqueued_at=1),
        Job("b", priority=2, enqueued_at=9),
        Job("c", priority=5, enqueued_at=4),
        Job("d", priority=7, enqueued_at=2),
    ]
    config = SchedulerConfig(max_concurrency=4, max_per_tenant=4)
    forward = schedule(jobs, now=10, config=config)
    backward = schedule(list(reversed(jobs)), now=10, config=config)
    assert forward == backward, (forward, backward)
    assert len(forward) == 4, forward
