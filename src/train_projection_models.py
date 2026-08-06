from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import (
    HistGradientBoostingRegressor,
    RandomForestRegressor,
)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATA_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "player_projection_training_data.parquet"
)

MODELS_DIRECTORY = PROJECT_ROOT / "models"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"


FEATURE_COLUMNS = [
    "age",
    "age_squared",
    "games_played",
    "total_minutes",
    "minutes_per_game",
    "points_per_game",
    "assists_per_game",
    "rebounds_per_game",
    "offensive_rebounds_per_game",
    "defensive_rebounds_per_game",
    "steals_per_game",
    "blocks_per_game",
    "turnovers_per_game",
    "threes_made_per_game",
    "threes_attempted_per_game",
    "points_per_36",
    "assists_per_36",
    "rebounds_per_36",
    "offensive_rebounds_per_36",
    "defensive_rebounds_per_36",
    "steals_per_36",
    "blocks_per_36",
    "turnovers_per_36",
    "threes_made_per_36",
    "threes_attempted_per_36",
    "availability_rate",
    "minutes_availability_value",
    "three_point_attempt_rate",
    "free_throw_attempt_rate",
    "assist_turnover_box_ratio",
    "base_fg_pct",
    "base_fg3_pct",
    "base_ft_pct",
    "base_plus_minus",
    "advanced_off_rating",
    "advanced_def_rating",
    "advanced_net_rating",
    "advanced_ast_pct",
    "advanced_ast_to",
    "advanced_ast_ratio",
    "advanced_oreb_pct",
    "advanced_dreb_pct",
    "advanced_reb_pct",
    "advanced_tm_tov_pct",
    "advanced_efg_pct",
    "advanced_ts_pct",
    "advanced_usg_pct",
    "advanced_pace",
    "advanced_pie",
    "advanced_poss",
    "changed_teams",
    "small_sample_flag",
    "rotation_player_flag",
    "high_minutes_flag",
    "sample_reliability",
]


TARGET_CONFIG: dict[str, dict[str, Any]] = {
    "next_minutes_per_game": {
        "label": "Next-season minutes per game",
        "persistence_column": "minutes_per_game",
        "lower_bound": 0.0,
        "upper_bound": 40.0,
    },
    "next_availability_rate": {
        "label": "Next-season availability rate",
        "persistence_column": "availability_rate",
        "lower_bound": 0.0,
        "upper_bound": 1.0,
    },
    "next_advanced_pie": {
        "label": "Next-season Player Impact Estimate",
        "persistence_column": "advanced_pie",
        "lower_bound": -0.05,
        "upper_bound": 0.30,
    },
}


BLEND_WEIGHTS = [round(value, 1) for value in np.arange(0.1, 1.01, 0.1)]


def create_candidate_models() -> dict[str, Pipeline]:
    """Create fresh candidate projection models."""

    ridge = Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(strategy="median"),
            ),
            (
                "scaler",
                StandardScaler(),
            ),
            (
                "model",
                Ridge(alpha=20.0),
            ),
        ]
    )

    random_forest = Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(strategy="median"),
            ),
            (
                "model",
                RandomForestRegressor(
                    n_estimators=500,
                    max_depth=8,
                    min_samples_leaf=8,
                    max_features=0.75,
                    random_state=42,
                    n_jobs=-1,
                ),
            ),
        ]
    )

    histogram_gradient_boosting = Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(strategy="median"),
            ),
            (
                "model",
                HistGradientBoostingRegressor(
                    learning_rate=0.04,
                    max_iter=300,
                    max_leaf_nodes=15,
                    min_samples_leaf=20,
                    l2_regularization=2.0,
                    random_state=42,
                ),
            ),
        ]
    )

    return {
        "ridge": ridge,
        "random_forest": random_forest,
        "hist_gradient_boosting": histogram_gradient_boosting,
    }


def fit_model(
    model: Pipeline,
    features: pd.DataFrame,
    target: pd.Series,
    sample_weight: pd.Series,
) -> Pipeline:
    """Fit a pipeline and pass sample weights to its final estimator."""

    model.fit(
        features,
        target,
        model__sample_weight=sample_weight,
    )

    return model


def clip_predictions(
    predictions: pd.Series | np.ndarray,
    lower_bound: float,
    upper_bound: float,
) -> np.ndarray:
    """Restrict predictions to plausible basketball ranges."""

    return np.clip(
        np.asarray(predictions, dtype=float),
        lower_bound,
        upper_bound,
    )


def calculate_metrics(
    actual: pd.Series | np.ndarray,
    predicted: pd.Series | np.ndarray,
    sample_weight: pd.Series | np.ndarray,
) -> dict[str, float]:
    """Calculate ordinary and reliability-weighted model metrics."""

    actual_array = np.asarray(actual, dtype=float)
    predicted_array = np.asarray(predicted, dtype=float)
    weight_array = np.asarray(sample_weight, dtype=float)

    valid = (
        np.isfinite(actual_array)
        & np.isfinite(predicted_array)
        & np.isfinite(weight_array)
        & (weight_array > 0)
    )

    if not valid.any():
        raise ValueError("No valid rows were available for metric calculation.")

    actual_array = actual_array[valid]
    predicted_array = predicted_array[valid]
    weight_array = weight_array[valid]

    absolute_errors = np.abs(actual_array - predicted_array)
    squared_errors = (actual_array - predicted_array) ** 2

    weighted_mae = float(
        np.average(
            absolute_errors,
            weights=weight_array,
        )
    )

    weighted_rmse = float(
        np.sqrt(
            np.average(
                squared_errors,
                weights=weight_array,
            )
        )
    )

    correlation_result = spearmanr(
        actual_array,
        predicted_array,
        nan_policy="omit",
    )

    spearman_value = getattr(
        correlation_result,
        "statistic",
        getattr(correlation_result, "correlation", np.nan),
    )

    spearman_correlation = float(spearman_value)

    if not np.isfinite(spearman_correlation):
        spearman_correlation = 0.0

    return {
        "mae": float(
            mean_absolute_error(
                actual_array,
                predicted_array,
            )
        ),
        "rmse": float(
            np.sqrt(
                mean_squared_error(
                    actual_array,
                    predicted_array,
                )
            )
        ),
        "weighted_mae": weighted_mae,
        "weighted_rmse": weighted_rmse,
        "r_squared": float(
            r2_score(
                actual_array,
                predicted_array,
                sample_weight=weight_array,
            )
        ),
        "spearman_correlation": spearman_correlation,
    }


def metric_record(
    target_name: str,
    split_name: str,
    model_name: str,
    blend_weight: float,
    metrics: dict[str, float],
) -> dict[str, Any]:
    """Create one model-evaluation record."""

    return {
        "target": target_name,
        "split": split_name,
        "model": model_name,
        "model_blend_weight": float(blend_weight),
        **metrics,
    }


def prepare_numeric_features(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    """Coerce every model feature to numeric without mutating the source data."""

    numeric_features = frame[FEATURE_COLUMNS].copy()

    for column in FEATURE_COLUMNS:
        numeric_features[column] = pd.to_numeric(
            numeric_features[column],
            errors="coerce",
        )

    return numeric_features


def is_better_choice(
    candidate_metrics: dict[str, float],
    best_choice: dict[str, Any],
) -> bool:
    """Compare validation candidates using weighted MAE, then rank correlation."""

    candidate_mae = candidate_metrics["weighted_mae"]
    best_mae = float(best_choice["weighted_mae"])

    if candidate_mae < best_mae - 1e-12:
        return True

    if abs(candidate_mae - best_mae) <= 1e-12:
        return (
            candidate_metrics["spearman_correlation"]
            > float(best_choice["spearman_correlation"])
        )

    return False


def main() -> None:
    """Train, select, test, and save player projection models."""

    if not DATA_PATH.exists():
        raise FileNotFoundError(
            "Projection training data was not found at:\n"
            f"{DATA_PATH}"
        )

    MODELS_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    projection_data = pd.read_parquet(DATA_PATH)

    required_columns = list(
        dict.fromkeys(
            FEATURE_COLUMNS
            + list(TARGET_CONFIG)
            + [
                "season_start",
                "player_id",
                "player_name",
                "season",
                "next_season",
                "team_abbreviation",
                "next_team_abbreviation",
                "training_sample_weight",
            ]
            + [
                config["persistence_column"]
                for config in TARGET_CONFIG.values()
            ]
        )
    )

    missing_columns = [
        column
        for column in required_columns
        if column not in projection_data.columns
    ]

    if missing_columns:
        raise ValueError(
            "Required model columns are missing:\n"
            + "\n".join(missing_columns)
        )

    projection_data["season_start"] = pd.to_numeric(
        projection_data["season_start"],
        errors="coerce",
    )

    projection_data["training_sample_weight"] = (
        pd.to_numeric(
            projection_data["training_sample_weight"],
            errors="coerce",
        )
        .fillna(0.25)
        .clip(lower=0.01)
    )

    train_data = projection_data.loc[
        projection_data["season_start"] == 2022
    ].copy()

    validation_data = projection_data.loc[
        projection_data["season_start"] == 2023
    ].copy()

    test_data = projection_data.loc[
        projection_data["season_start"] == 2024
    ].copy()

    if train_data.empty or validation_data.empty or test_data.empty:
        raise ValueError(
            "The expected chronological train, validation, and test splits "
            "were not found."
        )

    print("CHRONOLOGICAL MODEL SPLITS")
    print(
        f"Training rows: {len(train_data):,} "
        "(2022-23 to 2023-24)"
    )
    print(
        f"Validation rows: {len(validation_data):,} "
        "(2023-24 to 2024-25)"
    )
    print(
        f"Test rows: {len(test_data):,} "
        "(2024-25 to 2025-26)"
    )
    print()

    x_train = prepare_numeric_features(train_data)
    x_validation = prepare_numeric_features(validation_data)
    x_test = prepare_numeric_features(test_data)

    train_validation_data = pd.concat(
        [train_data, validation_data],
        ignore_index=True,
    )
    x_train_validation = prepare_numeric_features(train_validation_data)

    validation_records: list[dict[str, Any]] = []
    test_records: list[dict[str, Any]] = []
    model_metadata: dict[str, Any] = {}

    test_predictions = test_data[
        [
            "player_id",
            "player_name",
            "season",
            "next_season",
            "team_abbreviation",
            "next_team_abbreviation",
        ]
    ].reset_index(drop=True)

    for target_name, target_config in TARGET_CONFIG.items():
        target_label = str(target_config["label"])
        persistence_column = str(target_config["persistence_column"])
        lower_bound = float(target_config["lower_bound"])
        upper_bound = float(target_config["upper_bound"])

        print("=" * 72)
        print(target_label.upper())
        print("=" * 72)

        y_train = pd.to_numeric(
            train_data[target_name],
            errors="coerce",
        )
        weight_train = train_data["training_sample_weight"]

        y_validation = pd.to_numeric(
            validation_data[target_name],
            errors="coerce",
        )
        weight_validation = validation_data["training_sample_weight"]

        validation_persistence = clip_predictions(
            pd.to_numeric(
                validation_data[persistence_column],
                errors="coerce",
            ),
            lower_bound,
            upper_bound,
        )

        persistence_metrics = calculate_metrics(
            y_validation,
            validation_persistence,
            weight_validation,
        )

        validation_records.append(
            metric_record(
                target_name=target_name,
                split_name="validation",
                model_name="persistence",
                blend_weight=0.0,
                metrics=persistence_metrics,
            )
        )

        best_choice: dict[str, Any] = {
            "model_name": "persistence",
            "blend_weight": 0.0,
            "weighted_mae": persistence_metrics["weighted_mae"],
            "spearman_correlation": persistence_metrics[
                "spearman_correlation"
            ],
        }

        for model_name, model in create_candidate_models().items():
            fitted_model = fit_model(
                model=model,
                features=x_train,
                target=y_train,
                sample_weight=weight_train,
            )

            model_predictions = clip_predictions(
                fitted_model.predict(x_validation),
                lower_bound,
                upper_bound,
            )

            for blend_weight in BLEND_WEIGHTS:
                blended_predictions = (
                    blend_weight * model_predictions
                    + (1.0 - blend_weight) * validation_persistence
                )

                blended_predictions = clip_predictions(
                    blended_predictions,
                    lower_bound,
                    upper_bound,
                )

                metrics = calculate_metrics(
                    y_validation,
                    blended_predictions,
                    weight_validation,
                )

                validation_records.append(
                    metric_record(
                        target_name=target_name,
                        split_name="validation",
                        model_name=model_name,
                        blend_weight=blend_weight,
                        metrics=metrics,
                    )
                )

                if is_better_choice(metrics, best_choice):
                    best_choice = {
                        "model_name": model_name,
                        "blend_weight": blend_weight,
                        "weighted_mae": metrics["weighted_mae"],
                        "spearman_correlation": metrics[
                            "spearman_correlation"
                        ],
                    }

        print(
            "Best validation approach: "
            f"{best_choice['model_name']}"
        )
        print(
            "Model blend weight: "
            f"{float(best_choice['blend_weight']):.1f}"
        )
        print(
            "Validation weighted MAE: "
            f"{float(best_choice['weighted_mae']):.5f}"
        )

        y_train_validation = pd.to_numeric(
            train_validation_data[target_name],
            errors="coerce",
        )
        weight_train_validation = train_validation_data[
            "training_sample_weight"
        ]

        y_test = pd.to_numeric(
            test_data[target_name],
            errors="coerce",
        )
        weight_test = test_data["training_sample_weight"]

        test_persistence = clip_predictions(
            pd.to_numeric(
                test_data[persistence_column],
                errors="coerce",
            ),
            lower_bound,
            upper_bound,
        )

        test_persistence_metrics = calculate_metrics(
            y_test,
            test_persistence,
            weight_test,
        )

        test_records.append(
            metric_record(
                target_name=target_name,
                split_name="test",
                model_name="persistence",
                blend_weight=0.0,
                metrics=test_persistence_metrics,
            )
        )

        selected_model_name = str(best_choice["model_name"])
        selected_blend_weight = float(best_choice["blend_weight"])
        final_pipeline: Pipeline | None = None

        if selected_model_name == "persistence":
            final_predictions = test_persistence.copy()
        else:
            final_pipeline = create_candidate_models()[selected_model_name]

            final_pipeline = fit_model(
                model=final_pipeline,
                features=x_train_validation,
                target=y_train_validation,
                sample_weight=weight_train_validation,
            )

            test_model_predictions = clip_predictions(
                final_pipeline.predict(x_test),
                lower_bound,
                upper_bound,
            )

            final_predictions = (
                selected_blend_weight * test_model_predictions
                + (1.0 - selected_blend_weight) * test_persistence
            )

            final_predictions = clip_predictions(
                final_predictions,
                lower_bound,
                upper_bound,
            )

        final_test_metrics = calculate_metrics(
            y_test,
            final_predictions,
            weight_test,
        )

        if selected_model_name != "persistence":
            test_records.append(
                metric_record(
                    target_name=target_name,
                    split_name="test",
                    model_name=selected_model_name,
                    blend_weight=selected_blend_weight,
                    metrics=final_test_metrics,
                )
            )

        model_path = (
            MODELS_DIRECTORY
            / f"{target_name}_projection.joblib"
        )

        model_bundle = {
            "target": target_name,
            "target_label": target_label,
            "pipeline": final_pipeline,
            "model_name": selected_model_name,
            "blend_weight": selected_blend_weight,
            "persistence_column": persistence_column,
            "feature_columns": FEATURE_COLUMNS,
            "lower_bound": lower_bound,
            "upper_bound": upper_bound,
            "training_seasons": ["2022-23", "2023-24"],
            "test_season": "2024-25",
        }

        joblib.dump(model_bundle, model_path)

        test_predictions[f"actual_{target_name}"] = y_test.to_numpy()
        test_predictions[f"persistence_{target_name}"] = test_persistence
        test_predictions[f"projected_{target_name}"] = final_predictions

        model_metadata[target_name] = {
            "label": target_label,
            "selected_model": selected_model_name,
            "blend_weight": selected_blend_weight,
            "validation_weighted_mae": float(best_choice["weighted_mae"]),
            "test_weighted_mae": final_test_metrics["weighted_mae"],
            "persistence_test_weighted_mae": test_persistence_metrics[
                "weighted_mae"
            ],
            "test_spearman_correlation": final_test_metrics[
                "spearman_correlation"
            ],
            "model_file": str(model_path),
        }

        improvement = (
            test_persistence_metrics["weighted_mae"]
            - final_test_metrics["weighted_mae"]
        )

        print(
            "Test persistence weighted MAE: "
            f"{test_persistence_metrics['weighted_mae']:.5f}"
        )
        print(
            "Test selected weighted MAE: "
            f"{final_test_metrics['weighted_mae']:.5f}"
        )
        print(f"Test MAE improvement: {improvement:.5f}")
        print(
            "Test Spearman correlation: "
            f"{final_test_metrics['spearman_correlation']:.4f}"
        )
        print(f"Saved model: {model_path}")
        print()

    validation_metrics = pd.DataFrame(validation_records).sort_values(
        ["target", "weighted_mae", "model", "model_blend_weight"]
    )

    test_metrics = pd.DataFrame(test_records).sort_values(
        ["target", "weighted_mae", "model"]
    )

    validation_metrics_path = (
        OUTPUT_DIRECTORY / "projection_validation_metrics.csv"
    )
    test_metrics_path = OUTPUT_DIRECTORY / "projection_test_metrics.csv"
    test_predictions_path = (
        OUTPUT_DIRECTORY / "projection_test_predictions.csv"
    )
    metadata_path = MODELS_DIRECTORY / "projection_model_metadata.json"

    validation_metrics.to_csv(validation_metrics_path, index=False)
    test_metrics.to_csv(test_metrics_path, index=False)
    test_predictions.to_csv(test_predictions_path, index=False)

    with metadata_path.open("w", encoding="utf-8") as metadata_file:
        json.dump(
            model_metadata,
            metadata_file,
            indent=2,
        )

    print("=" * 72)
    print("PROJECTION MODELING COMPLETED")
    print("=" * 72)
    print()
    print("VALIDATION METRICS")
    print(validation_metrics_path)
    print()
    print("TEST METRICS")
    print(test_metrics_path)
    print()
    print("TEST PREDICTIONS")
    print(test_predictions_path)
    print()
    print("MODEL METADATA")
    print(metadata_path)
    print()
    print("TEST SUMMARY")
    print(
        test_metrics[
            [
                "target",
                "model",
                "model_blend_weight",
                "weighted_mae",
                "r_squared",
                "spearman_correlation",
            ]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()