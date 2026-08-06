"""Audit the realism, calibration, and explainability of player ratings V1.

This audit does not change ratings. It identifies:
- distribution compression and grade counts,
- high-rated players whose component support is unusually weak,
- large disagreements between OVR and contribution/skill rankings,
- potential-age anomalies,
- availability risks among elite-rated players,
- separation between OVR, contract value, and trade value.

Inputs:
    data/processed/player_rating_release_2026_27_v1.parquet
    outputs/player_rating_release_validation_v1.csv
    outputs/player_rating_methodology_v1.json

Outputs:
    outputs/player_rating_realism_validation_v1.csv
    outputs/player_rating_realism_metadata_v1.json
    outputs/player_rating_top_50_component_audit_v1.csv
    outputs/player_rating_rank_disagreement_audit_v1.csv
    outputs/player_rating_manual_review_queue_v1.csv
    outputs/player_rating_grade_distribution_v1.csv
    outputs/player_rating_team_leaders_v1.csv
    outputs/player_rating_age_potential_audit_v1.csv
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


SCRIPT_VERSION = "player-rating-realism-audit-v1-2026-08-06"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

RATING_PATH = (
    DATA_DIRECTORY / "player_rating_release_2026_27_v1.parquet"
)
UPSTREAM_VALIDATION_PATH = (
    OUTPUT_DIRECTORY / "player_rating_release_validation_v1.csv"
)
METHODOLOGY_PATH = (
    OUTPUT_DIRECTORY / "player_rating_methodology_v1.json"
)

VALIDATION_OUTPUT = (
    OUTPUT_DIRECTORY / "player_rating_realism_validation_v1.csv"
)
METADATA_OUTPUT = (
    OUTPUT_DIRECTORY / "player_rating_realism_metadata_v1.json"
)
TOP_50_OUTPUT = (
    OUTPUT_DIRECTORY / "player_rating_top_50_component_audit_v1.csv"
)
RANK_DISAGREEMENT_OUTPUT = (
    OUTPUT_DIRECTORY / "player_rating_rank_disagreement_audit_v1.csv"
)
MANUAL_REVIEW_OUTPUT = (
    OUTPUT_DIRECTORY / "player_rating_manual_review_queue_v1.csv"
)
GRADE_DISTRIBUTION_OUTPUT = (
    OUTPUT_DIRECTORY / "player_rating_grade_distribution_v1.csv"
)
TEAM_LEADERS_OUTPUT = (
    OUTPUT_DIRECTORY / "player_rating_team_leaders_v1.csv"
)
AGE_POTENTIAL_OUTPUT = (
    OUTPUT_DIRECTORY / "player_rating_age_potential_audit_v1.csv"
)

REQUIRED_COLUMNS = {
    "player_id",
    "player_name",
    "team_abbreviation",
    "age",
    "league_overall_rank",
    "overall_rating",
    "overall_grade",
    "role_label",
    "archetype",
    "overall_percentile",
    "expected_contribution_percentile_rating",
    "downside_contribution_percentile_rating",
    "roster_value_percentile_rating",
    "skill_mean_percentile_rating",
    "skill_peak_percentile_rating",
    "efficiency_percentile_rating",
    "availability_percentile_rating",
    "potential_rating",
    "contract_value_rating",
    "trade_value_rating",
    "development_direction",
    "rating_confidence",
    "finishing_rating_released",
}

COMPONENT_PERCENTILE_COLUMNS = {
    "expected_contribution_percentile_rating": "Expected contribution",
    "downside_contribution_percentile_rating": "Downside contribution",
    "roster_value_percentile_rating": "Roster value",
    "skill_mean_percentile_rating": "Skill breadth",
    "skill_peak_percentile_rating": "Peak skill",
    "efficiency_percentile_rating": "Efficiency",
    "availability_percentile_rating": "Availability",
}

DISPLAY_RATING_COLUMNS = [
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

GRADE_ORDER = [
    "A+",
    "A",
    "A-",
    "B+",
    "B",
    "B-",
    "C+",
    "C",
    "C-",
    "D+",
    "D",
    "D-",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run pure helper tests without loading project files.",
    )
    return parser.parse_args()


def safe_float(value: Any, default: float = np.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def percentile_rank(
    values: pd.Series,
    *,
    higher_is_better: bool = True,
) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    valid = numeric.notna()
    output = pd.Series(np.nan, index=values.index, dtype=float)

    if valid.sum() == 0:
        return output

    rank = numeric.loc[valid].rank(
        method="average",
        ascending=not higher_is_better,
    )
    output.loc[valid] = rank
    return output


def rating_precision_valid(
    frame: pd.DataFrame,
    columns: list[str],
) -> bool:
    for column in columns:
        values = pd.to_numeric(
            frame[column],
            errors="coerce",
        ).dropna()
        if not np.allclose(
            values.to_numpy(),
            values.round(1).to_numpy(),
        ):
            return False
    return True


def build_component_audit(
    ratings: pd.DataFrame,
) -> pd.DataFrame:
    output = ratings.copy()

    component_columns = list(COMPONENT_PERCENTILE_COLUMNS)
    output["component_min_percentile"] = output[
        component_columns
    ].min(axis=1)
    output["component_max_percentile"] = output[
        component_columns
    ].max(axis=1)
    output["component_mean_percentile"] = output[
        component_columns
    ].mean(axis=1)
    output["component_std_percentile"] = output[
        component_columns
    ].std(axis=1)

    output["weakest_component_column"] = output[
        component_columns
    ].idxmin(axis=1)
    output["strongest_component_column"] = output[
        component_columns
    ].idxmax(axis=1)
    output["weakest_component"] = output[
        "weakest_component_column"
    ].map(COMPONENT_PERCENTILE_COLUMNS)
    output["strongest_component"] = output[
        "strongest_component_column"
    ].map(COMPONENT_PERCENTILE_COLUMNS)
    output["weakest_component_percentile"] = [
        safe_float(row[column])
        for row, column in zip(
            output.to_dict(orient="records"),
            output["weakest_component_column"],
        )
    ]
    output["strongest_component_percentile"] = [
        safe_float(row[column])
        for row, column in zip(
            output.to_dict(orient="records"),
            output["strongest_component_column"],
        )
    ]

    output["elite_rating_flag"] = output[
        "overall_rating"
    ].ge(93.0)
    output["high_rating_flag"] = output[
        "overall_rating"
    ].ge(90.0)
    output["low_component_support_flag"] = (
        output["high_rating_flag"]
        & output["component_min_percentile"].lt(35.0)
    )
    output["single_component_dominance_flag"] = (
        output["high_rating_flag"]
        & output["component_std_percentile"].gt(28.0)
    )
    output["elite_availability_risk_flag"] = (
        output["elite_rating_flag"]
        & output["availability_percentile_rating"].lt(35.0)
    )
    output["elite_downside_risk_flag"] = (
        output["elite_rating_flag"]
        & output[
            "downside_contribution_percentile_rating"
        ].lt(55.0)
    )

    selected = [
        "league_overall_rank",
        "player_id",
        "player_name",
        "team_abbreviation",
        "age",
        "overall_rating",
        "overall_grade",
        "role_label",
        "archetype",
        "potential_rating",
        "contract_value_rating",
        "trade_value_rating",
        "development_direction",
        "rating_confidence",
        *component_columns,
        "component_min_percentile",
        "component_max_percentile",
        "component_mean_percentile",
        "component_std_percentile",
        "weakest_component",
        "weakest_component_percentile",
        "strongest_component",
        "strongest_component_percentile",
        "low_component_support_flag",
        "single_component_dominance_flag",
        "elite_availability_risk_flag",
        "elite_downside_risk_flag",
    ]

    return output[selected].sort_values(
        "league_overall_rank"
    ).reset_index(drop=True)


def build_rank_disagreements(
    ratings: pd.DataFrame,
) -> pd.DataFrame:
    output = ratings.copy()
    output["expected_contribution_rank"] = percentile_rank(
        output["expected_contribution_percentile_rating"]
    )
    output["roster_value_rank"] = percentile_rank(
        output["roster_value_percentile_rating"]
    )
    output["skill_mean_rank"] = percentile_rank(
        output["skill_mean_percentile_rating"]
    )
    output["efficiency_rank"] = percentile_rank(
        output["efficiency_percentile_rating"]
    )
    output["availability_rank"] = percentile_rank(
        output["availability_percentile_rating"]
    )
    output["potential_rank"] = percentile_rank(
        output["potential_rating"]
    )
    output["trade_value_rank"] = percentile_rank(
        output["trade_value_rating"]
    )

    comparison_rank_columns = [
        "expected_contribution_rank",
        "roster_value_rank",
        "skill_mean_rank",
        "efficiency_rank",
    ]
    for column in comparison_rank_columns:
        stem = column.removesuffix("_rank")
        output[f"overall_vs_{stem}_rank_gap"] = (
            output[column] - output["league_overall_rank"]
        )

    gap_columns = [
        column
        for column in output.columns
        if column.startswith("overall_vs_")
        and column.endswith("_rank_gap")
    ]
    output["maximum_positive_support_gap"] = output[
        gap_columns
    ].max(axis=1)
    output["maximum_absolute_support_gap"] = output[
        gap_columns
    ].abs().max(axis=1)
    output["rank_disagreement_flag"] = (
        (
            output["league_overall_rank"].le(50)
            & output["maximum_positive_support_gap"].ge(50)
        )
        | output["maximum_absolute_support_gap"].ge(100)
    )

    selected = [
        "player_id",
        "player_name",
        "team_abbreviation",
        "age",
        "league_overall_rank",
        "overall_rating",
        "expected_contribution_rank",
        "roster_value_rank",
        "skill_mean_rank",
        "efficiency_rank",
        "availability_rank",
        "potential_rank",
        "trade_value_rank",
        *gap_columns,
        "maximum_positive_support_gap",
        "maximum_absolute_support_gap",
        "rank_disagreement_flag",
    ]

    return output[selected].sort_values(
        [
            "rank_disagreement_flag",
            "maximum_absolute_support_gap",
            "league_overall_rank",
        ],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def build_age_potential_audit(
    ratings: pd.DataFrame,
) -> pd.DataFrame:
    output = ratings.copy()
    output["potential_minus_overall"] = (
        output["potential_rating"]
        - output["overall_rating"]
    )
    output["age_potential_review_flag"] = (
        (
            output["age"].ge(30.0)
            & output["potential_minus_overall"].ge(5.0)
        )
        | (
            output["age"].le(24.0)
            & output["development_direction"].eq("Declining")
        )
        | (
            output["age"].ge(34.0)
            & output["development_direction"].eq("Rising")
        )
    )

    selected = [
        "player_id",
        "player_name",
        "team_abbreviation",
        "age",
        "overall_rating",
        "potential_rating",
        "potential_minus_overall",
        "development_direction",
        "future_peak_season",
        "age_potential_review_flag",
    ]

    return output[selected].sort_values(
        [
            "age_potential_review_flag",
            "potential_minus_overall",
            "age",
        ],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def build_manual_review_queue(
    component_audit: pd.DataFrame,
    rank_audit: pd.DataFrame,
    age_audit: pd.DataFrame,
) -> pd.DataFrame:
    reasons: dict[str, list[str]] = {}

    def add_reason(player_id: Any, reason: str) -> None:
        key = str(player_id)
        reasons.setdefault(key, [])
        if reason not in reasons[key]:
            reasons[key].append(reason)

    for row in component_audit.to_dict(orient="records"):
        player_id = row["player_id"]
        if row["low_component_support_flag"]:
            add_reason(
                player_id,
                "high_overall_with_low_component_support",
            )
        if row["single_component_dominance_flag"]:
            add_reason(
                player_id,
                "high_overall_with_component_imbalance",
            )
        if row["elite_availability_risk_flag"]:
            add_reason(
                player_id,
                "elite_overall_with_low_availability_support",
            )
        if row["elite_downside_risk_flag"]:
            add_reason(
                player_id,
                "elite_overall_with_low_downside_support",
            )

    for row in rank_audit.to_dict(orient="records"):
        if row["rank_disagreement_flag"]:
            add_reason(
                row["player_id"],
                "large_overall_component_rank_disagreement",
            )

    for row in age_audit.to_dict(orient="records"):
        if row["age_potential_review_flag"]:
            add_reason(
                row["player_id"],
                "age_potential_trajectory_review",
            )

    base = component_audit[
        [
            "player_id",
            "player_name",
            "team_abbreviation",
            "age",
            "league_overall_rank",
            "overall_rating",
            "potential_rating",
            "trade_value_rating",
            "weakest_component",
            "weakest_component_percentile",
        ]
    ].copy()
    base["review_reasons"] = base["player_id"].map(
        lambda value: "|".join(reasons.get(str(value), []))
    )
    base["review_reason_count"] = base["player_id"].map(
        lambda value: len(reasons.get(str(value), []))
    )
    base = base.loc[
        base["review_reason_count"].gt(0)
    ].copy()

    return base.sort_values(
        [
            "review_reason_count",
            "league_overall_rank",
        ],
        ascending=[False, True],
    ).reset_index(drop=True)


def build_grade_distribution(
    ratings: pd.DataFrame,
) -> pd.DataFrame:
    counts = (
        ratings["overall_grade"]
        .value_counts()
        .reindex(GRADE_ORDER, fill_value=0)
        .rename_axis("overall_grade")
        .reset_index(name="player_count")
    )
    counts["share_pct"] = (
        100.0
        * counts["player_count"]
        / max(len(ratings), 1)
    ).round(3)

    ranges = (
        ratings.groupby("overall_grade", as_index=False)
        .agg(
            minimum_overall=("overall_rating", "min"),
            maximum_overall=("overall_rating", "max"),
            median_overall=("overall_rating", "median"),
        )
    )

    return counts.merge(
        ranges,
        on="overall_grade",
        how="left",
    )


def build_team_leaders(
    ratings: pd.DataFrame,
) -> pd.DataFrame:
    sorted_ratings = ratings.sort_values(
        [
            "team_abbreviation",
            "overall_rating",
            "trade_value_rating",
            "player_name",
        ],
        ascending=[True, False, False, True],
    )
    leaders = (
        sorted_ratings.groupby(
            "team_abbreviation",
            as_index=False,
        )
        .head(5)
        .copy()
    )
    leaders["team_rating_rank"] = (
        leaders.groupby("team_abbreviation").cumcount() + 1
    )

    return leaders[
        [
            "team_abbreviation",
            "team_rating_rank",
            "player_id",
            "player_name",
            "age",
            "overall_rating",
            "potential_rating",
            "contract_value_rating",
            "trade_value_rating",
            "archetype",
            "role_label",
        ]
    ].sort_values(
        ["team_abbreviation", "team_rating_rank"]
    ).reset_index(drop=True)


def validation_rows(
    ratings: pd.DataFrame,
    upstream_validation: pd.DataFrame,
    component_audit: pd.DataFrame,
    rank_audit: pd.DataFrame,
    age_audit: pd.DataFrame,
    manual_queue: pd.DataFrame,
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

    elite_count = int(ratings["overall_rating"].ge(93.0).sum())
    all_star_count = int(ratings["overall_rating"].ge(90.0).sum())
    high_starter_count = int(ratings["overall_rating"].ge(87.0).sum())
    overall_std = float(ratings["overall_rating"].std())
    top_10 = ratings.nsmallest(10, "league_overall_rank")

    overall_trade_corr = float(
        ratings[
            ["overall_rating", "trade_value_rating"]
        ].corr().iloc[0, 1]
    )
    overall_contract_corr = float(
        ratings[
            ["overall_rating", "contract_value_rating"]
        ].corr().iloc[0, 1]
    )

    required = [
        check(
            "upstream_release_valid",
            bool(upstream_validation["passed"].all()),
            int(upstream_validation["passed"].sum()),
            len(upstream_validation),
        ),
        check(
            "player_count_is_582",
            len(ratings) == 582,
            len(ratings),
            582,
        ),
        check(
            "required_columns_present",
            REQUIRED_COLUMNS.issubset(ratings.columns),
            len(REQUIRED_COLUMNS.intersection(ratings.columns)),
            len(REQUIRED_COLUMNS),
        ),
        check(
            "player_ids_unique",
            ratings["player_id"].is_unique
            and ratings["player_id"].ne("").all(),
            int(ratings["player_id"].nunique()),
            len(ratings),
        ),
        check(
            "league_ranks_unique_and_complete",
            ratings["league_overall_rank"].nunique() == len(ratings)
            and set(ratings["league_overall_rank"])
            == set(range(1, len(ratings) + 1)),
            int(ratings["league_overall_rank"].nunique()),
            len(ratings),
        ),
        check(
            "rank_order_matches_overall",
            ratings.sort_values("league_overall_rank")[
                "overall_rating"
            ].is_monotonic_decreasing,
            True,
            True,
        ),
        check(
            "display_precision_is_one_decimal",
            rating_precision_valid(
                ratings,
                DISPLAY_RATING_COLUMNS,
            ),
            True,
            True,
        ),
        check(
            "overall_distribution_not_flat",
            overall_std >= 4.0,
            round(overall_std, 3),
            ">=4.0",
        ),
        check(
            "elite_population_reasonable",
            3 <= elite_count <= 35,
            elite_count,
            "3-35 players at 93.0+",
        ),
        check(
            "all_star_population_reasonable",
            10 <= all_star_count <= 90,
            all_star_count,
            "10-90 players at 90.0+",
        ),
        check(
            "high_starter_population_reasonable",
            25 <= high_starter_count <= 180,
            high_starter_count,
            "25-180 players at 87.0+",
        ),
        check(
            "top_10_component_support",
            float(
                top_10[
                    [
                        "expected_contribution_percentile_rating",
                        "roster_value_percentile_rating",
                        "skill_mean_percentile_rating",
                    ]
                ].median().median()
            )
            >= 75.0,
            round(
                float(
                    top_10[
                        [
                            "expected_contribution_percentile_rating",
                            "roster_value_percentile_rating",
                            "skill_mean_percentile_rating",
                        ]
                    ].median().median()
                ),
                3,
            ),
            ">=75 median support percentile",
        ),
        check(
            "trade_value_distinct_from_overall",
            overall_trade_corr < 0.98,
            round(overall_trade_corr, 4),
            "<0.98 correlation",
        ),
        check(
            "contract_value_distinct_from_overall",
            abs(overall_contract_corr) < 0.95,
            round(overall_contract_corr, 4),
            "absolute correlation <0.95",
        ),
        check(
            "finishing_remains_unreleased",
            not ratings["finishing_rating_released"].any(),
            bool(ratings["finishing_rating_released"].any()),
            False,
        ),
    ]

    review_checks = [
        check(
            "no_high_overall_low_component_flags",
            int(
                component_audit[
                    "low_component_support_flag"
                ].sum()
            )
            == 0,
            int(
                component_audit[
                    "low_component_support_flag"
                ].sum()
            ),
            0,
            severity="review",
        ),
        check(
            "no_elite_availability_risk_flags",
            int(
                component_audit[
                    "elite_availability_risk_flag"
                ].sum()
            )
            == 0,
            int(
                component_audit[
                    "elite_availability_risk_flag"
                ].sum()
            ),
            0,
            severity="review",
        ),
        check(
            "no_elite_downside_risk_flags",
            int(
                component_audit[
                    "elite_downside_risk_flag"
                ].sum()
            )
            == 0,
            int(
                component_audit[
                    "elite_downside_risk_flag"
                ].sum()
            ),
            0,
            severity="review",
        ),
        check(
            "rank_disagreement_queue_empty",
            int(rank_audit["rank_disagreement_flag"].sum())
            == 0,
            int(rank_audit["rank_disagreement_flag"].sum()),
            0,
            severity="review",
        ),
        check(
            "age_potential_queue_empty",
            int(age_audit["age_potential_review_flag"].sum())
            == 0,
            int(age_audit["age_potential_review_flag"].sum()),
            0,
            severity="review",
        ),
        check(
            "manual_review_queue_empty",
            manual_queue.empty,
            len(manual_queue),
            0,
            severity="review",
        ),
    ]

    return required + review_checks


def run_self_test() -> int:
    sample = pd.DataFrame(
        {
            "overall_rating": [95.0, 90.0, 80.0],
            "trade_value_rating": [96.0, 88.0, 75.0],
            "contract_value_rating": [70.0, 90.0, 80.0],
        }
    )
    tests = {
        "precision_accepts_one_decimal": rating_precision_valid(
            pd.DataFrame({"rating": [96.7, 84.2]}),
            ["rating"],
        ),
        "precision_rejects_two_decimals": not rating_precision_valid(
            pd.DataFrame({"rating": [96.71, 84.2]}),
            ["rating"],
        ),
        "percentile_rank_order": percentile_rank(
            pd.Series([100.0, 50.0, 75.0])
        ).tolist()
        == [1.0, 3.0, 2.0],
        "correlation_is_finite": math.isfinite(
            float(sample.corr().iloc[0, 1])
        ),
    }
    print(json.dumps(tests, indent=2))
    return 0 if all(tests.values()) else 1


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    for path in [
        RATING_PATH,
        UPSTREAM_VALIDATION_PATH,
        METHODOLOGY_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required rating artifact was not found:\n{path}"
            )

    print("=" * 88)
    print("PLAYER RATING REALISM AND CALIBRATION AUDIT")
    print("=" * 88)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    print("[1/7] Loading rating release and methodology")
    ratings = pd.read_parquet(RATING_PATH)
    upstream_validation = pd.read_csv(
        UPSTREAM_VALIDATION_PATH
    )
    methodology = json.loads(
        METHODOLOGY_PATH.read_text(encoding="utf-8")
    )
    print(
        f"  Players: {len(ratings):,} | "
        f"upstream validation: "
        f"{int(upstream_validation['passed'].sum())}/"
        f"{len(upstream_validation)}"
    )

    missing = sorted(REQUIRED_COLUMNS.difference(ratings.columns))
    if missing:
        raise ValueError(
            "Rating release is missing required columns:\n"
            + "\n".join(missing)
        )

    print("[2/7] Auditing top-player component support")
    component_audit = build_component_audit(ratings)
    top_50 = component_audit.head(50).copy()

    print("[3/7] Auditing rank disagreements")
    rank_audit = build_rank_disagreements(ratings)

    print("[4/7] Auditing age and potential trajectories")
    age_audit = build_age_potential_audit(ratings)

    print("[5/7] Building distributions and team leaders")
    grade_distribution = build_grade_distribution(ratings)
    team_leaders = build_team_leaders(ratings)

    print("[6/7] Building manual review queue")
    manual_queue = build_manual_review_queue(
        component_audit,
        rank_audit,
        age_audit,
    )

    print("[7/7] Validating and writing artifacts")
    validation = pd.DataFrame(
        validation_rows(
            ratings,
            upstream_validation,
            component_audit,
            rank_audit,
            age_audit,
            manual_queue,
        )
    )

    required = validation.loc[
        validation["severity"].eq("required")
    ]
    review = validation.loc[
        validation["severity"].eq("review")
    ]
    structural_valid = bool(required["passed"].all())
    review_ready = bool(review["passed"].all())
    release_ready_for_app = structural_valid and review_ready

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    validation.to_csv(VALIDATION_OUTPUT, index=False)
    top_50.to_csv(TOP_50_OUTPUT, index=False)
    rank_audit.to_csv(RANK_DISAGREEMENT_OUTPUT, index=False)
    manual_queue.to_csv(MANUAL_REVIEW_OUTPUT, index=False)
    grade_distribution.to_csv(
        GRADE_DISTRIBUTION_OUTPUT,
        index=False,
    )
    team_leaders.to_csv(TEAM_LEADERS_OUTPUT, index=False)
    age_audit.to_csv(AGE_POTENTIAL_OUTPUT, index=False)

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "structural_valid": structural_valid,
        "review_ready": review_ready,
        "release_ready_for_app": release_ready_for_app,
        "player_count": len(ratings),
        "validation_passed": int(validation["passed"].sum()),
        "validation_total": len(validation),
        "required_validation_passed": int(
            required["passed"].sum()
        ),
        "required_validation_total": len(required),
        "review_validation_passed": int(
            review["passed"].sum()
        ),
        "review_validation_total": len(review),
        "manual_review_players": len(manual_queue),
        "rank_disagreement_players": int(
            rank_audit["rank_disagreement_flag"].sum()
        ),
        "age_potential_review_players": int(
            age_audit["age_potential_review_flag"].sum()
        ),
        "elite_availability_risk_players": int(
            component_audit[
                "elite_availability_risk_flag"
            ].sum()
        ),
        "elite_downside_risk_players": int(
            component_audit[
                "elite_downside_risk_flag"
            ].sum()
        ),
        "overall_distribution": {
            "minimum": round(
                float(ratings["overall_rating"].min()),
                3,
            ),
            "median": round(
                float(ratings["overall_rating"].median()),
                3,
            ),
            "mean": round(
                float(ratings["overall_rating"].mean()),
                3,
            ),
            "standard_deviation": round(
                float(ratings["overall_rating"].std()),
                3,
            ),
            "maximum": round(
                float(ratings["overall_rating"].max()),
                3,
            ),
            "players_93_plus": int(
                ratings["overall_rating"].ge(93.0).sum()
            ),
            "players_90_plus": int(
                ratings["overall_rating"].ge(90.0).sum()
            ),
            "players_87_plus": int(
                ratings["overall_rating"].ge(87.0).sum()
            ),
        },
        "methodology_release_valid": methodology.get(
            "release_valid"
        ),
        "outputs": {
            "validation": str(VALIDATION_OUTPUT),
            "top_50_component_audit": str(TOP_50_OUTPUT),
            "rank_disagreement_audit": str(
                RANK_DISAGREEMENT_OUTPUT
            ),
            "manual_review_queue": str(MANUAL_REVIEW_OUTPUT),
            "grade_distribution": str(
                GRADE_DISTRIBUTION_OUTPUT
            ),
            "team_leaders": str(TEAM_LEADERS_OUTPUT),
            "age_potential_audit": str(
                AGE_POTENTIAL_OUTPUT
            ),
        },
    }
    METADATA_OUTPUT.write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )

    print("Complete")
    print(
        f"Validation: {int(validation['passed'].sum())}/"
        f"{len(validation)}"
    )
    print(
        f"Required validation: "
        f"{int(required['passed'].sum())}/"
        f"{len(required)}"
    )
    print(
        f"Review checks: "
        f"{int(review['passed'].sum())}/"
        f"{len(review)}"
    )
    print(f"Structural valid: {structural_valid}")
    print(f"Review ready: {review_ready}")
    print(
        f"Release ready for app: {release_ready_for_app}"
    )
    print(
        f"Manual review players: {len(manual_queue)}"
    )
    print(
        "Overall distribution: "
        f"{ratings['overall_rating'].min():.1f}-"
        f"{ratings['overall_rating'].max():.1f} | "
        f"median {ratings['overall_rating'].median():.1f} | "
        f"std {ratings['overall_rating'].std():.1f}"
    )
    print(
        "Elite counts: "
        f"93+ {ratings['overall_rating'].ge(93.0).sum()} | "
        f"90+ {ratings['overall_rating'].ge(90.0).sum()} | "
        f"87+ {ratings['overall_rating'].ge(87.0).sum()}"
    )

    if not manual_queue.empty:
        print()
        print("TOP MANUAL REVIEW PLAYERS")
        print(
            manual_queue.head(15).to_string(index=False)
        )

    return 0 if structural_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())