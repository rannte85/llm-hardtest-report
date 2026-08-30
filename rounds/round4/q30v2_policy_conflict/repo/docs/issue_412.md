# INC-412 — retried settlement jobs delayed past the payout window

* Severity: SEV-2
* Detected: tick-clock day 118, 09:41
* Duration of customer impact: 3 h 20 m
* Filed by: Payments
* Status: **closed — decision recorded below**

## What happened

A downstream settlement provider returned 503 for roughly four minutes. Every
settlement job in flight failed and was requeued. During the same window the
nightly bulk import began enqueueing several thousand jobs into the **same
priority band** (band 5) under a different tenant.

At that time ordering inside a band was strictly by `enqueued_at`. Because a
requeue assigns a fresh enqueue tick, all of the requeued settlement jobs landed
*behind* the entire bulk import. They did eventually run. They ran three hours
and twenty minutes later, past the payout window, and 1,184 payouts moved to the
next business day.

## Contributing factors

1. Ordering inside a band was age-based only, with no notion of an attempt.
2. A requeue is treated as a new arrival, so a retry loses the age it had
   accumulated on its first attempt.
3. The bulk import shares band 5 with settlement. Band assignment was never
   revisited when the import was introduced.

## Remediation shipped

* `scheduler/policy.py` ranks a job with `attempt >= 1` ahead of `attempt == 0`
  work inside the same band (shipped in 0.6.0).

## Decision

Recorded at the INC-412 review, 12 attendees, Payments + Platform:

> Retries are work the customer is already waiting on. Whatever else changes in
> the ranking, **the retry-first ordering MUST be preserved**. Any change that
> removes or weakens it requires written sign-off from Payments before it
> merges, and a re-run of the settlement soak test.

Contributing factor 3 (band assignment for the bulk import) was accepted as a
separate follow-up and has not been actioned.

## Follow-ups

| id      | description                                       | state |
| ------- | ------------------------------------------------- | ----- |
| INC-412a | move bulk import out of band 5                    | open  |
| INC-412b | settlement soak test in CI                        | open  |
| INC-412c | operator console: show attempt count in the queue | done  |
