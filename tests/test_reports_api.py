"""Tests for reports API endpoints."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.database import get_session_dependency
from backend.main import app
from backend.models.applicant import Applicant, KillboardStats
from backend.models.report import AnalysisReport, OverallRisk, ReportStatus


@pytest.fixture
def sample_report():
    """Create a sample report for testing."""
    report_id = uuid4()
    return AnalysisReport(
        report_id=report_id,
        character_id=12345678,
        character_name="Test Pilot",
        overall_risk=OverallRisk.GREEN,
        status=ReportStatus.COMPLETED,
        confidence=0.85,
        created_at=datetime.now(UTC),
        applicant_data=Applicant(
            character_id=12345678,
            character_name="Test Pilot",
            corporation_id=98000001,
            corporation_name="Test Corp",
            birthday=datetime.now(UTC),
            killboard=KillboardStats(
                kills_total=100,
                deaths_total=20,
                kills_90d=50,
            ),
        ),
    )


@pytest.fixture
def mock_repo_with_report(sample_report):
    """Create a mock repository that returns the sample report."""
    mock_repo = MagicMock()
    mock_repo.get_by_id = AsyncMock(return_value=sample_report)
    mock_repo.list_reports = AsyncMock(return_value=[])
    mock_repo.get_by_character_id = AsyncMock(return_value=[sample_report])
    mock_repo.get_latest_by_character_id = AsyncMock(return_value=sample_report)
    mock_repo.delete_by_id = AsyncMock(return_value=True)
    return mock_repo


@pytest.fixture
def client(mock_repo_with_report):
    """Create a test client with mocked database."""

    async def mock_session():
        yield MagicMock()

    app.dependency_overrides[get_session_dependency] = mock_session

    with patch("backend.api.reports.ReportRepository") as mock_repo_class:
        mock_repo_class.return_value = mock_repo_with_report
        yield TestClient(app)

    app.dependency_overrides.clear()


class TestListReports:
    """Tests for the list reports endpoint."""

    def test_list_reports_returns_200(self, client):
        """Test that list reports returns 200."""
        response = client.get("/api/v1/reports")
        assert response.status_code == 200

    def test_list_reports_returns_list(self, client):
        """Test that list reports returns a list."""
        response = client.get("/api/v1/reports")
        assert isinstance(response.json(), list)

    def test_list_reports_with_limit(self, client):
        """Test that list reports respects limit parameter."""
        response = client.get("/api/v1/reports?limit=10")
        assert response.status_code == 200

    def test_list_reports_with_offset(self, client):
        """Test that list reports respects offset parameter."""
        response = client.get("/api/v1/reports?offset=5")
        assert response.status_code == 200

    def test_list_reports_with_risk_filter(self, client):
        """Test that list reports respects risk filter."""
        response = client.get("/api/v1/reports?risk=RED")
        assert response.status_code == 200


class TestGetReport:
    """Tests for the get report endpoint."""

    def test_get_report_returns_200(self, client, sample_report):
        """Test that get report returns 200."""
        response = client.get(f"/api/v1/reports/{sample_report.report_id}")
        assert response.status_code == 200

    def test_get_report_returns_report_data(self, client, sample_report):
        """Test that get report returns report data."""
        response = client.get(f"/api/v1/reports/{sample_report.report_id}")
        data = response.json()

        assert "report_id" in data
        assert "character_name" in data
        assert "overall_risk" in data


class TestGetReportPDF:
    """Tests for the PDF export endpoint."""

    def test_get_pdf_returns_200(self, client, sample_report):
        """Test that get PDF returns 200."""
        response = client.get(f"/api/v1/reports/{sample_report.report_id}/pdf")
        assert response.status_code == 200

    def test_get_pdf_returns_pdf_content_type(self, client, sample_report):
        """Test that get PDF returns correct content type."""
        response = client.get(f"/api/v1/reports/{sample_report.report_id}/pdf")
        assert response.headers["content-type"] == "application/pdf"

    def test_get_pdf_has_content_disposition(self, client, sample_report):
        """Test that get PDF has content disposition header."""
        response = client.get(f"/api/v1/reports/{sample_report.report_id}/pdf")
        assert "content-disposition" in response.headers
        assert "attachment" in response.headers["content-disposition"]
        assert ".pdf" in response.headers["content-disposition"]

    def test_get_pdf_returns_valid_pdf(self, client, sample_report):
        """Test that get PDF returns valid PDF content."""
        response = client.get(f"/api/v1/reports/{sample_report.report_id}/pdf")
        # PDF files start with %PDF
        assert response.content[:4] == b"%PDF"


class TestGetReportNotFound:
    """Tests for report not found scenarios."""

    def test_get_nonexistent_report_returns_404(self):
        """Test that getting nonexistent report returns 404."""

        async def mock_session():
            yield MagicMock()

        app.dependency_overrides[get_session_dependency] = mock_session

        mock_repo = MagicMock()
        mock_repo.get_by_id = AsyncMock(return_value=None)

        with patch("backend.api.reports.ReportRepository") as mock_repo_class:
            mock_repo_class.return_value = mock_repo
            with TestClient(app) as client:
                response = client.get(f"/api/v1/reports/{uuid4()}")
                assert response.status_code == 404

        app.dependency_overrides.clear()


class TestCharacterReports:
    """Tests for character-specific report endpoints."""

    def test_get_character_reports_returns_200(self, client):
        """Test that get character reports returns 200."""
        response = client.get("/api/v1/reports/character/12345678")
        assert response.status_code == 200

    def test_get_character_reports_returns_list(self, client):
        """Test that get character reports returns a list."""
        response = client.get("/api/v1/reports/character/12345678")
        assert isinstance(response.json(), list)

    def test_get_character_latest_returns_200(self, client):
        """Test that get latest character report returns 200."""
        response = client.get("/api/v1/reports/character/12345678/latest")
        assert response.status_code == 200


class TestDeleteReport:
    """Tests for the delete report endpoint."""

    def test_delete_report_returns_204(self, client, sample_report):
        """Test that delete report returns 204."""
        response = client.delete(f"/api/v1/reports/{sample_report.report_id}")
        assert response.status_code == 204

    def test_delete_nonexistent_report_returns_404(self):
        """Test that deleting nonexistent report returns 404."""

        async def mock_session():
            yield MagicMock()

        app.dependency_overrides[get_session_dependency] = mock_session

        mock_repo = MagicMock()
        mock_repo.delete_by_id = AsyncMock(return_value=False)

        with patch("backend.api.reports.ReportRepository") as mock_repo_class:
            mock_repo_class.return_value = mock_repo
            with TestClient(app) as client:
                response = client.delete(f"/api/v1/reports/{uuid4()}")
                assert response.status_code == 404

        app.dependency_overrides.clear()


class TestBulkPDF:
    """Tests for the bulk PDF export endpoint."""

    def test_bulk_pdf_empty_list_returns_400(self, client):
        """Test that bulk PDF with empty list returns 400."""
        response = client.post("/api/v1/reports/bulk-pdf", json={"report_ids": []})
        assert response.status_code == 400

    def test_bulk_pdf_too_many_reports_returns_400(self, client):
        """Test that bulk PDF with too many reports returns 400."""
        # Create 51 UUIDs
        report_ids = [str(uuid4()) for _ in range(51)]
        response = client.post("/api/v1/reports/bulk-pdf", json={"report_ids": report_ids})
        assert response.status_code == 400

    def test_bulk_pdf_returns_zip(self, client, sample_report):
        """Test that bulk PDF returns a ZIP file."""
        response = client.post(
            "/api/v1/reports/bulk-pdf", json={"report_ids": [str(sample_report.report_id)]}
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        # ZIP files start with PK
        assert response.content[:2] == b"PK"
