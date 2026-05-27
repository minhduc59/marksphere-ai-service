import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CaptionTemplate(Base):
    __tablename__ = "caption_templates"
    __table_args__ = {"schema": "ai"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    font_size: Mapped[int] = mapped_column(Integer, nullable=False, default=40)
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="#FFFFFF")
    outline_color: Mapped[str] = mapped_column(String(20), nullable=False, default="#000000")
    outline_width: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    vertical_position: Mapped[str] = mapped_column(String(20), nullable=False, default="bottom")
    style_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    video_tasks = relationship("VideoTask", back_populates="caption_template")
