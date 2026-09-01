#!/usr/bin/env python3
from __future__ import annotations

import unittest

from safe_http import FetchError, SafeHttpClient


PUBLIC = "93.184.216.34"


class Harness:
    def __init__(self, dns, responses):
        self.dns = dns
        self.responses = list(responses)
        self.calls = []

    def resolve(self, host, port):
        return self.dns[host]

    def transport(self, ip, port, server_name, target, headers):
        self.calls.append((ip, port, server_name, target, headers))
        return self.responses.pop(0)


class PublicTests(unittest.TestCase):
    def test_public_https_fetch_uses_resolved_ip(self):
        harness = Harness({"example.com": [PUBLIC]}, [{
            "status": 200, "headers": [], "body": [b"hello", b" world"],
        }])
        result = SafeHttpClient(harness.resolve, harness.transport).get(
            "https://example.com/a?x=1")
        self.assertEqual(result, b"hello world")
        self.assertEqual(harness.calls[0][0], PUBLIC)

    def test_initial_loopback_is_rejected_before_transport(self):
        harness = Harness({"internal": ["127.0.0.1"]}, [])
        with self.assertRaises(FetchError):
            SafeHttpClient(harness.resolve, harness.transport).get("https://internal/")
        self.assertEqual(harness.calls, [])

    def test_redirect_to_private_address_is_revalidated(self):
        harness = Harness(
            {"example.com": [PUBLIC], "metadata": ["169.254.169.254"]},
            [{"status": 302, "headers": [("Location", "https://metadata/latest")],
              "body": [b"ignored"]}],
        )
        with self.assertRaises(FetchError):
            SafeHttpClient(harness.resolve, harness.transport).get(
                "https://example.com/start")
        self.assertEqual(len(harness.calls), 1)

    def test_streaming_body_limit_stops_early(self):
        consumed = []

        def body():
            for chunk in (b"1234", b"5678", b"must-not-read"):
                consumed.append(chunk)
                yield chunk

        harness = Harness({"example.com": [PUBLIC]}, [{
            "status": 200, "headers": [], "body": body(),
        }])
        with self.assertRaises(FetchError):
            SafeHttpClient(
                harness.resolve, harness.transport, max_body_bytes=6).get(
                    "https://example.com/")
        self.assertEqual(consumed, [b"1234", b"5678"])


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PublicTests)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print(f"PUBLIC: {passed}/{result.testsRun}")
    raise SystemExit(not result.wasSuccessful())
