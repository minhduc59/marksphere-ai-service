"""Request/response schemas for the publish API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# --- Requests ---


class ManualPublishRequest(BaseModel):
    """Request body for manual immediate publish."""
    privacy_level: str = Field(
        default="SELF_ONLY",
        description="TikTok privacy level: SELF_ONLY, MUTUAL_FOLLOW_FRIENDS, FOLLOWER_OF_CREATOR, PUBLIC_TO_EVERYONE",
    )


class SchedulePublishRequest(BaseModel):
    """Request body for scheduling a publish at a specific time."""
    scheduled_at: datetime = Field(
        ..., description="ISO 8601 timestamp for when to publish (must be in the future)"
    )
    privacy_level: str = Field(default="SELF_ONLY")


class AutoPublishRequest(BaseModel):
    """Request body for auto-publish using golden hour scheduling."""
    privacy_level: str = Field(default="SELF_ONLY")


# --- Responses ---


class PublishAcceptedResponse(BaseModel):
    """202 Accepted response for publish requests."""
    published_post_id: str
    mode: str               # "auto" | "manual"
    status: str             # "processing" | "scheduled"
    scheduled_at: datetime | None = None
    message: str


class PublishStatusResponse(BaseModel):
    """Status of a specific publish attempt."""
    id: UUID
    content_post_id: UUID
    platform: str
    status: str
    publish_mode: str
    privacy_level: str
    tiktok_publish_id: str | None
    platform_post_id: str | None
    golden_hour_slot: str | None
    scheduled_at: datetime | None
    published_at: datetime | None
    error_message: str | None
    retry_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class PublishHistoryItem(BaseModel):
    """A single item in publish history."""
    id: UUID
    content_post_id: UUID
    platform: str
    status: str
    publish_mode: str
    golden_hour_slot: str | None
    scheduled_at: datetime | None
    published_at: datetime | None
    error_message: str | None
    retry_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class PublishHistoryResponse(BaseModel):
    """Paginated publish history."""
    items: list[PublishHistoryItem]
    total: int
    page: int
    page_size: int


class GoldenHourSlotResponse(BaseModel):
    """A single golden hour time slot."""
    slot_time: str
    slot_index: int
    weighted_score: float
    sample_count: int


class GoldenHoursResponse(BaseModel):
    """Golden hour analysis result."""
    top_slots: list[GoldenHourSlotResponse]
    selected_slot: GoldenHourSlotResponse
    scheduled_at: datetime
    is_fallback: bool
