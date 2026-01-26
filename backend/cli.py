"""CLI commands for EVE Sentinel."""

import argparse
import asyncio
import sys


async def train_model_command(min_samples: int) -> int:
    """Train the ML risk prediction model."""
    from backend.database import get_session, init_db
    from backend.ml.training import train_from_database

    print(f"Training ML risk model (min samples: {min_samples})...")
    print()

    await init_db()

    try:
        async with get_session() as session:
            model, metrics = await train_from_database(
                session, min_samples=min_samples, save=True
            )
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    print("Training complete!")
    print()
    print(f"  Samples used:     {metrics.training_samples}")
    print(f"  Test accuracy:    {metrics.accuracy:.1%}")
    print(f"  CV score (mean):  {metrics.cv_mean:.1%} (+/- {metrics.cv_std:.1%})")
    print()
    print("Class distribution:")
    for risk, count in metrics.class_distribution.items():
        print(f"  {risk}: {count}")
    print()
    print("Top 5 important features:")
    sorted_features = sorted(
        metrics.feature_importances.items(),
        key=lambda x: x[1],
        reverse=True,
    )[:5]
    for feature, importance in sorted_features:
        print(f"  {feature}: {importance:.3f}")
    print()
    print(f"Model saved to: {model.model_path}")

    return 0


async def check_model_command() -> int:
    """Check if a trained ML model exists."""
    from backend.ml import RiskModel

    model = RiskModel()

    if not model.is_available():
        print("No trained model found.")
        print()
        print("Train a model with:")
        print("  python -m backend.cli train-model")
        return 1

    if model.load():
        print("Trained model found and loaded successfully.")
        print()
        print("Top features:")
        importances = model.get_feature_importances()
        sorted_features = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:5]
        for feature, importance in sorted_features:
            print(f"  {feature}: {importance:.3f}")
        return 0
    else:
        print("Model file exists but failed to load.")
        return 1


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="eve-sentinel",
        description="EVE Sentinel CLI tools",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # train-model command
    train_parser = subparsers.add_parser(
        "train-model",
        help="Train the ML risk prediction model",
    )
    train_parser.add_argument(
        "--min-samples",
        type=int,
        default=50,
        help="Minimum number of historical reports required (default: 50)",
    )

    # check-model command
    subparsers.add_parser(
        "check-model",
        help="Check if a trained ML model exists",
    )

    args = parser.parse_args()

    if args.command == "train-model":
        return asyncio.run(train_model_command(args.min_samples))
    elif args.command == "check-model":
        return asyncio.run(check_model_command())
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
