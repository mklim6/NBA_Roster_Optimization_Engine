from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]

BOARD_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "current_player_projection_board_2025_26_to_2026_27.csv"
)

CONFIRMATION_PREDICTIONS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "contribution_uncertainty"
    / "confirmation_interval_predictions.csv"
)

CONFIRMATION_METRICS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "contribution_uncertainty"
    / "confirmation_interval_metrics.csv"
)

OUTPUT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "current_player_projection_board_audit.csv"
)

Q10_DIAGNOSTICS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "current_player_projection_board_q10_diagnostics.csv"
)


def numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        raise ValueError(f"Missing required column: {column}")

    return pd.to_numeric(
        frame[column],
        errors="coerce",
    )


def series_metrics(
    name: str,
    values: pd.Series,
) -> dict[str, float | int | str]:
    clean = values.dropna().astype(float)

    if clean.empty:
        return {
            "metric_group": name,
            "rows": 0,
            "missing": int(values.isna().sum()),
            "unique_values": 0,
            "minimum": np.nan,
            "p10": np.nan,
            "median": np.nan,
            "p90": np.nan,
            "maximum": np.nan,
            "zero_count": 0,
            "zero_rate": np.nan,
            "negative_count": 0,
            "negative_rate": np.nan,
        }

    zero_mask = np.isclose(
        clean.to_numpy(dtype=float),
        0.0,
        atol=1e-9,
    )
    negative_mask = clean.to_numpy(dtype=float) < -1e-9

    return {
        "metric_group": name,
        "rows": int(len(clean)),
        "missing": int(values.isna().sum()),
        "unique_values": int(clean.nunique()),
        "minimum": float(clean.min()),
        "p10": float(clean.quantile(0.10)),
        "median": float(clean.median()),
        "p90": float(clean.quantile(0.90)),
        "maximum": float(clean.max()),
        "zero_count": int(zero_mask.sum()),
        "zero_rate": float(zero_mask.mean()),
        "negative_count": int(negative_mask.sum()),
        "negative_rate": float(negative_mask.mean()),
    }


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


def main() -> None:
    if not BOARD_PATH.exists():
        raise FileNotFoundError(
            "Projection board was not found at:\n"
            f"{BOARD_PATH}"
        )

    board = pd.read_csv(BOARD_PATH)

    required_board_columns = [
        "player_id",
        "player_name",
        "team_abbreviation",
        "projected_expected_contribution",
        "projected_contribution_q10",
        "projected_contribution_q50",
        "projected_contribution_q90",
        "projected_downside_contribution_80",
        "projected_upside_contribution_80",
        "projection_interval_width_80",
        "projected_survival_probability",
        "projected_rotation_probability",
        "point_outside_80_interval_flag",
        "main_pool_eligible",
    ]

    require_columns(
        board,
        required_board_columns,
        "Projection board",
    )

    duplicate_players = int(
        board.duplicated(
            subset=["player_id"],
            keep=False,
        ).sum()
    )

    expected = numeric_series(
        board,
        "projected_expected_contribution",
    )
    q10 = numeric_series(
        board,
        "projected_contribution_q10",
    )
    q50 = numeric_series(
        board,
        "projected_contribution_q50",
    )
    q90 = numeric_series(
        board,
        "projected_contribution_q90",
    )
    lower_80 = numeric_series(
        board,
        "projected_downside_contribution_80",
    )
    upper_80 = numeric_series(
        board,
        "projected_upside_contribution_80",
    )
    width_80 = numeric_series(
        board,
        "projection_interval_width_80",
    )

    crossing_violations = int(
        (
            (q10 > q50 + 1e-9)
            | (q50 > q90 + 1e-9)
        ).sum()
    )

    invalid_intervals = int(
        (lower_80 > upper_80 + 1e-9).sum()
    )

    point_outside = int(
        pd.to_numeric(
            board["point_outside_80_interval_flag"],
            errors="coerce",
        )
        .fillna(0)
        .astype(int)
        .sum()
    )

    q10_zero_mask = np.isclose(
        q10.fillna(np.nan).to_numpy(dtype=float),
        0.0,
        atol=1e-9,
        equal_nan=False,
    )

    q10_diagnostics = board[
        [
            "player_id",
            "player_name",
            "team_abbreviation",
            "main_pool_eligible",
        ]
    ].copy()

    q10_diagnostics[
        "projected_expected_contribution"
    ] = expected
    q10_diagnostics["projected_q10"] = q10
    q10_diagnostics["projected_q50"] = q50
    q10_diagnostics["projected_q90"] = q90
    q10_diagnostics["lower_80"] = lower_80
    q10_diagnostics["upper_80"] = upper_80
    q10_diagnostics["interval_width_80"] = width_80
    q10_diagnostics["q10_is_zero"] = q10_zero_mask

    q10_diagnostics[
        "expected_contribution_quartile"
    ] = pd.qcut(
        expected.rank(method="first"),
        q=4,
        labels=[
            "Q1 lowest",
            "Q2",
            "Q3",
            "Q4 highest",
        ],
    )

    quartile_summary = (
        q10_diagnostics.groupby(
            "expected_contribution_quartile",
            observed=True,
            as_index=False,
        )
        .agg(
            players=("player_id", "size"),
            q10_zero_rate=("q10_is_zero", "mean"),
            average_expected_contribution=(
                "projected_expected_contribution",
                "mean",
            ),
            average_q10=("projected_q10", "mean"),
            average_q50=("projected_q50", "mean"),
            average_q90=("projected_q90", "mean"),
            average_interval_width_80=(
                "interval_width_80",
                "mean",
            ),
        )
    )

    audit_rows: list[dict[str, float | int | str]] = [
        {
            "metric_group": "board_structure",
            "rows": int(len(board)),
            "missing": int(board.isna().sum().sum()),
            "unique_values": int(
                board["player_id"].nunique()
            ),
            "minimum": duplicate_players,
            "p10": int(
                board["team_abbreviation"].nunique()
            ),
            "median": int(
                pd.Series(
                    board["main_pool_eligible"]
                )
                .fillna(False)
                .astype(bool)
                .sum()
            ),
            "p90": crossing_violations,
            "maximum": invalid_intervals,
            "zero_count": point_outside,
            "zero_rate": (
                point_outside / len(board)
                if len(board)
                else np.nan
            ),
            "negative_count": 0,
            "negative_rate": 0.0,
        },
        series_metrics("current_expected", expected),
        series_metrics("current_q10", q10),
        series_metrics("current_q50", q50),
        series_metrics("current_q90", q90),
        series_metrics("current_lower_80", lower_80),
        series_metrics("current_upper_80", upper_80),
        series_metrics("current_width_80", width_80),
    ]

    confirmation_available = (
        CONFIRMATION_PREDICTIONS_PATH.exists()
    )

    if confirmation_available:
        confirmation = pd.read_csv(
            CONFIRMATION_PREDICTIONS_PATH
        )

        for column in [
            "q10",
            "q50",
            "q90",
            "lower_80",
            "upper_80",
            "interval_width_80",
        ]:
            if column in confirmation.columns:
                audit_rows.append(
                    series_metrics(
                        f"confirmation_{column}",
                        numeric_series(
                            confirmation,
                            column,
                        ),
                    )
                )

    audit = pd.DataFrame(audit_rows)

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    audit.to_csv(
        OUTPUT_PATH,
        index=False,
    )

    q10_diagnostics.to_csv(
        Q10_DIAGNOSTICS_PATH,
        index=False,
    )

    print("=" * 80)
    print("CURRENT PLAYER PROJECTION BOARD AUDIT")
    print("=" * 80)
    print(f"Rows: {len(board):,}")
    print(
        "Unique players: "
        f"{board['player_id'].nunique():,}"
    )
    print(
        "Teams: "
        f"{board['team_abbreviation'].nunique():,}"
    )
    print(
        "Duplicate player IDs: "
        f"{duplicate_players:,}"
    )
    print(
        "Quantile-order violations: "
        f"{crossing_violations:,}"
    )
    print(
        "Invalid 80% intervals: "
        f"{invalid_intervals:,}"
    )
    print(
        "Point estimates outside 80% interval: "
        f"{point_outside:,}"
    )
    print()

    print("CURRENT-BOARD QUANTILE SUMMARY")
    current_display = audit.loc[
        audit["metric_group"].isin(
            [
                "current_expected",
                "current_q10",
                "current_q50",
                "current_q90",
                "current_lower_80",
                "current_upper_80",
                "current_width_80",
            ]
        )
    ]
    print(
        current_display[
            [
                "metric_group",
                "rows",
                "unique_values",
                "minimum",
                "median",
                "maximum",
                "zero_count",
                "zero_rate",
                "negative_count",
            ]
        ].to_string(index=False)
    )
    print()

    print("Q10 ZERO RATE BY EXPECTED-CONTRIBUTION QUARTILE")
    print(
        quartile_summary.to_string(
            index=False,
        )
    )
    print()

    if confirmation_available:
        confirmation_display = audit.loc[
            audit["metric_group"].str.startswith(
                "confirmation_",
                na=False,
            )
        ]
        print("HELD-OUT CONFIRMATION QUANTILE SUMMARY")
        print(
            confirmation_display[
                [
                    "metric_group",
                    "rows",
                    "unique_values",
                    "minimum",
                    "median",
                    "maximum",
                    "zero_count",
                    "zero_rate",
                    "negative_count",
                ]
            ].to_string(index=False)
        )
        print()
    else:
        print(
            "Held-out confirmation predictions were "
            "not found, so that comparison was skipped."
        )
        print()

    if CONFIRMATION_METRICS_PATH.exists():
        metrics = pd.read_csv(
            CONFIRMATION_METRICS_PATH
        )
        print("HELD-OUT INTERVAL METRICS")
        print(metrics.to_string(index=False))
        print()

    current_q10_zero_rate = float(
        np.mean(q10_zero_mask)
    )
    current_negative_lower_rate = float(
        (lower_80 < -1e-9).mean()
    )

    print("AUDIT INTERPRETATION")
    if current_negative_lower_rate > 0:
        print(
            "- Negative lower bounds exist even though "
            "the contribution target is nonnegative. "
            "The published board should clamp lower "
            "bounds to zero."
        )
    else:
        print(
            "- No negative lower bounds were found."
        )

    if current_q10_zero_rate >= 0.50:
        print(
            "- The q10 projection is zero for at least "
            "half of current players. This indicates "
            "lower-quantile collapse and makes the "
            "downside ranking weak."
        )
    else:
        print(
            "- The q10 projection retains meaningful "
            "variation for most players."
        )

    print()
    print("SAVED FILES")
    print(OUTPUT_PATH)
    print(Q10_DIAGNOSTICS_PATH)


if __name__ == "__main__":
    main()