"""Publish video processing progress events to Redis pub/sub."""
from __future__ import annotations

import json

import redis.asyncio as aioredis
import structlog

from app.config import get_settings

logger = structlog.get_logger()


async def publish_video_progress(
    task_id: str,
    stage: str,
    percent: int,
    status: str = "processing",
    message: str = "",
) -> None:
    """Publish a progress event to channel video:progress:{task_id}.

    Consumed by the NestJS WebSocket gateway which rebroadcasts to room video:{task_id}.
    """
    payload = json.dumps(
        {
            "taskId": task_id,
            "stage": stage,
            "percentComplete": percent,
            "status": status,
            "message": message,
        }
    )
    try:
        settings = get_settings()
        redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await redis.publish(f"video:progress:{task_id}", payload)
        await redis.aclose()
    except Exception as e:
        logger.warning("progress: Redis publish failed", task_id=task_id, error=str(e))
