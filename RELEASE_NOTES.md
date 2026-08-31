# Release Notes — 2.26.0

This repository is ready to publish as `rannte85/llm-hardtest-report`. It contains no raw
campaign outputs, credentials, local model files, personal filesystem paths, or
generated Python caches. The included Luna result is the allowlist-only public bundle,
not its prompts, responses, transcripts, account details, or local run directory.

The release validation now also covers:

- public schema v3 with explicit same-host, remote, and unreported serving provenance;
- conservative v1/v2 migration that never treats a contributor's client OS as the
  model server OS;
- signed-in GPT-5.6 Luna classified as remote without invented server coordinates;
- SQLite v3 and schema parity across catalog, recommendation, paired comparison,
  collection planning, and predictive-readiness paths;
- exclusion of unattested hosts from environment-diversity and portability gates while
  retaining their valid correctness and latency observations.

The retained validation also covers:

- one live signed-in Codex `gpt-5.6-luna` Round 1 control with 20/20 scored items,
  146.389 seconds total item wall time, no incomplete items, and no infrastructure
  errors, plus an included reusable one-round configuration;
- structured Codex JSONL usage parsing that keeps input, cached-input, output,
  reasoning-output, and total token meanings separate;
- quarantine of legacy Codex total-token footers from public completion-token
  throughput, while retaining their valid correctness and latency observations;
- a validated sanitized Luna submission, regenerated community index, JSON/SQLite
  parity, and explicit sparse-evidence readiness gaps without predictive authorization;

- executable predictive-serving readiness audits over canonical JSON and verified
  SQLite, with identical privacy-preserving results;
- independent per-objective configuration coverage, exact-configuration and declared
  environment diversity, and paired edges requiring five shared bundles;
- exact model-profile environment bridges that fix inference/model identity and require
  five independent bundles in each qualifying environment;
- explicit temporal holdout, abuse/duplicate/implausibility review, and future drift
  gates, with prediction authorization fixed false even when design targets pass;
- public prediction-readiness schema v1 plus repeated-row, missing-metric, one-bundle
  bridge, profile-confounding, pack, threshold, CLI, and cross-adapter controls;

- shared-independent-bundle head-to-head comparison for two exact serving
  configurations across accuracy, completion, latency, and throughput;
- deterministic paired-cluster bootstrap intervals, exact or deterministic Monte
  Carlo two-sided sign-flip tests, and Holm family-wise correction across objectives;
- direction-invariant seeding and exact left/right symmetry, repeated-run collapse,
  objective-specific missing-measurement gates, and explicit practical-effect caveats;
- canonical JSON/verified SQLite parity, paired-comparison schema v1, privacy-preserving
  Markdown/JSON output, and sparse/inconclusive/directional/mixed states;

- deterministic independent-bundle acquisition plans for accuracy, completion,
  latency, and throughput, with separate observed counts and per-objective deficits;
- configurable 5–1000 bundle targets, exact configuration filtering, explicit pack
  selection, and a conservative minimum-additional-complete-bundles lower bound;
- an explicit five-scored-bundle accuracy prerequisite even when only completion,
  latency, or throughput is selected;
- canonical JSON/verified SQLite parity, public collection-plan schema v1, read-only
  Markdown/JSON output, and no bundle or contributor identities;
- sparse, partial-metric, already-ready, high-target, multi-pack, invalid-target,
  conflicting-source, privacy, schema, CLI, and installed-package controls;

- exact discovery and filtering for every public configuration coordinate, including
  stable configuration ID, environment/Python, generation settings, model revision,
  serving version, accelerator count, and exact or maximum capacity values;
- catalog schema v2 and recommendation schema v2, with historical v1 contracts left
  intact and JSON/SQLite adapters producing identical full-coordinate responses;
- public schemas, SQLite DDL, result guides, and project documentation shipped inside
  the Python source distribution;
- numeric facet normalization plus explicit missing-coordinate coverage for every
  optional parameter and serving/hardware field;
- adversarial null/non-finite numeric, non-string key, malformed configuration ID,
  conflicting-coordinate, numeric-affinity, CLI, and installed-package controls;

- deterministic observed-serving catalogs from canonical JSON or verified SQLite,
  including exact configurations, queryable facets, evidence counts, conservative
  metrics, per-objective readiness, and explicit missing-metadata coverage;
- byte-identical cross-adapter catalog JSON with separate empty-source and filtered-
  no-match states, no bundle/contributor history, and a published schema-v1 contract;
- exact case-insensitive `--model` candidate filtering plus CLI discovery that removes
  the need to guess model, server, hardware, quantization, round, or pack values;
- adversarial privacy, sparse-readiness, invalid-filter, conflicting-source, Markdown,
  installed-package, and cross-adapter controls;

- direct gated Pareto recommendations from verified normalized SQLite databases;
- one shared recommendation implementation for canonical JSON and database aggregate
  adapters, with byte-identical machine-readable results for identical evidence;
- database schema v2 numeric-normalized, independently recomputable fingerprints and
  an explicit rebuild gate for version-2.18 schema-v1 generated files;
- standalone semantic checks for canonical/flattened configuration agreement, safe
  public fields, identities, relational links, metric domains, statuses, and flags;
- adversarial cross-adapter, repeat-cluster, stale-fingerprint, obsolete-schema,
  fresh-fingerprint semantic-tamper, ambiguous-source, and installed-wheel controls;

- the normalized SQLite database v1 foundation over validated public repository bundles
  (superseded by the independently verifiable schema v2 in this release);
- bundle-cluster provenance across exact configurations, benchmark runs, item rows,
  and Round 4 task rows without ingesting raw local evidence;
- queryable model, server, hardware, environment, and generation coordinates plus
  canonical allowlisted JSON and full SHA-256 row identities;
- deterministic logical content fingerprints, atomic builds, integrity/foreign-key
  validation, and read-only whole-database `--check` comparison;
- published SQL/privacy/query documentation and adversarial duplicate-row, tamper,
  deterministic-build, empty-dataset, CLI, and task-observation controls;

- analysis schema v10 with two-sided held-out label-permutation tests and Holm
  family-wise correction across both validation folds;
- exact enumeration for small assignment spaces and deterministic 20,000-draw Monte
  Carlo inference for larger spaces and fractional public-bundle rates;
- dual practical-effect and adjusted-significance gates for confirmed and reversed
  direction labels;
- raw and adjusted p-values plus complete permutation audit metadata in JSON and
  concise Markdown reports;
- panel-focus schema v3 family-wise alpha and multiplicity provenance;
- adversarial nominal-effect, perfect-replication, reversed, sparse, fractional-rate,
  and deterministic controls with unchanged public schema and canonical grading;

- analysis schema v9 with deterministic two-fold panel selection and untouched-fold
  directional evaluation;
- stable, weak-generalization, reversed-signal, and insufficient states that never
  present sparse or contradictory holdout evidence as successful replication;
- shared public-bundle fold assignment that preserves contribution-level dependence;
- direction confirmation rates, item-selection Jaccard overlap, and complete fold
  traces in machine-readable and Markdown outputs;
- `focus --require-holdout-stable` plus panel-focus schema v2 privacy-safe validation
  provenance in generated local configs;
- adversarial stable, reversal, sparse, shared-cluster, deterministic, and privacy
  controls with unchanged canonical questions, grading, and public schema;

- a new `focus` command that converts confirmed discriminative panels into runnable
  campaign configs with model-level round and item filters;
- exact installed-pack matching and mixed-fingerprint rejection before configuration
  output is written;
- inference identity that ignores prior routing-only rounds and filters but preserves
  model, endpoint, transport, sampling, and other settings;
- explicit `--allow-partial` authority with uncovered directional targets retained;
- deterministic duplicate-key suffixes, overwrite protection, offline validation, and
  privacy-safe panel provenance without source paths or source campaign names;
- adversarial controls plus an E4B one-run control that correctly refuses to invent a
  confirmed panel from insufficient evidence;
- local analysis schema v8 with unchanged public result schema v2 and canonical Round
  1–4 grading contracts;

- analysis schema v7 with a discriminative item panel built only from already-confirmed
  pair-specific configuration directions;
- deterministic greedy directional set cover that maximizes new coverage before
  dependency cost, simultaneous margin, absolute effect, and stable item-ID ties;
- robust positive and opposing item relationships used as penalties rather than
  automatic item deletion rules;
- preservation of both directions when one configuration pair has confirmed specialist
  strengths on different items;
- a per-round/pack `--panel-max-items` budget with explicit partial status and complete
  uncovered-direction retention;
- local and community Markdown panel summaries plus a complete JSON selection trace;
- adversarial controls for multi-pair compression, opposing specialties, robust
  dependency avoidance, budget shortfall, deterministic output, sparse community
  evidence, and ten identical directional items collapsing to one;
- unchanged public result schema v2 and canonical Round 1–4 grading contracts;

- a read-only `results recommend` command that queries only validated repository
  observations from one exact benchmark pack;
- exact public environment, transport, runtime, quantization, model-format, and
  declared-capacity filters, with missing metadata rejected instead of inferred;
- conservative accuracy and completion objectives based on bundle-cluster interval
  lower bounds and a conservative optional accuracy floor;
- latency and throughput objectives withheld until five independent bundles contain
  the corresponding measurements;
- multi-objective Pareto candidates instead of an opaque universal score, with
  explicit pack-required, no-match, insufficient-evidence, single-eligible, and
  descriptive-candidate states;
- deterministic Markdown and recommendation-schema-v1 JSON that omit bundle IDs and
  contributor/tool-version history;
- adversarial controls for a speed/accuracy tradeoff, sparse performance evidence,
  cross-pack ambiguity, missing hardware metadata, and 100 duplicate model rows in
  one bundle;
- unchanged public result schema v2 and canonical Round 1–4 grading contracts;

- analysis schema v6 with pair-specific item coverage for tasks that separate exact
  configuration pairs outside a single aggregate ability axis;
- cluster-weighted pass-rate effects gated on at least five independent attempts or
  bundles per configuration and item;
- deterministic maximum-error bootstrap intervals simultaneous over every eligible
  item in a configuration pair;
- Bonferroni allocation across eligible configuration pairs, targeting family-wise
  95% coverage over the complete exploratory scan;
- a ten-percentage-point practical effect gate in addition to simultaneous interval
  exclusion before `LEFT_HIGHER` or `RIGHT_HIGHER` is emitted;
- adversarial controls for a stable specialist item, a shared noisy item, a 20-item
  null family, three-pair error allocation, one bundle with 100 repeated rows, and
  deterministic shared-bundle resampling;
- complete pair/item JSON retention with concise 20-row Markdown decisive details;
- unchanged public result schema v2 and canonical Round 1–4 grading contracts;

- analysis schema v5 with per-item between-configuration separation,
  same-configuration repeat instability, and their repeat-adjusted difference;
- separate observed signals for stable separation, weak separation, noise-dominated
  behavior, unanimous no-separation, and insufficient evidence;
- deterministic hierarchical 95% intervals requiring at least five independent units
  for each of two configurations before a robust item signal is possible;
- shared-bundle community bootstrap draws that preserve outcomes from multiple
  configurations in one contribution instead of pretending they are independent;
- explicit `ROBUST_SEPARATING`, `ROBUST_NOISE_DOMINATED`, `ROBUST_NO_SEPARATION`,
  `UNCERTAIN`, `UNSTABLE`, and `INSUFFICIENT` decisions;
- adversarial controls for stable strong-vs-weak outcomes, identical noisy outcomes,
  unanimous outcomes, a bundle with 100 repeated rows, and deterministic shared-bundle
  resampling;
- bounded Codex session fallback reads that avoid loading a complete long-running
  JSONL transcript merely to recover its session ID;
- unchanged public result schema v2 and canonical Round 1–4 grading contracts;

- analysis schema v4 with pairwise item outcome agreement and phi correlation in both
  raw observation-weighted and independent-cluster-weighted forms;
- deterministic cluster-bootstrap intervals for empirical redundancy and opposing-
  pattern candidates, with robust signals withheld below ten independent units;
- a strict `±0.8` interval gate that prevents ordinary relatedness or a noisy point
  estimate from becoming a pack-maintenance signal;
- adversarial coverage proving that 100 repeated rows in one bundle cannot unlock a
  robust relationship and that equal bundle weighting can reverse a bulk-duplicate
  raw conclusion;
- complete machine-readable pair retention with concise 20-row Markdown views and
  explicit content-review requirements before any benchmark change;
- unchanged public result schema v2 and canonical Round 1–4 grading contracts;

- analysis schema v3 with raw and independent-cluster-weighted corrected item
  discrimination, bounded pass-rate intervals, and deterministic bootstrap intervals;
- robust item decisions gated on ten independent clusters and at least 80% defined
  bootstrap draws, while retaining the original five-observation point signal;
- `ROBUST_USEFUL`, `ROBUST_NEGATIVE`, `ROBUST_CEILING`, `ROBUST_FLOOR`, `UNCERTAIN`,
  `UNSTABLE`, and `INSUFFICIENT` states that keep noisy estimates reviewable;
- bundle-clustered community inference where repeated attempts and duplicate model
  rows in one contribution cannot narrow confidence intervals;
- equal-cluster weighting verified against an adversarial bulk duplicate cluster that
  reverses the raw observation-weighted correlation;
- unchanged public result schema v2 and canonical Round 1–4 grading contracts;

- retained anonymous `C1`-style configuration aliases and safe
  run/model input coordinates for mapping results back to the supplied configuration;
- per-configuration respondent counts, completion evidence, mean respondent pass
  rates, and conservative 95% intervals withheld below five scored respondents;
- directional pairwise effect sizes and item win/loss/tie counts across commonly
  scored items without converting incomplete, review, or invalid work into failures;
- exact two-sided sign tests with Holm family-wise correction across every eligible
  configuration pair;
- deterministic hierarchical bootstrap intervals that resample respondents and items,
  preventing an unstable nominal item winner from becoming a directional claim;
- a dual evidence gate requiring both adjusted p < 0.05 and an effect interval that
  excludes zero, with `UNCERTAIN` and `INSUFFICIENT` retained explicitly;
- unchanged canonical Round 1–4 questions and grading contracts;

- schema-v2 public bundles with every item status, attempt number, wall time, and
  completion-token count, plus backward validation of aggregate-only schema v1;
- aggregate/item consistency checks that reject rehashed score contradictions and
  conflicting duplicate item observations;
- community recomputation of item difficulty, corrected discrimination, signal
  class, missing outcomes, and repeat-vs-configuration disagreement;
- bundle-cluster 95% intervals where each independent submission contributes one
  rate regardless of repeated attempts or duplicate model entries;
- observed-bundle thresholds that cannot be unlocked by 0/0 test suites;
- optional model format, parameter count, server version, accelerator count, latency,
  and token-rate fields suitable for a future environment-aware serving recommender;

- explicit-opt-in Round 5 public export, complete JSON preview, and GitHub PR
  submission with no external write before `--open-pr --yes`;
- raw-evidence revalidation before export and an allowlist that excludes transcripts,
  messages, diffs, changed-file names, tool names, endpoints, credentials, paths,
  run identifiers, timestamps, and private labels;
- deterministic public pilot ZIPs, content-derived IDs, strict archive membership,
  semantic consistency validation, canonical filenames, and duplicate rejection;
- a separate community Round 5 index with exact configuration/pack grouping,
  correct unobserved 0/0 handling, and descriptive baselines withheld below five
  distinct accepted bundles;
- explicit documentation that sanitized submissions are voluntary observations and
  cannot independently reproduce the withheld raw evidence;

- anonymous-by-default Round 5 cross-pilot Markdown/JSON analysis across eight
  observed outcome axes, with explicit model-label opt-in;
- within-configuration repeat distance, between-configuration distance, net observed
  separation, exact-repeat agreement, and automatic minimum-evidence gates;
- independent revalidation of summary/raw-grade equality, turn completion, sandbox
  authority, release-readiness invariants, final-report facts, changed-file evidence,
  transcript size, evidence symlink boundaries, and unsupported Codex tool calls;
- correct preservation of unobserved `0/0` test suites as missing evidence rather
  than model failures, plus explicit refusal to predict untested models or promote
  Round 5 without manual ambiguity review;
- a dedicated non-canonical Round 5 command that preserves three persistent-session
  turns, uses read-only sandboxes until explicit approval, and keeps the complete
  workspace, transcripts, messages, diffs, public tests, and held-back grades;
- strict separation between transport-complete evidence and a passing result through
  independent `status`, `release_ready`, test, hypothesis-revision, and report-accuracy
  fields;
- safe interruption behavior for timeouts, nonzero exits, missing sessions, empty
  final messages, and pre-approval edits, with no partial-evidence overwrite;
- a live `/responses` doctor check for every repository-agent model and a local Ollama
  configuration example, with unsupported multi-agent fan-out disabled;
- status-only cross-run calibration reports that never copy prompts, responses,
  model identifiers, endpoint URLs, paths, or credentials;
- exact pack-fingerprint separation, duplicate-run and evidence-symlink rejection,
  Round 1–4 item extraction, and deterministic Markdown plus JSON output;
- corrected item-total discrimination, normalized difficulty balance, ceiling/floor
  and negative-signal review flags, configuration separation, and repeat instability;
- explicit small-sample limits and methodology documentation that avoid presenting
  descriptive diagnostics as IRT estimates or predictions for untested models;
- local-only, allowlist-based public exports with deterministic bundle IDs and no
  telemetry, raw responses, endpoint URLs, credentials, paths, run IDs, or timestamps;
- an exact JSON preview and an explicit `--open-pr --yes` consent boundary before any
  GitHub branch, file, fork, or pull-request write;
- owner and contributor-fork submission flows exercised with simulated GitHub APIs;
- CI validation of public schemas, content hashes, canonical filenames, privacy
  invariants, duplicate IDs, and a deterministic community result index;
- comparison groups separated by environment, model configuration, round, and pack
  fingerprint, with sparse descriptive baselines withheld below five distinct bundles;
- explicit incomplete-generation scoring, legacy-result compatibility, failure
  inspection, and focused replay into a new evidence directory;
- reusable manifests and stable content fingerprints for all bundled benchmark packs;
- an executable Round 5 pilot whose correct control passes 9/9 held-back checks while
  four public-green partial or tampered controls each fail their distinct contract;
- consistent `llm-hardtest` command, `llm_hardtest` package, report, and configuration
  naming, with no legacy compatibility alias in the published wheel;
- parsing every JSON asset;
- 20 Round 1 questions, 20 Round 2 questions, five Round 3 tasks, and six canonical
  Round 4 repository tasks;
- English-only source and assets;
- unit tests for answer normalization, structured grading, configuration validation,
  and comprehensive-report generation;
- Round 4 harness self-tests;
- executable Q30v2 and Q31 positive and negative trap proofs;
- dry-run orchestration for two model configurations across all four rounds.
- public onboarding, backend, integrity, development, issue, pull-request, support,
  and security documentation.
- adversarial-review fixes for credential handling, path safety, exact-answer grading,
  infrastructure quarantine, live server/model diagnosis, and installed package data.
- interactive terminal dashboard behavior, plain-log fallback, resume accounting, and
  Round 1–4 progress-event regression coverage.

The package deliberately does not include historical campaign results. A new
campaign writes its report and all evidence into the selected `runs/` directory.
