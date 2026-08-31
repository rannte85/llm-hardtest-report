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

Cross-pilot analysis is also implemented. It compares eight-axis outcome distance
within and between exact model configurations, exposes automatic repeat-evidence
gates, independently revalidates raw grades and transcripts, and deliberately refuses
to claim canonical promotion or predict untested models.

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

## Phase 7 — Community evidence and serving data

Goal: preserve enough privacy-safe evidence to recalibrate item discrimination and,
after sufficient representative collection, support environment-aware model serving
recommendations.

Deliverables:

1. Export every item status, attempt, wall time, and completion-token count by default
   without exporting prompts, responses, expected answers, errors, paths, or secrets.
2. Preserve aggregate-only schema-v1 compatibility while emitting schema v2 for new
   campaign bundles and rejecting aggregate/item contradictions.
3. Group exact model, serving, generation, environment, and pack configurations.
4. Recompute community item signal and repeat/configuration disagreement from accepted
   content-free observations.
5. Use independent bundles—not attempts—as the unit for baseline thresholds and 95%
   intervals, and exclude unobserved 0/0 bundles from the evidence threshold.
6. Record optional serving metadata and latency/token observations without inferring
   identifying hardware details.

Acceptance checks:

- Rehashed aggregate contradictions and conflicting duplicate outcomes are rejected.
- Duplicate model rows and repeated attempts cannot inflate the distinct-bundle count.
- Five 0/0 bundles do not reveal a baseline; five observed bundles do.
- Synthetic community observations reproduce known ceiling and negative-discrimination
  controls.
- A real historical run exports every recorded item with no raw content leakage.

## Phase 8 — Directional configuration evidence

Goal: move from detecting that configurations disagree to determining whether one
configuration is consistently better on the observed pack without mistaking repeat
noise or multiple testing for a winner.

Deliverables:

1. Add privacy-safe configuration aliases and input coordinates to local analysis.
2. Report respondent-cluster scorecards, completion, and bounded 95% intervals.
3. Compare every configuration pair on common items with effect size and item
   win/loss/tie counts.
4. Apply exact two-sided sign tests and Holm family-wise correction.
5. Resample both respondents and items, and require the hierarchical interval to
   exclude zero before emitting a directional result.

Acceptance checks:

- Five stable strong-vs-weak repeats produce a directional result.
- Fewer than five scored respondents withhold inference.
- A nominal item-level winner with unstable repeats remains `UNCERTAIN`.
- Multiple pair comparisons use corrected—not raw—p-values.
- Real historical evidence remains readable and private names, endpoints, paths, and
  response content do not enter Markdown or JSON output.

## Phase 9 — Robust item evidence

Goal: prevent noisy item point estimates or repeated observations from one contributor
from driving benchmark-pack decisions.

Deliverables:

1. Add bounded pass-rate intervals and bootstrap intervals for corrected item
   discrimination.
2. Keep raw point classifications separate from robust pack-decision signals.
3. Give every local attempt one uncertainty cluster and every community bundle one
   cluster regardless of its internal attempts or duplicate model rows.
4. Report raw and cluster-weighted discrimination when their weighting differs.
5. Require ten independent clusters and at least 80% defined bootstrap draws before
   emitting robust useful, negative, ceiling, or floor signals.

Acceptance checks:

- Known positive, negative, ceiling, uncertain, and unstable controls separate.
- The bootstrap output is deterministic across repeated analysis calls.
- One bundle containing many repeated or duplicate observations remains one
  independent unit and cannot unlock a robust item classification.
- Equal cluster weighting can resist a bulk duplicate cluster that reverses the raw
  point estimate.
- Existing runs and schema-v2 community submissions remain readable.

## Phase 10 — Item dependency and diversity evidence

Goal: detect when a benchmark appears broad only because several items reproduce the
same empirical outcome pattern, without confusing correlation with proof of duplicate
meaning.

Deliverables:

1. Evaluate every scored item pair with raw outcome agreement and binary phi
   correlation.
2. Give every local attempt or community bundle equal cluster weight and expose raw
   values when repeated rows change the conclusion.
3. Bootstrap whole independent clusters and require the complete 95% interval beyond
   `±0.8` before emitting a robust redundancy or opposing-pattern candidate.
4. Keep all pairs in machine-readable analysis while limiting Markdown to the first
   20 ranked review candidates.
5. Treat every dependency result as a content-review candidate rather than an
   automatic pack mutation.

Acceptance checks:

- Known duplicate, opposing, and independent synthetic outcome patterns separate.
- Repeated calculations are byte-for-byte deterministic.
- One bundle with 100 duplicate rows remains one independent unit and cannot unlock a
  robust relationship.
- Equal bundle weighting can reverse a raw redundancy point estimate created by a
  bulk duplicate contribution.
- Existing local runs and schema-v2 community submissions remain readable.

## Phase 11 — Repeat-adjusted item separation

Goal: distinguish stable item-level model differences from ordinary repeat instability
instead of rewarding whichever item happens to show the largest raw gap.

Deliverables:

1. Compute equal-weight between-configuration separation and same-configuration repeat
   instability for every item.
2. Report their difference as net repeat-adjusted separation with explicit stable,
   weak, noise-dominated, no-separation, uncertain, and insufficient states.
3. Require two configurations and five independent units per configuration for robust
   inference.
4. Resample attempts within local configurations while resampling shared community
   bundle IDs once per draw to preserve contributor-level dependence.
5. Withhold unstable intervals when fewer than 80% of 2,000 deterministic bootstrap
   draws retain sufficient evidence.

Acceptance checks:

- Stable strong-vs-weak item outcomes produce `ROBUST_SEPARATING`.
- Identical unstable outcome distributions are noise dominated rather than separating.
- Unanimous configuration outcomes are reported as no separation, not repeat noise.
- One bundle containing 100 repeated rows cannot satisfy the repeat or robust gates.
- Shared-bundle bootstrap output is deterministic, and existing local/public evidence
  remains readable.

## Phase 12 — Pair-specific item coverage

Goal: retain specialist tasks that reliably distinguish a particular configuration
pair even when they do not correlate with a single aggregate ability axis.

Deliverables:

1. Compute cluster-weighted item pass-rate effects for every exact configuration pair.
2. Require at least five independent units on both sides of an item comparison.
3. Resample complete cluster item records and use the maximum error across eligible
   items to construct simultaneous within-pair intervals.
4. Allocate the family error budget across configuration pairs with Bonferroni
   correction and require a practical ten-point effect in addition to interval exclusion.
5. Preserve shared public-bundle dependence, retain every eligible row in JSON, and
   cap Markdown decisive details at 20 rows.

Acceptance checks:

- A stable specialist item separates strong and weak configurations while a shared
  noisy item remains uncertain.
- A 20-item null family emits no false directional split.
- Three eligible configuration pairs receive one-third of the family error budget.
- One bundle with 100 repeated rows remains insufficient.
- Shared-bundle intervals are deterministic and preserve paired contributions.

## Phase 13 — Constraint-aware serving candidates

Goal: turn validated community observations into a reusable, read-only shortlist for
an exact user constraint set without presenting sparse or cross-pack evidence as a
prediction.

Deliverables:

1. Retain public environment, transport, generation, and serving coordinates beside
   every exact configuration aggregate.
2. Filter exact pack observations by declared environment and capacity constraints;
   missing metadata must not be inferred as a match.
3. Require five independent bundles for accuracy, completion, latency, and throughput
   whenever the corresponding axis is selected.
4. Apply accuracy floors to the bundle-cluster interval lower bound and return a
   multi-objective Pareto set rather than a universal weighted winner.
5. Emit deterministic Markdown and JSON with explicit insufficient, pack-required,
   no-match, single-candidate, and descriptive-candidate states.

Acceptance checks:

- Accuracy-only evidence selects the stronger conservative lower bound, while an
  accuracy/latency tradeoff retains both non-dominated controls.
- Four performance-bearing bundles cannot unlock latency or throughput selection even
  when five bundles contain correctness evidence.
- One bundle with 100 duplicate model rows remains insufficient.
- Multiple pack fingerprints require an exact pack selection.
- Missing hardware metadata fails a hardware constraint and query output copies no
  bundle IDs or contributor/tool-version history.

## Phase 14 — Discriminative item panels

Goal: convert statistically confirmed pair-specific item evidence into a compact,
reusable panel without discarding opposite specialties or treating empirical
correlation as automatic deletion authority.

Deliverables:

1. Treat every confirmed configuration winner/loser direction as an explicit coverage
   target, preserving both directions when specialist items disagree by capability.
2. Select a deterministic greedy set that first maximizes uncovered directional
   coverage and then penalizes robust positive or opposing item dependencies.
3. Use simultaneous interval margin, absolute effect, and stable item ID only as
   deterministic tie-breakers after coverage and dependency cost.
4. Support a per-round/pack item budget and expose all uncovered directions when the
   result is partial.
5. Add panels to local analysis-schema-v7 JSON/Markdown and the community index while
   keeping every source comparison and relationship available for audit.

Acceptance checks:

- One item covering two confirmed pair directions replaces two single-purpose items.
- Opposite confirmed specialties for the same configuration pair are both retained.
- A non-dependent alternative wins a coverage tie against a robustly dependent item.
- A one-item budget over two unique targets is `PARTIAL` and names the missing target.
- Ten identical directional items collapse to one while their robust dependencies
  remain counted, and insufficient community bundles cannot create a panel.

## Phase 15 — Runnable focused campaigns

Goal: convert confirmed panel selections into a validated, reproducible follow-up
campaign without manual item copying or accidental mixing of incompatible evidence.

Deliverables:

1. Add `focus` to reanalyze raw local runs and emit model-level round and item filters
   only for selected panel groups.
2. Treat prior round and item routing as scheduling metadata, while retaining model,
   endpoint, transport, sampling, and all other inference settings in configuration
   identity.
3. Require one exact current bundled-pack fingerprint per selected round and refuse
   mixed or stale pack evidence.
4. Refuse a partial directional panel unless the operator explicitly supplies
   `--allow-partial`, preserving every uncovered target in provenance.
5. Validate generated configs offline, refuse overwrite, resolve duplicate model keys,
   and exclude source paths and source run names from `panel_focus` metadata.

Acceptance checks:

- Routing-only `rounds` differences merge, while a temperature difference does not.
- Duplicate preferred model keys receive stable numeric suffixes.
- Pack drift is rejected before a config is written.
- A bounded partial panel requires explicit authority and retains its uncovered target.
- Generated provenance contains no source path or source campaign name.

## Phase 16 — Out-of-fold panel validation

Goal: distinguish genuinely reusable discriminative panels from selections that only
look strong because they were chosen and evaluated on the same observations.

Deliverables:

1. Deterministically stratify independent units into two balanced folds and rerun the
   complete coverage, dependency, and panel-selection pipeline on training data only.
2. Evaluate selected directional effects exclusively on the opposite holdout fold with
   explicit confirmed, weak, reversed, and insufficient outcomes.
3. Keep all rows from one public contribution bundle in one fold so shared submissions
   never masquerade as independent training and test evidence.
4. Report fold details, direction confirmation rate, item-selection Jaccard, and a
   conservative group status in local analysis and community indexes.
5. Add `focus --require-holdout-stable` and preserve concise validation provenance in
   generated configs without copying source paths or private identities.

Acceptance checks:

- A ten-unit stable strong/weak control confirms both held-out directions.
- Alternating fold-specific winners produce `REVERSED_SIGNAL`, not a stable panel.
- Five shared bundles remain insufficient after splitting instead of passing the gate.
- Shared multi-configuration bundle rows always move together and retain five units on
  each side when ten bundles exist.
- Repeated calls are byte-for-byte deterministic and emitted metadata uses only public
  configuration aliases.

## Phase 17 — Multiplicity-controlled holdout replication

Goal: prevent nominally positive held-out effects from becoming stable panel claims
when several selected directions are tested simultaneously.

Deliverables:

1. Test every evaluable held-out mean-rate difference with a two-sided exchangeable-
   label permutation test that supports fractional cluster rates.
2. Enumerate small assignment spaces exactly and use a fixed, SHA-256-seeded 20,000-
   draw Monte Carlo procedure with finite-sample correction for larger spaces.
3. Apply Holm family-wise correction once across every tested direction from both folds.
4. Require practical magnitude and adjusted p < 0.05 for confirmed or reversed labels;
   retain non-significant effects as weak rather than silently accepting them.
5. Expose raw and adjusted p-values, method, assignment counts, and concise provenance
   in local reports, community indexes, and focused configs.

Acceptance checks:

- Two perfect 5-vs-5 held-out splits remain confirmed after Holm correction.
- Two nominal p=0.047619 effects become p=0.095238 and `WEAK_GENERALIZATION`.
- Perfect opposite directions remain `REVERSED_SIGNAL` after correction.
- Fractional 11-vs-11 cluster rates trigger deterministic Monte Carlo and reproduce
  byte-for-byte across calls.
- Sparse rows remain insufficient and never enter the multiplicity family.

## Phase 18 — Normalized community observation database

Goal: turn reviewed public bundles into a reproducible relational source for future
environment-aware serving research without adding telemetry or weakening bundle-level
independence.

Deliverables:

1. Materialize validated repository JSON into normalized bundle, exact-configuration,
   benchmark-run, item-observation, and Round 4 task-observation SQLite tables.
2. Retain bundle IDs as the uncertainty-cluster foreign key and preserve duplicate model
   rows as auditable runs rather than new independent contributions.
3. Flatten model, server, hardware, and generation coordinates for queries while also
   retaining canonical allowlisted parameter and metadata JSON.
4. Add full SHA-256 run/observation identities, a deterministic logical dataset
   fingerprint, explicit SQLite application/schema versions, and published DDL.
5. Write atomically and add read-only `--check` validation for integrity, foreign keys,
   schema identity, row counts, fingerprint, and every normalized row.

Acceptance checks:

- Five two-configuration bundles produce five bundle clusters, two configurations,
  ten runs, and one hundred item rows.
- A repeated model row creates another run under the same bundle and configuration,
  never another independent bundle.
- Round 4 task flags retain boolean/null semantics and link to their benchmark run.
- Two identical builds have the same logical fingerprint and deterministic local bytes;
  a modified database fails `--check`.
- Empty repositories build and validate, wrong extensions fail, and no raw/private
  evidence field has a database column.

## Phase 19 — Database-backed serving-candidate queries

Goal: make the normalized database a verified service input without creating a second,
divergent recommendation implementation.

Deliverables:

1. Refactor candidate gating and Pareto selection to consume normalized aggregate rows,
   with canonical JSON and SQLite adapters sharing that final implementation.
2. Reproduce bundle-level aggregation directly from database runs and item observations,
   retaining duplicate rows within one bundle cluster.
3. Add `results recommend --database` and reject ambiguous directory-plus-database input.
4. Add schema v2 numeric-normalized fingerprints that can be recomputed after SQLite
   type affinity, plus an explicit schema-v1 rebuild requirement.
5. On standalone reads, verify schema/integrity/fingerprint and semantic identities,
   canonical JSON, flattened settings, environment links, domains, statuses, and flags.

Acceptance checks:

- Five two-configuration bundles produce exactly equal aggregate rows and recommendation
  JSON through canonical source files and the generated database.
- Constraints, three-axis objectives, accuracy floors, exclusions, and Pareto ordering
  are identical across adapters.
- Repeated model rows remain one independent bundle and cannot unlock an interval.
- A stale fingerprint, obsolete schema, unexpected table, unsafe configuration row with
  a freshly recomputed fingerprint, or two simultaneous input sources is rejected.
- Source and installed-package CI exercise empty database build, check, and recommendation
  paths on Linux Python 3.10/3.12 and macOS Python 3.12.
