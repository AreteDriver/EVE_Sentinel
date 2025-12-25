"""Applicant/Character profile models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CorpHistoryEntry(BaseModel):
    """A single corporation membership record."""

    corporation_id: int
    corporation_name: str
    start_date: datetime
    end_date: datetime | None = None
    duration_days: int | None = None
    is_hostile: bool = False
    is_npc: bool = False


class KillboardStats(BaseModel):
    """Killboard statistics summary."""

    kills_total: int = 0
    kills_30d: int = 0
    kills_90d: int = 0
    deaths_total: int = 0
    deaths_30d: int = 0
    solo_kills: int = 0
    awox_kills: int = 0  # Kills on corp/alliance mates
    isk_destroyed: float = 0.0
    isk_lost: float = 0.0
    top_ships: list[str] = Field(default_factory=list)
    top_regions: list[str] = Field(default_factory=list)
    avg_fleet_size: float | None = None
    danger_ratio: float | None = None  # zKill danger ratio
    gang_ratio: float | None = None  # zKill gang ratio


class ActivityPattern(BaseModel):
    """Character activity patterns."""

    primary_timezone: str | None = None  # e.g., "EU-TZ", "US-TZ", "AU-TZ"
    peak_hours: list[int] = Field(default_factory=list)  # 0-23 EVE time
    active_days_per_week: float | None = None
    last_kill_date: datetime | None = None
    last_loss_date: datetime | None = None
    activity_trend: str | None = None  # "increasing", "stable", "declining", "inactive"


class AssetSummary(BaseModel):
    """Character asset summary (requires auth data)."""

    total_value_isk: float | None = None
    capital_ships: list[str] = Field(default_factory=list)
    supercapitals: list[str] = Field(default_factory=list)
    primary_regions: list[str] = Field(default_factory=list)
    has_structures: bool = False


class SuspectedAlt(BaseModel):
    """A suspected alt character."""

    character_id: int
    character_name: str
    confidence: float  # 0.0 to 1.0
    detection_method: str  # e.g., "login_correlation", "naming_pattern", "shared_assets"
    evidence: dict[str, Any] | None = None


class Playstyle(BaseModel):
    """Character playstyle analysis."""

    primary: str | None = None  # e.g., "Capital Pilot", "Small Gang", "F1 Monkey"
    secondary: str | None = None
    ship_classes: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)  # "DPS", "Logi", "Tackle", "FC"
    space_preference: str | None = None  # "null", "low", "wh", "high"
    group_size_preference: str | None = None  # "solo", "small_gang", "fleet"


class Applicant(BaseModel):
    """Complete applicant profile for analysis."""

    # Core identity
    character_id: int
    character_name: str
    corporation_id: int | None = None
    corporation_name: str | None = None
    alliance_id: int | None = None
    alliance_name: str | None = None

    # Character info
    birthday: datetime | None = None
    security_status: float | None = None
    character_age_days: int | None = None

    # Analysis components
    corp_history: list[CorpHistoryEntry] = Field(default_factory=list)
    killboard: KillboardStats = Field(default_factory=KillboardStats)
    activity: ActivityPattern = Field(default_factory=ActivityPattern)
    assets: AssetSummary | None = None
    playstyle: Playstyle = Field(default_factory=Playstyle)

    # Alt detection
    suspected_alts: list[SuspectedAlt] = Field(default_factory=list)
    declared_alts: list[str] = Field(default_factory=list)

    # Metadata
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    data_sources: list[str] = Field(default_factory=list)  # ["esi", "zkill", "auth"]
