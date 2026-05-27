"""Internal API: trigger and query video processing tasks.

Called by the NestJS backend only — all endpoints require X-Internal-Api-Key.
"""
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.v1.deps import get_current_user_id, require_internal_auth
from app.db.models.video_task import VideoTask
from app.db.session import async_session_factory
from app.workers.job_queue import enqueue_video_task

logger = structlog.get_logger()
router = APIRouter()


@router.post(
    "/{task_id}/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_internal_auth)],
)
async def run_video_task(
    task_id: str,
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    """Enqueue a video processing job for the given task.

    The VideoTask row must already exist (created by the NestJS backend).
    Returns immediately — processing happens asynchronously in the arq worker.
    """
    task_uuid = _parse_uuid(task_id)

    async with async_session_factory() as db:
        result = await db.execute(
            select(VideoTask).where(
                VideoTask.id == task_uuid,
                VideoTask.user_id == user_id,
            )
        )
        task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"VideoTask {task_id} not found",
        )

    job_id = await enqueue_video_task(
        task_id=str(task.id),
        user_id=str(task.user_id),
        source_type=task.source_type,
        source_ref=task.source_ref,
        font_id=str(task.font_id) if task.font_id else "",
        caption_template_id=str(task.caption_template_id) if task.caption_template_id else "",
        max_clips=task.max_clips,
        caption_style=task.caption_style,
        aspect_ratio=task.aspect_ratio,
        crop_x=task.crop_x,
        crop_y=task.crop_y,
        reframe_mode=task.reframe_mode,
        add_subtitles=task.add_subtitles,
        font_family=task.font_family,
        font_size=task.font_size,
        font_color=task.font_color,
        caption_position=task.caption_position,
        start_time_s=task.start_time_s,
        end_time_s=task.end_time_s,
    )

    logger.info(
        "video_tasks: job enqueued",
        task_id=task_id,
        job_id=job_id,
    )
    return {"taskId": task_id, "jobId": job_id, "status": "queued"}


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid UUID: {value}",
        ) from exc
