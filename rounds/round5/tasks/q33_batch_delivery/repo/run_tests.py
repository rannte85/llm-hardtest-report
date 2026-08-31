#!/usr/bin/env python3
from __future__ import annotations

import unittest

from deliveries import AcceptedThenTimedOut, BatchDeliveryService, Ledger, Sender


class PublicTests(unittest.TestCase):
    def test_retry_after_accepted_timeout_is_idempotent(self):
        ledger, sender = Ledger(), Sender(timeout_after_accept_once=True)
        service = BatchDeliveryService(ledger, sender)
        with self.assertRaises(AcceptedThenTimedOut):
            service.retry_batch("b", "r", ["d"], 2)
        first = service.retry_batch("b", "r", ["d"], 2)
        second = service.retry_batch("b", "r", ["d"], 2)
        self.assertEqual(first, second)
        self.assertEqual((len(ledger.charges), len(sender.events)), (1, 1))

    def test_new_request_is_independent(self):
        ledger, sender = Ledger(), Sender()
        service = BatchDeliveryService(ledger, sender)
        service.retry_batch("b", "r1", ["d"], 2)
        service.retry_batch("b", "r2", ["d"], 2)
        self.assertEqual((len(ledger.charges), len(sender.events)), (2, 2))

    def test_v2_response_contract_is_exact(self):
        result = BatchDeliveryService(Ledger(), Sender()).retry_batch(
            "b", "r", ["d"], 2)
        self.assertEqual(result, {"delivered": ["d"], "schema": 2})

    def test_input_order_is_preserved(self):
        result = BatchDeliveryService(Ledger(), Sender()).retry_batch(
            "b", "r", ["d1", "d2"], 2)
        self.assertEqual(result["delivered"], ["d1", "d2"])


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PublicTests)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print(f"PUBLIC: {passed}/{result.testsRun}")
    raise SystemExit(not result.wasSuccessful())
