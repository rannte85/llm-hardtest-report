"""Naive ZIP extraction with a production boundary-escape bug."""

from __future__ import annotations

import zipfile
from pathlib import Path


def safe_extract(archive_path, destination, max_total_bytes=1048576):
    """Extract a tenant ZIP without yet validating member-controlled paths."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        names = [info.filename for info in archive.infolist() if not info.is_dir()]
        archive.extractall(destination)
    return sorted(names)
