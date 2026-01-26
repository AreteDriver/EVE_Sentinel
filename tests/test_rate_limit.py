"""Tests for rate limiting functionality."""

import pytest
from starlette.testclient import TestClient

from backend.rate_limit import LIMITS, get_key_func, limiter


class TestRateLimitConfig:
    """Tests for rate limit configuration."""

    def test_limiter_has_default_limits(self):
        """Test that limiter has default limits configured."""
        assert limiter._default_limits is not None
        assert len(limiter._default_limits) > 0

    def test_limits_dict_has_required_keys(self):
        """Test that LIMITS dict has all required endpoint categories."""
        required_keys = [
            "analyze",
            "analyze_batch",
            "reports",
            "pdf",
            "bulk_pdf",
            "ml_train",
            "admin",
            "default",
        ]
        for key in required_keys:
            assert key in LIMITS, f"Missing rate limit key: {key}"

    def test_limits_format_is_valid(self):
        """Test that all limits are in valid format."""
        for key, value in LIMITS.items():
            # Should be in format "number/period"
            parts = value.split("/")
            assert len(parts) == 2, f"Invalid limit format for {key}: {value}"
            assert parts[0].isdigit(), f"First part should be numeric for {key}: {value}"
            assert parts[1] in ["second", "minute", "hour", "day"], \
                f"Invalid period for {key}: {value}"


class TestRateLimitKeyFunc:
    """Tests for the rate limit key function."""

    def test_key_func_returns_api_key_when_present(self):
        """Test that key function returns API key when provided in header."""
        from starlette.requests import Request
        from starlette.testclient import TestClient

        # Create a mock request with API key header
        scope = {
            "type": "http",
            "headers": [(b"x-api-key", b"test-key-123")],
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "server": ("localhost", 8000),
        }
        request = Request(scope)

        key = get_key_func(request)
        assert key == "api_key:test-key-123"

    def test_key_func_returns_api_key_from_query_param(self):
        """Test that key function returns API key when provided in query."""
        from starlette.requests import Request

        scope = {
            "type": "http",
            "headers": [],
            "method": "GET",
            "path": "/",
            "query_string": b"api_key=query-key-456",
            "server": ("localhost", 8000),
        }
        request = Request(scope)

        key = get_key_func(request)
        assert key == "api_key:query-key-456"

    def test_key_func_returns_ip_when_no_api_key(self):
        """Test that key function returns IP when no API key provided."""
        from starlette.requests import Request

        scope = {
            "type": "http",
            "headers": [],
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "server": ("localhost", 8000),
            "client": ("192.168.1.1", 12345),
        }
        request = Request(scope)

        key = get_key_func(request)
        assert key == "192.168.1.1"


class TestRateLimitValues:
    """Tests for specific rate limit values."""

    def test_analyze_limit_is_reasonable(self):
        """Test that analyze limit is reasonable."""
        limit_str = LIMITS["analyze"]
        count = int(limit_str.split("/")[0])
        assert 1 <= count <= 100, "Analyze limit should be between 1 and 100/minute"

    def test_batch_limit_is_stricter_than_single(self):
        """Test that batch analyze limit is stricter than single."""
        single_limit = int(LIMITS["analyze"].split("/")[0])
        batch_limit = int(LIMITS["analyze_batch"].split("/")[0])
        assert batch_limit < single_limit, "Batch limit should be stricter"

    def test_ml_train_is_most_restrictive(self):
        """Test that ML training has the most restrictive limit."""
        ml_limit_str = LIMITS["ml_train"]
        assert "hour" in ml_limit_str, "ML training should be limited per hour"
        count = int(ml_limit_str.split("/")[0])
        assert count <= 5, "ML training should be very restricted"
