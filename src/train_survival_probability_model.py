from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import (
    ExtraTreesClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
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
    / "next_season_survival_probability.joblib"
)

METADATA_PATH = (
    MODELS_DIRECTORY
    / "next_season_survival_probability_metadata.json"
)

ROLLING_RESULTS_PATH = (
    OUTPUTS_DIRECTORY
    / "survival_probability_rolling_results.csv"
)

ROLLING_PREDICTIONS_PATH = (
    OUTPUTS_DIRECTORY
    / "survival_probability_rolling_predictions.csv"
)

TEST_METRICS_PATH = (
    OUTPUTS_DIRECTORY
    / "survival_probability_test_metrics.csv"
)

TEST_PREDICTIONS_PATH = (
    OUTPUTS_DIRECTORY
    / "survival_probability_test_predictions.csv"
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
    0.50,
    0.75,
    0.90,
    1.00,
]

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
class SelectedSurvivalApproach:
    model_name: str
    calibration_method: str
    model_weight: float
    weighted_brier: float


def make_logistic_pipeline(
    c_value: float,
) -> Pipeline:
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
                    C=c_value,
                    max_iter=3_000,
                    random_state=RANDOM_STATE,
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
                RandomForestClassifier(
                    n_estimators=500,
                    max_depth=10,
                    min_samples_leaf=8,
                    max_features=0.55,
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
                HistGradientBoostingClassifier(
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


def candidate_factories(
) -> dict[str, Callable[[], Pipeline]]:
    return {
        "logistic_c0_10": (
            lambda: make_logistic_pipeline(0.10)
        ),
        "logistic_c0_50": (
            lambda: make_logistic_pipeline(0.50)
        ),
        "logistic_c1_00": (
            lambda: make_logistic_pipeline(1.00)
        ),
        "random_forest": make_random_forest_pipeline,
        "extra_trees": make_extra_trees_pipeline,
        "hist_gradient_boosting": (
            make_hist_gradient_boosting_pipeline
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
            "The survival-aware training data is empty."
        )

    required_columns = {
        "player_id",
        "player_name",
        "season",
        "target_season",
        "season_start",
        "next_season_active_flag",
        "rotation_player_flag",
        "sample_reliability",
    }

    missing_columns = sorted(
        required_columns.difference(frame.columns)
    )

    if missing_columns:
        raise ValueError(
            "The survival-aware data is missing required columns:\n"
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
            "No usable survival-model features were found."
        )

    return sorted(features)


def fit_model(
    model: Pipeline,
    X: pd.DataFrame,
    y: pd.Series,
) -> Pipeline:
    model.fit(
        X,
        y,
        model__sample_weight=np.ones(
            len(y),
            dtype=float,
        ),
    )

    return model


def weighted_prevalence(
    y: np.ndarray,
    weights: np.ndarray,
) -> float:
    return float(
        np.average(
            y,
            weights=weights,
        )
    )


def expected_calibration_error(
    actual: np.ndarray,
    probabilities: np.ndarray,
    sample_weight: np.ndarray,
    bins: int = 10,
) -> float:
    edges = np.linspace(
        0.0,
        1.0,
        bins + 1,
    )

    total_weight = float(
        sample_weight.sum()
    )

    error = 0.0

    for index in range(bins):
        lower = edges[index]
        upper = edges[index + 1]

        if index == bins - 1:
            mask = (
                (probabilities >= lower)
                & (probabilities <= upper)
            )
        else:
            mask = (
                (probabilities >= lower)
                & (probabilities < upper)
            )

        if not mask.any():
            continue

        bin_weight = float(
            sample_weight[mask].sum()
        )

        mean_probability = float(
            np.average(
                probabilities[mask],
                weights=sample_weight[mask],
            )
        )

        observed_rate = float(
            np.average(
                actual[mask],
                weights=sample_weight[mask],
            )
        )

        error += (
            bin_weight
            / total_weight
            * abs(
                mean_probability
                - observed_rate
            )
        )

    return float(error)


def classification_metrics(
    actual: np.ndarray,
    probabilities: np.ndarray,
    sample_weight: np.ndarray,
) -> dict[str, float]:
    clipped = np.clip(
        probabilities,
        0.001,
        0.999,
    )

    weighted_brier = float(
        np.average(
            (clipped - actual) ** 2,
            weights=sample_weight,
        )
    )

    return {
        "weighted_brier": weighted_brier,
        "brier": float(
            brier_score_loss(
                actual,
                clipped,
                sample_weight=sample_weight,
            )
        ),
        "log_loss": float(
            log_loss(
                actual,
                clipped,
                sample_weight=sample_weight,
                labels=[0, 1],
            )
        ),
        "roc_auc": float(
            roc_auc_score(
                actual,
                clipped,
                sample_weight=sample_weight,
            )
        ),
        "average_precision": float(
            average_precision_score(
                actual,
                clipped,
                sample_weight=sample_weight,
            )
        ),
        "ece_10_bin": (
            expected_calibration_error(
                actual,
                clipped,
                sample_weight,
                bins=10,
            )
        ),
    }


def logit(
    probabilities: np.ndarray,
) -> np.ndarray:
    clipped = np.clip(
        probabilities,
        0.001,
        0.999,
    )

    return np.log(
        clipped / (1.0 - clipped)
    )


def fit_platt_calibrator(
    probabilities: np.ndarray,
    actual: np.ndarray,
    sample_weight: np.ndarray,
) -> LogisticRegression:
    calibrator = LogisticRegression(
        C=1.0,
        max_iter=2_000,
        random_state=RANDOM_STATE,
    )

    calibrator.fit(
        logit(probabilities).reshape(-1, 1),
        actual,
        sample_weight=sample_weight,
    )

    return calibrator


def apply_platt_calibrator(
    calibrator: LogisticRegression,
    probabilities: np.ndarray,
) -> np.ndarray:
    return calibrator.predict_proba(
        logit(probabilities).reshape(-1, 1)
    )[:, 1]


def fit_isotonic_calibrator(
    probabilities: np.ndarray,
    actual: np.ndarray,
    sample_weight: np.ndarray,
) -> IsotonicRegression:
    calibrator = IsotonicRegression(
        y_min=0.001,
        y_max=0.999,
        out_of_bounds="clip",
    )

    calibrator.fit(
        probabilities,
        actual,
        sample_weight=sample_weight,
    )

    return calibrator


def build_rolling_predictions(
    frame: pd.DataFrame,
    features: list[str],
) -> pd.DataFrame:
    factories = candidate_factories()
    fold_frames: list[pd.DataFrame] = []

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

        X_train = train[features]
        X_validation = validation[features]

        y_train = train[
            "next_season_active_flag"
        ].astype(int)

        y_validation = validation[
            "next_season_active_flag"
        ].astype(int)

        train_weights = np.ones(
            len(train),
            dtype=float,
        )

        validation_weights = np.ones(
            len(validation),
            dtype=float,
        )

        baseline_probability = (
            weighted_prevalence(
                y_train.to_numpy(),
                train_weights,
            )
        )

        fold = validation[
            [
                "player_id",
                "player_name",
                "season",
                "target_season",
                "team_abbreviation",
                "rotation_player_flag",
                "minutes_per_game",
                "total_minutes",
            ]
        ].copy()

        fold["actual"] = (
            y_validation.to_numpy()
        )

        fold["sample_weight"] = (
            validation_weights
        )

        fold["baseline_probability"] = (
            baseline_probability
        )

        for model_name, factory in (
            factories.items()
        ):
            print(
                f"  {validation_season}: fitting "
                f"{model_name}..."
            )

            model = factory()

            model = fit_model(
                model=model,
                X=X_train,
                y=y_train,
            )

            probabilities = (
                model.predict_proba(
                    X_validation
                )[:, 1]
            )

            fold[
                f"raw__{model_name}"
            ] = np.clip(
                probabilities,
                0.001,
                0.999,
            )

        fold_frames.append(fold)

    return pd.concat(
        fold_frames,
        ignore_index=True,
    )


def build_forward_calibrated_predictions(
    rolling: pd.DataFrame,
    model_name: str,
    method: str,
) -> np.ndarray:
    raw_column = f"raw__{model_name}"

    output = np.full(
        len(rolling),
        np.nan,
        dtype=float,
    )

    season_order = (
        ROLLING_VALIDATION_CURRENT_SEASONS
    )

    for index, validation_season in enumerate(
        season_order
    ):
        validation_mask = (
            rolling["season"]
            .eq(validation_season)
            .to_numpy()
        )

        if index == 0 or method == "none":
            output[validation_mask] = (
                rolling.loc[
                    validation_mask,
                    raw_column,
                ]
                .to_numpy(dtype=float)
            )
            continue

        prior_seasons = season_order[:index]

        calibration_mask = (
            rolling["season"]
            .isin(prior_seasons)
            .to_numpy()
        )

        calibration_probabilities = (
            rolling.loc[
                calibration_mask,
                raw_column,
            ]
            .to_numpy(dtype=float)
        )

        calibration_actual = (
            rolling.loc[
                calibration_mask,
                "actual",
            ]
            .to_numpy(dtype=int)
        )

        calibration_weights = (
            rolling.loc[
                calibration_mask,
                "sample_weight",
            ]
            .to_numpy(dtype=float)
        )

        validation_probabilities = (
            rolling.loc[
                validation_mask,
                raw_column,
            ]
            .to_numpy(dtype=float)
        )

        if method == "platt":
            calibrator = (
                fit_platt_calibrator(
                    calibration_probabilities,
                    calibration_actual,
                    calibration_weights,
                )
            )

            calibrated = (
                apply_platt_calibrator(
                    calibrator,
                    validation_probabilities,
                )
            )

        elif method == "isotonic":
            calibrator = (
                fit_isotonic_calibrator(
                    calibration_probabilities,
                    calibration_actual,
                    calibration_weights,
                )
            )

            calibrated = calibrator.predict(
                validation_probabilities
            )

        else:
            raise ValueError(
                f"Unknown calibration method: {method}"
            )

        output[validation_mask] = np.clip(
            calibrated,
            0.001,
            0.999,
        )

    return output


def select_best_approach(
    rolling: pd.DataFrame,
) -> tuple[
    SelectedSurvivalApproach,
    pd.DataFrame,
    dict[str, np.ndarray],
]:
    actual = rolling[
        "actual"
    ].to_numpy(dtype=int)

    weights = rolling[
        "sample_weight"
    ].to_numpy(dtype=float)

    baseline = rolling[
        "baseline_probability"
    ].to_numpy(dtype=float)

    evaluation_mask = (
        rolling["season"]
        .ne(
            ROLLING_VALIDATION_CURRENT_SEASONS[0]
        )
        .to_numpy()
    )

    prediction_cache: dict[
        str,
        np.ndarray,
    ] = {}

    rows: list[dict[str, object]] = []

    baseline_metrics = (
        classification_metrics(
            actual=actual[evaluation_mask],
            probabilities=baseline[
                evaluation_mask
            ],
            sample_weight=weights[
                evaluation_mask
            ],
        )
    )

    rows.append(
        {
            "model": "baseline_only",
            "calibration": "none",
            "model_weight": 0.0,
            **baseline_metrics,
        }
    )

    for model_name in candidate_factories():
        for calibration_method in (
            "none",
            "platt",
            "isotonic",
        ):
            calibrated = (
                build_forward_calibrated_predictions(
                    rolling=rolling,
                    model_name=model_name,
                    method=calibration_method,
                )
            )

            cache_key = (
                f"{model_name}__"
                f"{calibration_method}"
            )

            prediction_cache[
                cache_key
            ] = calibrated

            for model_weight in (
                MODEL_BLEND_WEIGHTS
            ):
                blended = (
                    model_weight
                    * calibrated
                    + (1.0 - model_weight)
                    * baseline
                )

                metrics = classification_metrics(
                    actual=actual[
                        evaluation_mask
                    ],
                    probabilities=blended[
                        evaluation_mask
                    ],
                    sample_weight=weights[
                        evaluation_mask
                    ],
                )

                rows.append(
                    {
                        "model": model_name,
                        "calibration": (
                            calibration_method
                        ),
                        "model_weight": (
                            model_weight
                        ),
                        **metrics,
                    }
                )

    results = pd.DataFrame(
        rows
    ).sort_values(
        [
            "weighted_brier",
            "log_loss",
            "ece_10_bin",
        ],
        ascending=True,
    ).reset_index(drop=True)

    best = results.iloc[0]

    selected = SelectedSurvivalApproach(
        model_name=str(
            best["model"]
        ),
        calibration_method=str(
            best["calibration"]
        ),
        model_weight=float(
            best["model_weight"]
        ),
        weighted_brier=float(
            best["weighted_brier"]
        ),
    )

    return (
        selected,
        results,
        prediction_cache,
    )


def fit_final_calibrator(
    method: str,
    probabilities: np.ndarray,
    actual: np.ndarray,
    sample_weight: np.ndarray,
) -> object | None:
    if method == "none":
        return None

    if method == "platt":
        return fit_platt_calibrator(
            probabilities,
            actual,
            sample_weight,
        )

    if method == "isotonic":
        return fit_isotonic_calibrator(
            probabilities,
            actual,
            sample_weight,
        )

    raise ValueError(
        f"Unknown calibration method: {method}"
    )


def apply_final_calibrator(
    calibrator: object | None,
    method: str,
    probabilities: np.ndarray,
) -> np.ndarray:
    if method == "none":
        return probabilities

    if method == "platt":
        if not isinstance(
            calibrator,
            LogisticRegression,
        ):
            raise TypeError(
                "The Platt calibrator is invalid."
            )

        return apply_platt_calibrator(
            calibrator,
            probabilities,
        )

    if method == "isotonic":
        if not isinstance(
            calibrator,
            IsotonicRegression,
        ):
            raise TypeError(
                "The isotonic calibrator is invalid."
            )

        return calibrator.predict(
            probabilities
        )

    raise ValueError(
        f"Unknown calibration method: {method}"
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
    print("NEXT-SEASON SURVIVAL PROBABILITY MODEL")
    print("=" * 80)
    print(
        f"Training rows: {len(frame):,}"
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
        "Rolling validation seasons: "
        + ", ".join(
            ROLLING_VALIDATION_CURRENT_SEASONS
        )
    )
    print()

    rolling = build_rolling_predictions(
        frame=frame,
        features=features,
    )

    (
        selected,
        rolling_results,
        prediction_cache,
    ) = select_best_approach(
        rolling
    )

    print()
    print(
        "Best rolling model: "
        f"{selected.model_name}"
    )
    print(
        "Calibration method: "
        f"{selected.calibration_method}"
    )
    print(
        "Model blend weight: "
        f"{selected.model_weight:.2f}"
    )
    print(
        "Rolling weighted Brier score: "
        f"{selected.weighted_brier:.5f}"
    )

    factories = candidate_factories()

    if selected.model_name == "baseline_only":
        final_model = None
        raw_test_probabilities = np.full(
            len(test),
            development[
                "next_season_active_flag"
            ].mean(),
            dtype=float,
        )

        final_calibrator = None

    else:
        final_model = (
            factories[
                selected.model_name
            ]()
        )

        final_model = fit_model(
            model=final_model,
            X=development[features],
            y=development[
                "next_season_active_flag"
            ].astype(int),
        )

        raw_test_probabilities = (
            final_model.predict_proba(
                test[features]
            )[:, 1]
        )

        raw_oof_probabilities = rolling[
            f"raw__{selected.model_name}"
        ].to_numpy(dtype=float)

        final_calibrator = (
            fit_final_calibrator(
                method=(
                    selected.calibration_method
                ),
                probabilities=(
                    raw_oof_probabilities
                ),
                actual=rolling[
                    "actual"
                ].to_numpy(dtype=int),
                sample_weight=rolling[
                    "sample_weight"
                ].to_numpy(dtype=float),
            )
        )

    calibrated_test_probabilities = (
        apply_final_calibrator(
            calibrator=final_calibrator,
            method=(
                selected.calibration_method
            ),
            probabilities=(
                raw_test_probabilities
            ),
        )
    )

    baseline_probability = float(
        development[
            "next_season_active_flag"
        ].mean()
    )

    final_test_probabilities = (
        selected.model_weight
        * calibrated_test_probabilities
        + (1.0 - selected.model_weight)
        * baseline_probability
    )

    final_test_probabilities = np.clip(
        final_test_probabilities,
        0.001,
        0.999,
    )

    test_actual = test[
        "next_season_active_flag"
    ].to_numpy(dtype=int)

    test_weights = np.ones(
        len(test),
        dtype=float,
    )

    test_metrics = (
        classification_metrics(
            actual=test_actual,
            probabilities=(
                final_test_probabilities
            ),
            sample_weight=test_weights,
        )
    )

    baseline_test_probabilities = np.full(
        len(test),
        baseline_probability,
        dtype=float,
    )

    baseline_metrics = (
        classification_metrics(
            actual=test_actual,
            probabilities=(
                baseline_test_probabilities
            ),
            sample_weight=test_weights,
        )
    )

    print(
        "Test baseline Brier score: "
        f"{baseline_metrics['weighted_brier']:.5f}"
    )
    print(
        "Test selected Brier score: "
        f"{test_metrics['weighted_brier']:.5f}"
    )
    print(
        "Test Brier improvement: "
        f"{baseline_metrics['weighted_brier'] - test_metrics['weighted_brier']:.5f}"
    )
    print(
        "Test ROC AUC: "
        f"{test_metrics['roc_auc']:.4f}"
    )
    print(
        "Test average precision: "
        f"{test_metrics['average_precision']:.4f}"
    )
    print(
        "Test calibration error: "
        f"{test_metrics['ece_10_bin']:.4f}"
    )

    model_bundle = {
        "model": final_model,
        "calibrator": final_calibrator,
        "model_name": selected.model_name,
        "calibration_method": (
            selected.calibration_method
        ),
        "model_weight": (
            selected.model_weight
        ),
        "baseline_probability": (
            baseline_probability
        ),
        "features": features,
        "probability_lower": 0.001,
        "probability_upper": 0.999,
    }

    joblib.dump(
        model_bundle,
        MODEL_PATH,
    )

    rolling_output = rolling.copy()

    if selected.model_name != "baseline_only":
        selected_cache_key = (
            f"{selected.model_name}__"
            f"{selected.calibration_method}"
        )

        selected_rolling_probabilities = (
            prediction_cache[
                selected_cache_key
            ]
        )

        rolling_output[
            "selected_probability"
        ] = (
            selected.model_weight
            * selected_rolling_probabilities
            + (1.0 - selected.model_weight)
            * rolling_output[
                "baseline_probability"
            ].to_numpy(dtype=float)
        )

    else:
        rolling_output[
            "selected_probability"
        ] = rolling_output[
            "baseline_probability"
        ]

    test_predictions = test[
        [
            "player_id",
            "player_name",
            "season",
            "target_season",
            "team_abbreviation",
            "minutes_per_game",
            "total_minutes",
            "rotation_player_flag",
            "next_season_active_flag",
        ]
    ].copy()

    test_predictions[
        "projected_survival_probability"
    ] = final_test_probabilities

    test_predictions[
        "baseline_survival_probability"
    ] = baseline_test_probabilities

    test_metrics_frame = pd.DataFrame(
        [
            {
                "model_name": (
                    selected.model_name
                ),
                "calibration_method": (
                    selected.calibration_method
                ),
                "model_weight": (
                    selected.model_weight
                ),
                **test_metrics,
                "baseline_brier": (
                    baseline_metrics[
                        "weighted_brier"
                    ]
                ),
                "brier_improvement": (
                    baseline_metrics[
                        "weighted_brier"
                    ]
                    - test_metrics[
                        "weighted_brier"
                    ]
                ),
            }
        ]
    )

    metadata = {
        "input_path": str(INPUT_PATH),
        "feature_count": len(features),
        "features": features,
        "development_rows": len(development),
        "test_rows": len(test),
        "selected_model": (
            selected.model_name
        ),
        "calibration_method": (
            selected.calibration_method
        ),
        "model_weight": (
            selected.model_weight
        ),
        "rolling_weighted_brier": (
            selected.weighted_brier
        ),
        "test_metrics": test_metrics,
        "baseline_test_metrics": (
            baseline_metrics
        ),
        "model_path": str(MODEL_PATH),
    }

    rolling_results.to_csv(
        ROLLING_RESULTS_PATH,
        index=False,
    )

    rolling_output.to_csv(
        ROLLING_PREDICTIONS_PATH,
        index=False,
    )

    test_metrics_frame.to_csv(
        TEST_METRICS_PATH,
        index=False,
    )

    test_predictions.to_csv(
        TEST_PREDICTIONS_PATH,
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
    print("SURVIVAL MODELING COMPLETED")
    print("=" * 80)
    print(MODEL_PATH)
    print(METADATA_PATH)
    print(ROLLING_RESULTS_PATH)
    print(ROLLING_PREDICTIONS_PATH)
    print(TEST_METRICS_PATH)
    print(TEST_PREDICTIONS_PATH)


if __name__ == "__main__":
    main()