"""Pricing.

``charge_segment`` is the only place a yen amount is produced; every other
entry point in the package funnels through it so that the block ladder (BL-1)
and the daily cap (CP-1) are applied exactly once per calendar day.
"""

import math
from datetime import datetime
from typing import List, Optional, Tuple

from .models import RateCard, Segment, Stay
from .normalize import build_segments
from .rates import get_rate_card
from .scheduler import billing_window


def billable_minutes(segment: Segment, card: RateCard) -> int:
    """Minutes of ``segment`` that survive the grace allowance.

    The decision of *whether* this segment carries the stay's grace allowance
    is not made here — it arrives on the segment (see ``Segment.grace``).
    """
    minutes = segment.minutes()
    if segment.grace:
        minutes = minutes - card.grace_minutes
    return max(0, minutes)


def block_count(minutes: int, card: RateCard) -> int:
    """Number of *started* billing blocks in ``minutes``."""
    if minutes <= 0:
        return 0
    return int(math.ceil(minutes / float(card.block_minutes)))


def ladder_amount(blocks: int, card: RateCard) -> int:
    """Price ``blocks`` through the per-day two-tier ladder (BL-1)."""
    if blocks <= 0:
        return 0
    first = min(blocks, card.first_block_count)
    later = blocks - first
    return first * card.first_block_rate + later * card.later_block_rate


# TODO(#412): the March report shows overnight stays coming out cheaper than
# the counter takings.  Suspect the grace deduction below.
def charge_segment(segment: Segment, card: RateCard) -> int:
    """Price a single calendar-day segment, in yen."""
    minutes = billable_minutes(segment, card)
    blocks = block_count(minutes, card)
    amount = ladder_amount(blocks, card)
    return min(amount, card.daily_cap)


def itemize_window(
    start: datetime,
    end: datetime,
    card: RateCard,
) -> List[Tuple[Segment, int]]:
    """Segment-by-segment breakdown of a raw window."""
    return [(seg, charge_segment(seg, card)) for seg in build_segments(start, end, card)]


def charge_window(start: datetime, end: datetime, card: RateCard) -> int:
    """Total price of a raw window."""
    return sum(amount for _seg, amount in itemize_window(start, end, card))


def charge_stay(stay: Stay, card: Optional[RateCard] = None) -> int:
    """Total price of ``stay``, in yen."""
    if card is None:
        card = get_rate_card(stay.vehicle_class)
    start, end = billing_window(stay)
    return charge_window(start, end, card)


def quote(
    vehicle_class: str,
    start: datetime,
    end: datetime,
) -> int:
    """Price a hypothetical window without creating a stay."""
    return charge_window(start, end, get_rate_card(vehicle_class))
