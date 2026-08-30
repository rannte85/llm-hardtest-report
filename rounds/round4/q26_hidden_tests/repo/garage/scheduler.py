"""Stay lifecycle: reservations, entry/exit, and billing-window resolution."""

from datetime import datetime
from typing import Tuple

from .models import Stay, StayStatus
from .normalize import normalize_plate
from .rates import get_rate_card, normalize_vehicle_class


class TransitionError(RuntimeError):
    """Raised when a stay is asked to make an illegal state transition."""


def reserve(
    stay_id: str,
    plate: str,
    vehicle_class: str,
    start: datetime,
    end: datetime,
) -> Stay:
    """Create a new RESERVED stay.

    The vehicle class is validated eagerly so that a bad class fails at
    booking time rather than at checkout time.
    """
    if end <= start:
        raise TransitionError("reservation must end after it starts")
    canonical_class = normalize_vehicle_class(vehicle_class)
    get_rate_card(canonical_class)  # validation only

    stay = Stay(
        stay_id=stay_id,
        plate=normalize_plate(plate),
        vehicle_class=canonical_class,
        reserved_start=start,
        reserved_end=end,
    )
    stay.log("reserved", start)
    return stay


def check_in(stay: Stay, at: datetime) -> Stay:
    """Vehicle enters the garage."""
    if stay.status is not StayStatus.RESERVED:
        raise TransitionError(
            "cannot check in a stay in state {0}".format(stay.status.value)
        )
    stay.actual_start = at
    stay.status = StayStatus.ACTIVE
    stay.log("checked_in", at)
    return stay


def check_out(stay: Stay, at: datetime) -> Stay:
    """Vehicle leaves the garage."""
    if stay.status is not StayStatus.ACTIVE:
        raise TransitionError(
            "cannot check out a stay in state {0}".format(stay.status.value)
        )
    if stay.actual_start is None or at <= stay.actual_start:
        raise TransitionError("check-out must be after check-in")
    stay.actual_end = at
    stay.status = StayStatus.CLOSED
    stay.log("checked_out", at)
    return stay


def extend(stay: Stay, new_end: datetime) -> Stay:
    """Push a stay's end later.

    Allowed while the stay is still open.  For an already-closed stay the
    caller must reopen it instead; silently moving a closed window would
    desynchronise any receipt already posted for it.
    """
    if not stay.is_open():
        raise TransitionError(
            "cannot extend a stay in state {0}".format(stay.status.value)
        )
    current_end = stay.actual_end or stay.reserved_end
    if new_end <= current_end:
        raise TransitionError("extension must move the end later")
    stay.reserved_end = new_end
    stay.log("extended", new_end)
    return stay


def cancel(stay: Stay, at: datetime) -> Stay:
    """Cancel a stay that has not started yet."""
    if stay.status is not StayStatus.RESERVED:
        raise TransitionError(
            "cannot cancel a stay in state {0}".format(stay.status.value)
        )
    stay.status = StayStatus.CANCELLED
    stay.log("cancelled", at)
    return stay


def billing_window(stay: Stay) -> Tuple[datetime, datetime]:
    """Resolve the window that should actually be billed for ``stay``.

    * CLOSED  -> the realised entry/exit pair.
    * ACTIVE  -> realised entry, planned exit (the vehicle is still inside).
    * RESERVED -> the planned window.
    * CANCELLED -> nothing to bill.
    """
    if stay.status is StayStatus.CANCELLED:
        raise TransitionError("a cancelled stay has no billing window")
    if stay.status is StayStatus.CLOSED:
        return (stay.actual_start, stay.actual_end)
    if stay.status is StayStatus.ACTIVE:
        return (stay.actual_start, stay.reserved_end)
    return (stay.reserved_start, stay.reserved_end)
