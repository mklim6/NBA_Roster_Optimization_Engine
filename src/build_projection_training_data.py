from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


SOURCE_DATABASE = Path(
    r"C:\Users\klima\Python Projects\Projects"
    r"\NBA_Front_Office_Decision_Center"
    r"\database\nba_front_office.duckdb"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "data" / "processed"


def safe_divide(
    numerator: pd.Series,
    denominator: pd.Series,
) -> pd.Series:
    """Divide two numeric series while avoiding zero-division errors."""

    numerator_numeric = pd.to_numeric(
        numerator,
        errors="coerce",
    )

    denominator_numeric = pd.to_numeric(
        denominator,
        errors="coerce",
    )

    result = np.where(
        denominator_numeric > 0,
        numerator_numeric / denominator_numeric,
        np.nan,
    )

    return pd.Series(
        result,
        index=numerator.index,
        dtype="float64",
    )


def add_season_features(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    """Create model-ready features for each player-season."""

    frame = frame.copy()

    numeric_columns = [
        column
        for column in frame.columns
        if column
        not in {
            "season",
            "player_name",
            "team_abbreviation",
        }
    ]

    for column in numeric_columns:
        frame[column] = pd.to_numeric(
            frame[column],
            errors="coerce",
        )

    frame["season_start"] = (
        frame["season"]
        .astype(str)
        .str.slice(0, 4)
        .astype(int)
    )

    frame["games_played"] = frame["base_gp"]
    frame["total_minutes"] = frame["base_min"]

    frame["minutes_per_game"] = safe_divide(
        frame["base_min"],
        frame["base_gp"],
    )

    per_game_columns = {
        "base_pts": "points_per_game",
        "base_ast": "assists_per_game",
        "base_reb": "rebounds_per_game",
        "base_oreb": "offensive_rebounds_per_game",
        "base_dreb": "defensive_rebounds_per_game",
        "base_stl": "steals_per_game",
        "base_blk": "blocks_per_game",
        "base_tov": "turnovers_per_game",
        "base_fg3m": "threes_made_per_game",
        "base_fg3a": "threes_attempted_per_game",
    }

    for source_column, output_column in per_game_columns.items():
        frame[output_column] = safe_divide(
            frame[source_column],
            frame["base_gp"],
        )

    per_36_columns = {
        "base_pts": "points_per_36",
        "base_ast": "assists_per_36",
        "base_reb": "rebounds_per_36",
        "base_oreb": "offensive_rebounds_per_36",
        "base_dreb": "defensive_rebounds_per_36",
        "base_stl": "steals_per_36",
        "base_blk": "blocks_per_36",
        "base_tov": "turnovers_per_36",
        "base_fg3m": "threes_made_per_36",
        "base_fg3a": "threes_attempted_per_36",
    }

    for source_column, output_column in per_36_columns.items():
        frame[output_column] = (
            safe_divide(
                frame[source_column],
                frame["base_min"],
            )
            * 36.0
        )

    frame["availability_rate"] = (
        frame["base_gp"] / 82.0
    ).clip(
        lower=0.0,
        upper=1.0,
    )

    frame["minutes_availability_value"] = (
        frame["minutes_per_game"]
        * frame["availability_rate"]
    )

    frame["three_point_attempt_rate"] = safe_divide(
        frame["base_fg3a"],
        frame["base_fga"],
    )

    frame["free_throw_attempt_rate"] = safe_divide(
        frame["base_fta"],
        frame["base_fga"],
    )

    frame["assist_turnover_box_ratio"] = safe_divide(
        frame["base_ast"],
        frame["base_tov"],
    )

    frame["age_squared"] = frame["age"] ** 2

    frame["changed_teams"] = (
        frame["base_team_count"]
        .fillna(1)
        .gt(1)
        .astype(int)
    )

    frame["small_sample_flag"] = (
        (frame["base_gp"] < 10)
        | (frame["minutes_per_game"] < 8)
    ).astype(int)

    frame["rotation_player_flag"] = (
        (frame["base_gp"] >= 20)
        & (frame["minutes_per_game"] >= 12)
    ).astype(int)

    frame["high_minutes_flag"] = (
        frame["total_minutes"] >= 1_500
    ).astype(int)

    frame["sample_reliability"] = (
        1.0
        - np.exp(
            -frame["total_minutes"]
            .fillna(0.0)
            .clip(lower=0.0)
            / 750.0
        )
    ).clip(
        lower=0.0,
        upper=1.0,
    )

    frame["target_quality_available"] = (
        frame[
            [
                "advanced_pie",
                "advanced_net_rating",
                "advanced_ts_pct",
            ]
        ]
        .notna()
        .all(axis=1)
        .astype(int)
    )

    return frame


def main() -> None:
    """Build player season-to-season transitions for projection modeling."""

    if not SOURCE_DATABASE.exists():
        raise FileNotFoundError(
            "The source NBA database could not be found at:\n"
            f"{SOURCE_DATABASE}"
        )

    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = duckdb.connect(
        database=str(SOURCE_DATABASE),
        read_only=True,
    )

    try:
        player_seasons = connection.execute(
            """
            SELECT
                season,
                player_id,
                player_name,
                team_id,
                team_abbreviation,
                age,

                COALESCE(base_team_count, 1)
                    AS base_team_count,

                base_gp,
                base_min,
                base_fgm,
                base_fga,
                base_fg_pct,
                base_fg3m,
                base_fg3a,
                base_fg3_pct,
                base_ftm,
                base_fta,
                base_ft_pct,
                base_oreb,
                base_dreb,
                base_reb,
                base_ast,
                base_tov,
                base_stl,
                base_blk,
                base_pts,
                base_plus_minus,

                advanced_off_rating,
                advanced_def_rating,
                advanced_net_rating,
                advanced_ast_pct,
                advanced_ast_to,
                advanced_ast_ratio,
                advanced_oreb_pct,
                advanced_dreb_pct,
                advanced_reb_pct,
                advanced_tm_tov_pct,
                advanced_efg_pct,
                advanced_ts_pct,
                advanced_usg_pct,
                advanced_pace,
                advanced_pie,
                advanced_poss

            FROM fact_player_season

            WHERE season_type = 'Regular Season'
              AND has_base_stats = TRUE
              AND has_advanced_stats = TRUE

            ORDER BY
                player_id,
                season
            """
        ).fetchdf()

    finally:
        connection.close()

    if player_seasons.empty:
        raise ValueError(
            "No player-season records were returned."
        )

    player_seasons = add_season_features(
        player_seasons
    )

    duplicate_mask = player_seasons.duplicated(
        subset=[
            "player_id",
            "season_start",
        ],
        keep=False,
    )

    if duplicate_mask.any():
        duplicates = player_seasons.loc[
            duplicate_mask,
            [
                "player_id",
                "player_name",
                "season",
                "team_abbreviation",
            ],
        ]

        raise ValueError(
            "Duplicate player-season records were found:\n"
            f"{duplicates.to_string(index=False)}"
        )

    current_seasons = player_seasons.copy()
    future_seasons = player_seasons.copy()

    future_seasons["join_season_start"] = (
        future_seasons["season_start"] - 1
    )

    future_rename = {
        column: f"next_{column}"
        for column in future_seasons.columns
        if column
        not in {
            "player_id",
            "join_season_start",
        }
    }

    future_seasons = future_seasons.rename(
        columns=future_rename
    )

    transitions = current_seasons.merge(
        future_seasons,
        how="inner",
        left_on=[
            "player_id",
            "season_start",
        ],
        right_on=[
            "player_id",
            "join_season_start",
        ],
        validate="one_to_one",
    )

    transitions = transitions.drop(
        columns=["join_season_start"]
    )

    valid_transition = (
        transitions["next_season_start"]
        == transitions["season_start"] + 1
    )

    if not valid_transition.all():
        invalid_rows = transitions.loc[
            ~valid_transition,
            [
                "player_name",
                "season",
                "next_season",
            ],
        ]

        raise ValueError(
            "Nonconsecutive season transitions were found:\n"
            f"{invalid_rows.to_string(index=False)}"
        )

    target_columns = [
        "next_games_played",
        "next_total_minutes",
        "next_minutes_per_game",
        "next_availability_rate",
        "next_minutes_availability_value",
        "next_advanced_off_rating",
        "next_advanced_def_rating",
        "next_advanced_net_rating",
        "next_advanced_efg_pct",
        "next_advanced_ts_pct",
        "next_advanced_usg_pct",
        "next_advanced_pie",
        "next_advanced_poss",
    ]

    missing_targets = [
        column
        for column in target_columns
        if column not in transitions.columns
    ]

    if missing_targets:
        raise ValueError(
            "Expected future target columns are missing:\n"
            + "\n".join(missing_targets)
        )

    transitions["next_rotation_player_flag"] = (
        (
            transitions["next_games_played"]
            >= 20
        )
        & (
            transitions["next_minutes_per_game"]
            >= 12
        )
    ).astype(int)

    transitions["next_high_minutes_flag"] = (
        transitions["next_total_minutes"]
        >= 1_500
    ).astype(int)

    transitions["training_sample_weight"] = (
        0.25
        + 0.75
        * transitions["sample_reliability"]
    ).clip(
        lower=0.25,
        upper=1.0,
    )

    transitions = transitions.sort_values(
        [
            "season_start",
            "player_name",
        ]
    ).reset_index(drop=True)

    parquet_path = (
        OUTPUT_DIRECTORY
        / "player_projection_training_data.parquet"
    )

    csv_path = (
        OUTPUT_DIRECTORY
        / "player_projection_training_data.csv"
    )

    transitions.to_parquet(
        parquet_path,
        index=False,
    )

    transitions.to_csv(
        csv_path,
        index=False,
    )

    transition_summary = (
        transitions.groupby(
            [
                "season",
                "next_season",
            ],
            dropna=False,
        )
        .agg(
            transition_rows=(
                "player_id",
                "size",
            ),
            current_rotation_players=(
                "rotation_player_flag",
                "sum",
            ),
            next_rotation_players=(
                "next_rotation_player_flag",
                "sum",
            ),
            average_current_age=(
                "age",
                "mean",
            ),
            average_next_minutes=(
                "next_minutes_per_game",
                "mean",
            ),
        )
        .reset_index()
    )

    transition_summary[
        [
            "average_current_age",
            "average_next_minutes",
        ]
    ] = transition_summary[
        [
            "average_current_age",
            "average_next_minutes",
        ]
    ].round(2)

    print("PROJECTION TRAINING DATA CREATED")
    print(
        "Player-season records: "
        f"{len(player_seasons):,}"
    )
    print(
        "Season transitions: "
        f"{len(transitions):,}"
    )
    print(
        "Unique players represented: "
        f"{transitions['player_id'].nunique():,}"
    )
    print()

    print("TRANSITIONS BY SEASON")
    print(
        transition_summary.to_string(
            index=False
        )
    )
    print()

    print("TARGET COMPLETENESS")

    target_completeness = (
        transitions[target_columns]
        .notna()
        .mean()
        .mul(100)
        .round(2)
        .rename("percent_complete")
        .reset_index()
        .rename(
            columns={
                "index": "target",
            }
        )
    )

    print(
        target_completeness.to_string(
            index=False
        )
    )
    print()

    print("SAVED FILES")
    print(parquet_path)
    print(csv_path)
    print()

    print("SAMPLE PLAYER TRANSITIONS")

    display_columns = [
        "player_name",
        "season",
        "team_abbreviation",
        "age",
        "games_played",
        "minutes_per_game",
        "advanced_pie",
        "advanced_net_rating",
        "next_season",
        "next_team_abbreviation",
        "next_games_played",
        "next_minutes_per_game",
        "next_advanced_pie",
        "next_advanced_net_rating",
    ]

    sample_transitions = (
        transitions
        .sort_values(
            [
                "season_start",
                "total_minutes",
            ],
            ascending=[
                True,
                False,
            ],
        )
        .head(20)
    )

    print(
        sample_transitions[
            display_columns
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()