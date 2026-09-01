# Community Results

This directory contains voluntarily submitted, sanitized benchmark summaries. The
project does not automatically collect telemetry or local campaign data.

- `schema-v1.json` documents legacy aggregate-only public results.
- `schema-v4.json` documents the current item-level, content-free public result shape,
  including the agent and isolation execution scaffold;
  v1, v2, and v3 remain available for historical bundles.
- `submissions/` contains one canonical JSON document per accepted bundle.
- `INDEX.md` is generated from accepted submissions and contains descriptive examples.
- `recommendation-schema-v3.json` documents the current full-coordinate deterministic
  serving-candidate query; v1 and v2 are retained for historical clients.
- `catalog-schema-v3.json` documents current observed-coordinate discovery; v1 and v2
  are retained for historical clients.
- `collection-plan-schema-v2.json` documents the current independent-bundle
  evidence-gap and acquisition-plan response; v1 is retained for compatibility.
- `paired-comparison-schema-v6.json` documents current cluster-paired head-to-head
  comparison with family-wise simultaneous practical-effect intervals, an adaptive
  bootstrap budget, a discrete sign-flip/Holm resolution audit, and explicit reserved
  objective-family slots; v1–v5 are retained for historical clients.
- `prediction-readiness-schema-v2.json` documents the current non-authorizing
  evidence-design audit required before any predictive serving model is fitted; v1 is
  retained.
- `database-schema-v4.sql` documents the current normalized SQLite observation schema.
  v1, v2, and v3 describe historical generated-database formats; rebuild old databases with
  the current CLI before querying.
- `pilot-schema-v2.json` documents the current sanitized Round 5 summary shape,
  including protocol-abort and stop-reason fields; v1 remains historical.
- `pilots/` contains accepted Round 5 pilot summaries.
- `PILOTS.md` is the separately generated Round 5 community index.

Submitters must preview the exact payload, remove anything they do not want public,
and open a pull request. Submissions are repository contributions under the project
license and remain visible in Git history after merge. See
[`docs/PUBLIC_RESULTS.md`](../docs/PUBLIC_RESULTS.md) for privacy and validation rules.

Maintainers and contributors can reproduce repository checks locally:

```bash
llm-hardtest results validate
llm-hardtest results build
llm-hardtest results build --check
llm-hardtest results database --output results/community.sqlite3
llm-hardtest results database --output results/community.sqlite3 --check
llm-hardtest results recommend --round 1 --json
llm-hardtest results recommend --database results/community.sqlite3 --round 1 --json
llm-hardtest results plan --round 1 --json
llm-hardtest results plan --database results/community.sqlite3 --round 1 --json
llm-hardtest results compare --round 1 \
  --left-configuration 0123456789 --right-configuration abcdef0123 --json
llm-hardtest results compare --database results/community.sqlite3 --round 1 \
  --left-configuration 0123456789 --right-configuration abcdef0123 --json
llm-hardtest results readiness --round 1 --objective accuracy --json
llm-hardtest results readiness --database results/community.sqlite3 \
  --round 1 --objective accuracy --json
llm-hardtest results pilots validate
llm-hardtest results pilots build
llm-hardtest results pilots build --check
```

The index groups only identical public configurations and pack fingerprints. An
observed baseline remains hidden until five distinct comparable bundles with scored
outcomes have been accepted; repeating a model entry inside one bundle cannot meet
that threshold. Schema-v2, schema-v3, and schema-v4 submissions also produce item discrimination
and stability diagnostics without publishing prompts or model outputs.

When pair-specific simultaneous inference confirms item directions, the generated
index also shows a compact discriminative panel. Robust item dependencies are selection
penalties, not automatic removal rules, and sparse bundles cannot unlock a panel.

`results recommend` validates the same accepted files, requires one exact pack and
sufficient independent bundles, applies explicit environment constraints and selected
objectives, and emits a non-dominated descriptive candidate set. It does not infer
missing metadata or predict performance on untested hardware.

`results database` materializes the validated JSON as linked bundle, configuration,
run, item, and task rows. It preserves bundle IDs as uncertainty clusters and emits a
deterministic logical content fingerprint. The generated SQLite file is ignored by Git;
the canonical repository sources remain the reviewed JSON submissions.

`results recommend --database` verifies the standalone database and reproduces the
same bundle-clustered aggregates and candidate result as the JSON path. It emits no
bundle IDs or contributor history. Supplying both a directory and `--database` fails
instead of silently selecting one source.

`results plan` uses the same query and independence rules to show how many complete
new bundles are needed per exact configuration and selected objective. Accuracy,
completion, latency, and throughput counts remain separate; the summed plan is a lower
bound only when each new bundle contains every selected measurement. JSON and database
inputs produce the same response, and no contributor or bundle identity is emitted.

`results compare` uses only bundles containing both requested exact configurations.
Repeated runs collapse within each bundle before paired effects, bootstrap intervals,
and sign-flip tests are calculated. Holm correction covers non-zero tests and a
Bonferroni simultaneous interval covers every non-zero practical-effect claim. The
bootstrap budget scales with the tested family to retain at least 100 expected draws
per adjusted tail. The result also exposes when the exact two-sided p-value grid cannot
reach 0.05 at Holm's strictest rank and reports the conservative additional non-zero
pair floor. Zero-difference pairs cannot manufacture resolution, and the floor is not
a power guarantee. The result contains configuration identities and counts but no
contributing bundle IDs.
When objectives were explored outside the current invocation,
`--multiplicity-family-size` reserves up to four family slots. Holm multipliers,
Bonferroni intervals, bootstrap draws, and resolution diagnostics use the declared
family rather than only emitted objectives, preventing a favorable subset query from
silently weakening correction.

`results readiness` evaluates independent objective coverage, configuration and
serving-environment diversity, paired overlap, and exact model-profile repetition
across environments. Repeated rows cannot inflate any count; every environment bridge
requires five independent bundles. Passing its operator targets still leaves temporal
holdout, abuse/implausibility review, and drift monitoring unresolved, so schema v1
always returns `predictive_service_authorized: false` and never predicts a missing row.
