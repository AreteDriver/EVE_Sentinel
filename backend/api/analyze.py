"""Analysis API endpoints."""

from fastapi import APIRouter, HTTPException

from backend.analyzers.risk_scorer import RiskScorer
from backend.api.webhooks import send_batch_webhook, send_report_webhook
from backend.connectors.esi import ESIClient
from backend.connectors.zkill import ZKillClient
from backend.database import ReportRepository, get_session
from backend.models.report import (
    AnalysisReport,
    BatchAnalysisRequest,
    BatchAnalysisResult,
    OverallRisk,
    ReportSummary,
)

router = APIRouter(prefix="/api/v1", tags=["analysis"])

# Initialize clients and scorer
esi_client = ESIClient()
zkill_client = ZKillClient()
risk_scorer = RiskScorer()


# NOTE: Static routes must be defined before dynamic routes to avoid path conflicts
# e.g., /analyze/batch must come before /analyze/{character_id}


@router.post("/analyze/batch", response_model=BatchAnalysisResult)
async def batch_analyze(request: BatchAnalysisRequest) -> BatchAnalysisResult:
    """
    Analyze multiple characters in batch.

    Useful for screening entire application queues.
    Returns summary results for each character.
    """
    completed = 0
    failed = 0
    reports: list[ReportSummary] = []
    full_reports: list[AnalysisReport] = []

    for char_id in request.character_ids:
        try:
            applicant = await esi_client.build_applicant(char_id)
            applicant = await zkill_client.enrich_applicant(applicant)
            report = await risk_scorer.analyze(applicant, request.requested_by)

            # Persist the report
            async with get_session() as session:
                repo = ReportRepository(session)
                await repo.save(report)

            full_reports.append(report)
            reports.append(
                ReportSummary(
                    report_id=report.report_id,
                    character_id=report.character_id,
                    character_name=report.character_name,
                    overall_risk=report.overall_risk,
                    confidence=report.confidence,
                    red_flag_count=report.red_flag_count,
                    yellow_flag_count=report.yellow_flag_count,
                    green_flag_count=report.green_flag_count,
                    created_at=report.created_at,
                    status=report.status,
                )
            )
            completed += 1

        except Exception:
            failed += 1

    # Send batch summary webhook if configured
    if full_reports:
        await send_batch_webhook(full_reports)

    return BatchAnalysisResult(
        total_requested=len(request.character_ids),
        completed=completed,
        failed=failed,
        reports=reports,
    )


@router.get("/analyze/by-name/{character_name}", response_model=AnalysisReport)
async def analyze_by_name(
    character_name: str,
    requested_by: str | None = None,
) -> AnalysisReport:
    """
    Analyze a character by name instead of ID.

    Searches for the character first, then runs full analysis.
    """
    # Search for character
    char_id = await esi_client.search_character(character_name)

    if not char_id:
        raise HTTPException(
            status_code=404,
            detail=f"Character '{character_name}' not found",
        )

    return await analyze_character(char_id, requested_by)


@router.post("/analyze/{character_id}", response_model=AnalysisReport)
async def analyze_character(
    character_id: int,
    requested_by: str | None = None,
) -> AnalysisReport:
    """
    Perform full recruitment analysis on a character.

    This fetches data from ESI and zKillboard, runs all analyzers,
    and produces a comprehensive risk assessment.

    Args:
        character_id: EVE Online character ID to analyze
        requested_by: Optional identifier for who requested this analysis

    Returns:
        Complete analysis report with risk flags and recommendations
    """
    try:
        # Fetch character data from ESI
        applicant = await esi_client.build_applicant(character_id)

        # Enrich with killboard data
        applicant = await zkill_client.enrich_applicant(applicant)

        # Run analysis
        report = await risk_scorer.analyze(applicant, requested_by)

        # Persist the report
        async with get_session() as session:
            repo = ReportRepository(session)
            await repo.save(report)

        # Send webhook notification if configured
        await send_report_webhook(report)

        return report

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed: {str(e)}",
        ) from e


@router.get("/quick-check/{character_id}")
async def quick_check(character_id: int) -> dict:
    """
    Fast risk check - just corp history and basic killboard.

    Use this for rapid screening before full analysis.
    Returns minimal data for quick decision making.
    """
    try:
        # Just fetch basic ESI data
        applicant = await esi_client.build_applicant(character_id)

        # Quick killboard check
        applicant = await zkill_client.enrich_applicant(applicant)

        # Run analysis
        report = await risk_scorer.analyze(applicant)

        return {
            "character_id": character_id,
            "character_name": report.character_name,
            "overall_risk": report.overall_risk.value,
            "confidence": report.confidence,
            "red_flags": report.red_flag_count,
            "yellow_flags": report.yellow_flag_count,
            "green_flags": report.green_flag_count,
            "quick_summary": _generate_quick_summary(report),
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Quick check failed: {str(e)}",
        ) from e


def _generate_quick_summary(report: AnalysisReport) -> str:
    """Generate a one-line summary for quick checks."""
    if report.overall_risk == OverallRisk.RED:
        return "HIGH RISK - Multiple red flags detected"
    elif report.overall_risk == OverallRisk.YELLOW:
        return "MODERATE RISK - Review recommended"
    elif report.overall_risk == OverallRisk.GREEN:
        return "LOW RISK - No major concerns"
    else:
        return "INSUFFICIENT DATA - Manual review needed"
