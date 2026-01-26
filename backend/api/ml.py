"""ML model management API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session_dependency
from backend.ml import RiskModel
from backend.ml.training import train_from_database
from backend.rate_limit import LIMITS, limiter

router = APIRouter(prefix="/api/v1/ml", tags=["ml"])


class ModelStatus(BaseModel):
    """ML model status response."""

    available: bool
    model_path: str | None = None
    feature_count: int
    feature_names: list[str]


class TrainingResult(BaseModel):
    """ML model training result."""

    success: bool
    message: str
    accuracy: float | None = None
    cv_mean: float | None = None
    cv_std: float | None = None
    training_samples: int | None = None
    class_distribution: dict[str, int] | None = None
    top_features: dict[str, float] | None = None


class TrainingRequest(BaseModel):
    """ML model training request."""

    min_samples: int = 50


@router.get("/status", response_model=ModelStatus)
@limiter.limit(LIMITS["admin"])
async def get_model_status(request: Request) -> ModelStatus:
    """
    Get the current ML model status.

    Returns whether a trained model is available and model metadata.
    """
    from backend.ml.feature_extractor import FeatureExtractor

    model = RiskModel()
    available = model.is_available()

    return ModelStatus(
        available=available,
        model_path=str(model.model_path) if available else None,
        feature_count=FeatureExtractor.feature_count(),
        feature_names=FeatureExtractor.FEATURE_NAMES,
    )


@router.post("/train", response_model=TrainingResult)
@limiter.limit(LIMITS["ml_train"])
async def train_model(
    request: Request,
    training_request: TrainingRequest = TrainingRequest(),
    session: AsyncSession = Depends(get_session_dependency),
) -> TrainingResult:
    """
    Train or retrain the ML risk prediction model.

    Uses historical reports from the database as training data.
    Requires at least `min_samples` completed reports.
    """
    try:
        model, metrics = await train_from_database(
            session,
            min_samples=training_request.min_samples,
            save=True,
        )

        # Get top 5 features
        sorted_features = sorted(
            metrics.feature_importances.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:5]

        return TrainingResult(
            success=True,
            message=f"Model trained successfully on {metrics.training_samples} samples",
            accuracy=metrics.accuracy,
            cv_mean=metrics.cv_mean,
            cv_std=metrics.cv_std,
            training_samples=metrics.training_samples,
            class_distribution=metrics.class_distribution,
            top_features=dict(sorted_features),
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Training failed: {str(e)}")


@router.delete("/model", status_code=204)
@limiter.limit(LIMITS["admin"])
async def delete_model(request: Request) -> None:
    """
    Delete the trained ML model.

    After deletion, the MLScorer analyzer will be disabled until
    a new model is trained.
    """
    model = RiskModel()

    if not model.model_path.exists():
        raise HTTPException(status_code=404, detail="No model found to delete")

    model.model_path.unlink()


@router.get("/feature-importances")
@limiter.limit(LIMITS["admin"])
async def get_feature_importances(request: Request) -> dict[str, float]:
    """
    Get feature importance scores from the trained model.

    Returns a dictionary mapping feature names to their importance scores.
    """
    model = RiskModel()

    if not model.load():
        raise HTTPException(status_code=404, detail="No trained model available")

    return model.get_feature_importances()
