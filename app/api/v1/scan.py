import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user_id, get_optional_user_id
from app.api.v1.schemas.scan import ScanRequest, ScanResponse, ScanStatusResponse
from app.db.models import ContentPost, PublishedPost, ScanRun, ScanStatus
from app.dependencies import get_session

router = APIRouter()


@router.post(
    "",
    status_code=202,
    response_model=ScanResponse,
    summary="Trigger a trend scan",
    description=(
        "Start an async HackerNews technology trend scan that crawls trending articles "
        "and optionally generates TikTok content via the content generation agent.\n\n"
        "Returns immediately with a `scan_id` and `pending` status. "
        "Poll `GET /api/v1/scan/{scan_id}/status` to track progress.\n\n"
        "**Pipeline:**\n"
        "1. **Crawl** — fetch top HackerNews stories, extract articles, filter by tech relevance\n"
        "2. **Analyze** — GPT-4o categorization, sentiment, lifecycle, TikTok relevance scoring\n"
        "3. **Save content** — persist articles as markdown files\n"
        "4. **Report** — generate Vietnamese TikTok trend report + content angles\n"
        "5. **Generate posts** *(optional)* — auto-generate TikTok posts from top trends\n\n"
        "**Platform:** `hackernews`\n\n"
        "**Scan options:**\n"
        "- `max_items_per_platform` — 1–200 items to fetch (default 50)\n"
        "- `include_comments` — fetch top comments for each item (default true)\n"
        "- `quality_threshold` — minimum quality score 1–10 to keep articles (default 5)\n"
        "- `keywords` — target tech keywords for trend filtering\n\n"
        "**Content generation options** (when `generate_posts=true`):\n"
        "- `post_gen_options.num_posts` — number of posts to generate, 1–10 (default 3)\n"
        "- `post_gen_options.formats` — allowed post formats "
        "(e.g. `quick_tips`, `hot_take`, `trending_breakdown`). Null = all formats"
    ),
    responses={
        202: {"description": "Scan accepted and queued"},
        422: {"description": "Invalid request body"},
        429: {"description": "Too many concurrent scans for this user"},
    },
)
async def trigger_scan(
    request: ScanRequest,
    http_request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    # Cap concurrent scans per user so one user can't starve others / the DB
    # pool. run_scan releases the slot in its finally block.
    from app.core.concurrency import MAX_CONCURRENT_SCANS_PER_USER, try_acquire_scan_slot

    redis = getattr(http_request.app.state, "redis", None)
    if not await try_acquire_scan_slot(redis, str(user_id)):
        raise HTTPException(
            status_code=429,
            detail=(
                f"You already have {MAX_CONCURRENT_SCANS_PER_USER} scans running. "
                "Wait for one to finish before starting another."
            ),
        )

    scan_run = ScanRun(
        platforms_requested=[p.value for p in request.platforms],
        status=ScanStatus.PENDING,
        triggered_by=user_id,
    )
    db.add(scan_run)
    await db.commit()
    await db.refresh(scan_run)

    # Dispatch the scan. In production (USE_ARQ_FOR_SCANS) it goes to the bounded
    # ARQ worker pool, off the API event loop; otherwise it runs in-process via
    # FastAPI BackgroundTasks. Either path runs the same run_scan pipeline.
    from app.config import get_settings

    if get_settings().USE_ARQ_FOR_SCANS:
        from app.workers.job_queue import enqueue_scan_task

        await enqueue_scan_task(
            str(scan_run.id), request.model_dump(mode="json", exclude_unset=True)
        )
    else:
        from app.agents.supervisor import run_scan

        background_tasks.add_task(run_scan, str(scan_run.id), request)

    return ScanResponse(
        scan_id=scan_run.id,
        status=scan_run.status,
        platforms=request.platforms,
        created_at=scan_run.started_at or datetime.now(timezone.utc),
    )


@router.get(
    "/{scan_id}/status",
    response_model=ScanStatusResponse,
    summary="Get scan status",
    description=(
        "Returns the current status of a scan run.\n\n"
        "**Status values:**\n"
        "- `pending` — queued, not yet started\n"
        "- `running` — actively scanning platforms\n"
        "- `completed` — all platforms succeeded\n"
        "- `partial` — some platforms failed, some succeeded\n"
        "- `failed` — all platforms failed\n\n"
        "Check `platforms_failed` for per-platform error messages."
    ),
    responses={
        200: {"description": "Scan status"},
        404: {"description": "Scan not found"},
    },
)
async def get_scan_status(
    scan_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    user_id: uuid.UUID | None = Depends(get_optional_user_id),
):
    stmt = select(ScanRun).where(ScanRun.id == scan_id)
    if user_id is not None:
        stmt = stmt.where(
            (ScanRun.triggered_by == user_id) | (ScanRun.triggered_by.is_(None))
        )
    result = await db.execute(stmt)
    scan_run = result.scalar_one_or_none()
    if not scan_run:
        raise HTTPException(status_code=404, detail="Scan not found")

    # Posts published from this scan's drafts (auto-publish). Lets the status UI
    # show the Publishing stage for standalone scan / From-URL runs, mirroring the
    # unified pipeline status endpoint.
    published_rows = (
        await db.execute(
            select(PublishedPost.id)
            .join(ContentPost, PublishedPost.content_post_id == ContentPost.id)
            .where(ContentPost.scan_run_id == scan_run.id)
        )
    ).scalars().all()

    return ScanStatusResponse(
        scan_id=scan_run.id,
        status=scan_run.status,
        platforms_completed=scan_run.platforms_completed or [],
        platforms_failed=scan_run.platforms_failed or {},
        total_items_found=scan_run.total_items_found or 0,
        started_at=scan_run.started_at,
        completed_at=scan_run.completed_at,
        duration_ms=scan_run.duration_ms,
        error=scan_run.error,
        current_step=scan_run.current_step,
        published_post_ids=[str(pid) for pid in published_rows],
    )
