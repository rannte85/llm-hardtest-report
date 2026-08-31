# Changelog

All notable changes are documented here. Benchmark-scoring compatibility is called
out separately from harness features.

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
