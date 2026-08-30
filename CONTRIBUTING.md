# Contributing

Thank you for improving LLM Hardtest Report. Contributions should keep benchmark
results reproducible, graders independent from candidate output, and public claims
auditable.

## Before opening an issue

- Search existing issues and discussions.
- Run `./llm-hardtest selftest` on the current default branch.
- For server compatibility problems, record the server name/version, endpoint type,
  model identifier, Python version, operating system, and a redacted error.
- Never post API keys, full environment dumps, private prompts, or proprietary model
  outputs without permission.

Usage questions belong in GitHub Discussions when enabled. Reproducible defects use
the bug form. Benchmark or scoring changes use the proposal form.

## Development setup

```bash
git clone https://github.com/rannte85/llm-hardtest-report.git
cd llm-hardtest-report
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Run all release checks before opening a pull request:

```bash
python -m compileall -q src rounds tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v
./llm-hardtest selftest
PYTHONDONTWRITEBYTECODE=1 python rounds/round4/q30v2_policy_conflict/verify_trap.py
PYTHONDONTWRITEBYTECODE=1 python rounds/round4/q31_approval_followup/verify_trap.py
```

## Change rules

- Keep shipped source, comments, prompts, tests, CLI output, and documentation in
  English so one release works for the widest audience.
- Add comments for design constraints, grading boundaries, and non-obvious safety
  choices. Do not narrate obvious syntax or leave commented-out code.
- Keep dependencies at zero unless a strong portability case is documented.
- Do not weaken held-back checks to accommodate a model submission.
- Do not include generated `runs/`, credentials, model weights, caches, or personal
  filesystem paths.
- Add or update tests for behavior changes and update user-facing documentation in
  the same pull request.
- Keep refactors separate from scoring changes when practical.

## Adding or changing benchmark tasks

New repository tasks must:

1. Keep the candidate workspace in `repo/` and grader-only material in `hidden/`.
2. Include a deterministic public runner and a documented grading contract.
3. Include positive and negative controls, plus a trap-verification script.
4. Declare whether tests and measurement artifacts are protected, editable, or
   subject to semantic review.
5. Start each attempt from a pristine task copy.
6. Explain any score incompatibility with previous releases in `CHANGELOG.md`.

If a visible authority source makes previously rejected behavior defensible, treat it
as a grader-design defect: document the conflict, add controls, and fix the benchmark
contract rather than grading around it.

## Pull requests

Keep pull requests focused and complete the template. Maintainers review correctness,
benchmark validity, backward compatibility, documentation, test evidence, and the
risk of contaminating held-back evaluation material. At least one maintainer review
is expected before merge.

By contributing, you agree that your contribution is licensed under this repository's
MIT License and that you have the right to submit it.
