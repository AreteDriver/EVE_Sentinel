"""Test configuration and shared fixtures."""

import pytest


@pytest.fixture(autouse=True)
def disable_rate_limiting():
    """Disable rate limiting for all tests."""
    from backend.rate_limit import limiter

    # Store original state
    original_enabled = limiter.enabled

    # Disable rate limiting
    limiter.enabled = False

    yield

    # Restore original state
    limiter.enabled = original_enabled
