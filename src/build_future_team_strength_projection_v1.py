from __future__ import annotations

import argparse
import json
import math
import time
import unicodedata
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = "future-team-strength-projection-v1-2026-08-04"

PROJECT_ROOT = Path(__file__).resolve().parents[1]

PROJECTION_BOARD_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "current_player_projection_board_2025_26_to_2026_27.parquet"
)

FINANCIAL_LAYER_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "player_financial_layer_2026_27_v2.parquet"
)

RAW_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "team_strength"
)

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

HISTORICAL_TEAM_RECORDS_PATH = (
    RAW_DIRECTORY
    / "nba_team_records_2014_15_2025_26.parquet"
)

HISTORICAL_TEAM_RECORDS_CSV_PATH = (
    RAW_DIRECTORY
    / "nba_team_records_2014_15_2025_26.csv"
)

PLAYER_FUTURE_PATH = (
    PROCESSED_DIRECTORY
    / "future_player_team_strength_inputs_2026_27_to_2032_33_v1.parquet"
)

TEAM_PROJECTION_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_team_strength_projections_2026_27_to_2032_33_v1.parquet"
)

TEAM_PROJECTION_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_team_strength_projections_2026_27_to_2032_33_v1.csv"
)

RANK_WIN_CURVE_PATH = (
    OUTPUT_DIRECTORY
    / "historical_league_rank_to_wins_curve_v1.csv"
)

TEAM_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_team_strength_selected_seasons_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_team_strength_projection_metadata_v1.json"
)


HISTORICAL_SEASONS = [
    f"{year}-{str(year + 1)[-2:]}"
    for year in range(
        2014,
        2026,
    )
]

PROJECTION_SEASON_STARTS = list(
    range(
        2026,
        2033,
    )
)

SALARY_COLUMN_BY_SEASON_START = {
    2026: [
        "salary_2026_27",
        "trade_salary_2026_27",
    ],
    2027: [
        "salary_2027_28",
    ],
    2028: [
        "salary_2028_29",
    ],
    2029: [
        "salary_2029_30",
    ],
    2030: [
        "salary_2030_31",
    ],
    2031: [
        "salary_2031_32",
    ],
    2032: [
        "salary_2032_33",
    ],
}

ROTATION_WEIGHTS = np.array(
    [
        1.00,
        1.00,
        1.00,
        1.00,
        1.00,
        0.88,
        0.88,
        0.88,
        0.68,
        0.68,
        0.68,
        0.68,
        0.42,
        0.42,
        0.42,
    ],
    dtype=float,
)

REGRESSION_TO_LEAGUE_AVERAGE = {
    0: 0.00,
    1: 0.08,
    2: 0.16,
    3: 0.25,
    4: 0.35,
    5: 0.45,
    6: 0.55,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Project future NBA team strength from the current "
            "player projection board, contracts, aging, survival, "
            "roster continuity, and historical rank-to-win outcomes."
        )
    )

    parser.add_argument(
        "--simulations",
        type=int,
        default=10_000,
        help=(
            "Number of team-strength simulations per future season."
        ),
    )

    parser.add_argument(
        "--random-seed",
        type=int,
        default=20260804,
        help="Random seed for team-strength simulations.",
    )

    parser.add_argument(
        "--force-team-record-download",
        action="store_true",
        help=(
            "Download historical NBA team records again even "
            "when the cached file exists."
        ),
    )

    return parser.parse_args()


def normalize_columns(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    output = frame.copy()

    output.columns = [
        str(column)
        .strip()
        .lower()
        .replace(" ", "_")
        for column in output.columns
    ]

    return output


def normalized_name(
    value: Any,
) -> str:
    if value is None or pd.isna(value):
        return ""

    text = unicodedata.normalize(
        "NFKD",
        str(value),
    )

    text = "".join(
        character
        for character in text
        if not unicodedata.combining(
            character
        )
    )

    return "".join(
        character.lower()
        for character in text
        if character.isalnum()
    )


def player_key(
    value: Any,
) -> str:
    if value is None or pd.isna(value):
        return ""

    text = str(value).strip()

    if text.endswith(".0"):
        numeric_part = text[:-2]

        if numeric_part.isdigit():
            return numeric_part

    return text


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


def first_existing_column(
    frame: pd.DataFrame,
    candidates: list[str],
    label: str,
    required: bool = True,
) -> str | None:
    for candidate in candidates:
        if candidate in frame.columns:
            return candidate

    if required:
        raise ValueError(
            f"Could not find a column for {label}.\n"
            "Tried:\n"
            + "\n".join(
                candidates
            )
        )

    return None


def season_label(
    start_year: int,
) -> str:
    return (
        f"{start_year}-"
        f"{str(start_year + 1)[-2:]}"
    )


def age_multiplier_for_age(
    age: float,
) -> float:
    if age <= 20.0:
        return 1.045
    if age <= 22.0:
        return 1.035
    if age <= 24.0:
        return 1.022
    if age <= 26.0:
        return 1.012
    if age <= 28.0:
        return 1.000
    if age <= 30.0:
        return 0.982
    if age <= 32.0:
        return 0.957
    if age <= 34.0:
        return 0.925
    if age <= 36.0:
        return 0.875
    return 0.800


def cumulative_age_multiplier(
    starting_age: float,
    horizon: int,
) -> float:
    multiplier = 1.0

    for step in range(
        horizon
    ):
        multiplier *= (
            age_multiplier_for_age(
                starting_age
                + step
            )
        )

    return float(
        np.clip(
            multiplier,
            0.18,
            1.35,
        )
    )


def contract_salary_for_year(
    frame: pd.DataFrame,
    season_start: int,
) -> pd.Series:
    candidates = (
        SALARY_COLUMN_BY_SEASON_START.get(
            season_start,
            [],
        )
    )

    available = [
        column
        for column in candidates
        if column in frame.columns
    ]

    if not available:
        return pd.Series(
            0.0,
            index=frame.index,
            dtype=float,
        )

    salary = pd.Series(
        0.0,
        index=frame.index,
        dtype=float,
    )

    for column in available:
        salary = np.maximum(
            salary,
            numeric_series(
                frame,
                column,
                fill_value=0.0,
            ),
        )

    return pd.Series(
        salary,
        index=frame.index,
        dtype=float,
    )


def load_projection_inputs() -> pd.DataFrame:
    if not PROJECTION_BOARD_PATH.exists():
        raise FileNotFoundError(
            "Projection board was not found:\n"
            f"{PROJECTION_BOARD_PATH}"
        )

    board = normalize_columns(
        pd.read_parquet(
            PROJECTION_BOARD_PATH
        )
    )

    player_id_column = (
        first_existing_column(
            board,
            [
                "player_id",
                "person_id",
            ],
            "projection-board player ID",
        )
    )

    player_name_column = (
        first_existing_column(
            board,
            [
                "player_name",
                "player_display_name",
            ],
            "projection-board player name",
        )
    )

    team_column = (
        first_existing_column(
            board,
            [
                "team_abbreviation",
                "current_team_2026_27",
            ],
            "projection-board team",
        )
    )

    age_column = (
        first_existing_column(
            board,
            [
                "age",
                "player_age",
            ],
            "projection-board age",
        )
    )

    expected_column = (
        first_existing_column(
            board,
            [
                "projected_expected_contribution",
            ],
            "expected contribution",
        )
    )

    downside_column = (
        first_existing_column(
            board,
            [
                (
                    "projected_active_downside_"
                    "contribution_80"
                ),
                (
                    "survival_weighted_active_"
                    "downside_score"
                ),
                "projected_downside_contribution_80",
            ],
            "downside contribution",
        )
    )

    upside_column = (
        first_existing_column(
            board,
            [
                (
                    "projected_active_upside_"
                    "contribution_80"
                ),
                "projected_upside_contribution_80",
            ],
            "upside contribution",
        )
    )

    survival_column = (
        first_existing_column(
            board,
            [
                "projected_survival_probability",
            ],
            "survival probability",
        )
    )

    rotation_column = (
        first_existing_column(
            board,
            [
                "projected_rotation_probability",
            ],
            "rotation probability",
        )
    )

    uncertainty_column = (
        first_existing_column(
            board,
            [
                "projection_uncertainty_percentile",
            ],
            "projection uncertainty percentile",
            required=False,
        )
    )

    main_pool_column = (
        first_existing_column(
            board,
            [
                "main_pool_eligible",
                "optimizer_projection_eligible",
            ],
            "main projection pool",
            required=False,
        )
    )

    output = pd.DataFrame(
        {
            "player_id": (
                board[
                    player_id_column
                ].map(
                    player_key
                )
            ),
            "player_name": (
                board[
                    player_name_column
                ].astype(str)
            ),
            "performance_team_2025_26": (
                board[
                    team_column
                ].astype(str)
            ),
            "age_2026_27": (
                numeric_series(
                    board,
                    age_column,
                )
            ),
            "base_expected_contribution": (
                numeric_series(
                    board,
                    expected_column,
                    fill_value=0.0,
                )
            ),
            "base_downside_contribution": (
                numeric_series(
                    board,
                    downside_column,
                    fill_value=0.0,
                )
            ),
            "base_upside_contribution": (
                numeric_series(
                    board,
                    upside_column,
                    fill_value=0.0,
                )
            ),
            "base_survival_probability": (
                numeric_series(
                    board,
                    survival_column,
                    fill_value=0.0,
                ).clip(
                    lower=0.01,
                    upper=0.999,
                )
            ),
            "base_rotation_probability": (
                numeric_series(
                    board,
                    rotation_column,
                    fill_value=0.0,
                ).clip(
                    lower=0.0,
                    upper=1.0,
                )
            ),
        }
    )

    if uncertainty_column is None:
        output[
            "projection_uncertainty_percentile"
        ] = 50.0
    else:
        output[
            "projection_uncertainty_percentile"
        ] = numeric_series(
            board,
            uncertainty_column,
            fill_value=50.0,
        ).clip(
            lower=0.0,
            upper=100.0,
        )

    if main_pool_column is None:
        output[
            "main_pool_eligible"
        ] = True
    else:
        output[
            "main_pool_eligible"
        ] = (
            board[
                main_pool_column
            ]
            .fillna(False)
            .astype(bool)
        )

    for optional_column in [
        "primary_skill",
        "secondary_skill",
        "value_tier",
        "confidence_tier",
        "roster_value_score",
        "roster_value_percentile",
    ]:
        if optional_column in board.columns:
            output[
                optional_column
            ] = board[
                optional_column
            ].to_numpy()

    output[
        "normalized_player_name"
    ] = output[
        "player_name"
    ].map(
        normalized_name
    )

    if not FINANCIAL_LAYER_PATH.exists():
        output[
            "current_team_2026_27"
        ] = output[
            "performance_team_2025_26"
        ]

        return output

    financial = normalize_columns(
        pd.read_parquet(
            FINANCIAL_LAYER_PATH
        )
    )

    financial_name_column = (
        first_existing_column(
            financial,
            [
                "player_name",
            ],
            "financial player name",
        )
    )

    financial[
        "normalized_player_name"
    ] = financial[
        financial_name_column
    ].map(
        normalized_name
    )

    if "player_id" in financial.columns:
        financial[
            "player_id"
        ] = financial[
            "player_id"
        ].map(
            player_key
        )

    merge_columns = [
        column
        for column in [
            "player_id",
            "normalized_player_name",
            "current_team_2026_27",
            "salary_2026_27",
            "trade_salary_2026_27",
            "salary_2027_28",
            "salary_2028_29",
            "salary_2029_30",
            "salary_2030_31",
            "salary_2031_32",
            "salary_2032_33",
            "future_salary_commitment_2027_28_plus",
            "contract_years_remaining_including_2026_27",
        ]
        if column in financial.columns
    ]

    financial_lookup = (
        financial[
            merge_columns
        ]
        .copy()
    )

    if (
        "player_id"
        in financial_lookup.columns
        and financial_lookup[
            "player_id"
        ].ne("").any()
    ):
        financial_lookup = (
            financial_lookup.sort_values(
                "normalized_player_name"
            )
            .drop_duplicates(
                subset=[
                    "player_id"
                ],
                keep="first",
            )
        )

        merged = output.merge(
            financial_lookup.drop(
                columns=[
                    "normalized_player_name"
                ],
                errors="ignore",
            ),
            how="left",
            on="player_id",
            validate="one_to_one",
        )
    else:
        financial_lookup = (
            financial_lookup.drop_duplicates(
                subset=[
                    "normalized_player_name"
                ],
                keep="first",
            )
        )

        merged = output.merge(
            financial_lookup.drop(
                columns=[
                    "player_id"
                ],
                errors="ignore",
            ),
            how="left",
            on="normalized_player_name",
            validate="one_to_one",
        )

    if "current_team_2026_27" not in merged.columns:
        merged[
            "current_team_2026_27"
        ] = merged[
            "performance_team_2025_26"
        ]
    else:
        merged[
            "current_team_2026_27"
        ] = (
            merged[
                "current_team_2026_27"
            ]
            .replace(
                {
                    "": np.nan,
                    "nan": np.nan,
                    "None": np.nan,
                }
            )
            .fillna(
                merged[
                    "performance_team_2025_26"
                ]
            )
            .astype(str)
        )

    return merged


def download_historical_team_records() -> pd.DataFrame:
    try:
        from nba_api.stats.endpoints import (
            leaguedashteamstats,
        )
    except ImportError as error:
        raise ImportError(
            "nba_api is required in the "
            "nba-roster-optimizer environment."
        ) from error

    frames = []

    for season in HISTORICAL_SEASONS:
        print(
            f"Downloading team records for {season}..."
        )

        endpoint = (
            leaguedashteamstats.LeagueDashTeamStats(
                season=season,
                season_type_all_star=(
                    "Regular Season"
                ),
                measure_type_detailed_defense=(
                    "Base"
                ),
                per_mode_detailed="Totals",
                timeout=90,
            )
        )

        data_frames = endpoint.get_data_frames()

        if not data_frames:
            raise RuntimeError(
                f"No team data returned for {season}."
            )

        frame = normalize_columns(
            data_frames[0]
        )

        required = [
            "team_id",
            "team_name",
            "w",
            "l",
        ]

        missing = [
            column
            for column in required
            if column not in frame.columns
        ]

        if missing:
            raise ValueError(
                f"Team stats for {season} are missing:\n"
                + "\n".join(
                    missing
                )
            )

        frame[
            "season"
        ] = season

        frames.append(
            frame[
                [
                    "season",
                    "team_id",
                    "team_name",
                    "w",
                    "l",
                ]
            ]
        )

        time.sleep(
            0.7
        )

    combined = pd.concat(
        frames,
        ignore_index=True,
    )

    for column in [
        "w",
        "l",
    ]:
        combined[column] = numeric_series(
            combined,
            column,
            fill_value=0.0,
        )

    combined[
        "games"
    ] = (
        combined[
            "w"
        ]
        + combined[
            "l"
        ]
    )

    combined[
        "win_percentage"
    ] = np.where(
        combined[
            "games"
        ].gt(0.0),
        combined[
            "w"
        ]
        / combined[
            "games"
        ],
        np.nan,
    )

    combined[
        "wins_equivalent_82"
    ] = (
        combined[
            "win_percentage"
        ]
        * 82.0
    )

    combined[
        "league_rank_by_wins"
    ] = (
        combined.groupby(
            "season"
        )[
            "wins_equivalent_82"
        ]
        .rank(
            method="first",
            ascending=False,
        )
        .astype(int)
    )

    return combined.sort_values(
        [
            "season",
            "league_rank_by_wins",
        ]
    ).reset_index(
        drop=True
    )


def load_or_download_team_records(
    force_download: bool,
) -> pd.DataFrame:
    if (
        HISTORICAL_TEAM_RECORDS_PATH.exists()
        and not force_download
    ):
        return pd.read_parquet(
            HISTORICAL_TEAM_RECORDS_PATH
        )

    frame = (
        download_historical_team_records()
    )

    RAW_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    frame.to_parquet(
        HISTORICAL_TEAM_RECORDS_PATH,
        index=False,
    )

    frame.to_csv(
        HISTORICAL_TEAM_RECORDS_CSV_PATH,
        index=False,
    )

    return frame


def build_rank_win_curve(
    records: pd.DataFrame,
) -> pd.DataFrame:
    ranked = records.copy()

    curve = (
        ranked.groupby(
            "league_rank_by_wins",
            as_index=False,
        )
        .agg(
            historical_seasons=(
                "season",
                "nunique",
            ),
            mean_wins=(
                "wins_equivalent_82",
                "mean",
            ),
            median_wins=(
                "wins_equivalent_82",
                "median",
            ),
            wins_sd=(
                "wins_equivalent_82",
                "std",
            ),
            wins_p10=(
                "wins_equivalent_82",
                lambda values: (
                    values.quantile(
                        0.10
                    )
                ),
            ),
            wins_p90=(
                "wins_equivalent_82",
                lambda values: (
                    values.quantile(
                        0.90
                    )
                ),
            ),
        )
        .sort_values(
            "league_rank_by_wins"
        )
        .reset_index(
            drop=True
        )
    )

    curve[
        "wins_sd"
    ] = curve[
        "wins_sd"
    ].fillna(
        3.0
    ).clip(
        lower=1.5,
    )

    return curve


def build_future_player_rows(
    players: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    league_expected_median = float(
        players[
            "base_expected_contribution"
        ].median()
    )

    for player in players.to_dict(
        orient="records"
    ):
        starting_age = float(
            player[
                "age_2026_27"
            ]
        )

        base_expected = max(
            0.0,
            float(
                player[
                    "base_expected_contribution"
                ]
            ),
        )

        base_downside = max(
            0.0,
            float(
                player[
                    "base_downside_contribution"
                ]
            ),
        )

        base_upside = max(
            base_expected,
            float(
                player[
                    "base_upside_contribution"
                ]
            ),
        )

        base_survival = float(
            player[
                "base_survival_probability"
            ]
        )

        rotation_probability = float(
            player[
                "base_rotation_probability"
            ]
        )

        uncertainty_percentile = float(
            player[
                "projection_uncertainty_percentile"
            ]
        )

        value_percentile = float(
            player.get(
                "roster_value_percentile",
                50.0,
            )
            if pd.notna(
                player.get(
                    "roster_value_percentile",
                    np.nan,
                )
            )
            else 50.0
        )

        for season_start in (
            PROJECTION_SEASON_STARTS
        ):
            horizon = (
                season_start
                - PROJECTION_SEASON_STARTS[
                    0
                ]
            )

            age = (
                starting_age
                + horizon
            )

            age_multiplier = (
                cumulative_age_multiplier(
                    starting_age=(
                        starting_age
                    ),
                    horizon=horizon,
                )
            )

            age_survival_penalty = max(
                0.82,
                1.0
                - max(
                    0.0,
                    age - 31.0,
                )
                * 0.018,
            )

            cumulative_survival = (
                base_survival
                ** (
                    1.0
                    + 0.62
                    * horizon
                )
                * (
                    age_survival_penalty
                    ** horizon
                )
            )

            cumulative_survival = float(
                np.clip(
                    cumulative_survival,
                    0.04,
                    0.999,
                )
            )

            salary = float(
                contract_salary_for_year(
                    pd.DataFrame(
                        [player]
                    ),
                    season_start,
                ).iloc[0]
            )

            under_contract = (
                salary > 0.0
            )

            if horizon == 0:
                continuity_factor = 1.0
            elif under_contract:
                continuity_factor = 0.97
            else:
                youth_bonus = float(
                    np.clip(
                        (
                            27.0 - age
                        )
                        * 0.018,
                        -0.10,
                        0.12,
                    )
                )

                core_bonus = float(
                    np.clip(
                        (
                            value_percentile
                            - 50.0
                        )
                        / 500.0,
                        -0.08,
                        0.10,
                    )
                )

                continuity_factor = float(
                    np.clip(
                        0.58
                        - 0.035
                        * horizon
                        + youth_bonus
                        + core_bonus,
                        0.25,
                        0.78,
                    )
                )

            projected_expected = (
                base_expected
                * age_multiplier
                * cumulative_survival
            )

            projected_downside = (
                base_downside
                * age_multiplier
                * cumulative_survival
            )

            projected_upside = (
                base_upside
                * age_multiplier
                * cumulative_survival
            )

            replacement_value = (
                max(
                    league_expected_median,
                    base_expected
                    * 0.38,
                )
                * (
                    1.0
                    - continuity_factor
                )
                * (
                    0.72
                    + 0.18
                    * rotation_probability
                )
            )

            organizational_contribution = (
                projected_expected
                * continuity_factor
                + replacement_value
            )

            active_interval_sd = max(
                (
                    projected_upside
                    - projected_downside
                )
                / 2.563,
                projected_expected
                * 0.10,
            )

            horizon_uncertainty = (
                projected_expected
                * (
                    0.035
                    * horizon
                    + 0.0012
                    * uncertainty_percentile
                )
            )

            projected_sd = float(
                np.sqrt(
                    active_interval_sd
                    ** 2
                    + horizon_uncertainty
                    ** 2
                )
            )

            rows.append(
                {
                    "player_id": (
                        player[
                            "player_id"
                        ]
                    ),
                    "player_name": (
                        player[
                            "player_name"
                        ]
                    ),
                    "team_abbreviation": (
                        player[
                            "current_team_2026_27"
                        ]
                    ),
                    "projection_season": (
                        season_label(
                            season_start
                        )
                    ),
                    "projection_horizon_years": (
                        horizon
                    ),
                    "projected_age": (
                        age
                    ),
                    "listed_salary": (
                        salary
                    ),
                    "under_listed_contract": (
                        under_contract
                    ),
                    "age_multiplier": (
                        age_multiplier
                    ),
                    "cumulative_survival_factor": (
                        cumulative_survival
                    ),
                    "continuity_factor": (
                        continuity_factor
                    ),
                    "projected_player_contribution": (
                        projected_expected
                    ),
                    "projected_player_downside": (
                        projected_downside
                    ),
                    "projected_player_upside": (
                        projected_upside
                    ),
                    "organizational_contribution": (
                        organizational_contribution
                    ),
                    "projected_contribution_sd": (
                        projected_sd
                    ),
                    "base_rotation_probability": (
                        rotation_probability
                    ),
                    "main_pool_eligible": (
                        bool(
                            player[
                                "main_pool_eligible"
                            ]
                        )
                    ),
                    "primary_skill": (
                        player.get(
                            "primary_skill",
                            "",
                        )
                    ),
                    "secondary_skill": (
                        player.get(
                            "secondary_skill",
                            "",
                        )
                    ),
                }
            )

    return pd.DataFrame(
        rows
    )


def aggregate_team_strength(
    future_players: pd.DataFrame,
) -> pd.DataFrame:
    team_rows = []

    for (
        projection_season,
        team,
    ), group in future_players.groupby(
        [
            "projection_season",
            "team_abbreviation",
        ],
        sort=True,
    ):
        ordered = (
            group.sort_values(
                "organizational_contribution",
                ascending=False,
            )
            .head(
                len(
                    ROTATION_WEIGHTS
                )
            )
            .copy()
        )

        weights = ROTATION_WEIGHTS[
            : len(
                ordered
            )
        ]

        weighted_contribution = float(
            np.sum(
                ordered[
                    "organizational_contribution"
                ].to_numpy(
                    dtype=float
                )
                * weights
            )
        )

        weighted_variance = float(
            np.sum(
                np.square(
                    ordered[
                        "projected_contribution_sd"
                    ].to_numpy(
                        dtype=float
                    )
                    * weights
                )
            )
        )

        top_three = float(
            ordered[
                "organizational_contribution"
            ].head(
                3
            ).sum()
        )

        top_eight = float(
            ordered[
                "organizational_contribution"
            ].head(
                8
            ).sum()
        )

        total_unweighted = float(
            ordered[
                "organizational_contribution"
            ].sum()
        )

        youth_core = float(
            ordered.loc[
                ordered[
                    "projected_age"
                ].le(25.0),
                "organizational_contribution",
            ].head(
                5
            ).sum()
        )

        contract_core = float(
            ordered.loc[
                ordered[
                    "under_listed_contract"
                ],
                "organizational_contribution",
            ].sum()
        )

        concentration = (
            top_three
            / total_unweighted
            if total_unweighted
            > 0.0
            else 0.0
        )

        team_rows.append(
            {
                "projection_season": (
                    projection_season
                ),
                "team_abbreviation": (
                    team
                ),
                "players_modeled": len(
                    group
                ),
                "rotation_players_used": len(
                    ordered
                ),
                "weighted_roster_strength_raw": (
                    weighted_contribution
                ),
                "weighted_roster_strength_sd_raw": (
                    np.sqrt(
                        weighted_variance
                    )
                ),
                "top_three_contribution": (
                    top_three
                ),
                "top_eight_contribution": (
                    top_eight
                ),
                "top_three_share": (
                    concentration
                ),
                "young_core_contribution": (
                    youth_core
                ),
                "listed_contract_core_contribution": (
                    contract_core
                ),
                "listed_contract_players": int(
                    ordered[
                        "under_listed_contract"
                    ].sum()
                ),
                "average_projected_age_top_eight": float(
                    ordered[
                        "projected_age"
                    ].head(
                        8
                    ).mean()
                ),
                "average_continuity_factor": float(
                    ordered[
                        "continuity_factor"
                    ].mean()
                ),
                "projection_horizon_years": int(
                    ordered[
                        "projection_horizon_years"
                    ].iloc[0]
                ),
            }
        )

    teams = pd.DataFrame(
        team_rows
    )

    adjusted_frames = []

    for season, group in teams.groupby(
        "projection_season",
        sort=True,
    ):
        season_group = group.copy()

        horizon = int(
            season_group[
                "projection_horizon_years"
            ].iloc[0]
        )

        league_average = float(
            season_group[
                "weighted_roster_strength_raw"
            ].mean()
        )

        regression_weight = (
            REGRESSION_TO_LEAGUE_AVERAGE[
                horizon
            ]
        )

        season_group[
            "team_strength_mean"
        ] = (
            (
                1.0
                - regression_weight
            )
            * season_group[
                "weighted_roster_strength_raw"
            ]
            + regression_weight
            * league_average
        )

        horizon_noise = (
            league_average
            * (
                0.025
                + 0.035
                * horizon
            )
        )

        season_group[
            "team_strength_sd"
        ] = np.sqrt(
            np.square(
                season_group[
                    "weighted_roster_strength_sd_raw"
                ]
            )
            + horizon_noise
            ** 2
        )

        season_group[
            "regression_to_league_average_weight"
        ] = regression_weight

        adjusted_frames.append(
            season_group
        )

    return pd.concat(
        adjusted_frames,
        ignore_index=True,
    )


def simulate_team_seasons(
    team_strength: pd.DataFrame,
    rank_win_curve: pd.DataFrame,
    simulations: int,
    random_seed: int,
) -> pd.DataFrame:
    if simulations < 1_000:
        raise ValueError(
            "--simulations must be at least 1,000."
        )

    rank_to_mean_wins = (
        rank_win_curve.set_index(
            "league_rank_by_wins"
        )[
            "mean_wins"
        ]
        .to_dict()
    )

    rank_to_sd_wins = (
        rank_win_curve.set_index(
            "league_rank_by_wins"
        )[
            "wins_sd"
        ]
        .to_dict()
    )

    rng = np.random.default_rng(
        random_seed
    )

    result_frames = []

    for season, group in (
        team_strength.groupby(
            "projection_season",
            sort=True,
        )
    ):
        season_group = (
            group.sort_values(
                "team_abbreviation"
            )
            .reset_index(
                drop=True
            )
            .copy()
        )

        teams = season_group[
            "team_abbreviation"
        ].to_numpy()

        means = season_group[
            "team_strength_mean"
        ].to_numpy(
            dtype=float
        )

        standard_deviations = (
            season_group[
                "team_strength_sd"
            ].to_numpy(
                dtype=float
            )
        )

        simulated_strength = rng.normal(
            loc=means,
            scale=standard_deviations,
            size=(
                simulations,
                len(
                    teams
                ),
            ),
        )

        order = np.argsort(
            -simulated_strength,
            axis=1,
        )

        ranks = np.empty_like(
            order
        )

        row_indices = np.arange(
            simulations
        )[
            :,
            None,
        ]

        ranks[
            row_indices,
            order,
        ] = (
            np.arange(
                len(
                    teams
                )
            )[
                None,
                :,
            ]
            + 1
        )

        wins = np.zeros_like(
            simulated_strength,
            dtype=float,
        )

        for rank in range(
            1,
            len(
                teams
            )
            + 1,
        ):
            rank_mean = float(
                rank_to_mean_wins.get(
                    rank,
                    41.0,
                )
            )

            rank_sd = float(
                rank_to_sd_wins.get(
                    rank,
                    3.0,
                )
            )

            rank_mask = (
                ranks == rank
            )

            rank_draws = rng.normal(
                loc=rank_mean,
                scale=rank_sd,
                size=int(
                    rank_mask.sum()
                ),
            )

            wins[
                rank_mask
            ] = rank_draws

        wins = np.clip(
            wins,
            8.0,
            74.0,
        )

        season_results = (
            season_group.copy()
        )

        season_results[
            "projected_mean_league_rank"
        ] = ranks.mean(
            axis=0
        )

        season_results[
            "projected_median_league_rank"
        ] = np.median(
            ranks,
            axis=0,
        )

        season_results[
            "projected_mean_wins_proxy"
        ] = wins.mean(
            axis=0
        )

        season_results[
            "projected_wins_sd_proxy"
        ] = wins.std(
            axis=0,
            ddof=1,
        )

        season_results[
            "projected_wins_p10_proxy"
        ] = np.quantile(
            wins,
            0.10,
            axis=0,
        )

        season_results[
            "projected_wins_p50_proxy"
        ] = np.quantile(
            wins,
            0.50,
            axis=0,
        )

        season_results[
            "projected_wins_p90_proxy"
        ] = np.quantile(
            wins,
            0.90,
            axis=0,
        )

        season_results[
            "top_4_league_probability"
        ] = (
            ranks <= 4
        ).mean(
            axis=0
        )

        season_results[
            "top_8_league_probability"
        ] = (
            ranks <= 8
        ).mean(
            axis=0
        )

        season_results[
            "top_12_league_probability"
        ] = (
            ranks <= 12
        ).mean(
            axis=0
        )

        season_results[
            "bottom_16_league_probability"
        ] = (
            ranks >= 15
        ).mean(
            axis=0
        )

        season_results[
            "bottom_10_league_probability"
        ] = (
            ranks >= 21
        ).mean(
            axis=0
        )

        season_results[
            "bottom_5_league_probability"
        ] = (
            ranks >= 26
        ).mean(
            axis=0
        )

        season_results[
            "best_record_probability"
        ] = (
            ranks == 1
        ).mean(
            axis=0
        )

        season_results[
            "worst_record_probability"
        ] = (
            ranks == len(
                teams
            )
        ).mean(
            axis=0
        )

        season_results[
            "team_strength_percentile"
        ] = (
            season_results[
                "team_strength_mean"
            ]
            .rank(
                method="average",
                pct=True,
            )
            * 100.0
        )

        result_frames.append(
            season_results
        )

    output = pd.concat(
        result_frames,
        ignore_index=True,
    )

    output[
        "projection_scope_note"
    ] = (
        "Roster-continuity and historical league-rank win proxy. "
        "This is not yet a conference playoff forecast or final "
        "future-pick valuation. Draft replenishment, future free "
        "agents, trades, lottery rules, and exact pick ownership "
        "are added in later stages."
    )

    return output.sort_values(
        [
            "projection_season",
            "projected_mean_league_rank",
        ]
    ).reset_index(
        drop=True
    )


def json_safe(
    value: Any,
) -> Any:
    if isinstance(
        value,
        dict,
    ):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }

    if isinstance(
        value,
        (
            list,
            tuple,
        ),
    ):
        return [
            json_safe(item)
            for item in value
        ]

    if isinstance(
        value,
        np.integer,
    ):
        return int(
            value
        )

    if isinstance(
        value,
        np.floating,
    ):
        if np.isnan(
            value
        ):
            return None

        return float(
            value
        )

    if isinstance(
        value,
        float,
    ):
        if math.isnan(
            value
        ):
            return None

        return value

    if pd.isna(
        value
    ):
        return None

    return value


def main() -> None:
    args = parse_args()

    for directory in [
        RAW_DIRECTORY,
        PROCESSED_DIRECTORY,
        OUTPUT_DIRECTORY,
    ]:
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    print("=" * 80)
    print("FUTURE NBA TEAM-STRENGTH PROJECTION ENGINE")
    print("=" * 80)
    print(
        f"Script version: {SCRIPT_VERSION}"
    )
    print(
        "Projection seasons: "
        f"{season_label(PROJECTION_SEASON_STARTS[0])} "
        "through "
        f"{season_label(PROJECTION_SEASON_STARTS[-1])}"
    )
    print(
        f"Simulations per season: "
        f"{args.simulations:,}"
    )
    print()

    players = load_projection_inputs()

    print(
        f"Projection-board players: "
        f"{len(players):,}"
    )
    print(
        "Current teams represented: "
        f"{players['current_team_2026_27'].nunique():,}"
    )

    records = (
        load_or_download_team_records(
            force_download=(
                args.force_team_record_download
            )
        )
    )

    rank_win_curve = build_rank_win_curve(
        records
    )

    future_players = build_future_player_rows(
        players
    )

    team_strength = aggregate_team_strength(
        future_players
    )

    projections = simulate_team_seasons(
        team_strength=team_strength,
        rank_win_curve=rank_win_curve,
        simulations=args.simulations,
        random_seed=args.random_seed,
    )

    future_players.to_parquet(
        PLAYER_FUTURE_PATH,
        index=False,
    )

    projections.to_parquet(
        TEAM_PROJECTION_PARQUET_PATH,
        index=False,
    )

    projections.to_csv(
        TEAM_PROJECTION_CSV_PATH,
        index=False,
    )

    rank_win_curve.to_csv(
        RANK_WIN_CURVE_PATH,
        index=False,
    )

    selected_summary = projections.loc[
        projections[
            "projection_season"
        ].isin(
            [
                "2026-27",
                "2028-29",
                "2030-31",
                "2032-33",
            ]
        ),
        [
            "projection_season",
            "team_abbreviation",
            "projected_mean_league_rank",
            "projected_mean_wins_proxy",
            "projected_wins_p10_proxy",
            "projected_wins_p90_proxy",
            "bottom_16_league_probability",
            "bottom_10_league_probability",
            "bottom_5_league_probability",
            "team_strength_percentile",
            "average_projected_age_top_eight",
            "listed_contract_players",
            "young_core_contribution",
        ],
    ].copy()

    selected_summary.to_csv(
        TEAM_SUMMARY_PATH,
        index=False,
    )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "projection_board_players": len(
            players
        ),
        "teams": int(
            players[
                "current_team_2026_27"
            ].nunique()
        ),
        "projection_seasons": [
            season_label(
                year
            )
            for year in (
                PROJECTION_SEASON_STARTS
            )
        ],
        "historical_team_seasons": int(
            records[
                "season"
            ].nunique()
        ),
        "historical_team_rows": len(
            records
        ),
        "simulations_per_projection_season": int(
            args.simulations
        ),
        "random_seed": int(
            args.random_seed
        ),
        "rotation_weights": (
            ROTATION_WEIGHTS.tolist()
        ),
        "regression_to_league_average": (
            REGRESSION_TO_LEAGUE_AVERAGE
        ),
        "methodology": [
            (
                "Current players begin with the availability-risk-"
                "adjusted expected contribution projection."
            ),
            (
                "Future contribution applies age multipliers, "
                "compounded survival, listed-contract continuity, "
                "and replacement value for unresolved roster spots."
            ),
            (
                "Team strength uses a weighted top-15 rotation "
                "rather than a raw sum of every roster player."
            ),
            (
                "Long-range projections regress toward league "
                "average as roster uncertainty grows."
            ),
            (
                "Monte Carlo team-strength ranks are converted to "
                "wins using the historical NBA league-rank win "
                "distribution from 2014-15 through 2025-26."
            ),
        ],
        "limitations": [
            (
                "Projected wins are rank-based proxies, not a "
                "game-level schedule model."
            ),
            (
                "Conference alignment and playoff qualification "
                "are not modeled in this stage."
            ),
            (
                "Future draft additions, free-agent signings, "
                "trades, coaching, and ownership decisions are "
                "represented only through regression and "
                "replacement uncertainty."
            ),
            (
                "Listed contract columns are payroll information, "
                "not a guarantee the player remains with the team."
            ),
            (
                "This stage does not yet apply lottery odds or "
                "value any specific owned pick."
            ),
        ],
        "output_files": {
            "historical_team_records": str(
                HISTORICAL_TEAM_RECORDS_PATH
            ),
            "future_player_inputs": str(
                PLAYER_FUTURE_PATH
            ),
            "future_team_projections": str(
                TEAM_PROJECTION_PARQUET_PATH
            ),
            "rank_win_curve": str(
                RANK_WIN_CURVE_PATH
            ),
            "selected_team_summary": str(
                TEAM_SUMMARY_PATH
            ),
        },
    }

    with METADATA_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            json_safe(
                metadata
            ),
            file,
            indent=2,
        )

    print()
    print("=" * 80)
    print("FUTURE TEAM-STRENGTH PROJECTIONS CREATED")
    print("=" * 80)
    print(
        f"Historical team rows: "
        f"{len(records):,}"
    )
    print(
        f"Future player-season rows: "
        f"{len(future_players):,}"
    )
    print(
        f"Future team-season rows: "
        f"{len(projections):,}"
    )
    print()

    for season in [
        "2026-27",
        "2028-29",
        "2030-31",
        "2032-33",
    ]:
        print(
            f"TOP AND BOTTOM TEAMS: {season}"
        )

        season_frame = (
            projections.loc[
                projections[
                    "projection_season"
                ].eq(
                    season
                )
            ]
            .sort_values(
                "projected_mean_league_rank"
            )
        )

        display = pd.concat(
            [
                season_frame.head(
                    5
                ),
                season_frame.tail(
                    5
                ),
            ],
            ignore_index=True,
        )[
            [
                "team_abbreviation",
                "projected_mean_league_rank",
                "projected_mean_wins_proxy",
                "projected_wins_p10_proxy",
                "projected_wins_p90_proxy",
                "bottom_16_league_probability",
                "bottom_5_league_probability",
                "team_strength_percentile",
            ]
        ].copy()

        percentage_columns = [
            "bottom_16_league_probability",
            "bottom_5_league_probability",
        ]

        for column in percentage_columns:
            display[column] = (
                display[column]
                * 100.0
            )

        for column in display.columns:
            if column != "team_abbreviation":
                display[column] = (
                    pd.to_numeric(
                        display[column],
                        errors="coerce",
                    )
                    .round(
                        2
                    )
                )

        print(
            display.to_string(
                index=False
            )
        )
        print()

    print("SAVED FILES")
    print(HISTORICAL_TEAM_RECORDS_PATH)
    print(HISTORICAL_TEAM_RECORDS_CSV_PATH)
    print(PLAYER_FUTURE_PATH)
    print(TEAM_PROJECTION_PARQUET_PATH)
    print(TEAM_PROJECTION_CSV_PATH)
    print(RANK_WIN_CURVE_PATH)
    print(TEAM_SUMMARY_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()