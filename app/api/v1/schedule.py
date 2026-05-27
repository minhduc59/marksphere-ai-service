from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.schedule import ScheduleRequest, ScheduleResponse
from app.db.models import ScanSchedule
from app.dependencies import get_session

router = APIRouter()


@router.post(
    "",
    status_code=201,
    response_model=ScheduleResponse,
    summary="Create a scheduled scan",
    description=(
        "Create a recurring scan schedule using a cron expression.\n\n"
        "**Cron examples:**\n"
        "- `0 */6 * * *` — every 6 hours\n"
        "- `0 9 * * *` — daily at 9am\n"
        "- `0 * * * *` — every hour\n\n"
        "Set `is_active: false` to create a paused schedule."
    ),
    responses={
        201: {"description": "Schedule created"},
        422: {"description": "Invalid cron expression or platforms"},
    },
)
async def create_schedule(
    request: ScheduleRequest,
    db: AsyncSession = Depends(get_session),
):
    schedule = ScanSchedule(
        cron_expression=request.cron_expression,
        platforms=[p.value for p in request.platforms],
        is_active=request.is_active,
    )
    db.add(schedule)
    await db.flush()
    return ScheduleResponse.model_validate(schedule)


@router.get(
    "",
    response_model=list[ScheduleResponse],
    summary="List scheduled scans",
    description="Returns all scan schedules (active and inactive).",
)
async def list_schedules(
    db: AsyncSession = Depends(get_session),
):
    result = await db.execute(select(ScanSchedule))
    schedules = result.scalars().all()
    return [ScheduleResponse.model_validate(s) for s in schedules]
