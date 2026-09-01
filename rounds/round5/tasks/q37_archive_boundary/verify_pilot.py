#!/usr/bin/env python3
"""Execute q37's positive and adversarial archive-boundary control matrix."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "repo"
HIDDEN = HERE / "hidden" / "hidden_tests.py"


CORRECT = '''"""Cross-platform, preflighted ZIP extraction boundary."""

from __future__ import annotations

import re
import shutil
import stat
import unicodedata
import zipfile
from pathlib import Path


_DRIVE = re.compile(r"^[A-Za-z]:")


def _member(info):
    raw = info.filename.replace("\\\\", "/")
    if (not raw or raw.startswith("/") or raw.startswith("//")
            or _DRIVE.match(raw)):
        raise ValueError("archive member is absolute")
    parts = []
    for part in raw.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            raise ValueError("archive member escapes destination")
        parts.append(unicodedata.normalize("NFC", part))
    mode = info.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    if stat.S_ISLNK(mode):
        raise ValueError("archive symlink members are forbidden")
    if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
        raise ValueError("unsupported archive member type")
    is_dir = info.is_dir() or file_type == stat.S_IFDIR
    if not parts:
        if is_dir:
            return None
        raise ValueError("archive file has no usable name")
    return tuple(parts), is_dir


def _key(parts):
    return tuple(part.casefold() for part in parts)


def _preflight(archive, max_total_bytes):
    entries = []
    seen = {}
    total = 0
    for info in archive.infolist():
        member = _member(info)
        if member is None:
            continue
        parts, is_dir = member
        key = _key(parts)
        if key in seen:
            raise ValueError("duplicate normalized archive member")
        for depth in range(1, len(key)):
            if seen.get(key[:depth]) == "file":
                raise ValueError("archive file-directory collision")
        if (not is_dir and any(
                len(existing) > len(key) and existing[:len(key)] == key
                for existing in seen)):
            raise ValueError("archive file-directory collision")
        seen[key] = "dir" if is_dir else "file"
        if not is_dir:
            total += info.file_size
            if total > max_total_bytes:
                raise ValueError("archive exceeds max_total_bytes")
        entries.append((info, parts, is_dir))
    return entries


def _check_destination(destination, entries):
    if destination.is_symlink():
        raise ValueError("destination cannot be a symlink")
    if destination.exists() and not destination.is_dir():
        raise ValueError("destination must be a directory")
    for _info, parts, is_dir in entries:
        current = destination
        for part in parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise ValueError("destination contains a symlink component")
            if current.exists() and not current.is_dir():
                raise ValueError("destination contains a file-directory collision")
        target = destination.joinpath(*parts)
        if target.is_symlink():
            raise ValueError("destination target is a symlink")
        if target.exists() and not (is_dir and target.is_dir()):
            raise ValueError("archive extraction would overwrite existing content")


def safe_extract(archive_path, destination, max_total_bytes=1048576):
    if (isinstance(max_total_bytes, bool) or not isinstance(max_total_bytes, int)
            or max_total_bytes < 0):
        raise ValueError("max_total_bytes must be a non-negative integer")
    destination = Path(destination)
    with zipfile.ZipFile(archive_path) as archive:
        entries = _preflight(archive, max_total_bytes)
        _check_destination(destination, entries)
        destination.mkdir(parents=True, exist_ok=True)
        for _info, parts, is_dir in sorted(entries, key=lambda row: len(row[1])):
            if is_dir:
                destination.joinpath(*parts).mkdir(parents=True, exist_ok=True)
        extracted = []
        for info, parts, is_dir in entries:
            if is_dir:
                continue
            target = destination.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            extracted.append("/".join(parts))
    return sorted(extracted)
'''


PARTIAL_WRITE = '''"""Lexical checks performed unsafely while extraction is already writing."""

from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path


_DRIVE = re.compile(r"^[A-Za-z]:")


def safe_extract(archive_path, destination, max_total_bytes=1048576):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    extracted = []
    total = 0
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            raw = info.filename.replace("\\\\", "/")
            if (not raw or raw.startswith("/") or raw.startswith("//")
                    or _DRIVE.match(raw)):
                raise ValueError("absolute member")
            parts = [part for part in raw.split("/") if part not in {"", "."}]
            if ".." in parts:
                raise ValueError("traversal member")
            target = destination.joinpath(*parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            total += info.file_size
            if total > max_total_bytes:
                raise ValueError("archive too large")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            extracted.append("/".join(parts))
    return sorted(extracted)
'''


def _implementation(state: str) -> str:
    if state == "partial_write":
        return PARTIAL_WRITE
    source = CORRECT
    if state == "backslash_alias":
        source = source.replace('raw = info.filename.replace("\\\\", "/")',
                                "raw = info.filename")
    elif state == "drive_prefix":
        source = source.replace(
            'if (not raw or raw.startswith("/") or raw.startswith("//")\n'
            '            or _DRIVE.match(raw)):',
            'if (not raw or raw.startswith("/") or raw.startswith("//")):')
    elif state == "symlink_member":
        source = source.replace("    if stat.S_ISLNK(mode):\n",
                                "    if False and stat.S_ISLNK(mode):\n")
        source = source.replace(
            "    if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:",
            "    if file_type not in {0, stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK}:")
    elif state == "existing_symlink":
        source = source.replace("            if current.is_symlink():\n",
                                "            if False and current.is_symlink():\n")
    elif state == "alias_duplicate":
        source = source.replace(
            "    return tuple(part.casefold() for part in parts)",
            "    return tuple(parts)")
    elif state == "file_dir_collision":
        source = source.replace(
            '            if seen.get(key[:depth]) == "file":',
            '            if False and seen.get(key[:depth]) == "file":')
    elif state == "compressed_limit":
        source = source.replace("            total += info.file_size",
                                "            total += info.compress_size")
    elif state == "overwrite_existing":
        source = source.replace(
            '        if target.exists() and not (is_dir and target.is_dir()):\n'
            '            raise ValueError("archive extraction would overwrite existing content")\n',
            "")
    return source


def _apply(state: str, repo: Path) -> None:
    if state == "baseline":
        return
    valid = {
        "correct", "backslash_alias", "drive_prefix", "symlink_member",
        "existing_symlink", "partial_write", "alias_duplicate",
        "file_dir_collision", "compressed_limit", "overwrite_existing", "tamper",
    }
    if state not in valid:
        raise ValueError(state)
    implementation = "correct" if state == "tamper" else state
    (repo / "secure_extract.py").write_text(
        _implementation(implementation), encoding="utf-8")
    if state == "tamper":
        with (repo / "run_tests.py").open("a", encoding="utf-8") as handle:
            handle.write("\n# candidate changed protected public-test authority\n")


def _run(command: list[str], cwd: Path) -> tuple[int, int, str]:
    proc = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=20)
    output = proc.stdout + proc.stderr
    match = re.search(r"(?:PUBLIC|HIDDEN): (\d+)/(\d+)", output)
    if not match:
        raise RuntimeError(f"control command produced no score: {output[-1000:]}")
    return int(match.group(1)), int(match.group(2)), output


def main() -> int:
    states = (
        "baseline", "correct", "backslash_alias", "drive_prefix",
        "symlink_member", "existing_symlink", "partial_write", "alias_duplicate",
        "file_dir_collision", "compressed_limit", "overwrite_existing", "tamper",
    )
    results = {}
    with tempfile.TemporaryDirectory(prefix="llm-hardtest-r5-q37-") as tmp:
        for state in states:
            repo = Path(tmp) / state
            shutil.copytree(SOURCE, repo)
            _apply(state, repo)
            public = _run([sys.executable, "run_tests.py"], repo)
            hidden = _run([sys.executable, str(HIDDEN), str(repo)], repo)
            results[state] = (public[:2], hidden[:2])
            print(f"{state:19} public {public[0]}/{public[1]} "
                  f"hidden {hidden[0]}/{hidden[1]}")
    checks = [
        (results["baseline"][0][0] < results["baseline"][0][1],
         "baseline must fail public tests"),
        (results["correct"][0][0] == results["correct"][0][1],
         "correct control must pass public tests"),
        (results["correct"][1][0] == results["correct"][1][1],
         "correct control must pass hidden tests"),
    ]
    for state in states[2:]:
        public, hidden = results[state]
        checks.append((public[0] == public[1], f"{state} must look public-green"))
        checks.append((hidden[0] < hidden[1], f"{state} must fail held-back checks"))
    failed = [message for ok, message in checks if not ok]
    if failed:
        print("PILOT_CONTROL_MATRIX=False")
        for message in failed:
            print("- " + message)
        return 1
    print("PILOT_CONTROL_MATRIX=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
