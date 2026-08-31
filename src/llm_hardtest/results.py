from __future__ import annotations


OUTPUT_LIMIT_REASONS = {"length", "max_tokens", "max_output_tokens"}


def output_limited(value: object) -> bool:
    """Return whether a provider explicitly stopped at its output limit."""
    return str(value or "").strip().lower() in OUTPUT_LIMIT_REASONS


def item_status(item: dict) -> str:
    """Normalize current and legacy saved rows to one public result status."""
    explicit = item.get("status")
    if isinstance(explicit, str) and explicit.upper() in {
            "PASS", "FAIL", "INCOMPLETE", "REVIEW", "INVALID"}:
        return explicit.upper()
    if item.get("valid") is False:
        return "INVALID"
    if item.get("incomplete") is True or output_limited(item.get("finish_reason")):
        return "INCOMPLETE"
    if item.get("manual_review_required") or item.get("correct") is None:
        return "REVIEW"
    return "PASS" if item.get("correct") is True else "FAIL"


def result_counts(payload: dict) -> dict[str, int]:
    """Count item statuses, deriving them from rows for old result schemas."""
    counts = {key: 0 for key in ("PASS", "FAIL", "INCOMPLETE", "REVIEW", "INVALID")}
    items = payload.get("results", [])
    for item in items:
        counts[item_status(item)] += 1
    if not items:
        score = int(payload.get("score", 0) or 0)
        total = int(payload.get("total", 0) or 0)
        counts["PASS"] = score
        counts["FAIL"] = max(0, total - score)
        counts["INCOMPLETE"] = int(payload.get("incomplete", 0) or 0)
        counts["REVIEW"] = int(payload.get("manual_review", 0) or 0)
        counts["INVALID"] = int(payload.get("infrastructure_errors", 0) or 0)
    return counts
