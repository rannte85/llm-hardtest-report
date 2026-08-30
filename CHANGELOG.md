# Changelog

All notable changes are documented here. Benchmark-scoring compatibility is called
out separately from harness features.

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

- Published Pattern0 rounds 1–4 as LLM Hardtest Report.
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
