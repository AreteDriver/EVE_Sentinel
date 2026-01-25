"""Analysis API endpoints."""

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.analyzers.risk_scorer import RiskScorer
from backend.api.webhooks import send_batch_webhook, send_report_webhook
from backend.config import settings
from backend.connectors.auth_bridge import AuthBridge, get_auth_bridge
from backend.connectors.esi import ESIClient
from backend.connectors.zkill import ZKillClient
from backend.database import ReportRepository, get_session
from backend.logging_config import get_logger
from backend.models.report import (
    AnalysisReport,
    BatchAnalysisRequest,
    BatchAnalysisResult,
    OverallRisk,
    ReportSummary,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["analysis"])

# Initialize clients and scorer
esi_client = ESIClient()
zkill_client = ZKillClient()
risk_scorer = RiskScorer()

# Initialize auth bridge if configured
auth_bridge: AuthBridge | None = None
if settings.auth_system and settings.auth_bridge_url and settings.auth_bridge_token:
    try:
        auth_bridge = get_auth_bridge(
            settings.auth_system,
            settings.auth_bridge_url,
            settings.auth_bridge_token,
        )
        logger.info(f"Auth bridge initialized: {settings.auth_system}")
    except ValueError as e:
        logger.warning(f"Failed to initialize auth bridge: {e}")


# NOTE: Static routes must be defined before dynamic routes to avoid path conflicts
# e.g., /analyze/batch must come before /analyze/{character_id}


async def _analyze_single_character(
    char_id: int,
    requested_by: str | None,
) -> AnalysisReport | None:
    """
    Analyze a single character for batch processing.

    Returns None if analysis fails.
    """
    try:
        applicant = await esi_client.build_applicant(char_id)
        applicant = await zkill_client.enrich_applicant(applicant)

        # Enrich with auth system data if available
        if auth_bridge:
            try:
                applicant = await auth_bridge.enrich_applicant(applicant)
            except Exception:
                pass  # Auth enrichment is optional

        report = await risk_scorer.analyze(applicant, requested_by)

        # Persist the report
        async with get_session() as session:
            repo = ReportRepository(session)
            await repo.save(report)

        logger.info(
            "Analyzed character %d (%s): %s",
            char_id,
            report.character_name,
            report.overall_risk.value,
        )
        return report

    except Exception as e:
        logger.error("Failed to analyze character %d: %s", char_id, str(e))
        return None


@router.post("/analyze/batch", response_model=BatchAnalysisResult)
async def batch_analyze(request: BatchAnalysisRequest) -> BatchAnalysisResult:
    """
    Analyze multiple characters in batch.

    Useful for screening entire application queues.
    Returns summary results for each character.
    """
    logger.info(
        "Starting batch analysis for %d characters", len(request.character_ids)
    )

    # Process all characters in parallel
    tasks = [
        _analyze_single_character(char_id, request.requested_by)
        for char_id in request.character_ids
    ]
    results = await asyncio.gather(*tasks)

    # Collect successful results
    reports: list[ReportSummary] = []
    full_reports: list[AnalysisReport] = []

    for report in results:
        if report is not None:
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

    completed = len(full_reports)
    failed = len(request.character_ids) - completed

    logger.info("Batch analysis complete: %d succeeded, %d failed", completed, failed)

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
    logger.info("Searching for character by name: %s", character_name)

    # Search for character
    char_id = await esi_client.search_character(character_name)

    if not char_id:
        logger.warning("Character not found: %s", character_name)
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
    logger.info("Starting analysis for character %d", character_id)

    try:
        # Fetch character data from ESI
        applicant = await esi_client.build_applicant(character_id)

        # Enrich with killboard data
        applicant = await zkill_client.enrich_applicant(applicant)

        # Enrich with auth system data if available
        if auth_bridge:
            try:
                applicant = await auth_bridge.enrich_applicant(applicant)
            except Exception as e:
                # Auth enrichment is optional, log and continue
                logger.debug(f"Auth bridge enrichment skipped: {e}")

        # Run analysis
        report = await risk_scorer.analyze(applicant, requested_by)

        # Persist the report
        async with get_session() as session:
            repo = ReportRepository(session)
            await repo.save(report)

        # Send webhook notification if configured
        await send_report_webhook(report)

        logger.info(
            "Analysis complete for %s (%d): %s",
            report.character_name,
            character_id,
            report.overall_risk.value,
        )

        return report

    except Exception as e:
        logger.error("Analysis failed for character %d: %s", character_id, str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed: {str(e)}",
        ) from e


@router.get("/quick-check/{character_id}")
async def quick_check(character_id: int) -> dict[str, Any]:
    """
    Fast risk check - just corp history and basic killboard.

    Use this for rapid screening before full analysis.
    Returns minimal data for quick decision making.
    """
    logger.debug("Quick check for character %d", character_id)

    try:
        # Just fetch basic ESI data
        applicant = await esi_client.build_applicant(character_id)

        # Quick killboard check
        applicant = await zkill_client.enrich_applicant(applicant)

        # Enrich with auth system data if available
        if auth_bridge:
            try:
                applicant = await auth_bridge.enrich_applicant(applicant)
            except Exception:
                pass  # Auth enrichment is optional

        # Run analysis
        report = await risk_scorer.analyze(applicant)

        logger.debug(
            "Quick check complete for %d: %s", character_id, report.overall_risk.value
        )

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
        logger.error("Quick check failed for character %d: %s", character_id, str(e))
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
