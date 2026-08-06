from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from scipy.stats import beta as beta_distribution
from sklearn.isotonic import IsotonicRegression


SCRIPT_VERSION = "historical-draft-pick-probability-calibration-v2-2026-08-04"

PROJECT_ROOT = Path(__file__).resolve().parents[1]

PLAYER_OUTCOMES_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "historical_draft_player_outcomes_2014_2022.parquet"
)

V1_CURVE_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "historical_draft_pick_value_curve_1_60_v1.parquet"
)

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"
MODEL_DIRECTORY = PROJECT_ROOT / "models"

V2_CURVE_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "historical_draft_pick_value_curve_1_60_v2_calibrated.parquet"
)

V2_CURVE_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "historical_draft_pick_value_curve_1_60_v2_calibrated.csv"
)

CALIBRATION_VALIDATION_PATH = (
    OUTPUT_DIRECTORY
    / "historical_draft_pick_probability_calibration_validation_v2.csv"
)

SELECTED_SLOT_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "historical_draft_pick_probability_selected_slots_v2.csv"
)

MODEL_PATH = (
    MODEL_DIRECTORY
    / "historical_draft_pick_probability_calibration_v2.joblib"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "historical_draft_pick_probability_calibration_metadata_v2.json"
)


BINARY_TARGETS = {
    "rotation_outcome": "rotation_probability_calibrated",
    "starter_outcome": "starter_probability_calibrated",
    "star_outcome": "star_proxy_probability_calibrated",
    "year4_active_outcome": "year4_active_probability_calibrated",
}

V1_PROBABILITY_COLUMNS = {
    "rotation_outcome": "rotation_probability",
    "starter_outcome": "starter_probability",
    "star_outcome": "star_proxy_probability",
    "year4_active_outcome": "year4_active_probability",
}

BANDWIDTH_GRID = [
    3.0,
    4.5,
    6.0,
    8.0,
]

PRIOR_STRENGTH_GRID = [
    8.0,
    12.0,
    18.0,
    26.0,
]

SLOT_GRID = np.arange(
    1,
    61,
    dtype=float,
)

SELECTED_SLOTS = [
    1,
    2,
    3,
    5,
    10,
    14,
    20,
    25,
    30,
    31,
    35,
    40,
    45,
    50,
    55,
    60,
]


def require_columns(
    frame: pd.DataFrame,
    columns: list[str],
    frame_name: str,
) -> None:
    missing = [
        column
        for column in columns
        if column not in frame.columns
    ]

    if missing:
        raise ValueError(
            f"{frame_name} is missing required columns:\n"
            + "\n".join(missing)
        )


def numeric_series(
    frame: pd.DataFrame,
    column: str,
    fill_value: float | None = None,
) -> pd.Series:
    values = pd.to_numeric(
        frame[column],
        errors="coerce",
    )

    if fill_value is not None:
        values = values.fillna(
            fill_value
        )

    return values.astype(float)


def safe_log_loss(
    actual: np.ndarray,
    predicted: np.ndarray,
) -> float:
    clipped = np.clip(
        predicted,
        1e-6,
        1.0 - 1e-6,
    )

    return float(
        -np.mean(
            actual * np.log(clipped)
            + (1.0 - actual)
            * np.log(
                1.0 - clipped
            )
        )
    )


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    for path in [
        PLAYER_OUTCOMES_PATH,
        V1_CURVE_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required file was not found:\n{path}"
            )

    outcomes = pd.read_parquet(
        PLAYER_OUTCOMES_PATH
    )

    curve = pd.read_parquet(
        V1_CURVE_PATH
    )

    require_columns(
        outcomes,
        [
            "draft_year",
            "overall_pick",
            *BINARY_TARGETS.keys(),
        ],
        "Historical draft player outcomes",
    )

    require_columns(
        curve,
        [
            "overall_pick",
            "historical_pick_value_score",
            "relative_pick_value_index_1_equals_100",
            *V1_PROBABILITY_COLUMNS.values(),
        ],
        "Historical draft-pick value curve V1",
    )

    outcomes = outcomes.copy()
    curve = curve.copy()

    outcomes[
        "draft_year"
    ] = numeric_series(
        outcomes,
        "draft_year",
    ).round().astype(int)

    outcomes[
        "overall_pick"
    ] = numeric_series(
        outcomes,
        "overall_pick",
    )

    for target in BINARY_TARGETS:
        outcomes[target] = (
            numeric_series(
                outcomes,
                target,
                fill_value=0.0,
            )
            .clip(
                lower=0.0,
                upper=1.0,
            )
        )

    curve[
        "overall_pick"
    ] = numeric_series(
        curve,
        "overall_pick",
    ).round().astype(int)

    return (
        outcomes,
        curve,
    )


def gaussian_weights(
    picks: np.ndarray,
    slot: float,
    bandwidth: float,
) -> np.ndarray:
    distance = (
        picks - slot
    ) / bandwidth

    return np.exp(
        -0.5
        * np.square(
            distance
        )
    )


def fit_probability_curve(
    training: pd.DataFrame,
    target: str,
    bandwidth: float,
    prior_strength: float,
) -> pd.DataFrame:
    picks = numeric_series(
        training,
        "overall_pick",
    ).to_numpy()

    outcomes = numeric_series(
        training,
        target,
        fill_value=0.0,
    ).to_numpy()

    overall_rate = float(
        np.mean(
            outcomes
        )
    )

    raw_means = []
    lower_bounds = []
    upper_bounds = []
    effective_samples = []

    for slot in SLOT_GRID:
        weights = gaussian_weights(
            picks=picks,
            slot=slot,
            bandwidth=bandwidth,
        )

        weighted_n = float(
            np.sum(
                weights
            )
        )

        weighted_successes = float(
            np.sum(
                weights
                * outcomes
            )
        )

        prior_alpha = (
            overall_rate
            * prior_strength
        )

        prior_beta = (
            (1.0 - overall_rate)
            * prior_strength
        )

        posterior_alpha = (
            weighted_successes
            + prior_alpha
        )

        posterior_beta = (
            weighted_n
            - weighted_successes
            + prior_beta
        )

        posterior_mean = (
            posterior_alpha
            / (
                posterior_alpha
                + posterior_beta
            )
        )

        lower = float(
            beta_distribution.ppf(
                0.10,
                posterior_alpha,
                posterior_beta,
            )
        )

        upper = float(
            beta_distribution.ppf(
                0.90,
                posterior_alpha,
                posterior_beta,
            )
        )

        raw_means.append(
            posterior_mean
        )

        lower_bounds.append(
            lower
        )

        upper_bounds.append(
            upper
        )

        effective_samples.append(
            weighted_n
        )

    raw_means_array = np.array(
        raw_means,
        dtype=float,
    )

    effective_samples_array = np.array(
        effective_samples,
        dtype=float,
    )

    isotonic = IsotonicRegression(
        increasing=False,
        out_of_bounds="clip",
        y_min=0.01,
        y_max=0.99,
    )

    calibrated = isotonic.fit_transform(
        SLOT_GRID,
        raw_means_array,
        sample_weight=(
            effective_samples_array
            + prior_strength
        ),
    )

    lower_array = np.minimum(
        np.array(
            lower_bounds,
            dtype=float,
        ),
        calibrated,
    )

    upper_array = np.maximum(
        np.array(
            upper_bounds,
            dtype=float,
        ),
        calibrated,
    )

    return pd.DataFrame(
        {
            "overall_pick": (
                SLOT_GRID.astype(int)
            ),
            "raw_posterior_probability": (
                raw_means_array
            ),
            "calibrated_probability": (
                calibrated
            ),
            "probability_p10": (
                np.clip(
                    lower_array,
                    0.0,
                    1.0,
                )
            ),
            "probability_p90": (
                np.clip(
                    upper_array,
                    0.0,
                    1.0,
                )
            ),
            "local_effective_sample_size": (
                effective_samples_array
            ),
            "overall_prior_rate": (
                overall_rate
            ),
        }
    )


def cross_validate_parameters(
    outcomes: pd.DataFrame,
    target: str,
) -> tuple[
    float,
    float,
    pd.DataFrame,
]:
    draft_years = sorted(
        outcomes[
            "draft_year"
        ].unique()
    )

    parameter_rows = []

    for bandwidth in BANDWIDTH_GRID:
        for prior_strength in (
            PRIOR_STRENGTH_GRID
        ):
            fold_rows = []

            for heldout_year in draft_years:
                train = outcomes.loc[
                    outcomes[
                        "draft_year"
                    ].ne(
                        heldout_year
                    )
                ].copy()

                test = outcomes.loc[
                    outcomes[
                        "draft_year"
                    ].eq(
                        heldout_year
                    )
                ].copy()

                curve = fit_probability_curve(
                    training=train,
                    target=target,
                    bandwidth=bandwidth,
                    prior_strength=(
                        prior_strength
                    ),
                )

                lookup = curve.set_index(
                    "overall_pick"
                )[
                    "calibrated_probability"
                ]

                predicted = (
                    numeric_series(
                        test,
                        "overall_pick",
                    )
                    .round()
                    .astype(int)
                    .map(
                        lookup
                    )
                    .to_numpy(
                        dtype=float
                    )
                )

                actual = numeric_series(
                    test,
                    target,
                    fill_value=0.0,
                ).to_numpy(
                    dtype=float
                )

                fold_rows.append(
                    {
                        "heldout_draft_year": (
                            int(
                                heldout_year
                            )
                        ),
                        "brier_score": float(
                            np.mean(
                                np.square(
                                    actual
                                    - predicted
                                )
                            )
                        ),
                        "log_loss": (
                            safe_log_loss(
                                actual,
                                predicted,
                            )
                        ),
                        "bias_actual_minus_prediction": float(
                            np.mean(
                                actual
                                - predicted
                            )
                        ),
                    }
                )

            folds = pd.DataFrame(
                fold_rows
            )

            parameter_rows.append(
                {
                    "target": target,
                    "bandwidth": (
                        bandwidth
                    ),
                    "prior_strength": (
                        prior_strength
                    ),
                    "mean_brier_score": float(
                        folds[
                            "brier_score"
                        ].mean()
                    ),
                    "mean_log_loss": float(
                        folds[
                            "log_loss"
                        ].mean()
                    ),
                    "mean_bias": float(
                        folds[
                            (
                                "bias_actual_"
                                "minus_prediction"
                            )
                        ].mean()
                    ),
                }
            )

    parameter_results = (
        pd.DataFrame(
            parameter_rows
        )
        .sort_values(
            [
                "mean_brier_score",
                "mean_log_loss",
                "prior_strength",
                "bandwidth",
            ],
            ascending=[
                True,
                True,
                True,
                True,
            ],
        )
        .reset_index(
            drop=True
        )
    )

    best = parameter_results.iloc[
        0
    ]

    return (
        float(
            best[
                "bandwidth"
            ]
        ),
        float(
            best[
                "prior_strength"
            ]
        ),
        parameter_results,
    )


def validate_selected_parameters(
    outcomes: pd.DataFrame,
    target: str,
    bandwidth: float,
    prior_strength: float,
) -> pd.DataFrame:
    rows = []

    for heldout_year in sorted(
        outcomes[
            "draft_year"
        ].unique()
    ):
        train = outcomes.loc[
            outcomes[
                "draft_year"
            ].ne(
                heldout_year
            )
        ].copy()

        test = outcomes.loc[
            outcomes[
                "draft_year"
            ].eq(
                heldout_year
            )
        ].copy()

        curve = fit_probability_curve(
            training=train,
            target=target,
            bandwidth=bandwidth,
            prior_strength=(
                prior_strength
            ),
        )

        lookup = curve.set_index(
            "overall_pick"
        )[
            "calibrated_probability"
        ]

        predicted = (
            numeric_series(
                test,
                "overall_pick",
            )
            .round()
            .astype(int)
            .map(
                lookup
            )
            .to_numpy(
                dtype=float
            )
        )

        actual = numeric_series(
            test,
            target,
            fill_value=0.0,
        ).to_numpy(
            dtype=float
        )

        rows.append(
            {
                "target": target,
                "heldout_draft_year": (
                    int(
                        heldout_year
                    )
                ),
                "players": len(
                    test
                ),
                "bandwidth": bandwidth,
                "prior_strength": (
                    prior_strength
                ),
                "actual_rate": float(
                    np.mean(
                        actual
                    )
                ),
                "predicted_rate": float(
                    np.mean(
                        predicted
                    )
                ),
                "brier_score": float(
                    np.mean(
                        np.square(
                            actual
                            - predicted
                        )
                    )
                ),
                "log_loss": (
                    safe_log_loss(
                        actual,
                        predicted,
                    )
                ),
                "bias_actual_minus_prediction": float(
                    np.mean(
                        actual
                        - predicted
                    )
                ),
            }
        )

    return pd.DataFrame(
        rows
    )


def add_pick_value_rating(
    curve: pd.DataFrame,
) -> pd.DataFrame:
    output = curve.copy()

    score = numeric_series(
        output,
        "historical_pick_value_score",
    )

    minimum = float(
        score.min()
    )

    maximum = float(
        score.max()
    )

    if maximum <= minimum:
        raise ValueError(
            "Historical pick scores do not have "
            "enough variation for a 60-99 rating."
        )

    normalized = (
        (
            score
            - minimum
        )
        / (
            maximum
            - minimum
        )
    ).clip(
        lower=0.0,
        upper=1.0,
    )

    output[
        "historical_pick_value_rating_60_99"
    ] = (
        60.0
        + 39.0
        * np.power(
            normalized,
            0.80,
        )
    ).round().astype(int)

    output[
        "pick_rating_scope_note"
    ] = (
        "Presentation-only 60-99 rating for a known draft slot. "
        "It is not yet the value of a specific future team's pick."
    )

    return output


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [
            json_safe(item)
            for item in value
        ]

    if isinstance(value, np.integer):
        return int(value)

    if isinstance(value, np.floating):
        if np.isnan(value):
            return None
        return float(value)

    if isinstance(value, float):
        if math.isnan(value):
            return None
        return value

    if pd.isna(value):
        return None

    return value


def main() -> None:
    for directory in [
        PROCESSED_DIRECTORY,
        OUTPUT_DIRECTORY,
        MODEL_DIRECTORY,
    ]:
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    print("=" * 80)
    print("HISTORICAL DRAFT-PICK PROBABILITY CALIBRATION V2")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    outcomes, v1_curve = load_inputs()

    calibrated_curve = v1_curve.copy()

    validation_frames = []
    parameter_audits = {}
    selected_parameters = {}
    fitted_curves = {}

    for target, output_column in (
        BINARY_TARGETS.items()
    ):
        print(
            f"Selecting calibration parameters for {target}..."
        )

        (
            best_bandwidth,
            best_prior_strength,
            parameter_results,
        ) = cross_validate_parameters(
            outcomes=outcomes,
            target=target,
        )

        selected_parameters[target] = {
            "bandwidth": (
                best_bandwidth
            ),
            "prior_strength": (
                best_prior_strength
            ),
            "mean_cv_brier_score": float(
                parameter_results.iloc[
                    0
                ][
                    "mean_brier_score"
                ]
            ),
            "mean_cv_log_loss": float(
                parameter_results.iloc[
                    0
                ][
                    "mean_log_loss"
                ]
            ),
        }

        parameter_audits[target] = (
            parameter_results
        )

        fitted = fit_probability_curve(
            training=outcomes,
            target=target,
            bandwidth=best_bandwidth,
            prior_strength=(
                best_prior_strength
            ),
        )

        fitted_curves[target] = (
            fitted
        )

        calibrated_curve = (
            calibrated_curve.merge(
                fitted[
                    [
                        "overall_pick",
                        "calibrated_probability",
                        "probability_p10",
                        "probability_p90",
                        "local_effective_sample_size",
                    ]
                ].rename(
                    columns={
                        "calibrated_probability": (
                            output_column
                        ),
                        "probability_p10": (
                            f"{output_column}_p10"
                        ),
                        "probability_p90": (
                            f"{output_column}_p90"
                        ),
                        "local_effective_sample_size": (
                            f"{output_column}_"
                            "effective_sample_size"
                        ),
                    }
                ),
                how="left",
                on="overall_pick",
                validate="one_to_one",
            )
        )

        validation_frames.append(
            validate_selected_parameters(
                outcomes=outcomes,
                target=target,
                bandwidth=best_bandwidth,
                prior_strength=(
                    best_prior_strength
                ),
            )
        )

    calibrated_curve = (
        add_pick_value_rating(
            calibrated_curve
        )
    )

    calibrated_curve[
        "calibration_scope_note"
    ] = (
        "Binary outcome probabilities use draft-class cross-validated "
        "Gaussian local smoothing, empirical-Bayes shrinkage, and a "
        "monotonic isotonic constraint. Future-pick valuation still "
        "requires originating-team projections and lottery simulation."
    )

    validation = pd.concat(
        validation_frames,
        ignore_index=True,
    )

    selected_audit_columns = [
        "overall_pick",
        "round_number",
        "historical_pick_value_score",
        "historical_pick_value_rating_60_99",
    ]

    for target, output_column in (
        BINARY_TARGETS.items()
    ):
        selected_audit_columns.extend(
            [
                V1_PROBABILITY_COLUMNS[
                    target
                ],
                output_column,
                f"{output_column}_p10",
                f"{output_column}_p90",
            ]
        )

    selected_slots = calibrated_curve.loc[
        calibrated_curve[
            "overall_pick"
        ].isin(
            SELECTED_SLOTS
        ),
        selected_audit_columns,
    ].copy()

    calibrated_curve.to_parquet(
        V2_CURVE_PARQUET_PATH,
        index=False,
    )

    calibrated_curve.to_csv(
        V2_CURVE_CSV_PATH,
        index=False,
    )

    validation.to_csv(
        CALIBRATION_VALIDATION_PATH,
        index=False,
    )

    selected_slots.to_csv(
        SELECTED_SLOT_AUDIT_PATH,
        index=False,
    )

    model_bundle = {
        "script_version": (
            SCRIPT_VERSION
        ),
        "selected_parameters": (
            selected_parameters
        ),
        "binary_targets": (
            BINARY_TARGETS
        ),
        "fitted_curves": (
            fitted_curves
        ),
        "parameter_grid_results": (
            parameter_audits
        ),
        "calibrated_slot_curve": (
            calibrated_curve.copy()
        ),
    }

    joblib.dump(
        model_bundle,
        MODEL_PATH,
    )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "draft_classes": int(
            outcomes[
                "draft_year"
            ].nunique()
        ),
        "drafted_players": len(
            outcomes
        ),
        "selected_parameters": (
            selected_parameters
        ),
        "average_validation_metrics": (
            validation.groupby(
                "target"
            )[
                [
                    "brier_score",
                    "log_loss",
                    (
                        "bias_actual_"
                        "minus_prediction"
                    ),
                ]
            ]
            .mean()
            .reset_index()
            .to_dict(
                orient="records"
            )
        ),
        "rating_scale": {
            "minimum": 60,
            "maximum": 99,
            "usage": (
                "Presentation rating for a known draft slot"
            ),
            "optimization_use": (
                "Underlying continuous historical_pick_value_score"
            ),
        },
        "method": {
            "local_smoothing": (
                "Gaussian kernel by overall pick"
            ),
            "prior": (
                "Empirical-Bayes prior centered on the overall "
                "historical outcome rate"
            ),
            "monotonic_constraint": (
                "Isotonic decreasing probability from Pick 1 to Pick 60"
            ),
            "hyperparameter_selection": (
                "Leave-one-draft-class-out mean Brier score"
            ),
        },
        "output_files": {
            "calibrated_curve": str(
                V2_CURVE_PARQUET_PATH
            ),
            "validation": str(
                CALIBRATION_VALIDATION_PATH
            ),
            "selected_slot_audit": str(
                SELECTED_SLOT_AUDIT_PATH
            ),
            "model_bundle": str(
                MODEL_PATH
            ),
        },
    }

    with METADATA_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            json_safe(metadata),
            file,
            indent=2,
        )

    print()
    print("=" * 80)
    print("CALIBRATED HISTORICAL PICK CURVE CREATED")
    print("=" * 80)
    print(
        f"Drafted players: {len(outcomes):,}"
    )
    print(
        "Draft classes: "
        f"{outcomes['draft_year'].nunique():,}"
    )
    print()

    print("SELECTED PARAMETERS")
    parameter_display = pd.DataFrame(
        [
            {
                "target": target,
                **parameters,
            }
            for target, parameters
            in selected_parameters.items()
        ]
    )

    print(
        parameter_display.to_string(
            index=False
        )
    )
    print()

    print("AVERAGE CROSS-VALIDATION METRICS")
    validation_display = (
        validation.groupby(
            "target",
            as_index=False,
        )
        .agg(
            mean_brier_score=(
                "brier_score",
                "mean",
            ),
            mean_log_loss=(
                "log_loss",
                "mean",
            ),
            mean_bias=(
                (
                    "bias_actual_"
                    "minus_prediction"
                ),
                "mean",
            ),
        )
    )

    print(
        validation_display.round(
            4
        ).to_string(
            index=False
        )
    )
    print()

    print("SELECTED SLOT AUDIT")
    display = selected_slots.copy()

    probability_columns = [
        column
        for column in display.columns
        if "probability" in column
    ]

    for column in probability_columns:
        display[column] = (
            numeric_series(
                display,
                column,
            )
            * 100.0
        ).round(2)

    display[
        "historical_pick_value_score"
    ] = numeric_series(
        display,
        "historical_pick_value_score",
    ).round(2)

    print(
        display.to_string(
            index=False
        )
    )
    print()

    print("SAVED FILES")
    print(V2_CURVE_PARQUET_PATH)
    print(V2_CURVE_CSV_PATH)
    print(CALIBRATION_VALIDATION_PATH)
    print(SELECTED_SLOT_AUDIT_PATH)
    print(MODEL_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()