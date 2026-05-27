import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.enums import VideoClipStatus


class VideoClip(Base):
    __tablename__ = "video_clips"
    __table_args__ = {"schema": "ai"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai.video_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content_post_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai.content_posts.id"),
        nullable=True,
        unique=True,
    )

    clip_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # Storage
    storage_url: Mapped[str] = mapped_column(Text, nullable=False)
    storage_public_id: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_public_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Display
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Timeline
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    # Content
    transcript_segment: Mapped[str | None] = mapped_column(Text, nullable=True)

    # LLM scoring
    llm_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    llm_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    hook_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    engagement_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Review
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=VideoClipStatus.DRAFT.value, index=True
    )
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Publish tracking
    platform_post_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_post_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.published_posts.id"), nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )

    # Relationships
    task = relationship("VideoTask", back_populates="clips")
    content_post = relationship("ContentPost", back_populates="video_clip")
    published_post = relationship("PublishedPost")
