# Operating the queue

Notes for on-call. Nothing here is normative; the normative documents are
`README.md` (`R` numbers) and `docs/product_spec.md` (`REQ-P` numbers).

## Pausing

`SchedulerConfig(paused=True)` stops new starts on the next tick. In-flight jobs
are untouched — a pause is not a drain. To drain, pause and then wait for
`running` to reach zero.

## Concurrency knobs

| knob               | default | notes                                          |
| ------------------ | ------- | ---------------------------------------------- |
| `max_concurrency`  | `4`     | hard cluster ceiling, includes in-flight work   |
| `max_per_tenant`   | `2`     | per-tenant ceiling, also includes in-flight     |
| `starvation_ticks` | `50`    | age at which a job is promoted one band (`R9`)  |

Raising `max_per_tenant` above `max_concurrency` has no effect: the global
ceiling binds first.

## Reading the queue

The operator console orders the pending list the same way `schedule()` does, so
what you see at the top of the list is what starts next. If the console and the
worker pool ever disagree, trust `schedule()` and file a bug against the console.

The console shows `attempt` in the queue view (INC-412c). A job showing
`attempt 2` has failed twice and is on its third try.

## Bands in use

| band | who                                        |
| ---- | ------------------------------------------ |
| 0    | reserved — manual operator escalation only  |
| 1    | fraud holds                                 |
| 3    | interactive API-triggered work              |
| 5    | settlement **and** the nightly bulk import  |
| 7    | reporting rollups                           |
| 9    | housekeeping, compaction                    |

Band 5 carrying both settlement and the bulk import is known and tracked as
INC-412a. Until that moves, expect band 5 to be deep between 01:00 and 04:00.

## When the queue looks stuck

1. Check `paused`.
2. Check whether the head of the queue is blocked on `depends_on` — a dependency
   that ended `failed` blocks its dependents indefinitely by design (`R5`), and
   this is by far the most common cause.
3. Check per-tenant occupancy before assuming the global ceiling is the binding
   constraint.
