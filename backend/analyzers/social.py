"""Social network analysis for detecting alt networks and social patterns."""

from backend.models.applicant import Applicant
from backend.models.flags import (
    FlagCategory,
    FlagSeverity,
    RedFlags,
    RiskFlag,
)

from .base import BaseAnalyzer


class SocialAnalyzer(BaseAnalyzer):
    """
    Analyzes character social connections and alt networks to identify:
    - Undisclosed alt networks
    - Alts in hostile corporations/alliances
    - Suspicious alt detection patterns
    - Contact network anomalies
    - Transparency concerns (suspected vs. declared alts)

    Partially requires auth data for contact analysis.
    """

    name = "social"
    description = "Analyzes social connections and alt networks"
    requires_auth = False  # Basic alt analysis works without auth

    # Thresholds
    HIGH_CONFIDENCE_ALT_THRESHOLD = 0.8
    MEDIUM_CONFIDENCE_ALT_THRESHOLD = 0.5
    MANY_ALTS_THRESHOLD = 5
    SUSPICIOUS_ALTS_THRESHOLD = 3

    # Configurable hostile entity lists
    HOSTILE_ALLIANCES: set[int] = set()
    HOSTILE_CORPS: set[int] = set()

    async def analyze(self, applicant: Applicant) -> list[RiskFlag]:
        """Analyze character social connections and alt networks."""
        flags: list[RiskFlag] = []

        # Analyze suspected alts
        flags.extend(self._analyze_alt_network(applicant))

        # Analyze declared vs suspected alts discrepancy
        flags.extend(self._analyze_alt_transparency(applicant))

        # Analyze contacts if available
        if applicant.standings_data:
            flags.extend(self._analyze_contacts(applicant))

        return flags

    def _analyze_alt_network(self, applicant: Applicant) -> list[RiskFlag]:
        """Analyze the detected alt network for concerns."""
        flags: list[RiskFlag] = []
        suspected_alts = applicant.suspected_alts

        if not suspected_alts:
            return flags

        # Check for alts in hostile entities
        hostile_alts = self._find_hostile_alts(suspected_alts, applicant)
        if hostile_alts:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.RED,
                    category=FlagCategory.ALTS,
                    code=RedFlags.HIDDEN_ALTS,
                    reason=f"Suspected alts detected in {len(hostile_alts)} hostile entities",
                    evidence={
                        "hostile_alts": hostile_alts,
                        "detection_methods": [
                            alt.detection_method
                            for alt in suspected_alts
                            if alt.character_name in [h["character_name"] for h in hostile_alts]
                        ],
                    },
                    confidence=0.85,
                )
            )

        # Check for high-confidence alt detections
        high_confidence_alts = [
            alt for alt in suspected_alts if alt.confidence >= self.HIGH_CONFIDENCE_ALT_THRESHOLD
        ]
        if len(high_confidence_alts) >= self.SUSPICIOUS_ALTS_THRESHOLD:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.YELLOW,
                    category=FlagCategory.ALTS,
                    code="LARGE_ALT_NETWORK",
                    reason=f"Large alt network detected ({len(high_confidence_alts)} high-confidence alts)",
                    evidence={
                        "alt_count": len(high_confidence_alts),
                        "detection_methods": list(
                            set(alt.detection_method for alt in high_confidence_alts)
                        ),
                        "alt_names": [alt.character_name for alt in high_confidence_alts[:5]],
                    },
                    confidence=0.7,
                )
            )

        # Check for suspicious detection patterns
        # Multiple alts detected by login correlation could indicate spy behavior
        login_corr_alts = [
            alt
            for alt in suspected_alts
            if alt.detection_method == "login_correlation"
            and alt.confidence >= self.MEDIUM_CONFIDENCE_ALT_THRESHOLD
        ]
        if len(login_corr_alts) >= self.MANY_ALTS_THRESHOLD:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.YELLOW,
                    category=FlagCategory.ALTS,
                    code="LOGIN_CORRELATION_ALTS",
                    reason=f"Multiple alts detected via login patterns ({len(login_corr_alts)})",
                    evidence={
                        "login_correlation_count": len(login_corr_alts),
                        "alt_names": [alt.character_name for alt in login_corr_alts[:5]],
                    },
                    confidence=0.65,
                )
            )

        return flags

    def _analyze_alt_transparency(self, applicant: Applicant) -> list[RiskFlag]:
        """Check for discrepancies between declared and suspected alts."""
        flags: list[RiskFlag] = []

        declared_count = len(applicant.declared_alts)
        suspected_count = len(
            [
                alt
                for alt in applicant.suspected_alts
                if alt.confidence >= self.MEDIUM_CONFIDENCE_ALT_THRESHOLD
            ]
        )

        # Red flag: Suspected alts but none declared (potential spy behavior)
        if suspected_count >= 2 and declared_count == 0:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.YELLOW,
                    category=FlagCategory.ALTS,
                    code="UNDECLARED_ALTS",
                    reason=f"Suspected alts detected but none declared ({suspected_count} suspected)",
                    evidence={
                        "suspected_count": suspected_count,
                        "declared_count": declared_count,
                        "suspected_names": [
                            alt.character_name
                            for alt in applicant.suspected_alts
                            if alt.confidence >= self.MEDIUM_CONFIDENCE_ALT_THRESHOLD
                        ][:5],
                    },
                    confidence=0.6,
                )
            )

        # Significant mismatch between declared and suspected
        if declared_count > 0 and suspected_count > declared_count * 2:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.YELLOW,
                    category=FlagCategory.ALTS,
                    code="ALT_COUNT_MISMATCH",
                    reason=f"More alts suspected than declared ({suspected_count} vs {declared_count})",
                    evidence={
                        "suspected_count": suspected_count,
                        "declared_count": declared_count,
                    },
                    confidence=0.5,
                )
            )

        # Green flag: Transparent about alts
        if declared_count >= 1 and suspected_count <= declared_count + 1:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.GREEN,
                    category=FlagCategory.ALTS,
                    code="TRANSPARENT_ALTS",
                    reason=f"Character is transparent about alt characters ({declared_count} declared)",
                    evidence={
                        "declared_count": declared_count,
                        "suspected_count": suspected_count,
                    },
                    confidence=0.7,
                )
            )

        return flags

    def _analyze_contacts(self, applicant: Applicant) -> list[RiskFlag]:
        """Analyze contact list for concerning patterns."""
        flags: list[RiskFlag] = []

        standings_data = applicant.standings_data
        if not standings_data:
            return flags

        contacts = standings_data.get("contacts", [])
        if not contacts:
            return flags

        # Count contacts by type and standing
        hostile_contacts = []
        negative_contacts = []
        positive_contacts = []

        for contact in contacts:
            entity_id = contact.get("contact_id")
            entity_type = contact.get("contact_type")
            standing = contact.get("standing", 0)

            # Check if contact is in hostile list
            if entity_type == "alliance" and entity_id in self.HOSTILE_ALLIANCES:
                hostile_contacts.append(
                    {
                        "entity_id": entity_id,
                        "entity_type": entity_type,
                        "standing": standing,
                    }
                )
            elif entity_type == "corporation" and entity_id in self.HOSTILE_CORPS:
                hostile_contacts.append(
                    {
                        "entity_id": entity_id,
                        "entity_type": entity_type,
                        "standing": standing,
                    }
                )

            if standing < 0:
                negative_contacts.append(contact)
            elif standing > 0:
                positive_contacts.append(contact)

        # Red flag: Positive standings with hostile contacts
        hostile_positive = [c for c in hostile_contacts if c["standing"] > 0]
        if hostile_positive:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.RED,
                    category=FlagCategory.ALTS,
                    code="HOSTILE_POSITIVE_CONTACTS",
                    reason=f"Positive contact standings with {len(hostile_positive)} hostile entities",
                    evidence={
                        "hostile_positive": hostile_positive,
                    },
                    confidence=0.85,
                )
            )

        # Yellow flag: Many negative contacts (could indicate conflict history)
        if len(negative_contacts) > 20:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.YELLOW,
                    category=FlagCategory.ALTS,
                    code="MANY_NEGATIVE_CONTACTS",
                    reason=f"High number of negative contacts ({len(negative_contacts)})",
                    evidence={
                        "negative_contact_count": len(negative_contacts),
                    },
                    confidence=0.4,
                )
            )

        # Green flag: Maintains contact list (organized player)
        if len(positive_contacts) >= 10 and len(hostile_contacts) == 0:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.GREEN,
                    category=FlagCategory.ALTS,
                    code="ORGANIZED_CONTACTS",
                    reason=f"Well-maintained contact list ({len(positive_contacts)} positive contacts)",
                    evidence={
                        "positive_contact_count": len(positive_contacts),
                        "total_contact_count": len(contacts),
                    },
                    confidence=0.5,
                )
            )

        return flags

    def _find_hostile_alts(
        self,
        suspected_alts: list,
        applicant: Applicant,
    ) -> list[dict]:
        """Find suspected alts that are in hostile entities."""
        hostile_alts = []

        for alt in suspected_alts:
            if alt.confidence < self.MEDIUM_CONFIDENCE_ALT_THRESHOLD:
                continue

            # Check if alt's evidence contains corp/alliance info
            evidence = alt.evidence or {}
            corp_id = evidence.get("corporation_id")
            alliance_id = evidence.get("alliance_id")

            if corp_id and corp_id in self.HOSTILE_CORPS:
                hostile_alts.append(
                    {
                        "character_id": alt.character_id,
                        "character_name": alt.character_name,
                        "hostile_corp_id": corp_id,
                        "confidence": alt.confidence,
                    }
                )
            elif alliance_id and alliance_id in self.HOSTILE_ALLIANCES:
                hostile_alts.append(
                    {
                        "character_id": alt.character_id,
                        "character_name": alt.character_name,
                        "hostile_alliance_id": alliance_id,
                        "confidence": alt.confidence,
                    }
                )

        return hostile_alts

    def add_hostile_alliance(self, alliance_id: int) -> None:
        """Add an alliance to the hostile list."""
        self.HOSTILE_ALLIANCES.add(alliance_id)

    def add_hostile_corp(self, corp_id: int) -> None:
        """Add a corporation to the hostile list."""
        self.HOSTILE_CORPS.add(corp_id)
