"""Shared HTTP cache with fail-closed variant and revalidation policy."""

from __future__ import annotations

import math
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass


class CacheError(RuntimeError):
    pass


_TOKEN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_SENSITIVE = {"authorization", "cookie", "range", "if-none-match",
              "if-modified-since"}
_HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate",
               "proxy-authorization", "te", "trailer", "transfer-encoding",
               "upgrade"}


@dataclass
class _Entry:
    vary: tuple[str, ...]
    values: tuple[str, ...]
    body: bytes
    fields: dict[str, list[str]]
    stored_at: float
    age: int
    max_age: int
    stale_if_error: int | None


class _Flight:
    def __init__(self, lock):
        self.condition = threading.Condition(lock)
        self.done = False
        self.result = None
        self.error = None


def _header_pairs(value, request=False):
    if value is None and request:
        pairs = []
    elif isinstance(value, Mapping):
        pairs = list(value.items())
    else:
        if isinstance(value, (str, bytes)):
            raise CacheError("headers must be pairs")
        try:
            pairs = list(value)
        except (TypeError, ValueError) as exc:
            raise CacheError("headers must be pairs") from exc
    normalized = {}
    fields = {}
    wire = {}
    for pair in pairs:
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise CacheError("headers must be pairs")
        name, raw_value = pair
        if (not isinstance(name, str) or not name.isascii()
                or _TOKEN.fullmatch(name) is None):
            raise CacheError("invalid header name")
        if not isinstance(raw_value, str) or "\r" in raw_value or "\n" in raw_value:
            raise CacheError("invalid header value")
        lower = name.lower()
        clean = raw_value.strip(" \t")
        if request:
            if lower in normalized and normalized[lower] != clean:
                raise CacheError("conflicting request header")
            normalized[lower] = clean
            wire.setdefault(name, clean)
        fields.setdefault(lower, []).append(clean)
    return normalized, fields, wire


def _numeric_directive(values, name, required=False):
    selected = []
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if not part:
                raise CacheError("empty Cache-Control directive")
            key, separator, raw = part.partition("=")
            if key.strip().lower() != name:
                continue
            if not separator:
                raise CacheError(f"{name} requires a value")
            raw = raw.strip()
            if len(raw) >= 2 and raw[0] == raw[-1] == '"':
                raw = raw[1:-1]
            if not raw.isascii() or not raw.isdigit():
                raise CacheError(f"invalid {name}")
            selected.append(int(raw))
    if len(set(selected)) > 1:
        raise CacheError(f"conflicting {name}")
    if required and not selected:
        return None
    return selected[0] if selected else None


def _cache_policy(fields):
    controls = fields.get("cache-control", [])
    directives = []
    for value in controls:
        directives.extend(part.strip().lower() for part in value.split(","))
    max_age = _numeric_directive(controls, "max-age", required=True)
    stale = _numeric_directive(controls, "stale-if-error")
    forbidden = any(part.split("=", 1)[0].strip() in {"private", "no-store"}
                    for part in directives)
    vary = []
    for value in fields.get("vary", []):
        for name in value.split(","):
            name = name.strip().lower()
            if name == "*":
                return None
            if not name or not name.isascii() or _TOKEN.fullmatch(name) is None:
                raise CacheError("invalid Vary")
            if name not in vary:
                vary.append(name)
    if forbidden or "set-cookie" in fields or max_age is None:
        return None
    return tuple(vary), max_age, stale


def _age(fields):
    values = fields.get("age", [])
    if not values:
        return 0
    if (len(set(values)) != 1 or not values[0].isascii()
            or not values[0].isdigit()):
        raise CacheError("invalid Age")
    return int(values[0])


class SharedHttpCache:
    def __init__(self, transport, clock):
        if not callable(transport) or not callable(clock):
            raise ValueError("transport and clock must be callable")
        self.transport = transport
        self.clock = clock
        self._entries = {}
        self._flights = {}
        self._lock = threading.RLock()

    def _now(self):
        value = self.clock()
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0):
            raise CacheError("clock must return finite non-negative time")
        return float(value)

    @staticmethod
    def _current_age(entry, now):
        return entry.age + max(0.0, now - entry.stored_at)

    def _matching(self, url, request):
        for entry in self._entries.get(url, []):
            if entry.values == tuple(request.get(name, "") for name in entry.vary):
                return entry
        return None

    @staticmethod
    def _response(value):
        if not isinstance(value, dict) or set(value) != {"status", "headers", "body"}:
            raise CacheError("invalid response shape")
        status, body = value["status"], value["body"]
        if isinstance(status, bool) or not isinstance(status, int):
            raise CacheError("invalid response status")
        if not isinstance(body, bytes):
            raise CacheError("response body must be bytes")
        _, fields, _ = _header_pairs(value["headers"])
        return status, fields, body

    @staticmethod
    def _merge_fields(old, update):
        merged = {name: list(values) for name, values in old.items()
                  if name not in _HOP_BY_HOP}
        for name, values in update.items():
            if name not in _HOP_BY_HOP:
                merged[name] = list(values)
        return merged

    def _entry(self, body, fields, request, now, minimum_age=0.0):
        policy = _cache_policy(fields)
        if policy is None:
            return None
        vary, max_age, stale = policy
        return _Entry(
            vary=vary,
            values=tuple(request.get(name, "") for name in vary),
            body=body,
            fields={name: list(values) for name, values in fields.items()
                    if name not in _HOP_BY_HOP},
            stored_at=now,
            age=max(_age(fields), math.ceil(minimum_age)),
            max_age=max_age,
            stale_if_error=stale,
        )

    def _replace(self, url, old, new):
        entries = self._entries.setdefault(url, [])
        if old is not None and old in entries:
            entries.remove(old)
        if new is not None:
            entries[:] = [entry for entry in entries
                          if not (entry.vary == new.vary and entry.values == new.values)]
            entries.append(new)
        if not entries:
            self._entries.pop(url, None)

    def _uncached(self, url, wire):
        status, _, body = self._response(self.transport(url, dict(wire)))
        if status != 200:
            raise CacheError("unexpected response status")
        return body

    def get(self, url, headers=None):
        if not isinstance(url, str) or not url:
            raise CacheError("URL must be non-empty text")
        request, _, wire = _header_pairs(headers, request=True)
        now = self._now()
        if set(request) & _SENSITIVE:
            return self._uncached(url, wire)

        with self._lock:
            entry = self._matching(url, request)
            if entry is not None and self._current_age(entry, now) < entry.max_age:
                return entry.body
            flight_key = (url, tuple(sorted(request.items())))
            flight = self._flights.get(flight_key)
            if flight is not None:
                while not flight.done:
                    flight.condition.wait()
                if flight.error is not None:
                    raise flight.error
                return flight.result
            flight = _Flight(self._lock)
            self._flights[flight_key] = flight

        try:
            outbound = dict(wire)
            if entry is not None:
                if entry.fields.get("etag"):
                    outbound["If-None-Match"] = entry.fields["etag"][-1]
                elif entry.fields.get("last-modified"):
                    outbound["If-Modified-Since"] = entry.fields["last-modified"][-1]
            try:
                raw_response = self.transport(url, outbound)
            except Exception:
                if (entry is not None and entry.stale_if_error is not None
                        and self._current_age(entry, now)
                        < entry.max_age + entry.stale_if_error):
                    result = entry.body
                else:
                    raise
            else:
                status, fields, body = self._response(raw_response)
                if status == 304:
                    if entry is None or body:
                        raise CacheError("invalid 304 response")
                    old_age = self._current_age(entry, now)
                    merged = self._merge_fields(entry.fields, fields)
                    updated = self._entry(
                        entry.body, merged, request, now, minimum_age=old_age)
                    with self._lock:
                        self._replace(url, entry, updated)
                    result = entry.body
                elif status == 200:
                    updated = self._entry(body, fields, request, now)
                    with self._lock:
                        self._replace(url, entry, updated)
                    result = body
                else:
                    raise CacheError("unexpected response status")
        except BaseException as exc:
            with self._lock:
                flight.error = exc
                flight.done = True
                flight.condition.notify_all()
                self._flights.pop(flight_key, None)
            raise
        with self._lock:
            flight.result = result
            flight.done = True
            flight.condition.notify_all()
            self._flights.pop(flight_key, None)
        return result
