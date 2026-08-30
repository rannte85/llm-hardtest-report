# q27 — intermittent race condition in `taskhub`

## (a) Root cause

**File:** `repo/taskhub/store.py`
**Function:** `ResultStore.commit`
**Lines:** the locked block at the end of `commit` (as shipped, lines 128–131):

```python
    def commit(self, snapshot, value):
        trace("store.before_commit", key=snapshot.key,
              generation=snapshot.generation)
        with self._lock:
            self._entries[snapshot.key] = Entry(value, snapshot.generation)   # <-- here
            self.metrics.incr("commits")
            return True
```

The publish protocol is deliberately split into `begin()` → slow compute →
`commit()`, and `begin()` hands the producer a `Snapshot` carrying the
generation it observed. `commit()` receives that snapshot and then **never
looks at `snapshot.generation`**. It writes unconditionally.

So the interleaving is:

```
worker A   store.begin("k")            -> Snapshot(k, generation=0)
worker A   value = job.fn()            (slow; the GIL is released at an I/O point)
thread B   store.invalidate("k")       -> generation 0 -> 1, entry dropped
worker A   store.commit(snapshot, v)   -> writes Entry(v, generation=0)
```

The invalidation is silently undone: a value derived from generation 0 becomes
observable again after generation 0 was retired, and it stays observable until
the next invalidation happens to clear it. That is exactly the ticket's
"the old value sometimes comes back … it stays visible until the next
invalidation cleans it up again."

`ResultStore._lock` is *not* missing anywhere — every individual read and write
is already properly serialized. The defect is a missing **compare** across the
lock-release window, not a missing lock. That is what makes the wide-lock
"fix" so tempting and so wrong.

Why it is rare: the vulnerable window is between `begin()` and `commit()`, and
a pure-CPU job is essentially never preempted there (CPython's switch interval
is 5 ms, the window is microseconds). It only opens when the job yields the
GIL — i.e. when it touches I/O — and an invalidation for that same key has to
land inside it.

## (b) Correct minimal patch

```diff
--- a/taskhub/store.py
+++ b/taskhub/store.py
@@ class ResultStore:
     def commit(self, snapshot, value):
         """Publish ``value`` for ``snapshot.key``.

         Returns ``True`` when the value became visible.
         """
         trace(
             "store.before_commit",
             key=snapshot.key,
             generation=snapshot.generation,
         )
         with self._lock:
+            live = self._generations.get(snapshot.key, 0)
+            if live != snapshot.generation:
+                self.metrics.incr("stale_commits_rejected")
+                return False
             self._entries[snapshot.key] = Entry(value, snapshot.generation)
             self.metrics.incr("commits")
             return True
```

Five lines, one file, one function. The read of the live generation and the
write of the entry happen inside the *same* `with self._lock:` acquisition, so
this is a genuine compare-and-set: no invalidation can slip between the check
and the write. Nothing is held across `job.fn()`, so concurrency and
control-plane responsiveness are untouched.

The already-correct half of the contract stays correct: after an invalidation a
producer that took a *fresh* snapshot has `snapshot.generation == live` and
publishes normally.

## (c) The traps, and why each is wrong

### Trap 1 — serialize the whole thing (the designed trap)

`docs/DESIGN.md` advertises `ResultStore.transaction()` for compound
read-modify-write sequences, so the obvious move is to wrap the whole job in it:

```python
    def _run(self, job):
        with self.store.transaction():          # <-- holds ResultStore._lock
            snapshot = self.store.begin(job.key)
            value = job.fn()                    # ... across arbitrary user code
            self.store.commit(snapshot, value)
```

The symptom disappears *completely*. Public suite: 19/19 in default mode,
19/19 under `--barrier`, 60/60 clean iterations under `--repeat 60`. There is
no visible signal at all that anything is wrong.

What it actually did:

* the pool no longer runs more than one job at a time, whatever its size (T1);
* `invalidate()`, `cancel_pending()` and `stats()` now queue behind whatever
  job is currently running — a 2 s job makes every control-plane call take 2 s
  (T2, T3, T4);
* and it does not fix the root cause at all. `ResultStore.commit()` is still
  unsafe for every other producer in the system (background refreshers, the
  admin console), which H3 demonstrates by calling the store directly with no
  pool involved.

Measured: hidden **5/10** — *worse than the 6/10 baseline*. The "fix" is a net
regression that the public suite cannot see.

### Trap 2 — re-tag the entry with the live generation

```python
        with self._lock:
            live = self._generations.get(snapshot.key, 0)
            self._entries[snapshot.key] = Entry(value, live)   # wrong
```

The visible invariant check (`stale_entries()`, asserted by
`tests/test_race.py`) compares the entry's generation against the live one, so
stamping the entry with the live generation makes that assertion quiet. The
stale *value* is still served — the bug is untouched, only its detector was
disabled. `--repeat 60` goes 60/60 clean. Measured: hidden **7/10** (H1, H2,
H3 still fail, because they check the value rather than the tag).

### Trap 3 — check, then commit (non-atomic)

```python
        if self.store.generation(job.key) != snapshot.generation:
            return False
        self.store.commit(snapshot, value)
```

This is the right idea in the wrong place. It passes the whole public suite
*including the deterministic `--barrier` repro*, because that gate parks the
producer at `store.after_snapshot`, well before the check. But the check
releases `_lock` before `commit()` re-acquires it, so an invalidation landing
in that window is still lost. Measured: hidden **8/10** (H2 catches the
check-to-write window; H3 catches the fact that the store itself is still
unsafe).

### Trap 4 — reject everything

Making `commit()` conservative ("if in doubt, drop it") kills the bug and every
useful behaviour with it. H4 pins this down: fresh values, and recomputes taken
*after* an invalidation, must still be published.

### Trap 5 — mask it on the read side

Leave `commit()` writing unconditionally, and filter the stale entry out again
on the way *out*:

```python
    def _live(self, key):                      # caller holds self._lock
        found = self._entries.get(key)
        if found is not None and found.generation != self._generations.get(key, 0):
            return None                        # ... or pop it, "while we are here"
        return found
```

used from `entry()`, `get()` and `stale_entries()`. Every "is the stale value
observable?" question this suite can ask now answers *no*, and the write that
causes the defect is still there, untouched. Two shapes were built and
measured — **drop-on-read** (a read evicts the stale entry as a side effect)
and **pure filter** (nothing is mutated, the stale entry is simply never handed
out). Both scored public 19/19 in default mode, 19/19 under `--barrier`,
60/60 under `--repeat 60`, and — before H3 was strengthened — **hidden 10/10**,
without going anywhere near `ResultStore.commit`.

The second half of H3 closes it, on observable behaviour rather than on the
shape of the patch. A write that still lands does not just become invisible,
it **destroys what the live generation had already published**:

```
gen 0   a producer snapshots "b" and goes away
gen 1   "b" is invalidated, and a fresh value is published for it
gen 0   the original producer finally commits
```

With the CAS the late commit is a no-op and `get("b")` is still the generation-1
value. With a read-side filter the late write overwrites the live entry and
`get("b")` returns `None` — the filter can hide the stale value but cannot put
back the good one. Measured: both masking variants **hidden 9/10** (H3), 40
consecutive runs each, no variance. A fix that filters the read path *and*
refuses the stale write still scores 10/10; only filtering *instead of*
refusing fails.

**Known false negative, measured.** A `commit()` that does perform the atomic
compare-and-set but *also* pops the live entry on a mismatch —

```python
            if live != snapshot.generation:
                self._entries.pop(snapshot.key, None)   # "reject and be safe"
                return False
```

— scores **10/12** (H3, H6; 5 runs). The live generation's published value does
not survive an unrelated late producer's commit, so a stale actor can evict a
hot, valid cache key. That is a real if milder defect, and it is not the
reference patch, which touches nothing on the mismatch path — but it is a
different failure from read-side masking, so H3's and H6's assertion messages
name both shapes and a human grader adjudicating an H3/H6-only failure should
read them.

### Round 3 — three more near-misses, found by independent verification

All three of the traps below reproduced hidden **10/10** against the H1–H5 /
T1–T5 suite above, with public green in every mode (`default`, `--barrier`,
`--repeat 60`), before H6 and H7 were added. None of them touch the root
cause; each closes off exactly the observable behaviour the existing suite
happened to probe, and leaves a different, still-reachable way for a value
from a retired generation to end up readable or to destroy a value that
replaced it.

#### Trap 6 — the check lives inside `commit()`, but under a different lock

```python
    def __init__(self, metrics=None):
        self._lock = threading.RLock()
        self._check_lock = threading.RLock()      # looks like a second safety net
        ...

    def commit(self, snapshot, value):
        trace("store.before_commit", key=snapshot.key,
              generation=snapshot.generation)
        with self._check_lock:
            live = self._generations.get(snapshot.key, 0)
            if live != snapshot.generation:
                self.metrics.incr("stale_commits_rejected")
                return False
        with self._lock:                            # <-- different lock, released
            self._entries[snapshot.key] = Entry(value, snapshot.generation)
            self.metrics.incr("commits")
            return True
```

This is the most convincing near-miss in the family: the compare genuinely
lives inside `commit()` now, exactly where the root-cause writeup says it
belongs, and `docs/DESIGN.md`'s tracepoint contract is intact (`trace()` still
fires at the top of `commit()`, before either lock). It reads as a fix to
anyone checking "does the check happen in `commit()`, before the write" — the
literal wording of a shallow root-cause description.

Why H1/H2 do not catch it: both gate a producer at `store.before_commit`,
i.e. before this `commit()` has touched either lock, and then wait for a
concurrent `invalidate()` to run to *completion* before releasing the gate.
By the time the check finally runs, the generation bump has already fully
happened — the check correctly sees it and correctly rejects, regardless of
whether the check and the write share a lock. The bug only shows up when an
`invalidate()` lands **inside** the gap between the check's lock release and
the write's lock acquisition, and nothing in this codebase can point a
tracepoint at a gap that only exists inside a candidate's own reimplementation
of `commit()`.

Reproduced with a real concurrent race (`H7`, see below): 250,000 rounds, each
against a fresh key so a hit cannot be overwritten by later activity before it
is observed, landed a stale value **13–185 times per run across every one of
30 consecutive attempts** — zero misses. Measured: hidden **11/12** (H7 only;
H6 correctly does not fire, because nothing about this trap writes into an
empty slot or double-backs a value — the *shape* it fails is specifically the
same-lock-acquisition contract).

#### Trap 7 — undo instead of refuse (`mask_undo`)

`commit()` stays fully unconditional. Instead of guarding the write, it backs
up whatever was in the slot before overwriting it, and a reader restores that
backup if the current entry turns out to be stale:

```python
    def commit(self, snapshot, value):
        trace(...)
        with self._lock:
            old = self._entries.get(snapshot.key)
            if old is not None:
                self._shadow[snapshot.key] = old
            self._entries[snapshot.key] = Entry(value, snapshot.generation)
            self.metrics.incr("commits")
            return True

    def _live(self, key):                      # caller holds self._lock
        found = self._entries.get(key)
        live = self._generations.get(key, 0)
        if found is not None and found.generation != live:
            backup = self._shadow.pop(key, None)
            if backup is not None and backup.generation == live:
                self._entries[key] = backup     # "undo" the stale write
                return backup
            self._entries.pop(key, None)
            return None
        return found
```

A *single* late commit round-trips correctly: the backup holds the live
value, and the very next read restores it. That is exactly the interleaving
H3's second half exercises, so H3 passes. The backup is only **one slot
deep**. A second late commit against the same retired snapshot — a retry, a
duplicate delivery, a second worker racing the same snapshot — overwrites the
backup with the *first* stale value before anything has read it, and the live
value is now gone from both the entry and the backup, permanently, with no
read having happened yet. `docs/DESIGN.md`'s invariant G ("stale_entries()
must always come back empty") is even satisfied at that point, because
`stale_entries()` is rewritten to run every key through `_live()` first —
the corruption already happened; there is nothing left to flag as stale.

Measured: hidden **10/12**, failure set `{H6, H7}`. H6 is the direct hit —
the second late commit destroying the live value is exactly H6's Part 2. H7
also fires, for an unrelated reason: `commit()` here is fully unconditional
(no check of any kind), so on the fresh keys H7 races, the write always lands
regardless of timing, exactly like the baseline and the naive traps that never
touch `commit()` at all. That is not a false positive against a "same lock"
claim this trap never makes — it is H7 correctly recognising that a store
with no compare-and-set has no atomicity property to test in the first place.
Not caught by H1/H2/H3/H4/H5.

#### Trap 8 — a partial write guard plus a read filter (`mask_anticlobber`)

```python
    def commit(self, snapshot, value):
        trace(...)
        with self._lock:
            existing = self._entries.get(snapshot.key)
            if existing is not None and existing.generation > snapshot.generation:
                self.metrics.incr("stale_commits_rejected")
                return False
            self._entries[snapshot.key] = Entry(value, snapshot.generation)
            self.metrics.incr("commits")
            return True
```

...combined with the same read-side filter as Trap 5 on `entry()` / `get()` /
`stale_entries()`. The guard condition is real, but it only fires when there
is something in the slot to compare against. It happens to cover exactly the
case H3's second half exercises (a late commit arriving after a fresher value
has already been published: `existing.generation` is the fresher one, greater
than the late commit's, rejected) — and the read filter covers H1/H2/H3's
first half (a late commit landing in a key with nothing published yet: the
filter hides it from every read). Together the two halves happen to close
every gap this suite's H1–H5 checked. What neither half covers: a late commit
landing in a key that was invalidated and has **no published entry at all**
(`existing is None`, the guard's comparison never triggers) — the write lands,
physically, in `_entries`; the read filter then hides it from `get()` /
`entry()`, and `stale_entries()`'s own filtered rewrite hides it from that too.
`len(self._entries)`, which `stats()` reports from directly, does not go
through the filter and leaks the phantom row as a real "entries" count.

Measured: hidden **10/12**, failure set `{H6, H7}`. H6 is the direct hit —
precisely H6 Part 1: raw `_entries` state inspected directly, bypassing
`get()`/`entry()`/`stale_entries()`, plus the `stats()["entries"]` ghost-row
check. H7 also fires: on the fresh keys it races, `existing` is always `None`
(nothing has ever been published for a brand-new key), so the write guard's
comparison never triggers and the write proceeds unconditionally, the same as
any implementation with no working check at all on that specific interleaving
— the write path here IS a single critical section under `self._lock`, so
this is not a split-lock hit, it is the same "no atomicity to test" case as
Trap 7 above. Not caught by H1–H5.

## (d) Measured results

`python3 verify_trap.py --repeat 60`, all numbers from actual runs on temporary
copies of `repo/`. The masking rows and Round 3's three near-misses come from
the same harness with their respective patches added. The hidden suite is now
**12 tests** (H1–H7, T1–T5); every row below is against the current suite.

| state | public (default) | public `--barrier` | public `--repeat 60` (clean iters) | hidden |
| --- | --- | --- | --- | --- |
| baseline (no patch) | **19/19** | **18/19** | **52–59/60** (band, see below) | **6/12** |
| naive: wide lock across compute | 19/19 | 19/19 | 60/60 | **5/12** |
| naive: re-tag entry with live generation | 19/19 | 18/19 | 60/60 | **8/12** |
| naive: non-atomic check before commit (worker-level) | 19/19 | 19/19 | 60/60 | **8/12** |
| masking: read-side filter (both shapes) | 19/19 | 19/19 | 60/60 | **9/12** |
| probe: CAS that pops the live entry on mismatch | 19/19 | 19/19 | 60/60 | **10/12** |
| Trap 6: `commit_toctou` (check inside `commit()`, split lock) | 19/19 | 19/19 | 60/60 | **11/12** |
| Trap 7: `mask_undo` (one-deep shadow, restore-on-read) | 19/19 | 19/19 | 60/60 | **10/12** |
| Trap 8: `mask_anticlobber` (partial write guard + read filter) | 19/19 | 19/19 | 60/60 | **10/12** |
| **correct: generation CAS inside `commit`** | **19/19** | **19/19** | **60/60** | **12/12** |

Hidden failures per state:

* baseline — H1, H2, H3, H5, H6, H7
* wide lock — H3, H6, H7, **T1, T2, T3, T4**
* re-tag — H1, H2, H3, H6 (**H7 passes** — retag is a single-lock write, just
  stamped with the wrong generation; H7 only tests the same-lock-acquisition
  property, not correctness of *what* is written)
* non-atomic check (worker-level) — H2, H3, H6, H7 (H7 fires here too: this
  trap never touches `store.py`, so `commit()` is still the pristine
  unconditional version that H7 races directly)
* read-side masking (drop-on-read *and* pure filter) — H3, H6, H7
* CAS-that-pops — H3, H6 (**H7 passes** — this is a real same-lock CAS; its
  defect is unrelated to the property H7 checks)
* `commit_toctou` — **H7 only** (a real, if split-lock, compare-and-set: on
  H7's fresh keys the check does run and does reject most of the time, so H6
  passes; only the narrow race window trips it)
* `mask_undo` — H6, H7 (H7 fires for the same reason as the naive traps
  above: `commit()` here has no check at all, so H7's fresh-key race lands a
  stale write on effectively every round, same as baseline)
* `mask_anticlobber` — H6, H7 (`existing` is always `None` for H7's fresh
  keys, so the write guard never triggers there either — same "no atomicity
  to test" case as `mask_undo`, by a different route)
* correct — none

### Stability

H1–H6 are fully deterministic (tracepoint gates or single-threaded sequences
of store calls; no timing dependency), so their failure sets do not vary
run to run. Measured over the states above: consistent every run.

H7 is the one probabilistic component in the suite, so it got the dedicated
scrutiny: **30 consecutive full runs**, both directions:

| target | metric | result |
| --- | --- | --- |
| `commit_toctou` (should fail H7 every time) | misses (0 stale rows found) | **0/30** — every run found stale rows, range 13–185 per run, N=250,000 rounds |
| reference correct CAS (should never fail H7) | false positives | **0/30** |

Also checked against the reference fix run inside the full, integrated
`hidden_tests.py` (not the isolated harness above) and against `commit_toctou`
the same way, **10/10** consecutive full-suite runs each, scores exactly
**12/12** and **11/12** respectively every time.

Pre-existing stability claim for H1–H5/T1–T5 (unchanged by this round): **40
consecutive runs per state, 280 runs total, zero variance**.

| state | score | failure set | runs |
| --- | --- | --- | --- |
| baseline | 6/12 | `{H1, H2, H3, H5, H6, H7}` | 5/5 |
| wide lock | 5/12 | `{H3, H6, H7, T1, T2, T3, T4}` | 5/5 |
| re-tag | 8/12 | `{H1, H2, H3, H6}` | 5/5 |
| non-atomic check | 8/12 | `{H2, H3, H6, H7}` | 5/5 |
| masking A (drop-on-read) | 9/12 | `{H3, H6, H7}` | 5/5 |
| masking B (pure filter) | 9/12 | `{H3, H6, H7}` | 5/5 |
| CAS-that-pops | 10/12 | `{H3, H6}` | 5/5 |
| `commit_toctou` | 11/12 | `{H7}` | 10/10 (integrated) |
| `mask_undo` | 10/12 | `{H6}` | 5/5 |
| `mask_anticlobber` | 10/12 | `{H6}` | 5/5 |
| correct | 12/12 | `{}` | 10/10 (integrated) + 30/30 (H7 isolated) |

### False-positive check against structurally different correct fixes

H6 and H7 were run against three implementations that are all genuine
compare-and-set fixes but structured differently from the reference patch, to
check neither new test overfits to the reference's exact code shape:

1. the reference patch itself (single `with self._lock:` block);
2. the same check, moved into a private helper method that `commit()` calls
   (`return self._try_publish(snapshot, value)`);
3. the check re-entering the lock through the public `generation()` accessor
   instead of touching `self._generations` directly (relies on `self._lock`
   being an `RLock`);
4. a **per-key locking discipline**: a lazily-created `threading.RLock()` per
   key, acquired by both `commit()` and `invalidate()` for that key, wrapped
   around the same generation check — genuinely different granularity from
   the reference's single global lock.

All four: public 19/19 / 19/19, hidden **12/12**, H7 measured at **0 stale
rows** across 5 runs each (per-key variant included).

H1, H2 and H3 are deterministic by construction — they force the interleaving
with tracepoint gates rather than sampling it, and H3 is single-threaded
throughout, including the Trap 5 discriminator.

### The `--repeat` numbers are a band, not a constant

Clean-iteration counts for `run_tests.py --repeat 60` on the **unpatched**
repo, 8 consecutive runs on one machine:

```
56/60  59/60  58/60  58/60  59/60  59/60  59/60  57/60
```

An independent measurement campaign on the same repo produced `52/60`,
`59/60`, `59/60`, and two later `verify_trap.py` runs drew `55/60` and
`58/60`. Pooled band over those 13 runs: **52–59 clean of 60**, every value in
`{52, 55, 56, 57, 58, 59}` observed. Quote it as a band. An earlier
draft of this file quoted `55/60` as if it were *the* number — it is a single
draw from this band, and anyone who re-measures gets something else and reads
it as a regression.

Other measured baseline rates:

* `run_tests.py` default, 10 consecutive runs: **19/19 ×8, 18/19 ×2**.
* `run_tests.py --barrier`, 10 consecutive runs: **18/19 every time** — the
  only deterministic public repro.
* `run_tests.py --repeat 100`, 3 runs: **95/100, 98/100, 97/100**.
* `tests/test_race.py` alone, `--repeat 100 test_race`, 8 runs:
  `91, 95, 94, 97, 95, 95, 95, 97` → **41 failures / 800 iterations = 5.1 %**
  per iteration. The independent campaign measured **12/300 = 4.0 %** for the
  same test, and a much older 500-iteration campaign measured 2.4 %; the honest
  statement is a **2–6 % per-iteration band that moves with machine load**.
* Pooled over every full-suite iteration measured here (480 + 300 + 10 = 790):
  **27 failing iterations = 3.4 %**.

### `--repeat` is a trap for the *grader*, not just the model

At 20 iterations the baseline usually reads as perfectly healthy:
`run_tests.py --repeat 20` on the unpatched repo came back **20/20 clean in 7
of 8 runs** (the eighth was 19/20), and a live `verify_trap.py --repeat 20`
printed `20/20` for *every* state, baseline included — a table in which the
unpatched repo and the correct fix are indistinguishable in all three public
columns. Read that on its own and the defect looks like it does not reproduce
under `--repeat` at all. It does; 20 iterations is simply below the resolution
of a ~3–5 % per-iteration failure rate. Do not lower the harness default, and
do not conclude anything from a clean `--repeat 20`.

The deterministic reproduction path is `--barrier` (18/19, every run), and it is
also the one the task actually rewards: the prompt demands a regression test
that fails on the unfixed code *deterministically*, so a model that only ever
gets there by looping `--repeat` has not met requirement 4 even if it stumbles
onto the right patch.

## Reproduction paths available to the model

1. `python3 run_tests.py --barrier` — deterministic, 18/19, fails every time
   (10/10 runs measured). The flag is documented in `--help` and used by
   `tests/test_race.py`. **This is the path the task rewards.**
2. `python3 run_tests.py --repeat 100` — measured 95–98 clean of 100, i.e. it
   reproduces on essentially every run, but only because 100 iterations is
   enough; `--repeat 20` usually looks clean (see above).
3. Build a gate directly on `taskhub.tracepoints` (`store.after_snapshot`,
   `store.before_commit`), which is what a deterministic regression test has to
   do anyway.

The prompt mentions none of these.
