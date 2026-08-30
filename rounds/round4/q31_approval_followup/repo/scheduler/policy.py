"""Ranking rules.

``engine.schedule()`` builds the candidate list and then sorts it with
``order_key(job, effective_priority(job, now, config))``.  Everything that
decides *what runs before what* lives here.
"""

#: A job is treated as a retry from this attempt number upward.
RETRY_ATTEMPT_THRESHOLD = 1


def effective_priority(job, now, config):
    """The priority band used for ordering this tick.

    This is an ordering-time computation: whatever it returns, ``job.priority``
    is never written to (R11).
    """
    return job.priority


def order_key(job, priority):
    """Sort key for one candidate, given its effective priority band.

    Bands come first (R2).  Inside a band the ranking is governed by
    ``docs/product_spec.md`` REQ-P7 and by the decision recorded in
    ``docs/issue_412.md``; read both before changing the tie-breaks.

    ``job_id`` is the final tie-break so that the result is stable no matter
    what order the caller handed the jobs to us in (R10).
    """
    retry_rank = 0 if job.attempt >= RETRY_ATTEMPT_THRESHOLD else 1
    return (priority, retry_rank, job.enqueued_at, job.job_id)


def rank(jobs, now, config):
    """Candidates, most-eligible first."""
    return sorted(jobs, key=lambda j: order_key(j, effective_priority(j, now, config)))
