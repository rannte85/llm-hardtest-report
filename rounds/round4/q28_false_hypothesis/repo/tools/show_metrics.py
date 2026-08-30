#!/usr/bin/env python3
"""Summarise the recorded upstream metrics snapshot.

    python3 tools/show_metrics.py [path/to/upstream_requests.jsonl]

The snapshot is what the observability pipeline stored for the incident window;
it is measured at the upstream edge, independently of this service's own logs.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_PATH = os.path.join(ROOT, "metrics", "upstream_requests.jsonl")

COLUMNS = (
    ("minute", "minute", 17),
    ("requests", "requests", 9),
    ("http_200", "200", 7),
    ("http_503", "503", 7),
    ("transport_timeouts", "timeouts", 9),
    ("latency_p50_ms", "p50ms", 6),
    ("latency_p95_ms", "p95ms", 6),
    ("distinct_client_request_ids", "req-ids", 8),
)


def load(path):
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def main(argv):
    path = argv[1] if len(argv) > 1 else DEFAULT_PATH
    rows = load(path)
    if not rows:
        print("no samples in %s" % path)
        return 1

    upstream = rows[0].get("upstream", "?")
    print("upstream : %s" % upstream)
    print("window   : %s .. %s  (%d one-minute samples)"
          % (rows[0]["minute"], rows[-1]["minute"], len(rows)))
    print()

    header = "".join(title.rjust(width) for _, title, width in COLUMNS)
    print(header)
    print("-" * len(header))
    for row in rows:
        print("".join(str(row.get(key, "")).rjust(width) for key, _, width in COLUMNS))
    print("-" * len(header))

    baseline = [r for r in rows if r["http_503"] == 0]
    elevated = [r for r in rows if r["http_503"] > 0]
    total_timeouts = sum(r["transport_timeouts"] for r in rows)
    worst_p95 = max(r["latency_p95_ms"] for r in rows)
    peak = max(rows, key=lambda r: r["requests"])
    quiet_avg = sum(r["requests"] for r in baseline) / float(len(baseline) or 1)

    print()
    print("transport timeouts across the whole window : %d" % total_timeouts)
    print("worst p95 round-trip latency               : %dms" % worst_p95)
    print("requests/min, quiet minutes                : %.0f" % quiet_avg)
    print("requests/min, peak minute (%s) : %d" % (peak["minute"], peak["requests"]))
    print("distinct client request ids at that peak   : %d"
          % peak["distinct_client_request_ids"])
    if elevated:
        tenants = {}
        for row in elevated:
            for tenant, count in row.get("http_503_by_tenant", {}).items():
                tenants[tenant] = tenants.get(tenant, 0) + count
        print("non-2xx answers by tenant                  : %s"
              % (", ".join("%s=%d" % item for item in sorted(tenants.items())) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
