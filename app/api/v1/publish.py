"""Publish API endpoints — manual publish, scheduling, history, golden hours."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select

from app.agents.publish_post.golden_hour import calculate_golden_hours
from app.agents.publish_post.runner import run_publish_pipeline
from app.api.v1.deps import get_current_user_id
from app.config import get_settings
from app.api.v1.schemas.publish import (
    AutoPublishRequest,
    GoldenHoursResponse,
    GoldenHourSlotResponse,
    ManualPublishRequest,
    PublishAcceptedResponse,
    PublishHistoryItem,
    PublishHistoryResponse,
    PublishStatusResponse,
    SchedulePublishRequest,
)
from app.db.models.content_post import ContentPost
from app.db.models.enums import ContentStatus, PublishMode, PublishStatus
from app.db.models.published_post import PublishedPost
from app.db.session import async_session_factory

logger = structlog.get_logger()
router = APIRouter()


@router.post(
    "/{post_id}",
    response_model=PublishAcceptedResponse,
    status_code=202,
    summary="Publish a post immediately",
    description="Manually publish an approved post to TikTok right now.",
)
async def publish_now(
    post_id: str,
    body: ManualPublishRequest,
    background_tasks: BackgroundTasks,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    await _validate_post_for_publish(post_id, user_id)

    published_post_id = await _create_published_post_row(
        content_post_id=post_id,
        user_id=user_id,
        mode=PublishMode.MANUAL,
        privacy_level=body.privacy_level,
    )

    background_tasks.add_task(
        run_publish_pipeline,
        content_post_id=post_id,
        mode="manual",
        scheduled_time=None,
        privacy_level=body.privacy_level,
        user_id=str(user_id),
        published_post_id=published_post_id,
    )

    return PublishAcceptedResponse(
        published_post_id=published_post_id,
        mode="manual",
        status="processing",
        message="Post submitted for immediate publishing. Check status via GET /publish/{id}/status.",
    )


@router.post(
    "/{post_id}/schedule",
    response_model=PublishAcceptedResponse,
    status_code=202,
    summary="Schedule a post for a specific time",
    description="Schedule an approved post to publish at a specific time.",
)
async def schedule_publish(
    post_id: str,
    body: SchedulePublishRequest,
    background_tasks: BackgroundTasks,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    await _validate_post_for_publish(post_id, user_id)

    # Validate scheduled time is in the future
    now = datetime.now(timezone.utc)
    scheduled_at = body.scheduled_at
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
    if scheduled_at <= now:
        raise HTTPException(status_code=400, detail="scheduled_at must be in the future")

    published_post_id = await _create_published_post_row(
        content_post_id=post_id,
        user_id=user_id,
        mode=PublishMode.MANUAL,
        privacy_level=body.privacy_level,
    )

    background_tasks.add_task(
        run_publish_pipeline,
        content_post_id=post_id,
        mode="manual",
        scheduled_time=scheduled_at,
        privacy_level=body.privacy_level,
        user_id=str(user_id),
        published_post_id=published_post_id,
    )

    return PublishAcceptedResponse(
        published_post_id=published_post_id,
        mode="manual",
        status="scheduled",
        scheduled_at=scheduled_at,
        message=f"Post scheduled for {scheduled_at.isoformat()}.",
    )


@router.post(
    "/{post_id}/auto",
    response_model=PublishAcceptedResponse,
    status_code=202,
    summary="Auto-publish using golden hour",
    description="Schedule an approved post using the optimal golden hour time.",
)
async def auto_publish(
    post_id: str,
    body: AutoPublishRequest,
    background_tasks: BackgroundTasks,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    await _validate_post_for_publish(post_id, user_id)

    published_post_id = await _create_published_post_row(
        content_post_id=post_id,
        user_id=user_id,
        mode=PublishMode.AUTO,
        privacy_level=body.privacy_level,
    )

    background_tasks.add_task(
        run_publish_pipeline,
        content_post_id=post_id,
        mode="auto",
        privacy_level=body.privacy_level,
        user_id=str(user_id),
        published_post_id=published_post_id,
    )

    return PublishAcceptedResponse(
        published_post_id=published_post_id,
        mode="auto",
        status="processing",
        message="Post submitted for golden hour scheduling.",
    )


@router.delete(
    "/{post_id}/schedule",
    status_code=200,
    summary="Cancel a scheduled publish",
)
async def cancel_scheduled_publish(
    post_id: str,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Cancel a pending scheduled publish job."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(PublishedPost).where(
                PublishedPost.content_post_id == uuid.UUID(post_id),
                PublishedPost.status == PublishStatus.PENDING,
                (PublishedPost.published_by == user_id)
                | (PublishedPost.published_by.is_(None)),
            ).order_by(PublishedPost.created_at.desc())
        )
        pub = result.scalar_one_or_none()

        if not pub:
            raise HTTPException(status_code=404, detail="No pending scheduled publish found for this post")

        # Cancel APScheduler job if exists
        # Cancel on Zernio via backend if there's a submitted post ID
        if pub.tiktok_publish_id:
            settings = get_settings()
            backend_url = settings.BACKEND_ORIGIN.rstrip("/")
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.delete(
                        f"{backend_url}/v1/publisher/internal/cancel-scheduled/{pub.id}",
                        headers={"x-internal-api-key": settings.INTERNAL_API_KEY},
                    )
                    resp.raise_for_status()
            except Exception as exc:
                logger.warning(
                    "cancel_scheduled: Zernio cancel failed (continuing)",
                    error=str(exc),
                )

        pub.status = PublishStatus.CANCELLED
        await db.commit()

    return {"message": "Scheduled publish cancelled", "post_id": post_id}


@router.get(
    "/history",
    response_model=PublishHistoryResponse,
    summary="List publish history",
)
async def publish_history(
    status: str | None = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """List all publish attempts with optional status filter."""
    async with async_session_factory() as db:
        user_filter = (PublishedPost.published_by == user_id) | (
            PublishedPost.published_by.is_(None)
        )
        query = (
            select(PublishedPost)
            .where(user_filter)
            .order_by(PublishedPost.created_at.desc())
        )
        count_query = select(func.count(PublishedPost.id)).where(user_filter)

        if status:
            query = query.where(PublishedPost.status == status)
            count_query = count_query.where(PublishedPost.status == status)

        total = (await db.execute(count_query)).scalar() or 0
        result = await db.execute(
            query.offset((page - 1) * page_size).limit(page_size)
        )
        items = result.scalars().all()

    return PublishHistoryResponse(
        items=[
            PublishHistoryItem(
                id=item.id,
                content_post_id=item.content_post_id,
                platform=item.platform,
                status=item.status.value,
                publish_mode=item.publish_mode.value,
                golden_hour_slot=item.golden_hour_slot,
                scheduled_at=item.scheduled_at,
                published_at=item.published_at,
                error_message=item.error_message,
                retry_count=item.retry_count,
                created_at=item.created_at,
            )
            for item in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/golden-hours",
    response_model=GoldenHoursResponse,
    summary="Get golden hour analysis",
    description="Returns the top 3 optimal posting time slots based on engagement data.",
)
async def get_golden_hours():
    async with async_session_factory() as db:
        result = await calculate_golden_hours(db)

    return GoldenHoursResponse(
        top_slots=[
            GoldenHourSlotResponse(
                slot_time=s.slot_time,
                slot_index=s.slot_index,
                weighted_score=s.weighted_score,
                sample_count=s.sample_count,
            )
            for s in result.top_slots
        ],
        selected_slot=GoldenHourSlotResponse(
            slot_time=result.selected_slot.slot_time,
            slot_index=result.selected_slot.slot_index,
            weighted_score=result.selected_slot.weighted_score,
            sample_count=result.selected_slot.sample_count,
        ),
        scheduled_at=result.scheduled_at,
        is_fallback=result.is_fallback,
    )


@router.get(
    "/{published_post_id}/status",
    response_model=PublishStatusResponse,
    summary="Check publish status",
)
async def get_publish_status(
    published_post_id: str,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Get the current status of a specific publish attempt."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(PublishedPost).where(
                PublishedPost.id == uuid.UUID(published_post_id),
                (PublishedPost.published_by == user_id)
                | (PublishedPost.published_by.is_(None)),
            )
        )
        pub = result.scalar_one_or_none()

    if not pub:
        raise HTTPException(status_code=404, detail="Published post not found")

    return PublishStatusResponse(
        id=pub.id,
        content_post_id=pub.content_post_id,
        platform=pub.platform,
        status=pub.status.value,
        publish_mode=pub.publish_mode.value,
        privacy_level=pub.privacy_level,
        tiktok_publish_id=pub.tiktok_publish_id,
        platform_post_id=pub.platform_post_id,
        golden_hour_slot=pub.golden_hour_slot,
        scheduled_at=pub.scheduled_at,
        published_at=pub.published_at,
        error_message=pub.error_message,
        retry_count=pub.retry_count,
        created_at=pub.created_at,
    )


async def _validate_post_for_publish(post_id: str, user_id: uuid.UUID) -> None:
    """Validate that a ContentPost exists, belongs to the user, and is eligible."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(ContentPost).where(
                ContentPost.id == uuid.UUID(post_id),
                (ContentPost.created_by == user_id) | (ContentPost.created_by.is_(None)),
            )
        )
        post = result.scalar_one_or_none()

    if not post:
        raise HTTPException(status_code=404, detail=f"Post {post_id} not found")

    if post.status not in (ContentStatus.APPROVED,):
        raise HTTPException(
            status_code=400,
            detail=f"Post has status '{post.status.value}'. Only 'approved' posts can be published.",
        )

    # Check for existing successful publish
    async with async_session_factory() as db:
        existing = await db.execute(
            select(PublishedPost).where(
                PublishedPost.content_post_id == uuid.UUID(post_id),
                PublishedPost.status == PublishStatus.PUBLISHED,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Post is already published")


async def _create_published_post_row(
    content_post_id: str,
    user_id: uuid.UUID,
    mode: PublishMode,
    privacy_level: str,
) -> str:
    """Insert a PROCESSING PublishedPost row and return its UUID as a string.

    Doing this synchronously (before queuing the background task) lets the API
    response carry the real id so the frontend can subscribe to the WebSocket
    room `publish:<id>` and poll `GET /publish/{id}/status` immediately.
    """
    async with async_session_factory() as db:
        pub = PublishedPost(
            content_post_id=uuid.UUID(content_post_id),
            published_by=user_id,
            publish_mode=mode,
            status=PublishStatus.PROCESSING,
            privacy_level=privacy_level,
        )
        db.add(pub)
        await db.flush()
        published_post_id = str(pub.id)
        await db.commit()
    return published_post_id
