"""In-memory order storage.

ALTERNATE LEGITIMATE SHAPE (alt_index_in_storage): the per-customer index
lives INSIDE Storage itself instead of inside OrderAPI -- explicitly called
out as a reasonable design in the turn-5 discussion ("storage.py is NOT
frozen -- a submission may legitimately extend it").  `ids_for_customer`
hands back ids only (newest first), priced the same as `keys()`.

Cost model
----------
``get()``              -- one read op per call
``keys()``              -- one read op per call
``ids_for_customer()``  -- one read op per call (ids only, like keys())
``put()``               -- one write op per call
``count()``             -- diagnostic only, not counted
"""

from .errors import OrderNotFound


class Storage:
    def __init__(self):
        self._records = {}
        self._insertion = []  # order ids, oldest first
        # customer_id -> [order_id, ...] newest first.  Not pruned on
        # cancellation -- list_orders still filters on status, same as the
        # baseline scan shape, so a stale id here costs nothing beyond the
        # one extra (cheap) `get()` that already happens for every listed id.
        self._by_customer = {}
        self.read_ops = 0
        self.write_ops = 0

    # ------------------------------------------------------------------ #
    # writes
    # ------------------------------------------------------------------ #
    def put(self, order_id, record):
        """Insert or replace a record.  Costs one write op."""
        self.write_ops += 1
        if order_id not in self._records:
            self._insertion.append(order_id)
            self._by_customer.setdefault(record["customer_id"], []).insert(0, order_id)
        self._records[order_id] = record

    # ------------------------------------------------------------------ #
    # reads
    # ------------------------------------------------------------------ #
    def get(self, order_id):
        """Return the *live* stored record.  Costs one read op."""
        self.read_ops += 1
        try:
            return self._records[order_id]
        except KeyError:
            raise OrderNotFound(order_id) from None

    def keys(self):
        """Return every order id, newest first.  Costs one read op."""
        self.read_ops += 1
        return list(reversed(self._insertion))

    def ids_for_customer(self, customer_id):
        """Every order id for one customer, newest first.  Ids only -- same
        price as keys(): one read op, regardless of how many ids come back."""
        self.read_ops += 1
        return list(self._by_customer.get(customer_id, ()))

    # ------------------------------------------------------------------ #
    # diagnostics (uncounted -- for tests and ops tooling only)
    # ------------------------------------------------------------------ #
    def count(self):
        return len(self._records)

    def raw_ids(self):
        """Every id in insertion order.  Diagnostic only, uncounted."""
        return list(self._insertion)

    def raw_peek(self, order_id):
        """Look at a record without paying a read op.  Diagnostic only."""
        return self._records.get(order_id)

    def reset_counters(self):
        self.read_ops = 0
        self.write_ops = 0
