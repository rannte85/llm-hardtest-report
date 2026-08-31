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

## Public schema v2

Current exports contain every content-free item outcome, aggregate benchmark results,
and an allowlisted set of reproducibility fields:

- schema and tool version;
- a content-derived bundle ID;
- selected rounds and pack fingerprints;
- operating-system family, CPU architecture, and Python major/minor version;
- a public model name, transport, selected generation parameters, and optional
  explicitly configured public metadata;
- aggregate per-round scores, incomplete/review/invalid counts, release readiness,
  handoff utility, false-green counts, timing, and task-level Round 4 grades.
- every item ID, attempt number, normalized status, wall time, and completion-token
  count. No prompt, expected answer, extracted answer, or generated content is copied.

The exporter never includes raw prompts or responses, transcripts, diffs, source
repositories, API keys, environment-variable names, endpoint URLs, campaign/run IDs,
timestamps, local paths, usernames, model keys, display labels, Codex homes, or error
messages. The current shape is documented in `results/schema-v2.json`; aggregate-only
schema-v1 bundles remain valid. The CLI applies additional semantic and privacy checks
without requiring a JSON Schema dependency.

Model identifiers containing an absolute path, URL, email-like value, control
character, or home-directory marker are replaced with `model-N`. Set a deliberately
public `public_name` in that model's config before running if the exact model identity
should be published.

## Optional public metadata

A model config may contain a `public_metadata` object with these keys:

- `model_revision`
- `quantization`
- `model_format`
- `parameter_count_b`
- `server`
- `server_version`
- `accelerator`
- `accelerator_count`
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
withholds a descriptive pass-rate baseline until five distinct accepted bundles with
observed scores exist in that exact group. Each bundle contributes one rate regardless
of its internal attempt count, and the displayed Wilson-style 95% interval is
calculated across bundle-level rates. Schema-v2 item outcomes also support community difficulty,
corrected-discrimination, and repeat-stability diagnostics. A future predictive model
would require substantially more
representative data, uncertainty reporting, abuse controls, and an explicit statement
of the population it claims to predict.

Community item confidence uses the accepted bundle as the independent resampling unit.
Repeated attempts and duplicate model rows remain visible as observations but cannot
increase the independent-bundle count or narrow a robust-discrimination interval. The
index shows raw and bundle-clustered corrected discrimination separately when those
weightings disagree.

The community index also derives a discriminative item panel from already-confirmed
pair directions. It greedily covers directions while penalizing robust positive or
opposing item dependencies. The operation does not expose bundle IDs, change accepted
submissions, or mutate benchmark content. Without sufficient independent bundles it
emits `INSUFFICIENT` rather than proposing a panel.

Community out-of-fold validation keeps every row from one contribution in a single
fold, recomputes panel selection on training bundles, and checks selected directions on
the untouched half. The index reports confirmation rate and selected-item Jaccard as
separate diagnostics. This reduces selection bias for observed configurations but does
not predict an unseen model, server, or hardware environment. Exact or deterministic
Monte Carlo label permutations support fractional bundle-level rates, and Holm
correction covers every tested held-out direction.

See [Community Data Model](COMMUNITY_DATA_MODEL.md) for the normalization and staged
path from descriptive observations to an environment-aware serving recommendation.

## Normalized SQLite database

Maintainers can materialize the validated repository JSON without changing its privacy
or independence boundaries:

```bash
llm-hardtest results database results/submissions \
  --output results/community.sqlite3
llm-hardtest results database results/submissions \
  --output results/community.sqlite3 --check
```

The builder makes no network request and cannot read local campaign directories. It
retains each public bundle as the uncertainty cluster, separates exact configurations,
and links benchmark runs to content-free item and Round 4 task observations. Integrity,
foreign keys, schema identity, every normalized row, and a deterministic logical
fingerprint are checked before a build is accepted. See
[Community Observation Database](COMMUNITY_DATABASE.md) for the table contract and
query examples.

The serving-candidate query can consume this verified snapshot directly:

```bash
llm-hardtest results recommend \
  --database results/community.sqlite3 \
  --round 1 --pack sha256:<full-pack-fingerprint> \
  --objective accuracy --objective latency --json
```

Database and JSON inputs use the same aggregation and recommendation implementation.
Schema v2 independently recomputes its numeric-normalized fingerprint and validates
relational semantics before returning a result. A schema-v1 file from version 2.18 must
be rebuilt from canonical JSON.

## Observed serving catalog

Use the catalog to discover valid query values and evidence coverage without reading
SQLite tables or guessing spelling:

```bash
llm-hardtest results catalog results/submissions --round 1
llm-hardtest results catalog --database results/community.sqlite3 --json
```

It lists exact public configurations and facets for the configuration ID, model,
OS/architecture/Python, transport, every generation parameter, model revision/format,
quantization, server/version, accelerator/count, and declared memory/model size. Each
round/pack observation shows its independent-bundle count, conservative metrics, and
readiness for accuracy, completion, latency, and throughput. Every missing optional
coordinate is counted separately and never converted into a match. JSON follows
`results/catalog-schema-v2.json`; it contains no bundle IDs, contributor identity, or
tool-version history. Canonical JSON and a verified database produce identical output.

## Descriptive serving-candidate query

`results recommend` is read-only: it validates accepted JSON and writes nothing unless
an explicit `--output` path is supplied. It never contacts submitters or a model server.

```bash
llm-hardtest results recommend results/submissions \
  --round 1 --pack sha256:<full-pack-fingerprint> \
  --configuration 0123456789 \
  --model "org/model" \
  --server-version "1.2.3" --context-window 32768 --temperature 0 \
  --objective accuracy --objective throughput --json
```

The query requires five independent bundles for every selected evidence axis, applies
an optional accuracy floor to the 95% lower bound, and returns the non-dominated set.
Repeated attempts or duplicate model rows inside one bundle cannot unlock a candidate.
Constraints with missing metadata do not match. Results remain descriptive for the
exact pack and public configuration; they are not predictions for untested hardware.
The machine-readable result follows `results/recommendation-schema-v2.json`. Exact
filters cover every allowlisted configuration coordinate; `max-memory-gb`,
`max-system-memory-gb`, and `max-parameter-count-b` remain ceiling filters rather than
exact settings.

## Evidence collection plan

Use `results plan` to turn sparse observed configurations into a concrete, bounded
request for additional independent contributions:

```bash
llm-hardtest results plan results/submissions \
  --round 1 --pack sha256:<full-pack-fingerprint> \
  --objective accuracy --objective latency \
  --target-bundles 10 --json

llm-hardtest results plan --database results/community.sqlite3 \
  --round 1 --pack sha256:<full-pack-fingerprint> \
  --objective accuracy --objective latency \
  --target-bundles 10 --json
```

Both sources return the same `results/collection-plan-schema-v1.json` response. For
each exact matching configuration, the plan keeps accuracy, completion, latency, and
throughput bundle counts separate and subtracts them from the selected target. Its
minimum-additional total is the maximum objective deficit per configuration, summed
across configurations. This is a lower bound assuming that every new bundle contains
all selected measurements. Partial bundles reduce only the deficits they observe.
Because every descriptive recommendation requires a scored accuracy baseline, the
plan separately reports the five-bundle accuracy prerequisite even when accuracy is
not among the selected target objectives.

The planner uses the accepted bundle—not attempts, model rows, or runs—as the
independent unit. It supports all recommendation constraints, does not reveal bundle
or contributor IDs, makes no network request, and never asks for data about an
unobserved configuration. Pack ambiguity, empty datasets, exact-filter misses, needed
collection, and completed targets have distinct statuses.

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
