from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


COACHING_ROLE_ROTATION_VERSION = (
    "franchise-coaching-role-rotation-v1-2026-09-30"
)

ROLE_PRIMARY_CREATOR = "primary_creator"
ROLE_SECONDARY_CREATOR = "secondary_creator"
ROLE_BALL_HANDLER = "ball_handler"
ROLE_SPACER = "spacer"
ROLE_RIM_PRESSURE = "rim_pressure"
ROLE_REBOUNDER = "rebounder"
ROLE_RIM_PROTECTOR = "rim_protector"
ROLE_POA_DEFENDER = "point_of_attack_defender"
ROLE_WING_STOPPER = "wing_stopper"
ROLE_INTERIOR_DEFENDER = "interior_defender"
ROLE_CONNECTOR = "connector"

ROLE_LABELS: dict[str, str] = {
    ROLE_PRIMARY_CREATOR: "primary creation",
    ROLE_SECONDARY_CREATOR: "secondary creation",
    ROLE_BALL_HANDLER: "ball handling",
    ROLE_SPACER: "floor spacing",
    ROLE_RIM_PRESSURE: "rim pressure",
    ROLE_REBOUNDER: "rebounding",
    ROLE_RIM_PROTECTOR: "rim protection",
    ROLE_POA_DEFENDER: "point-of-attack defense",
    ROLE_WING_STOPPER: "wing defense",
    ROLE_INTERIOR_DEFENDER: "interior defense",
    ROLE_CONNECTOR: "connective playmaking",
}

ROLE_KEYS = tuple(ROLE_LABELS)


@dataclass(frozen=True)
class FunctionalRoleProfile:
    version: str
    player_id: str
    player_name: str
    position: str
    scores: dict[str, float]


@dataclass(frozen=True)
class ReplacementDecision:
    missing_player_id: str
    missing_player_name: str
    replacement_player_id: str
    replacement_player_name: str
    combined_score: float
    role_fit: float
    position_fit: float
    quality: float
    primary_missing_roles: tuple[str, ...]
    explanation: str


@dataclass(frozen=True)
class CoachingAdjustmentReport:
    version: str
    team: str
    missing_starter_ids: tuple[str, ...]
    missing_starter_names: tuple[str, ...]
    role_deficits: tuple[tuple[str, float], ...]
    replacement_decisions: tuple[ReplacementDecision, ...]
    summary: str


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed if math.isfinite(parsed) else float(default)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(float(low), min(float(high), float(value)))


def _player(state: Any, player_id: str) -> Any | None:
    return (getattr(state, "players", {}) or {}).get(str(player_id))


def _skill(player: Any, name: str) -> float:
    values = getattr(player, "skill_ratings", {}) or {}
    overall = _number(getattr(player, "overall_rating", 70.0), 70.0)
    return _clamp(_number(values.get(name), overall), 40.0, 99.0)


def _baseline(player: Any, name: str, default: float) -> float:
    values = getattr(player, "baseline_per_36", {}) or {}
    return max(0.0, _number(values.get(name), default))


def _scale(value: float, practical_maximum: float) -> float:
    if practical_maximum <= 0:
        return 0.0
    return _clamp(float(value) / float(practical_maximum) * 100.0)


def _position_tokens(value: Any) -> set[str]:
    raw = (
        _clean(value)
        .upper()
        .replace("/", "-")
        .replace("_", "-")
        .replace(" ", "")
    )
    aliases = {
        "POINTGUARD": "PG",
        "SHOOTINGGUARD": "SG",
        "SMALLFORWARD": "SF",
        "POWERFORWARD": "PF",
        "CENTER": "C",
        "GUARD": "G",
        "FORWARD": "F",
    }
    raw = aliases.get(raw, raw)
    tokens = {token for token in raw.split("-") if token}
    expanded = set(tokens)
    if "G" in tokens:
        expanded.update({"PG", "SG"})
    if "F" in tokens:
        expanded.update({"SF", "PF"})
    if "GF" in tokens or "FG" in tokens:
        expanded.update({"PG", "SG", "SF", "PF"})
    if "FC" in tokens or "CF" in tokens:
        expanded.update({"SF", "PF", "C"})
    return expanded


def _position_family_scores(position: Any) -> tuple[float, float, float]:
    tokens = _position_tokens(position)
    guard = 1.0 if tokens.intersection({"PG", "SG"}) else 0.0
    wing = 1.0 if tokens.intersection({"SG", "SF", "PF"}) else 0.0
    big = 1.0 if tokens.intersection({"PF", "C"}) else 0.0
    return guard, wing, big


def functional_role_profile_v1(
    state: Any,
    player_id: str,
) -> FunctionalRoleProfile:
    player = _player(state, player_id)
    if player is None:
        raise ValueError(f"Unknown player for functional-role model: {player_id}")

    scoring = _skill(player, "scoring_rating")
    shooting = _skill(player, "shooting_rating")
    playmaking = _skill(player, "playmaking_rating")
    rebounding = _skill(player, "rebounding_rating")
    defense = _skill(player, "defense_rating")
    efficiency = _skill(player, "efficiency_rating")

    points = _scale(_baseline(player, "points_per_36", 14.0), 30.0)
    rebounds = _scale(_baseline(player, "rebounds_per_36", 5.0), 15.0)
    assists = _scale(_baseline(player, "assists_per_36", 3.0), 11.0)
    steals = _scale(_baseline(player, "steals_per_36", 1.0), 2.4)
    blocks = _scale(_baseline(player, "blocks_per_36", 0.5), 3.4)
    threes = _scale(_baseline(player, "three_attempts_per_36", 3.5), 10.0)
    free_throws = _scale(_baseline(player, "free_throw_attempts_per_36", 3.5), 10.0)
    turnovers = _scale(_baseline(player, "turnovers_per_36", 2.0), 5.0)

    guard, wing, big = _position_family_scores(getattr(player, "position", ""))

    primary_creator = (
        playmaking * 0.43
        + scoring * 0.22
        + assists * 0.22
        + points * 0.08
        + efficiency * 0.05
    )
    secondary_creator = (
        playmaking * 0.32
        + scoring * 0.25
        + assists * 0.18
        + shooting * 0.12
        + efficiency * 0.13
    )
    ball_handler = (
        playmaking * 0.52
        + assists * 0.22
        + scoring * 0.10
        + (100.0 - turnovers) * 0.08
        + guard * 8.0
    )
    spacer = (
        shooting * 0.58
        + threes * 0.24
        + efficiency * 0.10
        + scoring * 0.08
    )
    rim_pressure = (
        scoring * 0.48
        + free_throws * 0.25
        + points * 0.17
        + efficiency * 0.10
    )
    rebounder = (
        rebounding * 0.62
        + rebounds * 0.30
        + big * 8.0
    )
    rim_protector = (
        defense * 0.53
        + blocks * 0.32
        + big * 15.0
    )
    poa_defender = (
        defense * 0.63
        + steals * 0.22
        + guard * 9.0
        + wing * 6.0
    )
    wing_stopper = (
        defense * 0.67
        + steals * 0.13
        + wing * 16.0
        + rebounding * 0.04
    )
    interior_defender = (
        defense * 0.58
        + blocks * 0.20
        + rebounding * 0.10
        + big * 15.0
    )
    connector = (
        playmaking * 0.35
        + assists * 0.22
        + shooting * 0.13
        + efficiency * 0.18
        + (100.0 - turnovers) * 0.12
    )

    scores = {
        ROLE_PRIMARY_CREATOR: _clamp(primary_creator),
        ROLE_SECONDARY_CREATOR: _clamp(secondary_creator),
        ROLE_BALL_HANDLER: _clamp(ball_handler),
        ROLE_SPACER: _clamp(spacer),
        ROLE_RIM_PRESSURE: _clamp(rim_pressure),
        ROLE_REBOUNDER: _clamp(rebounder),
        ROLE_RIM_PROTECTOR: _clamp(rim_protector),
        ROLE_POA_DEFENDER: _clamp(poa_defender),
        ROLE_WING_STOPPER: _clamp(wing_stopper),
        ROLE_INTERIOR_DEFENDER: _clamp(interior_defender),
        ROLE_CONNECTOR: _clamp(connector),
    }

    return FunctionalRoleProfile(
        version=COACHING_ROLE_ROTATION_VERSION,
        player_id=str(player_id),
        player_name=_clean(getattr(player, "player_name", "")) or str(player_id),
        position=_clean(getattr(player, "position", "")) or "UNK",
        scores={key: round(value, 2) for key, value in scores.items()},
    )


def primary_roles_v1(
    state: Any,
    player_id: str,
    *,
    limit: int = 4,
    minimum_score: float = 58.0,
) -> tuple[tuple[str, float], ...]:
    profile = functional_role_profile_v1(state, player_id)
    ordered = sorted(
        profile.scores.items(),
        key=lambda item: (-float(item[1]), item[0]),
    )
    selected = [
        (role, score)
        for role, score in ordered
        if float(score) >= float(minimum_score)
    ][: max(1, int(limit))]
    if not selected:
        selected = ordered[: max(1, int(limit))]
    return tuple(selected)


def missing_role_weights_v1(
    state: Any,
    missing_player_ids: Iterable[str],
) -> dict[str, float]:
    aggregate: dict[str, float] = {}
    for player_id in missing_player_ids:
        team = _clean(getattr(_player(state, player_id), "team_abbreviation", ""))
        saved = 0.0
        if team and team in (getattr(state, "teams", {}) or {}):
            saved = _number(
                getattr(
                    getattr(state.teams[team], "rotation", None),
                    "minutes_targets",
                    {},
                ).get(str(player_id)),
                0.0,
            )
        minute_weight = max(0.65, min(1.20, saved / 30.0 if saved > 0 else 1.0))
        for role, score in primary_roles_v1(state, str(player_id)):
            importance = max(0.0, float(score) - 45.0) ** 1.35
            aggregate[role] = aggregate.get(role, 0.0) + importance * minute_weight

    total = sum(aggregate.values())
    if total <= 0.0:
        return {ROLE_SECONDARY_CREATOR: 1.0}
    return {
        role: value / total
        for role, value in aggregate.items()
    }


def role_fit_v1(
    state: Any,
    candidate_player_id: str,
    role_weights: Mapping[str, float],
) -> float:
    profile = functional_role_profile_v1(state, candidate_player_id)
    total_weight = sum(max(0.0, _number(value)) for value in role_weights.values())
    if total_weight <= 0:
        return 50.0
    return _clamp(
        sum(
            max(0.0, _number(weight))
            * float(profile.scores.get(role, 50.0))
            for role, weight in role_weights.items()
        )
        / total_weight
    )


def position_fit_v1(
    missing_position: Any,
    candidate_position: Any,
) -> float:
    missing = _position_tokens(missing_position)
    candidate = _position_tokens(candidate_position)
    if not missing or not candidate:
        return 55.0
    if missing.intersection(candidate):
        return 100.0

    adjacency = {
        "PG": {"SG", "SF"},
        "SG": {"PG", "SF"},
        "SF": {"SG", "PF"},
        "PF": {"SF", "C"},
        "C": {"PF", "SF"},
    }
    if any(
        any(other in candidate for other in adjacency.get(slot, set()))
        for slot in missing
    ):
        return 72.0
    return 35.0


def _effective_quality(state: Any, player_id: str) -> float:
    player = _player(state, player_id)
    if player is None:
        return 0.0
    quality = _number(getattr(player, "overall_rating", 0.0), 0.0)
    injury = (getattr(state, "injuries", {}) or {}).get(str(player_id))
    if injury is not None:
        status = _clean(getattr(getattr(injury, "status", ""), "value", getattr(injury, "status", ""))).lower()
        if status not in {"", "healthy"}:
            quality *= max(0.80, min(1.0, _number(getattr(injury, "performance_multiplier", 1.0), 1.0)))
    return _clamp(quality)


def _rotation_management_rating(state: Any, team: str) -> float:
    try:
        from franchise_staff_system_v1 import team_staff_effects
        return _clamp(
            _number(team_staff_effects(state, team, ensure=False).rotation_management, 70.0),
            45.0,
            99.0,
        )
    except Exception:
        return 70.0


def replacement_candidate_score_v1(
    state: Any,
    team: str,
    missing_player_id: str,
    candidate_player_id: str,
    *,
    rotation_priority_index: int,
) -> dict[str, float]:
    missing_player = _player(state, missing_player_id)
    candidate = _player(state, candidate_player_id)
    if missing_player is None or candidate is None:
        raise ValueError("Replacement candidate scoring requires two valid players.")

    role_weights = missing_role_weights_v1(state, (missing_player_id,))
    role_fit = role_fit_v1(state, candidate_player_id, role_weights)
    position_fit = position_fit_v1(
        getattr(missing_player, "position", ""),
        getattr(candidate, "position", ""),
    )
    quality = _effective_quality(state, candidate_player_id)
    hierarchy = _clamp(100.0 - max(0, int(rotation_priority_index)) * 8.0)

    rotation_management = _rotation_management_rating(state, team)
    role_weight = _clamp(
        0.42 + (rotation_management - 70.0) / 30.0 * 0.07,
        0.36,
        0.50,
    )
    quality_weight = 0.30
    position_weight = 0.18
    hierarchy_weight = max(
        0.02,
        1.0 - role_weight - quality_weight - position_weight,
    )

    combined = (
        role_fit * role_weight
        + quality * quality_weight
        + position_fit * position_weight
        + hierarchy * hierarchy_weight
    )

    return {
        "combined": round(combined, 4),
        "role_fit": round(role_fit, 4),
        "position_fit": round(position_fit, 4),
        "quality": round(quality, 4),
        "hierarchy": round(hierarchy, 4),
        "rotation_management": round(rotation_management, 4),
    }


def _replacement_explanation(
    state: Any,
    missing_player_id: str,
    replacement_player_id: str,
    metrics: Mapping[str, float],
) -> tuple[tuple[str, ...], str]:
    missing = functional_role_profile_v1(state, missing_player_id)
    replacement = functional_role_profile_v1(state, replacement_player_id)
    top = primary_roles_v1(state, missing_player_id, limit=3)
    top_labels = tuple(ROLE_LABELS.get(role, role) for role, _ in top)

    strongest_match = max(
        top,
        key=lambda item: replacement.scores.get(item[0], 0.0),
    )[0]
    match_label = ROLE_LABELS.get(strongest_match, strongest_match)
    explanation = (
        f"{missing.player_name} is unavailable, creating a deficit in "
        f"{', '.join(top_labels)}. {replacement.player_name} is preferred because "
        f"the replacement model rates the fit at {float(metrics['role_fit']):.0f}/100 "
        f"for the missing responsibilities, with {match_label} as the strongest "
        f"functional match and {float(metrics['position_fit']):.0f}/100 positional fit."
    )
    return top_labels, explanation


def reconstruct_injury_aware_rotation_v1(
    state: Any,
    team: str,
    *,
    available_player_ids: Iterable[str],
    original_starter_ids: Iterable[str],
    maximum_rotation_players: int = 10,
) -> tuple[tuple[str, ...], tuple[str, ...], CoachingAdjustmentReport]:
    available = tuple(dict.fromkeys(str(value) for value in available_player_ids))
    original = tuple(str(value) for value in original_starter_ids)
    available_set = set(available)

    surviving = [
        player_id
        for player_id in original
        if player_id in available_set
    ]
    missing = [
        player_id
        for player_id in original
        if player_id not in available_set
    ]

    # Healthy path is intentionally identical to the legacy starter ordering.
    if not missing:
        maximum_players = min(int(maximum_rotation_players), len(available))
        rotation_ids = list(available[:maximum_players])
        for player_id in surviving:
            if player_id not in rotation_ids:
                rotation_ids.append(player_id)
        rotation_ids.sort(
            key=lambda player_id: (
                0 if player_id in surviving else 1,
                available.index(player_id),
            )
        )
        rotation_ids = rotation_ids[: int(maximum_rotation_players)]
        report = CoachingAdjustmentReport(
            version=COACHING_ROLE_ROTATION_VERSION,
            team=str(team),
            missing_starter_ids=(),
            missing_starter_names=(),
            role_deficits=(),
            replacement_decisions=(),
            summary="Saved starting five is available; no coaching reconstruction is required.",
        )
        return tuple(rotation_ids), tuple(surviving[:5]), report

    selected = list(surviving)
    decisions: list[ReplacementDecision] = []

    for missing_player_id in missing:
        candidates = [
            player_id
            for player_id in available
            if player_id not in selected
        ]
        if not candidates:
            break

        ranked: list[tuple[float, int, str, dict[str, float]]] = []
        for candidate_id in candidates:
            priority_index = available.index(candidate_id)
            metrics = replacement_candidate_score_v1(
                state,
                str(team),
                missing_player_id,
                candidate_id,
                rotation_priority_index=priority_index,
            )
            ranked.append(
                (
                    -float(metrics["combined"]),
                    priority_index,
                    candidate_id,
                    metrics,
                )
            )
        ranked.sort(key=lambda item: (item[0], item[1], item[2]))
        _, _, replacement_id, metrics = ranked[0]
        selected.append(replacement_id)

        missing_player = _player(state, missing_player_id)
        replacement_player = _player(state, replacement_id)
        top_labels, explanation = _replacement_explanation(
            state,
            missing_player_id,
            replacement_id,
            metrics,
        )
        decisions.append(
            ReplacementDecision(
                missing_player_id=missing_player_id,
                missing_player_name=_clean(getattr(missing_player, "player_name", "")) or missing_player_id,
                replacement_player_id=replacement_id,
                replacement_player_name=_clean(getattr(replacement_player, "player_name", "")) or replacement_id,
                combined_score=float(metrics["combined"]),
                role_fit=float(metrics["role_fit"]),
                position_fit=float(metrics["position_fit"]),
                quality=float(metrics["quality"]),
                primary_missing_roles=top_labels,
                explanation=explanation,
            )
        )

    for player_id in available:
        if len(selected) >= 5:
            break
        if player_id not in selected:
            selected.append(player_id)

    maximum_players = min(int(maximum_rotation_players), len(available))
    rotation_ids = list(available[:maximum_players])
    for player_id in selected:
        if player_id not in rotation_ids:
            rotation_ids.append(player_id)
    rotation_ids.sort(
        key=lambda player_id: (
            0 if player_id in selected[:5] else 1,
            available.index(player_id),
        )
    )
    rotation_ids = rotation_ids[: int(maximum_rotation_players)]

    role_weights = missing_role_weights_v1(state, missing)
    deficits = tuple(
        sorted(
            (
                (ROLE_LABELS.get(role, role), round(weight * 100.0, 1))
                for role, weight in role_weights.items()
            ),
            key=lambda item: (-item[1], item[0]),
        )
    )
    missing_names = tuple(
        _clean(getattr(_player(state, player_id), "player_name", "")) or player_id
        for player_id in missing
    )

    if decisions:
        summary = " ".join(decision.explanation for decision in decisions)
    else:
        summary = (
            "A saved starter is unavailable. The available roster was reconstructed "
            "to maintain a legal five-player starting group."
        )

    report = CoachingAdjustmentReport(
        version=COACHING_ROLE_ROTATION_VERSION,
        team=str(team),
        missing_starter_ids=tuple(missing),
        missing_starter_names=missing_names,
        role_deficits=deficits,
        replacement_decisions=tuple(decisions),
        summary=summary,
    )
    return tuple(rotation_ids), tuple(selected[:5]), report


def injury_adjustment_report_v1(
    state: Any,
    team: str,
    *,
    available_player_ids: Iterable[str],
    original_starter_ids: Iterable[str],
    maximum_rotation_players: int = 10,
) -> CoachingAdjustmentReport:
    _, _, report = reconstruct_injury_aware_rotation_v1(
        state,
        team,
        available_player_ids=available_player_ids,
        original_starter_ids=original_starter_ids,
        maximum_rotation_players=maximum_rotation_players,
    )
    return report


COACHING_WORKLOAD_REDISTRIBUTION_VERSION = (
    "franchise-coaching-workload-redistribution-v1-2026-09-30"
)

MINUTE_MULTIPLIER_FLOOR = 0.90
MINUTE_MULTIPLIER_CEILING = 1.16

RESPONSIBILITY_BOUNDS: dict[str, tuple[float, float]] = {
    "scoring": (0.92, 1.12),
    "creation": (0.90, 1.15),
    "rebounding": (0.93, 1.10),
    "rim_defense": (0.93, 1.10),
    "perimeter_defense": (0.93, 1.10),
}

RESPONSIBILITY_ROLE_CHANNELS: dict[str, dict[str, float]] = {
    "scoring": {
        ROLE_PRIMARY_CREATOR: 1.00,
        ROLE_SECONDARY_CREATOR: 0.78,
        ROLE_BALL_HANDLER: 0.42,
        ROLE_SPACER: 0.48,
        ROLE_RIM_PRESSURE: 0.72,
        ROLE_CONNECTOR: 0.18,
    },
    "creation": {
        ROLE_PRIMARY_CREATOR: 1.00,
        ROLE_SECONDARY_CREATOR: 0.82,
        ROLE_BALL_HANDLER: 1.00,
        ROLE_CONNECTOR: 0.72,
        ROLE_SPACER: 0.12,
    },
    "rebounding": {
        ROLE_REBOUNDER: 1.00,
        ROLE_INTERIOR_DEFENDER: 0.42,
        ROLE_RIM_PROTECTOR: 0.30,
    },
    "rim_defense": {
        ROLE_RIM_PROTECTOR: 1.00,
        ROLE_INTERIOR_DEFENDER: 0.86,
        ROLE_REBOUNDER: 0.22,
    },
    "perimeter_defense": {
        ROLE_POA_DEFENDER: 1.00,
        ROLE_WING_STOPPER: 0.92,
        ROLE_CONNECTOR: 0.08,
    },
}


@dataclass(frozen=True)
class WorkloadRedistributionReport:
    version: str
    team: str
    missing_starter_ids: tuple[str, ...]
    missing_starter_names: tuple[str, ...]
    minute_multipliers: tuple[tuple[str, float], ...]
    scoring_multipliers: tuple[tuple[str, float], ...]
    creation_multipliers: tuple[tuple[str, float], ...]
    summary: str


def missing_saved_starter_ids_v1(
    state: Any,
    team: str,
    active_player_ids: Iterable[str],
) -> tuple[str, ...]:
    team_state = (getattr(state, "teams", {}) or {}).get(str(team))
    if team_state is None:
        return ()
    original_starters = tuple(
        str(value)
        for value in tuple(
            getattr(getattr(team_state, "rotation", None), "starter_ids", ()) or ()
        )
        if str(value)
    )
    active = {str(value) for value in active_player_ids}
    return tuple(
        player_id
        for player_id in original_starters
        if player_id not in active
    )


def _channel_missing_role_weights(
    state: Any,
    missing_player_ids: Iterable[str],
    channel: str,
) -> dict[str, float]:
    overall = missing_role_weights_v1(state, tuple(missing_player_ids))
    channel_weights = RESPONSIBILITY_ROLE_CHANNELS.get(str(channel), {})
    weighted = {
        role: float(overall.get(role, 0.0)) * float(channel_weights.get(role, 0.0))
        for role in overall
        if role in channel_weights
        and float(overall.get(role, 0.0)) > 0.0
        and float(channel_weights.get(role, 0.0)) > 0.0
    }
    total = sum(weighted.values())
    if total <= 0.0:
        return {}
    return {
        role: value / total
        for role, value in weighted.items()
    }


def _active_role_fit_average(
    state: Any,
    player_ids: Iterable[str],
    role_weights: Mapping[str, float],
) -> float:
    ids = tuple(str(value) for value in player_ids)
    if not ids or not role_weights:
        return 50.0
    values = [
        role_fit_v1(state, player_id, role_weights)
        for player_id in ids
        if _player(state, player_id) is not None
    ]
    if not values:
        return 50.0
    return sum(values) / len(values)


def coaching_minute_weight_multipliers_v1(
    state: Any,
    team: str,
    *,
    rotation_ids: Iterable[str],
    starter_ids: Iterable[str],
) -> dict[str, float]:
    rotation = tuple(str(value) for value in rotation_ids)
    starter_set = {str(value) for value in starter_ids}
    missing = missing_saved_starter_ids_v1(state, team, rotation)

    if not missing:
        return {player_id: 1.0 for player_id in rotation}

    role_weights = missing_role_weights_v1(state, missing)
    average_fit = _active_role_fit_average(state, rotation, role_weights)
    qualities = {
        player_id: _effective_quality(state, player_id)
        for player_id in rotation
    }
    average_quality = (
        sum(qualities.values()) / len(qualities)
        if qualities
        else 70.0
    )

    multipliers: dict[str, float] = {}
    for player_id in rotation:
        fit = role_fit_v1(state, player_id, role_weights)
        quality = qualities.get(player_id, 70.0)

        fit_edge = (fit - average_fit) / 28.0
        quality_edge = (quality - average_quality) / 28.0
        promoted_starter_bonus = 0.018 if player_id in starter_set else 0.0

        multiplier = (
            1.0
            + fit_edge * 0.090
            + quality_edge * 0.026
            + promoted_starter_bonus
        )
        multipliers[player_id] = round(
            _clamp(
                multiplier,
                MINUTE_MULTIPLIER_FLOOR,
                MINUTE_MULTIPLIER_CEILING,
            ),
            5,
        )

    return multipliers


def coaching_responsibility_multiplier_v1(
    state: Any,
    team: str,
    player_id: str,
    *,
    active_player_ids: Iterable[str],
    channel: str,
) -> float:
    active = tuple(str(value) for value in active_player_ids)
    missing = missing_saved_starter_ids_v1(state, team, active)
    if not missing:
        return 1.0

    normalized_channel = str(channel).strip().lower()
    role_weights = _channel_missing_role_weights(
        state,
        missing,
        normalized_channel,
    )
    if not role_weights:
        return 1.0

    fit = role_fit_v1(state, str(player_id), role_weights)
    average_fit = _active_role_fit_average(state, active, role_weights)
    quality = _effective_quality(state, str(player_id))
    average_quality = (
        sum(_effective_quality(state, pid) for pid in active) / len(active)
        if active
        else 70.0
    )

    fit_edge = (fit - average_fit) / 30.0
    quality_edge = (quality - average_quality) / 32.0

    raw = (
        1.0
        + fit_edge * 0.075
        + quality_edge * 0.018
    )
    low, high = RESPONSIBILITY_BOUNDS.get(
        normalized_channel,
        (0.94, 1.08),
    )
    return round(_clamp(raw, low, high), 5)


def workload_redistribution_report_v1(
    state: Any,
    team: str,
    *,
    rotation_ids: Iterable[str],
    starter_ids: Iterable[str],
) -> WorkloadRedistributionReport:
    rotation = tuple(str(value) for value in rotation_ids)
    missing = missing_saved_starter_ids_v1(state, team, rotation)
    minute_multipliers = coaching_minute_weight_multipliers_v1(
        state,
        team,
        rotation_ids=rotation,
        starter_ids=tuple(starter_ids),
    )
    scoring = {
        player_id: coaching_responsibility_multiplier_v1(
            state,
            team,
            player_id,
            active_player_ids=rotation,
            channel="scoring",
        )
        for player_id in rotation
    }
    creation = {
        player_id: coaching_responsibility_multiplier_v1(
            state,
            team,
            player_id,
            active_player_ids=rotation,
            channel="creation",
        )
        for player_id in rotation
    }

    missing_names = tuple(
        _clean(getattr(_player(state, player_id), "player_name", "")) or player_id
        for player_id in missing
    )

    if not missing:
        summary = (
            "All saved starters are available. Coaching workload redistribution "
            "is inactive and the saved minute/usage plan is preserved."
        )
    else:
        minute_leader = max(
            minute_multipliers,
            key=lambda pid: (minute_multipliers[pid], pid),
        )
        scoring_leader = max(
            scoring,
            key=lambda pid: (scoring[pid], pid),
        )
        creation_leader = max(
            creation,
            key=lambda pid: (creation[pid], pid),
        )
        minute_name = _clean(getattr(_player(state, minute_leader), "player_name", "")) or minute_leader
        scoring_name = _clean(getattr(_player(state, scoring_leader), "player_name", "")) or scoring_leader
        creation_name = _clean(getattr(_player(state, creation_leader), "player_name", "")) or creation_leader
        summary = (
            f"{', '.join(missing_names)} unavailable. The coaching model shifts "
            f"minutes most toward {minute_name}, scoring responsibility toward "
            f"{scoring_name}, and creation responsibility toward {creation_name}, "
            "while preserving medical caps and the fixed team-minute total."
        )

    return WorkloadRedistributionReport(
        version=COACHING_WORKLOAD_REDISTRIBUTION_VERSION,
        team=str(team),
        missing_starter_ids=missing,
        missing_starter_names=missing_names,
        minute_multipliers=tuple(
            sorted(
                (
                    (_clean(getattr(_player(state, player_id), "player_name", "")) or player_id, value)
                    for player_id, value in minute_multipliers.items()
                ),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        scoring_multipliers=tuple(
            sorted(
                (
                    (_clean(getattr(_player(state, player_id), "player_name", "")) or player_id, value)
                    for player_id, value in scoring.items()
                ),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        creation_multipliers=tuple(
            sorted(
                (
                    (_clean(getattr(_player(state, player_id), "player_name", "")) or player_id, value)
                    for player_id, value in creation.items()
                ),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        summary=summary,
    )


__all__ = [
    "COACHING_ROLE_ROTATION_VERSION",
    "ROLE_LABELS",
    "ROLE_KEYS",
    "FunctionalRoleProfile",
    "ReplacementDecision",
    "CoachingAdjustmentReport",
    "functional_role_profile_v1",
    "primary_roles_v1",
    "missing_role_weights_v1",
    "role_fit_v1",
    "position_fit_v1",
    "replacement_candidate_score_v1",
    "reconstruct_injury_aware_rotation_v1",
    "injury_adjustment_report_v1",
    "COACHING_WORKLOAD_REDISTRIBUTION_VERSION",
    "WorkloadRedistributionReport",
    "missing_saved_starter_ids_v1",
    "coaching_minute_weight_multipliers_v1",
    "coaching_responsibility_multiplier_v1",
    "workload_redistribution_report_v1",
]
