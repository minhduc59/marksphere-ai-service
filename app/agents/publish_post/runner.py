"""Entry point for the Publish Post Agent pipeline."""

from __future__ import annotations

from datetime import datetime

import structlog

from app.agents.publish_post.failure_handler import mark_publish_failed
from app.agents.publish_post.graph import build_publish_graph
from app.agents.publish_post.state import PublishPostState
from app.config import get_settings

logger = structlog.get_logger()


async def run_publish_pipeline(
    content_post_id: str,
    mode: str = "auto",
    scheduled_time: datetime | None = None,
    privacy_level: str | None = None,
    user_id: str | None = None,
    published_post_id: str = "",
) -> dict:
    """Run the Publish Post Agent pipeline.

    Args:
        content_post_id: UUID of the ContentPost to publish.
        mode: "auto" (golden hour scheduling) or "manual" (user-specified time).
        scheduled_time: For manual mode — specific time to publish.
            If None in manual mode, publishes immediately.
        privacy_level: TikTok privacy level. Defaults to config value.
        user_id: UUID of the triggering user. Propagated into PublishedPost.published_by.
        published_post_id: Optional pre-created PublishedPost row id. When provided,
            resolve_and_validate_node loads that row instead of creating a new one
            so the API can return the real id synchronously.

    Returns:
        Dict with publish_status, published_post_id, and error info if any.
    """
    settings = get_settings()

    initial_state = PublishPostState(
        content_post_id=content_post_id,
        user_id=user_id or "",
        publish_mode=mode,
        scheduled_time_override=scheduled_time.isoformat() if scheduled_time else "",
        privacy_level=privacy_level or settings.TIKTOK_DEFAULT_PRIVACY,
        published_post_id=published_post_id,
        image_public_url="",
        assembled_caption="",
        golden_hour_result={},
        scheduled_at="",
        provider_post_id="",
        content_type="",
        video_url="",
        publish_status="",
        error="",
    )

    logger.info(
        "publish_pipeline: starting",
        content_post_id=content_post_id,
        mode=mode,
        scheduled_time=str(scheduled_time) if scheduled_time else "auto",
    )

    graph = build_publish_graph()

    try:
        result = await graph.ainvoke(initial_state)
    except Exception as exc:
        # A node raised — ensure the failure is recorded if we have a row id.
        # mark_publish_failed is idempotent (a node may already have called it).
        error_text = str(exc)
        if published_post_id:
            await mark_publish_failed(
                published_post_id=published_post_id,
                error_message=error_text,
                stage="pipeline",
            )
        logger.error(
            "publish_pipeline: failed",
            content_post_id=content_post_id,
            published_post_id=published_post_id,
            error=error_text,
        )
        return {
            "content_post_id": content_post_id,
            "published_post_id": published_post_id,
            "publish_status": "failed",
            "provider_post_id": "",
            "platform_post_id": "",
            "error": error_text,
        }

    status = result.get("publish_status", "")
    if status == "failed":
        logger.error(
            "publish_pipeline: failed",
            content_post_id=content_post_id,
            publish_status=status,
            published_post_id=result.get("published_post_id"),
            error=result.get("error"),
        )
    else:
        logger.info(
            "publish_pipeline: completed",
            content_post_id=content_post_id,
            publish_status=status,
            published_post_id=result.get("published_post_id"),
        )

    return {
        "content_post_id": content_post_id,
        "published_post_id": result.get("published_post_id", ""),
        "publish_status": status,
        "provider_post_id": result.get("provider_post_id", ""),
        "platform_post_id": result.get("platform_post_id", ""),
        "error": result.get("error", ""),
    }


async def run_publish_pipeline_job(content_post_id: str) -> None:
    """APScheduler job callback — runs the publish pipeline for a scheduled post.

    This is called when a delayed golden-hour job fires.
    It re-runs the full pipeline which will detect that scheduling already happened
    and proceed directly to publishing.
    """
    logger.info("publish_job: triggered", content_post_id=content_post_id)

    try:
        result = await run_publish_pipeline(
            content_post_id=content_post_id,
            mode="auto",
            # No scheduled_time_override — will detect "publish_now" since it's time
        )
        logger.info(
            "publish_job: completed",
            content_post_id=content_post_id,
            status=result.get("publish_status"),
        )
    except Exception as e:
        logger.error(
            "publish_job: failed",
            content_post_id=content_post_id,
            error=str(e),
        )
