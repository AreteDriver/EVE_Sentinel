"""Tests for EVE SSO authentication."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.sso import (
    EVECharacter,
    is_sso_configured,
    is_token_expired,
    is_token_expiring_soon,
    parse_jwt_token,
    token_time_remaining,
)


@pytest.fixture
def client():
    """Create a test client."""
    with TestClient(app) as client:
        yield client


class TestSSOConfiguration:
    """Tests for SSO configuration checks."""

    def test_is_sso_configured_returns_false_when_not_set(self):
        """Test that SSO is not configured by default."""
        with patch("backend.sso.settings") as mock_settings:
            mock_settings.esi_client_id = None
            mock_settings.esi_secret_key = None
            assert is_sso_configured() is False

    def test_is_sso_configured_returns_true_when_set(self):
        """Test that SSO is configured when credentials are set."""
        with patch("backend.sso.settings") as mock_settings:
            mock_settings.esi_client_id = "test-client-id"
            mock_settings.esi_secret_key = "test-secret"
            assert is_sso_configured() is True

    def test_is_sso_configured_requires_both_values(self):
        """Test that both client ID and secret are required."""
        with patch("backend.sso.settings") as mock_settings:
            mock_settings.esi_client_id = "test-client-id"
            mock_settings.esi_secret_key = None
            assert is_sso_configured() is False

            mock_settings.esi_client_id = None
            mock_settings.esi_secret_key = "test-secret"
            assert is_sso_configured() is False


class TestJWTTokenParsing:
    """Tests for JWT token parsing."""

    def test_parse_valid_jwt_token(self):
        """Test parsing a valid EVE SSO JWT token."""
        import base64
        import json

        # Create a mock JWT payload
        payload = {
            "sub": "CHARACTER:EVE:12345678",
            "name": "Test Pilot",
            "scp": ["esi-characters.read_standings.v1"],
            "exp": int(datetime.now(UTC).timestamp()) + 3600,
        }

        # Encode payload
        payload_bytes = json.dumps(payload).encode()
        payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode().rstrip("=")

        # Create mock JWT (header.payload.signature)
        mock_jwt = f"eyJhbGciOiJSUzI1NiJ9.{payload_b64}.signature"

        token = {
            "access_token": mock_jwt,
            "token_type": "Bearer",
            "refresh_token": "mock_refresh_token",
        }

        character = parse_jwt_token(token)

        assert character is not None
        assert character.character_id == 12345678
        assert character.character_name == "Test Pilot"
        assert "esi-characters.read_standings.v1" in character.scopes
        assert character.refresh_token == "mock_refresh_token"

    def test_parse_invalid_jwt_returns_none(self):
        """Test that invalid JWT returns None."""
        token = {"access_token": "invalid-token"}
        assert parse_jwt_token(token) is None

    def test_parse_empty_token_returns_none(self):
        """Test that empty token returns None."""
        token = {"access_token": ""}
        assert parse_jwt_token(token) is None

    def test_parse_token_without_access_token_returns_none(self):
        """Test that token without access_token returns None."""
        token = {}
        assert parse_jwt_token(token) is None


class TestEVECharacterModel:
    """Tests for EVECharacter model."""

    def test_create_character(self):
        """Test creating an EVECharacter instance."""
        character = EVECharacter(
            character_id=12345678,
            character_name="Test Pilot",
            scopes=["scope1", "scope2"],
            access_token="test_token",
            refresh_token="refresh_token",
        )

        assert character.character_id == 12345678
        assert character.character_name == "Test Pilot"
        assert len(character.scopes) == 2
        assert character.token_type == "Bearer"

    def test_character_serialization(self):
        """Test that EVECharacter can be serialized to JSON."""
        character = EVECharacter(
            character_id=12345678,
            character_name="Test Pilot",
            access_token="test_token",
        )

        data = character.model_dump(mode="json")
        assert data["character_id"] == 12345678
        assert data["character_name"] == "Test Pilot"


class TestAuthStatusEndpoint:
    """Tests for the /auth/status endpoint."""

    def test_auth_status_returns_200(self, client):
        """Test that auth status endpoint returns 200."""
        response = client.get("/api/v1/auth/status")
        assert response.status_code == 200

    def test_auth_status_not_authenticated_by_default(self, client):
        """Test that user is not authenticated by default."""
        response = client.get("/api/v1/auth/status")
        data = response.json()

        assert data["authenticated"] is False
        assert data["character_id"] is None
        assert data["character_name"] is None

    def test_auth_status_includes_sso_configured(self, client):
        """Test that auth status includes SSO configuration status."""
        response = client.get("/api/v1/auth/status")
        data = response.json()

        assert "sso_configured" in data
        assert isinstance(data["sso_configured"], bool)


class TestSSOConfigEndpoint:
    """Tests for the /auth/sso-config endpoint."""

    def test_sso_config_returns_200(self, client):
        """Test that SSO config endpoint returns 200."""
        response = client.get("/api/v1/auth/sso-config")
        assert response.status_code == 200

    def test_sso_config_has_required_fields(self, client):
        """Test that SSO config has required fields."""
        response = client.get("/api/v1/auth/sso-config")
        data = response.json()

        assert "configured" in data
        assert "callback_url" in data
        assert "available_scopes" in data

    def test_sso_config_includes_default_scopes(self, client):
        """Test that SSO config includes default scopes."""
        response = client.get("/api/v1/auth/sso-config")
        data = response.json()

        scopes = data["available_scopes"]
        assert "esi-characters.read_standings.v1" in scopes
        assert "esi-wallet.read_character_wallet.v1" in scopes


class TestLoginEndpoint:
    """Tests for the /auth/login endpoint."""

    def test_login_returns_503_when_not_configured(self, client):
        """Test that login returns 503 when SSO is not configured."""
        response = client.get("/api/v1/auth/login", follow_redirects=False)
        # Should be 503 since SSO is not configured by default
        assert response.status_code == 503


class TestLogoutEndpoint:
    """Tests for the /auth/logout endpoint."""

    def test_logout_redirects(self, client):
        """Test that logout redirects to home."""
        response = client.get("/api/v1/auth/logout", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/"

    def test_logout_with_custom_redirect(self, client):
        """Test logout with custom redirect URI."""
        response = client.get(
            "/api/v1/auth/logout?redirect_uri=/reports",
            follow_redirects=False,
        )
        assert response.status_code == 307
        assert response.headers["location"] == "/reports"


class TestMeEndpoint:
    """Tests for the /auth/me endpoint."""

    def test_me_returns_401_when_not_authenticated(self, client):
        """Test that /me returns 401 when not authenticated."""
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 401


class TestTokenManagement:
    """Tests for token management functions."""

    @pytest.fixture
    def valid_character(self):
        """Create a character with valid token."""
        return EVECharacter(
            character_id=12345,
            character_name="Test Pilot",
            access_token="test_token",
            refresh_token="refresh_token",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

    @pytest.fixture
    def expiring_character(self):
        """Create a character with expiring token."""
        return EVECharacter(
            character_id=12345,
            character_name="Test Pilot",
            access_token="test_token",
            refresh_token="refresh_token",
            expires_at=datetime.now(UTC) + timedelta(minutes=3),  # Less than 5 min threshold
        )

    @pytest.fixture
    def expired_character(self):
        """Create a character with expired token."""
        return EVECharacter(
            character_id=12345,
            character_name="Test Pilot",
            access_token="test_token",
            refresh_token="refresh_token",
            expires_at=datetime.now(UTC) - timedelta(minutes=5),
        )

    def test_is_token_expired_returns_false_for_valid_token(self, valid_character):
        """Test that valid token is not expired."""
        assert is_token_expired(valid_character) is False

    def test_is_token_expired_returns_true_for_expired_token(self, expired_character):
        """Test that expired token is detected."""
        assert is_token_expired(expired_character) is True

    def test_is_token_expired_returns_false_when_no_expiry(self):
        """Test that token without expiry is not considered expired."""
        character = EVECharacter(
            character_id=12345,
            character_name="Test",
            access_token="token",
        )
        assert is_token_expired(character) is False

    def test_is_token_expiring_soon_returns_false_for_valid_token(self, valid_character):
        """Test that valid token is not expiring soon."""
        assert is_token_expiring_soon(valid_character) is False

    def test_is_token_expiring_soon_returns_true_for_expiring_token(self, expiring_character):
        """Test that expiring token is detected."""
        assert is_token_expiring_soon(expiring_character) is True

    def test_is_token_expiring_soon_returns_true_for_expired_token(self, expired_character):
        """Test that expired token counts as expiring soon."""
        assert is_token_expiring_soon(expired_character) is True

    def test_token_time_remaining_returns_timedelta(self, valid_character):
        """Test that time remaining is returned as timedelta."""
        remaining = token_time_remaining(valid_character)
        assert isinstance(remaining, timedelta)
        assert remaining.total_seconds() > 0

    def test_token_time_remaining_returns_zero_for_expired(self, expired_character):
        """Test that expired token returns zero timedelta."""
        remaining = token_time_remaining(expired_character)
        assert remaining == timedelta(0)

    def test_token_time_remaining_returns_none_when_no_expiry(self):
        """Test that token without expiry returns None."""
        character = EVECharacter(
            character_id=12345,
            character_name="Test",
            access_token="token",
        )
        assert token_time_remaining(character) is None


class TestTokenStatusEndpoint:
    """Tests for the /auth/token-status endpoint."""

    def test_token_status_returns_401_when_not_authenticated(self, client):
        """Test that token-status returns 401 when not authenticated."""
        response = client.get("/api/v1/auth/token-status")
        assert response.status_code == 401


class TestAuthStatusTokenInfo:
    """Tests for token info in auth status response."""

    def test_auth_status_includes_token_fields(self, client):
        """Test that auth status includes token-related fields."""
        response = client.get("/api/v1/auth/status")
        data = response.json()

        assert "token_valid" in data
        assert "token_expiring_soon" in data
        assert "time_remaining" in data
