# Community Data Model and Serving Recommendations

The public format is designed to become a normalized benchmark database without
turning the CLI into hidden telemetry. Test evidence is recorded locally by default;
a sanitized bundle contains all content-free outcomes by default; publishing that
bundle remains an explicit preview-and-submit action.

## Configuration identity

A comparable configuration is the exact combination of:

- public model name, revision, format, quantization, and declared parameter count;
- transport, serving implementation and version;
- reasoning effort, context window, output limit, and sampling parameters;
- OS family, architecture, accelerator description/count, and declared memory;
- benchmark round and immutable pack fingerprint.

Changing any field creates a different configuration ID. Missing metadata is not
guessed, and records with different IDs are not silently pooled.

## Normalized records

Repository JSON maps directly to five logical tables:

| Entity | Stable key | Important fields |
|---|---|---|
| Bundle | content-derived bundle ID | schema/tool version, environment, consent declaration |
| Configuration | configuration ID | model, serving, hardware, generation settings |
| Benchmark run | bundle + configuration + round + pack | aggregate status counts and bundle-level rates |
| Item observation | run + attempt + item | status, wall seconds, completion tokens |
| Pilot attempt | bundle + configuration + pilot + attempt | authority, revision, tests, release, report, protocol |

Prompts, responses, transcripts, patches, error messages, endpoint URLs, credentials,
usernames, local paths, timestamps, and private labels have no column in this model.

Statistical views must retain the bundle key as the uncertainty cluster. Item-level
rows may be numerous, but one bundle contributes one total cluster weight to robust
pass-rate and discrimination intervals. Raw observation-weighted estimates are kept
for auditability and displayed separately when they disagree with bundle weighting.
The same rule applies to item dependency diagnostics: repeated rows in one submission
cannot manufacture a robust redundancy signal. Pairwise phi relationships are stored
as review evidence, not as instructions to delete or merge benchmark items.
Repeat-adjusted item analysis also retains the bundle key. When a bundle reports more
than one configuration, bootstrap draws resample that bundle once and preserve all of
its configuration outcomes together. This prevents shared runtime or contributor
effects from being treated as unrelated evidence.
Pair-specific item coverage uses the same bundle records, computes configuration-pair
pass-rate effects only after five observed bundles per side, and applies simultaneous
item-family intervals plus a configuration-pair Bonferroni allocation. These rows are
evidence about exact submitted configurations, not recommendations by themselves.
The community discriminative panel operates only on those already-decisive rows. It
covers each observed configuration direction with a compact item set and uses robust
bundle-clustered dependency signals as tie-breaking penalties. Repeated rows in one
bundle therefore cannot create either a directional target or a dependency shortcut.
The panel is a review aid, not an automatic benchmark rewrite.

## What can be recommended

With enough representative bundles, a service can filter to a user's hardware and
serving constraints, then compare only compatible configurations on multiple axes:

- task accuracy and completion probability;
- release-ready probability for repository-agent work;
- item-level coverage and benchmark discrimination;
- repeat instability and configuration separation;
- median and tail item latency;
- observed completion tokens per second;
- context, memory, and model-size constraints declared by submitters.

The response should be a Pareto set rather than one universal winner—for example,
"highest observed release readiness under 24 GB", "lowest latency above an accuracy
floor", or "most stable configuration for this task mix". Every recommendation must
show the exact population filter, pack version, sample size, interval, and missing
metadata.

Version 2.13 provides the first read-only form of this interface:

```bash
llm-hardtest results recommend results/submissions \
  --round 1 \
  --pack sha256:<full-pack-fingerprint> \
  --max-memory-gb 24 \
  --accuracy-floor 0.60 \
  --objective accuracy --objective latency
```

The query validates every repository bundle, filters exact public configuration
records, requires at least five independent bundles for each selected metric, and
returns only non-dominated configurations. Accuracy and completion use their
bundle-cluster interval lower bounds. Latency is the p90 across bundle-level mean item
latencies; throughput is the p50 across bundle-level mean item token rates. Sparse
performance observations are not promoted merely because accuracy has enough data.

The machine-readable result follows `results/recommendation-schema-v1.json`. It omits
bundle IDs and contributor history, retains only public configuration coordinates,
and has explicit `PACK_REQUIRED`, `NO_MATCH`, `INSUFFICIENT_EVIDENCE`,
`SINGLE_ELIGIBLE_CONFIGURATION`, and `DESCRIPTIVE_CANDIDATES` states. A declared
memory ceiling is only an observational filter over tested environments. It is not a
model memory requirement or evidence of portability to another accelerator.

## Promotion gates

The current repository stops at descriptive candidate queries. A predictive service
must not launch until it has, per target population:

1. enough independent bundles and materially different configurations;
2. cluster-aware uncertainty and held-out temporal validation;
3. abuse, duplicate, and implausible-performance review;
4. calibration-drift monitoring across pack and server versions;
5. an explicit objective and constraint set supplied by the user;
6. a fallback that says evidence is insufficient instead of inventing a winner.

The first database implementation should ingest only validated repository JSON and
retain bundle IDs as provenance. Raw local evidence should remain outside the service.
