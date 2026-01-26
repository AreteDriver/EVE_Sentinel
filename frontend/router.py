"""Frontend router with Jinja2 templates and HTMX endpoints."""

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from backend.analyzers.risk_scorer import RiskScorer
from backend.connectors.esi import ESIClient
from backend.connectors.zkill import ZKillClient
from backend.database import ReportRepository, get_session, get_session_dependency
from backend.models.report import OverallRisk

# Template setup
TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["frontend"])

# Initialize clients
esi_client = ESIClient()
zkill_client = ZKillClient()
risk_scorer = RiskScorer()


# --- Page Routes ---


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    session: AsyncSession = Depends(get_session_dependency),
) -> HTMLResponse:
    """Dashboard - overview with stats and recent reports."""
    repo = ReportRepository(session)

    # Get stats
    total_reports = await repo.count_reports()
    red_count = await repo.count_reports(OverallRisk.RED)
    yellow_count = await repo.count_reports(OverallRisk.YELLOW)
    green_count = await repo.count_reports(OverallRisk.GREEN)

    # Get recent reports
    recent_reports = await repo.list_reports(limit=10)

    return templates.TemplateResponse(
        request=request,
        name="pages/dashboard.html",
        context={
            "stats": {
                "total": total_reports,
                "red": red_count,
                "yellow": yellow_count,
                "green": green_count,
            },
            "recent_reports": recent_reports,
        },
    )


@router.get("/reports", response_class=HTMLResponse)
async def reports_list(
    request: Request,
    risk: str | None = Query(default=None, description="Filter by risk level"),
    q: str | None = Query(default=None, description="Search by character name"),
    flag: str | None = Query(default=None, description="Filter by flag code"),
    date_from: str | None = Query(default=None, description="Start date"),
    date_to: str | None = Query(default=None, description="End date"),
    page: int = Query(default=1, ge=1),
    session: AsyncSession = Depends(get_session_dependency),
) -> HTMLResponse:
    """Reports list with filtering, search, and pagination."""
    from datetime import datetime

    repo = ReportRepository(session)

    limit = 25
    offset = (page - 1) * limit

    # Parse risk filter
    risk_filter = None
    if risk and risk.upper() in ["RED", "YELLOW", "GREEN"]:
        risk_filter = OverallRisk(risk.upper())

    # Parse date filters
    date_from_dt = None
    date_to_dt = None
    if date_from:
        try:
            date_from_dt = datetime.fromisoformat(date_from)
        except ValueError:
            pass
    if date_to:
        try:
            date_to_dt = datetime.fromisoformat(date_to)
        except ValueError:
            pass

    # Get available flag codes for dropdown
    available_flags = await repo.get_all_flag_codes()

    # Use search if any search params provided
    if q or flag or date_from_dt or date_to_dt:
        reports = await repo.search_reports(
            query=q,
            risk_filter=risk_filter,
            flag_code=flag,
            date_from=date_from_dt,
            date_to=date_to_dt,
            limit=limit,
            offset=offset,
        )
        total = await repo.count_search_results(
            query=q,
            risk_filter=risk_filter,
            flag_code=flag,
            date_from=date_from_dt,
            date_to=date_to_dt,
        )
    else:
        reports = await repo.list_reports(limit=limit, offset=offset, risk_filter=risk_filter)
        total = await repo.count_reports(risk_filter)

    total_pages = (total + limit - 1) // limit

    return templates.TemplateResponse(
        request=request,
        name="pages/reports.html",
        context={
            "reports": reports,
            "current_page": page,
            "total_pages": total_pages,
            "total_reports": total,
            "risk_filter": risk,
            "search_query": q,
            "flag_filter": flag,
            "date_from": date_from,
            "date_to": date_to,
            "available_flags": available_flags,
        },
    )


@router.get("/reports/{report_id}", response_class=HTMLResponse)
async def report_detail(
    request: Request,
    report_id: UUID,
    session: AsyncSession = Depends(get_session_dependency),
) -> HTMLResponse:
    """Single report detail view."""
    repo = ReportRepository(session)
    report = await repo.get_by_id(report_id)

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    return templates.TemplateResponse(
        request=request,
        name="pages/report_detail.html",
        context={"report": report},
    )


@router.get("/analyze", response_class=HTMLResponse)
async def analyze_form(request: Request) -> HTMLResponse:
    """New analysis form."""
    return templates.TemplateResponse(
        request=request,
        name="pages/analyze.html",
        context={},
    )


@router.get("/character/{character_id}", response_class=HTMLResponse)
async def character_history(
    request: Request,
    character_id: int,
    session: AsyncSession = Depends(get_session_dependency),
) -> HTMLResponse:
    """Character analysis history timeline."""
    repo = ReportRepository(session)
    reports = await repo.get_by_character_id(character_id, limit=50)

    if not reports:
        raise HTTPException(
            status_code=404,
            detail=f"No reports found for character {character_id}",
        )

    # Get character name from most recent report
    character_name = reports[0].character_name if reports else f"Character {character_id}"

    return templates.TemplateResponse(
        request=request,
        name="pages/character.html",
        context={
            "character_id": character_id,
            "character_name": character_name,
            "reports": reports,
        },
    )


@router.get("/compare", response_class=HTMLResponse)
async def compare_form(
    request: Request,
    session: AsyncSession = Depends(get_session_dependency),
) -> HTMLResponse:
    """Character comparison form page."""
    repo = ReportRepository(session)
    recent_reports = await repo.list_reports(limit=20)

    return templates.TemplateResponse(
        request=request,
        name="pages/compare.html",
        context={"recent_reports": recent_reports},
    )


# --- HTMX Partial Routes ---


@router.get("/partials/reports-table", response_class=HTMLResponse)
async def reports_table_partial(
    request: Request,
    risk: str | None = Query(default=None),
    q: str | None = Query(default=None),
    flag: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    session: AsyncSession = Depends(get_session_dependency),
) -> HTMLResponse:
    """HTMX partial: filtered and searched reports table."""
    from datetime import datetime

    repo = ReportRepository(session)

    limit = 25
    offset = (page - 1) * limit

    risk_filter = None
    if risk and risk.upper() in ["RED", "YELLOW", "GREEN"]:
        risk_filter = OverallRisk(risk.upper())

    # Parse date filters
    date_from_dt = None
    date_to_dt = None
    if date_from:
        try:
            date_from_dt = datetime.fromisoformat(date_from)
        except ValueError:
            pass
    if date_to:
        try:
            date_to_dt = datetime.fromisoformat(date_to)
        except ValueError:
            pass

    # Use search if any search params provided
    if q or flag or date_from_dt or date_to_dt:
        reports = await repo.search_reports(
            query=q,
            risk_filter=risk_filter,
            flag_code=flag,
            date_from=date_from_dt,
            date_to=date_to_dt,
            limit=limit,
            offset=offset,
        )
        total = await repo.count_search_results(
            query=q,
            risk_filter=risk_filter,
            flag_code=flag,
            date_from=date_from_dt,
            date_to=date_to_dt,
        )
    else:
        reports = await repo.list_reports(limit=limit, offset=offset, risk_filter=risk_filter)
        total = await repo.count_reports(risk_filter)

    total_pages = (total + limit - 1) // limit

    return templates.TemplateResponse(
        request=request,
        name="partials/reports_table.html",
        context={
            "reports": reports,
            "current_page": page,
            "total_pages": total_pages,
            "total_reports": total,
            "risk_filter": risk,
            "search_query": q,
            "flag_filter": flag,
        },
    )


@router.post("/partials/analyze", response_class=HTMLResponse)
async def analyze_partial(
    request: Request,
    character_input: str = Form(...),
) -> HTMLResponse:
    """HTMX partial: submit analysis and return result."""
    error = None
    report = None

    try:
        # Try to parse as character ID first
        character_id = None
        if character_input.isdigit():
            character_id = int(character_input)
        else:
            # Search by name
            character_id = await esi_client.search_character(character_input)

        if not character_id:
            error = f"Character '{character_input}' not found"
        else:
            # Run analysis
            applicant = await esi_client.build_applicant(character_id)
            applicant = await zkill_client.enrich_applicant(applicant)
            report = await risk_scorer.analyze(applicant)

            # Save report
            async with get_session() as session:
                repo = ReportRepository(session)
                await repo.save(report)

    except Exception as e:
        error = str(e)

    return templates.TemplateResponse(
        request=request,
        name="partials/analysis_result.html",
        context={
            "report": report,
            "error": error,
        },
    )
