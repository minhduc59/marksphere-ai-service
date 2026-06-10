import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import redis.asyncio as aioredis
import structlog
from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from app.agents.content_saver import content_saver_node
from app.agents.post_generator.runner import run_post_generation
from app.agents.scanners.hackernews import HackerNewsScannerNode
from app.agents.state import TrendScanState
from app.agents.trend_analyzer import trend_analyzer_node
from app.api.v1.schemas.scan import ScanRequest
from app.config import get_settings
from app.core.llm_errors import classify_llm_error
from app.core.rate_limiter import RateLimiter
from app.db.models import ScanRun, ScanStatus, TrendComment, TrendItem
from app.db.models.content_post import ContentPost
from app.db.models.enums import ContentStatus, SourceType
from app.db.models.pipeline_config import PipelineConfig
from app.db.session import async_session_factory

logger = structlog.get_logger()

# Map common LLM-generated source_type values to valid enum values
_SOURCE_TYPE_ALIASES: dict[str, str] = {
    "blog": "official_blog",
    "article": "news",
    "paper": "research",
    "forum": "community",
    "discussion": "community",
    "twitter": "social",
    "reddit": "social",
}
_VALID_SOURCE_TYPES = {e.value for e in SourceType}


def _normalize_source_type(raw: str | None) -> str | None:
    """Normalize LLM source_type output to a valid SourceType enum value."""
    if not raw:
        return None
    val = raw.strip().lower()
    if val in _VALID_SOURCE_TYPES:
        return val
    return _SOURCE_TYPE_ALIASES.get(val, "community")


# Maps LangGraph node names to pipeline step identifiers exposed via the status API.
_NODE_STEP_MAP: dict[str, str] = {
    "hackernews_scanner": "crawling",
    "collect_results":    "collecting",
    "trend_analyzer":     "analyzing",
    "content_saver":      "saving_report",
    "persist_results":    "persisting",
    "generate_posts":     "generating_content",
}


async def _update_scan_step(scan_run_id: str, step: str) -> None:
    """Write the current pipeline step to the DB so the status API reflects it."""
    try:
        async with async_session_factory() as db:
            row = (
                await db.execute(select(ScanRun).where(ScanRun.id == uuid.UUID(scan_run_id)))
            ).scalar_one_or_none()
            if row:
                row.current_step = step
                await db.commit()
    except Exception as exc:
        logger.warning("_update_scan_step failed", scan_run_id=scan_run_id, step=step, error=str(exc))


async def load_pipeline_cfg_for_owner(owner_id) -> dict | None:
    """Load a user's PipelineConfig as a plain dict.

    Returns the same shape ``run_scan`` builds: publish-driving keys plus the
    ``_cfg_*`` scan-default keys. Returns ``None`` when the user has no saved
    config. Shared by the HackerNews supervisor and the article-express pipeline
    so the dict shape stays in sync.
    """
    async with async_session_factory() as db:
        cfg_row = (
            await db.execute(
                select(PipelineConfig).where(PipelineConfig.owner_id == owner_id)
            )
        ).scalar_one_or_none()
    if cfg_row is None:
        return None
    return {
        "require_review": cfg_row.require_review,
        "auto_approve_threshold": cfg_row.auto_approve_threshold,
        "auto_publish": cfg_row.auto_publish,
        "publish_mode": cfg_row.publish_mode.value
        if hasattr(cfg_row.publish_mode, "value")
        else str(cfg_row.publish_mode),
        "scheduled_publish_time": cfg_row.scheduled_publish_time,
        "default_privacy_level": cfg_row.default_privacy_level,
        # Scan defaults — request values override these in run_scan.
        "_cfg_max_items": cfg_row.max_items_per_platform,
        "_cfg_quality_threshold": cfg_row.quality_threshold,
        "_cfg_include_comments": cfg_row.include_comments,
        "_cfg_keywords": cfg_row.keywords,
        "_cfg_num_posts": cfg_row.num_posts,
        "_cfg_allowed_formats": cfg_row.allowed_formats,
    }


async def apply_review_and_publish(
    scan_run_id: str,
    pipeline_cfg: dict | None,
    user_id: str | None,
    step_cb: Callable[[str], Awaitable[None]] | None = None,
) -> None:
    """Apply the review-gate and (optionally) auto-publish to a scan's draft posts.

    Shared by the HackerNews supervisor graph and the article-express pipeline so
    both honour the same PipelineConfig-driven behaviour:
      - When ``require_review`` is True, do nothing (posts await manual review).
      - Otherwise auto-approve DRAFT posts scoring >= threshold that have an image;
        flag imageless ones for manual review (a thumbnail is mandatory to publish).
      - When ``auto_publish`` is on, run the publish pipeline for each approved post,
        marking the ScanRun PARTIAL if any publish fails.
    """
    cfg = pipeline_cfg or {}
    approved_ids: list[str] = []

    if cfg.get("require_review", True):
        return

    threshold = float(cfg.get("auto_approve_threshold", 7.0))
    try:
        async with async_session_factory() as db:
            posts = (
                await db.execute(
                    select(ContentPost).where(
                        ContentPost.scan_run_id == uuid.UUID(scan_run_id),
                        ContentPost.status == ContentStatus.DRAFT,
                    )
                )
            ).scalars().all()
            for post in posts:
                meets_score = (post.review_score or 0.0) >= threshold
                has_image = bool((post.image_path or "").strip())
                if meets_score and has_image:
                    post.status = ContentStatus.APPROVED
                    approved_ids.append(str(post.id))
                    logger.info(
                        "apply_review_and_publish: auto-approved",
                        post_id=str(post.id),
                        score=post.review_score,
                        threshold=threshold,
                    )
                elif meets_score and not has_image:
                    # Thumbnail is mandatory — a post without an image cannot be
                    # published. Flag it for manual review instead of silently
                    # publishing imageless content.
                    post.status = ContentStatus.FLAGGED_FOR_REVIEW
                    logger.warning(
                        "apply_review_and_publish: post missing image, flagged for review",
                        post_id=str(post.id),
                        score=post.review_score,
                    )
            await db.commit()
    except Exception as _ae:
        logger.error(
            "apply_review_and_publish: auto-approve failed",
            scan_run_id=scan_run_id,
            error=str(_ae),
        )

    # ---- AUTO-PUBLISH ----
    if not (cfg.get("auto_publish", False) and approved_ids):
        return

    from app.agents.publish_post.runner import run_publish_pipeline

    publish_mode = cfg.get("publish_mode", "auto")
    privacy = cfg.get("default_privacy_level", "SELF_ONLY")
    sched_time: datetime | None = None

    if publish_mode == "schedule":
        time_str = cfg.get("scheduled_publish_time")
        if time_str:
            try:
                tz = ZoneInfo(get_settings().TIMEZONE)
                now = datetime.now(tz)
                h, m = map(int, time_str.split(":"))
                sched_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if sched_time <= now:
                    sched_time += timedelta(days=1)
            except Exception:
                sched_time = None
        publish_mode = "manual"

    # Surface the Publishing stage to the unified pipeline status.
    if step_cb:
        await step_cb("publishing")

    publish_failures = 0
    for pid in approved_ids:
        try:
            res = await run_publish_pipeline(
                content_post_id=pid,
                mode=publish_mode,
                scheduled_time=sched_time,
                privacy_level=privacy,
                user_id=user_id,
            )
            if res.get("publish_status") == "failed" or res.get("error"):
                publish_failures += 1
                logger.error(
                    "apply_review_and_publish: auto-publish reported failure",
                    post_id=pid,
                    error=res.get("error"),
                )
            else:
                logger.info(
                    "apply_review_and_publish: auto-published",
                    post_id=pid,
                    publish_mode=publish_mode,
                )
        except Exception as _pe:
            publish_failures += 1
            logger.error(
                "apply_review_and_publish: auto-publish failed",
                post_id=pid,
                error=str(_pe),
            )

    # Any publish failure → mark the run PARTIAL and keep current_step so the
    # status bar highlights the failed Publishing stage.
    if publish_failures:
        async with async_session_factory() as db:
            row = (
                await db.execute(
                    select(ScanRun).where(ScanRun.id == uuid.UUID(scan_run_id))
                )
            ).scalar_one_or_none()
            if row:
                row.status = ScanStatus.PARTIAL
                if not row.error:
                    row.error = (
                        "Some posts could not be published. "
                        "Please retry from the board."
                    )
                row.current_step = "publishing"
                await db.commit()


def _should_generate_posts(state: TrendScanState) -> str:
    """Conditional router: proceed to post generation or end."""
    if state.get("generate_posts", False):
        return "generate_posts"
    return "end"


def build_trend_scan_graph(rate_limiter: RateLimiter) -> StateGraph:
    """Build and compile the LangGraph trend scanning graph.

    Pipeline:
        hackernews_scanner → collect_results → trend_analyzer → content_saver
        → persist_results → [conditional: generate_posts or END]
        → generate_posts → END

    Combined trend_analyzer merges analysis + report generation into a single LLM pass.
    When generate_posts=True in state, the pipeline continues with TikTok post generation.
    """
    hackernews_node = HackerNewsScannerNode(rate_limiter)

    graph = StateGraph(TrendScanState)

    # Add nodes
    graph.add_node("hackernews_scanner", hackernews_node)
    graph.add_node("collect_results", collect_results_node)
    graph.add_node("trend_analyzer", trend_analyzer_node)
    graph.add_node("content_saver", content_saver_node)
    graph.add_node("persist_results", persist_results_node)
    graph.add_node("generate_posts", generate_posts_node)

    # Linear pipeline up to persist_results
    graph.add_edge(START, "hackernews_scanner")
    graph.add_edge("hackernews_scanner", "collect_results")
    graph.add_edge("collect_results", "trend_analyzer")
    graph.add_edge("trend_analyzer", "content_saver")
    graph.add_edge("content_saver", "persist_results")

    # Conditional: generate posts or finish
    graph.add_conditional_edges(
        "persist_results",
        _should_generate_posts,
        {
            "generate_posts": "generate_posts",
            "end": END,
        },
    )
    graph.add_edge("generate_posts", END)

    return graph.compile()


async def generate_posts_node(state: TrendScanState) -> dict:
    """Run the post generation pipeline using analyzed trends from this scan.

    Invokes the PostGenAgent graph (strategy_alignment → content_generation →
    image_prompt_creation → image_generation → auto_review → output_packaging)
    and stores the result in state.
    """
    scan_run_id = state.get("scan_run_id")
    post_gen_options = state.get("post_gen_options", {})

    if not scan_run_id:
        logger.error("generate_posts: no scan_run_id")
        return {"post_gen_output": {}}

    # Retrieve the owning user from the scan run so content_posts.created_by
    # is populated and the NestJS gateway can filter posts by user.
    user_id: str | None = None
    async with async_session_factory() as db:
        row = await db.get(ScanRun, scan_run_id)
        if row and row.triggered_by:
            user_id = str(row.triggered_by)

    logger.info(
        "generate_posts: starting post generation pipeline",
        scan_run_id=scan_run_id,
        user_id=user_id,
        options=post_gen_options,
    )

    async def _step_cb(step: str) -> None:
        await _update_scan_step(scan_run_id, step)

    try:
        output = await run_post_generation(
            scan_run_id, post_gen_options, user_id=user_id, step_callback=_step_cb
        )

        total_posts = len(output.get("posts", []))
        logger.info(
            "generate_posts: completed",
            scan_run_id=scan_run_id,
            total_posts=total_posts,
        )

        # ---- REVIEW + PUBLISH HOOK ----
        pipeline_cfg = state.get("pipeline_config") or {}
        await apply_review_and_publish(
            scan_run_id, pipeline_cfg, user_id, step_cb=_step_cb
        )

        return {"post_gen_output": output}

    except Exception as e:
        logger.error("generate_posts: failed", scan_run_id=scan_run_id, error=str(e))
        return {
            "post_gen_output": {},
            "errors": [{"platform": "post_generator", "error": str(e)}],
        }


async def collect_results_node(state: TrendScanState) -> dict:
    """Merge and validate results from the scanner."""
    raw_results = state.get("raw_results", [])

    total_items = 0
    platforms_ok = []
    platforms_failed = {}

    for result in raw_results:
        if result["error"]:
            platforms_failed[result["platform"]] = result["error"]
        else:
            platforms_ok.append(result["platform"])
            total_items += len(result["items"])

    logger.info(
        "Collect results",
        total_items=total_items,
        platforms_ok=platforms_ok,
        platforms_failed=list(platforms_failed.keys()),
    )

    return {}


async def persist_results_node(state: TrendScanState) -> dict:
    """Write analyzed trends to the database."""
    scan_run_id = state.get("scan_run_id")
    analyzed = state.get("analyzed_trends", [])
    errors = state.get("errors", [])
    raw_results = state.get("raw_results", [])

    if not scan_run_id:
        logger.error("persist_results: no scan_run_id")
        return {}

    async with async_session_factory() as db:
        try:
            # Update ScanRun
            result = await db.execute(
                select(ScanRun).where(ScanRun.id == uuid.UUID(scan_run_id))
            )
            scan_run = result.scalar_one_or_none()

            if not scan_run:
                logger.error("persist_results: scan_run not found", scan_run_id=scan_run_id)
                return {}

            # Determine completed/failed platforms
            platforms_completed = []
            platforms_failed = {}
            for r in raw_results:
                if r["error"]:
                    platforms_failed[r["platform"]] = r["error"]
                else:
                    platforms_completed.append(r["platform"])

            scan_run.platforms_completed = platforms_completed
            scan_run.platforms_failed = platforms_failed
            scan_run.total_items_found = len(analyzed)
            scan_run.completed_at = datetime.now(timezone.utc)

            report_file_path = state.get("report_file_path", "")
            if report_file_path:
                scan_run.report_file_path = report_file_path

            if platforms_failed and not platforms_completed:
                scan_run.status = ScanStatus.FAILED
            elif platforms_failed:
                scan_run.status = ScanStatus.PARTIAL
            else:
                scan_run.status = ScanStatus.COMPLETED

            # A fatal analysis error (bad key / quota) means the trends are
            # unusable — surface it instead of reporting a clean COMPLETED. The
            # crawl itself succeeded, so keep it PARTIAL (retryable) rather than
            # hard-failing the scan.
            fatal_errors = [e for e in errors if e.get("fatal")]
            if fatal_errors:
                scan_run.error = classify_llm_error(fatal_errors[0].get("error", ""))[0]
                if not analyzed:
                    scan_run.status = ScanStatus.PARTIAL

            # Persist trend items
            for item in analyzed:
                trend = TrendItem(
                    scan_run_id=uuid.UUID(scan_run_id),
                    title=item.get("title", "")[:500],
                    description=(item.get("description") or "")[:5000],
                    content_body=item.get("content_body"),
                    source_url=item.get("source_url"),
                    platform=item.get("_platform", "hackernews").lower(),
                    tags=item.get("tags", []),
                    hashtags=item.get("hashtags", []),
                    views=item.get("views"),
                    likes=item.get("likes"),
                    comments_count=item.get("comments_count"),
                    shares=item.get("shares"),
                    trending_score=item.get("trending_score"),
                    thumbnail_url=item.get("thumbnail_url"),
                    video_url=item.get("video_url"),
                    image_urls=item.get("image_urls", []),
                    author_name=item.get("author_name"),
                    author_url=item.get("author_url"),
                    author_followers=item.get("author_followers"),
                    category=item.get("category"),
                    sentiment=item.get("sentiment"),
                    lifecycle=item.get("lifecycle"),
                    relevance_score=item.get("relevance_score"),
                    quality_score=item.get("quality_score"),
                    related_topics=item.get("related_topics", []),
                    engagement_prediction=item.get("engagement_prediction"),
                    source_type=_normalize_source_type(item.get("source_type")),
                    content_angles=item.get("content_angles", []),
                    key_data_points=item.get("key_data_points", []),
                    target_audience=item.get("target_audience", []),
                    cleaned_content=item.get("cleaned_content"),
                    is_promoted=item.get("_promoted", False),
                    dedup_key=item.get("dedup_key"),
                    cross_platform_ids=item.get("cross_platform_ids", []),
                    raw_data=item.get("raw_data"),
                    published_at=_parse_datetime(item.get("published_at")),
                )
                db.add(trend)

            await db.commit()
            logger.info(
                "persist_results: saved",
                scan_run_id=scan_run_id,
                items_saved=len(analyzed),
                status=scan_run.status.value,
            )

        except Exception as e:
            await db.rollback()
            logger.error("persist_results: failed", error=str(e))
            try:
                scan_run = (
                    await db.execute(
                        select(ScanRun).where(ScanRun.id == uuid.UUID(scan_run_id))
                    )
                ).scalar_one_or_none()
                if scan_run:
                    scan_run.status = ScanStatus.FAILED
                    scan_run.error = "An unexpected error occurred. Please try again later or contact your administrator for support."
                    scan_run.completed_at = datetime.now(timezone.utc)
                    await db.commit()
            except Exception:
                pass

    return {}


def _parse_datetime(value) -> datetime | None:
    """Parse various datetime formats."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


async def run_scan(scan_run_id: str, request: ScanRequest):
    """Execute the full trend scan pipeline (HackerNews → Technology domain)."""
    start_time = time.time()
    settings = get_settings()
    redis = None
    owner_id = None  # scan owner, for releasing the per-user concurrency slot

    try:
        # Update status to RUNNING
        async with async_session_factory() as db:
            result = await db.execute(
                select(ScanRun).where(ScanRun.id == uuid.UUID(scan_run_id))
            )
            scan_run = result.scalar_one_or_none()
            if scan_run:
                owner_id = scan_run.triggered_by
                scan_run.status = ScanStatus.RUNNING
                scan_run.langgraph_thread_id = str(uuid.uuid4())
                await db.commit()

        # Load pipeline config for this user to apply defaults
        pipeline_cfg: dict | None = None
        async with async_session_factory() as cfg_db:
            _scan = (
                await cfg_db.execute(
                    select(ScanRun).where(ScanRun.id == uuid.UUID(scan_run_id))
                )
            ).scalar_one_or_none()
            _owner = _scan.triggered_by if _scan else None
        if _owner:
            pipeline_cfg = await load_pipeline_cfg_for_owner(_owner)

        # Merge: explicitly-set request fields win; config fills gaps
        _explicitly_set = getattr(request.options, "model_fields_set", set())
        _cfg = pipeline_cfg or {}

        resolved_max_items = int(
            request.options.max_items_per_platform
            if "max_items_per_platform" in _explicitly_set
            else _cfg.get("_cfg_max_items", request.options.max_items_per_platform)
        )
        resolved_quality = int(
            getattr(request.options, "quality_threshold", 5)
            if "quality_threshold" in _explicitly_set
            else _cfg.get("_cfg_quality_threshold", getattr(request.options, "quality_threshold", 5))
        )
        resolved_comments = bool(
            request.options.include_comments
            if "include_comments" in _explicitly_set
            else _cfg.get("_cfg_include_comments", request.options.include_comments)
        )
        resolved_keywords = (
            (getattr(request.options, "keywords", None) if "keywords" in _explicitly_set else None)
            or _cfg.get("_cfg_keywords")
            or getattr(request.options, "keywords", None)
            or [
                "Artificial Intelligence & Machine Learning",
                "Software Engineering & Developer Tools",
                "Cloud Computing & Infrastructure",
                "Cybersecurity & Privacy",
                "Open Source Projects",
                "Startups & Tech Industry",
                "Hardware & Semiconductors",
                "Programming Languages & Frameworks",
                "Data Science & Analytics",
                "Robotics & Automation",
            ]
        )

        # Build and run the graph
        redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        rate_limiter = RateLimiter(redis)
        graph = build_trend_scan_graph(rate_limiter)

        # Build post generation options dict (merge config defaults with request)
        post_gen_opts: dict = {}
        if hasattr(request.options, "post_gen_options") and request.options.post_gen_options:
            post_gen_opts = {
                "num_posts": request.options.post_gen_options.num_posts,
                "formats": request.options.post_gen_options.formats,
            }
        if "post_gen_options" not in _explicitly_set:
            if not post_gen_opts.get("num_posts"):
                post_gen_opts["num_posts"] = _cfg.get("_cfg_num_posts", 3)
            if post_gen_opts.get("formats") is None:
                post_gen_opts["formats"] = _cfg.get("_cfg_allowed_formats")

        initial_state = TrendScanState(
            scan_run_id=scan_run_id,
            platforms=["hackernews"],
            options={
                "max_items_per_platform": resolved_max_items,
                "include_comments": resolved_comments,
                "quality_threshold": resolved_quality,
                "generate_posts": getattr(request.options, "generate_posts", False),
                "num_posts": post_gen_opts.get("num_posts", 3),
                "keywords": resolved_keywords,
            },
            raw_results=[],
            analyzed_trends=[],
            discarded_articles=[],
            trend_report_md="",
            analysis_meta={},
            content_file_paths=[],
            report_file_path="",
            generate_posts=getattr(request.options, "generate_posts", False),
            post_gen_options=post_gen_opts,
            post_gen_output={},
            pipeline_config=pipeline_cfg,
            errors=[],
        )

        # Stream events so we can update current_step as each node starts.
        _last_emitted_step: str | None = None
        async for event in graph.astream_events(initial_state, version="v2"):
            if event["event"] == "on_chain_start":
                node = event.get("metadata", {}).get("langgraph_node", "")
                step = _NODE_STEP_MAP.get(node)
                if step and step != _last_emitted_step:
                    _last_emitted_step = step
                    await _update_scan_step(scan_run_id, step)

        # Clear the step indicator once the pipeline finishes, unless a post-gen
        # error was saved — in that case keep current_step so the UI can highlight
        # the failed stage.
        async with async_session_factory() as _chk:
            _row = (
                await _chk.execute(select(ScanRun).where(ScanRun.id == uuid.UUID(scan_run_id)))
            ).scalar_one_or_none()
        if _row is None or not _row.error:
            await _update_scan_step(scan_run_id, "")

        # Update duration
        duration_ms = int((time.time() - start_time) * 1000)
        async with async_session_factory() as update_db:
            result = await update_db.execute(
                select(ScanRun).where(ScanRun.id == uuid.UUID(scan_run_id))
            )
            scan_run = result.scalar_one_or_none()
            if scan_run:
                scan_run.duration_ms = duration_ms
                await update_db.commit()

        logger.info("Scan completed", scan_run_id=scan_run_id, duration_ms=duration_ms)

    except Exception as e:
        logger.error("Scan failed", scan_run_id=scan_run_id, error=str(e))
        async with async_session_factory() as error_db:
            result = await error_db.execute(
                select(ScanRun).where(ScanRun.id == uuid.UUID(scan_run_id))
            )
            scan_run = result.scalar_one_or_none()
            if scan_run:
                scan_run.status = ScanStatus.FAILED
                scan_run.error = "An unexpected error occurred. Please try again later or contact your administrator for support."
                scan_run.completed_at = datetime.now(timezone.utc)
                scan_run.duration_ms = int((time.time() - start_time) * 1000)
                await error_db.commit()
    finally:
        # Release the per-user concurrency slot reserved at trigger time.
        if owner_id is not None:
            from app.core.concurrency import release_scan_slot

            rel_redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            try:
                await release_scan_slot(rel_redis, str(owner_id))
            finally:
                await rel_redis.aclose()
        if redis is not None:
            await redis.aclose()
