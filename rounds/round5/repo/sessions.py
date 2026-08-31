"""Small session refresh service used by the Round 5 pilot."""

from __future__ import annotations

import threading
import uuid


class AcceptedThenTimedOut(TimeoutError):
    """The notifier accepted an event but its acknowledgement was lost."""


class TokenStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._by_operation = {}
        self.rotations = 0

    def rotate(self, session_id: str, operation_id: str) -> str:
        with self._lock:
            if operation_id not in self._by_operation:
                self.rotations += 1
                self._by_operation[operation_id] = f"token-{session_id}-{self.rotations}"
            return self._by_operation[operation_id]


class Notifier:
    def __init__(self, timeout_after_accept_once: bool = False):
        self._lock = threading.Lock()
        self._accepted = set()
        self.events = []
        self._timeout_once = timeout_after_accept_once

    def publish(self, event: dict, operation_id: str) -> None:
        with self._lock:
            if operation_id not in self._accepted:
                self._accepted.add(operation_id)
                self.events.append(dict(event))
                if self._timeout_once:
                    self._timeout_once = False
                    raise AcceptedThenTimedOut("acknowledgement lost after accept")


class SessionService:
    def __init__(self, store: TokenStore, notifier: Notifier):
        self.store = store
        self.notifier = notifier

    @staticmethod
    def _response(token: str, client_version: int) -> dict:
        if client_version == 1:
            return {"token": token}
        if client_version == 2:
            return {"token": token, "schema": 2}
        raise ValueError("unsupported client version")

    def refresh(self, session_id: str, request_id: str, client_version: int) -> dict:
        # BUG: retry attempts generate a fresh operation identity at both durable
        # boundaries, defeating the idempotency those boundaries already provide.
        store_operation = uuid.uuid4().hex
        notify_operation = uuid.uuid4().hex
        token = self.store.rotate(session_id, store_operation)
        self.notifier.publish(
            {"session_id": session_id, "kind": "session_refreshed"}, notify_operation)
        return self._response(token, client_version)
