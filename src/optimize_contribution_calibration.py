from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


PROJECT_ROOT = Path(__file__).resolve().parents[1]

ROLLING_PREDICTIONS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "expected_contribution_rolling_predictions.csv"
)

TEST_PREDICTIONS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "expected_contribution_test_predictions.csv"
)

SOURCE_DATA_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "survival_aware_projection_training_data.parquet"
)

BASE_METADATA_PATH = (
    PROJECT_ROOT
    / "models"
    / "final_expected_contribution_metadata.json"
)

OUTPUT_DIRECTORY = (
    PROJECT_ROOT
    / "outputs"
    / "contribution_calibration"
)

SELECTION_RESULTS_PATH = (
    OUTPUT_DIRECTORY
    / "forward_calibration_selection_results.csv"
)

FORWARD_PREDICTIONS_PATH = (
    OUTPUT_DIRECTORY
    / "forward_calibration_predictions.csv"
)

TEST_METRICS_PATH = (
    OUTPUT_DIRECTORY
    / "calibrated_test_metrics.csv"
)

TEST_OUTPUT_PATH = (
    OUTPUT_DIRECTORY
    / "calibrated_test_predictions.csv"
)

MODEL_PATH = (
    PROJECT_ROOT
    / "models"
    / "expected_contribution_calibrator.joblib"
)

METADATA_PATH = (
    PROJECT_ROOT
    / "models"
    / "expected_contribution_calibrator_metadata.json"
)


ROLLING_SEASONS = [
    "2018-19",
    "2019-20",
    "2020-21",
    "2021-22",
    "2022-23",
    "2023-24",
]

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

BASE_BLEND_GRID = np.round(
    np.linspace(0.0, 1.0, 21),
    2,
)

GROUP_SHRINKAGE_STRENGTH = 100.0
MIN_GROUP_ROWS = 30


@dataclass
class CalibrationParameters:
    scheme: str
    global_base_weight: float
    global_correction: float
    group_base_weights: dict[str, float]
    group_corrections: dict[str, float]
    group_counts: dict[str, int]


def weighted_mean(
    values: np.ndarray,
    weights: np.ndarray,
) -> float:
    if len(values) == 0:
        return np.nan

    weight_sum = float(
        np.sum(weights)
    )

    if weight_sum <= 0:
        return float(
            np.mean(values)
        )

    return float(
        np.average(
            values,
            weights=weights,
        )
    )


def weighted_median(
    values: np.ndarray,
    weights: np.ndarray,
) -> float:
    if len(values) == 0:
        return 0.0

    order = np.argsort(values)
    sorted_values = values[order]
    sorted_weights = weights[order]

    cumulative = np.cumsum(
        sorted_weights
    )

    cutoff = 0.5 * float(
        sorted_weights.sum()
    )

    index = int(
        np.searchsorted(
            cumulative,
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


def safe_spearman(
    actual: np.ndarray,
    predicted: np.ndarray,
) -> float:
    if len(actual) < 3:
        return np.nan

    if (
        np.unique(actual).size < 2
        or np.unique(predicted).size < 2
    ):
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


def regression_metrics(
    actual: np.ndarray,
    predicted: np.ndarray,
    weights: np.ndarray,
) -> dict[str, float]:
    return {
        "weighted_mae": float(
            mean_absolute_error(
                actual,
                predicted,
                sample_weight=weights,
            )
        ),
        "mae": float(
            mean_absolute_error(
                actual,
                predicted,
            )
        ),
        "weighted_rmse": float(
            np.sqrt(
                weighted_mean(
                    (
                        predicted
                        - actual
                    )
                    ** 2,
                    weights,
                )
            )
        ),
        "rmse": float(
            mean_squared_error(
                actual,
                predicted,
            )
            ** 0.5
        ),
        "weighted_bias": (
            weighted_mean(
                predicted - actual,
                weights,
            )
        ),
        "r_squared": float(
            r2_score(
                actual,
                predicted,
                sample_weight=weights,
            )
        ),
        "spearman_correlation": (
            safe_spearman(
                actual,
                predicted,
            )
        ),
    }


def choose_base_weight(
    actual: np.ndarray,
    base_prediction: np.ndarray,
    persistence: np.ndarray,
    weights: np.ndarray,
) -> float:
    best_weight = 1.0
    best_mae = np.inf

    for base_weight in BASE_BLEND_GRID:
        prediction = (
            base_weight
            * base_prediction
            + (1.0 - base_weight)
            * persistence
        )

        score = float(
            mean_absolute_error(
                actual,
                prediction,
                sample_weight=weights,
            )
        )

        if score < best_mae:
            best_mae = score
            best_weight = float(
                base_weight
            )

    return best_weight


def build_base_prediction(
    frame: pd.DataFrame,
    metadata: dict[str, object],
    rolling: bool,
) -> np.ndarray:
    direct_model_name = str(
        metadata[
            "selected_direct_model"
        ]
    )

    direct_weight = float(
        metadata["direct_weight"]
    )

    staged_weight = float(
        metadata["staged_weight"]
    )

    baseline_weight = float(
        metadata["baseline_weight"]
    )

    if rolling:
        direct_column = (
            f"direct__{direct_model_name}"
        )

        staged_column = (
            "staged_prediction"
        )

        baseline_column = (
            "persistence_baseline"
        )

    else:
        direct_column = (
            "projected_direct_total_impact"
        )

        staged_column = (
            "projected_staged_total_impact"
        )

        baseline_column = (
            "persistence_total_impact"
        )

    missing = [
        column
        for column in [
            direct_column,
            staged_column,
            baseline_column,
        ]
        if column not in frame.columns
    ]

    if missing:
        raise ValueError(
            "Prediction data is missing columns:\n"
            + "\n".join(missing)
        )

    staged_direct = (
        direct_weight
        * frame[
            direct_column
        ].to_numpy(dtype=float)
        + staged_weight
        * frame[
            staged_column
        ].to_numpy(dtype=float)
    )

    return (
        (1.0 - baseline_weight)
        * staged_direct
        + baseline_weight
        * frame[
            baseline_column
        ].to_numpy(dtype=float)
    )


def add_workload_data(
    frame: pd.DataFrame,
    source: pd.DataFrame,
) -> pd.DataFrame:
    source_columns = [
        "player_id",
        "season",
        "age",
        "minutes_per_game",
        "total_minutes",
        "advanced_pie",
        "rotation_player_flag",
    ]

    missing = [
        column
        for column in source_columns
        if column not in source.columns
    ]

    if missing:
        raise ValueError(
            "Source data is missing columns:\n"
            + "\n".join(missing)
        )

    output = frame.merge(
        source[source_columns],
        how="left",
        on=[
            "player_id",
            "season",
        ],
        validate="one_to_one",
    )

    output[
        "current_workload_group"
    ] = pd.cut(
        output["minutes_per_game"],
        bins=WORKLOAD_BINS,
        labels=WORKLOAD_LABELS,
        right=False,
        include_lowest=True,
    ).astype(str)

    return output


def fit_calibration(
    training: pd.DataFrame,
    scheme: str,
) -> CalibrationParameters:
    actual = training[
        "actual"
    ].to_numpy(dtype=float)

    base = training[
        "base_prediction"
    ].to_numpy(dtype=float)

    persistence = training[
        "persistence_baseline"
    ].to_numpy(dtype=float)

    weights = training[
        "sample_weight"
    ].to_numpy(dtype=float)

    if scheme in {
        "raw",
        "global_bias",
        "workload_bias",
    }:
        global_base_weight = 1.0

    else:
        global_base_weight = (
            choose_base_weight(
                actual=actual,
                base_prediction=base,
                persistence=persistence,
                weights=weights,
            )
        )

    global_blended = (
        global_base_weight * base
        + (1.0 - global_base_weight)
        * persistence
    )

    if scheme in {
        "raw",
        "global_blend",
        "workload_blend",
    }:
        global_correction = 0.0

    else:
        global_correction = (
            weighted_median(
                actual - global_blended,
                weights,
            )
        )

    group_base_weights: dict[
        str,
        float,
    ] = {}

    group_corrections: dict[
        str,
        float,
    ] = {}

    group_counts: dict[
        str,
        int,
    ] = {}

    for group_name, group in training.groupby(
        "current_workload_group",
        dropna=False,
    ):
        group_key = str(
            group_name
        )

        group_count = int(
            len(group)
        )

        group_counts[
            group_key
        ] = group_count

        group_actual = group[
            "actual"
        ].to_numpy(dtype=float)

        group_base = group[
            "base_prediction"
        ].to_numpy(dtype=float)

        group_persistence = group[
            "persistence_baseline"
        ].to_numpy(dtype=float)

        group_weights = group[
            "sample_weight"
        ].to_numpy(dtype=float)

        shrinkage = (
            group_count
            / (
                group_count
                + GROUP_SHRINKAGE_STRENGTH
            )
        )

        if (
            group_count
            < MIN_GROUP_ROWS
        ):
            shrinkage = 0.0

        if scheme in {
            "workload_blend",
            "workload_blend_bias",
        }:
            raw_group_weight = (
                choose_base_weight(
                    actual=group_actual,
                    base_prediction=group_base,
                    persistence=(
                        group_persistence
                    ),
                    weights=group_weights,
                )
            )

            group_base_weight = (
                shrinkage
                * raw_group_weight
                + (1.0 - shrinkage)
                * global_base_weight
            )

        else:
            group_base_weight = (
                global_base_weight
            )

        group_blended = (
            group_base_weight
            * group_base
            + (1.0 - group_base_weight)
            * group_persistence
        )

        if scheme in {
            "workload_bias",
            "workload_blend_bias",
        }:
            raw_group_correction = (
                weighted_median(
                    group_actual
                    - group_blended,
                    group_weights,
                )
            )

            group_correction = (
                shrinkage
                * raw_group_correction
                + (1.0 - shrinkage)
                * global_correction
            )

        else:
            group_correction = (
                global_correction
            )

        group_base_weights[
            group_key
        ] = float(
            group_base_weight
        )

        group_corrections[
            group_key
        ] = float(
            group_correction
        )

    return CalibrationParameters(
        scheme=scheme,
        global_base_weight=float(
            global_base_weight
        ),
        global_correction=float(
            global_correction
        ),
        group_base_weights=(
            group_base_weights
        ),
        group_corrections=(
            group_corrections
        ),
        group_counts=group_counts,
    )


def apply_calibration(
    frame: pd.DataFrame,
    parameters: CalibrationParameters,
) -> np.ndarray:
    predictions = np.zeros(
        len(frame),
        dtype=float,
    )

    for position, (_, row) in enumerate(
        frame.iterrows()
    ):
        group_key = str(
            row[
                "current_workload_group"
            ]
        )

        base_weight = (
            parameters.group_base_weights.get(
                group_key,
                parameters.global_base_weight,
            )
        )

        correction = (
            parameters.group_corrections.get(
                group_key,
                parameters.global_correction,
            )
        )

        predictions[position] = (
            base_weight
            * float(
                row["base_prediction"]
            )
            + (1.0 - base_weight)
            * float(
                row[
                    "persistence_baseline"
                ]
            )
            + correction
        )

    return predictions


def forward_validate_scheme(
    rolling: pd.DataFrame,
    scheme: str,
) -> tuple[
    pd.DataFrame,
    dict[str, float],
]:
    outputs: list[
        pd.DataFrame
    ] = []

    for index in range(
        1,
        len(ROLLING_SEASONS),
    ):
        validation_season = (
            ROLLING_SEASONS[index]
        )

        prior_seasons = (
            ROLLING_SEASONS[:index]
        )

        training = rolling.loc[
            rolling["season"].isin(
                prior_seasons
            )
        ].copy()

        validation = rolling.loc[
            rolling["season"].eq(
                validation_season
            )
        ].copy()

        parameters = fit_calibration(
            training=training,
            scheme=scheme,
        )

        validation[
            "calibrated_prediction"
        ] = apply_calibration(
            validation,
            parameters,
        )

        validation[
            "calibration_scheme"
        ] = scheme

        outputs.append(
            validation
        )

    forward = pd.concat(
        outputs,
        ignore_index=True,
    )

    metrics = regression_metrics(
        actual=forward[
            "actual"
        ].to_numpy(dtype=float),
        predicted=forward[
            "calibrated_prediction"
        ].to_numpy(dtype=float),
        weights=forward[
            "sample_weight"
        ].to_numpy(dtype=float),
    )

    return forward, metrics


def parameters_to_dict(
    parameters: CalibrationParameters,
) -> dict[str, object]:
    return {
        "scheme": parameters.scheme,
        "global_base_weight": (
            parameters.global_base_weight
        ),
        "global_correction": (
            parameters.global_correction
        ),
        "group_base_weights": (
            parameters.group_base_weights
        ),
        "group_corrections": (
            parameters.group_corrections
        ),
        "group_counts": (
            parameters.group_counts
        ),
    }


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    MODEL_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    required_paths = [
        ROLLING_PREDICTIONS_PATH,
        TEST_PREDICTIONS_PATH,
        SOURCE_DATA_PATH,
        BASE_METADATA_PATH,
    ]

    missing_paths = [
        path
        for path in required_paths
        if not path.exists()
    ]

    if missing_paths:
        raise FileNotFoundError(
            "Required files are missing:\n"
            + "\n".join(
                str(path)
                for path in missing_paths
            )
        )

    rolling = pd.read_csv(
        ROLLING_PREDICTIONS_PATH
    )

    test = pd.read_csv(
        TEST_PREDICTIONS_PATH
    )

    source = pd.read_parquet(
        SOURCE_DATA_PATH
    )

    with BASE_METADATA_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        metadata = json.load(file)

    rolling = add_workload_data(
        rolling,
        source,
    )

    test = add_workload_data(
        test,
        source,
    )

    rolling[
        "base_prediction"
    ] = build_base_prediction(
        rolling,
        metadata,
        rolling=True,
    )

    test[
        "base_prediction"
    ] = build_base_prediction(
        test,
        metadata,
        rolling=False,
    )

    # Standardize the persistence column name so the same
    # calibration function works for rolling and test data.
    test[
        "persistence_baseline"
    ] = test[
        "persistence_total_impact"
    ]

    if "actual" not in rolling.columns:
        raise ValueError(
            "Rolling predictions are missing the actual target."
        )

    if (
        "actual_total_impact_value"
        not in test.columns
    ):
        raise ValueError(
            "Test predictions are missing the actual target."
        )

    if "sample_weight" not in rolling.columns:
        raise ValueError(
            "Rolling predictions are missing sample_weight."
        )

    if "model_sample_weight" not in test.columns:
        raise ValueError(
            "Test predictions are missing model_sample_weight."
        )

    test = test.rename(
        columns={
            "actual_total_impact_value": (
                "actual"
            ),
            "model_sample_weight": (
                "sample_weight"
            ),
        }
    )

    schemes = [
        "raw",
        "global_bias",
        "global_blend",
        "global_blend_bias",
        "workload_bias",
        "workload_blend",
        "workload_blend_bias",
    ]

    selection_rows: list[
        dict[str, object]
    ] = []

    forward_outputs: list[
        pd.DataFrame
    ] = []

    print("=" * 80)
    print("FORWARD CONTRIBUTION CALIBRATION")
    print("=" * 80)
    print(
        "Calibration choices are selected only "
        "from earlier rolling seasons."
    )
    print()

    for scheme in schemes:
        print(
            f"Evaluating {scheme}..."
        )

        forward, metrics = (
            forward_validate_scheme(
                rolling=rolling,
                scheme=scheme,
            )
        )

        selection_rows.append(
            {
                "scheme": scheme,
                **metrics,
            }
        )

        forward_outputs.append(
            forward
        )

    selection_results = pd.DataFrame(
        selection_rows
    ).sort_values(
        [
            "weighted_mae",
            "weighted_rmse",
        ],
        ascending=True,
    ).reset_index(drop=True)

    selected_scheme = str(
        selection_results.iloc[0][
            "scheme"
        ]
    )

    print()
    print(
        "Selected calibration scheme: "
        f"{selected_scheme}"
    )
    print(
        "Forward weighted MAE: "
        f"{selection_results.iloc[0]['weighted_mae']:.5f}"
    )

    final_parameters = fit_calibration(
        training=rolling,
        scheme=selected_scheme,
    )

    test[
        "calibrated_prediction"
    ] = apply_calibration(
        test,
        final_parameters,
    )

    raw_metrics = regression_metrics(
        actual=test[
            "actual"
        ].to_numpy(dtype=float),
        predicted=test[
            "base_prediction"
        ].to_numpy(dtype=float),
        weights=test[
            "sample_weight"
        ].to_numpy(dtype=float),
    )

    calibrated_metrics = (
        regression_metrics(
            actual=test[
                "actual"
            ].to_numpy(dtype=float),
            predicted=test[
                "calibrated_prediction"
            ].to_numpy(dtype=float),
            weights=test[
                "sample_weight"
            ].to_numpy(dtype=float),
        )
    )

    print()
    print("=" * 80)
    print("CONFIRMATION-SEASON RESULTS")
    print("=" * 80)
    print(
        "Raw weighted MAE: "
        f"{raw_metrics['weighted_mae']:.5f}"
    )
    print(
        "Calibrated weighted MAE: "
        f"{calibrated_metrics['weighted_mae']:.5f}"
    )
    print(
        "MAE improvement: "
        f"{raw_metrics['weighted_mae'] - calibrated_metrics['weighted_mae']:.5f}"
    )
    print(
        "Raw weighted bias: "
        f"{raw_metrics['weighted_bias']:.5f}"
    )
    print(
        "Calibrated weighted bias: "
        f"{calibrated_metrics['weighted_bias']:.5f}"
    )
    print(
        "Calibrated R-squared: "
        f"{calibrated_metrics['r_squared']:.4f}"
    )
    print(
        "Calibrated Spearman: "
        f"{calibrated_metrics['spearman_correlation']:.4f}"
    )

    forward_predictions = pd.concat(
        forward_outputs,
        ignore_index=True,
    )

    forward_predictions.to_csv(
        FORWARD_PREDICTIONS_PATH,
        index=False,
    )

    selection_results.to_csv(
        SELECTION_RESULTS_PATH,
        index=False,
    )

    test_output_columns = [
        "player_id",
        "player_name",
        "season",
        "target_season",
        "team_abbreviation",
        "age",
        "minutes_per_game",
        "current_workload_group",
        "next_season_active_flag",
        "next_rotation_player_flag",
        "actual",
        "base_prediction",
        "calibrated_prediction",
        "persistence_baseline",
        "sample_weight",
    ]

    available_test_columns = [
        column
        for column in test_output_columns
        if column in test.columns
    ]

    test[
        available_test_columns
    ].to_csv(
        TEST_OUTPUT_PATH,
        index=False,
    )

    test_metrics = pd.DataFrame(
        [
            {
                "approach": "raw",
                **raw_metrics,
            },
            {
                "approach": (
                    f"calibrated__"
                    f"{selected_scheme}"
                ),
                **calibrated_metrics,
            },
        ]
    )

    test_metrics.to_csv(
        TEST_METRICS_PATH,
        index=False,
    )

    model_bundle = {
        "selected_scheme": (
            selected_scheme
        ),
        "parameters": (
            parameters_to_dict(
                final_parameters
            )
        ),
        "workload_bins": (
            WORKLOAD_BINS
        ),
        "workload_labels": (
            WORKLOAD_LABELS
        ),
        "group_shrinkage_strength": (
            GROUP_SHRINKAGE_STRENGTH
        ),
        "minimum_group_rows": (
            MIN_GROUP_ROWS
        ),
    }

    joblib.dump(
        model_bundle,
        MODEL_PATH,
    )

    calibration_metadata = {
        "selected_scheme": (
            selected_scheme
        ),
        "forward_selection_results": (
            selection_results.to_dict(
                orient="records"
            )
        ),
        "parameters": (
            parameters_to_dict(
                final_parameters
            )
        ),
        "confirmation_metrics": {
            "raw": raw_metrics,
            "calibrated": (
                calibrated_metrics
            ),
        },
        "model_path": str(
            MODEL_PATH
        ),
    }

    with METADATA_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            calibration_metadata,
            file,
            indent=2,
            default=float,
        )

    print()
    print("CALIBRATION PARAMETERS")
    print(
        "Global base-model weight: "
        f"{final_parameters.global_base_weight:.3f}"
    )
    print(
        "Global additive correction: "
        f"{final_parameters.global_correction:.3f}"
    )

    parameter_table = pd.DataFrame(
        {
            "workload_group": list(
                final_parameters.group_base_weights.keys()
            ),
            "base_model_weight": list(
                final_parameters.group_base_weights.values()
            ),
            "additive_correction": [
                final_parameters.group_corrections[
                    key
                ]
                for key in (
                    final_parameters.group_base_weights.keys()
                )
            ],
            "rolling_rows": [
                final_parameters.group_counts[
                    key
                ]
                for key in (
                    final_parameters.group_base_weights.keys()
                )
            ],
        }
    )

    print(
        parameter_table.to_string(
            index=False
        )
    )

    print()
    print("=" * 80)
    print("CALIBRATION OPTIMIZATION COMPLETED")
    print("=" * 80)
    print(SELECTION_RESULTS_PATH)
    print(FORWARD_PREDICTIONS_PATH)
    print(TEST_METRICS_PATH)
    print(TEST_OUTPUT_PATH)
    print(MODEL_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()