"""Normalisation helpers.

Everything here runs *before* pricing.  The job of this module is to turn
loosely-shaped operator input and a raw billing window into the canonical
segment list that :mod:`garage.billing` knows how to price.
"""

from datetime import datetime, time, timedelta
from typing import List, Tuple

from .models import RateCard, Segment


class InvalidWindow(ValueError):
    """Raised for a billing window that cannot be priced."""


def normalize_plate(raw: str) -> str:
    """Canonicalise a licence plate.

    Uppercases, drops separators and collapses whitespace so that
    ``" shinagawa 500-a 12-34 "`` and ``"SHINAGAWA500A1234"`` compare equal.
    """
    if raw is None:
        raise ValueError("plate is required")
    stripped = "".join(ch for ch in str(raw) if ch.isalnum())
    if not stripped:
        raise ValueError("plate is required")
    return stripped.upper()


def next_midnight(moment: datetime) -> datetime:
    """First midnight strictly after ``moment``."""
    return datetime.combine(moment.date() + timedelta(days=1), time(0, 0))


def split_days(start: datetime, end: datetime) -> List[Tuple[datetime, datetime]]:
    """Slice the half-open window ``[start, end)`` at midnight boundaries.

    The result never contains an empty window: a stay that ends exactly at
    midnight closes on the previous calendar day rather than opening a
    zero-length slice on the next one.
    """
    if start is None or end is None:
        raise InvalidWindow("billing window requires both endpoints")
    if end <= start:
        raise InvalidWindow(
            "billing window must be non-empty: {0} -> {1}".format(start, end)
        )

    windows: List[Tuple[datetime, datetime]] = []
    cursor = start
    while cursor < end:
        boundary = next_midnight(cursor)
        slice_end = boundary if boundary < end else end
        windows.append((cursor, slice_end))
        cursor = slice_end
    return windows


def build_segments(start: datetime, end: datetime, card: RateCard) -> List[Segment]:
    """Build the priceable segment list for a billing window.

    Each calendar day of the window becomes one :class:`~garage.models.Segment`
    so that the per-day block ladder (BL-1) and the per-day cap (CP-1) can be
    applied independently.

    The stay's grace allowance (GR-1) is attached here rather than in the
    pricing layer, because only this function can see where the stay begins.
    """
    windows = split_days(start, end)
    grace_pending = card.grace_minutes > 0

    segments: List[Segment] = []
    for (slice_start, slice_end) in windows:
        segments.append(
            Segment(start=slice_start, end=slice_end, grace=grace_pending)
        )
    return segments


def window_minutes(start: datetime, end: datetime) -> int:
    """Whole minutes covered by ``[start, end)``."""
    if end <= start:
        raise InvalidWindow("billing window must be non-empty")
    return int((end - start).total_seconds() // 60)


def describe_window(start: datetime, end: datetime) -> str:
    """Human readable form used in receipts and operator logs."""
    if start.date() == end.date():
        return "{0} {1}-{2}".format(
            start.date().isoformat(),
            start.strftime("%H:%M"),
            end.strftime("%H:%M"),
        )
    return "{0} {1} -> {2} {3}".format(
        start.date().isoformat(),
        start.strftime("%H:%M"),
        end.date().isoformat(),
        end.strftime("%H:%M"),
    )
