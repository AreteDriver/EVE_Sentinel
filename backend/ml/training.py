"""Training pipeline for the risk prediction model."""

import json
from datetime import UTC, datetime

import numpy as np
from sklearn.model_selection import (  # type: ignore[import-untyped]
    cross_val_score,
    train_test_split,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import ReportRecord
from backend.models.applicant import Applicant
from backend.models.report import OverallRisk

from .feature_extractor import FeatureExtractor
from .model import RiskModel


class TrainingMetrics:
    """Metrics from model training."""

    def __init__(
        self,
        accuracy: float,
        cv_scores: list[float],
        class_distribution: dict[str, int],
        feature_importances: dict[str, float],
        training_samples: int,
    ) -> None:
        self.accuracy = accuracy
        self.cv_scores = cv_scores
        self.cv_mean = float(np.mean(cv_scores))
        self.cv_std = float(np.std(cv_scores))
        self.class_distribution = class_distribution
        self.feature_importances = feature_importances
        self.training_samples = training_samples
        self.trained_at = datetime.now(UTC)

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "accuracy": self.accuracy,
            "cv_mean": self.cv_mean,
            "cv_std": self.cv_std,
            "class_distribution": self.class_distribution,
            "top_features": dict(
                sorted(
                    self.feature_importances.items(),
                    key=lambda x: x[1],
                    reverse=True,
                )[:10]
            ),
            "training_samples": self.training_samples,
            "trained_at": self.trained_at.isoformat(),
        }


async def fetch_training_data(
    session: AsyncSession,
    min_samples: int = 50,
) -> tuple[list[Applicant], list[OverallRisk]]:
    """
    Fetch historical reports for training data.

    Args:
        session: Database session
        min_samples: Minimum number of samples required

    Returns:
        Tuple of (applicants, risk_labels)

    Raises:
        ValueError: If not enough training data
    """
    # Query completed reports with applicant data
    query = select(ReportRecord).where(
        ReportRecord.status == "completed",
        ReportRecord.overall_risk.in_(["RED", "YELLOW", "GREEN"]),
        ReportRecord.applicant_data_json.isnot(None),
    )

    result = await session.execute(query)
    records = result.scalars().all()

    if len(records) < min_samples:
        raise ValueError(
            f"Insufficient training data: {len(records)} samples, need at least {min_samples}"
        )

    applicants = []
    labels = []

    for record in records:
        if record.applicant_data_json:
            applicant_dict = json.loads(record.applicant_data_json)
            applicant = Applicant.model_validate(applicant_dict)
            risk = OverallRisk(record.overall_risk)
            applicants.append(applicant)
            labels.append(risk)

    return applicants, labels


def train_model(
    applicants: list[Applicant],
    labels: list[OverallRisk],
    test_size: float = 0.2,
    cv_folds: int = 5,
) -> tuple[RiskModel, TrainingMetrics]:
    """
    Train the risk prediction model.

    Args:
        applicants: List of applicants for training
        labels: Corresponding risk labels
        test_size: Fraction of data to use for testing
        cv_folds: Number of cross-validation folds

    Returns:
        Tuple of (trained model, training metrics)
    """
    extractor = FeatureExtractor()

    # Extract features
    X = extractor.extract_batch(applicants)
    y = np.array([RiskModel.risk_to_int(label) for label in labels])

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=42, stratify=y
    )

    # Train model
    model = RiskModel()
    model.train(X_train, y_train)

    # Evaluate
    accuracy = float(model.model.score(X_test, y_test))  # type: ignore[union-attr]

    # Cross-validation
    cv_scores = cross_val_score(
        model.model,  # type: ignore[arg-type]
        X,
        y,
        cv=min(cv_folds, len(y) // 3),  # Ensure enough samples per fold
        scoring="accuracy",
    )

    # Class distribution
    class_distribution = {
        "GREEN": int(np.sum(y == 0)),
        "YELLOW": int(np.sum(y == 1)),
        "RED": int(np.sum(y == 2)),
    }

    # Feature importances
    feature_importances = model.get_feature_importances()

    metrics = TrainingMetrics(
        accuracy=accuracy,
        cv_scores=list(cv_scores),
        class_distribution=class_distribution,
        feature_importances=feature_importances,
        training_samples=len(y),
    )

    return model, metrics


async def train_from_database(
    session: AsyncSession,
    min_samples: int = 50,
    save: bool = True,
) -> tuple[RiskModel, TrainingMetrics]:
    """
    Train model using historical reports from database.

    Args:
        session: Database session
        min_samples: Minimum samples required
        save: Whether to save the trained model

    Returns:
        Tuple of (trained model, training metrics)
    """
    applicants, labels = await fetch_training_data(session, min_samples)

    model, metrics = train_model(applicants, labels)

    if save:
        model.save(metadata=metrics.to_dict())

    return model, metrics
