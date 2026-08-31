from __future__ import annotations

import hashlib
import json
import math
import platform
import re
import sys
import zipfile
from pathlib import Path

from . import __version__
from .common import load_json
from .report import collect
from .results import item_status


PUBLIC_SCHEMA_VERSION = 2
PUBLIC_METADATA_FIELDS = {
    "model_revision", "quantization", "model_format", "parameter_count_b",
    "server", "server_version", "accelerator", "accelerator_count",
    "memory_gb", "system_memory_gb",
}
PUBLIC_METADATA_NUMERIC_FIELDS = {
    "parameter_count_b", "accelerator_count", "memory_gb", "system_memory_gb",
}
MODEL_PARAMETER_FIELDS = {
    "reasoning_effort", "context_window", "max_tokens",
    "temperature", "top_p", "top_k", "min_p",
}
ROUND_FIELDS = {
    "attempts", "passed", "total", "mean_wall_seconds", "manual_review",
    "incomplete", "infrastructure_errors", "planned_attempts", "release_ready",
    "handoff_utility", "handoff_applicable", "false_green", "tampering",
    "mean_auto_score", "auto_score_max",
}
TASK_FIELDS = {
    "task", "attempt", "public_passed", "public_total", "hidden_passed",
    "hidden_total", "auto_score", "release_ready", "handoff_utility",
    "false_green", "tampering", "timed_out", "wall_seconds", "tokens",
}
TASK_BOOLEAN_FIELDS = {"release_ready", "false_green", "tampering", "timed_out"}
TASK_OPTIONAL_BOOLEAN_FIELDS = {"handoff_utility"}
TASK_NUMERIC_FIELDS = TASK_FIELDS - {
    "task", *TASK_BOOLEAN_FIELDS, *TASK_OPTIONAL_BOOLEAN_FIELDS,
}
PUBLIC_ITEM_FIELDS = {"item", "attempt", "status", "wall_seconds", "tokens"}
PUBLIC_ITEM_STATUSES = {"PASS", "FAIL", "INCOMPLETE", "REVIEW", "INVALID"}
PRIVATE_STRING = re.compile(
    r"(?:^[/~]|^[A-Za-z]:[\\/]|\\|://|/Users/|/home/|@|[\x00-\x1f])")
SECRET_STRING = re.compile(
    r"(?:AKIA[0-9A-Z]{16}|(?:sk|gh[opusr])-[A-Za-z0-9_-]{16,})")
FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")
FORBIDDEN_KEYS = {
    "api_key", "api_key_env", "base_url", "content", "error", "generated_at",
    "key", "label", "prompt", "raw_usage", "response", "run_id", "transcript",
}


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _bundle_id(payload_without_id: dict) -> str:
    return "sha256:" + hashlib.sha256(_canonical(payload_without_id)).hexdigest()


def _public_text(value: object, *, maximum: int = 160) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    path_parts = text.replace("\\", "/").split("/")
    if (not text or len(text) > maximum or PRIVATE_STRING.search(text)
            or SECRET_STRING.search(text)
            or any(part in {".", ".."} for part in path_parts)):
        return None
    return text


def _public_environment() -> dict:
    system = platform.system()
    if system not in {"Linux", "Darwin", "Windows"}:
        system = "Other"
    architecture = _public_text(platform.machine(), maximum=32) or "unknown"
    return {
        "os": system,
        "architecture": architecture,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
    }


def _clean_metadata(model: dict, warnings: list[str], model_number: int) -> dict:
    raw = model.get("public_metadata", {})
    if not isinstance(raw, dict):
        warnings.append(f"model-{model_number}: ignored non-object public_metadata")
        return {}
    cleaned = {}
    for key in sorted(PUBLIC_METADATA_FIELDS):
        value = raw.get(key)
        if value is None:
            continue
        if key in PUBLIC_METADATA_NUMERIC_FIELDS:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                warnings.append(f"model-{model_number}: dropped invalid {key}")
                continue
            cleaned[key] = value
        else:
            text = _public_text(value)
            if text is None:
                warnings.append(f"model-{model_number}: dropped unsafe {key}")
                continue
            cleaned[key] = text
    return cleaned


def _clean_rounds(rounds: dict) -> dict:
    cleaned = {}
    for number, data in sorted(rounds.items()):
        if number not in {"1", "2", "3", "4"} or not isinstance(data, dict):
            continue
        row = {key: data[key] for key in sorted(ROUND_FIELDS) if key in data}
        if number == "4" and isinstance(data.get("tasks"), list):
            row["tasks"] = [
                {key: task[key] for key in sorted(TASK_FIELDS) if key in task}
                for task in data["tasks"] if isinstance(task, dict)
            ]
        cleaned[number] = row
    return cleaned


def _public_item_observations(run_dir: Path, model: dict, warnings: list[str],
                              model_number: int) -> dict[str, list[dict]]:
    """Collect every item outcome while excluding prompts and generated content."""
    observations = {}
    excluded_ambiguous_tokens = 0
    model_key = model["key"]
    for number in (1, 2, 3):
        rows = []
        for path in sorted((run_dir / model_key / f"round{number}").glob(
                "attempt-*/result.json")):
            payload = load_json(path)
            attempt = payload.get("attempt", path.parent.name.removeprefix("attempt-"))
            if isinstance(attempt, bool) or not str(attempt).isdigit():
                raise ValueError(f"public export found an invalid attempt number in {path}")
            for result in payload.get("results", []):
                if not isinstance(result, dict) or result.get("id") is None:
                    raise ValueError(f"public export found an invalid item row in {path}")
                raw_item = str(result["id"])
                item = _public_text(
                    raw_item if raw_item.lower().startswith("q") else f"q{raw_item}",
                    maximum=80)
                if item is None:
                    raise ValueError(f"public export found an unsafe item ID in {path}")
                tokens = result.get("completion_tokens")
                if (model.get("transport") == "codex_cli"
                        and result.get("token_measurement") != "completion"):
                    if tokens is not None:
                        excluded_ambiguous_tokens += 1
                    tokens = None
                rows.append({
                    "item": item,
                    "attempt": int(attempt),
                    "status": item_status(result),
                    "wall_seconds": result.get("wall"),
                    "tokens": tokens,
                })
        if rows:
            observations[str(number)] = rows
    v4 = run_dir / model_key / "round4" / "run.json"
    if v4.is_file():
        payload = load_json(v4)
        rows = []
        graded = set()
        for grade in payload.get("grades", []):
            item = _public_text(grade.get("task", grade.get("qid")), maximum=80)
            attempt = (grade.get("run_meta") or {}).get("attempt")
            if item is None or isinstance(attempt, bool) or not isinstance(attempt, int):
                raise ValueError("public export found an invalid Round 4 grade identity")
            flags = grade.get("flags") or {}
            status = ("INVALID" if flags.get("model_timed_out") else
                      "PASS" if flags.get("attempt_pass") else "FAIL")
            meta = grade.get("run_meta") or {}
            tokens = meta.get("tokens")
            if model.get("transport") == "codex_cli":
                if tokens is not None:
                    excluded_ambiguous_tokens += 1
                tokens = None
            rows.append({"item": item, "attempt": attempt, "status": status,
                         "wall_seconds": meta.get("wall"), "tokens": tokens})
            graded.add((item, attempt))
        for error in payload.get("errors", []):
            item = _public_text(error.get("task"), maximum=80)
            attempt = error.get("attempt")
            if (item is not None and isinstance(attempt, int)
                    and not isinstance(attempt, bool) and (item, attempt) not in graded):
                rows.append({"item": item, "attempt": attempt, "status": "INVALID",
                             "wall_seconds": None, "tokens": None})
        if rows:
            observations["4"] = sorted(
                rows, key=lambda row: (row["attempt"], row["item"], row["status"]))
    if excluded_ambiguous_tokens:
        warnings.append(
            f"model-{model_number}: excluded {excluded_ambiguous_tokens} Codex "
            "total-token measurements from completion-throughput evidence")
    return observations


def build_public_result(run_dir: Path) -> tuple[dict, list[str]]:
    """Construct an allowlist-only public result from local campaign evidence."""
    summary = collect(run_dir)
    saved_summary_path = run_dir / "summary.json"
    if not saved_summary_path.is_file():
        raise ValueError("public export requires a completed run with summary.json")
    saved_summary = load_json(saved_summary_path)
    packs = saved_summary.get("packs")
    selected_rounds = [int(value) for value in summary["config"].get("rounds", [])]
    if (not isinstance(packs, dict)
            or any(str(number) not in packs for number in selected_rounds)):
        raise ValueError(
            "saved summary has no recorded pack fingerprints; regenerate the report "
            "with the original benchmark version before exporting")

    warnings = []
    by_key = {entry["key"]: entry for entry in summary["models"]}
    models = []
    for index, model in enumerate(summary["config"]["models"], 1):
        name = _public_text(model.get("public_name") or model.get("model"))
        if name is None:
            name = f"model-{index}"
            warnings.append(
                f"model-{index}: model identifier was replaced; set public_name to publish it")
        parameters = {}
        for key in sorted(MODEL_PARAMETER_FIELDS):
            value = model.get(key)
            if value is None or isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                parameters[key] = value
            elif key == "reasoning_effort" and _public_text(value, maximum=32):
                parameters[key] = value
        entry = by_key.get(model.get("key"), {"rounds": {}})
        rounds = _clean_rounds(entry.get("rounds", {}))
        observations = _public_item_observations(
            run_dir, model, warnings, index)
        for number in rounds:
            rounds[number]["items"] = observations.get(number, [])
        models.append({
            "public_name": name,
            "transport": model.get("transport"),
            "rounds": rounds,
            "parameters": parameters,
            "public_metadata": _clean_metadata(model, warnings, index),
        })

    body = {
        "schema_version": PUBLIC_SCHEMA_VERSION,
        "tool": {"name": "llm-hardtest-report", "version": __version__},
        "benchmark": {
            "rounds": selected_rounds,
            "packs": {str(number): packs[str(number)] for number in selected_rounds},
        },
        "environment": _public_environment(),
        "models": models,
        "privacy": {
            "raw_artifacts_included": False,
            "credentials_included": False,
            "local_paths_included": False,
            "submission_mode": "explicit-opt-in",
        },
    }
    payload = {"schema_version": PUBLIC_SCHEMA_VERSION,
               "bundle_id": _bundle_id(body),
               **{key: value for key, value in body.items() if key != "schema_version"}}
    validate_public_result(payload)
    return payload, warnings


def _walk(value, path="root"):
    if isinstance(value, dict):
        for key, child in value.items():
            yield path, key, child
            yield from _walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{path}[{index}]")


def validate_public_result(payload: dict) -> dict:
    """Validate public-result structure, content hash, and privacy invariants."""
    if not isinstance(payload, dict):
        raise ValueError("public result must be a JSON object")
    required = {"schema_version", "bundle_id", "tool", "benchmark",
                "environment", "models", "privacy"}
    schema_version = payload.get("schema_version")
    if set(payload) != required or schema_version not in {1, PUBLIC_SCHEMA_VERSION}:
        raise ValueError("public result has unsupported or unexpected top-level fields")
    without_id = {key: value for key, value in payload.items() if key != "bundle_id"}
    if (not isinstance(payload.get("bundle_id"), str)
            or FINGERPRINT.fullmatch(payload["bundle_id"]) is None
            or payload["bundle_id"] != _bundle_id(without_id)):
        raise ValueError("public result bundle_id does not match its content")
    tool = payload.get("tool")
    if (not isinstance(tool, dict) or set(tool) != {"name", "version"}
            or tool.get("name") != "llm-hardtest-report"
            or _public_text(tool.get("version"), maximum=32) is None):
        raise ValueError("public result tool identity is invalid")
    benchmark = payload.get("benchmark")
    if not isinstance(benchmark, dict) or set(benchmark) != {"rounds", "packs"}:
        raise ValueError("public result benchmark identity is invalid")
    rounds = benchmark.get("rounds")
    packs = benchmark.get("packs")
    if (not isinstance(rounds, list) or not rounds
            or any(isinstance(value, bool) or not isinstance(value, int)
                   or value not in (1, 2, 3, 4) for value in rounds)
            or len(rounds) != len(set(rounds))):
        raise ValueError("public result selected rounds are invalid")
    if (not isinstance(packs, dict) or set(packs) != {str(value) for value in rounds}
            or any(not isinstance(value, str) or FINGERPRINT.fullmatch(value) is None
                   for value in packs.values())):
        raise ValueError("public result pack fingerprints are invalid")
    environment = payload.get("environment")
    if (not isinstance(environment, dict)
            or set(environment) != {"os", "architecture", "python"}
            or environment.get("os") not in {"Linux", "Darwin", "Windows", "Other"}
            or _public_text(environment.get("architecture"), maximum=32) is None
            or not isinstance(environment.get("python"), str)
            or re.fullmatch(r"[0-9]+\.[0-9]+", environment["python"]) is None):
        raise ValueError("public result environment is invalid")
    models = payload.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError("public result requires at least one model")
    for index, model in enumerate(models, 1):
        expected = {"public_name", "transport", "rounds", "parameters", "public_metadata"}
        if not isinstance(model, dict) or set(model) != expected:
            raise ValueError(f"public model {index} has unexpected fields")
        if _public_text(model["public_name"]) is None:
            raise ValueError(f"public model {index} has an unsafe public_name")
        if model["transport"] not in {"openai_compat", "codex_cli"}:
            raise ValueError(f"public model {index} has an invalid transport")
        if not isinstance(model["rounds"], dict):
            raise ValueError(f"public model {index} rounds must be an object")
        if set(model["rounds"]) - {str(value) for value in rounds}:
            raise ValueError(f"public model {index} contains an unselected round")
        for round_number, result in model["rounds"].items():
            if not isinstance(result, dict):
                raise ValueError(f"public model {index} round {round_number} is invalid")
            allowed = set(ROUND_FIELDS) | ({"tasks"} if round_number == "4" else set())
            if schema_version >= 2:
                allowed.add("items")
            if set(result) - allowed:
                raise ValueError(f"public model {index} round {round_number} has extra fields")
            if schema_version >= 2 and "items" not in result:
                raise ValueError(f"public model {index} round {round_number} has no item outcomes")
            for key, value in result.items():
                if key == "items":
                    if not isinstance(value, list):
                        raise ValueError(f"public model {index} items must be a list")
                    seen_items = set()
                    for item in value:
                        if not isinstance(item, dict) or set(item) != PUBLIC_ITEM_FIELDS:
                            raise ValueError(f"public model {index} has an invalid item outcome")
                        identity = (item.get("item"), item.get("attempt"))
                        if (identity in seen_items
                                or _public_text(item.get("item"), maximum=80) is None
                                or isinstance(item.get("attempt"), bool)
                                or not isinstance(item.get("attempt"), int)
                                or item["attempt"] < 1
                                or item.get("status") not in PUBLIC_ITEM_STATUSES):
                            raise ValueError(f"public model {index} item outcome is invalid")
                        wall, tokens = item.get("wall_seconds"), item.get("tokens")
                        if (wall is not None and (
                                isinstance(wall, bool) or not isinstance(wall, (int, float))
                                or not math.isfinite(wall) or wall < 0)):
                            raise ValueError(f"public model {index} item wall_seconds is invalid")
                        if (tokens is not None and (
                                isinstance(tokens, bool) or not isinstance(tokens, int)
                                or tokens < 0)):
                            raise ValueError(f"public model {index} item tokens is invalid")
                        seen_items.add(identity)
                elif key == "tasks":
                    if not isinstance(value, list):
                        raise ValueError(f"public model {index} tasks must be a list")
                    for task in value:
                        if not isinstance(task, dict) or set(task) - TASK_FIELDS:
                            raise ValueError(f"public model {index} has an invalid task row")
                        if _public_text(task.get("task"), maximum=80) is None:
                            raise ValueError(f"public model {index} has an unsafe task id")
                        for task_key, task_value in task.items():
                            if task_key == "task":
                                continue
                            if task_key in TASK_BOOLEAN_FIELDS:
                                valid = isinstance(task_value, bool)
                            elif task_key in TASK_OPTIONAL_BOOLEAN_FIELDS:
                                valid = task_value is None or isinstance(task_value, bool)
                            else:
                                valid = (task_key in TASK_NUMERIC_FIELDS
                                         and (task_value is None or (
                                             not isinstance(task_value, bool)
                                             and isinstance(task_value, (int, float))
                                             and math.isfinite(task_value)
                                             and task_value >= 0)))
                            if not valid:
                                raise ValueError(
                                    f"public model {index} task {task_key} is invalid")
                elif value is not None and (
                        isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value) or value < 0):
                    raise ValueError(f"public model {index} round metric {key} is invalid")
            if schema_version >= 2:
                counts = {status: 0 for status in PUBLIC_ITEM_STATUSES}
                for item in result["items"]:
                    counts[item["status"]] += 1
                expected_metrics = (
                    {"passed": counts["PASS"],
                     "total": counts["PASS"] + counts["FAIL"],
                     "incomplete": counts["INCOMPLETE"],
                     "manual_review": counts["REVIEW"],
                     "infrastructure_errors": counts["INVALID"]}
                    if round_number != "4" else
                    {"release_ready": counts["PASS"]})
                for metric, expected_value in expected_metrics.items():
                    if metric in result and result[metric] != expected_value:
                        raise ValueError(
                            f"public model {index} round {round_number} {metric} "
                            "contradicts item outcomes")
        if set(model["public_metadata"]) - PUBLIC_METADATA_FIELDS:
            raise ValueError(f"public model {index} metadata is not allowlisted")
        if set(model["parameters"]) - MODEL_PARAMETER_FIELDS:
            raise ValueError(f"public model {index} parameters are not allowlisted")
        for key, value in model["public_metadata"].items():
            if key in PUBLIC_METADATA_NUMERIC_FIELDS:
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value) or value <= 0):
                    raise ValueError(f"public model {index} metadata {key} is invalid")
            elif _public_text(value) is None:
                raise ValueError(f"public model {index} metadata {key} is unsafe")
        for key, value in model["parameters"].items():
            if key == "reasoning_effort":
                if _public_text(value, maximum=32) is None:
                    raise ValueError(f"public model {index} reasoning effort is invalid")
            elif (isinstance(value, bool) or not isinstance(value, (int, float))
                  or not math.isfinite(value)):
                raise ValueError(f"public model {index} parameter {key} is invalid")
    privacy = payload.get("privacy")
    if privacy != {
        "raw_artifacts_included": False,
        "credentials_included": False,
        "local_paths_included": False,
        "submission_mode": "explicit-opt-in",
    }:
        raise ValueError("public result privacy declaration is invalid")
    for path, key, value in _walk(payload):
        if key in FORBIDDEN_KEYS:
            raise ValueError(f"forbidden private field at {path}.{key}")
        if isinstance(value, str) and (PRIVATE_STRING.search(value) or SECRET_STRING.search(value)):
            raise ValueError(f"private-looking string at {path}.{key}")
    if len(_canonical(payload)) > 2_000_000:
        raise ValueError("public result is too large")
    return payload


def export_public_bundle(run_dir: Path, output: Path) -> tuple[Path, dict, list[str]]:
    """Write a deterministic ZIP containing only a validated public submission."""
    if output.suffix.lower() != ".zip":
        raise ValueError("public export output must use a .zip extension")
    if output.exists():
        raise ValueError(f"refusing to overwrite existing public bundle: {output}")
    payload, warnings = build_public_result(run_dir)
    document = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    notice = (
        "This bundle contains a voluntary public LLM Hardtest aggregate.\n"
        "Preview submission.json before publishing it. No raw run artifacts are included.\n"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in (("submission.json", document), ("PRIVACY.txt", notice)):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, content.encode("utf-8"))
    return output, payload, warnings


def load_public_bundle(path: Path) -> dict:
    """Load and validate a public submission from canonical JSON or an export ZIP."""
    if path.suffix.lower() == ".json":
        return validate_public_result(load_json(path))
    if path.suffix.lower() != ".zip":
        raise ValueError("public result must be a .json or .zip file")
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if names != ["submission.json", "PRIVACY.txt"]:
                raise ValueError("public bundle contains unexpected files")
            if any(info.file_size > 2_000_000 or info.compress_size > 2_000_000
                   for info in archive.infolist()):
                raise ValueError("public bundle is too large")
            payload = json.loads(archive.read("submission.json").decode("utf-8"))
    except (zipfile.BadZipFile, UnicodeDecodeError) as exc:
        raise ValueError(f"invalid public bundle: {exc}") from exc
    return validate_public_result(payload)
