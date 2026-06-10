"""Enqueue video processing jobs to the arq video-processing queue."""
from __future__ import annotations

import structlog
from arq import create_pool
from arq.connections import RedisSettings

from app.config import get_settings

logger = structlog.get_logger()

_QUEUE_NAME = "video-processing"
_SCAN_QUEUE_NAME = "scan-processing"


def _redis_settings() -> RedisSettings:
    settings = get_settings()
    # arq RedisSettings accepts a URL string directly
    return RedisSettings.from_dsn(settings.REDIS_URL)


async def enqueue_scan_task(scan_run_id: str, request_data: dict) -> str:
    """Enqueue a trend scan job onto the 'scan-processing' queue.

    ``request_data`` should be the ScanRequest dumped with exclude_unset=True so
    the worker can reconstruct it with model_fields_set intact. Returns the job ID.
    """
    pool = await create_pool(_redis_settings())
    job = await pool.enqueue_job(
        "process_scan_task",
        scan_run_id,
        request_data,
        _queue_name=_SCAN_QUEUE_NAME,
    )
    await pool.aclose()

    job_id = job.job_id if job else "unknown"
    logger.info("job_queue: enqueued scan", scan_run_id=scan_run_id, job_id=job_id)
    return job_id


async def enqueue_video_task(
    task_id: str,
    user_id: str,
    source_type: str,
    source_ref: str,
    font_id: str = "",
    caption_template_id: str = "",
    max_clips: int = 5,
    caption_style: str = "default",
    aspect_ratio: str = "9:16",
    crop_x: float = 0.5,
    crop_y: float = 0.5,
    reframe_mode: str = "static",
    add_subtitles: bool = True,
    font_family: str = "Inter",
    font_size: int = 40,
    font_color: str = "#FFFFFF",
    caption_position: str = "bottom",
    start_time_s: float = 0.0,
    end_time_s: float = 0.0,
) -> str:
    """Enqueue a video processing job. Returns the arq job ID."""
    pool = await create_pool(_redis_settings())
    job = await pool.enqueue_job(
        "process_video_task",
        task_id,
        user_id,
        source_type,
        source_ref,
        _queue_name=_QUEUE_NAME,
        font_id=font_id,
        caption_template_id=caption_template_id,
        max_clips=max_clips,
        caption_style=caption_style,
        aspect_ratio=aspect_ratio,
        crop_x=crop_x,
        crop_y=crop_y,
        reframe_mode=reframe_mode,
        add_subtitles=add_subtitles,
        font_family=font_family,
        font_size=font_size,
        font_color=font_color,
        caption_position=caption_position,
        start_time_s=start_time_s,
        end_time_s=end_time_s,
    )
    await pool.aclose()

    job_id = job.job_id if job else "unknown"
    logger.info(
        "job_queue: enqueued",
        task_id=task_id,
        job_id=job_id,
        queue=_QUEUE_NAME,
    )
    return job_id
