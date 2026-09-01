# Bounded asynchronous fan-out incident

`map_concurrently(items, worker, max_concurrency=4, timeout=1.0)` runs one async
`worker(item)` call for every input item and returns its results in input order.

The input is a finite synchronous iterable. Materialize and validate it before any
worker starts, preserve duplicate positions as independent calls, and return `[]`
without calling the worker for an empty input. `worker` must be callable;
`max_concurrency` must be a positive integer other than `bool`; `timeout` must be a
finite positive `int` or `float` other than `bool`. Invalid input raises
`TypeError`/`ValueError` before child-task creation.

At most `max_concurrency` worker calls may be active. An item's timeout starts only
after it owns a concurrency slot, immediately before invoking its worker; time spent
queued for a slot is not charged. A timed-out worker is cancelled and fully awaited.
Results retain input order regardless of completion order.

The operation is fail-fast. On the first worker exception or per-item
`asyncio.TimeoutError`, cancel every active or queued sibling, await all of their
cleanup, then re-raise the original failure unchanged. If the caller cancels
`map_concurrently`, apply the same cancel-and-await cleanup and re-raise
`asyncio.CancelledError`. No task created by the function may still be pending when it
returns or raises, including a worker that briefly catches cancellation to perform
asynchronous cleanup. Independent and nested calls must not share coordination state.

Do not edit `run_tests.py` or `operator_note.txt`.
