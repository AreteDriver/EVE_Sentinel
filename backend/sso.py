"""EVE Online SSO OAuth2 authentication."""

from datetime import UTC, datetime, timedelta
from typing import Any

from authlib.integrations.starlette_client import OAuth
from pydantic import BaseModel
from starlette.requests import Request

from backend.config import settings
from backend.logging_config import get_logger

logger = get_logger(__name__)

# Token refresh threshold - refresh if expiring within this time
TOKEN_REFRESH_THRESHOLD = timedelta(minutes=5)


class EVECharacter(BaseModel):
    """Authenticated EVE character information."""

    character_id: int
    character_name: str
    scopes: list[str] = []
    token_type: str = "Bearer"
    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None


class EVEToken(BaseModel):
    """EVE SSO token data."""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int | None = None
    refresh_token: str | None = None
    expires_at: int | None = None


# EVE Online SSO endpoints
EVE_SSO_AUTH_URL = "https://login.eveonline.com/v2/oauth/authorize"
EVE_SSO_TOKEN_URL = "https://login.eveonline.com/v2/oauth/token"
EVE_SSO_JWKS_URL = "https://login.eveonline.com/oauth/jwks"
EVE_SSO_METADATA_URL = "https://login.eveonline.com/.well-known/oauth-authorization-server"

# Default scopes for recruitment analysis
DEFAULT_SCOPES = [
    "esi-characters.read_standings.v1",
    "esi-wallet.read_character_wallet.v1",
    "esi-assets.read_assets.v1",
    "esi-killmails.read_killmails.v1",
]


def create_oauth_client() -> OAuth:
    """Create and configure OAuth client for EVE SSO."""
    oauth = OAuth()

    oauth.register(
        name="eve",
        client_id=settings.esi_client_id,
        client_secret=settings.esi_secret_key,
        authorize_url=EVE_SSO_AUTH_URL,
        access_token_url=EVE_SSO_TOKEN_URL,
        jwks_uri=EVE_SSO_JWKS_URL,
        client_kwargs={
            "scope": " ".join(DEFAULT_SCOPES),
        },
    )

    return oauth


def parse_jwt_token(token: dict[str, Any]) -> EVECharacter | None:
    """
    Parse EVE SSO JWT token to extract character information.

    The access token is a JWT that contains character info in its payload.
    """
    import base64
    import json

    access_token = token.get("access_token", "")
    if not access_token:
        return None

    try:
        # JWT has 3 parts: header.payload.signature
        parts = access_token.split(".")
        if len(parts) != 3:
            return None

        # Decode payload (add padding if needed)
        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding

        decoded = base64.urlsafe_b64decode(payload)
        data = json.loads(decoded)

        # Extract character info from JWT claims
        # EVE SSO uses "sub" claim in format "CHARACTER:EVE:character_id"
        sub = data.get("sub", "")
        parts = sub.split(":")
        if len(parts) >= 3 and parts[0] == "CHARACTER":
            character_id = int(parts[2])
        else:
            return None

        character_name = data.get("name", f"Character {character_id}")
        scopes = data.get("scp", [])
        if isinstance(scopes, str):
            scopes = [scopes]

        expires_at = None
        if "exp" in data:
            expires_at = datetime.fromtimestamp(data["exp"], tz=UTC)

        return EVECharacter(
            character_id=character_id,
            character_name=character_name,
            scopes=scopes,
            token_type=token.get("token_type", "Bearer"),
            access_token=access_token,
            refresh_token=token.get("refresh_token"),
            expires_at=expires_at,
        )

    except Exception:
        return None


def is_token_expired(character: EVECharacter) -> bool:
    """Check if the token is expired."""
    if not character.expires_at:
        return False  # Unknown expiry, assume valid
    return datetime.now(UTC) >= character.expires_at


def is_token_expiring_soon(character: EVECharacter) -> bool:
    """Check if the token is expiring within the threshold."""
    if not character.expires_at:
        return False
    return datetime.now(UTC) >= (character.expires_at - TOKEN_REFRESH_THRESHOLD)


def token_time_remaining(character: EVECharacter) -> timedelta | None:
    """Get time remaining until token expires."""
    if not character.expires_at:
        return None
    remaining = character.expires_at - datetime.now(UTC)
    return remaining if remaining.total_seconds() > 0 else timedelta(0)


async def get_current_user(request: Request) -> EVECharacter | None:
    """
    Get the currently authenticated EVE character from session.

    Returns None if not authenticated.
    """
    user_data = request.session.get("user")
    if not user_data:
        return None

    try:
        return EVECharacter(**user_data)
    except Exception:
        return None


async def get_current_user_with_refresh(request: Request, oauth: OAuth) -> EVECharacter | None:
    """
    Get current user with automatic token refresh.

    If the token is expiring soon, attempts to refresh it automatically
    and updates the session with the new token.

    Returns None if not authenticated or refresh failed for an expired token.
    """
    user = await get_current_user(request)
    if not user:
        return None

    # Check if token needs refresh
    if is_token_expiring_soon(user):
        logger.debug(f"Token expiring soon for {user.character_name}, attempting refresh")
        refreshed = await refresh_token_if_needed(oauth, user)

        if refreshed:
            # Update session with new token
            request.session["user"] = refreshed.model_dump(mode="json")
            logger.info(f"Token refreshed for {user.character_name}")
            return refreshed
        elif is_token_expired(user):
            # Token expired and refresh failed - clear session
            logger.warning(f"Token expired and refresh failed for {user.character_name}")
            request.session.clear()
            return None
        # Refresh failed but token not yet expired - continue with current token

    return user


async def refresh_token_if_needed(
    oauth: OAuth,
    character: EVECharacter,
) -> EVECharacter | None:
    """
    Refresh the access token if it's expired or about to expire.

    Returns updated character or None if refresh failed.
    """
    if not character.refresh_token:
        logger.debug(f"No refresh token for {character.character_name}")
        return None

    # Check if refresh is needed
    if not is_token_expiring_soon(character):
        return character  # Token still valid

    try:
        eve = oauth.create_client("eve")
        new_token = await eve.fetch_access_token(
            grant_type="refresh_token",
            refresh_token=character.refresh_token,
        )

        updated = parse_jwt_token(new_token)
        if updated:
            # Preserve refresh token if not returned
            if not updated.refresh_token:
                updated.refresh_token = character.refresh_token
            logger.info(f"Successfully refreshed token for {character.character_name}")
            return updated

    except Exception as e:
        logger.error(f"Token refresh failed for {character.character_name}: {e}")

    return None


async def validate_token(character: EVECharacter) -> dict[str, Any]:
    """
    Validate a token and return its status.

    Returns a dict with:
    - valid: bool - whether the token is currently valid
    - expired: bool - whether the token is expired
    - expiring_soon: bool - whether the token is expiring within threshold
    - expires_at: datetime | None - when the token expires
    - time_remaining: str | None - human-readable time remaining
    - can_refresh: bool - whether the token can be refreshed
    """
    expired = is_token_expired(character)
    expiring_soon = is_token_expiring_soon(character)
    remaining = token_time_remaining(character)

    time_str = None
    if remaining:
        total_seconds = int(remaining.total_seconds())
        if total_seconds <= 0:
            time_str = "expired"
        elif total_seconds < 60:
            time_str = f"{total_seconds}s"
        elif total_seconds < 3600:
            time_str = f"{total_seconds // 60}m"
        else:
            time_str = f"{total_seconds // 3600}h {(total_seconds % 3600) // 60}m"

    return {
        "valid": not expired,
        "expired": expired,
        "expiring_soon": expiring_soon,
        "expires_at": character.expires_at,
        "time_remaining": time_str,
        "can_refresh": bool(character.refresh_token),
    }


def is_sso_configured() -> bool:
    """Check if EVE SSO is properly configured."""
    return bool(settings.esi_client_id and settings.esi_secret_key)
