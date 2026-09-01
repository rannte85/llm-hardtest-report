# Community Observation Database

`llm-hardtest results database` turns the accepted public result directory into a
normalized SQLite database. It is an explicit repository-maintainer operation, not a
telemetry collector: the command reads only canonical JSON already present in the
selected submissions directory and performs no network request.

```bash
llm-hardtest results database results/submissions \
  --output results/community.sqlite3

# Fail if the database is missing, corrupt, modified, or stale relative to JSON:
llm-hardtest results database results/submissions \
  --output results/community.sqlite3 --check
```

The generated file uses database schema v4, SQLite `user_version=4`, and application
ID `0x4c484452` (`LHDR`). Its logical DDL is published in
[`results/database-schema-v4.sql`](../results/database-schema-v4.sql). Rebuild older
files from canonical JSON with the current CLI; public bundle schemas v1/v2 remain
accepted and normalize to an explicitly unreported serving environment.
Because v3 configuration hashes include that explicit serving marker and runner
identity separately, configuration IDs from a v2 database are not stable migration
keys. Rediscover them with `results catalog` after rebuilding.

## Tables and independence

| Table | Unit | Important relationship |
|---|---|---|
| `bundles` | accepted public contribution | independent uncertainty cluster |
| `configurations` | exact model, server, generation, and environment identity | reused only when every identity field matches |
| `benchmark_runs` | bundle × model row × round × pack | retains `bundle_id`; repeated rows do not become new bundles |
| `item_observations` | run × item × attempt | content-free status, time, and completion tokens |
| `task_observations` | Round 4 run × task row | content-free public/hidden counts and release/safety flags |
| `dataset_metadata` | one database | schema identity, row counts, and logical content fingerprint |

`configuration_id` is the same deterministic identity used by community aggregation.
It covers the public model name, transport, generation parameters, serving metadata,
runner OS/architecture/Python, and explicit serving scope/OS/architecture. `run_id` and
observation IDs are full SHA-256
identities. The model ordinal is intentionally retained: duplicate configuration rows
remain auditable observations, while their common `bundle_id` prevents downstream
analysis from counting them as independent submissions.

Round 1–3 `scored_passed`/`scored_total` map to pass and scored-item totals. Round 4
maps them to release-ready and attempt totals. `metrics_json` preserves every other
allowlisted aggregate metric without copying item or task arrays. Parameter and serving
objects are available both as canonical JSON and as indexed/queryable scalar columns.

## Integrity and reproducibility

The builder validates each filename, content-derived bundle ID, schema, aggregate/item
consistency, safe-text boundary, and privacy declaration before opening the database.
Submission directories and entries must be real filesystem objects, not symlinks.
It writes to a temporary sibling file, validates SQLite integrity and foreign keys, and
atomically replaces the requested output only after success.

`--check` opens the existing file read-only and verifies:

- SQLite integrity and all foreign keys;
- application and schema version identifiers;
- the single metadata row and deterministic SHA-256 content fingerprint; and
- every normalized row against freshly validated repository JSON.

Schema v2 normalizes every `REAL` value before hashing, so SQLite's equivalent `8` to
`8.0` storage conversion cannot invalidate an otherwise identical dataset. The content
fingerprint is deterministic and independently recomputable from database rows. SQLite
file bytes are an implementation artifact and should not be used as the dataset identity.

Standalone reads additionally revalidate canonical parameter/metadata JSON, their
flattened columns, safe public text, configuration/run/observation IDs, pack IDs,
environment consistency, numeric domains, item statuses, and task boolean/null values.
Updating both a bad row and its fingerprint therefore does not bypass semantic checks.
The fingerprint is not a signature. A fully regenerated, semantically valid database
can describe different evidence, so deployments that claim repository provenance must
also run `results database ... --check` against the reviewed canonical JSON or pin a
separately authenticated database digest.

## Privacy boundary

The database has no columns for prompts, expected answers, responses, transcripts,
patches, error text, endpoints, credentials, environment-variable names, usernames,
local paths, run IDs, private labels, or timestamps. It cannot ingest raw local run
directories. Those data remain local unless a user separately previews and submits a
sanitized public bundle.

Bundle IDs and tool versions are retained as public provenance. A merged contribution
is already public in Git history, so deleting a generated SQLite file does not retract
its source JSON.

## Example queries

Count independent bundles rather than repeated runs:

```sql
SELECT c.public_name, c.server, c.quantization,
       COUNT(DISTINCT r.bundle_id) AS independent_bundles
FROM benchmark_runs AS r
JOIN configurations AS c USING (configuration_id)
WHERE r.round = 1 AND r.pack = 'sha256:<exact-pack-fingerprint>'
GROUP BY r.configuration_id
ORDER BY independent_bundles DESC, c.public_name;
```

Inspect pass rates without turning incomplete or invalid items into failures:

```sql
SELECT c.public_name,
       SUM(i.status = 'PASS') AS passed,
       SUM(i.status IN ('PASS', 'FAIL')) AS scored
FROM item_observations AS i
JOIN benchmark_runs AS r USING (run_id)
JOIN configurations AS c USING (configuration_id)
GROUP BY r.configuration_id;
```

These queries are descriptive. A serving service must still use bundle-clustered
uncertainty, exact pack filters, held-out validation, drift and abuse review, explicit
user constraints, and an insufficient-evidence outcome before making predictions.

## Discoverable serving space

Before constructing a candidate query, inspect the exact values and evidence currently
available in the verified snapshot:

```bash
llm-hardtest results catalog \
  --database results/community.sqlite3 \
  --round 1 --json
```

The response follows [`results/catalog-schema-v3.json`](../results/catalog-schema-v3.json)
and exposes every public configuration coordinate, round/pack observations, independent-
bundle counts, conservative metrics, objective-readiness flags, text/numeric facets,
and missing-coordinate counts. It omits bundle IDs and contributor/tool history. Its JSON is identical
to a catalog built directly from the canonical submissions directory. `EMPTY` and
`NO_MATCH` remain distinct so a service can distinguish an unpopulated source from an
unsupported filter.

## Direct candidate query

The existing gated Pareto recommender can read the verified database directly:

```bash
llm-hardtest results recommend \
  --database results/community.sqlite3 \
  --round 1 \
  --pack sha256:<exact-pack-fingerprint> \
  --configuration 0123456789 \
  --model "org/model" \
  --server-version "1.2.3" \
  --context-window 32768 \
  --accelerator "Example GPU" \
  --max-memory-gb 24 \
  --objective accuracy --objective latency --json
```

The database and canonical-JSON paths share one final recommendation implementation.
They produce identical aggregate rows and machine-readable results for identical
evidence. The response still omits bundle IDs and contributor history. Passing both a
submission directory and `--database` is an error.

Recommendation schema v3 accepts an exact filter for every configuration-table
coordinate. Text comparisons are case-insensitive except the lowercase stable
configuration ID; numeric settings compare by value, so SQLite's `8`/`8.0` affinity is
not a false mismatch. Capacity ceilings remain distinct from exact memory and model-size
filters. Missing coordinates never match.

## Paired configuration comparison

Use shared bundle clusters to compare two exact configurations without treating
different contributor populations as interchangeable:

```bash
llm-hardtest results compare \
  --database results/community.sqlite3 \
  --round 1 --pack sha256:<exact-pack-fingerprint> \
  --left-configuration 0123456789 \
  --right-configuration abcdef0123 \
  --objective accuracy --objective latency \
  --minimum-accuracy-effect 0.05 \
  --minimum-latency-effect-seconds 0.5 --json
```

The response uses Holm-adjusted paired sign-flip tests for non-zero evidence and
Bonferroni simultaneous bootstrap intervals for non-zero practical-effect floors.
Its deterministic bootstrap budget scales with the number of tested objectives so
each adjusted tail retains at least 100 expected draws.
The same response audits the discrete sign-flip grid. It discloses a conservative
effect tolerance aligned with the test's numerical tolerance, reports the best exact
raw p-value supported by pairs beyond it, applies the strictest Holm multiplier,
and gives a conservative additional non-zero pair floor when that adjusted value
cannot reach 0.05. Zero-difference pairs do not improve this resolution, and the floor
is not a statistical-power promise.
The optional `--multiplicity-family-size` applies identically to JSON and verified
SQLite. It reserves unreported or previously explored objective slots in the Holm and
Bonferroni family, so querying a favorable subset cannot silently reclaim a smaller
correction. The value must cover every selected objective and may not exceed four.

The database adapter first collapses repeated runs to one metric value per bundle and
configuration, then retains only shared bundles for each selected objective. It feeds
the same paired bootstrap, sign-flip, and Holm implementation as canonical JSON, so
identical evidence and minimum-effect floors produce byte-identical output. A direction
is promoted at a non-zero floor only when its simultaneous interval clears the declared
objective-specific floor; a Holm-controlled direction below that floor remains visible
as a small effect. Standalone database integrity and semantic checks run before
analysis. The response exposes neither pairing bundle IDs nor contributor history.

## Predictive-service readiness audit

```bash
llm-hardtest results readiness \
  --database results/community.sqlite3 \
  --round 1 --pack sha256:<full-pack-fingerprint> \
  --objective accuracy --objective latency --target-bundles 10 --json
```

The database adapter reuses the same collapsed bundle/configuration observations as
paired comparison. It counts each bundle once per objective, requires five independent
bundles on both sides of a paired edge, and requires five bundles per attested serving
environment for an exact model-profile portability bridge. Client coordinates and
remote/unreported hosts without both serving OS and architecture are excluded from
environment diversity and bridges. Canonical files and a verified SQLite
snapshot return identical JSON. The response exposes configuration and environment
coordinates but no bundle IDs or contributor history.

This audit is a data-design check, not a fitted predictor. Even when observable targets
pass, temporal validation, human abuse/implausibility review, and future drift
monitoring remain external required gates and authorization stays false.

## Plan evidence acquisition

The verified database can also answer which exact configurations need more independent
complete bundles before a selected evidence target is met:

```bash
llm-hardtest results plan \
  --database results/community.sqlite3 \
  --round 1 --pack sha256:<exact-pack-fingerprint> \
  --objective accuracy --objective throughput \
  --target-bundles 10 --json
```

The same command against canonical JSON produces an identical response. It counts
accuracy, completion, latency, and throughput independently, because item timing or
token data may be absent even when a score exists. Per configuration, the largest
selected-objective deficit is the minimum number of additional complete bundles; the
summary adds those lower bounds. The planner reads the already-verified snapshot,
and separately enforces the recommender's five-scored-bundle accuracy prerequisite.
It emits no bundle IDs and does not alter either the database or source submissions.
