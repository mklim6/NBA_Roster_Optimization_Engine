from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


PROJECT_ROOT = Path(__file__).resolve().parents[1]

PREDICTIONS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "expected_contribution_test_predictions.csv"
)

SURVIVAL_DATA_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "survival_aware_projection_training_data.parquet"
)

OUTPUT_DIRECTORY = (
    PROJECT_ROOT
    / "outputs"
    / "expected_contribution_error_audit"
)

OVERALL_PATH = (
    OUTPUT_DIRECTORY
    / "overall_metrics.csv"
)

AGE_PATH = (
    OUTPUT_DIRECTORY
    / "metrics_by_age_group.csv"
)

MINUTES_PATH = (
    OUTPUT_DIRECTORY
    / "metrics_by_current_minutes_group.csv"
)

IMPACT_PATH = (
    OUTPUT_DIRECTORY
    / "metrics_by_current_impact_group.csv"
)

ROTATION_PATH = (
    OUTPUT_DIRECTORY
    / "metrics_by_current_rotation_status.csv"
)

SURVIVAL_PATH = (
    OUTPUT_DIRECTORY
    / "metrics_by_next_season_survival.csv"
)

COMPONENT_PATH = (
    OUTPUT_DIRECTORY
    / "component_metrics.csv"
)

COMPONENT_BY_AGE_PATH = (
    OUTPUT_DIRECTORY
    / "component_metrics_by_age_group.csv"
)

COMPONENT_BY_MINUTES_PATH = (
    OUTPUT_DIRECTORY
    / "component_metrics_by_current_minutes_group.csv"
)

LARGEST_MISSES_PATH = (
    OUTPUT_DIRECTORY
    / "largest_player_misses.csv"
)

SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "audit_summary.txt"
)

PREDICTED_VS_ACTUAL_PATH = (
    OUTPUT_DIRECTORY
    / "predicted_vs_actual.png"
)

AGE_MAE_CHART_PATH = (
    OUTPUT_DIRECTORY
    / "weighted_mae_by_age_group.png"
)

MINUTES_MAE_CHART_PATH = (
    OUTPUT_DIRECTORY
    / "weighted_mae_by_minutes_group.png"
)

COMPONENT_CHART_PATH = (
    OUTPUT_DIRECTORY
    / "component_error_summary.png"
)


AGE_BINS = [
    0,
    22,
    25,
    28,
    31,
    34,
    37,
    100,
]

AGE_LABELS = [
    "21 and under",
    "22-24",
    "25-27",
    "28-30",
    "31-33",
    "34-36",
    "37+",
]

MINUTES_BINS = [
    -np.inf,
    8,
    12,
    20,
    28,
    34,
    np.inf,
]

MINUTES_LABELS = [
    "Under 8 MPG",
    "8-11.9 MPG",
    "12-19.9 MPG",
    "20-27.9 MPG",
    "28-33.9 MPG",
    "34+ MPG",
]


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


def weighted_mean(
    values: np.ndarray,
    weights: np.ndarray,
) -> float:
    if len(values) == 0:
        return np.nan

    if np.sum(weights) <= 0:
        return float(np.mean(values))

    return float(
        np.average(
            values,
            weights=weights,
        )
    )


def weighted_rmse(
    actual: np.ndarray,
    predicted: np.ndarray,
    weights: np.ndarray,
) -> float:
    squared_error = (
        predicted - actual
    ) ** 2

    return float(
        np.sqrt(
            weighted_mean(
                squared_error,
                weights,
            )
        )
    )


def contribution_metrics(
    frame: pd.DataFrame,
) -> dict[str, float | int]:
    clean = frame.dropna(
        subset=[
            "actual_total_impact_value",
            "projected_final_total_impact",
            "model_sample_weight",
        ]
    ).copy()

    actual = clean[
        "actual_total_impact_value"
    ].to_numpy(dtype=float)

    predicted = clean[
        "projected_final_total_impact"
    ].to_numpy(dtype=float)

    weights = clean[
        "model_sample_weight"
    ].to_numpy(dtype=float)

    residual = predicted - actual
    absolute_error = np.abs(residual)

    if len(clean) == 0:
        return {
            "rows": 0,
            "weighted_mae": np.nan,
            "mae": np.nan,
            "weighted_rmse": np.nan,
            "rmse": np.nan,
            "weighted_bias": np.nan,
            "mean_bias": np.nan,
            "median_absolute_error": np.nan,
            "r_squared": np.nan,
            "spearman_correlation": np.nan,
            "actual_mean": np.nan,
            "predicted_mean": np.nan,
        }

    if (
        len(clean) >= 2
        and np.unique(actual).size >= 2
    ):
        weighted_r_squared = float(
            r2_score(
                actual,
                predicted,
                sample_weight=weights,
            )
        )
    else:
        weighted_r_squared = np.nan

    return {
        "rows": int(len(clean)),
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
        "weighted_rmse": weighted_rmse(
            actual,
            predicted,
            weights,
        ),
        "rmse": float(
            mean_squared_error(
                actual,
                predicted,
            )
            ** 0.5
        ),
        "weighted_bias": weighted_mean(
            residual,
            weights,
        ),
        "mean_bias": float(
            np.mean(residual)
        ),
        "median_absolute_error": float(
            np.median(absolute_error)
        ),
        "r_squared": weighted_r_squared,
        "spearman_correlation": safe_spearman(
            actual,
            predicted,
        ),
        "actual_mean": weighted_mean(
            actual,
            weights,
        ),
        "predicted_mean": weighted_mean(
            predicted,
            weights,
        ),
    }


def grouped_contribution_metrics(
    frame: pd.DataFrame,
    group_column: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    for group_value, group in frame.groupby(
        group_column,
        observed=False,
        dropna=False,
    ):
        metrics = contribution_metrics(group)

        rows.append(
            {
                group_column: str(group_value),
                **metrics,
            }
        )

    return pd.DataFrame(rows)


def brier_score(
    actual: np.ndarray,
    probability: np.ndarray,
    weights: np.ndarray,
) -> float:
    return weighted_mean(
        (
            probability
            - actual
        )
        ** 2,
        weights,
    )


def component_metrics(
    frame: pd.DataFrame,
    group_name: str = "Overall",
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    survival_clean = frame.dropna(
        subset=[
            "next_season_active_flag",
            "projected_survival_probability",
            "model_sample_weight",
        ]
    )

    survival_actual = survival_clean[
        "next_season_active_flag"
    ].to_numpy(dtype=float)

    survival_probability = survival_clean[
        "projected_survival_probability"
    ].to_numpy(dtype=float)

    survival_weights = survival_clean[
        "model_sample_weight"
    ].to_numpy(dtype=float)

    rows.append(
        {
            "group": group_name,
            "component": "Survival probability",
            "rows": len(survival_clean),
            "primary_metric": "Weighted Brier score",
            "primary_value": brier_score(
                survival_actual,
                survival_probability,
                survival_weights,
            ),
            "weighted_bias": weighted_mean(
                (
                    survival_probability
                    - survival_actual
                ),
                survival_weights,
            ),
            "spearman_correlation": safe_spearman(
                survival_actual,
                survival_probability,
            ),
        }
    )

    active = frame.loc[
        frame[
            "next_season_active_flag"
        ].eq(1)
    ].copy()

    component_specs = [
        (
            "Conditional minutes",
            "next_minutes_per_game_if_active",
            "projected_conditional_minutes_per_game",
            "Weighted MAE",
        ),
        (
            "Conditional availability",
            "next_availability_rate_if_active",
            "projected_conditional_availability_rate",
            "Weighted MAE",
        ),
        (
            "Conditional PIE",
            "next_advanced_pie_if_active",
            "projected_conditional_pie",
            "Weighted MAE",
        ),
    ]

    for (
        component_name,
        actual_column,
        prediction_column,
        metric_name,
    ) in component_specs:
        clean = active.dropna(
            subset=[
                actual_column,
                prediction_column,
                "model_sample_weight",
            ]
        )

        actual = clean[
            actual_column
        ].to_numpy(dtype=float)

        predicted = clean[
            prediction_column
        ].to_numpy(dtype=float)

        weights = clean[
            "model_sample_weight"
        ].to_numpy(dtype=float)

        if len(clean) == 0:
            primary_value = np.nan
            bias = np.nan
            correlation = np.nan
        else:
            primary_value = float(
                mean_absolute_error(
                    actual,
                    predicted,
                    sample_weight=weights,
                )
            )

            bias = weighted_mean(
                predicted - actual,
                weights,
            )

            correlation = safe_spearman(
                actual,
                predicted,
            )

        rows.append(
            {
                "group": group_name,
                "component": component_name,
                "rows": len(clean),
                "primary_metric": metric_name,
                "primary_value": primary_value,
                "weighted_bias": bias,
                "spearman_correlation": correlation,
            }
        )

    return pd.DataFrame(rows)


def grouped_component_metrics(
    frame: pd.DataFrame,
    group_column: str,
) -> pd.DataFrame:
    outputs: list[pd.DataFrame] = []

    for group_value, group in frame.groupby(
        group_column,
        observed=False,
        dropna=False,
    ):
        output = component_metrics(
            group,
            group_name=str(group_value),
        )

        output.insert(
            0,
            group_column,
            str(group_value),
        )

        outputs.append(output)

    return pd.concat(
        outputs,
        ignore_index=True,
    )


def build_current_impact_groups(
    frame: pd.DataFrame,
) -> pd.Series:
    current_impact = frame[
        "current_total_impact_value"
    ].astype(float)

    try:
        buckets = pd.qcut(
            current_impact,
            q=5,
            duplicates="drop",
        )

        return buckets.astype(str)

    except ValueError:
        return pd.cut(
            current_impact,
            bins=5,
            include_lowest=True,
        ).astype(str)


def save_predicted_vs_actual_chart(
    frame: pd.DataFrame,
) -> None:
    clean = frame.dropna(
        subset=[
            "actual_total_impact_value",
            "projected_final_total_impact",
        ]
    )

    actual = clean[
        "actual_total_impact_value"
    ].to_numpy(dtype=float)

    predicted = clean[
        "projected_final_total_impact"
    ].to_numpy(dtype=float)

    minimum = float(
        min(
            np.min(actual),
            np.min(predicted),
        )
    )

    maximum = float(
        max(
            np.max(actual),
            np.max(predicted),
        )
    )

    figure, axis = plt.subplots(
        figsize=(8, 6)
    )

    axis.scatter(
        actual,
        predicted,
        alpha=0.55,
    )

    axis.plot(
        [minimum, maximum],
        [minimum, maximum],
        linestyle="--",
    )

    axis.set_xlabel(
        "Actual next-season total impact"
    )

    axis.set_ylabel(
        "Projected next-season total impact"
    )

    axis.set_title(
        "Projected vs. Actual Next-Season Contribution"
    )

    figure.tight_layout()

    figure.savefig(
        PREDICTED_VS_ACTUAL_PATH,
        dpi=180,
    )

    plt.close(figure)


def save_group_mae_chart(
    metrics: pd.DataFrame,
    group_column: str,
    title: str,
    output_path: Path,
) -> None:
    clean = metrics.dropna(
        subset=["weighted_mae"]
    )

    figure, axis = plt.subplots(
        figsize=(9, 5)
    )

    axis.bar(
        clean[group_column].astype(str),
        clean["weighted_mae"],
    )

    axis.set_xlabel(
        group_column.replace(
            "_",
            " ",
        ).title()
    )

    axis.set_ylabel(
        "Weighted MAE"
    )

    axis.set_title(title)

    axis.tick_params(
        axis="x",
        rotation=35,
    )

    figure.tight_layout()

    figure.savefig(
        output_path,
        dpi=180,
    )

    plt.close(figure)


def save_component_chart(
    metrics: pd.DataFrame,
) -> None:
    clean = metrics.dropna(
        subset=["primary_value"]
    )

    figure, axis = plt.subplots(
        figsize=(9, 5)
    )

    axis.bar(
        clean["component"],
        clean["primary_value"],
    )

    axis.set_xlabel("Component")
    axis.set_ylabel("Primary error metric")
    axis.set_title(
        "End-to-End Projection Component Errors"
    )

    axis.tick_params(
        axis="x",
        rotation=25,
    )

    figure.tight_layout()

    figure.savefig(
        COMPONENT_CHART_PATH,
        dpi=180,
    )

    plt.close(figure)


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not PREDICTIONS_PATH.exists():
        raise FileNotFoundError(
            "Expected-contribution predictions were not found at:\n"
            f"{PREDICTIONS_PATH}"
        )

    if not SURVIVAL_DATA_PATH.exists():
        raise FileNotFoundError(
            "Survival-aware modeling data was not found at:\n"
            f"{SURVIVAL_DATA_PATH}"
        )

    predictions = pd.read_csv(
        PREDICTIONS_PATH
    )

    source = pd.read_parquet(
        SURVIVAL_DATA_PATH
    )

    source_columns = [
        "player_id",
        "season",
        "age",
        "minutes_per_game",
        "total_minutes",
        "availability_rate",
        "advanced_pie",
        "rotation_player_flag",
        "sample_reliability",
        "next_minutes_per_game_if_active",
        "next_availability_rate_if_active",
        "next_advanced_pie_if_active",
    ]

    missing_source_columns = [
        column
        for column in source_columns
        if column not in source.columns
    ]

    if missing_source_columns:
        raise ValueError(
            "The survival-aware data is missing columns:\n"
            + "\n".join(
                missing_source_columns
            )
        )

    audit = predictions.merge(
        source[source_columns],
        how="left",
        on=[
            "player_id",
            "season",
        ],
        validate="one_to_one",
    )

    required_prediction_columns = [
        "actual_total_impact_value",
        "projected_final_total_impact",
        "projected_staged_total_impact",
        "projected_direct_total_impact",
        "persistence_total_impact",
        "projected_survival_probability",
        "projected_conditional_minutes_per_game",
        "projected_conditional_availability_rate",
        "projected_conditional_pie",
        "next_season_active_flag",
        "next_rotation_player_flag",
        "model_sample_weight",
    ]

    missing_prediction_columns = [
        column
        for column in required_prediction_columns
        if column not in audit.columns
    ]

    if missing_prediction_columns:
        raise ValueError(
            "The expected-contribution predictions are missing columns:\n"
            + "\n".join(
                missing_prediction_columns
            )
        )

    audit["current_total_impact_value"] = (
        pd.to_numeric(
            audit["advanced_pie"],
            errors="coerce",
        )
        .fillna(0.0)
        * pd.to_numeric(
            audit["total_minutes"],
            errors="coerce",
        )
        .fillna(0.0)
    )

    audit["residual"] = (
        audit[
            "projected_final_total_impact"
        ]
        - audit[
            "actual_total_impact_value"
        ]
    )

    audit["absolute_error"] = (
        audit["residual"].abs()
    )

    audit["error_direction"] = np.where(
        audit["residual"] > 0,
        "Overprediction",
        np.where(
            audit["residual"] < 0,
            "Underprediction",
            "Exact",
        ),
    )

    audit["age_group"] = pd.cut(
        audit["age"],
        bins=AGE_BINS,
        labels=AGE_LABELS,
        right=False,
        include_lowest=True,
    )

    audit["current_minutes_group"] = pd.cut(
        audit["minutes_per_game"],
        bins=MINUTES_BINS,
        labels=MINUTES_LABELS,
        right=False,
        include_lowest=True,
    )

    audit["current_impact_group"] = (
        build_current_impact_groups(
            audit
        )
    )

    audit["current_rotation_status"] = np.where(
        audit[
            "rotation_player_flag"
        ].eq(1),
        "Current rotation player",
        "Current non-rotation player",
    )

    audit["next_survival_status"] = np.where(
        audit[
            "next_season_active_flag"
        ].eq(1),
        "Returned next season",
        "Did not return next season",
    )

    overall = pd.DataFrame(
        [
            {
                "group": "Overall",
                **contribution_metrics(audit),
            }
        ]
    )

    age_metrics = grouped_contribution_metrics(
        audit,
        "age_group",
    )

    minutes_metrics = (
        grouped_contribution_metrics(
            audit,
            "current_minutes_group",
        )
    )

    impact_metrics = (
        grouped_contribution_metrics(
            audit,
            "current_impact_group",
        )
    )

    rotation_metrics = (
        grouped_contribution_metrics(
            audit,
            "current_rotation_status",
        )
    )

    survival_metrics = (
        grouped_contribution_metrics(
            audit,
            "next_survival_status",
        )
    )

    components = component_metrics(audit)

    components_by_age = (
        grouped_component_metrics(
            audit,
            "age_group",
        )
    )

    components_by_minutes = (
        grouped_component_metrics(
            audit,
            "current_minutes_group",
        )
    )

    largest_misses = audit.sort_values(
        "absolute_error",
        ascending=False,
    )[
        [
            "player_id",
            "player_name",
            "season",
            "target_season",
            "team_abbreviation",
            "age",
            "minutes_per_game",
            "rotation_player_flag",
            "next_season_active_flag",
            "next_rotation_player_flag",
            "actual_total_impact_value",
            "projected_final_total_impact",
            "projected_staged_total_impact",
            "projected_direct_total_impact",
            "persistence_total_impact",
            "residual",
            "absolute_error",
            "error_direction",
            "projected_survival_probability",
            "projected_conditional_minutes_per_game",
            "projected_conditional_availability_rate",
            "projected_conditional_pie",
            "next_minutes_per_game_if_active",
            "next_availability_rate_if_active",
            "next_advanced_pie_if_active",
        ]
    ].head(75)

    overall.to_csv(
        OVERALL_PATH,
        index=False,
    )

    age_metrics.to_csv(
        AGE_PATH,
        index=False,
    )

    minutes_metrics.to_csv(
        MINUTES_PATH,
        index=False,
    )

    impact_metrics.to_csv(
        IMPACT_PATH,
        index=False,
    )

    rotation_metrics.to_csv(
        ROTATION_PATH,
        index=False,
    )

    survival_metrics.to_csv(
        SURVIVAL_PATH,
        index=False,
    )

    components.to_csv(
        COMPONENT_PATH,
        index=False,
    )

    components_by_age.to_csv(
        COMPONENT_BY_AGE_PATH,
        index=False,
    )

    components_by_minutes.to_csv(
        COMPONENT_BY_MINUTES_PATH,
        index=False,
    )

    largest_misses.to_csv(
        LARGEST_MISSES_PATH,
        index=False,
    )

    save_predicted_vs_actual_chart(
        audit
    )

    save_group_mae_chart(
        age_metrics,
        "age_group",
        "Weighted Contribution Error by Age Group",
        AGE_MAE_CHART_PATH,
    )

    save_group_mae_chart(
        minutes_metrics,
        "current_minutes_group",
        "Weighted Contribution Error by Current Workload",
        MINUTES_MAE_CHART_PATH,
    )

    save_component_chart(
        components
    )

    overall_row = overall.iloc[0]

    worst_age = (
        age_metrics.sort_values(
            "weighted_mae",
            ascending=False,
        )
        .iloc[0]
    )

    worst_minutes = (
        minutes_metrics.sort_values(
            "weighted_mae",
            ascending=False,
        )
        .iloc[0]
    )

    worst_survival = (
        survival_metrics.sort_values(
            "weighted_mae",
            ascending=False,
        )
        .iloc[0]
    )

    overprediction_rate = float(
        audit["residual"].gt(0).mean()
    )

    top_overprediction = (
        audit.sort_values(
            "residual",
            ascending=False,
        )
        .iloc[0]
    )

    top_underprediction = (
        audit.sort_values(
            "residual",
            ascending=True,
        )
        .iloc[0]
    )

    summary_lines = [
        "EXPECTED CONTRIBUTION ERROR AUDIT",
        "=" * 50,
        "",
        (
            "Overall weighted MAE: "
            f"{overall_row['weighted_mae']:.4f}"
        ),
        (
            "Overall weighted bias: "
            f"{overall_row['weighted_bias']:.4f}"
        ),
        (
            "Overall R-squared: "
            f"{overall_row['r_squared']:.4f}"
        ),
        (
            "Overall Spearman correlation: "
            f"{overall_row['spearman_correlation']:.4f}"
        ),
        (
            "Share of players overpredicted: "
            f"{overprediction_rate:.2%}"
        ),
        "",
        (
            "Highest-error age group: "
            f"{worst_age['age_group']} "
            f"(weighted MAE "
            f"{worst_age['weighted_mae']:.4f})"
        ),
        (
            "Highest-error workload group: "
            f"{worst_minutes['current_minutes_group']} "
            f"(weighted MAE "
            f"{worst_minutes['weighted_mae']:.4f})"
        ),
        (
            "Highest-error survival group: "
            f"{worst_survival['next_survival_status']} "
            f"(weighted MAE "
            f"{worst_survival['weighted_mae']:.4f})"
        ),
        "",
        (
            "Largest overprediction: "
            f"{top_overprediction['player_name']} "
            f"({top_overprediction['residual']:.4f})"
        ),
        (
            "Largest underprediction: "
            f"{top_underprediction['player_name']} "
            f"({top_underprediction['residual']:.4f})"
        ),
        "",
        "Review the saved group and component tables before changing the model.",
    ]

    SUMMARY_PATH.write_text(
        "\n".join(summary_lines),
        encoding="utf-8",
    )

    print("=" * 80)
    print("EXPECTED CONTRIBUTION ERROR AUDIT COMPLETED")
    print("=" * 80)
    print(
        f"Players audited: {len(audit):,}"
    )
    print(
        "Overall weighted MAE: "
        f"{overall_row['weighted_mae']:.4f}"
    )
    print(
        "Overall weighted bias: "
        f"{overall_row['weighted_bias']:.4f}"
    )
    print(
        "Worst age group: "
        f"{worst_age['age_group']} "
        f"(MAE {worst_age['weighted_mae']:.4f})"
    )
    print(
        "Worst workload group: "
        f"{worst_minutes['current_minutes_group']} "
        f"(MAE {worst_minutes['weighted_mae']:.4f})"
    )
    print(
        "Worst survival group: "
        f"{worst_survival['next_survival_status']} "
        f"(MAE {worst_survival['weighted_mae']:.4f})"
    )
    print()
    print("SAVED AUDIT DIRECTORY")
    print(OUTPUT_DIRECTORY)


if __name__ == "__main__":
    main()