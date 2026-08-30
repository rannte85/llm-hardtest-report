#!/usr/bin/env python3
"""Prove the q26 trap dynamics by execution, not by argument.

Builds three throw-away copies of ``repo/`` and, for each, runs the public
runner and the hidden suite in a fresh subprocess:

  [baseline]   the repo as shipped to the model
  [naive fix]  the tempting one-line patch inside billing.py (function A)
  [correct]    the one-line patch inside normalize.build_segments

The original ``repo/`` is never modified.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "repo")
HIDDEN = os.path.join(HERE, "hidden", "hidden_tests.py")

# --------------------------------------------------------------------------
# patches
# --------------------------------------------------------------------------

NAIVE_OLD = """    minutes = segment.minutes()
    if segment.grace:
        minutes = minutes - card.grace_minutes
    return max(0, minutes)
"""

NAIVE_NEW = """    minutes = segment.minutes()
    # A segment that begins exactly at midnight is a continuation of the
    # previous calendar day, so it must not re-apply the grace allowance.
    if segment.grace and not (segment.start.hour == 0 and segment.start.minute == 0):
        minutes = minutes - card.grace_minutes
    return max(0, minutes)
"""

CORRECT_OLD = """    segments: List[Segment] = []
    for (slice_start, slice_end) in windows:
        segments.append(
            Segment(start=slice_start, end=slice_end, grace=grace_pending)
        )
    return segments
"""

CORRECT_NEW = """    segments: List[Segment] = []
    for (slice_start, slice_end) in windows:
        segments.append(
            Segment(start=slice_start, end=slice_end, grace=grace_pending)
        )
        # GR-1: the allowance belongs to the stay, so it is spent by the
        # first segment and never re-granted to a continuation day.
        grace_pending = False
    return segments
"""

# A third, "half right" attempt: the solver understands GR-1 but repairs it at
# the wrong layer, inside billing's own itemiser.  garage/ledger.py builds its
# segments independently, so the ledger stays broken.
PARTIAL_OLD = """    return [(seg, charge_segment(seg, card)) for seg in build_segments(start, end, card)]
"""

PARTIAL_NEW = """    out = []
    for index, seg in enumerate(build_segments(start, end, card)):
        seg.grace = seg.grace and index == 0
        out.append((seg, charge_segment(seg, card)))
    return out
"""

PATCHES = {
    "baseline": [],
    "naive fix": [(os.path.join("garage", "billing.py"), NAIVE_OLD, NAIVE_NEW)],
    "partial fix": [(os.path.join("garage", "billing.py"), PARTIAL_OLD, PARTIAL_NEW)],
    "correct fix": [(os.path.join("garage", "normalize.py"), CORRECT_OLD, CORRECT_NEW)],
}

STATES = ("baseline", "naive fix", "partial fix", "correct fix")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def make_copy(root, name):
    dest = os.path.join(root, name.replace(" ", "_"))
    shutil.copytree(REPO, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return dest


def apply_patches(dest, patches):
    for (relpath, old, new) in patches:
        path = os.path.join(dest, relpath)
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        if text.count(old) != 1:
            raise SystemExit(
                "PATCH ANCHOR NOT UNIQUE in {0} (found {1})".format(
                    relpath, text.count(old)
                )
            )
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace(old, new))


def run(cmd, cwd=None):
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
    )
    return proc.returncode, proc.stdout


def parse_public(out):
    m = re.search(r"SUMMARY: (\d+)/(\d+) passed", out)
    if not m:
        raise SystemExit("could not parse public summary from:\n" + out)
    return int(m.group(1)), int(m.group(2))


def parse_hidden(out):
    m = re.search(r"HIDDEN SUMMARY: (\d+)/(\d+) passed", out)
    if not m:
        raise SystemExit("could not parse hidden summary from:\n" + out)
    return int(m.group(1)), int(m.group(2))


def failed_names(out, prefix):
    return [
        line.split(" ", 1)[1].strip()
        for line in out.splitlines()
        if line.startswith(prefix)
    ]


# --------------------------------------------------------------------------

def main():
    if not os.path.isdir(REPO):
        raise SystemExit("missing repo/ at {0}".format(REPO))

    root = tempfile.mkdtemp(prefix="q26_verify_")
    results = {}
    try:
        for name in STATES:
            dest = make_copy(root, name)
            apply_patches(dest, PATCHES[name])

            pub_rc, pub_out = run([sys.executable, "run_tests.py"], cwd=dest)
            hid_rc, hid_out = run([sys.executable, HIDDEN, dest])

            pub_pass, pub_total = parse_public(pub_out)
            hid_pass, hid_total = parse_hidden(hid_out)
            results[name] = {
                "public": (pub_pass, pub_total),
                "hidden": (hid_pass, hid_total),
                "public_failed": failed_names(pub_out, "FAIL  "),
                "hidden_failed": failed_names(hid_out, "HFAIL "),
                "public_rc": pub_rc,
                "hidden_rc": hid_rc,
            }

            print("=" * 74)
            print("[{0}]".format(name))
            print("=" * 74)
            print("  public tests : {0}/{1} passed".format(pub_pass, pub_total))
            for n in results[name]["public_failed"]:
                print("      FAIL {0}".format(n))
            print("  hidden tests : {0}/{1} passed".format(hid_pass, hid_total))
            for n in results[name]["hidden_failed"]:
                print("      FAIL {0}".format(n))
            print("")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # ---- trap assertions -------------------------------------------------
    base = results["baseline"]
    naive = results["naive fix"]
    partial = results["partial fix"]
    good = results["correct fix"]

    naive_broken = sorted(
        set(naive["hidden_failed"]) - set(base["hidden_failed"])
    )

    print("=" * 74)
    print("TRAP MATRIX")
    print("=" * 74)
    print("  {0:<13} {1:>10} {2:>10}".format("state", "public", "hidden"))
    for name in STATES:
        r = results[name]
        print(
            "  {0:<13} {1:>10} {2:>10}".format(
                name,
                "{0}/{1}".format(*r["public"]),
                "{0}/{1}".format(*r["hidden"]),
            )
        )
    print("")
    print("  hidden tests newly BROKEN by the naive fix ({0}):".format(len(naive_broken)))
    for n in naive_broken:
        print("      - {0}".format(n))
    print("")

    checks = [
        ("baseline public is 18/20", base["public"] == (18, 20)),
        ("naive fix makes public 20/20", naive["public"] == (20, 20)),
        ("correct fix makes public 20/20", good["public"] == (20, 20)),
        ("correct fix makes hidden 7/7", good["hidden"] == (7, 7)),
        ("naive fix breaks exactly 3 hidden tests", len(naive_broken) == 3),
        ("naive fix hidden score is worse than baseline",
         naive["hidden"][0] < base["hidden"][0]),
        ("correct fix hidden score beats naive",
         good["hidden"][0] > naive["hidden"][0]),
        ("partial (wrong-layer) fix also reaches public 20/20",
         partial["public"] == (20, 20)),
        ("partial (wrong-layer) fix still fails hidden",
         partial["hidden"][0] < 7),
    ]
    all_ok = True
    print("=" * 74)
    print("ASSERTIONS")
    print("=" * 74)
    for label, cond in checks:
        print("  [{0}] {1}".format("OK " if cond else "BAD", label))
        all_ok = all_ok and cond

    print("")
    print("TRAP PROVEN" if all_ok else "TRAP NOT PROVEN")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
