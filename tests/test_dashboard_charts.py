"""Tests for dashboard chart data endpoints and repository methods."""

import json
import pytest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from backend.database.repository import ReportRepository
from backend.api.reports import DashboardStats


class TestReportRepositoryChartMethods:
    """Tests for ReportRepository chart data methods."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock async session."""
        session = MagicMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def repo(self, mock_session):
        """Create a ReportRepository with mock session."""
        return ReportRepository(mock_session)

    @pytest.mark.asyncio
    async def test_get_reports_by_date_range_returns_list(self, repo, mock_session):
        """Test that get_reports_by_date_range returns a list."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await repo.get_reports_by_date_range(days=30)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_get_reports_by_date_range_groups_by_date(self, repo, mock_session):
        """Test that reports are grouped by date."""
        # Create mock records
        record1 = MagicMock()
        record1.created_at = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
        record1.overall_risk = "red"

        record2 = MagicMock()
        record2.created_at = datetime(2024, 1, 15, 14, 0, tzinfo=UTC)
        record2.overall_risk = "green"

        record3 = MagicMock()
        record3.created_at = datetime(2024, 1, 16, 10, 0, tzinfo=UTC)
        record3.overall_risk = "yellow"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [record1, record2, record3]
        mock_session.execute.return_value = mock_result

        result = await repo.get_reports_by_date_range(days=30)

        # Should have 2 dates
        assert len(result) == 2

        # Check first date (2024-01-15)
        day1 = next(d for d in result if d["date"] == "2024-01-15")
        assert day1["red"] == 1
        assert day1["green"] == 1
        assert day1["yellow"] == 0
        assert day1["total"] == 2

        # Check second date (2024-01-16)
        day2 = next(d for d in result if d["date"] == "2024-01-16")
        assert day2["yellow"] == 1
        assert day2["total"] == 1

    @pytest.mark.asyncio
    async def test_get_top_flags_returns_list(self, repo, mock_session):
        """Test that get_top_flags returns a list."""
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await repo.get_top_flags(limit=10)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_get_top_flags_counts_correctly(self, repo, mock_session):
        """Test that flags are counted correctly."""
        flags1 = json.dumps([
            {"code": "HOSTILE_CORP", "title": "Hostile Corp", "severity": "red"},
            {"code": "LOW_ACTIVITY", "title": "Low Activity", "severity": "yellow"},
        ])
        flags2 = json.dumps([
            {"code": "HOSTILE_CORP", "title": "Hostile Corp", "severity": "red"},
        ])

        mock_result = MagicMock()
        mock_result.all.return_value = [(flags1,), (flags2,)]
        mock_session.execute.return_value = mock_result

        result = await repo.get_top_flags(limit=10)

        # HOSTILE_CORP should be first with count 2
        assert result[0]["code"] == "HOSTILE_CORP"
        assert result[0]["count"] == 2

        # LOW_ACTIVITY should be second with count 1
        assert result[1]["code"] == "LOW_ACTIVITY"
        assert result[1]["count"] == 1

    @pytest.mark.asyncio
    async def test_get_top_flags_respects_limit(self, repo, mock_session):
        """Test that get_top_flags respects the limit parameter."""
        # Create 15 different flags
        flags_data = []
        for i in range(15):
            flag = json.dumps([
                {"code": f"FLAG_{i}", "title": f"Flag {i}", "severity": "yellow"}
            ])
            flags_data.append((flag,))

        mock_result = MagicMock()
        mock_result.all.return_value = flags_data
        mock_session.execute.return_value = mock_result

        result = await repo.get_top_flags(limit=5)

        assert len(result) <= 5

    @pytest.mark.asyncio
    async def test_get_recent_activity_returns_dict(self, repo, mock_session):
        """Test that get_recent_activity returns a dict."""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 10
        mock_session.execute.return_value = mock_result

        result = await repo.get_recent_activity(days=7)

        assert isinstance(result, dict)
        assert "reports_last_7_days" in result
        assert "avg_per_day" in result

    @pytest.mark.asyncio
    async def test_get_recent_activity_calculates_average(self, repo, mock_session):
        """Test that average per day is calculated correctly."""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 14
        mock_session.execute.return_value = mock_result

        result = await repo.get_recent_activity(days=7)

        assert result["reports_last_7_days"] == 14
        assert result["avg_per_day"] == 2.0


class TestDashboardStatsModel:
    """Tests for the DashboardStats Pydantic model."""

    def test_dashboard_stats_model_validates(self):
        """Test that DashboardStats model validates correctly."""
        data = DashboardStats(
            total=100,
            red=30,
            yellow=40,
            green=30,
            reports_last_7_days=14,
            avg_per_day=2.0,
            time_series=[{"date": "2024-01-15", "red": 1, "yellow": 2, "green": 1}],
            top_flags=[{"code": "FLAG1", "count": 5}],
        )

        assert data.total == 100
        assert data.red == 30
        assert len(data.time_series) == 1
        assert len(data.top_flags) == 1

    def test_dashboard_stats_accepts_empty_lists(self):
        """Test that DashboardStats accepts empty lists."""
        data = DashboardStats(
            total=0,
            red=0,
            yellow=0,
            green=0,
            reports_last_7_days=0,
            avg_per_day=0.0,
            time_series=[],
            top_flags=[],
        )

        assert data.total == 0
        assert len(data.time_series) == 0
        assert len(data.top_flags) == 0

    def test_dashboard_stats_handles_float_avg(self):
        """Test that DashboardStats handles float avg_per_day."""
        data = DashboardStats(
            total=10,
            red=3,
            yellow=3,
            green=4,
            reports_last_7_days=7,
            avg_per_day=1.5,
            time_series=[],
            top_flags=[],
        )

        assert data.avg_per_day == 1.5
