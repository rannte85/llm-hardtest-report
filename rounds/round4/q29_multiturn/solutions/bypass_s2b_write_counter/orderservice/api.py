"""Order API -- wire formats v1 and v2.  REFERENCE SOLUTION (turns 1-5).

Design points that the turn thread never spells out but that the code has to
keep:

  INV-1  a payload handed to a caller is a deep copy; `Storage.get` returns the
         live record, so `_project` is the only place that may hand out data.
  INV-2  `list_orders` is newest-first (and `limit` therefore takes the newest
         N).  The turn-5 per-customer index has to be maintained newest-first
         for this to survive; appending on create would silently reverse it.
"""

import copy
import math

from .errors import OrderNotFound, UnsupportedWireVersion  # noqa: F401
from .storage import Storage

V1_ORDER_KEYS = ("order_id", "customer_id", "items", "total_cents", "status")
V1_ITEM_KEYS = ("sku", "unit_cents", "qty")
V2_ORDER_KEYS = V1_ORDER_KEYS + ("subtotal_cents", "discount_cents", "discount_pct", "priority")
V2_ITEM_KEYS = V1_ITEM_KEYS + ("line_total_cents",)

VALID_PRIORITIES = ("standard", "express")

# Records written before turn 2 have no v2 fields; project them as defaults
# rather than crashing or emitting nulls.
_ORDER_DEFAULTS = {"subtotal_cents": 0, "discount_cents": 0, "discount_pct": 0.0, "priority": "standard"}
_ITEM_DEFAULTS = {"line_total_cents": 0}

_UNSET = object()


class OrderAPI:
    def __init__(self, storage=None):
        self._store = storage if storage is not None else Storage()
        self._seq = 0
        self._v2_enabled = True

    @property
    def storage(self):
        return self._store

    # ------------------------------------------------------------------ #
    # wire version gating (turns 2 and 4)
    # ------------------------------------------------------------------ #
    def _check_wire(self, wire_version):
        if wire_version == 1:
            return
        if wire_version == 2 and self._v2_enabled:
            return
        raise UnsupportedWireVersion("wire_version=%r" % (wire_version,))

    def rollback_to_v1(self):
        self._v2_enabled = False
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
    # writes
    # ------------------------------------------------------------------ #
    def create_order(self, customer_id, items, priority=_UNSET, discount_pct=_UNSET):
        if not self._v2_enabled and (priority is not _UNSET or discount_pct is not _UNSET):
            raise UnsupportedWireVersion("v2-only fields are refused while rolled back to v1")

        priority = "standard" if priority is _UNSET else priority
        discount_pct = 0.0 if discount_pct is _UNSET else discount_pct

        if priority not in VALID_PRIORITIES:
            raise ValueError("priority must be one of %r, got %r" % (VALID_PRIORITIES, priority))
        if isinstance(discount_pct, bool) or not isinstance(discount_pct, (int, float)):
            raise ValueError("discount_pct must be a number, got %r" % (discount_pct,))
        if not (0.0 <= float(discount_pct) < 1.0):
            raise ValueError("discount_pct must satisfy 0.0 <= p < 1.0, got %r" % (discount_pct,))

        norm_items = self._validate_items(items)

        # Nothing has been written yet -- validation failures leave no trace.
        self._seq += 1
        order_id = "ord-%06d" % self._seq

        subtotal = sum(i["line_total_cents"] for i in norm_items)
        # Turn 3: floor the discount amount, never the total, and keep the
        # result an int -- old clients type-check total_cents.
        discount = math.floor(subtotal * float(discount_pct))
        record = {
            "order_id": order_id,
            "customer_id": str(customer_id),
            "items": norm_items,
            "subtotal_cents": int(subtotal),
            "discount_pct": float(discount_pct),
            "discount_cents": int(discount),
            "total_cents": int(subtotal - discount),
            "status": "open",
            "priority": priority,
            "created_seq": self._seq,
        }
        self._store.put(order_id, record)
        return order_id

    @staticmethod
    def _validate_items(items):
        if not items:
            raise ValueError("an order needs at least one item")
        norm = []
        for raw in items:
            qty = int(raw["qty"])
            unit = int(raw["unit_cents"])
            if qty < 1:
                raise ValueError("qty must be >= 1, got %r" % (qty,))
            if unit < 0:
                raise ValueError("unit_cents must be >= 0, got %r" % (unit,))
            norm.append(
                {
                    "sku": str(raw["sku"]),
                    "unit_cents": unit,
                    "qty": qty,
                    "line_total_cents": unit * qty,
                }
            )
        return norm

    def cancel_order(self, order_id):
        record = self._store.get(order_id)  # raises OrderNotFound
        if record["status"] == "cancelled":
            return
        record["status"] = "cancelled"
        self._store.put(order_id, record)

    # ------------------------------------------------------------------ #
    # reads
    # ------------------------------------------------------------------ #
    def get_order(self, order_id, wire_version=1):
        self._check_wire(wire_version)
        return self._project(self._store.get(order_id), wire_version)

    def list_orders(self, customer_id, limit=None, wire_version=1):
        """Full scan over the store.  Storage.keys() is newest-first (INV-2)."""
        self._check_wire(wire_version)
        want = str(customer_id)
        out = []
        for order_id in self._store.keys():
            record = self._store.get(order_id)
            if record["customer_id"] != want:
                continue
            if record.get("status") == "cancelled":
                continue
            out.append(self._project(record, wire_version))
            if limit is not None and len(out) >= limit:
                break
        return out

    # ------------------------------------------------------------------ #
    # projection -- the single choke point where a record becomes a payload
    # ------------------------------------------------------------------ #
    def _project(self, record, wire_version=1):
        if wire_version == 1:
            order_keys, item_keys = V1_ORDER_KEYS, V1_ITEM_KEYS
        elif wire_version == 2:
            order_keys, item_keys = V2_ORDER_KEYS, V2_ITEM_KEYS
        else:
            raise UnsupportedWireVersion("wire_version=%r" % (wire_version,))

        out = {}
        for key in order_keys:
            if key == "items":
                continue
            out[key] = copy.deepcopy(record[key]) if key in record else _ORDER_DEFAULTS[key]
        # INV-1: rebuild every item dict; never hand back the stored list.
        out["items"] = [
            {k: (it[k] if k in it else _ITEM_DEFAULTS[k]) for k in item_keys}
            for it in record["items"]
        ]
        return out
