# Community Results

This directory contains voluntarily submitted, sanitized benchmark summaries. The
project does not automatically collect telemetry or local campaign data.

- `schema-v1.json` documents legacy aggregate-only public results.
- `schema-v2.json` documents the current item-level, content-free public result shape.
- `submissions/` contains one canonical JSON document per accepted bundle.
- `INDEX.md` is generated from accepted submissions and contains descriptive examples.
- `recommendation-schema-v1.json` documents the deterministic serving-candidate query.
- `pilot-schema-v1.json` documents the sanitized Round 5 summary shape.
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
llm-hardtest results recommend --round 1 --json
llm-hardtest results pilots validate
llm-hardtest results pilots build
llm-hardtest results pilots build --check
```

The index groups only identical public configurations and pack fingerprints. An
observed baseline remains hidden until five distinct comparable bundles with scored
outcomes have been accepted; repeating a model entry inside one bundle cannot meet
that threshold. Schema-v2 submissions also produce item discrimination and stability
diagnostics without publishing prompts or model outputs.

When pair-specific simultaneous inference confirms item directions, the generated
index also shows a compact discriminative panel. Robust item dependencies are selection
penalties, not automatic removal rules, and sparse bundles cannot unlock a panel.

`results recommend` validates the same accepted files, requires one exact pack and
sufficient independent bundles, applies explicit environment constraints and selected
objectives, and emits a non-dominated descriptive candidate set. It does not infer
missing metadata or predict performance on untested hardware.
