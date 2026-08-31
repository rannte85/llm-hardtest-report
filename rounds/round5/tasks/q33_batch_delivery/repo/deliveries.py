"""Batch delivery retry service with an intentionally broken operation identity."""

from __future__ import annotations

import threading
import uuid


class AcceptedThenTimedOut(RuntimeError):
    pass


class Ledger:
    def __init__(self):
        self.charges = []
        self._operations = {}
        self._lock = threading.Lock()

    def charge(self, delivery_id, operation_id):
        with self._lock:
            if operation_id not in self._operations:
                self._operations[operation_id] = delivery_id
                self.charges.append(delivery_id)
            return self._operations[operation_id]


class Sender:
    def __init__(self, timeout_after_accept_once=False):
        self.events = []
        self._operations = {}
        self._timeout_once = timeout_after_accept_once
        self._lock = threading.Lock()

    def send(self, delivery_id, operation_id):
        with self._lock:
            if operation_id not in self._operations:
                self._operations[operation_id] = delivery_id
                self.events.append(delivery_id)
                if self._timeout_once:
                    self._timeout_once = False
                    raise AcceptedThenTimedOut("downstream accepted before timeout")
            return self._operations[operation_id]


class BatchDeliveryService:
    def __init__(self, ledger, sender):
        self.ledger = ledger
        self.sender = sender

    def retry_batch(self, batch_id, request_id, delivery_ids, client_version):
        delivered = []
        for delivery_id in delivery_ids:
            charge_operation = uuid.uuid4().hex
            send_operation = uuid.uuid4().hex
            self.ledger.charge(delivery_id, charge_operation)
            delivered.append(self.sender.send(delivery_id, send_operation))
        if client_version == 1:
            return {"delivered": delivered}
        return {"delivered": delivered, "schema": 2}
