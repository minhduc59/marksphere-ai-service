"""arq worker for video processing.

Start with:
    arq app.workers.video_worker.WorkerSettings

The worker consumes jobs from the 'video-processing' queue.
Each job runs the full Video Clipper Agent pipeline synchronously within
the worker process — no polling loop needed.
"""
from __future__ import annotations

import structlog
from arq.connections import RedisSettings

from app.config import get_settings

logger = structlog.get_logger()


async def process_video_task(
    ctx: dict,
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
) -> dict:
    """arq job function: run the Video Clipper pipeline for one task.

    All actual work is inside run_video_clipper; this function is just
    the arq entry point that routes the job to the LangGraph pipeline.
    """
    logger.info(
        "process_video_task: starting",
        task_id=task_id,
        source_type=source_type,
    )

    # Import here to avoid importing the entire agent stack at worker startup
    from app.agents.video_clipper.runner import run_video_clipper

    result = await run_video_clipper(
        task_id=task_id,
        user_id=user_id,
        source_type=source_type,
        source_ref=source_ref,
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

    logger.info(
        "process_video_task: done",
        task_id=task_id,
        clip_count=len(result.get("clip_ids", [])),
    )
    return result


def _redis_settings() -> RedisSettings:
    settings = get_settings()
    return RedisSettings.from_dsn(settings.REDIS_URL)


class WorkerSettings:
    """arq WorkerSettings for the video processing worker."""

    queue_name = "video-processing"
    redis_settings = _redis_settings()
    functions = [process_video_task]
    max_jobs = 2          # process up to 2 videos concurrently per worker instance
    job_timeout = 3600    # 1 hour max per job (long videos can take a while)
    max_tries = 1         # no auto-retry — video_clipper_node handles its own error state
