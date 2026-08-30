#!/usr/bin/env python3
"""Public test runner for quote-svc.

    python3 run_tests.py            # summary
    python3 run_tests.py -v         # summary + full tracebacks for failures

Standard library only: no pytest, no third-party packages.
"""

import importlib
import logging
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

MODULES = (
    "tests.test_config",
    "tests.test_retry",
    "tests.test_service",
)


def collect(module):
    functions = []
    for name in dir(module):
        if not name.startswith("test_"):
            continue
        function = getattr(module, name)
        if callable(function):
            functions.append(function)
    functions.sort(key=lambda f: f.__code__.co_firstlineno)
    return functions


def where(exc):
    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return ""
    frame = frames[-1]
    return "%s:%d" % (os.path.relpath(frame.filename, ROOT), frame.lineno)


def main(argv):
    verbose = "-v" in argv or "--verbose" in argv
    logging.disable(logging.CRITICAL)

    passed = 0
    total = 0
    failures = []

    print("quote-svc public test suite")
    for module_name in MODULES:
        module = importlib.import_module(module_name)
        print()
        print("%s" % module_name.replace(".", "/") + ".py")
        for function in collect(module):
            total += 1
            label = "%s.%s" % (module_name, function.__name__)
            try:
                function()
            except Exception as exc:  # noqa: BLE001 - a test runner catches everything
                failures.append((label, exc))
                print("  FAIL  %s" % function.__name__)
                print("        %s: %s" % (type(exc).__name__, exc))
                print("        at %s" % where(exc))
                if verbose:
                    traceback.print_exception(type(exc), exc, exc.__traceback__)
            else:
                passed += 1
                print("  PASS  %s" % function.__name__)

    print()
    print("PUBLIC: %d/%d passed" % (passed, total))
    if failures:
        print("FAILED: %s" % ", ".join(label for label, _ in failures))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
