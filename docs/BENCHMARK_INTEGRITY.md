# Benchmark Integrity

The benchmark is transparent and locally reproducible. Those strengths create limits
that must be disclosed with published results.

## What "hidden" means here

For Round 4, the candidate receives only a fresh copy of the task's `repo/` directory.
The runner does not copy `hidden/`, reference solutions, task metadata, or grader
notes into that working directory. Held-back checks run afterward against the
submission.

Because this is a public repository, these materials are auditable by people and may
be present elsewhere on the same machine. They are not cryptographic secrets. A
tool-enabled agent with broad filesystem access may find them, and a future model may
have encountered them during training.

## Appropriate uses

- local model diagnostics;
- regression tests across quantization or server changes;
- transparent analysis of failure modes;
- agent-harness engineering and grader research;
- reproducible comparisons that state the contamination caveat.

## Inappropriate claims

- a contamination-resistant public leaderboard;
- proof of general intelligence or production safety;
- statistical significance from one attempt;
- direct equality between answer accuracy and coding-agent release readiness;
- speed comparisons made under different hardware or concurrency conditions.

## Isolation recommendations

For more trustworthy local runs:

1. Run the benchmark controller in an account or container the candidate cannot
   inspect.
2. Mount only the copied candidate repository into the agent workspace.
3. Deny network access unless the task explicitly needs it.
4. Use short-lived, least-privilege credentials and no production secrets.
5. Keep controller logs and held-back checks outside the candidate-visible mount.
6. Record the benchmark commit and verify the worktree is clean.
7. Preserve every attempt, including failures and timeouts.

The bundled runner is designed for trusted local evaluation and artifact isolation;
it does not by itself enforce all of these operating-system boundaries.

## Changing graders

A scoring or held-back-test change can invalidate comparison with older reports.
Changes must include positive and negative controls, an explanation of the authority
source, trap verification, and a changelog entry. Never weaken a grader solely to make
a particular model pass.

## Reporting results

At minimum publish the repository commit and dirty/clean state, full campaign config
with secrets removed, model artifact revision and quantization, server version,
hardware, concurrency, timeout, repetition count, complete report, and whether the
agent could access this source tree.
