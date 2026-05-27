"""Article-express pipeline orchestrator.

Creates a synthetic ScanRun + TrendItem from a single article URL, then
hands off to the existing post-generation pipeline. By keying everything
on `scan_run_id` we reuse all downstream code (post listing, status
polling, the WebSocket gateway, the LangGraph post-gen graph itself)
without modification.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone

import structlog

from app.agents.post_generator.runner import run_post_generation
from app.core.storage import get_storage
from app.db.models import (
    Platform,
    ScanRun,
    ScanStatus,
    TrendItem,
)
from app.db.session import async_session_factory
from app.services.article_processor import (
    ArticleFetchError,
    PaywallDetectedError,
    ReportBuildError,
    build_article_report,
    detect_paywall,
    fetch_article,
)

logger = structlog.get_logger()

ARTICLE_SOURCE_TYPE = "article_url"


async def create_scan_for_article(url: str, user_id: uuid.UUID) -> uuid.UUID:
    """Insert a PENDING ScanRun shell so the caller can return 202 immediately.

    Background processing flips this row through RUNNING → COMPLETED/FAILED.
    """
    async with async_session_factory() as db:
        scan = ScanRun(
            triggered_by=user_id,
            status=ScanStatus.PENDING,
            platforms_requested=["article"],
            source_type=ARTICLE_SOURCE_TYPE,
            source_url=url,
        )
        db.add(scan)
        await db.commit()
        await db.refresh(scan)
        logger.info(
            "article_pipeline: scan shell created",
            scan_run_id=str(scan.id),
            user_id=str(user_id),
            url=url,
        )
        return scan.id


async def _set_status(
    scan_run_id: uuid.UUID,
    status: ScanStatus,
    *,
    error: str | None = None,
    report_file_path: str | None = None,
    completed: bool = False,
    only_if_running: bool = False,
) -> None:
    async with async_session_factory() as db:
        scan = await db.get(ScanRun, scan_run_id)
        if scan is None:
            logger.warning("article_pipeline: scan vanished mid-run", scan_run_id=str(scan_run_id))
            return
        if only_if_running and scan.status != ScanStatus.RUNNING:
            return
        scan.status = status
        if error is not None:
            scan.error = error
        if report_file_path is not None:
            scan.report_file_path = report_file_path
        if completed and scan.completed_at is None:
            scan.completed_at = datetime.now(timezone.utc)
            if scan.started_at is not None:
                delta = scan.completed_at - scan.started_at
                scan.duration_ms = int(delta.total_seconds() * 1000)
        await db.commit()


async def _update_step(scan_run_id: uuid.UUID, step: str) -> None:
    try:
        async with async_session_factory() as db:
            scan = await db.get(ScanRun, scan_run_id)
            if scan:
                scan.current_step = step
                await db.commit()
    except Exception as exc:
        logger.warning("article_pipeline: step update failed", scan_run_id=str(scan_run_id), step=step, error=str(exc))


async def _persist_trend_item(
    scan_run_id: uuid.UUID,
    article: dict,
    report,
) -> None:
    """Materialize a single TrendItem so strategy_alignment can load it."""
    block = report.trends[0]
    async with async_session_factory() as db:
        ti = TrendItem(
            scan_run_id=scan_run_id,
            title=article["title"][:500],
            description=block.topic,
            content_body=article["body"],
            source_url=article["url"],
            platform=Platform.ARTICLE,
            sentiment=block.sentiment,
            lifecycle=block.lifecycle,
            engagement_prediction=block.engagement_prediction,
            quality_score=block.quality_score,
            relevance_score=8.0,  # express path: user explicitly chose this article
            content_angles=[a.model_dump() for a in block.tiktok_angles],
            key_data_points=block.key_data_points,
            target_audience=block.target_audience,
            cleaned_content=block.cleaned_content,
        )
        db.add(ti)
        await db.commit()


async def run_article_pipeline(
    scan_run_id: uuid.UUID,
    url: str,
    options: dict,
    user_id: uuid.UUID,
) -> None:
    """Background task: crawl → build report → persist → invoke post-gen.

    Errors are recorded on the ScanRun row (status=FAILED, error=<reason>)
    so the existing WebSocket gateway surfaces them to the frontend
    automatically via `scan.completed`.
    """
    start = time.time()
    logger.info(
        "article_pipeline: starting",
        scan_run_id=str(scan_run_id),
        url=url,
        user_id=str(user_id),
    )

    try:
        await _set_status(scan_run_id, ScanStatus.RUNNING)

        article = await fetch_article(url)
        if detect_paywall(article["body"]):
            raise PaywallDetectedError("Article appears to be paywalled or empty")

        report = await build_article_report(article)

        report_path = f"article-reports/{scan_run_id}.json"
        get_storage().write_text(
            report_path,
            json.dumps(report.model_dump(mode="json"), indent=2),
            content_type="application/json",
        )

        await _persist_trend_item(scan_run_id, article, report)
        await _set_status(scan_run_id, ScanStatus.RUNNING, report_file_path=report_path)

        duration_ms = int((time.time() - start) * 1000)
        logger.info(
            "article_pipeline: report ready, handing off to post-gen",
            scan_run_id=str(scan_run_id),
            duration_ms=duration_ms,
        )

        async def _step_cb(step: str) -> None:
            await _update_step(scan_run_id, step)

        await run_post_generation(str(scan_run_id), options, str(user_id), step_callback=_step_cb)
        await _set_status(scan_run_id, ScanStatus.COMPLETED, completed=True, only_if_running=True)

    except PaywallDetectedError as exc:
        logger.warning("article_pipeline: paywall", scan_run_id=str(scan_run_id), error=str(exc))
        await _set_status(
            scan_run_id,
            ScanStatus.FAILED,
            error="Unable to access the article — it may be behind a paywall. Try a different URL.",
            completed=True,
        )
    except ArticleFetchError as exc:
        logger.warning("article_pipeline: fetch failed", scan_run_id=str(scan_run_id), error=str(exc))
        await _set_status(
            scan_run_id,
            ScanStatus.FAILED,
            error="Failed to fetch the article. Please check the URL or try again later.",
            completed=True,
        )
    except ReportBuildError as exc:
        logger.error("article_pipeline: report build failed", scan_run_id=str(scan_run_id), error=str(exc))
        await _set_status(
            scan_run_id,
            ScanStatus.FAILED,
            error="Generating the report failed. Please try again later or contact your administrator for support.",
            completed=True,
        )
    except Exception as exc:  # noqa: BLE001 — last-resort safety net
        logger.exception("article_pipeline: unexpected failure", scan_run_id=str(scan_run_id))
        await _set_status(
            scan_run_id,
            ScanStatus.FAILED,
            error="An unexpected error occurred. Please try again later or contact your administrator for support.",
            completed=True,
        )
