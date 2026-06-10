"""Watchdog that recovers scan / pipeline runs stuck in a non-terminal state.

``run_scan`` is launched as a FastAPI ``BackgroundTask``; if that task crashes,
hangs, or the service restarts mid-run, its ``scan_runs`` / ``pipeline_runs`` row
is left ``pending`` / ``running`` forever and keeps blocking new runs in the UI.
This module marks such rows ``failed`` so the system self-heals.
"""

from datetime import datetime, timedelta, timezone
from typing import TypeVar

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PipelineRun, ScanRun
from app.db.models.enums import ScanStatus
from app.db.session import async_session_factory

logger = structlog.get_logger()

# Both run tables share the columns the watchdog touches; constrain to them so
# attribute access (status / started_at / ...) type-checks per concrete model.
_RunModel = TypeVar("_RunModel", ScanRun, PipelineRun)

_ACTIVE_STATUSES = (ScanStatus.PENDING, ScanStatus.RUNNING)
# duration_ms is an INTEGER (int32) column; a run orphaned for weeks overflows
# it, so cap the recorded duration rather than crash the sweep.
_INT32_MAX = 2_147_483_647
_STALE_ERROR = (
    "Run exceeded the maximum runtime or was interrupted by a service restart, "
    "and was automatically marked as failed."
)


async def _fail_stale(
    db: AsyncSession,
    model: type[_RunModel],
    now: datetime,
    cutoff: datetime | None,
) -> int:
    """Mark all stale rows of ``model`` as failed. Returns the count."""
    stmt = select(model).where(model.status.in_(_ACTIVE_STATUSES))
    if cutoff is not None:
        stmt = stmt.where(model.started_at < cutoff)
    rows = (await db.execute(stmt)).scalars().all()

    for row in rows:
        row.status = ScanStatus.FAILED
        row.completed_at = now
        started = row.started_at
        if started is not None:
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            elapsed_ms = int((now - started).total_seconds() * 1000)
            row.duration_ms = min(elapsed_ms, _INT32_MAX)
        if not row.error:
            row.error = _STALE_ERROR
    return len(rows)


async def recover_stale_runs(max_age_minutes: int | None = None) -> int:
    """Auto-fail scan / pipeline runs stuck in a non-terminal state.

    Args:
        max_age_minutes: Only fail rows older than this. When ``None`` or ``0``,
            every non-terminal row is failed — startup-sweep semantics, since a
            background task cannot survive the process restart that just happened.

    Returns:
        Total number of rows recovered.
    """
    now = datetime.now(timezone.utc)
    cutoff = (
        now - timedelta(minutes=max_age_minutes)
        if max_age_minutes
        else None
    )

    async with async_session_factory() as db:
        scans = await _fail_stale(db, ScanRun, now, cutoff)
        pipelines = await _fail_stale(db, PipelineRun, now, cutoff)
        if scans or pipelines:
            await db.commit()

    if scans or pipelines:
        logger.info("Recovered stale runs", scans=scans, pipelines=pipelines)
    return scans + pipelines
