"""Feature extraction from Applicant data for ML model."""

from datetime import UTC, datetime, timedelta

import numpy as np

from backend.models.applicant import Applicant


class FeatureExtractor:
    """Extracts numerical features from Applicant data for ML model."""

    FEATURE_NAMES = [
        # Killboard features
        "kills_total",
        "kills_90d",
        "deaths_total",
        "awox_kills",
        "isk_destroyed_billions",
        "danger_ratio",
        "kill_death_ratio",
        "solo_kill_ratio",
        # Corp history features
        "total_corps",
        "recent_corps_6mo",
        "avg_tenure_days",
        "hostile_corp_count",
        "npc_corp_count",
        "current_corp_tenure_days",
        # Activity features
        "active_days_per_week",
        "days_since_last_activity",
        "is_declining_activity",
        # Character features
        "age_days",
        "security_status",
        # Derived features
        "recent_activity_ratio",
        "corp_stability_score",
    ]

    def extract(self, applicant: Applicant) -> np.ndarray:
        """
        Extract feature vector from an Applicant.

        Args:
            applicant: The applicant to extract features from

        Returns:
            NumPy array of features
        """
        features = []

        # Killboard features
        kb = applicant.killboard
        features.append(self._safe_float(kb.kills_total))
        features.append(self._safe_float(kb.kills_90d))
        features.append(self._safe_float(kb.deaths_total))
        features.append(self._safe_float(kb.awox_kills))
        features.append(self._safe_float(kb.isk_destroyed) / 1_000_000_000)  # In billions
        features.append(self._safe_float(kb.danger_ratio, default=0.5))

        # Kill/death ratio (avoid division by zero)
        deaths = max(kb.deaths_total, 1)
        features.append(kb.kills_total / deaths)

        # Solo kill ratio
        total_kills = max(kb.kills_total, 1)
        features.append(kb.solo_kills / total_kills)

        # Corp history features
        corp_history = applicant.corp_history
        features.append(float(len(corp_history)))

        # Recent corps (last 6 months)
        six_months_ago = datetime.now(UTC) - timedelta(days=180)
        recent_corps = sum(
            1 for c in corp_history if c.start_date.replace(tzinfo=UTC) > six_months_ago
        )
        features.append(float(recent_corps))

        # Average tenure
        tenures = [c.duration_days for c in corp_history if c.duration_days is not None]
        avg_tenure = sum(tenures) / len(tenures) if tenures else 365
        features.append(float(avg_tenure))

        # Hostile corp count
        hostile_count = sum(1 for c in corp_history if c.is_hostile)
        features.append(float(hostile_count))

        # NPC corp count
        npc_count = sum(1 for c in corp_history if c.is_npc)
        features.append(float(npc_count))

        # Current corp tenure
        if corp_history and corp_history[0].start_date:
            current_tenure = (
                datetime.now(UTC) - corp_history[0].start_date.replace(tzinfo=UTC)
            ).days
        else:
            current_tenure = 0
        features.append(float(current_tenure))

        # Activity features
        activity = applicant.activity
        features.append(self._safe_float(activity.active_days_per_week, default=3.0))

        # Days since last activity
        days_since_activity = 0
        if activity.last_kill_date:
            days_since_activity = (
                datetime.now(UTC) - activity.last_kill_date.replace(tzinfo=UTC)
            ).days
        elif activity.last_loss_date:
            days_since_activity = (
                datetime.now(UTC) - activity.last_loss_date.replace(tzinfo=UTC)
            ).days
        features.append(float(days_since_activity))

        # Activity trend
        is_declining = 1.0 if activity.activity_trend == "declining" else 0.0
        features.append(is_declining)

        # Character features
        features.append(self._safe_float(applicant.character_age_days, default=365))
        features.append(self._safe_float(applicant.security_status, default=0.0))

        # Derived features
        # Recent activity ratio (kills_90d / kills_total)
        total = max(kb.kills_total, 1)
        recent_ratio = kb.kills_90d / total
        features.append(recent_ratio)

        # Corp stability score (inverse of corp hopping frequency)
        if corp_history and applicant.character_age_days:
            corps_per_year = len(corp_history) / max(applicant.character_age_days / 365, 1)
            stability = 1.0 / max(corps_per_year, 0.1)
        else:
            stability = 1.0
        features.append(min(stability, 10.0))  # Cap at 10

        return np.array(features, dtype=np.float32)

    def extract_batch(self, applicants: list[Applicant]) -> np.ndarray:
        """Extract features from multiple applicants."""
        return np.vstack([self.extract(a) for a in applicants])

    @staticmethod
    def _safe_float(value: float | int | None, default: float = 0.0) -> float:
        """Safely convert value to float."""
        if value is None:
            return default
        return float(value)

    @classmethod
    def feature_count(cls) -> int:
        """Return the number of features extracted."""
        return len(cls.FEATURE_NAMES)
