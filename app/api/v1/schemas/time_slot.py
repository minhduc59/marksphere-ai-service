"""Request/response schemas for EngagementTimeSlot CRUD."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

TIME_SLOT_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$"


class TimeSlotBase(BaseModel):
    platform: str = Field(default="tiktok", max_length=20)
    time_slot: str = Field(..., pattern=TIME_SLOT_PATTERN, examples=["19:00-19:30"])
    slot_index: int = Field(..., ge=0, le=47)
    avg_views: float = Field(default=0.0, ge=0)
    avg_likes: float = Field(default=0.0, ge=0)
    avg_comments: float = Field(default=0.0, ge=0)
    avg_shares: float = Field(default=0.0, ge=0)
    weighted_score: float = Field(default=0.0, ge=0)
    sample_count: int = Field(default=0, ge=0)


class TimeSlotCreate(TimeSlotBase):
    pass


class TimeSlotUpdate(BaseModel):
    platform: str | None = Field(default=None, max_length=20)
    time_slot: str | None = Field(default=None, pattern=TIME_SLOT_PATTERN)
    slot_index: int | None = Field(default=None, ge=0, le=47)
    avg_views: float | None = Field(default=None, ge=0)
    avg_likes: float | None = Field(default=None, ge=0)
    avg_comments: float | None = Field(default=None, ge=0)
    avg_shares: float | None = Field(default=None, ge=0)
    weighted_score: float | None = Field(default=None, ge=0)
    sample_count: int | None = Field(default=None, ge=0)


class TimeSlotResponse(TimeSlotBase):
    id: UUID
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TimeSlotListResponse(BaseModel):
    items: list[TimeSlotResponse]
