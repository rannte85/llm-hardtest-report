# Implementation Plan

This plan turns observed campaign failures into improvements that can be reviewed,
tested, and released independently. Each phase must land as its own commit and must
leave the repository installable and the existing benchmark semantics documented.

## Design rules

- Do not count provider truncation, transport failures, or malformed responses as
  wrong model answers.
- Do not silently retry or change generation limits. Any retry policy must be
  explicit in the configuration and preserved in the run snapshot.
- Keep old result files readable. New result fields are additive unless a major
  release explicitly documents a schema break.
- Make benchmark packs self-describing before adding more hard-coded round branches.
- Every grader change requires positive controls, negative controls, and a regression
  test proving the intended distinction.
- Preserve raw evidence needed to explain a score without storing credentials.

## Phase 1 — Result integrity

Goal: distinguish a wrong answer from a completion that never produced a final answer.

Deliverables:

1. Add `INCOMPLETE` as a first-class result status for output-limit termination and
   other explicitly recognized unfinished generations.
2. Keep `PASS`, `FAIL`, `INCOMPLETE`, `REVIEW`, and `INVALID` separate in progress,
   saved results, summaries, and Markdown reports.
3. Exclude incomplete work from the correctness denominator while retaining its wall
   time and token evidence.
4. Treat an attempt containing incomplete items as resumable, just like an attempt
   containing infrastructure errors.
5. Add doctor diagnostics for empty final content and output-limit termination.
6. Document the scoring and compatibility behavior.

Acceptance checks:

- A wrong final answer remains `FAIL`.
- `finish_reason=length` becomes `INCOMPLETE`, even if partial reasoning exists.
- A stopped response without the required answer line remains `FAIL`; format
  noncompliance is not automatically excused.
- Existing result files without a `status` field still generate reports.
- The terminal dashboard displays an independent incomplete count.

## Phase 2 — Failure inspection and focused replay

Goal: let a user understand and rerun only unresolved work without editing result
files or constructing internal paths manually.

Deliverables:

1. Add `llm-hardtest inspect RUN_DIR` with a concise table of failed, incomplete,
   review-required, and infrastructure-invalid items.
2. Add machine-readable `--json` output for automation.
3. Add focused selection for Round 1/2 question IDs and Round 4 task IDs.
4. Add an explicit failed-only replay command or option that writes a new attempt and
   records its parent run and selection policy.
5. Never overwrite the original attempt or silently merge scores from incompatible
   configurations.

Acceptance checks:

- Inspection works for both current and pre-status result schemas.
- A replay selects only unresolved item IDs and produces a new evidence directory.
- A clean run reports that no unresolved work exists and exits successfully.
- Invalid run paths and config mismatches fail before calling a model.

## Phase 3 — Reusable benchmark packs

Goal: remove the need to modify CLI, orchestration, progress, and reporting code for
every new benchmark family.

Deliverables:

1. Define a versioned manifest schema containing pack ID, title, runner kind,
   capabilities, unit count, result schema, time limits, and grader/control commands.
2. Add `llm-hardtest pack validate PATH` and validation tests for unsafe paths,
   duplicate IDs, missing assets, and unsupported schema versions.
3. Add content fingerprints so reports identify the exact task and grader revision.
4. Adapt existing rounds incrementally; compatibility adapters may remain while the
   legacy structure is migrated.
5. Document authoring, positive controls, negative controls, and release requirements.

Acceptance checks:

- A minimal external pack validates without importing repository-private modules.
- A malformed or path-traversing pack is rejected.
- Changing a graded asset changes the recorded fingerprint.
- Existing rounds continue to produce equivalent scores.

## Phase 4 — Round 5 pilot

Goal: evaluate long-horizon evidence revision and safe implementation, rather than
increasing difficulty only through repository size.

The first pilot will model an evolving production incident. The candidate receives a
plausible but misleading incident report, must obtain deterministic evidence, preserve
unrelated work, implement the smallest valid fix, and revise its plan after a later
compatibility constraint. The controller will grade:

- evidence collection and hypothesis revision;
- product behavior under public, held-back, and metamorphic tests;
- regression-test quality;
- preservation of user changes and approval boundaries;
- false-green and test-tampering behavior;
- factual accuracy of the final handoff;
- elapsed time and tool cost as separate, non-correctness metrics.

The pilot must include at least one correct control, three realistic partial fixes,
one test-tampering control, and one honest blocked handoff where applicable. A task is
not promoted to the canonical set until all controls produce stable expected outcomes
and at least two materially different models have attempted it multiple times.

Current implementation status: the control matrix and non-canonical research runner
are complete. The runner enforces two read-only turns, one explicitly approved write
turn, persistent-session delivery, non-empty outputs, hidden grading, immutable raw
evidence, and independent final-report accuracy. Canonical promotion remains blocked
on repeated evidence from at least two materially different models and manual grader
ambiguity review.

## Phase 5 — Release verification

Every phase ends with the relevant focused tests. Before release, also run:

```bash
python -m compileall -q src rounds tests
PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -v
./llm-hardtest selftest
python rounds/round4/q30v2_policy_conflict/verify_trap.py
python rounds/round4/q31_approval_followup/verify_trap.py
python -m build
```

Install the resulting wheel into a clean temporary virtual environment and run
`llm-hardtest selftest`, configuration validation, inspection, and a dry campaign
outside the source checkout. Finish with a secret/path scan, a Markdown-link check,
and an adversarial review of resume and scoring behavior.

## Phase 6 — Empirical discrimination analysis

Goal: distinguish a benchmark that is merely difficult from one that reliably
separates model configurations beyond their own repeat instability.

Deliverables:

1. Analyze item-level evidence from multiple completed run directories without
   copying prompts, raw responses, model identifiers, paths, or credentials.
2. Never pool different benchmark pack fingerprints or count the same resolved run
   twice.
3. Keep incomplete, manual-review, and infrastructure-invalid observations outside
   correctness and correlation calculations.
4. Report pass rate, normalized difficulty balance, corrected item-total correlation,
   ceiling/floor/negative-signal review flags, configuration separation, and repeat
   instability in deterministic Markdown and JSON.
5. Reject evidence symlinks that escape their run directory and document sample-size
   and interpretation limits.

Acceptance checks:

- Synthetic positive, ceiling, negative-discrimination, and incomplete controls are
  classified independently.
- Repeated identical configurations contribute to within-configuration instability;
  materially different configurations contribute to between-configuration separation.
- Round 4 release outcomes and Round 1–3 item statuses use the same analysis contract.
- An installed wheel can analyze a real historical run outside the source checkout.
