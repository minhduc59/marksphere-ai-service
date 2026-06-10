"""End-to-end tests for the scan-schedule → full-pipeline wiring.

Covers the three moving parts of the feature:

1. ``register_schedule`` / ``unregister_schedule`` against a real
   APScheduler ``AsyncIOScheduler`` — proves a cron job is actually created.
2. ``load_schedules`` startup reconciliation — registers active rows and
   prunes stale jobs (DB is authoritative).
3. ``run_scheduled_pipeline`` — the cron callback. Proves a fired schedule
   creates a ``PipelineRun`` owned by the schedule owner and starts the FULL
   pipeline (``run_pipeline`` with ``generate_posts=True``), not a scan only.

The DB and ``run_pipeline`` are mocked so the wiring is exercised without
Postgres/Redis/OpenAI/TikTok.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db.models import PipelineRun, ScanSchedule
from app.db.models.enums import Platform
from app.services import scan_scheduler

_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


# --------------------------------------------------------------------------- #
# Fakes for the DB session used inside run_scheduled_pipeline / load_schedules
# --------------------------------------------------------------------------- #
class _FakeResult:
    def __init__(self, payload):
        self._payload = payload

    def scalar_one_or_none(self):
        return self._payload

    def scalars(self):
        return self

    def all(self):
        return self._payload


class _FakeSession:
    """Minimal async session: serves one query payload, captures adds."""

    def __init__(self, payload):
        self._payload = payload
        self.added: list = []

    async def execute(self, _stmt):
        return _FakeResult(self._payload)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()


class _FakeFactory:
    """Stand-in for async_session_factory (an async context manager)."""

    def __init__(self, payload):
        self.session = _FakeSession(payload)

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_a):
        return False


def _make_schedule(*, owner=True, active=True, platforms=None):
    return ScanSchedule(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4() if owner else None,
        cron_expression="0 * * * *",
        platforms=["hackernews"] if platforms is None else platforms,
        is_active=active,
    )


# --------------------------------------------------------------------------- #
# 1. register / unregister against a real scheduler
# --------------------------------------------------------------------------- #
async def test_register_and_unregister_creates_real_cron_job():
    scheduler = AsyncIOScheduler(jobstores={"default": MemoryJobStore()})
    scheduler.start(paused=True)
    try:
        sid = str(uuid.uuid4())
        scan_scheduler.register_schedule(scheduler, sid, "*/5 * * * *")

        job = scheduler.get_job(f"scan_schedule:{sid}")
        assert job is not None
        assert list(job.args) == [sid]
        # The cron trigger has a computable next fire time.
        assert job.trigger is not None

        scan_scheduler.unregister_schedule(scheduler, sid)
        assert scheduler.get_job(f"scan_schedule:{sid}") is None
        # Idempotent: removing again does not raise.
        scan_scheduler.unregister_schedule(scheduler, sid)
    finally:
        scheduler.shutdown(wait=False)


async def test_register_invalid_cron_raises_valueerror():
    scheduler = AsyncIOScheduler(jobstores={"default": MemoryJobStore()})
    scheduler.start(paused=True)
    try:
        with pytest.raises(ValueError):
            scan_scheduler.register_schedule(scheduler, str(uuid.uuid4()), "not a cron")
    finally:
        scheduler.shutdown(wait=False)


# --------------------------------------------------------------------------- #
# 2. load_schedules reconciliation
# --------------------------------------------------------------------------- #
async def test_load_schedules_registers_active_and_prunes_stale():
    scheduler = AsyncIOScheduler(jobstores={"default": MemoryJobStore()})
    scheduler.start(paused=True)
    try:
        # A stale job from a previous run (RedisJobStore would persist this).
        stale_id = str(uuid.uuid4())
        scan_scheduler.register_schedule(scheduler, stale_id, "0 * * * *")

        active = _make_schedule()
        inactive = _make_schedule(active=False)

        with patch(
            "app.db.session.async_session_factory",
            _FakeFactory([active, inactive]),
        ):
            await scan_scheduler.load_schedules(scheduler)

        assert scheduler.get_job(f"scan_schedule:{active.id}") is not None
        # Inactive row is not registered.
        assert scheduler.get_job(f"scan_schedule:{inactive.id}") is None
        # Stale job (no matching active row) is pruned.
        assert scheduler.get_job(f"scan_schedule:{stale_id}") is None
    finally:
        scheduler.shutdown(wait=False)


# --------------------------------------------------------------------------- #
# 3. the cron callback starts the FULL pipeline
# --------------------------------------------------------------------------- #
async def test_run_scheduled_pipeline_starts_full_pipeline_with_owner():
    sched = _make_schedule()
    factory = _FakeFactory(sched)

    with (
        patch("app.db.session.async_session_factory", factory),
        patch(
            "app.agents.pipeline_runner.run_pipeline", new=AsyncMock()
        ) as run_pipeline,
    ):
        await scan_scheduler.run_scheduled_pipeline(str(sched.id))

    # run_pipeline was invoked exactly once...
    run_pipeline.assert_awaited_once()
    pipeline_run_id, request = run_pipeline.await_args.args

    # ...with a PipelineRun that was created and linked.
    created = [o for o in factory.session.added if isinstance(o, PipelineRun)]
    assert len(created) == 1
    pr = created[0]
    assert str(pr.id) == pipeline_run_id
    # Owner propagated so PipelineConfig / publish tokens resolve → can publish.
    assert pr.triggered_by == sched.owner_id
    assert pr.stage == "scanning"

    # Full pipeline: generate_posts on, platform mapped to the enum.
    assert request.options.generate_posts is True
    assert request.platforms == [Platform.HACKERNEWS]

    # Bookkeeping updated.
    assert sched.last_run_at is not None


async def test_run_scheduled_pipeline_skips_inactive_schedule():
    sched = _make_schedule(active=False)

    with (
        patch("app.db.session.async_session_factory", _FakeFactory(sched)),
        patch(
            "app.agents.pipeline_runner.run_pipeline", new=AsyncMock()
        ) as run_pipeline,
    ):
        await scan_scheduler.run_scheduled_pipeline(str(sched.id))

    run_pipeline.assert_not_awaited()


async def test_run_scheduled_pipeline_missing_schedule_is_noop():
    with (
        patch("app.db.session.async_session_factory", _FakeFactory(None)),
        patch(
            "app.agents.pipeline_runner.run_pipeline", new=AsyncMock()
        ) as run_pipeline,
    ):
        await scan_scheduler.run_scheduled_pipeline(str(uuid.uuid4()))

    run_pipeline.assert_not_awaited()


# --------------------------------------------------------------------------- #
# 4. scheduling near the present time (time-of-day, configured timezone)
# --------------------------------------------------------------------------- #
def test_daily_time_cron_fires_at_next_local_minute():
    """A "run daily at HH:MM" cron picked just before that time schedules its
    next run ~1 minute away — and in Asia/Ho_Chi_Minh, not UTC."""
    now = datetime(2026, 6, 7, 6, 59, 0, tzinfo=_TZ)
    trigger = CronTrigger.from_crontab("0 7 * * *", timezone=_TZ)

    nxt = trigger.get_next_fire_time(None, now)

    # Fires at 07:00 local, ~60s after "now".
    assert nxt == datetime(2026, 6, 7, 7, 0, 0, tzinfo=_TZ)
    assert (nxt - now) == timedelta(minutes=1)
    # Same instant is 00:00Z — proving the schedule is NOT interpreted as 07:00 UTC.
    assert nxt.astimezone(timezone.utc).hour == 0


async def test_running_scheduler_fires_callback_near_now():
    """End-to-end firing: a real *running* scheduler invokes the actual
    run_scheduled_pipeline callback at a near-future time and starts the full
    pipeline. The trigger fires ~1-2s out (sub-minute, just to exercise the real
    firing path quickly; production crons are minute-granular)."""
    sched = _make_schedule()
    factory = _FakeFactory(sched)
    fired = asyncio.Event()

    async def _fake_run_pipeline(_pipeline_run_id, _request):
        fired.set()

    scheduler = AsyncIOScheduler(
        jobstores={"default": MemoryJobStore()}, timezone=_TZ
    )
    scheduler.start()
    try:
        with (
            patch("app.db.session.async_session_factory", factory),
            patch(
                "app.agents.pipeline_runner.run_pipeline",
                new=AsyncMock(side_effect=_fake_run_pipeline),
            ) as run_pipeline,
        ):
            # Fire ~1.5s from now via a sub-minute interval trigger.
            scheduler.add_job(
                scan_scheduler.run_scheduled_pipeline,
                trigger="interval",
                seconds=1,
                args=[str(sched.id)],
                id=scan_scheduler._job_id(str(sched.id)),
                next_run_time=datetime.now(_TZ) + timedelta(milliseconds=1500),
            )
            await asyncio.wait_for(fired.wait(), timeout=10)

        run_pipeline.assert_awaited_once()
        _pipeline_run_id, request = run_pipeline.await_args.args
        assert request.options.generate_posts is True
    finally:
        scheduler.shutdown(wait=False)
