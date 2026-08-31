#!/usr/bin/env python3
"""Public tests for the Round 5 session refresh pilot."""

import unittest

from sessions import AcceptedThenTimedOut, Notifier, SessionService, TokenStore


class PublicTests(unittest.TestCase):
    def test_normal_v2_refresh(self):
        store, notifier = TokenStore(), Notifier()
        result = SessionService(store, notifier).refresh("s1", "r1", 2)
        self.assertEqual(result, {"token": "token-s1-1", "schema": 2})
        self.assertEqual(len(notifier.events), 1)

    def test_retry_after_lost_ack_returns_the_same_token(self):
        store, notifier = TokenStore(), Notifier(timeout_after_accept_once=True)
        service = SessionService(store, notifier)
        with self.assertRaises(AcceptedThenTimedOut):
            service.refresh("s1", "retry-1", 2)
        result = service.refresh("s1", "retry-1", 2)
        self.assertEqual(result["token"], "token-s1-1")
        self.assertEqual(store.rotations, 1)

    def test_retry_after_lost_ack_notifies_once(self):
        store, notifier = TokenStore(), Notifier(timeout_after_accept_once=True)
        service = SessionService(store, notifier)
        with self.assertRaises(AcceptedThenTimedOut):
            service.refresh("s1", "retry-1", 2)
        service.refresh("s1", "retry-1", 2)
        self.assertEqual(len(notifier.events), 1)

    def test_repeating_completed_request_is_stable(self):
        store, notifier = TokenStore(), Notifier()
        service = SessionService(store, notifier)
        first = service.refresh("s1", "repeat-1", 2)
        second = service.refresh("s1", "repeat-1", 2)
        self.assertEqual(first, second)
        self.assertEqual((store.rotations, len(notifier.events)), (1, 1))


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PublicTests)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print(f"PUBLIC: {passed}/{result.testsRun}")
    raise SystemExit(not result.wasSuccessful())
