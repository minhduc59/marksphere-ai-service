"""APScheduler wiring for recurring scan schedules.

A ``ScanSchedule`` row stores a cron expression but does nothing on its own.
This module registers each active schedule as an APScheduler cron job whose
callback starts the full end-to-end pipeline (``run_pipeline``): scan → post
generation → publishing, with publishing governed by the owner's PipelineConfig.

Job callables go through ``RedisJobStore`` when Redis is available, so the
callback must be a top-level importable function taking serializable args — we
pass the schedule id as a string and re-load everything inside the callback.
"""

import uuid
from datetime import datetime, timezone

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = structlog.get_logger()

_JOB_PREFIX = "scan_schedule:"

# Set once in the FastAPI lifespan. Lets helpers without a Request (e.g. the
# pipeline-config PATCH handler) reach the scheduler.
_scheduler: AsyncIOScheduler | None = None


def set_scheduler(scheduler: AsyncIOScheduler | None) -> None:
    global _scheduler
    _scheduler = scheduler


def get_scheduler() -> AsyncIOScheduler | None:
    return _scheduler


def _job_id(schedule_id: str) -> str:
    return f"{_JOB_PREFIX}{schedule_id}"


async def run_scheduled_pipeline(schedule_id: str) -> None:
    """APScheduler callback: start the full pipeline for one schedule.

    Top-level + str arg keeps it RedisJobStore-serializable.
    """
    from sqlalchemy import select

    from app.agents.pipeline_runner import run_pipeline
    from app.api.v1.schemas.pipeline_run import PipelineRunRequest
    from app.api.v1.schemas.scan import ScanOptions
    from app.db.models import PipelineRun, ScanSchedule
    from app.db.models.enums import Platform, ScanStatus
    from app.db.session import async_session_factory

    async with async_session_factory() as db:
        sched = (
            await db.execute(
                select(ScanSchedule).where(ScanSchedule.id == uuid.UUID(schedule_id))
            )
        ).scalar_one_or_none()

        if sched is None or not sched.is_active:
            logger.warning(
                "scheduled pipeline: schedule missing or inactive",
                schedule_id=schedule_id,
            )
            return

        platforms: list[Platform] = []
        for p in sched.platforms or []:
            try:
                platforms.append(Platform(p))
            except ValueError:
                logger.warning(
                    "scheduled pipeline: unknown platform",
                    schedule_id=schedule_id,
                    platform=p,
                )
        if not platforms:
            platforms = [Platform.HACKERNEWS]

        owner_id = sched.owner_id
        if owner_id is None:
            logger.warning(
                "scheduled pipeline: schedule has no owner; publishing will be "
                "skipped (no PipelineConfig / publish tokens to resolve)",
                schedule_id=schedule_id,
            )

        pipeline_run = PipelineRun(
            status=ScanStatus.PENDING,
            stage="scanning",
            triggered_by=owner_id,
            triggered_type="scheduled",
        )
        db.add(pipeline_run)
        await db.commit()
        await db.refresh(pipeline_run)
        pipeline_run_id = str(pipeline_run.id)

        # Bookkeeping. next_run_at is read off the live APScheduler job.
        sched.last_run_at = datetime.now(timezone.utc)
        job = _scheduler.get_job(_job_id(schedule_id)) if _scheduler else None
        sched.next_run_at = getattr(job, "next_run_time", None)
        await db.commit()

    request = PipelineRunRequest(
        platforms=platforms,
        options=ScanOptions(generate_posts=True),
    )

    logger.info(
        "scheduled pipeline: starting",
        schedule_id=schedule_id,
        pipeline_run_id=pipeline_run_id,
        owner_id=str(owner_id) if owner_id else None,
    )

    # run_pipeline owns its own error handling and finalization.
    await run_pipeline(pipeline_run_id, request)


def register_schedule(
    scheduler: AsyncIOScheduler,
    schedule_id: str,
    cron_expression: str,
) -> None:
    """Add or replace the cron job for one schedule.

    Raises ``ValueError`` if the cron expression is invalid.
    """
    from zoneinfo import ZoneInfo

    from app.config import get_settings

    # Interpret the cron in the configured local timezone (e.g. a "0 7 * * *"
    # schedule means 07:00 Asia/Ho_Chi_Minh, not 07:00 UTC). Explicit here so a
    # RedisJobStore-serialized trigger keeps the right zone across restarts.
    tz = ZoneInfo(get_settings().TIMEZONE)
    trigger = CronTrigger.from_crontab(cron_expression, timezone=tz)
    scheduler.add_job(
        run_scheduled_pipeline,
        trigger=trigger,
        id=_job_id(schedule_id),
        args=[schedule_id],
        replace_existing=True,
    )
    logger.info(
        "registered scan schedule", schedule_id=schedule_id, cron=cron_expression
    )


def unregister_schedule(scheduler: AsyncIOScheduler, schedule_id: str) -> None:
    """Remove the cron job for one schedule. Idempotent."""
    try:
        scheduler.remove_job(_job_id(schedule_id))
        logger.info("unregistered scan schedule", schedule_id=schedule_id)
    except Exception:
        # JobLookupError when the job isn't present — nothing to do.
        pass


async def load_schedules(scheduler: AsyncIOScheduler) -> None:
    """Reconcile APScheduler jobs against the DB on startup (DB is authoritative).

    Registers/replaces a job for every active schedule and prunes any
    ``scan_schedule:*`` job whose row is gone or inactive (relevant with the
    persistent RedisJobStore across restarts).
    """
    from sqlalchemy import select

    from app.db.models import ScanSchedule
    from app.db.session import async_session_factory

    async with async_session_factory() as db:
        rows = (await db.execute(select(ScanSchedule))).scalars().all()

    active_ids: set[str] = set()
    for row in rows:
        sid = str(row.id)
        if not row.is_active:
            continue
        active_ids.add(sid)
        try:
            register_schedule(scheduler, sid, row.cron_expression)
        except ValueError as exc:
            logger.warning(
                "skipping schedule with invalid cron",
                schedule_id=sid,
                cron=row.cron_expression,
                error=str(exc),
            )

    for job in scheduler.get_jobs():
        if job.id.startswith(_JOB_PREFIX):
            sid = job.id[len(_JOB_PREFIX):]
            if sid not in active_ids:
                unregister_schedule(scheduler, sid)
