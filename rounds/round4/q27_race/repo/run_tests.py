#!/usr/bin/env python3
"""taskhub test runner (standard library only).

Usage:
  run_tests.py [options] [name-substring ...]

Options:
  -h, --help        show this message
  -l, --list        list the tests and exit
  -r, --repeat N    run the whole suite N times and report how many iterations
                    were clean (default 1)
  -b, --barrier     put interleaving-sensitive tests into deterministic mode:
                    producers are parked on taskhub tracepoints so that a
                    thread ordering is forced instead of hoped for
  -v, --verbose     print a line per test even when it passes
  -f, --failfast    stop at the first failure
"""

import argparse
import importlib
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

MODULES = [
    "tests.test_store",
    "tests.test_retry",
    "tests.test_worker",
    "tests.test_hub",
    "tests.test_race",
]


def collect(patterns):
    cases = []
    for module_name in MODULES:
        module = importlib.import_module(module_name)
        names = [n for n in dir(module) if n.startswith("test_")]
        names.sort(key=lambda n: getattr(module, n).__code__.co_firstlineno)
        for name in names:
            full = "%s.%s" % (module_name.split(".")[-1], name)
            if patterns and not any(p in full for p in patterns):
                continue
            cases.append((full, getattr(module, name)))
    return cases


def run_once(cases, verbose=False, failfast=False):
    failures = []
    for name, fn in cases:
        started = time.monotonic()
        try:
            fn()
        except Exception:
            failures.append((name, traceback.format_exc()))
            print("FAIL %s" % name)
            if failfast:
                break
        else:
            if verbose:
                print(
                    "ok   %s (%.0f ms)"
                    % (name, (time.monotonic() - started) * 1000.0)
                )
    return failures


def main(argv):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-h", "--help", action="store_true")
    parser.add_argument("-l", "--list", action="store_true")
    parser.add_argument("-r", "--repeat", type=int, default=1)
    parser.add_argument("-b", "--barrier", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-f", "--failfast", action="store_true")
    parser.add_argument("patterns", nargs="*")
    args = parser.parse_args(argv)

    if args.help:
        print(__doc__.strip())
        return 0

    from tests import config

    config.BARRIER_MODE = bool(args.barrier)

    cases = collect(args.patterns)
    if args.list:
        for name, _ in cases:
            print(name)
        return 0

    if not cases:
        print("no tests matched")
        return 2

    mode = "barrier" if args.barrier else "normal"
    total_failures = []
    clean_iterations = 0
    started = time.monotonic()

    for iteration in range(args.repeat):
        failures = run_once(cases, verbose=args.verbose, failfast=args.failfast)
        if failures:
            total_failures.extend((iteration, n, tb) for n, tb in failures)
            if args.repeat > 1:
                print("  iteration %d: %d failure(s)" % (iteration + 1, len(failures)))
            if args.failfast:
                break
        else:
            clean_iterations += 1

    elapsed = time.monotonic() - started

    if total_failures:
        print("\n" + "=" * 60)
        seen = set()
        for iteration, name, tb in total_failures:
            if name in seen:
                continue
            seen.add(name)
            print("FAILURE %s (first seen in iteration %d)" % (name, iteration + 1))
            print(tb)

    per_iteration = len(cases)
    if args.repeat == 1:
        passed = per_iteration - len(total_failures)
        print(
            "%s: %d/%d passed  [mode=%s, %.2fs]"
            % (
                "FAILED" if total_failures else "PASSED",
                passed,
                per_iteration,
                mode,
                elapsed,
            )
        )
    else:
        print(
            "%s: %d/%d clean iterations (%d tests each)  [mode=%s, %.2fs]"
            % (
                "FAILED" if total_failures else "PASSED",
                clean_iterations,
                args.repeat,
                per_iteration,
                mode,
                elapsed,
            )
        )
    return 1 if total_failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
