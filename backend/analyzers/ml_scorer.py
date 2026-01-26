"""ML-based risk scoring analyzer."""

from backend.ml import FeatureExtractor, RiskModel
from backend.models.applicant import Applicant
from backend.models.flags import FlagCategory, FlagSeverity, RiskFlag
from backend.models.report import OverallRisk

from .base import BaseAnalyzer


class MLScorer(BaseAnalyzer):
    """
    Machine learning-based risk scorer.

    Uses a trained GradientBoostingClassifier to predict risk levels
    based on historical analysis patterns. This analyzer augments
    (does not replace) rule-based scoring.
    """

    name = "ml_scorer"
    description = "ML-based risk prediction using historical patterns"
    requires_auth = False

    def __init__(self) -> None:
        self._model: RiskModel | None = None
        self._extractor = FeatureExtractor()

    def _get_model(self) -> RiskModel | None:
        """Lazy-load the model on first use."""
        if self._model is None:
            model = RiskModel()
            if model.load():
                self._model = model
        return self._model

    @classmethod
    def is_available(cls) -> bool:
        """Check if a trained model is available."""
        return RiskModel().is_available()

    async def analyze(self, applicant: Applicant) -> list[RiskFlag]:
        """
        Analyze applicant using ML model.

        Returns a single ML_RISK_ASSESSMENT flag with the model's
        prediction and confidence score.
        """
        model = self._get_model()
        if model is None:
            return []  # No model available, skip ML analysis

        try:
            # Extract features
            features = self._extractor.extract(applicant)
            features = features.reshape(1, -1)

            # Get prediction with confidence
            results = model.predict_with_confidence(features)
            prediction, confidence = results[0]

            # Create flag based on prediction
            flag = self._create_flag(prediction, confidence)
            return [flag]

        except Exception:
            # If ML prediction fails, don't block the analysis
            return []

    def _create_flag(self, prediction: OverallRisk, confidence: float) -> RiskFlag:
        """Create a risk flag from the ML prediction."""
        severity_map = {
            OverallRisk.RED: FlagSeverity.RED,
            OverallRisk.YELLOW: FlagSeverity.YELLOW,
            OverallRisk.GREEN: FlagSeverity.GREEN,
            OverallRisk.UNKNOWN: FlagSeverity.YELLOW,
        }

        severity = severity_map[prediction]

        reason_map = {
            OverallRisk.RED: "ML model predicts high risk based on historical patterns",
            OverallRisk.YELLOW: "ML model predicts moderate risk - additional review suggested",
            OverallRisk.GREEN: "ML model predicts low risk based on similar applicant profiles",
            OverallRisk.UNKNOWN: "ML model unable to make confident prediction",
        }

        return RiskFlag(
            severity=severity,
            category=FlagCategory.GENERAL,
            code="ML_RISK_ASSESSMENT",
            reason=reason_map[prediction],
            evidence={
                "ml_prediction": prediction.value,
                "ml_confidence": round(confidence, 3),
                "model_type": "GradientBoostingClassifier",
            },
            confidence=confidence,
        )

    def get_feature_importances(self) -> dict[str, float] | None:
        """Get feature importance scores from the model."""
        model = self._get_model()
        if model is None:
            return None
        return model.get_feature_importances()
