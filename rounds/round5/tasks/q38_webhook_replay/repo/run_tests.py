#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import hmac
import json
import unittest

from webhook import WebhookError, WebhookProcessor


SECRET = b"billing-secret"


def signature(timestamp, body, secret=SECRET):
    return hmac.new(
        secret, str(timestamp).encode() + b"." + body,
        hashlib.sha256).hexdigest()


def header(timestamp, body, signatures=None):
    values = signatures or [signature(timestamp, body)]
    return ",".join(
        [f"t={timestamp}", "kid=billing"] + [f"v1={value}" for value in values])


class PublicTests(unittest.TestCase):
    def processor(self, applied):
        return WebhookProcessor(
            {"billing": SECRET}, lambda value: applied.append(value) or value["id"],
            lambda: 1000, tolerance_seconds=10)

    def test_valid_event_is_authenticated_and_applied(self):
        applied = []
        body = b'{"id":"evt-1"}'
        self.assertEqual(self.processor(applied).process(body, header(1000, body)), "evt-1")
        self.assertEqual(applied, [{"id": "evt-1"}])

    def test_invalid_and_stale_events_are_rejected(self):
        applied = []
        body = b'{"id":"evt-2"}'
        processor = self.processor(applied)
        with self.assertRaises(WebhookError):
            processor.process(body, header(1000, body, ["0" * 64]))
        with self.assertRaises(WebhookError):
            processor.process(body, header(980, body))
        self.assertEqual(applied, [])

    def test_identical_valid_request_is_applied_once(self):
        applied = []
        body = b'{"id":"evt-3"}'
        processor = self.processor(applied)
        processor.process(body, header(1000, body))
        with self.assertRaises(WebhookError):
            processor.process(body, header(1000, body))
        self.assertEqual(len(applied), 1)

    def test_rotation_header_accepts_any_valid_v1(self):
        applied = []
        body = b'{"id":"evt-4"}'
        values = [signature(1000, body), "f" * 64]
        self.processor(applied).process(body, header(1000, body, values))
        self.assertEqual(len(applied), 1)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PublicTests)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print(f"PUBLIC: {passed}/{result.testsRun}")
    raise SystemExit(not result.wasSuccessful())
