"""EVE Online SSO OAuth2 authentication."""

from datetime import UTC, datetime
from typing import Any

from authlib.integrations.starlette_client import OAuth
from pydantic import BaseModel
from starlette.requests import Request

from backend.config import settings


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


async def refresh_token_if_needed(
    oauth: OAuth,
    character: EVECharacter,
) -> EVECharacter | None:
    """
    Refresh the access token if it's expired or about to expire.

    Returns updated character or None if refresh failed.
    """
    if not character.refresh_token:
        return None

    if character.expires_at:
        # Refresh if expires in less than 5 minutes
        now = datetime.now(UTC)
        if (character.expires_at - now).total_seconds() > 300:
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
            return updated

    except Exception:
        pass

    return None


def is_sso_configured() -> bool:
    """Check if EVE SSO is properly configured."""
    return bool(settings.esi_client_id and settings.esi_secret_key)
