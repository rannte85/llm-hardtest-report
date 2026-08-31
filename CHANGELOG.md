# Changelog

All notable changes are documented here. Benchmark-scoring compatibility is called
out separately from harness features.

## Unreleased

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
