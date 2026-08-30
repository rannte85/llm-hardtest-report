# taskhub design notes

## Pieces

| module           | responsibility                                             |
| ---------------- | ---------------------------------------------------------- |
| `store.py`       | versioned result store (generations + published entries)    |
| `worker.py`      | bounded worker pool, queueing, retry driving, cancellation  |
| `retry.py`       | backoff policy                                              |
| `hub.py`         | facade                                                      |
| `metrics.py`     | counters                                                    |
| `tracepoints.py` | test-only scheduling seam                                   |

## Generations

Each key in the store carries a generation counter starting at 0.
`invalidate(key)` bumps that counter and drops whatever value was published.
A generation number therefore identifies "the version of the world" a value was
derived from.

Publishing is deliberately split in two:

```python
snapshot = store.begin(key)   # observe the generation
value    = expensive()        # may take arbitrarily long
store.commit(snapshot, value) # publish
```

The snapshot is carried through the slow part precisely because the world can
move underneath it. Producers are *not* expected to hold any lock across the
slow part.

The store is the only component that owns generations. The worker pool is one
producer among several — background refreshers and the admin console publish
through `ResultStore.begin()` / `ResultStore.commit()` directly, without going
anywhere near `worker.py` — so whatever `commit()` guarantees is what the
system guarantees.

### Invariant G

> At any quiescent moment, for every key, either no entry is published, or the
> published entry's generation equals the key's live generation.

Equivalently: a value derived from a version of the world that has since been
invalidated must never be observable. `TaskHub.stale_entries()` returns the
keys that violate this; it must always return an empty list.

## Responsiveness requirements

`invalidate()`, `cancel_pending()` and `stats()` are control-plane operations.
They are called from request threads and from shutdown paths, and they are
expected to return promptly *while jobs are running*. The pool is also expected
to actually run `size` jobs concurrently — callers size the pool to their
throughput target.

`ResultStore.transaction()` exists for short compound read-modify-write
sequences. It blocks every other reader and writer of the store, including the
control-plane operations above, so the section it wraps has to stay short.

## Tracepoints

`tracepoints.trace()` is a no-op in production and is the only supported way to
write a reproducible regression test for an interleaving-dependent defect. The
emitted names and their positions are part of the internal test contract —
tests park threads on them. Keep them where they are.

## Known issue

CI goes red on `tests/test_race.py` roughly one run in fifty, always with a
stale entry reported for one of the stress keys. It has never reproduced on a
developer machine on the first try, so it keeps getting re-run and merged.
