"""Tests for StandingsAnalyzer."""

import pytest

from backend.analyzers.standings import StandingsAnalyzer
from backend.models.applicant import Applicant
from backend.models.flags import FlagCategory, FlagSeverity


@pytest.fixture
def analyzer() -> StandingsAnalyzer:
    """Create a StandingsAnalyzer with test configuration."""
    a = StandingsAnalyzer()
    # Configure test hostile/allied entities
    a.add_hostile_alliance(99000001)  # Test hostile alliance
    a.add_hostile_corp(98000001)  # Test hostile corp
    a.add_allied_alliance(99000002)  # Test allied alliance
    a.add_allied_corp(98000002)  # Test allied corp
    a.add_enemy_faction(500001)  # Test enemy faction
    return a


@pytest.fixture
def base_applicant() -> Applicant:
    """Create a base applicant for testing."""
    return Applicant(
        character_id=12345678,
        character_name="Test Pilot",
    )


class TestStandingsAnalyzer:
    """Tests for StandingsAnalyzer."""

    async def test_no_standings_data_returns_empty(
        self, analyzer: StandingsAnalyzer, base_applicant: Applicant
    ) -> None:
        """Test that no standings data returns no flags."""
        flags = await analyzer.analyze(base_applicant)
        assert flags == []

    async def test_hostile_positive_standing_red_flag(
        self, analyzer: StandingsAnalyzer, base_applicant: Applicant
    ) -> None:
        """Test that positive standings with hostiles triggers red flag."""
        base_applicant.standings_data = {
            "standings": [],
            "contacts": [
                {
                    "contact_id": 99000001,  # Hostile alliance
                    "contact_type": "alliance",
                    "standing": 10.0,
                }
            ],
        }

        flags = await analyzer.analyze(base_applicant)

        assert len(flags) == 1
        assert flags[0].severity == FlagSeverity.RED
        assert flags[0].code == "ENEMY_STANDINGS"
        assert flags[0].category == FlagCategory.STANDINGS

    async def test_allied_negative_standing_yellow_flag(
        self, analyzer: StandingsAnalyzer, base_applicant: Applicant
    ) -> None:
        """Test that negative standings with allies triggers yellow flag."""
        base_applicant.standings_data = {
            "standings": [],
            "contacts": [
                {
                    "contact_id": 99000002,  # Allied alliance
                    "contact_type": "alliance",
                    "standing": -10.0,
                }
            ],
        }

        flags = await analyzer.analyze(base_applicant)

        assert len(flags) == 1
        assert flags[0].severity == FlagSeverity.YELLOW
        assert flags[0].code == "ALLIED_NEGATIVE_STANDINGS"

    async def test_enemy_faction_standing_yellow_flag(
        self, analyzer: StandingsAnalyzer, base_applicant: Applicant
    ) -> None:
        """Test that positive standings with enemy faction triggers yellow flag."""
        base_applicant.standings_data = {
            "standings": [
                {
                    "from_id": 500001,  # Enemy faction
                    "from_type": "faction",
                    "standing": 5.0,
                }
            ],
            "contacts": [],
        }

        flags = await analyzer.analyze(base_applicant)

        assert len(flags) == 1
        assert flags[0].severity == FlagSeverity.YELLOW
        assert flags[0].code == "ENEMY_FACTION_STANDING"

    async def test_allied_positive_standing_green_flag(
        self, analyzer: StandingsAnalyzer, base_applicant: Applicant
    ) -> None:
        """Test that positive standings with allies triggers green flag."""
        base_applicant.standings_data = {
            "standings": [],
            "contacts": [
                {"contact_id": 99000002, "contact_type": "alliance", "standing": 10.0},
                {"contact_id": 98000002, "contact_type": "corporation", "standing": 10.0},
                {"contact_id": 99000002, "contact_type": "alliance", "standing": 5.0},
            ],
        }

        flags = await analyzer.analyze(base_applicant)

        assert len(flags) == 1
        assert flags[0].severity == FlagSeverity.GREEN
        assert flags[0].code == "ALLIED_STANDINGS"

    async def test_neutral_standings_no_flags(
        self, analyzer: StandingsAnalyzer, base_applicant: Applicant
    ) -> None:
        """Test that neutral standings produce no flags."""
        base_applicant.standings_data = {
            "standings": [
                {
                    "from_id": 99999999,  # Unknown entity
                    "from_type": "alliance",
                    "standing": 0.0,
                }
            ],
            "contacts": [],
        }

        flags = await analyzer.analyze(base_applicant)
        assert flags == []

    async def test_requires_auth_flag(self, analyzer: StandingsAnalyzer) -> None:
        """Test that analyzer requires auth."""
        assert analyzer.requires_auth is True

    async def test_analyzer_metadata(self, analyzer: StandingsAnalyzer) -> None:
        """Test analyzer name and description."""
        assert analyzer.name == "standings"
        assert "standings" in analyzer.description.lower()

    async def test_hostile_corp_positive_standing(
        self, analyzer: StandingsAnalyzer, base_applicant: Applicant
    ) -> None:
        """Test that positive standings with hostile corp triggers red flag."""
        base_applicant.standings_data = {
            "standings": [],
            "contacts": [
                {
                    "contact_id": 98000001,  # Hostile corp
                    "contact_type": "corporation",
                    "standing": 7.5,
                }
            ],
        }

        flags = await analyzer.analyze(base_applicant)

        assert len(flags) == 1
        assert flags[0].severity == FlagSeverity.RED
        assert flags[0].code == "ENEMY_STANDINGS"

    async def test_below_threshold_no_flag(
        self, analyzer: StandingsAnalyzer, base_applicant: Applicant
    ) -> None:
        """Test that standings below threshold don't trigger flags."""
        base_applicant.standings_data = {
            "standings": [],
            "contacts": [
                {
                    "contact_id": 99000001,  # Hostile alliance
                    "contact_type": "alliance",
                    "standing": 3.0,  # Below 5.0 threshold
                }
            ],
        }

        flags = await analyzer.analyze(base_applicant)
        assert flags == []
