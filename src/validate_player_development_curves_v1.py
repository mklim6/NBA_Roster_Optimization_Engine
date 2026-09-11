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
    annual_delta_limits,
    project_player_development,
    project_player_multi_year,
)
from simulation_player_stat_profiles_v1 import (  # noqa: E402
    load_player_stat_profiles,
    player_id_by_name,
)

SCRIPT_VERSION = "player-development-curve-validator-v2-2026-08-11"
JSON_REPORT = OUTPUTS / "player_development_curve_validation_v1.json"
CSV_REPORT = OUTPUTS / "player_development_one_year_projection_v1.csv"

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
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else float("nan")


def median(values: list[float]) -> float:
    return statistics.median(values) if values else float("nan")


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


def projection_row(projection: PlayerDevelopmentProjection) -> dict[str, Any]:
    row: dict[str, Any] = {
        "player_id": projection.player_id,
        "player_name": projection.player_name,
        "source_season": projection.source_season,
        "target_season": projection.target_season,
        "source_age": projection.source_age,
        "target_age": projection.target_age,
        "age_bucket": age_bucket(projection.source_age),
        "career_stage": projection.career_stage,
        "development_direction": projection.development_direction,
        "profile_reliability": projection.profile_reliability,
        "current_overall_rating": projection.current_overall_rating,
        "projected_overall_rating": projection.projected_overall_rating,
        "overall_delta": projection.overall_delta,
        "potential_rating": projection.potential_rating,
        "performance_signal": projection.performance_signal,
        "opportunity_score": projection.opportunity_score,
        "opportunity_component": projection.opportunity_component,
        "draft_pedigree_component": projection.draft_pedigree_component,
        "breakout_component": projection.breakout_component,
        "annual_growth_ceiling": projection.annual_growth_ceiling,
        "annual_decline_floor": projection.annual_decline_floor,
    }
    for field in SKILL_FIELDS:
        row[f"{field}_delta"] = projection.skill_deltas[field]
        row[f"projected_{field}"] = projection.projected_skill_ratings[field]
    for name, value in projection.projected_stat_factors.items():
        row[f"projected_{name}_factor"] = value
    return row


def synthetic_profile(
    *,
    player_id: str,
    age: float,
    overall: float,
    potential: float,
    games: int,
    mpg: float,
    pick: int | None,
    years: int,
    direction: str = "Rising",
) -> dict[str, Any]:
    profile = {
        "player_id": player_id,
        "player_name": player_id,
        "age_2026_27": age,
        "overall_rating": overall,
        "potential_rating": potential,
        "future_outlook_rating": potential,
        "development_direction": direction,
        "profile_reliability": 0.90,
        "games_played": games,
        "minutes_per_game": mpg,
        "total_minutes": games * mpg,
        "years_of_service": years,
        "draft_round": 1 if pick is not None and pick <= 30 else 2,
        "draft_pick": pick,
        "stat_factors": {
            "points": 1.0,
            "rebounds": 1.0,
            "assists": 1.0,
            "steals": 1.0,
            "blocks": 1.0,
            "turnovers": 1.0,
            "fouls": 1.0,
            "three_attempts": 1.0,
            "free_throw_attempts": 1.0,
        },
    }
    for field in SKILL_FIELDS:
        profile[field] = overall
    return profile


def named_projection(
    projections: dict[str, PlayerDevelopmentProjection],
    name: str,
) -> PlayerDevelopmentProjection | None:
    player_id = player_id_by_name(name)
    if not player_id and name == "Nikola Jokić":
        player_id = player_id_by_name("Nikola Jokic")
    return projections.get(player_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260808)
    parser.add_argument("--variance-scale", type=float, default=0.85)
    args = parser.parse_args()

    config = DevelopmentConfig(
        random_seed=args.seed,
        random_variance_scale=args.variance_scale,
    )
    profiles = load_player_stat_profiles()

    projections: dict[str, PlayerDevelopmentProjection] = {}
    rerun: dict[str, PlayerDevelopmentProjection] = {}
    errors: list[dict[str, str]] = []

    for player_id, profile in profiles.items():
        try:
            projections[player_id] = project_player_development(
                profile,
                config=config,
            )
            rerun[player_id] = project_player_development(
                profile,
                config=config,
            )
        except Exception as exc:
            errors.append(
                {
                    "player_id": player_id,
                    "player_name": str(profile.get("player_name", "")),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    rows = [projection_row(item) for item in projections.values()]
    league_deltas = [float(row["overall_delta"]) for row in rows]

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["age_bucket"])].append(row)

    age_summary: list[dict[str, Any]] = []
    for bucket in ("18-23", "24-25", "26-29", "30-32", "33-35", "36+"):
        bucket_rows = grouped.get(bucket, [])
        deltas = [float(row["overall_delta"]) for row in bucket_rows]
        age_summary.append(
            {
                "age_bucket": bucket,
                "players": len(bucket_rows),
                "average_overall_delta": round(mean(deltas), 4) if deltas else None,
                "median_overall_delta": round(median(deltas), 4) if deltas else None,
                "improved_players": sum(delta > 0.05 for delta in deltas),
                "declined_players": sum(delta < -0.05 for delta in deltas),
            }
        )
    age_map = {row["age_bucket"]: row for row in age_summary}

    all_finite = all(
        finite(row["source_age"])
        and finite(row["target_age"])
        and finite(row["current_overall_rating"])
        and finite(row["projected_overall_rating"])
        and finite(row["overall_delta"])
        for row in rows
    )
    all_bounds = all(
        60.0 <= float(row["projected_overall_rating"]) <= 99.9
        for row in rows
    )
    all_age_limits = True
    for row in rows:
        low, high = annual_delta_limits(float(row["source_age"]), config)
        delta = float(row["overall_delta"])
        if delta < low - 1e-9 or delta > high + 1e-9:
            all_age_limits = False
            break

    deterministic = projections == rerun

    high = synthetic_profile(
        player_id="VALIDATE-UPSIDE",
        age=20,
        overall=74,
        potential=92,
        games=76,
        mpg=30,
        pick=4,
        years=1,
    )
    low = dict(high)
    low.update(
        {
            "player_name": "VALIDATE-UPSIDE",
            "games_played": 18,
            "minutes_per_game": 6.0,
            "total_minutes": 108.0,
        }
    )
    high_projection = project_player_development(
        high,
        performance_signal=0.65,
        config=config,
    )
    low_projection = project_player_development(
        low,
        performance_signal=0.65,
        config=config,
    )

    late_first = synthetic_profile(
        player_id="VALIDATE-PEDIGREE",
        age=20,
        overall=74,
        potential=92,
        games=60,
        mpg=20,
        pick=28,
        years=1,
    )
    second = dict(late_first)
    second["draft_pick"] = 50
    second["draft_round"] = 2
    first_projection = project_player_development(late_first, config=config)
    second_projection = project_player_development(second, config=config)

    old = synthetic_profile(
        player_id="VALIDATE-OLD",
        age=37,
        overall=88,
        potential=88,
        games=72,
        mpg=30,
        pick=None,
        years=14,
        direction="Stable",
    )
    old_projection = project_player_development(old, config=config)
    old_five = project_player_multi_year(old, seasons=4, config=config)

    wemby = named_projection(projections, "Victor Wembanyama")
    curry = named_projection(projections, "Stephen Curry")

    young = age_map.get("18-23", {})
    prime = age_map.get("26-29", {})
    veteran = age_map.get("33-35", {})
    late = age_map.get("36+", {})

    improved_count = sum(delta > 0.05 for delta in league_deltas)
    declined_count = sum(delta < -0.05 for delta in league_deltas)

    checks = {
        "engine_version_is_v2": ENGINE_VERSION == "player-development-engine-v2.0-2026-08-11",
        "profile_layer_is_nonempty": len(profiles) >= 500,
        "all_profiles_projected": len(projections) == len(profiles) and not errors,
        "same_seed_is_deterministic": deterministic,
        "all_projection_numbers_are_finite": all_finite,
        "all_projected_ratings_within_scale": all_bounds,
        "all_one_year_deltas_respect_age_limits": all_age_limits,
        "young_players_improve_on_average": bool(young) and float(young["average_overall_delta"]) > 0.35,
        "prime_players_are_broadly_stable": bool(prime) and -0.75 <= float(prime["average_overall_delta"]) <= 0.75,
        "veterans_decline_on_average": bool(veteran) and float(veteran["average_overall_delta"]) < -0.90,
        "late_career_players_decline_clearly": bool(late) and float(late["average_overall_delta"]) < -2.00,
        "both_growth_and_decline_occur": improved_count >= 40 and declined_count >= 100,
        "high_minutes_lottery_can_make_major_jump": high_projection.overall_delta >= 5.0,
        "playing_time_materially_changes_early_growth": high_projection.overall_delta - low_projection.overall_delta >= 2.0,
        "first_round_pedigree_beats_late_second": first_projection.overall_delta > second_projection.overall_delta + 0.25,
        "late_career_sample_declines": old_projection.overall_delta <= -2.0,
        "late_career_multi_year_declines": old_five[-1].projected_overall_rating < old_projection.projected_overall_rating,
        "older_shooting_is_more_durable_than_defense": old_projection.skill_deltas["shooting_rating"] > old_projection.skill_deltas["defense_rating"],
        "wembanyama_not_forced_to_decline": wemby is None or wemby.overall_delta > -1.0,
        "curry_declines": curry is None or curry.overall_delta < -1.0,
        "league_average_does_not_inflate": -1.50 <= mean(league_deltas) <= 0.75,
    }

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "script": SCRIPT_VERSION,
        "engine": ENGINE_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "profiles": len(profiles),
        "average_overall_delta": round(mean(league_deltas), 4),
        "improved_players": improved_count,
        "declined_players": declined_count,
        "age_summary": age_summary,
        "v2_examples": {
            "high_minutes_lottery": asdict(high_projection),
            "low_minutes_same_prospect": asdict(low_projection),
            "late_first": asdict(first_projection),
            "late_second": asdict(second_projection),
            "old": asdict(old_projection),
        },
    }

    OUTPUTS.mkdir(parents=True, exist_ok=True)
    JSON_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if rows:
        with CSV_REPORT.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(sorted(rows, key=lambda row: (float(row["source_age"]), str(row["player_name"]))))

    print("=" * 92)
    print("PLAYER DEVELOPMENT & OPPORTUNITY V2 CURVE VALIDATION")
    print("=" * 92)
    print(f"Profiles: {len(profiles)} | Projected: {len(projections)} | Errors: {len(errors)}")
    print(f"League average OVR delta: {mean(league_deltas):+.3f}")
    print(f"Improved: {improved_count} | Declined: {declined_count}")
    print()
    print("AGE CURVES")
    for row in age_summary:
        if row["players"]:
            print(
                f"  {row['age_bucket']:5s} | n={row['players']:3d} | "
                f"avg={row['average_overall_delta']:+.3f} | "
                f"med={row['median_overall_delta']:+.3f} | "
                f"up={row['improved_players']:3d} | down={row['declined_players']:3d}"
            )
    print()
    print("V2 SYNTHETIC REALISM EXAMPLES")
    print(f"  High-minutes lottery: {high_projection.current_overall_rating:.1f} -> {high_projection.projected_overall_rating:.1f} ({high_projection.overall_delta:+.2f})")
    print(f"  Same player, low minutes: {low_projection.current_overall_rating:.1f} -> {low_projection.projected_overall_rating:.1f} ({low_projection.overall_delta:+.2f})")
    print(f"  Late first-round: {first_projection.overall_delta:+.2f}")
    print(f"  Late second-round: {second_projection.overall_delta:+.2f}")
    print(f"  Age-37 sample: {old_projection.current_overall_rating:.1f} -> {old_projection.projected_overall_rating:.1f} ({old_projection.overall_delta:+.2f})")
    print()
    print("CHECKS")
    for name, passed in checks.items():
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
    print()
    print("JSON report:", JSON_REPORT)
    print("CSV report: ", CSV_REPORT)

    if failed:
        print("\nPLAYER DEVELOPMENT & OPPORTUNITY V2 CURVE VALIDATION FAILED")
        return 1

    print("\nPLAYER DEVELOPMENT & OPPORTUNITY V2 CURVE VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
