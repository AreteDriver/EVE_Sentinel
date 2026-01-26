"""Report retrieval API endpoints."""

import csv
import io
import zipfile
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import AnnotationRepository, ReportRepository, get_session_dependency
from backend.database.repository import Annotation
from backend.models.report import AnalysisReport, OverallRisk, ReportSummary
from backend.rate_limit import LIMITS, limiter
from backend.services import PDFGenerator


def _report_to_csv_row(report: AnalysisReport) -> dict:
    """Convert a report to a CSV row dict."""
    red_flags = [f.reason for f in report.flags if f.severity.value == "red"]
    yellow_flags = [f.reason for f in report.flags if f.severity.value == "yellow"]
    green_flags = [f.reason for f in report.flags if f.severity.value == "green"]

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


class CharacterMetrics(BaseModel):
    """Detailed character metrics for comparison."""

    character_age_days: int | None = None
    security_status: float | None = None
    kills_total: int = 0
    kills_90d: int = 0
    deaths_total: int = 0
    solo_kills: int = 0
    awox_kills: int = 0
    isk_destroyed: float = 0.0
    isk_lost: float = 0.0
    danger_ratio: float | None = None
    gang_ratio: float | None = None
    corp_count: int = 0
    recent_corp_changes: int = 0  # Last 6 months
    avg_corp_tenure_days: float | None = None
    primary_timezone: str | None = None
    activity_trend: str | None = None


class CorpHistoryDiff(BaseModel):
    """Corporation history comparison entry."""

    corp_id: int
    corp_name: str
    in_char_1: bool
    in_char_2: bool
    char_1_joined: str | None = None
    char_2_joined: str | None = None


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

    # Detailed metrics
    metrics_1: CharacterMetrics | None = None
    metrics_2: CharacterMetrics | None = None

    # Corp history comparison
    shared_corps: list[CorpHistoryDiff] = Field(default_factory=list)
    unique_corps_1: list[CorpHistoryDiff] = Field(default_factory=list)
    unique_corps_2: list[CorpHistoryDiff] = Field(default_factory=list)


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


def _extract_metrics(report: AnalysisReport) -> CharacterMetrics | None:
    """Extract detailed metrics from report's applicant data."""
    if not report.applicant_data:
        return None

    app = report.applicant_data
    kb = app.killboard
    activity = app.activity

    # Calculate recent corp changes (last 6 months)
    recent_corp_changes = 0
    avg_tenure = None
    if app.corp_history:
        six_months_ago = datetime.now(UTC) - timedelta(days=180)
        for entry in app.corp_history:
            if entry.joined_at and entry.joined_at > six_months_ago:
                recent_corp_changes += 1

        # Calculate average tenure
        tenures = []
        for entry in app.corp_history:
            if entry.tenure_days is not None:
                tenures.append(entry.tenure_days)
        if tenures:
            avg_tenure = sum(tenures) / len(tenures)

    return CharacterMetrics(
        character_age_days=app.character_age_days,
        security_status=round(app.security_status, 2) if app.security_status else None,
        kills_total=kb.kills_total,
        kills_90d=kb.kills_90d,
        deaths_total=kb.deaths_total,
        solo_kills=kb.solo_kills,
        awox_kills=kb.awox_kills,
        isk_destroyed=kb.isk_destroyed,
        isk_lost=kb.isk_lost,
        danger_ratio=kb.danger_ratio,
        gang_ratio=kb.gang_ratio,
        corp_count=len(app.corp_history),
        recent_corp_changes=recent_corp_changes,
        avg_corp_tenure_days=round(avg_tenure, 1) if avg_tenure else None,
        primary_timezone=activity.primary_timezone,
        activity_trend=activity.activity_trend,
    )


def _compare_corp_history(
    report1: AnalysisReport, report2: AnalysisReport
) -> tuple[list[CorpHistoryDiff], list[CorpHistoryDiff], list[CorpHistoryDiff]]:
    """Compare corporation histories between two reports."""
    shared = []
    unique_1 = []
    unique_2 = []

    if not report1.applicant_data or not report2.applicant_data:
        return shared, unique_1, unique_2

    # Build corp sets
    corps1 = {
        entry.corp_id: entry for entry in report1.applicant_data.corp_history
    }
    corps2 = {
        entry.corp_id: entry for entry in report2.applicant_data.corp_history
    }

    all_corp_ids = set(corps1.keys()) | set(corps2.keys())

    for corp_id in all_corp_ids:
        entry1 = corps1.get(corp_id)
        entry2 = corps2.get(corp_id)

        in_1 = entry1 is not None
        in_2 = entry2 is not None

        corp_name = entry1.corp_name if entry1 else (entry2.corp_name if entry2 else "Unknown")

        diff = CorpHistoryDiff(
            corp_id=corp_id,
            corp_name=corp_name,
            in_char_1=in_1,
            in_char_2=in_2,
            char_1_joined=entry1.joined_at.strftime("%Y-%m-%d") if entry1 and entry1.joined_at else None,
            char_2_joined=entry2.joined_at.strftime("%Y-%m-%d") if entry2 and entry2.joined_at else None,
        )

        if in_1 and in_2:
            shared.append(diff)
        elif in_1:
            unique_1.append(diff)
        else:
            unique_2.append(diff)

    return shared, unique_1, unique_2


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
            title=flags1[code].reason,
            severity=flags1[code].severity.value,
            in_report_1=True,
            in_report_2=True,
        )
        for code in shared_codes
    ]

    only_in_1 = [
        FlagDiff(
            code=code,
            title=flags1[code].reason,
            severity=flags1[code].severity.value,
            in_report_1=True,
            in_report_2=False,
        )
        for code in only_in_1_codes
    ]

    only_in_2 = [
        FlagDiff(
            code=code,
            title=flags2[code].reason,
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

    # Extract detailed metrics
    metrics_1 = _extract_metrics(report1)
    metrics_2 = _extract_metrics(report2)

    # Compare corp histories
    shared_corps, unique_corps_1, unique_corps_2 = _compare_corp_history(report1, report2)

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
        metrics_1=metrics_1,
        metrics_2=metrics_2,
        shared_corps=shared_corps,
        unique_corps_1=unique_corps_1,
        unique_corps_2=unique_corps_2,
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


class SearchResponse(BaseModel):
    """Search results with pagination info."""

    results: list[ReportSummary]
    total: int
    limit: int
    offset: int
    query: str | None = None
    risk_filter: str | None = None
    flag_filter: str | None = None


@router.get("/search", response_model=SearchResponse)
@limiter.limit(LIMITS["reports"])
async def search_reports(
    request: Request,
    q: str | None = Query(default=None, description="Search by character name"),
    risk: OverallRisk | None = Query(default=None, description="Filter by risk level"),
    flag: str | None = Query(default=None, description="Filter by flag code"),
    date_from: datetime | None = Query(default=None, description="Start date (ISO format)"),
    date_to: datetime | None = Query(default=None, description="End date (ISO format)"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session_dependency),
) -> SearchResponse:
    """
    Search reports with multiple filters.

    Search criteria:
    - q: Character name (case-insensitive partial match)
    - risk: Filter by risk level (RED, YELLOW, GREEN)
    - flag: Filter by specific flag code
    - date_from/date_to: Filter by creation date range

    Returns paginated results with total count.
    """
    repo = ReportRepository(session)

    results = await repo.search_reports(
        query=q,
        risk_filter=risk,
        flag_code=flag,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )

    total = await repo.count_search_results(
        query=q,
        risk_filter=risk,
        flag_code=flag,
        date_from=date_from,
        date_to=date_to,
    )

    return SearchResponse(
        results=results,
        total=total,
        limit=limit,
        offset=offset,
        query=q,
        risk_filter=risk.value if risk else None,
        flag_filter=flag,
    )


@router.get("/search/flags", response_model=list[str])
@limiter.limit(LIMITS["reports"])
async def get_available_flags(
    request: Request,
    session: AsyncSession = Depends(get_session_dependency),
) -> list[str]:
    """
    Get all unique flag codes for filter dropdown.

    Returns sorted list of flag codes that exist in the database.
    """
    repo = ReportRepository(session)
    return await repo.get_all_flag_codes()


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


# --- Annotation Endpoints ---


class CreateAnnotationRequest(BaseModel):
    """Request to create an annotation."""

    author: str
    content: str
    annotation_type: str = "note"  # note, decision, warning, info


class UpdateAnnotationRequest(BaseModel):
    """Request to update an annotation."""

    content: str | None = None
    annotation_type: str | None = None


@router.get("/{report_id}/annotations", response_model=list[Annotation])
@limiter.limit(LIMITS["reports"])
async def get_report_annotations(
    request: Request,
    report_id: UUID,
    session: AsyncSession = Depends(get_session_dependency),
) -> list[Annotation]:
    """
    Get all annotations for a report.

    Returns annotations ordered by creation date, newest first.
    """
    # Verify report exists
    report_repo = ReportRepository(session)
    report = await report_repo.get_by_id(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    annotation_repo = AnnotationRepository(session)
    return await annotation_repo.get_by_report_id(report_id)


@router.post("/{report_id}/annotations", response_model=Annotation, status_code=201)
@limiter.limit(LIMITS["reports"])
async def create_annotation(
    request: Request,
    report_id: UUID,
    annotation_request: CreateAnnotationRequest,
    session: AsyncSession = Depends(get_session_dependency),
) -> Annotation:
    """
    Create a new annotation on a report.

    Annotation types:
    - note: General note or observation
    - decision: Recruitment decision (accept/reject/review)
    - warning: Important warning for other recruiters
    - info: Additional information about the applicant
    """
    # Verify report exists
    report_repo = ReportRepository(session)
    report = await report_repo.get_by_id(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    # Validate annotation type
    valid_types = ["note", "decision", "warning", "info"]
    if annotation_request.annotation_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid annotation type. Must be one of: {', '.join(valid_types)}",
        )

    annotation_repo = AnnotationRepository(session)
    return await annotation_repo.create(
        report_id=report_id,
        author=annotation_request.author,
        content=annotation_request.content,
        annotation_type=annotation_request.annotation_type,
    )


@router.get("/{report_id}/annotations/{annotation_id}", response_model=Annotation)
@limiter.limit(LIMITS["reports"])
async def get_annotation(
    request: Request,
    report_id: UUID,
    annotation_id: int,
    session: AsyncSession = Depends(get_session_dependency),
) -> Annotation:
    """Get a specific annotation by ID."""
    annotation_repo = AnnotationRepository(session)
    annotation = await annotation_repo.get_by_id(annotation_id)

    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")

    # Verify annotation belongs to the specified report
    if annotation.report_id != str(report_id):
        raise HTTPException(status_code=404, detail="Annotation not found")

    return annotation


@router.patch("/{report_id}/annotations/{annotation_id}", response_model=Annotation)
@limiter.limit(LIMITS["reports"])
async def update_annotation(
    request: Request,
    report_id: UUID,
    annotation_id: int,
    update_request: UpdateAnnotationRequest,
    session: AsyncSession = Depends(get_session_dependency),
) -> Annotation:
    """Update an annotation's content or type."""
    annotation_repo = AnnotationRepository(session)

    # Get existing annotation
    annotation = await annotation_repo.get_by_id(annotation_id)
    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")

    # Verify annotation belongs to the specified report
    if annotation.report_id != str(report_id):
        raise HTTPException(status_code=404, detail="Annotation not found")

    # Validate annotation type if provided
    if update_request.annotation_type:
        valid_types = ["note", "decision", "warning", "info"]
        if update_request.annotation_type not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid annotation type. Must be one of: {', '.join(valid_types)}",
            )

    updated = await annotation_repo.update(
        annotation_id=annotation_id,
        content=update_request.content,
        annotation_type=update_request.annotation_type,
    )

    if not updated:
        raise HTTPException(status_code=404, detail="Annotation not found")

    return updated


@router.delete("/{report_id}/annotations/{annotation_id}", status_code=204)
@limiter.limit(LIMITS["reports"])
async def delete_annotation(
    request: Request,
    report_id: UUID,
    annotation_id: int,
    session: AsyncSession = Depends(get_session_dependency),
) -> None:
    """Delete an annotation."""
    annotation_repo = AnnotationRepository(session)

    # Get existing annotation
    annotation = await annotation_repo.get_by_id(annotation_id)
    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")

    # Verify annotation belongs to the specified report
    if annotation.report_id != str(report_id):
        raise HTTPException(status_code=404, detail="Annotation not found")

    deleted = await annotation_repo.delete(annotation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Annotation not found")
