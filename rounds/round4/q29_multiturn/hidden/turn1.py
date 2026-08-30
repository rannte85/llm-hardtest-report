"""Hidden checks for TURN 1 -- order API v1 plus the two unstated invariants.

INV-1  every payload handed to a caller is a deep copy of the stored record
INV-2  list_orders is newest-first

Neither invariant is stated anywhere in the ticket thread.  Both are visible in
the shipped turn-1 code (`OrderAPI._project`, `Storage.keys` docstring).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import expect_raises, make_registry  # noqa: E402

TESTS, test = make_registry()


@test("h1_1_list_orders_is_newest_first")  # INV-2
def _t(ctx):
    api = ctx.api()
    ids = []
    for i in range(5):
        ids.append(api.create_order("cust-1", [ctx.item("s-%d" % i, 100, 1)]))
        api.create_order("cust-2", [ctx.item("noise", 100, 1)])
    rows = api.list_orders("cust-1")
    got = [r["order_id"] for r in rows]
    assert got == list(reversed(ids)), "expected newest-first %r, got %r" % (list(reversed(ids)), got)


@test("h1_2_limit_returns_the_newest_n")  # INV-2
def _t(ctx):
    api = ctx.api()
    ids = [api.create_order("cust-1", [ctx.item("s-%d" % i, 100, 1)]) for i in range(6)]
    rows = api.list_orders("cust-1", limit=2)
    got = [r["order_id"] for r in rows]
    assert got == [ids[5], ids[4]], "limit must take the newest 2, got %r" % (got,)


@test("h1_3_list_orders_payloads_are_deep_copies")  # INV-1
def _t(ctx):
    api = ctx.api()
    api.create_order("cust-1", [ctx.item("s", 500, 2), ctx.item("t", 100, 1)])
    rows = api.list_orders("cust-1")
    rows[0]["status"] = "tampered"
    rows[0]["items"][0]["qty"] = 9999
    rows[0]["items"].append({"sku": "injected", "unit_cents": 1, "qty": 1})

    again = api.list_orders("cust-1")[0]
    assert again["status"] == "open", again
    assert len(again["items"]) == 2, again["items"]
    assert again["items"][0]["qty"] == 2, again["items"]
    direct = api.get_order(again["order_id"])
    assert direct["items"][0]["qty"] == 2, direct["items"]


@test("h1_4_get_order_payloads_are_deep_copies")  # INV-1
def _t(ctx):
    api = ctx.api()
    oid = api.create_order("cust-1", [ctx.item("s", 500, 2)])
    payload = api.get_order(oid)
    payload["total_cents"] = -1
    payload["items"][0]["unit_cents"] = 0
    payload["items"].append({"sku": "x", "unit_cents": 1, "qty": 1})

    again = api.get_order(oid)
    assert again["total_cents"] == 1000, again
    assert len(again["items"]) == 1, again["items"]
    assert again["items"][0]["unit_cents"] == 500, again["items"]


@test("h1_5_customer_isolation")
def _t(ctx):
    api = ctx.api()
    api.create_order("cust-1", [ctx.item("s", 100, 1)])
    api.create_order("cust-2", [ctx.item("s", 100, 1)])
    api.create_order("cust-2", [ctx.item("s", 100, 1)])
    assert len(api.list_orders("cust-1")) == 1
    assert len(api.list_orders("cust-2")) == 2
    assert api.list_orders("nobody") == []


@test("h1_6_create_order_validation")
def _t(ctx):
    api = ctx.api()
    expect_raises(ValueError, api.create_order, "cust-1", [])
    expect_raises(ValueError, api.create_order, "cust-1", [ctx.item("s", 100, 0)])
    expect_raises(ValueError, api.create_order, "cust-1", [ctx.item("s", 100, -3)])
    expect_raises(ValueError, api.create_order, "cust-1", [ctx.item("s", -5, 1)])
    # a rejected order must leave no trace
    assert api.storage.count() == 0, api.storage.count()


@test("h1_7_unknown_order_id_raises")
def _t(ctx):
    api = ctx.api()
    api.create_order("cust-1", [ctx.item("s", 100, 1)])
    expect_raises(ctx.OrderNotFound, api.get_order, "ord-999999")


@test("h1_8_totals_are_ints_from_the_start")
def _t(ctx):
    api = ctx.api()
    oid = api.create_order("cust-1", [ctx.item("s", 333, 3), ctx.item("t", 7, 2)])
    got = api.get_order(oid)
    assert type(got["total_cents"]) is int, type(got["total_cents"])
    assert got["total_cents"] == 333 * 3 + 7 * 2, got["total_cents"]
