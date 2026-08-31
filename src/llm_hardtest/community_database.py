from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import statistics
import tempfile
from collections import defaultdict
from pathlib import Path

from .community_results import (
    _cluster_interval, _configuration_id, _percentile, _recommend_aggregate_rows,
    load_submission_directory,
)
from .serving_catalog import build_catalog
from .collection_plan import build_collection_plan
from .public_results import (
    FINGERPRINT, MODEL_PARAMETER_FIELDS, PUBLIC_ITEM_STATUSES,
    PUBLIC_METADATA_FIELDS, PUBLIC_METADATA_NUMERIC_FIELDS, _public_text,
)


DATABASE_SCHEMA_VERSION = 2
DATABASE_APPLICATION_ID = 0x4C484452  # "LHDR"
DATABASE_KIND = "validated_public_observation_database"
DATABASE_FINGERPRINT_METHOD = "canonical_relational_rows_numeric_v2"

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE dataset_metadata (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_version INTEGER NOT NULL,
    kind TEXT NOT NULL,
    fingerprint_method TEXT NOT NULL,
    content_fingerprint TEXT NOT NULL,
    bundle_count INTEGER NOT NULL,
    configuration_count INTEGER NOT NULL,
    benchmark_run_count INTEGER NOT NULL,
    item_observation_count INTEGER NOT NULL,
    task_observation_count INTEGER NOT NULL
);

CREATE TABLE bundles (
    bundle_id TEXT PRIMARY KEY,
    public_schema_version INTEGER NOT NULL,
    tool_name TEXT NOT NULL,
    tool_version TEXT NOT NULL,
    os TEXT NOT NULL,
    architecture TEXT NOT NULL,
    python TEXT NOT NULL,
    submission_mode TEXT NOT NULL
);

CREATE TABLE configurations (
    configuration_id TEXT PRIMARY KEY,
    public_name TEXT NOT NULL,
    transport TEXT NOT NULL,
    os TEXT NOT NULL,
    architecture TEXT NOT NULL,
    python TEXT NOT NULL,
    reasoning_effort TEXT,
    context_window REAL,
    max_tokens REAL,
    temperature REAL,
    top_p REAL,
    top_k REAL,
    min_p REAL,
    model_revision TEXT,
    quantization TEXT,
    model_format TEXT,
    parameter_count_b REAL,
    server TEXT,
    server_version TEXT,
    accelerator TEXT,
    accelerator_count REAL,
    memory_gb REAL,
    system_memory_gb REAL,
    parameters_json TEXT NOT NULL,
    public_metadata_json TEXT NOT NULL
);

CREATE TABLE benchmark_runs (
    run_id TEXT PRIMARY KEY,
    bundle_id TEXT NOT NULL REFERENCES bundles(bundle_id),
    configuration_id TEXT NOT NULL REFERENCES configurations(configuration_id),
    model_ordinal INTEGER NOT NULL,
    round INTEGER NOT NULL CHECK (round BETWEEN 1 AND 4),
    pack TEXT NOT NULL,
    scored_passed REAL,
    scored_total REAL,
    incomplete REAL,
    manual_review REAL,
    infrastructure_errors REAL,
    mean_wall_seconds REAL,
    metrics_json TEXT NOT NULL,
    UNIQUE (bundle_id, model_ordinal, round)
);

CREATE TABLE item_observations (
    observation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES benchmark_runs(run_id),
    item TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    status TEXT NOT NULL,
    wall_seconds REAL,
    completion_tokens INTEGER,
    UNIQUE (run_id, item, attempt)
);

CREATE TABLE task_observations (
    observation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES benchmark_runs(run_id),
    task_ordinal INTEGER NOT NULL,
    task TEXT NOT NULL,
    attempt INTEGER,
    public_passed REAL,
    public_total REAL,
    hidden_passed REAL,
    hidden_total REAL,
    auto_score REAL,
    release_ready INTEGER,
    handoff_utility INTEGER,
    false_green INTEGER,
    tampering INTEGER,
    timed_out INTEGER,
    wall_seconds REAL,
    completion_tokens INTEGER,
    UNIQUE (run_id, task_ordinal)
);

CREATE INDEX benchmark_runs_lookup
    ON benchmark_runs(round, pack, configuration_id);
CREATE INDEX benchmark_runs_bundle
    ON benchmark_runs(bundle_id);
CREATE INDEX item_observations_run_status
    ON item_observations(run_id, status);
CREATE INDEX task_observations_run_release
    ON task_observations(run_id, release_ready);
"""

TABLE_COLUMNS = {
    "bundles": (
        "bundle_id", "public_schema_version", "tool_name", "tool_version",
        "os", "architecture", "python", "submission_mode"),
    "configurations": (
        "configuration_id", "public_name", "transport", "os", "architecture",
        "python", "reasoning_effort", "context_window", "max_tokens",
        "temperature", "top_p", "top_k", "min_p", "model_revision",
        "quantization", "model_format", "parameter_count_b", "server",
        "server_version", "accelerator", "accelerator_count", "memory_gb",
        "system_memory_gb", "parameters_json", "public_metadata_json"),
    "benchmark_runs": (
        "run_id", "bundle_id", "configuration_id", "model_ordinal", "round",
        "pack", "scored_passed", "scored_total", "incomplete", "manual_review",
        "infrastructure_errors", "mean_wall_seconds", "metrics_json"),
    "item_observations": (
        "observation_id", "run_id", "item", "attempt", "status",
        "wall_seconds", "completion_tokens"),
    "task_observations": (
        "observation_id", "run_id", "task_ordinal", "task", "attempt",
        "public_passed", "public_total", "hidden_passed", "hidden_total",
        "auto_score", "release_ready", "handoff_utility", "false_green",
        "tampering", "timed_out", "wall_seconds", "completion_tokens"),
}

REAL_COLUMNS = {
    "configurations": {
        "context_window", "max_tokens", "temperature", "top_p", "top_k",
        "min_p", "parameter_count_b", "accelerator_count", "memory_gb",
        "system_memory_gb",
    },
    "benchmark_runs": {
        "scored_passed", "scored_total", "incomplete", "manual_review",
        "infrastructure_errors", "mean_wall_seconds",
    },
    "item_observations": {"wall_seconds"},
    "task_observations": {
        "public_passed", "public_total", "hidden_passed", "hidden_total",
        "auto_score", "wall_seconds",
    },
}


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _stable_id(kind: str, *parts: object) -> str:
    encoded = _canonical([kind, *parts]).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _optional_boolean(value: object) -> int | None:
    return None if value is None else int(bool(value))


def normalize_submissions(submissions: list[dict]) -> dict[str, list[tuple]]:
    """Map validated public bundles to deterministic relational rows."""
    rows: dict[str, list[tuple]] = {table: [] for table in TABLE_COLUMNS}
    configurations: dict[str, tuple] = {}
    for payload in sorted(submissions, key=lambda value: value["bundle_id"]):
        environment = payload["environment"]
        rows["bundles"].append((
            payload["bundle_id"], payload["schema_version"],
            payload["tool"]["name"], payload["tool"]["version"],
            environment["os"], environment["architecture"],
            environment["python"], payload["privacy"]["submission_mode"],
        ))
        for model_ordinal, model in enumerate(payload["models"], 1):
            configuration_id = _configuration_id(payload, model)
            parameters = model["parameters"]
            metadata = model["public_metadata"]
            configuration = (
                configuration_id, model["public_name"], model["transport"],
                environment["os"], environment["architecture"],
                environment["python"], parameters.get("reasoning_effort"),
                parameters.get("context_window"), parameters.get("max_tokens"),
                parameters.get("temperature"), parameters.get("top_p"),
                parameters.get("top_k"), parameters.get("min_p"),
                metadata.get("model_revision"), metadata.get("quantization"),
                metadata.get("model_format"), metadata.get("parameter_count_b"),
                metadata.get("server"), metadata.get("server_version"),
                metadata.get("accelerator"), metadata.get("accelerator_count"),
                metadata.get("memory_gb"), metadata.get("system_memory_gb"),
                _canonical(parameters), _canonical(metadata),
            )
            previous = configurations.setdefault(configuration_id, configuration)
            if previous != configuration:
                raise ValueError("public configuration ID collision")
            for round_text, metrics in sorted(model["rounds"].items()):
                round_number = int(round_text)
                pack = payload["benchmark"]["packs"][round_text]
                run_id = _stable_id(
                    "benchmark-run", payload["bundle_id"], configuration_id,
                    model_ordinal, round_number, pack)
                passed_key, total_key = (("release_ready", "attempts")
                                         if round_number == 4
                                         else ("passed", "total"))
                summary = {key: value for key, value in metrics.items()
                           if key not in {"items", "tasks"}}
                rows["benchmark_runs"].append((
                    run_id, payload["bundle_id"], configuration_id, model_ordinal,
                    round_number, pack, metrics.get(passed_key),
                    metrics.get(total_key), metrics.get("incomplete"),
                    metrics.get("manual_review"),
                    metrics.get("infrastructure_errors"),
                    metrics.get("mean_wall_seconds"), _canonical(summary),
                ))
                for item in metrics.get("items", []):
                    observation_id = _stable_id(
                        "item-observation", run_id, item["item"], item["attempt"])
                    rows["item_observations"].append((
                        observation_id, run_id, item["item"], item["attempt"],
                        item["status"], item["wall_seconds"], item["tokens"],
                    ))
                for task_ordinal, task in enumerate(metrics.get("tasks", []), 1):
                    observation_id = _stable_id(
                        "task-observation", run_id, task_ordinal,
                        task["task"], task.get("attempt"))
                    rows["task_observations"].append((
                        observation_id, run_id, task_ordinal, task["task"],
                        task.get("attempt"),
                        task.get("public_passed"), task.get("public_total"),
                        task.get("hidden_passed"), task.get("hidden_total"),
                        task.get("auto_score"),
                        _optional_boolean(task.get("release_ready")),
                        _optional_boolean(task.get("handoff_utility")),
                        _optional_boolean(task.get("false_green")),
                        _optional_boolean(task.get("tampering")),
                        _optional_boolean(task.get("timed_out")),
                        task.get("wall_seconds"), task.get("tokens"),
                    ))
    rows["configurations"] = list(configurations.values())
    for table in rows:
        rows[table].sort(key=lambda row: row[0])
    return rows


def _content_fingerprint(rows: dict[str, list[tuple]]) -> str:
    content = {}
    for table in sorted(rows):
        real_indices = {
            TABLE_COLUMNS[table].index(column)
            for column in REAL_COLUMNS.get(table, set())
        }
        content[table] = [
            tuple(float(value) if index in real_indices and value is not None else value
                  for index, value in enumerate(row))
            for row in rows[table]
        ]
    return "sha256:" + hashlib.sha256(
        _canonical(content).encode("utf-8")).hexdigest()


def _metadata_row(rows: dict[str, list[tuple]]) -> tuple:
    return (
        1, DATABASE_SCHEMA_VERSION, DATABASE_KIND, DATABASE_FINGERPRINT_METHOD,
        _content_fingerprint(rows),
        len(rows["bundles"]), len(rows["configurations"]),
        len(rows["benchmark_runs"]), len(rows["item_observations"]),
        len(rows["task_observations"]),
    )


def _read_rows(connection: sqlite3.Connection) -> dict[str, list[tuple]]:
    result = {}
    for table, columns in TABLE_COLUMNS.items():
        selected = ", ".join(columns)
        result[table] = connection.execute(
            f"SELECT {selected} FROM {table} ORDER BY {columns[0]}"
        ).fetchall()
    return result


def _schema_manifest(connection: sqlite3.Connection) -> list[tuple]:
    return connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()


def _expected_schema_manifest() -> list[tuple]:
    reference = sqlite3.connect(":memory:")
    reference.executescript(SCHEMA_SQL)
    manifest = _schema_manifest(reference)
    reference.close()
    return manifest


def load_database(path: Path) -> dict[str, list[tuple]]:
    """Read a self-consistent schema-v2 observation database in read-only mode."""
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"community database does not exist as a regular file: {path}")
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        connection.execute("PRAGMA trusted_schema = OFF")
        connection.execute("PRAGMA query_only = ON")
        application_id = connection.execute("PRAGMA application_id").fetchone()[0]
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        schema_manifest = _schema_manifest(connection)
        if (application_id != DATABASE_APPLICATION_ID
                or user_version != DATABASE_SCHEMA_VERSION):
            raise ValueError("community database schema identity is invalid")
        if schema_manifest != _expected_schema_manifest():
            raise ValueError(
                f"community database schema does not match schema v{DATABASE_SCHEMA_VERSION}")
        if integrity != "ok" or foreign_keys:
            raise ValueError("community database integrity check failed")
        actual = _read_rows(connection)
        metadata = connection.execute(
            "SELECT * FROM dataset_metadata WHERE singleton = 1").fetchone()
    except sqlite3.Error as exc:
        raise ValueError(f"invalid community database: {path}") from exc
    finally:
        if "connection" in locals():
            connection.close()
    if metadata != _metadata_row(actual):
        raise ValueError(
            "community database is stale or internally inconsistent; rebuild it")
    _validate_relational_semantics(actual)
    return actual


def _validate_database(path: Path, expected: dict[str, list[tuple]]) -> None:
    actual = load_database(path)
    if actual != expected:
        raise ValueError(f"community database is stale; rebuild {path}")


def _row_dicts(rows: dict[str, list[tuple]], table: str) -> list[dict]:
    columns = TABLE_COLUMNS[table]
    return [dict(zip(columns, row)) for row in rows[table]]


def _validate_relational_semantics(rows: dict[str, list[tuple]]) -> None:
    def valid_nonnegative_number(value: object, *, optional: bool = True) -> bool:
        return ((optional and value is None)
                or (not isinstance(value, bool) and isinstance(value, (int, float))
                    and math.isfinite(value) and value >= 0))

    def valid_fingerprint(value: object) -> bool:
        return isinstance(value, str) and FINGERPRINT.fullmatch(value) is not None

    def valid_python(value: object) -> bool:
        return isinstance(value, str) and re.fullmatch(r"[0-9]+\.[0-9]+", value) is not None

    bundles = {row["bundle_id"]: row for row in _row_dicts(rows, "bundles")}
    for bundle in bundles.values():
        if (not valid_fingerprint(bundle["bundle_id"])
                or bundle["public_schema_version"] not in {1, 2}
                or bundle["tool_name"] != "llm-hardtest-report"
                or _public_text(bundle["tool_version"], maximum=32) is None
                or bundle["os"] not in {"Linux", "Darwin", "Windows", "Other"}
                or _public_text(bundle["architecture"], maximum=32) is None
                or not valid_python(bundle["python"])
                or bundle["submission_mode"] != "explicit-opt-in"):
            raise ValueError("community database contains an invalid bundle row")

    configurations = {}
    for configuration in _row_dicts(rows, "configurations"):
        try:
            parameters = json.loads(configuration["parameters_json"])
            metadata = json.loads(configuration["public_metadata_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(
                "community database contains invalid configuration JSON") from exc
        if (not isinstance(parameters, dict) or not isinstance(metadata, dict)
                or _canonical(parameters) != configuration["parameters_json"]
                or _canonical(metadata) != configuration["public_metadata_json"]
                or set(parameters) - MODEL_PARAMETER_FIELDS
                or set(metadata) - PUBLIC_METADATA_FIELDS
                or _public_text(configuration["public_name"]) is None
                or configuration["transport"] not in {"openai_compat", "codex_cli"}
                or configuration["os"] not in {"Linux", "Darwin", "Windows", "Other"}
                or _public_text(configuration["architecture"], maximum=32) is None
                or not valid_python(configuration["python"])):
            raise ValueError("community database contains an invalid configuration row")
        for key, value in parameters.items():
            if key == "reasoning_effort":
                valid = _public_text(value, maximum=32) is not None
            else:
                valid = (not isinstance(value, bool)
                         and isinstance(value, (int, float)) and math.isfinite(value))
            if not valid or configuration[key] != value:
                raise ValueError("community database configuration parameters disagree")
        for key in MODEL_PARAMETER_FIELDS - set(parameters):
            if configuration[key] is not None:
                raise ValueError("community database has an undeclared parameter")
        for key, value in metadata.items():
            if key in PUBLIC_METADATA_NUMERIC_FIELDS:
                valid = (not isinstance(value, bool)
                         and isinstance(value, (int, float))
                         and math.isfinite(value) and value > 0)
            else:
                valid = _public_text(value) is not None
            if not valid or configuration[key] != value:
                raise ValueError("community database serving metadata disagrees")
        for key in PUBLIC_METADATA_FIELDS - set(metadata):
            if configuration[key] is not None:
                raise ValueError("community database has undeclared serving metadata")
        identity_payload = {"environment": {
            "os": configuration["os"],
            "architecture": configuration["architecture"],
            "python": configuration["python"],
        }}
        identity_model = {
            "public_name": configuration["public_name"],
            "transport": configuration["transport"],
            "parameters": parameters,
            "public_metadata": metadata,
        }
        if _configuration_id(identity_payload, identity_model) != configuration[
                "configuration_id"]:
            raise ValueError("community database configuration ID is invalid")
        configurations[configuration["configuration_id"]] = configuration

    runs = {}
    for run in _row_dicts(rows, "benchmark_runs"):
        bundle = bundles.get(run["bundle_id"])
        configuration = configurations.get(run["configuration_id"])
        try:
            metrics = json.loads(run["metrics_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("community database contains invalid run JSON") from exc
        expected_run_id = _stable_id(
            "benchmark-run", run["bundle_id"], run["configuration_id"],
            run["model_ordinal"], run["round"], run["pack"])
        if (bundle is None or configuration is None
                or tuple(bundle[key] for key in ("os", "architecture", "python"))
                != tuple(configuration[key] for key in ("os", "architecture", "python"))
                or not isinstance(run["model_ordinal"], int)
                or run["model_ordinal"] < 1 or not isinstance(run["round"], int)
                or run["round"] not in {1, 2, 3, 4}
                or not valid_fingerprint(run["pack"])
                or run["run_id"] != expected_run_id
                or not isinstance(metrics, dict)
                or _canonical(metrics) != run["metrics_json"]):
            raise ValueError("community database contains an invalid benchmark run")
        passed_key, total_key = (("release_ready", "attempts")
                                 if run["round"] == 4 else ("passed", "total"))
        metric_columns = {
            "scored_passed": passed_key, "scored_total": total_key,
            "incomplete": "incomplete", "manual_review": "manual_review",
            "infrastructure_errors": "infrastructure_errors",
            "mean_wall_seconds": "mean_wall_seconds",
        }
        if any(not valid_nonnegative_number(run[column])
               or run[column] != metrics.get(metric)
               for column, metric in metric_columns.items()):
            raise ValueError("community database run metrics disagree")
        runs[run["run_id"]] = run

    for item in _row_dicts(rows, "item_observations"):
        expected = _stable_id(
            "item-observation", item["run_id"], item["item"], item["attempt"])
        if (item["run_id"] not in runs or _public_text(item["item"], maximum=80) is None
                or not isinstance(item["attempt"], int) or item["attempt"] < 1
                or item["status"] not in PUBLIC_ITEM_STATUSES
                or not valid_nonnegative_number(item["wall_seconds"])
                or (item["completion_tokens"] is not None
                    and (not isinstance(item["completion_tokens"], int)
                         or item["completion_tokens"] < 0))
                or item["observation_id"] != expected):
            raise ValueError("community database contains an invalid item observation")
    for task in _row_dicts(rows, "task_observations"):
        expected = _stable_id(
            "task-observation", task["run_id"], task["task_ordinal"],
            task["task"], task["attempt"])
        if (task["run_id"] not in runs
                or not isinstance(task["task_ordinal"], int)
                or task["task_ordinal"] < 1
                or _public_text(task["task"], maximum=80) is None
                or (task["attempt"] is not None
                    and (not isinstance(task["attempt"], int) or task["attempt"] < 1))
                or any(not valid_nonnegative_number(task[key]) for key in (
                    "public_passed", "public_total", "hidden_passed", "hidden_total",
                    "auto_score", "wall_seconds"))
                or any(task[key] not in {None, 0, 1} for key in (
                    "release_ready", "handoff_utility", "false_green", "tampering",
                    "timed_out"))
                or (task["completion_tokens"] is not None
                    and (not isinstance(task["completion_tokens"], int)
                         or task["completion_tokens"] < 0))
                or task["observation_id"] != expected):
            raise ValueError("community database contains an invalid task observation")


def aggregate_database(rows: dict[str, list[tuple]]) -> list[dict]:
    """Reproduce bundle-clustered community aggregates from normalized rows."""
    configurations = {
        row["configuration_id"]: row
        for row in _row_dicts(rows, "configurations")
    }
    items_by_run = defaultdict(list)
    for item in _row_dicts(rows, "item_observations"):
        items_by_run[item["run_id"]].append(item)
    bundle_groups = defaultdict(lambda: defaultdict(lambda: {
        "runs": 0, "passed": 0, "total": 0, "incomplete": 0,
        "manual_review": 0, "infrastructure_errors": 0,
        "_item_walls": [], "_token_rates": [],
    }))
    identities = {}
    for run in _row_dicts(rows, "benchmark_runs"):
        configuration = configurations[run["configuration_id"]]
        key = (run["round"], run["pack"], configuration["public_name"],
               run["configuration_id"])
        identity = {
            "environment": {
                "os": configuration["os"],
                "architecture": configuration["architecture"],
                "python": configuration["python"],
            },
            "model": configuration["public_name"],
            "transport": configuration["transport"],
            "parameters": json.loads(configuration["parameters_json"]),
            "public_metadata": json.loads(configuration["public_metadata_json"]),
        }
        previous = identities.setdefault(run["configuration_id"], identity)
        if previous != identity:
            raise ValueError("community database configuration identity collision")
        local = bundle_groups[run["bundle_id"]][key]
        local["runs"] += 1
        for target, source in (
                ("passed", "scored_passed"), ("total", "scored_total"),
                ("incomplete", "incomplete"),
                ("manual_review", "manual_review"),
                ("infrastructure_errors", "infrastructure_errors")):
            value = run[source]
            if value is not None:
                local[target] += value
        for item in items_by_run[run["run_id"]]:
            wall = item["wall_seconds"]
            tokens = item["completion_tokens"]
            if wall is not None:
                local["_item_walls"].append(float(wall))
                if wall > 0 and tokens is not None:
                    local["_token_rates"].append(tokens / wall)

    groups = defaultdict(lambda: {
        "submissions": 0, "runs": 0, "passed": 0, "total": 0,
        "incomplete": 0, "manual_review": 0, "infrastructure_errors": 0,
        "_bundle_pass_rates": [], "_bundle_completion_rates": [],
        "_bundle_mean_walls": [], "_bundle_mean_token_rates": [],
    })
    for local_groups in bundle_groups.values():
        for key, local in local_groups.items():
            group = groups[key]
            group["submissions"] += 1
            for field in ("runs", "passed", "total", "incomplete",
                          "manual_review", "infrastructure_errors"):
                group[field] += local[field]
            if local["total"] > 0:
                group["_bundle_pass_rates"].append(
                    local["passed"] / local["total"])
            attempted = (local["total"] + local["incomplete"]
                         + local["manual_review"]
                         + local["infrastructure_errors"])
            if attempted > 0:
                group["_bundle_completion_rates"].append(
                    local["total"] / attempted)
            if local["_item_walls"]:
                group["_bundle_mean_walls"].append(
                    statistics.mean(local["_item_walls"]))
            if local["_token_rates"]:
                group["_bundle_mean_token_rates"].append(
                    statistics.mean(local["_token_rates"]))

    result = []
    for (round_number, pack, model_name, configuration_id), totals in sorted(
            groups.items(), key=lambda item: (
                item[0][0], item[0][2].lower(), item[0][3])):
        identity = identities[configuration_id]
        rates = totals["_bundle_pass_rates"]
        result.append({
            "round": round_number,
            "pack": pack,
            "model": model_name,
            "configuration": configuration_id,
            **identity,
            **{key: value for key, value in totals.items()
               if not key.startswith("_")},
            "observed_submissions": len(rates),
            "bundle_pass_rate_interval95": _cluster_interval(rates),
            "bundle_completion_rate_observed_submissions": len(
                totals["_bundle_completion_rates"]),
            "bundle_completion_rate_interval95": _cluster_interval(
                totals["_bundle_completion_rates"]),
            "bundle_item_wall_p50_seconds": _percentile(
                totals["_bundle_mean_walls"], 0.5),
            "bundle_item_wall_p90_seconds": _percentile(
                totals["_bundle_mean_walls"], 0.9),
            "bundle_item_wall_observed_submissions": len(
                totals["_bundle_mean_walls"]),
            "bundle_tokens_per_second_p50": _percentile(
                totals["_bundle_mean_token_rates"], 0.5),
            "bundle_token_rate_observed_submissions": len(
                totals["_bundle_mean_token_rates"]),
        })
    return result


def recommend_database(path: Path, *, round_number: int,
                       pack: str | None = None,
                       constraints: dict | None = None,
                       objectives: list[str] | None = None,
                       accuracy_floor: float | None = None) -> dict:
    """Query the same gated Pareto shortlist directly from SQLite."""
    return _recommend_aggregate_rows(
        aggregate_database(load_database(path)), round_number=round_number,
        pack=pack, constraints=constraints, objectives=objectives,
        accuracy_floor=accuracy_floor)


def catalog_database(path: Path, *, round_number: int | None = None,
                     pack: str | None = None) -> dict:
    """Build the serving-space catalog directly from a verified SQLite snapshot."""
    return build_catalog(
        aggregate_database(load_database(path)), round_number=round_number, pack=pack)


def plan_database(path: Path, **kwargs) -> dict:
    """Build an acquisition plan directly from a verified SQLite snapshot."""
    return build_collection_plan(aggregate_database(load_database(path)), **kwargs)


def build_database(directory: Path, output: Path, *, check: bool = False) -> dict:
    """Build or verify a normalized SQLite database from canonical submissions."""
    if output.suffix.lower() not in {".sqlite", ".sqlite3", ".db"}:
        raise ValueError("community database output must use .sqlite, .sqlite3, or .db")
    submissions = load_submission_directory(directory)
    rows = normalize_submissions(submissions)
    summary = {
        "schema_version": DATABASE_SCHEMA_VERSION,
        "content_fingerprint": _content_fingerprint(rows),
        "bundles": len(rows["bundles"]),
        "configurations": len(rows["configurations"]),
        "benchmark_runs": len(rows["benchmark_runs"]),
        "item_observations": len(rows["item_observations"]),
        "task_observations": len(rows["task_observations"]),
    }
    if check:
        _validate_database(output, rows)
        return summary

    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        connection = sqlite3.connect(temporary)
        with connection:
            connection.execute(f"PRAGMA application_id = {DATABASE_APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version = {DATABASE_SCHEMA_VERSION}")
            connection.executescript(SCHEMA_SQL)
            for table, columns in TABLE_COLUMNS.items():
                placeholders = ", ".join("?" for _ in columns)
                connection.executemany(
                    f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                    rows[table])
            connection.execute(
                "INSERT INTO dataset_metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                _metadata_row(rows))
        connection.close()
        _validate_database(temporary, rows)
        os.replace(temporary, output)
    finally:
        if "connection" in locals():
            connection.close()
        temporary.unlink(missing_ok=True)
    return summary
