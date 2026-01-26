"""Tests for ML risk scoring."""

from datetime import UTC, datetime

import numpy as np
import pytest

from backend.ml.feature_extractor import FeatureExtractor
from backend.ml.model import RiskModel
from backend.models.applicant import (
    ActivityPattern,
    Applicant,
    CorpHistoryEntry,
    KillboardStats,
)
from backend.models.report import OverallRisk


@pytest.fixture
def sample_applicant() -> Applicant:
    """Create a sample applicant for testing."""
    return Applicant(
        character_id=12345678,
        character_name="Test Pilot",
        corporation_id=98765432,
        corporation_name="Test Corp",
        character_age_days=730,
        security_status=2.5,
        killboard=KillboardStats(
            kills_total=200,
            kills_90d=50,
            deaths_total=40,
            solo_kills=30,
            awox_kills=0,
            isk_destroyed=100_000_000_000.0,
            danger_ratio=0.6,
        ),
        corp_history=[
            CorpHistoryEntry(
                corporation_id=98765432,
                corporation_name="Test Corp",
                start_date=datetime(2024, 6, 1, tzinfo=UTC),
                duration_days=200,
                is_hostile=False,
            ),
            CorpHistoryEntry(
                corporation_id=88888888,
                corporation_name="Previous Corp",
                start_date=datetime(2023, 1, 1, tzinfo=UTC),
                end_date=datetime(2024, 6, 1, tzinfo=UTC),
                duration_days=517,
                is_hostile=False,
            ),
        ],
        activity=ActivityPattern(
            primary_timezone="EU-TZ",
            active_days_per_week=5.0,
            last_kill_date=datetime(2025, 1, 15, tzinfo=UTC),
            activity_trend="stable",
        ),
    )


class TestFeatureExtractor:
    """Tests for FeatureExtractor."""

    def test_extract_returns_correct_shape(self, sample_applicant: Applicant) -> None:
        """Test that extract returns correct number of features."""
        extractor = FeatureExtractor()
        features = extractor.extract(sample_applicant)

        assert isinstance(features, np.ndarray)
        assert features.shape == (len(FeatureExtractor.FEATURE_NAMES),)

    def test_extract_batch(self, sample_applicant: Applicant) -> None:
        """Test batch extraction."""
        extractor = FeatureExtractor()
        applicants = [sample_applicant, sample_applicant]
        features = extractor.extract_batch(applicants)

        assert features.shape == (2, len(FeatureExtractor.FEATURE_NAMES))

    def test_feature_values_are_reasonable(self, sample_applicant: Applicant) -> None:
        """Test that extracted features have reasonable values."""
        extractor = FeatureExtractor()
        features = extractor.extract(sample_applicant)

        # Check kills_total (index 0)
        assert features[0] == 200.0

        # Check kills_90d (index 1)
        assert features[1] == 50.0

        # Check deaths (index 2)
        assert features[2] == 40.0

        # Check kill/death ratio (index 6)
        assert features[6] == 200.0 / 40.0  # 5.0

    def test_handles_missing_data(self) -> None:
        """Test extraction with minimal applicant data."""
        minimal_applicant = Applicant(
            character_id=1,
            character_name="Minimal",
        )

        extractor = FeatureExtractor()
        features = extractor.extract(minimal_applicant)

        # Should not raise, should return all zeros/defaults
        assert features.shape == (len(FeatureExtractor.FEATURE_NAMES),)
        assert not np.any(np.isnan(features))


class TestRiskModel:
    """Tests for RiskModel."""

    def test_risk_to_int_conversion(self) -> None:
        """Test risk level to integer conversion."""
        assert RiskModel.risk_to_int(OverallRisk.GREEN) == 0
        assert RiskModel.risk_to_int(OverallRisk.YELLOW) == 1
        assert RiskModel.risk_to_int(OverallRisk.RED) == 2

    def test_int_to_risk_conversion(self) -> None:
        """Test integer to risk level conversion."""
        assert RiskModel.int_to_risk(0) == OverallRisk.GREEN
        assert RiskModel.int_to_risk(1) == OverallRisk.YELLOW
        assert RiskModel.int_to_risk(2) == OverallRisk.RED

    def test_train_and_predict(self, sample_applicant: Applicant) -> None:
        """Test model training and prediction."""
        extractor = FeatureExtractor()

        # Create synthetic training data
        n_samples = 30
        X = np.random.rand(n_samples, extractor.feature_count()).astype(np.float32)
        y = np.array([0] * 10 + [1] * 10 + [2] * 10)  # Balanced classes

        # Train model
        model = RiskModel()
        model.train(X, y)

        # Predict
        predictions = model.predict(X[:3])
        assert len(predictions) == 3
        assert all(isinstance(p, OverallRisk) for p in predictions)

    def test_predict_with_confidence(self, sample_applicant: Applicant) -> None:
        """Test prediction with confidence scores."""
        extractor = FeatureExtractor()

        # Create synthetic training data
        n_samples = 30
        X = np.random.rand(n_samples, extractor.feature_count()).astype(np.float32)
        y = np.array([0] * 10 + [1] * 10 + [2] * 10)

        # Train and predict
        model = RiskModel()
        model.train(X, y)

        results = model.predict_with_confidence(X[:3])

        assert len(results) == 3
        for prediction, confidence in results:
            assert isinstance(prediction, OverallRisk)
            assert 0.0 <= confidence <= 1.0

    def test_feature_importances(self) -> None:
        """Test feature importance extraction."""
        extractor = FeatureExtractor()

        # Train a model
        n_samples = 30
        X = np.random.rand(n_samples, extractor.feature_count()).astype(np.float32)
        y = np.array([0] * 10 + [1] * 10 + [2] * 10)

        model = RiskModel()
        model.train(X, y)

        importances = model.get_feature_importances()

        assert len(importances) == extractor.feature_count()
        assert all(0.0 <= v <= 1.0 for v in importances.values())
        assert abs(sum(importances.values()) - 1.0) < 0.01  # Should sum to ~1
