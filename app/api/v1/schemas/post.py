"""Pydantic schemas for Post Generation API."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl

from app.db.models.enums import ContentStatus, PipelinePublishMode, PostFormat


class PostGenOptions(BaseModel):
    num_posts: int = Field(default=3, ge=1, le=100, description="Number of posts to generate")
    formats: list[PostFormat] | None = Field(
        default=None, description="Allowed formats (None = all)"
    )


class ArticlePublishSettings(BaseModel):
    """Per-request review/publishing overrides for the From Article URL flow.

    Every field is optional; any field left unset falls back to the user's saved
    PipelineConfig (and then to system defaults). Mirrors the review/publishing
    settings the HackerNews scan path reads from PipelineConfig.
    """

    require_review: bool | None = Field(
        default=None, description="Require manual review before publishing"
    )
    auto_approve_threshold: float | None = Field(
        default=None, ge=0, le=10, description="Min review score to auto-approve"
    )
    auto_publish: bool | None = Field(
        default=None, description="Auto-publish approved posts"
    )
    publish_mode: PipelinePublishMode | None = Field(
        default=None, description="Publishing strategy: auto | manual | schedule"
    )
    scheduled_publish_time: str | None = Field(
        default=None, description='HH:MM time, used only when publish_mode="schedule"'
    )
    privacy_level: str | None = Field(
        default=None, description="TikTok privacy level for published posts"
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
    publish_settings: ArticlePublishSettings = Field(
        default_factory=ArticlePublishSettings,
        description="Review/publishing overrides; unset fields fall back to PipelineConfig",
    )


class FromArticleResponse(BaseModel):
    pipeline_id: uuid.UUID
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
    failed_stage: str | None = None
    error_reason: str | None = None
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
    failed_stage: str | None = None
    error_reason: str | None = None
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
        default="",
        max_length=4000,
        description=(
            "Free-form rejection feedback; the LLM uses it to decide what to "
            "regenerate. Required for NEEDS_REVISION posts; optional when "
            "retrying a FAILED post (full regeneration is forced)."
        ),
    )


class PostRegenerateResponse(BaseModel):
    post_id: uuid.UUID
    status: str


class PostListResponse(BaseModel):
    items: list[PostSummary]
    total: int
    page: int
    page_size: int
