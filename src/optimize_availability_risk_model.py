from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
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

SOURCE_DATA_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "survival_aware_projection_training_data.parquet"
)

ROLLING_COMPONENTS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "expected_contribution_rolling_predictions.csv"
)

TEST_COMPONENTS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "expected_contribution_test_predictions.csv"
)

MODELS_DIRECTORY = PROJECT_ROOT / "models"
OUTPUT_DIRECTORY = (
    PROJECT_ROOT
    / "outputs"
    / "availability_risk_optimization"
)

MODEL_PATH = (
    MODELS_DIRECTORY
    / "availability_risk_adjusted_contribution_model.joblib"
)

METADATA_PATH = (
    MODELS_DIRECTORY
    / "availability_risk_adjusted_contribution_metadata.json"
)

ROLLING_RESULTS_PATH = (
    OUTPUT_DIRECTORY
    / "rolling_model_selection.csv"
)

ROLLING_PREDICTIONS_PATH = (
    OUTPUT_DIRECTORY
    / "rolling_predictions.csv"
)

TEST_METRICS_PATH = (
    OUTPUT_DIRECTORY
    / "confirmation_metrics.csv"
)

TEST_PREDICTIONS_PATH = (
    OUTPUT_DIRECTORY
    / "confirmation_predictions.csv"
)

WORKLOAD_METRICS_PATH = (
    OUTPUT_DIRECTORY
    / "confirmation_metrics_by_workload.csv"
)


RANDOM_STATE = 42

FINAL_CONFIRMATION_SEASON = "2024-25"

ROLLING_VALIDATION_SEASONS = [
    "2018-19",
    "2019-20",
    "2020-21",
    "2021-22",
    "2022-23",
    "2023-24",
]

TARGET_AVAILABILITY = (
    "next_expected_availability_rate"
)

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
    "model_sample_weight",
}

WORKLOAD_BINS = [
    -np.inf,
    8.0,
    12.0,
    20.0,
    28.0,
    34.0,
    np.inf,
]

WORKLOAD_LABELS = [
    "Under 8 MPG",
    "8-11.9 MPG",
    "12-19.9 MPG",
    "20-27.9 MPG",
    "28-33.9 MPG",
    "34+ MPG",
]

BLEND_STEP = 0.25


def make_ridge() -> Pipeline:
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
                Ridge(alpha=40.0),
            ),
        ]
    )


def make_random_forest() -> Pipeline:
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
                    max_depth=10,
                    min_samples_leaf=8,
                    max_features=0.60,
                    n_jobs=-1,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def make_extra_trees() -> Pipeline:
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
                    max_depth=12,
                    min_samples_leaf=6,
                    max_features=0.65,
                    n_jobs=-1,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def make_hgb_absolute() -> Pipeline:
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


def make_hgb_squared() -> Pipeline:
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
                    loss="squared_error",
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


def make_survival_classifier() -> Pipeline:
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


def make_regime_classifier() -> Pipeline:
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
                    max_iter=350,
                    max_leaf_nodes=15,
                    min_samples_leaf=25,
                    l2_regularization=4.0,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def fit_native_regressor(
    model: Pipeline,
    X: pd.DataFrame,
    y: pd.Series,
    weights: pd.Series,
) -> dict[str, Any]:
    model.fit(
        X,
        y,
        model__sample_weight=weights,
    )

    return {
        "kind": "native_regressor",
        "model": model,
    }


def fit_survival_conditional(
    train: pd.DataFrame,
    features: list[str],
) -> dict[str, Any]:
    X = train[features]

    survival = make_survival_classifier()

    survival.fit(
        X,
        train[
            "next_season_active_flag"
        ].astype(int),
        model__sample_weight=np.ones(
            len(train),
            dtype=float,
        ),
    )

    active = train.loc[
        train[
            "next_season_active_flag"
        ].eq(1)
    ].copy()

    conditional = make_hgb_squared()

    conditional.fit(
        active[features],
        active[
            "next_availability_rate_if_active"
        ].astype(float),
        model__sample_weight=active[
            "model_sample_weight"
        ],
    )

    return {
        "kind": "survival_conditional",
        "survival_model": survival,
        "conditional_model": conditional,
    }


def fit_regime_model(
    train: pd.DataFrame,
    features: list[str],
    threshold: float,
) -> dict[str, Any]:
    X = train[features]

    target = train[
        TARGET_AVAILABILITY
    ].astype(float)

    high_flag = (
        target >= threshold
    ).astype(int)

    classifier = make_regime_classifier()

    classifier.fit(
        X,
        high_flag,
        model__sample_weight=train[
            "model_sample_weight"
        ],
    )

    low_mask = high_flag.eq(0)
    high_mask = high_flag.eq(1)

    low_model = make_hgb_squared()
    high_model = make_hgb_squared()

    low_model.fit(
        X.loc[low_mask],
        target.loc[low_mask],
        model__sample_weight=train.loc[
            low_mask,
            "model_sample_weight",
        ],
    )

    high_model.fit(
        X.loc[high_mask],
        target.loc[high_mask],
        model__sample_weight=train.loc[
            high_mask,
            "model_sample_weight",
        ],
    )

    return {
        "kind": "regime_model",
        "threshold": threshold,
        "classifier": classifier,
        "low_model": low_model,
        "high_model": high_model,
    }


def fit_candidate(
    name: str,
    train: pd.DataFrame,
    features: list[str],
) -> dict[str, Any]:
    native_factories: dict[
        str,
        Callable[[], Pipeline],
    ] = {
        "ridge": make_ridge,
        "random_forest": make_random_forest,
        "extra_trees": make_extra_trees,
        "hgb_absolute": make_hgb_absolute,
        "hgb_squared": make_hgb_squared,
    }

    if name in native_factories:
        return fit_native_regressor(
            model=native_factories[name](),
            X=train[features],
            y=train[
                TARGET_AVAILABILITY
            ].astype(float),
            weights=train[
                "model_sample_weight"
            ],
        )

    if name == "survival_conditional":
        return fit_survival_conditional(
            train=train,
            features=features,
        )

    if name == "regime_050":
        return fit_regime_model(
            train=train,
            features=features,
            threshold=0.50,
        )

    if name == "regime_075":
        return fit_regime_model(
            train=train,
            features=features,
            threshold=0.75,
        )

    raise ValueError(
        f"Unknown availability candidate: {name}"
    )


def predict_candidate(
    bundle: dict[str, Any],
    frame: pd.DataFrame,
    features: list[str],
) -> np.ndarray:
    X = frame[features]
    kind = str(bundle["kind"])

    if kind == "native_regressor":
        prediction = bundle[
            "model"
        ].predict(X)

    elif kind == "survival_conditional":
        active_probability = bundle[
            "survival_model"
        ].predict_proba(X)[:, 1]

        conditional_availability = bundle[
            "conditional_model"
        ].predict(X)

        prediction = (
            active_probability
            * conditional_availability
        )

    elif kind == "regime_model":
        high_probability = bundle[
            "classifier"
        ].predict_proba(X)[:, 1]

        low_prediction = bundle[
            "low_model"
        ].predict(X)

        high_prediction = bundle[
            "high_model"
        ].predict(X)

        prediction = (
            high_probability
            * high_prediction
            + (1.0 - high_probability)
            * low_prediction
        )

    else:
        raise ValueError(
            f"Unknown model bundle kind: {kind}"
        )

    return np.clip(
        np.asarray(
            prediction,
            dtype=float,
        ),
        0.0,
        1.0,
    )


def load_source_data() -> pd.DataFrame:
    if not SOURCE_DATA_PATH.exists():
        raise FileNotFoundError(
            "The survival-aware training data was not found at:\n"
            f"{SOURCE_DATA_PATH}"
        )

    frame = pd.read_parquet(
        SOURCE_DATA_PATH
    )

    required = {
        "player_id",
        "player_name",
        "season",
        "season_start",
        "target_season",
        "minutes_per_game",
        "next_season_active_flag",
        "next_expected_availability_rate",
        "next_availability_rate_if_active",
        "next_total_impact_value",
        "sample_reliability",
    }

    missing = sorted(
        required.difference(
            frame.columns
        )
    )

    if missing:
        raise ValueError(
            "The source data is missing columns:\n"
            + "\n".join(missing)
        )

    frame = frame.copy()

    frame["model_sample_weight"] = (
        0.50
        + 0.50
        * pd.to_numeric(
            frame[
                "sample_reliability"
            ],
            errors="coerce",
        )
        .fillna(0.0)
        .clip(
            lower=0.0,
            upper=1.0,
        )
    )

    return frame


def select_features(
    frame: pd.DataFrame,
) -> list[str]:
    development = frame.loc[
        frame["season"].ne(
            FINAL_CONFIRMATION_SEASON
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
            "No usable numeric features were found."
        )

    return sorted(features)


def merge_components(
    source: pd.DataFrame,
    components: pd.DataFrame,
    rolling: bool,
) -> pd.DataFrame:
    if rolling:
        required = {
            "player_id",
            "season",
            "actual",
            "sample_weight",
            "staged_prediction",
            "staged_conditional_minutes_per_game",
            "staged_conditional_pie",
            "staged_target_schedule_games",
            "direct__hist_gradient_boosting",
        }

        missing = sorted(
            required.difference(
                components.columns
            )
        )

        if missing:
            raise ValueError(
                "Rolling components are missing columns:\n"
                + "\n".join(missing)
            )

        selected_columns = [
            "player_id",
            "season",
            "actual",
            "sample_weight",
            "staged_prediction",
            "staged_conditional_minutes_per_game",
            "staged_conditional_pie",
            "staged_target_schedule_games",
            "direct__hist_gradient_boosting",
        ]

    else:
        required = {
            "player_id",
            "season",
            "actual_total_impact_value",
            "model_sample_weight",
            "projected_staged_total_impact",
            "projected_conditional_minutes_per_game",
            "projected_conditional_pie",
            "projected_target_schedule_games",
            "projected_direct_total_impact",
            "projected_final_total_impact",
        }

        missing = sorted(
            required.difference(
                components.columns
            )
        )

        if missing:
            raise ValueError(
                "Confirmation components are missing columns:\n"
                + "\n".join(missing)
            )

        selected_columns = [
            "player_id",
            "season",
            "actual_total_impact_value",
            "model_sample_weight",
            "projected_staged_total_impact",
            "projected_conditional_minutes_per_game",
            "projected_conditional_pie",
            "projected_target_schedule_games",
            "projected_direct_total_impact",
            "projected_final_total_impact",
        ]

    source_columns = [
        "player_id",
        "player_name",
        "season",
        "season_start",
        "target_season",
        "team_abbreviation",
        "age",
        "minutes_per_game",
        "rotation_player_flag",
        "next_season_active_flag",
        "next_rotation_player_flag",
        TARGET_AVAILABILITY,
        "next_total_impact_value",
        "model_sample_weight",
    ]

    output = source.merge(
        components[selected_columns],
        how="inner",
        on=[
            "player_id",
            "season",
        ],
        validate="one_to_one",
        suffixes=(
            "",
            "_component",
        ),
    )

    if rolling:
        output["actual_contribution"] = (
            output["actual"]
        )

        output["contribution_weight"] = (
            output["sample_weight"]
        )

        output["old_staged"] = (
            output[
                "staged_prediction"
            ]
        )

        output["conditional_minutes"] = (
            output[
                "staged_conditional_minutes_per_game"
            ]
        )

        output["conditional_pie"] = (
            output[
                "staged_conditional_pie"
            ]
        )

        output["schedule_games"] = (
            output[
                "staged_target_schedule_games"
            ]
        )

        output["direct_prediction"] = (
            output[
                "direct__hist_gradient_boosting"
            ]
        )

        output["original_final"] = (
            0.75
            * output["old_staged"]
            + 0.25
            * output[
                "direct_prediction"
            ]
        )

    else:
        output["actual_contribution"] = (
            output[
                "actual_total_impact_value"
            ]
        )

        output["contribution_weight"] = (
            output[
                "model_sample_weight_component"
            ]
        )

        output["old_staged"] = (
            output[
                "projected_staged_total_impact"
            ]
        )

        output["conditional_minutes"] = (
            output[
                "projected_conditional_minutes_per_game"
            ]
        )

        output["conditional_pie"] = (
            output[
                "projected_conditional_pie"
            ]
        )

        output["schedule_games"] = (
            output[
                "projected_target_schedule_games"
            ]
        )

        output["direct_prediction"] = (
            output[
                "projected_direct_total_impact"
            ]
        )

        output["original_final"] = (
            output[
                "projected_final_total_impact"
            ]
        )

    output[
        "current_minutes_group"
    ] = pd.cut(
        output["minutes_per_game"],
        bins=WORKLOAD_BINS,
        labels=WORKLOAD_LABELS,
        right=False,
        include_lowest=True,
    ).astype(str)

    return output


def safe_spearman(
    actual: np.ndarray,
    predicted: np.ndarray,
) -> float:
    if len(actual) < 3:
        return np.nan

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


def metrics(
    actual: np.ndarray,
    prediction: np.ndarray,
    weights: np.ndarray,
) -> dict[str, float]:
    return {
        "weighted_mae": float(
            mean_absolute_error(
                actual,
                prediction,
                sample_weight=weights,
            )
        ),
        "mae": float(
            mean_absolute_error(
                actual,
                prediction,
            )
        ),
        "weighted_rmse": float(
            np.sqrt(
                np.average(
                    (
                        prediction
                        - actual
                    )
                    ** 2,
                    weights=weights,
                )
            )
        ),
        "rmse": float(
            mean_squared_error(
                actual,
                prediction,
            )
            ** 0.5
        ),
        "weighted_bias": float(
            np.average(
                prediction - actual,
                weights=weights,
            )
        ),
        "r_squared": float(
            r2_score(
                actual,
                prediction,
                sample_weight=weights,
            )
        ),
        "spearman": safe_spearman(
            actual,
            prediction,
        ),
    }


def blend_grid() -> list[
    tuple[float, float, float]
]:
    values = np.arange(
        0.0,
        1.0 + BLEND_STEP / 2.0,
        BLEND_STEP,
    )

    combinations: list[
        tuple[float, float, float]
    ] = []

    for new_staged_weight in values:
        for old_staged_weight in values:
            direct_weight = (
                1.0
                - new_staged_weight
                - old_staged_weight
            )

            if direct_weight < -1e-9:
                continue

            direct_weight = max(
                direct_weight,
                0.0,
            )

            combinations.append(
                (
                    float(
                        new_staged_weight
                    ),
                    float(
                        old_staged_weight
                    ),
                    float(
                        direct_weight
                    ),
                )
            )

    return combinations


def build_rolling_predictions(
    source: pd.DataFrame,
    features: list[str],
    merged_rolling: pd.DataFrame,
) -> pd.DataFrame:
    candidate_names = [
        "ridge",
        "random_forest",
        "extra_trees",
        "hgb_absolute",
        "hgb_squared",
        "survival_conditional",
        "regime_050",
        "regime_075",
    ]

    outputs: list[pd.DataFrame] = []

    for validation_season in (
        ROLLING_VALIDATION_SEASONS
    ):
        validation_start = int(
            validation_season[:4]
        )

        train = source.loc[
            source["season_start"]
            < validation_start
        ].copy()

        validation = source.loc[
            source["season"].eq(
                validation_season
            )
        ].copy()

        fold_components = (
            merged_rolling.loc[
                merged_rolling[
                    "season"
                ].eq(
                    validation_season
                )
            ]
            .copy()
        )

        if (
            train.empty
            or validation.empty
            or fold_components.empty
        ):
            raise ValueError(
                "An empty rolling fold was found for "
                f"{validation_season}."
            )

        fold = fold_components[
            [
                "player_id",
                "player_name",
                "season",
                "target_season",
                "team_abbreviation",
                "age",
                "minutes_per_game",
                "current_minutes_group",
                "next_season_active_flag",
                "actual_contribution",
                "contribution_weight",
                "old_staged",
                "direct_prediction",
                "original_final",
                "conditional_minutes",
                "conditional_pie",
                "schedule_games",
            ]
        ].copy()

        validation_lookup = validation.set_index(
            [
                "player_id",
                "season",
            ]
        )

        component_index = pd.MultiIndex.from_frame(
            fold[
                [
                    "player_id",
                    "season",
                ]
            ]
        )

        validation_ordered = (
            validation_lookup.loc[
                component_index
            ]
            .reset_index()
        )

        for candidate_name in candidate_names:
            print(
                f"{validation_season}: fitting "
                f"{candidate_name}..."
            )

            bundle = fit_candidate(
                name=candidate_name,
                train=train,
                features=features,
            )

            availability_prediction = (
                predict_candidate(
                    bundle=bundle,
                    frame=validation_ordered,
                    features=features,
                )
            )

            new_staged = (
                availability_prediction
                * fold[
                    "conditional_minutes"
                ].to_numpy(dtype=float)
                * fold[
                    "conditional_pie"
                ].to_numpy(dtype=float)
                * fold[
                    "schedule_games"
                ].to_numpy(dtype=float)
            )

            fold[
                f"availability__{candidate_name}"
            ] = availability_prediction

            fold[
                f"new_staged__{candidate_name}"
            ] = new_staged

        outputs.append(fold)

    return pd.concat(
        outputs,
        ignore_index=True,
    )


def select_best_configuration(
    rolling: pd.DataFrame,
) -> pd.DataFrame:
    actual = rolling[
        "actual_contribution"
    ].to_numpy(dtype=float)

    weights = rolling[
        "contribution_weight"
    ].to_numpy(dtype=float)

    old_staged = rolling[
        "old_staged"
    ].to_numpy(dtype=float)

    direct = rolling[
        "direct_prediction"
    ].to_numpy(dtype=float)

    rows: list[dict[str, object]] = []

    candidate_columns = [
        column
        for column in rolling.columns
        if column.startswith(
            "new_staged__"
        )
    ]

    for column in candidate_columns:
        candidate_name = column.replace(
            "new_staged__",
            "",
        )

        new_staged = rolling[
            column
        ].to_numpy(dtype=float)

        for (
            new_weight,
            old_weight,
            direct_weight,
        ) in blend_grid():
            prediction = (
                new_weight * new_staged
                + old_weight * old_staged
                + direct_weight * direct
            )

            result = metrics(
                actual=actual,
                prediction=prediction,
                weights=weights,
            )

            rows.append(
                {
                    "availability_model": (
                        candidate_name
                    ),
                    "new_staged_weight": (
                        new_weight
                    ),
                    "old_staged_weight": (
                        old_weight
                    ),
                    "direct_weight": (
                        direct_weight
                    ),
                    **result,
                }
            )

    return (
        pd.DataFrame(rows)
        .sort_values(
            [
                "weighted_mae",
                "weighted_rmse",
            ],
            ascending=True,
        )
        .reset_index(drop=True)
    )


def grouped_metrics(
    frame: pd.DataFrame,
    prediction_column: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    for group_name, group in frame.groupby(
        "current_minutes_group",
        dropna=False,
    ):
        result = metrics(
            actual=group[
                "actual_contribution"
            ].to_numpy(dtype=float),
            prediction=group[
                prediction_column
            ].to_numpy(dtype=float),
            weights=group[
                "contribution_weight"
            ].to_numpy(dtype=float),
        )

        rows.append(
            {
                "current_minutes_group": (
                    str(group_name)
                ),
                "rows": len(group),
                **result,
            }
        )

    return pd.DataFrame(rows)


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    MODELS_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    for path in [
        SOURCE_DATA_PATH,
        ROLLING_COMPONENTS_PATH,
        TEST_COMPONENTS_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required file not found:\n{path}"
            )

    source = load_source_data()

    features = select_features(
        source
    )

    rolling_components = pd.read_csv(
        ROLLING_COMPONENTS_PATH
    )

    test_components = pd.read_csv(
        TEST_COMPONENTS_PATH
    )

    merged_rolling = merge_components(
        source=source,
        components=rolling_components,
        rolling=True,
    )

    merged_test = merge_components(
        source=source,
        components=test_components,
        rolling=False,
    )

    development = source.loc[
        source["season"].ne(
            FINAL_CONFIRMATION_SEASON
        )
    ].copy()

    confirmation = source.loc[
        source["season"].eq(
            FINAL_CONFIRMATION_SEASON
        )
    ].copy()

    print("=" * 80)
    print("AVAILABILITY-RISK CONTRIBUTION OPTIMIZATION")
    print("=" * 80)
    print(
        f"Source rows: {len(source):,}"
    )
    print(
        f"Features used: {len(features):,}"
    )
    print(
        "The new availability target includes "
        "zero for players who miss the entire next season."
    )
    print(
        "Model selection is based on final contribution MAE, "
        "not availability MAE alone."
    )
    print()

    rolling = build_rolling_predictions(
        source=source,
        features=features,
        merged_rolling=merged_rolling,
    )

    selection = (
        select_best_configuration(
            rolling
        )
    )

    best = selection.iloc[0]

    selected_model_name = str(
        best["availability_model"]
    )

    new_weight = float(
        best["new_staged_weight"]
    )

    old_weight = float(
        best["old_staged_weight"]
    )

    direct_weight = float(
        best["direct_weight"]
    )

    print()
    print("=" * 80)
    print("BEST ROLLING CONFIGURATION")
    print("=" * 80)
    print(
        "Availability model: "
        f"{selected_model_name}"
    )
    print(
        "New risk-adjusted staged weight: "
        f"{new_weight:.2f}"
    )
    print(
        "Original staged weight: "
        f"{old_weight:.2f}"
    )
    print(
        "Direct contribution weight: "
        f"{direct_weight:.2f}"
    )
    print(
        "Rolling weighted MAE: "
        f"{best['weighted_mae']:.5f}"
    )

    print()
    print(
        "Retraining selected availability model "
        "on all development seasons..."
    )

    final_bundle = fit_candidate(
        name=selected_model_name,
        train=development,
        features=features,
    )

    confirmation_lookup = (
        confirmation.set_index(
            [
                "player_id",
                "season",
            ]
        )
    )

    test_index = pd.MultiIndex.from_frame(
        merged_test[
            [
                "player_id",
                "season",
            ]
        ]
    )

    confirmation_ordered = (
        confirmation_lookup.loc[
            test_index
        ]
        .reset_index()
    )

    availability_prediction = (
        predict_candidate(
            bundle=final_bundle,
            frame=confirmation_ordered,
            features=features,
        )
    )

    merged_test[
        "projected_unconditional_availability"
    ] = availability_prediction

    merged_test[
        "risk_adjusted_staged_prediction"
    ] = (
        availability_prediction
        * merged_test[
            "conditional_minutes"
        ].to_numpy(dtype=float)
        * merged_test[
            "conditional_pie"
        ].to_numpy(dtype=float)
        * merged_test[
            "schedule_games"
        ].to_numpy(dtype=float)
    )

    merged_test[
        "risk_adjusted_final_prediction"
    ] = (
        new_weight
        * merged_test[
            "risk_adjusted_staged_prediction"
        ]
        + old_weight
        * merged_test[
            "old_staged"
        ]
        + direct_weight
        * merged_test[
            "direct_prediction"
        ]
    )

    actual = merged_test[
        "actual_contribution"
    ].to_numpy(dtype=float)

    weights = merged_test[
        "contribution_weight"
    ].to_numpy(dtype=float)

    original_metrics = metrics(
        actual=actual,
        prediction=merged_test[
            "original_final"
        ].to_numpy(dtype=float),
        weights=weights,
    )

    risk_metrics = metrics(
        actual=actual,
        prediction=merged_test[
            "risk_adjusted_final_prediction"
        ].to_numpy(dtype=float),
        weights=weights,
    )

    new_staged_metrics = metrics(
        actual=actual,
        prediction=merged_test[
            "risk_adjusted_staged_prediction"
        ].to_numpy(dtype=float),
        weights=weights,
    )

    print()
    print("=" * 80)
    print("CONFIRMATION-SEASON RESULTS")
    print("=" * 80)
    print(
        "Original final weighted MAE: "
        f"{original_metrics['weighted_mae']:.5f}"
    )
    print(
        "Risk-adjusted weighted MAE: "
        f"{risk_metrics['weighted_mae']:.5f}"
    )
    print(
        "MAE improvement: "
        f"{original_metrics['weighted_mae'] - risk_metrics['weighted_mae']:.5f}"
    )
    print(
        "Original weighted bias: "
        f"{original_metrics['weighted_bias']:.5f}"
    )
    print(
        "Risk-adjusted weighted bias: "
        f"{risk_metrics['weighted_bias']:.5f}"
    )
    print(
        "Risk-adjusted R-squared: "
        f"{risk_metrics['r_squared']:.4f}"
    )
    print(
        "Risk-adjusted Spearman: "
        f"{risk_metrics['spearman']:.4f}"
    )

    rolling.to_csv(
        ROLLING_PREDICTIONS_PATH,
        index=False,
    )

    selection.to_csv(
        ROLLING_RESULTS_PATH,
        index=False,
    )

    confirmation_columns = [
        "player_id",
        "player_name",
        "season",
        "target_season",
        "team_abbreviation",
        "age",
        "minutes_per_game",
        "current_minutes_group",
        "next_season_active_flag",
        TARGET_AVAILABILITY,
        "actual_contribution",
        "original_final",
        "projected_unconditional_availability",
        "risk_adjusted_staged_prediction",
        "risk_adjusted_final_prediction",
        "conditional_minutes",
        "conditional_pie",
        "schedule_games",
        "contribution_weight",
    ]

    merged_test[
        confirmation_columns
    ].to_csv(
        TEST_PREDICTIONS_PATH,
        index=False,
    )

    metric_rows = [
        {
            "approach": "original_final",
            **original_metrics,
        },
        {
            "approach": (
                "risk_adjusted_staged_only"
            ),
            **new_staged_metrics,
        },
        {
            "approach": (
                "risk_adjusted_final"
            ),
            **risk_metrics,
        },
    ]

    pd.DataFrame(
        metric_rows
    ).to_csv(
        TEST_METRICS_PATH,
        index=False,
    )

    workload_metrics = grouped_metrics(
        merged_test,
        "risk_adjusted_final_prediction",
    )

    workload_metrics.to_csv(
        WORKLOAD_METRICS_PATH,
        index=False,
    )

    model_bundle = {
        "availability_model_name": (
            selected_model_name
        ),
        "availability_model": (
            final_bundle
        ),
        "features": features,
        "new_risk_adjusted_staged_weight": (
            new_weight
        ),
        "original_staged_weight": (
            old_weight
        ),
        "direct_contribution_weight": (
            direct_weight
        ),
        "target": TARGET_AVAILABILITY,
    }

    joblib.dump(
        model_bundle,
        MODEL_PATH,
    )

    metadata = {
        "availability_model_name": (
            selected_model_name
        ),
        "feature_count": len(features),
        "new_risk_adjusted_staged_weight": (
            new_weight
        ),
        "original_staged_weight": (
            old_weight
        ),
        "direct_contribution_weight": (
            direct_weight
        ),
        "rolling_weighted_mae": float(
            best["weighted_mae"]
        ),
        "confirmation_metrics": {
            "original": original_metrics,
            "risk_adjusted": risk_metrics,
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
    print("AVAILABILITY-RISK OPTIMIZATION COMPLETED")
    print("=" * 80)
    print(ROLLING_RESULTS_PATH)
    print(ROLLING_PREDICTIONS_PATH)
    print(TEST_METRICS_PATH)
    print(TEST_PREDICTIONS_PATH)
    print(WORKLOAD_METRICS_PATH)
    print(MODEL_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()
