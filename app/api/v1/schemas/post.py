"""Pydantic schemas for Post Generation API."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl

from app.db.models.enums import ContentStatus, PostFormat


class PostGenOptions(BaseModel):
    num_posts: int = Field(default=3, ge=1, le=10, description="Number of posts to generate")
    formats: list[PostFormat] | None = Field(
        default=None, description="Allowed formats (None = all)"
    )


class PostGenRequest(BaseModel):
    scan_run_id: uuid.UUID = Field(description="ID of the completed scan run")
    options: PostGenOptions = Field(default_factory=PostGenOptions)


class PostGenResponse(BaseModel):
    scan_run_id: uuid.UUID
    status: str
    message: str


class FromArticleRequest(BaseModel):
    url: HttpUrl = Field(description="Public URL of the article to crawl")
    options: PostGenOptions = Field(default_factory=PostGenOptions)


class FromArticleResponse(BaseModel):
    scan_run_id: uuid.UUID
    status: str
    message: str


class PostSummary(BaseModel):
    id: uuid.UUID
    scan_run_id: uuid.UUID
    format: PostFormat
    trend_title: str
    status: ContentStatus
    review_score: float | None
    word_count: int | None
    engagement_prediction: str | None
    best_posting_day: str | None
    is_promoted: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class PostDetail(BaseModel):
    id: uuid.UUID
    scan_run_id: uuid.UUID
    trend_item_id: uuid.UUID | None
    format: PostFormat
    caption: str
    hashtags: list[str]
    cta: str | None
    image_prompt: dict | None
    trend_title: str
    trend_url: str | None
    content_angle_used: str | None
    target_audience: list[str]
    word_count: int | None
    estimated_read_time: str | None
    engagement_prediction: str | None
    best_posting_day: str | None
    best_posting_time: str | None
    timing_window: str | None
    status: ContentStatus
    review_score: float | None
    review_notes: str | None
    review_criteria: dict | None
    revision_count: int
    is_promoted: bool = False
    file_path: str | None
    image_path: str | None = None
    content_type: str = "photo"
    created_at: datetime
    updated_at: datetime | None

    class Config:
        from_attributes = True


class PostStatusUpdate(BaseModel):
    status: ContentStatus = Field(description="New status for the post")


class PostRegenerateRequest(BaseModel):
    feedback: str = Field(
        min_length=1,
        max_length=4000,
        description="Free-form rejection feedback from the user; the LLM uses it to decide what to regenerate.",
    )


class PostRegenerateResponse(BaseModel):
    post_id: uuid.UUID
    status: str


class PostListResponse(BaseModel):
    items: list[PostSummary]
    total: int
    page: int
    page_size: int
