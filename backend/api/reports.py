"""Report retrieval API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import ReportRepository, get_session_dependency
from backend.models.report import AnalysisReport, OverallRisk, ReportSummary

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


@router.get("", response_model=list[ReportSummary])
async def list_reports(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    risk: OverallRisk | None = Query(default=None, description="Filter by risk level"),
    session: AsyncSession = Depends(get_session_dependency),
) -> list[ReportSummary]:
    """
    List report summaries with pagination.

    Returns lightweight summaries suitable for list views.
    Use the individual report endpoint for full details.
    """
    repo = ReportRepository(session)
    return await repo.list_reports(limit=limit, offset=offset, risk_filter=risk)


@router.get("/character/{character_id}", response_model=list[AnalysisReport])
async def get_character_reports(
    character_id: int,
    limit: int = Query(default=10, ge=1, le=100),
    session: AsyncSession = Depends(get_session_dependency),
) -> list[AnalysisReport]:
    """
    Get all reports for a character, newest first.

    Useful for viewing analysis history over time.
    """
    repo = ReportRepository(session)
    return await repo.get_by_character_id(character_id, limit=limit)


@router.get("/character/{character_id}/latest", response_model=AnalysisReport)
async def get_character_latest_report(
    character_id: int,
    session: AsyncSession = Depends(get_session_dependency),
) -> AnalysisReport:
    """
    Get the most recent report for a character.

    Returns 404 if no reports exist for this character.
    """
    repo = ReportRepository(session)
    report = await repo.get_latest_by_character_id(character_id)

    if not report:
        raise HTTPException(
            status_code=404,
            detail=f"No reports found for character {character_id}",
        )

    return report


@router.get("/{report_id}", response_model=AnalysisReport)
async def get_report(
    report_id: UUID,
    session: AsyncSession = Depends(get_session_dependency),
) -> AnalysisReport:
    """
    Retrieve a specific report by ID.

    Returns the full analysis report including all flags and applicant data.
    """
    repo = ReportRepository(session)
    report = await repo.get_by_id(report_id)

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    return report


@router.delete("/{report_id}", status_code=204)
async def delete_report(
    report_id: UUID,
    session: AsyncSession = Depends(get_session_dependency),
) -> None:
    """
    Delete a report by ID.

    Returns 404 if report doesn't exist.
    """
    repo = ReportRepository(session)
    deleted = await repo.delete_by_id(report_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Report not found")
