"""LangGraph node: determine publish schedule and pass to publish_node.

Scheduling is handled by the publisher (Zernio) via the `scheduledFor`
parameter on POST /api/v1/posts — no local APScheduler jobs are needed.
This node simply determines the target time and puts it in state for
publish_node to forward.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select

from app.agents.publish_post.failure_handler import mark_publish_failed
from app.agents.publish_post.state import PublishPostState
from app.db.models.published_post import PublishedPost
from app.db.models.enums import PublishStatus
from app.db.session import async_session_factory

logger = structlog.get_logger()

# If the scheduled time is within this window, treat as immediate (no scheduleDate)
IMMEDIATE_THRESHOLD = timedelta(minutes=2)


async def scheduler_node(state: PublishPostState) -> dict:
    """Determine publish time and persist to the PublishedPost record.

    Returns `scheduled_at` (ISO UTC string) for future posts, or "" for
    immediate publish. The publish_node passes this as `scheduledAt` to
    the NestJS backend which forwards `scheduledFor` to Zernio.
    """
    try:
        return await _scheduler_impl(state)
    except Exception as exc:
        published_post_id = state.get("published_post_id") or ""
        if published_post_id:
            await mark_publish_failed(
                published_post_id=published_post_id,
                error_message=str(exc),
                stage="schedule",
            )
        raise


async def _scheduler_impl(state: PublishPostState) -> dict:
    now = datetime.now(timezone.utc)
    published_post_id = state["published_post_id"]

    # Determine target publish time
    if state.get("scheduled_time_override"):
        target_time = datetime.fromisoformat(state["scheduled_time_override"])
        if target_time.tzinfo is None:
            target_time = target_time.replace(tzinfo=timezone.utc)
        golden_hour_slot = "manual"
    elif state.get("publish_mode") == "manual":
        # "Publish Now": manual mode with no scheduled_time_override -> publish immediately
        target_time = now
        golden_hour_slot = "manual"
    else:
        gh = state.get("golden_hour_result", {})
        target_time_str = gh.get("scheduled_at", "")
        if target_time_str:
            target_time = datetime.fromisoformat(target_time_str)
            if target_time.tzinfo is None:
                target_time = target_time.replace(tzinfo=timezone.utc)
        else:
            target_time = now  # No golden hour data — publish immediately
        golden_hour_slot = gh.get("selected_slot", {}).get("slot_time", "")

    time_until = target_time - now
    is_immediate = time_until <= IMMEDIATE_THRESHOLD

    if is_immediate:
        logger.info(
            "scheduler: publish immediately",
            published_post_id=published_post_id,
        )
        scheduled_at_iso = ""
        new_status = PublishStatus.PROCESSING
    else:
        # Pass scheduledFor to Zernio — it will deliver at that time
        scheduled_at_iso = target_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        new_status = PublishStatus.PENDING
        logger.info(
            "scheduler: scheduled via publisher",
            published_post_id=published_post_id,
            scheduled_at=scheduled_at_iso,
            golden_hour_slot=golden_hour_slot,
        )

    # Persist schedule metadata to the DB record
    async with async_session_factory() as db:
        result = await db.execute(
            select(PublishedPost).where(PublishedPost.id == published_post_id)
        )
        pub = result.scalar_one_or_none()
        if pub:
            pub.scheduled_at = target_time if not is_immediate else None
            pub.golden_hour_slot = golden_hour_slot
            pub.status = new_status
            await db.commit()

    return {
        "publish_status": "immediate" if is_immediate else "scheduled",
        "scheduled_at": scheduled_at_iso,
    }
