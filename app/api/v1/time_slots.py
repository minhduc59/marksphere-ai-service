"""EngagementTimeSlot CRUD endpoints.

Users manage the time slots that the golden-hour calculator uses to pick
the next auto-publish slot. The schema is shared across users — these
endpoints are gated on `require_internal_auth` only (no per-user filter).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.v1.deps import require_internal_auth
from app.api.v1.schemas.time_slot import (
    TimeSlotCreate,
    TimeSlotListResponse,
    TimeSlotResponse,
    TimeSlotUpdate,
)
from app.db.models.engagement_time_slot import EngagementTimeSlot
from app.db.session import async_session_factory

router = APIRouter()


@router.get(
    "",
    response_model=TimeSlotListResponse,
    summary="List engagement time slots",
)
async def list_time_slots(
    platform: str | None = Query(None, description="Filter by platform"),
    _: None = Depends(require_internal_auth),
):
    async with async_session_factory() as db:
        stmt = select(EngagementTimeSlot).order_by(
            EngagementTimeSlot.weighted_score.desc(),
            EngagementTimeSlot.slot_index.asc(),
        )
        if platform:
            stmt = stmt.where(EngagementTimeSlot.platform == platform)
        result = await db.execute(stmt)
        items = result.scalars().all()

    return TimeSlotListResponse(
        items=[TimeSlotResponse.model_validate(item) for item in items]
    )


@router.post(
    "",
    response_model=TimeSlotResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an engagement time slot",
)
async def create_time_slot(
    body: TimeSlotCreate,
    _: None = Depends(require_internal_auth),
):
    async with async_session_factory() as db:
        slot = EngagementTimeSlot(**body.model_dump())
        db.add(slot)
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Time slot already exists for platform={body.platform} slot_index={body.slot_index}",
            ) from exc
        await db.refresh(slot)

    return TimeSlotResponse.model_validate(slot)


@router.patch(
    "/{slot_id}",
    response_model=TimeSlotResponse,
    summary="Update an engagement time slot",
)
async def update_time_slot(
    slot_id: str,
    body: TimeSlotUpdate,
    _: None = Depends(require_internal_auth),
):
    try:
        slot_uuid = uuid.UUID(slot_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid slot id") from exc

    async with async_session_factory() as db:
        slot = await db.get(EngagementTimeSlot, slot_uuid)
        if not slot:
            raise HTTPException(status_code=404, detail="Time slot not found")

        updates = body.model_dump(exclude_unset=True)
        for key, value in updates.items():
            setattr(slot, key, value)

        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Update would create a duplicate (platform, slot_index)",
            ) from exc
        await db.refresh(slot)

    return TimeSlotResponse.model_validate(slot)


@router.delete(
    "/{slot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an engagement time slot",
)
async def delete_time_slot(
    slot_id: str,
    _: None = Depends(require_internal_auth),
):
    try:
        slot_uuid = uuid.UUID(slot_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid slot id") from exc

    async with async_session_factory() as db:
        slot = await db.get(EngagementTimeSlot, slot_uuid)
        if not slot:
            raise HTTPException(status_code=404, detail="Time slot not found")
        await db.delete(slot)
        await db.commit()
