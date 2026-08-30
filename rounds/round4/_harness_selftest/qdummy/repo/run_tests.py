#!/usr/bin/env python3
"""Public smoke suite for the self-test fixture.

Same output shape as the real v4 tasks: a final ``SUMMARY: N/M passed`` line.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import shop  # noqa: E402


def eq(got, want, what):
    if got != want:
        raise AssertionError("%s: expected %r, got %r" % (what, want, got))


def test_single_line_no_coupon():
    eq(shop.order_total([{"unit_cents": 100, "qty": 1}]), 100, "total")


def test_single_line_with_coupon():
    eq(shop.order_total([{"unit_cents": 100, "qty": 1}], 30), 70, "total")


def test_two_lines_with_coupon():
    items = [{"unit_cents": 100, "qty": 1}, {"unit_cents": 200, "qty": 1}]
    eq(shop.order_total(items, 30), 270, "total")


def test_mixed_quantities_with_coupon():
    items = [{"unit_cents": 50, "qty": 2}, {"unit_cents": 30, "qty": 1}]
    eq(shop.order_total(items, 10), 120, "total")


def test_multi_line_without_coupon():
    items = [{"unit_cents": 100, "qty": 1}, {"unit_cents": 200, "qty": 1}]
    eq(shop.order_total(items), 300, "total")


def test_empty_order():
    eq(shop.order_total([], 30), 0, "total")


def test_coupon_exceeds_order():
    eq(shop.order_total([{"unit_cents": 20, "qty": 1}], 50), 0, "total")


def test_zero_priced_line():
    items = [{"unit_cents": 0, "qty": 3}, {"unit_cents": 100, "qty": 1}]
    eq(shop.order_total(items), 100, "total")


TESTS = [
    test_single_line_no_coupon,
    test_single_line_with_coupon,
    test_two_lines_with_coupon,
    test_mixed_quantities_with_coupon,
    test_multi_line_without_coupon,
    test_empty_order,
    test_coupon_exceeds_order,
    test_zero_priced_line,
]


def main():
    passed, failed = 0, []
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failed.append((fn.__name__, exc))
            print("FAIL  %s" % fn.__name__)
            print("      %s" % exc)
        else:
            passed += 1
            print("ok    %s" % fn.__name__)
    print("")
    print("SUMMARY: %d/%d passed, %d failed" % (passed, len(TESTS), len(failed)))
    if failed:
        print("FAILED TESTS:")
        for name, exc in failed:
            print("  - %s: %s" % (name, exc))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
