from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.base import BaseEstimator
from sklearn.ensemble import (
    ExtraTreesRegressor,
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (
    brier_score_loss,
    log_loss,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


PROJECT_ROOT = Path(__file__).resolve().parents[1]

TRAINING_DATA_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "player_projection_training_data_multiyear.parquet"
)

MODELS_DIRECTORY = PROJECT_ROOT / "models"
OUTPUTS_DIRECTORY = PROJECT_ROOT / "outputs"

ROLLING_RESULTS_PATH = (
    OUTPUTS_DIRECTORY
    / "multiyear_projection_rolling_results.csv"
)

TEST_METRICS_PATH = (
    OUTPUTS_DIRECTORY
    / "multiyear_projection_test_metrics.csv"
)

TEST_PREDICTIONS_PATH = (
    OUTPUTS_DIRECTORY
    / "multiyear_projection_test_predictions.csv"
)

ROTATION_METRICS_PATH = (
    OUTPUTS_DIRECTORY
    / "multiyear_rotation_test_metrics.csv"
)

ROTATION_PREDICTIONS_PATH = (
    OUTPUTS_DIRECTORY
    / "multiyear_rotation_test_predictions.csv"
)

METADATA_PATH = (
    MODELS_DIRECTORY
    / "multiyear_projection_model_metadata.json"
)

RANDOM_STATE = 42

FINAL_TEST_CURRENT_SEASON = "2024-25"

ROLLING_VALIDATION_CURRENT_SEASONS = [
    "2018-19",
    "2019-20",
    "2020-21",
    "2021-22",
    "2022-23",
    "2023-24",
]

MODEL_BLEND_WEIGHTS = [
    0.25,
    0.50,
    0.75,
    1.00,
]

TARGET_CONFIG = {
    "next_minutes_per_game": {
        "label": "NEXT-SEASON MINUTES PER GAME",
        "persistence_column": "minutes_per_game",
        "history_column": "weighted3_minutes_per_game",
        "clip_lower": 0.0,
        "clip_upper": 40.0,
        "model_filename": (
            "multiyear_next_minutes_per_game_projection.joblib"
        ),
    },
    "next_availability_rate": {
        "label": "NEXT-SEASON AVAILABILITY RATE",
        "persistence_column": "availability_rate",
        "history_column": "weighted3_availability_rate",
        "clip_lower": 0.0,
        "clip_upper": 1.0,
        "model_filename": (
            "multiyear_next_availability_rate_projection.joblib"
        ),
    },
    "next_advanced_pie": {
        "label": "NEXT-SEASON PLAYER IMPACT ESTIMATE",
        "persistence_column": "advanced_pie",
        "history_column": "weighted3_advanced_pie",
        "clip_lower": -0.05,
        "clip_upper": 0.30,
        "model_filename": (
            "multiyear_next_advanced_pie_projection.joblib"
        ),
    },
}

IDENTIFIER_COLUMNS = {
    "player_id",
    "player_name",
    "team_id",
    "team_abbreviation",
    "season",
    "next_season",
    "next_team_abbreviation",
    "data_source",
}

EXCLUDED_NUMERIC_COLUMNS = {
    "advanced_gp",
    "advanced_min",
}


@dataclass
class SelectedApproach:
    """Description of the best rolling-validation projection approach."""

    target: str
    model_name: str
    baseline_name: str
    model_weight: float
    weighted_mae: float


class TwoStageMinutesModel(BaseEstimator):
    """
    Predict next-season minutes using:
    1. rotation probability,
    2. minutes conditional on a rotation role,
    3. minutes conditional on a non-rotation role.
    """

    def __init__(self, random_state: int = RANDOM_STATE):
        self.random_state = random_state
        self.classifier: Pipeline | None = None
        self.rotation_regressor: Pipeline | None = None
        self.nonrotation_regressor: Pipeline | None = None
        self.rotation_fallback = 20.0
        self.nonrotation_fallback = 5.0

    def _make_classifier(self) -> Pipeline:
        return Pipeline(
            steps=[
                (
                    "imputer",
                    SimpleImputer(
                        strategy="median",
                        add_indicator=True,
                    ),
                ),
                (
                    "model",
                    HistGradientBoostingClassifier(
                        learning_rate=0.04,
                        max_iter=300,
                        max_leaf_nodes=15,
                        min_samples_leaf=25,
                        l2_regularization=3.0,
                        random_state=self.random_state,
                    ),
                ),
            ]
        )

    def _make_regressor(self) -> Pipeline:
        return Pipeline(
            steps=[
                (
                    "imputer",
                    SimpleImputer(
                        strategy="median",
                        add_indicator=True,
                    ),
                ),
                (
                    "model",
                    HistGradientBoostingRegressor(
                        loss="absolute_error",
                        learning_rate=0.04,
                        max_iter=300,
                        max_leaf_nodes=15,
                        min_samples_leaf=20,
                        l2_regularization=3.0,
                        random_state=self.random_state,
                    ),
                ),
            ]
        )

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        rotation_target: pd.Series,
        sample_weight: pd.Series,
    ) -> "TwoStageMinutesModel":
        y_numeric = pd.to_numeric(
            y,
            errors="coerce",
        ).astype(float)

        rotation_numeric = (
            pd.to_numeric(
                rotation_target,
                errors="coerce",
            )
            .fillna(0)
            .astype(int)
        )

        weights = (
            pd.to_numeric(
                sample_weight,
                errors="coerce",
            )
            .fillna(1.0)
            .astype(float)
        )

        self.classifier = self._make_classifier()
        self.classifier.fit(
            X,
            rotation_numeric,
            model__sample_weight=weights,
        )

        rotation_mask = rotation_numeric.eq(1)
        nonrotation_mask = rotation_numeric.eq(0)

        if rotation_mask.sum() >= 30:
            self.rotation_regressor = self._make_regressor()
            self.rotation_regressor.fit(
                X.loc[rotation_mask],
                y_numeric.loc[rotation_mask],
                model__sample_weight=weights.loc[
                    rotation_mask
                ],
            )

            self.rotation_fallback = float(
                np.average(
                    y_numeric.loc[rotation_mask],
                    weights=weights.loc[rotation_mask],
                )
            )

        if nonrotation_mask.sum() >= 30:
            self.nonrotation_regressor = self._make_regressor()
            self.nonrotation_regressor.fit(
                X.loc[nonrotation_mask],
                y_numeric.loc[nonrotation_mask],
                model__sample_weight=weights.loc[
                    nonrotation_mask
                ],
            )

            self.nonrotation_fallback = float(
                np.average(
                    y_numeric.loc[nonrotation_mask],
                    weights=weights.loc[
                        nonrotation_mask
                    ],
                )
            )

        return self

    def predict_rotation_probability(
        self,
        X: pd.DataFrame,
    ) -> np.ndarray:
        if self.classifier is None:
            raise RuntimeError(
                "TwoStageMinutesModel has not been fitted."
            )

        probabilities = self.classifier.predict_proba(X)[:, 1]

        return np.clip(
            probabilities,
            0.01,
            0.99,
        )

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        rotation_probability = (
            self.predict_rotation_probability(X)
        )

        if self.rotation_regressor is None:
            rotation_minutes = np.full(
                len(X),
                self.rotation_fallback,
                dtype=float,
            )
        else:
            rotation_minutes = (
                self.rotation_regressor.predict(X)
            )

        if self.nonrotation_regressor is None:
            nonrotation_minutes = np.full(
                len(X),
                self.nonrotation_fallback,
                dtype=float,
            )
        else:
            nonrotation_minutes = (
                self.nonrotation_regressor.predict(X)
            )

        predictions = (
            rotation_probability * rotation_minutes
            + (1.0 - rotation_probability)
            * nonrotation_minutes
        )

        return np.clip(
            predictions,
            0.0,
            40.0,
        )


def make_ridge_pipeline() -> Pipeline:
    return Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(
                    strategy="median",
                    add_indicator=True,
                ),
            ),
            (
                "scaler",
                StandardScaler(),
            ),
            (
                "model",
                Ridge(
                    alpha=30.0,
                ),
            ),
        ]
    )


def make_random_forest_pipeline() -> Pipeline:
    return Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(
                    strategy="median",
                    add_indicator=True,
                ),
            ),
            (
                "model",
                RandomForestRegressor(
                    n_estimators=300,
                    max_depth=10,
                    min_samples_leaf=7,
                    max_features=0.60,
                    n_jobs=-1,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def make_extra_trees_pipeline() -> Pipeline:
    return Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(
                    strategy="median",
                    add_indicator=True,
                ),
            ),
            (
                "model",
                ExtraTreesRegressor(
                    n_estimators=350,
                    max_depth=12,
                    min_samples_leaf=5,
                    max_features=0.70,
                    n_jobs=-1,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def make_hist_gradient_boosting_pipeline() -> Pipeline:
    return Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(
                    strategy="median",
                    add_indicator=True,
                ),
            ),
            (
                "model",
                HistGradientBoostingRegressor(
                    loss="absolute_error",
                    learning_rate=0.035,
                    max_iter=350,
                    max_leaf_nodes=15,
                    min_samples_leaf=25,
                    l2_regularization=3.0,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def make_regression_candidates(
    target_name: str,
) -> dict[str, Callable[[], object]]:
    candidates: dict[str, Callable[[], object]] = {
        "ridge": make_ridge_pipeline,
        "random_forest": make_random_forest_pipeline,
        "extra_trees": make_extra_trees_pipeline,
        "hist_gradient_boosting": (
            make_hist_gradient_boosting_pipeline
        ),
    }

    if target_name == "next_minutes_per_game":
        candidates["two_stage_hgb"] = (
            lambda: TwoStageMinutesModel(
                random_state=RANDOM_STATE
            )
        )

    return candidates


def make_logistic_classifier() -> Pipeline:
    return Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(
                    strategy="median",
                    add_indicator=True,
                ),
            ),
            (
                "scaler",
                StandardScaler(),
            ),
            (
                "model",
                LogisticRegression(
                    C=0.50,
                    max_iter=2_000,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def make_random_forest_classifier() -> Pipeline:
    return Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(
                    strategy="median",
                    add_indicator=True,
                ),
            ),
            (
                "model",
                RandomForestClassifier(
                    n_estimators=300,
                    max_depth=10,
                    min_samples_leaf=7,
                    max_features=0.60,
                    n_jobs=-1,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def make_hist_gradient_boosting_classifier() -> Pipeline:
    return Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(
                    strategy="median",
                    add_indicator=True,
                ),
            ),
            (
                "model",
                HistGradientBoostingClassifier(
                    learning_rate=0.04,
                    max_iter=300,
                    max_leaf_nodes=15,
                    min_samples_leaf=25,
                    l2_regularization=3.0,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def make_classification_candidates(
) -> dict[str, Callable[[], Pipeline]]:
    return {
        "logistic_regression": make_logistic_classifier,
        "random_forest": make_random_forest_classifier,
        "hist_gradient_boosting": (
            make_hist_gradient_boosting_classifier
        ),
    }


def fit_pipeline(
    model: object,
    X: pd.DataFrame,
    y: pd.Series,
    sample_weight: pd.Series,
    rotation_target: pd.Series | None = None,
) -> object:
    if isinstance(model, TwoStageMinutesModel):
        if rotation_target is None:
            raise ValueError(
                "The two-stage minutes model requires "
                "a rotation target."
            )

        return model.fit(
            X=X,
            y=y,
            rotation_target=rotation_target,
            sample_weight=sample_weight,
        )

    model.fit(
        X,
        y,
        model__sample_weight=sample_weight,
    )

    return model


def weighted_mae(
    actual: np.ndarray,
    predicted: np.ndarray,
    sample_weight: np.ndarray,
) -> float:
    return float(
        mean_absolute_error(
            actual,
            predicted,
            sample_weight=sample_weight,
        )
    )


def safe_spearman(
    actual: np.ndarray,
    predicted: np.ndarray,
) -> float:
    result = spearmanr(
        actual,
        predicted,
        nan_policy="omit",
    )

    statistic = getattr(
        result,
        "statistic",
        result[0],
    )

    return float(statistic)


def regression_metrics(
    actual: np.ndarray,
    predicted: np.ndarray,
    sample_weight: np.ndarray,
) -> dict[str, float]:
    return {
        "weighted_mae": weighted_mae(
            actual,
            predicted,
            sample_weight,
        ),
        "mae": float(
            mean_absolute_error(
                actual,
                predicted,
            )
        ),
        "rmse": float(
            mean_squared_error(
                actual,
                predicted,
            )
            ** 0.5
        ),
        "r_squared": float(
            r2_score(
                actual,
                predicted,
                sample_weight=sample_weight,
            )
        ),
        "spearman_correlation": safe_spearman(
            actual,
            predicted,
        ),
    }


def load_training_data() -> pd.DataFrame:
    if not TRAINING_DATA_PATH.exists():
        raise FileNotFoundError(
            "The multi-year projection training data "
            "was not found at:\n"
            f"{TRAINING_DATA_PATH}"
        )

    frame = pd.read_parquet(
        TRAINING_DATA_PATH
    )

    if frame.empty:
        raise ValueError(
            "The multi-year training dataset is empty."
        )

    required_columns = {
        "player_id",
        "player_name",
        "season",
        "next_season",
        "season_start",
        "training_sample_weight",
        "next_minutes_per_game",
        "next_availability_rate",
        "next_advanced_pie",
        "next_rotation_player_flag",
        "minutes_per_game",
        "availability_rate",
        "advanced_pie",
        "weighted3_minutes_per_game",
        "weighted3_availability_rate",
        "weighted3_advanced_pie",
    }

    missing_columns = sorted(
        required_columns.difference(frame.columns)
    )

    if missing_columns:
        raise ValueError(
            "The training data is missing required columns:\n"
            + "\n".join(missing_columns)
        )

    frame = frame.copy()

    frame["training_sample_weight"] = (
        pd.to_numeric(
            frame["training_sample_weight"],
            errors="coerce",
        )
        .fillna(1.0)
        .clip(lower=0.25, upper=1.0)
    )

    frame["next_rotation_player_flag"] = (
        pd.to_numeric(
            frame["next_rotation_player_flag"],
            errors="coerce",
        )
        .fillna(0)
        .astype(int)
    )

    return frame


def select_numeric_features(
    frame: pd.DataFrame,
) -> list[str]:
    candidate_columns: list[str] = []

    for column in frame.columns:
        if column in IDENTIFIER_COLUMNS:
            continue

        if column in EXCLUDED_NUMERIC_COLUMNS:
            continue

        if column.startswith("next_"):
            continue

        if not pd.api.types.is_numeric_dtype(
            frame[column]
        ):
            continue

        candidate_columns.append(column)

    features: list[str] = []

    development_frame = frame.loc[
        frame["season"].ne(
            FINAL_TEST_CURRENT_SEASON
        )
    ]

    for column in candidate_columns:
        missing_rate = float(
            development_frame[column]
            .isna()
            .mean()
        )

        unique_count = int(
            development_frame[column]
            .nunique(
                dropna=True
            )
        )

        if missing_rate > 0.80:
            continue

        if unique_count <= 1:
            continue

        features.append(column)

    if not features:
        raise ValueError(
            "No usable numeric features were found."
        )

    return sorted(features)


def make_baseline_predictions(
    frame: pd.DataFrame,
    config: dict[str, object],
) -> dict[str, np.ndarray]:
    persistence_column = str(
        config["persistence_column"]
    )

    history_column = str(
        config["history_column"]
    )

    persistence = (
        pd.to_numeric(
            frame[persistence_column],
            errors="coerce",
        )
        .to_numpy(dtype=float)
    )

    history = (
        pd.to_numeric(
            frame[history_column],
            errors="coerce",
        )
        .to_numpy(dtype=float)
    )

    history = np.where(
        np.isfinite(history),
        history,
        persistence,
    )

    lower = float(
        config["clip_lower"]
    )

    upper = float(
        config["clip_upper"]
    )

    return {
        "persistence": np.clip(
            persistence,
            lower,
            upper,
        ),
        "weighted_three_year": np.clip(
            history,
            lower,
            upper,
        ),
    }


def build_rolling_predictions_for_target(
    frame: pd.DataFrame,
    features: list[str],
    target_name: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    config = TARGET_CONFIG[target_name]
    candidate_factories = (
        make_regression_candidates(
            target_name
        )
    )

    prediction_rows: list[pd.DataFrame] = []
    fold_result_rows: list[dict[str, object]] = []

    for validation_season in (
        ROLLING_VALIDATION_CURRENT_SEASONS
    ):
        validation_start = int(
            validation_season[:4]
        )

        train_mask = (
            frame["season_start"]
            < validation_start
        )

        validation_mask = (
            frame["season"]
            .eq(validation_season)
        )

        train = frame.loc[
            train_mask
        ].copy()

        validation = frame.loc[
            validation_mask
        ].copy()

        if train.empty or validation.empty:
            raise ValueError(
                "A rolling fold is empty for "
                f"{validation_season}."
            )

        X_train = train[features]
        X_validation = validation[features]

        y_train = pd.to_numeric(
            train[target_name],
            errors="coerce",
        ).astype(float)

        y_validation = pd.to_numeric(
            validation[target_name],
            errors="coerce",
        ).astype(float)

        train_weights = (
            train["training_sample_weight"]
            .astype(float)
        )

        validation_weights = (
            validation[
                "training_sample_weight"
            ]
            .astype(float)
        )

        fold_predictions = pd.DataFrame(
            {
                "player_id": validation[
                    "player_id"
                ].to_numpy(),
                "player_name": validation[
                    "player_name"
                ].to_numpy(),
                "season": validation[
                    "season"
                ].to_numpy(),
                "next_season": validation[
                    "next_season"
                ].to_numpy(),
                "target": target_name,
                "actual": y_validation.to_numpy(),
                "sample_weight": (
                    validation_weights.to_numpy()
                ),
            }
        )

        baselines = make_baseline_predictions(
            validation,
            config,
        )

        for baseline_name, values in (
            baselines.items()
        ):
            fold_predictions[
                f"baseline__{baseline_name}"
            ] = values

        for model_name, factory in (
            candidate_factories.items()
        ):
            print(
                f"  {validation_season}: "
                f"fitting {target_name} with "
                f"{model_name}..."
            )

            model = factory()

            model = fit_pipeline(
                model=model,
                X=X_train,
                y=y_train,
                sample_weight=train_weights,
                rotation_target=train[
                    "next_rotation_player_flag"
                ],
            )

            predictions = np.asarray(
                model.predict(
                    X_validation
                ),
                dtype=float,
            )

            predictions = np.clip(
                predictions,
                float(config["clip_lower"]),
                float(config["clip_upper"]),
            )

            fold_predictions[
                f"model__{model_name}"
            ] = predictions

            metrics = regression_metrics(
                actual=y_validation.to_numpy(),
                predicted=predictions,
                sample_weight=(
                    validation_weights.to_numpy()
                ),
            )

            fold_result_rows.append(
                {
                    "target": target_name,
                    "validation_season": (
                        validation_season
                    ),
                    "model": model_name,
                    "baseline": "",
                    "model_weight": 1.0,
                    "train_rows": len(train),
                    "validation_rows": len(
                        validation
                    ),
                    **metrics,
                }
            )

        prediction_rows.append(
            fold_predictions
        )

    rolling_predictions = pd.concat(
        prediction_rows,
        ignore_index=True,
    )

    fold_results = pd.DataFrame(
        fold_result_rows
    )

    return (
        rolling_predictions,
        fold_results,
    )


def choose_best_regression_approach(
    rolling_predictions: pd.DataFrame,
    target_name: str,
) -> tuple[
    SelectedApproach,
    pd.DataFrame,
]:
    actual = (
        rolling_predictions["actual"]
        .to_numpy(dtype=float)
    )

    sample_weight = (
        rolling_predictions["sample_weight"]
        .to_numpy(dtype=float)
    )

    baseline_columns = [
        column
        for column in rolling_predictions.columns
        if column.startswith("baseline__")
    ]

    model_columns = [
        column
        for column in rolling_predictions.columns
        if column.startswith("model__")
    ]

    candidates: list[dict[str, object]] = []

    for baseline_column in baseline_columns:
        baseline_name = baseline_column.replace(
            "baseline__",
            "",
        )

        baseline_predictions = (
            rolling_predictions[
                baseline_column
            ]
            .to_numpy(dtype=float)
        )

        metrics = regression_metrics(
            actual=actual,
            predicted=baseline_predictions,
            sample_weight=sample_weight,
        )

        candidates.append(
            {
                "target": target_name,
                "model": "baseline_only",
                "baseline": baseline_name,
                "model_weight": 0.0,
                **metrics,
            }
        )

    for model_column in model_columns:
        model_name = model_column.replace(
            "model__",
            "",
        )

        model_predictions = (
            rolling_predictions[
                model_column
            ]
            .to_numpy(dtype=float)
        )

        for baseline_column in baseline_columns:
            baseline_name = (
                baseline_column.replace(
                    "baseline__",
                    "",
                )
            )

            baseline_predictions = (
                rolling_predictions[
                    baseline_column
                ]
                .to_numpy(dtype=float)
            )

            for model_weight in (
                MODEL_BLEND_WEIGHTS
            ):
                blended_predictions = (
                    model_weight
                    * model_predictions
                    + (1.0 - model_weight)
                    * baseline_predictions
                )

                metrics = regression_metrics(
                    actual=actual,
                    predicted=blended_predictions,
                    sample_weight=sample_weight,
                )

                candidates.append(
                    {
                        "target": target_name,
                        "model": model_name,
                        "baseline": baseline_name,
                        "model_weight": (
                            model_weight
                        ),
                        **metrics,
                    }
                )

    candidate_results = pd.DataFrame(
        candidates
    ).sort_values(
        [
            "weighted_mae",
            "rmse",
        ],
        ascending=True,
    ).reset_index(drop=True)

    best_row = candidate_results.iloc[0]

    selected = SelectedApproach(
        target=target_name,
        model_name=str(
            best_row["model"]
        ),
        baseline_name=str(
            best_row["baseline"]
        ),
        model_weight=float(
            best_row["model_weight"]
        ),
        weighted_mae=float(
            best_row["weighted_mae"]
        ),
    )

    return (
        selected,
        candidate_results,
    )


def train_final_regression_model(
    development: pd.DataFrame,
    test: pd.DataFrame,
    features: list[str],
    selected: SelectedApproach,
) -> tuple[
    object | None,
    np.ndarray,
    np.ndarray,
]:
    target_name = selected.target
    config = TARGET_CONFIG[target_name]

    test_baselines = make_baseline_predictions(
        test,
        config,
    )

    baseline_predictions = (
        test_baselines[
            selected.baseline_name
        ]
    )

    if (
        selected.model_name
        == "baseline_only"
    ):
        return (
            None,
            baseline_predictions,
            baseline_predictions,
        )

    candidate_factories = (
        make_regression_candidates(
            target_name
        )
    )

    model = (
        candidate_factories[
            selected.model_name
        ]()
    )

    model = fit_pipeline(
        model=model,
        X=development[features],
        y=development[target_name],
        sample_weight=development[
            "training_sample_weight"
        ],
        rotation_target=development[
            "next_rotation_player_flag"
        ],
    )

    raw_model_predictions = np.asarray(
        model.predict(
            test[features]
        ),
        dtype=float,
    )

    raw_model_predictions = np.clip(
        raw_model_predictions,
        float(config["clip_lower"]),
        float(config["clip_upper"]),
    )

    selected_predictions = (
        selected.model_weight
        * raw_model_predictions
        + (1.0 - selected.model_weight)
        * baseline_predictions
    )

    selected_predictions = np.clip(
        selected_predictions,
        float(config["clip_lower"]),
        float(config["clip_upper"]),
    )

    return (
        model,
        selected_predictions,
        baseline_predictions,
    )


def evaluate_rotation_models(
    frame: pd.DataFrame,
    features: list[str],
) -> tuple[
    str,
    pd.DataFrame,
    object,
    pd.DataFrame,
    pd.DataFrame,
]:
    candidate_factories = (
        make_classification_candidates()
    )

    rolling_rows: list[pd.DataFrame] = []

    for validation_season in (
        ROLLING_VALIDATION_CURRENT_SEASONS
    ):
        validation_start = int(
            validation_season[:4]
        )

        train = frame.loc[
            frame["season_start"]
            < validation_start
        ].copy()

        validation = frame.loc[
            frame["season"]
            .eq(validation_season)
        ].copy()

        X_train = train[features]
        X_validation = validation[features]

        y_train = train[
            "next_rotation_player_flag"
        ].astype(int)

        y_validation = validation[
            "next_rotation_player_flag"
        ].astype(int)

        weights = validation[
            "training_sample_weight"
        ].to_numpy(dtype=float)

        fold = pd.DataFrame(
            {
                "season": validation[
                    "season"
                ].to_numpy(),
                "actual": y_validation.to_numpy(),
                "sample_weight": weights,
                "persistence": (
                    validation[
                        "rotation_player_flag"
                    ]
                    .astype(float)
                    .clip(0.01, 0.99)
                    .to_numpy()
                ),
            }
        )

        for model_name, factory in (
            candidate_factories.items()
        ):
            print(
                f"  {validation_season}: "
                "fitting next-rotation model "
                f"with {model_name}..."
            )

            model = factory()

            model.fit(
                X_train,
                y_train,
                model__sample_weight=train[
                    "training_sample_weight"
                ],
            )

            probabilities = (
                model.predict_proba(
                    X_validation
                )[:, 1]
            )

            fold[model_name] = np.clip(
                probabilities,
                0.01,
                0.99,
            )

        rolling_rows.append(fold)

    rolling = pd.concat(
        rolling_rows,
        ignore_index=True,
    )

    actual = rolling[
        "actual"
    ].to_numpy(dtype=int)

    weights = rolling[
        "sample_weight"
    ].to_numpy(dtype=float)

    result_rows: list[dict[str, object]] = []

    probability_columns = [
        "persistence",
        *candidate_factories.keys(),
    ]

    for column in probability_columns:
        probabilities = rolling[
            column
        ].to_numpy(dtype=float)

        result_rows.append(
            {
                "model": column,
                "weighted_brier": float(
                    np.average(
                        (
                            probabilities
                            - actual
                        )
                        ** 2,
                        weights=weights,
                    )
                ),
                "brier": float(
                    brier_score_loss(
                        actual,
                        probabilities,
                    )
                ),
                "log_loss": float(
                    log_loss(
                        actual,
                        probabilities,
                        sample_weight=weights,
                        labels=[0, 1],
                    )
                ),
                "roc_auc": float(
                    roc_auc_score(
                        actual,
                        probabilities,
                        sample_weight=weights,
                    )
                ),
            }
        )

    results = pd.DataFrame(
        result_rows
    ).sort_values(
        "weighted_brier",
        ascending=True,
    ).reset_index(drop=True)

    selected_model_name = str(
        results.iloc[0]["model"]
    )

    development = frame.loc[
        frame["season"].ne(
            FINAL_TEST_CURRENT_SEASON
        )
    ].copy()

    test = frame.loc[
        frame["season"].eq(
            FINAL_TEST_CURRENT_SEASON
        )
    ].copy()

    if selected_model_name == "persistence":
        final_model = None
        test_probabilities = (
            test["rotation_player_flag"]
            .astype(float)
            .clip(0.01, 0.99)
            .to_numpy()
        )
    else:
        final_model = (
            candidate_factories[
                selected_model_name
            ]()
        )

        final_model.fit(
            development[features],
            development[
                "next_rotation_player_flag"
            ].astype(int),
            model__sample_weight=development[
                "training_sample_weight"
            ],
        )

        test_probabilities = (
            final_model.predict_proba(
                test[features]
            )[:, 1]
        )

        test_probabilities = np.clip(
            test_probabilities,
            0.01,
            0.99,
        )

    test_actual = test[
        "next_rotation_player_flag"
    ].astype(int).to_numpy()

    test_weights = test[
        "training_sample_weight"
    ].to_numpy(dtype=float)

    test_metrics = pd.DataFrame(
        [
            {
                "selected_model": (
                    selected_model_name
                ),
                "weighted_brier": float(
                    np.average(
                        (
                            test_probabilities
                            - test_actual
                        )
                        ** 2,
                        weights=test_weights,
                    )
                ),
                "brier": float(
                    brier_score_loss(
                        test_actual,
                        test_probabilities,
                    )
                ),
                "log_loss": float(
                    log_loss(
                        test_actual,
                        test_probabilities,
                        sample_weight=test_weights,
                        labels=[0, 1],
                    )
                ),
                "roc_auc": float(
                    roc_auc_score(
                        test_actual,
                        test_probabilities,
                        sample_weight=test_weights,
                    )
                ),
            }
        ]
    )

    test_predictions = test[
        [
            "player_id",
            "player_name",
            "season",
            "next_season",
            "team_abbreviation",
            "next_team_abbreviation",
            "rotation_player_flag",
            "next_rotation_player_flag",
        ]
    ].copy()

    test_predictions[
        "projected_rotation_probability"
    ] = test_probabilities

    return (
        selected_model_name,
        results,
        final_model,
        test_metrics,
        test_predictions,
    )


def main() -> None:
    warnings.filterwarnings(
        "ignore",
        category=RuntimeWarning,
    )

    MODELS_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUTS_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    frame = load_training_data()
    features = select_numeric_features(
        frame
    )

    development = frame.loc[
        frame["season"].ne(
            FINAL_TEST_CURRENT_SEASON
        )
    ].copy()

    test = frame.loc[
        frame["season"].eq(
            FINAL_TEST_CURRENT_SEASON
        )
    ].copy()

    print("=" * 80)
    print("MULTI-YEAR ROLLING PROJECTION MODELING")
    print("=" * 80)
    print(
        f"Training transitions: {len(frame):,}"
    )
    print(
        f"Development transitions: "
        f"{len(development):,}"
    )
    print(
        f"Untouched test transitions: "
        f"{len(test):,}"
    )
    print(
        f"Numeric features used: "
        f"{len(features):,}"
    )
    print(
        "Rolling validation seasons: "
        + ", ".join(
            ROLLING_VALIDATION_CURRENT_SEASONS
        )
    )
    print(
        f"Final untouched test: "
        f"{FINAL_TEST_CURRENT_SEASON} "
        "to 2025-26"
    )

    all_rolling_results: list[
        pd.DataFrame
    ] = []

    test_metric_rows: list[
        dict[str, object]
    ] = []

    test_predictions = test[
        [
            "player_id",
            "player_name",
            "season",
            "next_season",
            "team_abbreviation",
            "next_team_abbreviation",
        ]
    ].copy()

    metadata: dict[str, object] = {
        "training_data_path": str(
            TRAINING_DATA_PATH
        ),
        "feature_count": len(features),
        "features": features,
        "rolling_validation_current_seasons": (
            ROLLING_VALIDATION_CURRENT_SEASONS
        ),
        "final_test_current_season": (
            FINAL_TEST_CURRENT_SEASON
        ),
        "targets": {},
    }

    for target_name, config in (
        TARGET_CONFIG.items()
    ):
        print()
        print("=" * 80)
        print(str(config["label"]))
        print("=" * 80)

        rolling_predictions, fold_results = (
            build_rolling_predictions_for_target(
                frame=frame,
                features=features,
                target_name=target_name,
            )
        )

        selected, candidate_results = (
            choose_best_regression_approach(
                rolling_predictions=(
                    rolling_predictions
                ),
                target_name=target_name,
            )
        )

        print()
        print(
            "Best rolling approach: "
            f"{selected.model_name}"
        )
        print(
            "Baseline component: "
            f"{selected.baseline_name}"
        )
        print(
            "Model blend weight: "
            f"{selected.model_weight:.2f}"
        )
        print(
            "Rolling weighted MAE: "
            f"{selected.weighted_mae:.5f}"
        )

        model, predictions, baseline = (
            train_final_regression_model(
                development=development,
                test=test,
                features=features,
                selected=selected,
            )
        )

        actual = pd.to_numeric(
            test[target_name],
            errors="coerce",
        ).to_numpy(dtype=float)

        weights = test[
            "training_sample_weight"
        ].to_numpy(dtype=float)

        selected_metrics = regression_metrics(
            actual=actual,
            predicted=predictions,
            sample_weight=weights,
        )

        baseline_metrics = regression_metrics(
            actual=actual,
            predicted=baseline,
            sample_weight=weights,
        )

        print(
            "Test baseline weighted MAE: "
            f"{baseline_metrics['weighted_mae']:.5f}"
        )
        print(
            "Test selected weighted MAE: "
            f"{selected_metrics['weighted_mae']:.5f}"
        )
        print(
            "Test MAE improvement: "
            f"{baseline_metrics['weighted_mae'] - selected_metrics['weighted_mae']:.5f}"
        )
        print(
            "Test R-squared: "
            f"{selected_metrics['r_squared']:.4f}"
        )
        print(
            "Test Spearman correlation: "
            f"{selected_metrics['spearman_correlation']:.4f}"
        )

        model_path = (
            MODELS_DIRECTORY
            / str(config["model_filename"])
        )

        bundle = {
            "target": target_name,
            "model": model,
            "model_name": (
                selected.model_name
            ),
            "baseline_name": (
                selected.baseline_name
            ),
            "model_weight": (
                selected.model_weight
            ),
            "features": features,
            "clip_lower": (
                config["clip_lower"]
            ),
            "clip_upper": (
                config["clip_upper"]
            ),
        }

        joblib.dump(
            bundle,
            model_path,
        )

        print(
            f"Saved model bundle: {model_path}"
        )

        fold_results[
            "result_type"
        ] = "individual_model_fold"

        candidate_results[
            "result_type"
        ] = "rolling_combination_summary"

        all_rolling_results.extend(
            [
                fold_results,
                candidate_results,
            ]
        )

        test_metric_rows.append(
            {
                "target": target_name,
                "selected_model": (
                    selected.model_name
                ),
                "selected_baseline": (
                    selected.baseline_name
                ),
                "model_weight": (
                    selected.model_weight
                ),
                **selected_metrics,
                "baseline_weighted_mae": (
                    baseline_metrics[
                        "weighted_mae"
                    ]
                ),
                "weighted_mae_improvement": (
                    baseline_metrics[
                        "weighted_mae"
                    ]
                    - selected_metrics[
                        "weighted_mae"
                    ]
                ),
            }
        )

        test_predictions[
            f"actual_{target_name}"
        ] = actual

        test_predictions[
            f"projected_{target_name}"
        ] = predictions

        test_predictions[
            f"baseline_{target_name}"
        ] = baseline

        metadata["targets"][
            target_name
        ] = {
            "selected_model": (
                selected.model_name
            ),
            "selected_baseline": (
                selected.baseline_name
            ),
            "model_weight": (
                selected.model_weight
            ),
            "rolling_weighted_mae": (
                selected.weighted_mae
            ),
            "test_metrics": (
                selected_metrics
            ),
            "baseline_test_metrics": (
                baseline_metrics
            ),
            "model_path": str(
                model_path
            ),
        }

    print()
    print("=" * 80)
    print("NEXT-SEASON ROTATION PROBABILITY")
    print("=" * 80)

    (
        selected_rotation_name,
        rotation_rolling_results,
        rotation_model,
        rotation_test_metrics,
        rotation_test_predictions,
    ) = evaluate_rotation_models(
        frame=frame,
        features=features,
    )

    rotation_model_path = (
        MODELS_DIRECTORY
        / "multiyear_next_rotation_probability.joblib"
    )

    rotation_bundle = {
        "model": rotation_model,
        "model_name": (
            selected_rotation_name
        ),
        "features": features,
        "probability_lower": 0.01,
        "probability_upper": 0.99,
    }

    joblib.dump(
        rotation_bundle,
        rotation_model_path,
    )

    print(
        "Best rolling rotation model: "
        f"{selected_rotation_name}"
    )
    print(
        "Test weighted Brier score: "
        f"{rotation_test_metrics.iloc[0]['weighted_brier']:.5f}"
    )
    print(
        "Test ROC AUC: "
        f"{rotation_test_metrics.iloc[0]['roc_auc']:.4f}"
    )
    print(
        f"Saved rotation bundle: "
        f"{rotation_model_path}"
    )

    metadata["rotation_probability"] = {
        "selected_model": (
            selected_rotation_name
        ),
        "test_metrics": (
            rotation_test_metrics.iloc[0]
            .to_dict()
        ),
        "model_path": str(
            rotation_model_path
        ),
    }

    rolling_results = pd.concat(
        all_rolling_results,
        ignore_index=True,
        sort=False,
    )

    test_metrics = pd.DataFrame(
        test_metric_rows
    ).sort_values(
        "target"
    ).reset_index(drop=True)

    rolling_results.to_csv(
        ROLLING_RESULTS_PATH,
        index=False,
    )

    test_metrics.to_csv(
        TEST_METRICS_PATH,
        index=False,
    )

    test_predictions.to_csv(
        TEST_PREDICTIONS_PATH,
        index=False,
    )

    rotation_rolling_results.to_csv(
        OUTPUTS_DIRECTORY
        / "multiyear_rotation_rolling_results.csv",
        index=False,
    )

    rotation_test_metrics.to_csv(
        ROTATION_METRICS_PATH,
        index=False,
    )

    rotation_test_predictions.to_csv(
        ROTATION_PREDICTIONS_PATH,
        index=False,
    )

    with METADATA_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            metadata,
            file,
            indent=2,
            default=float,
        )

    print()
    print("=" * 80)
    print("MULTI-YEAR MODELING COMPLETED")
    print("=" * 80)
    print()
    print("TEST SUMMARY")
    print(
        test_metrics[
            [
                "target",
                "selected_model",
                "selected_baseline",
                "model_weight",
                "weighted_mae",
                "baseline_weighted_mae",
                "weighted_mae_improvement",
                "r_squared",
                "spearman_correlation",
            ]
        ].to_string(
            index=False
        )
    )
    print()
    print("OUTPUT FILES")
    print(ROLLING_RESULTS_PATH)
    print(TEST_METRICS_PATH)
    print(TEST_PREDICTIONS_PATH)
    print(ROTATION_METRICS_PATH)
    print(ROTATION_PREDICTIONS_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()