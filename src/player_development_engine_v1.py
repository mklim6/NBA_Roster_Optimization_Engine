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


ENGINE_VERSION = "player-development-engine-v2.0-2026-08-11"
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
    random_variance_scale: float = 0.85
    performance_signal_weight: float = 1.15
    maximum_one_year_growth: float = 9.0
    maximum_one_year_decline: float = -9.0
    potential_soft_buffer: float = 0.75
    minimum_profile_reliability: float = 0.10
    opportunity_weight: float = 1.85
    draft_pedigree_weight: float = 1.0
    early_career_variance_boost: float = 1.35
    veteran_variance_boost: float = 1.18



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
    opportunity_score: float
    opportunity_component: float
    draft_pedigree_component: float
    breakout_component: float
    years_of_service: int
    games_played: int
    minutes_per_game: float
    total_minutes: float
    annual_growth_ceiling: float
    annual_decline_floor: float
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
    """Expected one-season movement before player-specific context."""
    anchors = {
        18: 0.90,
        19: 0.85,
        20: 0.75,
        21: 0.60,
        22: 0.45,
        23: 0.30,
        24: 0.15,
        25: 0.05,
        26: 0.00,
        27: 0.00,
        28: -0.05,
        29: -0.15,
        30: -0.35,
        31: -0.65,
        32: -1.00,
        33: -1.45,
        34: -2.05,
        35: -2.75,
        36: -3.50,
        37: -4.25,
        38: -4.90,
        39: -5.40,
        40: -5.80,
    }
    rounded_age = int(math.floor(age))
    if rounded_age <= 18:
        return anchors[18]
    if rounded_age >= 40:
        return anchors[40] - 0.30 * (rounded_age - 40)
    return anchors[rounded_age]




def potential_growth_rate(age: float) -> float:
    if age <= 20:
        return 0.30
    if age <= 21:
        return 0.27
    if age <= 22:
        return 0.24
    if age <= 23:
        return 0.20
    if age <= 24:
        return 0.15
    if age <= 25:
        return 0.10
    if age <= 26:
        return 0.06
    if age <= 27:
        return 0.03
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
    current = current_rating(profile, "overall_rating")
    potential = current_rating(profile, "potential_rating")
    gap = max(0.0, potential - current)
    return min(4.80, gap * potential_growth_rate(age))



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
    *,
    age: float | None = None,
) -> float:
    sigma = (
        0.32 + (1.0 - reliability) * 1.05
    ) * config.random_variance_scale
    if age is not None:
        if age <= 22:
            sigma *= config.early_career_variance_boost
        elif age <= 24:
            sigma *= 1.15
        elif age >= 34:
            sigma *= config.veteran_variance_boost
    return sigma




def profile_years_of_service(
    profile: Mapping[str, Any],
    source_season: str,
) -> int:
    direct = finite_float(profile.get("years_of_service"))

    # Generated draft prospects carry durable draft-year metadata. Derive
    # completed NBA seasons from that clock so their rookie-development
    # window advances even if an older checkpoint still stores service=0.
    draft_year = finite_float(profile.get("draft_year"))
    generated = bool(profile.get("generated_prospect", False))
    derived_from_draft: int | None = None
    if draft_year is not None:
        try:
            source_start = int(str(source_season).split("-", 1)[0])
        except (TypeError, ValueError):
            source_start = int(draft_year)
        derived_from_draft = max(
            0,
            source_start - int(draft_year) + 1,
        )

    if direct is not None and direct >= 0:
        resolved = int(round(direct))
        if generated and derived_from_draft is not None:
            return max(resolved, derived_from_draft)
        return resolved

    history_count = finite_float(
        profile.get("development_history_count")
    )
    if history_count is not None and history_count >= 0:
        resolved = int(round(history_count))
        if generated and derived_from_draft is not None:
            return max(resolved, derived_from_draft)
        return resolved

    if derived_from_draft is not None:
        return derived_from_draft

    return 99


def exposure_metrics(
    profile: Mapping[str, Any],
) -> tuple[int, float, float, float]:
    games = max(0, int(round(finite_float(
        profile.get("games_played"),
        0.0,
    ) or 0.0)))
    total_minutes = max(
        0.0,
        finite_float(profile.get("total_minutes"), 0.0) or 0.0,
    )
    mpg = finite_float(profile.get("minutes_per_game"))
    if mpg is None:
        mpg = total_minutes / games if games > 0 else 0.0
    mpg = max(0.0, mpg)

    games_score = clamp(games / 72.0, 0.0, 1.0)
    mpg_score = clamp((mpg - 4.0) / 26.0, 0.0, 1.0)
    minutes_score = clamp(total_minutes / 1800.0, 0.0, 1.0)
    score = (
        0.30 * games_score
        + 0.50 * mpg_score
        + 0.20 * minutes_score
    )
    return games, total_minutes, mpg, clamp(score, 0.0, 1.0)


def opportunity_component(
    profile: Mapping[str, Any],
    *,
    age: float,
    years_of_service: int,
    config: DevelopmentConfig,
) -> tuple[float, float]:
    _, _, _, score = exposure_metrics(profile)
    if age > 24 or years_of_service > 3:
        return score, 0.0

    experience_multiplier = {
        0: 1.00,
        1: 1.00,
        2: 0.85,
        3: 0.55,
    }.get(years_of_service, 0.0)
    return (
        score,
        score
        * config.opportunity_weight
        * experience_multiplier,
    )


def draft_pedigree_component(
    profile: Mapping[str, Any],
    *,
    years_of_service: int,
    config: DevelopmentConfig,
) -> float:
    if years_of_service > 3:
        return 0.0

    pick = finite_float(profile.get("draft_pick"))
    round_number = finite_float(profile.get("draft_round"))

    if pick is not None:
        if pick <= 5:
            base = 1.15
        elif pick <= 14:
            base = 0.90
        elif pick <= 30:
            base = 0.55
        elif pick <= 45:
            base = 0.20
        else:
            base = 0.05
    elif round_number is not None:
        base = 0.45 if round_number <= 1 else 0.08
    else:
        base = 0.0

    decay = {
        0: 1.00,
        1: 1.00,
        2: 0.65,
        3: 0.30,
    }.get(years_of_service, 0.0)
    return base * decay * config.draft_pedigree_weight


def annual_delta_limits(
    age: float,
    config: DevelopmentConfig,
) -> tuple[float, float]:
    if age <= 21:
        low, high = -3.0, 9.0
    elif age <= 24:
        low, high = -3.5, 8.0
    elif age <= 27:
        low, high = -4.0, 5.0
    elif age <= 30:
        low, high = -4.5, 3.0
    elif age <= 33:
        low, high = -6.0, 2.0
    elif age <= 35:
        low, high = -7.0, 1.5
    else:
        low, high = -9.0, 1.0

    return (
        max(low, config.maximum_one_year_decline),
        min(high, config.maximum_one_year_growth),
    )


def development_outcome_component(
    profile: Mapping[str, Any],
    *,
    age: float,
    years_of_service: int,
    opportunity_score: float,
    rng: random.Random,
) -> float:
    current = current_rating(profile, "overall_rating")
    potential = current_rating(profile, "potential_rating")
    gap = max(0.0, potential - current)

    if age <= 23 and years_of_service <= 3:
        gap_score = clamp((gap - 5.0) / 15.0, 0.0, 1.0)
        pedigree = draft_pedigree_component(
            profile,
            years_of_service=years_of_service,
            config=DevelopmentConfig(
                draft_pedigree_weight=1.0,
            ),
        )
        pedigree_score = clamp(pedigree / 1.15, 0.0, 1.0)

        boom_chance = (
            0.05
            + 0.13 * gap_score
            + 0.07 * opportunity_score
            + 0.04 * pedigree_score
        )
        bust_chance = (
            0.05
            + 0.08 * (1.0 - opportunity_score)
            + 0.03 * (1.0 - gap_score)
        )
        roll = rng.random()

        if roll < boom_chance:
            return (
                1.00
                + rng.random()
                * (1.50 + 1.40 * gap_score)
            )
        if roll > 1.0 - bust_chance:
            return -(
                0.75
                + rng.random()
                * (1.25 + 0.80 * (1.0 - opportunity_score))
            )

    if age >= 33:
        current_overall = current_rating(profile, "overall_rating")
        availability = current_rating(
            profile,
            "availability_rating",
        )
        elite_resilience = bool(
            current_overall >= 88.0
            and availability >= 84.0
        )
        resilience_chance = 0.07 if elite_resilience else 0.015
        decline_chance = min(
            0.62,
            0.12 + 0.055 * max(0.0, age - 33.0),
        )
        roll = rng.random()

        if roll < resilience_chance:
            return 0.65 + 1.35 * rng.random()
        if roll < resilience_chance + decline_chance:
            severity = (
                0.80
                + rng.random()
                * (1.40 + 0.24 * max(0.0, age - 33.0))
            )
            return -severity

    return 0.0

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
    development_modifier: float = 0.0,
) -> PlayerDevelopmentProjection:
    resolved_config = config or DevelopmentConfig()
    source_season = normalized_season_label(source_season)
    target_season = (
        normalized_season_label(target_season)
        if target_season is not None
        else next_season_label(source_season)
    )

    player_id = str(profile.get("player_id") or "").strip()
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

    years_of_service = profile_years_of_service(
        profile,
        source_season,
    )
    games, total_minutes, mpg, exposure_score = (
        exposure_metrics(profile)
    )
    exposure_score, exposure_component = (
        opportunity_component(
            profile,
            age=age,
            years_of_service=years_of_service,
            config=resolved_config,
        )
    )
    pedigree_component = draft_pedigree_component(
        profile,
        years_of_service=years_of_service,
        config=resolved_config,
    )

    age_component = baseline_age_delta(age)
    growth_component = potential_component(profile, age)
    if age <= 24 and years_of_service <= 3:
        # Practice and natural maturation still matter when a prospect is
        # buried, but real NBA reps determine how much of the ceiling is
        # converted into immediate year-over-year growth.
        growth_component *= (
            0.55 + 0.45 * exposure_score
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
    breakout_component = development_outcome_component(
        profile,
        age=age,
        years_of_service=years_of_service,
        opportunity_score=exposure_score,
        rng=rng,
    )
    lower_limit, upper_limit = annual_delta_limits(
        age,
        resolved_config,
    )
    sigma = uncertainty_sigma(
        reliability,
        resolved_config,
        age=age,
    )
    # FRANCHISE_STAFF_FOUNDATION_V1
    # A neutral/default value preserves every existing caller and validator.
    # Live Franchise Mode supplies a small organization-level modifier derived
    # from the head coach and player-development coach.
    staff_development_component = clamp(
        float(development_modifier),
        -0.45,
        0.45,
    )

    skill_deltas: dict[str, float] = {}
    projected_skills: dict[str, float] = {}

    for field in SKILL_FIELDS:
        random_component = rng.gauss(
            0.0,
            sigma * VOLATILITY[field],
        )
        raw_delta = (
            age_component * AGE_SENSITIVITY[field]
            + growth_component * GROWTH_SENSITIVITY[field]
            + trend_component * DIRECTION_SENSITIVITY[field]
            + observed_component * DIRECTION_SENSITIVITY[field]
            + exposure_component * GROWTH_SENSITIVITY[field]
            + pedigree_component * GROWTH_SENSITIVITY[field]
            + staff_development_component * GROWTH_SENSITIVITY[field]
            + breakout_component
            * (0.78 + 0.22 * GROWTH_SENSITIVITY[field])
            + random_component
        )
        delta = clamp(
            raw_delta,
            lower_limit,
            upper_limit,
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
    weighted_delta = clamp(
        weighted_delta,
        lower_limit,
        upper_limit,
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
        profile_reliability=round(reliability, 4),
        current_overall_rating=round(
            current_overall,
            3,
        ),
        projected_overall_rating=round(
            projected_overall,
            3,
        ),
        overall_delta=overall_delta,
        potential_rating=round(potential, 3),
        future_outlook_rating=round(future, 3),
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
        opportunity_score=round(
            exposure_score,
            4,
        ),
        opportunity_component=round(
            exposure_component,
            4,
        ),
        draft_pedigree_component=round(
            pedigree_component,
            4,
        ),
        breakout_component=round(
            breakout_component,
            4,
        ),
        years_of_service=years_of_service,
        games_played=games,
        minutes_per_game=round(mpg, 3),
        total_minutes=round(total_minutes, 3),
        annual_growth_ceiling=round(
            upper_limit,
            3,
        ),
        annual_decline_floor=round(
            lower_limit,
            3,
        ),
        skill_deltas=skill_deltas,
        projected_skill_ratings=projected_skills,
        projected_stat_factors=projected_stat_factors(
            profile,
            skill_deltas,
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
    games_played: int = 0,
    minutes_per_game: float = 0.0,
    years_of_service: int = 99,
    draft_pick: int | None = None,
    draft_round: int | None = None,
) -> dict[str, Any]:
    total_minutes = (
        float(games_played)
        * float(minutes_per_game)
    )
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
        "games_played": games_played,
        "minutes_per_game": minutes_per_game,
        "total_minutes": total_minutes,
        "years_of_service": years_of_service,
        "draft_pick": draft_pick,
        "draft_round": draft_round,
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
    )

    high_usage = synthetic_profile(
        player_id="UPSIDE-COMP",
        player_name="High-Minutes Lottery Prospect",
        age=20,
        overall=74.0,
        potential=92.0,
        direction="Rising",
        games_played=76,
        minutes_per_game=30.0,
        years_of_service=1,
        draft_pick=5,
        draft_round=1,
    )
    low_usage = dict(high_usage)
    low_usage["player_name"] = "Low-Minutes Lottery Prospect"
    low_usage["games_played"] = 18
    low_usage["minutes_per_game"] = 6.0
    low_usage["total_minutes"] = 108.0

    lottery = dict(high_usage)
    lottery["player_id"] = "PEDIGREE-COMP"
    lottery["player_name"] = "Lottery Pick"
    lottery["games_played"] = 60
    lottery["minutes_per_game"] = 20.0
    lottery["total_minutes"] = 1200.0
    late_second = dict(lottery)
    late_second["player_name"] = "Late Second"
    late_second["draft_pick"] = 55
    late_second["draft_round"] = 2

    prime = synthetic_profile(
        player_id="PRIME",
        player_name="Prime Player",
        age=28,
        overall=84.0,
        potential=86.0,
        direction="Stable",
        games_played=76,
        minutes_per_game=32.0,
    )
    old = synthetic_profile(
        player_id="OLD",
        player_name="Older Star",
        age=36,
        overall=88.0,
        potential=88.0,
        direction="Stable",
        games_played=72,
        minutes_per_game=31.0,
    )

    high_projection = project_player_development(
        high_usage,
        performance_signal=0.65,
        config=config,
    )
    high_projection_repeat = project_player_development(
        high_usage,
        performance_signal=0.65,
        config=config,
    )
    low_projection = project_player_development(
        low_usage,
        performance_signal=0.65,
        config=config,
    )
    lottery_projection = project_player_development(
        lottery,
        performance_signal=0.0,
        config=config,
    )
    late_second_projection = project_player_development(
        late_second,
        performance_signal=0.0,
        config=config,
    )
    prime_projection = project_player_development(
        prime,
        config=config,
    )
    old_projection = project_player_development(
        old,
        config=config,
    )

    checks = {
        "engine_is_deterministic": (
            high_projection
            == high_projection_repeat
        ),
        "young_ceiling_allows_plus_nine": (
            high_projection.annual_growth_ceiling
            == 9.0
        ),
        "high_potential_lottery_player_can_jump_big": (
            high_projection.overall_delta >= 5.0
        ),
        "playing_time_materially_boosts_early_growth": (
            high_projection.overall_delta
            >= low_projection.overall_delta + 1.0
        ),
        "first_round_pedigree_matters_early": (
            lottery_projection.overall_delta
            > late_second_projection.overall_delta
        ),
        "prime_player_does_not_receive_rookie_exposure_bonus": (
            prime_projection.opportunity_component == 0.0
        ),
        "older_player_declines_clearly": (
            old_projection.overall_delta <= -2.0
        ),
        "older_shooting_ages_better_than_defense": (
            old_projection.skill_deltas[
                "shooting_rating"
            ]
            > old_projection.skill_deltas[
                "defense_rating"
            ]
        ),
        "potential_ceiling_is_respected": (
            high_projection.projected_overall_rating
            <= high_projection.potential_rating
            + config.potential_soft_buffer
            + 1e-9
        ),
        "one_year_limits_are_respected": (
            high_projection.overall_delta <= 9.0
            and old_projection.overall_delta >= -9.0
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
            "high_usage_lottery": asdict(
                high_projection
            ),
            "low_usage_lottery": asdict(
                low_projection
            ),
            "lottery_pedigree": asdict(
                lottery_projection
            ),
            "late_second_pedigree": asdict(
                late_second_projection
            ),
            "prime": asdict(prime_projection),
            "old": asdict(old_projection),
        },
        "passed": not failed,
    }

    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )
    SELF_TEST_REPORT.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    if failed:
        raise AssertionError(
            "Player Development Engine V2 self-test "
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
            "\nPLAYER DEVELOPMENT ENGINE V2 "
            "SELF-TEST PASSED"
        )
        return 0

    report = run_demo()
    print(json.dumps(report, indent=2))
    print(
        "\nPLAYER DEVELOPMENT ENGINE V2 "
        "DEMO PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
