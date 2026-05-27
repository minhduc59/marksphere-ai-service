import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, Integer, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey

from app.db.base import Base
from app.db.models.enums import ContentStatus, ContentType, PostFormat


class ContentPost(Base):
    __tablename__ = "content_posts"
    __table_args__ = {"schema": "ai"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    scan_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.scan_runs.id"), nullable=False, index=True
    )
    trend_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.trend_items.id"), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    # Pipeline discriminator — 'photo' (default) or 'video'
    content_type: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="photo", default=ContentType.PHOTO.value
    )

    # Content
    format: Mapped[PostFormat] = mapped_column(
        Enum(PostFormat, name="PostFormat", schema="ai", values_callable=lambda e: [m.value for m in e]), nullable=False
    )
    caption: Mapped[str] = mapped_column(Text, nullable=False)
    hashtags: Mapped[list] = mapped_column(JSON, default=list)
    cta: Mapped[str | None] = mapped_column(String, nullable=True)
    image_prompt: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Source
    trend_title: Mapped[str] = mapped_column(String(500), nullable=False)
    trend_url: Mapped[str | None] = mapped_column(String, nullable=True)
    content_angle_used: Mapped[str | None] = mapped_column(String, nullable=True)
    target_audience: Mapped[list] = mapped_column(JSON, default=list)

    # Posting metadata
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_read_time: Mapped[str | None] = mapped_column(String(50), nullable=True)
    engagement_prediction: Mapped[str | None] = mapped_column(String(20), nullable=True)
    best_posting_day: Mapped[str | None] = mapped_column(String(20), nullable=True)
    best_posting_time: Mapped[str | None] = mapped_column(String(30), nullable=True)
    timing_window: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Review
    status: Mapped[ContentStatus] = mapped_column(
        Enum(ContentStatus, name="ContentStatus", schema="ai", values_callable=lambda e: [m.value for m in e]),
        default=ContentStatus.DRAFT,
    )
    review_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_criteria: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    revision_count: Mapped[int] = mapped_column(Integer, default=0)
    human_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_revision_targets: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Promotion flag — True if generated from a promoted (lower-quality) trend
    is_promoted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # File references
    file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    image_path: Mapped[str | None] = mapped_column(String, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )

    # Relationships
    scan_run = relationship("ScanRun", back_populates="content_posts")
    trend_item = relationship("TrendItem")
    published_posts = relationship(
        "PublishedPost", back_populates="content_post", cascade="all, delete-orphan"
    )
    video_clip = relationship("VideoClip", back_populates="content_post", uselist=False)
