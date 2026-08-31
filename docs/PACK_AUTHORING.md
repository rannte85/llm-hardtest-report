# Benchmark Pack Authoring

A pack is a directory with a versioned `manifest.json` and the assets needed to
reproduce its grading contract. Validate a bundled or external pack without calling a
model:

```bash
llm-hardtest pack validate rounds/round1
llm-hardtest pack validate path/to/external-pack --json
```

## Manifest fields

- `schema_version`: currently `1`.
- `id`: lowercase filesystem-safe identifier.
- `title`: human-readable title.
- `runner_kind`: `reasoning`, `structured`, or `coding_agent`.
- `capabilities`: any of `chat_completions`, `responses`, `filesystem`, and
  `multi_turn`.
- `unit_count`: planned independently reported units.
- `time_limit_seconds`: default per-unit ceiling.
- `result_schema`: result contract identifier owned by the pack.
- `assets`: relative paths or glob patterns included in the content fingerprint.
- `controls`: positive or negative control commands represented as argument arrays.

Asset paths may not be absolute, traverse to a parent directory, or resolve through a
symlink outside the pack. Every pattern must match at least one file. Commands are
stored as argument arrays so pack tooling never needs to interpret a shell string.
Python bytecode and standard tool-cache directories are excluded from matched assets
so a validation run cannot change the pack fingerprint.

The validator computes a SHA-256 fingerprint from the canonical manifest and every
matched asset path and byte sequence. Reports retain the fingerprint of each selected
bundled round. Any prompt, dataset, task repository, or held-back grader file capable
of changing a score must therefore appear in `assets`.

## Controls and review

A grader change must include a correct positive control and realistic negative
controls. Negative controls should represent tempting partial fixes rather than
arbitrary broken submissions. Verify that they fail for the intended reason, that the
correct control passes, and that repeated runs are stable before publishing the pack.

Schema validation proves structural safety and reproducibility; it does not execute a
pack or declare its scoring policy sound. Review authority sources, contamination
limits, sandbox assumptions, and trap behavior separately.
