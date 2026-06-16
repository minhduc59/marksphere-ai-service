"""Bounded-concurrency batching for the post-generation LLM stages.

Each stage used to send *all* posts in a single LLM call, which overflows the
output token limit (and produces truncated JSON) once a scan generates 50–100
posts. These helpers split the work into batches and run a bounded number of
them concurrently, so large scans stay within token limits and a single batch
failure is isolated to its own posts instead of tainting the whole run.
"""
import asyncio
from typing import Awaitable, Callable, TypeVar

# Posts per LLM call. Small enough to stay well under the 8k output-token limit
# even for verbose formats, large enough to keep call count reasonable.
BATCH_SIZE = 12
# How many batches to run at once. Bounded to avoid flooding the OpenAI rate
# limit while still cutting wall-clock time on large scans.
BATCH_CONCURRENCY = 3

R = TypeVar("R")


def chunked(items: list, size: int = BATCH_SIZE):
    """Yield successive ``size``-length slices of ``items``."""
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def run_batches(
    items: list,
    handler: Callable[[list, int], Awaitable[R]],
    *,
    size: int = BATCH_SIZE,
    concurrency: int = BATCH_CONCURRENCY,
) -> list[R]:
    """Run ``handler(batch, batch_index)`` over chunks of ``items``.

    Batches run with bounded concurrency; results are returned in batch order.
    ``handler`` must not raise — it should catch its own errors and return a
    result that encodes failure, so one bad batch never aborts the others.
    """
    sem = asyncio.Semaphore(concurrency)
    batches = list(chunked(items, size))

    async def _run(idx: int, batch: list) -> R:
        async with sem:
            return await handler(batch, idx)

    return await asyncio.gather(
        *(_run(i, b) for i, b in enumerate(batches))
    )
