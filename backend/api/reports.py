"""Report retrieval API endpoints."""

import csv
import io
import zipfile
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import ReportRepository, get_session_dependency
from backend.models.report import AnalysisReport, OverallRisk, ReportSummary
from backend.rate_limit import LIMITS, limiter
from backend.services import PDFGenerator


def _report_to_csv_row(report: AnalysisReport) -> dict:
    """Convert a report to a CSV row dict."""
    red_flags = [f.title for f in report.flags if f.severity.value == "red"]
    yellow_flags = [f.title for f in report.flags if f.severity.value == "yellow"]
    green_flags = [f.title for f in report.flags if f.severity.value == "green"]

    return {
        "report_id": str(report.report_id),
        "character_id": report.character_id,
        "character_name": report.character_name,
        "overall_risk": report.overall_risk.value,
        "confidence": round(report.confidence * 100, 1),
        "red_flag_count": report.red_flag_count,
        "yellow_flag_count": report.yellow_flag_count,
        "green_flag_count": report.green_flag_count,
        "red_flags": "; ".join(red_flags),
        "yellow_flags": "; ".join(yellow_flags),
        "green_flags": "; ".join(green_flags),
        "recommendations": "; ".join(report.recommendations),
        "created_at": report.created_at.isoformat(),
        "requested_by": report.requested_by or "",
        "status": report.status.value,
    }


def _generate_csv(reports: list[AnalysisReport]) -> str:
    """Generate CSV content from a list of reports."""
    if not reports:
        return ""

    output = io.StringIO()
    fieldnames = [
        "report_id",
        "character_id",
        "character_name",
        "overall_risk",
        "confidence",
        "red_flag_count",
        "yellow_flag_count",
        "green_flag_count",
        "red_flags",
        "yellow_flags",
        "green_flags",
        "recommendations",
        "created_at",
        "requested_by",
        "status",
    ]

    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for report in reports:
        writer.writerow(_report_to_csv_row(report))

    return output.getvalue()


class BulkPDFRequest(BaseModel):
    """Request for bulk PDF export."""

    report_ids: list[UUID]


class CompareRequest(BaseModel):
    """Request for comparing two characters."""

    character_id_1: int | None = None
    character_id_2: int | None = None
    report_id_1: UUID | None = None
    report_id_2: UUID | None = None


class FlagDiff(BaseModel):
    """Difference in a specific flag between two reports."""

    code: str
    title: str
    severity: str
    in_report_1: bool
    in_report_2: bool


class CharacterComparison(BaseModel):
    """Comparison result between two characters."""

    # Character 1 info
    character_1_id: int
    character_1_name: str
    report_1_id: UUID
    report_1_risk: str
    report_1_confidence: float

    # Character 2 info
    character_2_id: int
    character_2_name: str
    report_2_id: UUID
    report_2_risk: str
    report_2_confidence: float

    # Comparison metrics
    risk_difference: str  # "same", "1_higher", "2_higher"
    confidence_difference: float

    # Flag comparisons
    shared_flags: list[FlagDiff]
    only_in_1: list[FlagDiff]
    only_in_2: list[FlagDiff]

    # Summary
    total_flags_1: int
    total_flags_2: int
    red_flags_1: int
    red_flags_2: int
    yellow_flags_1: int
    yellow_flags_2: int
    green_flags_1: int
    green_flags_2: int


router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


@router.get("", response_model=list[ReportSummary])
@limiter.limit(LIMITS["reports"])
async def list_reports(
    request: Request,
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
@limiter.limit(LIMITS["reports"])
async def get_character_reports(
    request: Request,
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
@limiter.limit(LIMITS["reports"])
async def get_character_latest_report(
    request: Request,
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
@limiter.limit(LIMITS["reports"])
async def get_report(
    request: Request,
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
@limiter.limit(LIMITS["pdf"])
async def get_report_pdf(
    request: Request,
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
@limiter.limit(LIMITS["bulk_pdf"])
async def get_bulk_pdf(
    request: Request,
    bulk_request: BulkPDFRequest,
    session: AsyncSession = Depends(get_session_dependency),
) -> Response:
    """
    Download multiple reports as a ZIP file of PDFs.

    Takes a list of report IDs and returns a ZIP archive containing
    individual PDF files for each report.
    """
    if not bulk_request.report_ids:
        raise HTTPException(status_code=400, detail="No report IDs provided")

    if len(bulk_request.report_ids) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 reports per request")

    repo = ReportRepository(session)
    pdf_generator = PDFGenerator()

    # Create ZIP file in memory
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for report_id in bulk_request.report_ids:
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


class BulkCSVRequest(BaseModel):
    """Request for bulk CSV export."""

    report_ids: list[UUID] | None = None
    risk_filter: OverallRisk | None = None
    limit: int = 100


@router.get("/{report_id}/csv")
@limiter.limit(LIMITS["reports"])
async def get_report_csv(
    request: Request,
    report_id: UUID,
    session: AsyncSession = Depends(get_session_dependency),
) -> Response:
    """
    Download a single report as CSV.

    Returns the report data in CSV format for spreadsheet analysis.
    """
    repo = ReportRepository(session)
    report = await repo.get_by_id(report_id)

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    csv_content = _generate_csv([report])
    filename = f"sentinel_{report.character_name.replace(' ', '_')}_{report.created_at.strftime('%Y%m%d')}.csv"

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/export/csv")
@limiter.limit(LIMITS["bulk_pdf"])
async def export_reports_csv(
    request: Request,
    csv_request: BulkCSVRequest,
    session: AsyncSession = Depends(get_session_dependency),
) -> Response:
    """
    Export multiple reports as CSV.

    Options:
    - Provide specific report_ids to export those reports
    - Use risk_filter to export all reports of a specific risk level
    - Use limit to control max number of reports (default 100, max 500)

    Returns a CSV file with all report data.
    """
    repo = ReportRepository(session)
    reports: list[AnalysisReport] = []

    if csv_request.report_ids:
        # Export specific reports
        if len(csv_request.report_ids) > 500:
            raise HTTPException(status_code=400, detail="Maximum 500 reports per export")

        for report_id in csv_request.report_ids:
            report = await repo.get_by_id(report_id)
            if report:
                reports.append(report)
    else:
        # Export by filter
        limit = min(csv_request.limit, 500)
        summaries = await repo.list_reports(
            limit=limit,
            risk_filter=csv_request.risk_filter,
        )

        # Fetch full reports
        for summary in summaries:
            report = await repo.get_by_id(summary.report_id)
            if report:
                reports.append(report)

    if not reports:
        raise HTTPException(status_code=404, detail="No reports found matching criteria")

    csv_content = _generate_csv(reports)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    filename = f"sentinel_export_{timestamp}.csv"

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get("/export/csv")
@limiter.limit(LIMITS["reports"])
async def export_all_reports_csv(
    request: Request,
    risk: OverallRisk | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session_dependency),
) -> Response:
    """
    Export reports as CSV via GET request.

    Simpler alternative to POST endpoint for direct browser downloads.

    Query params:
    - risk: Filter by risk level (RED, YELLOW, GREEN)
    - limit: Max reports to export (default 100, max 500)
    """
    repo = ReportRepository(session)

    summaries = await repo.list_reports(limit=limit, risk_filter=risk)

    if not summaries:
        raise HTTPException(status_code=404, detail="No reports found")

    # Fetch full reports
    reports: list[AnalysisReport] = []
    for summary in summaries:
        report = await repo.get_by_id(summary.report_id)
        if report:
            reports.append(report)

    csv_content = _generate_csv(reports)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    risk_suffix = f"_{risk.value.lower()}" if risk else ""
    filename = f"sentinel_export{risk_suffix}_{timestamp}.csv"

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.delete("/{report_id}", status_code=204)
@limiter.limit(LIMITS["admin"])
async def delete_report(
    request: Request,
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


class DashboardStats(BaseModel):
    """Dashboard statistics response."""

    total: int
    red: int
    yellow: int
    green: int
    reports_last_7_days: int
    avg_per_day: float
    time_series: list[dict]
    top_flags: list[dict]


def _get_risk_level(risk: OverallRisk) -> int:
    """Convert risk to numeric level for comparison."""
    if risk == OverallRisk.RED:
        return 3
    elif risk == OverallRisk.YELLOW:
        return 2
    elif risk == OverallRisk.GREEN:
        return 1
    return 0


def _compare_reports(report1: AnalysisReport, report2: AnalysisReport) -> CharacterComparison:
    """Compare two reports and generate comparison result."""
    # Get flags as sets of codes
    flags1 = {f.code: f for f in report1.flags}
    flags2 = {f.code: f for f in report2.flags}

    codes1 = set(flags1.keys())
    codes2 = set(flags2.keys())

    shared_codes = codes1 & codes2
    only_in_1_codes = codes1 - codes2
    only_in_2_codes = codes2 - codes1

    # Build flag diffs
    shared_flags = [
        FlagDiff(
            code=code,
            title=flags1[code].title,
            severity=flags1[code].severity.value,
            in_report_1=True,
            in_report_2=True,
        )
        for code in shared_codes
    ]

    only_in_1 = [
        FlagDiff(
            code=code,
            title=flags1[code].title,
            severity=flags1[code].severity.value,
            in_report_1=True,
            in_report_2=False,
        )
        for code in only_in_1_codes
    ]

    only_in_2 = [
        FlagDiff(
            code=code,
            title=flags2[code].title,
            severity=flags2[code].severity.value,
            in_report_1=False,
            in_report_2=True,
        )
        for code in only_in_2_codes
    ]

    # Determine risk difference
    level1 = _get_risk_level(report1.overall_risk)
    level2 = _get_risk_level(report2.overall_risk)

    if level1 == level2:
        risk_difference = "same"
    elif level1 > level2:
        risk_difference = "1_higher"
    else:
        risk_difference = "2_higher"

    return CharacterComparison(
        character_1_id=report1.character_id,
        character_1_name=report1.character_name,
        report_1_id=report1.report_id,
        report_1_risk=report1.overall_risk.value,
        report_1_confidence=report1.confidence,
        character_2_id=report2.character_id,
        character_2_name=report2.character_name,
        report_2_id=report2.report_id,
        report_2_risk=report2.overall_risk.value,
        report_2_confidence=report2.confidence,
        risk_difference=risk_difference,
        confidence_difference=round(report1.confidence - report2.confidence, 3),
        shared_flags=shared_flags,
        only_in_1=only_in_1,
        only_in_2=only_in_2,
        total_flags_1=len(report1.flags),
        total_flags_2=len(report2.flags),
        red_flags_1=report1.red_flag_count,
        red_flags_2=report2.red_flag_count,
        yellow_flags_1=report1.yellow_flag_count,
        yellow_flags_2=report2.yellow_flag_count,
        green_flags_1=report1.green_flag_count,
        green_flags_2=report2.green_flag_count,
    )


@router.post("/compare", response_model=CharacterComparison)
@limiter.limit(LIMITS["reports"])
async def compare_characters(
    request: Request,
    compare_request: CompareRequest,
    session: AsyncSession = Depends(get_session_dependency),
) -> CharacterComparison:
    """
    Compare two characters side by side.

    Provide either:
    - report_id_1 and report_id_2 to compare specific reports
    - character_id_1 and character_id_2 to compare latest reports for each

    Returns a detailed comparison including:
    - Risk level differences
    - Shared flags
    - Flags unique to each character
    - Flag count summaries
    """
    repo = ReportRepository(session)

    # Get report 1
    if compare_request.report_id_1:
        report1 = await repo.get_by_id(compare_request.report_id_1)
        if not report1:
            raise HTTPException(status_code=404, detail="Report 1 not found")
    elif compare_request.character_id_1:
        report1 = await repo.get_latest_by_character_id(compare_request.character_id_1)
        if not report1:
            raise HTTPException(
                status_code=404,
                detail=f"No reports found for character {compare_request.character_id_1}",
            )
    else:
        raise HTTPException(
            status_code=400,
            detail="Must provide either report_id_1 or character_id_1",
        )

    # Get report 2
    if compare_request.report_id_2:
        report2 = await repo.get_by_id(compare_request.report_id_2)
        if not report2:
            raise HTTPException(status_code=404, detail="Report 2 not found")
    elif compare_request.character_id_2:
        report2 = await repo.get_latest_by_character_id(compare_request.character_id_2)
        if not report2:
            raise HTTPException(
                status_code=404,
                detail=f"No reports found for character {compare_request.character_id_2}",
            )
    else:
        raise HTTPException(
            status_code=400,
            detail="Must provide either report_id_2 or character_id_2",
        )

    return _compare_reports(report1, report2)


@router.get("/compare/{report_id_1}/{report_id_2}", response_model=CharacterComparison)
@limiter.limit(LIMITS["reports"])
async def compare_reports_by_id(
    request: Request,
    report_id_1: UUID,
    report_id_2: UUID,
    session: AsyncSession = Depends(get_session_dependency),
) -> CharacterComparison:
    """
    Compare two reports by their IDs.

    Returns a detailed comparison including risk differences,
    shared flags, and flags unique to each character.
    """
    repo = ReportRepository(session)

    report1 = await repo.get_by_id(report_id_1)
    if not report1:
        raise HTTPException(status_code=404, detail="Report 1 not found")

    report2 = await repo.get_by_id(report_id_2)
    if not report2:
        raise HTTPException(status_code=404, detail="Report 2 not found")

    return _compare_reports(report1, report2)


@router.get("/stats/dashboard", response_model=DashboardStats)
@limiter.limit(LIMITS["reports"])
async def get_dashboard_stats(
    request: Request,
    days: int = Query(default=30, ge=7, le=90),
    session: AsyncSession = Depends(get_session_dependency),
) -> DashboardStats:
    """
    Get dashboard statistics for charts.

    Returns:
    - Total counts by risk level
    - Time series data for the last N days
    - Top flags across all reports
    - Recent activity metrics
    """
    repo = ReportRepository(session)

    # Get counts
    total = await repo.count_reports()
    red = await repo.count_reports(OverallRisk.RED)
    yellow = await repo.count_reports(OverallRisk.YELLOW)
    green = await repo.count_reports(OverallRisk.GREEN)

    # Get time series
    time_series = await repo.get_reports_by_date_range(days=days)

    # Get top flags
    top_flags = await repo.get_top_flags(limit=10)

    # Get recent activity
    activity = await repo.get_recent_activity(days=7)

    return DashboardStats(
        total=total,
        red=red,
        yellow=yellow,
        green=green,
        reports_last_7_days=activity["reports_last_7_days"],
        avg_per_day=activity["avg_per_day"],
        time_series=time_series,
        top_flags=top_flags,
    )
