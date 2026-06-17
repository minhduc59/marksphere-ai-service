"""LangGraph node: orchestrates the full video clipping pipeline."""
from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import structlog
from sqlalchemy import select

from app.agents.video_clipper.state import VideoClipperState
from app.agents.video_clipper.steps import (
    caption,
    cut,
    download,
    persist,
    reframe,
    select as select_step,
    thumbnail,
    transcribe,
    upload,
)
from app.core.progress import publish_video_progress
from app.db.models.enums import VideoTaskStatus
from app.db.models.video_task import VideoTask
from app.db.session import async_session_factory
from app.utils.async_helpers import run_in_thread

logger = structlog.get_logger()


def _run_caption(
    framed_paths: list[str],
    task_temp_dir: str,
    selected_segments: list[dict],
    transcript_data: dict,
    state: VideoClipperState,
) -> list[str]:
    """Wrapper so caption.run's keyword-only args can be driven from state inside a thread."""
    return caption.run(
        framed_paths,
        task_temp_dir,
        selected_segments,
        transcript_data,
        font_family=state["font_family"],
        font_size=state["font_size"],
        font_color=state["font_color"],
        caption_style=state["caption_style"],
        caption_position=state["caption_position"],
    )


_STATUS_PROGRESS: dict[str, int] = {
    VideoTaskStatus.DOWNLOADING.value: 10,
    VideoTaskStatus.TRANSCRIBING.value: 30,
    VideoTaskStatus.UPLOADING.value: 75,
    VideoTaskStatus.COMPLETED.value: 100,
}


async def _update_task(task_id: str, status: str, progress: int, message: str = "") -> None:
    async with async_session_factory() as db:
        result = await db.execute(select(VideoTask).where(VideoTask.id == uuid.UUID(task_id)))
        task = result.scalar_one_or_none()
        if task:
            task.status = status
            task.progress = progress
            task.progress_message = message
            if status == VideoTaskStatus.DOWNLOADING.value:
                task.started_at = datetime.now(timezone.utc)
        await db.commit()


async def _set_state(task_id: str, status: str, message: str = "") -> None:
    progress = _STATUS_PROGRESS.get(status, 0)
    await _update_task(task_id, status, progress, message)
    await publish_video_progress(task_id, status, progress, message=message)


async def video_clipper_node(state: VideoClipperState) -> dict:
    """Single LangGraph node that runs the entire video clipping pipeline.

    Steps:
      1. Download / retrieve source video
      2. Transcribe with AssemblyAI
      3. LLM segment selection
      4. ffmpeg cut + 9:16 reframe
      5. ASS subtitle burn
      6. Cloudinary upload
      7. DB persist (VideoClip rows + task completion)
    """
    task_id = state["task_id"]
    user_id = state["user_id"]

    from app.config import get_settings
    settings = get_settings()
    task_temp_dir = str(Path(settings.VIDEO_TEMP_DIR) / task_id)
    Path(task_temp_dir).mkdir(parents=True, exist_ok=True)

    try:
        # ── Preparing: fetch the source video ───────────────────────────────
        await _set_state(task_id, VideoTaskStatus.DOWNLOADING.value, "Downloading video…")
        local_video_path = await run_in_thread(
            download.run,
            task_temp_dir,
            state["source_type"],
            state["source_ref"],
            state["start_time_s"],
            state["end_time_s"],
        )

        # ── Processing: transcribe + analyze + cut + reframe + caption ─────
        await _set_state(task_id, VideoTaskStatus.TRANSCRIBING.value, "Transcribing…")
        transcript_data = await run_in_thread(transcribe.run, local_video_path)

        selected_segments = await select_step.run(
            transcript_data,
            state["max_clips"],
            state["start_time_s"],
            state["end_time_s"],
        )

        raw_paths, framed_paths = await run_in_thread(
            cut.run,
            local_video_path,
            task_temp_dir,
            selected_segments,
            state["aspect_ratio"],
            state["crop_x"],
            state["crop_y"],
        )

        framed_paths = await run_in_thread(
            reframe.run,
            raw_paths,
            framed_paths,
            task_temp_dir,
            state["aspect_ratio"],
            state["reframe_mode"],
        )

        if state["add_subtitles"]:
            clip_local_paths = await run_in_thread(
                _run_caption,
                framed_paths,
                task_temp_dir,
                selected_segments,
                transcript_data,
                state,
            )
        else:
            logger.info("video_clipper_node: subtitles skipped", task_id=task_id)
            clip_local_paths = framed_paths

        thumbnails = await run_in_thread(
            thumbnail.run,
            clip_local_paths,
            selected_segments,
            task_temp_dir,
            task_id,
            user_id,
        )

        # ── Uploading: push clips + thumbnails to cloud storage ─────────────
        await _set_state(task_id, VideoTaskStatus.UPLOADING.value, "Uploading clips…")
        cloudinary_objects = await run_in_thread(
            upload.run, clip_local_paths, task_id, user_id
        )

        # ── Persist: create VideoClip rows and mark task completed ──────────
        clip_ids = await persist.run(
            task_id, selected_segments, cloudinary_objects, thumbnails
        )

        await publish_video_progress(
            task_id,
            VideoTaskStatus.COMPLETED.value,
            100,
            status="completed",
            message=f"{len(clip_ids)} clips ready for review",
        )
        logger.info("video_clipper_node: completed", task_id=task_id, clips=len(clip_ids))

        return {
            "task_temp_dir": task_temp_dir,
            "local_video_path": local_video_path,
            "transcript_data": transcript_data,
            "selected_segments": selected_segments,
            "clip_local_paths": clip_local_paths,
            "clip_cloudinary_objects": cloudinary_objects,
            "clip_ids": clip_ids,
            "errors": [],
        }

    except Exception as exc:
        error_msg = str(exc)
        logger.error("video_clipper_node: failed", task_id=task_id, error=error_msg)
        try:
            await publish_video_progress(task_id, "error", 0, status="error", message=error_msg)
            await _update_task(task_id, VideoTaskStatus.ERROR.value, 0, error_msg)
        except Exception:
            pass
        # Re-raise a clean error: some exceptions (e.g. yt-dlp DownloadError)
        # carry an unpicklable traceback object that breaks arq's result
        # serializer. `from None` drops the chain so the result serializes.
        raise RuntimeError(error_msg) from None

    finally:
        shutil.rmtree(task_temp_dir, ignore_errors=True)
        logger.info("video_clipper_node: temp dir cleaned up", task_id=task_id)
