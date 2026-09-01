"""Incomplete signed-webhook processor with a replay bug."""

from __future__ import annotations

import hashlib
import hmac
import json


class WebhookError(ValueError):
    pass


class WebhookProcessor:
    def __init__(self, keys, handler, clock, tolerance_seconds=300):
        self.keys = dict(keys)
        self.handler = handler
        self.clock = clock
        self.tolerance_seconds = tolerance_seconds

    def process(self, body, signature_header):
        fields = dict(part.split("=", 1) for part in signature_header.split(","))
        timestamp = int(fields["t"])
        if abs(int(self.clock()) - timestamp) > self.tolerance_seconds:
            raise WebhookError("timestamp outside tolerance")
        secret = self.keys[fields["kid"]]
        if isinstance(secret, (tuple, list)):
            secret = secret[0]
        payload = json.loads(body)
        canonical = json.dumps(payload, separators=(",", ":")).encode()
        expected = hmac.new(
            secret, str(timestamp).encode() + b"." + canonical,
            hashlib.sha256).hexdigest()
        if expected != fields["v1"]:
            raise WebhookError("invalid signature")
        return self.handler(payload)
