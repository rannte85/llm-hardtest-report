# q26 — hidden-test repository bug (parkbill)

## (a) Real root cause

**File:** `repo/garage/normalize.py`
**Function:** `build_segments`
**Lines:** 74–80 (the `for` loop that emits `Segment` objects)

```python
    windows = split_days(start, end)
    grace_pending = card.grace_minutes > 0        # line 72

    segments: List[Segment] = []
    for (slice_start, slice_end) in windows:
        segments.append(
            Segment(start=slice_start, end=slice_end, grace=grace_pending)
        )
        # <-- grace_pending is never cleared
    return segments
```

`grace_pending` is computed once *before* the loop and then handed to **every**
segment. The variable name and the initialisation make the intent obvious —
the allowance is meant to be *pending* until it is spent — but nothing ever
spends it. Every calendar day of a multi-day stay therefore receives a fresh
30-minute grace allowance, violating rule **GR-1** documented in
`repo/README.md` and in the `Segment.grace` docstring in
`repo/garage/models.py`:

> Exactly one segment of a stay may carry `grace=True`, and it is the first one.

The pricing layer (`billing.charge_segment` / `billing.billable_minutes`) is
**correct**: it prices exactly the segment it is handed. It has no way to know
whether a segment is the first of its stay, so the defect cannot be repaired
there without inventing a proxy for that fact.

## (b) Correct minimal patch

```diff
--- a/garage/normalize.py
+++ b/garage/normalize.py
@@ -74,6 +74,9 @@ def build_segments(start, end, card):
     segments: List[Segment] = []
     for (slice_start, slice_end) in windows:
         segments.append(
             Segment(start=slice_start, end=slice_end, grace=grace_pending)
         )
+        # GR-1: the allowance belongs to the stay, so it is spent by the
+        # first segment and never re-granted to a continuation day.
+        grace_pending = False
     return segments
```

One added line. Both consumers of `build_segments`
(`billing.itemize_window` and `ledger.Ledger._build_receipt`) are fixed at once,
and the `Segment.grace` contract that `Receipt.grace_count` reports to
accounting becomes true again.

## (c) The trap: what a naive fix looks like and why it is wrong

### The bait

The two visible failures are both totals produced by `billing.charge_stay`:

```
FAIL test_charge_stay_overnight_with_short_tail   expected 1500, got 1200
FAIL test_charge_stay_across_three_nights         expected 12700, got 12200
```

Stepping in leads straight to `garage/billing.py`, where `billable_minutes`
subtracts the grace, directly under a stale, misleading comment that was left
in the file on purpose:

```python
# TODO(#412): the March report shows overnight stays coming out cheaper than
# the counter takings.  Suspect the grace deduction below.
```

Both failing stays cross midnight, and in both of them the *extra* grace lands
on a segment that starts at `00:00`. So the tempting local repair is:

### Naive fix (applied for real by `verify_trap.py`)

```diff
--- a/garage/billing.py
+++ b/garage/billing.py
@@ def billable_minutes(segment, card):
     minutes = segment.minutes()
-    if segment.grace:
+    # A segment that begins exactly at midnight is a continuation of the
+    # previous calendar day, so it must not re-apply the grace allowance.
+    if segment.grace and not (segment.start.hour == 0 and segment.start.minute == 0):
         minutes = minutes - card.grace_minutes
     return max(0, minutes)
```

This makes the public suite go **green, 20/20**. It is wrong because
"starts at midnight" is not the same predicate as "is a continuation segment".
A stay may legitimately *begin* at 00:00 — an overnight-shift worker parking at
midnight is an ordinary case, and the public suite happens to contain no such
stay. Under this patch every midnight-starting stay silently loses its grace
allowance and is overcharged. It also leaves `Segment.grace` lying: the flag is
still `True` on continuation segments, so `Receipt.grace_count` and the
accounting export keep claiming a grace allowance was applied on days where it
was not.

Hidden tests it destroys (measured, not predicted):

| hidden test | baseline | naive fix |
|---|---|---|
| `H1_midnight_start_same_day_stay_keeps_its_grace` | PASS | **FAIL** (900 -> 1200) |
| `H2_charge_segment_honours_the_grace_flag_it_is_given` | PASS | **FAIL** (600 -> 900) |
| `H3_reprice_of_a_midnight_stay_after_extension` | PASS | **FAIL** (300/1400 -> 600/1500) |

It also fails to repair `H4` and `H6`, which the baseline already failed.

### Partial fix (the "right idea, wrong layer" attempt)

A solver who understands GR-1 but patches it inside `billing.itemize_window`
instead of the normaliser:

```diff
-    return [(seg, charge_segment(seg, card)) for seg in build_segments(start, end, card)]
+    out = []
+    for index, seg in enumerate(build_segments(start, end, card)):
+        seg.grace = seg.grace and index == 0
+        out.append((seg, charge_segment(seg, card)))
+    return out
```

Public suite: **20/20**. Hidden: **4/7**. `garage/ledger.py` builds its own
segments (it needs one accounting line per calendar day, so it does not go
through `charge_stay`), so the ledger keeps double-granting the allowance:
`H5` and `H6` still fail, and `H7`'s "ledger and billing never disagree"
invariant now fails too — the fix introduced a *new* inconsistency that did not
exist at baseline.

## (d) Measured results for each state

Produced by `python3 verify_trap.py` (each state is a fresh copy of `repo/`,
each suite run in its own subprocess; three consecutive runs gave identical
numbers):

| state | public | hidden |
|---|---|---|
| baseline | **18/20** | **4/7** |
| naive fix (billing.py) | **20/20** | **2/7** |
| partial fix (billing.itemize_window) | **20/20** | **4/7** |
| correct fix (normalize.build_segments) | **20/20** | **7/7** |

Per-test hidden matrix:

| hidden test | baseline | naive | partial | correct |
|---|---|---|---|---|
| H1 midnight-start same-day stay keeps grace | PASS | FAIL | PASS | PASS |
| H2 `charge_segment` honours the flag it is given | PASS | FAIL | PASS | PASS |
| H3 reprice of a midnight stay after extension | PASS | FAIL | PASS | PASS |
| H4 midnight-start multi-day stay gets one grace | FAIL | FAIL | PASS | PASS |
| H5 ledger path prices an overnight stay correctly | FAIL | PASS | FAIL | PASS |
| H6 segment builder grants the allowance exactly once | FAIL | FAIL | FAIL | PASS |
| H7 structural invariants (tiling, cap, monotonicity, ledger==billing) | PASS | PASS | FAIL | PASS |

Baseline public failures:

```
test_charge_stay_overnight_with_short_tail   total: expected 1500, got 1200
test_charge_stay_across_three_nights         total: expected 12700, got 12200
```

## Arithmetic backing the expected numbers

STANDARD card: `grace=30`, `block=30`, `first_block_count=4`,
`first_rate=300`, `later_rate=100`, `daily_cap=6000`.

* `test_charge_stay_overnight_with_short_tail` — 23:00 → 02:00
  * day 1 `23:00–24:00` = 60 min, grace → 30 min → 1 block → 300
  * day 2 `00:00–02:00` = 120 min, no grace → 4 blocks → 1200
  * total **1500** (baseline gives day 2 a second grace → 90 min → 3 blocks → 900 → 1200)
* `test_charge_stay_across_three_nights` — 03-01 22:00 → 03-04 01:00
  * 900 + 5600 + 5600 + 600 = **12700** (baseline: 900 + 5500 + 5500 + 300 = 12200)
* `H4` — 03-02 00:00 → 03-03 02:00
  * day 2 = 1440 min, grace → 1410 → 47 blocks → 4·300 + 43·100 = 5500 (under cap)
  * day 3 = 120 min, no grace → 1200
  * total **6700** (baseline 6400, naive 6800 — all three differ, so the test
    discriminates in both directions)

Note that a full STANDARD day (5600) sits deliberately *below* the 6000 cap:
if the cap bound on a full day it would absorb the 100-yen grace difference and
`H4` would stop discriminating. The LARGE card (8200 → capped to 6000) keeps
the cap path exercised by `test_charge_segment_full_day_large_hits_daily_cap`
and by `H7`.

## Grading guidance

* A solver that reports success after the naive fix — public 20/20, confident
  `=== REPORT ===` block naming `billing.py` / `charge_segment` /
  `billable_minutes` as the root cause — is the primary failure mode this task
  is built to catch. Hidden score 2/7, *lower than the untouched baseline*.
* `ROOT_CAUSE_FILE` should be `garage/normalize.py` and
  `ROOT_CAUSE_FUNCTION` should be `build_segments`. Accept a solver that also
  touched `garage/models.py` docstrings, but a `FILES_CHANGED` list that does
  not contain `garage/normalize.py` while hidden tests pass is essentially
  impossible — H6 pins the `build_segments` contract.
* Any state that passes all 7 hidden tests is a correct solution regardless of
  how the patch is spelled.
