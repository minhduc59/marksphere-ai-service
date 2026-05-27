import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.db.models.enums import (
    EngagementPrediction,
    Platform,
    Sentiment,
    SourceType,
    TrendLifecycle,
)


class ContentAngle(BaseModel):
    angle: str
    format: str
    hook_line: str


class TrendCommentResponse(BaseModel):
    id: uuid.UUID
    author: str | None = None
    text: str
    likes: int = 0
    sentiment: Sentiment | None = None
    posted_at: datetime | None = None

    model_config = {"from_attributes": True}


class TrendSummary(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None = None
    platform: Platform
    source_url: str | None = None
    thumbnail_url: str | None = None
    category: str | None = None
    sentiment: Sentiment | None = None
    lifecycle: TrendLifecycle | None = None
    relevance_score: float | None = None
    quality_score: float | None = None
    engagement_prediction: EngagementPrediction | None = None
    views: int | None = None
    likes: int | None = None
    hashtags: list[str] = []
    discovered_at: datetime

    model_config = {"from_attributes": True}


class TrendDetail(TrendSummary):
    content_body: str | None = None
    cleaned_content: str | None = None
    video_url: str | None = None
    image_urls: list[str] = []
    tags: list[str] = []
    comments_count: int | None = None
    shares: int | None = None
    trending_score: float | None = None
    author_name: str | None = None
    author_url: str | None = None
    author_followers: int | None = None
    source_type: SourceType | None = None
    related_topics: list[str] = []
    content_angles: list[ContentAngle] = []
    key_data_points: list[str] = []
    target_audience: list[str] = []
    cross_platform_ids: list[str] = []
    comments: list[TrendCommentResponse] = []
    raw_data: dict | None = None
    published_at: datetime | None = None


class TrendFilter(BaseModel):
    platform: Platform | None = None
    category: str | None = None
    sentiment: Sentiment | None = None
    lifecycle: TrendLifecycle | None = None
    min_score: float | None = Field(default=None, ge=0, le=10)
    sort_by: str = Field(default="relevance_score", pattern="^(relevance_score|views|discovered_at)$")
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=100)


class TrendListResponse(BaseModel):
    items: list[TrendSummary]
    total: int
    page: int
    limit: int
