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

Round 5 follows the same consent boundary with `pilot export --public`,
`pilot submit --preview`, and `pilot submit --open-pr --yes`. Nothing is uploaded
automatically.

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

`results build` groups records only when model name, environment, transport,
generation parameters, declared metadata, round, and pack fingerprint match. It
withholds a descriptive pass-rate baseline until five distinct accepted bundles exist
in that exact group. Duplicate entries inside one bundle count only once toward that
threshold. A future predictive model would require substantially more
representative data, uncertainty reporting, abuse controls, and an explicit statement
of the population it claims to predict.

## Round 5 public pilot summaries

Round 5 submissions use `results/pilot-schema-v1.json`, live under `results/pilots/`,
and are aggregated into `results/PILOTS.md`:

```bash
llm-hardtest pilot export runs/my-pilot --public --output pilot-bundle.zip
llm-hardtest pilot submit pilot-bundle.zip --preview
llm-hardtest pilot submit pilot-bundle.zip --open-pr --yes
```

Before export, the tool revalidates the saved raw grade against bounded transcripts,
patch evidence, transport state, sandbox sequence, test results, report claims, and
release-readiness invariants. The public bundle contains only status, completed-turn
count, authority and evidence-revision flags, public/hidden aggregate scores, release
and report flags, protocol-error counts, timing, tokens, and allowlisted public model
configuration.

It never contains transcripts, messages, prompts, response text, diffs, changed-file
names, tool names, endpoints, credentials, environment-variable names, run paths, or
private labels. Because those raw artifacts remain local, repository validation can
verify the public schema, hash, privacy rules, and internal consistency but cannot
independently reproduce a submitter's raw evidence. Community values are descriptive
and remain labeled `withheld` until five distinct comparable bundles are accepted.
