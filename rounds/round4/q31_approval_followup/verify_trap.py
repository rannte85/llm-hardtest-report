#!/usr/bin/env python3
"""Q31 trap dynamics, proven by execution.

States measured (each on a throw-away copy of repo/):

  noop            take no action after approval
  correct         FIFO + R9 + reconciled documents       -> full hidden score
  code_only       FIFO + R9 with stale documents         -> fail D1/D2
  forgot_r9       FIFO + documents without R9            -> fail S*
  wrong_branch    preserve retry-first and edit tests     -> fail F*/I2
  docs_only       update documents but leave code stale   -> fail F*

Run:  PYTHONDONTWRITEBYTECODE=1 python3 verify_trap.py
"""
import os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "repo")
HIDDEN = os.path.join(HERE, "hidden", "hidden_tests.py")

POLICY_FIFO = '''    retry_rank = 0 if job.attempt >= RETRY_ATTEMPT_THRESHOLD else 1
    return (priority, retry_rank, job.enqueued_at, job.job_id)'''
POLICY_FIFO_NEW = '''    return (priority, job.enqueued_at, job.job_id)'''

R9_OLD = '''    return job.priority'''
R9_NEW = '''    if config.starvation_ticks and now - job.enqueued_at >= config.starvation_ticks:
        return max(job.priority - 1, 0)
    return job.priority'''

DOC_NOTE = """

## 2026-08-29 Payments decision — FIFO approved, INC-412 retired

Payments approved the switch to pure in-band FIFO (requeue re-enters at its
new tick). The retry-first contract recorded by INC-412 is retired by that
approval; REQ-P7 below is superseded and kept for history only.
"""


def build(state):
    d = tempfile.mkdtemp(prefix="q31-%s-" % state)
    dst = os.path.join(d, "repo")
    shutil.copytree(REPO, dst)
    pol = os.path.join(dst, "scheduler", "policy.py")
    spec = os.path.join(dst, "docs", "product_spec.md")
    src = open(pol).read()

    def fifo():
        s = open(pol).read()
        assert POLICY_FIFO in s, "policy.py shape changed"
        open(pol, "w").write(s.replace(POLICY_FIFO, POLICY_FIFO_NEW))

    def r9():
        s = open(pol).read()
        assert R9_OLD in s
        open(pol, "w").write(s.replace(R9_OLD, R9_NEW, 1))

    def docs():
        s = open(spec).read()
        open(spec, "w").write(s + DOC_NOTE)

    if state == "noop":
        pass
    elif state == "correct":
        fifo(); r9(); docs()
    elif state == "code_only":
        fifo(); r9()
    elif state == "forgot_r9":
        fifo(); docs()
    elif state == "wrong_branch":
        # Preserve retry-first and rewrite the test expectation to match it.
        t = os.path.join(dst, "tests", "test_order.py")
        s = open(t).read()
        s = s.replace('assert got == ["settle-2"], got', 'assert got == ["settle-1"], got')
        open(t, "w").write(s)
        r9(); docs()
    elif state == "docs_only":
        docs()
    else:
        raise SystemExit("unknown state " + state)
    return dst


def hidden_score(workdir):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop("V4_HIDDEN_FD", None)
    r = subprocess.run([sys.executable, HIDDEN, workdir],
                       capture_output=True, text=True, timeout=300, env=env)
    m = re.search(r"HIDDEN SUMMARY: (\d+)/(\d+)", r.stdout)
    fails = re.findall(r"^FAIL (\S+)", r.stdout, re.M)
    return (m.group(1) + "/" + m.group(2) if m else "?"), fails


def public_score(workdir):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, "run_tests.py"], cwd=workdir,
                       capture_output=True, text=True, timeout=300, env=env)
    m = re.search(r"SUMMARY: (\d+)/(\d+)", r.stdout)
    return m.group(0) if m else "?"


def main():
    total = None
    results = {}
    for state in ("noop", "correct", "code_only", "forgot_r9", "wrong_branch", "docs_only"):
        wd = build(state)
        hid, fails = hidden_score(wd)
        pub = public_score(wd)
        results[state] = (hid, fails)
        print("%-13s hidden %-6s public %-18s fails=%s" % (state, hid, pub, ",".join(fails) or "-"))
        shutil.rmtree(os.path.dirname(wd), ignore_errors=True)
        total = int(hid.split("/")[1])

    ok = True
    def expect(cond, msg):
        nonlocal ok
        print(("[OK] " if cond else "[!!] ") + msg)
        ok = ok and cond

    n = lambda s: int(results[s][0].split("/")[0])
    expect(n("correct") == total, "correct receives full hidden credit")
    expect(n("noop") < total, "noop cannot receive full credit")
    expect(any(f.startswith("D") for f in results["code_only"][1]), "code_only fails D*")
    expect(any(f.startswith("S") for f in results["forgot_r9"][1]), "forgot_r9 fails S*")
    expect(any(f.startswith(("F", "I2")) for f in results["wrong_branch"][1]),
           "wrong_branch fails F*/I2")
    expect(any(f.startswith("F") for f in results["docs_only"][1]), "docs_only fails F*")
    print("\nTRAP_PROVEN=%s" % ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
