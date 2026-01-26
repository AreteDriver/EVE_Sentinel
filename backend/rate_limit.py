"""Rate limiting configuration for EVE Sentinel API."""

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse

from backend.config import settings


def get_key_func(request: Request) -> str:
    """
    Get rate limit key from request.

    Uses API key if provided, otherwise falls back to IP address.
    This allows authenticated users to have separate rate limits.
    """
    # Check for API key in header or query
    api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")

    if api_key:
        return f"api_key:{api_key}"

    return get_remote_address(request)


# Create limiter instance
limiter = Limiter(
    key_func=get_key_func,
    default_limits=[settings.rate_limit_default],
    enabled=settings.rate_limit_enabled,
)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Custom handler for rate limit exceeded errors."""
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded",
            "message": str(exc.detail),
            "retry_after": exc.detail.split("per")[1].strip() if "per" in exc.detail else "60 seconds",
        },
    )


# Rate limit decorators for different endpoint types
# These can be applied to routes like: @limiter.limit("10/minute")

# Limits for different endpoint categories
LIMITS = {
    "analyze": "10/minute",  # Character analysis is expensive
    "analyze_batch": "2/minute",  # Batch analysis even more so
    "reports": "60/minute",  # Report retrieval is cheap
    "pdf": "20/minute",  # PDF generation is moderately expensive
    "bulk_pdf": "5/minute",  # Bulk PDF is expensive
    "ml_train": "1/hour",  # Model training is very expensive
    "admin": "30/minute",  # Admin endpoints
    "default": "100/minute",  # Default for unspecified endpoints
}
