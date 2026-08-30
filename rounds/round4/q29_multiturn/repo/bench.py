#!/usr/bin/env python3
"""Deterministic cost bench for `OrderAPI.list_orders`.

There is no wall-clock timing here on purpose: latency on this service is
dominated by storage round-trips, so we count storage read ops instead.  The
number is identical on every machine and every run.

Workload: 400 orders spread over 20 customers (20 orders each).  One
`list_orders` call is sampled per customer; the reported figure is the p95 of
the per-call read-op counts.

DO NOT EDIT.  This file and `bench_baseline.json` are the measurement contract.
"""

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from orderservice import OrderAPI  # noqa: E402

TOTAL_ORDERS = 400
CUSTOMERS = 20
HERE = os.path.dirname(os.path.abspath(__file__))


def build_fixture():
    """Build the standard bench fixture.  Deterministic, no randomness."""
    api = OrderAPI()
    for i in range(TOTAL_ORDERS):
        cid = "c-%02d" % (i % CUSTOMERS)
        api.create_order(
            cid,
            [
                {"sku": "sku-%03d" % (i % 37), "unit_cents": 100 + (i % 13), "qty": 1 + (i % 4)},
                {"sku": "sku-%03d" % (i % 11), "unit_cents": 250 + (i % 7), "qty": 1 + (i % 3)},
            ],
        )
    return api


def percentile(values, pct):
    ordered = sorted(values)
    idx = int(math.ceil(pct * len(ordered))) - 1
    idx = max(0, min(idx, len(ordered) - 1))
    return ordered[idx]


def run_bench():
    api = build_fixture()
    samples = []
    for c in range(CUSTOMERS):
        api.storage.reset_counters()
        rows = api.list_orders("c-%02d" % c)
        samples.append(api.storage.read_ops)
        if len(rows) != TOTAL_ORDERS // CUSTOMERS:
            raise AssertionError(
                "bench fixture broken: customer c-%02d returned %d rows, expected %d"
                % (c, len(rows), TOTAL_ORDERS // CUSTOMERS)
            )
    with open(os.path.join(HERE, "bench_baseline.json")) as fh:
        cfg = json.load(fh)
    return {
        "samples": len(samples),
        "min": min(samples),
        "p50": percentile(samples, 0.50),
        "p95": percentile(samples, 0.95),
        "max": max(samples),
        "baseline": cfg["baseline_p95_read_ops"],
        "budget": cfg["budget_p95_read_ops"],
    }


def main():
    try:
        r = run_bench()
    except NotImplementedError as exc:
        print("BENCH ERROR: not implemented: %s" % exc)
        return 2
    ok = r["p95"] <= r["budget"]
    print(
        "samples=%(samples)d min=%(min)d p50=%(p50)d p95=%(p95)d max=%(max)d "
        "baseline=%(baseline)d budget=%(budget)d" % r
    )
    print("RESULT: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
