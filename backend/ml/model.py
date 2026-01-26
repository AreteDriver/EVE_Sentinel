"""ML model wrapper for risk prediction."""

from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier

from backend.models.report import OverallRisk

from .feature_extractor import FeatureExtractor


class RiskModel:
    """Wrapper around scikit-learn GradientBoostingClassifier for risk prediction."""

    # Risk level mapping
    RISK_LABELS = {
        0: OverallRisk.GREEN,
        1: OverallRisk.YELLOW,
        2: OverallRisk.RED,
    }
    LABEL_TO_INT = {v: k for k, v in RISK_LABELS.items()}

    DEFAULT_MODEL_PATH = Path(__file__).parent.parent / "data" / "models" / "risk_model.joblib"

    def __init__(self, model_path: Path | None = None) -> None:
        self.model_path = model_path or self.DEFAULT_MODEL_PATH
        self.model: GradientBoostingClassifier | None = None
        self.feature_extractor = FeatureExtractor()
        self._is_loaded = False

    def load(self) -> bool:
        """
        Load the trained model from disk.

        Returns:
            True if model loaded successfully, False otherwise
        """
        if not self.model_path.exists():
            return False

        try:
            data = joblib.load(self.model_path)
            self.model = data["model"]
            self._is_loaded = True
            return True
        except Exception:
            return False

    def save(self, metadata: dict[str, Any] | None = None) -> None:
        """Save the model to disk."""
        if self.model is None:
            raise ValueError("No model to save")

        self.model_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "model": self.model,
            "feature_names": FeatureExtractor.FEATURE_NAMES,
            "metadata": metadata or {},
        }
        joblib.dump(data, self.model_path)

    def is_available(self) -> bool:
        """Check if a trained model is available."""
        if self._is_loaded:
            return True
        return self.model_path.exists()

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        **kwargs: Any,
    ) -> "RiskModel":
        """
        Train the model on labeled data.

        Args:
            X: Feature matrix (n_samples, n_features)
            y: Labels as integers (0=GREEN, 1=YELLOW, 2=RED)
            **kwargs: Additional arguments for GradientBoostingClassifier

        Returns:
            Self for chaining
        """
        params = {
            "n_estimators": 100,
            "max_depth": 5,
            "learning_rate": 0.1,
            "min_samples_split": 5,
            "min_samples_leaf": 2,
            "random_state": 42,
        }
        params.update(kwargs)

        self.model = GradientBoostingClassifier(**params)
        self.model.fit(X, y)
        self._is_loaded = True
        return self

    def predict(self, X: np.ndarray) -> list[OverallRisk]:
        """
        Predict risk levels for samples.

        Args:
            X: Feature matrix

        Returns:
            List of OverallRisk predictions
        """
        if self.model is None:
            raise ValueError("Model not loaded")

        predictions = self.model.predict(X)
        return [self.RISK_LABELS[int(p)] for p in predictions]

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """
        Get prediction probabilities.

        Args:
            X: Feature matrix

        Returns:
            Probability matrix (n_samples, n_classes)
        """
        if self.model is None:
            raise ValueError("Model not loaded")

        return self.model.predict_proba(X)

    def predict_with_confidence(
        self, X: np.ndarray
    ) -> list[tuple[OverallRisk, float]]:
        """
        Predict risk levels with confidence scores.

        Args:
            X: Feature matrix

        Returns:
            List of (prediction, confidence) tuples
        """
        predictions = self.predict(X)
        probabilities = self.predict_proba(X)

        results = []
        for pred, probs in zip(predictions, probabilities):
            # Confidence is the probability of the predicted class
            pred_idx = self.LABEL_TO_INT[pred]
            confidence = float(probs[pred_idx])
            results.append((pred, confidence))

        return results

    def get_feature_importances(self) -> dict[str, float]:
        """Get feature importance scores."""
        if self.model is None:
            raise ValueError("Model not loaded")

        importances = self.model.feature_importances_
        return dict(zip(FeatureExtractor.FEATURE_NAMES, importances))

    @staticmethod
    def risk_to_int(risk: OverallRisk) -> int:
        """Convert OverallRisk to integer label."""
        return RiskModel.LABEL_TO_INT.get(risk, 1)  # Default to YELLOW

    @staticmethod
    def int_to_risk(label: int) -> OverallRisk:
        """Convert integer label to OverallRisk."""
        return RiskModel.RISK_LABELS.get(label, OverallRisk.YELLOW)
