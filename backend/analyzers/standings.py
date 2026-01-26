"""Standings analysis for detecting hostile affiliations and relationships."""

from backend.models.applicant import Applicant
from backend.models.flags import (
    FlagCategory,
    FlagSeverity,
    RedFlags,
    RiskFlag,
)

from .base import BaseAnalyzer


class StandingsAnalyzer(BaseAnalyzer):
    """
    Analyzes character standings to identify:
    - Positive standings with hostile entities
    - Negative standings with allied entities
    - Faction warfare affiliations
    - Patterns suggesting spy activity

    Requires auth data (Alliance Auth or SeAT) for standings information.
    """

    name = "standings"
    description = "Analyzes character standings for hostile affiliations"
    requires_auth = True

    # Configurable hostile and allied entity lists
    # These should be loaded from config in production
    HOSTILE_ALLIANCES: set[int] = set()
    HOSTILE_CORPS: set[int] = set()
    ALLIED_ALLIANCES: set[int] = set()
    ALLIED_CORPS: set[int] = set()

    # Faction warfare enemy factions (configurable per alliance)
    ENEMY_FACTIONS: set[int] = set()

    # Standings thresholds
    HOSTILE_STANDING_THRESHOLD = 5.0  # Positive standing with hostile = red flag
    ALLIED_NEGATIVE_THRESHOLD = -5.0  # Negative standing with ally = yellow flag

    async def analyze(self, applicant: Applicant) -> list[RiskFlag]:
        """Analyze character standings."""
        flags: list[RiskFlag] = []

        # Standings data comes from auth bridge enrichment
        standings_data = applicant.standings_data

        if not standings_data:
            # No standings data available - skip analysis
            return flags

        # Parse standings
        character_standings = standings_data.get("standings", [])
        contacts = standings_data.get("contacts", [])

        # Check for positive standings with hostile entities
        hostile_positive = self._find_hostile_positive_standings(character_standings, contacts)
        if hostile_positive:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.RED,
                    category=FlagCategory.STANDINGS,
                    code=RedFlags.ENEMY_STANDINGS,
                    reason=f"Positive standings with {len(hostile_positive)} hostile entities",
                    evidence={
                        "hostile_standings": hostile_positive,
                        "threshold": self.HOSTILE_STANDING_THRESHOLD,
                    },
                    confidence=0.9,
                )
            )

        # Check for negative standings with allied entities
        allied_negative = self._find_allied_negative_standings(character_standings, contacts)
        if allied_negative:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.YELLOW,
                    category=FlagCategory.STANDINGS,
                    code="ALLIED_NEGATIVE_STANDINGS",
                    reason=f"Negative standings with {len(allied_negative)} allied entities",
                    evidence={
                        "negative_standings": allied_negative,
                        "threshold": self.ALLIED_NEGATIVE_THRESHOLD,
                    },
                    confidence=0.75,
                )
            )

        # Check faction warfare standings
        fw_issues = self._check_faction_warfare(character_standings)
        if fw_issues:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.YELLOW,
                    category=FlagCategory.STANDINGS,
                    code="ENEMY_FACTION_STANDING",
                    reason="Positive standings with enemy faction(s)",
                    evidence={
                        "faction_standings": fw_issues,
                    },
                    confidence=0.7,
                )
            )

        # GREEN FLAG: Good standings with allies
        ally_positive = self._find_allied_positive_standings(character_standings, contacts)
        if len(ally_positive) >= 3 and not hostile_positive and not allied_negative:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.GREEN,
                    category=FlagCategory.STANDINGS,
                    code="ALLIED_STANDINGS",
                    reason=f"Positive standings with {len(ally_positive)} allied entities",
                    evidence={
                        "allied_standings_count": len(ally_positive),
                    },
                    confidence=0.7,
                )
            )

        return flags

    def _find_hostile_positive_standings(
        self,
        standings: list[dict],
        contacts: list[dict],
    ) -> list[dict]:
        """Find entities where character has positive standing with hostiles."""
        hostile_positive = []

        # Check standings
        for standing in standings:
            entity_id = standing.get("from_id") or standing.get("contact_id")
            entity_type = standing.get("from_type") or standing.get("contact_type")
            value = standing.get("standing", 0)

            if value >= self.HOSTILE_STANDING_THRESHOLD:
                if entity_type == "alliance" and entity_id in self.HOSTILE_ALLIANCES:
                    hostile_positive.append(
                        {
                            "entity_id": entity_id,
                            "entity_type": entity_type,
                            "standing": value,
                        }
                    )
                elif entity_type == "corporation" and entity_id in self.HOSTILE_CORPS:
                    hostile_positive.append(
                        {
                            "entity_id": entity_id,
                            "entity_type": entity_type,
                            "standing": value,
                        }
                    )

        # Check contacts
        for contact in contacts:
            entity_id = contact.get("contact_id")
            entity_type = contact.get("contact_type")
            value = contact.get("standing", 0)

            if value >= self.HOSTILE_STANDING_THRESHOLD:
                if entity_type == "alliance" and entity_id in self.HOSTILE_ALLIANCES:
                    hostile_positive.append(
                        {
                            "entity_id": entity_id,
                            "entity_type": entity_type,
                            "standing": value,
                        }
                    )
                elif entity_type == "corporation" and entity_id in self.HOSTILE_CORPS:
                    hostile_positive.append(
                        {
                            "entity_id": entity_id,
                            "entity_type": entity_type,
                            "standing": value,
                        }
                    )

        return hostile_positive

    def _find_allied_negative_standings(
        self,
        standings: list[dict],
        contacts: list[dict],
    ) -> list[dict]:
        """Find entities where character has negative standing with allies."""
        allied_negative = []

        all_standings = standings + contacts

        for standing in all_standings:
            entity_id = standing.get("from_id") or standing.get("contact_id")
            entity_type = standing.get("from_type") or standing.get("contact_type")
            value = standing.get("standing", 0)

            if value <= self.ALLIED_NEGATIVE_THRESHOLD:
                if entity_type == "alliance" and entity_id in self.ALLIED_ALLIANCES:
                    allied_negative.append(
                        {
                            "entity_id": entity_id,
                            "entity_type": entity_type,
                            "standing": value,
                        }
                    )
                elif entity_type == "corporation" and entity_id in self.ALLIED_CORPS:
                    allied_negative.append(
                        {
                            "entity_id": entity_id,
                            "entity_type": entity_type,
                            "standing": value,
                        }
                    )

        return allied_negative

    def _find_allied_positive_standings(
        self,
        standings: list[dict],
        contacts: list[dict],
    ) -> list[dict]:
        """Find entities where character has positive standing with allies."""
        allied_positive = []

        all_standings = standings + contacts

        for standing in all_standings:
            entity_id = standing.get("from_id") or standing.get("contact_id")
            entity_type = standing.get("from_type") or standing.get("contact_type")
            value = standing.get("standing", 0)

            if value >= 5.0:  # Positive threshold
                if entity_type == "alliance" and entity_id in self.ALLIED_ALLIANCES:
                    allied_positive.append(
                        {
                            "entity_id": entity_id,
                            "entity_type": entity_type,
                            "standing": value,
                        }
                    )
                elif entity_type == "corporation" and entity_id in self.ALLIED_CORPS:
                    allied_positive.append(
                        {
                            "entity_id": entity_id,
                            "entity_type": entity_type,
                            "standing": value,
                        }
                    )

        return allied_positive

    def _check_faction_warfare(self, standings: list[dict]) -> list[dict]:
        """Check for problematic faction warfare standings."""
        fw_issues = []

        for standing in standings:
            entity_id = standing.get("from_id")
            entity_type = standing.get("from_type")
            value = standing.get("standing", 0)

            if entity_type == "faction" and entity_id in self.ENEMY_FACTIONS:
                if value >= 1.0:  # Any positive standing with enemy faction
                    fw_issues.append(
                        {
                            "faction_id": entity_id,
                            "standing": value,
                        }
                    )

        return fw_issues

    def add_hostile_alliance(self, alliance_id: int) -> None:
        """Add an alliance to the hostile list."""
        self.HOSTILE_ALLIANCES.add(alliance_id)

    def add_hostile_corp(self, corp_id: int) -> None:
        """Add a corporation to the hostile list."""
        self.HOSTILE_CORPS.add(corp_id)

    def add_allied_alliance(self, alliance_id: int) -> None:
        """Add an alliance to the allied list."""
        self.ALLIED_ALLIANCES.add(alliance_id)

    def add_allied_corp(self, corp_id: int) -> None:
        """Add a corporation to the allied list."""
        self.ALLIED_CORPS.add(corp_id)

    def add_enemy_faction(self, faction_id: int) -> None:
        """Add a faction to the enemy list (for FW)."""
        self.ENEMY_FACTIONS.add(faction_id)
