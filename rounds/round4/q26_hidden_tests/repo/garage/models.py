"""Core data structures for the garage stay-billing engine.

Nothing in this module performs pricing or state transitions; it only holds
the shapes that the rest of the package passes around.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import List, Optional, Tuple


class StayStatus(str, Enum):
    """Lifecycle of a single stay."""

    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class RateCard:
    """Pricing parameters for one vehicle class.

    Attributes
    ----------
    vehicle_class:
        Identifier of the class this card prices, e.g. ``"STANDARD"``.
    grace_minutes:
        Length of the free grace allowance.  See rule GR-1 in the README:
        the allowance is granted **once per stay**, not once per day.
    block_minutes:
        Billing granularity.  Partial blocks are always rounded up.
    first_block_count:
        How many blocks of a calendar day are billed at ``first_block_rate``.
    first_block_rate / later_block_rate:
        Price of a block, in yen.
    daily_cap:
        Upper bound on the amount charged for one calendar day (rule CP-1).
    """

    vehicle_class: str
    grace_minutes: int
    block_minutes: int
    first_block_count: int
    first_block_rate: int
    later_block_rate: int
    daily_cap: int


@dataclass
class Segment:
    """One calendar-day slice of a stay's billing window.

    A segment never spans a midnight boundary: ``normalize.split_days`` cuts
    the window so that ``start`` and ``end`` always fall inside the same
    calendar day (``end`` may be the following midnight, which closes the day).

    Attributes
    ----------
    start / end:
        Half-open interval ``[start, end)`` billed by this segment.
    grace:
        Whether this segment consumes the stay's grace allowance.

        Rule GR-1: the grace allowance belongs to the *stay*, not to the day.
        Exactly one segment of a stay may carry ``grace=True``, and it is the
        first one.  Continuation segments — the second and later calendar days
        of a long stay — must carry ``grace=False``.
    """

    start: datetime
    end: datetime
    grace: bool = False

    def minutes(self) -> int:
        """Wall-clock length of the segment in whole minutes."""
        delta = self.end - self.start
        return int(delta.total_seconds() // 60)

    @property
    def day(self) -> date:
        """Calendar day this segment is billed against."""
        return self.start.date()

    def describe(self) -> str:
        return "{0} {1}-{2}{3}".format(
            self.start.date().isoformat(),
            self.start.strftime("%H:%M"),
            self.end.strftime("%H:%M"),
            " (grace)" if self.grace else "",
        )


@dataclass
class Stay:
    """A single vehicle occupancy, reserved and possibly realised."""

    stay_id: str
    plate: str
    vehicle_class: str
    reserved_start: datetime
    reserved_end: datetime
    status: StayStatus = StayStatus.RESERVED
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    history: List[Tuple[str, datetime]] = field(default_factory=list)

    def log(self, event: str, at: datetime) -> None:
        self.history.append((event, at))

    def is_open(self) -> bool:
        return self.status in (StayStatus.RESERVED, StayStatus.ACTIVE)

    def __str__(self) -> str:  # pragma: no cover - debugging aid
        return "Stay({0}, {1}, {2})".format(
            self.stay_id, self.plate, self.status.value
        )
