from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression


SCRIPT_VERSION = "historical-draft-pick-value-v1-2026-08-04"

PROJECT_ROOT = Path(__file__).resolve().parents[1]

UNIFIED_PLAYER_SEASONS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "unified_player_seasons_2014_15_2025_26.parquet"
)

RAW_DRAFT_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "draft"
)

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"
MODEL_DIRECTORY = PROJECT_ROOT / "models"

RAW_DRAFT_PARQUET_PATH = (
    RAW_DRAFT_DIRECTORY
    / "nba_draft_history_2014_2022.parquet"
)

RAW_DRAFT_CSV_PATH = (
    RAW_DRAFT_DIRECTORY
    / "nba_draft_history_2014_2022.csv"
)

PLAYER_OUTCOMES_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "historical_draft_player_outcomes_2014_2022.parquet"
)

PLAYER_OUTCOMES_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "historical_draft_player_outcomes_2014_2022.csv"
)

SLOT_CURVE_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "historical_draft_pick_value_curve_1_60_v1.parquet"
)

SLOT_CURVE_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "historical_draft_pick_value_curve_1_60_v1.csv"
)

VALIDATION_PATH = (
    OUTPUT_DIRECTORY
    / "historical_draft_pick_value_validation_by_class_v1.csv"
)

BAND_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "historical_draft_pick_value_band_summary_v1.csv"
)

MODEL_PATH = (
    MODEL_DIRECTORY
    / "historical_draft_pick_value_curve_v1.joblib"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "historical_draft_pick_value_metadata_v1.json"
)


DRAFT_YEAR_MIN = 2014
DRAFT_YEAR_MAX = 2022
ROOKIE_CONTRACT_SEASONS = 4

SEASON_VALUE_WEIGHTS = {
    "role_percentile": 0.45,
    "pie_percentile": 0.30,
    "net_rating_percentile": 0.10,
    "availability_percentile": 0.15,
}

PLAYER_PICK_TARGET_WEIGHTS = {
    "rookie_contract_value_percentile": 0.55,
    "starter_outcome": 0.20,
    "star_outcome": 0.10,
    "rotation_outcome": 0.10,
    "year4_active_outcome": 0.05,
}

DISCOUNT_WEIGHTS = {
    1: 1.00,
    2: 0.94,
    3: 0.88,
    4: 0.82,
}

UNIFIED_REQUIRED_COLUMNS = [
    "season",
    "player_id",
    "player_name",
    "games_played",
    "total_minutes",
    "minutes_per_game",
    "availability_rate",
    "minutes_availability_value",
    "advanced_pie",
    "advanced_net_rating",
    "rotation_player_flag",
    "high_minutes_flag",
]

DRAFT_REQUIRED_COLUMNS = [
    "person_id",
    "player_name",
    "draft_year",
    "round_number",
    "round_pick",
    "overall_pick",
    "draft_team_id",
    "draft_team_abbreviation",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a survivor-aware historical NBA draft-pick "
            "value curve from complete four-season rookie windows."
        )
    )

    parser.add_argument(
        "--force-download",
        action="store_true",
        help=(
            "Download NBA DraftHistory again even when the "
            "saved raw cache exists."
        ),
    )

    parser.add_argument(
        "--bootstrap-samples",
        type=int,
        default=300,
        help=(
            "Number of draft-class bootstrap samples used for "
            "slot-value uncertainty intervals."
        ),
    )

    parser.add_argument(
        "--random-seed",
        type=int,
        default=20260804,
        help="Random seed for bootstrap resampling.",
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


def player_key(value: Any) -> str:
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
    output = pd.to_numeric(
        frame[column],
        errors="coerce",
    )

    if fill_value is not None:
        output = output.fillna(
            fill_value
        )

    return output.astype(float)


def season_start_from_label(
    value: Any,
) -> float:
    if value is None or pd.isna(value):
        return np.nan

    text = str(value).strip()

    try:
        return float(
            int(
                text[:4]
            )
        )
    except (
        TypeError,
        ValueError,
    ):
        return np.nan


def rookie_season_label(
    draft_year: int,
) -> str:
    next_year_short = str(
        draft_year + 1
    )[-2:]

    return (
        f"{draft_year}-"
        f"{next_year_short}"
    )


def percentile_rank(
    values: pd.Series,
) -> pd.Series:
    numeric = pd.to_numeric(
        values,
        errors="coerce",
    )

    if numeric.notna().sum() == 0:
        return pd.Series(
            50.0,
            index=values.index,
        )

    filled = numeric.fillna(
        numeric.median()
    )

    return (
        filled.rank(
            method="average",
            pct=True,
        )
        * 100.0
    )


def safe_rank_correlation(
    actual: pd.Series,
    predicted: pd.Series,
) -> float:
    actual_numeric = pd.to_numeric(
        actual,
        errors="coerce",
    )

    predicted_numeric = pd.to_numeric(
        predicted,
        errors="coerce",
    )

    valid = (
        actual_numeric.notna()
        & predicted_numeric.notna()
    )

    if valid.sum() < 3:
        return float("nan")

    return float(
        actual_numeric.loc[
            valid
        ]
        .rank(
            method="average"
        )
        .corr(
            predicted_numeric.loc[
                valid
            ].rank(
                method="average"
            )
        )
    )


def load_unified_player_seasons() -> pd.DataFrame:
    if not UNIFIED_PLAYER_SEASONS_PATH.exists():
        raise FileNotFoundError(
            "Unified player-season data was not found:\n"
            f"{UNIFIED_PLAYER_SEASONS_PATH}"
        )

    frame = normalize_columns(
        pd.read_parquet(
            UNIFIED_PLAYER_SEASONS_PATH
        )
    )

    require_columns(
        frame,
        UNIFIED_REQUIRED_COLUMNS,
        "Unified player-season data",
    )

    frame[
        "player_merge_key"
    ] = frame[
        "player_id"
    ].map(
        player_key
    )

    if "season_start" in frame.columns:
        frame[
            "season_start"
        ] = numeric_series(
            frame,
            "season_start",
        )
    else:
        frame[
            "season_start"
        ] = frame[
            "season"
        ].map(
            season_start_from_label
        )

    numeric_columns = [
        "games_played",
        "total_minutes",
        "minutes_per_game",
        "availability_rate",
        "minutes_availability_value",
        "advanced_pie",
        "advanced_net_rating",
        "rotation_player_flag",
        "high_minutes_flag",
    ]

    for column in numeric_columns:
        frame[column] = numeric_series(
            frame,
            column,
            fill_value=0.0,
        )

    duplicate_mask = frame.duplicated(
        subset=[
            "season",
            "player_merge_key",
        ],
        keep=False,
    )

    if duplicate_mask.any():
        duplicates = frame.loc[
            duplicate_mask,
            [
                "season",
                "player_id",
                "player_name",
            ],
        ].head(30)

        raise ValueError(
            "Unified data contains duplicate player-season rows:\n"
            + duplicates.to_string(
                index=False
            )
        )

    return frame


def download_draft_history() -> pd.DataFrame:
    try:
        from nba_api.stats.endpoints import (
            drafthistory,
        )
    except ImportError as error:
        raise ImportError(
            "nba_api is required. Install it in the "
            "nba-roster-optimizer environment."
        ) from error

    print(
        "Downloading NBA DraftHistory from stats.nba.com..."
    )

    endpoint = drafthistory.DraftHistory(
        league_id="00",
        timeout=90,
    )

    frames = endpoint.get_data_frames()

    if not frames:
        raise RuntimeError(
            "NBA DraftHistory returned no data frames."
        )

    frame = normalize_columns(
        frames[0]
    )

    if frame.empty:
        raise RuntimeError(
            "NBA DraftHistory returned an empty table."
        )

    return frame


def clean_draft_history(
    raw: pd.DataFrame,
) -> pd.DataFrame:
    frame = normalize_columns(
        raw
    )

    rename_map = {
        "person_id": "person_id",
        "player_name": "player_name",
        "season": "draft_year",
        "round_number": "round_number",
        "round_pick": "round_pick",
        "overall_pick": "overall_pick",
        "team_id": "draft_team_id",
        "team_abbreviation": (
            "draft_team_abbreviation"
        ),
    }

    missing_sources = [
        column
        for column in rename_map
        if column not in frame.columns
    ]

    if missing_sources:
        raise ValueError(
            "DraftHistory response is missing expected columns:\n"
            + "\n".join(
                missing_sources
            )
        )

    frame = frame.rename(
        columns=rename_map
    )

    selected_columns = [
        "person_id",
        "player_name",
        "draft_year",
        "round_number",
        "round_pick",
        "overall_pick",
        "draft_team_id",
        "draft_team_abbreviation",
    ]

    for optional_column in [
        "team_city",
        "team_name",
        "organization",
        "organization_type",
        "draft_type",
    ]:
        if optional_column in frame.columns:
            selected_columns.append(
                optional_column
            )

    frame = frame[
        selected_columns
    ].copy()

    numeric_columns = [
        "draft_year",
        "round_number",
        "round_pick",
        "overall_pick",
        "draft_team_id",
    ]

    for column in numeric_columns:
        frame[column] = pd.to_numeric(
            frame[column],
            errors="coerce",
        )

    frame = frame.loc[
        frame[
            "draft_year"
        ].between(
            DRAFT_YEAR_MIN,
            DRAFT_YEAR_MAX,
            inclusive="both",
        )
        & frame[
            "round_number"
        ].isin(
            [
                1,
                2,
            ]
        )
        & frame[
            "overall_pick"
        ].between(
            1,
            60,
            inclusive="both",
        )
    ].copy()

    frame[
        "person_id"
    ] = frame[
        "person_id"
    ].map(
        player_key
    )

    integer_columns = [
        "draft_year",
        "round_number",
        "round_pick",
        "overall_pick",
        "draft_team_id",
    ]

    for column in integer_columns:
        frame[column] = (
            frame[column]
            .round()
            .astype(
                "Int64"
            )
        )

    frame[
        "rookie_season"
    ] = frame[
        "draft_year"
    ].astype(int).map(
        rookie_season_label
    )

    frame = frame.sort_values(
        [
            "draft_year",
            "overall_pick",
        ]
    ).reset_index(drop=True)

    duplicate_mask = frame.duplicated(
        subset=[
            "draft_year",
            "overall_pick",
        ],
        keep=False,
    )

    if duplicate_mask.any():
        duplicates = frame.loc[
            duplicate_mask,
            [
                "draft_year",
                "overall_pick",
                "player_name",
            ],
        ]

        raise ValueError(
            "Duplicate draft-year and overall-pick rows "
            "were found:\n"
            + duplicates.to_string(
                index=False
            )
        )

    require_columns(
        frame,
        DRAFT_REQUIRED_COLUMNS,
        "Clean draft history",
    )

    return frame


def load_or_download_draft_history(
    force_download: bool,
) -> pd.DataFrame:
    if (
        RAW_DRAFT_PARQUET_PATH.exists()
        and not force_download
    ):
        print(
            "Loading cached NBA DraftHistory:"
        )
        print(
            RAW_DRAFT_PARQUET_PATH
        )

        return clean_draft_history(
            pd.read_parquet(
                RAW_DRAFT_PARQUET_PATH
            )
        )

    raw = download_draft_history()
    cleaned = clean_draft_history(
        raw
    )

    RAW_DRAFT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    cleaned.to_parquet(
        RAW_DRAFT_PARQUET_PATH,
        index=False,
    )

    cleaned.to_csv(
        RAW_DRAFT_CSV_PATH,
        index=False,
    )

    time.sleep(0.6)

    return cleaned


def add_season_outcome_features(
    player_seasons: pd.DataFrame,
) -> pd.DataFrame:
    frame = player_seasons.copy()

    reliability = np.sqrt(
        (
            frame[
                "total_minutes"
            ]
            / 1_000.0
        ).clip(
            lower=0.0,
            upper=1.0,
        )
    )

    pie_median = frame.groupby(
        "season"
    )[
        "advanced_pie"
    ].transform(
        "median"
    )

    net_median = frame.groupby(
        "season"
    )[
        "advanced_net_rating"
    ].transform(
        "median"
    )

    frame[
        "reliability_weight"
    ] = reliability

    frame[
        "shrunk_advanced_pie"
    ] = (
        pie_median
        + reliability
        * (
            frame[
                "advanced_pie"
            ]
            - pie_median
        )
    )

    frame[
        "shrunk_advanced_net_rating"
    ] = (
        net_median
        + reliability
        * (
            frame[
                "advanced_net_rating"
            ]
            - net_median
        )
    )

    frame[
        "role_percentile"
    ] = (
        frame.groupby(
            "season"
        )[
            "minutes_availability_value"
        ]
        .rank(
            method="average",
            pct=True,
        )
        * 100.0
    )

    frame[
        "pie_percentile"
    ] = (
        frame.groupby(
            "season"
        )[
            "shrunk_advanced_pie"
        ]
        .rank(
            method="average",
            pct=True,
        )
        * 100.0
    )

    frame[
        "net_rating_percentile"
    ] = (
        frame.groupby(
            "season"
        )[
            "shrunk_advanced_net_rating"
        ]
        .rank(
            method="average",
            pct=True,
        )
        * 100.0
    )

    frame[
        "availability_percentile"
    ] = (
        frame.groupby(
            "season"
        )[
            "availability_rate"
        ]
        .rank(
            method="average",
            pct=True,
        )
        * 100.0
    )

    frame[
        "season_quality_role_score"
    ] = 0.0

    for component, weight in (
        SEASON_VALUE_WEIGHTS.items()
    ):
        frame[
            "season_quality_role_score"
        ] += (
            weight
            * frame[
                component
            ]
        )

    volume_factor = np.sqrt(
        (
            frame[
                "total_minutes"
            ]
            / 1_800.0
        ).clip(
            lower=0.0,
            upper=1.0,
        )
    )

    frame[
        "season_contribution_score"
    ] = (
        frame[
            "season_quality_role_score"
        ]
        * (
            0.20
            + 0.80
            * volume_factor
        )
    )

    frame[
        "starter_season_proxy"
    ] = (
        frame[
            "high_minutes_flag"
        ].ge(1)
        | (
            frame[
                "minutes_per_game"
            ].ge(24.0)
            & frame[
                "games_played"
            ].ge(40.0)
        )
    ).astype(int)

    frame[
        "star_season_proxy"
    ] = (
        frame[
            "starter_season_proxy"
        ].eq(1)
        & frame[
            "pie_percentile"
        ].ge(85.0)
        & frame[
            "season_contribution_score"
        ].ge(72.0)
    ).astype(int)

    return frame


def build_player_outcomes(
    draft_history: pd.DataFrame,
    player_seasons: pd.DataFrame,
) -> pd.DataFrame:
    season_features = (
        add_season_outcome_features(
            player_seasons
        )
    )

    season_lookup = {
        (
            row.player_merge_key,
            int(
                row.season_start
            ),
        ): row
        for row in season_features.itertuples(
            index=False
        )
        if (
            row.player_merge_key
            and pd.notna(
                row.season_start
            )
        )
    }

    rows: list[
        dict[str, Any]
    ] = []

    for draft_row in draft_history.to_dict(
        orient="records"
    ):
        player_id = player_key(
            draft_row[
                "person_id"
            ]
        )

        draft_year = int(
            draft_row[
                "draft_year"
            ]
        )

        season_records: list[
            dict[str, Any]
        ] = []

        for career_year in range(
            1,
            ROOKIE_CONTRACT_SEASONS + 1,
        ):
            season_start = (
                draft_year
                + career_year
                - 1
            )

            record = season_lookup.get(
                (
                    player_id,
                    season_start,
                )
            )

            if record is None:
                season_records.append(
                    {
                        "career_year": (
                            career_year
                        ),
                        "games_played": 0.0,
                        "total_minutes": 0.0,
                        "minutes_per_game": 0.0,
                        "availability_rate": 0.0,
                        "season_contribution_score": 0.0,
                        "rotation_player_flag": 0,
                        "starter_season_proxy": 0,
                        "star_season_proxy": 0,
                        "advanced_pie": 0.0,
                    }
                )

                continue

            season_records.append(
                {
                    "career_year": (
                        career_year
                    ),
                    "games_played": float(
                        record.games_played
                    ),
                    "total_minutes": float(
                        record.total_minutes
                    ),
                    "minutes_per_game": float(
                        record.minutes_per_game
                    ),
                    "availability_rate": float(
                        record.availability_rate
                    ),
                    "season_contribution_score": float(
                        record.season_contribution_score
                    ),
                    "rotation_player_flag": int(
                        record.rotation_player_flag
                    ),
                    "starter_season_proxy": int(
                        record.starter_season_proxy
                    ),
                    "star_season_proxy": int(
                        record.star_season_proxy
                    ),
                    "advanced_pie": float(
                        record.advanced_pie
                    ),
                }
            )

        seasons = pd.DataFrame(
            season_records
        )

        discounted_value = float(
            sum(
                seasons.loc[
                    seasons[
                        "career_year"
                    ].eq(
                        career_year
                    ),
                    "season_contribution_score",
                ].sum()
                * DISCOUNT_WEIGHTS[
                    career_year
                ]
                for career_year in range(
                    1,
                    ROOKIE_CONTRACT_SEASONS + 1,
                )
            )
        )

        player_row = {
            **draft_row,
            "player_merge_key": (
                player_id
            ),
            "rookie_contract_games": float(
                seasons[
                    "games_played"
                ].sum()
            ),
            "rookie_contract_total_minutes": float(
                seasons[
                    "total_minutes"
                ].sum()
            ),
            "rookie_contract_average_mpg": float(
                np.average(
                    seasons[
                        "minutes_per_game"
                    ],
                    weights=np.maximum(
                        seasons[
                            "games_played"
                        ],
                        1.0,
                    ),
                )
            ),
            "rookie_contract_average_availability": float(
                seasons[
                    "availability_rate"
                ].mean()
            ),
            "rookie_contract_value_units": (
                discounted_value
            ),
            "peak_season_contribution_score": float(
                seasons[
                    "season_contribution_score"
                ].max()
            ),
            "peak_advanced_pie": float(
                seasons[
                    "advanced_pie"
                ].max()
            ),
            "rotation_seasons": int(
                seasons[
                    "rotation_player_flag"
                ].sum()
            ),
            "starter_seasons": int(
                seasons[
                    "starter_season_proxy"
                ].sum()
            ),
            "star_proxy_seasons": int(
                seasons[
                    "star_season_proxy"
                ].sum()
            ),
            "rotation_outcome": int(
                seasons[
                    "rotation_player_flag"
                ].max()
            ),
            "starter_outcome": int(
                seasons[
                    "starter_season_proxy"
                ].max()
            ),
            "star_outcome": int(
                seasons[
                    "star_season_proxy"
                ].max()
            ),
            "year4_active_outcome": int(
                seasons.loc[
                    seasons[
                        "career_year"
                    ].eq(4),
                    "total_minutes",
                ].sum()
                > 0.0
            ),
            "never_appeared_in_unified_data": int(
                seasons[
                    "total_minutes"
                ].sum()
                <= 0.0
            ),
        }

        for career_year in range(
            1,
            ROOKIE_CONTRACT_SEASONS + 1,
        ):
            career_row = seasons.loc[
                seasons[
                    "career_year"
                ].eq(
                    career_year
                )
            ].iloc[0]

            player_row[
                f"year{career_year}_games"
            ] = float(
                career_row[
                    "games_played"
                ]
            )

            player_row[
                f"year{career_year}_minutes"
            ] = float(
                career_row[
                    "total_minutes"
                ]
            )

            player_row[
                (
                    f"year{career_year}_"
                    "contribution_score"
                )
            ] = float(
                career_row[
                    "season_contribution_score"
                ]
            )

        rows.append(
            player_row
        )

    outcomes = pd.DataFrame(
        rows
    )

    outcomes[
        "rookie_contract_value_percentile"
    ] = percentile_rank(
        outcomes[
            "rookie_contract_value_units"
        ]
    )

    outcomes[
        "player_pick_value_target"
    ] = 0.0

    for component, weight in (
        PLAYER_PICK_TARGET_WEIGHTS.items()
    ):
        values = outcomes[
            component
        ]

        if component.endswith(
            "_outcome"
        ):
            values = (
                values
                * 100.0
            )

        outcomes[
            "player_pick_value_target"
        ] += (
            weight
            * values
        )

    return outcomes.sort_values(
        [
            "draft_year",
            "overall_pick",
        ]
    ).reset_index(drop=True)


def fit_isotonic_curve(
    training: pd.DataFrame,
    target_column: str,
) -> IsotonicRegression:
    x = numeric_series(
        training,
        "overall_pick",
    ).to_numpy()

    y = numeric_series(
        training,
        target_column,
        fill_value=0.0,
    ).to_numpy()

    model = IsotonicRegression(
        increasing=False,
        out_of_bounds="clip",
        y_min=0.0,
    )

    model.fit(
        x,
        y,
    )

    return model


def validate_by_draft_class(
    outcomes: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for heldout_year in sorted(
        outcomes[
            "draft_year"
        ].dropna().astype(int).unique()
    ):
        train = outcomes.loc[
            outcomes[
                "draft_year"
            ].astype(int).ne(
                heldout_year
            )
        ].copy()

        test = outcomes.loc[
            outcomes[
                "draft_year"
            ].astype(int).eq(
                heldout_year
            )
        ].copy()

        model = fit_isotonic_curve(
            train,
            "player_pick_value_target",
        )

        prediction = model.predict(
            numeric_series(
                test,
                "overall_pick",
            ).to_numpy()
        )

        actual = numeric_series(
            test,
            "player_pick_value_target",
            fill_value=0.0,
        )

        error = (
            actual.to_numpy()
            - prediction
        )

        rows.append(
            {
                "heldout_draft_year": (
                    heldout_year
                ),
                "players": len(
                    test
                ),
                "mae": float(
                    np.mean(
                        np.abs(
                            error
                        )
                    )
                ),
                "rmse": float(
                    np.sqrt(
                        np.mean(
                            np.square(
                                error
                            )
                        )
                    )
                ),
                "bias_actual_minus_prediction": float(
                    np.mean(
                        error
                    )
                ),
                "rank_correlation": (
                    safe_rank_correlation(
                        actual,
                        pd.Series(
                            prediction,
                            index=test.index,
                        ),
                    )
                ),
                "actual_average_value": float(
                    actual.mean()
                ),
                "predicted_average_value": float(
                    np.mean(
                        prediction
                    )
                ),
            }
        )

    return pd.DataFrame(
        rows
    )


def bootstrap_pick_value_intervals(
    outcomes: pd.DataFrame,
    slot_grid: np.ndarray,
    bootstrap_samples: int,
    random_seed: int,
) -> tuple[
    np.ndarray,
    np.ndarray,
    np.ndarray,
]:
    if bootstrap_samples < 50:
        raise ValueError(
            "--bootstrap-samples must be at least 50."
        )

    draft_years = np.array(
        sorted(
            outcomes[
                "draft_year"
            ].astype(int).unique()
        )
    )

    rng = np.random.default_rng(
        random_seed
    )

    predictions = np.zeros(
        (
            bootstrap_samples,
            len(slot_grid),
        ),
        dtype=float,
    )

    for sample_index in range(
        bootstrap_samples
    ):
        sampled_years = rng.choice(
            draft_years,
            size=len(
                draft_years
            ),
            replace=True,
        )

        sampled_frames = []

        for synthetic_year_index, year in enumerate(
            sampled_years
        ):
            class_frame = outcomes.loc[
                outcomes[
                    "draft_year"
                ].astype(int).eq(
                    int(year)
                )
            ].copy()

            class_frame[
                "bootstrap_class_id"
            ] = synthetic_year_index

            sampled_frames.append(
                class_frame
            )

        sample = pd.concat(
            sampled_frames,
            ignore_index=True,
        )

        model = fit_isotonic_curve(
            sample,
            "player_pick_value_target",
        )

        predictions[
            sample_index,
            :,
        ] = model.predict(
            slot_grid
        )

    lower = np.quantile(
        predictions,
        0.10,
        axis=0,
    )

    median = np.quantile(
        predictions,
        0.50,
        axis=0,
    )

    upper = np.quantile(
        predictions,
        0.90,
        axis=0,
    )

    return (
        lower,
        median,
        upper,
    )


def pick_band(
    overall_pick: int,
) -> str:
    if overall_pick == 1:
        return "1"
    if overall_pick <= 3:
        return "2-3"
    if overall_pick <= 5:
        return "4-5"
    if overall_pick <= 10:
        return "6-10"
    if overall_pick <= 14:
        return "11-14"
    if overall_pick <= 20:
        return "15-20"
    if overall_pick <= 30:
        return "21-30"
    if overall_pick <= 40:
        return "31-40"
    if overall_pick <= 50:
        return "41-50"
    return "51-60"


def build_slot_curve(
    outcomes: pd.DataFrame,
    bootstrap_samples: int,
    random_seed: int,
) -> tuple[
    pd.DataFrame,
    dict[str, IsotonicRegression],
]:
    slot_grid = np.arange(
        1,
        61,
        dtype=float,
    )

    target_columns = [
        "player_pick_value_target",
        "rookie_contract_value_units",
        "rookie_contract_total_minutes",
        "rotation_outcome",
        "starter_outcome",
        "star_outcome",
        "year4_active_outcome",
    ]

    models = {
        target: fit_isotonic_curve(
            outcomes,
            target,
        )
        for target in target_columns
    }

    curve = pd.DataFrame(
        {
            "overall_pick": (
                slot_grid.astype(int)
            )
        }
    )

    curve[
        "round_number"
    ] = np.where(
        curve[
            "overall_pick"
        ].le(30),
        1,
        2,
    )

    curve[
        "round_pick"
    ] = np.where(
        curve[
            "overall_pick"
        ].le(30),
        curve[
            "overall_pick"
        ],
        curve[
            "overall_pick"
        ]
        - 30,
    )

    curve[
        "pick_band"
    ] = curve[
        "overall_pick"
    ].map(
        pick_band
    )

    curve[
        "historical_pick_value_score"
    ] = models[
        "player_pick_value_target"
    ].predict(
        slot_grid
    )

    curve[
        "expected_rookie_contract_value_units"
    ] = models[
        "rookie_contract_value_units"
    ].predict(
        slot_grid
    )

    curve[
        "expected_rookie_contract_minutes"
    ] = models[
        "rookie_contract_total_minutes"
    ].predict(
        slot_grid
    )

    probability_mapping = {
        "rotation_outcome": (
            "rotation_probability"
        ),
        "starter_outcome": (
            "starter_probability"
        ),
        "star_outcome": (
            "star_proxy_probability"
        ),
        "year4_active_outcome": (
            "year4_active_probability"
        ),
    }

    for target, output_column in (
        probability_mapping.items()
    ):
        curve[
            output_column
        ] = np.clip(
            models[
                target
            ].predict(
                slot_grid
            ),
            0.0,
            1.0,
        )

    (
        lower,
        median,
        upper,
    ) = bootstrap_pick_value_intervals(
        outcomes=outcomes,
        slot_grid=slot_grid,
        bootstrap_samples=(
            bootstrap_samples
        ),
        random_seed=random_seed,
    )

    curve[
        "pick_value_bootstrap_p10"
    ] = lower

    curve[
        "pick_value_bootstrap_median"
    ] = median

    curve[
        "pick_value_bootstrap_p90"
    ] = upper

    maximum_value = float(
        curve[
            "historical_pick_value_score"
        ].max()
    )

    if maximum_value <= 0.0:
        raise ValueError(
            "Historical pick-value curve has no "
            "positive values."
        )

    curve[
        "relative_pick_value_index_1_equals_100"
    ] = (
        curve[
            "historical_pick_value_score"
        ]
        / maximum_value
        * 100.0
    )

    curve[
        "pick_value_uncertainty_width"
    ] = (
        curve[
            "pick_value_bootstrap_p90"
        ]
        - curve[
            "pick_value_bootstrap_p10"
        ]
    )

    curve[
        "historical_sample_classes"
    ] = outcomes[
        "draft_year"
    ].nunique()

    curve[
        "historical_sample_players"
    ] = len(
        outcomes
    )

    curve[
        "value_scope_note"
    ] = (
        "Historical expected four-season rookie-window value. "
        "This is a draft-slot curve, not yet a future-pick value. "
        "Future team strength, lottery odds, protections, time "
        "discounting, and pick ownership are added later."
    )

    return (
        curve,
        models,
    )


def build_band_summary(
    curve: pd.DataFrame,
) -> pd.DataFrame:
    return (
        curve.groupby(
            [
                "round_number",
                "pick_band",
            ],
            as_index=False,
            sort=False,
        )
        .agg(
            first_pick=(
                "overall_pick",
                "min",
            ),
            last_pick=(
                "overall_pick",
                "max",
            ),
            average_historical_pick_value_score=(
                "historical_pick_value_score",
                "mean",
            ),
            average_relative_pick_value_index=(
                (
                    "relative_pick_value_index_"
                    "1_equals_100"
                ),
                "mean",
            ),
            average_rotation_probability=(
                "rotation_probability",
                "mean",
            ),
            average_starter_probability=(
                "starter_probability",
                "mean",
            ),
            average_star_proxy_probability=(
                "star_proxy_probability",
                "mean",
            ),
            average_year4_active_probability=(
                "year4_active_probability",
                "mean",
            ),
            average_expected_rookie_contract_minutes=(
                "expected_rookie_contract_minutes",
                "mean",
            ),
        )
    )


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
    args = parse_args()

    for directory in [
        RAW_DRAFT_DIRECTORY,
        PROCESSED_DIRECTORY,
        OUTPUT_DIRECTORY,
        MODEL_DIRECTORY,
    ]:
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    print("=" * 80)
    print("HISTORICAL NBA DRAFT-PICK VALUE ENGINE")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print(
        f"nba_api version: "
        f"{version('nba_api')}"
    )
    print(
        "Complete draft classes: "
        f"{DRAFT_YEAR_MIN}-{DRAFT_YEAR_MAX}"
    )
    print(
        "Rookie outcome window: "
        f"{ROOKIE_CONTRACT_SEASONS} seasons"
    )
    print(
        "Bootstrap samples: "
        f"{args.bootstrap_samples:,}"
    )
    print()

    player_seasons = (
        load_unified_player_seasons()
    )

    draft_history = (
        load_or_download_draft_history(
            force_download=(
                args.force_download
            )
        )
    )

    outcomes = build_player_outcomes(
        draft_history=draft_history,
        player_seasons=player_seasons,
    )

    validation = (
        validate_by_draft_class(
            outcomes
        )
    )

    curve, models = build_slot_curve(
        outcomes=outcomes,
        bootstrap_samples=(
            args.bootstrap_samples
        ),
        random_seed=(
            args.random_seed
        ),
    )

    band_summary = build_band_summary(
        curve
    )

    outcomes.to_parquet(
        PLAYER_OUTCOMES_PARQUET_PATH,
        index=False,
    )

    outcomes.to_csv(
        PLAYER_OUTCOMES_CSV_PATH,
        index=False,
    )

    curve.to_parquet(
        SLOT_CURVE_PARQUET_PATH,
        index=False,
    )

    curve.to_csv(
        SLOT_CURVE_CSV_PATH,
        index=False,
    )

    validation.to_csv(
        VALIDATION_PATH,
        index=False,
    )

    band_summary.to_csv(
        BAND_SUMMARY_PATH,
        index=False,
    )

    model_bundle = {
        "script_version": (
            SCRIPT_VERSION
        ),
        "draft_year_min": (
            DRAFT_YEAR_MIN
        ),
        "draft_year_max": (
            DRAFT_YEAR_MAX
        ),
        "rookie_contract_seasons": (
            ROOKIE_CONTRACT_SEASONS
        ),
        "season_value_weights": (
            SEASON_VALUE_WEIGHTS
        ),
        "player_pick_target_weights": (
            PLAYER_PICK_TARGET_WEIGHTS
        ),
        "discount_weights": (
            DISCOUNT_WEIGHTS
        ),
        "isotonic_models": models,
        "slot_curve": curve.copy(),
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
        "draft_year_min": (
            DRAFT_YEAR_MIN
        ),
        "draft_year_max": (
            DRAFT_YEAR_MAX
        ),
        "complete_draft_classes": int(
            outcomes[
                "draft_year"
            ].nunique()
        ),
        "drafted_players_in_sample": len(
            outcomes
        ),
        "first_round_players": int(
            outcomes[
                "round_number"
            ].eq(1).sum()
        ),
        "second_round_players": int(
            outcomes[
                "round_number"
            ].eq(2).sum()
        ),
        "players_never_appearing_in_unified_data": int(
            outcomes[
                "never_appeared_in_unified_data"
            ].sum()
        ),
        "rotation_outcome_rate": float(
            outcomes[
                "rotation_outcome"
            ].mean()
        ),
        "starter_outcome_rate": float(
            outcomes[
                "starter_outcome"
            ].mean()
        ),
        "star_proxy_outcome_rate": float(
            outcomes[
                "star_outcome"
            ].mean()
        ),
        "year4_active_rate": float(
            outcomes[
                "year4_active_outcome"
            ].mean()
        ),
        "validation_average_mae": float(
            validation[
                "mae"
            ].mean()
        ),
        "validation_average_rmse": float(
            validation[
                "rmse"
            ].mean()
        ),
        "validation_average_rank_correlation": float(
            validation[
                "rank_correlation"
            ].mean()
        ),
        "bootstrap_samples": int(
            args.bootstrap_samples
        ),
        "random_seed": int(
            args.random_seed
        ),
        "season_value_weights": (
            SEASON_VALUE_WEIGHTS
        ),
        "player_pick_target_weights": (
            PLAYER_PICK_TARGET_WEIGHTS
        ),
        "discount_weights": (
            DISCOUNT_WEIGHTS
        ),
        "important_scope": [
            (
                "Every drafted player remains in the sample, "
                "including players with zero NBA minutes in the "
                "available four-season window."
            ),
            (
                "The star outcome is a statistical proxy based "
                "on role, PIE percentile, and season value. It "
                "does not mean an All-Star selection."
            ),
            (
                "The curve values a known draft slot. Future-pick "
                "valuation still requires originating-team record "
                "projections, lottery simulation, protections, "
                "swaps, ownership, and time discounting."
            ),
            (
                "Relative pick value is internal model value and "
                "has not yet been calibrated to the current-player "
                "market-value scale."
            ),
        ],
        "output_files": {
            "raw_draft_history": str(
                RAW_DRAFT_PARQUET_PATH
            ),
            "player_outcomes": str(
                PLAYER_OUTCOMES_PARQUET_PATH
            ),
            "slot_value_curve": str(
                SLOT_CURVE_PARQUET_PATH
            ),
            "validation": str(
                VALIDATION_PATH
            ),
            "band_summary": str(
                BAND_SUMMARY_PATH
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

    print("=" * 80)
    print("HISTORICAL DRAFT VALUE CURVE CREATED")
    print("=" * 80)
    print(
        "Drafted players in sample: "
        f"{len(outcomes):,}"
    )
    print(
        "Complete draft classes: "
        f"{outcomes['draft_year'].nunique():,}"
    )
    print(
        "Players with zero NBA minutes in window: "
        f"{metadata['players_never_appearing_in_unified_data']:,}"
    )
    print(
        "Rotation outcome rate: "
        f"{metadata['rotation_outcome_rate']:.2%}"
    )
    print(
        "Starter outcome rate: "
        f"{metadata['starter_outcome_rate']:.2%}"
    )
    print(
        "Star-proxy outcome rate: "
        f"{metadata['star_proxy_outcome_rate']:.2%}"
    )
    print(
        "Year-4 active rate: "
        f"{metadata['year4_active_rate']:.2%}"
    )
    print()
    print(
        "Leave-one-draft-class-out MAE: "
        f"{metadata['validation_average_mae']:.3f}"
    )
    print(
        "Leave-one-draft-class-out RMSE: "
        f"{metadata['validation_average_rmse']:.3f}"
    )
    print(
        "Average rank correlation: "
        f"{metadata['validation_average_rank_correlation']:.3f}"
    )
    print()

    print("PICK-VALUE CURVE: SELECTED SLOTS")
    selected_slots = [
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

    display = curve.loc[
        curve[
            "overall_pick"
        ].isin(
            selected_slots
        ),
        [
            "overall_pick",
            "round_number",
            "historical_pick_value_score",
            (
                "relative_pick_value_index_"
                "1_equals_100"
            ),
            "rotation_probability",
            "starter_probability",
            "star_proxy_probability",
            "year4_active_probability",
            "pick_value_bootstrap_p10",
            "pick_value_bootstrap_p90",
        ],
    ].copy()

    percentage_columns = [
        "rotation_probability",
        "starter_probability",
        "star_proxy_probability",
        "year4_active_probability",
    ]

    for column in percentage_columns:
        display[column] = (
            display[column]
            * 100.0
        )

    numeric_display_columns = [
        column
        for column in display.columns
        if column
        not in {
            "overall_pick",
            "round_number",
        }
    ]

    for column in numeric_display_columns:
        display[column] = (
            pd.to_numeric(
                display[column],
                errors="coerce",
            )
            .round(2)
        )

    print(
        display.to_string(
            index=False
        )
    )
    print()

    print("DRAFT BAND SUMMARY")
    band_display = (
        band_summary.copy()
    )

    for column in [
        "average_rotation_probability",
        "average_starter_probability",
        "average_star_proxy_probability",
        "average_year4_active_probability",
    ]:
        band_display[column] = (
            band_display[column]
            * 100.0
        )

    for column in band_display.columns:
        if column not in {
            "round_number",
            "pick_band",
            "first_pick",
            "last_pick",
        }:
            band_display[column] = (
                pd.to_numeric(
                    band_display[column],
                    errors="coerce",
                )
                .round(2)
            )

    print(
        band_display.to_string(
            index=False
        )
    )
    print()

    print("SAVED FILES")
    print(RAW_DRAFT_PARQUET_PATH)
    print(RAW_DRAFT_CSV_PATH)
    print(PLAYER_OUTCOMES_PARQUET_PATH)
    print(PLAYER_OUTCOMES_CSV_PATH)
    print(SLOT_CURVE_PARQUET_PATH)
    print(SLOT_CURVE_CSV_PATH)
    print(VALIDATION_PATH)
    print(BAND_SUMMARY_PATH)
    print(MODEL_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()