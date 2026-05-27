"""Internal API: list, delete, duplicate video clips for the Clips Library page.

Called only by the NestJS backend gateway (X-Internal-Api-Key + X-User-Id).
The PATCH /review endpoint already exists on the NestJS side; this module
adds the cross-task listing + per-clip CRUD that the new Library page needs.
"""
from __future__ import annotations

import uuid
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, select

from app.api.v1.deps import get_current_user_id, require_internal_auth
from app.core.storage import get_cloudinary_storage
from app.db.models.video_clip import VideoClip
from app.db.models.video_task import VideoTask
from app.db.session import async_session_factory

logger = structlog.get_logger()
router = APIRouter()


SortField = Literal["created_at", "duration", "status"]
SortOrder = Literal["asc", "desc"]
ClipStatus = Literal["draft", "approved", "rejected", "published", "failed"]


def _serialize(clip: VideoClip, task: VideoTask | None) -> dict:
    return {
        "id": str(clip.id),
        "taskId": str(clip.task_id),
        "clipIndex": clip.clip_index,
        "title": clip.title,
        "storageUrl": clip.storage_url,
        "storagePublicId": clip.storage_public_id,
        "thumbnailUrl": clip.thumbnail_url,
        "thumbnailPublicId": clip.thumbnail_public_id,
        "durationSeconds": clip.duration_seconds,
        "startMs": clip.start_ms,
        "endMs": clip.end_ms,
        "transcriptSegment": clip.transcript_segment,
        "llmScore": clip.llm_score,
        "llmRationale": clip.llm_rationale,
        "hookScore": clip.hook_score,
        "engagementScore": clip.engagement_score,
        "status": clip.status,
        "feedback": clip.feedback,
        "createdAt": clip.created_at.isoformat() if clip.created_at else None,
        "updatedAt": clip.updated_at.isoformat() if clip.updated_at else None,
        "sourceType": task.source_type if task else None,
        "sourceRef": task.source_ref if task else None,
    }


@router.get(
    "",
    dependencies=[Depends(require_internal_auth)],
)
async def list_video_clips(
    user_id: uuid.UUID = Depends(get_current_user_id),
    status_filter: ClipStatus | None = Query(default=None, alias="status"),
    task_id: str | None = Query(default=None),
    sort: SortField = Query(default="created_at"),
    order: SortOrder = Query(default="desc"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """List clips owned by the current user, joined with their source task."""
    task_uuid: uuid.UUID | None = None
    if task_id:
        try:
            task_uuid = uuid.UUID(task_id)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid task_id") from exc

    sort_column = {
        "created_at": VideoClip.created_at,
        "duration": VideoClip.duration_seconds,
        "status": VideoClip.status,
    }[sort]
    sort_expr = sort_column if order == "asc" else desc(sort_column)

    async with async_session_factory() as db:
        # Always scope to the caller's tasks
        base = (
            select(VideoClip, VideoTask)
            .join(VideoTask, VideoClip.task_id == VideoTask.id)
            .where(VideoTask.user_id == user_id)
        )
        if status_filter:
            base = base.where(VideoClip.status == status_filter)
        if task_uuid:
            base = base.where(VideoClip.task_id == task_uuid)

        total_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(total_q)).scalar_one()

        rows = (
            await db.execute(base.order_by(sort_expr).limit(limit).offset(offset))
        ).all()
        items = [_serialize(clip, task) for clip, task in rows]

    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.delete(
    "/{clip_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_internal_auth)],
)
async def delete_video_clip(
    clip_id: str,
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> None:
    """Hard-delete a clip row and its Cloudinary assets (video + poster)."""
    clip_uuid = _parse_uuid(clip_id)

    async with async_session_factory() as db:
        row = (
            await db.execute(
                select(VideoClip, VideoTask)
                .join(VideoTask, VideoClip.task_id == VideoTask.id)
                .where(VideoClip.id == clip_uuid, VideoTask.user_id == user_id)
            )
        ).first()
        if not row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Clip {clip_id} not found")

        clip, _ = row
        public_id = clip.storage_public_id
        thumbnail_public_id = clip.thumbnail_public_id

        await db.delete(clip)
        await db.commit()

    # Best-effort Cloudinary cleanup; never fail the request over this.
    storage = get_cloudinary_storage()
    for key in (public_id, thumbnail_public_id):
        if not key:
            continue
        try:
            storage.delete(key)
        except Exception as exc:
            logger.warning("video_clips: cloudinary cleanup failed", key=key, error=str(exc))


@router.post(
    "/{clip_id}/duplicate",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_internal_auth)],
)
async def duplicate_video_clip(
    clip_id: str,
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    """Clone a clip's DB row (reusing the existing Cloudinary URLs).

    The new row is reset to `draft` status, unlinked from any content/published
    post, and ready for review again. No pipeline rerun.
    """
    clip_uuid = _parse_uuid(clip_id)

    async with async_session_factory() as db:
        row = (
            await db.execute(
                select(VideoClip, VideoTask)
                .join(VideoTask, VideoClip.task_id == VideoTask.id)
                .where(VideoClip.id == clip_uuid, VideoTask.user_id == user_id)
            )
        ).first()
        if not row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Clip {clip_id} not found")

        original, task = row
        clone = VideoClip(
            task_id=original.task_id,
            clip_index=original.clip_index,
            storage_url=original.storage_url,
            storage_public_id=original.storage_public_id,
            thumbnail_url=original.thumbnail_url,
            thumbnail_public_id=original.thumbnail_public_id,
            title=original.title,
            duration_seconds=original.duration_seconds,
            start_ms=original.start_ms,
            end_ms=original.end_ms,
            transcript_segment=original.transcript_segment,
            llm_score=original.llm_score,
            llm_rationale=original.llm_rationale,
            hook_score=original.hook_score,
            engagement_score=original.engagement_score,
            status="draft",
            # content_post_id / published_post_id intentionally left null
        )
        db.add(clone)
        await db.flush()
        await db.commit()

        # Re-read to capture server defaults (created_at)
        await db.refresh(clone)
        return _serialize(clone, task)


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid UUID: {value}") from exc
