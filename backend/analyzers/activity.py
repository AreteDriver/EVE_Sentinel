"""Activity pattern analysis for timezone and engagement detection."""

from datetime import UTC, datetime

from backend.models.applicant import Applicant
from backend.models.flags import (
    FlagCategory,
    FlagSeverity,
    GreenFlags,
    RiskFlag,
    YellowFlags,
)

from .base import BaseAnalyzer


class ActivityAnalyzer(BaseAnalyzer):
    """
    Analyzes character activity patterns to identify:
    - Timezone mismatches with target alliance
    - Inactive periods suggesting dormant accounts
    - Consistent activity patterns (positive indicator)
    - Low engagement warnings
    """

    name = "activity"
    description = "Analyzes login and activity patterns for timezone and engagement"
    requires_auth = True  # Best data comes from auth bridge

    # Thresholds
    INACTIVE_DAYS_THRESHOLD = 30  # No activity in 30 days = yellow flag
    SEVERELY_INACTIVE_DAYS = 90  # No activity in 90 days = stronger warning
    MIN_ACTIVE_DAYS_PER_WEEK = 2.0  # Less than 2 days/week = low engagement
    CONSISTENT_ACTIVE_DAYS = 4.0  # 4+ days/week = consistent activity

    # Target timezone for the alliance (configurable per-deployment)
    # Default to EU-TZ as most common
    TARGET_TIMEZONE: str | None = None  # Set to "EU-TZ", "US-TZ", or "AU-TZ"

    def __init__(self, target_timezone: str | None = None) -> None:
        """Initialize with optional target timezone."""
        self.target_tz = target_timezone or self.TARGET_TIMEZONE

    async def analyze(self, applicant: Applicant) -> list[RiskFlag]:
        """Analyze activity patterns for risk indicators."""
        flags: list[RiskFlag] = []
        activity = applicant.activity

        # 1. Timezone mismatch detection
        if self.target_tz:
            flags.extend(self._detect_timezone_mismatch(activity))

        # 2. Inactive period detection
        flags.extend(self._detect_inactive_periods(activity, applicant))

        # 3. Engagement level analysis
        flags.extend(self._analyze_engagement(activity))

        # 4. Activity trend analysis
        flags.extend(self._analyze_trend(activity))

        return flags

    def _detect_timezone_mismatch(self, activity) -> list[RiskFlag]:
        """Detect if player's timezone doesn't match alliance target."""
        flags: list[RiskFlag] = []

        if not activity.primary_timezone or not self.target_tz:
            return flags

        if activity.primary_timezone != self.target_tz:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.YELLOW,
                    category=FlagCategory.ACTIVITY,
                    code=YellowFlags.TIMEZONE_MISMATCH,
                    reason=(
                        f"Primary timezone {activity.primary_timezone} "
                        f"doesn't match alliance target {self.target_tz}"
                    ),
                    evidence={
                        "detected_tz": activity.primary_timezone,
                        "target_tz": self.target_tz,
                        "peak_hours": activity.peak_hours,
                    },
                    confidence=0.75,
                )
            )

        return flags

    def _detect_inactive_periods(
        self, activity, applicant: Applicant
    ) -> list[RiskFlag]:
        """Detect extended periods of inactivity."""
        flags: list[RiskFlag] = []
        now = datetime.now(UTC)

        # Check last kill date from killboard
        last_activity_date = activity.last_kill_date or activity.last_loss_date

        # If no killboard activity, check if we have activity trend data
        if not last_activity_date:
            if activity.activity_trend == "inactive":
                flags.append(
                    RiskFlag(
                        severity=FlagSeverity.YELLOW,
                        category=FlagCategory.ACTIVITY,
                        code=YellowFlags.INACTIVE_PERIOD,
                        reason="Account shows inactive status",
                        evidence={"activity_trend": activity.activity_trend},
                        confidence=0.7,
                    )
                )
            return flags

        days_since_activity = (now - last_activity_date).days

        if days_since_activity >= self.SEVERELY_INACTIVE_DAYS:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.YELLOW,
                    category=FlagCategory.ACTIVITY,
                    code=YellowFlags.INACTIVE_PERIOD,
                    reason=f"No PvP activity in {days_since_activity} days",
                    evidence={
                        "days_inactive": days_since_activity,
                        "last_activity": last_activity_date.isoformat(),
                        "threshold": self.SEVERELY_INACTIVE_DAYS,
                    },
                    confidence=0.85,
                )
            )
        elif days_since_activity >= self.INACTIVE_DAYS_THRESHOLD:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.YELLOW,
                    category=FlagCategory.ACTIVITY,
                    code=YellowFlags.INACTIVE_PERIOD,
                    reason=f"Limited recent activity ({days_since_activity} days since last PvP)",
                    evidence={
                        "days_inactive": days_since_activity,
                        "last_activity": last_activity_date.isoformat(),
                        "threshold": self.INACTIVE_DAYS_THRESHOLD,
                    },
                    confidence=0.7,
                )
            )

        return flags

    def _analyze_engagement(self, activity) -> list[RiskFlag]:
        """Analyze overall engagement level."""
        flags: list[RiskFlag] = []

        if activity.active_days_per_week is None:
            return flags

        if activity.active_days_per_week < self.MIN_ACTIVE_DAYS_PER_WEEK:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.YELLOW,
                    category=FlagCategory.ACTIVITY,
                    code=YellowFlags.LOW_ACTIVITY,
                    reason=(
                        f"Low engagement: {activity.active_days_per_week:.1f} "
                        f"active days per week"
                    ),
                    evidence={
                        "active_days_per_week": activity.active_days_per_week,
                        "threshold": self.MIN_ACTIVE_DAYS_PER_WEEK,
                    },
                    confidence=0.75,
                )
            )
        elif activity.active_days_per_week >= self.CONSISTENT_ACTIVE_DAYS:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.GREEN,
                    category=FlagCategory.ACTIVITY,
                    code=GreenFlags.CONSISTENT_ACTIVITY,
                    reason=(
                        f"Consistent activity: {activity.active_days_per_week:.1f} "
                        f"days per week"
                    ),
                    evidence={
                        "active_days_per_week": activity.active_days_per_week,
                        "peak_hours": activity.peak_hours,
                        "primary_timezone": activity.primary_timezone,
                    },
                    confidence=0.8,
                )
            )

        return flags

    def _analyze_trend(self, activity) -> list[RiskFlag]:
        """Analyze activity trend direction."""
        flags: list[RiskFlag] = []

        if not activity.activity_trend:
            return flags

        if activity.activity_trend == "declining":
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.YELLOW,
                    category=FlagCategory.ACTIVITY,
                    code=YellowFlags.INACTIVE_PERIOD,
                    reason="Activity trend is declining",
                    evidence={"activity_trend": activity.activity_trend},
                    confidence=0.65,
                )
            )
        elif activity.activity_trend == "increasing":
            # Positive indicator but not strong enough for green flag alone
            pass

        return flags

    def set_target_timezone(self, timezone: str) -> None:
        """Set the target timezone for mismatch detection.

        Args:
            timezone: One of "EU-TZ", "US-TZ", "AU-TZ"
        """
        valid_timezones = {"EU-TZ", "US-TZ", "AU-TZ"}
        if timezone not in valid_timezones:
            raise ValueError(f"Invalid timezone: {timezone}. Must be one of {valid_timezones}")
        self.target_tz = timezone
