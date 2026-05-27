import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.report import (
    ReportContentResponse,
    ReportListItem,
    ReportListResponse,
    ReportSummaryResponse,
)
from app.core.storage import get_storage
from app.db.models import ScanRun, ScanStatus
from app.dependencies import get_session

router = APIRouter()


@router.get(
    "",
    response_model=ReportListResponse,
    summary="List generated reports",
    description="Returns a paginated list of scan runs that have generated reports.",
)
async def list_reports(
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_session),
):
    query = (
        select(ScanRun)
        .where(ScanRun.report_file_path.isnot(None))
        .where(ScanRun.status.in_([ScanStatus.COMPLETED, ScanStatus.PARTIAL]))
        .order_by(desc(ScanRun.completed_at))
    )

    from sqlalchemy import func
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    query = query.offset((page - 1) * limit).limit(limit)
    result = await db.execute(query)
    scan_runs = result.scalars().all()

    items = [
        ReportListItem(
            scan_run_id=run.id,
            generated_at=run.completed_at or run.started_at,
            report_file_path=run.report_file_path,
            total_items_found=run.total_items_found,
            platforms_completed=run.platforms_completed or [],
        )
        for run in scan_runs
    ]

    return ReportListResponse(items=items, total=total)


@router.get(
    "/{scan_run_id}",
    response_model=ReportContentResponse,
    summary="Get full report",
    description="Returns the full Markdown report content for a given scan run.",
    responses={404: {"description": "Report not found"}},
)
async def get_report(
    scan_run_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
):
    result = await db.execute(
        select(ScanRun).where(ScanRun.id == scan_run_id)
    )
    scan_run = result.scalar_one_or_none()

    if not scan_run or not scan_run.report_file_path:
        raise HTTPException(status_code=404, detail="Report not found")

    storage = get_storage()
    report_key = scan_run.report_file_path

    if not await asyncio.to_thread(storage.exists, report_key):
        raise HTTPException(status_code=404, detail="Report file not found in storage")

    content = await asyncio.to_thread(storage.read_text, report_key)

    return ReportContentResponse(
        scan_run_id=scan_run.id,
        content=content,
        report_file_path=scan_run.report_file_path,
        generated_at=scan_run.completed_at or scan_run.started_at,
    )


@router.get(
    "/{scan_run_id}/summary",
    response_model=ReportSummaryResponse,
    summary="Get report summary",
    description="Returns a structured JSON summary with processed articles, discarded articles, and analysis meta.",
    responses={404: {"description": "Report not found"}},
)
async def get_report_summary(
    scan_run_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
):
    result = await db.execute(
        select(ScanRun).where(ScanRun.id == scan_run_id)
    )
    scan_run = result.scalar_one_or_none()

    if not scan_run or not scan_run.report_file_path:
        raise HTTPException(status_code=404, detail="Report not found")

    storage = get_storage()
    summary_key = scan_run.report_file_path.replace("_report.md", "_summary.json")

    if not await asyncio.to_thread(storage.exists, summary_key):
        raise HTTPException(status_code=404, detail="Report summary file not found")

    raw = await asyncio.to_thread(storage.read_text, summary_key)
    summary_data = json.loads(raw)

    return ReportSummaryResponse(**summary_data)
