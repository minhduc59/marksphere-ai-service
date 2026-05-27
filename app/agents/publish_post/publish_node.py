"""LangGraph node: publish post via NestJS backend → Zernio → TikTok."""

from __future__ import annotations

import uuid

import httpx
import structlog
from sqlalchemy import select

from app.agents.publish_post.constants import RETRY_DELAYS_SECONDS
from app.agents.publish_post.failure_handler import mark_publish_failed
from app.agents.publish_post.state import PublishPostState
from app.config import get_settings
from app.core.cloudinary_uploader import assert_cloudinary_url
from app.db.models.published_post import PublishedPost
from app.db.session import async_session_factory

logger = structlog.get_logger()


async def _call_backend_publish(
    published_post_id: str,
    user_id: str,
    image_url: str,
    caption: str,
    tags: list[str],
    scheduled_at: str | None,
    media_type: str = "PHOTO",
    video_url: str = "",
) -> dict:
    """POST to NestJS backend /v1/publisher/internal/publish.

    Returns the JSON response: { postId, status, publishedUrl, publishedPostId }
    Raises httpx.HTTPStatusError on non-2xx responses.
    """
    settings = get_settings()
    backend_url = settings.BACKEND_ORIGIN.rstrip("/")
    url = f"{backend_url}/v1/publisher/internal/publish"

    # Base payload shared by both photo and video paths
    payload: dict = {
        "publishedPostId": published_post_id,
        "userId": user_id,
        "caption": caption,
        "tags": tags,
    }
    if scheduled_at:
        payload["scheduledAt"] = scheduled_at

    # Media-type-specific field — exactly one of imageUrl / videoUrl is sent
    if media_type == "VIDEO":
        payload["videoUrl"] = video_url
    else:
        payload["imageUrl"] = image_url

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            url,
            json=payload,
            headers={
                "x-internal-api-key": settings.INTERNAL_API_KEY,
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        return response.json()


async def publish_node(state: PublishPostState) -> dict:
    """Call NestJS backend to publish the post via Zernio.

    Retries up to PUBLISH_MAX_RETRIES times with exponential backoff.
    NestJS handles the actual Zernio API call and TikTok publishing.
    """
    settings = get_settings()
    published_post_id = state["published_post_id"]
    content_post_id = state["content_post_id"]
    user_id = state.get("user_id", "")

    caption = state["assembled_caption"]
    image_url = state["image_public_url"]
    scheduled_at = state.get("scheduled_at") or None
    content_type = state.get("content_type", "photo") or "photo"
    video_url = state.get("video_url", "") or ""

    # Guard: photo posts require a public Cloudinary image URL.
    # Video posts require a public Cloudinary video URL (checked at resolve time).
    if content_type == "video":
        assert_cloudinary_url(video_url)
        media_type = "VIDEO"
    else:
        assert_cloudinary_url(image_url)
        media_type = "PHOTO"

    last_error = ""
    provider_post_id = ""

    for attempt in range(settings.PUBLISH_MAX_RETRIES + 1):
        try:
            logger.info(
                "publish_node: calling backend",
                published_post_id=published_post_id,
                attempt=attempt + 1,
                scheduled_at=scheduled_at,
            )

            result = await _call_backend_publish(
                published_post_id=published_post_id,
                user_id=user_id,
                image_url=image_url,
                caption=caption,
                tags=[],
                scheduled_at=scheduled_at,
                media_type=media_type,
                video_url=video_url,
            )

            provider_post_id = result.get("postId", "")
            backend_status = result.get("status", "")

            # Persist the provider post ID so the webhook handler can match it
            async with async_session_factory() as db:
                pub = (
                    await db.execute(
                        select(PublishedPost).where(
                            PublishedPost.id == uuid.UUID(published_post_id)
                        )
                    )
                ).scalar_one_or_none()
                if pub:
                    pub.tiktok_publish_id = provider_post_id
                    # Status stays PROCESSING until publisher webhook confirms
                    pub.retry_count = attempt
                    await db.commit()

            logger.info(
                "publish_node: backend accepted",
                provider_post_id=provider_post_id,
                backend_status=backend_status,
            )

            return {
                "publish_status": "scheduled" if scheduled_at else "processing",
                "provider_post_id": provider_post_id,
                "error": "",
            }

        except httpx.HTTPStatusError as e:
            last_error = f"Backend HTTP {e.response.status_code}: {e.response.text[:200]}"
            logger.warning(
                "publish_node: backend error",
                attempt=attempt + 1,
                status=e.response.status_code,
                error=last_error,
            )
            # Don't retry on 4xx (bad request, not linked, etc.)
            if 400 <= e.response.status_code < 500:
                break

        except Exception as e:
            last_error = str(e)
            logger.error(
                "publish_node: unexpected error",
                attempt=attempt + 1,
                error=last_error,
            )

        if attempt < settings.PUBLISH_MAX_RETRIES:
            import asyncio
            delay = RETRY_DELAYS_SECONDS[min(attempt, len(RETRY_DELAYS_SECONDS) - 1)]
            logger.info("publish_node: retrying after delay", delay_seconds=delay)
            await asyncio.sleep(delay)

    # All retries exhausted — mark as failed (DB + WebSocket broadcast)
    await mark_publish_failed(
        published_post_id=published_post_id,
        error_message=last_error,
        stage="publish",
    )

    logger.error(
        "publish_node: all retries exhausted",
        published_post_id=published_post_id,
        error=last_error,
    )

    return {
        "publish_status": "failed",
        "provider_post_id": provider_post_id,
        "error": last_error,
    }
