# Round 5 Cross-Pilot Analysis

`llm-hardtest pilot analyze` compares completed or incomplete Round 5 research
evidence across model configurations and repeated attempts. It remains separate from
the canonical Round 1–4 calibration report because each Round 5 scenario is a
long-horizon incident rather than a bank of independently scored items.

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
effect, or proof of general model quality. No score prediction for an untested model
is statistically supported.

## Cross-scenario portfolio

Analysis schema 6 includes the schema-5 portfolio and acquisition plan per exact
inference configuration.
It shows:

- which required q32–q41 scenarios were observed and which remain missing;
- whether one scenario ID was mixed across multiple fingerprints;
- attempts and transport-complete attempts;
- scenario-weighted mean public, held-back, and release-ready rates;
- the worst observed held-back rate as a failure-envelope indicator;
- authority and tool-protocol failures;
- pairwise configuration distance over exact shared `(pilot_id, fingerprint)` pairs;
- repeat-adjusted separation, a deterministic scenario-bootstrap interval, conservative
  evidence status, and the highest-priority next evidence action;
- per-axis attribution and leave-one-scenario-out robustness for stable results.

Missing scenarios remain missing and are never imputed as zero or success. A scenario
with more repeated attempts does not receive more weight in the displayed means. The
portfolio is a coverage and failure-envelope view, not a composite benchmark score.
`canonical_score` remains false.

For each exact shared scenario version, the analyzer averages every cross-configuration
attempt distance, averages within-configuration attempt distances on both sides, and
subtracts that repeat noise from the between-configuration distance. It then resamples
the scenario-level adjusted effects—not individual attempts or vector axes—5,000 times
with a fixed seed to produce a reproducible 95% percentile interval.

Inference requires at least three exact shared scenario versions, one version per shared
pilot, two transport-complete attempts per side/version, complete transport for every
shared attempt, and no pre-approval edit violation. If any gate fails, the status is
`INSUFFICIENT_EVIDENCE`. Otherwise, the interval is `STABLE_SEPARATION` only when its
lower bound exceeds the five-percentage-point minimum effect, `NO_STABLE_SEPARATION`
when its upper bound does not exceed that threshold, and `INCONCLUSIVE` when it crosses
the threshold. These labels are conservative descriptive evidence, not a significance
test, causal estimate, model prediction, leaderboard score, or automatic promotion.

## Directional observed-configuration contrast

Unsigned distance answers whether two configurations behave differently. Schema 6
separately asks which observed configuration had the better outcome over exact shared
scenario versions. All eight axes are defined as higher-is-better. For every attempt,
the analyzer takes their equal-weight mean only when all axes are observed, averages
repeats within each configuration/scenario cell, and defines the scenario effect as
`left - right`.

The deterministic hierarchical bootstrap resamples whole scenarios and then resamples
attempts within both sides of every selected scenario. Repeats therefore contribute
uncertainty without pretending to be independent incidents. The directional result
uses the same minimum three exact shared scenarios, two complete attempts per side,
complete transport, authority safety, fingerprint alignment, and full-axis gates as
repeat-adjusted separation.

The 95% interval must lie above +5 percentage points for
`STABLE_LEFT_ADVANTAGE` or below -5 points for `STABLE_RIGHT_ADVANTAGE`. An interval
fully inside the ±5-point equivalence band is `NO_MATERIAL_ADVANTAGE`; an interval that
crosses a boundary is `INCONCLUSIVE`. Failed gates yield `INSUFFICIENT_EVIDENCE` and no
favored configuration. A stable direction also receives the same single-scenario
removal audit, and signed per-axis rows show which observed capabilities favor each
side.

This contrast compares only the two anonymous configurations and observed scenarios.
It is not a significance test, population claim, causal effect, prediction for an
untested model, global ranking, or permission to promote a pilot.

The machine and Markdown reports also prioritize the next acquisition step: align mixed
or mismatched versions, collect missing scenarios, add repeat attempts, replace invalid
attempts or unobserved axes, replicate influential or noisy scenarios, or proceed to
manual ambiguity review. Missing observations are never synthesized.

For a pairwise summary, exact-version alignment is always first. Invalid shared history
then takes priority over unrelated missing scenarios because appending attempts cannot
repair its all-attempts gates; the report requests a fresh clean cohort. Missing
scenarios, ordinary repeat deficits, and unobserved axes follow in that order. The
detailed portfolio planner independently exposes every outstanding action and count.

## Evidence collection plan

Schema 5 and later add a finite lower-bound acquisition plan to every portfolio. For
each exact configuration and required pilot, it distinguishes `READY`, `MISSING`,
`REPEAT_DEFICIT`, `PACK_AMBIGUOUS`, and `FRESH_COHORT_REQUIRED`. The JSON and Markdown
outputs report the number of additional complete attempts needed for every actionable
configuration/pilot cell, then sum those counts by configuration and portfolio.

Priorities favor the largest attainable exact pair-coverage gain per additional
attempt. If `r` of `n` configurations are ready for a scenario, current pair coverage
is `r(r-1)/2`, target coverage is `n(n-1)/2`, and the difference is the potential pair
gain. That gain divided by the required additional attempts is the displayed planning
efficiency. This is an acquisition heuristic, not a model-quality score or permission
to run models.

A mixed fingerprint—within one configuration or across configurations—has no honest
numeric completion estimate until one version is selected, so its attempt count
remains unavailable and manual alignment comes first.
Likewise, an incomplete or pre-approval-invalid attempt permanently keeps the source
run's `all_attempts_*` gate false. The planner therefore emits
`RECOLLECT_CLEAN_COHORT` and requires two new complete authority-safe attempts in run
directories excluded from that invalid historical cohort. Appending good attempts to
the invalid directory is explicitly not presented as a repair.

All counts assume future attempts complete transport, respect authority, expose every
axis, and use the exact current fingerprint. Re-run `pilot analyze` after collection;
new failures, version changes, or configuration changes can alter the plan.

## Attribution and single-scenario robustness

For each outcome axis, schema 4 and later report scenario-weighted between-configuration
distance, within-configuration repeat noise, their difference, and the share of positive
adjusted separation. The shares sum to one when positive signal exists. This
decomposition remains unsigned and explains where configurations differ. The separate
schema-6 directional contrast uses signed higher-is-better differences and must pass
its stricter evidence and material-effect decision before naming an observed favored
configuration. Aggregate distance still weights all comparable axes equally.
Contribution shares remain unavailable until both sides have enough repeats to estimate
per-axis repeat noise; an unavailable share is never rendered as zero evidence.

When a fully eligible comparison is `STABLE_SEPARATION` and has at least four exact
shared scenarios, the analyzer removes each scenario in turn and reruns the same
scenario-bootstrap decision on the remainder. `ROBUST_TO_SINGLE_SCENARIO_REMOVAL` means
every omission stays stable. `SENSITIVE_TO_SINGLE_SCENARIO` lists each omission that
breaks stability and changes the next action to `REPLICATE_INFLUENTIAL_SCENARIOS`.
Three scenarios can establish the primary status but cannot support this omission audit,
so robustness remains `INSUFFICIENT_SCENARIOS`. Non-stable or ineligible comparisons are
`NOT_APPLICABLE`. These checks do not turn four incidents into population-level proof.

Inferential gates also require all eight axes to be observed for every shared attempt.
An absent public or held-back denominator remains missing rather than being silently
reweighted against configurations with complete outcome vectors.

## Automatic evidence gates

The report marks a group ready for manual ambiguity review only when it has:

- at least two materially different model configurations;
- at least two transport-complete attempts per configuration;
- no incomplete attempt;
- no pre-approval authority violation.

Passing these gates never promotes Round 5 automatically. Manual review of grader
ambiguity, runtime variance, transcript quality, and task contamination remains
required. `canonical_promotion_ready` therefore remains false in research reports.

A configuration portfolio is ready for cross-scenario interpretation only when all
required scenarios are present at one fingerprint each, every scenario has at least
two transport-complete attempts, every attempt completed transport, and no attempt
violated the pre-approval edit boundary. Product failure and protocol errors remain
visible outcomes; they do not disappear behind the coverage gate.

## Integrity and privacy

Before calculation, the analyzer:

- rejects a duplicate input directory;
- validates the pilot ID and exact scenario fingerprint for current schema-2 runs;
- rejects unsafe model keys and evidence symlinks escaping the run directory;
- requires the run summary and raw grade to match exactly;
- recomputes transport completion and release readiness from lower-level evidence;
- rescans bounded-size transcripts for unsupported tool calls;
- recomputes incomplete-attempt stop reasons and requires at least three transcript
  errors for a claimed `unsupported_tool_loop` abort;
- rejects contradictory or malformed status, timing, token, score, and sandbox data.

Configuration tables separately report protocol-error calls and circuit-breaker
aborts. A single recoverable error therefore remains visible without being confused
with an automatically terminated runaway turn.

Scenario fingerprints cover only that task's contract, verifier, candidate repository,
and held-back grader assets. Adding a new scenario therefore does not relabel unchanged
q32–q37 evidence. Schema-1 legacy summaries remain readable but retain their historical
opaque pack identity; exact-version grouping still prevents them from being silently
pooled with current evidence. Analyze schema-2 evidence with the matching installed
release so its asset fingerprint can be verified.

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
