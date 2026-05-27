import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EngagementTimeSlot(Base):
    __tablename__ = "engagement_time_slots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    platform: Mapped[str] = mapped_column(
        String(20), nullable=False, default="tiktok"
    )
    time_slot: Mapped[str] = mapped_column(
        String(11), nullable=False
    )
    slot_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # Engagement averages
    avg_views: Mapped[float] = mapped_column(Float, default=0.0)
    avg_likes: Mapped[float] = mapped_column(Float, default=0.0)
    avg_comments: Mapped[float] = mapped_column(Float, default=0.0)
    avg_shares: Mapped[float] = mapped_column(Float, default=0.0)

    # Computed score and sample size
    weighted_score: Mapped[float] = mapped_column(Float, default=0.0)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("platform", "slot_index", name="uq_platform_slot_index"),
        {"schema": "ai"},
    )
