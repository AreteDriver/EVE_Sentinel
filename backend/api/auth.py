"""Authentication API endpoints for EVE SSO."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from backend.config import settings
from backend.connectors.esi_authenticated import AuthenticatedESIClient
from backend.rate_limit import LIMITS, limiter
from backend.sso import (
    DEFAULT_SCOPES,
    EVECharacter,
    create_oauth_client,
    get_current_user,
    is_sso_configured,
    parse_jwt_token,
)

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])

# OAuth client - created once
oauth = create_oauth_client()


class AuthStatus(BaseModel):
    """Authentication status response."""

    authenticated: bool
    sso_configured: bool
    character_id: int | None = None
    character_name: str | None = None
    scopes: list[str] = []


class SSOConfig(BaseModel):
    """SSO configuration status."""

    configured: bool
    callback_url: str
    available_scopes: list[str]


@router.get("/status", response_model=AuthStatus)
async def get_auth_status(request: Request) -> AuthStatus:
    """
    Get current authentication status.

    Returns whether the user is authenticated and their character info.
    """
    user = await get_current_user(request)

    return AuthStatus(
        authenticated=user is not None,
        sso_configured=is_sso_configured(),
        character_id=user.character_id if user else None,
        character_name=user.character_name if user else None,
        scopes=user.scopes if user else [],
    )


@router.get("/sso-config", response_model=SSOConfig)
async def get_sso_config() -> SSOConfig:
    """
    Get SSO configuration status.

    Returns whether SSO is configured and what scopes are available.
    """
    return SSOConfig(
        configured=is_sso_configured(),
        callback_url=settings.esi_callback_url,
        available_scopes=DEFAULT_SCOPES,
    )


@router.get("/login")
async def login(request: Request, redirect_uri: str | None = None):
    """
    Initiate EVE SSO login.

    Redirects to EVE Online login page.
    """
    if not is_sso_configured():
        raise HTTPException(
            status_code=503,
            detail="EVE SSO not configured. Set ESI_CLIENT_ID and ESI_SECRET_KEY.",
        )

    # Store the desired redirect location
    if redirect_uri:
        request.session["login_redirect"] = redirect_uri

    # Get the callback URL
    callback_url = settings.esi_callback_url

    # Create authorization URL
    eve = oauth.create_client("eve")
    return await eve.authorize_redirect(request, callback_url)


@router.get("/callback")
async def callback(request: Request):
    """
    Handle EVE SSO callback.

    Exchanges authorization code for tokens and creates session.
    """
    if not is_sso_configured():
        raise HTTPException(
            status_code=503,
            detail="EVE SSO not configured",
        )

    try:
        eve = oauth.create_client("eve")
        token = await eve.authorize_access_token(request)

        # Parse the JWT to get character info
        character = parse_jwt_token(token)

        if not character:
            raise HTTPException(
                status_code=400,
                detail="Failed to parse authentication token",
            )

        # Store user in session
        request.session["user"] = character.model_dump(mode="json")

        # Redirect to original destination or dashboard
        redirect_uri = request.session.pop("login_redirect", "/")
        return RedirectResponse(url=redirect_uri)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Authentication failed: {str(e)}",
        ) from e


@router.get("/logout")
async def logout(request: Request, redirect_uri: str = "/"):
    """
    Log out the current user.

    Clears the session and redirects to the specified URI.
    """
    request.session.clear()
    return RedirectResponse(url=redirect_uri)


@router.get("/me", response_model=EVECharacter)
async def get_current_character(request: Request) -> EVECharacter:
    """
    Get the currently authenticated character.

    Returns 401 if not authenticated.
    """
    user = await get_current_user(request)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
        )

    return user


@router.post("/refresh")
async def refresh_session(request: Request) -> AuthStatus:
    """
    Refresh the current session token.

    Attempts to refresh the access token using the refresh token.
    Returns updated auth status.
    """
    from backend.sso import refresh_token_if_needed

    user = await get_current_user(request)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
        )

    updated = await refresh_token_if_needed(oauth, user)

    if updated:
        request.session["user"] = updated.model_dump(mode="json")
        return AuthStatus(
            authenticated=True,
            sso_configured=True,
            character_id=updated.character_id,
            character_name=updated.character_name,
            scopes=updated.scopes,
        )

    # Refresh failed, clear session
    request.session.clear()
    raise HTTPException(
        status_code=401,
        detail="Token refresh failed. Please log in again.",
    )


class AuthenticatedAnalysisResult(BaseModel):
    """Result of authenticated analysis with enriched data."""

    character_id: int
    character_name: str
    report_id: str
    overall_risk: str
    confidence: float
    red_flags: int
    yellow_flags: int
    green_flags: int
    data_sources: list[str]
    has_wallet_data: bool
    has_asset_data: bool
    has_standings_data: bool


@router.post("/analyze-me", response_model=AuthenticatedAnalysisResult)
@limiter.limit(LIMITS["analyze"])
async def analyze_authenticated_character(request: Request) -> AuthenticatedAnalysisResult:
    """
    Analyze the currently authenticated character with full ESI data.

    Uses the OAuth2 access token to fetch protected data:
    - Wallet journal (recent transactions)
    - Assets (ships, items)
    - Contacts and standings

    This provides a more comprehensive analysis than public-only data.
    Requires the user to be logged in via EVE SSO.
    """
    from backend.analyzers.risk_scorer import RiskScorer
    from backend.api.webhooks import send_report_webhook
    from backend.connectors.esi import ESIClient
    from backend.connectors.zkill import ZKillClient
    from backend.database import ReportRepository, get_session
    from backend.logging_config import get_logger

    logger = get_logger(__name__)

    # Get current user
    user = await get_current_user(request)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated. Please log in via EVE SSO.",
        )

    logger.info(
        "Starting authenticated analysis for %s (%d)",
        user.character_name,
        user.character_id,
    )

    try:
        # Build base applicant from public ESI data
        esi_client = ESIClient()
        applicant = await esi_client.build_applicant(user.character_id)

        # Enrich with killboard data
        zkill_client = ZKillClient()
        applicant = await zkill_client.enrich_applicant(applicant)

        # Enrich with authenticated ESI data
        auth_client = AuthenticatedESIClient(user.access_token, user.character_id)
        try:
            applicant = await auth_client.enrich_applicant(applicant)
        finally:
            await auth_client.close()

        # Run analysis
        risk_scorer = RiskScorer()
        report = await risk_scorer.analyze(
            applicant,
            requested_by=f"self:{user.character_name}",
        )

        # Persist the report
        async with get_session() as session:
            repo = ReportRepository(session)
            await repo.save(report)

        # Send webhook notification if configured
        await send_report_webhook(report)

        logger.info(
            "Authenticated analysis complete for %s: %s",
            user.character_name,
            report.overall_risk.value,
        )

        return AuthenticatedAnalysisResult(
            character_id=user.character_id,
            character_name=user.character_name,
            report_id=report.report_id,
            overall_risk=report.overall_risk.value,
            confidence=report.confidence,
            red_flags=report.red_flag_count,
            yellow_flags=report.yellow_flag_count,
            green_flags=report.green_flag_count,
            data_sources=applicant.data_sources,
            has_wallet_data=len(applicant.wallet_journal) > 0,
            has_asset_data=applicant.assets is not None,
            has_standings_data=applicant.standings_data is not None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Authenticated analysis failed for %s: %s",
            user.character_name,
            str(e),
        )
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed: {str(e)}",
        ) from e


class WalletSummary(BaseModel):
    """Summary of wallet data."""

    balance: float
    recent_transactions: int
    total_received_30d: float
    total_spent_30d: float


class AssetsSummary(BaseModel):
    """Summary of character assets."""

    capital_ships: list[str]
    supercapitals: list[str]
    primary_locations: list[str]


@router.get("/my-wallet", response_model=WalletSummary)
@limiter.limit(LIMITS["analyze"])
async def get_my_wallet(request: Request) -> WalletSummary:
    """
    Get wallet summary for the authenticated character.

    Returns wallet balance and recent transaction summary.
    Requires esi-wallet.read_character_wallet.v1 scope.
    """
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if "esi-wallet.read_character_wallet.v1" not in user.scopes:
        raise HTTPException(
            status_code=403,
            detail="Wallet scope not granted. Please re-authenticate with wallet permissions.",
        )

    auth_client = AuthenticatedESIClient(user.access_token, user.character_id)
    try:
        balance = await auth_client.get_wallet_balance()
        entries = await auth_client.build_wallet_entries(limit=100)

        # Calculate 30-day totals
        from datetime import UTC, datetime, timedelta

        cutoff = datetime.now(UTC) - timedelta(days=30)
        total_received = sum(e.amount for e in entries if e.amount > 0 and e.date >= cutoff)
        total_spent = abs(sum(e.amount for e in entries if e.amount < 0 and e.date >= cutoff))

        return WalletSummary(
            balance=balance,
            recent_transactions=len(entries),
            total_received_30d=total_received,
            total_spent_30d=total_spent,
        )
    finally:
        await auth_client.close()


@router.get("/my-assets", response_model=AssetsSummary)
@limiter.limit(LIMITS["analyze"])
async def get_my_assets(request: Request) -> AssetsSummary:
    """
    Get asset summary for the authenticated character.

    Returns capital ships, supercapitals, and primary locations.
    Requires esi-assets.read_assets.v1 scope.
    """
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if "esi-assets.read_assets.v1" not in user.scopes:
        raise HTTPException(
            status_code=403,
            detail="Assets scope not granted. Please re-authenticate with asset permissions.",
        )

    auth_client = AuthenticatedESIClient(user.access_token, user.character_id)
    try:
        summary = await auth_client.build_asset_summary()

        return AssetsSummary(
            capital_ships=summary.capital_ships,
            supercapitals=summary.supercapitals,
            primary_locations=summary.primary_regions,
        )
    finally:
        await auth_client.close()
