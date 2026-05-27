import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.enums import Sentiment


class TrendComment(Base):
    __tablename__ = "trend_comments"
    __table_args__ = {"schema": "ai"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    trend_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai.trend_items.id"), index=True
    )
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    sentiment: Mapped[Sentiment | None] = mapped_column(
        Enum(Sentiment, name="Sentiment", schema="ai", values_callable=lambda e: [m.value for m in e]), nullable=True
    )
    posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    trend_item = relationship("TrendItem", back_populates="comments")
