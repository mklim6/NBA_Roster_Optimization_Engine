from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import random
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from simulation_player_stat_profiles_v1 import (  # noqa: E402
    load_player_stat_profiles,
    player_id_by_name,
)


ENGINE_VERSION = "player-development-engine-v1.1-2026-08-08"
SELF_TEST_REPORT = (
    OUTPUTS / "player_development_engine_v1_self_test.json"
)
DEMO_REPORT = (
    OUTPUTS / "player_development_engine_v1_demo.json"
)

RATING_FLOOR = 60.0
RATING_CEILING = 99.9

SKILL_FIELDS = (
    "scoring_rating",
    "shooting_rating",
    "playmaking_rating",
    "rebounding_rating",
    "defense_rating",
    "efficiency_rating",
    "availability_rating",
)

OVERALL_WEIGHTS = {
    "scoring_rating": 0.24,
    "shooting_rating": 0.12,
    "playmaking_rating": 0.16,
    "rebounding_rating": 0.12,
    "defense_rating": 0.18,
    "efficiency_rating": 0.13,
    "availability_rating": 0.05,
}

# A value above 1.0 means the skill ages faster than the baseline age curve.
# Shooting and playmaking are intentionally more durable than defense,
# rebounding mobility, and availability.
AGE_SENSITIVITY = {
    "scoring_rating": 0.95,
    "shooting_rating": 0.48,
    "playmaking_rating": 0.44,
    "rebounding_rating": 1.00,
    "defense_rating": 1.12,
    "efficiency_rating": 0.68,
    "availability_rating": 1.28,
}

GROWTH_SENSITIVITY = {
    "scoring_rating": 1.00,
    "shooting_rating": 0.92,
    "playmaking_rating": 0.96,
    "rebounding_rating": 0.78,
    "defense_rating": 0.94,
    "efficiency_rating": 0.86,
    "availability_rating": 0.22,
}

DIRECTION_SENSITIVITY = {
    "scoring_rating": 1.00,
    "shooting_rating": 0.85,
    "playmaking_rating": 0.90,
    "rebounding_rating": 0.75,
    "defense_rating": 0.90,
    "efficiency_rating": 0.88,
    "availability_rating": 0.55,
}

VOLATILITY = {
    "scoring_rating": 1.00,
    "shooting_rating": 0.72,
    "playmaking_rating": 0.68,
    "rebounding_rating": 0.80,
    "defense_rating": 0.95,
    "efficiency_rating": 0.72,
    "availability_rating": 1.15,
}

STAT_FACTOR_BOUNDS = {
    "points": (0.35, 2.75),
    "rebounds": (0.25, 3.25),
    "assists": (0.20, 4.50),
    "steals": (0.25, 3.00),
    "blocks": (0.15, 5.00),
    "turnovers": (0.35, 2.75),
    "fouls": (0.45, 2.25),
    "three_attempts": (0.10, 4.25),
    "free_throw_attempts": (0.20, 3.50),
}


class PlayerDevelopmentError(RuntimeError):
    """Raised when a development projection cannot be created."""


@dataclass(frozen=True)
class DevelopmentConfig:
    random_seed: int = 20260808
    random_variance_scale: float = 0.55
    performance_signal_weight: float = 0.55
    maximum_one_year_growth: float = 2.8
    maximum_one_year_decline: float = -3.8
    potential_soft_buffer: float = 0.35
    minimum_profile_reliability: float = 0.10


@dataclass(frozen=True)
class PlayerDevelopmentProjection:
    engine_version: str
    player_id: str
    player_name: str
    source_season: str
    target_season: str
    source_age: float
    target_age: float
    career_stage: str
    deterministic_seed: int
    performance_signal: float
    profile_reliability: float
    current_overall_rating: float
    projected_overall_rating: float
    overall_delta: float
    potential_rating: float
    future_outlook_rating: float
    development_direction: str
    age_curve_component: float
    potential_growth_component: float
    direction_component: float
    performance_component: float
    skill_deltas: dict[str, float]
    projected_skill_ratings: dict[str, float]
    projected_stat_factors: dict[str, float]


def finite_float(
    value: Any,
    default: float | None = None,
) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def clamp(
    value: float,
    minimum: float,
    maximum: float,
) -> float:
    return max(minimum, min(maximum, value))


def normalized_season_label(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PlayerDevelopmentError(
            "A source or target season label is required."
        )
    return text


def next_season_label(source_season: str) -> str:
    source_season = normalized_season_label(
        source_season
    )
    try:
        start_text, end_text = source_season.split("-")
        start_year = int(start_text)
        if len(end_text) != 2:
            raise ValueError
    except (ValueError, TypeError):
        raise PlayerDevelopmentError(
            f"Unsupported season label: {source_season!r}"
        ) from None

    next_start = start_year + 1
    next_end = str(next_start + 1)[-2:]
    return f"{next_start}-{next_end}"


def stable_player_seed(
    *,
    global_seed: int,
    player_id: str,
    source_season: str,
    target_season: str,
) -> int:
    payload = (
        f"{int(global_seed)}|{player_id}|"
        f"{source_season}|{target_season}"
    ).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(
        digest[:8],
        byteorder="big",
        signed=False,
    )


def profile_age(profile: Mapping[str, Any]) -> float:
    age = finite_float(
        profile.get("age_2026_27"),
        finite_float(profile.get("age")),
    )
    if age is None or age < 18 or age > 50:
        raise PlayerDevelopmentError(
            "Player profile has an invalid age."
        )
    return age


def career_stage(age: float) -> str:
    if age <= 22:
        return "early_development"
    if age <= 25:
        return "development"
    if age <= 29:
        return "prime"
    if age <= 32:
        return "late_prime"
    if age <= 35:
        return "veteran_decline"
    return "late_career"


def baseline_age_delta(age: float) -> float:
    """Expected one-season rating movement before player context."""
    # Early-career growth is intentionally positive, but v1.1
    # trims the first release's league-wide optimism while preserving
    # meaningful upside for high-potential prospects.
    anchors = {
        18: 0.60,
        19: 0.57,
        20: 0.53,
        21: 0.47,
        22: 0.38,
        23: 0.28,
        24: 0.18,
        25: 0.09,
        26: 0.03,
        27: 0.00,
        28: -0.05,
        29: -0.13,
        30: -0.25,
        31: -0.42,
        32: -0.62,
        33: -0.86,
        34: -1.10,
        35: -1.36,
        36: -1.64,
        37: -1.90,
        38: -2.15,
        39: -2.38,
        40: -2.60,
    }

    rounded_age = int(math.floor(age))
    if rounded_age <= 18:
        return anchors[18]
    if rounded_age >= 40:
        return anchors[40] - 0.16 * (
            rounded_age - 40
        )
    return anchors[rounded_age]


def potential_growth_rate(age: float) -> float:
    # v1.1 uses a slightly more conservative conversion of potential
    # gap into realized one-year growth. This keeps prospect upside
    # intact without pushing the entire fixed player cohort upward.
    if age <= 20:
        return 0.19
    if age <= 21:
        return 0.165
    if age <= 22:
        return 0.14
    if age <= 23:
        return 0.115
    if age <= 24:
        return 0.085
    if age <= 25:
        return 0.06
    if age <= 26:
        return 0.035
    if age <= 27:
        return 0.015
    return 0.0


def direction_component(
    direction: str,
) -> float:
    normalized = str(
        direction or "Stable"
    ).strip().lower()
    return {
        "rising": 0.28,
        "stable": 0.0,
        "declining": -0.28,
    }.get(normalized, 0.0)


def profile_reliability(
    profile: Mapping[str, Any],
    config: DevelopmentConfig,
) -> float:
    reliability = finite_float(
        profile.get("profile_reliability"),
        0.50,
    )
    assert reliability is not None
    return clamp(
        reliability,
        config.minimum_profile_reliability,
        1.0,
    )


def current_rating(
    profile: Mapping[str, Any],
    field: str,
) -> float:
    value = finite_float(profile.get(field))
    if value is None:
        fallback = finite_float(
            profile.get("overall_rating"),
            67.0,
        )
        assert fallback is not None
        value = fallback
    return clamp(
        value,
        RATING_FLOOR,
        RATING_CEILING,
    )


def potential_component(
    profile: Mapping[str, Any],
    age: float,
) -> float:
    current = current_rating(
        profile,
        "overall_rating",
    )
    potential = current_rating(
        profile,
        "potential_rating",
    )
    gap = max(0.0, potential - current)
    return min(
        1.65,
        gap * potential_growth_rate(age),
    )


def performance_component(
    performance_signal: float,
    config: DevelopmentConfig,
) -> float:
    return clamp(
        performance_signal,
        -1.0,
        1.0,
    ) * config.performance_signal_weight


def uncertainty_sigma(
    reliability: float,
    config: DevelopmentConfig,
) -> float:
    return (
        0.28
        + (1.0 - reliability) * 0.82
    ) * config.random_variance_scale


def projected_stat_factors(
    profile: Mapping[str, Any],
    skill_deltas: Mapping[str, float],
) -> dict[str, float]:
    source = profile.get("stat_factors")
    if not isinstance(source, dict):
        source = {}

    scoring = skill_deltas["scoring_rating"]
    shooting = skill_deltas["shooting_rating"]
    playmaking = skill_deltas[
        "playmaking_rating"
    ]
    rebounding = skill_deltas[
        "rebounding_rating"
    ]
    defense = skill_deltas["defense_rating"]
    efficiency = skill_deltas[
        "efficiency_rating"
    ]
    availability = skill_deltas[
        "availability_rating"
    ]

    change_rates = {
        "points": (
            0.014 * scoring
            + 0.005 * shooting
            + 0.005 * efficiency
        ),
        "rebounds": 0.017 * rebounding,
        "assists": 0.017 * playmaking,
        "steals": 0.013 * defense,
        "blocks": 0.015 * defense,
        "turnovers": (
            -0.007 * playmaking
            - 0.003 * efficiency
        ),
        "fouls": (
            -0.004 * defense
            - 0.003 * availability
        ),
        "three_attempts": (
            0.012 * shooting
            + 0.003 * scoring
        ),
        "free_throw_attempts": (
            0.008 * scoring
            + 0.003 * availability
        ),
    }

    projected: dict[str, float] = {}
    for stat_name, bounds in (
        STAT_FACTOR_BOUNDS.items()
    ):
        current = finite_float(
            source.get(stat_name),
            1.0,
        )
        assert current is not None
        minimum, maximum = bounds
        projected[stat_name] = round(
            clamp(
                current
                * (1.0 + change_rates[stat_name]),
                minimum,
                maximum,
            ),
            4,
        )

    return projected


def project_player_development(
    profile: Mapping[str, Any],
    *,
    source_season: str = "2026-27",
    target_season: str | None = None,
    performance_signal: float = 0.0,
    config: DevelopmentConfig | None = None,
) -> PlayerDevelopmentProjection:
    resolved_config = (
        config or DevelopmentConfig()
    )
    source_season = normalized_season_label(
        source_season
    )
    target_season = (
        normalized_season_label(target_season)
        if target_season is not None
        else next_season_label(source_season)
    )

    player_id = str(
        profile.get("player_id") or ""
    ).strip()
    player_name = str(
        profile.get("player_name") or player_id
    ).strip()
    if not player_id:
        raise PlayerDevelopmentError(
            "Player profile is missing player_id."
        )

    age = profile_age(profile)
    target_age = age + 1.0
    reliability = profile_reliability(
        profile,
        resolved_config,
    )
    seed = stable_player_seed(
        global_seed=resolved_config.random_seed,
        player_id=player_id,
        source_season=source_season,
        target_season=target_season,
    )
    rng = random.Random(seed)

    age_component = baseline_age_delta(age)
    growth_component = potential_component(
        profile,
        age,
    )
    trend_component = direction_component(
        str(
            profile.get(
                "development_direction",
                "Stable",
            )
        )
    )
    observed_component = performance_component(
        performance_signal,
        resolved_config,
    )
    sigma = uncertainty_sigma(
        reliability,
        resolved_config,
    )

    skill_deltas: dict[str, float] = {}
    projected_skills: dict[str, float] = {}

    for field in SKILL_FIELDS:
        random_component = rng.gauss(
            0.0,
            sigma * VOLATILITY[field],
        )
        raw_delta = (
            age_component
            * AGE_SENSITIVITY[field]
            + growth_component
            * GROWTH_SENSITIVITY[field]
            + trend_component
            * DIRECTION_SENSITIVITY[field]
            + observed_component
            * DIRECTION_SENSITIVITY[field]
            + random_component
        )
        delta = clamp(
            raw_delta,
            resolved_config.maximum_one_year_decline,
            resolved_config.maximum_one_year_growth,
        )
        current = current_rating(profile, field)
        projected = clamp(
            current + delta,
            RATING_FLOOR,
            RATING_CEILING,
        )
        skill_deltas[field] = round(
            projected - current,
            3,
        )
        projected_skills[field] = round(
            projected,
            3,
        )

    weighted_delta = sum(
        skill_deltas[field] * weight
        for field, weight in OVERALL_WEIGHTS.items()
    )
    current_overall = current_rating(
        profile,
        "overall_rating",
    )
    potential = current_rating(
        profile,
        "potential_rating",
    )
    future = current_rating(
        profile,
        "future_outlook_rating",
    )

    projected_overall = current_overall + weighted_delta
    if age <= 27:
        projected_overall = min(
            projected_overall,
            max(
                current_overall,
                potential
                + resolved_config.potential_soft_buffer,
            ),
        )
    projected_overall = clamp(
        projected_overall,
        RATING_FLOOR,
        RATING_CEILING,
    )
    overall_delta = round(
        projected_overall - current_overall,
        3,
    )

    return PlayerDevelopmentProjection(
        engine_version=ENGINE_VERSION,
        player_id=player_id,
        player_name=player_name,
        source_season=source_season,
        target_season=target_season,
        source_age=round(age, 3),
        target_age=round(target_age, 3),
        career_stage=career_stage(age),
        deterministic_seed=seed,
        performance_signal=round(
            clamp(performance_signal, -1.0, 1.0),
            4,
        ),
        profile_reliability=round(
            reliability,
            4,
        ),
        current_overall_rating=round(
            current_overall,
            3,
        ),
        projected_overall_rating=round(
            projected_overall,
            3,
        ),
        overall_delta=overall_delta,
        potential_rating=round(
            potential,
            3,
        ),
        future_outlook_rating=round(
            future,
            3,
        ),
        development_direction=str(
            profile.get(
                "development_direction",
                "Stable",
            )
        ).strip()
        or "Stable",
        age_curve_component=round(
            age_component,
            4,
        ),
        potential_growth_component=round(
            growth_component,
            4,
        ),
        direction_component=round(
            trend_component,
            4,
        ),
        performance_component=round(
            observed_component,
            4,
        ),
        skill_deltas=skill_deltas,
        projected_skill_ratings=projected_skills,
        projected_stat_factors=(
            projected_stat_factors(
                profile,
                skill_deltas,
            )
        ),
    )


def apply_projection_to_profile(
    profile: Mapping[str, Any],
    projection: PlayerDevelopmentProjection,
) -> dict[str, Any]:
    updated = copy.deepcopy(dict(profile))
    updated["age_2026_27"] = (
        projection.target_age
    )
    updated["overall_rating"] = (
        projection.projected_overall_rating
    )
    for field, rating in (
        projection.projected_skill_ratings.items()
    ):
        updated[field] = rating

    updated["stat_factors"] = dict(
        projection.projected_stat_factors
    )
    updated["development_last_engine"] = (
        projection.engine_version
    )
    updated["development_last_source_season"] = (
        projection.source_season
    )
    updated["development_last_target_season"] = (
        projection.target_season
    )
    updated["development_last_overall_delta"] = (
        projection.overall_delta
    )
    return updated


def project_all_players(
    profiles: Mapping[str, Mapping[str, Any]],
    *,
    source_season: str = "2026-27",
    target_season: str | None = None,
    performance_signals: Mapping[
        str,
        float,
    ] | None = None,
    config: DevelopmentConfig | None = None,
) -> dict[str, PlayerDevelopmentProjection]:
    signals = performance_signals or {}
    return {
        player_id: project_player_development(
            profile,
            source_season=source_season,
            target_season=target_season,
            performance_signal=float(
                signals.get(player_id, 0.0)
            ),
            config=config,
        )
        for player_id, profile in profiles.items()
    }


def project_player_multi_year(
    profile: Mapping[str, Any],
    *,
    seasons: int,
    source_season: str = "2026-27",
    performance_signals: Mapping[
        str,
        float,
    ] | None = None,
    config: DevelopmentConfig | None = None,
) -> tuple[PlayerDevelopmentProjection, ...]:
    if seasons < 1:
        raise PlayerDevelopmentError(
            "seasons must be at least 1."
        )

    current_profile = copy.deepcopy(
        dict(profile)
    )
    current_season = source_season
    resolved_signals = performance_signals or {}
    projections: list[
        PlayerDevelopmentProjection
    ] = []

    for year_index in range(seasons):
        target = next_season_label(
            current_season
        )
        projection = project_player_development(
            current_profile,
            source_season=current_season,
            target_season=target,
            performance_signal=float(
                resolved_signals.get(
                    target,
                    resolved_signals.get(
                        str(year_index + 1),
                        0.0,
                    ),
                )
            ),
            config=config,
        )
        projections.append(projection)
        current_profile = apply_projection_to_profile(
            current_profile,
            projection,
        )
        current_season = target

    return tuple(projections)


def synthetic_profile(
    *,
    player_id: str,
    player_name: str,
    age: float,
    overall: float,
    potential: float,
    direction: str,
    reliability: float = 0.9,
) -> dict[str, Any]:
    return {
        "player_id": player_id,
        "player_name": player_name,
        "position": "SF/PF",
        "age_2026_27": age,
        "overall_rating": overall,
        "potential_rating": potential,
        "future_outlook_rating": max(
            overall,
            min(potential, overall + 4.0),
        ),
        "development_direction": direction,
        "profile_reliability": reliability,
        "scoring_rating": overall,
        "shooting_rating": overall,
        "playmaking_rating": overall,
        "rebounding_rating": overall,
        "defense_rating": overall,
        "efficiency_rating": overall,
        "availability_rating": overall,
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


def run_self_test() -> dict[str, Any]:
    config = DevelopmentConfig(
        random_seed=774411,
        random_variance_scale=0.0,
    )
    young = synthetic_profile(
        player_id="YOUNG",
        player_name="Young Prospect",
        age=21,
        overall=74.0,
        potential=90.0,
        direction="Rising",
    )
    prime = synthetic_profile(
        player_id="PRIME",
        player_name="Prime Player",
        age=27,
        overall=84.0,
        potential=86.0,
        direction="Stable",
    )
    old = synthetic_profile(
        player_id="OLD",
        player_name="Older Star",
        age=37,
        overall=90.0,
        potential=90.0,
        direction="Declining",
    )

    young_one = project_player_development(
        young,
        config=config,
    )
    young_two = project_player_development(
        young,
        config=config,
    )
    prime_projection = (
        project_player_development(
            prime,
            config=config,
        )
    )
    old_projection = (
        project_player_development(
            old,
            config=config,
        )
    )
    old_five_year = project_player_multi_year(
        old,
        seasons=5,
        config=config,
    )

    checks = {
        "engine_is_deterministic": (
            young_one == young_two
        ),
        "young_high_potential_player_improves": (
            young_one.overall_delta > 0.75
        ),
        "prime_stable_player_remains_near_flat": (
            abs(prime_projection.overall_delta)
            <= 0.25
        ),
        "older_declining_player_regresses": (
            old_projection.overall_delta < -1.0
        ),
        "older_shooting_ages_better_than_defense": (
            old_projection.skill_deltas[
                "shooting_rating"
            ]
            > old_projection.skill_deltas[
                "defense_rating"
            ]
        ),
        "older_playmaking_ages_better_than_availability": (
            old_projection.skill_deltas[
                "playmaking_rating"
            ]
            > old_projection.skill_deltas[
                "availability_rating"
            ]
        ),
        "young_projection_respects_potential_buffer": (
            young_one.projected_overall_rating
            <= young_one.potential_rating
            + config.potential_soft_buffer
            + 1e-9
        ),
        "stat_factors_change_with_skills": (
            young_one.projected_stat_factors[
                "points"
            ]
            > 1.0
            and old_projection.projected_stat_factors[
                "blocks"
            ]
            < 1.0
        ),
        "multi_year_projection_advances_age": (
            old_five_year[-1].target_age
            == old["age_2026_27"] + 5.0
        ),
        "multi_year_old_player_keeps_declining": (
            old_five_year[-1]
            .projected_overall_rating
            < old_projection.projected_overall_rating
        ),
    }
    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]

    report = {
        "script": ENGINE_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "examples": {
            "young": asdict(young_one),
            "prime": asdict(
                prime_projection
            ),
            "old": asdict(old_projection),
            "old_five_year": [
                asdict(item)
                for item in old_five_year
            ],
        },
        "passed": not failed,
    }

    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )
    SELF_TEST_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
        ),
        encoding="utf-8",
    )

    if failed:
        raise AssertionError(
            "Player Development Engine self-test "
            "failed: "
            + ", ".join(failed)
        )

    return report


def run_demo() -> dict[str, Any]:
    profiles = load_player_stat_profiles()
    names = (
        "Victor Wembanyama",
        "Nikola Jokić",
        "Stephen Curry",
        "Trae Young",
        "Jalen Duren",
    )
    output: dict[str, Any] = {
        "script": ENGINE_VERSION,
        "players": {},
    }

    for name in names:
        player_id = (
            player_id_by_name(name)
            or (
                player_id_by_name("Nikola Jokic")
                if name == "Nikola Jokić"
                else ""
            )
        )
        if not player_id:
            continue
        projection = project_player_development(
            profiles[player_id]
        )
        output["players"][name] = asdict(
            projection
        )

    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )
    DEMO_REPORT.write_text(
        json.dumps(
            output,
            indent=2,
        ),
        encoding="utf-8",
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
    )
    args = parser.parse_args()

    if args.self_test:
        report = run_self_test()
        print(json.dumps(report, indent=2))
        print(
            "\nPLAYER DEVELOPMENT ENGINE V1 "
            "SELF-TEST PASSED"
        )
        return 0

    report = run_demo()
    print(json.dumps(report, indent=2))
    print(
        "\nPLAYER DEVELOPMENT ENGINE V1 "
        "DEMO PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())