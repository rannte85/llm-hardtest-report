"""Hidden checks for TURN 2 -- v2 fields must not leak into the v1 wire shape."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import (  # noqa: E402
    V1_ITEM_KEYS,
    V1_ORDER_KEYS,
    V2_ITEM_KEYS,
    V2_ORDER_KEYS,
    expect_raises,
    make_registry,
)

TESTS, test = make_registry()


@test("h2_1_get_order_v1_key_set_is_exact")
def _t(ctx):
    api = ctx.api()
    oid = api.create_order("cust-1", [ctx.item("s", 1000, 2)], priority="express", discount_pct=0.1)
    got = api.get_order(oid)
    assert set(got) == V1_ORDER_KEYS, "v1 leak: %r" % (sorted(set(got) ^ V1_ORDER_KEYS),)


@test("h2_2_get_order_v2_key_set_is_exact")
def _t(ctx):
    api = ctx.api()
    oid = api.create_order("cust-1", [ctx.item("s", 1000, 2)], priority="express", discount_pct=0.1)
    got = api.get_order(oid, wire_version=2)
    assert set(got) == V2_ORDER_KEYS, "v2 shape wrong: %r" % (sorted(set(got) ^ V2_ORDER_KEYS),)
    assert "created_seq" not in got, "internal field on the wire"


@test("h2_3_v2_items_carry_line_totals")
def _t(ctx):
    api = ctx.api()
    oid = api.create_order("cust-1", [ctx.item("s", 700, 3)], priority="standard")
    got = api.get_order(oid, wire_version=2)
    it = got["items"][0]
    assert set(it) == V2_ITEM_KEYS, "v2 item shape wrong: %r" % (sorted(set(it) ^ V2_ITEM_KEYS),)
    assert it["line_total_cents"] == 2100, it


@test("h2_4_v1_items_do_not_carry_line_totals")
def _t(ctx):
    api = ctx.api()
    oid = api.create_order("cust-1", [ctx.item("s", 700, 3)], priority="express", discount_pct=0.2)
    it = api.get_order(oid)["items"][0]
    assert set(it) == V1_ITEM_KEYS, "v1 item leak: %r" % (sorted(set(it) ^ V1_ITEM_KEYS),)


@test("h2_5_priority_default_and_persistence")
def _t(ctx):
    api = ctx.api()
    a = api.create_order("cust-1", [ctx.item("s", 100, 1)])
    b = api.create_order("cust-1", [ctx.item("s", 100, 1)], priority="express")
    assert api.get_order(a, wire_version=2)["priority"] == "standard"
    assert api.get_order(b, wire_version=2)["priority"] == "express"


@test("h2_6_invalid_v2_inputs_rejected")
def _t(ctx):
    api = ctx.api()
    expect_raises(ValueError, api.create_order, "cust-1", [ctx.item("s", 100, 1)], priority="urgent")
    expect_raises(
        ValueError, api.create_order, "cust-1", [ctx.item("s", 100, 1)], discount_pct=1.0
    )
    expect_raises(
        ValueError, api.create_order, "cust-1", [ctx.item("s", 100, 1)], discount_pct=-0.01
    )


@test("h2_7_unsupported_wire_versions_rejected")
def _t(ctx):
    api = ctx.api()
    oid = api.create_order("cust-1", [ctx.item("s", 100, 1)])
    expect_raises(ctx.UnsupportedWireVersion, api.get_order, oid, wire_version=3)
    expect_raises(ctx.UnsupportedWireVersion, api.get_order, oid, wire_version=0)
