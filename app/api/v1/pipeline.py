import uuid
from datetime import datetime, timezone

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user_id, get_optional_user_id
from app.api.v1.schemas.pipeline import PipelineConfigResponse, PipelineConfigUpdate
from app.api.v1.schemas.schedule import ScheduleResponse
from app.api.v1.schemas.pipeline_run import (
    PipelineRunListResponse,
    PipelineRunRequest,
    PipelineRunResponse,
    PipelineRunStatusResponse,
    PipelineRunSummary,
)
from app.db.models import (
    ContentPost,
    PipelineRun,
    PublishedPost,
    ScanRun,
    ScanSchedule,
)
from app.db.models.enums import ScanStatus
from app.db.models.pipeline_config import PipelineConfig
from app.db.models.pipeline_config import PipelinePublishMode as _PipelinePublishMode
from app.dependencies import get_session
from app.services.scan_scheduler import (
    get_scheduler,
    register_schedule,
    unregister_schedule,
)

router = APIRouter()


# Maps the granular ScanRun step to the high-level pipeline stage.
_SCAN_STEPS = {"crawling", "collecting", "analyzing", "saving_report", "persisting"}
_GENERATE_STEPS = {
    "generating_content",
    "post_strategy",
    "post_content",
    "post_image_prompts",
    "post_images",
    "post_review",
    "post_packaging",
}


def _step_to_stage(step: str | None) -> str | None:
    if not step:
        return None
    if step in _SCAN_STEPS:
        return "scanning"
    if step in _GENERATE_STEPS:
        return "generating"
    if step == "publishing":
        return "publishing"
    return None


async def _get_or_create(
    db: AsyncSession, user_id: uuid.UUID
) -> PipelineConfig:
    row = (
        await db.execute(
            select(PipelineConfig).where(PipelineConfig.owner_id == user_id)
        )
    ).scalar_one_or_none()
    if row is None:
        row = PipelineConfig(owner_id=user_id)
        db.add(row)
        await db.flush()
    return row


@router.get(
    "/config",
    response_model=PipelineConfigResponse,
    summary="Get pipeline configuration",
    description=(
        "Returns the pipeline configuration for the current user. "
        "Creates one with defaults on first call."
    ),
)
async def get_pipeline_config(
    db: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> PipelineConfigResponse:
    row = await _get_or_create(db, user_id)
    await db.commit()
    return PipelineConfigResponse.from_orm(row)


@router.post(
    "/config",
    response_model=PipelineConfigResponse,
    summary="Create or replace pipeline configuration",
    description="Idempotent — delegates to PATCH if a row already exists.",
)
async def create_pipeline_config(
    body: PipelineConfigUpdate,
    db: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> PipelineConfigResponse:
    return await _patch_config(body, db, user_id)


@router.patch(
    "/config",
    response_model=PipelineConfigResponse,
    summary="Update pipeline configuration",
    description=(
        "Partially update the pipeline configuration. "
        "Only supplied fields are changed. "
        "When `scan_schedule_enabled` or `scan_cron_expression` changes, "
        "the corresponding `scan_schedules` row is upserted or deactivated."
    ),
)
async def patch_pipeline_config(
    body: PipelineConfigUpdate,
    db: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> PipelineConfigResponse:
    return await _patch_config(body, db, user_id)


async def _patch_config(
    body: PipelineConfigUpdate,
    db: AsyncSession,
    user_id: uuid.UUID,
) -> PipelineConfigResponse:
    row = await _get_or_create(db, user_id)

    updates = body.model_dump(exclude_none=True)
    for field, value in updates.items():
        if field == "publish_mode" and isinstance(value, str):
            value = _PipelinePublishMode(value)
        setattr(row, field, value)

    # Side-effect: sync the user's ScanSchedule row + APScheduler job.
    schedule_fields = {"scan_schedule_enabled", "scan_cron_expression"}
    # ("register", schedule_id, cron) | ("unregister", schedule_id) | None
    sync_action: tuple[str, ...] | None = None
    if schedule_fields.intersection(updates.keys()):
        schedule_row = (
            await db.execute(
                select(ScanSchedule).where(ScanSchedule.owner_id == user_id)
            )
        ).scalar_one_or_none()

        if row.scan_schedule_enabled and row.scan_cron_expression:
            # Validate before persisting so an unschedulable row never lands.
            try:
                CronTrigger.from_crontab(row.scan_cron_expression)
            except ValueError:
                raise HTTPException(
                    status_code=422, detail="Invalid cron expression"
                )
            if schedule_row:
                schedule_row.cron_expression = row.scan_cron_expression
                schedule_row.is_active = True
            else:
                schedule_row = ScanSchedule(
                    owner_id=user_id,
                    cron_expression=row.scan_cron_expression,
                    platforms=["hackernews"],
                    is_active=True,
                )
                db.add(schedule_row)
            await db.flush()  # populate schedule_row.id for new rows
            sync_action = (
                "register",
                str(schedule_row.id),
                row.scan_cron_expression,
            )
        elif schedule_row:
            schedule_row.is_active = False
            sync_action = ("unregister", str(schedule_row.id))

    await db.commit()
    await db.refresh(row)

    # Apply scheduler side-effects only after the DB commit succeeds.
    scheduler = get_scheduler()
    if scheduler is not None and sync_action is not None:
        if sync_action[0] == "register":
            register_schedule(scheduler, sync_action[1], sync_action[2])
        else:
            unregister_schedule(scheduler, sync_action[1])

    return PipelineConfigResponse.from_orm(row)


@router.get(
    "/schedule",
    response_model=ScheduleResponse | None,
    summary="Get the current user's active scan schedule",
    description=(
        "Returns the active recurring scan schedule for the current user "
        "(cron expression, next/last run time), or `null` when none is set. "
        "Powers the Pipeline Control Center 'Active schedule' card."
    ),
)
async def get_pipeline_schedule(
    db: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> ScheduleResponse | None:
    row = (
        await db.execute(
            select(ScanSchedule)
            .where(
                ScanSchedule.owner_id == user_id,
                ScanSchedule.is_active.is_(True),
            )
            .order_by(ScanSchedule.created_at.desc())
        )
    ).scalars().first()
    if row is None:
        return None
    return ScheduleResponse.model_validate(row)


# ── Pipeline runs ───────────────────────────────────────────────────────────
# The end-to-end pipeline (Trending Scanner → Post Generation → Publishing Post)
# is its own resource. It wraps a scan execution; live progress is derived from
# the linked ScanRun. Endpoints live under /pipeline/runs to avoid colliding
# with the /pipeline/config routes above.


@router.post(
    "/runs",
    status_code=202,
    response_model=PipelineRunResponse,
    summary="Trigger an end-to-end pipeline run",
    description=(
        "Start the full pipeline: Trending Scanner → Post Generation → "
        "Publishing Post. Returns immediately with a `pipeline_id`. Poll "
        "`GET /api/v1/pipeline/runs/{id}/status` for the unified 3-stage status. "
        "Whether publishing runs in-pipeline depends on the user's PipelineConfig "
        "(`require_review` / `auto_publish`); in manual-review mode the run ends "
        "after Post Generation."
    ),
    responses={202: {"description": "Pipeline accepted and queued"}},
)
async def trigger_pipeline_run(
    request: PipelineRunRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> PipelineRunResponse:
    pipeline_run = PipelineRun(
        status=ScanStatus.PENDING,
        stage="scanning",
        triggered_by=user_id,
        triggered_type="manual",
    )
    db.add(pipeline_run)
    await db.commit()
    await db.refresh(pipeline_run)

    from app.agents.pipeline_runner import run_pipeline

    background_tasks.add_task(run_pipeline, str(pipeline_run.id), request)

    return PipelineRunResponse(
        pipeline_id=pipeline_run.id,
        status=pipeline_run.status,
        stage=pipeline_run.stage,
        created_at=pipeline_run.started_at or datetime.now(timezone.utc),
    )


@router.get(
    "/runs",
    response_model=PipelineRunListResponse,
    summary="List pipeline runs for the current user",
)
async def list_pipeline_runs(
    db: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PipelineRunListResponse:
    base = select(PipelineRun).where(PipelineRun.triggered_by == user_id)
    total = (
        await db.execute(
            select(func.count()).select_from(base.subquery())
        )
    ).scalar_one()
    rows = (
        await db.execute(
            base.order_by(PipelineRun.started_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return PipelineRunListResponse(
        items=[
            PipelineRunSummary(
                pipeline_id=r.id,
                status=r.status,
                stage=r.stage,
                total_items_found=r.total_items_found or 0,
                started_at=r.started_at,
                completed_at=r.completed_at,
            )
            for r in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/runs/{pipeline_id}/status",
    response_model=PipelineRunStatusResponse,
    summary="Get unified pipeline status (3 stages)",
    description=(
        "Returns the live unified status across Trending Scanner, Post "
        "Generation and Publishing Post. While running, the stage/step is "
        "derived from the linked scan run; once terminal the stored summary is "
        "returned."
    ),
    responses={404: {"description": "Pipeline run not found"}},
)
async def get_pipeline_run_status(
    pipeline_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    user_id: uuid.UUID | None = Depends(get_optional_user_id),
) -> PipelineRunStatusResponse:
    stmt = select(PipelineRun).where(PipelineRun.id == pipeline_id)
    if user_id is not None:
        stmt = stmt.where(
            (PipelineRun.triggered_by == user_id) | (PipelineRun.triggered_by.is_(None))
        )
    pipeline_run = (await db.execute(stmt)).scalar_one_or_none()
    if not pipeline_run:
        raise HTTPException(status_code=404, detail="Pipeline run not found")

    scan_run: ScanRun | None = None
    if pipeline_run.scan_run_id:
        scan_run = (
            await db.execute(
                select(ScanRun).where(ScanRun.id == pipeline_run.scan_run_id)
            )
        ).scalar_one_or_none()

    # Live published/content ids (join through the scan run).
    published_ids: list[str] = []
    content_ids: list[str] = []
    if pipeline_run.scan_run_id:
        published_rows = (
            await db.execute(
                select(PublishedPost.id)
                .join(ContentPost, PublishedPost.content_post_id == ContentPost.id)
                .where(ContentPost.scan_run_id == pipeline_run.scan_run_id)
            )
        ).scalars().all()
        published_ids = [str(p) for p in published_rows]
        content_rows = (
            await db.execute(
                select(ContentPost.id).where(
                    ContentPost.scan_run_id == pipeline_run.scan_run_id
                )
            )
        ).scalars().all()
        content_ids = [str(c) for c in content_rows]

    # Derive live status/stage/step.
    #
    # `run_pipeline` writes `completed_at` only after the whole pipeline has
    # finished, so it is the authoritative terminal signal. Until then, a
    # non-empty scan step means the pipeline is still RUNNING (even if
    # scan_run.status already flipped to completed during the scan phase, while
    # post-gen/publish continue). Once finalized, report the stored terminal
    # status and clear the step so the UI can settle — note the scan step is
    # intentionally retained on error, so we must not let it mask the outcome.
    step = scan_run.current_step if scan_run else None
    if pipeline_run.completed_at is not None:
        status = pipeline_run.status
        stage = pipeline_run.stage or _step_to_stage(step)
        current_step = None
    elif step:
        status = ScanStatus.RUNNING
        stage = _step_to_stage(step)
        current_step = step
    elif scan_run is not None:
        status = ScanStatus.RUNNING
        stage = "publishing" if published_ids else (pipeline_run.stage or "generating")
        current_step = None
    else:
        status = pipeline_run.status
        stage = pipeline_run.stage
        current_step = pipeline_run.current_step

    total_items = (
        scan_run.total_items_found
        if scan_run is not None
        else (pipeline_run.total_items_found or 0)
    ) or 0
    error = (scan_run.error if scan_run is not None else None) or pipeline_run.error

    return PipelineRunStatusResponse(
        pipeline_id=pipeline_run.id,
        status=status,
        stage=stage,
        current_step=current_step,
        scan_run_id=pipeline_run.scan_run_id,
        total_items_found=total_items,
        content_post_ids=content_ids or (pipeline_run.content_post_ids or []),
        published_post_ids=published_ids or (pipeline_run.published_post_ids or []),
        error=error,
        started_at=pipeline_run.started_at,
        completed_at=pipeline_run.completed_at,
        duration_ms=pipeline_run.duration_ms,
    )
