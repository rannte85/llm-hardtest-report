"""Order pricing for the harness self-test fixture.

This module exists only so the v4 grader has something to grade.  It is NOT one
of the benchmark tasks.
"""


def order_total(items, coupon_cents=0):
    """Total price of an order, in cents.

    Contract:

    * ``coupon_cents`` is an ORDER-level adjustment.  It comes off the order
      total exactly once.  It is never applied to an individual line.
    * The order total is floored at zero.  Individual lines are not floored:
      flooring per line would silently swallow part of a coupon.
    * ``items`` belongs to the caller.  This function must not mutate it.
    """
    total = 0
    for item in items:
        line = item["unit_cents"] * item["qty"]
        if coupon_cents:
            line -= coupon_cents          # BUG: order-level coupon applied per line
        total += max(0, line)             # BUG: and floored per line
    return total
