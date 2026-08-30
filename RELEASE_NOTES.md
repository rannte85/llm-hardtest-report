# Release Notes — 1.0.1

This repository is ready to publish as `rannte85/llm-hardtest-report`. It contains no campaign
outputs, credentials, local model files, personal filesystem paths, or generated
Python caches.

The release validation covers:

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

The package deliberately does not include historical Pattern0 campaign results. A new
campaign writes its report and all evidence into the selected `runs/` directory.
