#!/usr/bin/env python3
"""Hidden grading tests for q27 (race condition).

Usage:  python3 hidden_tests.py [path/to/repo]

Two families of checks:

  H*  correctness -- a value derived from an invalidated generation must never
      become observable, forced deterministically with tracepoint gates.
  T*  trap        -- the fix must not be "serialize everything".  A pool sized
      for N must still run N jobs at once, and the control-plane operations
      (invalidate / cancel_pending / stats) must stay responsive while jobs run.

Nothing here imports anything outside the standard library.
"""

import os
import sys
import threading
import time
import traceback

def _v4_report(qid):
    """Load the grader's result recorder by ABSOLUTE PATH, before any candidate
    code is imported.  Walks upward from hidden/ through grader-private
    directories only, so it cannot be hijacked and does not use sys.path."""
    import importlib.util
    directory = os.path.dirname(os.path.abspath(__file__))
    while True:
        candidate = os.path.join(directory, "v4_hidden_report.py")
        if os.path.isfile(candidate):
            spec = importlib.util.spec_from_file_location("_v4_hidden_report", candidate)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.new(qid)
        parent = os.path.dirname(directory)
        if parent == directory:
            raise RuntimeError("v4_hidden_report.py not found above %s" % __file__)
        directory = parent


# Must happen BEFORE the candidate's package is imported below: the Recorder
# is created immediately so the os.write/stdout references v4_hidden_report.py
# captures are bound before candidate code can run.  Its handle is then pulled
# out of this module's globals right away -- kept alive only inside
# _get_recorder's default-argument cell -- so that a candidate which searches
# vars(sys.modules['__main__']) for an object exposing record()/publish()
# (measured to work here, see README's Threat Model section) finds nothing at
# top level; main() below recovers it as a pure local via _get_recorder().
# This raises that one bar; it does not and cannot stop a candidate that walks
# frames or hooks sys.setprofile/settrace instead -- those reach local
# variables directly and no in-process defence stops them (see README).
_recorder = _v4_report("q27")
_get_recorder = (lambda _r=_recorder: _r)
del _recorder

REPO = os.path.abspath(
    sys.argv[1]
    if len(sys.argv) > 1
    else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "repo")
)
sys.path.insert(0, REPO)

from taskhub import TaskHub  # noqa: E402
from taskhub.store import ResultStore  # noqa: E402
from taskhub.tracepoints import BarrierController, set_controller  # noqa: E402
from taskhub.worker import Job, WorkerPool  # noqa: E402

# Any fix that keeps a control-plane call waiting this long has serialized the
# system.  A healthy implementation answers in microseconds.
RESPONSIVENESS_BUDGET = 0.60
LONG_JOB = 2.0


def _off_thread(fn):
    thread = threading.Thread(target=fn, daemon=True)
    thread.start()
    return thread


def _wait_until(predicate, timeout=5.0, interval=0.002):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _spin(n=120):
    total = 0
    for i in range(n):
        total += i * i
    return total


# --------------------------------------------------------------------------
# H1 -- the plain interleaving: snapshot, invalidate, commit.
# --------------------------------------------------------------------------


def h1_stale_commit_after_snapshot_is_not_observable():
    controller = BarrierController()
    gate = controller.gate("store.after_snapshot", count=1, timeout=5.0)
    set_controller(controller)
    hub = TaskHub(workers=2).start()
    try:
        hub.submit("k", lambda: "value-from-generation-0")
        assert gate.wait_arrival(5.0), (
            "no producer reached the store.after_snapshot tracepoint; the "
            "tracepoint seam documented in docs/DESIGN.md was removed or moved"
        )
        invalidation = _off_thread(lambda: hub.invalidate("k"))
        invalidation.join(RESPONSIVENESS_BUDGET)
        gate.release()
        invalidation.join(5.0)

        assert hub.drain(10.0) is True, "hub never drained"
        got = hub.get("k")
        assert got is None, (
            "a value computed from generation 0 is observable after "
            "generation 0 was invalidated: %r" % (got,)
        )
        assert hub.stale_entries() == [], (
            "invariant G violated: %r" % (hub.stale_entries(),)
        )
        assert hub.generation("k") == 1
    finally:
        set_controller(None)
        controller.release_all()
        hub.shutdown()


# --------------------------------------------------------------------------
# H2 -- the narrow interleaving: the invalidation lands *after* a producer has
# decided to publish.  Only a check performed atomically with the write itself
# catches this one.
# --------------------------------------------------------------------------


def h2_invalidation_racing_the_publish_itself():
    controller = BarrierController()
    gate = controller.gate("store.before_commit", count=1, timeout=5.0)
    set_controller(controller)
    hub = TaskHub(workers=2).start()
    try:
        hub.submit("k", lambda: "value-from-generation-0")
        assert gate.wait_arrival(5.0), (
            "no producer reached the store.before_commit tracepoint; the "
            "tracepoint seam documented in docs/DESIGN.md was removed or moved"
        )
        invalidation = _off_thread(lambda: hub.invalidate("k"))
        invalidation.join(RESPONSIVENESS_BUDGET)
        gate.release()
        invalidation.join(5.0)

        assert hub.drain(10.0) is True, "hub never drained"
        got = hub.get("k")
        assert got is None, (
            "an invalidation that landed while the producer was publishing was "
            "lost; stale value still observable: %r" % (got,)
        )
        assert hub.stale_entries() == []
    finally:
        set_controller(None)
        controller.release_all()
        hub.shutdown()


# --------------------------------------------------------------------------
# H3 -- the same interleaving straight against the store, no pool involved.
#
# This is also the test that separates a real fix from a cosmetic one.  Hiding
# stale values on the way *out* -- filtering them in get()/entry()/
# stale_entries() -- satisfies every "is it observable?" check in this file
# while the unconditional write in commit() is still there.  The second half of
# H3 pins the write down instead, using only public behaviour: a commit that
# carries a retired generation must not reach the store at all, and the way to
# see that from outside is that it must not be able to overwrite what the live
# generation has already published.
# --------------------------------------------------------------------------


def h3_store_level_stale_commit_is_refused():
    store = ResultStore()
    store.commit(store.begin("a"), "gen0")
    snapshot = store.begin("a")
    assert snapshot.generation == 0
    store.invalidate("a")
    store.commit(snapshot, "computed-before-the-invalidation")
    # Asked before anyone reads "a": an implementation that only cleans the
    # stale value up once somebody happens to look at the key has deferred the
    # problem to the reader, not refused the commit.
    assert store.stale_entries() == [], (
        "the value from the retired generation is sitting in the store waiting "
        "for a reader to notice it: %r" % (store.stale_entries(),)
    )
    assert store.get("a") is None, (
        "commit() published a value carrying a generation that is no longer "
        "live: %r" % (store.entry("a"),)
    )
    assert store.stale_entries() == []
    assert store.generation("a") == 1

    # ---- the write has to be refused, not the read ------------------------
    #
    #   gen 0  a producer takes a snapshot and then goes away for a long time
    #   gen 1  the key is invalidated, and a fresh value is published for it
    #   gen 0  the original producer finally comes back and commits
    #
    # The late commit is a no-op on a store that checks the generation while it
    # writes.  On a store that still writes unconditionally it lands on top of
    # the live value and destroys it -- and no read-side filter can put that
    # value back, because it is gone from the store.  Nothing here depends on
    # how the fix is spelled or on which file it lives in.
    store = ResultStore()
    late = store.begin("b")
    assert late.generation == 0
    store.invalidate("b")
    fresh = store.begin("b")
    assert fresh.generation == 1
    store.commit(fresh, "published-by-generation-1")
    assert store.get("b") == "published-by-generation-1", (
        "a value produced *after* the invalidation was not published: %r"
        % (store.entry("b"),)
    )

    store.commit(late, "computed-before-the-invalidation")

    assert store.get("b") == "published-by-generation-1", (
        "a commit carrying a retired generation destroyed the value the live "
        "generation had already published (now %r).  Two ways to get here: "
        "(1) the stale write reached the store and overwrote it -- filtering "
        "stale values out of the read path hides the stale value but cannot "
        "undo this, which is what separates a real fix from a cosmetic one; "
        "(2) the write was refused, but the live entry was dropped along with "
        "it.  Either way: the generation check belongs atomically with the "
        "write, and a refused commit must leave the live entry alone."
        % (store.get("b"),)
    )
    live = store.entry("b")
    assert live is not None and live.generation == 1, (
        "the live entry for 'b' did not survive a stale commit: %r" % (live,)
    )
    assert store.stale_entries() == []
    assert store.generation("b") == 1


# --------------------------------------------------------------------------
# H4 -- the fix must not be "never publish anything".
# --------------------------------------------------------------------------


def h4_fresh_values_are_still_published():
    hub = TaskHub(workers=4).start()
    try:
        for n in range(24):
            hub.submit("k%d" % n, (lambda n=n: (_spin(), n)[1]))
        assert hub.drain(10.0) is True
        values = [hub.get("k%d" % n) for n in range(24)]
        assert values == list(range(24)), "results went missing: %r" % (values,)

        # ... and re-publishing after an invalidation must work.
        hub.invalidate("k0")
        hub.submit("k0", lambda: "recomputed")
        assert hub.drain(10.0) is True
        assert hub.get("k0") == "recomputed", (
            "a value produced *after* the invalidation was rejected: %r"
            % (hub.entry("k0"),)
        )
        assert hub.entry("k0").generation == 1
        assert hub.stale_entries() == []
    finally:
        hub.shutdown()


# --------------------------------------------------------------------------
# H5 -- aggressive stress; on an unfixed build this trips essentially always.
# --------------------------------------------------------------------------


def h5_stress_never_exposes_a_stale_generation():
    keys = ["s%d" % i for i in range(4)]
    for attempt in range(10):
        hub = TaskHub(workers=4).start()
        stop = threading.Event()
        seen = []

        def invalidator():
            while not stop.is_set():
                for key in keys:
                    hub.invalidate(key)
                time.sleep(0.0002)

        def watchdog():
            while not stop.is_set():
                stale = hub.stale_entries()
                if stale:
                    seen.append(stale)
                    return
                time.sleep(0.0002)

        threads = [_off_thread(invalidator), _off_thread(watchdog)]
        try:
            for n in range(120):
                key = keys[n % len(keys)]

                def fn(key=key, n=n):
                    for _ in range(4):
                        _spin()
                        time.sleep(0)
                    _spin()
                    return (key, n)

                hub.submit(key, fn)
            assert hub.drain(10.0) is True
            stop.set()
            for thread in threads:
                thread.join(5.0)
            stale = seen[0] if seen else hub.stale_entries()
            assert stale == [], (
                "attempt %d exposed a value from an invalidated generation: %r"
                % (attempt + 1, stale)
            )
        finally:
            stop.set()
            hub.shutdown()


# --------------------------------------------------------------------------
# H6 -- raw store state, inspected directly through ``_entries`` /
# ``_generations`` rather than through any store method.
#
# H3 closed "filter the read path instead of refusing the write" by making a
# late commit destroy a value the live generation had already published. That
# still leaves two related shapes open, both found by independent
# verification against near-miss fixes that pass H1-H5 and T1-T5 at 10/10:
#
#   * a store that writes a retired-generation value into a key that
#     currently has NO live entry (post-invalidation, before any republish)
#     and hides it behind a read-side filter -- get()/entry() report None
#     correctly, but the value physically sits in ``_entries`` for as long as
#     nobody happens to call a store method that filters it out.  stats()
#     computed off ``len(self._entries)`` (see docs/DESIGN.md) leaks it as a
#     phantom row even when every read-path filter is doing its job.
#   * a store that keeps ``commit()`` fully unconditional and "undoes" a
#     stale write by restoring a one-deep backup at read time.  A single
#     late commit round-trips correctly (the backup holds the live value),
#     but the backup slot is only one deep: a SECOND late commit against the
#     same stale snapshot overwrites the backup with the first stale value,
#     and the live value it was protecting is gone from both the entry and
#     the backup, permanently -- with nobody having called get() in between.
#
# Neither shape needs concurrency to reproduce: both are deterministic, single
# threaded, pure sequences of public store calls.  The discriminator is where
# the assertion looks -- directly at ``store._entries`` / ``store._generations``,
# never through ``entry()``, ``get()`` or ``stale_entries()``, all three of
# which a masking store is free to make lie.  A commit's return value is
# checked against that same raw state: ``True`` must mean the raw dict shows
# exactly the committed value under the snapshot's generation, and ``False``
# must mean the raw dict is byte-for-byte unchanged.
# --------------------------------------------------------------------------


def h6_raw_store_state_has_no_ghost_rows():
    # ---- Part 1: a stale commit into a key with no live entry -------------
    store = ResultStore()
    snap0 = store.begin("a")
    assert snap0.generation == 0
    store.invalidate("a")  # generation -> 1; "a" has no entry at all now
    raw_before = dict(store._entries)
    assert "a" not in raw_before

    ret = store.commit(snap0, "stale-into-empty-slot")
    raw_after = dict(store._entries)

    # P1 -- the return value has to match what the raw store actually shows,
    # under the generation the snapshot carried (not whatever generation is
    # live "now" -- publishing under a false generation is not "becoming
    # visible", it's a different bug wearing this test's success message).
    if ret:
        got = raw_after.get("a")
        assert (
            got is not None
            and got.value == "stale-into-empty-slot"
            and got.generation == snap0.generation
        ), (
            "commit() returned True but the raw store does not show the "
            "committed value under the snapshot's generation: %r" % (got,)
        )
    else:
        assert raw_after.get("a") == raw_before.get("a"), (
            "commit() returned False but the raw store changed anyway: "
            "before=%r after=%r" % (raw_before.get("a"), raw_after.get("a"))
        )

    # P6 -- nobody has called get()/entry()/stale_entries() yet.  Check the
    # dictionaries directly: a retired-generation value must not be sitting
    # in the store waiting for a read to notice (or clean up) it.
    got = raw_after.get("a")
    live = store._generations.get("a", 0)
    assert got is None or got.generation == live, (
        "a retired-generation value is physically sitting in the store "
        "before any reader looked at it: %r (live generation is %d) -- a "
        "read-side filter that hides this from get()/entry() is not a fix, "
        "it is the write bug with a curtain in front of it" % (got, live)
    )

    # P2 -- stats()["entries"] is documented as coming straight off
    # ``len(self._entries)``.  A ghost row nobody can legitimately observe
    # must not inflate it.
    assert store.stats()["entries"] == 0, (
        "stats()['entries'] reports %d row(s) for a key with no live value "
        "-- a phantom entry that every read-path filter hides is still "
        "there for anything that counts instead of reading" % (store.stats()["entries"],)
    )

    # ---- Part 2: a second late commit must not destroy a live value -------
    #
    #   gen 0   a producer snapshots "b" and goes away
    #   gen 1   "b" is invalidated, and a fresh value is published for it
    #   gen 0   the original producer's late commit arrives -- once
    #   gen 0   ... and then arrives AGAIN (a retry, a duplicate delivery, a
    #           second worker that raced the same snapshot)
    #
    # A store that "fixes" a stale write by remembering one prior value and
    # restoring it at read time survives the first late commit (the backup
    # holds the live value) but not the second: the backup itself gets
    # overwritten by the first stale value before anything ever reads it, and
    # the live value is gone from every slot the store has.
    store = ResultStore()
    late = store.begin("b")
    assert late.generation == 0
    store.invalidate("b")
    fresh = store.begin("b")
    assert fresh.generation == 1
    store.commit(fresh, "live-v1")
    assert store.get("b") == "live-v1"

    store.commit(late, "late-1")
    assert store.get("b") == "live-v1", (
        "a single late commit already destroyed the live value: %r"
        % (store.get("b"),)
    )
    store.commit(late, "late-2")
    assert store.get("b") == "live-v1", (
        "a SECOND late commit carrying the same retired generation destroyed "
        "a live value that had survived the first one -- restoring a stale "
        "write from a one-deep backup at read time is not the same as "
        "refusing the write: %r" % (store.get("b"),)
    )
    live_entry = store.entry("b")
    assert (
        live_entry is not None
        and live_entry.generation == 1
        and live_entry.value == "live-v1"
    ), "the live entry for 'b' did not survive two stale commits: %r" % (live_entry,)
    assert store.stale_entries() == []
    assert store.stats()["entries"] == 1


# --------------------------------------------------------------------------
# H7 -- the check inside commit() has to share ITS LOCK ACQUISITION with the
# write, not merely live in the same function.
#
# A commit() that reads the live generation under one lock, releases it, and
# only then takes a *different* lock to perform the write is not atomic: an
# invalidate() that lands in the gap between those two acquisitions is lost,
# exactly like Trap 3 (the non-atomic check in worker._run), just moved one
# level down.  H1/H2's tracepoint gates cannot see this: they park a producer
# at ``store.before_commit``, which fires before commit() has done anything,
# and by the time the gate releases, the concurrent invalidate() has already
# run to completion -- the check then correctly sees the bumped generation
# regardless of whether it shares a lock with the write.  There is no
# tracepoint *inside* commit() to gate on without dictating its internals, so
# this test forces the race the only way that does not assume a particular
# implementation shape: real concurrent threads, hammered hard enough, for
# long enough, that the gap gets hit if it exists at all.
#
# Every round below uses a FRESH key, so a hit is not a transient state that
# a later operation could paper over -- once a stale value physically lands
# next to a bumped generation, nothing on that key ever touches it again, and
# the mismatch is still sitting there when every thread has stopped and the
# raw dictionaries are read back, quiescent, with no other thread running.
# That is what makes a single post-hoc scan sound: at no point does this test
# read store internals while another thread might still be mutating them.
#
# Calibration (measured against a two-lock near-miss commit(), 250k rounds
# per attempt): every one of 30 consecutive attempts landed at least 10 stale
# rows (median well over 50); a real same-lock CAS landed 0 in every one of
# 30 consecutive attempts, and stayed at 0 against three structurally
# different atomic implementations (a helper-method indirection, a commit()
# that re-enters the RLock through generation(), and a per-key RLock
# discipline shared between commit() and invalidate()).  See SOLUTION.md.
# --------------------------------------------------------------------------


def h7_commit_check_and_write_are_not_separately_locked():
    rounds = 250000
    old_switchinterval = sys.getswitchinterval()
    sys.setswitchinterval(0.000001)
    try:
        store = ResultStore()
        keys = ["race-%d" % i for i in range(rounds)]
        barrier = threading.Barrier(2)

        def committer():
            for key in keys:
                barrier.wait()
                snap = store.begin(key)
                store.commit(snap, "stale")

        def invalidator():
            for key in keys:
                barrier.wait()
                store.invalidate(key)

        t1 = threading.Thread(target=committer)
        t2 = threading.Thread(target=invalidator)
        t1.start()
        t2.start()
        t1.join(120.0)
        t2.join(120.0)
        assert not t1.is_alive() and not t2.is_alive(), (
            "the race harness itself did not finish -- environment too slow "
            "or too loaded to trust this run"
        )

        # Quiescent now: both racer threads have already joined, so this is a
        # single-threaded read, exactly like H3's raw-state checks.
        bad = []
        for key in keys:
            entry = store._entries.get(key)
            live = store._generations.get(key, 0)
            if entry is not None and entry.generation != live:
                bad.append((key, entry.generation, live))
    finally:
        sys.setswitchinterval(old_switchinterval)

    assert bad == [], (
        "a stale commit landed while a concurrent invalidate() ran in the "
        "gap between commit()'s check and its write -- the check and the "
        "write are not under the same lock acquisition (%d/%d rounds hit, "
        "e.g. %r)" % (len(bad), rounds, bad[:5])
    )


# --------------------------------------------------------------------------
# T1 -- a pool of 4 must still run 4 jobs at the same time.
# --------------------------------------------------------------------------


def t1_pool_still_runs_jobs_concurrently():
    hub = TaskHub(workers=4).start()
    rendezvous = threading.Barrier(4)
    outcome = []

    def fn():
        try:
            rendezvous.wait(timeout=3.0)
            outcome.append(True)
        except threading.BrokenBarrierError:
            outcome.append(False)
        return "ok"

    try:
        for n in range(4):
            hub.submit("c%d" % n, fn)
        hub.drain(10.0)
        assert outcome == [True] * 4, (
            "a pool of 4 no longer runs 4 jobs concurrently (rendezvous "
            "results %r) -- the fix serializes job execution" % (outcome,)
        )
    finally:
        rendezvous.abort()
        hub.shutdown()


# --------------------------------------------------------------------------
# T2 -- invalidate() must not wait for a running job.
# --------------------------------------------------------------------------


def t2_invalidate_stays_responsive_while_a_job_runs():
    hub = TaskHub(workers=2).start()
    started = threading.Event()
    release = threading.Event()

    def slow():
        started.set()
        release.wait(LONG_JOB)
        return "slow"

    try:
        hub.submit("k", slow)
        assert started.wait(5.0), "slow job never started"
        time.sleep(0.05)
        began = time.monotonic()
        hub.invalidate("k")
        elapsed = time.monotonic() - began
        release.set()
        hub.drain(10.0)
        assert elapsed < RESPONSIVENESS_BUDGET, (
            "invalidate() blocked for %.2fs behind a running job (budget "
            "%.2fs) -- the fix holds a lock across user code"
            % (elapsed, RESPONSIVENESS_BUDGET)
        )
    finally:
        release.set()
        hub.shutdown()


# --------------------------------------------------------------------------
# T3 -- cancellation must not wait for a running job either.
# --------------------------------------------------------------------------


def t3_cancel_pending_stays_responsive():
    hub = TaskHub(workers=2).start()
    started = threading.Event()
    release = threading.Event()

    def slow():
        started.set()
        release.wait(LONG_JOB)
        return "slow"

    try:
        hub.submit("a", slow)
        hub.submit("b", slow)
        assert started.wait(5.0), "slow jobs never started"
        time.sleep(0.05)
        ids = [hub.submit("q%d" % n, lambda: 1) for n in range(10)]
        assert _wait_until(lambda: hub.pool.pending == 10, 5.0), (
            "queued jobs never showed up as pending (pending=%r)"
            % (hub.pool.pending,)
        )
        began = time.monotonic()
        dropped = hub.cancel_pending()
        elapsed = time.monotonic() - began
        release.set()
        hub.drain(10.0)
        assert dropped == 10, "expected 10 cancellations, got %r" % (dropped,)
        assert all(hub.store.is_cancelled(i) for i in ids)
        assert elapsed < RESPONSIVENESS_BUDGET, (
            "cancel_pending() blocked for %.2fs behind a running job (budget "
            "%.2fs) -- the fix holds a lock across user code"
            % (elapsed, RESPONSIVENESS_BUDGET)
        )
    finally:
        release.set()
        hub.shutdown()


# --------------------------------------------------------------------------
# T4 -- so must the metrics read used by the health endpoint.
# --------------------------------------------------------------------------


def t4_stats_stays_responsive():
    hub = TaskHub(workers=2).start()
    started = threading.Event()
    release = threading.Event()

    def slow():
        started.set()
        release.wait(LONG_JOB)
        return "slow"

    try:
        hub.submit("k", slow)
        assert started.wait(5.0), "slow job never started"
        time.sleep(0.05)
        began = time.monotonic()
        stats = hub.stats()
        elapsed = time.monotonic() - began
        release.set()
        hub.drain(10.0)
        assert isinstance(stats, dict)
        assert elapsed < RESPONSIVENESS_BUDGET, (
            "stats() blocked for %.2fs behind a running job (budget %.2fs) -- "
            "the fix holds a lock across user code"
            % (elapsed, RESPONSIVENESS_BUDGET)
        )
    finally:
        release.set()
        hub.shutdown()


# --------------------------------------------------------------------------
# T5 -- the retry / cancellation plumbing must survive the fix untouched.
# --------------------------------------------------------------------------


def t5_retry_and_cancellation_semantics_intact():
    from taskhub.retry import PermanentError, RetryPolicy

    store = ResultStore()
    calls = []
    pool = WorkerPool(
        store, retry=RetryPolicy(max_attempts=3, base_delay=0.0), size=2
    ).start()
    try:
        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise RuntimeError("transient")
            return "eventually"

        pool.submit(Job("flaky", flaky))
        assert pool.drain(10.0) is True
        assert store.get("flaky") == "eventually", (
            "a job that succeeded on its third attempt did not publish: %r"
            % (store.entry("flaky"),)
        )
        assert store.stats()["retries"] == 2

        hard = []

        def permanent():
            hard.append(1)
            raise PermanentError("no")

        pool.submit(Job("hard", permanent))
        assert pool.drain(10.0) is True
        assert len(hard) == 1
        assert store.get("hard") is None
    finally:
        pool.shutdown()


TESTS = [
    ("H1 stale commit after snapshot", h1_stale_commit_after_snapshot_is_not_observable),
    ("H2 invalidation racing the publish", h2_invalidation_racing_the_publish_itself),
    ("H3 store-level stale commit refused", h3_store_level_stale_commit_is_refused),
    ("H4 fresh values still published", h4_fresh_values_are_still_published),
    ("H5 stress exposes no stale generation", h5_stress_never_exposes_a_stale_generation),
    ("H6 raw store state has no ghost rows", h6_raw_store_state_has_no_ghost_rows),
    ("H7 commit check-and-write share one lock acquisition", h7_commit_check_and_write_are_not_separately_locked),
    ("T1 pool still concurrent", t1_pool_still_runs_jobs_concurrently),
    ("T2 invalidate responsive", t2_invalidate_stays_responsive_while_a_job_runs),
    ("T3 cancel_pending responsive", t3_cancel_pending_stays_responsive),
    ("T4 stats responsive", t4_stats_stays_responsive),
    ("T5 retry semantics intact", t5_retry_and_cancellation_semantics_intact),
]


def main():
    recorder = _get_recorder()
    print("hidden tests against %s" % REPO)
    failures = []
    for name, fn in TESTS:
        began = time.monotonic()
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failures.append((name, traceback.format_exc()))
            recorder.record(name, False)
            print("FAIL  %-42s (%.2fs)  %s" % (name, time.monotonic() - began, exc))
        else:
            recorder.record(name, True)
            print("pass  %-42s (%.2fs)" % (name, time.monotonic() - began))
    print("")
    recorder.publish()
    print("")
    for name, tb in failures:
        print("-" * 60)
        print(name)
        print(tb)
    passed = len(TESTS) - len(failures)
    print("HIDDEN: %d/%d passed" % (passed, len(TESTS)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
