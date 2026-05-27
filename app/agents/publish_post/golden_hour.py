"""Golden Hour calculation — find the optimal posting time based on historical engagement."""

from __future__ import annotations

from datetime import datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfo

from app.agents.publish_post.constants import (
    ENGAGEMENT_WEIGHTS,
    MIN_POSTS_FOR_GOLDEN_HOUR,
    SLOTS_PER_DAY,
    SLOT_DURATION_MIN,
)
from app.agents.publish_post.failure_handler import mark_publish_failed
from app.agents.publish_post.schemas import GoldenHourResult, GoldenHourSlot
from app.agents.publish_post.state import PublishPostState
from app.config import get_settings
from app.db.models.engagement_time_slot import EngagementTimeSlot

logger = structlog.get_logger()


def _slot_index_to_time(index: int) -> str:
    """Convert a slot index (0-47) to a time string like '07:00-07:30'."""
    hour = index // 2
    minute = (index % 2) * SLOT_DURATION_MIN
    end_minute = minute + SLOT_DURATION_MIN
    end_hour = hour
    if end_minute >= 60:
        end_minute = 0
        end_hour += 1
    return f"{hour:02d}:{minute:02d}-{end_hour:02d}:{end_minute:02d}"


def _time_to_slot_index(hour: int, minute: int) -> int:
    """Convert hour:minute to slot index (0-47)."""
    return hour * 2 + (1 if minute >= 30 else 0)


def _build_fallback_slots(settings_golden_hours: str) -> list[GoldenHourSlot]:
    """Build fallback golden hour slots from config defaults."""
    slots = []
    for time_str in settings_golden_hours.split(","):
        time_str = time_str.strip()
        parts = time_str.split(":")
        hour, minute = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        idx = _time_to_slot_index(hour, minute)
        slots.append(
            GoldenHourSlot(
                slot_time=_slot_index_to_time(idx),
                slot_index=idx,
                weighted_score=0.0,
                sample_count=0,
            )
        )
    return slots


def _find_next_slot(
    top_slots: list[GoldenHourSlot],
    now: datetime,
    tz: ZoneInfo,
) -> tuple[GoldenHourSlot, datetime]:
    """Find the next upcoming slot from the top slots list.

    Returns the selected slot and the scheduled datetime.
    """
    local_now = now.astimezone(tz)
    today = local_now.date()

    for slot in top_slots:
        # Parse start time of the slot
        start_str = slot.slot_time.split("-")[0]
        hour, minute = int(start_str.split(":")[0]), int(start_str.split(":")[1])
        slot_dt = datetime(today.year, today.month, today.day, hour, minute, tzinfo=tz)

        if slot_dt > local_now:
            return slot, slot_dt

    # All slots have passed today — schedule for the first slot tomorrow
    first_slot = top_slots[0]
    start_str = first_slot.slot_time.split("-")[0]
    hour, minute = int(start_str.split(":")[0]), int(start_str.split(":")[1])
    tomorrow = today + timedelta(days=1)
    slot_dt = datetime(tomorrow.year, tomorrow.month, tomorrow.day, hour, minute, tzinfo=tz)
    return first_slot, slot_dt


async def calculate_golden_hours(db: AsyncSession) -> GoldenHourResult:
    """Calculate the optimal posting time based on historical engagement data.

    If fewer than MIN_POSTS_FOR_GOLDEN_HOUR samples exist, falls back to config defaults.
    """
    settings = get_settings()
    tz = ZoneInfo(settings.TIMEZONE)
    now = datetime.now(tz)

    # Query total sample count
    total_result = await db.execute(
        select(func.sum(EngagementTimeSlot.sample_count)).where(
            EngagementTimeSlot.platform == "tiktok"
        )
    )
    total_samples = total_result.scalar() or 0

    if total_samples < MIN_POSTS_FOR_GOLDEN_HOUR:
        logger.info(
            "golden_hour: insufficient data, using fallback",
            total_samples=total_samples,
            threshold=MIN_POSTS_FOR_GOLDEN_HOUR,
        )
        fallback_slots = _build_fallback_slots(settings.DEFAULT_GOLDEN_HOURS)
        selected, scheduled_at = _find_next_slot(fallback_slots, now, tz)
        return GoldenHourResult(
            top_slots=fallback_slots,
            selected_slot=selected,
            scheduled_at=scheduled_at,
            is_fallback=True,
        )

    # Query all slots with data, sorted by weighted score descending
    result = await db.execute(
        select(EngagementTimeSlot)
        .where(EngagementTimeSlot.platform == "tiktok")
        .order_by(EngagementTimeSlot.weighted_score.desc())
    )
    all_slots = result.scalars().all()

    # Build top 3 slots
    top_slots = []
    for slot_row in all_slots[:3]:
        top_slots.append(
            GoldenHourSlot(
                slot_time=slot_row.time_slot,
                slot_index=slot_row.slot_index,
                weighted_score=slot_row.weighted_score,
                sample_count=slot_row.sample_count,
            )
        )

    if not top_slots:
        # No engagement data at all — use fallback
        fallback_slots = _build_fallback_slots(settings.DEFAULT_GOLDEN_HOURS)
        selected, scheduled_at = _find_next_slot(fallback_slots, now, tz)
        return GoldenHourResult(
            top_slots=fallback_slots,
            selected_slot=selected,
            scheduled_at=scheduled_at,
            is_fallback=True,
        )

    # Sort top slots by time for finding next upcoming
    top_slots_by_time = sorted(top_slots, key=lambda s: s.slot_index)
    selected, scheduled_at = _find_next_slot(top_slots_by_time, now, tz)

    logger.info(
        "golden_hour: calculated",
        top_slots=[s.slot_time for s in top_slots],
        selected=selected.slot_time,
        scheduled_at=str(scheduled_at),
    )

    return GoldenHourResult(
        top_slots=top_slots,
        selected_slot=selected,
        scheduled_at=scheduled_at,
        is_fallback=False,
    )


async def golden_hour_node(state: PublishPostState) -> dict:
    """LangGraph node: calculate golden hours and determine scheduling."""
    from app.db.session import async_session_factory

    try:
        async with async_session_factory() as db:
            result = await calculate_golden_hours(db)

        return {
            "golden_hour_result": result.model_dump(mode="json"),
        }
    except Exception as exc:
        published_post_id = state.get("published_post_id") or ""
        if published_post_id:
            await mark_publish_failed(
                published_post_id=published_post_id,
                error_message=str(exc),
                stage="schedule",
            )
        raise
