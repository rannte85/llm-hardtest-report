# Release Notes — 2.7.0

This repository is ready to publish as `rannte85/llm-hardtest-report`. It contains no campaign
outputs, credentials, local model files, personal filesystem paths, or generated
Python caches.

The release validation covers:

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
