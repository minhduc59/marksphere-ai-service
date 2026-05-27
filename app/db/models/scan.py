import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, JSON, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.enums import ScanStatus


class ScanRun(Base):
    __tablename__ = "scan_runs"
    __table_args__ = {"schema": "ai"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    status: Mapped[ScanStatus] = mapped_column(
        Enum(ScanStatus, name="ScanStatus", schema="ai", values_callable=lambda e: [m.value for m in e]),
        default=ScanStatus.PENDING,
    )
    platforms_requested: Mapped[list] = mapped_column(JSON, default=list)
    platforms_completed: Mapped[list] = mapped_column(JSON, default=list)
    platforms_failed: Mapped[dict] = mapped_column(JSON, default=dict)
    total_items_found: Mapped[int] = mapped_column(Integer, default=0)
    langgraph_thread_id: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    report_file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    current_step: Mapped[str | None] = mapped_column(String(50), nullable=True)

    trend_items: Mapped[list["TrendItem"]] = relationship(
        back_populates="scan_run", cascade="all, delete-orphan"
    )
    content_posts: Mapped[list["ContentPost"]] = relationship(
        back_populates="scan_run", cascade="all, delete-orphan"
    )
