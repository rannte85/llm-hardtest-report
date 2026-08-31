from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path

from .community_results import _configuration_id, load_submission_directory


DATABASE_SCHEMA_VERSION = 1
DATABASE_APPLICATION_ID = 0x4C484452  # "LHDR"
DATABASE_KIND = "validated_public_observation_database"

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE dataset_metadata (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_version INTEGER NOT NULL,
    kind TEXT NOT NULL,
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
    content = {table: rows[table] for table in sorted(rows)}
    return "sha256:" + hashlib.sha256(
        _canonical(content).encode("utf-8")).hexdigest()


def _metadata_row(rows: dict[str, list[tuple]]) -> tuple:
    return (
        1, DATABASE_SCHEMA_VERSION, DATABASE_KIND, _content_fingerprint(rows),
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


def _validate_database(path: Path, expected: dict[str, list[tuple]]) -> None:
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
        metadata = connection.execute(
            "SELECT * FROM dataset_metadata WHERE singleton = 1").fetchone()
        schema_manifest = _schema_manifest(connection)
        actual = _read_rows(connection)
    except sqlite3.Error as exc:
        raise ValueError(f"invalid community database: {path}") from exc
    finally:
        if "connection" in locals():
            connection.close()
    if application_id != DATABASE_APPLICATION_ID or user_version != DATABASE_SCHEMA_VERSION:
        raise ValueError("community database schema identity is invalid")
    reference = sqlite3.connect(":memory:")
    reference.executescript(SCHEMA_SQL)
    expected_schema_manifest = _schema_manifest(reference)
    reference.close()
    if schema_manifest != expected_schema_manifest:
        raise ValueError("community database schema does not match schema v1")
    if integrity != "ok" or foreign_keys:
        raise ValueError("community database integrity check failed")
    if metadata != _metadata_row(expected) or actual != expected:
        raise ValueError(f"community database is stale; rebuild {path}")


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
                "INSERT INTO dataset_metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                _metadata_row(rows))
        connection.close()
        _validate_database(temporary, rows)
        os.replace(temporary, output)
    finally:
        if "connection" in locals():
            connection.close()
        temporary.unlink(missing_ok=True)
    return summary
