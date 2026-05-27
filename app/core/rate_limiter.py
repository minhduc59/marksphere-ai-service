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
