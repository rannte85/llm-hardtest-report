# Implementation Plan

## Round 4 pluggable agents and fail-closed isolation — completed in 2.36.0

1. Extract the canonical runner behind a shared attempt-scoped agent contract while
   retaining Codex as the default.
2. Add optional OpenCode JSONL execution, same-attempt session continuation, fresh
   next-attempt state, capability/model checks, and failure artifact retention.
3. Add generic isolation wiring and macOS Seatbelt policy generation without moving
   the grader into the candidate boundary.
4. Fail closed on unavailable isolation, malformed policy, protected-read canaries,
   candidate work smoke checks, external-network access, or endpoint denial.
5. Record content-free backend, policy hash, canary, audit, and execution-scaffold
   identity in local reports, public schema v4, and SQLite schema v4.
6. Re-run source tests, repository selftest, Round 4 trap proofs, pack validation,
   isolated fake-agent integration, installed-package smoke, and CI before release.

Canonical Round 4 prompts, repositories, graders, and score thresholds are unchanged.
Seatbelt is explicitly defense in depth rather than a complete security boundary.

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

## Phase 20 — Discoverable serving evidence

Goal: let users and service clients discover the exact observed query space before
specifying model, runtime, hardware, pack, or objective constraints.

Deliverables:

1. Add one deterministic catalog contract over normalized aggregate rows, shared by
   canonical JSON and verified SQLite adapters.
2. Enumerate exact public configurations and case-insensitive model, environment,
   transport, server, accelerator, quantization, and model-format facets.
3. Show independent-bundle counts, conservative metrics, per-objective readiness, and
   missing optional metadata without emitting bundle IDs or contributor history.
4. Distinguish empty sources from valid round/pack filters with no observations.
5. Add an exact case-insensitive model constraint to the existing Pareto query.

Acceptance checks:

- Five two-configuration bundles expose two configurations whose four objectives are
  ready, while one bundle leaves every objective unready.
- JSON and database adapters produce byte-identical catalogs under the same filters.
- Missing values are counted separately, never rendered as selectable facet values.
- Invalid rounds, non-exact pack aliases, conflicting sources, and overwrite attempts
  fail without output mutation.
- Catalog JSON and Markdown contain no bundle IDs, tool versions, or private evidence.
- Source and installed-package CI exercise an empty verified database catalog.

## Phase 21 — Full configuration-coordinate queries

Goal: make every public coordinate that defines a configuration both discoverable and
filterable, so a service never has to guess or silently collapse generation, runtime,
revision, or hardware settings.

Deliverables:

1. Add exact constraints for stable configuration ID, Python version, every generation
   parameter, every model/server metadata field, and exact hardware/capacity values.
2. Retain case-insensitive text comparison, exact numeric comparison, and distinct
   maximum-capacity constraints without treating an omitted value as a match.
3. Expand the catalog to text and numeric facets for every identity coordinate and
   report every missing optional parameter or metadata coordinate.
4. Publish catalog and recommendation schema v2 while preserving the immutable v1 files.
5. Harden direct API validation against null/non-finite numerics, malformed IDs, and
   non-string keys.

Acceptance checks:

- One query specifying all 23 configuration coordinates selects exactly one observed
  setup and returns the same JSON through canonical submissions and SQLite.
- A conflicting server version, generation parameter, or stable ID produces `NO_MATCH`;
  missing values are never inferred.
- Integer JSON settings and SQLite REAL affinity compare consistently and produce
  byte-identical catalogs with normalized numeric facets.
- Runtime constraint/facet sets exactly equal the published schema-v2 property sets.
- Historical v1 schemas remain byte-for-byte unchanged.
- Null, NaN, malformed IDs, non-string keys, and ambiguous input sources fail cleanly.

## Phase 22 — Independent evidence acquisition planning

Goal: convert sparse serving observations into a reproducible collection plan without
turning missing measurements into evidence or exposing contributor identities.

Deliverables:

1. Count independent bundles separately for accuracy, completion, latency, and
   throughput for every exact observed configuration and pack.
2. Add `results plan` over canonical submissions and verified SQLite, sharing the full
   recommender constraint, objective, pack, and validation contract.
3. Compute per-objective deficits against an explicit 5–1000 target and the minimum
   additional complete bundles per configuration as the largest selected deficit,
   while separately enforcing the five-scored-bundle accuracy prerequisite.
4. Distinguish pack ambiguity, empty evidence, exact-filter misses, collection needed,
   and target met with a versioned machine-readable schema and human report.
5. Preserve the bundle as the independence unit, omit all bundle/contributor IDs, and
   state that the total assumes complete future measurements and is only a lower bound.

Acceptance checks:

- One complete bundle for each of two configurations yields four-bundle deficits per
  objective and eight minimum additional complete bundles at the default target.
- Five scored bundles with one missing timing/token bundle retain five accuracy but
  four latency/throughput observations and request one bundle per configuration.
- Five completion-only bundles still request five scored bundles because the
  recommender's accuracy prerequisite is not satisfied.
- A five-bundle complete dataset reports `TARGET_MET`; a target of eight reports three
  additional accuracy bundles per configuration.
- Canonical JSON and verified SQLite produce byte-identical plans under the same exact
  filters, objectives, and target, including through the CLI.
- Multiple packs require an exact choice, absent constraints never match, target values
  outside 5–1000 fail, and ambiguous sources are rejected.
- The public schema exactly covers runtime fields, plans expose no provenance, and
  installed-package CI exercises the empty-database path.

## Phase 23 — Paired exact-configuration comparisons

Goal: increase model discrimination while reducing between-contributor confounding by
comparing two exact configurations only inside independent bundles that observed both.

Deliverables:

1. Collapse repeated runs and duplicate model rows to one accuracy, completion,
   latency, and throughput value per bundle/configuration before pairing.
2. Require five shared bundles per objective and report objective-specific missingness
   without leaking the shared bundle IDs or contributor history.
3. Estimate a deterministic paired-bundle bootstrap 95% interval and exact or fixed
   SHA-256-seeded Monte Carlo two-sided sign-flip p-value for each eligible objective.
4. Apply Holm family-wise correction across all tested objectives and require both the
   adjusted p-value and interval direction for a directional classification.
5. Add one shared JSON/SQLite comparison contract, CLI, Markdown report, public schema,
   explicit sparse/inconclusive/directional/mixed states, and practical-effect caveat.

Acceptance checks:

- Seven shared bundles recover an accuracy-versus-speed tradeoff after three-objective
  Holm correction, with positive latency advantage consistently meaning lower latency.
- Two perfect six-bundle directions have raw p=0.03125 but Holm p=0.0625 and remain
  inconclusive rather than becoming two false claims.
- Fifty duplicate runs inside one bundle still count as one pair; missing performance
  measurements reduce only latency or throughput paired counts.
- Swapping left and right exactly swaps means and classifications, negates effects and
  intervals, and preserves raw/adjusted p-values through a direction-invariant seed.
- Large sign-flip spaces use deterministic 20,000-draw Monte Carlo with finite-sample
  correction and reproduce byte-for-byte.
- Canonical JSON and verified SQLite, including their CLI paths, return byte-identical
  comparisons and reject ambiguous sources, invalid IDs, same-side IDs, and pack drift.
- The public schema matches every runtime field, no output includes bundle identity,
  and installed-package CI exercises an empty verified database.

## Phase 24 — Predictive-service readiness boundary

Goal: make the gap between descriptive evidence and a deployable serving predictor
executable, so sparse or confounded public data cannot silently authorize model fitting.

Deliverables:

1. Audit independent bundle coverage separately for every selected objective and exact
   configuration against an explicit 5–1000 operator target.
2. Measure exact-configuration diversity, declared serving-environment diversity, and
   configuration-pair overlap with five shared bundles on every selected objective.
3. Define an exact model profile from model name, transport, generation settings,
   revision, format, quantization, and parameter count; count an environment bridge
   only when that profile has five independent bundles in at least two environments.
4. Publish deterministic JSON/SQLite adapters, CLI, Markdown report, and schema with
   explicit empty, pack-ambiguous, evidence-gap, and design-target-met states.
5. Keep prediction authorization false and name temporal holdout, maintainer
   abuse/implausibility review, and future pack/server drift monitoring as external
   gates that the current public schema cannot prove.

Acceptance checks:

- Three profiles observed in ten Darwin and ten Linux bundles produce six exact
  configurations, six eligible within-environment paired edges, and three qualified
  environment bridges, but still do not authorize a predictive service.
- Missing timing on one profile reduces only its latency coverage; duplicating each
  model row twenty times cannot change any independent count.
- One bundle containing two runtime metadata variants cannot create an environment
  bridge, and five differently quantized observations do not bridge an otherwise
  identical public model name.
- Canonical JSON and verified SQLite, including CLI paths, produce byte-identical
  audits for all four objectives and reject simultaneous sources.
- Multiple packs require one exact fingerprint; invalid objective lists and every
  threshold boundary fail cleanly without output mutation.
- Runtime fields exactly match the public schema, outputs contain no bundle/contributor
  identity, and source plus installed-package CI exercise an empty database audit.

## Phase 25 — Codex control provenance and live Luna observation

Goal: use a cloud control without allowing ambiguous provider counters to contaminate
serving-throughput comparisons, and retain one sanitized real-model observation.

Deliverables:

1. Add a reusable signed-in Codex configuration restricted to one Round 1 repetition.
2. Run and inspect the exact `gpt-5.6-luna` control, preserving raw evidence only in
   the ignored local run directory.
3. Parse Codex JSONL completion usage into separate input, cached-input, output,
   reasoning-output, and total measurements.
4. Exclude legacy Codex `tokens used` totals from completion-throughput evidence and
   emit an explicit export warning instead of silently relabeling the value.
5. Publish only the allowlist-sanitized Luna result and verify canonical JSON, SQLite,
   catalog, index, and readiness behavior with missing throughput.

Acceptance checks:

- Live `doctor` resolves `gpt-5.6-luna`, and one Round 1 run completes 20/20 with no
  incomplete or infrastructure-invalid items.
- A mixed diagnostic/JSONL transcript recovers exact structured output tokens; an old
  total-only transcript leaves completion tokens unavailable.
- A legacy Codex run exports `tokens: null` for every item and reports the quarantine,
  while an explicitly measured completion-token row remains publishable.
- The Luna public bundle contains no raw output, transcript, credential, endpoint, or
  local path, validates under schema v2, and produces equal JSON/SQLite catalog data.
- Readiness counts one accuracy and latency bundle but zero throughput bundles and
  remains `EVIDENCE_GAPS` with predictive authorization false.

## Phase 26 — Runner and serving provenance separation

Goal: prevent a benchmark client, network hop, or cloud control from being mistaken for
the machine that served the model.

Deliverables:

1. Publish result schema v3 with a per-model `same_host`, `remote`, or `unreported`
   relationship and optional attested remote OS/architecture.
2. Treat the existing top-level OS/architecture/Python fields as runner coordinates;
   normalize legacy v1/v2 serving provenance to unknown without inference.
3. Include both identities in configuration hashing, SQLite schema v3, discovery,
   recommendation, comparison, and acquisition-planning results.
4. Count only serving environments with attested OS and architecture in predictive
   diversity and cross-environment model-profile gates.
5. Preserve all historical public/output schema files and accept canonical v1/v2
   public bundles through the current ingestion and database paths.

Acceptance checks:

- Signed-in Codex/Luna defaults to remote with null host coordinates and rejects a
  `same_host` declaration.
- Same-host exports copy exact runner coordinates; contradictory coordinates and
  unreported coordinates fail even after a valid content rehash.
- Varying legacy client OS/architecture creates no serving-environment diversity or
  portability bridge, while all measured outcome observations remain available.
- Catalog and recommendation expose separate runner and serving filters, and canonical
  JSON/verified SQLite outputs remain byte-identical.
- Every new Draft 2020-12 schema validates both itself and a populated runtime result;
  the full source, installed-package, and repository self-tests pass.

## Phase 27 — Multi-scenario Round 5 discrimination

Goal: move Round 5 beyond a single incident while preserving old evidence and prove
that a new scenario separates a plausible public-green fix from the complete fix.

Deliverables:

1. Add `q33_batch_delivery`, an incident involving a partial downstream acceptance,
   retry identity across batch/request/delivery/effect coordinates, and late v1 schema
   compatibility.
2. Generalize live grading and offline analysis around explicit per-task contracts
   instead of q32-specific filenames and phrases.
3. Add `--pilot-id` with q32 as the backward-compatible default, isolate q33 evidence
   paths, and reject resume attempts that mix scenario identities.
4. Build public, held-back, integrity, collision, and concurrency checks plus a
   seven-state deterministic control matrix.
5. Run one real signed-in `gpt-5.6-luna` attempt while retaining its raw evidence only
   in the ignored local run directory.

Acceptance checks:

- Both scenario control matrices pass; q32's correct control remains 4/4 public and
  9/9 held-back, while q33's correct control reaches 4/4 and 10/10.
- Missing batch scope, delimiter concatenation, schema breakage, test tampering, and
  global serialization all pass q33's public suite but fail held-back evidence.
- q32 uses its historical attempt path; q33 uses a scenario-qualified path, and both
  are accepted by the same tamper-resistant analyzer.
- A live Luna attempt completes all three turns with no authority or tool-protocol
  violation and an accurate final report; its delimiter-based public-green fix scores
  4/4 public and 9/10 held-back, demonstrating real-model discrimination.
- Repository selftest and all 209 source tests pass without publishing raw live-model
  transcripts, local paths, credentials, or run identifiers.

## Phase 28 — Orthogonal configuration-contract pilot

Goal: broaden Round 5 beyond retry/idempotency incidents and measure whether a model
can translate evolving, recursive data semantics into a complete immutable merge.

Deliverables:

1. Add `q34_config_overlay` with an initially visible falsy-value defect and late
   evidence defining nested null tombstones and list replacement.
2. Grade recursive map preservation, false/zero/empty replacements, tombstones at
   every depth, mapping/scalar transitions, and deep independence from both inputs.
3. Build an eight-state control matrix covering the baseline, complete fix, null
   fallback, top-level-only deletion, list append, base mutation, overlay aliasing,
   and protected-test tampering.
4. Remove the runner's response-schema-specific turn-2 assumption and exercise q34
   through live grading, offline analysis, public export, package data, and CI.
5. Compare one local Gemma 4 E4B attempt with one signed-in GPT-5.6 Luna attempt while
   retaining all raw evidence only under the ignored local run directory.

Acceptance checks:

- The baseline scores 3/4 public and 6/10 held-back; the correct control reaches 4/4
  and 10/10; every public-green false fix is rejected at 8–9/10 held-back.
- A tombstone inside a newly introduced mapping is tested alongside a live sibling so
  no empty-parent representation choice can affect the expected result.
- q32, q33, and q34 all execute and analyze through the same contract-driven runner;
  q34 also exports through the voluntary allowlist-only public result path.
- E4B's transport completes but its context/protocol failure retains the 3/4·6/10
  baseline, while Luna reaches 4/4·9/10 and misses only the new-parent tombstone case.
- Repository selftest, all 210 source tests, installed-package verification, and the
  Linux/macOS CI matrix pass without publishing raw model evidence.

## Phase 29 — Scenario-stable evidence portfolios

Goal: keep Round 5 evidence reusable as new incidents are added and compare a model
configuration's observed failure envelope across scenarios without manufacturing a
single leaderboard score.

Deliverables:

1. Fingerprint each scenario's task contract, verifier, candidate repository, and
   held-back grader assets independently while continuing to validate the global pack.
2. Record schema-2 internal summaries with explicit scenario fingerprint scope and
   reject relabelled current evidence or incompatible resume directories.
3. Preserve schema-1 historical analysis in exact pack groups; never silently migrate
   or merge its opaque historical identity with current schema-2 evidence.
4. Add a q32–q34 configuration portfolio with explicit coverage, missing scenarios,
   mixed-version ambiguity, scenario-weighted means, worst observed held-back rate,
   authority/protocol outcomes, and conservative evidence gates.
5. Compare configurations only over exact shared `(pilot_id, fingerprint)` coordinates
   and retain every missing coordinate as unavailable rather than zero.

Acceptance checks:

- Editing q34 changes only q34's fingerprint; q32/q33 remain stable, and generated
  caches do not affect any fingerprint.
- A schema-2 summary with a relabelled fingerprint is rejected; two versions under one
  pilot ID are marked ambiguous and cannot become interpretation-ready.
- Full q32–q34 coverage requires two complete attempts per configuration per scenario;
  exact shared-version distance is reproducible and no canonical score is emitted.
- Historical schema-1 synthetic evidence remains analyzable and anonymous by default.
- Repository selftest, all 214 source tests, installed-package verification, live E4B
  and Luna one-scenario smoke checks, and the Linux/macOS CI matrix pass without
  publishing raw model evidence.

## Phase 30 — Temporal-concurrency hard test

Goal: add a fourth Round 5 capability axis that distinguishes correct temporal
reasoning from superficially safe locks, counters, and value comparisons.

Deliverables:

1. Add `q35_snapshot_race`, where overlapping remote refreshes can publish a stale
   snapshot after a newer request has completed.
2. Reveal late constraints that a newer loader may fail without suppressing an older
   success, loaders may reenter `get`, and different keys must load concurrently.
3. Grade per-key successful-request epochs, failed-newer fallback, ABA resistance,
   cross-key independence, last-good-value preservation, loader reentrancy, and the
   authoritative return value of a stale completion.
4. Build baseline, correct, latest-issued, value-CAS, global-epoch, serialized-loader,
   destructive-failure, stale-return, and tamper controls.
5. Integrate q35 with scenario fingerprints, portfolios, voluntary public export,
   package data, selftest, CI, documentation, and live one-attempt E4B/Luna trials.

Acceptance checks:

- The baseline scores 3/4 public and 7/10 held-back; the correct implementation reaches
  4/4 and 10/10; all seven false controls stay public-green and fail held-back checks.
- Each semantic false control fails its intended distinct contract, and the integrity
  control fails only protected authority.
- q35 changes only its own scenario fingerprint and complete portfolio readiness now
  requires repeated exact-version evidence across q32–q35.
- E4B stops safely after an empty second-turn final message and retains the 3/4·7/10
  baseline as incomplete; Luna reaches 4/4·10/10 with safe authority, clean protocol,
  evidence revision, release readiness, and an accurate final report. Their exact
  q35-version eight-axis distance is 56.875%.
- Repository selftest, all 215 source tests, installed-package verification, and the
  Linux/macOS CI matrix pass without publishing raw model evidence.

## Phase 31 — Repeat-adjusted cross-scenario evidence

Goal: distinguish reproducible configuration separation from variation between repeated
attempts, while keeping sparse or mismatched evidence explicitly non-inferential.

Deliverables:

1. Calculate exact-version between-configuration distance and within-configuration
   repeat distance for every shared Round 5 scenario.
2. Subtract mean repeat noise at the scenario level without clamping negative effects.
3. Bootstrap whole scenario effects deterministically for a 95% interval; never treat
   dependent attempts or the eight outcome axes as independent sampling units.
4. Require three exact shared scenarios, one version per pilot, two complete attempts
   per side/version, complete transport, and safe authority behavior before inference.
5. Emit stable, inconclusive, no-stable-separation, or insufficient-evidence status
   using a five-percentage-point minimum effect, plus a deterministic next-evidence
   acquisition priority.
6. Publish analysis schema 3 and human-readable methodology while preserving
   `canonical_score: false` and mandatory manual ambiguity review.

Acceptance checks:

- Two identical stable configurations produce zero adjusted separation and
  `NO_STABLE_SEPARATION` with a zero-width interval.
- Stable correct-versus-baseline controls clear the minimum effect and require manual
  ambiguity review before any interpretation beyond the observed configurations.
- Alternating correct/baseline repeats on both sides create visible repeat noise that
  is subtracted and cannot become a false stable separation.
- Sparse single-scenario evidence remains `INSUFFICIENT_EVIDENCE` and requests missing
  scenarios; mixed fingerprints request version alignment before more repeats.
- Markdown and JSON agree, the bootstrap is reproducible, missing data is not imputed,
  and no canonical score, significance claim, causal claim, or model prediction appears.
- Repository selftest, all 217 source tests, installed-package verification, and the
  Linux/macOS CI matrix pass without publishing raw model evidence.

## Phase 32 — Explainable and omission-robust separation

Goal: reveal which capability axes create a Round 5 configuration difference and stop
one influential incident from silently carrying an otherwise stable conclusion.

Deliverables:

1. Decompose every exact shared scenario into the same eight unsigned outcome-axis
   distances used by the aggregate calculation.
2. Report scenario-weighted between distance, repeat noise, adjusted separation, and
   positive contribution share per axis without declaring a directional winner.
3. Require all eight outcome axes to be observed on every shared attempt before an
   inferential separation status can be issued.
4. For eligible stable comparisons with four or more scenarios, remove each scenario
   in turn and rerun the deterministic bootstrap and minimum-effect decision.
5. Distinguish robust, single-scenario-sensitive, too-few-scenario, and non-applicable
   omission states, retaining every omission case in JSON.
6. Prioritize replication of all influential scenarios before manual ambiguity review
   whenever an omission breaks stable separation.

Acceptance checks:

- Identical configurations have zero contribution on all axes and no omission audit.
- Diffuse correct-versus-baseline separation has positive correctness attribution and
  remains stable after every single scenario removal.
- A comparison with one identical scenario and three separating scenarios is stable in
  aggregate but is flagged sensitive when a separating scenario is removed.
- Transport and other invariant axes retain exactly zero contribution, positive shares
  sum to one when signal exists, and repeat instability is subtracted per axis.
- Sparse, mixed-version, incomplete, authority-invalid, or missing-axis evidence cannot
  reach omission-robust manual review.
- Repository selftest, all 218 source tests, installed-package verification, and the
  Linux/macOS CI matrix pass without publishing raw model evidence.

## Phase 33 — Byte-stream framing and reentrant delivery hard test

Goal: add an orthogonal protocol-state challenge that distinguishes byte-correct,
recoverable streaming implementations from fixes that only pass ordinary text chunks.

Deliverables:

1. Add `q36_jsonl_stream`, whose network input may split records and UTF-8 code points
   at arbitrary byte boundaries.
2. Reveal late constraints for raw-byte limits, one-error malformed-frame recovery,
   EOF flush, object-only records, and callback-triggered reentrant `feed()` calls.
3. Grade exact authority, UTF-8 preservation, byte counting, newline recovery,
   non-recursive wire-order delivery, close idempotence, and post-close rejection.
4. Build baseline, correct, text-concatenation, replacement-decoding, inline-callback,
   character-limit, abort-on-error, no-EOF-flush, scalar-acceptance, and tamper controls.
5. Integrate q36 with fingerprints, five-scenario portfolios, voluntary public export,
   package data, selftest, CI, documentation, and one-attempt E4B/Luna smoke checks.

Acceptance checks:

- The baseline fails a visible split-frame check; the correct implementation reaches
  4/4 public and 10/10 held-back; every incomplete or adversarial control is
  public-green but fails held-back evidence.
- Malformed UTF-8 is explicitly distinguished from replacement decoding, oversized
  fragments report once and recover, and callback reentrancy preserves already-framed
  outer records without recursive callback depth.
- q36 changes only its own fingerprint, and full portfolio readiness requires two
  exact-version attempts per configuration across q32–q36.
- Source tests, repository selftest, installed-package validation, live E4B/Luna
  smoke checks, and the Linux/macOS CI matrix pass without publishing raw evidence.

## Phase 34 — Bounded unsupported-tool circuit breaker

Goal: prevent a Round 5 Codex agent from consuming the full turn timeout while
repeating a tool that the active runtime cannot provide, without misclassifying one
recoverable router error as a failed attempt.

Deliverables:

1. Scan only newly appended, complete transcript lines while the spawned Codex process
   runs, retaining partial UTF-8/log lines safely between polls.
2. Permit one or two authoritative unsupported-tool router errors and terminate the
   exact spawned process group on the third error in one agent turn.
3. Record `protocol_aborted` and a normalized `stop_reason` through attempt grades,
   terminal progress, offline analysis, public export, and community aggregation.
4. Publish pilot schema v2 while keeping schema-v1 validation and aggregation support.
5. Recompute abort claims from bounded raw transcripts so edited grade metadata cannot
   manufacture a protocol-loop termination.

Acceptance checks:

- A normal process and a process recovering after one unsupported call finish normally.
- Three errors stop a fresh or resumed turn before its deadline and preserve the tool
  name, transcript marker, non-timeout state, and explicit stop reason.
- Public schema v2 rejects contradictory or below-threshold abort claims; v1 bundles
  remain readable.
- Round 5 reports and community indexes distinguish protocol errors from aborts, and
  no raw prompts, outputs, paths, or credentials enter public bundles.
- Source tests, repository selftest, installed-package validation, a bounded live E4B
  smoke check, and the Linux/macOS CI matrix pass.

## Phase 35 — Adversarial archive boundary hard test

Goal: add a security and preflight-atomicity capability axis that cannot be passed by
the common `resolve()`/string-prefix ZIP-slip patch or by validating members only as
they are written.

Deliverables:

1. Add `q37_archive_boundary` with a visible tenant ZIP boundary escape and late
   cross-platform, symlink, alias, collision, size, overwrite, and atomicity rules.
2. Require full archive and destination preflight before the first write, normalize
   platform-independent names, reject unsafe member types, and count uncompressed
   bytes.
3. Build baseline, correct, backslash-only, drive-prefix, archive-symlink,
   destination-symlink, sequential-write, alias, collision, compressed-size,
   overwrite, and authority-tamper controls.
4. Integrate q37 with isolated fingerprints, six-scenario portfolios, public pilot
   export, package data, selftest, documentation, and CI.
5. Run one exact-fingerprint attempt each with local E4B and signed-in GPT-5.6 Luna,
   retaining raw evidence locally and treating the pair as a smoke observation only.

Acceptance checks:

- The baseline fails visible traversal checks and reaches 2/4 public and 0/10
  held-back; the complete implementation reaches 4/4 and 10/10.
- Every incomplete or adversarial control remains 4/4 public but fails at least one
  distinct held-back boundary or authority check.
- A late invalid member leaves an existing destination unchanged, symlink paths never
  escape, platform aliases are rejected deterministically, and compressed bytes cannot
  satisfy the uncompressed limit.
- q37 changes only its own scenario fingerprint, and portfolio readiness requires two
  exact-version attempts per configuration across q32–q37.
- Source tests, repository selftest, installed-package validation, live E4B/Luna smoke
  checks, and the Linux/macOS CI matrix pass without publishing raw evidence.

## Phase 36 — Authenticated webhook replay boundary

Goal: distinguish an implementation that merely checks one HMAC from one that
preserves exact wire authenticity and exactly-once handler effects under rotation,
failure, concurrency, and reentrancy.

Deliverables:

1. Add `q38_webhook_replay` with a visible duplicate billing delivery and late raw
   byte, rotation, timestamp, replay, failure, concurrency, and JSON constraints.
2. Verify all active secrets and all supplied signatures over the exact raw body,
   with strict header grammar and inclusive past/future tolerance boundaries.
3. Reserve authenticated replay identity before invoking the handler, permit unrelated
   and reentrant requests to progress, release only failed reservations, and retain
   successful reservations.
4. Build baseline, correct, canonical-body, first-signature, current-secret,
   timestamp-boundary, future-window, late-reservation, stuck-failure, global-lock,
   body-only, duplicate/scalar JSON, and authority-tamper controls.
5. Integrate q38 with isolated fingerprints, seven-scenario portfolios, voluntary
   public export, package data, selftest, documentation, and CI.

Acceptance checks:

- The baseline reaches 2/4 public and 2/10 held-back; the complete implementation
  reaches 4/4 and 10/10.
- Every incomplete or adversarial control remains 4/4 public while failing at least
  one distinct held-back authentication, replay, concurrency, recovery, JSON, or
  authority contract.
- Concurrent identical requests invoke the handler once; different requests and a
  callback-triggered nested request do not deadlock behind a handler-wide lock.
- Invalid authentication cannot poison replay state, handler failure permits retry,
  and the same body under a separately signed timestamp is not a false replay.
- q38 changes only its own scenario fingerprint, and portfolio readiness requires two
  exact-version attempts per configuration across q32–q38.

## Phase 37 — q38 semantic-grader and live-model validation

Goal: verify that q38 measures the intended engineering revision instead of one
preferred phrase, then collect a bounded final-fingerprint smoke comparison.

Deliverables:

1. Accept explicit all-signature/all-active-secret reasoning even when formatting
   inserts a line break, while rejecting first-signature/current-secret-only plans.
2. Preserve the baseline, correct, and twelve partial/adversarial control outcomes.
3. Run one final-fingerprint attempt each with local E4B and signed-in GPT-5.6 Luna.
4. Independently analyze the eight outcome axes and retain the raw evidence locally.

Acceptance checks:

- The semantic positive and partial-plan negative regression both pass.
- All fourteen q38 controls retain their 2/4·2/10 baseline, 4/4·10/10 correct, and
  public-green held-back separation contracts.
- Live evidence shares fingerprint
  `sha256:1baf8e1d5fe47ecd9a94c6da6d9a70e42fb2f916961c50adfffad93e2b344c62`.
- The one-scenario, one-attempt observation remains `INSUFFICIENT_EVIDENCE` and is
  never presented as a model ranking or prediction.

## Phase 38 — Durable SQLite lease fencing hard test

Goal: add an orthogonal persistent-concurrency axis that distinguishes a locally
locked queue from a transactionally fenced lease shared by independent processes.

Deliverables:

1. Add `q39_job_lease` with visible duplicate execution and late atomicity, expiry,
   fencing, heartbeat, completion, ordering, duplicate, and rollback constraints.
2. Use a durable monotonically increasing token on every claim/reclaim and require the
   exact active `(worker, token)` pair for every mutation.
3. Build baseline, correct, deferred-claim, exclusive-expiry, skipped-token,
   heartbeat-shortening/unfenced, expired/unfenced-completion, unstable-order,
   overwrite, validation, fresh-schema-only, and authority-tamper controls.
4. Integrate q39 with isolated fingerprints, eight-scenario portfolios, voluntary
   public export, package data, selftest, documentation, and CI.
5. Run one exact-fingerprint attempt each with local E4B and signed-in GPT-5.6 Luna,
   retaining raw evidence locally and reporting the pair as a smoke observation only.

Acceptance checks:

- The baseline reaches 2/4 public and 0/10 held-back; the complete implementation
  reaches 4/4 and 10/10.
- All twelve incomplete/adversarial implementations stay 4/4 public while failing at
  least one distinct held-back transaction, lease, fencing, ordering, validation, or
  authority contract.
- The atomic-claim concurrency control passes five consecutive matrix runs without
  duplicate ownership or SQLite lock leakage.
- Exact-version evidence remains non-canonical and cannot become a ranking without
  repeated complete attempts and broader shared-scenario coverage.
- Final live evidence shares fingerprint
  `sha256:3a7b4f3f8d1bdd9bbd03090f173f59cf7a8759efc2981faabd734b1bc84ab20b`;
  its 65% one-attempt distance remains `INSUFFICIENT_EVIDENCE`.

## Phase 39 — Per-hop SSRF and redirect authority hard test

Goal: add an orthogonal network-authority axis that distinguishes URL-string filters
from fail-closed resolution, connection pinning, and redirect processing.

Deliverables:

1. Add `q40_ssrf_redirect` with an initial metadata-redirect incident and late
   absolute-HTTPS, IDNA, DNS-answer, mapped/zone IPv6, redirect, credential, header,
   and streaming constraints.
2. Require exactly one resolution per hop, reject the whole answer on any non-global
   address, and pass only an approved numeric IP while preserving normalized Host/SNI.
3. Build baseline, correct, first-answer, mapped/zone, normalization/query, repeated-
   resolution, redirect-body/loop, credential, header, length, body-limit, status, and
   authority-tamper controls.
4. Integrate q40 with isolated fingerprints, nine-scenario portfolios, voluntary
   public export, package data, selftest, documentation, and CI.
5. Run one exact-fingerprint attempt each with local E4B and signed-in GPT-5.6 Luna,
   retaining raw evidence locally and treating the pair as a smoke observation only.

Acceptance checks:

- The baseline reaches 2/4 public and 0/10 held-back; the complete implementation
  reaches 4/4 and 10/10.
- All fifteen incomplete/adversarial implementations stay 4/4 public while failing at
  least one distinct held-back DNS, authority, redirect, credential, header, streaming,
  response-shape, or protected-evidence contract.
- Five consecutive matrix runs preserve the same public/held-back separation.
- Final live evidence shares fingerprint
  `sha256:6593578c18a44350aee6846ad177e9d8c3a2429001569899f5f64e09ca068822`;
  its 61.3% one-attempt distance remains `INSUFFICIENT_EVIDENCE`.

## Phase 40 — Structured async fan-out hard test

Goal: add an orthogonal asynchronous task-lifetime axis that distinguishes a semaphore
plus bare `gather()` from structured failure and cancellation cleanup.

Deliverables:

1. Add `q41_async_fanout` with visible queue-charged timeout and surviving-sibling
   failures plus late validation, duplicate-order, caller-cancellation, cleanup, and
   nested-call constraints.
2. Begin each item timeout only after slot acquisition, set failure state before slot
   release, and cancel and await all active or queued siblings before propagating the
   original failure object.
3. Build baseline, correct, boolean/infinite-limit, lazy-input, deduplication, global-
   coordination, cancellation, timeout-leak, non-awaitable, exception-identity,
   empty-validation, and authority-tamper controls.
4. Integrate q41 with isolated fingerprints, ten-scenario portfolios, voluntary public
   export, package data, selftest, documentation, and CI.
5. Run one exact-fingerprint attempt each with local E4B and signed-in GPT-5.6 Luna,
   retaining raw evidence locally and treating the pair as a smoke observation only.

Acceptance checks:

- The baseline reaches 2/4 public and 0/10 held-back; the complete implementation
  reaches 4/4 and 10/10.
- All twelve incomplete/adversarial implementations stay 4/4 public while failing at
  least one distinct held-back validation, ordering, timeout, failure, caller-
  cancellation, cleanup, isolation, exception-identity, or authority contract.
- Five consecutive matrix runs preserve the same public/held-back separation.
- Final live evidence shares fingerprint
  `sha256:baeff06c0549643491eaf64a57e6686b500e2a97e0920b9e10f0470cdbb0cadc`;
  its 68.8% one-attempt distance remains `INSUFFICIENT_EVIDENCE`.

## Phase 41 — Finite Round 5 evidence acquisition planning

Goal: convert portfolio gate failures into an executable lower-bound collection plan
without implying that missing or invalid evidence has been repaired.

Deliverables:

1. Classify every configuration/pilot cell as ready, missing, repeat-deficient,
   fingerprint-ambiguous, or requiring a fresh clean cohort.
2. Report exact additional complete-attempt counts per cell, configuration, scenario,
   and portfolio when the fingerprint choice is unambiguous.
3. Prioritize scenarios by potential exact configuration-pair coverage gained per
   additional attempt, with deterministic tie-breaking.
4. Prevent the impossible `append attempts to clear all-attempts gates` workflow by
   excluding invalid run directories from a fresh inferential cohort.
5. Render the plan in both JSON and Markdown while retaining anonymous configuration
   aliases and `canonical_score: false`.

Acceptance checks:

- A complete ten-scenario, two-repeat, two-configuration portfolio requires zero new
  attempts.
- Two configurations observed only on q32 require 36 complete attempts: two attempts
  for each of nine missing scenarios and each configuration.
- Mixed fingerprints require manual alignment and do not report a false numeric total.
- Any incomplete or authority-invalid history produces a two-attempt clean-cohort
  action that explicitly excludes invalid run directories.

## Phase 42 — Current-fingerprint planner validation

Goal: exercise schema-5 acquisition planning against real incomplete and complete q41
evidence and remove any contradiction between pairwise and portfolio guidance.

Deliverables:

1. Run one current-fingerprint q41 attempt each with local E4B and GPT-5.6 Luna.
2. Preserve raw evidence locally and verify exact scenario-fingerprint grouping.
3. Require clean-cohort recovery to precede unrelated missing-scenario guidance when a
   shared attempt is transport-incomplete or authority-invalid.
4. Recompute the finite lower bound and verify the same priority in JSON and Markdown.

Acceptance checks:

- Both runs share current fingerprint
  `sha256:b4a74e5d7fd3b4aeec0a58ac4f134408ad65840edfc13812223a58bcf173bb2e`.
- E4B's invalid run remains descriptive and triggers a separate two-attempt clean
  cohort; Luna requires one ordinary q41 repeat.
- The total lower bound is 39 complete attempts and q41 ranks before every missing
  scenario.
- Pairwise and detailed collection-plan next actions both identify clean-cohort
  recovery rather than contradictory missing-scenario collection.

## Phase 43 — Directional Round 5 configuration evidence

Goal: distinguish “these configurations behave differently” from the narrower claim
that one observed configuration performed materially better across shared Round 5
scenarios, without turning research pilots into a leaderboard.

Deliverables:

1. Compute a signed left-minus-right contrast across the same eight equal-weight,
   higher-is-better outcome axes only when every axis is observed.
2. Average repeats inside exact configuration/scenario cells and use a deterministic
   hierarchical bootstrap that resamples scenarios and attempts within scenarios.
3. Reuse exact-version, minimum-scenario, complete-repeat, transport, authority, and
   observed-axis gates before naming a favored configuration.
4. Require the complete 95% interval to clear a five-percentage-point material-effect
   boundary; distinguish stable-left, stable-right, no-material, inconclusive, and
   insufficient evidence.
5. Add signed axis contrasts and a directional leave-one-scenario-out audit to JSON
   and Markdown while retaining anonymous aliases and `canonical_score: false`.

Acceptance checks:

- Symmetric strong/weak controls reverse the favored alias and effect sign exactly.
- Identical configurations report `NO_MATERIAL_ADVANTAGE` with no favored alias.
- Opposing scenario effects remain `INCONCLUSIVE` instead of selecting a winner.
- Missing axes, incomplete transport, unsafe authority, insufficient repeats, or fewer
  than three exact shared scenarios produce `INSUFFICIENT_EVIDENCE`.
- A stable result over at least four scenarios reports whether every one-scenario
  omission preserves the same direction.

## Phase 44 — Family-wise Round 5 directional control

Goal: prevent a growing configuration portfolio from producing chance stable
differences or directional “winners” merely because it displays many pairwise intervals.

Deliverables:

1. Treat all directionally eligible configuration pairs in one portfolio as a single
   comparison family; never select the family after observing favorable results.
2. Preserve hierarchical pointwise 95% intervals for diagnosis while basing both
   stable-separation and favored-configuration decisions on Bonferroni simultaneous
   intervals at confidence `1 - 0.05/m` for `m` eligible pairs.
3. Record family-wise alpha, multiplicity method, eligible family size, adjustment
   divisor, simultaneous confidence, pointwise status, and adjusted status in JSON and
   Markdown.
4. Reuse the original family size in every unsigned and directional leave-one-scenario-
   out case so robustness cannot weaken the decision threshold.
5. Keep ineligible comparisons visible as `INSUFFICIENT_EVIDENCE` without counting
   them as tested directional hypotheses.

Acceptance checks:

- Two configurations retain the schema-6 result because a one-pair family requires no
  additional widening.
- Three fully eligible configurations produce three pair comparisons, each using the
  same 98.33% simultaneous confidence.
- A synthetic pointwise `STABLE_LEFT_ADVANTAGE` whose simultaneous lower bound does
  not clear five points becomes `INCONCLUSIVE` with no favored configuration.
- The same boundary pattern converts pointwise `STABLE_SEPARATION` to family-wise
  `INCONCLUSIVE` and changes next-evidence guidance accordingly.
- Strong symmetric controls remain stable and reverse exactly after the family-wise
  adjustment.
- Missing, incomplete, unsafe, repeat-deficient, or partially observed pairs remain
  ineligible and cannot shrink or expand the tested family after seeing outcomes.

## Phase 45 — Load-stable q41 control timing

Goal: preserve q41's queue-neutral timeout discrimination without treating loaded CI
scheduling delay as a model or harness defect.

Deliverables:

1. Increase per-worker execution headroom from 80 ms to 200 ms in both public and
   held-back queue checks.
2. Increase the serialized queue to 20 workers so implementations that start timeout
   clocks before semaphore acquisition still cross the deadline.
3. Update the protected public-test hash and exact scenario fingerprint rather than
   silently pooling earlier evidence.
4. Include unexpected public and complete-control test output in verifier failures.

Acceptance checks:

- Three q41 matrices running concurrently all preserve the intended 14-state result.
- The correct control passes 4/4 public and 10/10 held-back checks.
- The baseline remains 2/4 public and 0/10 held-back.
- All twelve incomplete or adversarial controls remain public-green and fail at least
  one held-back check.
- The Phase 45 release fingerprint was
  `sha256:1186a977c1b4264fcf47497c027299b84f627ae1308f6488d85cfa34d1443679`.

## Phase 46 — Family-wise bootstrap tail resolution

Goal: prevent large configuration portfolios from presenting Bonferroni endpoints
whose extreme tails are supported by only a handful of Monte Carlo draws.

Deliverables:

1. Calculate the complete eligible pair family before drawing bootstrap samples.
2. Select `max(5,000, 4,000m)` deterministic draws for `m` eligible pairs, preserving
   at least 100 expected draws in each adjusted tail.
3. Reuse the adaptive budget for unsigned separation, signed directional advantage,
   and every leave-one-scenario-out case with the original family size.
4. Publish interval tail probability and expected draws plus multiplicity sample policy,
   selected samples, target resolution, and achieved expected resolution.
5. Show family size, draws, and expected tail resolution in Markdown and document the
   increased cost for large comparison families.

Acceptance checks:

- Zero- and one-pair families retain the 5,000-draw floor.
- Three, six, and 45 eligible pairs select 12,000, 24,000, and 180,000 draws.
- Every eligible family-wise interval reports at least 100 expected draws per tail.
- Pointwise and family-wise intervals reuse the same deterministic draws.
- Adaptive sampling does not change evidence gates, material-effect boundaries,
  canonical scoring, or automatic promotion behavior.

## Phase 47 — q41 100× scheduling-headroom hardening (completed)

Goal: remove the remaining overloaded-macOS false negative without weakening the
queue-charged timeout trap.

Deliverables:

1. Shorten each healthy public-control worker from 20 ms to 5 ms and raise its item
   timeout from 200 ms to 500 ms.
2. Expand the serial queue from 20 to 120 items, keeping accumulated work above the
   timeout so timeout-around-semaphore implementations remain rejected.
3. Rotate the protected public-test hash and exact q41 scenario fingerprint.
4. Re-run concurrent q41 matrices, all source tests, selftest, clean installs, and both
   main/tag CI matrices before publishing v2.45.1.

Acceptance:

- A correct implementation gets 100× nominal per-worker scheduling headroom.
- The public control remains red for a timeout wrapped around semaphore acquisition.
- All twelve incomplete/adversarial controls remain public-green and held-back-negative.
- Current fingerprint is
  `sha256:06c886e8d9d5e8fc6bb1af3b59aa40f5f9a26c2feb3175003ccd1d4fc5e2ffa4`.

## Phase 48 — Trusted historical Round 5 contract verification (completed)

Goal: keep evidence from prior public scenario releases analyzable without weakening
the fingerprint boundary or applying a newer grading contract to older evidence.

Deliverables:

1. Package a strict q32–q41 release registry that binds each published exact scenario
   fingerprint to its first/last release and historical grading contract.
2. Accept schema-2 evidence only when its fingerprint matches the installed assets or
   an exact registry entry; continue rejecting arbitrary relabelling.
3. Recompute final-report accuracy with the contract bound to the selected fingerprint.
4. Preserve exact `(pilot_id, fingerprint)` grouping and expose verification provenance
   in analysis schema 9 and Markdown.
5. Test registry completeness, duplicate rejection, trusted historical analysis,
   unknown-fingerprint rejection, and current/historical non-pooling.

Acceptance:

- Every currently installed q32–q41 fingerprint appears in the registry.
- Historical q41 v2.44.1–v2.45.0 evidence can be analyzed by the current release.
- A zeroed or otherwise unknown fingerprint is rejected.
- Current and historical q41 evidence produces two groups and a portfolio version-
  alignment blocker rather than a pooled comparison.

## Phase 49 — Shared HTTP cache isolation and revalidation pilot (completed)

Goal: add an orthogonal scenario that distinguishes agents able to reason across shared
representation security, HTTP cache state transitions, time boundaries, and concurrent
request coalescing.

Deliverables:

1. Add `q42_shared_http_cache` with a visible authenticated cross-tenant leak and wrong
   language variant, followed by late header, policy, freshness, 304, stale, and
   single-flight constraints.
2. Require fail-closed header validation; sensitive-request bypass; private/no-store,
   Set-Cookie, and `Vary:*` exclusion; case-insensitive exact variants; strict `Age` and
   max-age boundaries; validator-driven 304 body preservation and metadata rekeying;
   bounded stale-if-error; and exact-request flight cleanup.
3. Build baseline, complete, conflicting-header, Cookie, Range, Set-Cookie, `Vary:*`,
   conflicting max-age, ignored-Age, stale-Vary, unbounded-stale, global-flight,
   failed-flight, and protected-authority controls.
4. Integrate q42 with CLI selection, isolated fingerprints, q32–q42 portfolios,
   acquisition planning, anonymous public export, installed assets, selftest, and docs.
5. Fingerprint task-root Python control dependencies while proving q32–q41 remain
   unchanged.

Acceptance:

- The URL-only baseline is 0/4 public and 0/10 held-back.
- The complete control is 4/4 public and 10/10 held-back.
- Every incomplete/adversarial control is 4/4 public and fails at least one distinct
  held-back contract.
- q32–q41 fingerprints remain unchanged; q42 fingerprint is
  `sha256:c1a1d19d78c91ef335735734cf0ff15fff3fa25aa3aed986101e86ebc29b539f`.
- Full portfolio readiness requires two complete exact-version attempts per
  configuration across all eleven q32–q42 scenarios.
