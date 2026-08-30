#!/usr/bin/env python3
"""Hidden grading tests for q26 (parkbill).

NOT visible to the model under test.  Run by the grader only:

    python3 hidden/hidden_tests.py [path/to/repo]

Exit code 0 when all 7 hidden tests pass.
"""

import os
import sys
import traceback
from datetime import datetime, timedelta

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
_recorder = _v4_report("q26")
_get_recorder = (lambda _r=_recorder: _r)
del _recorder

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_HERE, "..", "repo")
_REPO = os.path.abspath(_REPO)
sys.path.insert(0, _REPO)

from garage import billing, ledger, normalize, rates, scheduler  # noqa: E402
from garage.models import Segment  # noqa: E402

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


def eq(actual, expected, what="value"):
    if actual != expected:
        raise AssertionError(
            "{0}: expected {1!r}, got {2!r}".format(what, expected, actual)
        )


def ok(cond, what):
    if not cond:
        raise AssertionError(what)


def dt(day, hour, minute=0, month=3, year=2026):
    return datetime(year, month, day, hour, minute)


STANDARD = rates.get_rate_card("STANDARD")
COMPACT = rates.get_rate_card("COMPACT")
LARGE = rates.get_rate_card("LARGE")


def closed_stay(stay_id, vehicle_class, start, end, plate="SHINAGAWA500A1234"):
    stay = scheduler.reserve(stay_id, plate, vehicle_class, start, end)
    scheduler.check_in(stay, start)
    scheduler.check_out(stay, end)
    return stay


# ==========================================================================
# H1-H3: invariants that the naive "midnight segments are continuations"
#        patch destroys.  A stay may legitimately BEGIN at 00:00.
# ==========================================================================

@test
def H1_midnight_start_same_day_stay_keeps_its_grace():
    # 00:00 -> 02:00 on one day is a perfectly ordinary stay and it is the
    # FIRST segment, so rule GR-1 grants it the grace allowance.
    #   120min - 30min grace = 90min -> 3 started blocks -> 3 * 300
    stay = closed_stay("H1", "STANDARD", dt(2, 0), dt(2, 2))
    eq(billing.charge_stay(stay), 900, "midnight-start same-day total")


@test
def H2_charge_segment_honours_the_grace_flag_it_is_given():
    # charge_segment must price exactly what the segment says, including a
    # grace segment that happens to begin at midnight.
    #   90min - 30min = 60min -> 2 blocks -> 2 * 300
    seg = Segment(start=dt(2, 0), end=dt(2, 1, 30), grace=True)
    eq(billing.charge_segment(seg, STANDARD), 600, "graced midnight segment")

    # ... and a matching non-grace segment costs strictly more.
    plain = Segment(start=dt(2, 0), end=dt(2, 1, 30), grace=False)
    ok(
        billing.charge_segment(plain, STANDARD)
        > billing.charge_segment(seg, STANDARD),
        "a grace segment must be cheaper than the same segment without grace",
    )


@test
def H3_reprice_of_a_midnight_stay_after_extension():
    book = ledger.Ledger()
    stay = scheduler.reserve("H3", "NERIMA300B0009", "STANDARD", dt(2, 0), dt(2, 1))
    first = book.post_stay(stay)
    #   60min - 30min = 30min -> 1 block -> 300
    eq(first.total, 300, "initial receipt total")

    scheduler.extend(stay, dt(2, 3, 30))
    again = book.reprice(stay)
    #   210min - 30min = 180min -> 6 blocks -> 4*300 + 2*100
    eq(again.total, 1400, "repriced receipt total")
    eq(book.grand_total(), 1400, "ledger grand total after reprice")


# ==========================================================================
# H4-H6: the real invariant — one grace allowance per stay, on the first
#        calendar day of the billing window.
# ==========================================================================

@test
def H4_midnight_start_multi_day_stay_gets_exactly_one_grace():
    # 00:00 Mar 2 -> 02:00 Mar 3
    #   day 2: 1440min - 30min grace = 1410min -> 47 blocks
    #          -> 4*300 + 43*100 = 5500   (under the 6000 cap)
    #   day 3: 120min, no grace -> 4 blocks -> 1200
    stay = closed_stay("H4", "STANDARD", dt(2, 0), dt(3, 2))
    eq(billing.charge_stay(stay), 6700, "midnight-start overnight total")


@test
def H5_ledger_path_prices_an_overnight_stay_like_the_billing_path():
    book = ledger.Ledger()
    stay = closed_stay("H5", "STANDARD", dt(1, 23), dt(2, 2))
    receipt = book.post_stay(stay)
    eq(receipt.total, 1500, "ledger overnight total")
    eq(receipt.total, billing.charge_stay(stay), "ledger vs billing")
    eq(len(receipt.items), 2, "line item count")


@test
def H6_segment_builder_grants_the_grace_allowance_exactly_once():
    windows = [
        (dt(1, 9), dt(1, 17)),        # same day
        (dt(1, 23), dt(2, 2)),        # overnight
        (dt(2, 0), dt(3, 2)),         # starts at midnight, two days
        (dt(1, 22), dt(4, 1)),        # four calendar days
    ]
    for card in (COMPACT, STANDARD, LARGE):
        for (start, end) in windows:
            segs = normalize.build_segments(start, end, card)
            granted = [i for i, s in enumerate(segs) if s.grace]
            eq(
                granted,
                [0],
                "grace segments for {0} {1}".format(
                    card.vehicle_class, normalize.describe_window(start, end)
                ),
            )

    # The receipt must report the same thing to accounting.
    book = ledger.Ledger()
    stay = closed_stay("H6", "STANDARD", dt(1, 22), dt(4, 1))
    receipt = book.post_stay(stay)
    eq(receipt.grace_count, 1, "grace line items on a four-day receipt")
    eq(receipt.total, 12700, "four-day receipt total")


# ==========================================================================
# H7: structural invariants that must survive any fix.
# ==========================================================================

@test
def H7_structural_invariants_hold():
    cards = (COMPACT, STANDARD, LARGE)

    # (a) segments tile the window exactly, never empty, never cross midnight
    for card in cards:
        for (start, end) in [
            (dt(1, 9), dt(1, 17)),
            (dt(1, 23), dt(2, 2)),
            (dt(2, 0), dt(3, 2)),
            (dt(1, 22), dt(4, 1)),
            (dt(1, 9), dt(2, 0)),
        ]:
            segs = normalize.build_segments(start, end, card)
            eq(segs[0].start, start, "first segment start")
            eq(segs[-1].end, end, "last segment end")
            for prev, nxt in zip(segs, segs[1:]):
                eq(prev.end, nxt.start, "segments must be contiguous")
            for seg in segs:
                ok(seg.minutes() > 0, "no empty segment")
                ok(seg.minutes() <= 1440, "no segment longer than a day")
                # (b) per-day cap is never exceeded
                ok(
                    billing.charge_segment(seg, card) <= card.daily_cap,
                    "daily cap exceeded for {0}".format(seg.describe()),
                )

    # (c) total is monotonically non-decreasing in the exit time
    start = dt(1, 22)
    previous = -1
    cursor = start + timedelta(minutes=15)
    limit = dt(3, 3)
    while cursor <= limit:
        total = billing.charge_window(start, cursor, STANDARD)
        ok(
            total >= previous,
            "total dropped when the exit time moved from {0} to {1}".format(
                previous, total
            ),
        )
        previous = total
        cursor += timedelta(minutes=15)

    # (d) the ledger and the billing façade never disagree
    book = ledger.Ledger()
    for idx, (vclass, s, e) in enumerate(
        [
            ("STANDARD", dt(1, 9), dt(1, 11)),
            ("COMPACT", dt(1, 8), dt(1, 8, 20)),
            ("LARGE", dt(1, 20), dt(2, 6)),
            ("STANDARD", dt(1, 22), dt(4, 1)),
        ]
    ):
        stay = closed_stay("H7-{0}".format(idx), vclass, s, e)
        receipt = book.post_stay(stay)
        eq(receipt.total, billing.charge_stay(stay), "ledger vs billing #{0}".format(idx))

    # (e) a cancelled stay is not billable
    cancelled = scheduler.reserve("H7-C", "NERIMA300B0100", "STANDARD", dt(1, 9), dt(1, 10))
    scheduler.cancel(cancelled, dt(1, 8))
    try:
        billing.charge_stay(cancelled)
    except scheduler.TransitionError:
        pass
    else:
        raise AssertionError("a cancelled stay must not produce a charge")


# ==========================================================================

def main():
    recorder = _get_recorder()
    passed = 0
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            failed.append((fn.__name__, exc))
            recorder.record(fn.__name__, False)
            print("HFAIL {0}".format(fn.__name__))
            print("      {0}: {1}".format(type(exc).__name__, exc))
            if not isinstance(exc, AssertionError):
                traceback.print_exc()
        else:
            passed += 1
            recorder.record(fn.__name__, True)
            print("hok   {0}".format(fn.__name__))

    total = len(TESTS)
    print("")
    recorder.publish()
    print("")
    print("HIDDEN SUMMARY: {0}/{1} passed, {2} failed".format(passed, total, len(failed)))
    if failed:
        print("HIDDEN FAILED:")
        for name, exc in failed:
            print("  - {0}: {1}".format(name, exc))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
