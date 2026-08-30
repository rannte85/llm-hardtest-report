#!/usr/bin/env python3
"""Public test runner for parkbill.

Pure standard library.  Run with:

    python3 run_tests.py
"""

import os
import sys
import traceback
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from garage import billing, ledger, normalize, rates, scheduler  # noqa: E402
from garage.models import Segment, StayStatus  # noqa: E402

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


def eq(actual, expected, what="value"):
    if actual != expected:
        raise AssertionError(
            "{0}: expected {1!r}, got {2!r}".format(what, expected, actual)
        )


def raises(exc_type, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc_type:
        return
    except Exception as exc:  # pragma: no cover - diagnostic path
        raise AssertionError(
            "expected {0}, got {1}: {2}".format(exc_type.__name__, type(exc).__name__, exc)
        )
    raise AssertionError("expected {0}, nothing raised".format(exc_type.__name__))


def dt(day, hour, minute=0, month=3, year=2026):
    return datetime(year, month, day, hour, minute)


STANDARD = rates.get_rate_card("STANDARD")
COMPACT = rates.get_rate_card("COMPACT")
LARGE = rates.get_rate_card("LARGE")


# --------------------------------------------------------------------------
# rates
# --------------------------------------------------------------------------

@test
def test_rate_card_standard_fields():
    eq(STANDARD.grace_minutes, 30, "grace_minutes")
    eq(STANDARD.block_minutes, 30, "block_minutes")
    eq(STANDARD.first_block_count, 4, "first_block_count")
    eq(STANDARD.first_block_rate, 300, "first_block_rate")
    eq(STANDARD.later_block_rate, 100, "later_block_rate")
    eq(STANDARD.daily_cap, 6000, "daily_cap")


@test
def test_rate_card_lookup_is_case_insensitive_and_validates():
    eq(rates.get_rate_card(" standard ").vehicle_class, "STANDARD", "normalised lookup")
    raises(rates.UnknownVehicleClass, rates.get_rate_card, "MONSTER_TRUCK")


# --------------------------------------------------------------------------
# models / normalize
# --------------------------------------------------------------------------

@test
def test_segment_shape_and_plate_normalisation():
    seg = Segment(start=dt(1, 9, 15), end=dt(1, 11, 45))
    eq(seg.minutes(), 150, "segment minutes")
    eq(seg.day, dt(1, 0).date(), "segment day")
    eq(normalize.normalize_plate(" shinagawa 500-a 12-34 "), "SHINAGAWA500A1234", "plate")


@test
def test_split_days_same_day_is_single_window():
    windows = normalize.split_days(dt(1, 9), dt(1, 17, 30))
    eq(len(windows), 1, "window count")
    eq(windows[0], (dt(1, 9), dt(1, 17, 30)), "window")


@test
def test_split_days_cuts_at_midnight():
    windows = normalize.split_days(dt(1, 23), dt(2, 2))
    eq(len(windows), 2, "window count")
    eq(windows[0], (dt(1, 23), dt(2, 0)), "first window")
    eq(windows[1], (dt(2, 0), dt(2, 2)), "second window")


@test
def test_split_days_ending_exactly_at_midnight_closes_previous_day():
    windows = normalize.split_days(dt(1, 9), dt(2, 0))
    eq(len(windows), 1, "window count")
    eq(windows[0], (dt(1, 9), dt(2, 0)), "window")


@test
def test_build_segments_slices_every_calendar_day():
    segs = normalize.build_segments(dt(1, 22), dt(4, 1), STANDARD)
    eq(len(segs), 4, "segment count")
    eq([s.minutes() for s in segs], [120, 1440, 1440, 60], "segment lengths")
    eq([s.day.day for s in segs], [1, 2, 3, 4], "segment days")


# --------------------------------------------------------------------------
# billing — segment level
# --------------------------------------------------------------------------

@test
def test_charge_segment_inside_grace_is_free():
    seg = Segment(start=dt(1, 9), end=dt(1, 9, 20), grace=True)
    eq(billing.charge_segment(seg, STANDARD), 0, "charge")


@test
def test_charge_segment_grace_leaves_partial_block():
    seg = Segment(start=dt(1, 9), end=dt(1, 9, 45), grace=True)
    eq(billing.charge_segment(seg, STANDARD), 300, "charge")


@test
def test_charge_segment_without_grace_two_hours():
    seg = Segment(start=dt(1, 9), end=dt(1, 11), grace=False)
    eq(billing.charge_segment(seg, STANDARD), 1200, "charge")


@test
def test_charge_segment_full_day_standard_stays_under_cap():
    seg = Segment(start=dt(2, 0), end=dt(3, 0), grace=False)
    eq(billing.charge_segment(seg, STANDARD), 5600, "charge")


@test
def test_charge_segment_full_day_large_hits_daily_cap():
    seg = Segment(start=dt(2, 0), end=dt(3, 0), grace=False)
    eq(billing.charge_segment(seg, LARGE), LARGE.daily_cap, "charge")


# --------------------------------------------------------------------------
# billing — stay level
# --------------------------------------------------------------------------

def _closed_stay(stay_id, vehicle_class, start, end, plate="SHINAGAWA500A1234"):
    stay = scheduler.reserve(stay_id, plate, vehicle_class, start, end)
    scheduler.check_in(stay, start)
    scheduler.check_out(stay, end)
    return stay


@test
def test_charge_stay_same_day_standard():
    stay = _closed_stay("S-1", "STANDARD", dt(1, 9), dt(1, 11))
    eq(billing.charge_stay(stay), 900, "total")


@test
def test_charge_stay_same_day_compact_inside_grace():
    stay = _closed_stay("S-2", "COMPACT", dt(1, 8), dt(1, 8, 20))
    eq(billing.charge_stay(stay), 0, "total")


@test
def test_charge_stay_overnight_with_short_tail():
    # Entered 23:00, left 02:00 the next day.
    #   day 1: 23:00-24:00 -> 60min, one grace allowance -> 30min -> 1 block
    #   day 2: 00:00-02:00 -> 120min                              -> 4 blocks
    stay = _closed_stay("S-3", "STANDARD", dt(1, 23), dt(2, 2))
    eq(billing.charge_stay(stay), 1500, "total")


@test
def test_charge_stay_across_three_nights():
    # 2026-03-01 22:00 -> 2026-03-04 01:00
    stay = _closed_stay("S-4", "STANDARD", dt(1, 22), dt(4, 1))
    eq(billing.charge_stay(stay), 12700, "total")


# --------------------------------------------------------------------------
# scheduler
# --------------------------------------------------------------------------

@test
def test_scheduler_happy_path_transitions():
    stay = scheduler.reserve("S-5", "NERIMA300B0001", "STANDARD", dt(1, 9), dt(1, 12))
    eq(stay.status, StayStatus.RESERVED, "status after reserve")
    eq(scheduler.billing_window(stay), (dt(1, 9), dt(1, 12)), "reserved window")
    scheduler.check_in(stay, dt(1, 9, 10))
    eq(stay.status, StayStatus.ACTIVE, "status after check-in")
    eq(scheduler.billing_window(stay), (dt(1, 9, 10), dt(1, 12)), "active window")
    scheduler.check_out(stay, dt(1, 11, 40))
    eq(stay.status, StayStatus.CLOSED, "status after check-out")
    eq(scheduler.billing_window(stay), (dt(1, 9, 10), dt(1, 11, 40)), "closed window")


@test
def test_scheduler_rejects_illegal_transitions():
    stay = scheduler.reserve("S-6", "NERIMA300B0002", "STANDARD", dt(1, 9), dt(1, 12))
    raises(scheduler.TransitionError, scheduler.check_out, stay, dt(1, 10))
    scheduler.check_in(stay, dt(1, 9))
    raises(scheduler.TransitionError, scheduler.check_in, stay, dt(1, 9, 30))
    raises(scheduler.TransitionError, scheduler.cancel, stay, dt(1, 9, 30))


@test
def test_scheduler_extend_moves_the_billing_window():
    stay = scheduler.reserve("S-7", "NERIMA300B0003", "STANDARD", dt(1, 9), dt(1, 10))
    scheduler.extend(stay, dt(1, 12))
    eq(scheduler.billing_window(stay), (dt(1, 9), dt(1, 12)), "extended window")
    raises(scheduler.TransitionError, scheduler.extend, stay, dt(1, 11))
    scheduler.check_in(stay, dt(1, 9))
    scheduler.check_out(stay, dt(1, 12))
    eq(billing.charge_stay(stay), 1300, "total after extension")


# --------------------------------------------------------------------------
# ledger
# --------------------------------------------------------------------------

@test
def test_ledger_receipt_agrees_with_charge_stay():
    book = ledger.Ledger()
    stay = _closed_stay("S-8", "STANDARD", dt(1, 13), dt(1, 15, 30))
    receipt = book.post_stay(stay)
    eq(receipt.total, 1200, "receipt total")
    eq(receipt.total, billing.charge_stay(stay), "receipt vs charge_stay")
    eq(len(receipt.items), 1, "line item count")
    eq(book.grand_total(), 1200, "ledger grand total")
    raises(ledger.LedgerError, book.post_stay, stay)


# --------------------------------------------------------------------------

def main():
    passed = 0
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            failed.append((fn.__name__, exc))
            print("FAIL  {0}".format(fn.__name__))
            print("      {0}: {1}".format(type(exc).__name__, exc))
            if not isinstance(exc, AssertionError):
                traceback.print_exc()
        else:
            passed += 1
            print("ok    {0}".format(fn.__name__))

    total = len(TESTS)
    print("")
    print("SUMMARY: {0}/{1} passed, {2} failed".format(passed, total, len(failed)))
    if failed:
        print("FAILED TESTS:")
        for name, exc in failed:
            print("  - {0}: {1}".format(name, exc))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
