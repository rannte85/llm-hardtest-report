"""Layered configuration merge with intentionally broken falsy-value semantics."""

from __future__ import annotations

import copy


def merge_config(base, overlay):
    """Return a merged configuration without changing either input."""
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if not value:
            continue
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_config(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result
