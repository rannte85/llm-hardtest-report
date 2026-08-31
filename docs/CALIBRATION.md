# Calibration and Discrimination Analysis

`llm-hardtest analyze` reads completed local run evidence and produces status-only
Markdown and JSON diagnostics. It does not call a model or copy prompts, responses,
paths, model identifiers, endpoint URLs, or credentials into either output.

```bash
llm-hardtest analyze runs/campaign-a runs/campaign-b --output calibration.md
```

The command requires each run to contain both `config.json` and `summary.json`.
Evidence from different benchmark pack fingerprints is never pooled. Passing the
same resolved run directory twice is rejected, and evidence symlinks may not escape
their run directory.

## Observation unit

For Rounds 1–3, one respondent is one model-configuration attempt across that round's
items. For Round 4, one respondent is one coding-agent attempt across repository
tasks. Only `PASS` and `FAIL` enter correctness and correlation calculations.
`INCOMPLETE`, `REVIEW`, `INVALID`, and missing observations retain separate counts.

A configuration identity is a one-way hash of the saved model configuration after
removing display labels, filesystem keys, public aliases, and focused item filters.
The hash is used only for equality tests and is not emitted in the analysis.

## Item diagnostics

- **Pass rate** is `PASS / (PASS + FAIL)`.
- **Difficulty balance** is `4p(1-p)`. It ranges from zero for unanimous outcomes to
  one at a 50% pass rate. This is a normalized balance heuristic, not IRT information.
- **Corrected discrimination** is the Pearson correlation between an item's binary
  score and each respondent's mean score on all other scored items. Removing the item
  from the total avoids part-whole inflation.
- **Signal** flags insufficient samples, observed ceiling/floor effects, undefined
  low-information cases, negative or weak corrected correlation, and useful signal.

Signal classifications require at least five scored observations. Five is only an
operational display floor; it is not evidence of statistical precision. Confidence
intervals in this report remain conservative descriptive diagnostics; latent-trait
IRT models, differential-item-functioning claims, and population generalization require
larger, representative samples and a separately reviewed analysis protocol.

Negative discrimination is a review trigger rather than an automatic deletion rule.
It can indicate ambiguity, a grader defect, multidimensional ability, unstable model
behavior, or ordinary small-sample noise.

## Configuration separation and repeat stability

For every respondent pair sharing at least two scored items, the analyzer measures
the fraction with different outcomes. It reports pair-weighted means separately for:

- different saved model configurations; and
- repeated attempts of the same saved model configuration.

When both exist, net separation is between-configuration disagreement minus
within-configuration disagreement. A large raw configuration difference is less
useful if the same configuration is similarly unstable across repeats. These metrics
are descriptive and do not predict an untested model.

## Configuration scorecards and directional comparisons

Each exact private configuration receives an alias (`C1`, `C2`, and so on) based on
its first appearance in the supplied run/config order. The report includes source
coordinates such as `r2/m1`, so the operator can map an alias back to the second input
run's first model without copying the model name, endpoint, path, or credentials into
the analysis artifact.

The scorecard averages one pass rate per scored respondent rather than treating every
item as an independent sample. Its 95% interval is withheld below five scored
respondents. At or above that gate, a bounded Wilson-style interval across respondent
rates avoids presenting five unanimous attempts as perfect certainty.

For every configuration pair, the analyzer computes per-item pass-rate differences on
commonly scored items. It reports the mean effect and item win/loss/tie counts. The
directional test is deliberately conservative:

1. both configurations need at least five scored respondents;
2. they need at least five commonly scored items;
3. a two-sided exact sign test measures consistent direction across items;
4. Holm correction controls family-wise error across all eligible pairs; and
5. a deterministic hierarchical bootstrap resamples both respondents and common
   items, so observed repeat instability widens the effect interval.

`LEFT_HIGHER` or `RIGHT_HIGHER` is emitted only when the adjusted p-value is below
0.05 and the bootstrap interval excludes zero in the same direction. Otherwise the
result is `UNCERTAIN` or `INSUFFICIENT`. This is evidence about the observed benchmark
pack and configurations, not a universal model ranking. Related items are not fully
independent, so even a directional result must be reported with its item set, effect,
interval, respondent count, and contamination limits rather than as a bare p-value.

## Recommended calibration design

Use at least two materially different model families and multiple independent
attempts per configuration. Keep the prompt, pack fingerprint, generation settings,
tool policy, and grader fixed. Investigate ceiling, floor, negative-signal, high
incompletion, and high-invalid items before using aggregate scores to claim model
separation. Round 5 promotion still requires its task-specific controls and manual
grader-ambiguity review in addition to these diagnostics.
