"""End-to-end pipeline orchestrator.

A PipelineRun is the parent record for the full pipeline (Trending Scanner →
Post Generation → Publishing Post). It wraps the existing scan execution:
``run_pipeline`` creates a ScanRun, links it, runs the proven scan graph
unchanged, then aggregates the generated/published post ids and finalizes the
PipelineRun status. Live, fine-grained progress is read through from the linked
ScanRun by the status endpoint.
"""

import time
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select

from app.api.v1.schemas.pipeline_run import PipelineRunRequest
from app.api.v1.schemas.scan import ScanRequest
from app.db.models import ContentPost, PipelineRun, PublishedPost, ScanRun
from app.db.models.enums import ScanStatus
from app.db.session import async_session_factory

logger = structlog.get_logger()


async def _set_pipeline(pipeline_run_id: str, **fields: object) -> None:
    """Patch a PipelineRun row with the given fields."""
    try:
        async with async_session_factory() as db:
            row = (
                await db.execute(
                    select(PipelineRun).where(PipelineRun.id == uuid.UUID(pipeline_run_id))
                )
            ).scalar_one_or_none()
            if row:
                for key, value in fields.items():
                    setattr(row, key, value)
                await db.commit()
    except Exception as exc:
        logger.warning(
            "_set_pipeline failed", pipeline_run_id=pipeline_run_id, error=str(exc)
        )


async def create_article_pipeline_run(
    user_id: uuid.UUID, scan_run_id: uuid.UUID, url: str
) -> uuid.UUID:
    """Create the parent PipelineRun for a From-URL (article) run.

    Lets the article flow be polled through the unified pipeline status endpoint
    (scan → generate → publish), exactly like the HackerNews pipeline.
    """
    async with async_session_factory() as db:
        run = PipelineRun(
            triggered_by=user_id,
            status=ScanStatus.PENDING,
            stage="scanning",
            scan_run_id=scan_run_id,
            options={"source": "article_url", "url": url},
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return run.id


async def finalize_pipeline_run(
    pipeline_run_id: str, scan_run_id: str, start_time: float
) -> None:
    """Aggregate the scan run's terminal state into the parent PipelineRun.

    Pulls the final scan status plus generated/published post ids and writes the
    coarse milestones + completion timing so the unified status endpoint settles.
    Shared by the HackerNews pipeline and the article pipeline.
    """
    async with async_session_factory() as db:
        scan_row: ScanRun | None = (
            await db.execute(select(ScanRun).where(ScanRun.id == uuid.UUID(scan_run_id)))
        ).scalar_one_or_none()

        content_ids = (
            await db.execute(
                select(ContentPost.id).where(
                    ContentPost.scan_run_id == uuid.UUID(scan_run_id)
                )
            )
        ).scalars().all()

        published_ids = (
            await db.execute(
                select(PublishedPost.id)
                .join(ContentPost, PublishedPost.content_post_id == ContentPost.id)
                .where(ContentPost.scan_run_id == uuid.UUID(scan_run_id))
            )
        ).scalars().all()

    duration_ms = int((time.time() - start_time) * 1000)
    final_status = scan_row.status if scan_row else ScanStatus.FAILED
    # The end-to-end goal is generated posts; a run that errored and produced none
    # is a failure, even if the scan/report partially succeeded. The ScanRun keeps
    # its own (PARTIAL) status so the scan stays retryable.
    if scan_row and scan_row.error and not content_ids:
        final_status = ScanStatus.FAILED
    final_stage = "publishing" if published_ids else "generating"

    await _set_pipeline(
        pipeline_run_id,
        status=final_status,
        stage=final_stage,
        current_step=(scan_row.current_step if scan_row else None),
        total_items_found=(scan_row.total_items_found if scan_row else 0),
        content_post_ids=[str(cid) for cid in content_ids],
        published_post_ids=[str(pid) for pid in published_ids],
        error=(scan_row.error if scan_row else "Pipeline failed"),
        completed_at=datetime.now(timezone.utc),
        duration_ms=duration_ms,
    )

    logger.info(
        "finalize_pipeline_run: completed",
        pipeline_run_id=pipeline_run_id,
        status=final_status.value if hasattr(final_status, "value") else str(final_status),
        published=len(published_ids),
    )


async def run_pipeline(pipeline_run_id: str, request: PipelineRunRequest) -> None:
    """Execute the full pipeline by wrapping a scan run."""
    from app.agents.supervisor import run_scan

    start_time = time.time()

    # Resolve owning user from the pipeline run.
    triggered_by: uuid.UUID | None = None
    async with async_session_factory() as db:
        prow = (
            await db.execute(
                select(PipelineRun).where(PipelineRun.id == uuid.UUID(pipeline_run_id))
            )
        ).scalar_one_or_none()
        if prow:
            triggered_by = prow.triggered_by

    # Create the underlying scan run and link it.
    async with async_session_factory() as db:
        scan_run = ScanRun(
            platforms_requested=[p.value for p in request.platforms],
            status=ScanStatus.PENDING,
            triggered_by=triggered_by,
        )
        db.add(scan_run)
        await db.commit()
        await db.refresh(scan_run)
        scan_run_id = str(scan_run.id)

    await _set_pipeline(
        pipeline_run_id,
        status=ScanStatus.RUNNING,
        stage="scanning",
        scan_run_id=uuid.UUID(scan_run_id),
        options={
            "platforms": [p.value for p in request.platforms],
            "generate_posts": getattr(request.options, "generate_posts", True),
        },
    )

    logger.info(
        "run_pipeline: starting",
        pipeline_run_id=pipeline_run_id,
        scan_run_id=scan_run_id,
    )

    # Run the proven scan graph unchanged. The scan endpoint always generates
    # posts in the pipeline context; force generate_posts on.
    scan_request = ScanRequest(platforms=request.platforms, options=request.options)
    try:
        await run_scan(scan_run_id, scan_request)
    except Exception as exc:
        logger.error(
            "run_pipeline: scan failed",
            pipeline_run_id=pipeline_run_id,
            scan_run_id=scan_run_id,
            error=str(exc),
        )

    # Aggregate final state from the scan run + generated/published posts.
    await finalize_pipeline_run(pipeline_run_id, scan_run_id, start_time)
