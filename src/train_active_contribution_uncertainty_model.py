from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import Pipeline


PROJECT_ROOT = Path(__file__).resolve().parents[1]

TRAINING_DATA_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "survival_aware_projection_training_data.parquet"
)

MODELS_DIRECTORY = PROJECT_ROOT / "models"

OUTPUT_DIRECTORY = (
    PROJECT_ROOT
    / "outputs"
    / "active_contribution_uncertainty"
)

MODEL_PATH = (
    MODELS_DIRECTORY
    / "active_contribution_uncertainty_model.joblib"
)

METADATA_PATH = (
    MODELS_DIRECTORY
    / "active_contribution_uncertainty_metadata.json"
)

ROLLING_PREDICTIONS_PATH = (
    OUTPUT_DIRECTORY
    / "rolling_quantile_predictions.csv"
)

ROLLING_METRICS_PATH = (
    OUTPUT_DIRECTORY
    / "rolling_interval_metrics.csv"
)

CONFIRMATION_PREDICTIONS_PATH = (
    OUTPUT_DIRECTORY
    / "confirmation_interval_predictions.csv"
)

CONFIRMATION_METRICS_PATH = (
    OUTPUT_DIRECTORY
    / "confirmation_interval_metrics.csv"
)


RANDOM_STATE = 42

TARGET_COLUMN = "next_total_impact_value"
ACTIVE_FLAG_COLUMN = "next_season_active_flag"

FINAL_CONFIRMATION_SEASON = "2024-25"

ROLLING_VALIDATION_SEASONS = [
    "2018-19",
    "2019-20",
    "2020-21",
    "2021-22",
    "2022-23",
    "2023-24",
]

QUANTILES = [
    0.05,
    0.10,
    0.50,
    0.90,
    0.95,
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
    "model_sample_weight",
}


def make_quantile_model(
    quantile: float,
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
                "model",
                HistGradientBoostingRegressor(
                    loss="quantile",
                    quantile=quantile,
                    learning_rate=0.035,
                    max_iter=450,
                    max_leaf_nodes=15,
                    min_samples_leaf=25,
                    l2_regularization=4.0,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def load_active_data() -> pd.DataFrame:
    if not TRAINING_DATA_PATH.exists():
        raise FileNotFoundError(
            "The survival-aware training data was not found at:\n"
            f"{TRAINING_DATA_PATH}"
        )

    frame = pd.read_parquet(
        TRAINING_DATA_PATH
    )

    if frame.empty:
        raise ValueError(
            "The survival-aware training data is empty."
        )

    required = {
        "player_id",
        "player_name",
        "season",
        "target_season",
        "season_start",
        "team_abbreviation",
        "sample_reliability",
        ACTIVE_FLAG_COLUMN,
        TARGET_COLUMN,
    }

    missing = sorted(
        required.difference(frame.columns)
    )

    if missing:
        raise ValueError(
            "The training data is missing required columns:\n"
            + "\n".join(missing)
        )

    frame = frame.copy()

    frame["season_start"] = pd.to_numeric(
        frame["season_start"],
        errors="raise",
    ).astype(int)

    active_flag = pd.to_numeric(
        frame[ACTIVE_FLAG_COLUMN],
        errors="coerce",
    )

    frame = frame.loc[
        active_flag.eq(1)
    ].copy()

    if frame.empty:
        raise ValueError(
            "No active next-season rows were found."
        )

    frame[TARGET_COLUMN] = pd.to_numeric(
        frame[TARGET_COLUMN],
        errors="coerce",
    )

    frame = frame.dropna(
        subset=[TARGET_COLUMN]
    ).copy()

    if (
        "conditional_training_sample_weight"
        in frame.columns
    ):
        weights = pd.to_numeric(
            frame[
                "conditional_training_sample_weight"
            ],
            errors="coerce",
        )
    elif "training_sample_weight" in frame.columns:
        weights = pd.to_numeric(
            frame["training_sample_weight"],
            errors="coerce",
        )
    else:
        reliability = pd.to_numeric(
            frame["sample_reliability"],
            errors="coerce",
        ).fillna(0.0).clip(
            lower=0.0,
            upper=1.0,
        )

        weights = 0.25 + 0.75 * reliability

    fallback_reliability = pd.to_numeric(
        frame["sample_reliability"],
        errors="coerce",
    ).fillna(0.0).clip(
        lower=0.0,
        upper=1.0,
    )

    fallback_weights = (
        0.25 + 0.75 * fallback_reliability
    )

    frame["model_sample_weight"] = (
        weights.fillna(fallback_weights)
        .clip(
            lower=0.25,
            upper=1.0,
        )
    )

    return frame.sort_values(
        [
            "season_start",
            "player_name",
        ]
    ).reset_index(drop=True)


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


def fit_quantile_models(
    train: pd.DataFrame,
    features: list[str],
) -> dict[float, Pipeline]:
    models: dict[float, Pipeline] = {}

    for quantile in QUANTILES:
        print(
            f"    fitting quantile {quantile:.2f}..."
        )

        model = make_quantile_model(
            quantile
        )

        model.fit(
            train[features],
            train[TARGET_COLUMN].astype(float),
            model__sample_weight=train[
                "model_sample_weight"
            ],
        )

        models[quantile] = model

    return models


def predict_quantiles(
    models: dict[float, Pipeline],
    frame: pd.DataFrame,
    features: list[str],
) -> pd.DataFrame:
    raw_predictions = np.column_stack(
        [
            models[quantile].predict(
                frame[features]
            )
            for quantile in QUANTILES
        ]
    )

    ordered_predictions = np.sort(
        raw_predictions,
        axis=1,
    )

    columns = [
        f"q{int(quantile * 100):02d}"
        for quantile in QUANTILES
    ]

    return pd.DataFrame(
        ordered_predictions,
        columns=columns,
        index=frame.index,
    )


def weighted_quantile(
    values: np.ndarray,
    weights: np.ndarray,
    quantile: float,
) -> float:
    if len(values) == 0:
        return 0.0

    order = np.argsort(values)

    sorted_values = values[order]
    sorted_weights = weights[order]

    total_weight = float(
        sorted_weights.sum()
    )

    if total_weight <= 0:
        return float(
            np.quantile(
                sorted_values,
                quantile,
            )
        )

    cumulative_weight = np.cumsum(
        sorted_weights
    )

    cutoff = quantile * total_weight

    index = int(
        np.searchsorted(
            cumulative_weight,
            cutoff,
            side="left",
        )
    )

    index = min(
        index,
        len(sorted_values) - 1,
    )

    return float(
        sorted_values[index]
    )


def pinball_loss(
    actual: np.ndarray,
    predicted: np.ndarray,
    quantile: float,
    weights: np.ndarray,
) -> float:
    residual = actual - predicted

    loss = np.maximum(
        quantile * residual,
        (quantile - 1.0) * residual,
    )

    return float(
        np.average(
            loss,
            weights=weights,
        )
    )


def interval_metrics(
    actual: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    weights: np.ndarray,
    nominal_coverage: float,
) -> dict[str, float]:
    lower_ordered = np.minimum(
        lower,
        upper,
    )

    upper_ordered = np.maximum(
        lower,
        upper,
    )

    covered = (
        (actual >= lower_ordered)
        & (actual <= upper_ordered)
    ).astype(float)

    width = (
        upper_ordered
        - lower_ordered
    )

    alpha = 1.0 - nominal_coverage

    interval_score = width.copy()

    below = actual < lower_ordered
    above = actual > upper_ordered

    interval_score[below] += (
        2.0
        / alpha
        * (
            lower_ordered[below]
            - actual[below]
        )
    )

    interval_score[above] += (
        2.0
        / alpha
        * (
            actual[above]
            - upper_ordered[above]
        )
    )

    return {
        "coverage": float(
            np.average(
                covered,
                weights=weights,
            )
        ),
        "mean_width": float(
            np.average(
                width,
                weights=weights,
            )
        ),
        "interval_score": float(
            np.average(
                interval_score,
                weights=weights,
            )
        ),
    }


def nonconformity_scores(
    actual: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
) -> np.ndarray:
    return np.maximum.reduce(
        [
            lower - actual,
            actual - upper,
            np.zeros(
                len(actual),
                dtype=float,
            ),
        ]
    )


def conformal_adjustment(
    actual: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    weights: np.ndarray,
    nominal_coverage: float,
) -> float:
    scores = nonconformity_scores(
        actual=actual,
        lower=lower,
        upper=upper,
    )

    return weighted_quantile(
        values=scores,
        weights=weights,
        quantile=nominal_coverage,
    )


def build_rolling_predictions(
    frame: pd.DataFrame,
    features: list[str],
) -> pd.DataFrame:
    outputs: list[pd.DataFrame] = []

    for validation_season in (
        ROLLING_VALIDATION_SEASONS
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

        print(
            f"{validation_season}: "
            f"train={len(train):,}, "
            f"validation={len(validation):,}"
        )

        models = fit_quantile_models(
            train=train,
            features=features,
        )

        quantile_predictions = (
            predict_quantiles(
                models=models,
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

        for column in (
            quantile_predictions.columns
        ):
            fold[column] = (
                quantile_predictions[
                    column
                ].to_numpy(dtype=float)
            )

        outputs.append(fold)

    return pd.concat(
        outputs,
        ignore_index=True,
    )


def add_forward_conformal_intervals(
    rolling: pd.DataFrame,
) -> pd.DataFrame:
    output = rolling.copy()

    output["lower_80_forward"] = np.nan
    output["upper_80_forward"] = np.nan
    output["lower_90_forward"] = np.nan
    output["upper_90_forward"] = np.nan
    output["adjustment_80"] = np.nan
    output["adjustment_90"] = np.nan

    for index, validation_season in enumerate(
        ROLLING_VALIDATION_SEASONS
    ):
        validation_mask = (
            output["season"]
            .eq(validation_season)
        )

        if index == 0:
            adjustment_80 = 0.0
            adjustment_90 = 0.0
        else:
            prior_seasons = (
                ROLLING_VALIDATION_SEASONS[
                    :index
                ]
            )

            calibration = output.loc[
                output["season"].isin(
                    prior_seasons
                )
            ]

            calibration_actual = (
                calibration["actual"]
                .to_numpy(dtype=float)
            )

            calibration_weights = (
                calibration[
                    "sample_weight"
                ]
                .to_numpy(dtype=float)
            )

            adjustment_80 = (
                conformal_adjustment(
                    actual=calibration_actual,
                    lower=calibration[
                        "q10"
                    ].to_numpy(dtype=float),
                    upper=calibration[
                        "q90"
                    ].to_numpy(dtype=float),
                    weights=calibration_weights,
                    nominal_coverage=0.80,
                )
            )

            adjustment_90 = (
                conformal_adjustment(
                    actual=calibration_actual,
                    lower=calibration[
                        "q05"
                    ].to_numpy(dtype=float),
                    upper=calibration[
                        "q95"
                    ].to_numpy(dtype=float),
                    weights=calibration_weights,
                    nominal_coverage=0.90,
                )
            )

        output.loc[
            validation_mask,
            "lower_80_forward",
        ] = (
            output.loc[
                validation_mask,
                "q10",
            ]
            - adjustment_80
        )

        output.loc[
            validation_mask,
            "upper_80_forward",
        ] = (
            output.loc[
                validation_mask,
                "q90",
            ]
            + adjustment_80
        )

        output.loc[
            validation_mask,
            "lower_90_forward",
        ] = (
            output.loc[
                validation_mask,
                "q05",
            ]
            - adjustment_90
        )

        output.loc[
            validation_mask,
            "upper_90_forward",
        ] = (
            output.loc[
                validation_mask,
                "q95",
            ]
            + adjustment_90
        )

        output.loc[
            validation_mask,
            "adjustment_80",
        ] = adjustment_80

        output.loc[
            validation_mask,
            "adjustment_90",
        ] = adjustment_90

    return output


def summarize_metrics(
    predictions: pd.DataFrame,
    use_forward_intervals: bool,
) -> pd.DataFrame:
    actual = predictions[
        "actual"
    ].to_numpy(dtype=float)

    weights = predictions[
        "sample_weight"
    ].to_numpy(dtype=float)

    rows: list[dict[str, Any]] = []

    for quantile in QUANTILES:
        column = (
            f"q{int(quantile * 100):02d}"
        )

        rows.append(
            {
                "metric_type": "pinball_loss",
                "interval": "",
                "quantile": quantile,
                "value": pinball_loss(
                    actual=actual,
                    predicted=predictions[
                        column
                    ].to_numpy(dtype=float),
                    quantile=quantile,
                    weights=weights,
                ),
            }
        )

    median_mae = float(
        mean_absolute_error(
            actual,
            predictions["q50"]
            .to_numpy(dtype=float),
            sample_weight=weights,
        )
    )

    rows.append(
        {
            "metric_type": "median_mae",
            "interval": "",
            "quantile": 0.50,
            "value": median_mae,
        }
    )

    q10_values = predictions[
        "q10"
    ].to_numpy(dtype=float)

    rows.extend(
        [
            {
                "metric_type": "q10_zero_rate",
                "interval": "",
                "quantile": 0.10,
                "value": float(
                    np.isclose(
                        q10_values,
                        0.0,
                        atol=1e-9,
                    ).mean()
                ),
            },
            {
                "metric_type": "q10_unique_values",
                "interval": "",
                "quantile": 0.10,
                "value": float(
                    pd.Series(
                        q10_values
                    ).nunique()
                ),
            },
        ]
    )

    interval_specs = [
        (
            "raw_80",
            "q10",
            "q90",
            0.80,
        ),
        (
            "raw_90",
            "q05",
            "q95",
            0.90,
        ),
    ]

    if use_forward_intervals:
        interval_specs.extend(
            [
                (
                    "forward_conformal_80",
                    "lower_80_forward",
                    "upper_80_forward",
                    0.80,
                ),
                (
                    "forward_conformal_90",
                    "lower_90_forward",
                    "upper_90_forward",
                    0.90,
                ),
            ]
        )
    else:
        interval_specs.extend(
            [
                (
                    "conformal_80",
                    "lower_80",
                    "upper_80",
                    0.80,
                ),
                (
                    "conformal_90",
                    "lower_90",
                    "upper_90",
                    0.90,
                ),
            ]
        )

    for (
        interval_name,
        lower_column,
        upper_column,
        nominal_coverage,
    ) in interval_specs:
        result = interval_metrics(
            actual=actual,
            lower=predictions[
                lower_column
            ].to_numpy(dtype=float),
            upper=predictions[
                upper_column
            ].to_numpy(dtype=float),
            weights=weights,
            nominal_coverage=nominal_coverage,
        )

        for metric_name, value in (
            result.items()
        ):
            rows.append(
                {
                    "metric_type": metric_name,
                    "interval": interval_name,
                    "quantile": np.nan,
                    "value": value,
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

    frame = load_active_data()
    features = select_features(frame)

    development = frame.loc[
        frame["season"].ne(
            FINAL_CONFIRMATION_SEASON
        )
    ].copy()

    confirmation = frame.loc[
        frame["season"].eq(
            FINAL_CONFIRMATION_SEASON
        )
    ].copy()

    if development.empty or confirmation.empty:
        raise ValueError(
            "Development or confirmation data is empty."
        )

    print("=" * 80)
    print("ACTIVE-SEASON CONTRIBUTION UNCERTAINTY")
    print("=" * 80)
    print(
        f"Active player-season rows: "
        f"{len(frame):,}"
    )
    print(
        f"Development rows: "
        f"{len(development):,}"
    )
    print(
        f"Confirmation rows: "
        f"{len(confirmation):,}"
    )
    print(
        f"Features used: {len(features):,}"
    )
    print(
        "Quantiles: "
        + ", ".join(
            f"{quantile:.2f}"
            for quantile in QUANTILES
        )
    )
    print()

    rolling = build_rolling_predictions(
        frame=frame,
        features=features,
    )

    rolling = (
        add_forward_conformal_intervals(
            rolling
        )
    )

    rolling_evaluation = rolling.loc[
        rolling["season"].ne(
            ROLLING_VALIDATION_SEASONS[0]
        )
    ].copy()

    rolling_metrics = summarize_metrics(
        predictions=rolling_evaluation,
        use_forward_intervals=True,
    )

    print()
    print(
        "Retraining final active-season quantile "
        "models on all development seasons..."
    )

    final_models = fit_quantile_models(
        train=development,
        features=features,
    )

    confirmation_quantiles = (
        predict_quantiles(
            models=final_models,
            frame=confirmation,
            features=features,
        )
    )

    confirmation_output = confirmation[
        [
            "player_id",
            "player_name",
            "season",
            "target_season",
            "team_abbreviation",
            TARGET_COLUMN,
            "model_sample_weight",
        ]
    ].copy()

    confirmation_output = (
        confirmation_output.rename(
            columns={
                TARGET_COLUMN: "actual",
                "model_sample_weight": (
                    "sample_weight"
                ),
            }
        )
    )

    for column in (
        confirmation_quantiles.columns
    ):
        confirmation_output[
            column
        ] = confirmation_quantiles[
            column
        ].to_numpy(dtype=float)

    rolling_actual = rolling[
        "actual"
    ].to_numpy(dtype=float)

    rolling_weights = rolling[
        "sample_weight"
    ].to_numpy(dtype=float)

    final_adjustment_80 = (
        conformal_adjustment(
            actual=rolling_actual,
            lower=rolling[
                "q10"
            ].to_numpy(dtype=float),
            upper=rolling[
                "q90"
            ].to_numpy(dtype=float),
            weights=rolling_weights,
            nominal_coverage=0.80,
        )
    )

    final_adjustment_90 = (
        conformal_adjustment(
            actual=rolling_actual,
            lower=rolling[
                "q05"
            ].to_numpy(dtype=float),
            upper=rolling[
                "q95"
            ].to_numpy(dtype=float),
            weights=rolling_weights,
            nominal_coverage=0.90,
        )
    )

    confirmation_output[
        "lower_80"
    ] = (
        confirmation_output["q10"]
        - final_adjustment_80
    )

    confirmation_output[
        "upper_80"
    ] = (
        confirmation_output["q90"]
        + final_adjustment_80
    )

    confirmation_output[
        "lower_90"
    ] = (
        confirmation_output["q05"]
        - final_adjustment_90
    )

    confirmation_output[
        "upper_90"
    ] = (
        confirmation_output["q95"]
        + final_adjustment_90
    )

    confirmation_output[
        "interval_width_80"
    ] = (
        confirmation_output["upper_80"]
        - confirmation_output["lower_80"]
    )

    confirmation_output[
        "interval_width_90"
    ] = (
        confirmation_output["upper_90"]
        - confirmation_output["lower_90"]
    )

    confirmation_metrics = summarize_metrics(
        predictions=confirmation_output,
        use_forward_intervals=False,
    )

    rolling.to_csv(
        ROLLING_PREDICTIONS_PATH,
        index=False,
    )

    rolling_metrics.to_csv(
        ROLLING_METRICS_PATH,
        index=False,
    )

    confirmation_output.to_csv(
        CONFIRMATION_PREDICTIONS_PATH,
        index=False,
    )

    confirmation_metrics.to_csv(
        CONFIRMATION_METRICS_PATH,
        index=False,
    )

    model_bundle: dict[str, Any] = {
        "target": TARGET_COLUMN,
        "conditioning_event": (
            "next_season_active_flag == 1"
        ),
        "quantile_models": final_models,
        "quantiles": QUANTILES,
        "features": features,
        "conformal_adjustment_80": (
            final_adjustment_80
        ),
        "conformal_adjustment_90": (
            final_adjustment_90
        ),
        "nominal_coverage_80": 0.80,
        "nominal_coverage_90": 0.90,
    }

    joblib.dump(
        model_bundle,
        MODEL_PATH,
    )

    q10_values = confirmation_output[
        "q10"
    ].to_numpy(dtype=float)

    metadata = {
        "target": TARGET_COLUMN,
        "conditioning_event": (
            "next_season_active_flag == 1"
        ),
        "feature_count": len(features),
        "features": features,
        "quantiles": QUANTILES,
        "active_rows": len(frame),
        "development_rows": len(development),
        "confirmation_rows": len(confirmation),
        "rolling_validation_seasons": (
            ROLLING_VALIDATION_SEASONS
        ),
        "conformal_adjustment_80": (
            final_adjustment_80
        ),
        "conformal_adjustment_90": (
            final_adjustment_90
        ),
        "confirmation_q10_zero_rate": float(
            np.isclose(
                q10_values,
                0.0,
                atol=1e-9,
            ).mean()
        ),
        "confirmation_q10_unique_values": int(
            pd.Series(q10_values).nunique()
        ),
        "rolling_metrics": (
            rolling_metrics.to_dict(
                orient="records"
            )
        ),
        "confirmation_metrics": (
            confirmation_metrics.to_dict(
                orient="records"
            )
        ),
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
    print("ACTIVE-SEASON CONFIRMATION RESULTS")
    print("=" * 80)
    print(
        confirmation_metrics.to_string(
            index=False
        )
    )
    print()
    print(
        "Confirmation q10 zero rate: "
        f"{metadata['confirmation_q10_zero_rate']:.2%}"
    )
    print(
        "Confirmation q10 unique values: "
        f"{metadata['confirmation_q10_unique_values']:,}"
    )
    print(
        "Final 80% conformal adjustment: "
        f"{final_adjustment_80:.4f}"
    )
    print(
        "Final 90% conformal adjustment: "
        f"{final_adjustment_90:.4f}"
    )
    print()
    print("=" * 80)
    print(
        "ACTIVE-SEASON UNCERTAINTY MODELING COMPLETED"
    )
    print("=" * 80)
    print(MODEL_PATH)
    print(METADATA_PATH)
    print(ROLLING_PREDICTIONS_PATH)
    print(ROLLING_METRICS_PATH)
    print(CONFIRMATION_PREDICTIONS_PATH)
    print(CONFIRMATION_METRICS_PATH)


if __name__ == "__main__":
    main()