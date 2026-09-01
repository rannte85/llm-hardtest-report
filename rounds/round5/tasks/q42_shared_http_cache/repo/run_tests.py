#!/usr/bin/env python3
from __future__ import annotations

import threading
import unittest

from shared_cache import SharedHttpCache


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class PublicTests(unittest.TestCase):
    def test_authenticated_tenants_never_share(self):
        calls = []

        def transport(url, headers):
            calls.append((url, dict(headers)))
            tenant = headers["Authorization"].split()[-1]
            return {"status": 200, "headers": [("Cache-Control", "public, max-age=60")],
                    "body": tenant.encode()}

        cache = SharedHttpCache(transport, Clock())
        self.assertEqual(cache.get("https://service/items", {"Authorization": "Bearer A"}), b"A")
        self.assertEqual(cache.get("https://service/items", {"Authorization": "Bearer B"}), b"B")
        self.assertEqual(len(calls), 2)

    def test_vary_language_selects_the_representation(self):
        calls = []

        def transport(url, headers):
            calls.append(dict(headers))
            language = headers.get("Accept-Language", "en")
            return {"status": 200,
                    "headers": [("Cache-Control", "max-age=60"),
                                ("Vary", "Accept-Language")],
                    "body": language.encode()}

        cache = SharedHttpCache(transport, Clock())
        self.assertEqual(cache.get("https://service/greeting", {"Accept-Language": "en"}), b"en")
        self.assertEqual(cache.get("https://service/greeting", {"Accept-Language": "ko"}), b"ko")
        self.assertEqual(cache.get("https://service/greeting", {"accept-language": " en "}), b"en")
        self.assertEqual(len(calls), 2)

    def test_stale_etag_304_preserves_the_body(self):
        clock = Clock()
        calls = []

        def transport(url, headers):
            calls.append(dict(headers))
            if len(calls) == 1:
                return {"status": 200,
                        "headers": [("Cache-Control", "max-age=1"), ("ETag", '"v1"')],
                        "body": b"payload"}
            self.assertEqual(headers.get("If-None-Match"), '"v1"')
            return {"status": 304, "headers": [("Cache-Control", "max-age=10")],
                    "body": b""}

        cache = SharedHttpCache(transport, clock)
        self.assertEqual(cache.get("https://service/data"), b"payload")
        clock.value = 1.0
        self.assertEqual(cache.get("https://service/data"), b"payload")
        clock.value = 5.0
        self.assertEqual(cache.get("https://service/data"), b"payload")
        self.assertEqual(len(calls), 2)

    def test_identical_cold_requests_are_single_flighted(self):
        entered = threading.Event()
        release = threading.Event()
        calls = 0

        def transport(url, headers):
            nonlocal calls
            calls += 1
            entered.set()
            release.wait(1)
            return {"status": 200, "headers": [("Cache-Control", "max-age=60")],
                    "body": b"one"}

        cache = SharedHttpCache(transport, Clock())
        results = []
        threads = [threading.Thread(target=lambda: results.append(
            cache.get("https://service/cold", {"Accept": "text/plain"}))) for _ in range(3)]
        for thread in threads:
            thread.start()
        self.assertTrue(entered.wait(1))
        release.set()
        for thread in threads:
            thread.join(1)
        self.assertEqual(results, [b"one"] * 3)
        self.assertEqual(calls, 1)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PublicTests)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print(f"PUBLIC: {passed}/{result.testsRun}")
    raise SystemExit(not result.wasSuccessful())
