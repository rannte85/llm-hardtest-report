# jobq product specification

Status: **normative**. Owner: Platform / Queueing.
Applies to `scheduler/` at and after 0.4.0.

The `README.md` requirement list (`R1`–`R14`) is the engineering restatement of
this document. Where a requirement here carries a `REQ-P` number it is the
product-level statement of intent; the `R` number is the implementation contract.

---

## REQ-P1 — the scheduler is a pure function of queue state

`schedule(jobs, now, config)` observes state and returns an ordered list of ids.
It performs no I/O, mutates nothing, and is reproducible from its arguments
alone. (`R10`, `R11`.)

## REQ-P2 — urgency is expressed as a band, not as a score

Priority is a small integer band, lower being more urgent. We deliberately do
not expose a continuous score: operators reason about "which band is this in",
and support answers questions in those terms. (`R2`.)

## REQ-P3 — scheduled work does not start early

A job carrying a release time does not start before that tick. This is a
correctness property for billing runs, which must not observe a partially
closed period. (`R3`.)

## REQ-P4 — the cluster is never oversubscribed

The global concurrency ceiling is a hard ceiling and includes work already in
flight. A tick may return fewer ids than there is queue depth; it may never
return more than the remaining budget. (`R4`.)

## REQ-P5 — declared dependencies are honoured

A job whose declared predecessors have not all completed successfully is not a
candidate. We do not attempt to infer intent when a predecessor ends badly: the
dependent stays queued and an operator decides. (`R5`.)

## REQ-P6 — one tenant cannot occupy the cluster

Per-tenant concurrency is capped. A tenant at its cap is passed over and the
tick continues to be filled from the remaining candidates, so one noisy tenant
delays only itself. (`R6`.)

## REQ-P7 — a retried job is ahead of new work in its band

A job with `attempt >= 1` MUST start before every job in the same priority band
that has `attempt == 0`, regardless of enqueue order.

Rationale: a retry represents work a customer is already waiting on and has
already been told is in progress. Placing it behind arbitrarily much newly
arriving work turns a transient failure into an unbounded delay. This
requirement was reaffirmed after INC-412 — see `docs/issue_412.md`.

## REQ-P8 — the queue can be stopped

An operator can pause the queue. A paused queue starts nothing; in-flight work
is unaffected. (`R8`.)

## REQ-P9 — nothing waits forever

Waiting must have a bounded effect on rank. A job that has waited past the
starvation threshold is promoted, and the promotion is bounded so that the band
structure of REQ-P2 is not dissolved by age. (`R9`.)

## REQ-P10 — the tick is filled greedily

Capacity that could be used is used. The scheduler does not reserve capacity for
work that has not arrived, and does not delay a start in order to co-schedule a
group. (`R12`.)

## REQ-P11 — terminal work is invisible to scheduling

Completed, failed and cancelled jobs neither start nor consume budget. (`R14`.)

## REQ-P12 — a requeue is a new arrival

A retry is modelled as a requeue rather than as a resumption: the job re-enters
the queue with an incremented `attempt` and the enqueue tick of the retry.
Modelling it this way keeps `enqueued_at` meaning "when this attempt entered the
queue", which is what the age-based reporting in the operator console displays.
(`R13`.)
