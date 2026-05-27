import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.enums import VideoTaskStatus


class VideoTask(Base):
    __tablename__ = "video_tasks"
    __table_args__ = {"schema": "ai"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )

    # Source
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'url' | 'upload'
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)          # URL or Cloudinary public_id

    # Processing config
    font_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.brand_fonts.id"), nullable=True
    )
    caption_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.caption_templates.id"), nullable=True
    )
    max_clips: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=5)

    # Customization (one-time per task; not saved as preset in v1)
    caption_style: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="default", default="default"
    )
    aspect_ratio: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="9:16", default="9:16"
    )
    crop_x: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="0.5", default=0.5
    )
    crop_y: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="0.5", default=0.5
    )
    reframe_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="static", default="static"
    )
    add_subtitles: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true", default=True
    )
    font_family: Mapped[str] = mapped_column(
        String(60), nullable=False, server_default="Inter", default="Inter"
    )
    font_size: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="40", default=40
    )
    font_color: Mapped[str] = mapped_column(
        String(9), nullable=False, server_default="#FFFFFF", default="#FFFFFF"
    )
    caption_position: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="bottom", default="bottom"
    )

    # Time range — bracket the portion of the source video to analyze
    start_time_s: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="0.0", default=0.0
    )
    end_time_s: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="0.0", default=0.0
    )

    # Status tracking
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=VideoTaskStatus.QUEUED.value, index=True
    )
    progress: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0", default=0)
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    temp_dir: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Optional linkage for analytics
    scan_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.scan_runs.id"), nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    font = relationship("BrandFont", back_populates="video_tasks")
    caption_template = relationship("CaptionTemplate", back_populates="video_tasks")
    clips = relationship("VideoClip", back_populates="task", cascade="all, delete-orphan")
