from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from collections import defaultdict
from itertools import combinations
from pathlib import Path

from .common import load_json, slug
from .results import item_status


SCORED = {"PASS", "FAIL"}
MIN_ITEM_OBSERVATIONS = 5
MIN_ITEM_INTERVAL_OBSERVATIONS = 10
MIN_PAIR_ITEMS = 2
MIN_COMPARISON_ITEMS = 5
MIN_CONFIGURATION_RESPONDENTS = 5
BOOTSTRAP_SAMPLES = 2_000
ITEM_RELATIONSHIP_THRESHOLD = 0.5
ITEM_REDUNDANCY_THRESHOLD = 0.8
ITEM_NET_SEPARATION_THRESHOLD = 0.1
ITEM_PAIR_EFFECT_THRESHOLD = 0.1
HOLDOUT_EXACT_PERMUTATION_LIMIT = 100_000
HOLDOUT_MONTE_CARLO_SAMPLES = 20_000


class _HashSampler:
    """Cross-version deterministic sampler backed only by SHA-256."""

    def __init__(self, seed: str):
        self.seed = hashlib.sha256(seed.encode("utf-8")).digest()
        self.counter = 0

    def choice(self, values: list):
        if not values:
            raise ValueError("cannot sample an empty collection")
        block = hashlib.sha256(
            self.seed + self.counter.to_bytes(16, "big")).digest()
        self.counter += 1
        return values[int.from_bytes(block, "big") % len(values)]


def _bounded_rate_interval(values: list[float], minimum: int, method: str) -> dict | None:
    if len(values) < minimum:
        return None
    z = 1.96
    sample_size = len(values)
    estimate = statistics.mean(values)
    denominator = 1 + z ** 2 / sample_size
    center = (estimate + z ** 2 / (2 * sample_size)) / denominator
    margin = z / denominator * math.sqrt(
        estimate * (1 - estimate) / sample_size
        + z ** 2 / (4 * sample_size ** 2))
    return {
        "low": round(max(0.0, center - margin), 6),
        "high": round(min(1.0, center + margin), 6),
        "method": method,
    }


def _model_identity(model: dict, round4_isolation: dict | None = None) -> str:
    public = {key: value for key, value in model.items()
              if key not in {
                  "key", "label", "public_name", "item_filters", "rounds"}}
    if round4_isolation is not None:
        public["round4_isolation"] = round4_isolation
    encoded = json.dumps(public, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_model_root(run_dir: Path, key: object) -> Path:
    if (not isinstance(key, str) or key in {"", ".", ".."}
            or slug(key) != key or Path(key).name != key):
        raise ValueError(f"unsafe model key in saved config: {key!r}")
    root = (run_dir / key).resolve()
    try:
        root.relative_to(run_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"model path escapes run directory: {key!r}") from exc
    return root


def _safe_evidence_file(path: Path, run_dir: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(run_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"evidence file escapes run directory: {path}") from exc
    if not resolved.is_file():
        raise ValueError(f"missing evidence file: {path}")
    return resolved


def _record(matrix: dict, respondent: tuple, item: str, status: str) -> None:
    if status not in {"PASS", "FAIL", "INCOMPLETE", "REVIEW", "INVALID"}:
        raise ValueError(f"unsupported item status: {status}")
    previous = matrix[respondent].get(item)
    if previous is not None and previous != status:
        raise ValueError(f"duplicate conflicting result for {item}")
    matrix[respondent][item] = status


def collect_observations(run_dirs: list[Path]) -> dict[tuple[int, str], dict]:
    """Collect status-only observations without copying prompts or model responses."""
    canonical_runs = [path.resolve() for path in run_dirs]
    if len(canonical_runs) != len(set(canonical_runs)):
        raise ValueError("the same run directory cannot be analyzed more than once")
    groups = defaultdict(lambda: {"matrix": defaultdict(dict), "models": {}})
    for run_index, run_dir in enumerate(run_dirs, 1):
        config_path = run_dir / "config.json"
        summary_path = run_dir / "summary.json"
        if not config_path.is_file() or not summary_path.is_file():
            raise ValueError(f"analysis requires config.json and summary.json: {run_dir}")
        config = load_json(_safe_evidence_file(config_path, run_dir))
        summary = load_json(_safe_evidence_file(summary_path, run_dir))
        packs = summary.get("packs")
        if not isinstance(packs, dict):
            raise ValueError(f"saved summary has no pack fingerprints: {run_dir}")
        if any(not isinstance(value, str)
               or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None
               for value in packs.values()):
            raise ValueError(f"saved summary has invalid pack fingerprints: {run_dir}")
        for model_index, model in enumerate(config.get("models", []), 1):
            if not isinstance(model, dict):
                raise ValueError(f"invalid saved model config in {run_dir}")
            key = model.get("key")
            model_root = _safe_model_root(run_dir, key)
            identity = _model_identity(model, config.get("round4_isolation"))
            for round_number in (1, 2, 3):
                round_text = str(round_number)
                paths = sorted((model_root / f"round{round_number}").glob(
                    "attempt-*/result.json"))
                if paths and round_text not in packs:
                    raise ValueError(
                        f"round {round_number} results lack a saved pack fingerprint")
                for path in paths:
                    payload = load_json(_safe_evidence_file(path, run_dir))
                    attempt = payload.get("attempt") or path.parent.name.removeprefix("attempt-")
                    respondent = (run_index, model_index, str(attempt))
                    group = groups[(round_number, packs[round_text])]
                    group["models"][respondent] = identity
                    for row in payload.get("results", []):
                        if not isinstance(row, dict) or row.get("id") is None:
                            raise ValueError(f"invalid item row in {path}")
                        _record(group["matrix"], respondent, f"q{row['id']}",
                                item_status(row))
            round4_path = model_root / "round4" / "run.json"
            if not round4_path.is_file():
                continue
            if "4" not in packs:
                raise ValueError("round 4 results lack a saved pack fingerprint")
            payload = load_json(_safe_evidence_file(round4_path, run_dir))
            group = groups[(4, packs["4"])]
            graded = set()
            for grade in payload.get("grades", []):
                item = grade.get("task", grade.get("qid"))
                attempt = (grade.get("run_meta") or {}).get("attempt")
                if not isinstance(item, str) or attempt is None:
                    raise ValueError(f"invalid Round 4 grade in {round4_path}")
                respondent = (run_index, model_index, str(attempt))
                group["models"][respondent] = identity
                flags = grade.get("flags") or {}
                status = ("INVALID" if flags.get("model_timed_out") else
                          "PASS" if flags.get("attempt_pass") else "FAIL")
                _record(group["matrix"], respondent, item, status)
                graded.add((item, str(attempt)))
            for error in payload.get("errors", []):
                item, attempt = error.get("task"), error.get("attempt")
                if not isinstance(item, str) or attempt is None:
                    continue
                if (item, str(attempt)) in graded:
                    continue
                respondent = (run_index, model_index, str(attempt))
                group["models"][respondent] = identity
                _record(group["matrix"], respondent, item, "INVALID")
    if not groups:
        raise ValueError("no item-level results were found in the selected runs")
    return groups


def _correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    mean_x, mean_y = statistics.mean(xs), statistics.mean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator = math.sqrt(
        sum((x - mean_x) ** 2 for x in xs)
        * sum((y - mean_y) ** 2 for y in ys))
    return numerator / denominator if denominator else None


def _item_metrics(matrix: dict, clusters: dict | None = None) -> list[dict]:
    item_ids = sorted({item for rows in matrix.values() for item in rows})
    metrics = []
    for item in item_ids:
        counts = {status: 0 for status in
                  ("PASS", "FAIL", "INCOMPLETE", "REVIEW", "INVALID", "MISSING")}
        xs, rest_scores = [], []
        outcomes_by_cluster = defaultdict(list)
        pairs_by_cluster = defaultdict(list)
        for respondent, rows in matrix.items():
            status = rows.get(item, "MISSING")
            counts[status] += 1
            if status not in SCORED:
                continue
            cluster = clusters.get(respondent, respondent) if clusters else respondent
            outcome = 1.0 if status == "PASS" else 0.0
            outcomes_by_cluster[cluster].append(outcome)
            rest = [1.0 if value == "PASS" else 0.0
                    for other, value in rows.items()
                    if other != item and value in SCORED]
            if rest:
                xs.append(outcome)
                rest_score = statistics.mean(rest)
                rest_scores.append(rest_score)
                pairs_by_cluster[cluster].append((outcome, rest_score))
        scored = counts["PASS"] + counts["FAIL"]
        pass_rate = counts["PASS"] / scored if scored else None
        discrimination = _correlation(xs, rest_scores)
        cluster_rates = [statistics.mean(values)
                         for values in outcomes_by_cluster.values()]
        clustered_pass_rate = statistics.mean(cluster_rates) if cluster_rates else None
        pass_interval = _bounded_rate_interval(
            cluster_rates, MIN_ITEM_OBSERVATIONS, "independent_cluster_wilson_95")
        clustered_discrimination = _cluster_weighted_correlation(
            list(pairs_by_cluster.values()))
        discrimination_interval = (
            _item_discrimination_interval(
                list(pairs_by_cluster.values()), f"item:{item}")
            if len(pairs_by_cluster) >= MIN_ITEM_INTERVAL_OBSERVATIONS else None)
        information = 4 * pass_rate * (1 - pass_rate) if pass_rate is not None else None
        clustered_information = (4 * clustered_pass_rate * (1 - clustered_pass_rate)
                                 if clustered_pass_rate is not None else None)
        if scored < MIN_ITEM_OBSERVATIONS:
            classification = "INSUFFICIENT"
        elif pass_rate >= 0.95:
            classification = "CEILING"
        elif pass_rate <= 0.05:
            classification = "FLOOR"
        elif discrimination is None:
            classification = "LOW_INFORMATION"
        elif discrimination < 0:
            classification = "NEGATIVE"
        elif discrimination < 0.15:
            classification = "WEAK"
        else:
            classification = "USEFUL"
        if len(outcomes_by_cluster) < MIN_ITEM_INTERVAL_OBSERVATIONS:
            robust_classification = "INSUFFICIENT"
        elif (clustered_pass_rate is not None and clustered_pass_rate >= 0.95
              and pass_interval is not None and pass_interval["low"] >= 0.8):
            robust_classification = "ROBUST_CEILING"
        elif (clustered_pass_rate is not None and clustered_pass_rate <= 0.05
              and pass_interval is not None and pass_interval["high"] <= 0.2):
            robust_classification = "ROBUST_FLOOR"
        elif discrimination_interval is None:
            robust_classification = "UNSTABLE"
        elif (clustered_discrimination is not None and clustered_discrimination < 0
              and discrimination_interval["high"] < 0):
            robust_classification = "ROBUST_NEGATIVE"
        elif (clustered_discrimination is not None and clustered_discrimination >= 0.15
              and discrimination_interval["low"] >= 0.15):
            robust_classification = "ROBUST_USEFUL"
        else:
            robust_classification = "UNCERTAIN"
        metrics.append({
            "item": item,
            "scored": scored,
            "pass": counts["PASS"],
            "fail": counts["FAIL"],
            "incomplete": counts["INCOMPLETE"],
            "review": counts["REVIEW"],
            "invalid": counts["INVALID"],
            "missing": counts["MISSING"],
            "independent_units": len(outcomes_by_cluster),
            "discrimination_units": len(pairs_by_cluster),
            "pass_rate": round(pass_rate, 6) if pass_rate is not None else None,
            "clustered_pass_rate": (
                round(clustered_pass_rate, 6)
                if clustered_pass_rate is not None else None),
            "pass_rate_interval95": pass_interval,
            "difficulty_balance": round(information, 6) if information is not None else None,
            "clustered_difficulty_balance": (
                round(clustered_information, 6)
                if clustered_information is not None else None),
            "corrected_item_total_correlation": (
                round(discrimination, 6) if discrimination is not None else None),
            "clustered_corrected_discrimination": (
                round(clustered_discrimination, 6)
                if clustered_discrimination is not None else None),
            "discrimination_interval95": discrimination_interval,
            "classification": classification,
            "robust_classification": robust_classification,
        })
    def ranking(row: dict) -> tuple:
        discrimination = row["clustered_corrected_discrimination"]
        information = row["clustered_difficulty_balance"]
        return (discrimination is None,
                -discrimination if discrimination is not None else 0,
                -information if information is not None else 0,
                row["item"])

    return sorted(metrics, key=ranking)


def _pairwise_stability(matrix: dict, models: dict) -> dict:
    buckets = {"between": [], "within": []}
    for left, right in combinations(sorted(matrix), 2):
        common = [item for item in set(matrix[left]) & set(matrix[right])
                  if matrix[left][item] in SCORED and matrix[right][item] in SCORED]
        if len(common) < MIN_PAIR_ITEMS:
            continue
        disagreement = sum(matrix[left][item] != matrix[right][item]
                           for item in common) / len(common)
        bucket = "within" if models[left] == models[right] else "between"
        buckets[bucket].append(disagreement)
    between = statistics.mean(buckets["between"]) if buckets["between"] else None
    within = statistics.mean(buckets["within"]) if buckets["within"] else None
    return {
        "between_configuration_pairs": len(buckets["between"]),
        "between_configuration_disagreement": (
            round(between, 6) if between is not None else None),
        "within_configuration_pairs": len(buckets["within"]),
        "within_configuration_disagreement": (
            round(within, 6) if within is not None else None),
        "net_separation": (round(between - within, 6)
                           if between is not None and within is not None else None),
    }


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1,
                       math.ceil(probability * len(ordered)) - 1))
    return ordered[index]


def _cluster_moments(cluster: list[tuple[float, float]]) -> tuple[float, ...]:
    count = len(cluster)
    return (
        1.0,
        sum(pair[0] for pair in cluster) / count,
        sum(pair[1] for pair in cluster) / count,
        sum(pair[0] ** 2 for pair in cluster) / count,
        sum(pair[1] ** 2 for pair in cluster) / count,
        sum(pair[0] * pair[1] for pair in cluster) / count,
    )


def _correlation_from_moments(rows: list[tuple[float, ...]]) -> float | None:
    count = sum(row[0] for row in rows)
    if not count:
        return None
    sum_x = sum(row[1] for row in rows)
    sum_y = sum(row[2] for row in rows)
    sum_x2 = sum(row[3] for row in rows)
    sum_y2 = sum(row[4] for row in rows)
    sum_xy = sum(row[5] for row in rows)
    numerator = sum_xy - sum_x * sum_y / count
    variance_x = sum_x2 - sum_x ** 2 / count
    variance_y = sum_y2 - sum_y ** 2 / count
    denominator = math.sqrt(max(0.0, variance_x) * max(0.0, variance_y))
    if not denominator:
        return None
    return max(-1.0, min(1.0, numerator / denominator))


def _cluster_weighted_correlation(
        pair_clusters: list[list[tuple[float, float]]]) -> float | None:
    return _correlation_from_moments([_cluster_moments(cluster)
                                      for cluster in pair_clusters])


def _item_discrimination_interval(pair_clusters: list[list[tuple[float, float]]],
                                  seed: str) -> dict | None:
    """Bootstrap independent clusters; withhold intervals dominated by undefined draws."""
    if len(pair_clusters) < MIN_ITEM_INTERVAL_OBSERVATIONS:
        return None
    generator = _HashSampler(seed)
    cluster_stats = [_cluster_moments(cluster) for cluster in pair_clusters]
    correlations = []
    for _ in range(BOOTSTRAP_SAMPLES):
        sampled = [generator.choice(cluster_stats) for _ in cluster_stats]
        correlation = _correlation_from_moments(sampled)
        if correlation is not None:
            correlations.append(correlation)
    if len(correlations) < 0.8 * BOOTSTRAP_SAMPLES:
        return None
    return {
        "low": round(_percentile(correlations, 0.025), 6),
        "high": round(_percentile(correlations, 0.975), 6),
        "method": "independent_cluster_bootstrap_95",
        "samples": BOOTSTRAP_SAMPLES,
        "valid_samples": len(correlations),
        "independent_clusters": len(pair_clusters),
    }


def _item_relationships(matrix: dict, clusters: dict | None = None) -> list[dict]:
    """Measure empirical item overlap without treating repeated bundle rows as independent."""
    item_ids = sorted({item for rows in matrix.values() for item in rows})
    relationships = []
    for left, right in combinations(item_ids, 2):
        raw_pairs = []
        pairs_by_cluster = defaultdict(list)
        for respondent, rows in matrix.items():
            if rows.get(left) not in SCORED or rows.get(right) not in SCORED:
                continue
            pair = (1.0 if rows[left] == "PASS" else 0.0,
                    1.0 if rows[right] == "PASS" else 0.0)
            raw_pairs.append(pair)
            cluster = clusters.get(respondent, respondent) if clusters else respondent
            pairs_by_cluster[cluster].append(pair)
        raw_correlation = _correlation(
            [pair[0] for pair in raw_pairs], [pair[1] for pair in raw_pairs])
        cluster_rows = list(pairs_by_cluster.values())
        clustered_correlation = _cluster_weighted_correlation(cluster_rows)
        interval = (
            _item_discrimination_interval(
                cluster_rows, f"relationship:{left}:{right}")
            if (len(cluster_rows) >= MIN_ITEM_INTERVAL_OBSERVATIONS
                and clustered_correlation is not None
                and abs(clustered_correlation) >= ITEM_REDUNDANCY_THRESHOLD)
            else None)
        raw_agreement = (statistics.mean(pair[0] == pair[1] for pair in raw_pairs)
                         if raw_pairs else None)
        cluster_agreement = (
            statistics.mean(
                statistics.mean(pair[0] == pair[1] for pair in cluster)
                for cluster in cluster_rows)
            if cluster_rows else None)

        if len(raw_pairs) < MIN_ITEM_OBSERVATIONS:
            classification = "INSUFFICIENT"
        elif raw_correlation is None:
            classification = "LOW_INFORMATION"
        elif raw_correlation >= ITEM_REDUNDANCY_THRESHOLD:
            classification = "REDUNDANCY_CANDIDATE"
        elif raw_correlation <= -ITEM_REDUNDANCY_THRESHOLD:
            classification = "OPPOSING_CANDIDATE"
        elif abs(raw_correlation) >= ITEM_RELATIONSHIP_THRESHOLD:
            classification = "RELATED"
        else:
            classification = "DISTINCT"

        if len(cluster_rows) < MIN_ITEM_INTERVAL_OBSERVATIONS:
            robust_classification = "INSUFFICIENT"
        elif clustered_correlation is None:
            robust_classification = "UNSTABLE"
        elif abs(clustered_correlation) < ITEM_REDUNDANCY_THRESHOLD:
            robust_classification = "UNCERTAIN"
        elif interval is None:
            robust_classification = "UNSTABLE"
        elif (clustered_correlation is not None
              and clustered_correlation >= ITEM_REDUNDANCY_THRESHOLD
              and interval["low"] >= ITEM_REDUNDANCY_THRESHOLD):
            robust_classification = "ROBUST_REDUNDANCY_CANDIDATE"
        elif (clustered_correlation is not None
              and clustered_correlation <= -ITEM_REDUNDANCY_THRESHOLD
              and interval["high"] <= -ITEM_REDUNDANCY_THRESHOLD):
            robust_classification = "ROBUST_OPPOSING_CANDIDATE"
        else:
            robust_classification = "UNCERTAIN"

        relationships.append({
            "left": left,
            "right": right,
            "common_scored": len(raw_pairs),
            "independent_units": len(cluster_rows),
            "outcome_agreement": (
                round(raw_agreement, 6) if raw_agreement is not None else None),
            "clustered_outcome_agreement": (
                round(cluster_agreement, 6)
                if cluster_agreement is not None else None),
            "phi_correlation": (
                round(raw_correlation, 6) if raw_correlation is not None else None),
            "clustered_phi_correlation": (
                round(clustered_correlation, 6)
                if clustered_correlation is not None else None),
            "correlation_interval95": interval,
            "classification": classification,
            "robust_classification": robust_classification,
        })

    robust_order = {
        "ROBUST_REDUNDANCY_CANDIDATE": 0,
        "ROBUST_OPPOSING_CANDIDATE": 1,
        "UNCERTAIN": 2,
        "UNSTABLE": 3,
        "INSUFFICIENT": 4,
    }

    def ranking(row: dict) -> tuple:
        correlation = row["clustered_phi_correlation"]
        return (robust_order[row["robust_classification"]],
                -abs(correlation) if correlation is not None else 0,
                row["left"], row["right"])

    return sorted(relationships, key=ranking)


def _repeat_adjusted_components(
        rates_by_configuration: dict[str, dict[object, float]]) -> tuple[float, float, float]:
    means = [statistics.mean(rates.values())
             for rates in rates_by_configuration.values()]
    between = statistics.mean(
        abs(left - right) for left, right in combinations(means, 2))
    within = statistics.mean(
        statistics.mean(abs(left - right)
                        for left, right in combinations(rates.values(), 2))
        for rates in rates_by_configuration.values())
    return between, within, between - within


def _repeat_adjusted_interval(
        rates_by_configuration: dict[str, dict[object, float]], seed: str,
        *, shared_clusters: bool) -> dict | None:
    generator = _HashSampler(seed)
    samples = []
    if shared_clusters:
        population = sorted({cluster for rates in rates_by_configuration.values()
                             for cluster in rates}, key=repr)
    for _ in range(BOOTSTRAP_SAMPLES):
        sampled = {}
        if shared_clusters:
            selected = [generator.choice(population) for _ in population]
            for configuration, rates in rates_by_configuration.items():
                values = [rates[cluster] for cluster in selected if cluster in rates]
                if len(values) >= 2:
                    sampled[configuration] = {
                        index: value for index, value in enumerate(values)}
        else:
            for configuration, rates in rates_by_configuration.items():
                population = list(rates.values())
                sampled[configuration] = {
                    index: generator.choice(population)
                    for index in range(len(population))}
        if len(sampled) != len(rates_by_configuration):
            continue
        samples.append(_repeat_adjusted_components(sampled)[2])
    if len(samples) < 0.8 * BOOTSTRAP_SAMPLES:
        return None
    return {
        "low": round(_percentile(samples, 0.025), 6),
        "high": round(_percentile(samples, 0.975), 6),
        "method": ("shared_cluster_hierarchical_bootstrap_95" if shared_clusters
                   else "configuration_cluster_bootstrap_95"),
        "samples": BOOTSTRAP_SAMPLES,
        "valid_samples": len(samples),
    }


def _item_repeat_separation(matrix: dict, models: dict,
                            clusters: dict | None = None) -> list[dict]:
    """Compare per-item configuration separation with same-configuration repeat noise."""
    item_ids = sorted({item for rows in matrix.values() for item in rows})
    diagnostics = []
    for item in item_ids:
        grouped = defaultdict(lambda: defaultdict(list))
        for respondent, rows in matrix.items():
            status = rows.get(item)
            if status not in SCORED:
                continue
            configuration = models[respondent]
            cluster = clusters.get(respondent, respondent) if clusters else respondent
            grouped[configuration][cluster].append(1.0 if status == "PASS" else 0.0)
        cluster_rates = {
            configuration: {
                cluster: statistics.mean(values)
                for cluster, values in by_cluster.items()
            }
            for configuration, by_cluster in grouped.items()
        }
        repeated = {configuration: rates
                    for configuration, rates in cluster_rates.items()
                    if len(rates) >= 2}
        robust = {configuration: rates
                  for configuration, rates in cluster_rates.items()
                  if len(rates) >= MIN_CONFIGURATION_RESPONDENTS}
        if len(repeated) >= 2:
            between, within, net = _repeat_adjusted_components(repeated)
            if between == 0 and within == 0:
                classification = "NO_SEPARATION"
            elif net < 0:
                classification = "NOISE_DOMINATED"
            elif net < ITEM_NET_SEPARATION_THRESHOLD:
                classification = "WEAK_SEPARATION"
            else:
                classification = "SEPARATING"
        else:
            between = within = net = None
            classification = "INSUFFICIENT"

        if len(robust) >= 2:
            robust_between, robust_within, robust_net = (
                _repeat_adjusted_components(robust))
            interval = _repeat_adjusted_interval(
                robust, f"repeat-separation:{item}",
                shared_clusters=clusters is not None)
            if interval is None:
                robust_classification = "UNSTABLE"
            elif robust_between == 0 and robust_within == 0:
                robust_classification = "ROBUST_NO_SEPARATION"
            elif (robust_net >= ITEM_NET_SEPARATION_THRESHOLD
                  and interval["low"] >= ITEM_NET_SEPARATION_THRESHOLD):
                robust_classification = "ROBUST_SEPARATING"
            elif robust_net < 0 and interval["high"] < 0:
                robust_classification = "ROBUST_NOISE_DOMINATED"
            else:
                robust_classification = "UNCERTAIN"
        else:
            robust_between = robust_within = robust_net = interval = None
            robust_classification = "INSUFFICIENT"

        independent_clusters = {cluster for rates in cluster_rates.values()
                                for cluster in rates}
        minimum_clusters = min((len(rates) for rates in robust.values()), default=0)
        diagnostics.append({
            "item": item,
            "configurations": len(cluster_rates),
            "repeat_configurations": len(repeated),
            "robust_configurations": len(robust),
            "independent_units": len(independent_clusters),
            "minimum_robust_units_per_configuration": minimum_clusters,
            "between_configuration_separation": (
                round(between, 6) if between is not None else None),
            "within_configuration_instability": (
                round(within, 6) if within is not None else None),
            "net_repeat_adjusted_separation": (
                round(net, 6) if net is not None else None),
            "robust_between_configuration_separation": (
                round(robust_between, 6) if robust_between is not None else None),
            "robust_within_configuration_instability": (
                round(robust_within, 6) if robust_within is not None else None),
            "robust_net_repeat_adjusted_separation": (
                round(robust_net, 6) if robust_net is not None else None),
            "net_separation_interval95": interval,
            "classification": classification,
            "robust_classification": robust_classification,
        })

    robust_order = {
        "ROBUST_SEPARATING": 0,
        "ROBUST_NOISE_DOMINATED": 1,
        "ROBUST_NO_SEPARATION": 2,
        "UNCERTAIN": 3,
        "UNSTABLE": 4,
        "INSUFFICIENT": 5,
    }

    def ranking(row: dict) -> tuple:
        net = row["robust_net_repeat_adjusted_separation"]
        return (robust_order[row["robust_classification"]],
                -net if net is not None else 0, row["item"])

    return sorted(diagnostics, key=ranking)


def _cluster_item_rows(matrix: dict, models: dict,
                       clusters: dict | None) -> dict:
    grouped = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for respondent, rows in matrix.items():
        configuration = models[respondent]
        cluster = clusters.get(respondent, respondent) if clusters else respondent
        for item, status in rows.items():
            if status in SCORED:
                grouped[configuration][cluster][item].append(
                    1.0 if status == "PASS" else 0.0)
    return {
        configuration: {
            cluster: {item: statistics.mean(values)
                      for item, values in items.items()}
            for cluster, items in by_cluster.items()
        }
        for configuration, by_cluster in grouped.items()
    }


def _simultaneous_pair_interval(
        left_rows: dict, right_rows: dict, effects: dict[str, float],
        seed: str, alpha: float, *, shared_clusters: bool) -> dict | None:
    generator = _HashSampler(seed)
    maximum_errors = []
    if shared_clusters:
        population = sorted(set(left_rows) | set(right_rows), key=repr)
    for _ in range(BOOTSTRAP_SAMPLES):
        if shared_clusters:
            selected = [generator.choice(population) for _ in population]
            sampled_left = [left_rows[cluster] for cluster in selected
                            if cluster in left_rows]
            sampled_right = [right_rows[cluster] for cluster in selected
                             if cluster in right_rows]
        else:
            left_population = list(left_rows.values())
            right_population = list(right_rows.values())
            sampled_left = [generator.choice(left_population)
                            for _ in left_population]
            sampled_right = [generator.choice(right_population)
                             for _ in right_population]
        errors = []
        for item, observed in effects.items():
            left = [row[item] for row in sampled_left if item in row]
            right = [row[item] for row in sampled_right if item in row]
            if not left or not right:
                errors = []
                break
            bootstrapped = statistics.mean(left) - statistics.mean(right)
            errors.append(abs(bootstrapped - observed))
        if errors:
            maximum_errors.append(max(errors))
    if len(maximum_errors) < 0.8 * BOOTSTRAP_SAMPLES:
        return None
    critical = _percentile(maximum_errors, 1 - alpha)
    return {
        "critical_value": round(critical, 6),
        "confidence": round(1 - alpha, 6),
        "method": ("shared_cluster_max_error_bootstrap" if shared_clusters
                   else "configuration_cluster_max_error_bootstrap"),
        "samples": BOOTSTRAP_SAMPLES,
        "valid_samples": len(maximum_errors),
    }


def _configuration_item_coverage(matrix: dict, models: dict, aliases: dict,
                                 clusters: dict | None = None) -> dict:
    """Find pair-specific separating items with family-wise simultaneous intervals."""
    rows = _cluster_item_rows(matrix, models, clusters)
    def alias_order(identity: str) -> tuple:
        alias = aliases[identity]
        match = re.fullmatch(r"C(\d+)", alias)
        return (0, int(match.group(1))) if match else (1, alias)

    configurations = sorted(rows, key=alias_order)
    candidates = []
    for left, right in combinations(configurations, 2):
        left_items = defaultdict(list)
        right_items = defaultdict(list)
        for row in rows[left].values():
            for item, value in row.items():
                left_items[item].append(value)
        for row in rows[right].values():
            for item, value in row.items():
                right_items[item].append(value)
        common = sorted(
            item for item in set(left_items) & set(right_items)
            if (len(left_items[item]) >= MIN_CONFIGURATION_RESPONDENTS
                and len(right_items[item]) >= MIN_CONFIGURATION_RESPONDENTS))
        effects = {item: statistics.mean(left_items[item])
                   - statistics.mean(right_items[item]) for item in common}
        candidates.append((left, right, effects, left_items, right_items))

    eligible_pairs = sum(bool(effects) for _, _, effects, _, _ in candidates)
    alpha = 0.05 / eligible_pairs if eligible_pairs else None
    comparisons = []
    coverage = defaultdict(lambda: {
        "eligible_configuration_pairs": 0,
        "decisive_configuration_pairs": 0,
        "maximum_absolute_effect": 0.0,
    })
    for left, right, effects, left_items, right_items in candidates:
        if not effects:
            comparisons.append({
                "left": aliases[left], "right": aliases[right],
                "eligible_items": 0, "decisive_items": 0,
                "familywise_alpha": None, "interval": None,
                "classification": "INSUFFICIENT", "items": [],
            })
            continue
        interval = _simultaneous_pair_interval(
            rows[left], rows[right], effects,
            f"item-coverage:{left}:{right}", alpha,
            shared_clusters=clusters is not None)
        item_rows = []
        for item, effect in effects.items():
            coverage[item]["eligible_configuration_pairs"] += 1
            coverage[item]["maximum_absolute_effect"] = max(
                coverage[item]["maximum_absolute_effect"], abs(effect))
            if interval is None:
                low = high = None
                classification = "UNSTABLE"
            else:
                critical = interval["critical_value"]
                low = max(-1.0, effect - critical)
                high = min(1.0, effect + critical)
                if effect >= ITEM_PAIR_EFFECT_THRESHOLD and low >= ITEM_PAIR_EFFECT_THRESHOLD:
                    classification = "LEFT_HIGHER"
                elif (effect <= -ITEM_PAIR_EFFECT_THRESHOLD
                      and high <= -ITEM_PAIR_EFFECT_THRESHOLD):
                    classification = "RIGHT_HIGHER"
                else:
                    classification = "UNCERTAIN"
            if classification in {"LEFT_HIGHER", "RIGHT_HIGHER"}:
                coverage[item]["decisive_configuration_pairs"] += 1
            item_rows.append({
                "item": item,
                "left_independent_units": len(left_items[item]),
                "right_independent_units": len(right_items[item]),
                "pass_rate_difference": round(effect, 6),
                "simultaneous_interval": (
                    {"low": round(low, 6), "high": round(high, 6)}
                    if low is not None else None),
                "classification": classification,
            })
        item_rows.sort(key=lambda row: (
            row["classification"] not in {"LEFT_HIGHER", "RIGHT_HIGHER"},
            -abs(row["pass_rate_difference"]), row["item"]))
        decisive = sum(row["classification"] in {"LEFT_HIGHER", "RIGHT_HIGHER"}
                       for row in item_rows)
        comparisons.append({
            "left": aliases[left], "right": aliases[right],
            "eligible_items": len(item_rows), "decisive_items": decisive,
            "familywise_alpha": round(alpha, 8), "interval": interval,
            "classification": (
                "UNSTABLE" if interval is None else
                "SEPARATING" if decisive else "UNCERTAIN"),
            "items": item_rows,
        })

    item_coverage = [{"item": item,
                      **values,
                      "maximum_absolute_effect": round(
                          values["maximum_absolute_effect"], 6)}
                     for item, values in coverage.items()]
    item_coverage.sort(key=lambda row: (
        -row["decisive_configuration_pairs"],
        -row["maximum_absolute_effect"], row["item"]))
    return {
        "eligible_configuration_pairs": eligible_pairs,
        "bonferroni_familywise_alpha": round(alpha, 8) if alpha else None,
        "effect_threshold": ITEM_PAIR_EFFECT_THRESHOLD,
        "comparisons": comparisons,
        "item_coverage": item_coverage,
    }


def _discriminative_item_panel(coverage: dict, relationships: list[dict],
                               max_items: int | None = None) -> dict:
    """Greedily cover confirmed pair directions while penalizing dependent items."""
    if max_items is not None and (
            isinstance(max_items, bool) or not isinstance(max_items, int)
            or max_items < 1):
        raise ValueError("panel max items must be a positive integer")
    targets_by_item = defaultdict(set)
    margins_by_item = defaultdict(list)
    effects_by_item = defaultdict(list)
    for pair in coverage.get("comparisons", []):
        left, right = pair["left"], pair["right"]
        for row in pair.get("items", []):
            classification = row.get("classification")
            interval = row.get("simultaneous_interval")
            if (classification not in {"LEFT_HIGHER", "RIGHT_HIGHER"}
                    or not isinstance(interval, dict)):
                continue
            if classification == "LEFT_HIGHER":
                target = f"{left}>{right}"
                margin = interval["low"]
            else:
                target = f"{right}>{left}"
                margin = -interval["high"]
            targets_by_item[row["item"]].add(target)
            margins_by_item[row["item"]].append(float(margin))
            effects_by_item[row["item"]].append(
                abs(float(row["pass_rate_difference"])))

    dependency = defaultdict(set)
    dependency_rows = 0
    for row in relationships:
        if row.get("robust_classification") not in {
                "ROBUST_REDUNDANCY_CANDIDATE",
                "ROBUST_OPPOSING_CANDIDATE"}:
            continue
        left, right = row.get("left"), row.get("right")
        if left in targets_by_item and right in targets_by_item:
            dependency[left].add(right)
            dependency[right].add(left)
            dependency_rows += 1

    all_targets = set().union(*targets_by_item.values()) if targets_by_item else set()
    uncovered = set(all_targets)
    remaining = set(targets_by_item)
    selected = []
    while uncovered and remaining and (
            max_items is None or len(selected) < max_items):
        ranked = []
        selected_names = {row["item"] for row in selected}
        for item in remaining:
            new_targets = targets_by_item[item] & uncovered
            if not new_targets:
                continue
            dependent_with = sorted(dependency[item] & selected_names)
            ranked.append((
                -len(new_targets), len(dependent_with), len(dependency[item]),
                -min(margins_by_item[item]), -max(effects_by_item[item]), item,
                new_targets, dependent_with,
            ))
        if not ranked:
            break
        (_, _, dependency_degree, _, _, item,
         new_targets, dependent_with) = min(ranked)
        selected.append({
            "item": item,
            "new_directional_targets": sorted(new_targets),
            "all_directional_targets": sorted(targets_by_item[item]),
            "minimum_simultaneous_margin": round(min(margins_by_item[item]), 6),
            "maximum_absolute_effect": round(max(effects_by_item[item]), 6),
            "robust_dependency_degree": dependency_degree,
            "robustly_dependent_with_selected": dependent_with,
        })
        uncovered -= new_targets
        remaining.remove(item)

    if not all_targets:
        status = ("INSUFFICIENT" if not coverage.get("eligible_configuration_pairs")
                  else "NO_DECISIVE_ITEMS")
    elif uncovered:
        status = "PARTIAL"
    else:
        status = "COMPLETE"
    return {
        "status": status,
        "selection_method": "deterministic_greedy_directional_set_cover",
        "max_items": max_items,
        "candidate_items": len(targets_by_item),
        "selected_items": selected,
        "directional_targets": len(all_targets),
        "covered_directional_targets": len(all_targets) - len(uncovered),
        "uncovered_directional_targets": sorted(uncovered),
        "robust_dependency_pairs_considered": dependency_rows,
        "interpretation": (
            "heuristic review panel; not a globally minimal set or an automatic "
            "benchmark-pack mutation"),
    }


def _permutation_difference_test(higher_values: list[float],
                                 lower_values: list[float], seed: str) -> dict:
    """Two-sided label permutation test for a held-out mean difference."""
    pooled = list(higher_values) + list(lower_values)
    higher_count = len(higher_values)
    if not higher_count or not lower_values:
        raise ValueError("permutation test requires two non-empty groups")
    observed = abs(statistics.mean(higher_values) - statistics.mean(lower_values))
    total_sum = sum(pooled)
    assignments = math.comb(len(pooled), higher_count)
    tolerance = 1e-12
    extreme = 0
    if assignments <= HOLDOUT_EXACT_PERMUTATION_LIMIT:
        evaluated = assignments
        for selected in combinations(range(len(pooled)), higher_count):
            selected_sum = sum(pooled[index] for index in selected)
            difference = abs(
                selected_sum / higher_count
                - (total_sum - selected_sum) / len(lower_values))
            extreme += difference + tolerance >= observed
        p_value = extreme / evaluated
        method = "exact_label_permutation_two_sided"
    else:
        evaluated = HOLDOUT_MONTE_CARLO_SAMPLES
        generator = _HashSampler(seed)
        population = list(range(len(pooled)))
        for _ in range(evaluated):
            shuffled = population.copy()
            for position in range(higher_count):
                selected_position = position + generator.choice(
                    range(len(shuffled) - position))
                shuffled[position], shuffled[selected_position] = (
                    shuffled[selected_position], shuffled[position])
            selected_sum = sum(pooled[index]
                               for index in shuffled[:higher_count])
            difference = abs(
                selected_sum / higher_count
                - (total_sum - selected_sum) / len(lower_values))
            extreme += difference + tolerance >= observed
        p_value = (extreme + 1) / (evaluated + 1)
        method = "deterministic_monte_carlo_label_permutation_two_sided"
    conservative_p = min(1.0, math.ceil(p_value * 100_000_000) / 100_000_000)
    return {
        "p_value": conservative_p,
        "method": method,
        "assignments": assignments,
        "evaluated_permutations": evaluated,
        "extreme_permutations": extreme,
    }


def _panel_holdout_validation(matrix: dict, models: dict, aliases: dict,
                              max_items: int | None = None,
                              clusters: dict | None = None) -> dict:
    """Select panels on one fold and test their directions on the other fold."""
    units_by_respondent = {
        respondent: (clusters.get(respondent, respondent)
                     if clusters else respondent)
        for respondent in matrix
    }
    configurations_by_unit = defaultdict(set)
    for respondent, unit in units_by_respondent.items():
        configurations_by_unit[unit].add(models[respondent])

    fold_by_unit = {}
    configuration_counts = [defaultdict(int), defaultdict(int)]
    for index, unit in enumerate(sorted(configurations_by_unit, key=repr)):
        configurations = configurations_by_unit[unit]
        scores = [sum(configuration_counts[fold][configuration]
                      for configuration in configurations)
                  for fold in (0, 1)]
        fold = index % 2 if scores[0] == scores[1] else scores.index(min(scores))
        fold_by_unit[unit] = fold
        for configuration in configurations:
            configuration_counts[fold][configuration] += 1

    identity_by_alias = {alias: identity for identity, alias in aliases.items()}
    folds = []
    all_evaluations = []
    selected_sets = []
    for holdout_fold in (0, 1):
        training_matrix = {
            respondent: rows for respondent, rows in matrix.items()
            if fold_by_unit[units_by_respondent[respondent]] != holdout_fold
        }
        holdout_matrix = {
            respondent: rows for respondent, rows in matrix.items()
            if fold_by_unit[units_by_respondent[respondent]] == holdout_fold
        }
        relationships = _item_relationships(
            training_matrix, clusters if clusters else None)
        coverage = _configuration_item_coverage(
            training_matrix, models, aliases, clusters if clusters else None)
        panel = _discriminative_item_panel(coverage, relationships, max_items)
        selected_items = [row["item"] for row in panel["selected_items"]]
        selected_sets.append(set(selected_items))
        holdout_rows = _cluster_item_rows(
            holdout_matrix, models, clusters if clusters else None)
        evaluations = []
        for selected in panel["selected_items"]:
            item = selected["item"]
            for target in selected["new_directional_targets"]:
                higher_alias, separator, lower_alias = target.partition(">")
                higher = identity_by_alias.get(higher_alias)
                lower = identity_by_alias.get(lower_alias)
                higher_values = [row[item] for row in holdout_rows.get(higher, {}).values()
                                 if item in row]
                lower_values = [row[item] for row in holdout_rows.get(lower, {}).values()
                                if item in row]
                if (not separator or higher is None or lower is None
                        or len(higher_values) < MIN_CONFIGURATION_RESPONDENTS
                        or len(lower_values) < MIN_CONFIGURATION_RESPONDENTS):
                    effect = None
                    permutation = None
                else:
                    effect = statistics.mean(higher_values) - statistics.mean(lower_values)
                    permutation = _permutation_difference_test(
                        higher_values, lower_values,
                        f"panel-holdout:{holdout_fold}:{item}:{target}")
                evaluations.append({
                    "item": item,
                    "directional_target": target,
                    "higher_holdout_units": len(higher_values),
                    "lower_holdout_units": len(lower_values),
                    "holdout_pass_rate_difference": (
                        round(effect, 6) if effect is not None else None),
                    "permutation_p_raw": (
                        permutation["p_value"] if permutation else None),
                    "permutation_p_holm": None,
                    "permutation": permutation,
                    "classification": (
                        "PENDING" if permutation else "INSUFFICIENT"),
                })
        all_evaluations.extend(evaluations)
        training_units = {
            alias: configuration_counts[1 - holdout_fold][identity]
            for identity, alias in aliases.items()
        }
        holdout_units = {
            alias: configuration_counts[holdout_fold][identity]
            for identity, alias in aliases.items()
        }
        folds.append({
            "fold": holdout_fold + 1,
            "training_independent_units": training_units,
            "holdout_independent_units": holdout_units,
            "training_panel_status": panel["status"],
            "selected_items": selected_items,
            "selected_directional_targets": sum(
                len(row["new_directional_targets"])
                for row in panel["selected_items"]),
            "holdout_evaluations": evaluations,
        })

    tested = [row for row in all_evaluations
              if row["permutation_p_raw"] is not None]
    previous = 0.0
    for rank, row in enumerate(
            sorted(tested, key=lambda value: (
                value["permutation_p_raw"], value["directional_target"],
                value["item"])), 1):
        adjusted = min(1.0, max(
            previous, row["permutation_p_raw"] * (len(tested) - rank + 1)))
        previous = adjusted
        row["permutation_p_holm"] = round(adjusted, 8)
        effect = row["holdout_pass_rate_difference"]
        if adjusted >= 0.05 or abs(effect) < ITEM_PAIR_EFFECT_THRESHOLD:
            row["classification"] = "WEAK"
        elif effect > 0:
            row["classification"] = "CONFIRMED"
        else:
            row["classification"] = "REVERSED"

    counts = {
        classification.lower(): sum(
            row["classification"] == classification for row in all_evaluations)
        for classification in ("CONFIRMED", "WEAK", "REVERSED", "INSUFFICIENT")
    }
    eligible = counts["confirmed"] + counts["weak"] + counts["reversed"]
    folds_evaluated = sum(any(
        row["classification"] != "INSUFFICIENT"
        for row in fold["holdout_evaluations"])
        for fold in folds)
    if counts["reversed"]:
        status = "REVERSED_SIGNAL"
    elif (folds_evaluated < 2 or eligible == 0
          or counts["insufficient"]):
        status = "INSUFFICIENT"
    elif counts["weak"]:
        status = "WEAK_GENERALIZATION"
    else:
        status = "STABLE"
    union = selected_sets[0] | selected_sets[1]
    selection_jaccard = (
        len(selected_sets[0] & selected_sets[1]) / len(union) if union else None)
    return {
        "status": status,
        "method": "deterministic_stratified_two_fold_cross_validation",
        "minimum_units_per_configuration_per_side": MIN_CONFIGURATION_RESPONDENTS,
        "effect_threshold": ITEM_PAIR_EFFECT_THRESHOLD,
        "familywise_alpha": 0.05,
        "multiplicity_method": "holm_across_all_out_of_fold_direction_tests",
        "folds_evaluated": folds_evaluated,
        "eligible_direction_evaluations": eligible,
        "confirmed_direction_evaluations": counts["confirmed"],
        "weak_direction_evaluations": counts["weak"],
        "reversed_direction_evaluations": counts["reversed"],
        "insufficient_direction_evaluations": counts["insufficient"],
        "direction_confirmation_rate": (
            round(counts["confirmed"] / eligible, 6) if eligible else None),
        "selection_jaccard": (
            round(selection_jaccard, 6) if selection_jaccard is not None else None),
        "folds": folds,
        "interpretation": (
            "out-of-fold directional replication diagnostic; not an unseen-model "
            "prediction or proof of benchmark validity"),
    }


def _hierarchical_difference_interval(left_rows: list[dict], right_rows: list[dict],
                                      items: list[str], seed: str) -> dict | None:
    """Resample respondents and items so repeat instability enters the effect interval."""
    generator = _HashSampler(seed)
    means = []
    for _ in range(BOOTSTRAP_SAMPLES):
        sampled_left = [generator.choice(left_rows) for _ in left_rows]
        sampled_right = [generator.choice(right_rows) for _ in right_rows]
        differences = []
        for item in (generator.choice(items) for _ in items):
            left = [row[item] == "PASS" for row in sampled_left
                    if row.get(item) in SCORED]
            right = [row[item] == "PASS" for row in sampled_right
                     if row.get(item) in SCORED]
            if left and right:
                differences.append(statistics.mean(left) - statistics.mean(right))
        if differences:
            means.append(statistics.mean(differences))
    if not means:
        return None
    return {
        "low": round(_percentile(means, 0.025), 6),
        "high": round(_percentile(means, 0.975), 6),
        "method": "hierarchical_respondent_item_bootstrap_95",
        "samples": BOOTSTRAP_SAMPLES,
    }


def _cluster_rate_interval(values: list[float]) -> dict | None:
    """Conservative Wilson-style interval across respondent-level rates."""
    return _bounded_rate_interval(
        values, MIN_CONFIGURATION_RESPONDENTS, "respondent_cluster_wilson_95")


def _configuration_aliases(matrix: dict, models: dict) -> dict[str, str]:
    first_seen = {}
    for respondent in sorted(matrix):
        identity = models[respondent]
        first_seen.setdefault(identity, respondent)
    ordered = sorted(first_seen, key=lambda identity: first_seen[identity])
    return {identity: f"C{index}" for index, identity in enumerate(ordered, 1)}


def _configuration_scorecards(matrix: dict, models: dict,
                              aliases: dict[str, str]) -> list[dict]:
    respondents = defaultdict(list)
    status_counts = defaultdict(lambda: defaultdict(int))
    sources = defaultdict(set)
    for respondent, rows in matrix.items():
        identity = models[respondent]
        sources[identity].add((respondent[0], respondent[1]))
        scored = [status for status in rows.values() if status in SCORED]
        if scored:
            respondents[identity].append(
                sum(status == "PASS" for status in scored) / len(scored))
        for status in rows.values():
            status_counts[identity][status] += 1
    scorecards = []
    for identity, alias in sorted(
            aliases.items(), key=lambda pair: int(pair[1].removeprefix("C"))):
        rates = respondents[identity]
        counts = status_counts[identity]
        scored = counts["PASS"] + counts["FAIL"]
        attempted = scored + counts["INCOMPLETE"] + counts["REVIEW"] + counts["INVALID"]
        scorecards.append({
            "configuration": alias,
            "sources": [f"r{run}/m{model}" for run, model in sorted(sources[identity])],
            "respondents": len(rates),
            "scored": scored,
            "pass": counts["PASS"],
            "fail": counts["FAIL"],
            "incomplete": counts["INCOMPLETE"],
            "review": counts["REVIEW"],
            "invalid": counts["INVALID"],
            "mean_respondent_pass_rate": (
                round(statistics.mean(rates), 6) if rates else None),
            "respondent_pass_rate_interval95": _cluster_rate_interval(rates),
            "completion_rate": round(scored / attempted, 6) if attempted else None,
        })
    return scorecards


def _exact_sign_pvalue(wins: int, losses: int) -> float | None:
    trials = wins + losses
    if not trials:
        return None
    tail = sum(math.comb(trials, index) for index in range(min(wins, losses) + 1))
    return min(1.0, 2 * tail / (2 ** trials))


def _configuration_comparisons(matrix: dict, models: dict,
                               aliases: dict[str, str]) -> list[dict]:
    by_configuration = defaultdict(lambda: defaultdict(list))
    rows_by_configuration = defaultdict(list)
    respondent_counts = defaultdict(set)
    for respondent, rows in matrix.items():
        identity = models[respondent]
        if any(status in SCORED for status in rows.values()):
            respondent_counts[identity].add(respondent)
            rows_by_configuration[identity].append(rows)
        for item, status in rows.items():
            if status in SCORED:
                by_configuration[identity][item].append(status == "PASS")

    comparisons = []
    identities = sorted(
        aliases, key=lambda identity: int(aliases[identity].removeprefix("C")))
    for left, right in combinations(identities, 2):
        common = sorted(set(by_configuration[left]) & set(by_configuration[right]))
        differences = []
        for item in common:
            left_rate = statistics.mean(by_configuration[left][item])
            right_rate = statistics.mean(by_configuration[right][item])
            differences.append(left_rate - right_rate)
        wins = sum(value > 0 for value in differences)
        losses = sum(value < 0 for value in differences)
        ties = sum(value == 0 for value in differences)
        effect = statistics.mean(differences) if differences else None
        raw_p = _exact_sign_pvalue(wins, losses)
        enough = (
            len(common) >= MIN_COMPARISON_ITEMS
            and len(respondent_counts[left]) >= MIN_CONFIGURATION_RESPONDENTS
            and len(respondent_counts[right]) >= MIN_CONFIGURATION_RESPONDENTS
        )
        comparisons.append({
            "left": aliases[left],
            "right": aliases[right],
            "left_respondents": len(respondent_counts[left]),
            "right_respondents": len(respondent_counts[right]),
            "common_items": len(common),
            "left_item_wins": wins,
            "right_item_wins": losses,
            "item_ties": ties,
            "mean_pass_rate_difference": round(effect, 6) if effect is not None else None,
            "difference_interval95": (
                _hierarchical_difference_interval(
                    rows_by_configuration[left], rows_by_configuration[right], common,
                    f"comparison:{left}:{right}")
                if enough else None),
            "sign_test_p_raw": round(raw_p, 6) if raw_p is not None else None,
            "sign_test_p_holm": None,
            "classification": "INSUFFICIENT" if not enough else "UNCERTAIN",
        })

    eligible = [(index, _exact_sign_pvalue(
                    row["left_item_wins"], row["right_item_wins"]))
                for index, row in enumerate(comparisons)
                if row["classification"] != "INSUFFICIENT"
                and row["sign_test_p_raw"] is not None]
    previous = 0.0
    for rank, (index, p_value) in enumerate(
            sorted(eligible, key=lambda pair: (pair[1], pair[0])), 1):
        adjusted = min(1.0, max(previous, p_value * (len(eligible) - rank + 1)))
        previous = adjusted
        row = comparisons[index]
        row["sign_test_p_holm"] = round(adjusted, 6)
        interval = row["difference_interval95"]
        if adjusted < 0.05 and interval is not None:
            difference = row["mean_pass_rate_difference"]
            if difference > 0 and interval["low"] > 0:
                row["classification"] = "LEFT_HIGHER"
            elif difference < 0 and interval["high"] < 0:
                row["classification"] = "RIGHT_HIGHER"
    return comparisons


def analyze_runs(run_dirs: list[Path], panel_max_items: int | None = None) -> dict:
    if panel_max_items is not None and (
            isinstance(panel_max_items, bool) or not isinstance(panel_max_items, int)
            or panel_max_items < 1):
        raise ValueError("panel max items must be a positive integer")
    groups = collect_observations(run_dirs)
    analyses = []
    for (round_number, pack), group in sorted(groups.items()):
        matrix = group["matrix"]
        aliases = _configuration_aliases(matrix, group["models"])
        relationships = _item_relationships(matrix)
        coverage = _configuration_item_coverage(
            matrix, group["models"], aliases)
        panel = _discriminative_item_panel(
            coverage, relationships, panel_max_items)
        analyses.append({
            "round": round_number,
            "pack": pack,
            "respondents": len(matrix),
            "model_configurations": len(set(group["models"].values())),
            "pairwise": _pairwise_stability(matrix, group["models"]),
            "configurations": _configuration_scorecards(
                matrix, group["models"], aliases),
            "configuration_comparisons": _configuration_comparisons(
                matrix, group["models"], aliases),
            "items": _item_metrics(matrix),
            "item_relationships": relationships,
            "item_repeat_separation": _item_repeat_separation(
                matrix, group["models"]),
            "configuration_item_coverage": coverage,
            "discriminative_item_panel": panel,
            "panel_holdout_validation": _panel_holdout_validation(
                matrix, group["models"], aliases, panel_max_items),
        })
    return {"schema_version": 10, "source_runs": len(run_dirs), "groups": analyses}


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}%"


def _estimate_interval(value: float | None, interval: dict | None,
                       *, percent: bool = False) -> str:
    estimate = _percent(value) if percent else ("n/a" if value is None else str(value))
    if interval is None:
        return estimate
    low = _percent(interval["low"]) if percent else str(interval["low"])
    high = _percent(interval["high"]) if percent else str(interval["high"])
    return f"{estimate} [{low}–{high}]"


def render_analysis(analysis: dict) -> str:
    lines = [
        "# LLM Hardtest Calibration Analysis", "",
        f"Analyzed local run directories: **{analysis['source_runs']}**. Raw prompts, model",
        "responses, paths, model identifiers, and credentials are not copied into this report.",
        "Results are separated by exact benchmark pack fingerprint.", "",
    ]
    for group in analysis["groups"]:
        pairwise = group["pairwise"]
        comparisons = group["configuration_comparisons"]
        relationships = group["item_relationships"]
        repeat_separation = group["item_repeat_separation"]
        item_coverage = group["configuration_item_coverage"]
        panel = group["discriminative_item_panel"]
        holdout = group["panel_holdout_validation"]
        decisive = sum(row["classification"] in {"LEFT_HIGHER", "RIGHT_HIGHER"}
                       for row in comparisons)
        lines += [
            f"## Round {group['round']} — `{group['pack']}`", "",
            f"Respondents: **{group['respondents']}**; distinct model configurations: "
            f"**{group['model_configurations']}**.", "",
            f"- Between-configuration disagreement: "
            f"{_percent(pairwise['between_configuration_disagreement'])} "
            f"across {pairwise['between_configuration_pairs']} comparable pair(s).",
            f"- Within-configuration repeat disagreement: "
            f"{_percent(pairwise['within_configuration_disagreement'])} "
            f"across {pairwise['within_configuration_pairs']} comparable pair(s).",
            f"- Net separation (between minus within): {_percent(pairwise['net_separation'])}.", "",
            "### Configuration scorecards", "",
            "Aliases follow first appearance in the supplied run/config order and do not copy",
            "private model labels or endpoints into this analysis.", "",
            "| Config | Input source(s) | Respondents | Scored | Mean respondent pass | 95% interval | Completion | Incomplete | Review | Invalid |",
            "|---|---|---:|---:|---:|---|---:|---:|---:|---:|",
        ]
        for row in group["configurations"]:
            interval = row["respondent_pass_rate_interval95"]
            interval_text = (f"{_percent(interval['low'])}–{_percent(interval['high'])}"
                             if interval else "withheld")
            lines.append(
                f"| {row['configuration']} | {', '.join(row['sources'])} | "
                f"{row['respondents']} | {row['scored']} | "
                f"{_percent(row['mean_respondent_pass_rate'])} | {interval_text} | "
                f"{_percent(row['completion_rate'])} | {row['incomplete']} | "
                f"{row['review']} | {row['invalid']} |")
        lines += [
            "", "### Head-to-head configuration evidence", "",
            f"Decisive after Holm correction: **{decisive}/{len(comparisons)}** comparison(s).", "",
            "| Left | Right | Respondents | Common items | Item W–L–T | Mean difference | 95% interval | Holm p | Result |",
            "|---|---|---:|---:|---:|---:|---|---:|---|",
        ]
        for row in comparisons:
            interval = row["difference_interval95"]
            interval_text = (f"{_percent(interval['low'])}–{_percent(interval['high'])}"
                             if interval else "withheld")
            p_value = row["sign_test_p_holm"]
            lines.append(
                f"| {row['left']} | {row['right']} | "
                f"{row['left_respondents']}/{row['right_respondents']} | "
                f"{row['common_items']} | {row['left_item_wins']}–"
                f"{row['right_item_wins']}–{row['item_ties']} | "
                f"{_percent(row['mean_pass_rate_difference'])} | {interval_text} | "
                f"{p_value if p_value is not None else 'n/a'} | "
                f"{row['classification']} |")
        coverage_comparisons = item_coverage["comparisons"]
        decisive_details = [
            (pair, item)
            for pair in coverage_comparisons
            for item in pair["items"]
            if item["classification"] in {"LEFT_HIGHER", "RIGHT_HIGHER"}
        ]
        lines += [
            "", "### Pair-specific item coverage", "",
            f"Eligible configuration pairs: **{item_coverage['eligible_configuration_pairs']}**; "
            f"decisive item splits: **{len(decisive_details)}**.", "",
            "| Left | Right | Eligible items | Decisive items | Family alpha | Valid bootstrap | Result |",
            "|---|---|---:|---:|---:|---:|---|",
        ]
        for pair in coverage_comparisons:
            interval = pair["interval"]
            lines.append(
                f"| {pair['left']} | {pair['right']} | {pair['eligible_items']} | "
                f"{pair['decisive_items']} | "
                f"{pair['familywise_alpha'] if pair['familywise_alpha'] is not None else 'n/a'} | "
                f"{interval['valid_samples'] if interval else 'n/a'} | "
                f"{pair['classification']} |")
        if not coverage_comparisons:
            lines.append("| none | none | 0 | 0 | n/a | n/a | INSUFFICIENT |")
        lines += [
            "", "Decisive item details (first 20):", "",
            "| Pair | Item | Independent units | Pass-rate difference [simultaneous interval] | Result |",
            "|---|---|---:|---:|---|",
        ]
        for pair, item in decisive_details[:20]:
            interval = item["simultaneous_interval"]
            estimate = _estimate_interval(
                item["pass_rate_difference"], interval, percent=True)
            lines.append(
                f"| {pair['left']} ↔ {pair['right']} | {item['item']} | "
                f"{item['left_independent_units']}/{item['right_independent_units']} | "
                f"{estimate} | {item['classification']} |")
        if not decisive_details:
            lines.append("| none | none | 0/0 | n/a | n/a |")
        if len(decisive_details) > 20:
            lines += ["", "Only the first 20 decisive splits are shown; JSON retains "
                      "all eligible item/configuration-pair results."]
        lines += [
            "", "### Discriminative item panel", "",
            f"Status: **{panel['status']}** · selected items: "
            f"**{len(panel['selected_items'])}/{panel['candidate_items']}** · "
            f"directional targets covered: **{panel['covered_directional_targets']}/"
            f"{panel['directional_targets']}** · robust dependency pairs considered: "
            f"**{panel['robust_dependency_pairs_considered']}**.", "",
            "| Item | Newly covered directions | All confirmed directions | Minimum simultaneous margin | Maximum effect | Robust dependency degree | Dependency with earlier selection |",
            "|---|---|---|---:|---:|---:|---|",
        ]
        for row in panel["selected_items"]:
            lines.append(
                f"| {row['item']} | {', '.join(row['new_directional_targets'])} | "
                f"{', '.join(row['all_directional_targets'])} | "
                f"{_percent(row['minimum_simultaneous_margin'])} | "
                f"{_percent(row['maximum_absolute_effect'])} | "
                f"{row['robust_dependency_degree']} | "
                f"{', '.join(row['robustly_dependent_with_selected']) or 'none'} |")
        if not panel["selected_items"]:
            lines.append("| none | none | none | n/a | n/a | 0 | none |")
        if panel["uncovered_directional_targets"]:
            lines += ["", "Uncovered directional targets: "
                      + ", ".join(panel["uncovered_directional_targets"]) + "."]
        lines += [
            "", "### Out-of-fold panel validation", "",
            f"Status: **{holdout['status']}** · folds evaluated: "
            f"**{holdout['folds_evaluated']}/2** · confirmed/weak/reversed: "
            f"**{holdout['confirmed_direction_evaluations']}/"
            f"{holdout['weak_direction_evaluations']}/"
            f"{holdout['reversed_direction_evaluations']}** · direction confirmation: "
            f"**{_percent(holdout['direction_confirmation_rate'])}** · selection Jaccard: "
            f"**{holdout['selection_jaccard'] if holdout['selection_jaccard'] is not None else 'n/a'}**.",
            "",
            "| Fold | Training panel | Selected items | Direction | Holdout units | Holdout difference | Holm p | Result |",
            "|---:|---|---|---|---:|---:|---:|---|",
        ]
        for fold in holdout["folds"]:
            if not fold["holdout_evaluations"]:
                lines.append(
                    f"| {fold['fold']} | {fold['training_panel_status']} | "
                    f"{', '.join(fold['selected_items']) or 'none'} | none | 0/0 | n/a | n/a | INSUFFICIENT |")
            for row in fold["holdout_evaluations"]:
                lines.append(
                    f"| {fold['fold']} | {fold['training_panel_status']} | "
                    f"{row['item']} | {row['directional_target']} | "
                    f"{row['higher_holdout_units']}/{row['lower_holdout_units']} | "
                    f"{_percent(row['holdout_pass_rate_difference'])} | "
                    f"{row['permutation_p_holm'] if row['permutation_p_holm'] is not None else 'n/a'} | "
                    f"{row['classification']} |")
        lines += [
            "", "### Item diagnostics", "",
            "| Item | Scored | Independent units | Pass raw | Clustered pass [95%] | Balance raw / clustered | Corrected discrimination (raw) | Clustered corrected discrimination [95%] | "
            "Observed signal | Robust signal | Incomplete | Review | Invalid | Missing |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---:|---:|---:|",
        ]
        for item in group["items"]:
            discrimination = item["corrected_item_total_correlation"]
            clustered = item["clustered_corrected_discrimination"]
            lines.append(
                f"| {item['item']} | {item['scored']} | {item['independent_units']} | "
                f"{_percent(item['pass_rate'])} | "
                f"{_estimate_interval(item['clustered_pass_rate'], item['pass_rate_interval95'], percent=True)} | "
                f"{item['difficulty_balance'] if item['difficulty_balance'] is not None else 'n/a'} / "
                f"{item['clustered_difficulty_balance'] if item['clustered_difficulty_balance'] is not None else 'n/a'} | "
                f"{discrimination if discrimination is not None else 'n/a'} | "
                f"{_estimate_interval(clustered, item['discrimination_interval95'])} | "
                f"{item['classification']} | {item['robust_classification']} | "
                f"{item['incomplete']} | {item['review']} | {item['invalid']} | "
                f"{item['missing']} |")
        candidates = [row for row in relationships
                      if row["classification"] in {
                          "REDUNDANCY_CANDIDATE", "OPPOSING_CANDIDATE", "RELATED"}
                      or row["robust_classification"] in {
                          "ROBUST_REDUNDANCY_CANDIDATE",
                          "ROBUST_OPPOSING_CANDIDATE"}]
        displayed = candidates[:20]
        robust_redundant = sum(
            row["robust_classification"] == "ROBUST_REDUNDANCY_CANDIDATE"
            for row in relationships)
        lines += [
            "", "### Item dependency diagnostics", "",
            f"Empirical relationship candidates: **{len(candidates)}/{len(relationships)}**; "
            f"robust redundancy candidates: **{robust_redundant}**.", "",
            "| Items | Common | Independent units | Agreement raw / clustered | Phi raw | Clustered phi [95%] | Observed | Robust |",
            "|---|---:|---:|---:|---:|---:|---|---|",
        ]
        for row in displayed:
            lines.append(
                f"| {row['left']} ↔ {row['right']} | {row['common_scored']} | "
                f"{row['independent_units']} | {_percent(row['outcome_agreement'])} / "
                f"{_percent(row['clustered_outcome_agreement'])} | "
                f"{row['phi_correlation'] if row['phi_correlation'] is not None else 'n/a'} | "
                f"{_estimate_interval(row['clustered_phi_correlation'], row['correlation_interval95'])} | "
                f"{row['classification']} | {row['robust_classification']} |")
        if len(candidates) > len(displayed):
            lines += ["", f"The table shows the first {len(displayed)} ranked candidates; "
                      "the JSON artifact retains every item pair."]
        if not displayed:
            lines.append("| none | 0 | 0 | n/a | n/a | n/a | n/a | n/a |")
        robust_separating = sum(
            row["robust_classification"] == "ROBUST_SEPARATING"
            for row in repeat_separation)
        lines += [
            "", "### Repeat-adjusted item separation", "",
            f"Robustly separating items: **{robust_separating}/{len(repeat_separation)}**.",
            "",
            "| Item | Configs / repeated / robust | Independent units | Between separation | Repeat instability | Net separation | Robust net [95%] | Observed | Robust |",
            "|---|---:|---:|---:|---:|---:|---:|---|---|",
        ]
        for row in repeat_separation:
            lines.append(
                f"| {row['item']} | {row['configurations']}/"
                f"{row['repeat_configurations']}/{row['robust_configurations']} | "
                f"{row['independent_units']} | "
                f"{_percent(row['between_configuration_separation'])} | "
                f"{_percent(row['within_configuration_instability'])} | "
                f"{_percent(row['net_repeat_adjusted_separation'])} | "
                f"{_estimate_interval(row['robust_net_repeat_adjusted_separation'], row['net_separation_interval95'], percent=True)} | "
                f"{row['classification']} | {row['robust_classification']} |")
        lines += ["",]
    lines += [
        "## Interpretation", "",
        f"- Item classifications require at least {MIN_ITEM_OBSERVATIONS} scored observations.",
        f"- Robust item classifications require at least {MIN_ITEM_INTERVAL_OBSERVATIONS}",
        "  independent units and a cluster bootstrap with at least 80% defined draws.",
        "- Difficulty balance is `4p(1-p)`: 1.0 at a 50% pass rate and 0.0 at",
        "  unanimous pass/fail. It is not an item-response-theory information estimate.",
        "- `CEILING` and `FLOOR` items add little separation in the observed sample.",
        "- `NEGATIVE` discrimination is a review trigger for ambiguity, grading defects,",
        "  multidimensional skills, or sampling noise; it is not automatic proof of a bad item.",
        "- `ROBUST_USEFUL` requires the discrimination interval to stay at or above 0.15;",
        "  `ROBUST_NEGATIVE` requires it to remain below zero. Other non-extreme items are",
        "  `UNCERTAIN` or `UNSTABLE`, so point estimates alone cannot drive pack changes.",
        f"- Item dependency candidates use phi correlation. `{ITEM_REDUNDANCY_THRESHOLD}` is",
        "  a deliberately high empirical-overlap threshold, not proof that two prompts test",
        "  the same construct. Robust candidates require the entire cluster-bootstrap interval",
        "  beyond that threshold and still require content review before removal.",
        "- Opposing candidates may reveal complementary skills, ambiguity, or grader polarity.",
        "  The Markdown table is capped at 20 candidates; JSON retains every pair.",
        "- Repeat-adjusted item separation compares equal-weight configuration pass-rate",
        "  differences with same-configuration cluster disagreement on that item. Both",
        "  observed estimates require two configurations with repeats.",
        f"- `ROBUST_SEPARATING` requires at least {MIN_CONFIGURATION_RESPONDENTS} independent",
        "  units for each of two configurations and the complete bootstrap interval at or",
        f"  above {ITEM_NET_SEPARATION_THRESHOLD}. `ROBUST_NOISE_DOMINATED` requires the",
        "  interval below zero. `ROBUST_NO_SEPARATION` means every eligible repeat had",
        "  the same outcome across configurations. Other cases remain uncertain or insufficient.",
        f"- Pair-specific item coverage requires {MIN_CONFIGURATION_RESPONDENTS} independent",
        "  units per configuration and preserves all item outcomes within a resampled cluster.",
        "  A maximum-error bootstrap makes intervals simultaneous across items in each pair;",
        "  Bonferroni allocation across eligible configuration pairs targets family-wise 95%",
        f"  coverage. Directional labels also require an absolute effect of {ITEM_PAIR_EFFECT_THRESHOLD}.",
        "- The discriminative panel greedily covers confirmed pair directions, preferring",
        "  fewer selected conflicts, lower total robust dependency degree, and stronger",
        "  simultaneous margins when coverage ties. It is deterministic but not guaranteed",
        "  globally minimal. A budget-limited",
        "  partial panel exposes every uncovered direction and never mutates a benchmark pack.",
        "- Out-of-fold panel validation selects a panel on one deterministic half of",
        "  independent units and evaluates its directional effects only on the other half.",
        f"  Each side needs {MIN_CONFIGURATION_RESPONDENTS} units per configuration; shared",
        "  public bundles remain in one fold. `REVERSED_SIGNAL` is direct evidence that a",
        "  selected direction did not replicate, while `INSUFFICIENT` is not a pass.",
        "  Confirmation additionally requires a two-sided label-permutation p-value below",
        "  0.05 after Holm correction across every tested held-out direction.",
        f"- Pair comparisons require at least {MIN_PAIR_ITEMS} commonly scored items.",
        "- Between-configuration disagreement measures observed separation. Within-configuration",
        "  disagreement measures repeat instability. Net separation requires both.",
        f"- Head-to-head inference requires at least {MIN_COMPARISON_ITEMS} common items and",
        f"  {MIN_CONFIGURATION_RESPONDENTS} scored respondents per configuration. It compares",
        "  item-level pass-rate differences, uses an exact two-sided sign test, and applies",
        "  Holm family-wise correction across all eligible configuration pairs.",
        "- Scorecard intervals use a conservative Wilson-style calculation across respondent",
        "  rates. Head-to-head intervals use a deterministic hierarchical bootstrap over both",
        "  respondents and common items, so repeat instability widens the effect interval.",
        "  Directional claims require both a Holm-adjusted p < 0.05 and an interval excluding 0.",
        "- These descriptive diagnostics are not an IRT fit, causal attribution, or a score",
        "  prediction for an untested model.", "",
    ]
    return "\n".join(lines)


def write_analysis(run_dirs: list[Path], output: Path,
                   panel_max_items: int | None = None) -> tuple[Path, Path, dict]:
    if output.suffix.lower() != ".md":
        raise ValueError("analysis output must use a .md extension")
    analysis = analyze_runs(run_dirs, panel_max_items)
    json_path = output.with_suffix(".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_analysis(analysis), encoding="utf-8")
    json_path.write_text(json.dumps(analysis, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    return output, json_path, analysis
