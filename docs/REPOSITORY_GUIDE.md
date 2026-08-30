# Repository and Source Guide

## Layout

```text
.
├── llm-hardtest                # checkout-local launcher
├── pattern0-bench              # compatibility launcher
├── pyproject.toml              # package metadata and installed commands
├── setup.py / MANIFEST.in      # wheel and source-data bundling
├── configs/                    # safe example configurations
├── docs/                       # user, scoring, integrity, and developer guides
├── rounds/                     # benchmark data, tasks, runners, and graders
├── src/pattern0_bench/         # installable harness source
└── tests/                      # harness unit tests
```

The source package contains `cli.py` for commands, `orchestrator.py` for validation
and resume behavior, `backends.py` for API transports, round-specific runners, and
`report.py` for the machine-readable summary and Markdown report.

## Execution flow

1. The CLI loads and validates a JSON config.
2. The orchestrator snapshots it in a timestamped run directory.
3. A backend is created for each model configuration.
4. Each selected round and repetition starts independently.
5. Result JSON is written atomically after each completed unit.
6. Existing result files are skipped during resume.
7. The reporter collects saved evidence into `summary.json` and `REPORT.md`.

## Comment and documentation style

Comments should explain why a constraint exists, especially around sandbox boundaries,
resume semantics, grading authority, false-green detection, or provider quirks. Use a
docstring for public modules, classes, and functions whose contract is not obvious.
Avoid comments that merely repeat the next line, stale commented-out code, or TODOs
without an issue reference and enough context to evaluate them.

User-visible behavior belongs in `README.md` or `docs/`. Configuration fields belong
in `CONFIGURATION.md`. A scoring rule must also be explained in `SCORING.md`, covered
by controls, and recorded in `CHANGELOG.md` when it changes compatibility.

## Generated data

Campaign results belong under `runs/` and are ignored by Git. A result intended for
publication should normally live in a separate release artifact or results repository,
not in the harness history. Never commit local Codex homes, authentication material,
model weights, caches, or personally identifying paths.
