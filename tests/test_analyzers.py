"""Tests for risk analyzers."""

from datetime import UTC, datetime, timedelta

import pytest

from backend.analyzers.corp_history import CorpHistoryAnalyzer
from backend.analyzers.killboard import KillboardAnalyzer
from backend.models.applicant import Applicant, CorpHistoryEntry, KillboardStats
from backend.models.flags import FlagSeverity, GreenFlags, RedFlags, YellowFlags


# Fixtures
@pytest.fixture
def corp_history_analyzer():
    """Create a CorpHistoryAnalyzer instance."""
    return CorpHistoryAnalyzer()


@pytest.fixture
def killboard_analyzer():
    """Create a KillboardAnalyzer instance."""
    return KillboardAnalyzer()


@pytest.fixture
def base_applicant():
    """Create a basic applicant for testing."""
    return Applicant(
        character_id=12345678,
        character_name="Test Pilot",
        corporation_id=98000001,
        corporation_name="Test Corp",
    )


# Corp History Analyzer Tests
class TestCorpHistoryAnalyzer:
    """Tests for CorpHistoryAnalyzer."""

    @pytest.mark.asyncio
    async def test_empty_history_returns_no_flags(self, corp_history_analyzer, base_applicant):
        """Empty corp history should return no flags."""
        base_applicant.corp_history = []
        flags = await corp_history_analyzer.analyze(base_applicant)
        assert flags == []

    @pytest.mark.asyncio
    async def test_hostile_corp_detected(self, corp_history_analyzer, base_applicant):
        """Membership in a hostile corp should raise a red flag."""
        # Add a hostile corp to the analyzer's list
        hostile_corp_id = 667531913
        corp_history_analyzer.add_hostile_corp(hostile_corp_id)

        base_applicant.corp_history = [
            CorpHistoryEntry(
                corporation_id=hostile_corp_id,
                corporation_name="Hostile Corp",
                start_date=datetime.now(UTC) - timedelta(days=100),
                end_date=datetime.now(UTC) - timedelta(days=50),
                duration_days=50,
            ),
        ]

        flags = await corp_history_analyzer.analyze(base_applicant)

        red_flags = [f for f in flags if f.severity == FlagSeverity.RED]
        assert len(red_flags) >= 1
        assert any(f.code == RedFlags.KNOWN_SPY_CORP for f in red_flags)

    @pytest.mark.asyncio
    async def test_rapid_corp_hopping_detected(self, corp_history_analyzer, base_applicant):
        """5+ corps in 6 months should raise a red flag."""
        now = datetime.now(UTC)
        # Create 6 corps in the last 6 months
        base_applicant.corp_history = [
            CorpHistoryEntry(
                corporation_id=1000000 + i,
                corporation_name=f"Corp {i}",
                start_date=now - timedelta(days=30 * (6 - i)),
                end_date=now - timedelta(days=30 * (5 - i)) if i < 5 else None,
                duration_days=30,
            )
            for i in range(6)
        ]

        flags = await corp_history_analyzer.analyze(base_applicant)

        red_flags = [f for f in flags if f.severity == FlagSeverity.RED]
        assert any(f.code == RedFlags.RAPID_CORP_HOP for f in red_flags)

    @pytest.mark.asyncio
    async def test_short_tenure_detected(self, corp_history_analyzer, base_applicant):
        """Less than 30 days in current corp should raise a yellow flag."""
        now = datetime.now(UTC)
        base_applicant.corp_history = [
            CorpHistoryEntry(
                corporation_id=98000001,
                corporation_name="Current Corp",
                start_date=now - timedelta(days=15),
                end_date=None,
                duration_days=15,
            ),
        ]

        flags = await corp_history_analyzer.analyze(base_applicant)

        yellow_flags = [f for f in flags if f.severity == FlagSeverity.YELLOW]
        assert any(f.code == YellowFlags.SHORT_TENURE for f in yellow_flags)

    @pytest.mark.asyncio
    async def test_established_character_green_flag(self, corp_history_analyzer, base_applicant):
        """2+ years history with stable tenure should get green flag."""
        now = datetime.now(UTC)
        base_applicant.corp_history = [
            CorpHistoryEntry(
                corporation_id=98000001,
                corporation_name="Current Corp",
                start_date=now - timedelta(days=400),
                end_date=None,
                duration_days=400,
            ),
            CorpHistoryEntry(
                corporation_id=98000002,
                corporation_name="Previous Corp",
                start_date=now - timedelta(days=800),
                end_date=now - timedelta(days=400),
                duration_days=400,
            ),
        ]

        flags = await corp_history_analyzer.analyze(base_applicant)

        green_flags = [f for f in flags if f.severity == FlagSeverity.GREEN]
        assert any(f.code == GreenFlags.ESTABLISHED for f in green_flags)

    @pytest.mark.asyncio
    async def test_clean_history_green_flag(self, corp_history_analyzer, base_applicant):
        """No hostile corps and stable history should get clean history flag."""
        now = datetime.now(UTC)
        base_applicant.corp_history = [
            CorpHistoryEntry(
                corporation_id=98000001,
                corporation_name="Current Corp",
                start_date=now - timedelta(days=200),
                end_date=None,
                duration_days=200,
            ),
        ]

        flags = await corp_history_analyzer.analyze(base_applicant)

        green_flags = [f for f in flags if f.severity == FlagSeverity.GREEN]
        assert any(f.code == GreenFlags.CLEAN_HISTORY for f in green_flags)

    @pytest.mark.asyncio
    async def test_npc_corp_pattern_detected(self, corp_history_analyzer, base_applicant):
        """Multiple extended NPC corp stints should raise yellow flag."""
        now = datetime.now(UTC)
        base_applicant.corp_history = [
            CorpHistoryEntry(
                corporation_id=98000001,
                corporation_name="Current Corp",
                start_date=now - timedelta(days=30),
                end_date=None,
                duration_days=30,
            ),
            CorpHistoryEntry(
                corporation_id=1000002,
                corporation_name="NPC Corp 1",
                start_date=now - timedelta(days=100),
                end_date=now - timedelta(days=30),
                duration_days=70,
                is_npc=True,
            ),
            CorpHistoryEntry(
                corporation_id=1000003,
                corporation_name="NPC Corp 2",
                start_date=now - timedelta(days=200),
                end_date=now - timedelta(days=100),
                duration_days=100,
                is_npc=True,
            ),
        ]

        flags = await corp_history_analyzer.analyze(base_applicant)

        yellow_flags = [f for f in flags if f.severity == FlagSeverity.YELLOW]
        assert any(f.code == "NPC_CORP_PATTERN" for f in yellow_flags)


# Killboard Analyzer Tests
class TestKillboardAnalyzer:
    """Tests for KillboardAnalyzer."""

    @pytest.mark.asyncio
    async def test_awox_history_detected(self, killboard_analyzer, base_applicant):
        """AWOX kills should raise a red flag."""
        base_applicant.killboard = KillboardStats(
            kills_total=100,
            kills_90d=30,
            awox_kills=3,
        )

        flags = await killboard_analyzer.analyze(base_applicant)

        red_flags = [f for f in flags if f.severity == FlagSeverity.RED]
        assert any(f.code == RedFlags.AWOX_HISTORY for f in red_flags)

    @pytest.mark.asyncio
    async def test_single_awox_still_flagged(self, killboard_analyzer, base_applicant):
        """Even a single AWOX kill should be flagged."""
        base_applicant.killboard = KillboardStats(
            kills_total=100,
            kills_90d=30,
            awox_kills=1,
        )

        flags = await killboard_analyzer.analyze(base_applicant)

        red_flags = [f for f in flags if f.severity == FlagSeverity.RED]
        assert any(f.code == RedFlags.AWOX_HISTORY for f in red_flags)

    @pytest.mark.asyncio
    async def test_low_activity_detected(self, killboard_analyzer, base_applicant):
        """Low kill count should raise yellow flag."""
        base_applicant.killboard = KillboardStats(
            kills_total=50,
            kills_90d=10,
        )

        flags = await killboard_analyzer.analyze(base_applicant)

        yellow_flags = [f for f in flags if f.severity == FlagSeverity.YELLOW]
        assert any(f.code == YellowFlags.LOW_ACTIVITY for f in yellow_flags)

    @pytest.mark.asyncio
    async def test_zero_kills_no_low_activity_flag(self, killboard_analyzer, base_applicant):
        """Zero total kills should not raise low activity (new player edge case)."""
        base_applicant.killboard = KillboardStats(
            kills_total=0,
            kills_90d=0,
        )

        flags = await killboard_analyzer.analyze(base_applicant)

        yellow_flags = [f for f in flags if f.severity == FlagSeverity.YELLOW]
        assert not any(f.code == YellowFlags.LOW_ACTIVITY for f in yellow_flags)

    @pytest.mark.asyncio
    async def test_active_pvper_green_flag(self, killboard_analyzer, base_applicant):
        """High activity should get green flag."""
        base_applicant.killboard = KillboardStats(
            kills_total=500,
            kills_90d=75,
            kills_30d=30,
            solo_kills=20,
        )

        flags = await killboard_analyzer.analyze(base_applicant)

        green_flags = [f for f in flags if f.severity == FlagSeverity.GREEN]
        assert any(f.code == GreenFlags.ACTIVE_PVPER for f in green_flags)

    @pytest.mark.asyncio
    async def test_logi_pilot_detected(self, killboard_analyzer, base_applicant):
        """Flying logi ships should get green flag."""
        base_applicant.killboard = KillboardStats(
            kills_total=100,
            kills_90d=30,
            top_ships=["Guardian", "Muninn", "Eagle"],
        )

        flags = await killboard_analyzer.analyze(base_applicant)

        green_flags = [f for f in flags if f.severity == FlagSeverity.GREEN]
        assert any(f.code == GreenFlags.LOGI_PILOT for f in green_flags)

    @pytest.mark.asyncio
    async def test_no_flags_for_moderate_activity(self, killboard_analyzer, base_applicant):
        """Moderate activity with no special patterns should have minimal flags."""
        base_applicant.killboard = KillboardStats(
            kills_total=200,
            kills_90d=35,  # Above LOW_ACTIVITY but below ACTIVE_PVPER
            kills_30d=15,
            awox_kills=0,
            top_ships=["Muninn", "Eagle", "Cerberus"],
        )

        flags = await killboard_analyzer.analyze(base_applicant)

        # Should have no red flags
        red_flags = [f for f in flags if f.severity == FlagSeverity.RED]
        assert len(red_flags) == 0

        # Should have no low activity flag
        assert not any(f.code == YellowFlags.LOW_ACTIVITY for f in flags)
