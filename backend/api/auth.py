"""Authentication API endpoints for EVE SSO."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from backend.config import settings
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
