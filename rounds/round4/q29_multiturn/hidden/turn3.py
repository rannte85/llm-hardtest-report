"""Hidden checks for TURN 3 -- the client-team crash report.

Three separate facts came out of that report:
  (a) old clients read list_orders too, so it must project like get_order does
  (b) total_cents must stay an int, and the discount rule is floor-on-the-discount
  (c) the leak is nested: items[*] carry a v2-only key as well
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import V1_ITEM_KEYS, V1_ORDER_KEYS, V2_ITEM_KEYS, V2_ORDER_KEYS, make_registry  # noqa: E402

TESTS, test = make_registry()

# (unit_cents, qty, discount_pct, expected_discount_cents, expected_total_cents)
DISCOUNT_CASES = [
    (1999, 1, 0.15, 299, 1700),
    (777, 1, 0.5, 388, 389),
    (1234, 1, 0.33, 407, 827),
    (9999, 1, 0.05, 499, 9500),
    (2500, 1, 0.0, 0, 2500),
    (1250, 2, 0.25, 625, 1875),
]


@test("h3_1_list_orders_v1_key_set_is_exact")
def _t(ctx):
    api = ctx.api()
    api.create_order("cust-1", [ctx.item("s", 900, 2)], priority="express", discount_pct=0.3)
    row = api.list_orders("cust-1")[0]
    assert set(row) == V1_ORDER_KEYS, "list v1 leak: %r" % (sorted(set(row) ^ V1_ORDER_KEYS),)


@test("h3_2_list_orders_v1_items_are_exact")
def _t(ctx):
    api = ctx.api()
    api.create_order("cust-1", [ctx.item("s", 900, 2), ctx.item("t", 50, 4)], priority="express")
    row = api.list_orders("cust-1")[0]
    for it in row["items"]:
        assert set(it) == V1_ITEM_KEYS, "list v1 item leak: %r" % (sorted(set(it) ^ V1_ITEM_KEYS),)


@test("h3_3_list_orders_supports_v2")
def _t(ctx):
    api = ctx.api()
    api.create_order("cust-1", [ctx.item("s", 900, 2)], priority="express", discount_pct=0.3)
    row = api.list_orders("cust-1", wire_version=2)[0]
    assert set(row) == V2_ORDER_KEYS, "list v2 shape wrong: %r" % (sorted(set(row) ^ V2_ORDER_KEYS),)
    assert set(row["items"][0]) == V2_ITEM_KEYS, sorted(row["items"][0])
    assert row["priority"] == "express", row


@test("h3_4_total_cents_type_is_int_everywhere")
def _t(ctx):
    api = ctx.api()
    for unit, qty, pct, _dc, _tc in DISCOUNT_CASES:
        oid = api.create_order("cust-1", [ctx.item("s", unit, qty)], discount_pct=pct)
        for payload in (api.get_order(oid), api.get_order(oid, wire_version=2)):
            assert type(payload["total_cents"]) is int, (
                pct,
                payload["total_cents"],
                type(payload["total_cents"]).__name__,
            )
    for row in api.list_orders("cust-1"):
        assert type(row["total_cents"]) is int, (row["order_id"], type(row["total_cents"]).__name__)


@test("h3_5_discount_uses_floor_on_the_discount_amount")
def _t(ctx):
    api = ctx.api()
    for unit, qty, pct, want_disc, want_total in DISCOUNT_CASES:
        oid = api.create_order("cust-1", [ctx.item("s", unit, qty)], discount_pct=pct)
        v2 = api.get_order(oid, wire_version=2)
        subtotal = unit * qty
        assert v2["subtotal_cents"] == subtotal, (pct, v2["subtotal_cents"], subtotal)
        assert v2["discount_cents"] == want_disc, (
            "pct=%r subtotal=%d: discount_cents=%r want %d (floor(%d*%r)=%d)"
            % (pct, subtotal, v2["discount_cents"], want_disc, subtotal, pct, math.floor(subtotal * pct))
        )
        assert v2["total_cents"] == want_total, (pct, v2["total_cents"], want_total)
        assert api.get_order(oid)["total_cents"] == want_total, pct


@test("h3_6_v1_omits_keys_rather_than_nulling_them")
def _t(ctx):
    api = ctx.api()
    oid = api.create_order("cust-1", [ctx.item("s", 800, 1)], priority="express", discount_pct=0.4)
    for payload in (api.get_order(oid), api.list_orders("cust-1")[0]):
        for banned in ("priority", "discount_pct", "discount_cents", "subtotal_cents", "created_seq"):
            assert banned not in payload, "v1 payload carries %r (value=%r)" % (
                banned,
                payload.get(banned),
            )
        for it in payload["items"]:
            assert "line_total_cents" not in it, "v1 item carries line_total_cents"


@test("h3_7_v1_projection_survives_pre_v2_records")
def _t(ctx):
    api = ctx.api()
    plain = api.create_order("cust-1", [ctx.item("s", 400, 1)])
    got = api.get_order(plain)
    assert set(got) == V1_ORDER_KEYS, sorted(got)
    assert got["total_cents"] == 400, got
    v2 = api.get_order(plain, wire_version=2)
    assert v2["discount_pct"] == 0.0, v2
    assert v2["discount_cents"] == 0, v2
    assert v2["priority"] == "standard", v2
