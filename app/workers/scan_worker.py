"""arq worker for trend scans (+ optional post generation).

Start with:
    arq app.workers.scan_worker.WorkerSettings

Consumes jobs from the 'scan-processing' queue. Each job runs the full trend
scan pipeline inside the worker process, OFF the API event loop. ``max_jobs``
bounds how many scans run system-wide at once, giving natural backpressure: it
caps concurrent HackerNews API pressure (so the global rate budget isn't
starved) and the number of live DB sessions. Enable via USE_ARQ_FOR_SCANS.
"""
from __future__ import annotations

import structlog
from arq.connections import RedisSettings

from app.config import get_settings

logger = structlog.get_logger()


async def process_scan_task(ctx: dict, scan_run_id: str, request_data: dict) -> dict:
    """arq job: run the trend scan pipeline for one ScanRun.

    ``request_data`` is a JSON dump of the original ScanRequest (only the
    explicitly-set fields, so model_fields_set is preserved on reconstruction,
    which run_scan relies on to merge per-user PipelineConfig defaults).
    """
    # Imported here so the worker process doesn't pull the full agent stack at
    # startup, only when a job actually runs.
    from app.agents.supervisor import run_scan
    from app.api.v1.schemas.scan import ScanRequest

    request = ScanRequest.model_validate(request_data)
    logger.info("process_scan_task: starting", scan_run_id=scan_run_id)
    await run_scan(scan_run_id, request)
    logger.info("process_scan_task: done", scan_run_id=scan_run_id)
    return {"scan_run_id": scan_run_id}


def _redis_settings() -> RedisSettings:
    settings = get_settings()
    return RedisSettings.from_dsn(settings.REDIS_URL)


class WorkerSettings:
    """arq WorkerSettings for the scan processing worker."""

    queue_name = "scan-processing"
    redis_settings = _redis_settings()
    functions = [process_scan_task]
    max_jobs = 4          # max concurrent scans system-wide per worker instance
    job_timeout = 1800    # 30 min per scan (analysis + optional post generation)
    max_tries = 1         # run_scan persists its own FAILED/PARTIAL state
