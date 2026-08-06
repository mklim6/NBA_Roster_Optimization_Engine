from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.base import BaseEstimator
from sklearn.ensemble import (
    ExtraTreesClassifier,
    ExtraTreesRegressor,
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    RandomForestRegressor,
)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


PROJECT_ROOT = Path(__file__).resolve().parents[1]

INPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "survival_aware_projection_training_data.parquet"
)

MODELS_DIRECTORY = PROJECT_ROOT / "models"
OUTPUTS_DIRECTORY = PROJECT_ROOT / "outputs"

MODEL_PATH = (
    MODELS_DIRECTORY
    / "final_expected_contribution_model.joblib"
)

METADATA_PATH = (
    MODELS_DIRECTORY
    / "final_expected_contribution_metadata.json"
)

ROLLING_RESULTS_PATH = (
    OUTPUTS_DIRECTORY
    / "expected_contribution_rolling_results.csv"
)

ROLLING_PREDICTIONS_PATH = (
    OUTPUTS_DIRECTORY
    / "expected_contribution_rolling_predictions.csv"
)

TEST_METRICS_PATH = (
    OUTPUTS_DIRECTORY
    / "expected_contribution_test_metrics.csv"
)

TEST_PREDICTIONS_PATH = (
    OUTPUTS_DIRECTORY
    / "expected_contribution_test_predictions.csv"
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

DIRECT_BLEND_WEIGHTS = [
    0.00,
    0.25,
    0.50,
    0.75,
    1.00,
]

BASELINE_BLEND_WEIGHTS = [
    0.00,
    0.10,
    0.20,
]

TARGET_COLUMN = "next_total_impact_value"

SEASON_SCHEDULE_GAMES = {
    "2015-16": 82,
    "2016-17": 82,
    "2017-18": 82,
    "2018-19": 82,
    "2019-20": 74,
    "2020-21": 72,
    "2021-22": 82,
    "2022-23": 82,
    "2023-24": 82,
    "2024-25": 82,
    "2025-26": 82,
}

IDENTIFIER_COLUMNS = {
    "player_id",
    "player_name",
    "season",
    "target_season",
    "team_id",
    "team_abbreviation",
    "data_source",
}

EXCLUDED_FEATURE_COLUMNS = {
    "training_sample_weight",
    "survival_training_sample_weight",
    "conditional_training_sample_weight",
}


@dataclass
class SelectedContributionApproach:
    direct_model_name: str
    direct_weight: float
    baseline_weight: float
    weighted_mae: float


class TwoStageConditionalMinutesModel(BaseEstimator):
    """
    Predict minutes per game among players who remain active.

    Stage 1 estimates next-season rotation probability.
    Stage 2 estimates minutes for rotation and non-rotation players.
    """

    def __init__(self, random_state: int = RANDOM_STATE):
        self.random_state = random_state
        self.rotation_classifier: Pipeline | None = None
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
    ) -> "TwoStageConditionalMinutesModel":
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

        self.rotation_classifier = (
            self._make_classifier()
        )

        self.rotation_classifier.fit(
            X,
            rotation_numeric,
            model__sample_weight=weights,
        )

        rotation_mask = rotation_numeric.eq(1)
        nonrotation_mask = rotation_numeric.eq(0)

        if rotation_mask.sum() >= 30:
            self.rotation_regressor = (
                self._make_regressor()
            )

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
                    weights=weights.loc[
                        rotation_mask
                    ],
                )
            )

        if nonrotation_mask.sum() >= 30:
            self.nonrotation_regressor = (
                self._make_regressor()
            )

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
        if self.rotation_classifier is None:
            raise RuntimeError(
                "The minutes model has not been fitted."
            )

        probabilities = (
            self.rotation_classifier.predict_proba(X)[:, 1]
        )

        return np.clip(
            probabilities,
            0.01,
            0.99,
        )

    def predict(
        self,
        X: pd.DataFrame,
    ) -> np.ndarray:
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
            rotation_probability
            * rotation_minutes
            + (1.0 - rotation_probability)
            * nonrotation_minutes
        )

        return np.clip(
            predictions,
            0.0,
            40.0,
        )


def make_survival_model() -> Pipeline:
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
                ExtraTreesClassifier(
                    n_estimators=500,
                    max_depth=12,
                    min_samples_leaf=6,
                    max_features=0.65,
                    n_jobs=-1,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def make_conditional_regressor() -> Pipeline:
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


def make_ridge_direct_model() -> Pipeline:
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
                    alpha=40.0,
                ),
            ),
        ]
    )


def make_random_forest_direct_model() -> Pipeline:
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
                    n_estimators=400,
                    max_depth=11,
                    min_samples_leaf=7,
                    max_features=0.60,
                    n_jobs=-1,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def make_extra_trees_direct_model() -> Pipeline:
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
                    n_estimators=500,
                    max_depth=13,
                    min_samples_leaf=5,
                    max_features=0.70,
                    n_jobs=-1,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def make_hgb_direct_model() -> Pipeline:
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
                    max_iter=400,
                    max_leaf_nodes=15,
                    min_samples_leaf=25,
                    l2_regularization=4.0,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def direct_model_factories(
) -> dict[str, Callable[[], Pipeline]]:
    return {
        "ridge": make_ridge_direct_model,
        "random_forest": (
            make_random_forest_direct_model
        ),
        "extra_trees": (
            make_extra_trees_direct_model
        ),
        "hist_gradient_boosting": (
            make_hgb_direct_model
        ),
    }


def load_data() -> pd.DataFrame:
    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            "The survival-aware training data was not found at:\n"
            f"{INPUT_PATH}"
        )

    frame = pd.read_parquet(INPUT_PATH)

    if frame.empty:
        raise ValueError(
            "The survival-aware training dataset is empty."
        )

    required_columns = {
        "player_id",
        "player_name",
        "season",
        "target_season",
        "season_start",
        "team_abbreviation",
        "next_season_active_flag",
        "next_rotation_player_flag",
        "next_minutes_per_game_if_active",
        "next_availability_rate_if_active",
        "next_advanced_pie_if_active",
        "next_total_impact_value",
        "minutes_per_game",
        "availability_rate",
        "advanced_pie",
        "weighted3_minutes_per_game",
        "weighted3_availability_rate",
        "weighted3_advanced_pie",
        "sample_reliability",
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

    frame["season_start"] = pd.to_numeric(
        frame["season_start"],
        errors="raise",
    ).astype(int)

    frame["next_season_active_flag"] = (
        pd.to_numeric(
            frame["next_season_active_flag"],
            errors="raise",
        )
        .astype(int)
    )

    frame["next_rotation_player_flag"] = (
        pd.to_numeric(
            frame["next_rotation_player_flag"],
            errors="raise",
        )
        .astype(int)
    )

    frame["model_sample_weight"] = (
        0.50
        + 0.50
        * pd.to_numeric(
            frame["sample_reliability"],
            errors="coerce",
        )
        .fillna(0.0)
        .clip(lower=0.0, upper=1.0)
    )

    return frame


def select_features(
    frame: pd.DataFrame,
) -> list[str]:
    development = frame.loc[
        frame["season"].ne(
            FINAL_TEST_CURRENT_SEASON
        )
    ]

    features: list[str] = []

    for column in frame.columns:
        if column in IDENTIFIER_COLUMNS:
            continue

        if column in EXCLUDED_FEATURE_COLUMNS:
            continue

        if column == "model_sample_weight":
            continue

        if column.startswith("next_"):
            continue

        if column.startswith("target_"):
            continue

        if not pd.api.types.is_numeric_dtype(
            frame[column]
        ):
            continue

        missing_rate = float(
            development[column]
            .isna()
            .mean()
        )

        unique_count = int(
            development[column]
            .nunique(dropna=True)
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


def fit_pipeline(
    model: Pipeline,
    X: pd.DataFrame,
    y: pd.Series,
    sample_weight: pd.Series,
) -> Pipeline:
    model.fit(
        X,
        y,
        model__sample_weight=sample_weight,
    )

    return model


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
        "weighted_mae": float(
            mean_absolute_error(
                actual,
                predicted,
                sample_weight=sample_weight,
            )
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
        "spearman_correlation": (
            safe_spearman(
                actual,
                predicted,
            )
        ),
    }


def target_schedule_games(
    target_seasons: pd.Series,
) -> np.ndarray:
    missing = sorted(
        set(
            target_seasons.dropna().astype(str)
        ).difference(
            SEASON_SCHEDULE_GAMES
        )
    )

    if missing:
        raise ValueError(
            "Schedule-game counts are missing for:\n"
            + "\n".join(missing)
        )

    return (
        target_seasons
        .map(SEASON_SCHEDULE_GAMES)
        .to_numpy(dtype=float)
    )


def make_persistence_baseline(
    frame: pd.DataFrame,
) -> np.ndarray:
    current_total_impact = (
        pd.to_numeric(
            frame["advanced_pie"],
            errors="coerce",
        )
        .fillna(0.0)
        .to_numpy(dtype=float)
        * pd.to_numeric(
            frame["total_minutes"],
            errors="coerce",
        )
        .fillna(0.0)
        .to_numpy(dtype=float)
    )

    return current_total_impact


def fit_staged_models(
    train: pd.DataFrame,
    features: list[str],
) -> dict[str, object]:
    X_train = train[features]

    survival_model = make_survival_model()

    survival_model = fit_pipeline(
        model=survival_model,
        X=X_train,
        y=train[
            "next_season_active_flag"
        ].astype(int),
        sample_weight=pd.Series(
            np.ones(len(train)),
            index=train.index,
        ),
    )

    active_train = train.loc[
        train["next_season_active_flag"].eq(1)
    ].copy()

    X_active = active_train[features]

    conditional_weights = (
        active_train["model_sample_weight"]
    )

    minutes_model = (
        TwoStageConditionalMinutesModel(
            random_state=RANDOM_STATE
        )
    )

    minutes_model.fit(
        X=X_active,
        y=active_train[
            "next_minutes_per_game_if_active"
        ],
        rotation_target=active_train[
            "next_rotation_player_flag"
        ],
        sample_weight=conditional_weights,
    )

    availability_model = (
        make_conditional_regressor()
    )

    availability_model = fit_pipeline(
        model=availability_model,
        X=X_active,
        y=active_train[
            "next_availability_rate_if_active"
        ],
        sample_weight=conditional_weights,
    )

    pie_model = make_conditional_regressor()

    pie_model = fit_pipeline(
        model=pie_model,
        X=X_active,
        y=active_train[
            "next_advanced_pie_if_active"
        ],
        sample_weight=conditional_weights,
    )

    return {
        "survival": survival_model,
        "minutes": minutes_model,
        "availability": availability_model,
        "pie": pie_model,
    }


def predict_staged_contribution(
    models: dict[str, object],
    frame: pd.DataFrame,
    features: list[str],
) -> tuple[
    np.ndarray,
    dict[str, np.ndarray],
]:
    X = frame[features]

    survival_model = models["survival"]
    minutes_model = models["minutes"]
    availability_model = models["availability"]
    pie_model = models["pie"]

    if not isinstance(
        survival_model,
        Pipeline,
    ):
        raise TypeError(
            "The survival model bundle is invalid."
        )

    if not isinstance(
        minutes_model,
        TwoStageConditionalMinutesModel,
    ):
        raise TypeError(
            "The minutes model bundle is invalid."
        )

    if not isinstance(
        availability_model,
        Pipeline,
    ):
        raise TypeError(
            "The availability model bundle is invalid."
        )

    if not isinstance(
        pie_model,
        Pipeline,
    ):
        raise TypeError(
            "The PIE model bundle is invalid."
        )

    survival_probability = np.clip(
        survival_model.predict_proba(X)[:, 1],
        0.001,
        0.999,
    )

    conditional_minutes = np.clip(
        minutes_model.predict(X),
        0.0,
        40.0,
    )

    current_minutes = (
        pd.to_numeric(
            frame["minutes_per_game"],
            errors="coerce",
        )
        .fillna(0.0)
        .to_numpy(dtype=float)
    )

    conditional_minutes = (
        0.75 * conditional_minutes
        + 0.25 * current_minutes
    )

    conditional_availability = np.clip(
        availability_model.predict(X),
        0.0,
        1.0,
    )

    history_availability = (
        pd.to_numeric(
            frame[
                "weighted3_availability_rate"
            ],
            errors="coerce",
        )
        .fillna(
            pd.to_numeric(
                frame["availability_rate"],
                errors="coerce",
            )
        )
        .fillna(0.0)
        .to_numpy(dtype=float)
    )

    conditional_availability = np.clip(
        0.75 * conditional_availability
        + 0.25 * history_availability,
        0.0,
        1.0,
    )

    conditional_pie = np.clip(
        pie_model.predict(X),
        -0.05,
        0.30,
    )

    history_pie = (
        pd.to_numeric(
            frame["weighted3_advanced_pie"],
            errors="coerce",
        )
        .fillna(
            pd.to_numeric(
                frame["advanced_pie"],
                errors="coerce",
            )
        )
        .fillna(0.0)
        .to_numpy(dtype=float)
    )

    conditional_pie = np.clip(
        0.75 * conditional_pie
        + 0.25 * history_pie,
        -0.05,
        0.30,
    )

    schedule_games = target_schedule_games(
        frame["target_season"]
    )

    staged_contribution = (
        survival_probability
        * conditional_minutes
        * conditional_availability
        * schedule_games
        * conditional_pie
    )

    components = {
        "survival_probability": (
            survival_probability
        ),
        "conditional_minutes_per_game": (
            conditional_minutes
        ),
        "conditional_availability_rate": (
            conditional_availability
        ),
        "conditional_pie": conditional_pie,
        "target_schedule_games": schedule_games,
    }

    return staged_contribution, components


def build_rolling_predictions(
    frame: pd.DataFrame,
    features: list[str],
) -> pd.DataFrame:
    factories = direct_model_factories()

    rolling_frames: list[
        pd.DataFrame
    ] = []

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
            frame["season"].eq(
                validation_season
            )
        ].copy()

        if train.empty or validation.empty:
            raise ValueError(
                "An empty rolling fold was found for "
                f"{validation_season}."
            )

        print()
        print(
            f"{validation_season}: fitting "
            "staged projection components..."
        )

        staged_models = fit_staged_models(
            train=train,
            features=features,
        )

        staged_predictions, components = (
            predict_staged_contribution(
                models=staged_models,
                frame=validation,
                features=features,
            )
        )

        fold = validation[
            [
                "player_id",
                "player_name",
                "season",
                "target_season",
                "team_abbreviation",
                "next_season_active_flag",
                "next_rotation_player_flag",
                TARGET_COLUMN,
                "model_sample_weight",
            ]
        ].copy()

        fold = fold.rename(
            columns={
                TARGET_COLUMN: "actual",
                "model_sample_weight": (
                    "sample_weight"
                ),
            }
        )

        fold["staged_prediction"] = (
            staged_predictions
        )

        fold["persistence_baseline"] = (
            make_persistence_baseline(
                validation
            )
        )

        for component_name, values in (
            components.items()
        ):
            fold[
                f"staged_{component_name}"
            ] = values

        for model_name, factory in (
            factories.items()
        ):
            print(
                f"{validation_season}: fitting "
                f"direct {model_name}..."
            )

            model = factory()

            model = fit_pipeline(
                model=model,
                X=train[features],
                y=train[TARGET_COLUMN],
                sample_weight=train[
                    "model_sample_weight"
                ],
            )

            fold[
                f"direct__{model_name}"
            ] = model.predict(
                validation[features]
            )

        rolling_frames.append(fold)

    return pd.concat(
        rolling_frames,
        ignore_index=True,
    )


def select_best_blend(
    rolling: pd.DataFrame,
) -> tuple[
    SelectedContributionApproach,
    pd.DataFrame,
]:
    actual = (
        rolling["actual"]
        .to_numpy(dtype=float)
    )

    weights = (
        rolling["sample_weight"]
        .to_numpy(dtype=float)
    )

    staged = (
        rolling["staged_prediction"]
        .to_numpy(dtype=float)
    )

    baseline = (
        rolling["persistence_baseline"]
        .to_numpy(dtype=float)
    )

    rows: list[
        dict[str, object]
    ] = []

    for direct_column in [
        column
        for column in rolling.columns
        if column.startswith("direct__")
    ]:
        model_name = direct_column.replace(
            "direct__",
            "",
        )

        direct = (
            rolling[direct_column]
            .to_numpy(dtype=float)
        )

        for direct_weight in (
            DIRECT_BLEND_WEIGHTS
        ):
            staged_direct = (
                direct_weight * direct
                + (1.0 - direct_weight)
                * staged
            )

            for baseline_weight in (
                BASELINE_BLEND_WEIGHTS
            ):
                prediction = (
                    (1.0 - baseline_weight)
                    * staged_direct
                    + baseline_weight
                    * baseline
                )

                metrics = regression_metrics(
                    actual=actual,
                    predicted=prediction,
                    sample_weight=weights,
                )

                rows.append(
                    {
                        "direct_model": (
                            model_name
                        ),
                        "direct_weight": (
                            direct_weight
                        ),
                        "staged_weight": (
                            1.0 - direct_weight
                        ),
                        "baseline_weight": (
                            baseline_weight
                        ),
                        **metrics,
                    }
                )

    results = pd.DataFrame(
        rows
    ).sort_values(
        [
            "weighted_mae",
            "rmse",
        ],
        ascending=True,
    ).reset_index(drop=True)

    best = results.iloc[0]

    selected = SelectedContributionApproach(
        direct_model_name=str(
            best["direct_model"]
        ),
        direct_weight=float(
            best["direct_weight"]
        ),
        baseline_weight=float(
            best["baseline_weight"]
        ),
        weighted_mae=float(
            best["weighted_mae"]
        ),
    )

    return selected, results


def final_prediction_from_components(
    direct: np.ndarray,
    staged: np.ndarray,
    baseline: np.ndarray,
    selected: SelectedContributionApproach,
) -> np.ndarray:
    staged_direct = (
        selected.direct_weight
        * direct
        + (1.0 - selected.direct_weight)
        * staged
    )

    return (
        (1.0 - selected.baseline_weight)
        * staged_direct
        + selected.baseline_weight
        * baseline
    )


def main() -> None:
    MODELS_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUTS_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    frame = load_data()
    features = select_features(frame)

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
    print("END-TO-END EXPECTED CONTRIBUTION OPTIMIZATION")
    print("=" * 80)
    print(
        f"Total rows: {len(frame):,}"
    )
    print(
        f"Development rows: "
        f"{len(development):,}"
    )
    print(
        f"Untouched test rows: "
        f"{len(test):,}"
    )
    print(
        f"Features used: {len(features):,}"
    )
    print(
        "Target: next-season total impact value "
        "including zero for players who leave"
    )

    rolling = build_rolling_predictions(
        frame=frame,
        features=features,
    )

    selected, blend_results = (
        select_best_blend(
            rolling
        )
    )

    print()
    print("=" * 80)
    print("BEST ROLLING APPROACH")
    print("=" * 80)
    print(
        "Direct model: "
        f"{selected.direct_model_name}"
    )
    print(
        "Direct model weight: "
        f"{selected.direct_weight:.2f}"
    )
    print(
        "Staged model weight: "
        f"{1.0 - selected.direct_weight:.2f}"
    )
    print(
        "Persistence baseline weight: "
        f"{selected.baseline_weight:.2f}"
    )
    print(
        "Rolling weighted MAE: "
        f"{selected.weighted_mae:.5f}"
    )

    print()
    print(
        "Retraining final staged components "
        "on all development seasons..."
    )

    final_staged_models = fit_staged_models(
        train=development,
        features=features,
    )

    staged_test, staged_components = (
        predict_staged_contribution(
            models=final_staged_models,
            frame=test,
            features=features,
        )
    )

    direct_factory = (
        direct_model_factories()[
            selected.direct_model_name
        ]
    )

    print(
        "Retraining final direct model "
        "on all development seasons..."
    )

    final_direct_model = direct_factory()

    final_direct_model = fit_pipeline(
        model=final_direct_model,
        X=development[features],
        y=development[TARGET_COLUMN],
        sample_weight=development[
            "model_sample_weight"
        ],
    )

    direct_test = final_direct_model.predict(
        test[features]
    )

    baseline_test = make_persistence_baseline(
        test
    )

    final_test = (
        final_prediction_from_components(
            direct=direct_test,
            staged=staged_test,
            baseline=baseline_test,
            selected=selected,
        )
    )

    actual_test = (
        test[TARGET_COLUMN]
        .to_numpy(dtype=float)
    )

    test_weights = (
        test["model_sample_weight"]
        .to_numpy(dtype=float)
    )

    final_metrics = regression_metrics(
        actual=actual_test,
        predicted=final_test,
        sample_weight=test_weights,
    )

    staged_metrics = regression_metrics(
        actual=actual_test,
        predicted=staged_test,
        sample_weight=test_weights,
    )

    direct_metrics = regression_metrics(
        actual=actual_test,
        predicted=direct_test,
        sample_weight=test_weights,
    )

    baseline_metrics = regression_metrics(
        actual=actual_test,
        predicted=baseline_test,
        sample_weight=test_weights,
    )

    print()
    print("=" * 80)
    print("UNTOUCHED TEST RESULTS")
    print("=" * 80)
    print(
        "Persistence weighted MAE: "
        f"{baseline_metrics['weighted_mae']:.5f}"
    )
    print(
        "Pure staged weighted MAE: "
        f"{staged_metrics['weighted_mae']:.5f}"
    )
    print(
        "Pure direct weighted MAE: "
        f"{direct_metrics['weighted_mae']:.5f}"
    )
    print(
        "Final blended weighted MAE: "
        f"{final_metrics['weighted_mae']:.5f}"
    )
    print(
        "Improvement over persistence: "
        f"{baseline_metrics['weighted_mae'] - final_metrics['weighted_mae']:.5f}"
    )
    print(
        "Final R-squared: "
        f"{final_metrics['r_squared']:.4f}"
    )
    print(
        "Final Spearman correlation: "
        f"{final_metrics['spearman_correlation']:.4f}"
    )

    model_bundle = {
        "target": TARGET_COLUMN,
        "features": features,
        "staged_models": final_staged_models,
        "direct_model": final_direct_model,
        "direct_model_name": (
            selected.direct_model_name
        ),
        "direct_weight": (
            selected.direct_weight
        ),
        "staged_weight": (
            1.0 - selected.direct_weight
        ),
        "baseline_weight": (
            selected.baseline_weight
        ),
        "season_schedule_games": (
            SEASON_SCHEDULE_GAMES
        ),
    }

    joblib.dump(
        model_bundle,
        MODEL_PATH,
    )

    rolling.to_csv(
        ROLLING_PREDICTIONS_PATH,
        index=False,
    )

    blend_results.to_csv(
        ROLLING_RESULTS_PATH,
        index=False,
    )

    test_predictions = test[
        [
            "player_id",
            "player_name",
            "season",
            "target_season",
            "team_abbreviation",
            "next_season_active_flag",
            "next_rotation_player_flag",
            TARGET_COLUMN,
            "model_sample_weight",
        ]
    ].copy()

    test_predictions = (
        test_predictions.rename(
            columns={
                TARGET_COLUMN: (
                    "actual_total_impact_value"
                )
            }
        )
    )

    test_predictions[
        "projected_staged_total_impact"
    ] = staged_test

    test_predictions[
        "projected_direct_total_impact"
    ] = direct_test

    test_predictions[
        "projected_final_total_impact"
    ] = final_test

    test_predictions[
        "persistence_total_impact"
    ] = baseline_test

    for component_name, values in (
        staged_components.items()
    ):
        test_predictions[
            f"projected_{component_name}"
        ] = values

    test_predictions.to_csv(
        TEST_PREDICTIONS_PATH,
        index=False,
    )

    metrics_rows = []

    for approach_name, metrics in [
        ("persistence", baseline_metrics),
        ("staged", staged_metrics),
        ("direct", direct_metrics),
        ("final_blend", final_metrics),
    ]:
        metrics_rows.append(
            {
                "approach": approach_name,
                **metrics,
            }
        )

    test_metrics = pd.DataFrame(
        metrics_rows
    )

    test_metrics.to_csv(
        TEST_METRICS_PATH,
        index=False,
    )

    metadata = {
        "input_path": str(INPUT_PATH),
        "target": TARGET_COLUMN,
        "feature_count": len(features),
        "features": features,
        "development_rows": len(development),
        "test_rows": len(test),
        "rolling_validation_current_seasons": (
            ROLLING_VALIDATION_CURRENT_SEASONS
        ),
        "final_test_current_season": (
            FINAL_TEST_CURRENT_SEASON
        ),
        "selected_direct_model": (
            selected.direct_model_name
        ),
        "direct_weight": (
            selected.direct_weight
        ),
        "staged_weight": (
            1.0 - selected.direct_weight
        ),
        "baseline_weight": (
            selected.baseline_weight
        ),
        "rolling_weighted_mae": (
            selected.weighted_mae
        ),
        "test_metrics": {
            "persistence": baseline_metrics,
            "staged": staged_metrics,
            "direct": direct_metrics,
            "final_blend": final_metrics,
        },
        "model_path": str(MODEL_PATH),
    }

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
    print("END-TO-END OPTIMIZATION COMPLETED")
    print("=" * 80)
    print(MODEL_PATH)
    print(METADATA_PATH)
    print(ROLLING_RESULTS_PATH)
    print(ROLLING_PREDICTIONS_PATH)
    print(TEST_METRICS_PATH)
    print(TEST_PREDICTIONS_PATH)


if __name__ == "__main__":
    main()