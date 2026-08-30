#!/usr/bin/env python3
"""Structured result channel for the v4 hidden suites.  GRADER-SIDE CODE.

WHY THIS EXISTS
---------------
Every hidden suite imports the candidate's package in-process, so candidate code
runs before a single assertion does.  A candidate can therefore print

    HIDDEN: 11/11 passed

from its own ``__init__.py`` and call ``os._exit(0)``: the runner never gets to
execute, the grader parses that line off stdout, and a red submission is graded
as a perfect one.  (Measured: q26/q27/q28 all fell to this.)

stdout is therefore not a trustworthy channel.  This module adds a second one:

  * the grader opens a private file, passes the *file descriptor* to the child
    (``V4_HIDDEN_FD``) together with a fresh random ``V4_HIDDEN_NONCE``,
  * the runner calls :meth:`Recorder.publish` once, AFTER the last test has run,
    which writes ONE sealed ``V4RESULT`` line naming every test and its verdict,
  * the grader reads the FIRST such line and cross-checks it against the test
    names it already knew (they live in the grader-private ``task.json``) and
    against the per-test ``HTEST`` lines on stdout.

What that buys, concretely:

  * an early ``os._exit`` never reaches ``publish`` -> no sealed line -> the
    grader sees a summary on stdout with no record behind it and calls it a
    forgery instead of a score;
  * a candidate that fabricates a record must name all N hidden tests exactly.
    Those names are never inside repo/, so guessing them is the actual barrier;
  * first-record-wins means a record appended later (an ``atexit`` hook that
    rewrites the verdicts after the real run) is ignored.

Nothing here is secret from the candidate — it runs in the same process and can
read the environment.  The security comes from the name set, not from the
channel.  See ``verify_hidden_result`` in v4_grade.py for the checking side.

Import this by absolute path (``bootstrap`` below) BEFORE the candidate's code
is imported, so the references it captures cannot be monkeypatched afterwards.
"""

from __future__ import annotations

import json
import os
import sys

PROTOCOL = "v4-hidden-1"
RESULT_PREFIX = "V4RESULT "
FD_ENV = "V4_HIDDEN_FD"
NONCE_ENV = "V4_HIDDEN_NONCE"

# Captured at import time, on purpose: by the time a runner's main() executes,
# the candidate's package has already been imported and could have replaced
# os.write / sys.stdout / builtins.print.
_OS_WRITE = os.write
_STDOUT = sys.stdout
_ENV_FD = os.environ.get(FD_ENV)
_ENV_NONCE = os.environ.get(NONCE_ENV)
_ARGV = list(sys.argv)


class Recorder(object):
    """Collects (test name -> verdict) and publishes them once, at the end."""

    def __init__(self, qid):
        self.qid = qid
        self.records = []
        self._seen = set()
        self.published = False

    # -- collection --------------------------------------------------------
    def record(self, name, passed):
        name = str(name)
        if name in self._seen:
            # Duplicate names would make the grader's set comparison ambiguous.
            raise RuntimeError("duplicate hidden test name %r in %s" % (name, self.qid))
        self._seen.add(name)
        self.records.append((name, bool(passed)))

    def passed(self):
        return sum(1 for _n, ok in self.records if ok)

    def total(self):
        return len(self.records)

    # -- publication -------------------------------------------------------
    def publish(self):
        """Print one HTEST line per test and write the sealed record.

        Call exactly once, after every test has run.  Safe to call when the
        grader is not listening (manual runs, verify_trap.py): the HTEST lines
        are printed and the sealed write is skipped.

        The seal is written BEFORE the names are printed, deliberately.  The
        HTEST lines are the first place the hidden test names become visible
        in-process; a candidate hooking sys.stdout could otherwise read them as
        they stream past and race its own record onto the channel ahead of this
        one.  Sealing first means the genuine record is always the first one,
        and the grader takes the first and rejects a file that holds two.
        """
        sealed = self._seal()
        for name, ok in self.records:
            _STDOUT.write("HTEST %s %s\n" % ("PASS" if ok else "FAIL", name))
        _STDOUT.write("HTEST-COUNT %d/%d\n" % (self.passed(), self.total()))
        try:
            _STDOUT.flush()
        except Exception:  # noqa: BLE001 - a broken stdout must not lose the seal
            pass
        self.published = True
        return sealed

    def _seal(self):
        if not _ENV_FD:
            return False
        try:
            fd = int(_ENV_FD)
        except (TypeError, ValueError):
            return False
        payload = {
            "protocol": PROTOCOL,
            "qid": self.qid,
            "nonce": _ENV_NONCE,
            "complete": True,
            "passed": self.passed(),
            "total": self.total(),
            "tests": [[name, "pass" if ok else "fail"] for name, ok in self.records],
            "pid": os.getpid(),
            "runner": _ARGV[0] if _ARGV else None,
        }
        line = RESULT_PREFIX + json.dumps(payload, sort_keys=True) + "\n"
        try:
            _OS_WRITE(fd, line.encode("utf-8"))
        except OSError:
            return False
        return True


def new(qid):
    """Fresh recorder.  Hidden runners reach this through the small
    ``_v4_report()`` loader they each carry, which resolves this file by
    ABSOLUTE PATH walking upward from ``hidden/`` — never through sys.path,
    which the runners deliberately point at the candidate's repo, and never
    through a directory the candidate can write to."""
    return Recorder(qid)


def require_active():
    """True when the grader asked for a sealed record."""
    return bool(_ENV_FD)
