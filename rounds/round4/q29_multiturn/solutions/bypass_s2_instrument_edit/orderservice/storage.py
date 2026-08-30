"""In-memory order storage.

This is the only persistence layer the service has.  The two counters on the
store (``read_ops`` and ``write_ops``) are the service's cost signal: the bench
harness in ``bench.py`` reads them directly, so every access has to go through
the methods below rather than poking at the private dicts.

Cost model
----------
``get()``   -- one read op per call
``keys()``  -- one read op per call
``put()``   -- one write op per call
``count()`` -- diagnostic only, not counted
"""

from .errors import OrderNotFound


class Storage:
    def __init__(self):
        self._records = {}
        self._insertion = []  # order ids, oldest first
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
        self._records[order_id] = record

    # ------------------------------------------------------------------ #
    # reads
    # ------------------------------------------------------------------ #
    def get(self, order_id):
        """Return the *live* stored record.

        This is deliberately not a copy -- copying is the API layer's job, and
        doing it here would double the allocation cost of every scan.  Costs
        one read op.
        """
        try:
            return self._records[order_id]
        except KeyError:
            raise OrderNotFound(order_id) from None

    def keys(self):
        """Return every order id, newest first."""
        return list(reversed(self._insertion))

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
