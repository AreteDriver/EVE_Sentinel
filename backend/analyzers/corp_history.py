"""Corporation history analysis for detecting spies and suspicious patterns."""

from datetime import UTC, datetime, timedelta

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


class CorpHistoryAnalyzer(BaseAnalyzer):
    """
    Analyzes corporation history to identify:
    - Known spy/hostile corporations
    - Rapid corp hopping patterns
    - NPC corp stints (possible awaiters)
    - Tenure stability
    """

    name = "corp_history"
    description = "Analyzes corporation history for suspicious patterns"
    requires_auth = False

    # Known hostile/spy corporations (configurable)
    # These should be loaded from config in production
    HOSTILE_CORPS: set[int] = {
        # Example hostile corp IDs - configure per alliance
        # 667531913,  # Goonwaffe
        # 98000001,   # Example
    }

    HOSTILE_ALLIANCES: set[int] = {
        # Example hostile alliance IDs
        # 1354830081,  # Goonswarm Federation
    }

    # Thresholds
    RAPID_HOP_COUNT = 5  # Corps in 6 months = red flag
    RAPID_HOP_WINDOW_DAYS = 180
    SHORT_TENURE_DAYS = 30
    ESTABLISHED_TENURE_DAYS = 365
    ESTABLISHED_TOTAL_DAYS = 730  # 2 years total history

    async def analyze(self, applicant: Applicant) -> list[RiskFlag]:
        """Analyze corporation history."""
        flags: list[RiskFlag] = []
        history = applicant.corp_history

        if not history:
            return flags

        # Check for hostile corp membership
        hostile_memberships = [
            entry for entry in history
            if entry.corporation_id in self.HOSTILE_CORPS or entry.is_hostile
        ]

        if hostile_memberships:
            for entry in hostile_memberships:
                flags.append(
                    RiskFlag(
                        severity=FlagSeverity.RED,
                        category=FlagCategory.CORP_HISTORY,
                        code=RedFlags.KNOWN_SPY_CORP,
                        reason=f"Was member of hostile corp '{entry.corporation_name}'",
                        evidence={
                            "corp_id": entry.corporation_id,
                            "corp_name": entry.corporation_name,
                            "start_date": entry.start_date.isoformat(),
                            "end_date": entry.end_date.isoformat() if entry.end_date else None,
                            "duration_days": entry.duration_days,
                        },
                        confidence=0.95,
                    )
                )

        # Check for rapid corp hopping
        now = datetime.now(UTC)
        window_start = now - timedelta(days=self.RAPID_HOP_WINDOW_DAYS)
        recent_corps = [
            entry for entry in history
            if entry.start_date >= window_start
        ]

        if len(recent_corps) >= self.RAPID_HOP_COUNT:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.RED,
                    category=FlagCategory.CORP_HISTORY,
                    code=RedFlags.RAPID_CORP_HOP,
                    reason=f"{len(recent_corps)} corporations in {self.RAPID_HOP_WINDOW_DAYS} days",
                    evidence={
                        "corp_count": len(recent_corps),
                        "window_days": self.RAPID_HOP_WINDOW_DAYS,
                        "recent_corps": [
                            {"name": e.corporation_name, "days": e.duration_days}
                            for e in recent_corps
                        ],
                    },
                    confidence=0.85,
                )
            )

        # Check current corp tenure
        current_corp = history[0] if history else None
        if current_corp and current_corp.duration_days is not None:
            if current_corp.duration_days < self.SHORT_TENURE_DAYS:
                flags.append(
                    RiskFlag(
                        severity=FlagSeverity.YELLOW,
                        category=FlagCategory.CORP_HISTORY,
                        code=YellowFlags.SHORT_TENURE,
                        reason=f"Only {current_corp.duration_days} days in current corp",
                        evidence={
                            "current_corp": current_corp.corporation_name,
                            "duration_days": current_corp.duration_days,
                            "threshold": self.SHORT_TENURE_DAYS,
                        },
                        confidence=0.75,
                    )
                )

        # Check for NPC corp patterns (potential awaiters/spies)
        npc_stints = [entry for entry in history if entry.is_npc]
        long_npc_stints = [e for e in npc_stints if e.duration_days and e.duration_days > 30]
        if len(long_npc_stints) >= 2:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.YELLOW,
                    category=FlagCategory.CORP_HISTORY,
                    code="NPC_CORP_PATTERN",
                    reason=f"Multiple extended NPC corp stints ({len(long_npc_stints)})",
                    evidence={
                        "npc_stints": len(long_npc_stints),
                        "details": [
                            {"corp": e.corporation_name, "days": e.duration_days}
                            for e in long_npc_stints
                        ],
                    },
                    confidence=0.6,
                )
            )

        # GREEN FLAG: Established character
        total_player_corp_days = sum(
            e.duration_days or 0 for e in history if not e.is_npc
        )
        longest_tenure = max((e.duration_days or 0 for e in history), default=0)

        if (total_player_corp_days >= self.ESTABLISHED_TOTAL_DAYS and
            longest_tenure >= self.ESTABLISHED_TENURE_DAYS):
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.GREEN,
                    category=FlagCategory.CORP_HISTORY,
                    code=GreenFlags.ESTABLISHED,
                    reason="Established character with stable corp history",
                    evidence={
                        "total_player_corp_days": total_player_corp_days,
                        "longest_tenure_days": longest_tenure,
                        "total_corps": len(history),
                    },
                    confidence=0.8,
                )
            )

        # GREEN FLAG: Clean history (no hostiles, reasonable stability)
        if not hostile_memberships and len(recent_corps) < 3:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.GREEN,
                    category=FlagCategory.CORP_HISTORY,
                    code=GreenFlags.CLEAN_HISTORY,
                    reason="No hostile affiliations, stable corp history",
                    evidence={
                        "recent_corp_count": len(recent_corps),
                        "hostile_count": 0,
                    },
                    confidence=0.7,
                )
            )

        return flags

    def add_hostile_corp(self, corp_id: int) -> None:
        """Add a corporation to the hostile list."""
        self.HOSTILE_CORPS.add(corp_id)

    def add_hostile_alliance(self, alliance_id: int) -> None:
        """Add an alliance to the hostile list."""
        self.HOSTILE_ALLIANCES.add(alliance_id)
