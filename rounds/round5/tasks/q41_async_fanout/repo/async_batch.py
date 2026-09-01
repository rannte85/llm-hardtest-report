"""Incomplete bounded async fan-out helper."""

from __future__ import annotations

import asyncio


async def map_concurrently(items, worker, max_concurrency=4, timeout=1.0):
    semaphore = asyncio.Semaphore(max_concurrency)

    async def guarded(item):
        async with semaphore:
            return await worker(item)

    tasks = [asyncio.create_task(
        asyncio.wait_for(guarded(item), timeout)) for item in items]
    return await asyncio.gather(*tasks)
