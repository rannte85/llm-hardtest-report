# Durable job lease incident

`JobQueue` stores JSON-object jobs in a SQLite database shared by independent queue
instances. A worker claims one available job for a bounded lease and receives a
monotonically increasing integer fencing token. Only the current, unexpired
`(worker, token)` owner may heartbeat or complete that job.

The public API is:

- `JobQueue(database_path, clock)` where `clock()` returns finite numeric seconds;
- `enqueue(job_id, payload, priority=0, created_at=None)`;
- `claim(worker, lease_seconds)`, returning `None` or a mapping containing `id`,
  `payload`, `priority`, `created_at`, `lease_token`, and `lease_until`;
- `heartbeat(job_id, worker, lease_token, lease_seconds)`, returning the new boundary;
- `complete(job_id, worker, lease_token)`, returning `True`.

Inputs use non-empty string job/worker IDs, JSON objects, integer priorities, finite
timestamps, positive finite lease lengths, and positive integer fencing tokens.
Duplicate job IDs are errors and must never replace an existing job. Availability at
the lease boundary is inclusive. Claims order jobs by descending priority, then
ascending creation time, then ascending ID. Successful completion is permanent.
Databases created by the shipped schema may lack a fencing-token column; opening them
must upgrade in place without losing, reopening, or replacing queued/completed rows.

The process may crash at any point and another `JobQueue` instance may use the same
database. Correctness therefore comes from a SQLite transaction, not a Python lock or
process-local cache. Busy conditions may be retried by SQLite's bounded timeout, but
the API must not spin forever. Cross-host databases and distributed clock
synchronization are outside this API.
