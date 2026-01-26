"""Tests for AssetsAnalyzer."""

import pytest

from backend.analyzers.assets import AssetsAnalyzer
from backend.models.applicant import Applicant, AssetSummary
from backend.models.flags import FlagSeverity, GreenFlags, YellowFlags


@pytest.fixture
def assets_analyzer():
    """Create an AssetsAnalyzer instance."""
    return AssetsAnalyzer()


@pytest.fixture
def base_applicant():
    """Create a basic applicant for testing."""
    return Applicant(
        character_id=12345678,
        character_name="Test Pilot",
        corporation_id=98000001,
        corporation_name="Test Corp",
    )


class TestAssetsAnalyzer:
    """Tests for AssetsAnalyzer."""

    @pytest.mark.asyncio
    async def test_no_assets_data_returns_empty(self, assets_analyzer, base_applicant):
        """No asset data should return no flags."""
        base_applicant.assets = None
        flags = await assets_analyzer.analyze(base_applicant)
        assert flags == []

    @pytest.mark.asyncio
    async def test_capital_pilot_flag_for_carriers(self, assets_analyzer, base_applicant):
        """Capital ship ownership should trigger CAPITAL_PILOT flag."""
        base_applicant.assets = AssetSummary(
            total_value_isk=5_000_000_000,
            capital_ships=["Archon", "Revelation"],
            supercapitals=[],
            primary_regions=["Delve"],
        )

        flags = await assets_analyzer.analyze(base_applicant)

        green_flags = [f for f in flags if f.severity == FlagSeverity.GREEN]
        assert any(f.code == GreenFlags.CAPITAL_PILOT for f in green_flags)

    @pytest.mark.asyncio
    async def test_capital_pilot_flag_for_supers(self, assets_analyzer, base_applicant):
        """Supercapital ownership should trigger CAPITAL_PILOT with higher confidence."""
        base_applicant.assets = AssetSummary(
            total_value_isk=100_000_000_000,
            capital_ships=["Archon"],
            supercapitals=["Nyx", "Avatar"],
            primary_regions=["Delve"],
        )

        flags = await assets_analyzer.analyze(base_applicant)

        capital_flags = [f for f in flags if f.code == GreenFlags.CAPITAL_PILOT]
        assert len(capital_flags) == 1
        assert capital_flags[0].confidence == 0.95
        assert "Nyx" in capital_flags[0].reason

    @pytest.mark.asyncio
    async def test_no_assets_flag_for_low_value(self, assets_analyzer, base_applicant):
        """Low asset value should trigger NO_ASSETS flag."""
        base_applicant.assets = AssetSummary(
            total_value_isk=100_000_000,  # 100M - below threshold
            capital_ships=[],
            supercapitals=[],
            primary_regions=["The Forge"],
        )

        flags = await assets_analyzer.analyze(base_applicant)

        yellow_flags = [f for f in flags if f.severity == FlagSeverity.YELLOW]
        assert any(f.code == YellowFlags.NO_ASSETS for f in yellow_flags)

    @pytest.mark.asyncio
    async def test_no_flag_for_moderate_assets(self, assets_analyzer, base_applicant):
        """Moderate asset value should not trigger NO_ASSETS flag."""
        base_applicant.assets = AssetSummary(
            total_value_isk=2_000_000_000,  # 2B
            capital_ships=[],
            supercapitals=[],
            primary_regions=["The Forge"],
        )

        flags = await assets_analyzer.analyze(base_applicant)

        assert not any(f.code == YellowFlags.NO_ASSETS for f in flags)

    @pytest.mark.asyncio
    async def test_established_flag_for_wealthy(self, assets_analyzer, base_applicant):
        """High asset value should trigger ESTABLISHED flag."""
        base_applicant.assets = AssetSummary(
            total_value_isk=15_000_000_000,  # 15B
            capital_ships=[],
            supercapitals=[],
            primary_regions=["Delve"],
        )

        flags = await assets_analyzer.analyze(base_applicant)

        green_flags = [f for f in flags if f.severity == FlagSeverity.GREEN]
        assert any(f.code == GreenFlags.ESTABLISHED for f in green_flags)

    @pytest.mark.asyncio
    async def test_highsec_only_flag(self, assets_analyzer, base_applicant):
        """Assets only in highsec should trigger HIGH_SEC_ONLY flag."""
        base_applicant.assets = AssetSummary(
            total_value_isk=5_000_000_000,
            capital_ships=[],
            supercapitals=[],
            primary_regions=["The Forge", "Domain", "Sinq Laison"],
        )

        flags = await assets_analyzer.analyze(base_applicant)

        yellow_flags = [f for f in flags if f.severity == FlagSeverity.YELLOW]
        assert any(f.code == YellowFlags.HIGH_SEC_ONLY for f in yellow_flags)

    @pytest.mark.asyncio
    async def test_no_highsec_flag_for_nullsec_presence(self, assets_analyzer, base_applicant):
        """Assets in nullsec should not trigger HIGH_SEC_ONLY flag."""
        base_applicant.assets = AssetSummary(
            total_value_isk=5_000_000_000,
            capital_ships=[],
            supercapitals=[],
            primary_regions=["The Forge", "Delve"],  # Mix of highsec and null
        )

        flags = await assets_analyzer.analyze(base_applicant)

        assert not any(f.code == YellowFlags.HIGH_SEC_ONLY for f in flags)

    @pytest.mark.asyncio
    async def test_structure_ownership_established_flag(self, assets_analyzer, base_applicant):
        """Structure ownership should trigger ESTABLISHED flag."""
        base_applicant.assets = AssetSummary(
            total_value_isk=5_000_000_000,
            capital_ships=[],
            supercapitals=[],
            primary_regions=["Delve"],
            has_structures=True,
        )

        flags = await assets_analyzer.analyze(base_applicant)

        established_flags = [f for f in flags if f.code == GreenFlags.ESTABLISHED]
        assert any("structure" in f.reason.lower() for f in established_flags)

    @pytest.mark.asyncio
    async def test_no_structure_flag_when_false(self, assets_analyzer, base_applicant):
        """No structure ownership should not add structure-related flags."""
        base_applicant.assets = AssetSummary(
            total_value_isk=5_000_000_000,
            capital_ships=[],
            supercapitals=[],
            primary_regions=["Delve"],
            has_structures=False,
        )

        flags = await assets_analyzer.analyze(base_applicant)

        structure_flags = [f for f in flags if "structure" in f.reason.lower()]
        assert len(structure_flags) == 0

    @pytest.mark.asyncio
    async def test_empty_regions_no_highsec_flag(self, assets_analyzer, base_applicant):
        """Empty regions list should not trigger HIGH_SEC_ONLY flag."""
        base_applicant.assets = AssetSummary(
            total_value_isk=5_000_000_000,
            capital_ships=[],
            supercapitals=[],
            primary_regions=[],
        )

        flags = await assets_analyzer.analyze(base_applicant)

        assert not any(f.code == YellowFlags.HIGH_SEC_ONLY for f in flags)

    @pytest.mark.asyncio
    async def test_none_total_value_no_asset_flag(self, assets_analyzer, base_applicant):
        """None total_value_isk should not trigger asset value flags."""
        base_applicant.assets = AssetSummary(
            total_value_isk=None,
            capital_ships=["Archon"],
            supercapitals=[],
            primary_regions=["Delve"],
        )

        flags = await assets_analyzer.analyze(base_applicant)

        # Should still get capital pilot flag
        assert any(f.code == GreenFlags.CAPITAL_PILOT for f in flags)
        # But no asset value flags
        assert not any(f.code == YellowFlags.NO_ASSETS for f in flags)
        # And no established flag from value (only from structures)
        value_established = [
            f for f in flags if f.code == GreenFlags.ESTABLISHED and "ISK" in f.reason
        ]
        assert len(value_established) == 0

    @pytest.mark.asyncio
    async def test_all_capital_types_recognized(self, assets_analyzer, base_applicant):
        """All capital ship types should be recognized."""
        # Test carriers
        for ship in ["Archon", "Chimera", "Nidhoggur", "Thanatos"]:
            base_applicant.assets = AssetSummary(
                total_value_isk=5_000_000_000,
                capital_ships=[ship],
            )
            flags = await assets_analyzer.analyze(base_applicant)
            assert any(f.code == GreenFlags.CAPITAL_PILOT for f in flags), f"{ship} not recognized"

        # Test dreads
        for ship in ["Revelation", "Phoenix", "Naglfar", "Moros"]:
            base_applicant.assets = AssetSummary(
                total_value_isk=5_000_000_000,
                capital_ships=[ship],
            )
            flags = await assets_analyzer.analyze(base_applicant)
            assert any(f.code == GreenFlags.CAPITAL_PILOT for f in flags), f"{ship} not recognized"

        # Test FAX
        for ship in ["Apostle", "Minokawa", "Lif", "Ninazu"]:
            base_applicant.assets = AssetSummary(
                total_value_isk=5_000_000_000,
                capital_ships=[ship],
            )
            flags = await assets_analyzer.analyze(base_applicant)
            assert any(f.code == GreenFlags.CAPITAL_PILOT for f in flags), f"{ship} not recognized"

    @pytest.mark.asyncio
    async def test_all_supercapital_types_recognized(self, assets_analyzer, base_applicant):
        """All supercapital ship types should be recognized."""
        # Test supercarriers
        for ship in ["Aeon", "Wyvern", "Hel", "Nyx", "Vendetta", "Revenant"]:
            base_applicant.assets = AssetSummary(
                total_value_isk=100_000_000_000,
                supercapitals=[ship],
            )
            flags = await assets_analyzer.analyze(base_applicant)
            assert any(f.code == GreenFlags.CAPITAL_PILOT for f in flags), f"{ship} not recognized"
            assert any(
                f.code == GreenFlags.CAPITAL_PILOT and f.confidence == 0.95 for f in flags
            ), f"{ship} should have 0.95 confidence"

        # Test titans
        for ship in ["Avatar", "Leviathan", "Ragnarok", "Erebus", "Vanquisher", "Komodo", "Molok"]:
            base_applicant.assets = AssetSummary(
                total_value_isk=100_000_000_000,
                supercapitals=[ship],
            )
            flags = await assets_analyzer.analyze(base_applicant)
            assert any(f.code == GreenFlags.CAPITAL_PILOT for f in flags), f"{ship} not recognized"

    @pytest.mark.asyncio
    async def test_combined_flags(self, assets_analyzer, base_applicant):
        """Test that multiple flag types can be returned together."""
        base_applicant.assets = AssetSummary(
            total_value_isk=50_000_000_000,  # 50B
            capital_ships=["Revelation", "Apostle"],
            supercapitals=["Nyx"],
            primary_regions=["Delve", "Querious"],
            has_structures=True,
        )

        flags = await assets_analyzer.analyze(base_applicant)

        # Should have: CAPITAL_PILOT (super), ESTABLISHED (value), ESTABLISHED (structures)
        assert any(f.code == GreenFlags.CAPITAL_PILOT for f in flags)
        established_flags = [f for f in flags if f.code == GreenFlags.ESTABLISHED]
        assert len(established_flags) >= 2  # One for value, one for structures

    @pytest.mark.asyncio
    async def test_analyzer_metadata(self, assets_analyzer):
        """Test analyzer metadata properties."""
        assert assets_analyzer.name == "assets"
        assert assets_analyzer.requires_auth is True
        assert "asset" in assets_analyzer.description.lower()
