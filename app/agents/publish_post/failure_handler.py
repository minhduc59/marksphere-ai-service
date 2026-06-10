"""Centralized publish-failure handler.

Used by every node in the publish pipeline (resolve_and_validate, golden_hour,
scheduler, publish) and by the runner. Ensures a terminal failure (a) marks the
PublishedPost row as FAILED in one place and (b) pushes a real-time
publish.status_changed event through the NestJS backend so the UI updates
without waiting for the 3s polling fallback.

Notify failures are swallowed on purpose — they must never mask the original
pipeline failure.
"""

from __future__ import annotations

import uuid

import httpx
import structlog
from sqlalchemy import select

from app.config import get_settings
from app.db.models.enums import PublishStatus
from app.db.models.published_post import PublishedPost
from app.db.session import async_session_factory

logger = structlog.get_logger()


async def _notify_backend(
    published_post_id: str,
    status: str,
    error_message: str,
    stage: str,
) -> None:
    settings = get_settings()
    backend_url = settings.BACKEND_ORIGIN.rstrip("/")
    url = f"{backend_url}/v1/publisher/internal/notify-status"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                url,
                json={
                    "publishedPostId": published_post_id,
                    "status": status,
                    "errorMessage": error_message,
                    "stage": stage,
                },
                headers={
                    "x-internal-api-key": settings.INTERNAL_API_KEY,
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
    except Exception as exc:
        logger.warning(
            "failure_handler: backend notify failed",
            published_post_id=published_post_id,
            error=str(exc),
        )


async def mark_publish_failed(
    published_post_id: str,
    error_message: str,
    *,
    stage: str,
) -> None:
    """Mark a PublishedPost as FAILED and broadcast the status change.

    Args:
        published_post_id: UUID string of the PublishedPost row.
        error_message: Raw error text. Stored in DB for ops; NOT shown to the
            end user — the frontend renders a sanitized message instead.
        stage: One of "resolve" | "schedule" | "publish" | "pipeline".
            Helps the backend log / categorize the failure.
    """
    settings = get_settings()

    try:
        async with async_session_factory() as db:
            pub = (
                await db.execute(
                    select(PublishedPost).where(
                        PublishedPost.id == uuid.UUID(published_post_id)
                    )
                )
            ).scalar_one_or_none()
            if pub is not None:
                pub.status = PublishStatus.FAILED
                pub.error_message = error_message[:2000]
                pub.failed_stage = stage
                pub.retry_count = settings.PUBLISH_MAX_RETRIES
                await db.commit()
    except Exception as exc:
        logger.error(
            "failure_handler: db update failed",
            published_post_id=published_post_id,
            error=str(exc),
        )

    await _notify_backend(
        published_post_id=published_post_id,
        status="failed",
        error_message=error_message,
        stage=stage,
    )
