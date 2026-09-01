from __future__ import annotations

import re


MAX_UNSUPPORTED_CALLS_PER_AGENT_TURN = 3
UNSUPPORTED_CALL_PATTERN = re.compile(
    r"^.*\b(?:ERROR\s+codex_core::tools::router:\s+error=|"
    r"tool router error:\s*)unsupported call:\s*([A-Za-z0-9_.-]+)",
    re.I | re.M,
)
UNAVAILABLE_TOOL_PATTERN = re.compile(
    r"^.*\bERROR\s+codex_core::tools::router:\s+error="
    r"([A-Za-z0-9_.-]+)\s+is unavailable in [^\r\n]* mode\b",
    re.I | re.M,
)


def unsupported_tool_calls(transcript: str) -> list[str]:
    """Return normalized unsupported tool names from authoritative router errors."""
    text = str(transcript or "")
    matches = UNSUPPORTED_CALL_PATTERN.findall(text)
    matches += UNAVAILABLE_TOOL_PATTERN.findall(text)
    return [name.lower() for name in matches]
