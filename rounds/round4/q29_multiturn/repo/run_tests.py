#!/usr/bin/env python3
"""Public test suite for orderservice.

Pure stdlib.  Run with:  python3 run_tests.py
Exit code 0 when every test passes.
"""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from orderservice import OrderAPI  # noqa: E402
from orderservice.errors import OrderNotFound, UnsupportedWireVersion  # noqa: E402

TESTS = []


def test(name):
    def deco(fn):
        TESTS.append((name, fn))
        return fn

    return deco


def item(sku, unit_cents, qty):
    return {"sku": sku, "unit_cents": unit_cents, "qty": qty}


def basic_api():
    return OrderAPI()


# --------------------------------------------------------------------------- #
# Turn 1 -- order API v1
# --------------------------------------------------------------------------- #
@test("t1_create_get_roundtrip")
def _t():
    api = basic_api()
    oid = api.create_order("cust-1", [item("sku-a", 500, 2), item("sku-b", 250, 1)])
    got = api.get_order(oid)
    assert got["order_id"] == oid, got
    assert got["customer_id"] == "cust-1", got
    assert got["total_cents"] == 1250, got
    assert got["status"] == "open", got
    assert len(got["items"]) == 2, got


@test("t1_get_order_returns_a_copy")
def _t():
    api = basic_api()
    oid = api.create_order("cust-1", [item("sku-a", 500, 2)])
    payload = api.get_order(oid)
    payload["status"] = "tampered"
    payload["total_cents"] = -1
    again = api.get_order(oid)
    assert again["status"] == "open", again
    assert again["total_cents"] == 1000, again


@test("t1_list_orders_returns_customer_orders")
def _t():
    api = basic_api()
    a = api.create_order("cust-1", [item("s", 100, 1)])
    b = api.create_order("cust-2", [item("s", 100, 1)])
    c = api.create_order("cust-1", [item("s", 100, 1)])
    rows = api.list_orders("cust-1")
    assert {r["order_id"] for r in rows} == {a, c}, rows
    assert b not in {r["order_id"] for r in rows}, rows


@test("t1_list_orders_limit")
def _t():
    api = basic_api()
    for _ in range(5):
        api.create_order("cust-1", [item("s", 100, 1)])
    rows = api.list_orders("cust-1", limit=2)
    assert len(rows) == 2, rows


@test("t1_create_order_validates_input")
def _t():
    api = basic_api()
    try:
        api.create_order("cust-1", [])
    except ValueError:
        pass
    else:
        raise AssertionError("empty item list should raise ValueError")
    try:
        api.create_order("cust-1", [item("s", 100, 0)])
    except ValueError:
        pass
    else:
        raise AssertionError("qty=0 should raise ValueError")


@test("t1_unknown_order_id")
def _t():
    api = basic_api()
    try:
        api.get_order("ord-999999")
    except OrderNotFound:
        pass
    else:
        raise AssertionError("expected OrderNotFound")


# --------------------------------------------------------------------------- #
# Turn 2 -- v2 fields behind a wire version
# --------------------------------------------------------------------------- #
@test("t2_get_order_v1_key_set_is_exact")
def _t():
    api = basic_api()
    oid = api.create_order("cust-1", [item("s", 100, 1)], priority="express", discount_pct=0.1)
    got = api.get_order(oid)
    assert set(got) == {"order_id", "customer_id", "items", "total_cents", "status"}, sorted(got)


@test("t2_get_order_v2_exposes_new_fields")
def _t():
    api = basic_api()
    oid = api.create_order("cust-1", [item("s", 100, 1)], priority="express", discount_pct=0.1)
    got = api.get_order(oid, wire_version=2)
    assert got["priority"] == "express", got
    assert "discount_pct" in got, sorted(got)
    assert "subtotal_cents" in got, sorted(got)


@test("t2_invalid_priority_rejected")
def _t():
    api = basic_api()
    try:
        api.create_order("cust-1", [item("s", 100, 1)], priority="urgent-ish")
    except ValueError:
        pass
    else:
        raise AssertionError("bad priority should raise ValueError")


# --------------------------------------------------------------------------- #
# Turn 3 -- old clients also read list_orders
# --------------------------------------------------------------------------- #
@test("t3_list_orders_v1_key_set_is_exact")
def _t():
    api = basic_api()
    api.create_order("cust-1", [item("s", 100, 1)], priority="express", discount_pct=0.1)
    rows = api.list_orders("cust-1")
    assert rows, rows
    assert set(rows[0]) == {"order_id", "customer_id", "items", "total_cents", "status"}, sorted(rows[0])


@test("t3_total_cents_is_an_int")
def _t():
    api = basic_api()
    a = api.create_order("cust-1", [item("s", 1999, 1)], discount_pct=0.0)
    got = api.get_order(a)
    assert type(got["total_cents"]) is int, (got["total_cents"], type(got["total_cents"]))
    assert got["total_cents"] == 1999, got

    b = api.create_order("cust-1", [item("s", 1250, 2)], discount_pct=0.25)
    got = api.get_order(b)
    assert type(got["total_cents"]) is int, (got["total_cents"], type(got["total_cents"]))
    assert got["total_cents"] == 1875, got


@test("t3_unsupported_wire_version")
def _t():
    api = basic_api()
    oid = api.create_order("cust-1", [item("s", 100, 1)])
    try:
        api.get_order(oid, wire_version=3)
    except UnsupportedWireVersion:
        pass
    else:
        raise AssertionError("wire_version=3 should raise UnsupportedWireVersion")


# --------------------------------------------------------------------------- #
# Turn 4 -- cancellation and rollback
# --------------------------------------------------------------------------- #
@test("t4_cancel_is_a_soft_delete")
def _t():
    api = basic_api()
    oid = api.create_order("cust-1", [item("s", 100, 1)])
    before = api.storage.count()
    api.cancel_order(oid)
    assert api.storage.count() == before, (api.storage.count(), before)
    got = api.get_order(oid)
    assert got["status"] == "cancelled", got


@test("t4_rollback_disables_v2_reads")
def _t():
    api = basic_api()
    oid = api.create_order("cust-1", [item("s", 100, 1)], priority="express")
    api.rollback_to_v1()
    try:
        api.get_order(oid, wire_version=2)
    except UnsupportedWireVersion:
        pass
    else:
        raise AssertionError("v2 reads should be refused after rollback")
    assert api.get_order(oid)["order_id"] == oid


@test("t4_roll_forward_restores_v2")
def _t():
    api = basic_api()
    oid = api.create_order("cust-1", [item("s", 100, 1)], priority="express")
    api.rollback_to_v1()
    api.roll_forward_to_v2()
    got = api.get_order(oid, wire_version=2)
    assert "priority" in got, sorted(got)


@test("t4_rollback_refuses_v2_writes")
def _t():
    api = basic_api()
    api.rollback_to_v1()
    try:
        api.create_order("cust-1", [item("s", 100, 1)], priority="express")
    except UnsupportedWireVersion:
        pass
    else:
        raise AssertionError("v2-only kwargs should be refused after rollback")


@test("t4_rollback_keeps_every_record")
def _t():
    api = basic_api()
    for _ in range(4):
        api.create_order("cust-1", [item("s", 100, 1)], priority="express")
    before = api.storage.count()
    api.rollback_to_v1()
    assert api.storage.count() == before, (api.storage.count(), before)


# --------------------------------------------------------------------------- #
# Turn 5 -- cost budget
# --------------------------------------------------------------------------- #
def scale_fixture():
    api = OrderAPI()
    for i in range(400):
        api.create_order(
            "c-%02d" % (i % 20),
            [item("sku-%03d" % (i % 37), 100 + (i % 13), 1 + (i % 4))],
        )
    return api


@test("t5_bench_within_budget")
def _t():
    import bench

    r = bench.run_bench()
    assert r["p95"] <= r["budget"], r


@test("t5_single_list_call_within_budget")
def _t():
    api = scale_fixture()
    api.storage.reset_counters()
    api.list_orders("c-07")
    assert api.storage.read_ops <= 25, api.storage.read_ops


@test("t5_list_orders_still_correct_at_scale")
def _t():
    api = scale_fixture()
    rows = api.list_orders("c-07")
    assert len(rows) == 20, len(rows)
    assert {r["customer_id"] for r in rows} == {"c-07"}, rows[:2]


@test("t5_bench_files_untouched")
def _t():
    import json

    with open(os.path.join(HERE, "bench_baseline.json")) as fh:
        cfg = json.load(fh)
    assert cfg["baseline_p95_read_ops"] == 21, cfg
    assert cfg["budget_p95_read_ops"] == 25, cfg


# --------------------------------------------------------------------------- #
def main():
    passed = failed = 0
    for name, fn in TESTS:
        try:
            fn()
        except Exception:
            failed += 1
            print("FAIL %s" % name)
            for line in traceback.format_exc().strip().splitlines()[-2:]:
                print("      %s" % line.strip())
        else:
            passed += 1
            print("PASS %s" % name)
    total = passed + failed
    print("")
    print("PUBLIC: %d/%d passed" % (passed, total))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
