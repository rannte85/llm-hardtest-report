#!/usr/bin/env python3
"""Hidden suite for the self-test fixture.

Mirrors the real v4 hidden suites: takes the model's repo path as argv[1],
prints per-test lines and a final ``HIDDEN SUMMARY: N/M passed``.

Reference states (measured, and asserted by selftest.py):
    untouched repo   6/9   (h2, h3, h5 fail)
    naive fix        8/9   (h5 still fails: the coupon lands on the first line,
                            which is still floored, so part of it is swallowed)
    correct fix      9/9
"""

import copy
import os
import sys
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


# Must happen BEFORE the candidate's module is imported below.
RECORDER = _v4_report("qdummy")

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(sys.argv[1] if len(sys.argv) > 1
                        else os.path.join(_HERE, "..", "repo"))
sys.path.insert(0, _REPO)

import shop  # noqa: E402


def eq(got, want, what):
    if got != want:
        raise AssertionError("%s: expected %r, got %r" % (what, want, got))


def h1_single_line_with_coupon():
    eq(shop.order_total([{"unit_cents": 100, "qty": 1}], 30), 70, "total")


def h2_two_lines_share_one_coupon():
    items = [{"unit_cents": 100, "qty": 1}, {"unit_cents": 200, "qty": 1}]
    eq(shop.order_total(items, 30), 270, "total")


def h3_four_lines_share_one_coupon():
    items = [{"unit_cents": 100, "qty": 1}] * 4
    eq(shop.order_total(copy.deepcopy(items), 25), 375, "total")


def h4_no_coupon_is_a_plain_sum():
    items = [{"unit_cents": 100, "qty": 2}, {"unit_cents": 200, "qty": 3}]
    eq(shop.order_total(items), 800, "total")


def h5_coupon_larger_than_the_first_line():
    # C-2: lines are not floored individually, so the whole coupon must land.
    items = [{"unit_cents": 20, "qty": 1}, {"unit_cents": 500, "qty": 1}]
    eq(shop.order_total(items, 50), 470, "total")


def h6_coupon_exceeding_the_whole_order_floors_at_zero():
    eq(shop.order_total([{"unit_cents": 20, "qty": 1}], 500), 0, "total")


def h7_empty_order_is_zero():
    eq(shop.order_total([], 30), 0, "total")


def h8_does_not_mutate_the_caller_items():
    # C-3: the caller keeps ownership of items.
    items = [{"unit_cents": 100, "qty": 1}, {"unit_cents": 200, "qty": 1}]
    before = copy.deepcopy(items)
    shop.order_total(items, 30)
    eq(items, before, "items after call")


def h9_repeated_calls_are_stable():
    items = [{"unit_cents": 100, "qty": 1}, {"unit_cents": 200, "qty": 1}]
    first = shop.order_total(items, 30)
    second = shop.order_total(items, 30)
    eq(second, first, "second call")


TESTS = [
    h1_single_line_with_coupon,
    h2_two_lines_share_one_coupon,
    h3_four_lines_share_one_coupon,
    h4_no_coupon_is_a_plain_sum,
    h5_coupon_larger_than_the_first_line,
    h6_coupon_exceeding_the_whole_order_floors_at_zero,
    h7_empty_order_is_zero,
    h8_does_not_mutate_the_caller_items,
    h9_repeated_calls_are_stable,
]


def main():
    passed, failed = 0, []
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failed.append((fn.__name__, exc))
            RECORDER.record(fn.__name__, False)
            print("HFAIL %s" % fn.__name__)
            print("      %s: %s" % (type(exc).__name__, exc))
            if not isinstance(exc, AssertionError):
                traceback.print_exc()
        else:
            passed += 1
            RECORDER.record(fn.__name__, True)
            print("hok   %s" % fn.__name__)
    print("")
    RECORDER.publish()
    print("")
    print("HIDDEN SUMMARY: %d/%d passed, %d failed" % (passed, len(TESTS), len(failed)))
    if failed:
        print("HIDDEN FAILED:")
        for name, exc in failed:
            print("  - %s: %s" % (name, exc))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
