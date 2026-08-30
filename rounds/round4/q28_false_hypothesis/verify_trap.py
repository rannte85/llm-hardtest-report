#!/usr/bin/env python3
"""Prove the q28 trap dynamics by execution, not by argument.

For each of four states the script

  * copies ``repo/`` to a throw-away directory (the real repo is never touched),
  * applies that state's patch to the copy,
  * runs the public suite (``run_tests.py``) inside the copy,
  * runs the untouched hidden suite (``hidden/hidden_tests.py``) against the copy,

and prints the four (public, hidden) pairs side by side.

    python3 verify_trap.py [-v]

Standard library only.
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

PUBLIC_RE = re.compile(r"^PUBLIC: (\d+)/(\d+)", re.M)
HIDDEN_RE = re.compile(r"^HIDDEN: (\d+)/(\d+)", re.M)

# --------------------------------------------------------------------------- #
# patches
# --------------------------------------------------------------------------- #

COERCE_HELPER = '''def _coerce(key, raw_value):
    """Convert an override to the type declared for ``key`` in ``SCHEMA``."""
    expected = SCHEMA.get(key)
    if expected is None or isinstance(raw_value, expected):
        return raw_value
    try:
        return expected(str(raw_value).strip())
    except (TypeError, ValueError):
        raise ConfigError(
            "configuration key %r must be %s, got %r"
            % (key, expected.__name__, raw_value))


def apply_overrides(config, overrides):'''

NAIVE_TIMEOUT = {
    "name": "naive fix A: raise the network timeout",
    "blurb": "config/service.env  SVC_TIMEOUT_MS  100 -> 5000",
    "edits": [(
        os.path.join("config", "service.env"),
        "SVC_TIMEOUT_MS=100",
        "SVC_TIMEOUT_MS=5000",
    )],
}

NAIVE_CAP = {
    "name": "naive fix B: hard-code a retry ceiling",
    "blurb": "svc/service.py  `if attempt >= 5 or self.policy.is_last_attempt(attempt)`",
    "edits": [(
        os.path.join("svc", "service.py"),
        "                if self.policy.is_last_attempt(attempt):",
        "                if attempt >= 5 or self.policy.is_last_attempt(attempt):",
    )],
}

CORRECT = {
    "name": "correct fix: coerce overrides to their declared type",
    "blurb": "svc/config.py  apply_overrides() + validate the merged config",
    "edits": [
        (
            os.path.join("svc", "config.py"),
            "def apply_overrides(config, overrides):",
            COERCE_HELPER,
        ),
        (
            os.path.join("svc", "config.py"),
            "        merged[key] = raw_value",
            "        merged[key] = _coerce(key, raw_value)",
        ),
        (
            os.path.join("svc", "config.py"),
            "    overrides = collect_overrides(read_env_file(env_file), environ)\n"
            "    return apply_overrides(defaults, overrides)",
            "    overrides = collect_overrides(read_env_file(env_file), environ)\n"
            "    return validate(apply_overrides(defaults, overrides))",
        ),
    ],
}

PARTIAL = {
    "name": "partial fix: coerce at the symptom site only",
    "blurb": "svc/retry.py  self.max_attempts = int(max_attempts)",
    "edits": [(
        os.path.join("svc", "retry.py"),
        "        self.max_attempts = max_attempts",
        "        self.max_attempts = int(max_attempts)",
    )],
}

BASELINE = {"name": "baseline (repo as shipped)", "blurb": "no changes", "edits": []}

STATES = (BASELINE, NAIVE_TIMEOUT, NAIVE_CAP, PARTIAL, CORRECT)


def apply_edits(root, edits):
    for relative_path, old, new in edits:
        path = os.path.join(root, relative_path)
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        occurrences = text.count(old)
        if occurrences != 1:
            raise SystemExit(
                "patch anchor found %d times (expected exactly 1) in %s:\n%r"
                % (occurrences, relative_path, old))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text.replace(old, new))


def run(command, cwd):
    result = subprocess.run(
        command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=300, text=True)
    return result.stdout


def score(pattern, output, label):
    match = pattern.search(output)
    if not match:
        raise SystemExit("could not find the %s summary line in:\n%s" % (label, output))
    return int(match.group(1)), int(match.group(2))


def evaluate(state, verbose=False):
    workdir = tempfile.mkdtemp(prefix="q28-")
    try:
        copy = os.path.join(workdir, "repo")
        shutil.copytree(REPO, copy)
        apply_edits(copy, state["edits"])

        public_output = run([sys.executable, "run_tests.py"], cwd=copy)
        hidden_output = run([sys.executable, HIDDEN, copy], cwd=workdir)

        if verbose:
            print(public_output)
            print(hidden_output)

        public = score(PUBLIC_RE, public_output, "public")
        hidden = score(HIDDEN_RE, hidden_output, "hidden")
        failing_public = re.findall(r"^  FAIL  (\S+)", public_output, re.M)
        failing_hidden = re.findall(r"^  FAIL  (\S+)", hidden_output, re.M)
        return public, hidden, failing_public, failing_hidden
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def main(argv):
    verbose = "-v" in argv or "--verbose" in argv
    print("q28 trap verification -- every number below comes from an actual run")
    print("repo   : %s" % REPO)
    print("hidden : %s" % HIDDEN)

    rows = []
    for state in STATES:
        print()
        print("=" * 78)
        print("[%s]" % state["name"])
        print("  patch: %s" % state["blurb"])
        public, hidden, failing_public, failing_hidden = evaluate(state, verbose)
        print("  public tests : %d/%d" % public)
        print("  hidden tests : %d/%d" % hidden)
        if failing_public:
            print("  public failures:")
            for name in failing_public:
                print("      - %s" % name)
        if failing_hidden:
            print("  hidden failures:")
            for name in failing_hidden:
                print("      - %s" % name)
        rows.append((state["name"], public, hidden))

    print()
    print("=" * 78)
    print("%-52s %-14s %s" % ("state", "public", "hidden"))
    print("-" * 78)
    for name, public, hidden in rows:
        print("%-52s %-14s %s" % (name, "%d/%d" % public, "%d/%d" % hidden))
    print("-" * 78)

    baseline_public, baseline_hidden = rows[0][1], rows[0][2]
    timeout_public, timeout_hidden = rows[1][1], rows[1][2]
    cap_public, cap_hidden = rows[2][1], rows[2][2]
    partial_public, partial_hidden = rows[3][1], rows[3][2]
    correct_public, correct_hidden = rows[4][1], rows[4][2]

    checks = [
        ("baseline fails some public tests",
         baseline_public[0] < baseline_public[1]),
        ("baseline fails most hidden tests",
         baseline_hidden[0] < baseline_hidden[1]),
        ("naive fix A improves the public score",
         timeout_public[0] > baseline_public[0]),
        ("naive fix A does not fix the hidden tests",
         timeout_hidden[0] < timeout_hidden[1]),
        ("naive fix B passes every public test",
         cap_public[0] == cap_public[1]),
        ("naive fix B still fails hidden tests",
         cap_hidden[0] < cap_hidden[1]),
        ("partial fix passes every public test",
         partial_public[0] == partial_public[1]),
        ("partial fix still fails hidden tests",
         partial_hidden[0] < partial_hidden[1]),
        ("correct fix passes every public test",
         correct_public[0] == correct_public[1]),
        ("correct fix passes every hidden test",
         correct_hidden[0] == correct_hidden[1]),
    ]
    print()
    all_ok = True
    for label, condition in checks:
        print("  [%s] %s" % ("ok" if condition else "XX", label))
        all_ok = all_ok and condition
    print()
    print("TRAP PROVEN: %s" % ("yes" if all_ok else "NO"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
