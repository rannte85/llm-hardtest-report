"""Hidden checks for TURN 5 -- the cost budget, measured independently.

These never import repo/bench.py, and -- since the three bypasses that used to
work -- they no longer trust the repo's own counters either.  The workload is
rebuilt here on top of a grader-owned counting Storage (`_meter.py`) that

  * counts EVERY read path, `raw_ids()` / `raw_peek()` and direct pokes at the
    private containers included, so an "uncounted" public accessor is not a way
    to make a full scan free;
  * keeps its counters out of reach of `reset_counters()`, and measures a
    before/after delta rather than resetting, so the callee cannot zero the
    instrument (a reset during the measured call is reported outright, and the
    repo's own counter must not go backwards either);
  * subclasses whatever Storage the submission ships, so deleting the
    `read_ops += 1` lines from storage.py changes nothing here.

Every earlier-turn property is re-checked at scale, because the cheapest way to
hit the budget is an index, and an index is exactly what quietly reverses the
listing order and starts handing out live records.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import BUDGET_READ_OPS, V1_ITEM_KEYS, V1_ORDER_KEYS, make_registry  # noqa: E402

TESTS, test = make_registry()

TOTAL = 400
CUSTOMERS = 20
PER_CUSTOMER = TOTAL // CUSTOMERS


def build(ctx):
    """Bench-shaped fixture on an instrumented store.

    Returns ``(env, by_customer)``: ``env.api`` is the OrderAPI under test,
    ``env.list_orders(...)`` returns ``(rows, read_ops)`` measured by the
    grader, and ``by_customer`` is the creation order per customer.
    """
    env = ctx.measured()
    api = env.api
    by_customer = {}
    for i in range(TOTAL):
        cid = "c-%02d" % (i % CUSTOMERS)
        oid = api.create_order(
            cid,
            [
                ctx.item("sku-%03d" % (i % 37), 100 + (i % 13), 1 + (i % 4)),
                ctx.item("sku-%03d" % (i % 11), 250 + (i % 7), 1 + (i % 3)),
            ],
            priority="express" if i % 3 == 0 else "standard",
            discount_pct=0.25 if i % 5 == 0 else 0.0,
        )
        by_customer.setdefault(cid, []).append(oid)
    env.assert_live()
    return env, by_customer


@test("h5_1_p95_read_ops_within_budget")
def _t(ctx):
    env, _ = build(ctx)
    samples = []
    for c in range(CUSTOMERS):
        rows, ops = env.list_orders("c-%02d" % c)
        samples.append(ops)
        assert len(rows) == PER_CUSTOMER, (c, len(rows))
    p95 = ctx.percentile(samples, 0.95)
    assert p95 <= BUDGET_READ_OPS, "p95=%d read ops, budget=%d (samples=%r, measured via %s)" % (
        p95,
        BUDGET_READ_OPS,
        sorted(samples)[-3:],
        env.path,
    )


@test("h5_2_single_call_read_ops_within_budget")
def _t(ctx):
    env, _ = build(ctx)
    _rows, ops = env.list_orders("c-07")
    assert ops <= BUDGET_READ_OPS, "%d read ops (measured via %s)" % (ops, env.path)


@test("h5_3_ordering_still_newest_first_at_scale")  # INV-2
def _t(ctx):
    env, by_customer = build(ctx)
    want = list(reversed(by_customer["c-07"]))
    got = [r["order_id"] for r in env.api.list_orders("c-07")]
    assert got == want, "listing order wrong at scale\n want %r\n got  %r" % (want[:4], got[:4])
    assert [r["order_id"] for r in env.api.list_orders("c-07", limit=3)] == want[:3]


@test("h5_4_payloads_are_still_deep_copies_at_scale")  # INV-1
def _t(ctx):
    env, _ = build(ctx)
    api = env.api
    rows = api.list_orders("c-07")
    target = rows[0]["order_id"]
    rows[0]["status"] = "tampered"
    rows[0]["items"][0]["qty"] = 9999
    rows[0]["items"].append({"sku": "injected", "unit_cents": 1, "qty": 1})

    fresh = api.get_order(target)
    assert fresh["status"] == "open", fresh["status"]
    assert len(fresh["items"]) == 2, fresh["items"]
    assert fresh["items"][0]["qty"] != 9999, fresh["items"]
    again = api.list_orders("c-07")[0]
    assert again["status"] == "open", again["status"]
    assert len(again["items"]) == 2, again["items"]


@test("h5_5_cancellation_visible_at_scale")
def _t(ctx):
    env, by_customer = build(ctx)
    ids = by_customer["c-07"]
    for oid in (ids[0], ids[5], ids[-1]):
        env.api.cancel_order(oid)
    rows, ops = env.list_orders("c-07")
    got = [r["order_id"] for r in rows]
    want = [o for o in reversed(ids) if o not in (ids[0], ids[5], ids[-1])]
    assert got == want, "cancelled orders still listed\n want %r\n got  %r" % (want[:4], got[:4])
    assert ops <= BUDGET_READ_OPS, "%d read ops (measured via %s)" % (ops, env.path)


@test("h5_6_v1_purity_holds_at_scale")
def _t(ctx):
    env, _ = build(ctx)
    for row in env.api.list_orders("c-00"):
        assert set(row) == V1_ORDER_KEYS, sorted(set(row) ^ V1_ORDER_KEYS)
        assert type(row["total_cents"]) is int, type(row["total_cents"]).__name__
        for it in row["items"]:
            assert set(it) == V1_ITEM_KEYS, sorted(set(it) ^ V1_ITEM_KEYS)


@test("h5_7_budget_holds_after_a_rollback_round_trip")
def _t(ctx):
    env, by_customer = build(ctx)
    env.api.rollback_to_v1()
    rows, ops = env.list_orders("c-07")
    assert ops <= BUDGET_READ_OPS, "read_ops=%d after rollback (measured via %s)" % (ops, env.path)
    want = list(reversed(by_customer["c-07"]))
    got = [r["order_id"] for r in rows]
    assert got == want, "listing order wrong after rollback\n want %r\n got  %r" % (want[:4], got[:4])
    env.api.roll_forward_to_v2()
    _rows, ops = env.list_orders("c-07")
    assert ops <= BUDGET_READ_OPS, "%d read ops (measured via %s)" % (ops, env.path)


@test("h5_8_new_orders_after_the_fixture_still_land_on_top")  # INV-2
def _t(ctx):
    env, _ = build(ctx)
    fresh = env.api.create_order("c-07", [ctx.item("late", 10, 1)], priority="express")
    rows, _ops = env.list_orders("c-07")
    assert rows[0]["order_id"] == fresh, "newest order is not first: %r" % (rows[0]["order_id"],)
    assert len(rows) == PER_CUSTOMER + 1, len(rows)
    _rows, ops = env.list_orders("c-07")
    assert ops <= BUDGET_READ_OPS + 1, "%d read ops (measured via %s)" % (ops, env.path)
