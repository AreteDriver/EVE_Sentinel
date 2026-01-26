"""Asset analysis for capital ships, wealth, and regional presence."""

from backend.models.applicant import Applicant, AssetSummary
from backend.models.flags import (
    FlagCategory,
    FlagSeverity,
    GreenFlags,
    RiskFlag,
    YellowFlags,
)

from .base import BaseAnalyzer


class AssetsAnalyzer(BaseAnalyzer):
    """
    Analyzes character assets to identify:
    - Capital/supercapital ownership (positive indicator)
    - Low/no asset declarations (potential risk)
    - Regional presence and commitment
    - Structure ownership (investment indicator)
    """

    name = "assets"
    description = "Analyzes character assets for wealth and capability indicators"
    requires_auth = True  # Needs auth bridge data for full asset info

    # Thresholds
    MIN_ASSET_VALUE_ISK = 500_000_000  # 500M minimum to not be flagged
    WEALTHY_THRESHOLD_ISK = 10_000_000_000  # 10B considered established
    SUPER_WEALTHY_THRESHOLD_ISK = 50_000_000_000  # 50B considered very wealthy

    # EVE capital ship type names
    CAPITAL_SHIPS = {
        # Carriers
        "Archon",
        "Chimera",
        "Nidhoggur",
        "Thanatos",
        # Force Auxiliaries
        "Apostle",
        "Minokawa",
        "Lif",
        "Ninazu",
        # Dreadnoughts
        "Revelation",
        "Phoenix",
        "Naglfar",
        "Moros",
        # Rorqual
        "Rorqual",
    }

    SUPERCAPITAL_SHIPS = {
        # Supercarriers
        "Aeon",
        "Wyvern",
        "Hel",
        "Nyx",
        "Vendetta",
        "Revenant",
        # Titans
        "Avatar",
        "Leviathan",
        "Ragnarok",
        "Erebus",
        "Vanquisher",
        "Komodo",
        "Molok",
    }

    async def analyze(self, applicant: Applicant) -> list[RiskFlag]:
        """Analyze applicant assets for risk indicators."""
        flags: list[RiskFlag] = []

        assets = applicant.assets

        # No asset data available
        if assets is None:
            return flags

        # 1. Check for capital ownership (positive)
        flags.extend(self._check_capital_ownership(assets))

        # 2. Check for low/no assets (negative)
        flags.extend(self._check_asset_value(assets))

        # 3. Check regional presence
        flags.extend(self._check_regional_presence(assets))

        # 4. Check structure ownership
        flags.extend(self._check_structure_ownership(assets))

        return flags

    def _check_capital_ownership(self, assets: AssetSummary) -> list[RiskFlag]:
        """Check for capital and supercapital ownership."""
        flags: list[RiskFlag] = []

        has_capitals = bool(assets.capital_ships)
        has_supers = bool(assets.supercapitals)

        if has_supers:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.GREEN,
                    category=FlagCategory.ASSETS,
                    code=GreenFlags.CAPITAL_PILOT,
                    reason=f"Owns supercapitals: {', '.join(assets.supercapitals)}",
                    evidence={
                        "supercapitals": assets.supercapitals,
                        "capitals": assets.capital_ships,
                    },
                    confidence=0.95,
                )
            )
        elif has_capitals:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.GREEN,
                    category=FlagCategory.ASSETS,
                    code=GreenFlags.CAPITAL_PILOT,
                    reason=f"Owns capital ships: {', '.join(assets.capital_ships)}",
                    evidence={
                        "capitals": assets.capital_ships,
                    },
                    confidence=0.90,
                )
            )

        return flags

    def _check_asset_value(self, assets: AssetSummary) -> list[RiskFlag]:
        """Check total asset value for warning signs."""
        flags: list[RiskFlag] = []

        total_value = assets.total_value_isk

        if total_value is None:
            # No value data available
            return flags

        if total_value < self.MIN_ASSET_VALUE_ISK:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.YELLOW,
                    category=FlagCategory.ASSETS,
                    code=YellowFlags.NO_ASSETS,
                    reason=f"Very low asset value: {total_value / 1e6:.0f}M ISK",
                    evidence={
                        "total_value_isk": total_value,
                        "threshold_isk": self.MIN_ASSET_VALUE_ISK,
                    },
                    confidence=0.80,
                )
            )
        elif total_value >= self.WEALTHY_THRESHOLD_ISK:
            # Established player with significant assets
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.GREEN,
                    category=FlagCategory.ASSETS,
                    code=GreenFlags.ESTABLISHED,
                    reason=f"Substantial assets: {total_value / 1e9:.1f}B ISK",
                    evidence={
                        "total_value_isk": total_value,
                    },
                    confidence=0.85,
                )
            )

        return flags

    def _check_regional_presence(self, assets: AssetSummary) -> list[RiskFlag]:
        """Check where the applicant's assets are located."""
        flags: list[RiskFlag] = []

        regions = assets.primary_regions

        if not regions:
            # No regional data
            return flags

        # Check for high-sec only presence (potential yellow flag for null alliances)
        highsec_regions = {
            "The Forge",
            "Domain",
            "Sinq Laison",
            "Metropolis",
            "Heimatar",
            "The Citadel",
            "Essence",
            "Lonetrek",
            "Placid",
            "Everyshore",
            "Verge Vendor",
            "Tash-Murkon",
            "Khanid",
            "Kador",
            "Kor-Azor",
            "Genesis",
            "Devoid",
            "Derelik",
            "Molden Heath",
            "Solitude",
            "Aridia",
        }

        all_highsec = all(r in highsec_regions for r in regions)

        if all_highsec and len(regions) > 0:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.YELLOW,
                    category=FlagCategory.ASSETS,
                    code=YellowFlags.HIGH_SEC_ONLY,
                    reason=f"Assets only in highsec regions: {', '.join(regions)}",
                    evidence={
                        "regions": regions,
                    },
                    confidence=0.70,
                )
            )

        return flags

    def _check_structure_ownership(self, assets: AssetSummary) -> list[RiskFlag]:
        """Check for structure ownership (indicates investment/commitment)."""
        flags: list[RiskFlag] = []

        if assets.has_structures:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.GREEN,
                    category=FlagCategory.ASSETS,
                    code=GreenFlags.ESTABLISHED,
                    reason="Owns player structures (citadels/engineering complexes)",
                    evidence={
                        "has_structures": True,
                    },
                    confidence=0.85,
                )
            )

        return flags
