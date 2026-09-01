#!/usr/bin/env python3
"""Held-back DNS, redirect, authority, and streaming checks for q40."""

from __future__ import annotations

import hashlib
import importlib
import sys
import unittest
from pathlib import Path


EXPECTED = {
    "README.md": "37884a69bea63c716287844f52598d5ad74ce84b1c645ecefcc2465ee0b6e994",
    "run_tests.py": "630b244ce76378a02e599b0cd12a51a9906744595400bc7346eb79da86a67ec2",
    "operator_note.txt": "792f9f18912802a7ba991471b4ed72c3be943d11d75563f0189b6b355b1c7b88",
}
PUBLIC4 = "93.184.216.34"
PUBLIC6 = "2606:4700:4700::1111"


if len(sys.argv) != 2:
    raise SystemExit("usage: hidden_tests.py PATH_TO_CANDIDATE_REPO")
REPO = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(REPO))
safe_http = importlib.import_module("safe_http")


class Harness:
    def __init__(self, dns, responses):
        self.dns = dns
        self.responses = list(responses)
        self.resolutions = []
        self.calls = []

    def resolve(self, host, port):
        self.resolutions.append((host, port))
        value = self.dns[host]
        return value() if callable(value) else list(value)

    def transport(self, ip, port, server_name, target, headers):
        self.calls.append((ip, port, server_name, target, dict(headers)))
        return self.responses.pop(0)

    def client(self, **kwargs):
        return safe_http.SafeHttpClient(self.resolve, self.transport, **kwargs)


class HiddenTests(unittest.TestCase):
    def test_authority_files_are_untouched(self):
        for relative, expected in EXPECTED.items():
            actual = hashlib.sha256((REPO / relative).read_bytes()).hexdigest()
            self.assertEqual(actual, expected, relative)

    def test_every_dns_answer_is_checked_before_transport(self):
        harness = Harness({"mixed.example": [PUBLIC4, "10.0.0.7"]}, [])
        with self.assertRaises(safe_http.FetchError):
            harness.client().get("https://mixed.example/")
        self.assertEqual(harness.resolutions, [("mixed.example", 443)])
        self.assertEqual(harness.calls, [])

    def test_mapped_and_zone_scoped_ipv6_are_rejected(self):
        for address in ("::ffff:127.0.0.1", PUBLIC6 + "%en0"):
            with self.subTest(address=address):
                harness = Harness({"v6.example": [address]}, [])
                with self.assertRaises(safe_http.FetchError):
                    harness.client().get("https://v6.example/")
                self.assertEqual(harness.calls, [])

    def test_url_authority_validation_and_idna_canonicalization(self):
        invalid = (
            "http://example.com/", "//example.com/", "https://u:p@example.com/",
            "https://example.com/#fragment", "https://example.com../",
        )
        for url in invalid:
            with self.subTest(url=url):
                harness = Harness({}, [])
                with self.assertRaises(safe_http.FetchError):
                    harness.client().get(url)
                self.assertEqual(harness.calls, [])
        harness = Harness({"xn--bcher-kva.example": [PUBLIC4]}, [
            {"status": 200, "headers": [], "body": [b"ok"]},
        ])
        self.assertEqual(
            harness.client().get("https://B\u00dcCHER.Example./book"), b"ok")
        self.assertEqual(harness.resolutions, [("xn--bcher-kva.example", 443)])
        self.assertEqual(harness.calls[0][2], "xn--bcher-kva.example")

    def test_dns_is_single_use_and_transport_is_pinned_with_full_target(self):
        answers = iter(([PUBLIC6], ["127.0.0.1"]))
        harness = Harness({"example.com": lambda: next(answers)}, [
            {"status": 200, "headers": [], "body": [b"ok"]},
        ])
        result = harness.client().get("https://example.com:8443/a/b?x=1&y=2")
        self.assertEqual(result, b"ok")
        self.assertEqual(harness.resolutions, [("example.com", 8443)])
        ip, port, sni, target, headers = harness.calls[0]
        self.assertEqual((ip, port, sni, target),
                         (PUBLIC6, 8443, "example.com", "/a/b?x=1&y=2"))
        self.assertEqual(headers["Host"], "example.com:8443")

    def test_redirect_grammar_loop_limit_and_body_non_consumption(self):
        consumed = []

        def redirect_body():
            consumed.append(True)
            yield b"never"

        harness = Harness({"example.com": [PUBLIC4]}, [
            {"status": 302, "headers": [("Location", "/next")],
             "body": redirect_body()},
            {"status": 200, "headers": [], "body": [b"done"]},
        ])
        self.assertEqual(harness.client().get("https://example.com/start"), b"done")
        self.assertEqual(consumed, [])
        self.assertEqual([call[3] for call in harness.calls], ["/start", "/next"])

        loop = Harness({"example.com": [PUBLIC4]}, [{
            "status": 302,
            "headers": [("Location", "https://EXAMPLE.com:443/a")],
            "body": [],
        }])
        with self.assertRaises(safe_http.FetchError):
            loop.client().get("https://example.com/a")
        self.assertEqual(len(loop.calls), 1)

        duplicate = Harness({"example.com": [PUBLIC4]}, [{
            "status": 302,
            "headers": [("Location", "/a"), ("location", "/b")], "body": [],
        }])
        with self.assertRaises(safe_http.FetchError):
            duplicate.client().get("https://example.com/")
        self.assertEqual(len(duplicate.calls), 1)

        bounded = Harness({"example.com": [PUBLIC4]}, [{
            "status": 302, "headers": [("Location", "/next")], "body": [],
        }])
        with self.assertRaises(safe_http.FetchError):
            bounded.client(max_redirects=0).get("https://example.com/")
        self.assertEqual(len(bounded.calls), 1)

    def test_credentials_are_stripped_only_on_origin_change(self):
        supplied = {"Authorization": "Bearer secret", "Cookie": "sid=secret",
                    "X-Trace": "yes"}
        same = Harness({"a.example": [PUBLIC4]}, [
            {"status": 302, "headers": [("Location", "/next")], "body": []},
            {"status": 200, "headers": [], "body": [b"same"]},
        ])
        self.assertEqual(same.client().get("https://a.example/start", supplied), b"same")
        self.assertIn("Authorization", same.calls[1][4])
        self.assertIn("Cookie", same.calls[1][4])

        cross = Harness({"a.example": [PUBLIC4], "b.example": ["8.8.8.8"]}, [
            {"status": 302, "headers": [("Location", "https://b.example/next")],
             "body": []},
            {"status": 200, "headers": [], "body": [b"cross"]},
        ])
        self.assertEqual(cross.client().get("https://a.example/start", supplied), b"cross")
        second = {name.lower(): value for name, value in cross.calls[1][4].items()}
        self.assertNotIn("authorization", second)
        self.assertNotIn("cookie", second)
        self.assertEqual(second["x-trace"], "yes")
        self.assertEqual(second["host"], "b.example")

    def test_request_and_response_header_grammar(self):
        for headers in ({"Host": "attacker"}, {"Bad Name": "x"},
                        {"X-Test": "ok\r\ninjected: yes"}):
            harness = Harness({"example.com": [PUBLIC4]}, [])
            with self.subTest(headers=headers), self.assertRaises(safe_http.FetchError):
                harness.client().get("https://example.com/", headers)
            self.assertEqual(harness.calls, [])
        for response_headers in (
            [("Bad Name", "x")], [("X-Test", "bad\nvalue")],
            [("Content-Length", "1"), ("content-length", "2")],
        ):
            harness = Harness({"example.com": [PUBLIC4]}, [{
                "status": 200, "headers": response_headers, "body": [b"x"],
            }])
            with self.subTest(response_headers=response_headers), self.assertRaises(
                    safe_http.FetchError):
                harness.client().get("https://example.com/")

    def test_content_length_preflight_and_streaming_limit(self):
        consumed = []

        def body():
            consumed.append(True)
            yield b"never"

        harness = Harness({"example.com": [PUBLIC4]}, [{
            "status": 200, "headers": [("Content-Length", "7")], "body": body(),
        }])
        with self.assertRaises(safe_http.FetchError):
            harness.client(max_body_bytes=6).get("https://example.com/")
        self.assertEqual(consumed, [])

        exact = Harness({"example.com": [PUBLIC4]}, [{
            "status": 200,
            "headers": [("Content-Length", "6"), ("content-length", "6")],
            "body": [b"123", b"456"],
        }])
        self.assertEqual(exact.client(max_body_bytes=6).get(
            "https://example.com/"), b"123456")

        bad_chunk = Harness({"example.com": [PUBLIC4]}, [{
            "status": 200, "headers": [], "body": [b"ok", "not-bytes"],
        }])
        with self.assertRaises(safe_http.FetchError):
            bad_chunk.client().get("https://example.com/")

    def test_response_status_dns_and_shape_fail_closed(self):
        empty = Harness({"empty.example": []}, [])
        with self.assertRaises(safe_http.FetchError):
            empty.client().get("https://empty.example/")
        self.assertEqual(empty.calls, [])
        cases = (
            {"status": 404, "headers": [], "body": [b"no"]},
            {"status": True, "headers": [], "body": []},
            {"status": 200, "headers": "not-pairs", "body": []},
        )
        for response in cases:
            harness = Harness({"example.com": [PUBLIC4]}, [response])
            with self.subTest(response=response), self.assertRaises(safe_http.FetchError):
                harness.client().get("https://example.com/")


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(HiddenTests)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    passed = max(0, result.testsRun - len(result.failures) - len(result.errors))
    print(f"HIDDEN: {passed}/{result.testsRun}")
    raise SystemExit(not result.wasSuccessful())
