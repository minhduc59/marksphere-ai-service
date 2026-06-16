"""Per-user concurrency guard for scans.

Scans run in-process on the FastAPI event loop, so one user firing many scans
at once can starve other users and exhaust the DB pool / HN rate budget. This
caps how many scans a single user can have in flight, returning a clear "at
capacity" signal instead of silently degrading everyone. The counter lives in
Redis (shared across workers) with a TTL safety net so a crashed run can't pin
a slot forever.
"""
from __future__ import annotations

import structlog
from redis.asyncio import Redis

logger = structlog.get_logger()

# Max scans a single user may have running concurrently.
MAX_CONCURRENT_SCANS_PER_USER = 3
# Safety expiry (seconds): if a run dies without releasing, the slot frees itself.
_SLOT_TTL = 3600


def _key(user_id: str) -> str:
    return f"scan:active:{user_id}"


async def try_acquire_scan_slot(
    redis: Redis | None,
    user_id: str | None,
    *,
    limit: int = MAX_CONCURRENT_SCANS_PER_USER,
) -> bool:
    """Atomically reserve a per-user scan slot.

    Returns False if the user is already at ``limit``. A no-op returning True
    when redis/user_id is absent — a Redis outage must never block scanning.
    """
    if redis is None or not user_id:
        return True
    key = _key(str(user_id))
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, _SLOT_TTL)
    if count > limit:
        # Over the cap — undo our increment and reject.
        await redis.decr(key)
        return False
    return True


async def release_scan_slot(redis: Redis | None, user_id: str | None) -> None:
    """Release a previously acquired slot. Never raises."""
    if redis is None or not user_id:
        return
    key = _key(str(user_id))
    try:
        remaining = await redis.decr(key)
        if remaining < 0:
            # Floor at zero — a double-release or post-TTL decr must not go negative.
            await redis.set(key, 0)
    except Exception as exc:  # noqa: BLE001 — releasing a slot must never crash the run
        logger.warning("concurrency: slot release failed", user_id=str(user_id), error=str(exc))
