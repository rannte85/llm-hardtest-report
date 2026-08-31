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

The generated file uses database schema v1, SQLite `user_version=1`, and application
ID `0x4c484452` (`LHDR`). Its logical DDL is published in
[`results/database-schema-v1.sql`](../results/database-schema-v1.sql).

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
OS, architecture, and Python version. `run_id` and observation IDs are full SHA-256
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

The content fingerprint is deterministic across machines. SQLite file bytes are an
implementation artifact and should not be used as the dataset identity.

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
