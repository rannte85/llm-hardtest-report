# Community Data Model and Serving Recommendations

The public format is designed to become a normalized benchmark database without
turning the CLI into hidden telemetry. Test evidence is recorded locally by default;
a sanitized bundle contains all content-free outcomes by default; publishing that
bundle remains an explicit preview-and-submit action.

## Configuration identity

A comparable configuration is the exact combination of:

- public model name, revision, format, quantization, and declared parameter count;
- transport, serving implementation and version;
- Round 4 agent backend, isolation mode, network policy, and fail-closed state;
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
| Item observation | run + attempt + item | status, wall seconds, measured completion tokens |
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
The index additionally assigns each complete contribution bundle to one deterministic
cross-validation fold. It selects a panel from the other fold and checks the selected
directions only on the held-out bundles. Ten bundles are normally required to leave
five independent bundles per configuration on both sides. `REVERSED_SIGNAL` exposes a
direction that fails to replicate; `INSUFFICIENT` is not evidence of stability. Every
evaluable held-out direction also receives a two-sided permutation test and Holm
family-wise correction across both folds.

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

When two exact configurations share contributor bundles, `results compare` can also
apply user-declared minimum practical effects separately to accuracy, completion,
latency seconds, and throughput. Holm controls non-zero tests while Bonferroni
simultaneous paired intervals control non-zero practical-effect claims across every
tested objective. Directions that do not simultaneously clear the declared floor
remain visible as small effects but are not configuration wins. These floors express
the caller's operational decision, not a universal benchmark constant or evidence
about an untested environment.

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

The current machine-readable result follows `results/recommendation-schema-v3.json`. It omits
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

Version 2.18 implemented that boundary with `llm-hardtest results database`. It emits a
normalized SQLite schema with bundle, exact configuration, benchmark-run, item, and
Round 4 task tables; validates every source bundle; and supports read-only staleness and
integrity checking. The database is a reproducible descriptive input, not authorization
to skip the predictive-service promotion gates above. See
[Community Observation Database](COMMUNITY_DATABASE.md).

Version 2.19 adds database schema v2 and direct `results recommend --database` queries.
The database path and canonical-JSON path must produce identical bundle-clustered
aggregates and Pareto results. Standalone reads recompute the logical fingerprint and
revalidate public identities, canonical configuration JSON, flattened coordinates,
numeric domains, and relational links before analysis. This makes the snapshot usable
as a service input while retaining the same descriptive-evidence limits.

Version 2.20 adds `results catalog` over the same aggregate-row boundary. It lets a
human or service discover exact model, server, hardware, format, quantization, transport,
round, and pack values before forming constraints. Per-observation readiness means only
that the existing five-independent-bundle descriptive gate is met; it is not predictive
promotion. Catalog JSON omits bundle and contributor history, reports missing metadata
instead of guessing it, and is identical for canonical JSON and verified SQLite inputs.
The recommender also accepts an exact case-insensitive `--model` constraint.

Version 2.21 closes the remaining query-identity gap. Catalog schema v2 exposes a facet
for every exact configuration coordinate and reports every missing optional parameter
or metadata field. Recommendation schema v2 accepts those same coordinates, including
the stable configuration ID, Python version, all generation parameters, model/server
revisions, and exact hardware/capacity values. Text values compare case-insensitively;
the lowercase configuration ID and numeric values compare exactly. The original three
capacity ceilings remain separate filters. Both adapters still share the same final
filtering implementation and withhold sparse evidence.

Version 2.22 adds the evidence-acquisition step before predictive promotion. The
collection planner accepts the same exact configuration and capacity constraints as
the recommender, keeps observed counts separate for accuracy, completion, latency, and
throughput, and reports each deficit against a target of 5–1000 independent bundles.
The per-configuration maximum deficit is a lower bound on complete new bundles when
each contribution contains all selected measurements. Plans from canonical JSON and a
verified SQLite snapshot are identical. A separate accuracy prerequisite prevents a
set of completion-only bundles from appearing recommendation-ready. Plans reveal no
contributor history and never invent configurations that have not been observed.

Version 2.23 adds paired head-to-head evidence for exact configurations observed in the
same accepted bundles. This removes between-bundle level shifts from each paired effect
instead of comparing only marginal means. Repeated runs collapse inside their bundle;
missing timing or token measurements reduce only the corresponding objective's paired
count. Deterministic cluster bootstrap intervals and two-sided sign-flip tests operate
on the shared bundle differences, with Holm correction across selected objectives.
Directional evidence requires the adjusted test and interval to agree. The result
does not define universal practical importance and cannot extrapolate beyond the exact
pack and configurations.

Version 2.24 makes the predictive-service promotion boundary executable with
`results readiness`. It audits per-objective independent coverage, exact-configuration
diversity, five-bundle paired overlap, declared serving-environment diversity, and
exact model-profile repetition across environments. A profile fixes model identity,
transport, generation parameters, revision, format, quantization, and parameter count;
each participating environment needs five independent bundles. The audit cannot be
unlocked by repeated rows or one-off metadata variants and returns identical results
from canonical JSON and verified SQLite without provenance IDs.

Passing those observable operator targets is reported as
`DESIGN_TARGET_MET_VALIDATION_REQUIRED`, not predictive readiness. Public schema v3
does not contain a trustworthy collection timestamp, automated structural validation
does not replace abuse and implausibility review, and a current snapshot cannot prove
future pack/server drift control. Version 2.24 therefore fixes
`predictive_service_authorized` to false and names every remaining external gate.

Version 2.26 separates observation provenance that earlier versions could conflate.
The top-level environment is now explicitly the runner/client; public schema v3 adds
each model's serving relationship and optional serving OS/architecture. Configuration
identity includes both because client/network placement can affect latency. Legacy v1/v2
bundles normalize to `unreported`, and signed-in Codex defaults to remote with unknown
coordinates. Such observations remain usable for their measured outcomes but do not
count toward readiness environment diversity or portability bridges. Database v3,
catalog/recommendation v3, comparison/collection-plan v2, and readiness v2 expose the
same distinction end to end.

Version 2.36 adds the execution scaffold needed to compare repository-agent results
honestly. Public schema and database schema v4 identify the Round 4 agent backend and
the requested isolation/network boundary. A Codex run, an OpenCode run, and an
optionally fail-closed macOS Seatbelt run therefore receive different configuration
IDs and are never silently pooled. The fields are reproducibility coordinates, not a
claim that operating-system sandboxing is a complete security boundary.
