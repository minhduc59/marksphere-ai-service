import json

import structlog
from redis.asyncio import Redis

logger = structlog.get_logger()


class Cache:
    def __init__(self, redis: Redis):
        self.redis = redis

    async def get(self, key: str) -> dict | list | None:
        data = await self.redis.get(f"cache:{key}")
        if data:
            logger.debug("Cache hit", key=key)
            return json.loads(data)
        return None

    async def set(self, key: str, value: dict | list, ttl: int = 1800) -> None:
        await self.redis.set(
            f"cache:{key}",
            json.dumps(value, default=str),
            ex=ttl,
        )
        logger.debug("Cache set", key=key, ttl=ttl)

    async def delete(self, key: str) -> None:
        await self.redis.delete(f"cache:{key}")

    async def exists(self, key: str) -> bool:
        return bool(await self.redis.exists(f"cache:{key}"))
