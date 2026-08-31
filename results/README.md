# Community Results

This directory contains voluntarily submitted, sanitized benchmark summaries. The
project does not automatically collect telemetry or local campaign data.

- `schema-v1.json` documents the public result shape.
- `submissions/` contains one canonical JSON document per accepted bundle.
- `INDEX.md` is generated from accepted submissions and contains descriptive examples.

Submitters must preview the exact payload, remove anything they do not want public,
and open a pull request. Submissions are repository contributions under the project
license and remain visible in Git history after merge. See
[`docs/PUBLIC_RESULTS.md`](../docs/PUBLIC_RESULTS.md) for privacy and validation rules.

Maintainers and contributors can reproduce repository checks locally:

```bash
llm-hardtest results validate
llm-hardtest results build
llm-hardtest results build --check
```

The index groups only identical public configurations and pack fingerprints. An
observed baseline remains hidden until five comparable runs have been accepted.
