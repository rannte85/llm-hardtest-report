from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath

from .common import load_json


SCHEMA_VERSION = 1
CAPABILITIES = {"chat_completions", "responses", "filesystem", "multi_turn"}
RUNNER_KINDS = {"reasoning", "structured", "coding_agent"}
GENERATED_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def _generated(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return (bool(GENERATED_PARTS.intersection(relative.parts))
            or path.suffix in {".pyc", ".pyo"}
            or path.name in {".DS_Store", ".coverage"})


def _safe_pattern(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("pack assets must be non-empty relative path patterns")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError(f"unsafe pack asset pattern: {value!r}")
    return value


def _asset_files(root: Path, patterns: list) -> list[Path]:
    files = {}
    for raw in patterns:
        pattern = _safe_pattern(raw)
        matches = [path for path in root.glob(pattern)
                   if path.is_file() and not _generated(path, root)]
        if not matches:
            raise ValueError(f"pack asset pattern matched no files: {pattern}")
        for path in matches:
            resolved = path.resolve()
            try:
                relative = resolved.relative_to(root.resolve())
            except ValueError as exc:
                raise ValueError(f"pack asset escapes its directory: {path}") from exc
            files[relative.as_posix()] = resolved
    return [files[name] for name in sorted(files)]


def validate_pack(path: Path) -> dict:
    """Validate a self-describing benchmark pack and return its content fingerprint."""
    root = path.resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"pack has no manifest.json: {path}")
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ValueError("pack manifest must be a JSON object")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported pack schema_version: {manifest.get('schema_version')!r}")
    pack_id = manifest.get("id")
    if (not isinstance(pack_id, str)
            or re.fullmatch(r"[a-z0-9][a-z0-9._-]*", pack_id) is None):
        raise ValueError("pack id must be lowercase and filesystem-safe")
    if not isinstance(manifest.get("title"), str) or not manifest["title"].strip():
        raise ValueError("pack title is required")
    if manifest.get("runner_kind") not in RUNNER_KINDS:
        raise ValueError("unsupported pack runner_kind")
    capabilities = manifest.get("capabilities")
    if (not isinstance(capabilities, list) or len(capabilities) != len(set(capabilities))
            or any(value not in CAPABILITIES for value in capabilities)):
        raise ValueError("pack capabilities are invalid or duplicated")
    for field in ("unit_count", "time_limit_seconds"):
        value = manifest.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"pack {field} must be a positive integer")
    if not isinstance(manifest.get("result_schema"), str) or not manifest["result_schema"]:
        raise ValueError("pack result_schema is required")
    patterns = manifest.get("assets")
    if not isinstance(patterns, list) or not patterns:
        raise ValueError("pack assets must be a non-empty JSON list")
    assets = _asset_files(root, patterns)
    controls = manifest.get("controls", [])
    if not isinstance(controls, list):
        raise ValueError("pack controls must be a JSON list")
    control_ids = []
    for control in controls:
        if not isinstance(control, dict):
            raise ValueError("every pack control must be a JSON object")
        control_ids.append(control.get("id"))
        command = control.get("command")
        if (control.get("kind") not in {"positive", "negative"}
                or not isinstance(command, list) or not command
                or any(not isinstance(part, str) or not part for part in command)):
            raise ValueError("pack controls require kind and an argument-array command")
    if any(not isinstance(value, str) or not value for value in control_ids):
        raise ValueError("pack control ids are required")
    if len(control_ids) != len(set(control_ids)):
        raise ValueError("pack control ids must be unique")

    canonical = dict(manifest)
    canonical.pop("fingerprint", None)
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    relative_assets = []
    for asset in assets:
        relative = asset.relative_to(root).as_posix()
        relative_assets.append(relative)
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(asset.read_bytes())
    fingerprint = "sha256:" + digest.hexdigest()
    declared = manifest.get("fingerprint")
    if declared is not None and declared != fingerprint:
        raise ValueError("pack fingerprint does not match its manifest and assets")
    return {
        "id": pack_id,
        "title": manifest["title"],
        "schema_version": SCHEMA_VERSION,
        "runner_kind": manifest["runner_kind"],
        "unit_count": manifest["unit_count"],
        "fingerprint": fingerprint,
        "assets": relative_assets,
    }
