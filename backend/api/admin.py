"""Admin API endpoints for EVE Sentinel."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.auth import generate_api_key
from backend.config import settings

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class AuthStatus(BaseModel):
    """Authentication status response."""

    auth_required: bool
    api_keys_configured: int


class GeneratedKey(BaseModel):
    """Generated API key response."""

    api_key: str
    message: str


@router.get("/auth-status", response_model=AuthStatus)
async def get_auth_status() -> AuthStatus:
    """
    Get current authentication status.

    Returns whether API key authentication is enabled and how many keys are configured.
    """
    return AuthStatus(
        auth_required=settings.require_api_key,
        api_keys_configured=len(settings.get_api_keys()),
    )


@router.post("/generate-key", response_model=GeneratedKey)
async def create_api_key() -> GeneratedKey:
    """
    Generate a new API key.

    NOTE: This endpoint is for development/testing only.
    In production, you should manually configure API keys via environment variables.

    The generated key must be added to the API_KEYS environment variable
    to be valid.
    """
    if settings.require_api_key:
        raise HTTPException(
            status_code=403,
            detail="Cannot generate keys when auth is required. Add keys manually to API_KEYS env var.",
        )

    new_key = generate_api_key()

    return GeneratedKey(
        api_key=new_key,
        message="Add this key to the API_KEYS environment variable to enable it.",
    )


@router.get("/config")
async def get_config() -> dict:
    """
    Get current configuration (non-sensitive values only).

    Returns configuration settings that are safe to expose.
    """
    return {
        "log_level": settings.log_level,
        "auth_required": settings.require_api_key,
        "auth_system": settings.auth_system,
        "auth_bridge_configured": bool(settings.auth_bridge_url),
        "discord_webhook_configured": bool(settings.discord_webhook_url),
        "hostile_corps_count": len(settings.get_hostile_corp_ids()),
        "hostile_alliances_count": len(settings.get_hostile_alliance_ids()),
    }
