#!/usr/bin/env python3
from __future__ import annotations

import threading
import unittest

from snapshot_cache import SnapshotCache


class PublicTests(unittest.TestCase):
    def test_basic_refresh(self):
        cache = SnapshotCache({"catalog": "v1"})
        self.assertEqual(cache.refresh("catalog", lambda: "v2"), "v2")
        self.assertEqual(cache.get("catalog"), "v2")

    def test_later_request_wins_when_older_loader_finishes_last(self):
        cache = SnapshotCache({"catalog": "v0"})
        old_started = threading.Event()
        release_old = threading.Event()
        new_finished = threading.Event()

        def old_loader():
            old_started.set()
            self.assertTrue(release_old.wait(2))
            return "v1"

        def new_loader():
            new_finished.set()
            return "v2"

        old = threading.Thread(target=cache.refresh, args=("catalog", old_loader))
        old.start()
        self.assertTrue(old_started.wait(1))
        new = threading.Thread(target=cache.refresh, args=("catalog", new_loader))
        new.start()
        new_finished.wait(0.25)
        release_old.set()
        old.join(2)
        new.join(2)
        self.assertFalse(old.is_alive() or new.is_alive())
        self.assertEqual(cache.get("catalog"), "v2")

    def test_keys_are_distinct(self):
        cache = SnapshotCache()
        cache.refresh("a", lambda: 1)
        cache.refresh("b", lambda: 2)
        self.assertEqual((cache.get("a"), cache.get("b")), (1, 2))

    def test_loader_error_is_propagated(self):
        cache = SnapshotCache({"catalog": "v1"})

        def fail():
            raise RuntimeError("remote unavailable")

        with self.assertRaisesRegex(RuntimeError, "remote unavailable"):
            cache.refresh("catalog", fail)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PublicTests)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print(f"PUBLIC: {passed}/{result.testsRun}")
    raise SystemExit(not result.wasSuccessful())
