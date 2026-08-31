# Changelog

All notable changes are documented here. Benchmark-scoring compatibility is called
out separately from harness features.

## Unreleased

## 2.23.0 — 2026-09-01

- Added `results compare` for head-to-head analysis of two exact configurations using
  only independent public bundles that contain both configurations.
- Added per-objective paired accuracy, completion, latency, and throughput effects,
  with latency oriented so positive advantage always favors the left configuration.
- Added deterministic paired-bundle bootstrap 95% intervals, exact or SHA-256-seeded
  Monte Carlo two-sided sign-flip tests, and Holm correction across tested objectives.
- Added explicit sparse, inconclusive, left/right directional, and mixed-tradeoff
  states without imposing an undocumented practical-effect threshold.
- Added byte-identical canonical-JSON and verified-SQLite adapters, CLI/Markdown output,
  and `paired-comparison-schema-v1.json` without bundle or contributor identities.
- Added repeat-collapse, missing-metric, unpaired, multiplicity, side-symmetry,
  deterministic Monte Carlo, pack, validation, privacy, and cross-adapter controls.
- Kept canonical benchmark content, public result schema v2, SQLite schema v2, catalog
  schema v2, recommendation schema v2, and collection-plan schema v1 unchanged.

## 2.22.0 — 2026-09-01

- Added `results plan` to calculate exact per-objective independent-bundle deficits
  for every matching observed configuration and a user-selected target of 5–1000.
- Reused the full recommendation query contract, including exact pack selection, all
  23 identity coordinates, three capacity ceilings, and case/numeric matching rules.
- Added separate accuracy, completion, latency, and throughput observation counts so
  partial performance data cannot be treated as a complete contribution.
- Added an explicit five-scored-bundle accuracy prerequisite so completion-only data
  cannot incorrectly produce a target-met collection plan.
- Added identical canonical-JSON and verified-SQLite planning paths, human Markdown,
  machine-readable output, and `collection-plan-schema-v1.json`.
- Added sparse, target-met, partial-metric, high-target, multi-pack, privacy, invalid-
  target, conflicting-source, schema, CLI, and cross-adapter controls.
- Kept canonical benchmark content, graders, public result schema v2, SQLite schema v2,
  catalog schema v2, and recommendation schema v2 unchanged.

## 2.21.0 — 2026-09-01

- Made every allowlisted configuration-identity coordinate discoverable and exactly
  filterable: configuration ID, model, environment/Python, transport, all seven
  generation parameters, and all ten model/server/hardware metadata fields.
- Added exact numeric facets and explicit missing-coordinate counts while retaining
  case-insensitive grouping for text values and separate capacity-ceiling constraints.
- Added `--configuration`, `--python-version`, generation-setting, revision,
  server-version, accelerator-count, and exact memory/model-size CLI filters.
- Published catalog schema v2 and recommendation schema v2 without rewriting the
  historical v1 contracts.
- Included public schemas, SQL DDL, result guides, and project documentation in the
  Python source distribution.
- Hardened API validation for null numeric values, non-finite numbers, malformed
  configuration IDs, and non-string constraint keys.
- Added full-coordinate JSON/SQLite, CLI, schema, numeric-affinity, conflicting-value,
  missing-value, and installed-package controls.
- Kept database schema v2, public result schema v2, and canonical Round 1–4 content and
  grading unchanged.

## 2.20.0 — 2026-09-01

- Added `results catalog` for deterministic discovery of observed models, servers,
  accelerators, quantizations, formats, operating systems, architectures, transports,
  exact configurations, rounds, and pack fingerprints before composing a query.
- Added per-observation independent-bundle counts, objective readiness, conservative
  metrics, case-insensitive facet aggregation, and explicit missing-metadata counts.
- Added `--model` as an exact, case-insensitive serving-candidate constraint.
- Made canonical JSON and verified SQLite catalog responses byte-identical, with
  explicit `EMPTY`, `NO_MATCH`, and `OBSERVED` states and no bundle or contributor IDs.
- Published catalog schema v1 and added filter, privacy, sparse-evidence, conflicting-
  source, installed-package, and cross-adapter controls.
- Kept database schema v2, public result schema v2, recommendation schema v1, and
  canonical Round 1–4 content and grading unchanged.

## 2.19.0 — 2026-09-01

- Added `results recommend --database` for gated Pareto queries directly from normalized
  SQLite observations, with no bundle IDs or contributor history in the response.
- Refactored JSON and database adapters to share one aggregate-row recommendation path;
  identical evidence now produces identical metrics, gates, exclusions, and candidates.
- Added database schema v2 with a numeric-normalized, independently recomputable content
  fingerprint; version-2.18 schema-v1 databases must be rebuilt from canonical JSON.
- Added standalone semantic validation for canonical configuration JSON, flattened
  settings, safe text, identities, pack/environment links, numeric domains, statuses,
  and Round 4 boolean/null flags.
- Rejected ambiguous directory-plus-database queries and added cross-adapter, stale,
  obsolete-schema, semantic-tamper, repeat-cluster, CLI, and installed-package controls.
- Kept public result schema v2, recommendation result schema v1, and canonical Round 1–4
  content and grading unchanged.

## 2.18.0 — 2026-09-01

- Added `results database` to materialize validated public submissions as a normalized
  SQLite observation database without scanning local runs or making network requests.
- Added linked bundle, exact-configuration, benchmark-run, item-observation, and Round 4
  task-observation tables with bundle IDs preserved as uncertainty clusters.
- Added flattened model/server/hardware/generation coordinates, canonical allowlisted
  JSON, full SHA-256 row identities, and a deterministic logical content fingerprint.
- Added atomic output, SQLite integrity and foreign-key checks, application/schema
  identifiers, and read-only `--check` comparison of every row to repository JSON.
- Rejected symlinked submission directories and JSON entries before public-result or
  pilot validation so generated indexes and databases cannot follow external evidence.
- Published database schema v1, privacy/independence documentation, SQL examples, and
  adversarial repeat, tamper, deterministic-build, CLI, and Round 4 controls.
- Kept public result schema v2 and canonical Round 1–4 content and grading unchanged.

## 2.17.0 — 2026-09-01

- Added analysis-schema-v10 two-sided label-permutation tests for every evaluable
  held-out panel direction.
- Added exact enumeration through 100,000 assignments and deterministic 20,000-draw
  Monte Carlo tests with finite-sample correction for larger and fractional-rate data.
- Added Holm family-wise correction across all tested directions from both folds.
- Required both a ten-percentage-point effect and adjusted p < 0.05 for confirmed or
  reversed replication; nominal effects remain `WEAK_GENERALIZATION`.
- Added raw/adjusted p-values, permutation audit metadata, Markdown columns, and panel-
  focus schema v3 multiplicity provenance.
- Added adversarial controls proving two nominal p=0.047619 replications become
  p=0.095238, while perfect confirmation and reversal survive correction.
- Kept public result schema v2 and canonical Round 1–4 content and grading unchanged.

## 2.16.0 — 2026-09-01

- Added analysis-schema-v9 deterministic two-fold validation that selects panels on
  training evidence and evaluates their directional effects only on held-out units.
- Added explicit `STABLE`, `WEAK_GENERALIZATION`, `REVERSED_SIGNAL`, and `INSUFFICIENT`
  group states plus confirmed, weak, reversed, and insufficient direction outcomes.
- Preserved shared community-bundle dependence by assigning every row from one bundle
  to a single fold and balancing configuration evidence deterministically.
- Added direction confirmation rates, item-selection Jaccard overlap, full fold traces,
  and local/community Markdown summaries.
- Added `focus --require-holdout-stable` and concise holdout provenance in generated
  panel-focus schema v2 configs; insufficient evidence never satisfies the strict gate.
- Added adversarial controls for stable replication, fold-specific reversal, sparse
  evidence, shared clusters, determinism, and private-identity exclusion.
- Kept public result schema v2 and canonical Round 1–4 content and grading unchanged.

## 2.15.0 — 2026-09-01

- Added `focus`, which converts locally revalidated discriminative panels into runnable
  campaign JSON with per-model round and item filters.
- Required selected evidence to use one fingerprint per round and exactly match the
  currently installed benchmark pack before a config can be written.
- Made routing-only `rounds` and `item_filters` irrelevant to inference-configuration
  identity while preserving model, endpoint, transport, sampling, and other settings.
- Added explicit `--allow-partial` authority for budget-limited panels with uncovered
  directions; complete panels remain the safe default.
- Added deterministic duplicate-key resolution, overwrite protection, offline config
  validation, and privacy-safe panel provenance without source paths or run names.
- Added adversarial controls for routing merges, inference-setting separation, key
  collisions, pack drift, partial panels, output safety, and CLI argument forwarding.
- Bumped local analysis to schema v8; public result schema v2 and canonical Round 1–4
  content and grading remain unchanged.

## 2.14.0 — 2026-09-01

- Added analysis-schema-v7 discriminative item panels over confirmed pair-specific
  configuration directions.
- Added deterministic greedy directional set cover that prioritizes new coverage,
  penalizes robust positive and opposing dependencies, and uses simultaneous margin
  plus absolute effect for stable tie-breaking.
- Preserved opposite specialist directions for the same configuration pair instead of
  collapsing them into a universal model ordering.
- Added `analyze --panel-max-items` with explicit `PARTIAL` status and uncovered target
  retention when a per-pack budget cannot cover all confirmed directions.
- Added panel sections to local and community Markdown while retaining the complete
  machine-readable selection trace and all source evidence.
- Added adversarial controls for multi-pair compression, opposite specialties,
  dependency avoidance, budget shortfall, deterministic selection, and a ten-item
  duplicate panel collapsing to one item.
- Kept public result schema v2 and canonical Round 1–4 content and grading unchanged.

## 2.13.0 — 2026-09-01

- Added `results recommend`, a read-only exact-pack query over validated public
  observations with Markdown and JSON output.
- Added environment, runtime, quantization, model-format, and declared-capacity
  filters that reject missing metadata instead of guessing compatibility.
- Added conservative accuracy and completion objectives based on bundle-cluster 95%
  lower bounds, plus latency and throughput objectives gated on five measured bundles.
- Added multi-objective Pareto selection, an optional conservative accuracy floor,
  and explicit pack-required, no-match, insufficient, single-eligible, and descriptive
  candidate states.
- Prevented repeated model rows in one bundle from unlocking candidate evidence and
  kept bundle IDs and contributor/tool-version history out of query results.
- Added recommendation JSON schema v1 and adversarial controls for cross-pack mixing,
  sparse performance, missing metadata, bulk duplicates, and speed/accuracy tradeoffs.
- Kept public result schema v2 and canonical Round 1–4 content and grading unchanged.

## 2.12.0 — 2026-09-01

- Added analysis-schema-v6 pair-specific item coverage for specialist tasks that
  distinguish exact configuration pairs.
- Added cluster-weighted item pass-rate effects with five-independent-unit gates on
  both sides.
- Added deterministic maximum-error bootstrap intervals simultaneous across every
  eligible item in a configuration pair.
- Added Bonferroni allocation across eligible configuration pairs and a practical
  ten-percentage-point effect gate before directional labels.
- Added item coverage summaries and concise decisive-split tables while retaining all
  eligible pair/item results in JSON.
- Preserved shared public-bundle dependence and prevented 100 repeated rows in one
  bundle from unlocking a comparison.
- Kept public schema v2 and canonical Round 1–4 content and grading unchanged.

## 2.11.0 — 2026-09-01

- Added analysis-schema-v5 repeat-adjusted item separation, comparing equal-weight
  between-configuration outcome differences with same-configuration repeat instability.
- Added distinct `SEPARATING`, `WEAK_SEPARATION`, `NOISE_DOMINATED`, and
  `NO_SEPARATION` observed states.
- Added deterministic hierarchical intervals and robust separating, noise-dominated,
  no-separation, uncertain, unstable, and insufficient states.
- Required at least five independent attempts or bundles for each of two
  configurations before robust inference.
- Preserved shared community-bundle dependence by resampling each bundle once per
  bootstrap draw, even when it contains multiple configurations or repeated rows.
- Fixed Codex session fallback discovery to read at most a bounded transcript header
  instead of loading an entire potentially large JSONL session into memory.
- Kept public schema v2 and canonical Round 1–4 content and grading unchanged.

## 2.10.0 — 2026-09-01

- Added analysis-schema-v4 item dependency diagnostics with raw and independent-
  cluster-weighted outcome agreement and phi correlation for every scored item pair.
- Added deterministic cluster-bootstrap intervals and separate robust redundancy and
  opposing-pattern review signals gated on ten independent units and a full interval
  beyond `±0.8`.
- Added dependency candidate tables to local calibration reports and community result
  indexes, with all pairs retained in JSON and Markdown limited to 20 ranked rows.
- Proved that repeated rows inside one public contribution cannot manufacture robust
  dependency evidence and that bundle weighting can reverse a bulk-duplicate point
  conclusion.
- Kept dependency labels advisory: they never mutate a benchmark pack or claim that
  correlated prompts measure the same latent construct.

## 2.9.0 — 2026-09-01

- Added bounded independent-cluster pass-rate intervals and deterministic bootstrap
  intervals for corrected item discrimination.
- Added separate robust item signals so noisy point estimates cannot directly drive
  benchmark-pack changes.
- Added equal-cluster weighting: local attempts are independent units, while all
  repeated attempts and model rows inside one community bundle remain one unit.
- Added raw and cluster-weighted discrimination side by side, with explicit
  independent-unit and valid-bootstrap counts.
- Added adversarial controls for stable positive/negative/ceiling signal, small-sample
  uncertainty, undefined resamples, determinism, and bulk duplicate-cluster reversal.
- Kept public schema v2 and all canonical Round 1–4 grading contracts unchanged.

## 2.8.0 — 2026-09-01

- Added anonymous configuration scorecards with respondent-level pass rates,
  completion evidence, and bounded 95% intervals withheld below five respondents.
- Added directional head-to-head comparisons with common-item effect sizes,
  win/loss/tie counts, exact two-sided sign tests, and Holm multiple-test correction.
- Added hierarchical respondent/item bootstrap intervals and require both corrected
  significance and an interval excluding zero before reporting a higher configuration.
- Added privacy-safe run/model input coordinates while continuing to exclude model
  labels, endpoint URLs, paths, credentials, prompts, and responses from analysis.
- Kept all benchmark questions and canonical grading contracts unchanged.

## 2.7.0 — 2026-09-01

- Added public result schema v2, collecting every sanitized item status, attempt,
  wall time, and completion-token count by default while continuing to exclude all
  prompts, outputs, transcripts, errors, paths, endpoints, and credentials.
- Added community-side recomputation of item difficulty, corrected discrimination,
  missing/incomplete/review/invalid counts, and within/between-configuration stability.
- Added independent-bundle 95% intervals that prevent repeated attempts or duplicate
  model entries from overstating sample size; 0/0 bundles no longer unlock baselines.
- Added optional serving metadata for model format, parameter count, server version,
  and accelerator count, plus bundle-level latency and token-rate observations.

## 2.6.0 — 2026-09-01

- Added explicit-opt-in, allowlist-only Round 5 public exports that revalidate local
  raw evidence before excluding transcripts, diffs, paths, credentials, endpoints,
  private labels, and tool names from deterministic bundles.
- Added preview-first GitHub pull-request submission for Round 5 summaries, with all
  external writes gated by `--open-pr --yes`.
- Added a separately validated community Round 5 index that groups exact public
  configurations and pack fingerprints, preserves unobserved 0/0 suites, and
  withholds descriptive baselines below five distinct accepted bundles.

## 2.5.0 — 2026-09-01

- Added anonymous-by-default Round 5 cross-pilot analysis with eight-axis outcome
  distance, within-configuration instability, between-configuration separation,
  empirical review gates, Markdown/JSON output, and explicit non-canonical limits.
- Added independent pilot evidence validation for summary/raw-grade agreement,
  transport and sandbox metadata, release-readiness invariants, evidence path safety,
  and bounded transcript rescanning for unsupported tool calls.
- Added unsupported tool-call evidence to new single-pilot grades and reports.

## 2.4.0 — 2026-08-31

- Added a non-canonical three-turn Round 5 research runner with persistent Codex
  sessions, read-only pre-approval enforcement, full local evidence preservation,
  held-back grading, final-report accuracy checks, safe resume behavior, and explicit
  separation from leaderboard scores.
- Fixed `doctor` so every custom `codex_cli` or repository-agent configuration makes
  a real Codex `/responses` probe instead of accepting `/models` discovery alone.
- Fixed relative evidence/state paths, rejected empty agent messages as incomplete,
  and disabled unsupported multi-agent fan-out in the controlled local-model runner.
- Fixed `selftest` source-language scanning so ignored run evidence, build output, and
  isolated environments cannot make a healthy checkout fail after local use.

## 2.3.0 — 2026-08-31

- Added local cross-run calibration reports with pack-separated item difficulty,
  corrected discrimination, ceiling/floor warnings, between-model separation, and
  within-model repeat instability.

## 2.2.0 — 2026-08-31

- Added explicit, allowlist-only public result exports with deterministic bundle IDs,
  privacy validation, stable ZIP output, and no telemetry or automatic submission.
- Added local submission previews and an explicitly confirmed GitHub pull-request
  workflow that supports both repository owners and contributor forks.
- Added CI validation for accepted submissions and a deterministic community index
  that separates incomparable configurations and withholds sparse baselines.

## 2.1.0 — 2026-08-31

- Classified provider output-limit termination as `INCOMPLETE` instead of a wrong
  answer, excluded it from correctness denominators, and exposed it independently in
  progress displays and reports.
- Added provider response-shape diagnostics and retained compatibility with result
  files created before explicit item statuses were introduced.
- Added `inspect` text and JSON views for unresolved items in current and legacy runs.
- Added focused `replay` campaigns that preserve parent evidence and select only
  failed, incomplete, or infrastructure-invalid question and task IDs.
- Added versioned benchmark-pack manifests, safe asset validation, content
  fingerprints in reports, and `pack validate` for external authoring workflows.
- Added an executable Round 5 research pilot with evolving requirements and a stable
  control matrix that separates a correct fix from four public-green failure modes.

## 2.0.0 — 2026-08-31

- Unified the repository, benchmark, reports, Python package, and command under the
  LLM Hardtest name.
- Renamed the public Python import package to `llm_hardtest` and removed the legacy
  compatibility launcher and installed command.
- Renamed the default API-key environment variable to `LLM_HARDTEST_API_KEY` and the
  default campaign to `llm-hardtest`. Existing configuration files must update the
  environment-variable name explicitly.

## 1.1.0 — 2026-08-31

- Added a dependency-free live terminal dashboard with campaign progress, current
  model/round/item, elapsed time, ETA, result counters, resume counts, and output path.
- Added `--progress auto|dashboard|plain`; interactive terminals default to the live
  dashboard while redirected output and CI retain stable line-oriented logs.
- Connected Round 4 attempt progress to the shared display and preserved its detailed
  harness output in `round4/harness.log` while the dashboard is active.

## 1.0.1 — 2026-08-30

- Stopped persisting real custom-provider API keys and restricted generated auth files.
- Enforced exact final-answer matching and quarantined infrastructure errors from
  correctness denominators.
- Rejected path-traversal campaign names and reserved model keys.
- Added authenticated Round 4 preflight, `discover`, live `doctor` probes, server
  presets, and per-model round selection.
- Bundled benchmark data in wheels so standard `pip install .` works.
- Preserved infrastructure exceptions in reports and made failed attempts resumable.
- Added regression coverage for all adversarial-review findings.

## 1.0.0 — 2026-08-30

- Published rounds 1–4 as LLM Hardtest Report.
- Added interactive and JSON-configured multi-model campaign execution.
- Added independent repetitions, resumability, raw artifact retention, and English reports.
- Added local-model smoke configuration, backend setup, integrity guidance, and a
  configuration-validation command.
- Added GitHub issue forms, pull-request guidance, security policy, support policy,
  contribution rules, and multi-version CI.
- Hardened config validation and OpenAI-compatible response parsing.
- Ported all prompts, code comments, test descriptions, and grader messages to English.
- Adopted corrected Q30v2 dual-path grading and Q31 approval follow-through.
- Preserved release readiness and safe-handoff utility as separate axes.
- Added unit tests, grader self-tests, trap proofs, and CI.
