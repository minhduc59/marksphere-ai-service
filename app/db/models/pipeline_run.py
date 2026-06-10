import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, JSON, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import ScanStatus


class PipelineRun(Base):
    """Parent orchestration record for the end-to-end pipeline.

    Wraps a single scan execution (Trending Scanner → Post Generation →
    Publishing Post). The live, fine-grained progress is read through from the
    linked ``ScanRun`` (``current_step``); this row stores the coarse milestones
    plus the aggregated content/published post ids so the unified 3-stage
    status can be served from one resource.
    """

    __tablename__ = "pipeline_runs"
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
    # High-level stage: "scanning" | "generating" | "publishing".
    stage: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Mirror of the granular ScanRun step at terminal time.
    current_step: Mapped[str | None] = mapped_column(String(50), nullable=True)

    scan_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    content_post_ids: Mapped[list] = mapped_column(JSON, default=list)
    published_post_ids: Mapped[list] = mapped_column(JSON, default=list)
    total_items_found: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    options: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
