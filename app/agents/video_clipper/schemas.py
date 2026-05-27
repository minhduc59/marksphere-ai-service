"""Pydantic models for the LLM segment selection response."""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class ViralityScore(BaseModel):
    hook_score: float = Field(ge=0, le=25)
    engagement_score: float = Field(ge=0, le=25)
    value_score: float = Field(ge=0, le=25)
    shareability_score: float = Field(ge=0, le=25)
    total_score: float = Field(ge=0, le=100)


class SegmentSelection(BaseModel):
    start_ms: int = Field(ge=0, description="Start offset in ms from video start")
    end_ms: int = Field(ge=0, description="End offset in ms from video start")
    text: str = ""
    score: float = Field(ge=0, le=100, default=0.0)
    rationale: str = ""
    virality: ViralityScore | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "SegmentSelection":
        if self.end_ms <= self.start_ms:
            raise ValueError(
                f"end_ms ({self.end_ms}) must be greater than start_ms ({self.start_ms})"
            )
        duration_s = (self.end_ms - self.start_ms) / 1000
        if duration_s < 10:
            raise ValueError(f"Clip too short: {duration_s:.1f}s (minimum 10s)")
        if duration_s > 90:
            raise ValueError(f"Clip too long: {duration_s:.1f}s (maximum 90s)")
        return self


class SelectionResult(BaseModel):
    segments: list[SegmentSelection]
    summary: str = ""
