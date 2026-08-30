# jobq — deterministic job scheduler core

`jobq` decides **which pending jobs start next**. It does not execute them: the
worker pool calls `schedule()` once per tick and starts whatever ids come back,
in the order they come back.

```python
from scheduler import Job, SchedulerConfig, schedule

ids = schedule(jobs, now=12, config=SchedulerConfig(max_concurrency=4))
```

## Repository layout

| path                    | what it is                                              |
| ----------------------- | ------------------------------------------------------- |
| `scheduler/model.py`    | `Job`, `SchedulerConfig`, `requeue()`                    |
| `scheduler/policy.py`   | priority + ordering rules                                |
| `scheduler/engine.py`   | `schedule()` — eligibility, ordering, capacity           |
| `tests/`                | the acceptance tests, run via `run_tests.py`             |
| `docs/product_spec.md`  | the product specification (normative)                    |
| `docs/issue_412.md`     | incident record INC-412 and the decision that came of it |
| `docs/operations.md`    | operator-facing notes for the queue                      |
| `CHANGELOG.md`          | what shipped when                                        |

Run the acceptance tests with:

```
python3 run_tests.py
```

## Vocabulary

* **tick** — an integer logical clock. `now` is a tick. There is no wall clock
  anywhere in the scheduler; this is deliberate (see R10).
* **priority band** — all jobs sharing the same priority value. **Lower numbers
  are more urgent**: priority `0` is the most urgent band, `9` the least.
* **attempt** — `0` for a job that has never been started, `1` after its first
  failure-and-requeue, `2` after the second, and so on.

## Requirements

These are the rules `schedule()` implements. They are numbered `R1`–`R14` and
the product specification refers to them by number.

**R1 — states.** A job is in exactly one of `pending`, `running`, `done`,
`failed`, `cancelled`. Only `pending` jobs are candidates to start.

**R2 — priority bands first.** An eligible job in a more urgent band (lower
priority value) always starts before an eligible job in a less urgent band.

**R3 — release time.** A job with `not_before > now` is not eligible. At
`not_before == now` it becomes eligible.

**R4 — global concurrency.** At most `config.max_concurrency` jobs may be in
the `running` state at any moment. Jobs already `running` count against the
budget, so a tick returns at most `max_concurrency - len(running)` ids.

**R5 — dependencies.** A job is eligible only when *every* id in its
`depends_on` is a job in state `done`. An unknown id is never satisfied. A
dependency that ends `failed` or `cancelled` therefore blocks its dependents
forever; unblocking that is an operator action, not a scheduler action.

**R6 — per-tenant fairness.** At most `config.max_per_tenant` jobs of any one
tenant may run concurrently. When a candidate's tenant is already at its cap the
scheduler **skips that candidate and keeps going** down the ranking — it does
not stop filling the tick.

**R7 — ordering inside a band.** Within a priority band, eligible jobs start in
FIFO order of `enqueued_at`; ties are broken by ascending `job_id`.

**R8 — pause.** When `config.paused` is set, `schedule()` returns an empty list
regardless of anything else.

**R9 — starvation guard.** If an eligible job has been waiting at least
`config.starvation_ticks` — that is, `now - enqueued_at >= config.starvation_ticks`
— then its **effective** priority for ordering purposes is `max(0, priority - 1)`.
The promotion is worth **at most one band**, no matter how long the job has
waited, and it is an ordering-time computation only: `job.priority` itself is
never mutated.

**R10 — determinism.** For identical inputs `schedule()` returns an identical
list. No randomness, no wall clock, no dependence on the order in which jobs
appear in the input sequence.

**R11 — purity.** `schedule()` never mutates the jobs it is given, and never
mutates the config. Callers reuse both across ticks.

**R12 — no partial bands.** The scheduler fills a tick greedily from the top of
the ranking. It never holds capacity back "so that a whole band can start
together".

**R13 — requeue.** When a failed job is retried it is **requeued**: `attempt` is
incremented and `enqueued_at` is set to the tick at which the requeue happens.
`scheduler.model.requeue()` does this and returns a new `Job`; the old object is
left alone (R11).

**R14 — terminal states are inert.** `done`, `failed` and `cancelled` jobs are
never returned by `schedule()` and never consume capacity.

## Status

R1–R8 and R10–R14 are implemented and covered by `tests/`. R9 is specified but
not yet implemented — see `CHANGELOG.md`.
