"""Fleet and Corporation analysis API endpoints."""

import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.analyzers.risk_scorer import RiskScorer
from backend.connectors.esi import ESIClient
from backend.connectors.zkill import ZKillClient
from backend.database import ReportRepository, get_session_dependency
from backend.logging_config import get_logger
from backend.rate_limit import LIMITS, limiter

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/fleet", tags=["fleet"])

# Initialize clients
esi_client = ESIClient()
zkill_client = ZKillClient()
risk_scorer = RiskScorer()


class CorpAnalysisRequest(BaseModel):
    """Request to analyze a corporation's members."""

    corporation_id: int | None = None
    corporation_name: str | None = None
    requested_by: str | None = None
    max_members: int = 50  # Limit to avoid rate limiting


class FleetAnalysisRequest(BaseModel):
    """Request to analyze a fleet from D-Scan or member list."""

    input_text: str  # Raw D-Scan or character list paste
    requested_by: str | None = None


class CharacterResult(BaseModel):
    """Analysis result for a single character."""

    character_id: int
    character_name: str
    corporation_name: str | None = None
    overall_risk: str
    confidence: float
    red_flags: int
    yellow_flags: int
    green_flags: int
    report_id: str | None = None
    error: str | None = None


class FleetAnalysisResult(BaseModel):
    """Result of fleet/corp analysis."""

    total_characters: int
    analyzed: int
    failed: int
    risk_summary: dict[str, int]
    characters: list[CharacterResult]
    analysis_time_ms: int


@router.post("/analyze-corp", response_model=FleetAnalysisResult)
@limiter.limit(LIMITS["analyze_batch"])
async def analyze_corporation(
    request: Request,
    corp_request: CorpAnalysisRequest,
    session: AsyncSession = Depends(get_session_dependency),
) -> FleetAnalysisResult:
    """
    Analyze members of a corporation.

    Fetches corporation member list and analyzes each character.
    Limited to max_members to avoid rate limiting.
    """
    # Resolve corporation
    corp_id = corp_request.corporation_id
    if not corp_id and corp_request.corporation_name:
        # Search for corporation by name
        corp_id = await esi_client.search_corporation(corp_request.corporation_name)

    if not corp_id:
        raise HTTPException(
            status_code=404,
            detail="Corporation not found",
        )

    # Get corporation info
    corp_info = await esi_client.get_corporation(corp_id)
    if not corp_info:
        raise HTTPException(
            status_code=404,
            detail="Failed to get corporation info",
        )

    # Get member list (requires corporation auth, so we'll use affiliations approach)
    # For now, we'll accept a list of character IDs or names instead
    # This is a limitation - full member list requires director tokens

    raise HTTPException(
        status_code=501,
        detail="Corporation member analysis requires director-level ESI tokens. "
        "Use /analyze-fleet with a list of character names instead.",
    )


@router.post("/analyze-fleet", response_model=FleetAnalysisResult)
@limiter.limit(LIMITS["analyze_batch"])
async def analyze_fleet(
    request: Request,
    fleet_request: FleetAnalysisRequest,
    session: AsyncSession = Depends(get_session_dependency),
) -> FleetAnalysisResult:
    """
    Analyze characters from a D-Scan, fleet list, or character name list.

    Accepts various input formats:
    - One character name per line
    - D-Scan format (ship type and character name)
    - Fleet window copy-paste
    - CSV format
    """
    start_time = datetime.now(UTC)

    # Parse input to get character names
    character_names = parse_input_text(fleet_request.input_text)

    if not character_names:
        raise HTTPException(
            status_code=400,
            detail="No character names found in input",
        )

    # Limit to prevent abuse
    max_chars = 50
    if len(character_names) > max_chars:
        character_names = character_names[:max_chars]
        logger.warning(f"Truncated fleet analysis to {max_chars} characters")

    results: list[CharacterResult] = []
    risk_summary = {"RED": 0, "YELLOW": 0, "GREEN": 0}
    failed_count = 0

    repo = ReportRepository(session)

    for name in character_names:
        try:
            # Resolve character ID
            character_id = await esi_client.search_character(name)
            if not character_id:
                results.append(
                    CharacterResult(
                        character_id=0,
                        character_name=name,
                        overall_risk="UNKNOWN",
                        confidence=0,
                        red_flags=0,
                        yellow_flags=0,
                        green_flags=0,
                        error="Character not found",
                    )
                )
                failed_count += 1
                continue

            # Check if we have a recent report
            existing = await repo.get_latest_by_character_id(character_id)
            if existing and (datetime.now(UTC) - existing.created_at).days < 1:
                # Use existing report from last 24 hours
                results.append(
                    CharacterResult(
                        character_id=character_id,
                        character_name=existing.character_name,
                        corporation_name=None,
                        overall_risk=existing.overall_risk.value,
                        confidence=existing.confidence,
                        red_flags=existing.red_flag_count,
                        yellow_flags=existing.yellow_flag_count,
                        green_flags=existing.green_flag_count,
                        report_id=str(existing.report_id),
                    )
                )
                risk_summary[existing.overall_risk.value] += 1
                continue

            # Run new analysis
            applicant = await esi_client.build_applicant(character_id)
            applicant = await zkill_client.enrich_applicant(applicant)
            report = await risk_scorer.analyze(
                applicant,
                requested_by=fleet_request.requested_by or "fleet_analysis",
            )

            # Save report
            await repo.save(report)

            results.append(
                CharacterResult(
                    character_id=character_id,
                    character_name=report.character_name,
                    corporation_name=applicant.corporation.name if applicant.corporation else None,
                    overall_risk=report.overall_risk.value,
                    confidence=report.confidence,
                    red_flags=report.red_flag_count,
                    yellow_flags=report.yellow_flag_count,
                    green_flags=report.green_flag_count,
                    report_id=str(report.report_id),
                )
            )
            risk_summary[report.overall_risk.value] += 1

        except Exception as e:
            logger.error(f"Failed to analyze {name}: {e}")
            results.append(
                CharacterResult(
                    character_id=0,
                    character_name=name,
                    overall_risk="UNKNOWN",
                    confidence=0,
                    red_flags=0,
                    yellow_flags=0,
                    green_flags=0,
                    error=str(e),
                )
            )
            failed_count += 1

    end_time = datetime.now(UTC)
    analysis_time_ms = int((end_time - start_time).total_seconds() * 1000)

    # Sort by risk (RED first, then YELLOW, then GREEN)
    risk_order = {"RED": 0, "YELLOW": 1, "GREEN": 2, "UNKNOWN": 3}
    results.sort(key=lambda x: risk_order.get(x.overall_risk, 4))

    return FleetAnalysisResult(
        total_characters=len(character_names),
        analyzed=len(results) - failed_count,
        failed=failed_count,
        risk_summary=risk_summary,
        characters=results,
        analysis_time_ms=analysis_time_ms,
    )


@router.get("/parse-preview")
async def parse_preview(
    request: Request,
    text: str = Query(..., description="Input text to parse"),
) -> dict:
    """
    Preview what characters would be parsed from input text.

    Useful for validating input before analysis.
    """
    names = parse_input_text(text)
    return {
        "count": len(names),
        "characters": names[:100],  # Limit preview
        "truncated": len(names) > 100,
    }


def parse_input_text(text: str) -> list[str]:
    """
    Parse character names from various input formats.

    Handles:
    - Simple list (one name per line)
    - D-Scan format (ship type + character)
    - Fleet window copy
    - CSV format
    - Tab-separated format
    """
    names: list[str] = []
    lines = text.strip().split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Skip common header lines
        lower_line = line.lower()
        if any(
            skip in lower_line
            for skip in ["name", "character", "pilot", "ship", "type", "distance", "---"]
        ):
            continue

        # Try to extract character name from various formats

        # D-Scan format: "Ship Type\tCharacter Name\tDistance"
        if "\t" in line:
            parts = line.split("\t")
            # D-Scan typically has ship type first, then character name
            if len(parts) >= 2:
                # Check if second part looks like a distance
                if re.match(r"[\d,.]+ (km|m|AU)", parts[-1]):
                    # Last part is distance, second-to-last might be name
                    potential_name = parts[-2].strip() if len(parts) > 2 else parts[0].strip()
                else:
                    # No distance, assume last part is name
                    potential_name = parts[-1].strip()

                # Validate it's not a ship type
                if not is_ship_type(potential_name) and is_valid_character_name(potential_name):
                    names.append(potential_name)
                continue

        # CSV format
        if "," in line:
            parts = [p.strip().strip('"') for p in line.split(",")]
            for part in parts:
                if is_valid_character_name(part) and not is_ship_type(part):
                    names.append(part)
                    break
            continue

        # Fleet format: "Character Name (Corporation) - Ship Type"
        match = re.match(r"^([^(]+)\s*\(", line)
        if match:
            potential_name = match.group(1).strip()
            if is_valid_character_name(potential_name):
                names.append(potential_name)
            continue

        # Simple name format
        if is_valid_character_name(line) and not is_ship_type(line):
            names.append(line)

    # Remove duplicates while preserving order
    seen = set()
    unique_names = []
    for name in names:
        if name.lower() not in seen:
            seen.add(name.lower())
            unique_names.append(name)

    return unique_names


def is_valid_character_name(name: str) -> bool:
    """Check if string looks like a valid EVE character name."""
    if not name or len(name) < 3 or len(name) > 37:
        return False

    # Must contain at least one letter
    if not any(c.isalpha() for c in name):
        return False

    # Shouldn't be all numbers
    if name.replace(" ", "").isdigit():
        return False

    # Basic validation - EVE names can have letters, numbers, spaces, and some special chars
    if not re.match(r"^[a-zA-Z0-9\s'\-\.]+$", name):
        return False

    return True


def is_ship_type(text: str) -> bool:
    """Check if text is likely a ship type rather than a character name."""
    # Common ship type indicators
    ship_indicators = [
        "frigate", "destroyer", "cruiser", "battlecruiser", "battleship",
        "carrier", "dreadnought", "titan", "supercarrier", "freighter",
        "industrial", "mining", "shuttle", "capsule", "pod",
        "interceptor", "assault", "recon", "command", "logistics",
        "stealth", "bomber", "corvette", "venture", "procurer", "retriever",
        "hulk", "skiff", "mackinaw", "rorqual", "orca",
    ]

    lower_text = text.lower()
    return any(indicator in lower_text for indicator in ship_indicators)
