from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]

INPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "unified_player_seasons_2014_15_2025_26.parquet"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "data" / "processed"

OUTPUT_PARQUET_PATH = (
    OUTPUT_DIRECTORY
    / "survival_aware_projection_training_data.parquet"
)

OUTPUT_CSV_PATH = (
    OUTPUT_DIRECTORY
    / "survival_aware_projection_training_data.csv"
)

SUMMARY_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "survival_aware_projection_data_summary.csv"
)


NEXT_SEASON_SOURCE_COLUMNS = [
    "season",
    "season_start",
    "team_id",
    "team_abbreviation",
    "games_played",
    "total_minutes",
    "minutes_per_game",
    "availability_rate",
    "minutes_availability_value",
    "advanced_off_rating",
    "advanced_def_rating",
    "advanced_net_rating",
    "advanced_efg_pct",
    "advanced_ts_pct",
    "advanced_usg_pct",
    "advanced_pie",
    "advanced_poss",
    "rotation_player_flag",
    "high_minutes_flag",
]


def require_columns(
    frame: pd.DataFrame,
    required_columns: list[str],
) -> None:
    missing_columns = [
        column
        for column in required_columns
        if column not in frame.columns
    ]

    if missing_columns:
        raise ValueError(
            "The unified player-season dataset is missing required columns:\n"
            + "\n".join(missing_columns)
        )


def season_label_from_start(
    season_start: int,
) -> str:
    return (
        f"{season_start}-"
        f"{str(season_start + 1)[-2:]}"
    )


def load_unified_data() -> pd.DataFrame:
    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            "The unified player-season file was not found at:\n"
            f"{INPUT_PATH}"
        )

    frame = pd.read_parquet(INPUT_PATH)

    if frame.empty:
        raise ValueError(
            "The unified player-season file is empty."
        )

    required_columns = [
        "player_id",
        "player_name",
        "season",
        "season_start",
        "team_id",
        "team_abbreviation",
        "sample_reliability",
        *NEXT_SEASON_SOURCE_COLUMNS,
    ]

    require_columns(
        frame,
        sorted(set(required_columns)),
    )

    frame = frame.copy()

    frame["player_id"] = pd.to_numeric(
        frame["player_id"],
        errors="raise",
    ).astype("int64")

    frame["season_start"] = pd.to_numeric(
        frame["season_start"],
        errors="raise",
    ).astype(int)

    duplicate_mask = frame.duplicated(
        subset=["player_id", "season_start"],
        keep=False,
    )

    if duplicate_mask.any():
        duplicates = frame.loc[
            duplicate_mask,
            [
                "player_id",
                "player_name",
                "season",
                "team_abbreviation",
            ],
        ]

        raise ValueError(
            "Duplicate player-season rows were found:\n"
            f"{duplicates.to_string(index=False)}"
        )

    return frame.sort_values(
        ["season_start", "player_id"]
    ).reset_index(drop=True)


def build_survival_aware_transitions(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    latest_season_start = int(
        frame["season_start"].max()
    )

    current = frame.loc[
        frame["season_start"] < latest_season_start
    ].copy()

    next_frame = frame[
        [
            "player_id",
            *NEXT_SEASON_SOURCE_COLUMNS,
        ]
    ].copy()

    next_frame = next_frame.rename(
        columns={
            column: f"observed_next_{column}"
            for column in NEXT_SEASON_SOURCE_COLUMNS
        }
    )

    next_frame["season_start"] = (
        next_frame["observed_next_season_start"]
        - 1
    )

    transitions = current.merge(
        next_frame,
        how="left",
        on=[
            "player_id",
            "season_start",
        ],
        validate="one_to_one",
    )

    transitions["target_season_start"] = (
        transitions["season_start"] + 1
    )

    transitions["target_season"] = (
        transitions["target_season_start"]
        .map(season_label_from_start)
    )

    transitions["next_season_active_flag"] = (
        transitions["observed_next_season"]
        .notna()
        .astype(int)
    )

    active_mask = (
        transitions["next_season_active_flag"]
        .eq(1)
    )

    observed_next_start = pd.to_numeric(
        transitions[
            "observed_next_season_start"
        ],
        errors="coerce",
    )

    invalid_active_rows = (
        active_mask
        & observed_next_start.ne(
            transitions[
                "target_season_start"
            ]
        )
    )

    if invalid_active_rows.any():
        invalid = transitions.loc[
            invalid_active_rows,
            [
                "player_id",
                "player_name",
                "season",
                "observed_next_season",
            ],
        ]

        raise ValueError(
            "A player was matched to a non-consecutive future season:\n"
            f"{invalid.to_string(index=False)}"
        )

    conditional_mapping = {
        "minutes_per_game": (
            "next_minutes_per_game_if_active"
        ),
        "availability_rate": (
            "next_availability_rate_if_active"
        ),
        "advanced_pie": (
            "next_advanced_pie_if_active"
        ),
        "advanced_off_rating": (
            "next_advanced_off_rating_if_active"
        ),
        "advanced_def_rating": (
            "next_advanced_def_rating_if_active"
        ),
        "advanced_net_rating": (
            "next_advanced_net_rating_if_active"
        ),
        "advanced_efg_pct": (
            "next_advanced_efg_pct_if_active"
        ),
        "advanced_ts_pct": (
            "next_advanced_ts_pct_if_active"
        ),
        "advanced_usg_pct": (
            "next_advanced_usg_pct_if_active"
        ),
    }

    for source_suffix, output_column in (
        conditional_mapping.items()
    ):
        source_column = (
            f"observed_next_{source_suffix}"
        )

        transitions[output_column] = (
            pd.to_numeric(
                transitions[source_column],
                errors="coerce",
            )
            .where(active_mask)
        )

    zeroed_mapping = {
        "games_played": "next_games_played",
        "total_minutes": "next_total_minutes",
        "minutes_per_game": (
            "next_expected_minutes_per_game"
        ),
        "availability_rate": (
            "next_expected_availability_rate"
        ),
        "minutes_availability_value": (
            "next_minutes_availability_value"
        ),
        "advanced_poss": "next_expected_possessions",
        "rotation_player_flag": (
            "next_rotation_player_flag"
        ),
        "high_minutes_flag": (
            "next_high_minutes_flag"
        ),
    }

    for source_suffix, output_column in (
        zeroed_mapping.items()
    ):
        source_column = (
            f"observed_next_{source_suffix}"
        )

        transitions[output_column] = (
            pd.to_numeric(
                transitions[source_column],
                errors="coerce",
            )
            .where(active_mask, 0.0)
            .fillna(0.0)
        )

    transitions["next_impact_workload_value"] = (
        transitions[
            "next_advanced_pie_if_active"
        ]
        .fillna(0.0)
        * transitions[
            "next_expected_minutes_per_game"
        ]
        * transitions[
            "next_expected_availability_rate"
        ]
    )

    transitions["next_total_impact_value"] = (
        transitions[
            "next_advanced_pie_if_active"
        ]
        .fillna(0.0)
        * transitions["next_total_minutes"]
    )

    transitions["training_sample_weight"] = (
        0.25
        + 0.75
        * pd.to_numeric(
            transitions["sample_reliability"],
            errors="coerce",
        )
        .fillna(0.0)
        .clip(lower=0.0, upper=1.0)
    )

    transitions[
        "survival_training_sample_weight"
    ] = 1.0

    transitions[
        "conditional_training_sample_weight"
    ] = transitions[
        "training_sample_weight"
    ].where(
        active_mask,
        np.nan,
    )

    observed_next_columns = [
        column
        for column in transitions.columns
        if column.startswith("observed_next_")
    ]

    transitions = transitions.drop(
        columns=observed_next_columns
    )

    transitions = transitions.sort_values(
        [
            "season_start",
            "player_name",
        ]
    ).reset_index(drop=True)

    return transitions


def validate_transitions(
    transitions: pd.DataFrame,
) -> None:
    duplicate_mask = transitions.duplicated(
        subset=[
            "player_id",
            "season_start",
        ],
        keep=False,
    )

    if duplicate_mask.any():
        raise ValueError(
            "Duplicate survival-aware transitions were created."
        )

    required_complete_columns = [
        "player_id",
        "player_name",
        "season",
        "target_season",
        "next_season_active_flag",
        "next_games_played",
        "next_total_minutes",
        "next_expected_minutes_per_game",
        "next_expected_availability_rate",
        "next_rotation_player_flag",
        "next_high_minutes_flag",
        "next_impact_workload_value",
        "next_total_impact_value",
        "training_sample_weight",
        "survival_training_sample_weight",
    ]

    incomplete = (
        transitions[
            required_complete_columns
        ]
        .isna()
        .sum()
    )

    if incomplete.any():
        raise ValueError(
            "Required survival-aware targets contain missing values:\n"
            f"{incomplete[incomplete > 0]}"
        )

    active_rows = transitions.loc[
        transitions[
            "next_season_active_flag"
        ].eq(1)
    ]

    conditional_columns = [
        "next_minutes_per_game_if_active",
        "next_availability_rate_if_active",
        "next_advanced_pie_if_active",
    ]

    conditional_missing = (
        active_rows[
            conditional_columns
        ]
        .isna()
        .sum()
    )

    if conditional_missing.any():
        raise ValueError(
            "Active players have missing conditional targets:\n"
            f"{conditional_missing[conditional_missing > 0]}"
        )

    inactive_rows = transitions.loc[
        transitions[
            "next_season_active_flag"
        ].eq(0)
    ]

    zero_columns = [
        "next_games_played",
        "next_total_minutes",
        "next_expected_minutes_per_game",
        "next_expected_availability_rate",
        "next_rotation_player_flag",
        "next_high_minutes_flag",
        "next_impact_workload_value",
        "next_total_impact_value",
    ]

    nonzero_inactive = (
        inactive_rows[
            zero_columns
        ]
        .abs()
        .gt(1e-12)
        .any(axis=1)
    )

    if nonzero_inactive.any():
        raise ValueError(
            "Inactive next-season players received nonzero outcomes."
        )


def build_summary(
    transitions: pd.DataFrame,
) -> pd.DataFrame:
    summary = (
        transitions.groupby(
            [
                "season",
                "target_season",
            ],
            as_index=False,
        )
        .agg(
            current_player_rows=(
                "player_id",
                "size",
            ),
            next_season_active_players=(
                "next_season_active_flag",
                "sum",
            ),
            next_rotation_players=(
                "next_rotation_player_flag",
                "sum",
            ),
            next_high_minutes_players=(
                "next_high_minutes_flag",
                "sum",
            ),
            average_next_total_minutes=(
                "next_total_minutes",
                "mean",
            ),
            average_next_impact_workload=(
                "next_impact_workload_value",
                "mean",
            ),
        )
    )

    summary[
        "next_season_inactive_players"
    ] = (
        summary["current_player_rows"]
        - summary[
            "next_season_active_players"
        ]
    )

    summary["retention_rate"] = (
        summary[
            "next_season_active_players"
        ]
        / summary["current_player_rows"]
    )

    summary[
        "rotation_rate_from_current_pool"
    ] = (
        summary["next_rotation_players"]
        / summary["current_player_rows"]
    )

    numeric_columns = [
        "average_next_total_minutes",
        "average_next_impact_workload",
        "retention_rate",
        "rotation_rate_from_current_pool",
    ]

    summary[numeric_columns] = (
        summary[numeric_columns].round(4)
    )

    return summary[
        [
            "season",
            "target_season",
            "current_player_rows",
            "next_season_active_players",
            "next_season_inactive_players",
            "retention_rate",
            "next_rotation_players",
            "rotation_rate_from_current_pool",
            "next_high_minutes_players",
            "average_next_total_minutes",
            "average_next_impact_workload",
        ]
    ]


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    SUMMARY_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    unified = load_unified_data()

    transitions = (
        build_survival_aware_transitions(
            unified
        )
    )

    validate_transitions(
        transitions
    )

    summary = build_summary(
        transitions
    )

    transitions.to_parquet(
        OUTPUT_PARQUET_PATH,
        index=False,
    )

    transitions.to_csv(
        OUTPUT_CSV_PATH,
        index=False,
    )

    summary.to_csv(
        SUMMARY_PATH,
        index=False,
    )

    active_count = int(
        transitions[
            "next_season_active_flag"
        ].sum()
    )

    inactive_count = (
        len(transitions) - active_count
    )

    retention_rate = (
        active_count / len(transitions)
    )

    print("=" * 80)
    print("SURVIVAL-AWARE PROJECTION DATA CREATED")
    print("=" * 80)
    print(
        f"Current player-season rows: "
        f"{len(transitions):,}"
    )
    print(
        f"Next-season active rows: "
        f"{active_count:,}"
    )
    print(
        f"Next-season inactive rows: "
        f"{inactive_count:,}"
    )
    print(
        f"Overall retention rate: "
        f"{retention_rate:.2%}"
    )
    print(
        f"Seasons represented: "
        f"{transitions['season'].nunique()}"
    )
    print(
        f"Numeric columns: "
        f"{transitions.select_dtypes(include='number').shape[1]:,}"
    )
    print()
    print("SEASON SUMMARY")
    print(
        summary.to_string(
            index=False
        )
    )
    print()
    print("SAVED FILES")
    print(OUTPUT_PARQUET_PATH)
    print(OUTPUT_CSV_PATH)
    print(SUMMARY_PATH)
    print()
    print(
        "This dataset includes players who did not "
        "appear in the following NBA season."
    )


if __name__ == "__main__":
    main()