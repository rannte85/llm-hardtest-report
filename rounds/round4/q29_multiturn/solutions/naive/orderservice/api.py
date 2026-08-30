"""Order API -- v1 + v2.  NAIVE SOLUTION (the trap).

This is what turn-by-turn greedy implementation produces: every turn's stated
requirement is satisfied, the whole public suite is green, and five earlier
properties have quietly died.

  1. `_project` filters top-level keys only -- items are passed through, so v1
     items leak `line_total_cents` and the caller gets the store's live list.
  2. the turn-5 index appends on create, so listings come back oldest-first.
  3. `total_cents = int(subtotal * (1 - pct))` -- an int, but off by one whenever
     the product lands just under a whole cent.
  4. `rollback_to_v1` "reverts the data" by resetting v2 fields in place.
  5. `cancel_order` never touches the index, so cancelled orders keep listing.
"""

import math  # noqa: F401

from .errors import OrderNotFound, UnsupportedWireVersion  # noqa: F401
from .storage import Storage

V1_ORDER_KEYS = ("order_id", "customer_id", "items", "total_cents", "status")
V1_ITEM_KEYS = ("sku", "unit_cents", "qty")
V2_ORDER_KEYS = V1_ORDER_KEYS + ("subtotal_cents", "discount_cents", "discount_pct", "priority")
V2_ITEM_KEYS = V1_ITEM_KEYS + ("line_total_cents",)

VALID_PRIORITIES = ("standard", "express")
_UNSET = object()


class OrderAPI:
    def __init__(self, storage=None):
        self._store = storage if storage is not None else Storage()
        self._seq = 0
        self._v2_enabled = True
        self._by_customer = {}

    @property
    def storage(self):
        return self._store

    def _check_wire(self, wire_version):
        if wire_version == 1:
            return
        if wire_version == 2 and self._v2_enabled:
            return
        raise UnsupportedWireVersion("wire_version=%r" % (wire_version,))

    def rollback_to_v1(self):
        self._v2_enabled = False
        # DEFECT 4: "roll the data back too" -- writes, and loses the v2 fields.
        for order_id in self._store.keys():
            record = self._store.get(order_id)
            record["priority"] = "standard"
            record["discount_pct"] = 0.0
            record["discount_cents"] = 0
            record["total_cents"] = record["subtotal_cents"]
            self._store.put(order_id, record)

    def roll_forward_to_v2(self):
        self._v2_enabled = True

    # ------------------------------------------------------------------ #
    def create_order(self, customer_id, items, priority=_UNSET, discount_pct=_UNSET):
        if not self._v2_enabled and (priority is not _UNSET or discount_pct is not _UNSET):
            raise UnsupportedWireVersion("v2-only fields are refused while rolled back to v1")

        priority = "standard" if priority is _UNSET else priority
        discount_pct = 0.0 if discount_pct is _UNSET else discount_pct

        if priority not in VALID_PRIORITIES:
            raise ValueError("bad priority %r" % (priority,))
        if isinstance(discount_pct, bool) or not isinstance(discount_pct, (int, float)):
            raise ValueError("bad discount_pct %r" % (discount_pct,))
        if not (0.0 <= float(discount_pct) < 1.0):
            raise ValueError("bad discount_pct %r" % (discount_pct,))

        if not items:
            raise ValueError("empty item list")
        norm_items = []
        for raw in items:
            qty = int(raw["qty"])
            unit = int(raw["unit_cents"])
            if qty < 1:
                raise ValueError("bad qty %r" % (qty,))
            if unit < 0:
                raise ValueError("bad unit_cents %r" % (unit,))
            norm_items.append(
                {"sku": str(raw["sku"]), "unit_cents": unit, "qty": qty, "line_total_cents": unit * qty}
            )

        self._seq += 1
        order_id = "ord-%06d" % self._seq
        subtotal = sum(i["line_total_cents"] for i in norm_items)
        # DEFECT 3: int() of the discounted total instead of flooring the discount.
        total = int(subtotal * (1.0 - float(discount_pct)))
        record = {
            "order_id": order_id,
            "customer_id": str(customer_id),
            "items": norm_items,
            "subtotal_cents": int(subtotal),
            "discount_pct": float(discount_pct),
            "discount_cents": int(subtotal - total),
            "total_cents": total,
            "status": "open",
            "priority": priority,
            "created_seq": self._seq,
        }
        self._store.put(order_id, record)
        # DEFECT 2: append -> the index is oldest-first.
        self._by_customer.setdefault(record["customer_id"], []).append(order_id)
        return order_id

    def cancel_order(self, order_id):
        record = self._store.get(order_id)
        record["status"] = "cancelled"
        self._store.put(order_id, record)
        # DEFECT 5: the index is never updated.

    # ------------------------------------------------------------------ #
    def get_order(self, order_id, wire_version=1):
        self._check_wire(wire_version)
        return self._project(self._store.get(order_id), wire_version)

    def list_orders(self, customer_id, limit=None, wire_version=1):
        self._check_wire(wire_version)
        out = []
        for order_id in self._by_customer.get(str(customer_id), ()):
            record = self._store.get(order_id)
            out.append(self._project(record, wire_version))
            if limit is not None and len(out) >= limit:
                break
        return out

    # ------------------------------------------------------------------ #
    def _project(self, record, wire_version=1):
        if wire_version == 1:
            order_keys = V1_ORDER_KEYS
        elif wire_version == 2:
            order_keys = V2_ORDER_KEYS
        else:
            raise UnsupportedWireVersion("wire_version=%r" % (wire_version,))
        # DEFECT 1: top-level filter only; `items` goes out by reference.
        return {k: record[k] for k in order_keys}
