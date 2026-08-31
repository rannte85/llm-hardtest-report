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

## Promotion gates

The current repository stops at descriptive observations. A predictive service must
not launch until it has, per target population:

1. enough independent bundles and materially different configurations;
2. cluster-aware uncertainty and held-out temporal validation;
3. abuse, duplicate, and implausible-performance review;
4. calibration-drift monitoring across pack and server versions;
5. an explicit objective and constraint set supplied by the user;
6. a fallback that says evidence is insufficient instead of inventing a winner.

The first database implementation should ingest only validated repository JSON and
retain bundle IDs as provenance. Raw local evidence should remain outside the service.
