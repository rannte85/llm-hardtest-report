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
intervals, latent-trait IRT models, and differential-item-functioning claims require
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

## Recommended calibration design

Use at least two materially different model families and multiple independent
attempts per configuration. Keep the prompt, pack fingerprint, generation settings,
tool policy, and grader fixed. Investigate ceiling, floor, negative-signal, high
incompletion, and high-invalid items before using aggregate scores to claim model
separation. Round 5 promotion still requires its task-specific controls and manual
grader-ambiguity review in addition to these diagnostics.
