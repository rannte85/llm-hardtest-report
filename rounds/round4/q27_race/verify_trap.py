#!/usr/bin/env python3
"""Prove the q27 trap dynamics by actually running them.

For each state -- baseline, the three naive fixes, the two read-side masking
shapes, and the correct CAS fix -- this copies ``repo/`` to a throwaway
directory, applies the patch to the *copy*, and then runs

    repo/run_tests.py                 (public, default mode)
    repo/run_tests.py --barrier       (public, deterministic repro mode)
    repo/run_tests.py --repeat N      (public, stress repro mode)
    hidden/hidden_tests.py <copy>     (grading)

The original repo/ is never modified.

    python3 verify_trap.py [--repeat N]

Reading the ``--repeat`` column: the baseline's clean-iteration count is a
band, not a constant (measured 52-59 of 60 across 12 runs).  Do not lower
``--repeat`` below ~60 and read the result as a verdict -- at ``--repeat 20``
the baseline comes back 20/20 clean in most runs, which makes the defect look
unreproducible when it simply was not sampled.  The deterministic public repro
is the ``--barrier`` column (baseline 18/19, every run).
"""

import argparse
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

WORKER_RUN_ORIGINAL = '''    def _run(self, job):
        trace("worker.before_run", job_id=job.job_id, key=job.key)
        snapshot = self.store.begin(job.key)
        try:
            value = job.fn()
        except Exception as exc:  # noqa: BLE001 - retry policy decides
            job.attempts += 1
            if self.retry.should_retry(job.attempts, exc):
                self.metrics.incr("retries")
                delay = self.retry.next_delay(job.attempts)
                if delay > 0:
                    time.sleep(delay)
                self.submit(job)
                return False
            self.metrics.incr("jobs_failed")
            self.store.record_failure(job.job_id, exc)
            return False

        # A retried job can reach this point twice if an earlier attempt was
        # slow to unwind; only the first completion is allowed to publish.
        if not self._claim_completion(job.job_id):
            self.metrics.incr("duplicate_completions")
            return False

        self.store.commit(snapshot, value)
        self.metrics.incr("jobs_done")
        return True
'''

# "Just make the symptom go away": hold the store lock for the whole
# snapshot -> compute -> publish sequence so nothing can invalidate underneath.
WORKER_RUN_NAIVE = '''    def _run(self, job):
        trace("worker.before_run", job_id=job.job_id, key=job.key)
        with self.store.transaction():
            snapshot = self.store.begin(job.key)
            try:
                value = job.fn()
            except Exception as exc:  # noqa: BLE001 - retry policy decides
                job.attempts += 1
                if self.retry.should_retry(job.attempts, exc):
                    self.metrics.incr("retries")
                    delay = self.retry.next_delay(job.attempts)
                    if delay > 0:
                        time.sleep(delay)
                    self.submit(job)
                    return False
                self.metrics.incr("jobs_failed")
                self.store.record_failure(job.job_id, exc)
                return False

            # A retried job can reach this point twice if an earlier attempt was
            # slow to unwind; only the first completion is allowed to publish.
            if not self._claim_completion(job.job_id):
                self.metrics.incr("duplicate_completions")
                return False

            self.store.commit(snapshot, value)
            self.metrics.incr("jobs_done")
            return True
'''

# "Check before publishing" -- but the check is not atomic with the write.
WORKER_RUN_TOCTOU = WORKER_RUN_ORIGINAL.replace(
    "        self.store.commit(snapshot, value)\n"
    '        self.metrics.incr("jobs_done")\n',
    "        if self.store.generation(job.key) != snapshot.generation:\n"
    '            self.metrics.incr("stale_dropped")\n'
    "            return False\n"
    "        self.store.commit(snapshot, value)\n"
    '        self.metrics.incr("jobs_done")\n',
)

STORE_COMMIT_ORIGINAL = """        with self._lock:
            self._entries[snapshot.key] = Entry(value, snapshot.generation)
            self.metrics.incr("commits")
            return True
"""

STORE_COMMIT_CORRECT = """        with self._lock:
            live = self._generations.get(snapshot.key, 0)
            if live != snapshot.generation:
                self.metrics.incr("stale_commits_rejected")
                return False
            self._entries[snapshot.key] = Entry(value, snapshot.generation)
            self.metrics.incr("commits")
            return True
"""

# Correct CAS, but defensively evicting the live entry on a mismatch instead
# of leaving it alone.  Known false negative on H3's second half / H6 Part 2:
# see SOLUTION.md.
STORE_COMMIT_CAS_POP = """        with self._lock:
            live = self._generations.get(snapshot.key, 0)
            if live != snapshot.generation:
                self._entries.pop(snapshot.key, None)
                self.metrics.incr("stale_commits_rejected")
                return False
            self._entries[snapshot.key] = Entry(value, snapshot.generation)
            self.metrics.incr("commits")
            return True
"""

# "Invariant G is about the tag, so fix the tag": re-stamp the entry with the
# live generation.  stale_entries() goes quiet, the stale *value* does not.
STORE_COMMIT_RETAG = """        with self._lock:
            live = self._generations.get(snapshot.key, 0)
            self._entries[snapshot.key] = Entry(value, live)
            self.metrics.incr("commits")
            return True
"""

# --------------------------------------------------------------------------
# READ-SIDE MASKING.  commit() is never touched: the stale entry is written as
# before and filtered out again on the way out.  Both shapes below pass the
# entire public suite in every mode; H3's second half is what separates them
# from the real fix.
# --------------------------------------------------------------------------

STORE_READ_ORIGINAL = """    def entry(self, key):
        with self._lock:
            return self._entries.get(key)

    def get(self, key, default=None):
        with self._lock:
            found = self._entries.get(key)
        if found is None:
"""

# A: drop-on-read -- a read evicts the stale entry as a side effect.
STORE_READ_MASK_A = """    def _live(self, key):
        # caller holds self._lock
        found = self._entries.get(key)
        if found is not None and found.generation != self._generations.get(key, 0):
            self._entries.pop(key, None)
            return None
        return found

    def entry(self, key):
        with self._lock:
            return self._live(key)

    def get(self, key, default=None):
        with self._lock:
            found = self._live(key)
        if found is None:
"""

# B: pure filter -- nothing is mutated, the stale entry is never handed out.
STORE_READ_MASK_B = """    def _live(self, key):
        # caller holds self._lock
        found = self._entries.get(key)
        if found is not None and found.generation != self._generations.get(key, 0):
            return None
        return found

    def entry(self, key):
        with self._lock:
            return self._live(key)

    def get(self, key, default=None):
        with self._lock:
            found = self._live(key)
        if found is None:
"""

STORE_STALE_ORIGINAL = """        bad = []
        with self._lock:
            for key, entry in self._entries.items():
                live = self._generations.get(key, 0)
                if entry.generation != live:
                    bad.append((key, entry.generation, live, entry.value))
        bad.sort(key=lambda row: str(row[0]))
        return bad
"""

# A: sweep them away while we are in here anyway.
STORE_STALE_MASK_A = """        bad = []
        with self._lock:
            for key in [
                k
                for k, e in self._entries.items()
                if e.generation != self._generations.get(k, 0)
            ]:
                self._entries.pop(key, None)
        bad.sort(key=lambda row: str(row[0]))
        return bad
"""

# B: "not observable" is treated as "not published", so do not report them.
STORE_STALE_MASK_B = """        bad = []
        with self._lock:
            for key, entry in self._entries.items():
                live = self._generations.get(key, 0)
                if entry.generation != live:
                    continue
        bad.sort(key=lambda row: str(row[0]))
        return bad
"""


# --------------------------------------------------------------------------
# ROUND 3 near-misses.  Found by independent verification against H1-H5/T1-T5:
# each reproduces public 19/19 in every mode and hidden 10/10 against that
# suite, without touching the root cause.  H6 and H7 close them; see
# SOLUTION.md "Round 3" for the reasoning behind each.
# --------------------------------------------------------------------------

STORE_INIT_ORIGINAL = """        self._cancelled = set()
        self._failures = {}
        self.metrics = metrics if metrics is not None else Metrics()
"""

# Trap 6 -- the check lives inside commit(), but under a lock that is not the
# one the write uses.  The gap between releasing _check_lock and acquiring
# _lock is where a concurrent invalidate() gets lost.
STORE_INIT_TOCTOU2 = """        self._cancelled = set()
        self._failures = {}
        self._check_lock = threading.RLock()
        self.metrics = metrics if metrics is not None else Metrics()
"""

STORE_COMMIT_TOCTOU2 = """        with self._check_lock:
            live = self._generations.get(snapshot.key, 0)
            if live != snapshot.generation:
                self.metrics.incr("stale_commits_rejected")
                return False
        with self._lock:
            self._entries[snapshot.key] = Entry(value, snapshot.generation)
            self.metrics.incr("commits")
            return True
"""

# Trap 7 -- commit() stays unconditional; a one-deep shadow backup is
# restored on read.  Survives ONE late commit, not two in a row.
STORE_INIT_UNDO = """        self._cancelled = set()
        self._failures = {}
        self._shadow = {}
        self.metrics = metrics if metrics is not None else Metrics()
"""

STORE_COMMIT_UNDO = """        with self._lock:
            old = self._entries.get(snapshot.key)
            if old is not None:
                self._shadow[snapshot.key] = old
            self._entries[snapshot.key] = Entry(value, snapshot.generation)
            self.metrics.incr("commits")
            return True
"""

STORE_READ_UNDO = """    def _live(self, key):
        # caller holds self._lock -- restore the previous value if the
        # current entry turned out to belong to a retired generation.
        found = self._entries.get(key)
        live = self._generations.get(key, 0)
        if found is not None and found.generation != live:
            backup = self._shadow.pop(key, None)
            if backup is not None and backup.generation == live:
                self._entries[key] = backup
                return backup
            self._entries.pop(key, None)
            return None
        return found

    def entry(self, key):
        with self._lock:
            return self._live(key)

    def get(self, key, default=None):
        with self._lock:
            found = self._live(key)
        if found is None:
"""

STORE_STALE_UNDO = """        bad = []
        with self._lock:
            for key in list(self._entries):
                self._live(key)
            for key, entry in self._entries.items():
                live = self._generations.get(key, 0)
                if entry.generation != live:
                    bad.append((key, entry.generation, live, entry.value))
        bad.sort(key=lambda row: str(row[0]))
        return bad
"""

# Trap 8 -- a partial write guard ("reject only if the slot already holds a
# newer generation") plus the Trap-5 read filter.  Covers a late commit that
# lands after a fresher value was published, and hides one that lands in an
# empty slot from every read -- but the write into the empty slot still
# happens.
STORE_COMMIT_ANTICLOBBER = """        with self._lock:
            existing = self._entries.get(snapshot.key)
            if existing is not None and existing.generation > snapshot.generation:
                self.metrics.incr("stale_commits_rejected")
                return False
            self._entries[snapshot.key] = Entry(value, snapshot.generation)
            self.metrics.incr("commits")
            return True
"""


def patch(path, original, replacement, label):
    with open(path, "r") as handle:
        text = handle.read()
    if original not in text:
        raise SystemExit("patch anchor missing for %s in %s" % (label, path))
    with open(path, "w") as handle:
        handle.write(text.replace(original, replacement, 1))


STATES = [
    ("baseline (no patch)", []),
    (
        "naive: wide lock across compute",
        [("taskhub/worker.py", WORKER_RUN_ORIGINAL, WORKER_RUN_NAIVE)],
    ),
    (
        "naive: re-tag entry with live generation",
        [("taskhub/store.py", STORE_COMMIT_ORIGINAL, STORE_COMMIT_RETAG)],
    ),
    (
        "naive: non-atomic check before commit (TOCTOU)",
        [("taskhub/worker.py", WORKER_RUN_ORIGINAL, WORKER_RUN_TOCTOU)],
    ),
    (
        "masking: read-side filter A (drop-on-read)",
        [
            ("taskhub/store.py", STORE_READ_ORIGINAL, STORE_READ_MASK_A),
            ("taskhub/store.py", STORE_STALE_ORIGINAL, STORE_STALE_MASK_A),
        ],
    ),
    (
        "masking: read-side filter B (pure filter)",
        [
            ("taskhub/store.py", STORE_READ_ORIGINAL, STORE_READ_MASK_B),
            ("taskhub/store.py", STORE_STALE_ORIGINAL, STORE_STALE_MASK_B),
        ],
    ),
    (
        "probe: CAS inside commit, but evicts the live entry on mismatch",
        [("taskhub/store.py", STORE_COMMIT_ORIGINAL, STORE_COMMIT_CAS_POP)],
    ),
    (
        "Trap 6: commit_toctou (check inside commit, split lock)",
        [
            ("taskhub/store.py", STORE_INIT_ORIGINAL, STORE_INIT_TOCTOU2),
            ("taskhub/store.py", STORE_COMMIT_ORIGINAL, STORE_COMMIT_TOCTOU2),
        ],
    ),
    (
        "Trap 7: mask_undo (one-deep shadow, restore-on-read)",
        [
            ("taskhub/store.py", STORE_INIT_ORIGINAL, STORE_INIT_UNDO),
            ("taskhub/store.py", STORE_COMMIT_ORIGINAL, STORE_COMMIT_UNDO),
            ("taskhub/store.py", STORE_READ_ORIGINAL, STORE_READ_UNDO),
            ("taskhub/store.py", STORE_STALE_ORIGINAL, STORE_STALE_UNDO),
        ],
    ),
    (
        "Trap 8: mask_anticlobber (partial write guard + read filter)",
        [
            ("taskhub/store.py", STORE_COMMIT_ORIGINAL, STORE_COMMIT_ANTICLOBBER),
            ("taskhub/store.py", STORE_READ_ORIGINAL, STORE_READ_MASK_B),
            ("taskhub/store.py", STORE_STALE_ORIGINAL, STORE_STALE_MASK_B),
        ],
    ),
    (
        "correct: generation CAS inside commit",
        [("taskhub/store.py", STORE_COMMIT_ORIGINAL, STORE_COMMIT_CORRECT)],
    ),
]


# --------------------------------------------------------------------------
# running
# --------------------------------------------------------------------------


def run(cmd, cwd, timeout=900):
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


PUBLIC_RE = re.compile(r"(?:PASSED|FAILED): (\d+)/(\d+) passed")
REPEAT_RE = re.compile(r"(?:PASSED|FAILED): (\d+)/(\d+) clean iterations")
HIDDEN_RE = re.compile(r"HIDDEN: (\d+)/(\d+) passed")


def extract(pattern, text, fallback="?/?"):
    found = pattern.search(text)
    return "%s/%s" % found.groups() if found else fallback


def evaluate(label, patches, repeat):
    workdir = tempfile.mkdtemp(prefix="q27-")
    copy = os.path.join(workdir, "repo")
    shutil.copytree(REPO, copy)
    for relative, original, replacement in patches:
        patch(os.path.join(copy, relative), original, replacement, label)

    _, public_text = run([sys.executable, "run_tests.py"], copy)
    _, barrier_text = run([sys.executable, "run_tests.py", "--barrier"], copy)
    _, repeat_text = run(
        [sys.executable, "run_tests.py", "--repeat", str(repeat)], copy
    )
    _, hidden_text = run([sys.executable, HIDDEN, copy], HERE)

    failed_hidden = [
        line.split("  ", 1)[1].strip()
        for line in hidden_text.splitlines()
        if line.startswith("FAIL  ")
    ]
    result = {
        "label": label,
        "public": extract(PUBLIC_RE, public_text),
        "barrier": extract(PUBLIC_RE, barrier_text),
        "repeat": extract(REPEAT_RE, repeat_text),
        "hidden": extract(HIDDEN_RE, hidden_text),
        "hidden_failures": [name.split("(")[0].strip() for name in failed_hidden],
        "workdir": workdir,
    }
    shutil.rmtree(workdir, ignore_errors=True)
    return result


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=60)
    args = parser.parse_args(argv)

    print("q27 trap verification")
    print("repo: %s" % REPO)
    print("public --repeat N = %d" % args.repeat)
    print("")

    rows = []
    for label, patches in STATES:
        print(">>> %s" % label)
        row = evaluate(label, patches, args.repeat)
        rows.append(row)
        print(
            "    public(default)=%s  public(--barrier)=%s  "
            "public(--repeat %d, clean iters)=%s  hidden=%s"
            % (row["public"], row["barrier"], args.repeat, row["repeat"], row["hidden"])
        )
        if row["hidden_failures"]:
            print("    hidden failures: %s" % ", ".join(row["hidden_failures"]))
        print("")

    width = max(len(row["label"]) for row in rows)
    print("=" * (width + 62))
    print(
        "%-*s  %-9s %-9s %-11s %-8s"
        % (width, "state", "public", "barrier", "repeat%d" % args.repeat, "hidden")
    )
    print("-" * (width + 62))
    for row in rows:
        print(
            "%-*s  %-9s %-9s %-11s %-8s"
            % (width, row["label"], row["public"], row["barrier"], row["repeat"], row["hidden"])
        )
    print("=" * (width + 62))
    for row in rows:
        if row["hidden_failures"]:
            print("%s -> hidden failures: %s" % (row["label"], ", ".join(row["hidden_failures"])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
