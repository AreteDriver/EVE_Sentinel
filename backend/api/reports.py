"""Report retrieval API endpoints."""

import io
import zipfile
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import ReportRepository, get_session_dependency
from backend.models.report import AnalysisReport, OverallRisk, ReportSummary
from backend.services import PDFGenerator


class BulkPDFRequest(BaseModel):
    """Request for bulk PDF export."""

    report_ids: list[UUID]

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


@router.get("/{report_id}/pdf")
async def get_report_pdf(
    report_id: UUID,
    session: AsyncSession = Depends(get_session_dependency),
) -> Response:
    """
    Download report as PDF.

    Returns the analysis report formatted as a professional PDF document.
    """
    repo = ReportRepository(session)
    report = await repo.get_by_id(report_id)

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    pdf_generator = PDFGenerator()
    pdf_content = pdf_generator.generate(report)
    filename = pdf_generator.generate_filename(report)

    return Response(
        content=pdf_content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/bulk-pdf")
async def get_bulk_pdf(
    request: BulkPDFRequest,
    session: AsyncSession = Depends(get_session_dependency),
) -> Response:
    """
    Download multiple reports as a ZIP file of PDFs.

    Takes a list of report IDs and returns a ZIP archive containing
    individual PDF files for each report.
    """
    if not request.report_ids:
        raise HTTPException(status_code=400, detail="No report IDs provided")

    if len(request.report_ids) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 reports per request")

    repo = ReportRepository(session)
    pdf_generator = PDFGenerator()

    # Create ZIP file in memory
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for report_id in request.report_ids:
            report = await repo.get_by_id(report_id)
            if report:
                pdf_content = pdf_generator.generate(report)
                filename = pdf_generator.generate_filename(report)
                zip_file.writestr(filename, pdf_content)

    zip_buffer.seek(0)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="sentinel_reports_{timestamp}.zip"',
        },
    )


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
