"""Post Generation API endpoints."""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user_id, get_optional_user_id
from app.api.v1.schemas.post import (
    FromArticleRequest,
    FromArticleResponse,
    PostDetail,
    PostGenRequest,
    PostGenResponse,
    PostListResponse,
    PostRegenerateRequest,
    PostRegenerateResponse,
    PostStatusUpdate,
    PostSummary,
)
from app.db.models import ContentPost, ContentStatus, PostFormat, ScanRun, ScanStatus
from app.dependencies import get_session
from app.agents.pipeline_runner import create_article_pipeline_run
from app.services.article_pipeline import (
    create_scan_for_article,
    run_article_pipeline,
)

router = APIRouter()


@router.post(
    "/generate",
    status_code=202,
    response_model=PostGenResponse,
    summary="Generate TikTok posts from a completed scan",
    description=(
        "Triggers async post generation for a completed scan run. "
        "The pipeline reads analyzed trends and strategy, then generates "
        "TikTok-ready posts with captions, hashtags, and image prompts.\n\n"
        "Includes an auto-review loop that scores posts and revises "
        "those scoring below 7 (up to 2 revision cycles)."
    ),
)
async def generate_posts(
    request: PostGenRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    # Validate scan run exists, is completed, and belongs to the caller.
    stmt = select(ScanRun).where(ScanRun.id == request.scan_run_id)
    stmt = stmt.where(
        (ScanRun.triggered_by == user_id) | (ScanRun.triggered_by.is_(None))
    )
    result = await db.execute(stmt)
    scan_run = result.scalar_one_or_none()

    if not scan_run:
        raise HTTPException(status_code=404, detail="Scan run not found")

    if scan_run.status not in (ScanStatus.COMPLETED, ScanStatus.PARTIAL):
        raise HTTPException(
            status_code=400,
            detail=f"Scan run is not completed (status: {scan_run.status.value})",
        )

    # Launch post generation in background
    from app.agents.post_generator.runner import run_post_generation

    options = {
        "num_posts": request.options.num_posts,
        "formats": [f.value for f in request.options.formats] if request.options.formats else None,
    }
    background_tasks.add_task(
        run_post_generation, str(request.scan_run_id), options, str(user_id)
    )

    return PostGenResponse(
        scan_run_id=request.scan_run_id,
        status="accepted",
        message=f"Post generation started for scan {request.scan_run_id}",
    )


@router.post(
    "/from-article",
    status_code=202,
    response_model=FromArticleResponse,
    summary="Generate TikTok posts from a single article URL",
    description=(
        "Express pipeline: crawls the article, builds a Stage-3-equivalent "
        "report, then invokes the existing post-generation graph. "
        "Skips trend scanning entirely.\n\n"
        "Returns 202 immediately with a pipeline_id the client can subscribe "
        "to via the WebSocket gateway (`pipeline:<id>` room) to follow the "
        "unified scan → generate → publish progress."
    ),
)
async def create_post_from_article(
    request: FromArticleRequest,
    background_tasks: BackgroundTasks,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    url_str = str(request.url)
    scan_run_id = await create_scan_for_article(url_str, user_id)
    # Wrap in a parent PipelineRun so the run is polled via /pipeline/runs/{id}/status.
    pipeline_run_id = await create_article_pipeline_run(user_id, scan_run_id, url_str)

    options = {
        "num_posts": request.options.num_posts,
        "formats": (
            [f.value for f in request.options.formats]
            if request.options.formats
            else None
        ),
    }
    # Only forward explicitly-set overrides; unset fields fall back to PipelineConfig.
    publish_overrides = request.publish_settings.model_dump(
        mode="json", exclude_none=True
    )
    background_tasks.add_task(
        run_article_pipeline,
        pipeline_run_id,
        scan_run_id,
        url_str,
        options,
        user_id,
        publish_overrides,
    )

    return FromArticleResponse(
        pipeline_id=pipeline_run_id,
        scan_run_id=scan_run_id,
        status="accepted",
        message=f"Article pipeline started for {url_str}",
    )


@router.get(
    "",
    response_model=PostListResponse,
    summary="List generated posts",
    description="List posts with optional filters by scan_run_id, format, and status.",
)
async def list_posts(
    scan_run_id: uuid.UUID | None = Query(default=None),
    format: PostFormat | None = Query(default=None),
    status: ContentStatus | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    query = select(ContentPost).where(
        (ContentPost.created_by == user_id) | (ContentPost.created_by.is_(None))
    )

    if scan_run_id:
        query = query.where(ContentPost.scan_run_id == scan_run_id)
    if format:
        query = query.where(ContentPost.format == format)
    if status:
        query = query.where(ContentPost.status == status)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Paginate
    query = (
        query.order_by(ContentPost.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(query)
    posts = result.scalars().all()

    return PostListResponse(
        items=[PostSummary.model_validate(p) for p in posts],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{post_id}",
    response_model=PostDetail,
    summary="Get post detail",
    description="Returns full detail for a single generated post.",
)
async def get_post(
    post_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    result = await db.execute(
        select(ContentPost).where(
            ContentPost.id == post_id,
            (ContentPost.created_by == user_id) | (ContentPost.created_by.is_(None)),
        )
    )
    post = result.scalar_one_or_none()

    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    return PostDetail.model_validate(post)


@router.post(
    "/{post_id}/regenerate",
    status_code=202,
    response_model=PostRegenerateResponse,
    summary="Regenerate a post based on human feedback",
    description=(
        "Triggers human-feedback-driven regeneration of a single post. "
        "Called by the NestJS backend when a user rejects a post via the "
        "review endpoint. The AI service classifies the feedback with an "
        "LLM to decide whether to regenerate the caption, image, or both, "
        "overwrites the row in place, and flips the status back to draft "
        "when done. The status transitions are observable via "
        "`GET /posts/{id}` so the frontend can poll."
    ),
)
async def regenerate_post(
    post_id: uuid.UUID,
    request: PostRegenerateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    # Confirm the post exists, is owned by the caller, and is in the
    # needs_revision state set by the backend's review handler.
    result = await db.execute(
        select(ContentPost).where(
            ContentPost.id == post_id,
            (ContentPost.created_by == user_id) | (ContentPost.created_by.is_(None)),
        )
    )
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    # NEEDS_REVISION: user rejected on quality (feedback required).
    # FAILED: post errored mid-pipeline (retry; feedback optional).
    if post.status not in (ContentStatus.NEEDS_REVISION, ContentStatus.FAILED):
        raise HTTPException(
            status_code=409,
            detail=(
                "Post is not retryable (current: "
                f"{post.status.value}); expected needs_revision or failed"
            ),
        )
    if post.status == ContentStatus.NEEDS_REVISION and not request.feedback.strip():
        raise HTTPException(
            status_code=422, detail="feedback is required to revise a post"
        )

    from app.agents.post_generator.revision_runner import run_human_feedback_revision

    background_tasks.add_task(
        run_human_feedback_revision, str(post_id), request.feedback, None
    )

    return PostRegenerateResponse(post_id=post_id, status="regenerating")


@router.patch(
    "/{post_id}/status",
    response_model=PostDetail,
    summary="Update post status",
    description="Update the status of a post (e.g., approve, flag for review).",
)
async def update_post_status(
    post_id: uuid.UUID,
    body: PostStatusUpdate,
    db: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    result = await db.execute(
        select(ContentPost).where(
            ContentPost.id == post_id,
            (ContentPost.created_by == user_id) | (ContentPost.created_by.is_(None)),
        )
    )
    post = result.scalar_one_or_none()

    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    post.status = body.status
    await db.commit()
    await db.refresh(post)

    return PostDetail.model_validate(post)
