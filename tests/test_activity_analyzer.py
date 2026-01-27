"""Tests for ActivityAnalyzer."""

from datetime import UTC, datetime, timedelta

import pytest

from backend.analyzers.activity import ActivityAnalyzer
from backend.models.applicant import ActivityPattern, Applicant
from backend.models.flags import FlagSeverity, GreenFlags, YellowFlags


@pytest.fixture
def activity_analyzer():
    """Create an ActivityAnalyzer instance."""
    return ActivityAnalyzer()


@pytest.fixture
def activity_analyzer_with_tz():
    """Create an ActivityAnalyzer with target timezone."""
    return ActivityAnalyzer(target_timezone="EU-TZ")


@pytest.fixture
def base_applicant():
    """Create a basic applicant for testing."""
    return Applicant(
        character_id=12345678,
        character_name="Test Pilot",
        corporation_id=98000001,
        corporation_name="Test Corp",
    )


class TestActivityAnalyzer:
    """Tests for ActivityAnalyzer."""

    @pytest.mark.asyncio
    async def test_empty_activity_returns_no_flags(self, activity_analyzer, base_applicant):
        """Empty activity data should return no flags."""
        base_applicant.activity = ActivityPattern()
        flags = await activity_analyzer.analyze(base_applicant)
        assert flags == []

    @pytest.mark.asyncio
    async def test_timezone_mismatch_detected(self, activity_analyzer_with_tz, base_applicant):
        """Timezone mismatch should be flagged."""
        base_applicant.activity = ActivityPattern(
            primary_timezone="US-TZ",
            peak_hours=[1, 2, 3],
        )

        flags = await activity_analyzer_with_tz.analyze(base_applicant)

        yellow_flags = [f for f in flags if f.severity == FlagSeverity.YELLOW]
        assert any(f.code == YellowFlags.TIMEZONE_MISMATCH for f in yellow_flags)

    @pytest.mark.asyncio
    async def test_timezone_match_no_flag(self, activity_analyzer_with_tz, base_applicant):
        """Matching timezone should not be flagged."""
        base_applicant.activity = ActivityPattern(
            primary_timezone="EU-TZ",
            peak_hours=[18, 19, 20],
        )

        flags = await activity_analyzer_with_tz.analyze(base_applicant)

        assert not any(f.code == YellowFlags.TIMEZONE_MISMATCH for f in flags)

    @pytest.mark.asyncio
    async def test_no_target_tz_skips_mismatch_check(self, activity_analyzer, base_applicant):
        """Without target TZ configured, no mismatch flag."""
        base_applicant.activity = ActivityPattern(
            primary_timezone="AU-TZ",
            peak_hours=[9, 10, 11],
        )

        flags = await activity_analyzer.analyze(base_applicant)

        assert not any(f.code == YellowFlags.TIMEZONE_MISMATCH for f in flags)

    @pytest.mark.asyncio
    async def test_severe_inactivity_detected(self, activity_analyzer, base_applicant):
        """90+ days without activity should be flagged."""
        now = datetime.now(UTC)
        base_applicant.activity = ActivityPattern(
            last_kill_date=now - timedelta(days=100),
        )

        flags = await activity_analyzer.analyze(base_applicant)

        yellow_flags = [f for f in flags if f.severity == FlagSeverity.YELLOW]
        assert any(f.code == YellowFlags.INACTIVE_PERIOD for f in yellow_flags)
        # Check evidence contains correct days
        inactive_flag = next(f for f in yellow_flags if f.code == YellowFlags.INACTIVE_PERIOD)
        assert inactive_flag.evidence["days_inactive"] >= 100

    @pytest.mark.asyncio
    async def test_moderate_inactivity_detected(self, activity_analyzer, base_applicant):
        """30-90 days without activity should be flagged."""
        now = datetime.now(UTC)
        base_applicant.activity = ActivityPattern(
            last_kill_date=now - timedelta(days=45),
        )

        flags = await activity_analyzer.analyze(base_applicant)

        yellow_flags = [f for f in flags if f.severity == FlagSeverity.YELLOW]
        assert any(f.code == YellowFlags.INACTIVE_PERIOD for f in yellow_flags)

    @pytest.mark.asyncio
    async def test_recent_activity_no_inactive_flag(self, activity_analyzer, base_applicant):
        """Activity within 30 days should not flag inactivity."""
        now = datetime.now(UTC)
        base_applicant.activity = ActivityPattern(
            last_kill_date=now - timedelta(days=10),
        )

        flags = await activity_analyzer.analyze(base_applicant)

        assert not any(f.code == YellowFlags.INACTIVE_PERIOD for f in flags)

    @pytest.mark.asyncio
    async def test_loss_date_used_if_no_kill(self, activity_analyzer, base_applicant):
        """Last loss date should be used if no kill date."""
        now = datetime.now(UTC)
        base_applicant.activity = ActivityPattern(
            last_kill_date=None,
            last_loss_date=now - timedelta(days=5),
        )

        flags = await activity_analyzer.analyze(base_applicant)

        assert not any(f.code == YellowFlags.INACTIVE_PERIOD for f in flags)

    @pytest.mark.asyncio
    async def test_inactive_trend_flagged(self, activity_analyzer, base_applicant):
        """Inactive activity trend should be flagged."""
        base_applicant.activity = ActivityPattern(
            activity_trend="inactive",
        )

        flags = await activity_analyzer.analyze(base_applicant)

        yellow_flags = [f for f in flags if f.severity == FlagSeverity.YELLOW]
        assert any(f.code == YellowFlags.INACTIVE_PERIOD for f in yellow_flags)

    @pytest.mark.asyncio
    async def test_declining_trend_flagged(self, activity_analyzer, base_applicant):
        """Declining activity trend should be flagged."""
        base_applicant.activity = ActivityPattern(
            activity_trend="declining",
        )

        flags = await activity_analyzer.analyze(base_applicant)

        yellow_flags = [f for f in flags if f.severity == FlagSeverity.YELLOW]
        assert any(f.code == YellowFlags.INACTIVE_PERIOD for f in yellow_flags)

    @pytest.mark.asyncio
    async def test_low_engagement_flagged(self, activity_analyzer, base_applicant):
        """Low active days per week should be flagged."""
        base_applicant.activity = ActivityPattern(
            active_days_per_week=1.5,
        )

        flags = await activity_analyzer.analyze(base_applicant)

        yellow_flags = [f for f in flags if f.severity == FlagSeverity.YELLOW]
        assert any(f.code == YellowFlags.LOW_ACTIVITY for f in yellow_flags)

    @pytest.mark.asyncio
    async def test_consistent_activity_green_flag(self, activity_analyzer, base_applicant):
        """High active days per week should get green flag."""
        base_applicant.activity = ActivityPattern(
            active_days_per_week=5.0,
            peak_hours=[18, 19, 20],
            primary_timezone="EU-TZ",
        )

        flags = await activity_analyzer.analyze(base_applicant)

        green_flags = [f for f in flags if f.severity == FlagSeverity.GREEN]
        assert any(f.code == GreenFlags.CONSISTENT_ACTIVITY for f in green_flags)

    @pytest.mark.asyncio
    async def test_moderate_activity_no_flags(self, activity_analyzer, base_applicant):
        """Moderate activity (2-4 days/week) should have no activity flags."""
        base_applicant.activity = ActivityPattern(
            active_days_per_week=3.0,
        )

        flags = await activity_analyzer.analyze(base_applicant)

        # Should have neither low activity nor consistent activity flags
        assert not any(f.code == YellowFlags.LOW_ACTIVITY for f in flags)
        assert not any(f.code == GreenFlags.CONSISTENT_ACTIVITY for f in flags)

    @pytest.mark.asyncio
    async def test_requires_auth_flag_set(self, activity_analyzer):
        """ActivityAnalyzer should indicate it requires auth data."""
        assert activity_analyzer.requires_auth is True

    @pytest.mark.asyncio
    async def test_analyzer_metadata(self, activity_analyzer):
        """Verify analyzer metadata."""
        assert activity_analyzer.name == "activity"
        assert "activity" in activity_analyzer.description.lower()

    @pytest.mark.asyncio
    async def test_set_target_timezone(self, activity_analyzer):
        """Test setting target timezone."""
        activity_analyzer.set_target_timezone("US-TZ")
        assert activity_analyzer.target_tz == "US-TZ"

    @pytest.mark.asyncio
    async def test_set_invalid_timezone_raises(self, activity_analyzer):
        """Invalid timezone should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid timezone"):
            activity_analyzer.set_target_timezone("INVALID-TZ")

    @pytest.mark.asyncio
    async def test_multiple_flags_can_be_returned(self, activity_analyzer_with_tz, base_applicant):
        """Multiple issues should return multiple flags."""
        now = datetime.now(UTC)
        base_applicant.activity = ActivityPattern(
            primary_timezone="US-TZ",  # Mismatch with EU-TZ target
            active_days_per_week=1.0,  # Low engagement
            last_kill_date=now - timedelta(days=100),  # Inactive
        )

        flags = await activity_analyzer_with_tz.analyze(base_applicant)

        yellow_flags = [f for f in flags if f.severity == FlagSeverity.YELLOW]
        flag_codes = {f.code for f in yellow_flags}

        assert YellowFlags.TIMEZONE_MISMATCH in flag_codes
        assert YellowFlags.LOW_ACTIVITY in flag_codes
        assert YellowFlags.INACTIVE_PERIOD in flag_codes
