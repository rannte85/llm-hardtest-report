"""Rate card table and lookup.

Prices are in whole yen.  The table is intentionally static: the back office
edits it by hand and redeploys, so there is no loader here.
"""

from typing import Dict, List

from .models import RateCard


class UnknownVehicleClass(ValueError):
    """Raised when a stay references a vehicle class with no rate card."""


_CARDS: Dict[str, RateCard] = {
    "COMPACT": RateCard(
        vehicle_class="COMPACT",
        grace_minutes=30,
        block_minutes=30,
        first_block_count=4,
        first_block_rate=200,
        later_block_rate=80,
        daily_cap=4000,
    ),
    "STANDARD": RateCard(
        vehicle_class="STANDARD",
        grace_minutes=30,
        block_minutes=30,
        first_block_count=4,
        first_block_rate=300,
        later_block_rate=100,
        daily_cap=6000,
    ),
    "LARGE": RateCard(
        vehicle_class="LARGE",
        grace_minutes=30,
        block_minutes=30,
        first_block_count=4,
        first_block_rate=400,
        later_block_rate=150,
        daily_cap=6000,
    ),
}


def normalize_vehicle_class(raw: str) -> str:
    """Canonicalise a vehicle class string.

    Accepts sloppy operator input such as ``" standard "`` or ``"Large"``.
    """
    if raw is None:
        raise UnknownVehicleClass("vehicle class is required")
    canonical = str(raw).strip().upper().replace("-", "_")
    if not canonical:
        raise UnknownVehicleClass("vehicle class is required")
    return canonical


def get_rate_card(vehicle_class: str) -> RateCard:
    """Return the rate card for ``vehicle_class``.

    Raises
    ------
    UnknownVehicleClass
        If no card is registered for the (normalised) class.
    """
    canonical = normalize_vehicle_class(vehicle_class)
    try:
        return _CARDS[canonical]
    except KeyError:
        raise UnknownVehicleClass(
            "no rate card for vehicle class {0!r}".format(vehicle_class)
        )


def known_classes() -> List[str]:
    """Sorted list of vehicle classes that have a rate card."""
    return sorted(_CARDS)
