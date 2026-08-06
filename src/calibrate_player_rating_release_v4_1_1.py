"""Calibrate NBA player ratings with demonstrated-value eligibility gates.

V4 starts from the V3 accomplishment-aware release and makes two refinements:

1. Projection lift limit
   Projected contribution may improve OVR, but only by a limited amount above
   a player's demonstrated impact, role burden, skill breadth, and downside.

2. Tier eligibility gates
   Superstar and All-Star OVRs require sufficiently strong demonstrated impact,
   role burden, skill breadth, downside protection, and evidence.

POT remains a career ceiling. FUT remains a projected future standing. POT is
always at least OVR and FUT is capped at POT.

This script never changes optimizer inputs, source projections, market values,
or legality data. It writes the active app alias only after all required and
player-sanity validations pass.

Inputs
------
data/processed/player_rating_release_2026_27_v3.parquet
data/processed/player_rating_release_2026_27_v3.csv

Outputs
-------
data/processed/player_rating_release_2026_27_v4.parquet
data/processed/player_rating_release_2026_27_v4.csv
app_data/player_ratings_2026_27_v4.json
app_data/player_ratings_2026_27_v2.json              active app alias
outputs/player_rating_v4_validation.csv
outputs/player_rating_v4_distribution.csv
outputs/player_rating_v4_player_audit.csv
outputs/player_rating_v4_top_100.csv
outputs/player_rating_v4_methodology.json
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


SCRIPT_VERSION = "player-rating-tier-gates-v4-1-1-2026-08-06"
RELEASE_NAME = "player_ratings_2026_27_v4_1_1"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"
APP_DATA_DIRECTORY = PROJECT_ROOT / "app_data"

INPUT_CANDIDATES = [
    DATA_DIRECTORY / "player_rating_release_2026_27_v3.parquet",
    DATA_DIRECTORY / "player_rating_release_2026_27_v3.csv",
]

OUTPUT_PARQUET = (
    DATA_DIRECTORY / "player_rating_release_2026_27_v4_1_1.parquet"
)
OUTPUT_CSV = OUTPUT_PARQUET.with_suffix(".csv")
OUTPUT_APP_JSON = (
    APP_DATA_DIRECTORY / "player_ratings_2026_27_v4_1_1.json"
)
ACTIVE_APP_ALIAS = (
    APP_DATA_DIRECTORY / "player_ratings_2026_27_v2.json"
)
ACTIVE_APP_BACKUP = (
    APP_DATA_DIRECTORY
    / "player_ratings_2026_27_v2_backup_before_v4_1_1.json"
)
VALIDATION_OUTPUT = (
    OUTPUT_DIRECTORY / "player_rating_v4_1_1_validation.csv"
)
DISTRIBUTION_OUTPUT = (
    OUTPUT_DIRECTORY / "player_rating_v4_1_1_distribution.csv"
)
PLAYER_AUDIT_OUTPUT = (
    OUTPUT_DIRECTORY / "player_rating_v4_1_1_player_audit.csv"
)
TOP_100_OUTPUT = (
    OUTPUT_DIRECTORY / "player_rating_v4_1_1_top_100.csv"
)
METHODOLOGY_OUTPUT = (
    OUTPUT_DIRECTORY / "player_rating_v4_1_1_methodology.json"
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

POTENTIAL_RATING_ANCHORS = np.array(
    [
        60.0,
        64.0,
        67.0,
        71.0,
        74.0,
        77.0,
        80.0,
        82.0,
        84.0,
        86.0,
        87.5,
        89.5,
        91.0,
        93.0,
        95.0,
        96.5,
        97.8,
        98.7,
        99.5,
    ],
    dtype=float,
)

DEMONSTRATED_WEIGHTS = {
    "current_impact_rank_pct": 0.38,
    "role_burden_rank_pct": 0.30,
    "skill_mean_percentile_rating": 0.14,
    "downside_contribution_percentile_rating": 0.12,
    "availability_percentile_rating": 0.06,
}

POTENTIAL_SIGNAL_WEIGHTS = {
    "future_ceiling_rank_pct": 0.28,
    "upside_contribution_rank_pct": 0.25,
    "skill_peak_percentile_rating": 0.23,
    "age_runway_score": 0.14,
    "overall_league_percentile_v4": 0.10,
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
            "Promote the validated V4.1 candidate into the active app alias. "
            "Without this flag, the script only writes and validates candidate "
            "artifacts."
        ),
    )
    return parser.parse_args()


def locate_input() -> Path:
    for path in INPUT_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError(
        "V3 player rating release was not found:\n"
        + "\n".join(str(path) for path in INPUT_CANDIDATES)
    )


def read_frame(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, low_memory=False)
    raise ValueError(f"Unsupported input: {path}")


def normalize_player_id(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    try:
        numeric_value = float(value)
        if math.isfinite(numeric_value) and numeric_value.is_integer():
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
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").astype(float)


def empirical_percentile(values: pd.Series) -> pd.Series:
    numbers = pd.to_numeric(values, errors="coerce")
    valid = numbers.notna()
    output = pd.Series(50.0, index=values.index, dtype=float)
    if valid.sum() == 0:
        return output
    output.loc[valid] = (
        numbers.loc[valid]
        .rank(method="average", pct=True, ascending=True)
        * 100.0
    )
    return output.clip(0.0, 100.0)


def weighted_mean(
    frame: pd.DataFrame,
    weights: dict[str, float],
) -> pd.Series:
    if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
        raise ValueError("Weights must sum to 1.0.")
    missing = sorted(set(weights).difference(frame.columns))
    if missing:
        raise ValueError(
            "Weighted mean is missing:\n" + "\n".join(missing)
        )

    output = pd.Series(0.0, index=frame.index, dtype=float)
    for column, weight in weights.items():
        output += (
            pd.to_numeric(frame[column], errors="coerce")
            .fillna(50.0)
            .clip(0.0, 100.0)
            * weight
        )
    return output.clip(0.0, 100.0)


def interpolate_rating(
    percentile: Any,
    rating_anchors: np.ndarray,
) -> float:
    value = float(
        np.clip(safe_float(percentile, 50.0), 0.0, 100.0)
    )
    return round(
        float(
            np.interp(
                value,
                PERCENTILE_ANCHORS,
                rating_anchors,
            )
        ),
        1,
    )


def overall_rating_from_percentile(value: Any) -> float:
    return interpolate_rating(value, OVERALL_RATING_ANCHORS)


def potential_rating_from_percentile(value: Any) -> float:
    return interpolate_rating(value, POTENTIAL_RATING_ANCHORS)


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


def age_runway_score(age: Any) -> float:
    value = safe_float(age, 28.0)
    ages = np.array(
        [18.0, 20.0, 22.0, 24.0, 26.0, 28.0, 30.0, 33.0, 36.0, 40.0]
    )
    scores = np.array(
        [100.0, 99.0, 96.0, 90.0, 80.0, 67.0, 52.0, 32.0, 16.0, 5.0]
    )
    return float(np.interp(value, ages, scores))


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
        [18.0, 20.0, 22.0, 24.0, 26.0, 28.0, 30.0, 33.0, 36.0, 40.0]
    )
    gains = np.array(
        [10.0, 9.0, 8.0, 6.5, 4.5, 2.5, 1.2, 0.5, 0.2, 0.0]
    )
    return float(np.interp(value, ages, gains))


def projection_lift_allowance(evidence: Any) -> float:
    value = float(
        np.clip(safe_float(evidence, 0.65), 0.45, 1.0)
    )
    return round(0.75 + 1.25 * value, 3)


def tier_cap(row: pd.Series) -> tuple[float, str]:
    """Return the highest OVR supported by demonstrated qualifications."""
    impact = safe_float(row.get("current_impact_rank_pct"), 50.0)
    role = safe_float(row.get("role_burden_rank_pct"), 50.0)
    breadth = safe_float(
        row.get("skill_mean_percentile_rating"),
        50.0,
    )
    downside = safe_float(
        row.get("downside_contribution_percentile_rating"),
        50.0,
    )
    evidence = safe_float(row.get("evidence_weight"), 0.65)

    cap = 98.5
    reasons: list[str] = []

    # Franchise-superstar eligibility.
    if (
        impact < 96.0
        or role < 94.0
        or breadth < 80.0
        or downside < 78.0
    ):
        cap = min(cap, 93.9)
        reasons.append("franchise_superstar_gate")

    # General superstar eligibility.
    if (
        impact < 92.0
        or role < 89.0
        or breadth < 74.0
        or downside < 68.0
    ):
        cap = min(cap, 92.9)
        reasons.append("superstar_gate")

    # All-Star eligibility.
    if (
        impact < 88.0
        or role < 82.0
        or breadth < 68.0
        or downside < 58.0
    ):
        cap = min(cap, 89.9)
        reasons.append("all_star_gate")

    # High-end starter eligibility.
    if impact < 76.0 or role < 65.0:
        cap = min(cap, 86.9)
        reasons.append("high_starter_gate")

    # Large-role starter eligibility.
    if impact < 67.0 or role < 52.0:
        cap = min(cap, 84.9)
        reasons.append("starter_gate")

    # Limited evidence cannot independently create a superstar-level OVR.
    if evidence < 0.80 and (impact < 92.0 or role < 92.0):
        cap = min(cap, 88.9)
        reasons.append("limited_evidence_gate")

    # Extremely narrow profiles receive an additional current-value ceiling.
    if breadth < 58.0:
        cap = min(cap, 86.9)
        reasons.append("skill_breadth_gate")

    return round(cap, 1), "|".join(reasons) or "none"


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


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if np.isnan(value) else float(value)
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



def prepare_v4_input_columns(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Normalize compatible V3 schemas into the fields V4 expects.

    Multiple V3 builders were produced during development. The active V3
    release uses ``future_outlook_percentile_v3`` while an earlier draft used
    ``future_ceiling_rank_pct``. V4.1.1 accepts either schema and records every
    derived compatibility field.
    """
    output = frame.copy()
    derivations: dict[str, str] = {}

    if "future_ceiling_rank_pct" not in output.columns:
        if "future_outlook_percentile_v3" in output.columns:
            output["future_ceiling_rank_pct"] = pd.to_numeric(
                output["future_outlook_percentile_v3"],
                errors="coerce",
            )
            derivations[
                "future_ceiling_rank_pct"
            ] = "copied_from_future_outlook_percentile_v3"
        elif {
            "future_peak_rank_pct",
            "future_long_rank_pct",
            "future_growth_rank_pct",
        }.issubset(output.columns):
            output["future_ceiling_rank_pct"] = (
                0.55
                * pd.to_numeric(
                    output["future_peak_rank_pct"],
                    errors="coerce",
                ).fillna(50.0)
                + 0.25
                * pd.to_numeric(
                    output["future_long_rank_pct"],
                    errors="coerce",
                ).fillna(50.0)
                + 0.20
                * pd.to_numeric(
                    output["future_growth_rank_pct"],
                    errors="coerce",
                ).fillna(50.0)
            ).clip(0.0, 100.0)
            derivations[
                "future_ceiling_rank_pct"
            ] = (
                "weighted_from_future_peak_long_growth_rank_percentiles"
            )
        elif "potential_league_percentile_v3" in output.columns:
            output["future_ceiling_rank_pct"] = pd.to_numeric(
                output["potential_league_percentile_v3"],
                errors="coerce",
            )
            derivations[
                "future_ceiling_rank_pct"
            ] = "copied_from_potential_league_percentile_v3"
        elif "future_outlook_rating" in output.columns:
            output["future_ceiling_rank_pct"] = empirical_percentile(
                pd.to_numeric(
                    output["future_outlook_rating"],
                    errors="coerce",
                )
            )
            derivations[
                "future_ceiling_rank_pct"
            ] = "ranked_from_future_outlook_rating"
        else:
            raise ValueError(
                "V3 release has no usable future ceiling signal. Expected "
                "one of: future_outlook_percentile_v3; the future peak/long/"
                "growth rank trio; potential_league_percentile_v3; or "
                "future_outlook_rating."
            )

    if "upside_contribution_rank_pct" not in output.columns:
        if "projected_upside_contribution" in output.columns:
            output["upside_contribution_rank_pct"] = (
                empirical_percentile(
                    pd.to_numeric(
                        output["projected_upside_contribution"],
                        errors="coerce",
                    )
                )
            )
            derivations[
                "upside_contribution_rank_pct"
            ] = "ranked_from_projected_upside_contribution"
        elif "projected_expected_contribution" in output.columns:
            output["upside_contribution_rank_pct"] = (
                empirical_percentile(
                    pd.to_numeric(
                        output["projected_expected_contribution"],
                        errors="coerce",
                    )
                )
            )
            derivations[
                "upside_contribution_rank_pct"
            ] = "ranked_from_projected_expected_contribution"
        else:
            raise ValueError(
                "V3 release has no usable upside contribution signal."
            )

    canonical_percentile_fields = [
        "future_ceiling_rank_pct",
        "upside_contribution_rank_pct",
    ]
    for column in canonical_percentile_fields:
        values = pd.to_numeric(
            output[column],
            errors="coerce",
        )
        if values.notna().sum() == 0:
            raise ValueError(
                f"Compatibility field {column} has no numeric values."
            )
        output[column] = values.fillna(50.0).clip(0.0, 100.0)

    return output, derivations


def build_v4(
    v3: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, str]]:
    output, input_derivations = prepare_v4_input_columns(v3)
    output["player_id"] = output["player_id"].map(
        normalize_player_id
    )

    required = {
        "current_value_final_score",
        "current_impact_rank_pct",
        "role_burden_rank_pct",
        "skill_mean_percentile_rating",
        "skill_peak_percentile_rating",
        "downside_contribution_percentile_rating",
        "availability_percentile_rating",
        "evidence_weight",
        "age",
    }
    missing = sorted(required.difference(output.columns))
    if missing:
        raise ValueError(
            "V3 release is missing required V4 fields:\n"
            + "\n".join(missing)
        )

    output["demonstrated_value_score_v4"] = weighted_mean(
        output,
        DEMONSTRATED_WEIGHTS,
    )
    output["demonstrated_league_percentile_v4"] = (
        empirical_percentile(output["demonstrated_value_score_v4"])
    )
    output["demonstrated_rating_v4"] = output[
        "demonstrated_league_percentile_v4"
    ].map(overall_rating_from_percentile)

    output["projection_based_percentile_v4"] = empirical_percentile(
        numeric(output, "current_value_final_score")
    )
    output["projection_based_rating_v4"] = output[
        "projection_based_percentile_v4"
    ].map(overall_rating_from_percentile)

    output["projection_lift_allowance_v4"] = output[
        "evidence_weight"
    ].map(projection_lift_allowance)
    output["projection_lift_cap_v4"] = (
        output["demonstrated_rating_v4"]
        + output["projection_lift_allowance_v4"]
    ).clip(upper=98.5)

    gate_results = output.apply(
        tier_cap,
        axis=1,
        result_type="expand",
    )
    gate_results.columns = [
        "tier_eligibility_cap_v4",
        "tier_gate_reasons_v4",
    ]
    output = pd.concat(
        [output, gate_results],
        axis=1,
    )

    output["overall_rating_pre_gate_v4"] = output[
        "projection_based_rating_v4"
    ]
    output["overall_rating"] = np.minimum.reduce(
        [
            output["overall_rating_pre_gate_v4"].to_numpy(dtype=float),
            output["projection_lift_cap_v4"].to_numpy(dtype=float),
            output["tier_eligibility_cap_v4"].to_numpy(dtype=float),
        ]
    )
    output["overall_rating"] = (
        pd.Series(output["overall_rating"], index=output.index)
        .clip(60.0, 98.5)
        .round(1)
    )

    # Continuous ranking score keeps appropriate separation among players whose
    # one-decimal OVRs are tied by a tier cap.
    output["overall_continuous_score_v4"] = (
        0.58 * output["demonstrated_value_score_v4"]
        + 0.42 * numeric(output, "current_value_final_score", 50.0)
    )

    output = output.sort_values(
        [
            "overall_rating",
            "overall_continuous_score_v4",
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
    output["overall_league_percentile_v4"] = (
        empirical_percentile(output["overall_continuous_score_v4"])
    )

    output["overall_grade"] = output[
        "overall_rating"
    ].map(grade_from_rating)
    output["role_label"] = output[
        "overall_rating"
    ].map(role_from_rating)

    output["age_runway_score"] = output["age"].map(
        age_runway_score
    )
    output["potential_signal_v4"] = weighted_mean(
        output,
        POTENTIAL_SIGNAL_WEIGHTS,
    )

    # Convert the potential signal into an age-limited amount of ceiling room.
    normalized_signal = (
        (output["potential_signal_v4"] - 45.0) / 55.0
    ).clip(0.0, 1.0) ** 1.25

    minimum_gap = output["age"].map(minimum_potential_gap)
    maximum_gain = output["age"].map(maximum_potential_gain)
    modeled_gain = (
        minimum_gap
        + (maximum_gain - minimum_gap).clip(lower=0.0)
        * normalized_signal
    )

    output["potential_rating_pre_cap_v4"] = (
        output["overall_rating"] + modeled_gain
    )
    output["potential_breadth_cap_v4"] = [
        skill_breadth_potential_cap(
            overall=row.get("overall_rating"),
            skill_mean=row.get("skill_mean_percentile_rating"),
        )
        for row in output.to_dict(orient="records")
    ]
    output["potential_rating"] = np.minimum(
        output["potential_rating_pre_cap_v4"],
        output["potential_breadth_cap_v4"],
    )
    output["potential_rating"] = np.maximum(
        output["potential_rating"],
        output["overall_rating"] + minimum_gap,
    )
    output["potential_rating"] = (
        output["potential_rating"]
        .clip(upper=99.5)
        .round(1)
    )
    output["potential_grade"] = output[
        "potential_rating"
    ].map(grade_from_rating)

    # FUT is a forecast rather than a ceiling. Blend it with current value to
    # avoid extreme future ratings that have little current demonstrated base.
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
        output["potential_rating"] - output["overall_rating"]
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
        "V4 OVR is constrained by demonstrated impact, role burden, skill "
        "breadth, downside, availability, evidence, and tier eligibility. "
        "POT is an age-limited career ceiling and FUT is projected future "
        "standing. Source projections and optimizer values are unchanged."
    )

    return output, input_derivations


def find_player(
    frame: pd.DataFrame,
    names: list[str],
) -> pd.Series | None:
    normalized = {
        name.casefold()
        for name in names
    }
    matches = frame.loc[
        frame["player_name"].astype(str).str.casefold().isin(normalized)
    ]
    return None if matches.empty else matches.iloc[0]


def validation_rows(
    v3: pd.DataFrame,
    v4: pd.DataFrame,
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

    kon = find_player(v4, ["Kon Knueppel"])
    moussa = find_player(
        v4,
        ["Moussa Diabaté", "Moussa Diabate"],
    )

    elite_count = int(v4["overall_rating"].ge(93.0).sum())
    all_star_count = int(v4["overall_rating"].ge(90.0).sum())
    high_starter_count = int(v4["overall_rating"].ge(87.0).sum())

    # Confirm non-presentation model values remain identical by player.
    preserved_columns = [
        "projected_expected_contribution",
        "projected_downside_contribution",
        "projected_upside_contribution",
        "current_value_final_score",
        "current_impact_rank_pct",
        "role_burden_rank_pct",
        "skill_mean_percentile_rating",
        "skill_peak_percentile_rating",
        "downside_contribution_percentile_rating",
        "future_ceiling_rank_pct",
        "upside_contribution_rank_pct",
    ]
    common = [
        column
        for column in preserved_columns
        if column in v3.columns and column in v4.columns
    ]
    old = (
        v3.assign(_id=v3["player_id"].map(normalize_player_id))
        .set_index("_id")
        .sort_index()
    )
    new = (
        v4.assign(_id=v4["player_id"].map(normalize_player_id))
        .set_index("_id")
        .sort_index()
    )
    preserved = all(
        np.allclose(
            numeric(old, column).fillna(-9999.0),
            numeric(new, column).fillna(-9999.0),
        )
        for column in common
    )

    young = v4.loc[v4["age"].le(24.0)]
    young_gap = (
        young["potential_rating"]
        - young["overall_rating"]
    )

    return [
        check(
            "player_count_preserved",
            len(v3) == len(v4) == 582,
            len(v4),
            582,
        ),
        check(
            "player_ids_unique",
            v4["player_id"].is_unique
            and v4["player_id"].ne("").all(),
            int(v4["player_id"].nunique()),
            len(v4),
        ),
        check(
            "source_model_values_preserved",
            preserved,
            True,
            True,
        ),
        check(
            "league_ranks_complete",
            set(v4["league_overall_rank"])
            == set(range(1, len(v4) + 1)),
            int(v4["league_overall_rank"].nunique()),
            len(v4),
        ),
        check(
            "overall_scale_valid",
            v4["overall_rating"].between(60.0, 98.5).all(),
            {
                "minimum": float(v4["overall_rating"].min()),
                "maximum": float(v4["overall_rating"].max()),
            },
            "60.0-98.5",
        ),
        check(
            "potential_never_below_overall",
            v4["potential_rating"].ge(
                v4["overall_rating"]
            ).all(),
            int(
                v4["potential_rating"].lt(
                    v4["overall_rating"]
                ).sum()
            ),
            0,
        ),
        check(
            "future_outlook_never_above_potential",
            v4["future_outlook_rating"].le(
                v4["potential_rating"]
            ).all(),
            int(
                v4["future_outlook_rating"].gt(
                    v4["potential_rating"]
                ).sum()
            ),
            0,
        ),
        check(
            "young_players_have_ceiling_room",
            young_gap.ge(1.5 - 1e-9).all(),
            round(float(young_gap.min()), 3),
            ">=1.5",
        ),
        check(
            "elite_population_selective",
            5 <= elite_count <= 24,
            elite_count,
            "5-24 players at 93.0+",
        ),
        check(
            "all_star_population_selective",
            18 <= all_star_count <= 55,
            all_star_count,
            "18-55 players at 90.0+",
        ),
        check(
            "high_starter_population_reasonable",
            45 <= high_starter_count <= 115,
            high_starter_count,
            "45-115 players at 87.0+",
        ),
        check(
            "median_overall_reasonable",
            77.0 <= float(v4["overall_rating"].median()) <= 81.0,
            round(float(v4["overall_rating"].median()), 3),
            "77.0-81.0",
        ),
        check(
            "top_overall_below_perfect",
            float(v4["overall_rating"].max()) <= 98.5,
            round(float(v4["overall_rating"].max()), 3),
            "<=98.5",
        ),
        check(
            "kon_current_rating_moderated",
            (
                kon is None
                or (
                    int(kon["league_overall_rank"]) > 50
                    and float(kon["overall_rating"]) < 90.0
                )
            ),
            (
                None
                if kon is None
                else {
                    "rank": int(kon["league_overall_rank"]),
                    "overall": float(kon["overall_rating"]),
                    "potential": float(kon["potential_rating"]),
                    "future": float(kon["future_outlook_rating"]),
                    "tier_cap": float(
                        kon["tier_eligibility_cap_v4"]
                    ),
                }
            ),
            "rank >50 and OVR <90.0",
            severity="player_sanity",
        ),
        check(
            "moussa_has_meaningful_ceiling_room",
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
                    "rank": int(moussa["league_overall_rank"]),
                    "overall": float(moussa["overall_rating"]),
                    "potential": float(moussa["potential_rating"]),
                    "future": float(
                        moussa["future_outlook_rating"]
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
            "development_labels_complete",
            v4["development_direction"].isin(
                ["Rising", "Stable", "Declining"]
            ).all(),
            v4["development_direction"].value_counts().to_dict(),
            "Rising|Stable|Declining",
        ),
        check(
            "finishing_remains_unreleased",
            not v4["finishing_rating_released"].any(),
            bool(v4["finishing_rating_released"].any()),
            False,
        ),
    ]


def distribution_summary(frame: pd.DataFrame) -> pd.DataFrame:
    columns = [
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
    for column in columns:
        values = numeric(frame, column)
        rows.append(
            {
                "rating": column,
                "count": int(values.notna().sum()),
                "minimum": round(float(values.min()), 3),
                "p10": round(float(values.quantile(0.10)), 3),
                "p25": round(float(values.quantile(0.25)), 3),
                "median": round(float(values.median()), 3),
                "mean": round(float(values.mean()), 3),
                "p75": round(float(values.quantile(0.75)), 3),
                "p90": round(float(values.quantile(0.90)), 3),
                "p95": round(float(values.quantile(0.95)), 3),
                "maximum": round(float(values.max()), 3),
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
        "career_seasons",
        "career_games",
        "career_minutes",
        "evidence_weight",
        "points_per_game",
        "rebounds_per_game",
        "assists_per_game",
        "minutes_per_game",
        "overall_rating",
        "potential_rating",
        "future_outlook_rating",
        "contract_value_rating",
        "trade_value_rating",
        "current_impact_rank_pct",
        "role_burden_rank_pct",
        "skill_mean_percentile_rating",
        "skill_peak_percentile_rating",
        "downside_contribution_percentile_rating",
        "demonstrated_value_score_v4",
        "demonstrated_rating_v4",
        "projection_based_rating_v4",
        "projection_lift_allowance_v4",
        "projection_lift_cap_v4",
        "tier_eligibility_cap_v4",
        "tier_gate_reasons_v4",
        "overall_rating_pre_gate_v4",
        "overall_continuous_score_v4",
        "potential_signal_v4",
        "potential_rating_pre_cap_v4",
        "potential_breadth_cap_v4",
        "development_direction",
        "archetype",
    ]
    return frame[
        [column for column in columns if column in frame.columns]
    ].copy()


def build_app_payload(
    frame: pd.DataFrame,
    methodology: dict[str, Any],
) -> dict[str, Any]:
    available = [
        column for column in APP_COLUMNS if column in frame.columns
    ]
    records = frame[available].where(
        pd.notna(frame[available]),
        None,
    ).to_dict(orient="records")

    players_by_id = {
        str(record["player_id"]): json_safe(record)
        for record in records
    }
    player_ids_by_team: dict[str, list[str]] = {}
    for record in records:
        team = str(record.get("team_abbreviation", ""))
        player_ids_by_team.setdefault(team, []).append(
            str(record["player_id"])
        )

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
    """Validate the serialized app payload before any live promotion."""
    if payload.get("release_name") != RELEASE_NAME:
        raise ValueError(
            "Candidate app payload release name is incorrect: "
            f"{payload.get('release_name')!r}"
        )

    players = payload.get("players_by_id")
    if not isinstance(players, dict):
        raise ValueError(
            "Candidate app payload is missing players_by_id."
        )
    if len(players) != expected_player_count:
        raise ValueError(
            "Candidate app payload player count mismatch: "
            f"{len(players)} != {expected_player_count}"
        )

    required_fields = {
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
                f"Player payload is not a mapping: {player_id}"
            )
        missing = required_fields.difference(row)
        if missing:
            raise ValueError(
                f"Player {player_id} is missing app fields: "
                + ", ".join(sorted(missing))
            )


def promote_active_alias(
    candidate_text: str,
    *,
    expected_player_count: int,
) -> None:
    """Back up the current live alias and atomically promote V4.1."""
    candidate_payload = json.loads(candidate_text)
    validate_app_payload(
        candidate_payload,
        expected_player_count=expected_player_count,
    )

    if ACTIVE_APP_ALIAS.exists():
        ACTIVE_APP_BACKUP.write_text(
            ACTIVE_APP_ALIAS.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    temporary_path = ACTIVE_APP_ALIAS.with_suffix(".json.tmp")
    temporary_path.write_text(
        candidate_text,
        encoding="utf-8",
    )

    # Re-read the temporary file before replacing the live alias.
    temporary_payload = json.loads(
        temporary_path.read_text(encoding="utf-8")
    )
    validate_app_payload(
        temporary_payload,
        expected_player_count=expected_player_count,
    )
    temporary_path.replace(ACTIVE_APP_ALIAS)


def run_self_test() -> int:
    sample = pd.DataFrame(
        {
            "current_impact_rank_pct": [84.5, 97.0],
            "role_burden_rank_pct": [84.9, 96.0],
            "skill_mean_percentile_rating": [66.5, 90.0],
            "downside_contribution_percentile_rating": [90.9, 90.0],
            "availability_percentile_rating": [95.0, 90.0],
            "evidence_weight": [0.7596, 0.95],
        }
    )
    sample["demonstrated_value_score_v4"] = weighted_mean(
        sample,
        DEMONSTRATED_WEIGHTS,
    )

    compatibility_sample = pd.DataFrame(
        {
            "future_outlook_percentile_v3": [25.0, 75.0],
            "upside_contribution_rank_pct": [40.0, 90.0],
        }
    )
    normalized_sample, normalized_derivations = (
        prepare_v4_input_columns(compatibility_sample)
    )

    kon_like_cap, kon_like_reasons = tier_cap(sample.iloc[0])
    star_cap, _ = tier_cap(sample.iloc[1])

    tests = {
        "demonstrated_weights_sum_to_one": math.isclose(
            sum(DEMONSTRATED_WEIGHTS.values()),
            1.0,
        ),
        "potential_weights_sum_to_one": math.isclose(
            sum(POTENTIAL_SIGNAL_WEIGHTS.values()),
            1.0,
        ),
        "overall_anchors_monotonic": np.all(
            np.diff(OVERALL_RATING_ANCHORS) > 0
        ),
        "potential_anchors_monotonic": np.all(
            np.diff(POTENTIAL_RATING_ANCHORS) > 0
        ),
        "kon_like_profile_below_all_star": kon_like_cap <= 88.9,
        "kon_like_profile_hits_limited_evidence_gate": (
            "limited_evidence_gate" in kon_like_reasons
        ),
        "qualified_star_not_capped": star_cap == 98.5,
        "projection_lift_grows_with_evidence": (
            projection_lift_allowance(0.95)
            > projection_lift_allowance(0.60)
        ),
        "age_24_minimum_gap": minimum_potential_gap(24) == 1.5,
        "age_24_maximum_gain": maximum_potential_gain(24) == 6.5,
        "potential_breadth_cap_is_conservative": (
            skill_breadth_potential_cap(89.0, 66.5) == 96.0
        ),
        "grade_mapping": (
            grade_from_rating(93.0) == "A"
            and grade_from_rating(89.9) == "B+"
        ),
        "candidate_and_active_paths_are_distinct": (
            OUTPUT_APP_JSON != ACTIVE_APP_ALIAS
        ),
        "backup_and_active_paths_are_distinct": (
            ACTIVE_APP_BACKUP != ACTIVE_APP_ALIAS
        ),
        "release_name_is_v4_1_1": (
            RELEASE_NAME == "player_ratings_2026_27_v4_1_1"
        ),
        "v3_future_field_compatibility": (
            normalized_sample[
                "future_ceiling_rank_pct"
            ].tolist()
            == [25.0, 75.0]
        ),
        "v3_future_field_derivation_recorded": (
            normalized_derivations.get(
                "future_ceiling_rank_pct"
            )
            == "copied_from_future_outlook_percentile_v3"
        ),
    }
    serializable = {
        key: bool(value)
        for key, value in tests.items()
    }
    print(json.dumps(serializable, indent=2))
    return 0 if all(serializable.values()) else 1


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    input_path = locate_input()

    print("=" * 88)
    print("PLAYER RATING RELEASE V4.1.1")
    print("=" * 88)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    print("[1/6] Loading V3 accomplishment-aware release")
    v3 = read_frame(input_path)
    print(
        f"  Players: {len(v3):,} | columns: {len(v3.columns):,}"
    )

    print("[2/6] Applying demonstrated-value projection lift limits")
    print("[3/6] Applying superstar and All-Star eligibility gates")
    print("[4/6] Rebuilding POT ceiling and FUT standing")
    v4, input_derivations = build_v4(v3)
    if input_derivations:
        print("  V3 compatibility fields:")
        for field, source in input_derivations.items():
            print(f"    {field}: {source}")
    else:
        print("  V3 compatibility fields: none required")

    print("[5/6] Validating release and player sanity checks")
    validation = pd.DataFrame(validation_rows(v3, v4))
    required = validation.loc[
        validation["severity"].eq("required")
    ]
    player_checks = validation.loc[
        validation["severity"].eq("player_sanity")
    ]
    release_valid = bool(
        required["passed"].all()
        and player_checks["passed"].all()
    )

    distribution = distribution_summary(v4)
    audit = player_audit(v4)

    kon = find_player(v4, ["Kon Knueppel"])
    moussa = find_player(
        v4,
        ["Moussa Diabaté", "Moussa Diabate"],
    )

    methodology = {
        "release_name": RELEASE_NAME,
        "script_version": SCRIPT_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "release_valid": release_valid,
        "source_release": str(input_path),
        "core_interpretation": {
            "overall": (
                "Current demonstrated value constrained by impact, role "
                "burden, skill breadth, downside, availability, evidence, "
                "and tier eligibility."
            ),
            "potential": (
                "Age-limited plausible career ceiling. Never below OVR."
            ),
            "future_outlook": (
                "Projected future standing blended with current value and "
                "capped at POT."
            ),
        },
        "demonstrated_weights": DEMONSTRATED_WEIGHTS,
        "potential_signal_weights": POTENTIAL_SIGNAL_WEIGHTS,
        "v3_input_derivations": input_derivations,
        "tier_gates": {
            "franchise_superstar": {
                "impact": 96,
                "role": 94,
                "skill_breadth": 80,
                "downside": 78,
            },
            "superstar": {
                "impact": 92,
                "role": 89,
                "skill_breadth": 74,
                "downside": 68,
            },
            "all_star": {
                "impact": 88,
                "role": 82,
                "skill_breadth": 68,
                "downside": 58,
            },
            "high_end_starter": {
                "impact": 76,
                "role": 65,
            },
            "starter": {
                "impact": 67,
                "role": 52,
            },
        },
        "promotion_requested": bool(args.promote),
        "active_app_alias_promoted": bool(
            release_valid and args.promote
        ),
        "validation_passed": int(validation["passed"].sum()),
        "validation_total": len(validation),
        "outputs": {
            "parquet": str(OUTPUT_PARQUET),
            "csv": str(OUTPUT_CSV),
            "app_json": str(OUTPUT_APP_JSON),
            "active_alias": str(ACTIVE_APP_ALIAS),
            "active_alias_backup": str(ACTIVE_APP_BACKUP),
            "validation": str(VALIDATION_OUTPUT),
            "distribution": str(DISTRIBUTION_OUTPUT),
            "player_audit": str(PLAYER_AUDIT_OUTPUT),
            "top_100": str(TOP_100_OUTPUT),
        },
    }

    print("[6/6] Writing V4 artifacts")
    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    APP_DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)

    v4.to_parquet(OUTPUT_PARQUET, index=False)
    v4.to_csv(OUTPUT_CSV, index=False)
    validation.to_csv(VALIDATION_OUTPUT, index=False)
    distribution.to_csv(DISTRIBUTION_OUTPUT, index=False)
    audit.to_csv(PLAYER_AUDIT_OUTPUT, index=False)
    audit.head(100).to_csv(TOP_100_OUTPUT, index=False)
    METHODOLOGY_OUTPUT.write_text(
        json.dumps(
            json_safe(methodology),
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = build_app_payload(v4, methodology)
    validate_app_payload(
        payload,
        expected_player_count=len(v4),
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

    active_alias_promoted = False
    if args.promote:
        if not release_valid:
            raise RuntimeError(
                "Promotion was requested, but V4.1 did not pass all "
                "required and player-sanity validation checks."
            )
        promote_active_alias(
            payload_text,
            expected_player_count=len(v4),
        )
        active_alias_promoted = True

    print("Complete")
    print(
        f"Validation: {int(validation['passed'].sum())}/"
        f"{len(validation)}"
    )
    print(f"Release valid: {release_valid}")
    print(f"Promotion requested: {bool(args.promote)}")
    print(
        f"Active app alias promoted: {active_alias_promoted}"
    )
    if release_valid and not args.promote:
        print(
            "V4.1.1 candidate is valid but not live. Re-run with --promote "
            "after reviewing the top-player output."
        )
    print(f"Players rated: {len(v4):,}")
    print(
        "Overall distribution: "
        f"{v4['overall_rating'].min():.1f}-"
        f"{v4['overall_rating'].max():.1f} | "
        f"median {v4['overall_rating'].median():.1f} | "
        f"std {v4['overall_rating'].std():.1f}"
    )
    print(
        "OVR tiers: "
        f"93+ {v4['overall_rating'].ge(93.0).sum()} | "
        f"90+ {v4['overall_rating'].ge(90.0).sum()} | "
        f"87+ {v4['overall_rating'].ge(87.0).sum()}"
    )
    print(
        "Development: "
        + " | ".join(
            f"{key} {value}"
            for key, value in (
                v4["development_direction"]
                .value_counts()
                .to_dict()
                .items()
            )
        )
    )

    for name, row in [
        ("Kon Knueppel", kon),
        ("Moussa Diabaté", moussa),
    ]:
        if row is not None:
            print(
                f"{name}: rank #{int(row['league_overall_rank'])} | "
                f"OVR {float(row['overall_rating']):.1f} | "
                f"POT {float(row['potential_rating']):.1f} | "
                f"FUT {float(row['future_outlook_rating']):.1f} | "
                f"demonstrated {float(row['demonstrated_rating_v4']):.1f} | "
                f"projection {float(row['projection_based_rating_v4']):.1f} | "
                f"tier cap {float(row['tier_eligibility_cap_v4']):.1f} | "
                f"gates {row['tier_gate_reasons_v4']}"
            )

    print()
    print("TOP 25 V4 OVERALL RATINGS")
    print(
        v4[
            [
                "league_overall_rank",
                "player_name",
                "team_abbreviation",
                "overall_rating",
                "potential_rating",
                "future_outlook_rating",
                "demonstrated_rating_v4",
                "projection_based_rating_v4",
                "tier_eligibility_cap_v4",
                "career_seasons",
                "archetype",
            ]
        ]
        .head(25)
        .to_string(index=False)
    )

    failed = validation.loc[~validation["passed"]]
    if not failed.empty:
        print()
        print("FAILED VALIDATION CHECKS")
        print(failed.to_string(index=False))

    return 0 if release_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
