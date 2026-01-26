"""Tests for PDF report generation."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from backend.models.applicant import Applicant, KillboardStats
from backend.models.flags import FlagCategory, FlagSeverity, RiskFlag
from backend.models.report import AnalysisReport, OverallRisk, ReportStatus
from backend.services.pdf_generator import PDFGenerator


@pytest.fixture
def sample_applicant() -> Applicant:
    """Create a sample applicant for testing."""
    return Applicant(
        character_id=12345678,
        character_name="Test Pilot",
        corporation_id=98765432,
        corporation_name="Test Corp",
        alliance_id=11111111,
        alliance_name="Test Alliance",
        character_age_days=365,
        security_status=2.5,
        killboard=KillboardStats(
            kills_total=100,
            kills_90d=25,
            deaths_total=20,
            awox_kills=0,
            isk_destroyed=50_000_000_000.0,
        ),
    )


@pytest.fixture
def sample_report(sample_applicant: Applicant) -> AnalysisReport:
    """Create a sample report for testing."""
    return AnalysisReport(
        report_id=uuid4(),
        character_id=sample_applicant.character_id,
        character_name=sample_applicant.character_name,
        status=ReportStatus.COMPLETED,
        overall_risk=OverallRisk.GREEN,
        confidence=0.8,
        flags=[
            RiskFlag(
                severity=FlagSeverity.GREEN,
                category=FlagCategory.KILLBOARD,
                code="ACTIVE_PVPER",
                reason="Character shows consistent PvP activity",
                evidence={"kills_90d": 25},
                confidence=0.9,
            ),
            RiskFlag(
                severity=FlagSeverity.YELLOW,
                category=FlagCategory.CORP_HISTORY,
                code="SHORT_TENURE",
                reason="Less than 3 months in current corporation",
                evidence={"days_in_corp": 45},
                confidence=0.8,
            ),
        ],
        recommendations=["Low risk indicators - standard onboarding appropriate"],
        applicant_data=sample_applicant,
        analyzers_run=["KillboardAnalyzer", "CorpHistoryAnalyzer"],
        processing_time_ms=150,
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )


def test_pdf_generator_creates_pdf(sample_report: AnalysisReport) -> None:
    """Test that PDF generator creates valid PDF bytes."""
    generator = PDFGenerator()
    pdf_content = generator.generate(sample_report)

    # Check that we got bytes back
    assert isinstance(pdf_content, bytes)
    assert len(pdf_content) > 0

    # Check PDF magic bytes
    assert pdf_content.startswith(b"%PDF")


def test_pdf_generator_filename(sample_report: AnalysisReport) -> None:
    """Test filename generation."""
    generator = PDFGenerator()
    filename = generator.generate_filename(sample_report)

    assert filename.startswith("sentinel_report_")
    assert filename.endswith(".pdf")
    assert "Test_Pilot" in filename


def test_pdf_generator_handles_special_characters() -> None:
    """Test filename generation with special characters."""
    report = AnalysisReport(
        character_id=1,
        character_name="Pilot <With> Special/Chars",
        status=ReportStatus.COMPLETED,
    )

    generator = PDFGenerator()
    filename = generator.generate_filename(report)

    # Should not contain special characters
    assert "<" not in filename
    assert ">" not in filename
    assert "/" not in filename


def test_pdf_generator_with_no_flags() -> None:
    """Test PDF generation with empty flags."""
    report = AnalysisReport(
        character_id=1,
        character_name="Empty Report Pilot",
        status=ReportStatus.COMPLETED,
        flags=[],
    )

    generator = PDFGenerator()
    pdf_content = generator.generate(report)

    assert isinstance(pdf_content, bytes)
    assert pdf_content.startswith(b"%PDF")
