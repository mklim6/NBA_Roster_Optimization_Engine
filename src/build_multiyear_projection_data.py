from __future__ import annotations

from doctest import Example
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]

SOURCE_DATABASE = (
    PROJECT_ROOT.parent
    / "NBA_Front_Office_Decision_Center"
    / "database"
    / "nba_front_office.duckdb"
)

HISTORICAL_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "historical_player_stats"
)

HISTORICAL_BASE_PATH = (
    HISTORICAL_DIRECTORY
    / "historical_player_stats_base_2014_15_2021_22.parquet"
)

HISTORICAL_ADVANCED_PATH = (
    HISTORICAL_DIRECTORY
    / "historical_player_stats_advanced_2014_15_2021_22.parquet"
)

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

UNIFIED_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "unified_player_seasons_2014_15_2025_26.parquet"
)

UNIFIED_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "unified_player_seasons_2014_15_2025_26.csv"
)

TRAINING_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "player_projection_training_data_multiyear.parquet"
)

TRAINING_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "player_projection_training_data_multiyear.csv"
)


SEASON_SCHEDULE_GAMES = {
    "2014-15": 82,
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


HISTORICAL_BASE_RENAME = {
    "gp": "base_gp",
    "w": "base_w",
    "l": "base_l",
    "w_pct": "base_w_pct",
    "min": "base_min",
    "fgm": "base_fgm",
    "fga": "base_fga",
    "fg_pct": "base_fg_pct",
    "fg3m": "base_fg3m",
    "fg3a": "base_fg3a",
    "fg3_pct": "base_fg3_pct",
    "ftm": "base_ftm",
    "fta": "base_fta",
    "ft_pct": "base_ft_pct",
    "oreb": "base_oreb",
    "dreb": "base_dreb",
    "reb": "base_reb",
    "ast": "base_ast",
    "tov": "base_tov",
    "stl": "base_stl",
    "blk": "base_blk",
    "blka": "base_blka",
    "pf": "base_pf",
    "pfd": "base_pfd",
    "pts": "base_pts",
    "plus_minus": "base_plus_minus",
}

HISTORICAL_ADVANCED_RENAME = {
    "gp": "advanced_gp",
    "w": "advanced_w",
    "l": "advanced_l",
    "w_pct": "advanced_w_pct",
    "min": "advanced_min",
    "e_off_rating": "advanced_e_off_rating",
    "off_rating": "advanced_off_rating",
    "e_def_rating": "advanced_e_def_rating",
    "def_rating": "advanced_def_rating",
    "e_net_rating": "advanced_e_net_rating",
    "net_rating": "advanced_net_rating",
    "ast_pct": "advanced_ast_pct",
    "ast_to": "advanced_ast_to",
    "ast_ratio": "advanced_ast_ratio",
    "oreb_pct": "advanced_oreb_pct",
    "dreb_pct": "advanced_dreb_pct",
    "reb_pct": "advanced_reb_pct",
    "tm_tov_pct": "advanced_tm_tov_pct",
    "efg_pct": "advanced_efg_pct",
    "ts_pct": "advanced_ts_pct",
    "usg_pct": "advanced_usg_pct",
    "pace": "advanced_pace",
    "pie": "advanced_pie",
    "poss": "advanced_poss",
}


CORE_NUMERIC_COLUMNS = [
    "age",
    "base_team_count",
    "base_gp",
    "base_min",
    "base_fgm",
    "base_fga",
    "base_fg_pct",
    "base_fg3m",
    "base_fg3a",
    "base_fg3_pct",
    "base_ftm",
    "base_fta",
    "base_ft_pct",
    "base_oreb",
    "base_dreb",
    "base_reb",
    "base_ast",
    "base_tov",
    "base_stl",
    "base_blk",
    "base_pts",
    "base_plus_minus",
    "advanced_off_rating",
    "advanced_def_rating",
    "advanced_net_rating",
    "advanced_ast_pct",
    "advanced_ast_to",
    "advanced_ast_ratio",
    "advanced_oreb_pct",
    "advanced_dreb_pct",
    "advanced_reb_pct",
    "advanced_tm_tov_pct",
    "advanced_efg_pct",
    "advanced_ts_pct",
    "advanced_usg_pct",
    "advanced_pace",
    "advanced_pie",
    "advanced_poss",
]


HISTORY_METRICS = [
    "minutes_per_game",
    "availability_rate",
    "minutes_availability_value",
    "points_per_36",
    "assists_per_36",
    "rebounds_per_36",
    "steals_per_36",
    "blocks_per_36",
    "turnovers_per_36",
    "threes_made_per_36",
    "threes_attempted_per_36",
    "base_fg_pct",
    "base_fg3_pct",
    "base_ft_pct",
    "advanced_off_rating",
    "advanced_def_rating",
    "advanced_net_rating",
    "advanced_ast_pct",
    "advanced_ast_to",
    "advanced_reb_pct",
    "advanced_tm_tov_pct",
    "advanced_efg_pct",
    "advanced_ts_pct",
    "advanced_usg_pct",
    "advanced_pie",
    "advanced_poss",
]


TARGET_COLUMNS = [
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


def normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize incoming column names."""

    frame = frame.copy()
    frame.columns = [
        str(column).strip().lower()
        for column in frame.columns
    ]
    return frame


def safe_divide(
    numerator: pd.Series,
    denominator: pd.Series,
) -> pd.Series:
    """Divide numeric series while safely handling zero denominators."""

    numerator_numeric = pd.to_numeric(
        numerator,
        errors="coerce",
    )

    denominator_numeric = pd.to_numeric(
        denominator,
        errors="coerce",
    )

    return pd.Series(
        np.where(
            denominator_numeric > 0,
            numerator_numeric / denominator_numeric,
            np.nan,
        ),
        index=numerator.index,
        dtype="float64",
    )


def require_columns(
    frame: pd.DataFrame,
    columns: list[str],
    frame_name: str,
) -> None:
    """Raise a helpful error when required columns are absent."""

    missing_columns = [
        column
        for column in columns
        if column not in frame.columns
    ]

    if missing_columns:
        raise ValueError(
            f"{frame_name} is missing required columns:\n"
            + "\n".join(missing_columns)
        )


def build_historical_player_seasons() -> pd.DataFrame:
    """Merge the downloaded 2014-15 through 2021-22 Base and Advanced files."""

    for path in (
        HISTORICAL_BASE_PATH,
        HISTORICAL_ADVANCED_PATH,
    ):
        if not path.exists():
            raise FileNotFoundError(
                f"Historical source file not found:\n{path}"
            )

    base = normalize_columns(
        pd.read_parquet(HISTORICAL_BASE_PATH)
    )

    advanced = normalize_columns(
        pd.read_parquet(HISTORICAL_ADVANCED_PATH)
    )

    base_required = [
        "season",
        "player_id",
        "player_name",
        "team_id",
        "team_abbreviation",
        "age",
        *HISTORICAL_BASE_RENAME.keys(),
    ]

    advanced_required = [
        "season",
        "player_id",
        *HISTORICAL_ADVANCED_RENAME.keys(),
    ]

    require_columns(
        base,
        base_required,
        "Historical Base data",
    )

    require_columns(
        advanced,
        advanced_required,
        "Historical Advanced data",
    )

    base = base[
        base_required
    ].rename(
        columns=HISTORICAL_BASE_RENAME
    )

    advanced = advanced[
        advanced_required
    ].rename(
        columns=HISTORICAL_ADVANCED_RENAME
    )

    duplicate_base = base.duplicated(
        subset=["season", "player_id"],
        keep=False,
    )

    duplicate_advanced = advanced.duplicated(
        subset=["season", "player_id"],
        keep=False,
    )

    if duplicate_base.any():
        raise ValueError(
            "Duplicate historical Base player-seasons were found."
        )

    if duplicate_advanced.any():
        raise ValueError(
            "Duplicate historical Advanced player-seasons were found."
        )

    merged = base.merge(
        advanced,
        how="inner",
        on=["season", "player_id"],
        validate="one_to_one",
    )

    if len(merged) != len(base) or len(merged) != len(advanced):
        raise ValueError(
            "Historical Base and Advanced files did not merge one-to-one."
        )

    merged["base_team_count"] = np.where(
        (
            merged["team_id"].eq(0)
            | merged["team_abbreviation"]
            .astype(str)
            .str.upper()
            .eq("TOT")
        ),
        2,
        1,
    )

    merged["data_source"] = "historical_nba_api"

    return merged


def build_recent_player_seasons() -> pd.DataFrame:
    """Read the 2022-23 through 2025-26 player-seasons from DuckDB."""

    if not SOURCE_DATABASE.exists():
        raise FileNotFoundError(
            "The current NBA database was not found at:\n"
            f"{SOURCE_DATABASE}"
        )

    connection = duckdb.connect(
        database=str(SOURCE_DATABASE),
        read_only=True,
    )

    try:
        recent = connection.execute(
            """
            SELECT
                season,
                player_id,
                player_name,
                team_id,
                team_abbreviation,
                age,
                COALESCE(base_team_count, 1) AS base_team_count,

                base_gp,
                base_w,
                base_l,
                base_w_pct,
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
                base_blka,
                base_pf,
                base_pfd,
                base_pts,
                base_plus_minus,

                advanced_gp,
                advanced_w,
                advanced_l,
                advanced_w_pct,
                advanced_min,
                advanced_e_off_rating,
                advanced_off_rating,
                advanced_e_def_rating,
                advanced_def_rating,
                advanced_e_net_rating,
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
                season,
                player_id
            """
        ).fetchdf()

    finally:
        connection.close()

    if recent.empty:
        raise ValueError(
            "The recent player-season query returned no rows."
        )

    recent["data_source"] = "front_office_duckdb"

    return recent


def add_single_season_features(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    """Create consistent model-ready features for every player-season."""

    frame = frame.copy()

    frame["season_start"] = (
        frame["season"]
        .astype(str)
        .str.slice(0, 4)
        .astype(int)
    )

    unknown_seasons = sorted(
        set(frame["season"])
        .difference(SEASON_SCHEDULE_GAMES)
    )

    if unknown_seasons:
        raise ValueError(
            "Schedule-game counts are missing for seasons:\n"
            + "\n".join(unknown_seasons)
        )

    frame["scheduled_games"] = (
        frame["season"]
        .map(SEASON_SCHEDULE_GAMES)
        .astype(float)
    )

    for column in CORE_NUMERIC_COLUMNS:
        if column not in frame.columns:
            frame[column] = np.nan

        frame[column] = pd.to_numeric(
            frame[column],
            errors="coerce",
        )

    frame["games_played"] = frame["base_gp"]
    frame["total_minutes"] = frame["base_min"]

    frame["minutes_per_game"] = safe_divide(
        frame["base_min"],
        frame["base_gp"],
    )

    per_game_mapping = {
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

    for source_column, output_column in per_game_mapping.items():
        frame[output_column] = safe_divide(
            frame[source_column],
            frame["base_gp"],
        )

    per_36_mapping = {
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

    for source_column, output_column in per_36_mapping.items():
        frame[output_column] = (
            safe_divide(
                frame[source_column],
                frame["base_min"],
            )
            * 36.0
        )

    frame["availability_rate"] = (
        safe_divide(
            frame["base_gp"],
            frame["scheduled_games"],
        )
        .clip(lower=0.0, upper=1.0)
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
    frame["age_cubed"] = frame["age"] ** 3

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

    frame = frame.sort_values(
        ["player_id", "season_start"]
    ).reset_index(drop=True)

    frame["observed_history_seasons"] = (
        frame.groupby("player_id").cumcount() + 1
    )

    frame["career_minutes_observed"] = (
        frame.groupby("player_id")[
            "total_minutes"
        ]
        .transform(
            lambda series: (
                series
                .fillna(0.0)
                .clip(lower=0.0)
                .cumsum()
            )
        )
    )

    return frame


def weighted_history_average(
    current: pd.Series,
    previous_one: pd.Series,
    previous_two: pd.Series,
) -> pd.Series:
    """Create a recency-weighted average using available consecutive seasons."""

    values = np.column_stack(
        [
            pd.to_numeric(current, errors="coerce"),
            pd.to_numeric(previous_one, errors="coerce"),
            pd.to_numeric(previous_two, errors="coerce"),
        ]
    )

    base_weights = np.array(
        [0.60, 0.30, 0.10],
        dtype=float,
    )

    valid = np.isfinite(values)

    weighted_values = np.where(
        valid,
        values * base_weights,
        0.0,
    ).sum(axis=1)

    available_weights = np.where(
        valid,
        base_weights,
        0.0,
    ).sum(axis=1)

    result = np.divide(
        weighted_values,
        available_weights,
        out=np.full(
            len(values),
            np.nan,
            dtype=float,
        ),
        where=available_weights > 0,
    )

    return pd.Series(
        result,
        index=current.index,
        dtype="float64",
    )


def three_season_volatility(
    current: pd.Series,
    previous_one: pd.Series,
    previous_two: pd.Series,
) -> pd.Series:
    """Calculate within-player volatility across up to three consecutive seasons."""

    values = np.column_stack(
        [
            pd.to_numeric(current, errors="coerce"),
            pd.to_numeric(previous_one, errors="coerce"),
            pd.to_numeric(previous_two, errors="coerce"),
        ]
    )

    valid_counts = np.isfinite(values).sum(axis=1)

    with np.errstate(
        invalid="ignore",
        divide="ignore",
    ):
        volatility = np.nanstd(
            values,
            axis=1,
            ddof=0,
        )

    volatility = np.where(
        valid_counts >= 2,
        volatility,
        np.nan,
    )

    return pd.Series(
        volatility,
        index=current.index,
        dtype="float64",
    )


def add_multiseason_history_features(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    """Add consecutive-season lags, trends, weighted averages, and volatility."""

    frame = frame.copy()

    grouped = frame.groupby(
        "player_id",
        sort=False,
    )

    previous_one_season = grouped[
        "season_start"
    ].shift(1)

    previous_two_season = grouped[
        "season_start"
    ].shift(2)

    has_previous_one = (
        frame["season_start"] - previous_one_season
        == 1
    )

    has_previous_two = (
        (frame["season_start"] - previous_two_season == 2)
        & has_previous_one
    )

    frame["has_previous_season"] = (
        has_previous_one.astype(int)
    )

    frame["has_two_year_history"] = (
        has_previous_two.astype(int)
    )

    new_columns: dict[str, pd.Series] = {}

    for metric in HISTORY_METRICS:
        previous_one = grouped[metric].shift(1)
        previous_two = grouped[metric].shift(2)

        previous_one = previous_one.where(
            has_previous_one
        )

        previous_two = previous_two.where(
            has_previous_two
        )

        new_columns[f"prev1_{metric}"] = previous_one
        new_columns[f"prev2_{metric}"] = previous_two

        new_columns[f"weighted3_{metric}"] = (
            weighted_history_average(
                current=frame[metric],
                previous_one=previous_one,
                previous_two=previous_two,
            )
        )

        new_columns[f"trend1_{metric}"] = (
            frame[metric] - previous_one
        )

        new_columns[f"trend2_{metric}"] = (
            previous_one - previous_two
        )

        new_columns[f"volatility3_{metric}"] = (
            three_season_volatility(
                current=frame[metric],
                previous_one=previous_one,
                previous_two=previous_two,
            )
        )

    history_features = pd.DataFrame(
        new_columns,
        index=frame.index,
    )

    frame = pd.concat(
        [
            frame,
            history_features,
        ],
        axis=1,
    )

    return frame.copy()


def build_projection_transitions(
    player_seasons: pd.DataFrame,
) -> pd.DataFrame:
    """Attach each player's next consecutive season as the modeling target."""

    frame = player_seasons.sort_values(
        ["player_id", "season_start"]
    ).reset_index(drop=True)

    grouped = frame.groupby(
        "player_id",
        sort=False,
    )

    next_season_start = grouped[
        "season_start"
    ].shift(-1)

    has_next_season = (
        next_season_start - frame["season_start"]
        == 1
    )

    transitions = frame.loc[
        has_next_season
    ].copy()

    for column in [
        "season",
        "team_abbreviation",
        *TARGET_COLUMNS,
    ]:
        next_values = grouped[column].shift(-1)

        transitions[f"next_{column}"] = (
            next_values.loc[has_next_season]
            .to_numpy()
        )

    transitions["next_season_start"] = (
        next_season_start.loc[
            has_next_season
        ].astype(int).to_numpy()
    )

    transitions["training_sample_weight"] = (
        0.25
        + 0.75
        * transitions["sample_reliability"]
    ).clip(
        lower=0.25,
        upper=1.0,
    )

    transitions = transitions.sort_values(
        ["season_start", "player_name"]
    ).reset_index(drop=True)

    return transitions


def validate_unified_data(
    player_seasons: pd.DataFrame,
) -> None:
    """Validate season coverage and unique player-season keys."""

    expected_seasons = list(
        SEASON_SCHEDULE_GAMES
    )

    actual_seasons = sorted(
        player_seasons["season"]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )

    if actual_seasons != expected_seasons:
        raise ValueError(
            "Unified season coverage is incorrect.\n"
            f"Expected: {expected_seasons}\n"
            f"Actual: {actual_seasons}"
        )

    duplicate_mask = player_seasons.duplicated(
        subset=["season", "player_id"],
        keep=False,
    )

    if duplicate_mask.any():
        duplicates = player_seasons.loc[
            duplicate_mask,
            [
                "season",
                "player_id",
                "player_name",
                "team_abbreviation",
                "data_source",
            ],
        ]

        raise ValueError(
            "Duplicate unified player-season rows were found:\n"
            f"{duplicates.to_string(index=False)}"
        )

    required_model_columns = [
        "player_id",
        "player_name",
        "season",
        "season_start",
        "games_played",
        "minutes_per_game",
        "availability_rate",
        "advanced_pie",
        "advanced_net_rating",
    ]

    null_counts = (
        player_seasons[
            required_model_columns
        ]
        .isna()
        .sum()
    )

    if null_counts.any():
        raise ValueError(
            "Required unified fields contain missing values:\n"
            f"{null_counts[null_counts > 0]}"
        )


def main() -> None:
    """Build a unified 12-season table and multi-year projection dataset."""

    PROCESSED_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    historical = build_historical_player_seasons()
    recent = build_recent_player_seasons()

    common_columns = sorted(
        set(historical.columns)
        | set(recent.columns)
    )

    historical = historical.reindex(
        columns=common_columns
    )

    recent = recent.reindex(
        columns=common_columns
    )

    unified = pd.concat(
        [
            historical,
            recent,
        ],
        ignore_index=True,
        sort=False,
    )

    unified = add_single_season_features(
        unified
    )

    validate_unified_data(
        unified
    )

    enriched = add_multiseason_history_features(
        unified
    )

    transitions = build_projection_transitions(
        enriched
    )

    target_columns = [
        f"next_{column}"
        for column in TARGET_COLUMNS
    ]

    target_completeness = (
        transitions[target_columns]
        .notna()
        .mean()
        .mul(100.0)
        .round(2)
    )

    if (target_completeness < 100.0).any():
        incomplete = target_completeness.loc[
            target_completeness < 100.0
        ]

        raise ValueError(
            "One or more future targets are incomplete:\n"
            f"{incomplete}"
        )

    enriched.to_parquet(
        UNIFIED_PARQUET_PATH,
        index=False,
    )

    enriched.to_csv(
        UNIFIED_CSV_PATH,
        index=False,
    )

    transitions.to_parquet(
        TRAINING_PARQUET_PATH,
        index=False,
    )

    transitions.to_csv(
        TRAINING_CSV_PATH,
        index=False,
    )

    season_summary = (
        enriched.groupby(
            [
                "season",
                "data_source",
            ],
            dropna=False,
        )
        .agg(
            player_rows=("player_id", "size"),
            unique_players=("player_id", "nunique"),
            average_age=("age", "mean"),
            rotation_players=(
                "rotation_player_flag",
                "sum",
            ),
        )
        .reset_index()
    )

    season_summary["average_age"] = (
        season_summary["average_age"].round(2)
    )

    transition_summary = (
        transitions.groupby(
            [
                "season",
                "next_season",
            ]
        )
        .agg(
            transition_rows=("player_id", "size"),
            unique_players=("player_id", "nunique"),
            with_previous_season=(
                "has_previous_season",
                "sum",
            ),
            with_two_year_history=(
                "has_two_year_history",
                "sum",
            ),
            current_rotation_players=(
                "rotation_player_flag",
                "sum",
            ),
            next_rotation_players=(
                "next_rotation_player_flag",
                "sum",
            ),
        )
        .reset_index()
    )

    print("=" * 80)
    print("UNIFIED 12-SEASON PLAYER DATA CREATED")
    print("=" * 80)
    print(
        f"Historical rows: {len(historical):,}"
    )
    print(
        f"Recent rows: {len(recent):,}"
    )
    print(
        f"Unified player-seasons: {len(enriched):,}"
    )
    print(
        f"Unique players: "
        f"{enriched['player_id'].nunique():,}"
    )
    print(
        f"Seasons: {enriched['season'].nunique()}"
    )
    print(
        f"Projection transitions: "
        f"{len(transitions):,}"
    )
    print()
    print("SEASON COVERAGE")
    print(
        season_summary.to_string(
            index=False
        )
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
    print(
        target_completeness
        .rename("percent_complete")
        .reset_index()
        .rename(columns={"index": "target"})
        .to_string(index=False)
    )
    print()
    print("SAVED FILES")
    print(UNIFIED_PARQUET_PATH)
    print(UNIFIED_CSV_PATH)
    print(TRAINING_PARQUET_PATH)
    print(TRAINING_CSV_PATH)
    print()
    print("MULTI-YEAR FEATURE EXAMPLE")

    example_columns = [
        "player_name",
        "season",
        "age",
        "minutes_per_game",
        "prev1_minutes_per_game",
        "prev2_minutes_per_game",
        "weighted3_minutes_per_game",
        "trend1_minutes_per_game",
        "volatility3_minutes_per_game",
        "advanced_pie",
        "prev1_advanced_pie",
        "weighted3_advanced_pie",
        "next_season",
        "next_minutes_per_game",
        "next_advanced_pie",
    ]

    example = (
        transitions.loc[
            transitions["has_two_year_history"].eq(1)
        ]
        .sort_values(
            [
                "season_start",
                "total_minutes",
            ],
            ascending=[
                False,
                False,
            ],
        )
        .loc[
            :,
            example_columns,
        ]
        .head(15)
    )

    print(
        example.to_string(
            index=False
        )
    )


if __name__ == "__main__":
    main()