"""Helpers for running blocking operations in a thread pool."""
from __future__ import annotations

import asyncio
from functools import wraps
from typing import Any, Callable, TypeVar

import structlog

logger = structlog.get_logger()
T = TypeVar("T")


async def run_in_thread(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a sync function in a thread pool to avoid blocking the event loop."""
    try:
        return await asyncio.to_thread(func, *args, **kwargs)
    except Exception as e:
        logger.error("run_in_thread: error", func=func.__name__, error=str(e))
        raise


def async_wrap(func: Callable[..., T]) -> Callable[..., Any]:
    """Decorator: wrap a sync function so it runs in a thread pool when awaited."""

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> T:
        return await run_in_thread(func, *args, **kwargs)

    return wrapper
