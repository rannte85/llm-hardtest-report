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

For local analysis, each independently started attempt is an uncertainty cluster. In
community analysis, every accepted public bundle is one cluster regardless of how many
attempts or model rows it contains. Raw observation counts remain visible, while
confidence intervals and robust item decisions use the independent-cluster count.

## Item diagnostics

- **Pass rate** is `PASS / (PASS + FAIL)`.
- **Pass-rate interval** is a bounded Wilson-style 95% interval across independent
  cluster rates and is withheld below five clusters. Raw and cluster-weighted pass
  rates are shown separately when repeated observations make them differ.
- **Difficulty balance** is `4p(1-p)`. It ranges from zero for unanimous outcomes to
  one at a 50% pass rate. Raw and cluster-weighted values are shown. This is a
  normalized balance heuristic, not IRT information.
- **Corrected discrimination** is the Pearson correlation between an item's binary
  score and each respondent's mean score on all other scored items. Removing the item
  from the total avoids part-whole inflation.
- **Clustered corrected discrimination** gives every independent cluster equal total
  weight. Its deterministic bootstrap resamples whole clusters, preserving correlated
  repetitions within a public bundle instead of treating them as new independent data.
- **Signal** flags insufficient samples, observed ceiling/floor effects, undefined
  low-information cases, negative or weak corrected correlation, and useful signal.

Observed signal classifications require at least five scored observations. Five is only an
operational display floor; it is not evidence of statistical precision. Confidence
intervals in this report remain conservative descriptive diagnostics; latent-trait
IRT models, differential-item-functioning claims, and population generalization require
larger, representative samples and a separately reviewed analysis protocol.

Negative discrimination is a review trigger rather than an automatic deletion rule.
It can indicate ambiguity, a grader defect, multidimensional ability, unstable model
behavior, or ordinary small-sample noise.

Robust classification requires at least ten independent clusters and at least 80% of
2,000 bootstrap draws to have defined variance. `ROBUST_USEFUL` requires the entire
clustered discrimination interval to remain at or above 0.15. `ROBUST_NEGATIVE`
requires the entire interval below zero. `ROBUST_CEILING` and `ROBUST_FLOOR` require
both an extreme cluster-weighted pass rate and a cluster interval beyond the 80% boundary.
Everything else remains `UNCERTAIN`, `UNSTABLE`, or `INSUFFICIENT`; point estimates
alone should not cause a benchmark-pack change.

## Item dependency and test diversity

The analyzer also evaluates every scored item pair using the phi correlation of their
binary outcomes. This answers a different question from corrected item-total
discrimination: whether two items repeatedly contribute nearly the same empirical
response pattern.

- Raw phi and outcome agreement treat every respondent row equally.
- Clustered phi and agreement give every local attempt or accepted community bundle
  equal total weight.
- `REDUNDANCY_CANDIDATE` and `OPPOSING_CANDIDATE` are observed point signals at
  correlations of at least `0.8` or at most `-0.8`.
- `ROBUST_REDUNDANCY_CANDIDATE` and `ROBUST_OPPOSING_CANDIDATE` require at least ten
  independent clusters and the complete deterministic 95% bootstrap interval beyond
  the same threshold.
- Relationships with absolute correlation from `0.5` to `0.8` are shown as `RELATED`;
  weaker observed relationships are retained as `DISTINCT` in JSON.

The Markdown report shows at most 20 ranked candidates; the JSON artifact preserves
every pair. A high empirical correlation is not proof of duplicate meaning. It may
reflect a shared capability, prerequisite chain, contamination, grader coupling, or a
narrow sample. Likewise, a strong negative relationship can reveal complementary
skills rather than an error. Always inspect task content and grader behavior before
changing a pack. The thresholds are deliberately conservative descriptive review
gates and do not correct for every possible exploratory comparison.

## Repeat-adjusted item separation

Corrected item-total correlation and dependency analysis do not by themselves show
whether an item separates configurations more than the same configuration fluctuates
between attempts. The repeat-adjusted table addresses that distinction for each item.

For each exact configuration, the analyzer first gives every independent local attempt
or public bundle one item pass-rate value. It then uses only configurations with at
least two independent units to calculate:

- **between-configuration separation**: the equal-weight mean absolute difference
  between configuration pass rates;
- **within-configuration instability**: the equal-weight mean pairwise outcome
  difference across repeated units of the same configuration; and
- **net repeat-adjusted separation**: between separation minus repeat instability.

The observed signal is `SEPARATING` at a net value of at least `0.1`,
`WEAK_SEPARATION` below that threshold, `NOISE_DOMINATED` below zero, and
`NO_SEPARATION` when every eligible configuration and repeat has the same outcome.
Observed labels require at least two repeated configurations.

Robust inference requires at least five independent units for each of at least two
configurations. Local evidence resamples attempts within configurations. Community
evidence resamples the union of bundle IDs once per draw so results from configurations
in the same contribution remain dependent. `ROBUST_SEPARATING` requires the entire
95% interval at or above `0.1`; `ROBUST_NOISE_DOMINATED` requires it below zero; and
`ROBUST_NO_SEPARATION` requires unanimous identical outcomes. Draws missing enough
configuration evidence are discarded, and an interval is withheld as `UNSTABLE` if
fewer than 80% of 2,000 deterministic draws remain valid.

This is still a descriptive result for the observed configurations and pack. It does
not prove a universal item ordering, replace content review, or predict an unseen
model. It is especially useful for retaining specialist items that distinguish a
configuration pair even when they do not align with one overall ability axis.

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
