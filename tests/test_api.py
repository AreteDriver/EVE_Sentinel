"""Tests for API endpoints."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.models.applicant import Applicant, CorpHistoryEntry, KillboardStats


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def mock_applicant():
    """Create a mock applicant for testing."""
    now = datetime.now(UTC)
    return Applicant(
        character_id=12345678,
        character_name="Test Pilot",
        corporation_id=98000001,
        corporation_name="Test Corp",
        alliance_id=99000001,
        alliance_name="Test Alliance",
        birthday=now - timedelta(days=365 * 3),
        security_status=2.5,
        character_age_days=365 * 3,
        corp_history=[
            CorpHistoryEntry(
                corporation_id=98000001,
                corporation_name="Test Corp",
                start_date=now - timedelta(days=200),
                end_date=None,
                duration_days=200,
            ),
        ],
        killboard=KillboardStats(
            kills_total=150,
            kills_90d=40,
            kills_30d=15,
            awox_kills=0,
        ),
    )


class TestRootEndpoints:
    """Tests for root-level endpoints."""

    def test_root_returns_api_info(self, client):
        """Root endpoint should return API info."""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "EVE Sentinel"
        assert data["version"] == "0.1.0"
        assert "endpoints" in data

    def test_health_check(self, client):
        """Health endpoint should return healthy status."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "eve-sentinel"


class TestAnalyzeEndpoint:
    """Tests for /api/v1/analyze/{character_id} endpoint."""

    def test_analyze_character_success(self, client, mock_applicant):
        """Successful analysis should return a report."""
        with (
            patch("backend.api.analyze.esi_client") as mock_esi,
            patch("backend.api.analyze.zkill_client") as mock_zkill,
        ):
            mock_esi.build_applicant = AsyncMock(return_value=mock_applicant)
            mock_zkill.enrich_applicant = AsyncMock(return_value=mock_applicant)

            response = client.post("/api/v1/analyze/12345678")

            assert response.status_code == 200
            data = response.json()
            assert data["character_id"] == 12345678
            assert data["character_name"] == "Test Pilot"
            assert "overall_risk" in data
            assert "flags" in data
            assert "recommendations" in data

    def test_analyze_with_requested_by(self, client, mock_applicant):
        """Analysis should record who requested it."""
        with (
            patch("backend.api.analyze.esi_client") as mock_esi,
            patch("backend.api.analyze.zkill_client") as mock_zkill,
        ):
            mock_esi.build_applicant = AsyncMock(return_value=mock_applicant)
            mock_zkill.enrich_applicant = AsyncMock(return_value=mock_applicant)

            response = client.post(
                "/api/v1/analyze/12345678", params={"requested_by": "TestRecruiter"}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["requested_by"] == "TestRecruiter"

    def test_analyze_handles_esi_error(self, client):
        """Analysis should return 500 on ESI error."""
        with patch("backend.api.analyze.esi_client") as mock_esi:
            mock_esi.build_applicant = AsyncMock(side_effect=Exception("ESI unavailable"))

            response = client.post("/api/v1/analyze/12345678")

            assert response.status_code == 500
            assert "ESI unavailable" in response.json()["detail"]


class TestQuickCheckEndpoint:
    """Tests for /api/v1/quick-check/{character_id} endpoint."""

    def test_quick_check_success(self, client, mock_applicant):
        """Quick check should return summary data."""
        with (
            patch("backend.api.analyze.esi_client") as mock_esi,
            patch("backend.api.analyze.zkill_client") as mock_zkill,
        ):
            mock_esi.build_applicant = AsyncMock(return_value=mock_applicant)
            mock_zkill.enrich_applicant = AsyncMock(return_value=mock_applicant)

            response = client.get("/api/v1/quick-check/12345678")

            assert response.status_code == 200
            data = response.json()
            assert data["character_id"] == 12345678
            assert data["character_name"] == "Test Pilot"
            assert "overall_risk" in data
            assert "confidence" in data
            assert "red_flags" in data
            assert "yellow_flags" in data
            assert "green_flags" in data
            assert "quick_summary" in data

    def test_quick_check_handles_error(self, client):
        """Quick check should return 500 on error."""
        with patch("backend.api.analyze.esi_client") as mock_esi:
            mock_esi.build_applicant = AsyncMock(side_effect=Exception("API error"))

            response = client.get("/api/v1/quick-check/12345678")

            assert response.status_code == 500


class TestBatchAnalyzeEndpoint:
    """Tests for /api/v1/analyze/batch endpoint."""

    def test_batch_analyze_success(self, client, mock_applicant):
        """Batch analysis should process multiple characters."""
        with (
            patch("backend.api.analyze.esi_client") as mock_esi,
            patch("backend.api.analyze.zkill_client") as mock_zkill,
        ):
            mock_esi.build_applicant = AsyncMock(return_value=mock_applicant)
            mock_zkill.enrich_applicant = AsyncMock(return_value=mock_applicant)

            response = client.post(
                "/api/v1/analyze/batch",
                json={"character_ids": [12345678, 87654321]},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["total_requested"] == 2
            assert data["completed"] == 2
            assert data["failed"] == 0
            assert len(data["reports"]) == 2

    def test_batch_analyze_partial_failure(self, client, mock_applicant):
        """Batch should continue on individual failures."""
        call_count = 0

        async def mock_build_applicant(char_id):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("First character failed")
            return mock_applicant

        with (
            patch("backend.api.analyze.esi_client") as mock_esi,
            patch("backend.api.analyze.zkill_client") as mock_zkill,
        ):
            mock_esi.build_applicant = mock_build_applicant
            mock_zkill.enrich_applicant = AsyncMock(return_value=mock_applicant)

            response = client.post(
                "/api/v1/analyze/batch",
                json={"character_ids": [11111111, 22222222]},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["total_requested"] == 2
            assert data["completed"] == 1
            assert data["failed"] == 1

    def test_batch_analyze_with_requested_by(self, client, mock_applicant):
        """Batch should pass requested_by to reports."""
        with (
            patch("backend.api.analyze.esi_client") as mock_esi,
            patch("backend.api.analyze.zkill_client") as mock_zkill,
        ):
            mock_esi.build_applicant = AsyncMock(return_value=mock_applicant)
            mock_zkill.enrich_applicant = AsyncMock(return_value=mock_applicant)

            response = client.post(
                "/api/v1/analyze/batch",
                json={"character_ids": [12345678], "requested_by": "BatchTester"},
            )

            assert response.status_code == 200

    def test_batch_analyze_empty_list(self, client):
        """Batch with empty list should return empty results."""
        response = client.post(
            "/api/v1/analyze/batch",
            json={"character_ids": []},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total_requested"] == 0
        assert data["completed"] == 0
        assert data["failed"] == 0
        assert data["reports"] == []


class TestAnalyzeByNameEndpoint:
    """Tests for /api/v1/analyze/by-name/{character_name} endpoint."""

    def test_analyze_by_name_success(self, client, mock_applicant):
        """Analyze by name should search and analyze."""
        with (
            patch("backend.api.analyze.esi_client") as mock_esi,
            patch("backend.api.analyze.zkill_client") as mock_zkill,
        ):
            mock_esi.search_character = AsyncMock(return_value=12345678)
            mock_esi.build_applicant = AsyncMock(return_value=mock_applicant)
            mock_zkill.enrich_applicant = AsyncMock(return_value=mock_applicant)

            response = client.get("/api/v1/analyze/by-name/Test%20Pilot")

            assert response.status_code == 200
            data = response.json()
            assert data["character_name"] == "Test Pilot"

    def test_analyze_by_name_not_found(self, client):
        """Analyze by name should return 404 if not found."""
        with patch("backend.api.analyze.esi_client") as mock_esi:
            mock_esi.search_character = AsyncMock(return_value=None)

            response = client.get("/api/v1/analyze/by-name/NonexistentPilot")

            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()
