"""Killboard analysis for detecting PvP patterns and AWOX behavior."""

from backend.models.applicant import Applicant
from backend.models.flags import (
    FlagCategory,
    FlagSeverity,
    GreenFlags,
    RedFlags,
    RiskFlag,
    YellowFlags,
)

from .base import BaseAnalyzer


class KillboardAnalyzer(BaseAnalyzer):
    """
    Analyzes zKillboard data to identify:
    - AWOX history (killing corp/alliance mates)
    - Activity levels
    - PvP competence
    - Ship preferences and roles
    """

    name = "killboard"
    description = "Analyzes zKillboard data for PvP patterns and AWOX detection"
    requires_auth = False

    # Thresholds
    AWOX_THRESHOLD = 1  # Any corp/alliance kills is a red flag
    LOW_ACTIVITY_KILLS_90D = 20
    ACTIVE_PVPER_KILLS_90D = 50
    INACTIVE_DAYS = 60

    async def analyze(self, applicant: Applicant) -> list[RiskFlag]:
        """Analyze killboard data."""
        flags: list[RiskFlag] = []
        kb = applicant.killboard

        # RED FLAG: AWOX history
        if kb.awox_kills >= self.AWOX_THRESHOLD:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.RED,
                    category=FlagCategory.KILLBOARD,
                    code=RedFlags.AWOX_HISTORY,
                    reason=f"Has {kb.awox_kills} kills on corp/alliance members",
                    evidence={
                        "awox_kills": kb.awox_kills,
                        "note": "Review kills for context - may be valid structure bashing",
                    },
                    confidence=0.9 if kb.awox_kills > 3 else 0.7,
                )
            )

        # YELLOW FLAG: Low activity
        if kb.kills_90d < self.LOW_ACTIVITY_KILLS_90D and kb.kills_total > 0:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.YELLOW,
                    category=FlagCategory.KILLBOARD,
                    code=YellowFlags.LOW_ACTIVITY,
                    reason=f"Only {kb.kills_90d} kills in past 90 days",
                    evidence={
                        "kills_90d": kb.kills_90d,
                        "kills_total": kb.kills_total,
                        "threshold": self.LOW_ACTIVITY_KILLS_90D,
                    },
                    confidence=0.8,
                )
            )

        # YELLOW FLAG: Highsec-only activity
        if kb.top_regions:
            highsec_regions = {"The Forge", "Domain", "Sinq Laison", "Metropolis", "Heimatar"}
            if all(r in highsec_regions for r in kb.top_regions[:3]):
                flags.append(
                    RiskFlag(
                        severity=FlagSeverity.YELLOW,
                        category=FlagCategory.KILLBOARD,
                        code=YellowFlags.HIGH_SEC_ONLY,
                        reason="Activity primarily in high-sec regions",
                        evidence={"top_regions": kb.top_regions[:5]},
                        confidence=0.7,
                    )
                )

        # GREEN FLAG: Active PvPer
        if kb.kills_90d >= self.ACTIVE_PVPER_KILLS_90D:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.GREEN,
                    category=FlagCategory.KILLBOARD,
                    code=GreenFlags.ACTIVE_PVPER,
                    reason=f"Active PvPer with {kb.kills_90d} kills in 90 days",
                    evidence={
                        "kills_90d": kb.kills_90d,
                        "kills_30d": kb.kills_30d,
                        "solo_kills": kb.solo_kills,
                    },
                    confidence=0.85,
                )
            )

        # GREEN FLAG: Logi pilot (from ship preferences)
        logi_ships = {
            "Guardian",
            "Oneiros",
            "Basilisk",
            "Scimitar",
            "Lif",
            "Ninazu",
            "Apostle",
            "Minokawa",
        }
        if any(ship in logi_ships for ship in kb.top_ships[:5]):
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.GREEN,
                    category=FlagCategory.KILLBOARD,
                    code=GreenFlags.LOGI_PILOT,
                    reason="Flies logistics ships",
                    evidence={
                        "logi_ships_in_top": [s for s in kb.top_ships[:5] if s in logi_ships]
                    },
                    confidence=0.8,
                )
            )

        return flags
