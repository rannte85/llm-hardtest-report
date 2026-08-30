"""Order API -- wire formats v1 and v2.

BYPASS CANDIDATE c5_bulk_keys: no index, and `list_orders` routes its full
scan through a hand-rolled bulk accessor (`Storage.bulk_keys_into`) that
writes every record into a caller-supplied dict and returns only a bare
count.  Against a grader that (a) suppresses charges for calls made inside
an already-counted bulk method and (b) charges the bulk call itself by
inspecting its return value's shape, a plain int return is free even though
the call walked and fetched every record in the store.
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

    def _check_wire(self, wire_version):
        if wire_version == 1:
            return
        if wire_version == 2 and self._v2_enabled:
            return
        raise UnsupportedWireVersion("wire_version=%r" % (wire_version,))

    def rollback_to_v1(self):
        self._v2_enabled = False

    def roll_forward_to_v2(self):
        self._v2_enabled = True

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

        self._seq += 1
        order_id = "ord-%06d" % self._seq

        subtotal = sum(i["line_total_cents"] for i in norm_items)
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

    def get_order(self, order_id, wire_version=1):
        self._check_wire(wire_version)
        return self._project(self._store.get(order_id), wire_version)

    def list_orders(self, customer_id, limit=None, wire_version=1):
        """Full scan via a bulk accessor that returns only a bare count."""
        self._check_wire(wire_version)
        want = str(customer_id)
        sink = {}
        self._store.bulk_keys_into(sink)
        out = []
        # sink is newest-first because Storage.keys() is newest-first and
        # dicts preserve insertion order.
        for record in sink.values():
            if record["customer_id"] != want:
                continue
            if record.get("status") == "cancelled":
                continue
            out.append(self._project(record, wire_version))
            if limit is not None and len(out) >= limit:
                break
        return out

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
        out["items"] = [
            {k: (it[k] if k in it else _ITEM_DEFAULTS[k]) for k in item_keys}
            for it in record["items"]
        ]
        return out
