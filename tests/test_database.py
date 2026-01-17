"""Tests for database persistence layer."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from backend.database.models import Base, ReportRecord
from backend.database.repository import ReportRepository
from backend.database.session import _get_async_url
from backend.models.applicant import Applicant, CorpHistoryEntry, KillboardStats
from backend.models.flags import FlagCategory, FlagSeverity, RiskFlag
from backend.models.report import AnalysisReport, OverallRisk, ReportStatus


@pytest.fixture
def sample_report():
    """Create a sample analysis report for testing."""
    return AnalysisReport(
        character_id=12345678,
        character_name="Test Pilot",
        overall_risk=OverallRisk.YELLOW,
        confidence=0.75,
        status=ReportStatus.COMPLETED,
        requested_by="test_recruiter",
        flags=[
            RiskFlag(
                severity=FlagSeverity.YELLOW,
                category=FlagCategory.CORP_HISTORY,
                code="SHORT_TENURE",
                reason="Short tenure in current corp",
            ),
            RiskFlag(
                severity=FlagSeverity.GREEN,
                category=FlagCategory.KILLBOARD,
                code="ACTIVE_PVPER",
                reason="Active PvP pilot",
            ),
        ],
        recommendations=["Monitor for first 30 days", "Standard onboarding"],
        analyzers_run=["CorpHistoryAnalyzer", "KillboardAnalyzer"],
        red_flag_count=0,
        yellow_flag_count=1,
        green_flag_count=1,
    )


@pytest.fixture
def sample_report_with_applicant():
    """Create a report with full applicant data."""
    now = datetime.now(UTC)
    applicant = Applicant(
        character_id=12345678,
        character_name="Test Pilot",
        corporation_id=98000001,
        corporation_name="Test Corp",
        birthday=now,
        security_status=2.5,
        corp_history=[
            CorpHistoryEntry(
                corporation_id=98000001,
                corporation_name="Test Corp",
                start_date=now,
                duration_days=100,
            ),
        ],
        killboard=KillboardStats(
            kills_total=50,
            kills_90d=20,
            kills_30d=10,
        ),
    )

    return AnalysisReport(
        character_id=12345678,
        character_name="Test Pilot",
        overall_risk=OverallRisk.GREEN,
        confidence=0.85,
        status=ReportStatus.COMPLETED,
        applicant_data=applicant,
        flags=[],
        recommendations=["Standard onboarding"],
        analyzers_run=["CorpHistoryAnalyzer"],
        green_flag_count=2,
    )


@pytest.fixture
def red_report():
    """Create a high-risk report."""
    return AnalysisReport(
        character_id=87654321,
        character_name="Risky Pilot",
        overall_risk=OverallRisk.RED,
        confidence=0.90,
        status=ReportStatus.COMPLETED,
        flags=[
            RiskFlag(
                severity=FlagSeverity.RED,
                category=FlagCategory.KILLBOARD,
                code="AWOX_HISTORY",
                reason="AWOX kills detected",
            ),
        ],
        recommendations=["Reject application"],
        analyzers_run=["KillboardAnalyzer"],
        red_flag_count=1,
    )


class TestAsyncUrl:
    """Tests for URL conversion."""

    def test_sqlite_url_converted(self):
        """SQLite URL should be converted to aiosqlite."""
        url = "sqlite:///./test.db"
        async_url = _get_async_url(url)
        assert async_url == "sqlite+aiosqlite:///./test.db"

    def test_non_sqlite_url_unchanged(self):
        """Non-SQLite URLs should be unchanged."""
        url = "postgresql://user:pass@localhost/db"
        async_url = _get_async_url(url)
        assert async_url == url


class TestReportRecord:
    """Tests for ReportRecord model."""

    def test_record_creation(self):
        """ReportRecord should be created with correct fields."""
        record = ReportRecord(
            report_id="test-uuid",
            character_id=12345678,
            character_name="Test Pilot",
            overall_risk="YELLOW",
            confidence=0.75,
            status="completed",
            created_at=datetime.now(UTC),
            red_flag_count=0,
            yellow_flag_count=1,
            green_flag_count=1,
            flags_json="[]",
            recommendations_json="[]",
            analyzers_run_json="[]",
            errors_json="[]",
            suspected_alts_json="[]",
        )

        assert record.report_id == "test-uuid"
        assert record.character_id == 12345678
        assert record.overall_risk == "YELLOW"


class TestReportRepository:
    """Tests for ReportRepository with in-memory database."""

    @pytest.fixture
    async def db_session(self):
        """Create an in-memory database session for testing."""
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with session_factory() as session:
            yield session

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_save_and_retrieve_by_id(self, db_session, sample_report):
        """Save a report and retrieve it by ID."""
        repo = ReportRepository(db_session)

        await repo.save(sample_report)
        retrieved = await repo.get_by_id(sample_report.report_id)

        assert retrieved is not None
        assert retrieved.report_id == sample_report.report_id
        assert retrieved.character_id == sample_report.character_id
        assert retrieved.character_name == sample_report.character_name
        assert retrieved.overall_risk == sample_report.overall_risk
        assert retrieved.confidence == sample_report.confidence

    @pytest.mark.asyncio
    async def test_retrieve_nonexistent_returns_none(self, db_session):
        """Retrieving non-existent report returns None."""
        repo = ReportRepository(db_session)

        result = await repo.get_by_id(uuid4())

        assert result is None

    @pytest.mark.asyncio
    async def test_flags_preserved(self, db_session, sample_report):
        """Flags should be preserved through save/load cycle."""
        repo = ReportRepository(db_session)

        await repo.save(sample_report)
        retrieved = await repo.get_by_id(sample_report.report_id)

        assert len(retrieved.flags) == 2
        assert retrieved.flags[0].severity == FlagSeverity.YELLOW
        assert retrieved.flags[0].code == "SHORT_TENURE"
        assert retrieved.flags[1].severity == FlagSeverity.GREEN

    @pytest.mark.asyncio
    async def test_recommendations_preserved(self, db_session, sample_report):
        """Recommendations should be preserved."""
        repo = ReportRepository(db_session)

        await repo.save(sample_report)
        retrieved = await repo.get_by_id(sample_report.report_id)

        assert retrieved.recommendations == sample_report.recommendations

    @pytest.mark.asyncio
    async def test_applicant_data_preserved(self, db_session, sample_report_with_applicant):
        """Applicant data should be preserved."""
        repo = ReportRepository(db_session)

        await repo.save(sample_report_with_applicant)
        retrieved = await repo.get_by_id(sample_report_with_applicant.report_id)

        assert retrieved.applicant_data is not None
        assert retrieved.applicant_data.character_id == 12345678
        assert retrieved.applicant_data.corporation_name == "Test Corp"
        assert len(retrieved.applicant_data.corp_history) == 1

    @pytest.mark.asyncio
    async def test_get_by_character_id(self, db_session, sample_report, red_report):
        """Get reports by character ID."""
        repo = ReportRepository(db_session)

        await repo.save(sample_report)
        await repo.save(red_report)

        results = await repo.get_by_character_id(12345678)

        assert len(results) == 1
        assert results[0].character_id == 12345678

    @pytest.mark.asyncio
    async def test_get_latest_by_character_id(self, db_session, sample_report):
        """Get most recent report for character."""
        repo = ReportRepository(db_session)

        # Save first report
        await repo.save(sample_report)

        # Create and save a newer report for same character
        newer_report = AnalysisReport(
            character_id=12345678,
            character_name="Test Pilot",
            overall_risk=OverallRisk.GREEN,
            confidence=0.90,
            status=ReportStatus.COMPLETED,
            flags=[],
            recommendations=[],
            analyzers_run=[],
        )
        await repo.save(newer_report)

        latest = await repo.get_latest_by_character_id(12345678)

        assert latest is not None
        assert latest.report_id == newer_report.report_id

    @pytest.mark.asyncio
    async def test_list_reports(self, db_session, sample_report, red_report):
        """List reports with pagination."""
        repo = ReportRepository(db_session)

        await repo.save(sample_report)
        await repo.save(red_report)

        summaries = await repo.list_reports(limit=10)

        assert len(summaries) == 2

    @pytest.mark.asyncio
    async def test_list_reports_with_risk_filter(self, db_session, sample_report, red_report):
        """Filter reports by risk level."""
        repo = ReportRepository(db_session)

        await repo.save(sample_report)
        await repo.save(red_report)

        red_only = await repo.list_reports(risk_filter=OverallRisk.RED)
        yellow_only = await repo.list_reports(risk_filter=OverallRisk.YELLOW)

        assert len(red_only) == 1
        assert red_only[0].overall_risk == OverallRisk.RED

        assert len(yellow_only) == 1
        assert yellow_only[0].overall_risk == OverallRisk.YELLOW

    @pytest.mark.asyncio
    async def test_list_reports_pagination(self, db_session):
        """Pagination should work correctly."""
        repo = ReportRepository(db_session)

        # Create 5 reports
        for i in range(5):
            report = AnalysisReport(
                character_id=1000000 + i,
                character_name=f"Pilot {i}",
                overall_risk=OverallRisk.GREEN,
                confidence=0.5,
                status=ReportStatus.COMPLETED,
                flags=[],
                recommendations=[],
                analyzers_run=[],
            )
            await repo.save(report)

        page1 = await repo.list_reports(limit=2, offset=0)
        page2 = await repo.list_reports(limit=2, offset=2)

        assert len(page1) == 2
        assert len(page2) == 2
        # They should be different reports
        assert page1[0].character_id != page2[0].character_id

    @pytest.mark.asyncio
    async def test_count_reports(self, db_session, sample_report, red_report):
        """Count reports with optional filter."""
        repo = ReportRepository(db_session)

        await repo.save(sample_report)
        await repo.save(red_report)

        total = await repo.count_reports()
        red_count = await repo.count_reports(risk_filter=OverallRisk.RED)

        assert total == 2
        assert red_count == 1

    @pytest.mark.asyncio
    async def test_delete_by_id(self, db_session, sample_report):
        """Delete report by ID."""
        repo = ReportRepository(db_session)

        await repo.save(sample_report)
        deleted = await repo.delete_by_id(sample_report.report_id)
        retrieved = await repo.get_by_id(sample_report.report_id)

        assert deleted is True
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self, db_session):
        """Deleting non-existent report returns False."""
        repo = ReportRepository(db_session)

        deleted = await repo.delete_by_id(uuid4())

        assert deleted is False

    @pytest.mark.asyncio
    async def test_update_existing_report(self, db_session, sample_report):
        """Saving existing report should update it."""
        repo = ReportRepository(db_session)

        await repo.save(sample_report)

        # Modify and save again
        sample_report.overall_risk = OverallRisk.RED
        sample_report.confidence = 0.95
        await repo.save(sample_report)

        retrieved = await repo.get_by_id(sample_report.report_id)

        assert retrieved.overall_risk == OverallRisk.RED
        assert retrieved.confidence == 0.95

        # Should still be only one report
        count = await repo.count_reports()
        assert count == 1
