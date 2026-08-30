"""``schedule()`` — eligibility, ranking, capacity."""

from .model import DONE, PENDING, RUNNING, SchedulerConfig
from .policy import rank


def _done_ids(jobs):
    return set(j.job_id for j in jobs if j.state == DONE)


def is_eligible(job, now, done_ids):
    """R1, R3, R5, R14 — may this job be considered for a start at ``now``?"""
    if job.state != PENDING:
        return False
    if job.not_before > now:
        return False
    for dep in job.depends_on:
        if dep not in done_ids:
            return False
    return True


def schedule(jobs, now, config=None):
    """Return the ids to start at ``now``, in the order they should start.

    ``jobs`` is the whole queue: pending, running and terminal jobs alike.
    Nothing in ``jobs`` and nothing in ``config`` is mutated (R11).
    """
    if config is None:
        config = SchedulerConfig()

    if config.paused:
        return []

    jobs = list(jobs)

    running = [j for j in jobs if j.state == RUNNING]
    capacity = config.max_concurrency - len(running)
    if capacity <= 0:
        return []

    done_ids = _done_ids(jobs)
    candidates = [j for j in jobs if is_eligible(j, now, done_ids)]

    tenant_used = {}
    for j in running:
        tenant_used[j.tenant] = tenant_used.get(j.tenant, 0) + 1

    started = []
    for job in rank(candidates, now, config):
        if len(started) >= capacity:
            break
        used = tenant_used.get(job.tenant, 0)
        if used >= config.max_per_tenant:
            # R6 — skip this candidate, keep filling the tick.
            continue
        tenant_used[job.tenant] = used + 1
        started.append(job.job_id)

    return started
