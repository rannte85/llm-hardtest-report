#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from job_queue import JobQueue, LeaseError


class Clock:
    def __init__(self, value=1000.0):
        self.value = value

    def __call__(self):
        return self.value


class PublicTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        self.queue = JobQueue(Path(self.temp.name) / "jobs.sqlite3", self.clock)

    def test_enqueue_claim_and_complete(self):
        self.queue.enqueue("a", {"kind": "email"})
        lease = self.queue.claim("worker-a", 10)
        self.assertEqual(lease["payload"], {"kind": "email"})
        self.assertTrue(self.queue.complete("a", "worker-a", lease["lease_token"]))
        self.assertIsNone(self.queue.claim("worker-b", 10))

    def test_priority_then_creation_order(self):
        self.queue.enqueue("low", {"n": 1}, priority=1, created_at=1)
        self.queue.enqueue("late", {"n": 2}, priority=5, created_at=3)
        self.queue.enqueue("early", {"n": 3}, priority=5, created_at=2)
        self.assertEqual(self.queue.claim("w", 10)["id"], "early")

    def test_expired_lease_is_reclaimed_with_a_new_token(self):
        self.queue.enqueue("a", {"n": 1})
        first = self.queue.claim("worker-a", 5)
        self.clock.value = 1006
        second = self.queue.claim("worker-b", 5)
        self.assertEqual(second["id"], "a")
        self.assertGreater(second["lease_token"], first["lease_token"])

    def test_stale_owner_cannot_complete_after_reclaim(self):
        self.queue.enqueue("a", {"n": 1})
        first = self.queue.claim("worker-a", 5)
        self.clock.value = 1006
        second = self.queue.claim("worker-b", 5)
        with self.assertRaises(LeaseError):
            self.queue.complete("a", "worker-a", first["lease_token"])
        self.assertTrue(self.queue.complete("a", "worker-b", second["lease_token"]))


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PublicTests)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print(f"PUBLIC: {passed}/{result.testsRun}")
    raise SystemExit(not result.wasSuccessful())
