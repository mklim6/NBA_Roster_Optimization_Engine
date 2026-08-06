"""Build the calibrated 2026-27 NBA player-rating release.

This release creates presentation ratings on a 60.0-99.9 scale while
preserving the original full-precision optimizer and projection values.

Ratings released:
    OVR, scoring, shooting, playmaking, rebounding, defense, efficiency,
    availability, potential, contract value, and trade value.

Finishing is intentionally not released because the current audited sources
do not include direct rim-attempt frequency and rim efficiency.

Outputs:
    data/processed/player_rating_release_2026_27_v1.parquet
    data/processed/player_rating_release_2026_27_v1.csv
    app_data/player_ratings_2026_27_v1.json
    outputs/player_rating_release_validation_v1.csv
    outputs/player_rating_distribution_summary_v1.csv
    outputs/player_rating_top_50_v1.csv
    outputs/player_rating_methodology_v1.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


SCRIPT_VERSION = "player-rating-release-v1-2026-08-06"
RELEASE_NAME = "player_ratings_2026_27_v1"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"
APP_DATA_DIRECTORY = PROJECT_ROOT / "app_data"

SOURCE_CANDIDATES = {
    "projection": [
        DATA_DIRECTORY
        / "current_player_projection_board_2025_26_to_2026_27.parquet",
        DATA_DIRECTORY
        / "current_player_projection_board_2025_26_to_2026_27.csv",
    ],
    "skills": [
        DATA_DIRECTORY / "player_skill_profiles_2025_26.parquet",
        DATA_DIRECTORY / "player_skill_profiles_2025_26.csv",
    ],
    "market": [
        DATA_DIRECTORY
        / "player_trade_market_value_layer_2026_27_v4_protected.parquet",
        DATA_DIRECTORY
        / "player_trade_market_value_layer_2026_27_v4_protected.csv",
        DATA_DIRECTORY
        / "player_trade_market_value_layer_2026_27_v3.parquet",
        DATA_DIRECTORY
        / "player_trade_market_value_layer_2026_27_v3.csv",
        DATA_DIRECTORY
        / "player_trade_market_value_layer_2026_27_v2.parquet",
        DATA_DIRECTORY
        / "player_trade_market_value_layer_2026_27_v2.csv",
        DATA_DIRECTORY
        / "player_trade_market_value_layer_2026_27.parquet",
        DATA_DIRECTORY
        / "player_trade_market_value_layer_2026_27.csv",
    ],
    "financial": [
        DATA_DIRECTORY / "player_financial_layer_2026_27_v2.parquet",
        DATA_DIRECTORY / "player_financial_layer_2026_27_v2.csv",
        DATA_DIRECTORY / "player_financial_layer_2026_27.parquet",
        DATA_DIRECTORY / "player_financial_layer_2026_27.csv",
    ],
    "future": [
        DATA_DIRECTORY
        / "future_player_team_strength_inputs_2026_27_to_2032_33_v1.parquet",
        DATA_DIRECTORY
        / "future_player_team_strength_inputs_2026_27_to_2032_33_v1.csv",
    ],
}

OUTPUT_PARQUET = (
    DATA_DIRECTORY / "player_rating_release_2026_27_v1.parquet"
)
OUTPUT_CSV = OUTPUT_PARQUET.with_suffix(".csv")
APP_JSON = (
    APP_DATA_DIRECTORY / "player_ratings_2026_27_v1.json"
)
VALIDATION_OUTPUT = (
    OUTPUT_DIRECTORY / "player_rating_release_validation_v1.csv"
)
DISTRIBUTION_OUTPUT = (
    OUTPUT_DIRECTORY / "player_rating_distribution_summary_v1.csv"
)
TOP_PLAYERS_OUTPUT = (
    OUTPUT_DIRECTORY / "player_rating_top_50_v1.csv"
)
METHODOLOGY_OUTPUT = (
    OUTPUT_DIRECTORY / "player_rating_methodology_v1.json"
)

RATING_MINIMUM = 60.0
RATING_MAXIMUM = 99.9
RATING_DECIMALS = 1

ROTATION_POPULATION_MINIMUM_GAMES = 10
ROTATION_POPULATION_MINIMUM_MPG = 8.0

SKILL_DIMENSIONS = [
    "scoring",
    "shooting",
    "playmaking",
    "rebounding",
    "defense",
]

OVR_PERCENTILE_WEIGHTS = {
    "expected_contribution_percentile_rating": 0.30,
    "downside_contribution_percentile_rating": 0.15,
    "roster_value_percentile_rating": 0.15,
    "skill_mean_percentile_rating": 0.15,
    "skill_peak_percentile_rating": 0.10,
    "efficiency_percentile_rating": 0.10,
    "availability_percentile_rating": 0.05,
}

EFFICIENCY_WEIGHTS = {
    "true_shooting_percentile": 0.40,
    "effective_field_goal_percentile": 0.20,
    "pie_percentile": 0.20,
    "net_rating_percentile": 0.20,
}

AVAILABILITY_WEIGHTS = {
    "availability_rate_percentile": 0.40,
    "games_played_percentile": 0.25,
    "survival_probability_percentile": 0.20,
    "rotation_probability_percentile": 0.15,
}

POTENTIAL_WEIGHTS = {
    "peak_future_contribution_percentile": 0.55,
    "future_growth_percentile": 0.30,
    "long_horizon_contribution_percentile": 0.15,
}

FALLBACK_TRADE_VALUE_WEIGHTS = {
    "overall_percentile": 0.50,
    "potential_percentile": 0.20,
    "contract_value_percentile_rating": 0.15,
    "age_runway_score": 0.10,
    "availability_percentile_rating": 0.05,
}

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

SEASON_COLUMN_CANDIDATES = [
    "projection_season",
    "season",
    "projected_season",
    "target_season",
    "future_season",
    "season_start",
]

FUTURE_CONTRIBUTION_CANDIDATES = [
    "projected_player_contribution",
    "projected_expected_contribution",
    "projected_contribution",
    "expected_contribution",
    "active_expected_contribution",
    "future_strength_contribution",
    "team_strength_contribution",
    "projected_player_strength",
    "player_strength_contribution",
    "survival_weighted_contribution",
]

COLUMN_CANDIDATES = {
    "player_name": [
        "player_name",
        "player_display_name",
    ],
    "team": [
        "team_abbreviation",
        "current_team_2026_27",
        "team",
    ],
    "age": [
        "age",
        "age_2026_27",
        "projection_age",
    ],
    "games": ["games_played", "gp"],
    "minutes": ["minutes_per_game", "mpg"],
    "points": ["points_per_game", "ppg"],
    "rebounds": ["rebounds_per_game", "rpg"],
    "assists": ["assists_per_game", "apg"],
    "fg_pct": ["base_fg_pct", "fg_pct"],
    "three_pct": ["base_fg3_pct", "fg3_pct", "three_point_pct"],
    "ts_pct": ["advanced_ts_pct", "ts_pct"],
    "efg_pct": ["advanced_efg_pct", "efg_pct"],
    "pie": ["advanced_pie", "pie"],
    "net_rating": ["advanced_net_rating", "net_rating"],
    "usage": ["advanced_usg_pct", "usage_pct"],
    "availability": ["availability_rate"],
    "expected_contribution": [
        "projected_expected_contribution",
        "expected_contribution",
    ],
    "downside_contribution": [
        "survival_weighted_active_downside_score",
        "projected_active_downside_contribution_80",
        "projected_downside_contribution",
    ],
    "upside_contribution": [
        "projected_active_upside_contribution_80",
        "projected_upside_contribution",
    ],
    "survival_probability": [
        "projected_survival_probability",
        "survival_probability",
    ],
    "rotation_probability": [
        "projected_rotation_probability",
        "rotation_probability",
    ],
    "roster_value_score": ["roster_value_score"],
    "roster_value_percentile": ["roster_value_percentile"],
    "reliability_weight": ["reliability_weight"],
    "confidence_tier": ["confidence_tier"],
    "value_tier": ["value_tier"],
    "primary_skill": ["primary_skill"],
    "secondary_skill": ["secondary_skill"],
    "contract_value_raw": [
        "projected_contract_value_score",
        "contract_value_score",
        "downside_contract_value_score",
    ],
    "contract_value_percentile": [
        "contract_value_percentile",
    ],
    "salary_2026_27": [
        "salary_2026_27",
        "trade_salary_2026_27",
    ],
    "future_salary_commitment": [
        "future_salary_commitment_2027_28_plus",
        "future_salary_commitment",
        "guaranteed_remaining",
    ],
    "under_contract": [
        "under_contract_2026_27",
    ],
    "market_value_percentile": [
        "front_office_value_percentile",
        "market_value_percentile",
        "trade_market_value_percentile",
    ],
    "market_value_score": [
        "front_office_value_score",
        "trade_market_value_score",
        "market_value_score",
    ],
    "age_market_score": ["age_market_score"],
    "contract_control_score": ["contract_control_score"],
    "asset_class": [
        "recommendation_asset_class_v4",
        "recommendation_asset_class_v3",
        "front_office_asset_tier",
        "market_asset_tier",
        "asset_tier",
    ],
    "protected_player": [
        "protected_player_flag_v4",
        "protected_player_flag_v3",
        "protected_core_flag",
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run pure helper tests without loading project files.",
    )
    return parser.parse_args()


def locate_source(name: str) -> Path:
    for path in SOURCE_CANDIDATES[name]:
        if path.exists():
            return path
    raise FileNotFoundError(
        f"Required source '{name}' was not found:\n"
        + "\n".join(str(path) for path in SOURCE_CANDIDATES[name])
    )


def read_frame(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, low_memory=False)
    raise ValueError(f"Unsupported source format: {path}")


def normalize_player_id(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    try:
        numeric = float(value)
        if math.isfinite(numeric) and numeric.is_integer():
            return str(int(numeric))
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


def safe_bool(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if value is None or pd.isna(value):
        return False
    return str(value).strip().lower() in {
        "true",
        "1",
        "yes",
        "y",
    }


def parse_season_start(value: Any) -> float:
    if value is None or pd.isna(value):
        return np.nan
    if isinstance(value, (int, np.integer)):
        return float(value)
    if isinstance(value, (float, np.floating)) and math.isfinite(float(value)):
        return float(value)
    match = re.search(r"(20\d{2})", str(value))
    return float(match.group(1)) if match else np.nan


def first_existing(
    frame: pd.DataFrame,
    candidates: Iterable[str],
) -> str | None:
    columns = set(frame.columns)
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def numeric_series(
    frame: pd.DataFrame,
    candidates: Iterable[str],
    default: float = np.nan,
) -> pd.Series:
    for candidate in candidates:
        if candidate in frame.columns:
            values = pd.to_numeric(frame[candidate], errors="coerce")
            if values.notna().sum() > 0:
                return values.astype(float)
    return pd.Series(default, index=frame.index, dtype=float)


def text_series(
    frame: pd.DataFrame,
    candidates: Iterable[str],
    default: str = "",
) -> pd.Series:
    for candidate in candidates:
        if candidate in frame.columns:
            return (
                frame[candidate]
                .fillna(default)
                .astype(str)
                .str.strip()
            )
    return pd.Series(default, index=frame.index, dtype=str)


def bool_series(
    frame: pd.DataFrame,
    candidates: Iterable[str],
) -> pd.Series:
    for candidate in candidates:
        if candidate in frame.columns:
            return frame[candidate].map(safe_bool).astype(bool)
    return pd.Series(False, index=frame.index, dtype=bool)


def percentile_rank(
    values: pd.Series,
    *,
    higher_is_better: bool = True,
    fill_percentile: float = 50.0,
) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    valid = numeric.notna()

    output = pd.Series(fill_percentile, index=values.index, dtype=float)
    if valid.sum() == 0:
        return output

    ranked = numeric.loc[valid].rank(
        method="average",
        pct=True,
        ascending=higher_is_better,
    )
    if higher_is_better:
        percentile = ranked * 100.0
    else:
        percentile = (1.0 - ranked + 1.0 / valid.sum()) * 100.0

    output.loc[valid] = percentile
    return output.clip(0.0, 100.0)


def percentile_against_population(
    values: pd.Series,
    population_mask: pd.Series,
) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    population = numeric.loc[
        population_mask.reindex(values.index, fill_value=False)
        & numeric.notna()
    ].sort_values()

    if population.empty:
        return pd.Series(50.0, index=values.index, dtype=float)

    sorted_values = population.to_numpy(dtype=float)
    output = pd.Series(50.0, index=values.index, dtype=float)

    for index, value in numeric.items():
        if not math.isfinite(safe_float(value)):
            continue
        right = np.searchsorted(
            sorted_values,
            float(value),
            side="right",
        )
        output.loc[index] = 100.0 * right / len(sorted_values)

    return output.clip(0.0, 100.0)


def weighted_mean(
    frame: pd.DataFrame,
    weights: dict[str, float],
) -> pd.Series:
    missing = [
        column for column in weights if column not in frame.columns
    ]
    if missing:
        raise ValueError(
            "Weighted mean is missing columns:\n"
            + "\n".join(missing)
        )

    total_weight = sum(weights.values())
    if not math.isclose(total_weight, 1.0, abs_tol=1e-9):
        raise ValueError(
            f"Weights must sum to 1.0, observed {total_weight:.8f}"
        )

    result = pd.Series(0.0, index=frame.index, dtype=float)
    for column, weight in weights.items():
        result += (
            pd.to_numeric(frame[column], errors="coerce")
            .fillna(50.0)
            .clip(0.0, 100.0)
            * weight
        )
    return result.clip(0.0, 100.0)


def reliability_shrink(
    percentile: pd.Series,
    reliability: pd.Series,
) -> pd.Series:
    p = pd.to_numeric(percentile, errors="coerce").fillna(50.0)
    r = (
        pd.to_numeric(reliability, errors="coerce")
        .fillna(0.50)
        .clip(0.0, 1.0)
    )
    return (50.0 + (p - 50.0) * r).clip(0.0, 100.0)


def percentile_to_rating(percentile: Any) -> float:
    value = float(np.clip(safe_float(percentile, 50.0), 0.0, 100.0))
    rating = (
        RATING_MINIMUM
        + (RATING_MAXIMUM - RATING_MINIMUM) * value / 100.0
    )
    return round(float(rating), RATING_DECIMALS)


def rating_series(percentile: pd.Series) -> pd.Series:
    return percentile.map(percentile_to_rating).astype(float)


def rating_grade(rating: Any) -> str:
    value = safe_float(rating, RATING_MINIMUM)
    for threshold, grade in GRADE_THRESHOLDS:
        if value >= threshold:
            return grade
    return "D-"


def role_label(rating: Any) -> str:
    value = safe_float(rating, RATING_MINIMUM)
    for threshold, label in ROLE_THRESHOLDS:
        if value >= threshold:
            return label
    return "Developmental player"


def age_runway_score(age: Any) -> float:
    value = safe_float(age, 28.0)
    age_points = np.array(
        [18.0, 22.0, 24.0, 27.0, 30.0, 33.0, 36.0, 40.0]
    )
    runway_points = np.array(
        [100.0, 100.0, 92.0, 78.0, 58.0, 38.0, 20.0, 8.0]
    )
    return round(
        float(np.interp(value, age_points, runway_points)),
        3,
    )


def prefix_frame(
    frame: pd.DataFrame,
    prefix: str,
) -> pd.DataFrame:
    output = frame.copy()
    output["_player_key"] = output["player_id"].map(normalize_player_id)
    output = output.loc[output["_player_key"].ne("")].copy()
    output = output.drop_duplicates("_player_key", keep="first")
    rename = {
        column: f"{prefix}__{column}"
        for column in output.columns
        if column != "_player_key"
    }
    return output.rename(columns=rename)


def source_candidates(
    source_prefixes: Iterable[str],
    canonical_key: str,
) -> list[str]:
    candidates: list[str] = []
    for prefix in source_prefixes:
        for column in COLUMN_CANDIDATES[canonical_key]:
            candidates.append(f"{prefix}__{column}")
    return candidates


def choose_future_contribution_column(
    future: pd.DataFrame,
) -> str:
    for candidate in FUTURE_CONTRIBUTION_CANDIDATES:
        if candidate in future.columns:
            numeric = pd.to_numeric(
                future[candidate],
                errors="coerce",
            )
            if numeric.notna().sum() > 0:
                return candidate

    for column in future.columns:
        lower = column.lower()
        if not any(
            term in lower
            for term in ["contribution", "strength"]
        ):
            continue
        if any(
            term in lower
            for term in [
                "percentile",
                "rank",
                "salary",
                "contract",
                "market",
            ]
        ):
            continue
        numeric = pd.to_numeric(future[column], errors="coerce")
        if numeric.notna().sum() > 0:
            return column

    raise ValueError(
        "No numeric future player contribution column was found."
    )


def build_future_summary(
    future: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if "player_id" not in future.columns:
        raise ValueError("Future player inputs are missing player_id.")

    season_column = first_existing(
        future,
        SEASON_COLUMN_CANDIDATES,
    )
    if season_column is None:
        raise ValueError(
            "Future player inputs are missing a projection season column."
        )

    value_column = choose_future_contribution_column(future)

    working = future.copy()
    working["_player_key"] = working["player_id"].map(
        normalize_player_id
    )
    working["_season_start"] = working[season_column].map(
        parse_season_start
    )
    working["_future_value"] = pd.to_numeric(
        working[value_column],
        errors="coerce",
    )

    working = working.loc[
        working["_player_key"].ne("")
        & working["_season_start"].notna()
        & working["_future_value"].notna()
    ].copy()

    rows: list[dict[str, Any]] = []
    for player_key, group in working.groupby(
        "_player_key",
        sort=False,
    ):
        group = group.sort_values("_season_start")
        first = group.iloc[0]
        last = group.iloc[-1]
        current_value = float(first["_future_value"])
        peak_index = group["_future_value"].idxmax()
        peak = group.loc[peak_index]

        current_season = int(first["_season_start"])
        near_target = current_season + 2
        near_rows = group.loc[
            group["_season_start"] >= near_target
        ]
        near = (
            near_rows.iloc[0]
            if not near_rows.empty
            else last
        )

        peak_value = float(peak["_future_value"])
        long_value = float(last["_future_value"])
        near_value = float(near["_future_value"])

        rows.append(
            {
                "_player_key": player_key,
                "future_current_season": current_season,
                "future_peak_season": int(peak["_season_start"]),
                "future_long_horizon_season": int(
                    last["_season_start"]
                ),
                "future_current_contribution": current_value,
                "future_peak_contribution": peak_value,
                "future_long_horizon_contribution": long_value,
                "future_near_term_contribution": near_value,
                "future_growth_to_peak": peak_value - current_value,
                "future_near_term_delta": near_value - current_value,
                "future_peak_years_away": int(
                    peak["_season_start"] - current_season
                ),
            }
        )

    summary = pd.DataFrame(rows)

    summary[
        "peak_future_contribution_percentile"
    ] = percentile_rank(
        summary["future_peak_contribution"]
    )
    summary[
        "future_growth_percentile"
    ] = percentile_rank(
        summary["future_growth_to_peak"]
    )
    summary[
        "long_horizon_contribution_percentile"
    ] = percentile_rank(
        summary["future_long_horizon_contribution"]
    )
    summary["potential_percentile"] = weighted_mean(
        summary,
        POTENTIAL_WEIGHTS,
    )

    delta = summary["future_near_term_delta"]
    delta_scale = max(
        float(delta.abs().median()),
        0.25,
    )
    summary["development_direction"] = np.select(
        [
            delta >= delta_scale,
            delta <= -delta_scale,
        ],
        [
            "Rising",
            "Declining",
        ],
        default="Stable",
    )
    summary["development_arrow"] = summary[
        "development_direction"
    ].map(
        {
            "Rising": "↑",
            "Stable": "→",
            "Declining": "↓",
        }
    )

    metadata = {
        "season_column": season_column,
        "contribution_column": value_column,
        "players": len(summary),
        "minimum_season": int(working["_season_start"].min()),
        "maximum_season": int(working["_season_start"].max()),
        "rows": len(working),
    }
    return summary, metadata


def archetype_label(
    primary: Any,
    secondary: Any,
) -> str:
    first = str(primary or "").strip().lower()
    second = str(secondary or "").strip().lower()
    pair = (first, second)

    mappings = {
        ("scoring", "playmaking"): "Primary Shot Creator",
        ("playmaking", "scoring"): "Lead Playmaker",
        ("scoring", "shooting"): "Three-Level Scorer",
        ("shooting", "scoring"): "Scoring Sharpshooter",
        ("shooting", "defense"): "3-and-D Specialist",
        ("defense", "shooting"): "Two-Way Floor Spacer",
        ("playmaking", "shooting"): "Floor-Spacing Playmaker",
        ("shooting", "playmaking"): "Movement Playmaker",
        ("playmaking", "defense"): "Two-Way Connector",
        ("defense", "playmaking"): "Defensive Connector",
        ("rebounding", "defense"): "Interior Defensive Anchor",
        ("defense", "rebounding"): "Defensive Glass Cleaner",
        ("rebounding", "scoring"): "Interior Scoring Big",
        ("scoring", "rebounding"): "Scoring Forward",
        ("rebounding", "shooting"): "Stretch Big",
        ("shooting", "rebounding"): "Floor-Spacing Big",
        ("playmaking", "rebounding"): "Point Forward",
        ("rebounding", "playmaking"): "Playmaking Big",
        ("defense", "scoring"): "Two-Way Scorer",
        ("scoring", "defense"): "Two-Way Shot Creator",
    }

    if pair in mappings:
        return mappings[pair]
    if first:
        return f"{first.title()} Specialist"
    return "Balanced Contributor"


def strength_and_concern_labels(
    row: pd.Series,
) -> tuple[str, str, str, str]:
    rating_labels = {
        "scoring_rating": "Scoring",
        "shooting_rating": "Shooting",
        "playmaking_rating": "Playmaking",
        "rebounding_rating": "Rebounding",
        "defense_rating": "Defense",
        "efficiency_rating": "Efficiency",
        "availability_rating": "Availability",
    }

    ordered = sorted(
        (
            (safe_float(row.get(column), RATING_MINIMUM), label)
            for column, label in rating_labels.items()
        ),
        reverse=True,
    )
    strengths = [label for _, label in ordered[:2]]
    concerns = [label for _, label in sorted(ordered)[:2]]

    extra_strengths: list[str] = []
    extra_concerns: list[str] = []

    if safe_float(row.get("potential_rating")) >= 90.0:
        extra_strengths.append("High upside")
    if safe_float(row.get("contract_value_rating")) >= 90.0:
        extra_strengths.append("Contract value")
    if safe_float(row.get("trade_value_rating")) >= 93.0:
        extra_strengths.append("Premium trade asset")

    if safe_float(row.get("availability_rating")) < 72.0:
        extra_concerns.append("Availability risk")
    if safe_float(row.get("contract_value_rating")) < 70.0:
        extra_concerns.append("Contract cost")
    if row.get("development_direction") == "Declining":
        extra_concerns.append("Declining projection")

    strengths = list(dict.fromkeys(strengths + extra_strengths))[:3]
    concerns = list(dict.fromkeys(concerns + extra_concerns))[:3]

    return (
        strengths[0] if strengths else "",
        strengths[1] if len(strengths) > 1 else "",
        "|".join(strengths),
        "|".join(concerns),
    )


def build_rating_release(
    projection: pd.DataFrame,
    skills: pd.DataFrame,
    market: pd.DataFrame,
    financial: pd.DataFrame,
    future: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    for frame_name, frame in {
        "projection": projection,
        "skills": skills,
        "market": market,
        "financial": financial,
    }.items():
        if "player_id" not in frame.columns:
            raise ValueError(
                f"{frame_name} is missing player_id."
            )

    base = prefix_frame(projection, "projection")
    merged = base.merge(
        prefix_frame(skills, "skills"),
        on="_player_key",
        how="left",
        validate="one_to_one",
    ).merge(
        prefix_frame(financial, "financial"),
        on="_player_key",
        how="left",
        validate="one_to_one",
    ).merge(
        prefix_frame(market, "market"),
        on="_player_key",
        how="left",
        validate="one_to_one",
    )

    future_summary, future_metadata = build_future_summary(
        future
    )
    merged = merged.merge(
        future_summary,
        on="_player_key",
        how="left",
        validate="one_to_one",
    )

    output = pd.DataFrame(index=merged.index)
    output["player_id"] = merged["_player_key"]
    output["player_name"] = text_series(
        merged,
        source_candidates(
            ["projection", "skills", "market", "financial"],
            "player_name",
        ),
    )
    output["team_abbreviation"] = text_series(
        merged,
        source_candidates(
            ["market", "financial", "projection", "skills"],
            "team",
        ),
    ).str.upper()
    output["age"] = numeric_series(
        merged,
        source_candidates(
            ["market", "financial", "projection", "skills"],
            "age",
        ),
    )

    output["games_played"] = numeric_series(
        merged,
        source_candidates(["projection", "skills"], "games"),
    )
    output["minutes_per_game"] = numeric_series(
        merged,
        source_candidates(["projection", "skills"], "minutes"),
    )
    output["points_per_game"] = numeric_series(
        merged,
        source_candidates(["projection", "skills"], "points"),
    )
    output["rebounds_per_game"] = numeric_series(
        merged,
        source_candidates(["projection", "skills"], "rebounds"),
    )
    output["assists_per_game"] = numeric_series(
        merged,
        source_candidates(["projection", "skills"], "assists"),
    )
    output["field_goal_pct"] = numeric_series(
        merged,
        source_candidates(["projection", "skills"], "fg_pct"),
    )
    output["three_point_pct"] = numeric_series(
        merged,
        source_candidates(["projection", "skills"], "three_pct"),
    )
    output["true_shooting_pct"] = numeric_series(
        merged,
        source_candidates(["projection", "skills"], "ts_pct"),
    )
    output["effective_field_goal_pct"] = numeric_series(
        merged,
        source_candidates(["projection", "skills"], "efg_pct"),
    )
    output["pie"] = numeric_series(
        merged,
        source_candidates(["projection", "skills"], "pie"),
    )
    output["net_rating"] = numeric_series(
        merged,
        source_candidates(["projection", "skills"], "net_rating"),
    )
    output["usage_pct"] = numeric_series(
        merged,
        source_candidates(["projection", "skills"], "usage"),
    )

    output["availability_rate"] = numeric_series(
        merged,
        source_candidates(
            ["projection", "skills"],
            "availability",
        ),
    )
    output["projected_expected_contribution"] = numeric_series(
        merged,
        source_candidates(
            ["projection", "market"],
            "expected_contribution",
        ),
    )
    output["projected_downside_contribution"] = numeric_series(
        merged,
        source_candidates(
            ["market", "projection"],
            "downside_contribution",
        ),
    )
    output["projected_upside_contribution"] = numeric_series(
        merged,
        source_candidates(
            ["projection", "market"],
            "upside_contribution",
        ),
    )
    output["projected_survival_probability"] = numeric_series(
        merged,
        source_candidates(
            ["projection", "market"],
            "survival_probability",
        ),
    )
    output["projected_rotation_probability"] = numeric_series(
        merged,
        source_candidates(
            ["projection", "market"],
            "rotation_probability",
        ),
    )
    output["roster_value_score"] = numeric_series(
        merged,
        source_candidates(
            ["skills", "projection", "market"],
            "roster_value_score",
        ),
    )
    output["roster_value_percentile_source"] = numeric_series(
        merged,
        source_candidates(
            ["skills", "projection", "market"],
            "roster_value_percentile",
        ),
    )
    output["reliability_weight"] = numeric_series(
        merged,
        source_candidates(
            ["skills", "projection"],
            "reliability_weight",
        ),
        default=0.50,
    ).fillna(0.50).clip(0.0, 1.0)

    output["primary_skill"] = text_series(
        merged,
        source_candidates(
            ["skills", "projection", "market"],
            "primary_skill",
        ),
    )
    output["secondary_skill"] = text_series(
        merged,
        source_candidates(
            ["skills", "projection", "market"],
            "secondary_skill",
        ),
    )
    output["value_tier"] = text_series(
        merged,
        source_candidates(
            ["skills", "projection", "market"],
            "value_tier",
        ),
    )
    output["source_confidence_tier"] = text_series(
        merged,
        source_candidates(
            ["skills", "projection"],
            "confidence_tier",
        ),
    )

    for dimension in SKILL_DIMENSIONS:
        score_candidates = [
            f"skills__{dimension}_score",
            f"projection__{dimension}_score",
            f"market__{dimension}_score",
        ]
        output[f"{dimension}_score_source"] = numeric_series(
            merged,
            score_candidates,
        )

    rotation_population = (
        output["games_played"].ge(
            ROTATION_POPULATION_MINIMUM_GAMES
        )
        & output["minutes_per_game"].ge(
            ROTATION_POPULATION_MINIMUM_MPG
        )
    )

    for dimension in SKILL_DIMENSIONS:
        raw_percentile = percentile_against_population(
            output[f"{dimension}_score_source"],
            rotation_population,
        )
        output[f"{dimension}_percentile"] = reliability_shrink(
            raw_percentile,
            output["reliability_weight"],
        )
        output[f"{dimension}_rating"] = rating_series(
            output[f"{dimension}_percentile"]
        )
        output[f"{dimension}_grade"] = output[
            f"{dimension}_rating"
        ].map(rating_grade)

    output["true_shooting_percentile"] = (
        percentile_against_population(
            output["true_shooting_pct"],
            rotation_population,
        )
    )
    output["effective_field_goal_percentile"] = (
        percentile_against_population(
            output["effective_field_goal_pct"],
            rotation_population,
        )
    )
    output["pie_percentile"] = percentile_against_population(
        output["pie"],
        rotation_population,
    )
    output["net_rating_percentile"] = (
        percentile_against_population(
            output["net_rating"],
            rotation_population,
        )
    )
    output["efficiency_percentile_raw"] = weighted_mean(
        output,
        EFFICIENCY_WEIGHTS,
    )
    output["efficiency_percentile"] = reliability_shrink(
        output["efficiency_percentile_raw"],
        output["reliability_weight"],
    )
    output["efficiency_rating"] = rating_series(
        output["efficiency_percentile"]
    )
    output["efficiency_grade"] = output[
        "efficiency_rating"
    ].map(rating_grade)

    output["availability_rate_percentile"] = percentile_rank(
        output["availability_rate"]
    )
    output["games_played_percentile"] = percentile_rank(
        output["games_played"]
    )
    output["survival_probability_percentile"] = percentile_rank(
        output["projected_survival_probability"]
    )
    output["rotation_probability_percentile"] = percentile_rank(
        output["projected_rotation_probability"]
    )
    output["availability_percentile"] = weighted_mean(
        output.rename(
            columns={
                "availability_percentile": (
                    "availability_percentile_existing"
                )
            }
        ),
        AVAILABILITY_WEIGHTS,
    )
    output["availability_rating"] = rating_series(
        output["availability_percentile"]
    )
    output["availability_grade"] = output[
        "availability_rating"
    ].map(rating_grade)

    output[
        "expected_contribution_percentile_rating"
    ] = percentile_rank(
        output["projected_expected_contribution"]
    )
    output[
        "downside_contribution_percentile_rating"
    ] = percentile_rank(
        output["projected_downside_contribution"]
    )

    roster_source = output[
        "roster_value_percentile_source"
    ].where(
        output["roster_value_percentile_source"].between(
            0.0,
            100.0,
            inclusive="both",
        )
    )
    output["roster_value_percentile_rating"] = (
        roster_source.fillna(
            percentile_rank(output["roster_value_score"])
        )
    ).clip(0.0, 100.0)

    skill_percentile_columns = [
        f"{dimension}_percentile"
        for dimension in SKILL_DIMENSIONS
    ]
    output["skill_mean_percentile_rating"] = output[
        skill_percentile_columns
    ].mean(axis=1)
    output["skill_peak_percentile_rating"] = output[
        skill_percentile_columns
    ].max(axis=1)
    output["efficiency_percentile_rating"] = output[
        "efficiency_percentile"
    ]
    output["availability_percentile_rating"] = output[
        "availability_percentile"
    ]

    output["overall_percentile"] = weighted_mean(
        output,
        OVR_PERCENTILE_WEIGHTS,
    )
    output["overall_rating"] = rating_series(
        output["overall_percentile"]
    )
    output["overall_grade"] = output[
        "overall_rating"
    ].map(rating_grade)
    output["role_label"] = output[
        "overall_rating"
    ].map(role_label)

    for column in [
        "future_current_season",
        "future_peak_season",
        "future_long_horizon_season",
        "future_current_contribution",
        "future_peak_contribution",
        "future_long_horizon_contribution",
        "future_near_term_contribution",
        "future_growth_to_peak",
        "future_near_term_delta",
        "future_peak_years_away",
        "peak_future_contribution_percentile",
        "future_growth_percentile",
        "long_horizon_contribution_percentile",
        "potential_percentile",
        "development_direction",
        "development_arrow",
    ]:
        output[column] = merged[column]

    output["potential_percentile"] = pd.to_numeric(
        output["potential_percentile"],
        errors="coerce",
    ).fillna(output["overall_percentile"])
    output["potential_rating"] = rating_series(
        output["potential_percentile"]
    )
    output["potential_grade"] = output[
        "potential_rating"
    ].map(rating_grade)

    output["salary_2026_27"] = numeric_series(
        merged,
        source_candidates(
            ["financial", "market"],
            "salary_2026_27",
        ),
    )
    output["future_salary_commitment"] = numeric_series(
        merged,
        source_candidates(
            ["financial", "market"],
            "future_salary_commitment",
        ),
    )
    output["under_contract_2026_27"] = bool_series(
        merged,
        source_candidates(
            ["financial", "market"],
            "under_contract",
        ),
    )

    contract_percentile_source = numeric_series(
        merged,
        source_candidates(
            ["market", "financial"],
            "contract_value_percentile",
        ),
    )
    contract_raw = numeric_series(
        merged,
        source_candidates(
            ["financial", "market"],
            "contract_value_raw",
        ),
    )
    calculated_contract_percentile = percentile_rank(
        contract_raw
    )
    output["contract_value_percentile"] = (
        contract_percentile_source.where(
            contract_percentile_source.between(
                0.0,
                100.0,
                inclusive="both",
            )
        ).fillna(calculated_contract_percentile)
    ).clip(0.0, 100.0)
    # The trade-value fallback uses the explicit ``*_rating`` alias so
    # percentile components are clearly separated from displayed ratings.
    output["contract_value_percentile_rating"] = output[
        "contract_value_percentile"
    ]
    output["contract_value_rating"] = rating_series(
        output["contract_value_percentile"]
    )
    output["contract_value_grade"] = output[
        "contract_value_rating"
    ].map(rating_grade)
    output["contract_value_source"] = np.where(
        contract_percentile_source.notna(),
        "validated_market_contract_percentile",
        np.where(
            contract_raw.notna(),
            "financial_layer_projected_contract_value",
            "neutral_missing_contract_context",
        ),
    )

    market_percentile = numeric_series(
        merged,
        source_candidates(
            ["market"],
            "market_value_percentile",
        ),
    )
    market_score = numeric_series(
        merged,
        source_candidates(
            ["market"],
            "market_value_score",
        ),
    )
    market_score_percentile = percentile_rank(
        market_score
    )
    direct_market_percentile = market_percentile.where(
        market_percentile.between(
            0.0,
            100.0,
            inclusive="both",
        )
    ).fillna(
        market_score_percentile.where(market_score.notna())
    )

    output["age_runway_score"] = output["age"].map(
        age_runway_score
    )
    output["fallback_trade_value_percentile"] = weighted_mean(
        output,
        FALLBACK_TRADE_VALUE_WEIGHTS,
    )
    output["trade_value_percentile"] = (
        direct_market_percentile.fillna(
            output["fallback_trade_value_percentile"]
        )
    ).clip(0.0, 100.0)
    output["trade_value_rating"] = rating_series(
        output["trade_value_percentile"]
    )
    output["trade_value_grade"] = output[
        "trade_value_rating"
    ].map(rating_grade)
    output["trade_value_source"] = np.where(
        direct_market_percentile.notna(),
        "validated_player_market_layer",
        "derived_fallback_outside_market_pool",
    )

    output["market_asset_class"] = text_series(
        merged,
        source_candidates(
            ["market"],
            "asset_class",
        ),
    )
    output["protected_player_flag"] = bool_series(
        merged,
        source_candidates(
            ["market"],
            "protected_player",
        ),
    )

    output["archetype"] = [
        archetype_label(primary, secondary)
        for primary, secondary in zip(
            output["primary_skill"],
            output["secondary_skill"],
        )
    ]

    strength_results = output.apply(
        strength_and_concern_labels,
        axis=1,
        result_type="expand",
    )
    strength_results.columns = [
        "primary_strength",
        "secondary_strength",
        "strengths",
        "concerns",
    ]
    output = pd.concat(
        [output, strength_results],
        axis=1,
    )

    output["rating_confidence"] = np.select(
        [
            output["reliability_weight"].ge(0.80),
            output["reliability_weight"].ge(0.55),
        ],
        [
            "High",
            "Medium",
        ],
        default="Limited",
    )
    output["finishing_rating_released"] = False
    output["rating_scope_note"] = (
        "Display ratings are calibrated presentation transforms on a "
        "60.0-99.9 scale. Optimizer, projection, legality, and simulation "
        "logic retain the original full-precision values."
    )
    output["finishing_scope_note"] = (
        "A finishing rating is not released because the audited sources "
        "do not include direct rim-attempt frequency and rim efficiency."
    )

    output = output.sort_values(
        [
            "overall_rating",
            "trade_value_rating",
            "potential_rating",
            "player_name",
        ],
        ascending=[False, False, False, True],
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

    metadata = {
        "future_projection": future_metadata,
        "market_direct_players": int(
            direct_market_percentile.notna().sum()
        ),
        "market_fallback_players": int(
            direct_market_percentile.isna().sum()
        ),
        "players": len(output),
    }
    return output, metadata


def distribution_summary(
    release: pd.DataFrame,
) -> pd.DataFrame:
    rating_columns = [
        column
        for column in release.columns
        if column.endswith("_rating")
    ]
    rows: list[dict[str, Any]] = []

    for column in rating_columns:
        series = pd.to_numeric(
            release[column],
            errors="coerce",
        )
        rows.append(
            {
                "rating": column,
                "count": int(series.notna().sum()),
                "minimum": round(float(series.min()), 3),
                "p10": round(float(series.quantile(0.10)), 3),
                "p25": round(float(series.quantile(0.25)), 3),
                "median": round(float(series.median()), 3),
                "mean": round(float(series.mean()), 3),
                "p75": round(float(series.quantile(0.75)), 3),
                "p90": round(float(series.quantile(0.90)), 3),
                "maximum": round(float(series.max()), 3),
            }
        )

    return pd.DataFrame(rows)


def validation_rows(
    release: pd.DataFrame,
    build_metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    rating_columns = [
        "overall_rating",
        "scoring_rating",
        "shooting_rating",
        "playmaking_rating",
        "rebounding_rating",
        "defense_rating",
        "efficiency_rating",
        "availability_rating",
        "potential_rating",
        "contract_value_rating",
        "trade_value_rating",
    ]

    def check(
        name: str,
        passed: bool,
        observed: Any,
        expected: Any,
    ) -> dict[str, Any]:
        return {
            "check_name": name,
            "passed": bool(passed),
            "observed": observed,
            "expected": expected,
        }

    rating_matrix = release[rating_columns].apply(
        pd.to_numeric,
        errors="coerce",
    )

    one_decimal = all(
        np.allclose(
            rating_matrix[column].dropna().to_numpy(),
            rating_matrix[column].dropna().round(1).to_numpy(),
        )
        for column in rating_columns
    )

    return [
        check(
            "player_count_matches_projection_board",
            len(release) == 582,
            len(release),
            582,
        ),
        check(
            "player_ids_unique_and_nonblank",
            release["player_id"].ne("").all()
            and release["player_id"].is_unique,
            int(release["player_id"].nunique()),
            len(release),
        ),
        check(
            "all_core_ratings_non_null",
            not rating_matrix.isna().any().any(),
            int(rating_matrix.notna().sum().sum()),
            int(rating_matrix.size),
        ),
        check(
            "all_ratings_within_60_to_99_9",
            (
                rating_matrix.ge(RATING_MINIMUM)
                & rating_matrix.le(RATING_MAXIMUM)
            ).all().all(),
            {
                "minimum": float(rating_matrix.min().min()),
                "maximum": float(rating_matrix.max().max()),
            },
            f"{RATING_MINIMUM}-{RATING_MAXIMUM}",
        ),
        check(
            "all_ratings_one_decimal",
            one_decimal,
            RATING_DECIMALS,
            1,
        ),
        check(
            "potential_coverage_complete",
            release["potential_rating"].notna().all(),
            int(release["potential_rating"].notna().sum()),
            len(release),
        ),
        check(
            "contract_value_coverage_complete",
            release["contract_value_rating"].notna().all(),
            int(release["contract_value_rating"].notna().sum()),
            len(release),
        ),
        check(
            "trade_value_coverage_complete",
            release["trade_value_rating"].notna().all(),
            int(release["trade_value_rating"].notna().sum()),
            len(release),
        ),
        check(
            "validated_market_players_preserved",
            build_metadata["market_direct_players"] >= 395,
            build_metadata["market_direct_players"],
            ">=395",
        ),
        check(
            "overall_distribution_centered",
            78.0
            <= float(release["overall_rating"].median())
            <= 82.0,
            round(float(release["overall_rating"].median()), 3),
            "78.0-82.0",
        ),
        check(
            "elite_overall_ceiling_present",
            float(release["overall_rating"].max()) >= 97.0,
            round(float(release["overall_rating"].max()), 3),
            ">=97.0",
        ),
        check(
            "development_directions_complete",
            release["development_direction"].isin(
                ["Rising", "Stable", "Declining"]
            ).all(),
            release["development_direction"]
            .value_counts()
            .to_dict(),
            "Rising|Stable|Declining",
        ),
        check(
            "archetypes_complete",
            release["archetype"].ne("").all(),
            int(release["archetype"].ne("").sum()),
            len(release),
        ),
        check(
            "grades_complete",
            release[
                [
                    "overall_grade",
                    "potential_grade",
                    "contract_value_grade",
                    "trade_value_grade",
                ]
            ].ne("").all().all(),
            True,
            True,
        ),
        check(
            "finishing_not_released",
            not release["finishing_rating_released"].any(),
            bool(release["finishing_rating_released"].any()),
            False,
        ),
        check(
            "optimizer_precision_scope_preserved",
            release["rating_scope_note"].str.contains(
                "full-precision",
                regex=False,
            ).all(),
            True,
            True,
        ),
    ]


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, pd._libs.missing.NAType):
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def build_app_json(
    release: pd.DataFrame,
    methodology: dict[str, Any],
) -> dict[str, Any]:
    display_columns = [
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
        "rating_scope_note",
        "finishing_scope_note",
    ]

    records = release[display_columns].where(
        pd.notna(release[display_columns]),
        None,
    ).to_dict(orient="records")

    by_player_id = {
        str(record["player_id"]): json_safe(record)
        for record in records
    }
    by_team: dict[str, list[str]] = {}
    for record in records:
        team = str(record["team_abbreviation"])
        by_team.setdefault(team, []).append(
            str(record["player_id"])
        )

    return {
        "release_name": RELEASE_NAME,
        "script_version": SCRIPT_VERSION,
        "league_year": "2026-27",
        "rating_scale": {
            "minimum": RATING_MINIMUM,
            "maximum": RATING_MAXIMUM,
            "decimals": RATING_DECIMALS,
            "example": "96.7",
        },
        "player_count": len(records),
        "methodology": methodology,
        "players_by_id": by_player_id,
        "player_ids_by_team": by_team,
    }


def run_self_test() -> int:
    sample = pd.Series([10.0, 20.0, 30.0, 40.0])
    percentiles = percentile_rank(sample).round(1).tolist()

    tests = {
        "weights_sum_to_one_overall": math.isclose(
            sum(OVR_PERCENTILE_WEIGHTS.values()),
            1.0,
        ),
        "weights_sum_to_one_efficiency": math.isclose(
            sum(EFFICIENCY_WEIGHTS.values()),
            1.0,
        ),
        "weights_sum_to_one_availability": math.isclose(
            sum(AVAILABILITY_WEIGHTS.values()),
            1.0,
        ),
        "weights_sum_to_one_potential": math.isclose(
            sum(POTENTIAL_WEIGHTS.values()),
            1.0,
        ),
        "weights_sum_to_one_trade_fallback": math.isclose(
            sum(FALLBACK_TRADE_VALUE_WEIGHTS.values()),
            1.0,
        ),
        "trade_fallback_contract_alias_expected": (
            "contract_value_percentile_rating"
            in FALLBACK_TRADE_VALUE_WEIGHTS
        ),
        "player_id_normalization": (
            normalize_player_id(1630180.0) == "1630180"
        ),
        "season_parsing": parse_season_start("2028-29") == 2028.0,
        "percentile_ordering": percentiles == [
            25.0,
            50.0,
            75.0,
            100.0,
        ],
        "rating_floor": percentile_to_rating(0.0) == 60.0,
        "rating_midpoint": percentile_to_rating(50.0) == 80.0,
        "rating_ceiling": percentile_to_rating(100.0) == 99.9,
        "rating_precision": percentile_to_rating(91.73) == 96.6,
        "grade_mapping": (
            rating_grade(97.2) == "A+"
            and rating_grade(84.0) == "B"
            and rating_grade(69.0) == "D+"
        ),
        "role_mapping": (
            role_label(94.5) == "Franchise superstar"
            and role_label(84.0) == "Quality starter"
        ),
        "archetype_mapping": (
            archetype_label("Shooting", "Defense")
            == "3-and-D Specialist"
        ),
        "younger_age_has_more_runway": (
            age_runway_score(22) > age_runway_score(32)
        ),
    }

    print(json.dumps(tests, indent=2))
    return 0 if all(tests.values()) else 1


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    APP_DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)

    paths = {
        name: locate_source(name)
        for name in SOURCE_CANDIDATES
    }

    print("=" * 88)
    print("NBA PLAYER RATING RELEASE")
    print("=" * 88)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    print("[1/7] Loading validated rating sources")
    frames = {
        name: read_frame(path)
        for name, path in paths.items()
    }
    for name, frame in frames.items():
        print(
            f"  {name}: {len(frame):,} rows x "
            f"{len(frame.columns):,} columns"
        )

    print("[2/7] Building current on-court ratings")
    print("[3/7] Building potential and development ratings")
    print("[4/7] Building contract and trade-value ratings")
    release, build_metadata = build_rating_release(
        projection=frames["projection"],
        skills=frames["skills"],
        market=frames["market"],
        financial=frames["financial"],
        future=frames["future"],
    )

    print("[5/7] Assigning grades, roles, and archetypes")
    distributions = distribution_summary(release)

    print("[6/7] Validating rating release")
    validations = pd.DataFrame(
        validation_rows(release, build_metadata)
    )
    release_valid = bool(validations["passed"].all())

    methodology = {
        "release_name": RELEASE_NAME,
        "script_version": SCRIPT_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "release_valid": release_valid,
        "rating_scale": {
            "minimum": RATING_MINIMUM,
            "maximum": RATING_MAXIMUM,
            "decimals": RATING_DECIMALS,
            "example": "96.7",
            "scope": (
                "Presentation values only. Original precise values remain "
                "authoritative for projections, optimization, legality, and "
                "simulation."
            ),
        },
        "overall_percentile_weights": OVR_PERCENTILE_WEIGHTS,
        "efficiency_weights": EFFICIENCY_WEIGHTS,
        "availability_weights": AVAILABILITY_WEIGHTS,
        "potential_weights": POTENTIAL_WEIGHTS,
        "fallback_trade_value_weights": FALLBACK_TRADE_VALUE_WEIGHTS,
        "grade_thresholds": GRADE_THRESHOLDS,
        "role_thresholds": ROLE_THRESHOLDS,
        "rotation_population": {
            "minimum_games": ROTATION_POPULATION_MINIMUM_GAMES,
            "minimum_minutes_per_game": (
                ROTATION_POPULATION_MINIMUM_MPG
            ),
        },
        "finishing_rating_released": False,
        "finishing_reason": (
            "The audited data does not include direct rim-attempt frequency "
            "and rim efficiency. FG% and TS% are not sufficient for a "
            "standalone finishing grade."
        ),
        "build_metadata": build_metadata,
        "source_paths": {
            name: str(path)
            for name, path in paths.items()
        },
        "validation_passed": int(validations["passed"].sum()),
        "validation_total": len(validations),
    }

    print("[7/7] Writing rating artifacts")
    release.to_parquet(OUTPUT_PARQUET, index=False)
    release.to_csv(OUTPUT_CSV, index=False)
    validations.to_csv(VALIDATION_OUTPUT, index=False)
    distributions.to_csv(DISTRIBUTION_OUTPUT, index=False)
    release.head(50).to_csv(TOP_PLAYERS_OUTPUT, index=False)
    METHODOLOGY_OUTPUT.write_text(
        json.dumps(
            json_safe(methodology),
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    APP_JSON.write_text(
        json.dumps(
            json_safe(
                build_app_json(release, methodology)
            ),
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("Complete")
    print(
        f"Validation: {int(validations['passed'].sum())}/"
        f"{len(validations)}"
    )
    print(f"Release valid: {release_valid}")
    print(f"Players rated: {len(release):,}")
    print(
        "Direct market ratings: "
        f"{build_metadata['market_direct_players']:,}"
    )
    print(
        "Transparent trade-value fallbacks: "
        f"{build_metadata['market_fallback_players']:,}"
    )
    print(
        "Overall range: "
        f"{release['overall_rating'].min():.1f}-"
        f"{release['overall_rating'].max():.1f}"
    )
    print(
        "Overall median: "
        f"{release['overall_rating'].median():.1f}"
    )
    print("Finishing rating released: False")
    print()
    print("TOP 10 OVERALL RATINGS")
    print(
        release[
            [
                "league_overall_rank",
                "player_name",
                "team_abbreviation",
                "overall_rating",
                "overall_grade",
                "potential_rating",
                "trade_value_rating",
                "archetype",
            ]
        ]
        .head(10)
        .to_string(index=False)
    )

    return 0 if release_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())