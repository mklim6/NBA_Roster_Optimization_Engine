from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from player_development_engine_v1 import (  # noqa: E402
    ENGINE_VERSION,
    DevelopmentConfig,
    PlayerDevelopmentProjection,
    project_player_development,
    project_player_multi_year,
)
from simulation_player_stat_profiles_v1 import (  # noqa: E402
    load_player_stat_profiles,
    player_id_by_name,
)


SCRIPT_VERSION = (
    "player-development-curve-validator-v1.1-2026-08-08"
)
JSON_REPORT = (
    OUTPUTS / "player_development_curve_validation_v1.json"
)
CSV_REPORT = (
    OUTPUTS / "player_development_one_year_projection_v1.csv"
)

SKILL_FIELDS = (
    "scoring_rating",
    "shooting_rating",
    "playmaking_rating",
    "rebounding_rating",
    "defense_rating",
    "efficiency_rating",
    "availability_rating",
)


def finite(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number)


def mean(values: list[float]) -> float:
    return (
        statistics.fmean(values)
        if values
        else float("nan")
    )


def median(values: list[float]) -> float:
    return (
        statistics.median(values)
        if values
        else float("nan")
    )


def age_bucket(age: float) -> str:
    if age <= 23:
        return "18-23"
    if age <= 25:
        return "24-25"
    if age <= 29:
        return "26-29"
    if age <= 32:
        return "30-32"
    if age <= 35:
        return "33-35"
    return "36+"


def projection_row(
    projection: PlayerDevelopmentProjection,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "player_id": projection.player_id,
        "player_name": projection.player_name,
        "source_season": projection.source_season,
        "target_season": projection.target_season,
        "source_age": projection.source_age,
        "target_age": projection.target_age,
        "age_bucket": age_bucket(
            projection.source_age
        ),
        "career_stage": projection.career_stage,
        "development_direction": (
            projection.development_direction
        ),
        "profile_reliability": (
            projection.profile_reliability
        ),
        "current_overall_rating": (
            projection.current_overall_rating
        ),
        "projected_overall_rating": (
            projection.projected_overall_rating
        ),
        "overall_delta": projection.overall_delta,
        "potential_rating": (
            projection.potential_rating
        ),
        "future_outlook_rating": (
            projection.future_outlook_rating
        ),
        "age_curve_component": (
            projection.age_curve_component
        ),
        "potential_growth_component": (
            projection.potential_growth_component
        ),
        "direction_component": (
            projection.direction_component
        ),
        "performance_component": (
            projection.performance_component
        ),
        "deterministic_seed": (
            projection.deterministic_seed
        ),
    }

    for field, delta in (
        projection.skill_deltas.items()
    ):
        row[f"{field}_delta"] = delta

    for field, rating in (
        projection.projected_skill_ratings.items()
    ):
        row[f"projected_{field}"] = rating

    for stat_name, factor in (
        projection.projected_stat_factors.items()
    ):
        row[
            f"projected_{stat_name}_factor"
        ] = factor

    return row


def build_age_summary(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[
        str,
        list[dict[str, Any]],
    ] = defaultdict(list)

    for row in rows:
        grouped[row["age_bucket"]].append(row)

    ordered = (
        "18-23",
        "24-25",
        "26-29",
        "30-32",
        "33-35",
        "36+",
    )
    summary: list[dict[str, Any]] = []

    for bucket in ordered:
        bucket_rows = grouped.get(bucket, [])
        if not bucket_rows:
            continue

        deltas = [
            float(row["overall_delta"])
            for row in bucket_rows
        ]
        summary.append(
            {
                "age_bucket": bucket,
                "players": len(bucket_rows),
                "average_overall_delta": round(
                    mean(deltas),
                    3,
                ),
                "median_overall_delta": round(
                    median(deltas),
                    3,
                ),
                "improved_players": sum(
                    delta > 0.05
                    for delta in deltas
                ),
                "stable_players": sum(
                    abs(delta) <= 0.05
                    for delta in deltas
                ),
                "declined_players": sum(
                    delta < -0.05
                    for delta in deltas
                ),
                "average_shooting_delta": round(
                    mean(
                        [
                            float(
                                row[
                                    "shooting_rating_delta"
                                ]
                            )
                            for row in bucket_rows
                        ]
                    ),
                    3,
                ),
                "average_playmaking_delta": round(
                    mean(
                        [
                            float(
                                row[
                                    "playmaking_rating_delta"
                                ]
                            )
                            for row in bucket_rows
                        ]
                    ),
                    3,
                ),
                "average_defense_delta": round(
                    mean(
                        [
                            float(
                                row[
                                    "defense_rating_delta"
                                ]
                            )
                            for row in bucket_rows
                        ]
                    ),
                    3,
                ),
                "average_availability_delta": round(
                    mean(
                        [
                            float(
                                row[
                                    "availability_rating_delta"
                                ]
                            )
                            for row in bucket_rows
                        ]
                    ),
                    3,
                ),
            }
        )

    return summary


def summary_by_bucket(
    summary: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        str(row["age_bucket"]): row
        for row in summary
    }


def named_projection(
    projections: dict[
        str,
        PlayerDevelopmentProjection,
    ],
    name: str,
) -> PlayerDevelopmentProjection | None:
    player_id = player_id_by_name(name)
    if not player_id and name == "Nikola Jokić":
        player_id = player_id_by_name(
            "Nikola Jokic"
        )
    return projections.get(player_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--seed",
        type=int,
        default=20260808,
    )
    parser.add_argument(
        "--variance-scale",
        type=float,
        default=0.55,
    )
    args = parser.parse_args()

    config = DevelopmentConfig(
        random_seed=args.seed,
        random_variance_scale=args.variance_scale,
    )
    profiles = load_player_stat_profiles()

    projections: dict[
        str,
        PlayerDevelopmentProjection,
    ] = {}
    rerun: dict[
        str,
        PlayerDevelopmentProjection,
    ] = {}
    projection_errors: list[dict[str, str]] = []

    for player_id, profile in profiles.items():
        try:
            projections[player_id] = (
                project_player_development(
                    profile,
                    config=config,
                )
            )
            rerun[player_id] = (
                project_player_development(
                    profile,
                    config=config,
                )
            )
        except Exception as exc:
            projection_errors.append(
                {
                    "player_id": player_id,
                    "player_name": str(
                        profile.get(
                            "player_name",
                            "",
                        )
                    ),
                    "error": (
                        f"{type(exc).__name__}: {exc}"
                    ),
                }
            )

    rows = [
        projection_row(projection)
        for projection in projections.values()
    ]
    age_summary = build_age_summary(rows)
    buckets = summary_by_bucket(age_summary)

    all_numbers_finite = all(
        finite(row["source_age"])
        and finite(row["target_age"])
        and finite(
            row["current_overall_rating"]
        )
        and finite(
            row["projected_overall_rating"]
        )
        and finite(row["overall_delta"])
        and all(
            finite(row[f"{field}_delta"])
            and finite(
                row[f"projected_{field}"]
            )
            for field in SKILL_FIELDS
        )
        for row in rows
    )
    all_rating_bounds = all(
        60.0
        <= float(
            row["projected_overall_rating"]
        )
        <= 99.9
        and all(
            60.0
            <= float(
                row[f"projected_{field}"]
            )
            <= 99.9
            for field in SKILL_FIELDS
        )
        for row in rows
    )
    all_delta_bounds = all(
        -3.8
        <= float(row["overall_delta"])
        <= 2.8
        for row in rows
    )
    all_ages_advance = all(
        math.isclose(
            float(row["target_age"]),
            float(row["source_age"]) + 1.0,
            abs_tol=1e-9,
        )
        for row in rows
    )
    all_stat_factors_positive = all(
        all(
            finite(value)
            and float(value) > 0
            for key, value in row.items()
            if (
                key.startswith("projected_")
                and key.endswith("_factor")
            )
        )
        for row in rows
    )

    deterministic = (
        set(projections) == set(rerun)
        and all(
            projections[player_id]
            == rerun[player_id]
            for player_id in projections
        )
    )

    young = buckets.get("18-23", {})
    prime = buckets.get("26-29", {})
    veteran = buckets.get("33-35", {})
    late = buckets.get("36+", {})

    older_rows = [
        row
        for row in rows
        if float(row["source_age"]) >= 33
    ]
    older_shooting_delta = mean(
        [
            float(row["shooting_rating_delta"])
            for row in older_rows
        ]
    )
    older_playmaking_delta = mean(
        [
            float(
                row["playmaking_rating_delta"]
            )
            for row in older_rows
        ]
    )
    older_defense_delta = mean(
        [
            float(row["defense_rating_delta"])
            for row in older_rows
        ]
    )
    older_availability_delta = mean(
        [
            float(
                row[
                    "availability_rating_delta"
                ]
            )
            for row in older_rows
        ]
    )

    league_deltas = [
        float(row["overall_delta"])
        for row in rows
    ]
    improved_count = sum(
        delta > 0.05
        for delta in league_deltas
    )
    declined_count = sum(
        delta < -0.05
        for delta in league_deltas
    )

    wemby = named_projection(
        projections,
        "Victor Wembanyama",
    )
    jokic = named_projection(
        projections,
        "Nikola Jokić",
    )
    curry = named_projection(
        projections,
        "Stephen Curry",
    )
    duren = named_projection(
        projections,
        "Jalen Duren",
    )

    curry_five_year = None
    wemby_five_year = None
    if curry is not None:
        curry_five_year = (
            project_player_multi_year(
                profiles[curry.player_id],
                seasons=5,
                config=config,
            )
        )
    if wemby is not None:
        wemby_five_year = (
            project_player_multi_year(
                profiles[wemby.player_id],
                seasons=5,
                config=config,
            )
        )

    checks = {
        "engine_version_is_current": (
            ENGINE_VERSION
            == "player-development-engine-v1.1-2026-08-08"
        ),
        "profile_layer_has_582_players": (
            len(profiles) == 582
        ),
        "all_profiles_projected": (
            len(projections) == len(profiles)
            and not projection_errors
        ),
        "same_seed_is_deterministic": deterministic,
        "all_projection_numbers_are_finite": (
            all_numbers_finite
        ),
        "all_projected_ratings_within_scale": (
            all_rating_bounds
        ),
        "all_one_year_deltas_are_bounded": (
            all_delta_bounds
        ),
        "all_ages_advance_one_year": (
            all_ages_advance
        ),
        "all_projected_stat_factors_positive": (
            all_stat_factors_positive
        ),
        "all_major_age_buckets_present": all(
            bucket in buckets
            for bucket in (
                "18-23",
                "26-29",
                "33-35",
                "36+",
            )
        ),
        "young_players_improve_on_average": (
            bool(young)
            and float(
                young["average_overall_delta"]
            )
            > 0.25
        ),
        "prime_players_remain_near_stable": (
            bool(prime)
            and -0.45
            <= float(
                prime["average_overall_delta"]
            )
            <= 0.55
        ),
        "veterans_decline_on_average": (
            bool(veteran)
            and float(
                veteran[
                    "average_overall_delta"
                ]
            )
            < -0.55
        ),
        "late_career_players_decline_clearly": (
            bool(late)
            and float(
                late["average_overall_delta"]
            )
            < -1.15
        ),
        "older_shooting_ages_better_than_defense": (
            older_shooting_delta
            > older_defense_delta
        ),
        "older_playmaking_ages_better_than_availability": (
            older_playmaking_delta
            > older_availability_delta
        ),
        "league_average_change_is_plausible": (
            -0.85
            <= mean(league_deltas)
            <= 0.30
        ),
        "both_growth_and_decline_occur": (
            improved_count >= 40
            and declined_count >= 100
        ),
        "wembanyama_projects_up": bool(
            wemby
            and wemby.overall_delta > 0.35
        ),
        "jokic_decline_is_moderate": bool(
            jokic
            and -1.60
            <= jokic.overall_delta
            <= 0.10
        ),
        "curry_projects_clear_decline": bool(
            curry
            and curry.overall_delta < -1.00
        ),
        "curry_shooting_declines_slower_than_defense": bool(
            curry
            and curry.skill_deltas[
                "shooting_rating"
            ]
            > curry.skill_deltas[
                "defense_rating"
            ]
        ),
        "duren_projects_positive_or_stable": bool(
            duren
            and duren.overall_delta > -0.05
        ),
        "curry_five_year_curve_declines": bool(
            curry_five_year
            and (
                curry_five_year[-1]
                .projected_overall_rating
                < curry_five_year[0]
                .projected_overall_rating
            )
        ),
        "wembanyama_five_year_curve_respects_ceiling": bool(
            wemby_five_year
            and all(
                item.projected_overall_rating
                <= item.potential_rating
                + config.potential_soft_buffer
                + 1e-9
                for item in wemby_five_year
            )
        ),
    }
    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]

    report = {
        "script": SCRIPT_VERSION,
        "engine": ENGINE_VERSION,
        "configuration": asdict(config),
        "checks": checks,
        "failed_checks": failed,
        "projection_errors": projection_errors,
        "population": {
            "profiles": len(profiles),
            "projected": len(projections),
            "average_overall_delta": round(
                mean(league_deltas),
                3,
            ),
            "median_overall_delta": round(
                median(league_deltas),
                3,
            ),
            "improved_players": improved_count,
            "declined_players": declined_count,
            "older_average_shooting_delta": round(
                older_shooting_delta,
                3,
            ),
            "older_average_playmaking_delta": round(
                older_playmaking_delta,
                3,
            ),
            "older_average_defense_delta": round(
                older_defense_delta,
                3,
            ),
            "older_average_availability_delta": round(
                older_availability_delta,
                3,
            ),
        },
        "age_buckets": age_summary,
        "sample_players": {
            name: asdict(projection)
            for name, projection in {
                "Victor Wembanyama": wemby,
                "Nikola Jokic": jokic,
                "Stephen Curry": curry,
                "Jalen Duren": duren,
            }.items()
            if projection is not None
        },
        "multi_year_samples": {
            "Stephen Curry": [
                asdict(item)
                for item in (
                    curry_five_year or ()
                )
            ],
            "Victor Wembanyama": [
                asdict(item)
                for item in (
                    wemby_five_year or ()
                )
            ],
        },
        "passed": not failed,
    }

    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )
    JSON_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
        ),
        encoding="utf-8",
    )

    if rows:
        fieldnames = list(rows[0])
        with CSV_REPORT.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=fieldnames,
            )
            writer.writeheader()
            writer.writerows(
                sorted(
                    rows,
                    key=lambda row: (
                        float(row["source_age"]),
                        str(row["player_name"]),
                    ),
                )
            )

    print("=" * 88)
    print("PLAYER DEVELOPMENT CURVE VALIDATION")
    print("=" * 88)
    print(
        f"Profiles: {len(profiles)} | "
        f"Projected: {len(projections)} | "
        f"Errors: {len(projection_errors)}"
    )
    print(
        "League average overall delta:",
        round(mean(league_deltas), 3),
    )
    print(
        f"Improved: {improved_count} | "
        f"Declined: {declined_count}"
    )

    print("\nAGE CURVES")
    for row in age_summary:
        print(
            f"{row['age_bucket']:5s} | "
            f"players={row['players']:3d} | "
            f"avg={row['average_overall_delta']:+.3f} | "
            f"median={row['median_overall_delta']:+.3f} | "
            f"up={row['improved_players']:3d} | "
            f"down={row['declined_players']:3d}"
        )

    print("\nSAMPLE PLAYERS")
    for name, projection in (
        report["sample_players"].items()
    ):
        print(
            f"{name:22s} | "
            f"age={projection['source_age']:.0f} | "
            f"OVR "
            f"{projection['current_overall_rating']:.2f}"
            f" -> "
            f"{projection['projected_overall_rating']:.2f} "
            f"({projection['overall_delta']:+.2f})"
        )

    print("\nCHECKS")
    for name, passed in checks.items():
        print(
            f"{'PASS' if passed else 'FAIL':4s}  "
            f"{name}"
        )

    print(f"\nJSON report: {JSON_REPORT}")
    print(f"CSV report:  {CSV_REPORT}")

    if failed:
        print(
            "\nPLAYER DEVELOPMENT CURVE "
            "VALIDATION FAILED"
        )
        return 1

    print(
        "\nPLAYER DEVELOPMENT CURVE "
        "VALIDATION PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())