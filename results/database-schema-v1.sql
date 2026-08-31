-- Logical schema emitted by `llm-hardtest results database`.
-- The generated database also sets application_id=0x4c484452 (LHDR) and user_version=1.
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
