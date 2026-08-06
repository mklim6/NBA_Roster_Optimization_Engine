"""Build a history-stabilized NBA player rating release.

V4.3 starts from the validated V4.2.1 candidate and its validated multi-season
history audit.

The goal is not to replace current-season evidence with reputation. Instead,
recent multi-season performance acts as a controlled stabilizer:

- one-season players receive zero history weight
- young players receive a smaller history weight
- established prime-age players receive the largest history weight
- older players receive a reduced history weight so genuine decline remains
  visible
- sustained history can remove an overly restrictive current tier cap
- sustained history cannot override the existing one-season or limited-evidence
  safeguards

This script does not alter projection models, trade values, optimizer inputs,
or legality data. The active Streamlit alias is updated only with --promote
after every validation passes.

Inputs
------
data/processed/player_rating_release_2026_27_v4_2_1.parquet
outputs/player_rating_v4_2_1_history_context_audit_v1.csv

Outputs
-------
data/processed/player_rating_release_2026_27_v4_3_history.parquet
data/processed/player_rating_release_2026_27_v4_3_history.csv
app_data/player_ratings_2026_27_v4_3_history.json
outputs/player_rating_v4_3_history_validation.csv
outputs/player_rating_v4_3_history_distribution.csv
outputs/player_rating_v4_3_history_player_audit.csv
outputs/player_rating_v4_3_history_top_100.csv
outputs/player_rating_v4_3_history_methodology.json
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "player-rating-history-stabilized-v4-3-2026-08-06"
)
RELEASE_NAME = "player_ratings_2026_27_v4_3_history"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"
APP_DATA_DIRECTORY = PROJECT_ROOT / "app_data"

RATING_CANDIDATES = [
    DATA_DIRECTORY
    / "player_rating_release_2026_27_v4_2_1.parquet",
    DATA_DIRECTORY
    / "player_rating_release_2026_27_v4_2_1.csv",
]
HISTORY_AUDIT_CANDIDATES = [
    OUTPUT_DIRECTORY
    / "player_rating_v4_2_1_history_context_audit_v1.csv",
]

OUTPUT_PARQUET = (
    DATA_DIRECTORY
    / "player_rating_release_2026_27_v4_3_history.parquet"
)
OUTPUT_CSV = OUTPUT_PARQUET.with_suffix(".csv")
OUTPUT_APP_JSON = (
    APP_DATA_DIRECTORY
    / "player_ratings_2026_27_v4_3_history.json"
)
ACTIVE_APP_ALIAS = (
    APP_DATA_DIRECTORY / "player_ratings_2026_27_v2.json"
)
ACTIVE_APP_BACKUP = (
    APP_DATA_DIRECTORY
    / "player_ratings_2026_27_v2_backup_before_v4_3_history.json"
)
VALIDATION_OUTPUT = (
    OUTPUT_DIRECTORY
    / "player_rating_v4_3_history_validation.csv"
)
DISTRIBUTION_OUTPUT = (
    OUTPUT_DIRECTORY
    / "player_rating_v4_3_history_distribution.csv"
)
PLAYER_AUDIT_OUTPUT = (
    OUTPUT_DIRECTORY
    / "player_rating_v4_3_history_player_audit.csv"
)
TOP_100_OUTPUT = (
    OUTPUT_DIRECTORY
    / "player_rating_v4_3_history_top_100.csv"
)
METHODOLOGY_OUTPUT = (
    OUTPUT_DIRECTORY
    / "player_rating_v4_3_history_methodology.json"
)

PERCENTILE_ANCHORS = np.array(
    [
        0.0,
        5.0,
        10.0,
        20.0,
        30.0,
        40.0,
        50.0,
        60.0,
        70.0,
        80.0,
        85.0,
        90.0,
        92.5,
        95.0,
        97.0,
        98.0,
        99.0,
        99.5,
        100.0,
    ],
    dtype=float,
)

OVERALL_RATING_ANCHORS = np.array(
    [
        60.0,
        64.0,
        67.0,
        71.0,
        74.0,
        77.0,
        79.5,
        81.5,
        83.5,
        85.5,
        87.0,
        89.0,
        90.5,
        92.5,
        94.5,
        95.7,
        96.9,
        97.7,
        98.5,
    ],
    dtype=float,
)

GRADE_THRESHOLDS = [
    (97.0, "A+"),
    (93.0, "A"),
    (90.0, "A-"),
    (87.0, "B+"),
    (83.0, "B"),
    (80.0, "B-"),
    (77.0, "C+"),
    (73.0, "C"),
    (70.0, "C-"),
    (67.0, "D+"),
    (63.0, "D"),
    (60.0, "D-"),
]

ROLE_THRESHOLDS = [
    (97.0, "MVP-level superstar"),
    (94.0, "Franchise superstar"),
    (90.0, "All-Star caliber"),
    (87.0, "High-end starter"),
    (83.0, "Quality starter"),
    (79.0, "Rotation player"),
    (75.0, "Bench contributor"),
    (70.0, "Depth player"),
    (60.0, "Developmental player"),
]

HISTORY_QUALITY_WEIGHTS = {
    "history_recent3_value_percentile": 0.45,
    "history_recent3_pie_percentile": 0.15,
    "history_recent3_role_percentile": 0.15,
    "history_latest_value_percentile": 0.10,
    "history_best_recent_value_percentile": 0.05,
    "history_persistence_score_v43": 0.10,
}

APP_COLUMNS = [
    "player_id",
    "player_name",
    "team_abbreviation",
    "age",
    "league_overall_rank",
    "team_overall_rank",
    "overall_rating",
    "overall_grade",
    "role_label",
    "archetype",
    "primary_skill",
    "secondary_skill",
    "primary_strength",
    "secondary_strength",
    "strengths",
    "concerns",
    "rating_confidence",
    "development_direction",
    "development_arrow",
    "future_peak_season",
    "games_played",
    "minutes_per_game",
    "points_per_game",
    "rebounds_per_game",
    "assists_per_game",
    "field_goal_pct",
    "three_point_pct",
    "true_shooting_pct",
    "usage_pct",
    "scoring_rating",
    "scoring_grade",
    "shooting_rating",
    "shooting_grade",
    "playmaking_rating",
    "playmaking_grade",
    "rebounding_rating",
    "rebounding_grade",
    "defense_rating",
    "defense_grade",
    "efficiency_rating",
    "efficiency_grade",
    "availability_rating",
    "availability_grade",
    "potential_rating",
    "potential_grade",
    "future_outlook_rating",
    "future_outlook_grade",
    "contract_value_rating",
    "contract_value_grade",
    "contract_value_source",
    "trade_value_rating",
    "trade_value_grade",
    "trade_value_source",
    "market_asset_class",
    "protected_player_flag",
    "salary_2026_27",
    "future_salary_commitment",
    "career_seasons",
    "career_games",
    "career_minutes",
    "evidence_weight",
    "history_recent3_value_percentile",
    "history_quality_score_v43",
    "history_weight_v43",
    "rating_scope_note",
    "finishing_scope_note",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run pure helper tests without loading project files.",
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        help=(
            "Promote the validated V4.3 candidate into the active "
            "Streamlit alias."
        ),
    )
    return parser.parse_args()


def locate(candidates: list[Path], label: str) -> Path:
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(
        f"{label} was not found:\n"
        + "\n".join(str(path) for path in candidates)
    )


def read_frame(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, low_memory=False)
    raise ValueError(f"Unsupported input format: {path}")


def normalize_player_id(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    try:
        numeric_value = float(value)
        if (
            math.isfinite(numeric_value)
            and numeric_value.is_integer()
        ):
            return str(int(numeric_value))
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text[:-2] if text.endswith(".0") else text


def safe_float(value: Any, default: float = np.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def numeric(
    frame: pd.DataFrame,
    column: str,
    default: float = np.nan,
) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(
            default,
            index=frame.index,
            dtype=float,
        )
    return pd.to_numeric(
        frame[column],
        errors="coerce",
    ).astype(float)


def empirical_percentile(values: pd.Series) -> pd.Series:
    numbers = pd.to_numeric(values, errors="coerce")
    valid = numbers.notna()
    output = pd.Series(
        50.0,
        index=numbers.index,
        dtype=float,
    )
    if valid.sum() == 0:
        return output
    output.loc[valid] = (
        numbers.loc[valid]
        .rank(method="average", pct=True)
        .mul(100.0)
    )
    return output.clip(0.0, 100.0)


def weighted_mean(
    frame: pd.DataFrame,
    weights: dict[str, float],
) -> pd.Series:
    if not math.isclose(
        sum(weights.values()),
        1.0,
        abs_tol=1e-9,
    ):
        raise ValueError("Weights must sum to 1.0.")

    missing = sorted(set(weights).difference(frame.columns))
    if missing:
        raise ValueError(
            "Weighted mean is missing columns:\n"
            + "\n".join(missing)
        )

    output = pd.Series(
        0.0,
        index=frame.index,
        dtype=float,
    )
    for column, weight in weights.items():
        output += (
            numeric(frame, column, 50.0)
            .fillna(50.0)
            .clip(0.0, 100.0)
            * weight
        )
    return output.clip(0.0, 100.0)


def rating_from_percentile(value: Any) -> float:
    percentile = float(
        np.clip(
            safe_float(value, 50.0),
            0.0,
            100.0,
        )
    )
    return round(
        float(
            np.interp(
                percentile,
                PERCENTILE_ANCHORS,
                OVERALL_RATING_ANCHORS,
            )
        ),
        1,
    )


def grade_from_rating(value: Any) -> str:
    rating = safe_float(value, 60.0)
    for threshold, grade in GRADE_THRESHOLDS:
        if rating >= threshold:
            return grade
    return "D-"


def role_from_rating(value: Any) -> str:
    rating = safe_float(value, 60.0)
    for threshold, role in ROLE_THRESHOLDS:
        if rating >= threshold:
            return role
    return "Developmental player"


def age_history_multiplier(age: Any) -> float:
    value = safe_float(age, 28.0)
    ages = np.array(
        [
            18.0,
            21.0,
            24.0,
            27.0,
            30.0,
            33.0,
            36.0,
            40.0,
        ]
    )
    multipliers = np.array(
        [
            0.25,
            0.35,
            0.60,
            1.00,
            1.00,
            0.80,
            0.60,
            0.45,
        ]
    )
    return float(
        np.interp(value, ages, multipliers)
    )


def history_depth_score(
    recent_seasons: Any,
    career_seasons: Any,
    recent_minutes: Any,
) -> float:
    recent = float(
        np.clip(
            safe_float(recent_seasons, 0.0) / 3.0,
            0.0,
            1.0,
        )
    )
    career = float(
        np.clip(
            safe_float(career_seasons, 0.0) / 5.0,
            0.0,
            1.0,
        )
    )
    minutes = float(
        np.clip(
            safe_float(recent_minutes, 0.0) / 6500.0,
            0.0,
            1.0,
        )
    )
    return (
        0.40 * recent
        + 0.30 * career
        + 0.30 * minutes
    )


def history_weight(
    recent_seasons: Any,
    career_seasons: Any,
    recent_minutes: Any,
    age: Any,
) -> float:
    # One season is current evidence, not sustained history.
    if safe_float(recent_seasons, 0.0) < 2.0:
        return 0.0

    depth = history_depth_score(
        recent_seasons,
        career_seasons,
        recent_minutes,
    )
    multiplier = age_history_multiplier(age)

    return round(
        float(
            np.clip(
                0.38 * depth * multiplier,
                0.0,
                0.38,
            )
        ),
        5,
    )


def persistence_score(
    elite_seasons: Any,
    star_seasons: Any,
    quality_seasons: Any,
) -> float:
    elite = safe_float(elite_seasons, 0.0)
    star = safe_float(star_seasons, 0.0)
    quality = safe_float(quality_seasons, 0.0)

    value = (
        45.0
        + 10.0 * elite
        + 5.0 * star
        + 2.5 * quality
    )
    return round(float(np.clip(value, 0.0, 100.0)), 3)


def history_supported_cap(row: pd.Series) -> tuple[float, str]:
    """Return a history-supported tier ceiling.

    This only removes an overly restrictive current cap for established players.
    It never sets the actual OVR and never applies to one-season players.
    """
    recent_seasons = safe_float(
        row.get("history_recent_seasons"),
        0.0,
    )
    career_seasons = safe_float(
        row.get("career_seasons"),
        0.0,
    )
    history_quality = safe_float(
        row.get("history_quality_score_v43"),
        50.0,
    )
    latest = safe_float(
        row.get("history_latest_value_percentile"),
        50.0,
    )
    elite = safe_float(
        row.get("history_recent_elite_seasons"),
        0.0,
    )
    star = safe_float(
        row.get("history_recent_star_seasons"),
        0.0,
    )

    if recent_seasons < 3.0 or career_seasons < 3.0:
        return 60.0, "no_history_tier_support"

    if (
        history_quality >= 97.0
        and latest >= 92.0
        and elite >= 2.0
        and star >= 3.0
    ):
        return 98.5, "sustained_franchise_support"

    if (
        history_quality >= 94.0
        and latest >= 85.0
        and elite >= 2.0
        and star >= 3.0
    ):
        return 96.5, "sustained_superstar_support"

    if (
        history_quality >= 90.0
        and latest >= 80.0
        and star >= 2.0
    ):
        return 93.5, "sustained_all_star_support"

    if (
        history_quality >= 85.0
        and latest >= 75.0
        and star >= 2.0
    ):
        return 90.5, "sustained_high_starter_support"

    return 60.0, "no_history_tier_support"


def minimum_potential_gap(age: Any) -> float:
    value = safe_float(age, 28.0)
    if value <= 20.0:
        return 2.5
    if value <= 22.0:
        return 2.0
    if value <= 24.0:
        return 1.5
    if value <= 26.0:
        return 0.7
    if value <= 27.0:
        return 0.3
    return 0.0


def maximum_potential_gain(age: Any) -> float:
    value = safe_float(age, 28.0)
    ages = np.array(
        [
            18.0,
            20.0,
            22.0,
            24.0,
            26.0,
            28.0,
            30.0,
            33.0,
            36.0,
            40.0,
        ]
    )
    gains = np.array(
        [
            10.0,
            9.0,
            8.0,
            6.5,
            4.5,
            2.5,
            1.2,
            0.5,
            0.2,
            0.0,
        ]
    )
    return float(np.interp(value, ages, gains))


def skill_breadth_potential_cap(
    overall: Any,
    skill_mean: Any,
) -> float:
    current = safe_float(overall, 60.0)
    breadth = safe_float(skill_mean, 50.0)

    if breadth < 52.0:
        return min(93.0, current + 5.0)
    if breadth < 60.0:
        return min(94.5, current + 6.5)
    if breadth < 68.0:
        return min(96.0, current + 8.0)
    if breadth < 76.0:
        return min(97.5, current + 9.0)
    return 99.5


def merge_history(
    ratings: pd.DataFrame,
    history: pd.DataFrame,
) -> pd.DataFrame:
    ratings = ratings.copy()
    history = history.copy()

    ratings["player_id"] = ratings["player_id"].map(
        normalize_player_id
    )
    history["player_id"] = history["player_id"].map(
        normalize_player_id
    )

    if ratings["player_id"].duplicated().any():
        raise ValueError("Duplicate player IDs in rating input.")
    if history["player_id"].duplicated().any():
        raise ValueError("Duplicate player IDs in history audit.")

    history_columns = [
        "player_id",
        "history_recent_seasons",
        "history_recent3_value_percentile",
        "history_recent3_league_rank",
        "history_recent3_pie_percentile",
        "history_recent3_role_percentile",
        "history_best_recent_value_percentile",
        "history_worst_recent_value_percentile",
        "history_recent_elite_seasons",
        "history_recent_star_seasons",
        "history_recent_quality_seasons",
        "history_recent_total_minutes",
        "history_latest_season",
        "history_latest_value_percentile",
    ]
    missing = sorted(
        set(history_columns).difference(history.columns)
    )
    if missing:
        raise ValueError(
            "History audit is missing required columns:\n"
            + "\n".join(missing)
        )

    merged = ratings.merge(
        history[history_columns],
        how="left",
        on="player_id",
        validate="one_to_one",
    )

    if merged["history_recent_seasons"].isna().any():
        missing_players = merged.loc[
            merged["history_recent_seasons"].isna(),
            ["player_id", "player_name"],
        ]
        raise ValueError(
            "History audit did not cover every rated player:\n"
            + missing_players.head(25).to_string(index=False)
        )

    return merged


def build_v43(
    ratings: pd.DataFrame,
    history: pd.DataFrame,
) -> pd.DataFrame:
    output = merge_history(ratings, history)

    output["history_persistence_score_v43"] = [
        persistence_score(
            row.get("history_recent_elite_seasons"),
            row.get("history_recent_star_seasons"),
            row.get("history_recent_quality_seasons"),
        )
        for row in output.to_dict(orient="records")
    ]

    output["history_quality_score_v43"] = weighted_mean(
        output,
        HISTORY_QUALITY_WEIGHTS,
    )

    output["history_depth_score_v43"] = [
        history_depth_score(
            row.get("history_recent_seasons"),
            row.get("career_seasons"),
            row.get("history_recent_total_minutes"),
        )
        for row in output.to_dict(orient="records")
    ]
    output["history_age_multiplier_v43"] = output[
        "age"
    ].map(age_history_multiplier)
    output["history_weight_v43"] = [
        history_weight(
            row.get("history_recent_seasons"),
            row.get("career_seasons"),
            row.get("history_recent_total_minutes"),
            row.get("age"),
        )
        for row in output.to_dict(orient="records")
    ]

    current_percentile = numeric(
        output,
        "overall_league_percentile_v4",
        np.nan,
    )
    if current_percentile.isna().any():
        current_percentile = empirical_percentile(
            numeric(
                output,
                "overall_continuous_score_v4",
                numeric(output, "overall_rating", 60.0),
            )
        )

    output["current_percentile_before_history_v43"] = (
        current_percentile.clip(0.0, 100.0)
    )
    output["history_adjusted_percentile_v43"] = (
        (
            1.0 - output["history_weight_v43"]
        )
        * output["current_percentile_before_history_v43"]
        + output["history_weight_v43"]
        * output["history_quality_score_v43"]
    ).clip(0.0, 100.0)

    output["history_adjusted_rating_pre_cap_v43"] = output[
        "history_adjusted_percentile_v43"
    ].map(rating_from_percentile)

    support_results = output.apply(
        history_supported_cap,
        axis=1,
        result_type="expand",
    )
    support_results.columns = [
        "history_supported_cap_v43",
        "history_support_reason_v43",
    ]
    output = pd.concat(
        [output, support_results],
        axis=1,
    )

    existing_cap = numeric(
        output,
        "tier_eligibility_cap_v4",
        98.5,
    )
    output["effective_tier_cap_v43"] = np.maximum(
        existing_cap,
        output["history_supported_cap_v43"],
    ).clip(60.0, 98.5)

    # Existing one-season and limited-evidence caps remain binding because
    # history support requires at least three seasons.
    output["overall_rating"] = np.minimum(
        output["history_adjusted_rating_pre_cap_v43"],
        output["effective_tier_cap_v43"],
    )
    output["overall_rating"] = (
        output["overall_rating"]
        .clip(60.0, 98.5)
        .round(1)
    )

    output["overall_continuous_score_v43"] = (
        output["history_adjusted_percentile_v43"]
    )

    output = output.sort_values(
        [
            "overall_rating",
            "overall_continuous_score_v43",
            "player_name",
        ],
        ascending=[False, False, True],
    ).reset_index(drop=True)

    output["league_overall_rank"] = np.arange(
        1,
        len(output) + 1,
    )
    output["team_overall_rank"] = (
        output.groupby("team_abbreviation")[
            "overall_rating"
        ]
        .rank(method="first", ascending=False)
        .astype("Int64")
    )
    output["overall_league_percentile_v43"] = (
        empirical_percentile(
            output["overall_continuous_score_v43"]
        )
    )
    output["overall_grade"] = output[
        "overall_rating"
    ].map(grade_from_rating)
    output["role_label"] = output[
        "overall_rating"
    ].map(role_from_rating)

    # Recalculate potential from the existing potential signal but with the new
    # current OVR. This keeps POT a ceiling rather than a historical rating.
    potential_signal = numeric(
        output,
        "potential_signal_v4",
        50.0,
    )
    normalized_signal = (
        (potential_signal - 45.0) / 55.0
    ).clip(0.0, 1.0) ** 1.25

    minimum_gap = output["age"].map(
        minimum_potential_gap
    )
    maximum_gain = output["age"].map(
        maximum_potential_gain
    )
    modeled_gain = (
        minimum_gap
        + (
            maximum_gain - minimum_gap
        ).clip(lower=0.0)
        * normalized_signal
    )

    output["potential_rating_pre_cap_v43"] = (
        output["overall_rating"] + modeled_gain
    )
    output["potential_breadth_cap_v43"] = [
        skill_breadth_potential_cap(
            row.get("overall_rating"),
            row.get("skill_mean_percentile_rating"),
        )
        for row in output.to_dict(orient="records")
    ]

    output["potential_rating"] = np.minimum(
        output["potential_rating_pre_cap_v43"],
        output["potential_breadth_cap_v43"],
    )
    output["potential_rating"] = np.maximum(
        output["potential_rating"],
        output["overall_rating"] + minimum_gap,
    )
    output["potential_rating"] = (
        output["potential_rating"]
        .clip(60.0, 99.5)
        .round(1)
    )
    output["potential_grade"] = output[
        "potential_rating"
    ].map(grade_from_rating)

    # Recover a raw future rating from V3 percentile when available so the
    # V4.2.1 blend is not blended a second time.
    if "future_outlook_percentile_v3" in output.columns:
        raw_future = output[
            "future_outlook_percentile_v3"
        ].map(rating_from_percentile)
    elif "future_ceiling_rank_pct" in output.columns:
        raw_future = output[
            "future_ceiling_rank_pct"
        ].map(rating_from_percentile)
    else:
        raw_future = numeric(
            output,
            "future_outlook_rating",
            numeric(output, "overall_rating"),
        )

    output["future_outlook_rating"] = (
        0.65 * raw_future
        + 0.35 * output["overall_rating"]
    )
    output["future_outlook_rating"] = np.minimum(
        output["future_outlook_rating"],
        output["potential_rating"],
    )
    output["future_outlook_rating"] = (
        output["future_outlook_rating"]
        .clip(60.0, 99.5)
        .round(1)
    )
    output["future_outlook_grade"] = output[
        "future_outlook_rating"
    ].map(grade_from_rating)

    potential_gap = (
        output["potential_rating"]
        - output["overall_rating"]
    )
    future_gap = (
        output["future_outlook_rating"]
        - output["overall_rating"]
    )

    output["development_direction"] = np.select(
        [
            (
                output["age"].le(28.0)
                & potential_gap.ge(1.5)
                & future_gap.ge(-2.5)
            ),
            (
                output["age"].ge(29.0)
                & future_gap.le(-2.0)
            ),
        ],
        ["Rising", "Declining"],
        default="Stable",
    )
    output["development_arrow"] = output[
        "development_direction"
    ].map(
        {
            "Rising": "↑",
            "Stable": "→",
            "Declining": "↓",
        }
    )

    output["rating_scope_note"] = (
        "V4.3 OVR blends current V4.2.1 evidence with a controlled "
        "multi-season history stabilizer. One-season players receive zero "
        "history weight. POT remains a career ceiling and FUT remains a "
        "future projection. Source models and optimizer values are unchanged."
    )

    return output


def find_player(
    frame: pd.DataFrame,
    names: list[str],
) -> pd.Series | None:
    normalized_names = {
        name.casefold()
        for name in names
    }
    matches = frame.loc[
        frame["player_name"]
        .astype(str)
        .str.casefold()
        .isin(normalized_names)
    ]
    return None if matches.empty else matches.iloc[0]


def rank_alignment_mae(
    frame: pd.DataFrame,
    rank_column: str,
) -> float:
    eligible = frame.loc[
        numeric(frame, "career_seasons", 0.0).ge(3.0)
        & numeric(
            frame,
            "history_recent_seasons",
            0.0,
        ).ge(3.0)
    ].copy()

    if eligible.empty:
        return float("nan")

    return float(
        (
            numeric(eligible, rank_column)
            - numeric(
                eligible,
                "history_recent3_league_rank",
            )
        )
        .abs()
        .mean()
    )


def validation_rows(
    original: pd.DataFrame,
    candidate: pd.DataFrame,
) -> list[dict[str, Any]]:
    def check(
        name: str,
        passed: bool,
        observed: Any,
        expected: Any,
        severity: str = "required",
    ) -> dict[str, Any]:
        return {
            "check_name": name,
            "passed": bool(passed),
            "severity": severity,
            "observed": observed,
            "expected": expected,
        }

    kon = find_player(candidate, ["Kon Knueppel"])
    moussa = find_player(
        candidate,
        ["Moussa Diabaté", "Moussa Diabate"],
    )

    elite_count = int(
        candidate["overall_rating"].ge(93.0).sum()
    )
    all_star_count = int(
        candidate["overall_rating"].ge(90.0).sum()
    )
    high_starter_count = int(
        candidate["overall_rating"].ge(87.0).sum()
    )

    old_alignment = rank_alignment_mae(
        candidate.assign(
            original_league_overall_rank=original.set_index(
                original["player_id"].map(normalize_player_id)
            ).reindex(candidate["player_id"])[
                "league_overall_rank"
            ].to_numpy()
        ),
        "original_league_overall_rank",
    )
    new_alignment = rank_alignment_mae(
        candidate,
        "league_overall_rank",
    )

    one_season = candidate.loc[
        numeric(candidate, "career_seasons", 0.0).le(1.0)
    ]
    top_five = candidate.head(5)
    rating_97 = candidate.loc[
        candidate["overall_rating"].ge(97.0)
    ]

    top_five_supported = (
        numeric(
            top_five,
            "history_recent3_value_percentile",
            0.0,
        ).ge(90.0)
        | (
            numeric(
                top_five,
                "career_seasons",
                0.0,
            ).lt(3.0)
            & numeric(
                top_five,
                "history_latest_value_percentile",
                0.0,
            ).ge(95.0)
        )
    ).all()

    rating_97_supported = (
        rating_97.empty
        or (
            numeric(
                rating_97,
                "history_quality_score_v43",
                0.0,
            ).ge(94.0)
            | (
                numeric(
                    rating_97,
                    "career_seasons",
                    0.0,
                ).lt(3.0)
                & numeric(
                    rating_97,
                    "history_latest_value_percentile",
                    0.0,
                ).ge(97.0)
            )
        ).all()
    )

    return [
        check(
            "player_count_preserved",
            len(original) == len(candidate) == 582,
            len(candidate),
            582,
        ),
        check(
            "player_ids_unique",
            candidate["player_id"].is_unique
            and candidate["player_id"].ne("").all(),
            int(candidate["player_id"].nunique()),
            len(candidate),
        ),
        check(
            "history_coverage_complete",
            candidate[
                "history_recent_seasons"
            ].notna().all(),
            int(
                candidate[
                    "history_recent_seasons"
                ].notna().sum()
            ),
            len(candidate),
        ),
        check(
            "overall_scale_valid",
            candidate["overall_rating"]
            .between(60.0, 98.5)
            .all(),
            {
                "minimum": float(
                    candidate["overall_rating"].min()
                ),
                "maximum": float(
                    candidate["overall_rating"].max()
                ),
            },
            "60.0-98.5",
        ),
        check(
            "potential_never_below_overall",
            candidate["potential_rating"]
            .ge(candidate["overall_rating"])
            .all(),
            int(
                candidate["potential_rating"]
                .lt(candidate["overall_rating"])
                .sum()
            ),
            0,
        ),
        check(
            "future_never_above_potential",
            candidate["future_outlook_rating"]
            .le(candidate["potential_rating"])
            .all(),
            int(
                candidate["future_outlook_rating"]
                .gt(candidate["potential_rating"])
                .sum()
            ),
            0,
        ),
        check(
            "one_season_players_not_all_stars",
            one_season["overall_rating"].lt(90.0).all(),
            int(
                one_season["overall_rating"]
                .ge(90.0)
                .sum()
            ),
            0,
        ),
        check(
            "elite_population_selective",
            5 <= elite_count <= 24,
            elite_count,
            "5-24 at 93.0+",
        ),
        check(
            "all_star_population_selective",
            18 <= all_star_count <= 55,
            all_star_count,
            "18-55 at 90.0+",
        ),
        check(
            "high_starter_population_reasonable",
            45 <= high_starter_count <= 115,
            high_starter_count,
            "45-115 at 87.0+",
        ),
        check(
            "median_overall_reasonable",
            77.0
            <= float(
                candidate["overall_rating"].median()
            )
            <= 81.0,
            round(
                float(
                    candidate["overall_rating"].median()
                ),
                3,
            ),
            "77.0-81.0",
        ),
        check(
            "history_alignment_improves",
            (
                math.isfinite(old_alignment)
                and math.isfinite(new_alignment)
                and new_alignment <= old_alignment
            ),
            {
                "before_mae": round(old_alignment, 3),
                "after_mae": round(new_alignment, 3),
            },
            "after <= before",
        ),
        check(
            "top_five_have_history_support",
            top_five_supported,
            top_five[
                [
                    "player_name",
                    "history_recent3_value_percentile",
                    "history_latest_value_percentile",
                    "career_seasons",
                ]
            ].to_dict(orient="records"),
            "recent3 >=90 or young exceptional latest season",
        ),
        check(
            "ninety_seven_plus_have_history_support",
            rating_97_supported,
            rating_97[
                [
                    "player_name",
                    "overall_rating",
                    "history_quality_score_v43",
                    "history_latest_value_percentile",
                    "career_seasons",
                ]
            ].to_dict(orient="records"),
            "history quality >=94 or young exceptional latest season",
        ),
        check(
            "kon_current_rating_moderated",
            (
                kon is None
                or (
                    int(kon["league_overall_rank"]) > 50
                    and float(kon["overall_rating"]) <= 87.5
                    and float(kon["history_weight_v43"]) == 0.0
                )
            ),
            (
                None
                if kon is None
                else {
                    "rank": int(
                        kon["league_overall_rank"]
                    ),
                    "overall": float(
                        kon["overall_rating"]
                    ),
                    "potential": float(
                        kon["potential_rating"]
                    ),
                    "future": float(
                        kon["future_outlook_rating"]
                    ),
                    "history_weight": float(
                        kon["history_weight_v43"]
                    ),
                }
            ),
            "rank >50, OVR <=87.5, history weight 0",
            severity="player_sanity",
        ),
        check(
            "moussa_has_ceiling_room",
            (
                moussa is None
                or (
                    float(moussa["potential_rating"])
                    - float(moussa["overall_rating"])
                    >= 2.0
                )
            ),
            (
                None
                if moussa is None
                else {
                    "rank": int(
                        moussa["league_overall_rank"]
                    ),
                    "overall": float(
                        moussa["overall_rating"]
                    ),
                    "potential": float(
                        moussa["potential_rating"]
                    ),
                    "gap": round(
                        float(moussa["potential_rating"])
                        - float(moussa["overall_rating"]),
                        3,
                    ),
                }
            ),
            "POT-OVR >=2.0",
            severity="player_sanity",
        ),
        check(
            "finishing_remains_unreleased",
            (
                "finishing_rating_released"
                not in candidate.columns
                or not candidate[
                    "finishing_rating_released"
                ].fillna(False).astype(bool).any()
            ),
            False,
            False,
        ),
    ]


def distribution_summary(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    rating_columns = [
        "overall_rating",
        "potential_rating",
        "future_outlook_rating",
        "scoring_rating",
        "shooting_rating",
        "playmaking_rating",
        "rebounding_rating",
        "defense_rating",
        "efficiency_rating",
        "availability_rating",
        "contract_value_rating",
        "trade_value_rating",
    ]

    rows: list[dict[str, Any]] = []
    for column in rating_columns:
        values = numeric(frame, column)
        rows.append(
            {
                "rating": column,
                "count": int(values.notna().sum()),
                "minimum": round(
                    float(values.min()),
                    3,
                ),
                "p10": round(
                    float(values.quantile(0.10)),
                    3,
                ),
                "p25": round(
                    float(values.quantile(0.25)),
                    3,
                ),
                "median": round(
                    float(values.median()),
                    3,
                ),
                "mean": round(
                    float(values.mean()),
                    3,
                ),
                "p75": round(
                    float(values.quantile(0.75)),
                    3,
                ),
                "p90": round(
                    float(values.quantile(0.90)),
                    3,
                ),
                "p95": round(
                    float(values.quantile(0.95)),
                    3,
                ),
                "maximum": round(
                    float(values.max()),
                    3,
                ),
            }
        )
    return pd.DataFrame(rows)


def player_audit(frame: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "league_overall_rank",
        "player_id",
        "player_name",
        "team_abbreviation",
        "age",
        "overall_rating",
        "potential_rating",
        "future_outlook_rating",
        "career_seasons",
        "career_games",
        "career_minutes",
        "evidence_weight",
        "demonstrated_rating_v4",
        "projection_based_rating_v4",
        "tier_eligibility_cap_v4",
        "tier_gate_reasons_v4",
        "history_recent_seasons",
        "history_recent3_value_percentile",
        "history_recent3_league_rank",
        "history_recent3_pie_percentile",
        "history_recent3_role_percentile",
        "history_latest_value_percentile",
        "history_recent_elite_seasons",
        "history_recent_star_seasons",
        "history_recent_quality_seasons",
        "history_persistence_score_v43",
        "history_quality_score_v43",
        "history_depth_score_v43",
        "history_age_multiplier_v43",
        "history_weight_v43",
        "current_percentile_before_history_v43",
        "history_adjusted_percentile_v43",
        "history_adjusted_rating_pre_cap_v43",
        "history_supported_cap_v43",
        "history_support_reason_v43",
        "effective_tier_cap_v43",
        "archetype",
    ]
    return frame[
        [
            column
            for column in columns
            if column in frame.columns
        ]
    ].copy()


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
        return (
            None
            if np.isnan(value)
            else float(value)
        )
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def build_app_payload(
    frame: pd.DataFrame,
    methodology: dict[str, Any],
) -> dict[str, Any]:
    available = [
        column
        for column in APP_COLUMNS
        if column in frame.columns
    ]
    records = (
        frame[available]
        .where(pd.notna(frame[available]), None)
        .to_dict(orient="records")
    )

    players_by_id = {
        str(record["player_id"]): json_safe(record)
        for record in records
    }
    player_ids_by_team: dict[str, list[str]] = {}
    for record in records:
        team = str(
            record.get("team_abbreviation", "")
        )
        player_ids_by_team.setdefault(
            team,
            [],
        ).append(str(record["player_id"]))

    return {
        "release_name": RELEASE_NAME,
        "script_version": SCRIPT_VERSION,
        "league_year": "2026-27",
        "rating_scale": {
            "overall_minimum": 60.0,
            "overall_maximum": 98.5,
            "potential_maximum": 99.5,
            "decimals": 1,
        },
        "player_count": len(records),
        "methodology": methodology,
        "players_by_id": players_by_id,
        "player_ids_by_team": player_ids_by_team,
    }


def validate_app_payload(
    payload: dict[str, Any],
    expected_player_count: int,
) -> None:
    if payload.get("release_name") != RELEASE_NAME:
        raise ValueError(
            "Candidate app payload has the wrong release name."
        )

    players = payload.get("players_by_id")
    if not isinstance(players, dict):
        raise ValueError(
            "Candidate app payload is missing players_by_id."
        )
    if len(players) != expected_player_count:
        raise ValueError(
            "Candidate app payload player count mismatch."
        )

    required = {
        "player_id",
        "player_name",
        "league_overall_rank",
        "overall_rating",
        "potential_rating",
        "future_outlook_rating",
    }
    for player_id, row in players.items():
        if not isinstance(row, dict):
            raise ValueError(
                f"Invalid player payload: {player_id}"
            )
        missing = required.difference(row)
        if missing:
            raise ValueError(
                f"Player {player_id} is missing app fields: "
                + ", ".join(sorted(missing))
            )


def promote_active_alias(
    candidate_text: str,
    expected_player_count: int,
) -> None:
    candidate_payload = json.loads(candidate_text)
    validate_app_payload(
        candidate_payload,
        expected_player_count,
    )

    if ACTIVE_APP_ALIAS.exists():
        ACTIVE_APP_BACKUP.write_text(
            ACTIVE_APP_ALIAS.read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )

    temporary_path = ACTIVE_APP_ALIAS.with_suffix(
        ".json.tmp"
    )
    temporary_path.write_text(
        candidate_text,
        encoding="utf-8",
    )

    temporary_payload = json.loads(
        temporary_path.read_text(
            encoding="utf-8"
        )
    )
    validate_app_payload(
        temporary_payload,
        expected_player_count,
    )
    temporary_path.replace(ACTIVE_APP_ALIAS)


def run_self_test() -> int:
    tests = {
        "history_weights_sum_to_one": math.isclose(
            sum(HISTORY_QUALITY_WEIGHTS.values()),
            1.0,
        ),
        "one_season_has_zero_history_weight": (
            history_weight(
                recent_seasons=1,
                career_seasons=1,
                recent_minutes=2500,
                age=20,
            )
            == 0.0
        ),
        "prime_established_has_more_history_weight": (
            history_weight(
                recent_seasons=3,
                career_seasons=6,
                recent_minutes=7000,
                age=28,
            )
            > history_weight(
                recent_seasons=3,
                career_seasons=6,
                recent_minutes=7000,
                age=35,
            )
        ),
        "history_weight_capped": (
            history_weight(
                recent_seasons=3,
                career_seasons=12,
                recent_minutes=9000,
                age=28,
            )
            <= 0.38
        ),
        "persistence_score_ordering": (
            persistence_score(3, 3, 3)
            > persistence_score(1, 1, 1)
        ),
        "rating_curve_monotonic": (
            rating_from_percentile(99.0)
            > rating_from_percentile(90.0)
            > rating_from_percentile(50.0)
        ),
        "young_potential_floor": (
            minimum_potential_gap(24) == 1.5
        ),
        "history_support_requires_three_seasons": (
            history_supported_cap(
                pd.Series(
                    {
                        "history_recent_seasons": 1,
                        "career_seasons": 1,
                        "history_quality_score_v43": 99,
                        "history_latest_value_percentile": 99,
                        "history_recent_elite_seasons": 1,
                        "history_recent_star_seasons": 1,
                    }
                )
            )[0]
            == 60.0
        ),
        "sustained_history_supports_tier": (
            history_supported_cap(
                pd.Series(
                    {
                        "history_recent_seasons": 3,
                        "career_seasons": 6,
                        "history_quality_score_v43": 95,
                        "history_latest_value_percentile": 92,
                        "history_recent_elite_seasons": 2,
                        "history_recent_star_seasons": 3,
                    }
                )
            )[0]
            >= 96.5
        ),
        "candidate_and_active_paths_distinct": (
            OUTPUT_APP_JSON != ACTIVE_APP_ALIAS
        ),
        "backup_and_active_paths_distinct": (
            ACTIVE_APP_BACKUP != ACTIVE_APP_ALIAS
        ),
    }
    print(json.dumps(tests, indent=2))
    return 0 if all(tests.values()) else 1


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    rating_path = locate(
        RATING_CANDIDATES,
        "V4.2.1 rating candidate",
    )
    history_path = locate(
        HISTORY_AUDIT_CANDIDATES,
        "V4.2.1 history audit",
    )

    print("=" * 92)
    print("PLAYER RATING RELEASE V4.3 HISTORY-STABILIZED")
    print("=" * 92)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    print("[1/6] Loading V4.2.1 and validated history audit")
    original = read_frame(rating_path)
    history = read_frame(history_path)
    print(
        f"  Ratings: {len(original):,} x "
        f"{len(original.columns):,}"
    )
    print(
        f"  History audit: {len(history):,} x "
        f"{len(history.columns):,}"
    )

    print("[2/6] Building history quality and reliability weights")
    print("[3/6] Blending current evidence with sustained performance")
    print("[4/6] Recalculating OVR, POT, FUT, and league ranks")
    candidate = build_v43(original, history)

    print("[5/6] Running distribution and realism validation")
    validations = pd.DataFrame(
        validation_rows(original, candidate)
    )
    required = validations.loc[
        validations["severity"].eq("required")
    ]
    player_sanity = validations.loc[
        validations["severity"].eq(
            "player_sanity"
        )
    ]
    release_valid = bool(
        required["passed"].all()
        and player_sanity["passed"].all()
    )

    distribution = distribution_summary(candidate)
    audit = player_audit(candidate)

    kon = find_player(
        candidate,
        ["Kon Knueppel"],
    )
    moussa = find_player(
        candidate,
        ["Moussa Diabaté", "Moussa Diabate"],
    )

    old_alignment = rank_alignment_mae(
        candidate.assign(
            original_league_overall_rank=original.set_index(
                original["player_id"].map(
                    normalize_player_id
                )
            ).reindex(candidate["player_id"])[
                "league_overall_rank"
            ].to_numpy()
        ),
        "original_league_overall_rank",
    )
    new_alignment = rank_alignment_mae(
        candidate,
        "league_overall_rank",
    )

    methodology = {
        "release_name": RELEASE_NAME,
        "script_version": SCRIPT_VERSION,
        "created_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "release_valid": release_valid,
        "rating_source": str(rating_path),
        "history_source": str(history_path),
        "history_quality_weights": (
            HISTORY_QUALITY_WEIGHTS
        ),
        "history_weight_design": {
            "maximum_weight": 0.38,
            "one_season_weight": 0.0,
            "depth_components": {
                "recent_seasons": 0.40,
                "career_seasons": 0.30,
                "recent_minutes": 0.30,
            },
            "age_note": (
                "Prime-age established players receive the largest "
                "history weight; young and older players receive less."
            ),
        },
        "rank_alignment": {
            "before_mae": old_alignment,
            "after_mae": new_alignment,
        },
        "promotion_requested": bool(args.promote),
        "active_alias_promoted": bool(
            args.promote and release_valid
        ),
        "validation_passed": int(
            validations["passed"].sum()
        ),
        "validation_total": len(validations),
        "outputs": {
            "parquet": str(OUTPUT_PARQUET),
            "csv": str(OUTPUT_CSV),
            "app_json": str(OUTPUT_APP_JSON),
            "active_alias": str(ACTIVE_APP_ALIAS),
            "active_alias_backup": str(
                ACTIVE_APP_BACKUP
            ),
            "validation": str(VALIDATION_OUTPUT),
            "distribution": str(
                DISTRIBUTION_OUTPUT
            ),
            "player_audit": str(
                PLAYER_AUDIT_OUTPUT
            ),
            "top_100": str(TOP_100_OUTPUT),
        },
    }

    print("[6/6] Writing candidate artifacts")
    DATA_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )
    APP_DATA_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    candidate.to_parquet(
        OUTPUT_PARQUET,
        index=False,
    )
    candidate.to_csv(
        OUTPUT_CSV,
        index=False,
    )
    validations.to_csv(
        VALIDATION_OUTPUT,
        index=False,
    )
    distribution.to_csv(
        DISTRIBUTION_OUTPUT,
        index=False,
    )
    audit.to_csv(
        PLAYER_AUDIT_OUTPUT,
        index=False,
    )
    audit.head(100).to_csv(
        TOP_100_OUTPUT,
        index=False,
    )

    METHODOLOGY_OUTPUT.write_text(
        json.dumps(
            json_safe(methodology),
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = build_app_payload(
        candidate,
        methodology,
    )
    validate_app_payload(
        payload,
        expected_player_count=len(candidate),
    )
    payload_text = json.dumps(
        json_safe(payload),
        indent=2,
        ensure_ascii=False,
    )
    OUTPUT_APP_JSON.write_text(
        payload_text,
        encoding="utf-8",
    )

    promoted = False
    if args.promote:
        if not release_valid:
            raise RuntimeError(
                "Promotion requested, but V4.3 failed validation."
            )
        promote_active_alias(
            payload_text,
            expected_player_count=len(candidate),
        )
        promoted = True

    print("Complete")
    print(
        f"Validation: "
        f"{int(validations['passed'].sum())}/"
        f"{len(validations)}"
    )
    print(f"Release valid: {release_valid}")
    print(f"Promotion requested: {bool(args.promote)}")
    print(f"Active app alias promoted: {promoted}")
    print(f"Players rated: {len(candidate):,}")
    print(
        "Overall distribution: "
        f"{candidate['overall_rating'].min():.1f}-"
        f"{candidate['overall_rating'].max():.1f} | "
        f"median "
        f"{candidate['overall_rating'].median():.1f} | "
        f"std "
        f"{candidate['overall_rating'].std():.1f}"
    )
    print(
        "OVR tiers: "
        f"93+ "
        f"{candidate['overall_rating'].ge(93).sum()} | "
        f"90+ "
        f"{candidate['overall_rating'].ge(90).sum()} | "
        f"87+ "
        f"{candidate['overall_rating'].ge(87).sum()}"
    )
    print(
        "Established-player history rank MAE: "
        f"{old_alignment:.1f} -> {new_alignment:.1f}"
    )

    for name, row in [
        ("Kon Knueppel", kon),
        ("Moussa Diabaté", moussa),
    ]:
        if row is not None:
            print(
                f"{name}: "
                f"rank #{int(row['league_overall_rank'])} | "
                f"OVR {float(row['overall_rating']):.1f} | "
                f"POT {float(row['potential_rating']):.1f} | "
                f"FUT "
                f"{float(row['future_outlook_rating']):.1f} | "
                f"history "
                f"{float(row['history_quality_score_v43']):.1f} | "
                f"history weight "
                f"{float(row['history_weight_v43']):.3f}"
            )

    print()
    print("TOP 30 V4.3 OVERALL RATINGS")
    print(
        candidate[
            [
                "league_overall_rank",
                "player_name",
                "team_abbreviation",
                "overall_rating",
                "potential_rating",
                "future_outlook_rating",
                "history_recent3_value_percentile",
                "history_quality_score_v43",
                "history_weight_v43",
                "history_support_reason_v43",
                "career_seasons",
                "archetype",
            ]
        ]
        .head(30)
        .to_string(index=False)
    )

    print()
    print("LARGEST RANK CHANGES FROM V4.2.1")
    rank_comparison = candidate[
        [
            "player_id",
            "player_name",
            "league_overall_rank",
            "overall_rating",
        ]
    ].merge(
        original.assign(
            player_id=original["player_id"].map(
                normalize_player_id
            )
        )[
            [
                "player_id",
                "league_overall_rank",
                "overall_rating",
            ]
        ].rename(
            columns={
                "league_overall_rank": (
                    "v4_2_1_league_rank"
                ),
                "overall_rating": "v4_2_1_overall",
            }
        ),
        on="player_id",
        how="left",
        validate="one_to_one",
    )
    rank_comparison["rank_change"] = (
        rank_comparison["v4_2_1_league_rank"]
        - rank_comparison["league_overall_rank"]
    )
    print(
        rank_comparison.reindex(
            rank_comparison["rank_change"]
            .abs()
            .sort_values(ascending=False)
            .index
        )
        .head(25)
        .to_string(index=False)
    )

    failed = validations.loc[
        ~validations["passed"]
    ]
    if not failed.empty:
        print()
        print("FAILED VALIDATION CHECKS")
        print(failed.to_string(index=False))

    if release_valid and not args.promote:
        print()
        print(
            "Candidate is valid but not live. Review the rankings, "
            "then re-run with --promote."
        )

    return 0 if release_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())