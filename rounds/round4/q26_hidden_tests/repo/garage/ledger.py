"""Receipts and the posting ledger.

The ledger keeps a per-day breakdown because the accounting export needs one
line per calendar day, so it walks the segments itself instead of asking
:func:`garage.billing.charge_stay` for a single number.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

from .billing import charge_segment
from .models import Segment, Stay, StayStatus
from .normalize import build_segments, describe_window
from .rates import get_rate_card
from .scheduler import billing_window


class LedgerError(RuntimeError):
    """Raised for posting operations that would corrupt the ledger."""


@dataclass(frozen=True)
class LineItem:
    """One calendar day of one stay."""

    stay_id: str
    day: date
    minutes: int
    grace_applied: bool
    amount: int

    def label(self) -> str:
        suffix = " (incl. grace)" if self.grace_applied else ""
        return "{0} {1}min{2}".format(self.day.isoformat(), self.minutes, suffix)


@dataclass
class Receipt:
    """Immutable-ish snapshot of what a stay was billed."""

    stay_id: str
    plate: str
    vehicle_class: str
    window_label: str
    items: List[LineItem] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(item.amount for item in self.items)

    @property
    def grace_count(self) -> int:
        """How many line items consumed a grace allowance."""
        return sum(1 for item in self.items if item.grace_applied)

    def day_totals(self) -> Dict[date, int]:
        totals: Dict[date, int] = {}
        for item in self.items:
            totals[item.day] = totals.get(item.day, 0) + item.amount
        return totals


class Ledger:
    """In-memory posting ledger."""

    def __init__(self) -> None:
        self._receipts: Dict[str, Receipt] = {}

    # -- posting ---------------------------------------------------------

    def post_stay(self, stay: Stay) -> Receipt:
        """Price ``stay`` and record a receipt for it."""
        if stay.stay_id in self._receipts:
            raise LedgerError(
                "stay {0} already posted; use reprice()".format(stay.stay_id)
            )
        receipt = self._build_receipt(stay)
        self._receipts[stay.stay_id] = receipt
        return receipt

    def reprice(self, stay: Stay) -> Receipt:
        """Recompute a receipt after the stay's window moved."""
        if stay.stay_id not in self._receipts:
            raise LedgerError(
                "stay {0} has not been posted".format(stay.stay_id)
            )
        receipt = self._build_receipt(stay)
        self._receipts[stay.stay_id] = receipt
        return receipt

    def void(self, stay_id: str) -> Receipt:
        """Remove a receipt, returning the voided snapshot."""
        try:
            return self._receipts.pop(stay_id)
        except KeyError:
            raise LedgerError("stay {0} has not been posted".format(stay_id))

    # -- queries ---------------------------------------------------------

    def receipt_for(self, stay_id: str) -> Optional[Receipt]:
        return self._receipts.get(stay_id)

    def total_for_plate(self, plate: str) -> int:
        return sum(
            r.total for r in self._receipts.values() if r.plate == plate
        )

    def grand_total(self) -> int:
        return sum(r.total for r in self._receipts.values())

    def day_totals(self) -> Dict[date, int]:
        totals: Dict[date, int] = {}
        for receipt in self._receipts.values():
            for day, amount in receipt.day_totals().items():
                totals[day] = totals.get(day, 0) + amount
        return totals

    # -- internals -------------------------------------------------------

    def _build_receipt(self, stay: Stay) -> Receipt:
        if stay.status is StayStatus.CANCELLED:
            raise LedgerError("cannot post a cancelled stay")
        card = get_rate_card(stay.vehicle_class)
        start, end = billing_window(stay)
        segments: List[Segment] = build_segments(start, end, card)

        items: List[LineItem] = []
        for segment in segments:
            items.append(
                LineItem(
                    stay_id=stay.stay_id,
                    day=segment.day,
                    minutes=segment.minutes(),
                    grace_applied=segment.grace,
                    amount=charge_segment(segment, card),
                )
            )
        return Receipt(
            stay_id=stay.stay_id,
            plate=stay.plate,
            vehicle_class=stay.vehicle_class,
            window_label=describe_window(start, end),
            items=items,
        )
