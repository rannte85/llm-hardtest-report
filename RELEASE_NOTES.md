# Release Notes — 2.2.0

This repository is ready to publish as `rannte85/llm-hardtest-report`. It contains no campaign
outputs, credentials, local model files, personal filesystem paths, or generated
Python caches.

The release validation covers:

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
