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
removing display labels, filesystem keys, public aliases, and routing-only `rounds` and
focused item filters. Round selection changes what is scheduled, not how a shared item
is inferred; model, endpoint, transport, sampling, and other inference settings remain
part of the identity.
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

## Pair-specific item coverage

The pair-specific coverage section directly searches for those specialist items. For
each exact configuration pair and item with at least five independent scored units on
both sides, it computes the cluster-weighted pass-rate difference. It then resamples
whole respondent records rather than independent item cells, preserving correlations
among outcomes from the same attempt or public bundle.

Each bootstrap draw records the largest absolute estimation error across every eligible
item in that configuration pair. The resulting maximum-error critical value produces
simultaneous intervals for the entire item family, rather than a separate uncorrected
95% interval for every row. The overall `0.05` error budget is divided by the number of
eligible configuration pairs with a Bonferroni allocation. Thus the procedure targets
family-wise 95% coverage across both the item scan and configuration-pair scan.

`LEFT_HIGHER` or `RIGHT_HIGHER` requires the simultaneous interval to remain at least
`0.1` away from zero in the observed direction. A pair is `SEPARATING` when at least one
item passes that gate, `UNCERTAIN` when none does, `UNSTABLE` when fewer than 80% of the
2,000 deterministic draws retain every eligible item, and `INSUFFICIENT` when no item
has five units per side. Markdown shows at most 20 decisive splits; JSON retains every
eligible item result and an item-level count of how many configuration pairs it covers.

For community evidence, bundle IDs are sampled once per draw. If one contribution
contains both compared configurations, their outcomes move together. This is an
observed-pack diagnostic, not proof of a general model capability or a prediction for
an untested configuration. Bonferroni plus maximum-error resampling is deliberately
conservative because false specialist discoveries are more damaging than withholding
a plausible but uncertain item.

## Discriminative item panel

Pair-specific evidence may leave many items that reproduce the same confirmed model
direction. Analysis schema v8 includes a compact review panel over those results:

```bash
llm-hardtest analyze runs/campaign-a runs/campaign-b \
  --panel-max-items 8 --output calibration.md
```

The target universe contains one entry for each confirmed direction, such as `C1>C2`.
If one configuration pair has reliable specialist items in both directions, `C1>C2`
and `C2>C1` are separate targets and both must be covered. This preserves
multidimensional strengths instead of forcing one global ordering.

Selection is deterministic greedy directional set cover. At each step it prefers:

1. the item covering the most still-uncovered directions;
2. the item with the fewest robust dependency conflicts with earlier selections;
3. the lower total robust dependency degree among panel candidates;
4. the stronger minimum simultaneous margin and absolute effect; then
5. the stable item ID as a final tie-breaker.

Both `ROBUST_REDUNDANCY_CANDIDATE` and `ROBUST_OPPOSING_CANDIDATE` relationships are
dependency penalties. They do not prohibit selection: an empirically dependent item
is retained when it uniquely covers a confirmed direction. A limit applies separately
to each round/pack group. If the budget ends first, the panel is `PARTIAL` and records
every uncovered direction in JSON and Markdown. With no decisive item it reports
`NO_DECISIVE_ITEMS`; with too little pair evidence it reports `INSUFFICIENT`.

This is a transparent heuristic, not proof of a globally minimum test, a replacement
for task-content review, or authorization to mutate a benchmark pack automatically.
Its selected item IDs can be copied into advanced `item_filters` for a focused follow-up
campaign, but canonical reports should continue to identify that focused selection.

## Focused follow-up configuration

`focus` performs that conversion automatically from the same locally revalidated raw
evidence:

```bash
llm-hardtest focus runs/campaign-a runs/campaign-b \
  --panel-max-items 8 --repetitions 5 --output panel-benchmark.json
```

Only round/pack groups with selected panel items enter the generated campaign. The
command requires one observed fingerprint per selected round and an exact match with
the currently installed bundled pack. It refuses a budget-limited `PARTIAL` panel by
default; `--allow-partial` is an explicit decision to run despite named uncovered
configuration directions.

Exact inference configurations are merged even if their source campaigns scheduled
different rounds or item filters. Distinct inference settings remain distinct, and
colliding filesystem keys receive deterministic numeric suffixes. The generated
`panel_focus` metadata records the analysis schema, selection method, source-run count,
pack fingerprints, selected items, and uncovered targets without source paths or run
names. The rest of the file intentionally preserves the local model configurations
needed to run it, including endpoint URLs and environment-variable names. Treat it as
private configuration, validate and probe it before execution, and use `export --public`
only on completed runs when preparing a sanitized contribution.

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
