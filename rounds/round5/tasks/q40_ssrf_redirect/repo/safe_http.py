"""Incomplete outbound HTTPS client with redirect and DNS policy gaps."""

from __future__ import annotations

import ipaddress
from urllib.parse import urljoin, urlsplit


class FetchError(RuntimeError):
    pass


class SafeHttpClient:
    def __init__(self, resolver, transport, max_redirects=5, max_body_bytes=1_048_576):
        self.resolver = resolver
        self.transport = transport
        self.max_redirects = max_redirects
        self.max_body_bytes = max_body_bytes

    def get(self, url, headers=None):
        original = urlsplit(url)
        if original.scheme != "https" or not original.hostname:
            raise FetchError("HTTPS URL required")
        addresses = list(self.resolver(original.hostname, original.port or 443))
        if not addresses:
            raise FetchError("hostname did not resolve")
        first = ipaddress.ip_address(addresses[0])
        if first.is_private or first.is_loopback:
            raise FetchError("blocked address")

        current = url
        for _ in range(self.max_redirects + 1):
            parsed = urlsplit(current)
            resolved = list(self.resolver(parsed.hostname, parsed.port or 443))
            response = self.transport(
                resolved[0], parsed.port or 443, parsed.hostname,
                parsed.path or "/", dict(headers or {}),
            )
            if response["status"] in {301, 302, 303, 307, 308}:
                location = dict(response.get("headers", []))["Location"]
                current = urljoin(current, location)
                continue
            if not 200 <= response["status"] < 300:
                raise FetchError("unexpected status")
            return b"".join(response.get("body", []))
        raise FetchError("too many redirects")
