import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.schemas.trend import (
    TrendDetail,
    TrendFilter,
    TrendListResponse,
    TrendSummary,
)
from app.db.models import Platform, Sentiment, TrendItem, TrendLifecycle
from app.dependencies import get_session

router = APIRouter()


@router.get(
    "",
    response_model=TrendListResponse,
    summary="List trends",
    description=(
        "Returns a paginated list of analyzed trends with optional filters.\n\n"
        "**Filter params:**\n"
        "- `platform` — `hackernews`\n"
        "- `category` — `tech` | `business` | `education` | `other` (focused on Technology domain)\n"
        "- `sentiment` — `bullish` | `neutral` | `bearish` | `controversial`\n"
        "- `lifecycle` — `emerging` | `rising` | `peaking` | `saturated` | `declining`\n"
        "- `min_score` — minimum relevance score (0–10)\n\n"
        "**Sort:** `relevance_score` (default) | `views` | `discovered_at`"
    ),
)
async def list_trends(
    platform: Platform | None = None,
    category: str | None = None,
    sentiment: Sentiment | None = None,
    lifecycle: TrendLifecycle | None = None,
    min_score: float | None = Query(default=None, ge=0, le=10, description="Minimum relevance score (0–10)"),
    sort_by: str = Query(default="relevance_score", pattern="^(relevance_score|views|discovered_at)$", description="Field to sort by"),
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_session),
):
    query = select(TrendItem)

    if platform:
        query = query.where(TrendItem.platform == platform)
    if category:
        query = query.where(TrendItem.category == category)
    if sentiment:
        query = query.where(TrendItem.sentiment == sentiment)
    if lifecycle:
        query = query.where(TrendItem.lifecycle == lifecycle)
    if min_score is not None:
        query = query.where(TrendItem.relevance_score >= min_score)

    # Count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Sort
    sort_column = getattr(TrendItem, sort_by, TrendItem.relevance_score)
    query = query.order_by(desc(sort_column))

    # Paginate
    query = query.offset((page - 1) * limit).limit(limit)

    result = await db.execute(query)
    items = result.scalars().all()

    return TrendListResponse(
        items=[TrendSummary.model_validate(item) for item in items],
        total=total,
        page=page,
        limit=limit,
    )


@router.get(
    "/top",
    response_model=list[TrendSummary],
    summary="Top trends by timeframe",
    description=(
        "Returns the highest-scoring trends within a time window, ordered by relevance score.\n\n"
        "**Timeframe:** `24h` (default) | `7d` | `30d`"
    ),
)
async def get_top_trends(
    limit: int = Query(default=20, ge=1, le=100, description="Max results to return"),
    timeframe: str = Query(default="24h", pattern="^(24h|7d|30d)$", description="Time window: 24h, 7d, or 30d"),
    db: AsyncSession = Depends(get_session),
):
    hours_map = {"24h": 24, "7d": 168, "30d": 720}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_map[timeframe])

    query = (
        select(TrendItem)
        .where(TrendItem.discovered_at >= cutoff)
        .order_by(desc(TrendItem.relevance_score))
        .limit(limit)
    )

    result = await db.execute(query)
    items = result.scalars().all()
    return [TrendSummary.model_validate(item) for item in items]


@router.get(
    "/{trend_id}",
    response_model=TrendDetail,
    summary="Get trend detail",
    description=(
        "Returns full detail for a single trend item including:\n"
        "- Content body, video/image URLs\n"
        "- Author info and engagement metrics\n"
        "- AI-generated category, sentiment, lifecycle, related topics\n"
        "- Top comments (if collected)\n"
        "- Raw platform data"
    ),
    responses={
        200: {"description": "Trend detail"},
        404: {"description": "Trend not found"},
    },
)
async def get_trend_detail(
    trend_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
):
    query = (
        select(TrendItem)
        .options(selectinload(TrendItem.comments))
        .where(TrendItem.id == trend_id)
    )
    result = await db.execute(query)
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Trend not found")

    return TrendDetail.model_validate(item)
