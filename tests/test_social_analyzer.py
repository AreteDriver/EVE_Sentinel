"""Tests for SocialAnalyzer."""

from datetime import UTC, datetime

import pytest

from backend.analyzers.social import SocialAnalyzer
from backend.models.applicant import Applicant, SuspectedAlt


@pytest.fixture
def analyzer():
    """Create a SocialAnalyzer instance."""
    analyzer = SocialAnalyzer()
    # Add some hostile entities for testing
    analyzer.add_hostile_corp(98000001)
    analyzer.add_hostile_alliance(99000001)
    return analyzer


@pytest.fixture
def base_applicant():
    """Create a base applicant for testing."""
    return Applicant(
        character_id=12345678,
        character_name="Test Pilot",
        corporation_id=98000002,
        corporation_name="Test Corp",
        birthday=datetime.now(UTC),
    )


class TestSocialAnalyzer:
    """Tests for the SocialAnalyzer class."""

    @pytest.mark.asyncio
    async def test_no_alts_returns_no_flags(self, analyzer, base_applicant):
        """Test that no alts produces no flags."""
        flags = await analyzer.analyze(base_applicant)
        assert len(flags) == 0

    @pytest.mark.asyncio
    async def test_hostile_alt_red_flag(self, analyzer, base_applicant):
        """Test that an alt in a hostile corp produces a red flag."""
        base_applicant.suspected_alts = [
            SuspectedAlt(
                character_id=87654321,
                character_name="Suspicious Alt",
                confidence=0.85,
                detection_method="login_correlation",
                evidence={
                    "corporation_id": 98000001,  # Hostile corp
                    "alliance_id": None,
                },
            )
        ]

        flags = await analyzer.analyze(base_applicant)

        red_flags = [f for f in flags if f.severity.value == "RED"]
        assert len(red_flags) >= 1
        assert any(f.code == "HIDDEN_ALTS" for f in red_flags)

    @pytest.mark.asyncio
    async def test_hostile_alliance_alt_red_flag(self, analyzer, base_applicant):
        """Test that an alt in a hostile alliance produces a red flag."""
        base_applicant.suspected_alts = [
            SuspectedAlt(
                character_id=87654321,
                character_name="Suspicious Alt",
                confidence=0.85,
                detection_method="login_correlation",
                evidence={
                    "corporation_id": 98000999,
                    "alliance_id": 99000001,  # Hostile alliance
                },
            )
        ]

        flags = await analyzer.analyze(base_applicant)

        red_flags = [f for f in flags if f.severity.value == "RED"]
        assert len(red_flags) >= 1
        assert any(f.code == "HIDDEN_ALTS" for f in red_flags)

    @pytest.mark.asyncio
    async def test_large_alt_network_yellow_flag(self, analyzer, base_applicant):
        """Test that many high-confidence alts produce a yellow flag."""
        base_applicant.suspected_alts = [
            SuspectedAlt(
                character_id=i,
                character_name=f"Alt {i}",
                confidence=0.85,
                detection_method="login_correlation",
            )
            for i in range(5)
        ]

        flags = await analyzer.analyze(base_applicant)

        yellow_flags = [f for f in flags if f.severity.value == "YELLOW"]
        assert any(f.code == "LARGE_ALT_NETWORK" for f in yellow_flags)

    @pytest.mark.asyncio
    async def test_login_correlation_alts_yellow_flag(self, analyzer, base_applicant):
        """Test that many login-correlated alts produce a yellow flag."""
        base_applicant.suspected_alts = [
            SuspectedAlt(
                character_id=i,
                character_name=f"Alt {i}",
                confidence=0.6,
                detection_method="login_correlation",
            )
            for i in range(6)
        ]

        flags = await analyzer.analyze(base_applicant)

        yellow_flags = [f for f in flags if f.severity.value == "YELLOW"]
        assert any(f.code == "LOGIN_CORRELATION_ALTS" for f in yellow_flags)

    @pytest.mark.asyncio
    async def test_undeclared_alts_yellow_flag(self, analyzer, base_applicant):
        """Test that suspected alts with none declared produces a yellow flag."""
        base_applicant.suspected_alts = [
            SuspectedAlt(
                character_id=i,
                character_name=f"Alt {i}",
                confidence=0.6,
                detection_method="naming_pattern",
            )
            for i in range(3)
        ]
        base_applicant.declared_alts = []

        flags = await analyzer.analyze(base_applicant)

        yellow_flags = [f for f in flags if f.severity.value == "YELLOW"]
        assert any(f.code == "UNDECLARED_ALTS" for f in yellow_flags)

    @pytest.mark.asyncio
    async def test_alt_count_mismatch_yellow_flag(self, analyzer, base_applicant):
        """Test that more suspected than declared alts produces a yellow flag."""
        base_applicant.suspected_alts = [
            SuspectedAlt(
                character_id=i,
                character_name=f"Alt {i}",
                confidence=0.6,
                detection_method="naming_pattern",
            )
            for i in range(5)
        ]
        base_applicant.declared_alts = ["One Alt"]

        flags = await analyzer.analyze(base_applicant)

        yellow_flags = [f for f in flags if f.severity.value == "YELLOW"]
        assert any(f.code == "ALT_COUNT_MISMATCH" for f in yellow_flags)

    @pytest.mark.asyncio
    async def test_transparent_alts_green_flag(self, analyzer, base_applicant):
        """Test that declared alts matching suspected produces a green flag."""
        base_applicant.suspected_alts = [
            SuspectedAlt(
                character_id=1,
                character_name="Declared Alt",
                confidence=0.6,
                detection_method="naming_pattern",
            )
        ]
        base_applicant.declared_alts = ["Declared Alt"]

        flags = await analyzer.analyze(base_applicant)

        green_flags = [f for f in flags if f.severity.value == "GREEN"]
        assert any(f.code == "TRANSPARENT_ALTS" for f in green_flags)

    @pytest.mark.asyncio
    async def test_hostile_positive_contacts_red_flag(self, analyzer, base_applicant):
        """Test that positive contacts with hostiles produces a red flag."""
        base_applicant.standings_data = {
            "contacts": [
                {
                    "contact_id": 98000001,  # Hostile corp
                    "contact_type": "corporation",
                    "standing": 10.0,
                }
            ]
        }

        flags = await analyzer.analyze(base_applicant)

        red_flags = [f for f in flags if f.severity.value == "RED"]
        assert any(f.code == "HOSTILE_POSITIVE_CONTACTS" for f in red_flags)

    @pytest.mark.asyncio
    async def test_many_negative_contacts_yellow_flag(self, analyzer, base_applicant):
        """Test that many negative contacts produces a yellow flag."""
        base_applicant.standings_data = {
            "contacts": [
                {
                    "contact_id": i,
                    "contact_type": "character",
                    "standing": -5.0,
                }
                for i in range(25)
            ]
        }

        flags = await analyzer.analyze(base_applicant)

        yellow_flags = [f for f in flags if f.severity.value == "YELLOW"]
        assert any(f.code == "MANY_NEGATIVE_CONTACTS" for f in yellow_flags)

    @pytest.mark.asyncio
    async def test_organized_contacts_green_flag(self, analyzer, base_applicant):
        """Test that well-organized contacts produces a green flag."""
        base_applicant.standings_data = {
            "contacts": [
                {
                    "contact_id": i,
                    "contact_type": "character",
                    "standing": 5.0,
                }
                for i in range(15)
            ]
        }

        flags = await analyzer.analyze(base_applicant)

        green_flags = [f for f in flags if f.severity.value == "GREEN"]
        assert any(f.code == "ORGANIZED_CONTACTS" for f in green_flags)

    @pytest.mark.asyncio
    async def test_low_confidence_alts_ignored(self, analyzer, base_applicant):
        """Test that low-confidence alts don't produce hostile flags."""
        base_applicant.suspected_alts = [
            SuspectedAlt(
                character_id=87654321,
                character_name="Low Confidence Alt",
                confidence=0.3,  # Below threshold
                detection_method="login_correlation",
                evidence={
                    "corporation_id": 98000001,  # Hostile corp
                },
            )
        ]

        flags = await analyzer.analyze(base_applicant)

        red_flags = [f for f in flags if f.severity.value == "RED"]
        assert not any(f.code == "HIDDEN_ALTS" for f in red_flags)

    @pytest.mark.asyncio
    async def test_analyzer_metadata(self, analyzer):
        """Test analyzer metadata is correct."""
        assert analyzer.name == "social"
        assert analyzer.description == "Analyzes social connections and alt networks"
        assert analyzer.requires_auth is False

    @pytest.mark.asyncio
    async def test_add_hostile_entities(self, base_applicant):
        """Test adding hostile entities dynamically."""
        analyzer = SocialAnalyzer()

        # Initially no hostile flags
        base_applicant.suspected_alts = [
            SuspectedAlt(
                character_id=87654321,
                character_name="Alt",
                confidence=0.85,
                detection_method="login_correlation",
                evidence={"corporation_id": 98000099},
            )
        ]

        flags = await analyzer.analyze(base_applicant)
        assert not any(f.code == "HIDDEN_ALTS" for f in flags)

        # Add the corp as hostile
        analyzer.add_hostile_corp(98000099)

        flags = await analyzer.analyze(base_applicant)
        red_flags = [f for f in flags if f.severity.value == "RED"]
        assert any(f.code == "HIDDEN_ALTS" for f in red_flags)
