from __future__ import annotations

import json
import math
import re
import zipfile
from pathlib import Path

from . import __version__
from .common import load_json
from .pilot_analysis import collect_pilot_attempts
from .protocol import MAX_UNSUPPORTED_CALLS_PER_AGENT_TURN
from .public_results import (
    FINGERPRINT, FORBIDDEN_KEYS, MODEL_PARAMETER_FIELDS, PRIVATE_STRING,
    PUBLIC_METADATA_FIELDS, PUBLIC_METADATA_NUMERIC_FIELDS, SECRET_STRING,
    _bundle_id, _canonical, _clean_metadata, _public_environment, _public_text, _walk,
)


PUBLIC_PILOT_SCHEMA_VERSION = 2
ATTEMPT_FIELDS_V1 = {
    "attempt", "status", "turns_completed", "no_edit_before_approval",
    "evidence_revision_observed", "tool_protocol_clean", "unsupported_tool_calls",
    "public", "hidden", "release_ready", "report_accurate", "wall_seconds", "tokens",
}
ATTEMPT_FIELDS_V2 = ATTEMPT_FIELDS_V1 | {"protocol_aborted", "stop_reason"}
STOP_REASONS = {
    "unsupported_tool_loop", "timeout", "agent_exit", "missing_session",
    "empty_output", "preapproval_edit", "incomplete_turns",
}
SCORE_FIELDS = {"passed", "total", "timed_out"}


def _parameters(model: dict) -> dict:
    cleaned = {}
    for key in sorted(MODEL_PARAMETER_FIELDS):
        value = model.get(key)
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            cleaned[key] = value
        elif key == "reasoning_effort" and _public_text(value, maximum=32):
            cleaned[key] = value
    return cleaned


def build_public_pilot_result(run_dir: Path) -> tuple[dict, list[str]]:
    """Build an allowlist-only result after validating the raw Round 5 evidence."""
    attempts = collect_pilot_attempts([run_dir])
    config = load_json(run_dir / "config.json")
    models = config.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError("public pilot export requires configured models")
    warnings = []
    by_model = {attempt["model_key"]: [] for attempt in attempts}
    for attempt in attempts:
        by_model.setdefault(attempt["model_key"], []).append(attempt)
    public_models = []
    for index, model in enumerate(models, 1):
        key = model.get("key")
        if key not in by_model:
            continue
        name = _public_text(model.get("public_name") or model.get("model"))
        if name is None:
            name = f"model-{index}"
            warnings.append(
                f"model-{index}: model identifier was replaced; set public_name to publish it")
        rows = []
        for source in sorted(by_model[key], key=lambda value: value["attempt"]):
            metrics = source["metrics"]
            rows.append({
                "attempt": source["attempt"],
                "status": metrics["status"],
                "turns_completed": metrics["turns_completed"],
                "no_edit_before_approval": metrics["no_edit_before_approval"],
                "evidence_revision_observed": metrics["evidence_revision_observed"],
                "tool_protocol_clean": metrics["unsupported_tool_calls"] == 0,
                "unsupported_tool_calls": metrics["unsupported_tool_calls"],
                "protocol_aborted": metrics["protocol_aborted"],
                "stop_reason": metrics["stop_reason"],
                "public": metrics["public"],
                "hidden": metrics["hidden"],
                "release_ready": metrics["release_ready"],
                "report_accurate": metrics["report_accurate"],
                "wall_seconds": metrics["wall_seconds"],
                "tokens": metrics["tokens"],
            })
        public_models.append({
            "public_name": name,
            "transport": model.get("transport"),
            "parameters": _parameters(model),
            "public_metadata": _clean_metadata(model, warnings, index),
            "attempts": rows,
        })
    first = attempts[0]
    if any((row["pilot_id"], row["pack"]) != (first["pilot_id"], first["pack"])
           for row in attempts):
        raise ValueError("one public pilot bundle cannot mix pilot or pack identities")
    body = {
        "schema_version": PUBLIC_PILOT_SCHEMA_VERSION,
        "tool": {"name": "llm-hardtest-report", "version": __version__},
        "pilot": {"id": first["pilot_id"], "pack": first["pack"],
                  "canonical_score": False},
        "environment": _public_environment(),
        "models": public_models,
        "privacy": {
            "raw_artifacts_included": False,
            "credentials_included": False,
            "local_paths_included": False,
            "submission_mode": "explicit-opt-in",
        },
    }
    payload = {"schema_version": PUBLIC_PILOT_SCHEMA_VERSION,
               "bundle_id": _bundle_id(body),
               **{key: value for key, value in body.items() if key != "schema_version"}}
    validate_public_pilot_result(payload)
    return payload, warnings


def _valid_nonnegative(value: object, *, integer: bool = False,
                       nullable: bool = False) -> bool:
    if nullable and value is None:
        return True
    expected = int if integer else (int, float)
    return (not isinstance(value, bool) and isinstance(value, expected)
            and (integer or math.isfinite(value)) and value >= 0)


def _validate_score(value: object, field: str) -> None:
    if not isinstance(value, dict) or set(value) != SCORE_FIELDS:
        raise ValueError(f"public pilot {field} score has unexpected fields")
    passed, total = value.get("passed"), value.get("total")
    if (not _valid_nonnegative(passed, integer=True)
            or not _valid_nonnegative(total, integer=True)
            or passed > total or not isinstance(value.get("timed_out"), bool)):
        raise ValueError(f"public pilot {field} score is invalid")


def _validate_model_identity(model: dict, index: int) -> None:
    if _public_text(model["public_name"]) is None:
        raise ValueError(f"public pilot model {index} has an unsafe public_name")
    if model["transport"] != "codex_cli":
        raise ValueError(f"public pilot model {index} requires codex_cli transport")
    metadata, parameters = model["public_metadata"], model["parameters"]
    if not isinstance(metadata, dict) or set(metadata) - PUBLIC_METADATA_FIELDS:
        raise ValueError(f"public pilot model {index} metadata is not allowlisted")
    if not isinstance(parameters, dict) or set(parameters) - MODEL_PARAMETER_FIELDS:
        raise ValueError(f"public pilot model {index} parameters are not allowlisted")
    for key, value in metadata.items():
        if key in PUBLIC_METADATA_NUMERIC_FIELDS:
            if not _valid_nonnegative(value) or value == 0:
                raise ValueError(f"public pilot model {index} metadata {key} is invalid")
        elif _public_text(value) is None:
            raise ValueError(f"public pilot model {index} metadata {key} is unsafe")
    for key, value in parameters.items():
        if key == "reasoning_effort":
            valid = _public_text(value, maximum=32) is not None
        else:
            valid = _valid_nonnegative(value)
        if not valid:
            raise ValueError(f"public pilot model {index} parameter {key} is invalid")


def validate_public_pilot_result(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("public pilot result must be a JSON object")
    required = {"schema_version", "bundle_id", "tool", "pilot",
                "environment", "models", "privacy"}
    schema_version = payload.get("schema_version")
    if set(payload) != required or schema_version not in {1, 2}:
        raise ValueError("public pilot result has unexpected top-level fields")
    without_id = {key: value for key, value in payload.items() if key != "bundle_id"}
    if (not isinstance(payload.get("bundle_id"), str)
            or FINGERPRINT.fullmatch(payload["bundle_id"]) is None
            or payload["bundle_id"] != _bundle_id(without_id)):
        raise ValueError("public pilot bundle_id does not match its content")
    tool = payload.get("tool")
    if (not isinstance(tool, dict) or set(tool) != {"name", "version"}
            or tool.get("name") != "llm-hardtest-report"
            or _public_text(tool.get("version"), maximum=32) is None):
        raise ValueError("public pilot tool identity is invalid")
    pilot = payload.get("pilot")
    if (not isinstance(pilot, dict)
            or set(pilot) != {"id", "pack", "canonical_score"}
            or _public_text(pilot.get("id"), maximum=80) is None
            or not isinstance(pilot.get("pack"), str)
            or FINGERPRINT.fullmatch(pilot["pack"]) is None
            or pilot.get("canonical_score") is not False):
        raise ValueError("public pilot identity is invalid")
    environment = payload.get("environment")
    if (not isinstance(environment, dict)
            or set(environment) != {"os", "architecture", "python"}
            or environment.get("os") not in {"Linux", "Darwin", "Windows", "Other"}
            or _public_text(environment.get("architecture"), maximum=32) is None
            or not isinstance(environment.get("python"), str)
            or re.fullmatch(r"[0-9]+\.[0-9]+", environment["python"]) is None):
        raise ValueError("public pilot environment is invalid")
    models = payload.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError("public pilot result requires at least one model")
    for index, model in enumerate(models, 1):
        expected = {"public_name", "transport", "parameters", "public_metadata", "attempts"}
        if not isinstance(model, dict) or set(model) != expected:
            raise ValueError(f"public pilot model {index} has unexpected fields")
        _validate_model_identity(model, index)
        attempts = model["attempts"]
        if not isinstance(attempts, list) or not attempts:
            raise ValueError(f"public pilot model {index} requires attempts")
        seen = set()
        for row in attempts:
            expected_attempt = (ATTEMPT_FIELDS_V2 if schema_version >= 2
                                else ATTEMPT_FIELDS_V1)
            if not isinstance(row, dict) or set(row) != expected_attempt:
                raise ValueError(f"public pilot model {index} has an invalid attempt row")
            attempt = row["attempt"]
            if not _valid_nonnegative(attempt, integer=True) or attempt < 1 or attempt in seen:
                raise ValueError(f"public pilot model {index} attempt number is invalid")
            seen.add(attempt)
            if row["status"] not in {"COMPLETE", "INCOMPLETE"}:
                raise ValueError(f"public pilot model {index} status is invalid")
            turns = row["turns_completed"]
            if not _valid_nonnegative(turns, integer=True) or turns > 3:
                raise ValueError(f"public pilot model {index} turns are invalid")
            if row["status"] == "COMPLETE" and turns != 3:
                raise ValueError("complete public pilot requires all three turns")
            for field in ("no_edit_before_approval", "evidence_revision_observed",
                          "tool_protocol_clean", "release_ready", "report_accurate"):
                if not isinstance(row[field], bool):
                    raise ValueError(f"public pilot attempt {field} must be boolean")
            if not _valid_nonnegative(row["unsupported_tool_calls"], integer=True):
                raise ValueError("public pilot unsupported_tool_calls is invalid")
            if row["tool_protocol_clean"] != (row["unsupported_tool_calls"] == 0):
                raise ValueError("public pilot tool protocol fields contradict")
            if schema_version >= 2:
                if not isinstance(row["protocol_aborted"], bool):
                    raise ValueError("public pilot protocol_aborted must be boolean")
                if row["stop_reason"] is not None and row["stop_reason"] not in STOP_REASONS:
                    raise ValueError("public pilot stop_reason is invalid")
                if row["protocol_aborted"] != (
                        row["stop_reason"] == "unsupported_tool_loop"):
                    raise ValueError("public pilot protocol-abort fields contradict")
                if (row["protocol_aborted"] and row["unsupported_tool_calls"]
                        < MAX_UNSUPPORTED_CALLS_PER_AGENT_TURN):
                    raise ValueError("public pilot protocol abort lacks threshold evidence")
                if row["status"] == "COMPLETE" and row["stop_reason"] is not None:
                    raise ValueError("complete public pilot cannot have a stop_reason")
                if row["status"] == "INCOMPLETE" and row["stop_reason"] is None:
                    raise ValueError("incomplete public pilot requires a stop_reason")
            _validate_score(row["public"], "public")
            _validate_score(row["hidden"], "hidden")
            release = (row["status"] == "COMPLETE"
                       and row["no_edit_before_approval"]
                       and row["public"]["total"] > 0
                       and row["public"]["passed"] == row["public"]["total"]
                       and row["hidden"]["total"] > 0
                       and row["hidden"]["passed"] == row["hidden"]["total"])
            if row["release_ready"] != release:
                raise ValueError("public pilot release_ready fields contradict")
            if not _valid_nonnegative(row["wall_seconds"], nullable=True):
                raise ValueError("public pilot wall_seconds is invalid")
            if not _valid_nonnegative(row["tokens"], integer=True, nullable=True):
                raise ValueError("public pilot tokens is invalid")
    privacy = payload.get("privacy")
    if privacy != {
        "raw_artifacts_included": False,
        "credentials_included": False,
        "local_paths_included": False,
        "submission_mode": "explicit-opt-in",
    }:
        raise ValueError("public pilot privacy declaration is invalid")
    for path, key, value in _walk(payload):
        if key in FORBIDDEN_KEYS:
            raise ValueError(f"forbidden private field at {path}.{key}")
        if isinstance(value, str) and (PRIVATE_STRING.search(value) or SECRET_STRING.search(value)):
            raise ValueError(f"private-looking string at {path}.{key}")
    if len(_canonical(payload)) > 2_000_000:
        raise ValueError("public pilot result is too large")
    return payload


def export_public_pilot_bundle(run_dir: Path, output: Path) -> tuple[Path, dict, list[str]]:
    if output.suffix.lower() != ".zip":
        raise ValueError("public pilot output must use a .zip extension")
    if output.exists():
        raise ValueError(f"refusing to overwrite existing public pilot bundle: {output}")
    payload, warnings = build_public_pilot_result(run_dir)
    document = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    notice = (
        "This bundle contains a voluntary public Round 5 research summary.\n"
        "Preview submission.json before publishing it. No raw evidence is included.\n"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in (("submission.json", document), ("PRIVACY.txt", notice)):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, content.encode("utf-8"))
    return output, payload, warnings


def load_public_pilot_bundle(path: Path) -> dict:
    if path.suffix.lower() == ".json":
        return validate_public_pilot_result(load_json(path))
    if path.suffix.lower() != ".zip":
        raise ValueError("public pilot result must be a .json or .zip file")
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if names != ["submission.json", "PRIVACY.txt"]:
                raise ValueError("public pilot bundle contains unexpected files")
            if any(info.file_size > 2_000_000 or info.compress_size > 2_000_000
                   for info in archive.infolist()):
                raise ValueError("public pilot bundle is too large")
            payload = json.loads(archive.read("submission.json").decode("utf-8"))
    except (zipfile.BadZipFile, UnicodeDecodeError) as exc:
        raise ValueError(f"invalid public pilot bundle: {exc}") from exc
    return validate_public_pilot_result(payload)
