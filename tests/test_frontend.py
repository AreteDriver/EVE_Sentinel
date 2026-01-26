"""Tests for frontend routes and templates."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session_dependency
from backend.main import app
from backend.models.flags import FlagCategory, FlagSeverity, RiskFlag
from backend.models.report import AnalysisReport, OverallRisk, ReportStatus, ReportSummary


async def mock_session_override() -> AsyncIterator[AsyncSession]:
    """Override for database session dependency."""
    mock_session = MagicMock(spec=AsyncSession)
    yield mock_session


@pytest.fixture
def mock_report():
    """Create a mock analysis report."""
    return AnalysisReport(
        report_id=uuid4(),
        character_id=12345678,
        character_name="Test Pilot",
        overall_risk=OverallRisk.YELLOW,
        confidence=0.75,
        status=ReportStatus.COMPLETED,
        created_at=datetime.now(UTC),
        red_flag_count=1,
        yellow_flag_count=2,
        green_flag_count=1,
        flags=[
            RiskFlag(
                severity=FlagSeverity.RED,
                category=FlagCategory.CORP_HISTORY,
                code="KNOWN_SPY_CORP",
                reason="Member of known hostile corporation",
            ),
            RiskFlag(
                severity=FlagSeverity.YELLOW,
                category=FlagCategory.ACTIVITY,
                code="LOW_ACTIVITY",
                reason="Low activity in last 30 days",
            ),
            RiskFlag(
                severity=FlagSeverity.YELLOW,
                category=FlagCategory.KILLBOARD,
                code="HIGH_SEC_ONLY",
                reason="Primarily highsec activity",
            ),
            RiskFlag(
                severity=FlagSeverity.GREEN,
                category=FlagCategory.CORP_HISTORY,
                code="CLEAN_HISTORY",
                reason="No suspicious corp history",
            ),
        ],
        recommendations=["Review corp history manually", "Check for alt characters"],
    )


@pytest.fixture
def mock_summary(mock_report):
    """Create a mock report summary."""
    return ReportSummary(
        report_id=mock_report.report_id,
        character_id=mock_report.character_id,
        character_name=mock_report.character_name,
        overall_risk=mock_report.overall_risk,
        confidence=mock_report.confidence,
        red_flag_count=mock_report.red_flag_count,
        yellow_flag_count=mock_report.yellow_flag_count,
        green_flag_count=mock_report.green_flag_count,
        created_at=mock_report.created_at,
        status=mock_report.status,
    )


@pytest.fixture
def client():
    """Create a test client with mocked database."""
    app.dependency_overrides[get_session_dependency] = mock_session_override
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestDashboard:
    """Tests for dashboard page."""

    def test_dashboard_loads(self, client):
        """Dashboard should load successfully."""
        with patch("frontend.router.ReportRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.count_reports = AsyncMock(return_value=10)
            mock_repo.list_reports = AsyncMock(return_value=[])
            mock_repo_class.return_value = mock_repo

            response = client.get("/")

            assert response.status_code == 200
            assert "text/html" in response.headers["content-type"]
            assert "EVE Sentinel" in response.text
            assert "Dashboard" in response.text

    def test_dashboard_shows_stats(self, client, mock_summary):
        """Dashboard should display statistics."""
        with patch("frontend.router.ReportRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.count_reports = AsyncMock(side_effect=[100, 20, 30, 50])
            mock_repo.list_reports = AsyncMock(return_value=[mock_summary])
            mock_repo_class.return_value = mock_repo

            response = client.get("/")

            assert response.status_code == 200
            assert "100" in response.text  # Total
            assert "Test Pilot" in response.text


class TestReportsList:
    """Tests for reports list page."""

    def test_reports_list_loads(self, client, mock_summary):
        """Reports list should load successfully."""
        with patch("frontend.router.ReportRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.list_reports = AsyncMock(return_value=[mock_summary])
            mock_repo.count_reports = AsyncMock(return_value=1)
            mock_repo.get_all_flag_codes = AsyncMock(return_value=["FLAG_001", "FLAG_002"])
            mock_repo_class.return_value = mock_repo

            response = client.get("/reports")

            assert response.status_code == 200
            assert "text/html" in response.headers["content-type"]
            assert "Reports" in response.text
            assert "Test Pilot" in response.text

    def test_reports_list_with_filter(self, client, mock_summary):
        """Reports list should filter by risk level."""
        with patch("frontend.router.ReportRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.list_reports = AsyncMock(return_value=[mock_summary])
            mock_repo.count_reports = AsyncMock(return_value=1)
            mock_repo.get_all_flag_codes = AsyncMock(return_value=[])
            mock_repo_class.return_value = mock_repo

            response = client.get("/reports?risk=red")

            assert response.status_code == 200
            # Should call with RED filter
            mock_repo.list_reports.assert_called_once()
            call_kwargs = mock_repo.list_reports.call_args[1]
            assert call_kwargs["risk_filter"] == OverallRisk.RED

    def test_reports_list_pagination(self, client, mock_summary):
        """Reports list should handle pagination."""
        with patch("frontend.router.ReportRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.list_reports = AsyncMock(return_value=[mock_summary])
            mock_repo.count_reports = AsyncMock(return_value=100)
            mock_repo.get_all_flag_codes = AsyncMock(return_value=[])
            mock_repo_class.return_value = mock_repo

            response = client.get("/reports?page=3")

            assert response.status_code == 200
            call_kwargs = mock_repo.list_reports.call_args[1]
            assert call_kwargs["offset"] == 50  # (3-1) * 25


class TestReportDetail:
    """Tests for report detail page."""

    def test_report_detail_loads(self, client, mock_report):
        """Report detail should load successfully."""
        with patch("frontend.router.ReportRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.get_by_id = AsyncMock(return_value=mock_report)
            mock_repo_class.return_value = mock_repo

            response = client.get(f"/reports/{mock_report.report_id}")

            assert response.status_code == 200
            assert "text/html" in response.headers["content-type"]
            assert "Test Pilot" in response.text
            assert "KNOWN_SPY_CORP" in response.text

    def test_report_detail_not_found(self, client):
        """Report detail should return 404 for missing report."""
        with patch("frontend.router.ReportRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.get_by_id = AsyncMock(return_value=None)
            mock_repo_class.return_value = mock_repo

            response = client.get(f"/reports/{uuid4()}")

            assert response.status_code == 404

    def test_report_detail_shows_flags(self, client, mock_report):
        """Report detail should display all flag types."""
        with patch("frontend.router.ReportRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.get_by_id = AsyncMock(return_value=mock_report)
            mock_repo_class.return_value = mock_repo

            response = client.get(f"/reports/{mock_report.report_id}")

            assert "Red Flags" in response.text
            assert "Yellow Flags" in response.text
            assert "Green Flags" in response.text


class TestAnalyzePage:
    """Tests for analyze page."""

    def test_analyze_page_loads(self, client):
        """Analyze page should load successfully."""
        response = client.get("/analyze")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "New Analysis" in response.text
        assert "character_input" in response.text


class TestCharacterHistory:
    """Tests for character history page."""

    def test_character_history_loads(self, client, mock_report):
        """Character history should load successfully."""
        with patch("frontend.router.ReportRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.get_by_character_id = AsyncMock(return_value=[mock_report])
            mock_repo_class.return_value = mock_repo

            response = client.get("/character/12345678")

            assert response.status_code == 200
            assert "text/html" in response.headers["content-type"]
            assert "Test Pilot" in response.text
            assert "History" in response.text

    def test_character_history_not_found(self, client):
        """Character history should return 404 for unknown character."""
        with patch("frontend.router.ReportRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.get_by_character_id = AsyncMock(return_value=[])
            mock_repo_class.return_value = mock_repo

            response = client.get("/character/99999999")

            assert response.status_code == 404


class TestPartials:
    """Tests for HTMX partial endpoints."""

    def test_reports_table_partial(self, client, mock_summary):
        """Reports table partial should return HTML fragment."""
        with patch("frontend.router.ReportRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.list_reports = AsyncMock(return_value=[mock_summary])
            mock_repo.count_reports = AsyncMock(return_value=1)
            mock_repo_class.return_value = mock_repo

            response = client.get("/partials/reports-table")

            assert response.status_code == 200
            assert "Test Pilot" in response.text
            # Should not include full HTML document
            assert "<!DOCTYPE" not in response.text


class TestStaticFiles:
    """Tests for static file serving."""

    def test_css_served(self, client):
        """CSS files should be served correctly."""
        response = client.get("/static/css/sentinel.css")

        assert response.status_code == 200
        assert "text/css" in response.headers["content-type"]
        assert "--eve-bg-dark" in response.text


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    def test_health_check(self, client):
        """Health endpoint should return healthy status."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "eve-sentinel"
