#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import unittest

from async_batch import map_concurrently


class PublicTests(unittest.IsolatedAsyncioTestCase):
    async def test_order_and_concurrency_limit(self):
        active = 0
        peak = 0

        async def worker(value):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01 * (4 - value))
            active -= 1
            return value * 10

        result = await map_concurrently(
            [1, 2, 3], worker, max_concurrency=2, timeout=1)
        self.assertEqual(result, [10, 20, 30])
        self.assertEqual(peak, 2)

    async def test_queued_time_is_not_charged_to_item_timeout(self):
        async def worker(value):
            await asyncio.sleep(0.02)
            return value

        result = await map_concurrently(
            list(range(8)), worker, max_concurrency=1, timeout=0.08)
        self.assertEqual(result, list(range(8)))

    async def test_failure_cancels_and_awaits_sibling_cleanup(self):
        started = asyncio.Event()
        cleaned = asyncio.Event()

        async def worker(value):
            if value == "fail":
                await started.wait()
                raise LookupError("boom")
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await asyncio.sleep(0)
                cleaned.set()
                raise

        with self.assertRaisesRegex(LookupError, "boom"):
            await map_concurrently(
                ["slow", "fail"], worker, max_concurrency=2, timeout=1)
        self.assertTrue(cleaned.is_set())

    async def test_empty_input_does_not_call_worker(self):
        called = False

        async def worker(value):
            nonlocal called
            called = True
            return value

        self.assertEqual(await map_concurrently([], worker), [])
        self.assertFalse(called)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PublicTests)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print(f"PUBLIC: {passed}/{result.testsRun}")
    raise SystemExit(not result.wasSuccessful())
