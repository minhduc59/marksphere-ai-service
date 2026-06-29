import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.api.v1.schemas.scan import ScanOptions
from app.db.models.enums import Platform, ScanStatus


class PipelineRunRequest(BaseModel):
    """Trigger the end-to-end pipeline (scan → post generation → publishing).

    Reuses the scan options. ``generate_posts`` defaults to True since the
    pipeline always generates posts; auto-publish is governed by the user's
    saved PipelineConfig (``require_review`` / ``auto_publish``).
    """

    platforms: list[Platform] = Field(
        default=[Platform.HACKERNEWS],
        description="Platforms to scan (currently only hackernews)",
    )
    options: ScanOptions = Field(default_factory=ScanOptions)


class PipelineRunResponse(BaseModel):
    pipeline_id: uuid.UUID
    status: ScanStatus
    stage: str | None = None
    created_at: datetime


class PipelineRunStatusResponse(BaseModel):
    pipeline_id: uuid.UUID
    status: ScanStatus
    # High-level stage: "scanning" | "generating" | "publishing".
    stage: str | None = None
    # Granular step (mirrors ScanRun.current_step) for the progress sub-detail.
    current_step: str | None = None
    scan_run_id: uuid.UUID | None = None
    total_items_found: int = 0
    content_post_ids: list[str] = []
    published_post_ids: list[str] = []
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    source_type: str | None = None


class PipelineRunSummary(BaseModel):
    pipeline_id: uuid.UUID
    status: ScanStatus
    stage: str | None = None
    total_items_found: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None


class PipelineRunListResponse(BaseModel):
    items: list[PipelineRunSummary] = []
    total: int = 0
    page: int = 1
    page_size: int = 20
