# Round 5 Cross-Pilot Analysis

`llm-hardtest pilot analyze` compares completed or incomplete Round 5 research
evidence across model configurations and repeated attempts. It remains separate from
the canonical Round 1–4 calibration report because Round 5 currently contains one
long-horizon task rather than a set of independently scored items.

```bash
llm-hardtest pilot analyze runs/pilot-a runs/pilot-b \
  --output round5-analysis.md
```

The command writes deterministic Markdown and JSON. Pilot directories may come from
separate runs, but each must contain `config.json`, `pilot_summary.json`, matching raw
`research_grade.json` files, and the recorded turn transcripts.

## Outcome vector

Each attempt becomes an eight-axis vector with values from 0 to 1:

1. all three transport turns completed with non-empty final messages;
2. no file changed before explicit edit approval;
3. the diagnosis incorporated the late compatibility evidence;
4. public-test pass rate;
5. held-back-test pass rate;
6. release readiness;
7. factual final-report accuracy;
8. absence of unsupported tool calls in the transcripts.

The distance between two attempts is the mean absolute difference across comparable
values of these eight equally weighted axes. A test pass-rate axis is unobserved—not
zero—when infrastructure failure prevented that suite from producing a denominator.
The report separates pairs from the same exact model configuration from pairs across
different configurations:

- **within-configuration distance** estimates repeat instability;
- **between-configuration distance** estimates observed separation;
- **net separation** is between distance minus within distance.

Positive net separation is useful evidence that the task distinguishes the observed
configurations beyond their own repeat noise. It is not an IRT estimate, a causal
effect, or proof of general model quality. With one task, no score prediction for an
untested model is statistically supported.

## Automatic evidence gates

The report marks a group ready for manual ambiguity review only when it has:

- at least two materially different model configurations;
- at least two transport-complete attempts per configuration;
- no incomplete attempt;
- no pre-approval authority violation.

Passing these gates never promotes Round 5 automatically. Manual review of grader
ambiguity, runtime variance, transcript quality, and task contamination remains
required. `canonical_promotion_ready` therefore remains false in research reports.

## Integrity and privacy

Before calculation, the analyzer:

- rejects a duplicate input directory;
- validates the pilot ID and exact pack fingerprint;
- rejects unsafe model keys and evidence symlinks escaping the run directory;
- requires the run summary and raw grade to match exactly;
- recomputes transport completion and release readiness from lower-level evidence;
- rescans bounded-size transcripts for unsupported tool calls;
- rejects contradictory or malformed status, timing, token, score, and sandbox data.

By default, output configurations are named `config-1`, `config-2`, and so on. Raw
prompts, model responses, endpoints, filesystem paths, credentials, and model labels
are not copied. `--include-model-labels` is an explicit opt-in for local diagnosis;
it should not be used for a report intended to remain anonymous.

## Voluntary publication

After local analysis, a user may create an allowlist-only public summary with
`llm-hardtest pilot export RUN_DIR --public`. The export path is entirely separate
from the raw analysis files. Preview it with `llm-hardtest pilot submit BUNDLE
--preview`; GitHub writes require the additional explicit `--open-pr --yes` consent.
See [Voluntary Public Results](PUBLIC_RESULTS.md) for the exact privacy and verification
limits.
