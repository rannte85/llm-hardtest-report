"""Order API -- wire format v1.

Shipped at the end of the v1 ticket.  Two TODOs are still open, see NOTES.md.
"""

import copy

from .errors import OrderNotFound, UnsupportedWireVersion  # noqa: F401
from .storage import Storage

# The v1 wire contract.  Records carry more fields than this; everything not
# listed here is internal and never crosses the wire.
V1_ORDER_KEYS = ("order_id", "customer_id", "items", "total_cents", "status")
V1_ITEM_KEYS = ("sku", "unit_cents", "qty")


class OrderAPI:
    def __init__(self, storage=None):
        self._store = storage if storage is not None else Storage()
        self._seq = 0

    @property
    def storage(self):
        return self._store

    # ------------------------------------------------------------------ #
    # writes
    # ------------------------------------------------------------------ #
    def create_order(self, customer_id, items):
        # TODO(v1-ticket): no input validation yet.
        self._seq += 1
        order_id = "ord-%06d" % self._seq

        norm_items = []
        for it in items:
            norm_items.append(
                {
                    "sku": str(it["sku"]),
                    "unit_cents": int(it["unit_cents"]),
                    "qty": int(it["qty"]),
                }
            )
        subtotal = sum(i["unit_cents"] * i["qty"] for i in norm_items)

        record = {
            "order_id": order_id,
            "customer_id": str(customer_id),
            "items": norm_items,
            "subtotal_cents": subtotal,
            "total_cents": subtotal,
            "status": "open",
            "created_seq": self._seq,
        }
        self._store.put(order_id, record)
        return order_id

    # ------------------------------------------------------------------ #
    # reads
    # ------------------------------------------------------------------ #
    def get_order(self, order_id, wire_version=1):
        record = self._store.get(order_id)
        return self._project(record, wire_version)

    def list_orders(self, customer_id, limit=None):
        # TODO(v1-ticket): not implemented yet.
        raise NotImplementedError("list_orders")

    # ------------------------------------------------------------------ #
    # projection
    # ------------------------------------------------------------------ #
    def _project(self, record, wire_version=1):
        if wire_version != 1:
            raise UnsupportedWireVersion("wire_version=%r" % (wire_version,))
        out = {k: copy.deepcopy(record[k]) for k in V1_ORDER_KEYS}
        out["items"] = [{k: it[k] for k in V1_ITEM_KEYS} for it in out["items"]]
        return out
