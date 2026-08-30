"""Value types for the scheduler.

Nothing in this module mutates anything; see R11 in the README.
"""

PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"

TERMINAL_STATES = (DONE, FAILED, CANCELLED)
VALID_STATES = (PENDING, RUNNING) + TERMINAL_STATES


class Job(object):
    """A unit of work sitting in the queue.

    Fields
    ------
    job_id      stable identifier, also the final ordering tie-break (R7)
    priority    band; lower is more urgent (R2)
    enqueued_at tick at which *this attempt* entered the queue (R13)
    attempt     0 for a first try, >= 1 for a retry
    not_before  earliest tick at which the job may start (R3)
    tenant      fairness key (R6)
    depends_on  ids that must be ``done`` first (R5)
    state       one of VALID_STATES (R1)
    """

    __slots__ = (
        "job_id",
        "priority",
        "enqueued_at",
        "attempt",
        "not_before",
        "tenant",
        "depends_on",
        "state",
    )

    def __init__(
        self,
        job_id,
        priority=5,
        enqueued_at=0,
        attempt=0,
        not_before=0,
        tenant="default",
        depends_on=(),
        state=PENDING,
    ):
        if state not in VALID_STATES:
            raise ValueError("unknown state: %r" % (state,))
        self.job_id = job_id
        self.priority = priority
        self.enqueued_at = enqueued_at
        self.attempt = attempt
        self.not_before = not_before
        self.tenant = tenant
        self.depends_on = tuple(depends_on)
        self.state = state

    def snapshot(self):
        """Field-by-field copy of the job's state, for equality checks."""
        return tuple(getattr(self, name) for name in self.__slots__)

    def __repr__(self):
        return "Job(%r, priority=%r, enqueued_at=%r, attempt=%r, state=%r)" % (
            self.job_id,
            self.priority,
            self.enqueued_at,
            self.attempt,
            self.state,
        )


class SchedulerConfig(object):
    """Knobs. See docs/operations.md for the defaults table."""

    __slots__ = ("max_concurrency", "max_per_tenant", "starvation_ticks", "paused")

    def __init__(
        self,
        max_concurrency=4,
        max_per_tenant=2,
        starvation_ticks=50,
        paused=False,
    ):
        self.max_concurrency = max_concurrency
        self.max_per_tenant = max_per_tenant
        self.starvation_ticks = starvation_ticks
        self.paused = paused

    def __repr__(self):
        return (
            "SchedulerConfig(max_concurrency=%r, max_per_tenant=%r, "
            "starvation_ticks=%r, paused=%r)"
            % (
                self.max_concurrency,
                self.max_per_tenant,
                self.starvation_ticks,
                self.paused,
            )
        )


def requeue(job, now):
    """R13 — a retry re-enters the queue as a new arrival.

    ``attempt`` goes up by one and ``enqueued_at`` becomes the requeue tick.
    A new ``Job`` is returned; ``job`` is left untouched (R11).
    """
    return Job(
        job_id=job.job_id,
        priority=job.priority,
        enqueued_at=now,
        attempt=job.attempt + 1,
        not_before=job.not_before,
        tenant=job.tenant,
        depends_on=job.depends_on,
        state=PENDING,
    )
