# Development and Release Guide

## Local checks

```bash
python -m compileall -q src rounds tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v
./llm-hardtest selftest
PYTHONDONTWRITEBYTECODE=1 python rounds/round4/q30v2_policy_conflict/verify_trap.py
PYTHONDONTWRITEBYTECODE=1 python rounds/round4/q31_approval_followup/verify_trap.py
```

The first two commands test the Python harness. `selftest` parses datasets, checks the
source release policy, and exercises the Round 4 harness. Trap proofs verify positive
and negative controls for the policy-conflict tasks.

## Branch and commit hygiene

- Branch from the current default branch.
- Use a focused branch such as `fix/resume-validation` or `feat/backend-notes`.
- Keep generated runs and local configuration out of commits.
- Prefer small commits whose messages describe the behavior or benchmark contract.
- Do not rewrite another contributor's published branch.

## Versioning

The project follows semantic versioning for the harness API. Benchmark content and
scoring compatibility require additional care:

- Patch: documentation or implementation correction with unchanged intended scores.
- Minor: backward-compatible feature or a new separately identified task or metric.
- Major: changed scoring meaning, task replacement, or report schema incompatibility.

If a correction changes historical scores, document the exact compatibility boundary
even when the code version would otherwise be a patch.

## Release checklist

1. Confirm `git status` is clean and inspect tracked files for secrets or local paths.
2. Run all local checks and confirm CI passes.
3. Update `CHANGELOG.md` and release notes with scoring compatibility information.
4. Confirm versions in `pyproject.toml` and `src/pattern0_bench/__init__.py`.
5. Validate example JSON and run a dry campaign configuration.
6. Create an annotated tag such as `v1.0.0` from the reviewed commit.
7. Publish only artifacts containing no credentials or private model content.

The runtime intentionally uses the Python standard library. Any new dependency must
have a clear portability or correctness benefit and a compatible license.
