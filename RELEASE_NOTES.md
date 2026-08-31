# Release Notes — 2.14.0

This repository is ready to publish as `rannte85/llm-hardtest-report`. It contains no campaign
outputs, credentials, local model files, personal filesystem paths, or generated
Python caches.

The release validation covers:

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
