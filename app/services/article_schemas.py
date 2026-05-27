"""Pydantic schemas for the article-express pipeline.

These are the LLM's structured output target — they intentionally mirror
the Stage 3 trend report shape so downstream post-generation can consume
them without modification.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.db.models.enums import (
    EngagementPrediction,
    Sentiment,
    TrendLifecycle,
)


class TikTokAngle(BaseModel):
    format: str = Field(
        description=(
            "One of: educational_breakdown, hot_take, tutorial, "
            "behind_the_scenes, trend_commentary"
        )
    )
    hook_line: str = Field(description="Opening hook to grab attention")


class ArticleTrendBlock(BaseModel):
    id: str = Field(description="Stable id, e.g. 'article_<hash>'")
    topic: str = Field(description="One-line topic / headline")
    quality_score: float = Field(ge=0, le=10)
    sentiment: Sentiment
    engagement_prediction: EngagementPrediction
    lifecycle: TrendLifecycle
    tiktok_angles: list[TikTokAngle] = Field(min_length=1, max_length=5)
    cleaned_content: str = Field(description="Markdown summary, 800-2500 words")
    key_data_points: list[str] = Field(default_factory=list)
    target_audience: list[str] = Field(default_factory=list)


class ArticleReport(BaseModel):
    """Stage 3-equivalent report produced from a single article URL."""

    report_type: str = Field(default="article_express")
    source_url: str
    executive_summary: str
    trends: list[ArticleTrendBlock] = Field(min_length=1, max_length=1)
    content_calendar_suggestions: list[str] = Field(default_factory=list)
