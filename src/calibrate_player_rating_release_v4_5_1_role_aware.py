"""Build a current-first, history-balanced NBA player rating release.

V4.4 corrects the two remaining asymmetries in V4.3:

1. Sustained history could pull an elite current player down too aggressively.
2. A projection-heavy breakout could remain above 95 without sufficient
   sustained-history support.

V4.4 therefore:

- builds a current-core rating from demonstrated value, projection value, and
  the uncapped current percentile
- uses history as a stabilizer with a maximum 25% weight
- limits negative history adjustment to 1.5 rating points for strong current
  profiles and 2.5 points otherwise
- limits positive history adjustment to 2.5 rating points
- applies general 93+, 95+, and 97+ qualification rules
- preserves the one-season and limited-evidence safeguards
- keeps POT as career ceiling and FUT as future outlook

No source projection, optimizer, market, or legality values are changed.

Inputs
------
data/processed/player_rating_release_2026_27_v4_3_history.parquet

Outputs
-------
data/processed/player_rating_release_2026_27_v4_5_1_role_aware.parquet
data/processed/player_rating_release_2026_27_v4_4_balanced.csv
app_data/player_ratings_2026_27_v4_5_1_role_aware.json
outputs/player_rating_v4_5_1_role_aware_validation.csv
outputs/player_rating_v4_5_1_role_aware_distribution.csv
outputs/player_rating_v4_5_1_role_aware_player_audit.csv
outputs/player_rating_v4_5_1_role_aware_top_100.csv
outputs/player_rating_v4_5_1_role_aware_methodology.json
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
    "player-rating-role-aware-v4-5-1-2026-08-06"
)
RELEASE_NAME = "player_ratings_2026_27_v4_5_1_role_aware"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"
APP_DATA_DIRECTORY = PROJECT_ROOT / "app_data"

INPUT_CANDIDATES = [
    DATA_DIRECTORY
    / "player_rating_release_2026_27_v4_4_balanced.parquet",
    DATA_DIRECTORY
    / "player_rating_release_2026_27_v4_4_balanced.csv",
]

OUTPUT_PARQUET = (
    DATA_DIRECTORY
    / "player_rating_release_2026_27_v4_5_1_role_aware.parquet"
)
OUTPUT_CSV = OUTPUT_PARQUET.with_suffix(".csv")
OUTPUT_APP_JSON = (
    APP_DATA_DIRECTORY
    / "player_ratings_2026_27_v4_5_1_role_aware.json"
)
ACTIVE_APP_ALIAS = (
    APP_DATA_DIRECTORY / "player_ratings_2026_27_v2.json"
)
ACTIVE_APP_BACKUP = (
    APP_DATA_DIRECTORY
    / "player_ratings_2026_27_v2_backup_before_v4_5_1_role_aware.json"
)
VALIDATION_OUTPUT = (
    OUTPUT_DIRECTORY
    / "player_rating_v4_5_1_role_aware_validation.csv"
)
DISTRIBUTION_OUTPUT = (
    OUTPUT_DIRECTORY
    / "player_rating_v4_5_1_role_aware_distribution.csv"
)
PLAYER_AUDIT_OUTPUT = (
    OUTPUT_DIRECTORY
    / "player_rating_v4_5_1_role_aware_player_audit.csv"
)
TOP_100_OUTPUT = (
    OUTPUT_DIRECTORY
    / "player_rating_v4_5_1_role_aware_top_100.csv"
)
METHODOLOGY_OUTPUT = (
    OUTPUT_DIRECTORY
    / "player_rating_v4_5_1_role_aware_methodology.json"
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

CURRENT_CORE_WEIGHTS = {
    "demonstrated_rating_v4": 0.50,
    "projection_based_rating_v4": 0.30,
    "uncapped_current_rating_v44": 0.20,
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
    "history_weight_v44",
    "current_core_rating_v44",
    "tier_cap_v45",
    "rating_scope_note",
    "finishing_scope_note",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run helper tests without loading project files.",
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        help=(
            "Promote the validated V4.4 candidate into the active "
            "Streamlit alias."
        ),
    )
    return parser.parse_args()


def locate_input() -> Path:
    for path in INPUT_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError(
        "V4.4 rating release was not found:\n"
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
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").astype(float)


def empirical_percentile(values: pd.Series) -> pd.Series:
    numbers = pd.to_numeric(values, errors="coerce")
    valid = numbers.notna()
    output = pd.Series(50.0, index=numbers.index, dtype=float)
    if valid.sum() == 0:
        return output
    output.loc[valid] = (
        numbers.loc[valid]
        .rank(method="average", pct=True)
        .mul(100.0)
    )
    return output.clip(0.0, 100.0)


def rating_from_percentile(value: Any) -> float:
    percentile = float(
        np.clip(safe_float(value, 50.0), 0.0, 100.0)
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


def weighted_rating_mean(
    frame: pd.DataFrame,
    weights: dict[str, float],
) -> pd.Series:
    if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
        raise ValueError("Weights must sum to 1.0.")

    missing = sorted(set(weights).difference(frame.columns))
    if missing:
        raise ValueError(
            "Weighted rating mean is missing:\n"
            + "\n".join(missing)
        )

    result = pd.Series(0.0, index=frame.index, dtype=float)
    for column, weight in weights.items():
        result += (
            numeric(frame, column, 60.0)
            .fillna(60.0)
            .clip(60.0, 99.5)
            * weight
        )
    return result


def history_weight_v44(
    v43_weight: Any,
    career_seasons: Any,
) -> float:
    seasons = safe_float(career_seasons, 0.0)
    if seasons <= 1.0:
        return 0.0

    old_weight = float(
        np.clip(safe_float(v43_weight, 0.0), 0.0, 0.38)
    )
    return round(
        float(
            np.clip(
                old_weight * (0.25 / 0.38),
                0.0,
                0.25,
            )
        ),
        5,
    )


def negative_history_allowance(
    current_core: Any,
    current_impact: Any,
    role_burden: Any = 50.0,
) -> float:
    """Limit how far history may pull down strong current performance."""
    core = safe_float(current_core, 60.0)
    impact = safe_float(current_impact, 50.0)
    role = safe_float(role_burden, 50.0)

    if (
        core >= 93.0
        and impact >= 90.0
        and role >= 90.0
    ):
        return 0.75
    if core >= 90.0 and impact >= 85.0:
        return 1.5
    return 2.5


def positive_history_allowance(
    history_quality: Any,
    career_seasons: Any,
) -> float:
    quality = safe_float(history_quality, 50.0)
    seasons = safe_float(career_seasons, 0.0)

    if quality >= 95.0 and seasons >= 3.0:
        return 2.5
    return 1.5


def tier_cap_v45(row: pd.Series) -> tuple[float, str]:
    """Apply role-aware current and sustainability qualification rules.

    Skill breadth remains an input to the current-core model, but is no longer
    a hard OVR ceiling. This allows legitimate specialist stars, such as elite
    scoring/playmaking guards, to earn high OVRs without pretending that every
    star must be equally strong in all five skill families.
    """
    core = safe_float(row.get("current_core_rating_v44"), 60.0)
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
    history = safe_float(
        row.get("history_quality_score_v43"),
        50.0,
    )
    evidence = safe_float(row.get("evidence_weight"), 0.65)
    seasons = safe_float(row.get("career_seasons"), 1.0)
    recent_elite_seasons = safe_float(
        row.get("history_recent_elite_seasons"),
        0.0,
    )
    scoring = safe_float(row.get("scoring_rating"), 60.0)
    playmaking = safe_float(row.get("playmaking_rating"), 60.0)
    efficiency = safe_float(row.get("efficiency_rating"), 60.0)

    reasons: list[str] = []
    cap = 98.5

    qualifies_97 = (
        core >= 97.0
        and history >= 95.0
        and impact >= 92.0
        and role >= 92.0
        and breadth >= 70.0
    )
    if not qualifies_97:
        cap = min(cap, 96.9)
        reasons.append("97_plus_gate")

    qualifies_95 = (
        core >= 95.0
        and history >= 90.0
        and impact >= 92.0
        and role >= 90.0
    )
    if not qualifies_95:
        cap = min(cap, 94.9)
        reasons.append("95_plus_gate")

    # A 94+ rating requires sustained support or repeated elite seasons.
    # An exceptional current season can also qualify, but the current impact,
    # role burden, and downside must all be truly elite.
    qualifies_94 = (
        core >= 94.0
        and (
            history >= 90.0
            or recent_elite_seasons >= 2.0
            or (
                impact >= 95.0
                and role >= 95.0
                and downside >= 90.0
            )
        )
    )
    if not qualifies_94:
        cap = min(cap, 93.9)
        reasons.append("94_plus_sustainability_gate")

    # Established elite-current route protects players whose historical score
    # is depressed by availability or an older season, while still requiring
    # strong current impact, role, downside, and career evidence.
    established_elite_current = (
        seasons >= 5.0
        and core >= 93.0
        and impact >= 90.0
        and role >= 92.0
        and downside >= 80.0
    )
    qualifies_93 = (
        core >= 93.0
        and (
            history >= 86.0
            or established_elite_current
            or (
                impact >= 93.0
                and role >= 93.0
                and downside >= 70.0
            )
        )
    )
    if not qualifies_93:
        cap = min(cap, 92.9)
        reasons.append("93_plus_gate")

    # Role-aware specialist route. A narrow five-skill average is acceptable
    # when current role, history, downside, and at least one offensive skill are
    # strong enough to support an All-Star-level contribution.
    established_specialist = (
        seasons >= 3.0
        and core >= 90.0
        and history >= 88.0
        and role >= 88.0
        and downside >= 80.0
        and max(scoring, playmaking, efficiency) >= 88.0
    )
    qualifies_90 = (
        core >= 90.0
        and (
            history >= 82.0
            or (
                impact >= 88.0
                and role >= 82.0
            )
            or established_specialist
        )
    )
    if not qualifies_90:
        cap = min(cap, 89.9)
        reasons.append("90_plus_gate")

    limited_exception = (
        impact >= 92.0
        and role >= 90.0
        and breadth >= 72.0
        and downside >= 65.0
    )
    if evidence < 0.80 and not limited_exception:
        cap = min(cap, 87.9)
        reasons.append("limited_evidence_gate")

    if seasons <= 1.0 and not limited_exception:
        cap = min(cap, 87.5)
        reasons.append("one_season_gate")

    # Two-season players need an exceptional demonstrated profile before
    # entering the 90+ tier. This catches premature All-Star ratings while
    # preserving room for truly elite young players.
    two_season_exception = (
        core >= 92.0
        and impact >= 90.0
        and role >= 90.0
        and downside >= 70.0
    )
    if seasons <= 2.0 and not two_season_exception:
        cap = min(cap, 89.9)
        reasons.append("two_season_gate")

    return round(cap, 1), "|".join(reasons) or "none"


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


def build_v44(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    output["player_id"] = output["player_id"].map(normalize_player_id)

    required = {
        "demonstrated_rating_v4",
        "projection_based_rating_v4",
        "current_percentile_before_history_v43",
        "history_quality_score_v43",
        "history_weight_v43",
        "current_impact_rank_pct",
        "role_burden_rank_pct",
        "skill_mean_percentile_rating",
        "downside_contribution_percentile_rating",
        "evidence_weight",
        "career_seasons",
        "age",
    }
    missing = sorted(required.difference(output.columns))
    if missing:
        raise ValueError(
            "V4.3 release is missing required V4.4 fields:\n"
            + "\n".join(missing)
        )

    output["uncapped_current_rating_v44"] = output[
        "current_percentile_before_history_v43"
    ].map(rating_from_percentile)

    output["current_core_rating_v44"] = weighted_rating_mean(
        output,
        CURRENT_CORE_WEIGHTS,
    )

    output["history_rating_v44"] = output[
        "history_quality_score_v43"
    ].map(rating_from_percentile)

    output["history_weight_v44"] = [
        history_weight_v44(
            row.get("history_weight_v43"),
            row.get("career_seasons"),
        )
        for row in output.to_dict(orient="records")
    ]

    output["raw_history_blend_rating_v44"] = (
        (
            1.0 - output["history_weight_v44"]
        )
        * output["current_core_rating_v44"]
        + output["history_weight_v44"]
        * output["history_rating_v44"]
    )

    output["negative_history_allowance_v44"] = [
        negative_history_allowance(
            row.get("current_core_rating_v44"),
            row.get("current_impact_rank_pct"),
            row.get("role_burden_rank_pct"),
        )
        for row in output.to_dict(orient="records")
    ]
    output["positive_history_allowance_v44"] = [
        positive_history_allowance(
            row.get("history_quality_score_v43"),
            row.get("career_seasons"),
        )
        for row in output.to_dict(orient="records")
    ]

    output["history_lower_bound_v44"] = (
        output["current_core_rating_v44"]
        - output["negative_history_allowance_v44"]
    )
    output["history_upper_bound_v44"] = (
        output["current_core_rating_v44"]
        + output["positive_history_allowance_v44"]
    )

    output["bounded_history_rating_v44"] = np.maximum(
        output["raw_history_blend_rating_v44"],
        output["history_lower_bound_v44"],
    )
    output["bounded_history_rating_v44"] = np.minimum(
        output["bounded_history_rating_v44"],
        output["history_upper_bound_v44"],
    )

    cap_results = output.apply(
        tier_cap_v45,
        axis=1,
        result_type="expand",
    )
    cap_results.columns = [
        "tier_cap_v45",
        "tier_gate_reasons_v45",
    ]
    output = pd.concat([output, cap_results], axis=1)

    output["overall_rating"] = np.minimum(
        output["bounded_history_rating_v44"],
        output["tier_cap_v45"],
    )
    output["overall_rating"] = (
        output["overall_rating"]
        .clip(60.0, 98.5)
        .round(1)
    )

    # Continuous score preserves ordering among equal one-decimal ratings.
    output["overall_continuous_score_v44"] = (
        output["bounded_history_rating_v44"]
        - 0.002
        * (
            98.5 - output["tier_cap_v45"]
        ).clip(lower=0.0)
    )

    output = output.sort_values(
        [
            "overall_rating",
            "overall_continuous_score_v44",
            "player_name",
        ],
        ascending=[False, False, True],
    ).reset_index(drop=True)

    output["league_overall_rank"] = np.arange(1, len(output) + 1)
    output["team_overall_rank"] = (
        output.groupby("team_abbreviation")["overall_rating"]
        .rank(method="first", ascending=False)
        .astype("Int64")
    )
    output["overall_league_percentile_v44"] = empirical_percentile(
        output["overall_continuous_score_v44"]
    )
    output["overall_grade"] = output["overall_rating"].map(
        grade_from_rating
    )
    output["role_label"] = output["overall_rating"].map(
        role_from_rating
    )

    # Recalculate POT from the existing V4 signal and the new OVR.
    potential_signal = numeric(output, "potential_signal_v4", 50.0)
    normalized_signal = (
        (potential_signal - 45.0) / 55.0
    ).clip(0.0, 1.0) ** 1.25

    minimum_gap = output["age"].map(minimum_potential_gap)
    maximum_gain = output["age"].map(maximum_potential_gain)
    modeled_gain = (
        minimum_gap
        + (maximum_gain - minimum_gap).clip(lower=0.0)
        * normalized_signal
    )

    output["potential_rating_pre_cap_v44"] = (
        output["overall_rating"] + modeled_gain
    )
    output["potential_breadth_cap_v44"] = [
        skill_breadth_potential_cap(
            row.get("overall_rating"),
            row.get("skill_mean_percentile_rating"),
        )
        for row in output.to_dict(orient="records")
    ]

    output["potential_rating"] = np.minimum(
        output["potential_rating_pre_cap_v44"],
        output["potential_breadth_cap_v44"],
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
    output["potential_grade"] = output["potential_rating"].map(
        grade_from_rating
    )

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
            output["overall_rating"],
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
        output["future_outlook_rating"] - output["overall_rating"]
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
        "V4.5 is current-first, history-balanced, and role-aware. Skill "
        "breadth remains a model input but is not a hard OVR ceiling. A 94+ "
        "rating requires sustained support or exceptional current evidence, "
        "and two-season players need an elite demonstrated exception to enter "
        "the 90+ tier. POT remains career ceiling and FUT remains future "
        "outlook."
    )

    return output


def find_player(
    frame: pd.DataFrame,
    names: list[str],
) -> pd.Series | None:
    normalized = {name.casefold() for name in names}
    matches = frame.loc[
        frame["player_name"].astype(str).str.casefold().isin(normalized)
    ]
    return None if matches.empty else matches.iloc[0]


def validation_rows(
    source: pd.DataFrame,
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
    giannis = find_player(
        candidate,
        ["Giannis Antetokounmpo"],
    )
    booker = find_player(
        candidate,
        ["Devin Booker"],
    )
    jalen_johnson = find_player(
        candidate,
        ["Jalen Johnson"],
    )
    castle = find_player(
        candidate,
        ["Stephon Castle"],
    )

    elite_count = int(candidate["overall_rating"].ge(93.0).sum())
    all_star_count = int(candidate["overall_rating"].ge(90.0).sum())
    high_starter_count = int(candidate["overall_rating"].ge(87.0).sum())

    one_season = candidate.loc[
        numeric(candidate, "career_seasons", 0.0).le(1.0)
    ]
    players_97 = candidate.loc[
        candidate["overall_rating"].ge(97.0)
    ]
    players_95 = candidate.loc[
        candidate["overall_rating"].ge(95.0)
    ]

    qualified_97 = (
        players_97.empty
        or (
            numeric(players_97, "current_core_rating_v44").ge(97.0)
            & numeric(
                players_97,
                "history_quality_score_v43",
            ).ge(95.0)
            & numeric(
                players_97,
                "current_impact_rank_pct",
            ).ge(92.0)
            & numeric(
                players_97,
                "role_burden_rank_pct",
            ).ge(92.0)
        ).all()
    )

    qualified_95 = (
        players_95.empty
        or (
            numeric(players_95, "current_core_rating_v44").ge(95.0)
            & numeric(
                players_95,
                "history_quality_score_v43",
            ).ge(90.0)
            & numeric(
                players_95,
                "current_impact_rank_pct",
            ).ge(92.0)
            & numeric(
                players_95,
                "role_burden_rank_pct",
            ).ge(90.0)
        ).all()
    )

    max_negative_adjustment = (
        candidate["current_core_rating_v44"]
        - candidate["bounded_history_rating_v44"]
    ).max()

    return [
        check(
            "player_count_preserved",
            len(source) == len(candidate) == 582,
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
            "overall_scale_valid",
            candidate["overall_rating"]
            .between(60.0, 98.5)
            .all(),
            {
                "minimum": float(candidate["overall_rating"].min()),
                "maximum": float(candidate["overall_rating"].max()),
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
            "history_weight_never_exceeds_25_percent",
            candidate["history_weight_v44"].le(0.25).all(),
            float(candidate["history_weight_v44"].max()),
            "<=0.25",
        ),
        check(
            "negative_history_adjustment_bounded",
            max_negative_adjustment <= 2.5 + 1e-9,
            round(float(max_negative_adjustment), 3),
            "<=2.5 rating points",
        ),
        check(
            "one_season_players_not_all_stars",
            one_season["overall_rating"].lt(90.0).all(),
            int(one_season["overall_rating"].ge(90.0).sum()),
            0,
        ),
        check(
            "ninety_seven_plus_qualified",
            qualified_97,
            players_97[
                [
                    "player_name",
                    "overall_rating",
                    "current_core_rating_v44",
                    "history_quality_score_v43",
                ]
            ].to_dict(orient="records"),
            "all 97+ players satisfy qualification",
        ),
        check(
            "ninety_five_plus_qualified",
            qualified_95,
            players_95[
                [
                    "player_name",
                    "overall_rating",
                    "current_core_rating_v44",
                    "history_quality_score_v43",
                ]
            ].to_dict(orient="records"),
            "all 95+ players satisfy qualification",
        ),
        check(
            "elite_population_selective",
            5 <= elite_count <= 24,
            elite_count,
            "5-24 at 93+",
        ),
        check(
            "all_star_population_selective",
            18 <= all_star_count <= 55,
            all_star_count,
            "18-55 at 90+",
        ),
        check(
            "high_starter_population_reasonable",
            45 <= high_starter_count <= 115,
            high_starter_count,
            "45-115 at 87+",
        ),
        check(
            "median_overall_reasonable",
            77.0 <= float(candidate["overall_rating"].median()) <= 81.0,
            round(float(candidate["overall_rating"].median()), 3),
            "77.0-81.0",
        ),
        check(
            "kon_current_rating_moderated",
            (
                kon is None
                or (
                    int(kon["league_overall_rank"]) > 50
                    and float(kon["overall_rating"]) <= 87.5
                    and float(kon["history_weight_v44"]) == 0.0
                )
            ),
            (
                None
                if kon is None
                else {
                    "rank": int(kon["league_overall_rank"]),
                    "overall": float(kon["overall_rating"]),
                    "potential": float(kon["potential_rating"]),
                    "history_weight": float(kon["history_weight_v44"]),
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
                    "rank": int(moussa["league_overall_rank"]),
                    "overall": float(moussa["overall_rating"]),
                    "potential": float(moussa["potential_rating"]),
                }
            ),
            "POT-OVR >=2.0",
            severity="player_sanity",
        ),
        check(
            "elite_current_multi_year_players_not_over_penalized",
            (
                giannis is None
                or (
                    float(giannis["overall_rating"]) >= 93.0
                    and int(giannis["league_overall_rank"]) <= 25
                )
            ),
            (
                None
                if giannis is None
                else {
                    "rank": int(giannis["league_overall_rank"]),
                    "overall": float(giannis["overall_rating"]),
                    "current_core": float(
                        giannis["current_core_rating_v44"]
                    ),
                    "history": float(
                        giannis["history_quality_score_v43"]
                    ),
                }
            ),
            "OVR >=93.0 and rank <=25",
            severity="player_sanity",
        ),
        check(
            "established_specialists_not_artificially_collapsed",
            (
                booker is None
                or (
                    float(booker["overall_rating"]) >= 90.0
                    and int(booker["league_overall_rank"]) <= 55
                )
            ),
            (
                None
                if booker is None
                else {
                    "rank": int(booker["league_overall_rank"]),
                    "overall": float(booker["overall_rating"]),
                    "current_core": float(
                        booker["current_core_rating_v44"]
                    ),
                    "history": float(
                        booker["history_quality_score_v43"]
                    ),
                    "skill_mean": float(
                        booker["skill_mean_percentile_rating"]
                    ),
                }
            ),
            "OVR >=90.0 and rank <=55",
            severity="player_sanity",
        ),
        check(
            "breakout_without_sustained_support_below_94",
            (
                jalen_johnson is None
                or float(jalen_johnson["overall_rating"]) < 94.0
            ),
            (
                None
                if jalen_johnson is None
                else {
                    "rank": int(
                        jalen_johnson["league_overall_rank"]
                    ),
                    "overall": float(
                        jalen_johnson["overall_rating"]
                    ),
                    "history": float(
                        jalen_johnson[
                            "history_quality_score_v43"
                        ]
                    ),
                    "recent_elite_seasons": float(
                        jalen_johnson[
                            "history_recent_elite_seasons"
                        ]
                    ),
                }
            ),
            "OVR <94.0 when history <90 and fewer than two elite seasons",
            severity="player_sanity",
        ),
        check(
            "two_season_nonexception_not_all_star",
            (
                castle is None
                or (
                    float(castle["overall_rating"]) < 90.0
                    or (
                        float(
                            castle["current_impact_rank_pct"]
                        ) >= 90.0
                        and float(
                            castle["role_burden_rank_pct"]
                        ) >= 90.0
                    )
                )
            ),
            (
                None
                if castle is None
                else {
                    "rank": int(castle["league_overall_rank"]),
                    "overall": float(castle["overall_rating"]),
                    "impact": float(
                        castle["current_impact_rank_pct"]
                    ),
                    "role": float(
                        castle["role_burden_rank_pct"]
                    ),
                }
            ),
            "OVR <90 unless two-season elite exception is met",
            severity="player_sanity",
        ),
        check(
            "finishing_remains_unreleased",
            (
                "finishing_rating_released" not in candidate.columns
                or not candidate[
                    "finishing_rating_released"
                ].fillna(False).astype(bool).any()
            ),
            False,
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
        "overall_rating",
        "potential_rating",
        "future_outlook_rating",
        "career_seasons",
        "evidence_weight",
        "demonstrated_rating_v4",
        "projection_based_rating_v4",
        "uncapped_current_rating_v44",
        "current_core_rating_v44",
        "history_quality_score_v43",
        "history_rating_v44",
        "history_weight_v44",
        "raw_history_blend_rating_v44",
        "negative_history_allowance_v44",
        "positive_history_allowance_v44",
        "history_lower_bound_v44",
        "history_upper_bound_v44",
        "bounded_history_rating_v44",
        "tier_cap_v45",
        "tier_gate_reasons_v45",
        "current_impact_rank_pct",
        "role_burden_rank_pct",
        "skill_mean_percentile_rating",
        "downside_contribution_percentile_rating",
        "history_recent3_value_percentile",
        "archetype",
    ]
    return frame[
        [column for column in columns if column in frame.columns]
    ].copy()


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


def build_app_payload(
    frame: pd.DataFrame,
    methodology: dict[str, Any],
) -> dict[str, Any]:
    available = [
        column for column in APP_COLUMNS if column in frame.columns
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
    if payload.get("release_name") != RELEASE_NAME:
        raise ValueError("Incorrect candidate release name.")

    players = payload.get("players_by_id")
    if not isinstance(players, dict):
        raise ValueError("Candidate is missing players_by_id.")
    if len(players) != expected_player_count:
        raise ValueError("Candidate player count mismatch.")

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
            raise ValueError(f"Invalid player payload: {player_id}")
        missing = required.difference(row)
        if missing:
            raise ValueError(
                f"Player {player_id} missing fields: "
                + ", ".join(sorted(missing))
            )


def promote_active_alias(
    candidate_text: str,
    expected_player_count: int,
) -> None:
    payload = json.loads(candidate_text)
    validate_app_payload(payload, expected_player_count)

    if ACTIVE_APP_ALIAS.exists():
        ACTIVE_APP_BACKUP.write_text(
            ACTIVE_APP_ALIAS.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    temporary = ACTIVE_APP_ALIAS.with_suffix(".json.tmp")
    temporary.write_text(candidate_text, encoding="utf-8")
    reloaded = json.loads(temporary.read_text(encoding="utf-8"))
    validate_app_payload(reloaded, expected_player_count)
    temporary.replace(ACTIVE_APP_ALIAS)


def run_self_test() -> int:
    kon_like = pd.Series(
        {
            "current_core_rating_v44": 92.5,
            "current_impact_rank_pct": 84.5,
            "role_burden_rank_pct": 84.9,
            "skill_mean_percentile_rating": 66.5,
            "downside_contribution_percentile_rating": 90.9,
            "history_quality_score_v43": 91.2,
            "evidence_weight": 0.7596,
            "career_seasons": 1.0,
        }
    )
    giannis_like = pd.Series(
        {
            "current_core_rating_v44": 94.1,
            "current_impact_rank_pct": 91.5,
            "role_burden_rank_pct": 94.5,
            "skill_mean_percentile_rating": 71.5,
            "downside_contribution_percentile_rating": 88.6,
            "history_quality_score_v43": 85.0,
            "evidence_weight": 0.95,
            "career_seasons": 12.0,
        }
    )

    booker_like = pd.Series(
        {
            "current_core_rating_v44": 92.2,
            "current_impact_rank_pct": 88.9,
            "role_burden_rank_pct": 92.8,
            "skill_mean_percentile_rating": 49.6,
            "downside_contribution_percentile_rating": 95.2,
            "history_quality_score_v43": 93.8,
            "history_recent_elite_seasons": 3.0,
            "evidence_weight": 0.95,
            "career_seasons": 11.0,
            "scoring_rating": 91.0,
            "playmaking_rating": 91.9,
            "efficiency_rating": 85.8,
        }
    )
    castle_like = pd.Series(
        {
            "current_core_rating_v44": 91.9,
            "current_impact_rank_pct": 85.9,
            "role_burden_rank_pct": 87.8,
            "skill_mean_percentile_rating": 62.8,
            "downside_contribution_percentile_rating": 90.4,
            "history_quality_score_v43": 84.3,
            "history_recent_elite_seasons": 1.0,
            "evidence_weight": 0.85,
            "career_seasons": 2.0,
            "scoring_rating": 87.4,
            "playmaking_rating": 92.3,
            "efficiency_rating": 85.7,
        }
    )

    kon_cap, kon_reasons = tier_cap_v45(kon_like)
    giannis_cap, _ = tier_cap_v45(giannis_like)
    booker_cap, booker_reasons = tier_cap_v45(booker_like)
    castle_cap, castle_reasons = tier_cap_v45(castle_like)

    tests = {
        "current_core_weights_sum_to_one": math.isclose(
            sum(CURRENT_CORE_WEIGHTS.values()),
            1.0,
        ),
        "one_season_history_weight_zero": (
            history_weight_v44(0.30, 1) == 0.0
        ),
        "history_weight_capped_at_25_percent": (
            history_weight_v44(0.38, 10) == 0.25
        ),
        "elite_negative_adjustment_is_0_75": (
            negative_history_allowance(94.0, 91.0, 94.0) == 0.75
        ),
        "ordinary_negative_adjustment_is_2_5": (
            negative_history_allowance(88.0, 80.0) == 2.5
        ),
        "strong_history_positive_allowance_is_2_5": (
            positive_history_allowance(96.0, 5) == 2.5
        ),
        "kon_like_profile_capped_at_87_5": kon_cap == 87.5,
        "kon_like_profile_hits_one_season_gate": (
            "one_season_gate" in kon_reasons
        ),
        "giannis_like_profile_allowed_93_plus": (
            giannis_cap >= 93.9
        ),
        "booker_like_specialist_not_narrow_capped": (
            booker_cap >= 92.9
            and "narrow_profile_gate" not in booker_reasons
        ),
        "castle_like_profile_hits_two_season_gate": (
            castle_cap == 89.9
            and "two_season_gate" in castle_reasons
        ),
        "rating_curve_monotonic": (
            rating_from_percentile(99.0)
            > rating_from_percentile(95.0)
            > rating_from_percentile(80.0)
        ),
        "candidate_and_active_paths_distinct": (
            OUTPUT_APP_JSON != ACTIVE_APP_ALIAS
        ),
        "backup_and_active_paths_distinct": (
            ACTIVE_APP_BACKUP != ACTIVE_APP_ALIAS
        ),
        "console_focus_player_names_complete": (
            {
                "Giannis Antetokounmpo",
                "Devin Booker",
                "Jalen Johnson",
                "Stephon Castle",
                "Kon Knueppel",
                "Moussa Diabaté",
            }
            == {
                "Giannis Antetokounmpo",
                "Devin Booker",
                "Jalen Johnson",
                "Stephon Castle",
                "Kon Knueppel",
                "Moussa Diabaté",
            }
        ),
    }
    print(json.dumps(tests, indent=2))
    return 0 if all(tests.values()) else 1


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    input_path = locate_input()

    print("=" * 92)
    print("PLAYER RATING RELEASE V4.5.1 ROLE-AWARE")
    print("=" * 92)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    print("[1/6] Loading validated V4.4 candidate")
    source = read_frame(input_path)
    print(f"  Players: {len(source):,} x {len(source.columns):,}")

    print("[2/6] Building current-core ratings")
    print("[3/6] Applying bounded history stabilization")
    print("[4/6] Applying role-aware 90+/93+/94+/95+/97+ qualification")
    candidate = build_v44(source)

    print("[5/6] Running realism and distribution validation")
    validations = pd.DataFrame(validation_rows(source, candidate))
    required = validations.loc[
        validations["severity"].eq("required")
    ]
    player_sanity = validations.loc[
        validations["severity"].eq("player_sanity")
    ]
    release_valid = bool(
        required["passed"].all()
        and player_sanity["passed"].all()
    )

    distribution = distribution_summary(candidate)
    audit = player_audit(candidate)

    kon = find_player(candidate, ["Kon Knueppel"])
    moussa = find_player(
        candidate,
        ["Moussa Diabaté", "Moussa Diabate"],
    )
    giannis = find_player(
        candidate,
        ["Giannis Antetokounmpo"],
    )
    booker = find_player(
        candidate,
        ["Devin Booker"],
    )
    jalen_johnson = find_player(
        candidate,
        ["Jalen Johnson"],
    )
    castle = find_player(
        candidate,
        ["Stephon Castle"],
    )

    methodology = {
        "release_name": RELEASE_NAME,
        "script_version": SCRIPT_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "release_valid": release_valid,
        "source_release": str(input_path),
        "role_aware_changes": {
            "hard_skill_breadth_cap_removed": True,
            "94_plus_sustainability_gate": True,
            "two_season_gate": True,
            "elite_negative_history_limit": 0.75,
        },
        "current_core_weights": CURRENT_CORE_WEIGHTS,
        "history_design": {
            "maximum_weight": 0.25,
            "one_season_weight": 0.0,
            "elite_negative_adjustment_limit": 0.75,
            "general_negative_adjustment_limit": 2.5,
            "positive_adjustment_limit": 2.5,
        },
        "tier_qualification": {
            "97_plus": (
                "current core >=97, history >=95, impact >=92, "
                "role >=92, breadth >=70"
            ),
            "95_plus": (
                "current core >=95, history >=90, impact >=92, "
                "role >=90"
            ),
            "94_plus": (
                "current core >=94 and history >=90, two recent elite "
                "seasons, or exceptional current evidence"
            ),
            "93_plus": (
                "current core >=93 and either history >=88 or "
                "exceptional current impact/role/downside"
            ),
            "90_plus": (
                "current core >=90 and either history >=82 or "
                "All-Star-level current impact/role"
            ),
        },
        "promotion_requested": bool(args.promote),
        "active_alias_promoted": bool(
            args.promote and release_valid
        ),
        "validation_passed": int(validations["passed"].sum()),
        "validation_total": len(validations),
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

    print("[6/6] Writing candidate artifacts")
    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    APP_DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)

    candidate.to_parquet(OUTPUT_PARQUET, index=False)
    candidate.to_csv(OUTPUT_CSV, index=False)
    validations.to_csv(VALIDATION_OUTPUT, index=False)
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

    payload = build_app_payload(candidate, methodology)
    validate_app_payload(payload, len(candidate))
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
                "Promotion requested, but V4.5.1 failed validation."
            )
        promote_active_alias(payload_text, len(candidate))
        promoted = True

    print("Complete")
    print(
        f"Validation: {int(validations['passed'].sum())}/"
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
        f"median {candidate['overall_rating'].median():.1f} | "
        f"std {candidate['overall_rating'].std():.1f}"
    )
    print(
        "OVR tiers: "
        f"93+ {candidate['overall_rating'].ge(93).sum()} | "
        f"90+ {candidate['overall_rating'].ge(90).sum()} | "
        f"87+ {candidate['overall_rating'].ge(87).sum()}"
    )

    for name, row in [
        ("Giannis Antetokounmpo", giannis),
        ("Devin Booker", booker),
        ("Jalen Johnson", jalen_johnson),
        ("Stephon Castle", castle),
        ("Kon Knueppel", kon),
        ("Moussa Diabaté", moussa),
    ]:
        if row is not None:
            print(
                f"{name}: rank #{int(row['league_overall_rank'])} | "
                f"OVR {float(row['overall_rating']):.1f} | "
                f"POT {float(row['potential_rating']):.1f} | "
                f"FUT {float(row['future_outlook_rating']):.1f} | "
                f"current core "
                f"{float(row['current_core_rating_v44']):.1f} | "
                f"history "
                f"{float(row['history_rating_v44']):.1f} | "
                f"history weight "
                f"{float(row['history_weight_v44']):.3f} | "
                f"cap {float(row['tier_cap_v45']):.1f}"
            )

    print()
    print("TOP 30 V4.5.1 OVERALL RATINGS")
    print(
        candidate[
            [
                "league_overall_rank",
                "player_name",
                "team_abbreviation",
                "overall_rating",
                "potential_rating",
                "future_outlook_rating",
                "current_core_rating_v44",
                "history_rating_v44",
                "history_weight_v44",
                "tier_cap_v45",
                "tier_gate_reasons_v45",
                "career_seasons",
                "archetype",
            ]
        ]
        .head(30)
        .to_string(index=False)
    )

    print()
    print("LARGEST RANK CHANGES FROM V4.4")
    comparison = candidate[
        [
            "player_id",
            "player_name",
            "league_overall_rank",
            "overall_rating",
        ]
    ].merge(
        source.assign(
            player_id=source["player_id"].map(normalize_player_id)
        )[
            [
                "player_id",
                "league_overall_rank",
                "overall_rating",
            ]
        ].rename(
            columns={
                "league_overall_rank": "v4_4_rank",
                "overall_rating": "v4_4_overall",
            }
        ),
        on="player_id",
        how="left",
        validate="one_to_one",
    )
    comparison["rank_change"] = (
        comparison["v4_4_rank"]
        - comparison["league_overall_rank"]
    )
    print(
        comparison.reindex(
            comparison["rank_change"]
            .abs()
            .sort_values(ascending=False)
            .index
        )
        .head(25)
        .to_string(index=False)
    )

    failed = validations.loc[~validations["passed"]]
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
