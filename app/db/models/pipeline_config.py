import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, Integer, JSON, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import PipelinePublishMode


class PipelineConfig(Base):
    __tablename__ = "pipeline_configs"
    __table_args__ = {"schema": "ai"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    # Scan config
    max_items_per_platform: Mapped[int] = mapped_column(Integer, default=50)
    quality_threshold: Mapped[int] = mapped_column(Integer, default=5)
    include_comments: Mapped[bool] = mapped_column(Boolean, default=True)
    keywords: Mapped[list] = mapped_column(JSON, default=list)

    # Post generation
    num_posts: Mapped[int] = mapped_column(Integer, default=3)
    allowed_formats: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Review config
    require_review: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_approve_threshold: Mapped[float] = mapped_column(Float, default=7.0)

    # Auto-publish config
    auto_publish: Mapped[bool] = mapped_column(Boolean, default=False)
    publish_mode: Mapped[PipelinePublishMode] = mapped_column(
        Enum(
            PipelinePublishMode,
            name="pipelinepublishmode",
            schema="ai",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=PipelinePublishMode.AUTO,
    )
    scheduled_publish_time: Mapped[str | None] = mapped_column(
        String(5), nullable=True
    )
    default_privacy_level: Mapped[str] = mapped_column(
        String(50), default="SELF_ONLY"
    )

    # Schedule config
    scan_schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    scan_cron_expression: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )

    # HackerNews API config
    hn_rate_limit_per_min: Mapped[int] = mapped_column(Integer, default=60)
    hn_retry_strategy: Mapped[str] = mapped_column(
        String(20), default="exponential"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )
