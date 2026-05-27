import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.enums import PublishMode, PublishStatus


class PublishedPost(Base):
    __tablename__ = "published_posts"
    __table_args__ = {"schema": "ai"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    content_post_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai.content_posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    published_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    platform: Mapped[str] = mapped_column(
        String(20), nullable=False, default="tiktok"
    )

    # Publish configuration
    publish_mode: Mapped[PublishMode] = mapped_column(
        Enum(PublishMode, name="PublishMode", schema="ai", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    status: Mapped[PublishStatus] = mapped_column(
        Enum(PublishStatus, name="PublishStatus", schema="ai", values_callable=lambda e: [m.value for m in e]),
        default=PublishStatus.PENDING,
    )
    privacy_level: Mapped[str] = mapped_column(
        String(50), default="SELF_ONLY"
    )

    # TikTok API references
    tiktok_publish_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    platform_post_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )

    # Scheduling
    golden_hour_slot: Mapped[str | None] = mapped_column(
        String(11), nullable=True
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scheduler_job_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )

    # Content snapshot
    assembled_caption: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Error tracking
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    api_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )

    # Relationships
    content_post = relationship("ContentPost", back_populates="published_posts")
