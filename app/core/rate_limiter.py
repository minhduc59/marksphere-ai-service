import asyncio
import time

import structlog
from redis.asyncio import Redis

from app.core.exceptions import RateLimitError

logger = structlog.get_logger()

# Platform rate limits: (max_requests, window_seconds)
PLATFORM_LIMITS: dict[str, tuple[int, int]] = {
    "hackernews": (30, 60),          # HN Firebase API: ~30 req/min to be polite
    "tiktok": (6, 60),               # TikTok Content Posting API: 6 req/min per token
}


class RateLimiter:
    def __init__(self, redis: Redis):
        self.redis = redis

    async def check(self, platform: str, cost: int = 1) -> bool:
        limit, window = PLATFORM_LIMITS.get(platform, (100, 60))
        key = f"ratelimit:{platform}"
        now = time.time()

        pipe = self.redis.pipeline()
        # Remove old entries outside the window
        pipe.zremrangebyscore(key, 0, now - window)
        # Count current entries
        pipe.zcard(key)
        # Add new entry
        pipe.zadd(key, {f"{now}:{cost}": now})
        # Set expiry on the key
        pipe.expire(key, window)

        results = await pipe.execute()
        current_count = results[1]

        if current_count >= limit:
            logger.warning("Rate limit exceeded", platform=platform, limit=limit, window=window)
            raise RateLimitError(platform, f"Rate limit exceeded: {current_count}/{limit} in {window}s")

        return True

    async def acquire(
        self,
        platform: str,
        cost: int = 1,
        *,
        max_wait: float = 30.0,
        poll: float = 0.5,
    ) -> bool:
        """Reserve a rate-limit slot, waiting if the window is full.

        The platform limit (e.g. HN's 30/60s) is GLOBAL across all users — it
        protects the upstream API from our single egress IP. Under concurrent
        multi-user load, raising immediately makes one user's scan fail because
        another user is mid-scan. Instead we wait up to ``max_wait`` for a slot
        to free up, so contending scans queue briefly rather than erroring. We
        only raise if still saturated after ``max_wait`` (genuine overload).
        """
        limit, window = PLATFORM_LIMITS.get(platform, (100, 60))
        key = f"ratelimit:{platform}"
        deadline = time.time() + max_wait

        while True:
            now = time.time()
            pipe = self.redis.pipeline()
            pipe.zremrangebyscore(key, 0, now - window)
            pipe.zcard(key)
            current_count = (await pipe.execute())[1]

            if current_count < limit:
                await self.redis.zadd(key, {f"{now}:{cost}": now})
                await self.redis.expire(key, window)
                return True

            if time.time() >= deadline:
                logger.warning(
                    "Rate limit still exceeded after waiting",
                    platform=platform,
                    limit=limit,
                    waited=max_wait,
                )
                raise RateLimitError(
                    platform,
                    f"Rate limit exceeded: {current_count}/{limit} in {window}s "
                    f"(waited {max_wait}s)",
                )

            await asyncio.sleep(poll)

    async def get_usage(self, platform: str) -> dict:
        limit, window = PLATFORM_LIMITS.get(platform, (100, 60))
        key = f"ratelimit:{platform}"
        now = time.time()

        await self.redis.zremrangebyscore(key, 0, now - window)
        current = await self.redis.zcard(key)

        return {
            "platform": platform,
            "used": current,
            "limit": limit,
            "remaining": max(0, limit - current),
            "window_seconds": window,
        }
