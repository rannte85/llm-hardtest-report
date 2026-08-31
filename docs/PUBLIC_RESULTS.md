# Voluntary Public Results

LLM Hardtest does not collect telemetry. Campaign artifacts stay on the machine that
ran them unless a user deliberately exports and submits a public result.

## Consent boundary

The public-results workflow has three separate actions:

1. `export --public` creates a local, sanitized bundle.
2. `submit --preview` validates and displays the exact JSON proposed for publication.
3. `submit --open-pr --yes` explicitly authorizes GitHub writes and opens a pull
   request. No command performs this step by default.

Publishing a result makes the submitted fields, GitHub account, and pull-request
history public. Deleting a merged file later cannot guarantee removal from Git history,
forks, caches, or downstream copies.

## Public schema v1

Each submission contains only aggregate benchmark results and an allowlisted set of
reproducibility fields:

- schema and tool version;
- a content-derived bundle ID;
- selected rounds and pack fingerprints;
- operating-system family, CPU architecture, and Python major/minor version;
- a public model name, transport, selected generation parameters, and optional
  explicitly configured public metadata;
- aggregate per-round scores, incomplete/review/invalid counts, release readiness,
  handoff utility, false-green counts, timing, and task-level Round 4 grades.

The exporter never includes raw prompts or responses, transcripts, diffs, source
repositories, API keys, environment-variable names, endpoint URLs, campaign/run IDs,
timestamps, local paths, usernames, model keys, display labels, Codex homes, or error
messages. The formal shape is documented in `results/schema-v1.json`; the CLI applies
additional semantic and privacy checks without requiring a JSON Schema dependency.

Model identifiers containing an absolute path, URL, email-like value, control
character, or home-directory marker are replaced with `model-N`. Set a deliberately
public `public_name` in that model's config before running if the exact model identity
should be published.

## Optional public metadata

A model config may contain a `public_metadata` object with these keys:

- `model_revision`
- `quantization`
- `server`
- `accelerator`
- `memory_gb`
- `system_memory_gb`

These fields are never inferred from the machine. Hardware combinations can still be
identifying, so include them only when publication is intended. Unknown metadata keys
are dropped rather than copied through.

## Repository workflow

Validated submissions live under `results/submissions/` as one canonical JSON file
per bundle ID. A pull request must add exactly the sanitized result intended for
publication. CI validates schemas, bundle hashes, filenames, privacy invariants, and
duplicate IDs. Maintainers may reject unverifiable, misleading, poisoned, or
personally identifying submissions even when structural validation passes.

The repository can aggregate accepted files into counts, score distributions, and
descriptive baselines. Aggregates are observational examples, not predictions of an
unseen model and not evidence that different hardware, quantization, prompts, server
versions, or pack fingerprints are directly comparable.
