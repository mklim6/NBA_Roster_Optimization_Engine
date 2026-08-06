"""Calibrate player-rating display values using percentile anchors.

This script preserves every underlying model percentile and source value from
player_rating_release_2026_27_v1. It only recalibrates the presentation layer
from a linear 60.0-99.9 scale to an NBA-style anchored scale with a more
selective elite tier.

Inputs:
    data/processed/player_rating_release_2026_27_v1.parquet
    outputs/player_rating_methodology_v1.json

Outputs:
    data/processed/player_rating_release_2026_27_v2.parquet
    data/processed/player_rating_release_2026_27_v2.csv
    app_data/player_ratings_2026_27_v2.json
    outputs/player_rating_calibration_validation_v2.csv
    outputs/player_rating_distribution_summary_v2.csv
    outputs/player_rating_calibration_comparison_v2.csv
    outputs/player_rating_methodology_v2.json
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


SCRIPT_VERSION = "player-rating-calibration-v2-2-2026-08-06"
RELEASE_NAME = "player_ratings_2026_27_v2_2"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"
APP_DATA_DIRECTORY = PROJECT_ROOT / "app_data"

INPUT_PARQUET = (
    DATA_DIRECTORY / "player_rating_release_2026_27_v1.parquet"
)
INPUT_CSV = INPUT_PARQUET.with_suffix(".csv")
INPUT_METHODOLOGY = (
    OUTPUT_DIRECTORY / "player_rating_methodology_v1.json"
)

OUTPUT_PARQUET = (
    DATA_DIRECTORY / "player_rating_release_2026_27_v2.parquet"
)
OUTPUT_CSV = OUTPUT_PARQUET.with_suffix(".csv")
OUTPUT_APP_JSON = (
    APP_DATA_DIRECTORY / "player_ratings_2026_27_v2.json"
)
OUTPUT_VALIDATION = (
    OUTPUT_DIRECTORY / "player_rating_calibration_validation_v2.csv"
)
OUTPUT_DISTRIBUTION = (
    OUTPUT_DIRECTORY / "player_rating_distribution_summary_v2.csv"
)
OUTPUT_COMPARISON = (
    OUTPUT_DIRECTORY / "player_rating_calibration_comparison_v2.csv"
)
OUTPUT_METHODOLOGY = (
    OUTPUT_DIRECTORY / "player_rating_methodology_v2.json"
)

# Percentile-to-rating anchors. These intentionally make elite ratings rarer.
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
        82.0,
        85.0,
        88.0,
        90.0,
        92.0,
        95.0,
        97.0,
        98.0,
        99.0,
        99.5,
        100.0,
    ],
    dtype=float,
)

RATING_ANCHORS = np.array(
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
        86.5,
        87.0,
        88.0,
        89.0,
        90.0,
        91.0,
        93.0,
        95.0,
        96.0,
        97.2,
        98.3,
        99.9,
    ],
    dtype=float,
)

RATING_PERCENTILE_COLUMNS = {
    "overall_rating": "overall_percentile",
    "scoring_rating": "scoring_percentile",
    "shooting_rating": "shooting_percentile",
    "playmaking_rating": "playmaking_percentile",
    "rebounding_rating": "rebounding_percentile",
    "defense_rating": "defense_percentile",
    "efficiency_rating": "efficiency_percentile",
    "availability_rating": "availability_percentile",
    "potential_rating": "potential_percentile",
    "contract_value_rating": "contract_value_percentile",
    "trade_value_rating": "trade_value_percentile",
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run helper tests without loading project files.",
    )
    return parser.parse_args()


def safe_float(value: Any, default: float = np.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def empirical_league_percentile(values: pd.Series) -> pd.Series:
    """Rank a model score within the full player release.

    The source percentile fields are weighted model scores and are not
    guaranteed to be uniformly distributed. Re-ranking them across the league
    makes display thresholds such as top 5 percent and top 10 percent literal
    while preserving the original ordering and underlying values.
    """
    numeric = pd.to_numeric(values, errors="coerce")
    valid = numeric.notna()
    output = pd.Series(50.0, index=values.index, dtype=float)

    if valid.sum() == 0:
        return output

    output.loc[valid] = (
        numeric.loc[valid]
        .rank(method="average", pct=True, ascending=True)
        * 100.0
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
                RATING_ANCHORS,
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


def meaningful_development_direction(
    *,
    overall_rating: Any,
    potential_rating: Any,
    near_term_delta: Any,
    current_contribution: Any,
    age: Any,
) -> tuple[str, str]:
    """Classify meaningful development direction.

    Potential is the primary signal. Future contribution movement acts as
    supporting evidence, while small changes are treated as stable.
    """
    overall = safe_float(overall_rating, 80.0)
    potential = safe_float(potential_rating, overall)
    delta = safe_float(near_term_delta, 0.0)
    current = abs(safe_float(current_contribution, 0.0))
    player_age = safe_float(age, 27.0)

    potential_gap = potential - overall
    movement_threshold = max(1.0, 0.15 * current)

    rising = (
        player_age <= 28.0
        and (
            potential_gap >= 1.5
            or (
                potential_gap >= 0.8
                and delta >= movement_threshold
            )
        )
    )

    declining = (
        (
            player_age >= 30.0
            and potential_gap <= -2.0
        )
        or (
            player_age >= 28.0
            and potential_gap <= -1.0
            and delta <= -movement_threshold
        )
    )

    if rising:
        return "Rising", "↑"
    if declining:
        return "Declining", "↓"
    return "Stable", "→"


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


def distribution_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for rating_column in RATING_PERCENTILE_COLUMNS:
        values = pd.to_numeric(
            frame[rating_column],
            errors="coerce",
        )
        rows.append(
            {
                "rating": rating_column,
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


def build_app_json(
    frame: pd.DataFrame,
    methodology: dict[str, Any],
) -> dict[str, Any]:
    available_columns = [
        column
        for column in APP_COLUMNS
        if column in frame.columns
    ]
    records = frame[available_columns].where(
        pd.notna(frame[available_columns]),
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
            "minimum": 60.0,
            "maximum": 99.9,
            "decimals": 1,
            "example": "96.7",
            "calibration": "empirical_league_percentile_anchors_v2_2",
        },
        "player_count": len(records),
        "methodology": methodology,
        "players_by_id": players_by_id,
        "player_ids_by_team": player_ids_by_team,
    }


def validation_rows(
    v1: pd.DataFrame,
    v2: pd.DataFrame,
) -> list[dict[str, Any]]:
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

    rating_columns = list(RATING_PERCENTILE_COLUMNS)
    rating_matrix = v2[rating_columns].apply(
        pd.to_numeric,
        errors="coerce",
    )

    unchanged_percentiles = all(
        np.allclose(
            pd.to_numeric(v1[percentile], errors="coerce")
            .fillna(-9999.0)
            .to_numpy(),
            pd.to_numeric(v2[percentile], errors="coerce")
            .fillna(-9999.0)
            .to_numpy(),
        )
        for percentile in RATING_PERCENTILE_COLUMNS.values()
    )

    top_10_ids_v1 = (
        v1.sort_values("league_overall_rank")
        .head(10)["player_id"]
        .astype(str)
        .tolist()
    )
    top_10_ids_v2 = (
        v2.sort_values("league_overall_rank")
        .head(10)["player_id"]
        .astype(str)
        .tolist()
    )

    elite_count = int(v2["overall_rating"].ge(93.0).sum())
    all_star_count = int(v2["overall_rating"].ge(90.0).sum())
    high_starter_count = int(v2["overall_rating"].ge(87.0).sum())

    return [
        check(
            "player_count_preserved",
            len(v1) == len(v2) == 582,
            len(v2),
            582,
        ),
        check(
            "player_ids_preserved",
            set(v1["player_id"].astype(str))
            == set(v2["player_id"].astype(str)),
            int(v2["player_id"].nunique()),
            int(v1["player_id"].nunique()),
        ),
        check(
            "underlying_percentiles_unchanged",
            unchanged_percentiles,
            True,
            True,
        ),
        check(
            "ratings_complete",
            not rating_matrix.isna().any().any(),
            int(rating_matrix.notna().sum().sum()),
            int(rating_matrix.size),
        ),
        check(
            "ratings_within_scale",
            (
                rating_matrix.ge(60.0)
                & rating_matrix.le(99.9)
            ).all().all(),
            {
                "minimum": float(rating_matrix.min().min()),
                "maximum": float(rating_matrix.max().max()),
            },
            "60.0-99.9",
        ),
        check(
            "ratings_use_one_decimal",
            all(
                np.allclose(
                    rating_matrix[column].to_numpy(),
                    rating_matrix[column].round(1).to_numpy(),
                )
                for column in rating_columns
            ),
            True,
            True,
        ),
        check(
            "overall_rank_complete",
            set(v2["league_overall_rank"])
            == set(range(1, len(v2) + 1)),
            int(v2["league_overall_rank"].nunique()),
            len(v2),
        ),
        check(
            "top_10_order_preserved",
            top_10_ids_v1 == top_10_ids_v2,
            top_10_ids_v2,
            top_10_ids_v1,
        ),
        check(
            "elite_population_calibrated",
            10 <= elite_count <= 35,
            elite_count,
            "10-35 players at 93.0+",
        ),
        check(
            "all_star_population_calibrated",
            30 <= all_star_count <= 75,
            all_star_count,
            "30-75 players at 90.0+",
        ),
        check(
            "high_starter_population_calibrated",
            70 <= high_starter_count <= 130,
            high_starter_count,
            "70-130 players at 87.0+",
        ),
        check(
            "overall_median_reasonable",
            78.0 <= float(v2["overall_rating"].median()) <= 82.0,
            round(float(v2["overall_rating"].median()), 3),
            "78.0-82.0",
        ),
        check(
            "overall_standard_deviation_reasonable",
            5.0 <= float(v2["overall_rating"].std()) <= 9.5,
            round(float(v2["overall_rating"].std()), 3),
            "5.0-9.5",
        ),
        check(
            "development_directions_complete",
            v2["development_direction"].isin(
                ["Rising", "Stable", "Declining"]
            ).all(),
            v2["development_direction"].value_counts().to_dict(),
            "Rising|Stable|Declining",
        ),
        check(
            "rising_players_present",
            int(
                v2["development_direction"].eq("Rising").sum()
            ) >= 5,
            int(
                v2["development_direction"].eq("Rising").sum()
            ),
            ">=5",
        ),
        check(
            "declining_label_not_overused",
            int(
                v2["development_direction"].eq("Declining").sum()
            ) <= 175,
            int(
                v2["development_direction"].eq("Declining").sum()
            ),
            "<=175",
        ),
        check(
            "finishing_remains_unreleased",
            not v2["finishing_rating_released"].any(),
            bool(v2["finishing_rating_released"].any()),
            False,
        ),
        check(
            "full_precision_scope_preserved",
            v2["rating_scope_note"].str.contains(
                "full-precision",
                regex=False,
            ).all(),
            True,
            True,
        ),
    ]


def run_self_test() -> int:
    tests = {
        "anchors_are_monotonic": (
            np.all(np.diff(PERCENTILE_ANCHORS) > 0)
            and np.all(np.diff(RATING_ANCHORS) > 0)
        ),
        "anchor_lengths_match": (
            len(PERCENTILE_ANCHORS) == len(RATING_ANCHORS)
        ),
        "rating_floor": rating_from_percentile(0.0) == 60.0,
        "rating_midpoint": rating_from_percentile(50.0) == 80.0,
        "rating_all_star": rating_from_percentile(90.0) == 90.0,
        "rating_elite": rating_from_percentile(95.0) == 93.0,
        "rating_ceiling": rating_from_percentile(100.0) == 99.9,
        "rating_precision": rating_from_percentile(98.4) == 96.5,
        "grade_mapping": (
            grade_from_rating(97.2) == "A+"
            and grade_from_rating(90.0) == "A-"
        ),
        "empirical_percentile_ordering": (
            empirical_league_percentile(
                pd.Series([10.0, 20.0, 30.0, 40.0])
            ).round(1).tolist()
            == [25.0, 50.0, 75.0, 100.0]
        ),
        "young_small_decline_stable": (
            meaningful_development_direction(
                overall_rating=80.0,
                potential_rating=80.5,
                near_term_delta=-0.5,
                current_contribution=8.0,
                age=22.0,
            )[0]
            == "Stable"
        ),
        "young_upside_rising": (
            meaningful_development_direction(
                overall_rating=80.0,
                potential_rating=83.0,
                near_term_delta=0.5,
                current_contribution=8.0,
                age=22.0,
            )[0]
            == "Rising"
        ),
        "older_decline_detected": (
            meaningful_development_direction(
                overall_rating=88.0,
                potential_rating=84.0,
                near_term_delta=-2.0,
                current_contribution=8.0,
                age=32.0,
            )[0]
            == "Declining"
        ),
    }

    serializable_tests = {
        key: bool(value)
        for key, value in tests.items()
    }
    print(json.dumps(serializable_tests, indent=2))
    return 0 if all(serializable_tests.values()) else 1


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    input_path = (
        INPUT_PARQUET
        if INPUT_PARQUET.exists()
        else INPUT_CSV
    )
    if not input_path.exists():
        raise FileNotFoundError(
            "Player rating V1 was not found:\n"
            f"{INPUT_PARQUET}\n{INPUT_CSV}"
        )
    if not INPUT_METHODOLOGY.exists():
        raise FileNotFoundError(
            f"Methodology not found: {INPUT_METHODOLOGY}"
        )

    print("=" * 88)
    print("PLAYER RATING DISPLAY CALIBRATION")
    print("=" * 88)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    print("[1/6] Loading valid V1 rating release")
    if input_path.suffix.lower() == ".parquet":
        v1 = pd.read_parquet(input_path)
    else:
        v1 = pd.read_csv(input_path, low_memory=False)
    methodology_v1 = json.loads(
        INPUT_METHODOLOGY.read_text(encoding="utf-8")
    )
    print(f"  Players: {len(v1):,}")

    missing_percentiles = sorted(
        set(RATING_PERCENTILE_COLUMNS.values())
        .difference(v1.columns)
    )
    if missing_percentiles:
        raise ValueError(
            "V1 rating release is missing percentile columns:\n"
            + "\n".join(missing_percentiles)
        )

    print("[2/6] Applying anchored percentile calibration")
    v2 = v1.copy()
    comparison = pd.DataFrame(
        {
            "player_id": v1["player_id"].astype(str),
            "player_name": v1["player_name"],
            "team_abbreviation": v1["team_abbreviation"],
        }
    )

    v2["source_league_overall_rank_v1"] = v1[
        "league_overall_rank"
    ].astype(int)

    for rating_column, percentile_column in (
        RATING_PERCENTILE_COLUMNS.items()
    ):
        comparison[f"{rating_column}_v1"] = v1[rating_column]

        calibration_column = rating_column.replace(
            "_rating",
            "_calibration_percentile",
        )
        v2[calibration_column] = empirical_league_percentile(
            v2[percentile_column]
        )
        v2[rating_column] = v2[calibration_column].map(
            rating_from_percentile
        )
        comparison[
            f"{rating_column}_calibration_percentile"
        ] = v2[calibration_column]
        comparison[f"{rating_column}_v2"] = v2[rating_column]
        comparison[f"{rating_column}_change"] = (
            v2[rating_column] - v1[rating_column]
        ).round(1)

        grade_column = rating_column.replace(
            "_rating",
            "_grade",
        )
        if grade_column in v2.columns:
            v2[grade_column] = v2[rating_column].map(
                grade_from_rating
            )

    print("[3/6] Reclassifying roles and development direction")
    v2["overall_grade"] = v2["overall_rating"].map(
        grade_from_rating
    )
    v2["role_label"] = v2["overall_rating"].map(
        role_from_rating
    )

    direction_results = [
        meaningful_development_direction(
            overall_rating=row.get("overall_rating"),
            potential_rating=row.get("potential_rating"),
            near_term_delta=row.get("future_near_term_delta"),
            current_contribution=row.get(
                "future_current_contribution"
            ),
            age=row.get("age"),
        )
        for row in v2.to_dict(orient="records")
    ]
    v2["development_direction"] = [
        item[0] for item in direction_results
    ]
    v2["development_arrow"] = [
        item[1] for item in direction_results
    ]

    v2 = v2.sort_values(
        [
            "overall_rating",
            "source_league_overall_rank_v1",
        ],
        ascending=[False, True],
    ).reset_index(drop=True)
    v2["league_overall_rank"] = np.arange(
        1,
        len(v2) + 1,
    )
    v2["team_overall_rank"] = (
        v2.groupby("team_abbreviation")[
            "overall_rating"
        ]
        .rank(method="first", ascending=False)
        .astype("Int64")
    )

    print("[4/6] Building calibration diagnostics")
    distributions = distribution_summary(v2)
    comparison = comparison.merge(
        v2[
            [
                "player_id",
                "league_overall_rank",
                "overall_rating",
                "overall_grade",
                "role_label",
                "development_direction",
            ]
        ].assign(
            player_id=lambda frame: frame[
                "player_id"
            ].astype(str)
        ),
        on="player_id",
        how="left",
        validate="one_to_one",
    )

    print("[5/6] Validating calibrated release")
    validations = pd.DataFrame(
        validation_rows(v1, v2)
    )
    release_valid = bool(validations["passed"].all())

    methodology_v2 = {
        "release_name": RELEASE_NAME,
        "script_version": SCRIPT_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "release_valid": release_valid,
        "source_release": methodology_v1.get(
            "release_name",
            "player_ratings_2026_27_v1",
        ),
        "calibration_scope": (
            "Presentation-layer recalibration only. Each source score is "
            "first ranked empirically across the 582-player league, then "
            "mapped through the display anchors. Underlying model "
            "percentiles, projections, optimizer inputs, legality results, "
            "and simulation values are unchanged."
        ),
        "percentile_anchors": PERCENTILE_ANCHORS.tolist(),
        "rating_anchors": RATING_ANCHORS.tolist(),
        "rating_scale": {
            "minimum": 60.0,
            "maximum": 99.9,
            "decimals": 1,
            "example": "96.7",
        },
        "elite_threshold_interpretation": {
            "93_plus": "approximately top 5 percent",
            "90_plus": "approximately top 10 percent",
            "87_plus": "approximately top 18 percent",
        },
        "development_direction_rule": {
            "primary_signal": (
                "calibrated potential rating minus current overall rating"
            ),
            "supporting_signal": (
                "near-term projected contribution change exceeding "
                "max(1.0, 15 percent of current contribution)"
            ),
            "reason": (
                "Avoid treating ordinary age-curve decay or small projection "
                "movement as meaningful player development direction."
            ),
        },
        "finishing_rating_released": False,
        "validation_passed": int(
            validations["passed"].sum()
        ),
        "validation_total": len(validations),
        "outputs": {
            "parquet": str(OUTPUT_PARQUET),
            "csv": str(OUTPUT_CSV),
            "app_json": str(OUTPUT_APP_JSON),
            "validation": str(OUTPUT_VALIDATION),
            "distribution": str(OUTPUT_DISTRIBUTION),
            "comparison": str(OUTPUT_COMPARISON),
            "methodology": str(OUTPUT_METHODOLOGY),
        },
    }

    print("[6/6] Writing V2 rating artifacts")
    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    APP_DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)

    v2.to_parquet(OUTPUT_PARQUET, index=False)
    v2.to_csv(OUTPUT_CSV, index=False)
    validations.to_csv(OUTPUT_VALIDATION, index=False)
    distributions.to_csv(OUTPUT_DISTRIBUTION, index=False)
    comparison.to_csv(OUTPUT_COMPARISON, index=False)
    OUTPUT_METHODOLOGY.write_text(
        json.dumps(
            json_safe(methodology_v2),
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    OUTPUT_APP_JSON.write_text(
        json.dumps(
            json_safe(
                build_app_json(v2, methodology_v2)
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
    print(f"Players rated: {len(v2):,}")
    print(
        "Overall range: "
        f"{v2['overall_rating'].min():.1f}-"
        f"{v2['overall_rating'].max():.1f}"
    )
    print(
        "Overall distribution: "
        f"median {v2['overall_rating'].median():.1f} | "
        f"std {v2['overall_rating'].std():.1f}"
    )
    print(
        "Elite counts: "
        f"93+ {v2['overall_rating'].ge(93.0).sum()} | "
        f"90+ {v2['overall_rating'].ge(90.0).sum()} | "
        f"87+ {v2['overall_rating'].ge(87.0).sum()}"
    )
    print(
        "Development direction: "
        + " | ".join(
            f"{key} {value}"
            for key, value in (
                v2["development_direction"]
                .value_counts()
                .to_dict()
                .items()
            )
        )
    )
    print()
    print("TOP 10 CALIBRATED OVERALL RATINGS")
    print(
        v2[
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