#!/usr/bin/env python3
"""Acceptance test runner for jobq.

    python3 run_tests.py            # run everything
    python3 run_tests.py test_order # run one module

Standard library only, on purpose: this runs in environments where nothing can
be installed.
"""

import importlib
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))

MODULES = (
    "tests.test_order",
    "tests.test_eligibility",
    "tests.test_concurrency",
)


def collect(module):
    names = sorted(n for n in dir(module) if n.startswith("test_"))
    return [(n, getattr(module, n)) for n in names if callable(getattr(module, n))]


def main(argv):
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

    wanted = argv[1:]
    modules = MODULES
    if wanted:
        modules = tuple(m for m in MODULES if m.split(".")[-1] in wanted or m in wanted)
        if not modules:
            sys.stderr.write("no such test module: %s\n" % ", ".join(wanted))
            return 2

    passed = 0
    failures = []
    total = 0

    for mod_name in modules:
        module = importlib.import_module(mod_name)
        short = mod_name.split(".")[-1]
        for name, fn in collect(module):
            total += 1
            label = "%s::%s" % (short, name)
            try:
                fn()
            except Exception:
                lines = traceback.format_exc().strip().splitlines()
                detail = lines[-1] if lines else "error"
                failures.append((label, detail))
                print("FAIL %s" % label)
                print("     %s" % detail)
            else:
                passed += 1
                print("PASS %s" % label)

    print("")
    print("SUMMARY: %d/%d passed" % (passed, total))
    if failures:
        print("FAILED TESTS:")
        for label, detail in failures:
            print("  - %s" % label)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
