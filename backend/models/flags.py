"""Risk flag definitions for recruitment analysis."""

from enum import Enum
from typing import Any

from pydantic import BaseModel


class FlagSeverity(str, Enum):
    """Risk flag severity levels."""

    RED = "RED"  # High risk - likely reject
    YELLOW = "YELLOW"  # Caution - needs investigation
    GREEN = "GREEN"  # Positive indicator


class FlagCategory(str, Enum):
    """Categories of risk flags."""

    CORP_HISTORY = "corp_history"
    KILLBOARD = "killboard"
    ACTIVITY = "activity"
    ASSETS = "assets"
    WALLET = "wallet"
    STANDINGS = "standings"
    ALTS = "alts"
    GENERAL = "general"


class RiskFlag(BaseModel):
    """A single risk flag from analysis."""

    severity: FlagSeverity
    category: FlagCategory
    code: str  # e.g., "KNOWN_SPY_CORP", "LOW_ACTIVITY"
    reason: str  # Human-readable explanation
    evidence: dict[str, Any] | None = None  # Supporting data
    confidence: float = 1.0  # 0.0 to 1.0


# Pre-defined flag codes
class RedFlags:
    """High-risk flag codes."""

    KNOWN_SPY_CORP = "KNOWN_SPY_CORP"
    AWOX_HISTORY = "AWOX_HISTORY"
    RAPID_CORP_HOP = "RAPID_CORP_HOP"
    RMT_PATTERN = "RMT_PATTERN"
    HIDDEN_ALTS = "HIDDEN_ALTS"
    ENEMY_STANDINGS = "ENEMY_STANDINGS"
    RECENT_BIOMASS = "RECENT_BIOMASS"
    API_MANIPULATION = "API_MANIPULATION"


class YellowFlags:
    """Caution flag codes."""

    LOW_ACTIVITY = "LOW_ACTIVITY"
    SHORT_TENURE = "SHORT_TENURE"
    NO_ASSETS = "NO_ASSETS"
    TIMEZONE_MISMATCH = "TIMEZONE_MISMATCH"
    CYNO_ALT_PATTERN = "CYNO_ALT_PATTERN"
    NEW_CHARACTER = "NEW_CHARACTER"
    INACTIVE_PERIOD = "INACTIVE_PERIOD"
    HIGH_SEC_ONLY = "HIGH_SEC_ONLY"
    NO_FLEET_ACTIVITY = "NO_FLEET_ACTIVITY"


class GreenFlags:
    """Positive indicator codes."""

    ACTIVE_PVPER = "ACTIVE_PVPER"
    ESTABLISHED = "ESTABLISHED"
    CAPITAL_PILOT = "CAPITAL_PILOT"
    VOUCHED = "VOUCHED"
    CLEAN_HISTORY = "CLEAN_HISTORY"
    CONSISTENT_ACTIVITY = "CONSISTENT_ACTIVITY"
    FC_EXPERIENCE = "FC_EXPERIENCE"
    LOGI_PILOT = "LOGI_PILOT"
