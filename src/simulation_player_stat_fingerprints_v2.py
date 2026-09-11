from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping


FINGERPRINT_VERSION = "player-statistical-fingerprint-v2.1-2026-09-09"


POSITION_RATE_FALLBACKS: dict[str, dict[str, float]] = {
    "PG": {
        "rebounds_per_36": 4.1,
        "assists_per_36": 7.1,
        "steals_per_36": 1.25,
        "blocks_per_36": 0.28,
        "turnovers_per_36": 2.8,
        "fouls_per_36": 2.4,
        "three_attempts_per_36": 7.4,
        "free_throw_attempts_per_36": 4.6,
    },
    "SG": {
        "rebounds_per_36": 4.7,
        "assists_per_36": 4.5,
        "steals_per_36": 1.15,
        "blocks_per_36": 0.42,
        "turnovers_per_36": 2.2,
        "fouls_per_36": 2.6,
        "three_attempts_per_36": 7.1,
        "free_throw_attempts_per_36": 4.1,
    },
    "SF": {
        "rebounds_per_36": 6.1,
        "assists_per_36": 3.6,
        "steals_per_36": 1.05,
        "blocks_per_36": 0.62,
        "turnovers_per_36": 2.0,
        "fouls_per_36": 2.8,
        "three_attempts_per_36": 6.0,
        "free_throw_attempts_per_36": 4.0,
    },
    "PF": {
        "rebounds_per_36": 8.7,
        "assists_per_36": 2.8,
        "steals_per_36": 0.90,
        "blocks_per_36": 1.05,
        "turnovers_per_36": 1.9,
        "fouls_per_36": 3.2,
        "three_attempts_per_36": 4.5,
        "free_throw_attempts_per_36": 4.2,
    },
    "C": {
        "rebounds_per_36": 10.9,
        "assists_per_36": 2.4,
        "steals_per_36": 0.78,
        "blocks_per_36": 1.45,
        "turnovers_per_36": 2.0,
        "fouls_per_36": 3.5,
        "three_attempts_per_36": 2.5,
        "free_throw_attempts_per_36": 4.8,
    },
}

RATE_LIMITS: dict[str, tuple[float, float]] = {
    "rebounds_per_36": (0.3, 18.0),
    "assists_per_36": (0.2, 14.5),
    "steals_per_36": (0.1, 3.2),
    "blocks_per_36": (0.0, 5.2),
    "turnovers_per_36": (0.2, 6.5),
    "fouls_per_36": (0.5, 5.4),
    "three_attempts_per_36": (0.0, 15.5),
    "free_throw_attempts_per_36": (0.0, 14.5),
}

SECONDARY_RATE_FIELD_BY_STAT = {
    "rebounds": "rebounds_per_36",
    "assists": "assists_per_36",
    "steals": "steals_per_36",
    "blocks": "blocks_per_36",
    "turnovers": "turnovers_per_36",
    "fouls": "fouls_per_36",
}


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def finite_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not math.isfinite(parsed):
        return float(default)
    return parsed


def position_tokens(position: str) -> tuple[str, ...]:
    tokens = tuple(
        token
        for token in str(position or "").upper().split("/")
        if token in POSITION_RATE_FALLBACKS
    )
    return tokens or ("SF",)


def position_fallback(position: str, field_name: str) -> float:
    tokens = position_tokens(position)
    values = [
        POSITION_RATE_FALLBACKS[token][field_name]
        for token in tokens
    ]
    return sum(values) / len(values)


def blended_rate(
    baseline: Mapping[str, Any],
    *,
    position: str,
    field_name: str,
    reliability: float,
) -> float:
    fallback = position_fallback(position, field_name)
    raw = finite_float(baseline.get(field_name), 0.0)
    if raw <= 0.0:
        raw = fallback
        data_weight = 0.0
    else:
        data_weight = 0.72 + 0.23 * clamp(reliability, 0.0, 1.0)
    value = data_weight * raw + (1.0 - data_weight) * fallback
    minimum, maximum = RATE_LIMITS[field_name]
    return clamp(value, minimum, maximum)


def skill_rating(player: Any, field_name: str) -> float:
    ratings = getattr(player, "skill_ratings", {})
    if not isinstance(ratings, Mapping):
        ratings = {}
    overall = finite_float(getattr(player, "overall_rating", 77.0), 77.0)
    return clamp(
        finite_float(ratings.get(field_name), overall),
        45.0,
        99.0,
    )


def live_shooting_targets(
    player: Any,
    *,
    shooting: float,
    scoring: float,
    efficiency: float,
) -> dict[str, float] | None:
    """Apply sourced live-start shooting targets without freezing development.

    Live-start supplemental players retain sample-adjusted percentage targets
    and the skill ratings present when those targets were installed. Later
    development changes move the percentages from that anchored starting point.
    Players without this optional evidence continue through the standard model.
    """
    evidence = getattr(player, "live_reference_shooting_evidence", {})
    if not isinstance(evidence, Mapping):
        return None
    targets = evidence.get("simulation_targets", {})
    anchor = evidence.get("development_skill_anchor", {})
    required_targets = {
        "three_point_percentage",
        "two_point_percentage",
        "free_throw_percentage",
    }
    required_anchor = {
        "shooting_rating",
        "scoring_rating",
        "efficiency_rating",
    }
    if (
        not isinstance(targets, Mapping)
        or not isinstance(anchor, Mapping)
        or set(targets) != required_targets
        or set(anchor) != required_anchor
    ):
        return None
    anchor_shooting = finite_float(anchor.get("shooting_rating"), shooting)
    anchor_scoring = finite_float(anchor.get("scoring_rating"), scoring)
    anchor_efficiency = finite_float(anchor.get("efficiency_rating"), efficiency)
    return {
        "three_point_percentage": clamp(
            finite_float(targets.get("three_point_percentage"), 0.345)
            + (shooting - anchor_shooting) * 0.00355
            + (efficiency - anchor_efficiency) * 0.00055,
            0.255,
            0.455,
        ),
        "two_point_percentage": clamp(
            finite_float(targets.get("two_point_percentage"), 0.515)
            + (efficiency - anchor_efficiency) * 0.0033
            + (scoring - anchor_scoring) * 0.0012,
            0.43,
            0.70,
        ),
        "free_throw_percentage": clamp(
            finite_float(targets.get("free_throw_percentage"), 0.755)
            + (shooting - anchor_shooting) * 0.0062,
            0.52,
            0.95,
        ),
    }


def derived_free_throw_attempts_per_36(
    player: Any,
    baseline: Mapping[str, Any],
    *,
    position: str,
    reliability: float,
) -> float:
    """Resolve a player-specific foul-drawing prior.

    The installed source profiles currently expose a reliable historical
    3PA/36 field much more often than FTA/36. When FTA/36 is absent, do not
    collapse every player onto the narrow position fallback. Instead derive
    a stable prior from the player's persistent scoring volume and the
    existing free-throw-attempt stat factor, then lightly shrink it toward
    the position prior. This keeps the model data-driven without hardcoding
    individual player names.
    """
    raw = finite_float(baseline.get("free_throw_attempts_per_36"), 0.0)
    if raw > 0.0:
        return blended_rate(
            baseline,
            position=position,
            field_name="free_throw_attempts_per_36",
            reliability=reliability,
        )

    fallback = position_fallback(position, "free_throw_attempts_per_36")
    overall = finite_float(getattr(player, "overall_rating", 77.0), 77.0)
    points_per_36 = finite_float(baseline.get("points_per_36"), 0.0)
    if points_per_36 <= 0.0:
        points_per_36 = 12.0 + max(0.0, overall - 70.0) * 0.62
    points_per_36 = clamp(points_per_36, 4.0, 38.0)

    scoring = skill_rating(player, "scoring_rating")
    high_usage = max(0.0, points_per_36 - 18.0)
    usage_prior = (
        1.20
        + 0.14 * points_per_36
        + 0.012 * high_usage * high_usage
        + 0.045 * (scoring - 75.0)
    )

    stat_factors = getattr(player, "stat_factors", {})
    if not isinstance(stat_factors, Mapping):
        stat_factors = {}
    raw_factor = finite_float(stat_factors.get("free_throw_attempts"), 1.0)
    if raw_factor <= 0.0:
        raw_factor = 1.0
    tendency = clamp(1.0 + 0.80 * (raw_factor - 1.0), 0.55, 1.80)

    # Keep a small amount of position shrinkage for sparse profiles, while
    # allowing high-usage and low-usage players to separate meaningfully.
    derived = (0.15 * fallback + 0.85 * usage_prior) * tendency
    minimum, maximum = RATE_LIMITS["free_throw_attempts_per_36"]
    return clamp(derived, minimum, maximum)


@dataclass(frozen=True)
class PlayerStatFingerprint:
    player_id: str
    position: str
    reliability: float
    rebounds_per_36: float
    assists_per_36: float
    steals_per_36: float
    blocks_per_36: float
    turnovers_per_36: float
    fouls_per_36: float
    three_attempts_per_36: float
    free_throw_attempts_per_36: float
    three_point_percentage: float
    two_point_percentage: float
    free_throw_percentage: float

    def secondary_rate(self, stat_name: str) -> float:
        field_name = SECONDARY_RATE_FIELD_BY_STAT[stat_name]
        return float(getattr(self, field_name))


def build_player_stat_fingerprint(player: Any) -> PlayerStatFingerprint:
    baseline = getattr(player, "baseline_per_36", {})
    if not isinstance(baseline, Mapping):
        baseline = {}

    reliability = clamp(
        finite_float(getattr(player, "profile_reliability", 0.5), 0.5),
        0.0,
        1.0,
    )
    position = str(getattr(player, "position", "SF") or "SF")
    player_id = str(getattr(player, "player_id", ""))

    shooting = skill_rating(player, "shooting_rating")
    scoring = skill_rating(player, "scoring_rating")
    efficiency = skill_rating(player, "efficiency_rating")
    tokens = set(position_tokens(position))

    guard_bonus = 0.004 if {"PG", "SG"}.intersection(tokens) else 0.0
    center_three_penalty = -0.006 if "C" in tokens else 0.0
    big_two_bonus = (
        0.022 if "C" in tokens else 0.012 if "PF" in tokens else 0.0
    )
    center_ft_penalty = -0.018 if "C" in tokens else 0.0

    live_targets = live_shooting_targets(
        player,
        shooting=shooting,
        scoring=scoring,
        efficiency=efficiency,
    )
    if live_targets is not None:
        three_pct = live_targets["three_point_percentage"]
        two_pct = live_targets["two_point_percentage"]
        free_throw_pct = live_targets["free_throw_percentage"]
    else:
        # Use persistent player skill ratings, not overall rating alone. This
        # intentionally creates a wider shooting-skill distribution than V1.
        three_pct = clamp(
            0.345
            + (shooting - 75.0) * 0.00355
            + (efficiency - 75.0) * 0.00055
            + guard_bonus
            + center_three_penalty,
            0.255,
            0.455,
        )
        two_pct = clamp(
            0.515
            + (efficiency - 75.0) * 0.0033
            + (scoring - 75.0) * 0.0012
            + big_two_bonus,
            0.43,
            0.70,
        )
        free_throw_pct = clamp(
            0.755
            + (shooting - 75.0) * 0.0062
            + (0.010 if "PG" in tokens else 0.0)
            + center_ft_penalty,
            0.52,
            0.95,
        )

    return PlayerStatFingerprint(
        player_id=player_id,
        position=position,
        reliability=round(reliability, 4),
        rebounds_per_36=round(
            blended_rate(
                baseline,
                position=position,
                field_name="rebounds_per_36",
                reliability=reliability,
            ),
            4,
        ),
        assists_per_36=round(
            blended_rate(
                baseline,
                position=position,
                field_name="assists_per_36",
                reliability=reliability,
            ),
            4,
        ),
        steals_per_36=round(
            blended_rate(
                baseline,
                position=position,
                field_name="steals_per_36",
                reliability=reliability,
            ),
            4,
        ),
        blocks_per_36=round(
            blended_rate(
                baseline,
                position=position,
                field_name="blocks_per_36",
                reliability=reliability,
            ),
            4,
        ),
        turnovers_per_36=round(
            blended_rate(
                baseline,
                position=position,
                field_name="turnovers_per_36",
                reliability=reliability,
            ),
            4,
        ),
        fouls_per_36=round(
            blended_rate(
                baseline,
                position=position,
                field_name="fouls_per_36",
                reliability=reliability,
            ),
            4,
        ),
        three_attempts_per_36=round(
            blended_rate(
                baseline,
                position=position,
                field_name="three_attempts_per_36",
                reliability=reliability,
            ),
            4,
        ),
        free_throw_attempts_per_36=round(
            derived_free_throw_attempts_per_36(
                player,
                baseline,
                position=position,
                reliability=reliability,
            ),
            4,
        ),
        three_point_percentage=round(three_pct, 5),
        two_point_percentage=round(two_pct, 5),
        free_throw_percentage=round(free_throw_pct, 5),
    )


def expected_secondary_count(
    fingerprint: PlayerStatFingerprint,
    stat_name: str,
    minutes: float,
) -> float:
    rate = fingerprint.secondary_rate(stat_name)
    return max(0.0, rate * max(0.0, float(minutes)) / 36.0)


def fingerprint_summary(player: Any) -> dict[str, Any]:
    fp = build_player_stat_fingerprint(player)
    return {
        "version": FINGERPRINT_VERSION,
        "player_id": fp.player_id,
        "position": fp.position,
        "reliability": fp.reliability,
        "3PA_per_36": fp.three_attempts_per_36,
        "FTA_per_36": fp.free_throw_attempts_per_36,
        "REB_per_36": fp.rebounds_per_36,
        "AST_per_36": fp.assists_per_36,
        "STL_per_36": fp.steals_per_36,
        "BLK_per_36": fp.blocks_per_36,
        "TO_per_36": fp.turnovers_per_36,
        "PF_per_36": fp.fouls_per_36,
        "3P_target": round(100.0 * fp.three_point_percentage, 1),
        "2P_target": round(100.0 * fp.two_point_percentage, 1),
        "FT_target": round(100.0 * fp.free_throw_percentage, 1),
    }
