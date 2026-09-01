"""Incomplete URL-only shared HTTP cache."""

from __future__ import annotations


class CacheError(RuntimeError):
    pass


class SharedHttpCache:
    def __init__(self, transport, clock):
        self.transport = transport
        self.clock = clock
        self._entries = {}

    def get(self, url, headers=None):
        if url in self._entries:
            return self._entries[url]
        response = self.transport(url, dict(headers or {}))
        if response["status"] != 200:
            raise CacheError("unexpected response")
        body = response["body"]
        self._entries[url] = body
        return body
