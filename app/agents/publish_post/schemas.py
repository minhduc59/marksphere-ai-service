"""Pydantic schemas for the Publish Post Agent."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class GoldenHourSlot(BaseModel):
    """A single 30-minute time slot with engagement score."""
    slot_time: str          # e.g. "19:00-19:30"
    slot_index: int         # 0-47
    weighted_score: float
    sample_count: int


class GoldenHourResult(BaseModel):
    """Result of golden hour calculation."""
    top_slots: list[GoldenHourSlot]
    selected_slot: GoldenHourSlot
    scheduled_at: datetime
    is_fallback: bool       # True if using default slots (insufficient data)
