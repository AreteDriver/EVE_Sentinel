"""API key authentication for EVE Sentinel."""

import hashlib
import secrets
from datetime import datetime

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, APIKeyQuery
from pydantic import BaseModel

from backend.config import settings

# API key can be passed in header or query parameter
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
api_key_query = APIKeyQuery(name="api_key", auto_error=False)


class APIKeyInfo(BaseModel):
    """Information about an API key."""

    key_id: str
    name: str
    created_at: datetime
    last_used: datetime | None = None
    scopes: list[str] = []


def hash_api_key(api_key: str) -> str:
    """Hash an API key for secure storage."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def generate_api_key() -> str:
    """Generate a new API key."""
    return f"sk_sentinel_{secrets.token_urlsafe(32)}"


def validate_api_key(api_key: str) -> bool:
    """
    Validate an API key against configured keys.

    In production, this would check against a database.
    For now, it checks against environment-configured keys.
    """
    if not api_key:
        return False

    # Check against configured API keys
    configured_keys = settings.get_api_keys()

    if not configured_keys:
        # No keys configured = auth disabled
        return True

    return api_key in configured_keys


async def get_api_key(
    api_key_header: str | None = Security(api_key_header),
    api_key_query: str | None = Security(api_key_query),
) -> str | None:
    """
    Extract API key from request (header or query parameter).

    Returns None if no key provided and auth is not required.
    Raises HTTPException if auth is required but key is invalid.
    """
    api_key = api_key_header or api_key_query

    # Check if auth is required
    if not settings.require_api_key:
        return api_key  # Auth not required, return whatever we have

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required. Provide via X-API-Key header or api_key query parameter.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if not validate_api_key(api_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )

    return api_key


async def require_api_key(
    api_key: str | None = Depends(get_api_key),
) -> str:
    """
    Dependency that requires a valid API key.

    Use this for endpoints that must always be authenticated.
    """
    if settings.require_api_key and not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if api_key and not validate_api_key(api_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )

    return api_key or ""


async def optional_api_key(
    api_key: str | None = Depends(get_api_key),
) -> str | None:
    """
    Dependency that optionally accepts an API key.

    Use this for endpoints that work without auth but may have
    different behavior with auth.
    """
    return api_key
