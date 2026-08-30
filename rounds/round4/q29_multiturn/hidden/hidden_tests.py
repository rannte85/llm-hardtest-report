#!/usr/bin/env python3
"""Hidden test suite for Q29 (multi-turn order service).

GRADER ONLY -- never place this file, or anything under hidden/, inside the
model's working copy of repo/.

Usage:
    python3 hidden/hidden_tests.py --repo /path/to/repo
    python3 hidden/hidden_tests.py --repo /path/to/repo --turn 3
    python3 hidden/hidden_tests.py --repo /path/to/repo --turn integrity
    python3 hidden/hidden_tests.py --repo /path/to/repo --quiet
    python3 hidden/hidden_tests.py --repo /path/to/repo --print-hashes

Exit code 0 only when every selected test passes.

The suite is five turn files plus `integrity.py`.  Turn 5 is a cost budget, so
it is measured on a storage the GRADER owns (`_meter.py`), never on the
submission's own counters -- see the module docstring there for the three
bypasses that shape forced.
"""

import argparse
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _v4_report(qid):
    """Load the grader's result recorder by ABSOLUTE PATH, before any candidate
    code is imported.  Walks upward from hidden/ through grader-private
    directories only, so it cannot be hijacked and does not use sys.path."""
    import importlib.util
    directory = os.path.dirname(os.path.abspath(__file__))
    while True:
        candidate = os.path.join(directory, "v4_hidden_report.py")
        if os.path.isfile(candidate):
            spec = importlib.util.spec_from_file_location("_v4_hidden_report", candidate)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.new(qid)
        parent = os.path.dirname(directory)
        if parent == directory:
            raise RuntimeError("v4_hidden_report.py not found above %s" % __file__)
        directory = parent


# Must happen BEFORE Ctx() imports the candidate's package: the Recorder is
# created immediately so the os.write/stdout references v4_hidden_report.py
# captures are bound before candidate code can run.  Its handle is then pulled
# out of this module's globals right away -- kept alive only inside
# _get_recorder's default-argument cell -- so that a candidate which searches
# vars(sys.modules['__main__']) for an object exposing record()/publish()
# (measured to work here, see README's Threat Model section) finds nothing at
# top level; main() below recovers it as a pure local via _get_recorder().
# This raises that one bar; it does not and cannot stop a candidate that walks
# frames or hooks sys.setprofile/settrace instead -- those reach local
# variables directly and no in-process defence stops them (see README).
_recorder = _v4_report("q29")
_get_recorder = (lambda _r=_recorder: _r)
del _recorder

from _harness import BASELINE_SHA, MEASUREMENT_PATHS, Ctx, load_turn  # noqa: E402

TURNS = ["turn1", "turn2", "turn3", "turn4", "turn5"]
MODULES = TURNS + ["integrity"]


def integrity_lines(ctx):
    """One line per pinned file, so a diff is visible even where it is allowed."""
    out = []
    for name in sorted(BASELINE_SHA):
        got = ctx.sha256(name)
        state = "OK" if got == BASELINE_SHA[name] else ("MISSING" if got is None else "MODIFIED")
        out.append("  INTEGRITY %-24s %s" % (name, state))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="path to the repo/ under test")
    ap.add_argument("--turn", default="all", help="1..5, 'integrity' or 'all' (default)")
    ap.add_argument("--quiet", action="store_true", help="summary lines only")
    ap.add_argument(
        "--print-hashes",
        action="store_true",
        help="print the BASELINE_SHA table for this repo and exit (run on a pristine repo/)",
    )
    args = ap.parse_args(argv)

    recorder = _get_recorder()
    ctx = Ctx(args.repo)

    if args.print_hashes:
        for name in BASELINE_SHA:
            print('    "%s": "%s",' % (name, ctx.sha256(name)))
        return 0

    if args.turn == "all":
        selected = list(MODULES)
    elif args.turn == "integrity":
        selected = ["integrity"]
    else:
        selected = ["turn%s" % int(args.turn)]

    total_pass = total_fail = 0
    per_turn = {}
    failures = []

    for turn_name in selected:
        mod = load_turn(turn_name)
        tpass = tfail = 0
        for name, fn in mod.TESTS:
            try:
                fn(ctx)
            except Exception:
                tfail += 1
                recorder.record("%s/%s" % (turn_name, name), False)
                last = traceback.format_exc().strip().splitlines()[-1]
                failures.append((turn_name, name, last))
                if not args.quiet:
                    print("FAIL [%s] %s" % (turn_name, name))
                    print("        %s" % last.strip()[:200])
            else:
                tpass += 1
                recorder.record("%s/%s" % (turn_name, name), True)
                if not args.quiet:
                    print("PASS [%s] %s" % (turn_name, name))
        per_turn[turn_name] = (tpass, tpass + tfail)
        total_pass += tpass
        total_fail += tfail

    print("")
    recorder.publish()
    print("")
    for turn_name in selected:
        p, t = per_turn[turn_name]
        print("  %s: %d/%d" % (turn_name, p, t))
    print("")
    for line in integrity_lines(ctx):
        print(line)
    print(
        "  MEASUREMENT %-24s %s"
        % (
            "storage instrumentation",
            ", ".join("%s x%d" % (k, v) for k, v in sorted(MEASUREMENT_PATHS.items()))
            or "(not exercised)",
        )
    )
    print("")
    print("HIDDEN: %d/%d passed" % (total_pass, total_pass + total_fail))
    if failures:
        print("HIDDEN_FAILED: %s" % ",".join("%s/%s" % (t, n) for t, n, _ in failures))
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
