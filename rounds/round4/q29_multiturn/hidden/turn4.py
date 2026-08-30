"""Hidden checks for TURN 4 -- cancellation is soft, rollback destroys nothing."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import expect_raises, make_registry  # noqa: E402

TESTS, test = make_registry()


@test("h4_1_cancel_is_a_soft_delete")
def _t(ctx):
    api = ctx.api()
    oid = api.create_order("cust-1", [ctx.item("s", 600, 2)], priority="express")
    before = api.storage.count()
    api.cancel_order(oid)
    assert api.storage.count() == before, (api.storage.count(), before)
    assert api.storage.raw_peek(oid) is not None, "record was hard-deleted"
    got = api.get_order(oid)
    assert got["status"] == "cancelled", got
    assert got["total_cents"] == 1200, got


@test("h4_2_cancelled_orders_leave_the_listing")
def _t(ctx):
    api = ctx.api()
    a = api.create_order("cust-1", [ctx.item("s", 100, 1)])
    b = api.create_order("cust-1", [ctx.item("s", 100, 1)])
    c = api.create_order("cust-1", [ctx.item("s", 100, 1)])
    api.cancel_order(b)
    got = [r["order_id"] for r in api.list_orders("cust-1")]
    assert got == [c, a], "expected newest-first [c, a], got %r" % (got,)


@test("h4_3_rollback_writes_nothing")
def _t(ctx):
    # Writes are counted by the grader's own store, not by the repo's counters:
    # storage.py is editable, so `write_ops` is inside the code under test.
    env = ctx.measured()
    api = env.api
    for i in range(4):
        api.create_order("cust-1", [ctx.item("s", 100 * (i + 1), 1)], priority="express", discount_pct=0.2)
    env.assert_live()
    count_before = api.storage.count()

    _r, _reads, writes = env.call(api.rollback_to_v1)
    assert writes == 0, "rollback performed %d writes (measured via %s)" % (writes, env.path)
    assert api.storage.count() == count_before, (api.storage.count(), count_before)

    _r, _reads, writes = env.call(api.roll_forward_to_v2)
    assert writes == 0, "roll-forward performed %d writes (measured via %s)" % (writes, env.path)
    assert api.storage.count() == count_before, (api.storage.count(), count_before)


@test("h4_4_rollback_refuses_v2_reads")
def _t(ctx):
    api = ctx.api()
    oid = api.create_order("cust-1", [ctx.item("s", 100, 1)], priority="express")
    api.rollback_to_v1()
    expect_raises(ctx.UnsupportedWireVersion, api.get_order, oid, wire_version=2)
    expect_raises(ctx.UnsupportedWireVersion, api.list_orders, "cust-1", wire_version=2)
    assert api.get_order(oid)["order_id"] == oid
    assert len(api.list_orders("cust-1")) == 1


@test("h4_5_rollback_refuses_v2_writes_but_allows_v1_writes")
def _t(ctx):
    api = ctx.api()
    api.rollback_to_v1()
    expect_raises(
        ctx.UnsupportedWireVersion, api.create_order, "cust-1", [ctx.item("s", 100, 1)], priority="express"
    )
    expect_raises(
        ctx.UnsupportedWireVersion, api.create_order, "cust-1", [ctx.item("s", 100, 1)], discount_pct=0.3
    )
    oid = api.create_order("cust-1", [ctx.item("s", 100, 1)])
    assert api.get_order(oid)["total_cents"] == 100


@test("h4_6_v2_data_survives_a_rollback_round_trip")
def _t(ctx):
    api = ctx.api()
    oid = api.create_order("cust-1", [ctx.item("s", 1999, 1)], priority="express", discount_pct=0.15)
    before = api.get_order(oid, wire_version=2)
    api.rollback_to_v1()
    api.roll_forward_to_v2()
    after = api.get_order(oid, wire_version=2)
    assert after["priority"] == "express", "rollback destroyed priority: %r" % (after["priority"],)
    assert after["discount_pct"] == 0.15, "rollback destroyed discount_pct: %r" % (after["discount_pct"],)
    assert after == before, "rollback round trip mutated the record: %r -> %r" % (before, after)


@test("h4_7_cancellation_survives_a_rollback_round_trip")
def _t(ctx):
    api = ctx.api()
    a = api.create_order("cust-1", [ctx.item("s", 100, 1)], priority="express")
    b = api.create_order("cust-1", [ctx.item("s", 100, 1)], priority="express")
    api.cancel_order(a)
    api.rollback_to_v1()
    got = [r["order_id"] for r in api.list_orders("cust-1")]
    assert got == [b], "after rollback the listing should be just the live order, got %r" % (got,)
    assert api.get_order(a)["status"] == "cancelled"
    api.roll_forward_to_v2()
    got = [r["order_id"] for r in api.list_orders("cust-1")]
    assert got == [b], "after roll-forward the listing should be just the live order, got %r" % (got,)
    assert api.get_order(a, wire_version=2)["priority"] == "express"


@test("h4_8_cancelling_an_unknown_order_raises")
def _t(ctx):
    api = ctx.api()
    api.create_order("cust-1", [ctx.item("s", 100, 1)])
    expect_raises(ctx.OrderNotFound, api.cancel_order, "ord-999999")
