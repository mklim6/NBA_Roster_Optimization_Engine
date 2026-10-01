from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, Iterable

from franchise_coaching_role_rotation_v1 import (
    ROLE_BALL_HANDLER,
    ROLE_CONNECTOR,
    ROLE_INTERIOR_DEFENDER,
    ROLE_POA_DEFENDER,
    ROLE_PRIMARY_CREATOR,
    ROLE_REBOUNDER,
    ROLE_RIM_PRESSURE,
    ROLE_RIM_PROTECTOR,
    ROLE_SECONDARY_CREATOR,
    ROLE_SPACER,
    ROLE_WING_STOPPER,
    functional_role_profile_v1,
)
from franchise_staff_system_v1 import (
    ROLE_ASSISTANT_COACH,
    ROLE_HEAD_COACH,
    team_staff,
    team_staff_effects,
)


COACHING_MATCHUP_TACTICS_VERSION = (
    "franchise-coaching-matchup-tactics-v1-2026-09-30"
)

SCHEME_BALANCED = "balanced"
SCHEME_LOAD_CREATOR = "load_primary_creator"
SCHEME_PACK_PAINT = "pack_paint"
SCHEME_STAY_HOME = "stay_home_on_shooters"
SCHEME_SWITCH = "switch_perimeter_actions"
SCHEME_MATCH_SIZE = "match_size_and_glass"

SCHEME_LABELS = {
    SCHEME_BALANCED: "Balanced",
    SCHEME_LOAD_CREATOR: "Load up on the primary creator",
    SCHEME_PACK_PAINT: "Pack the paint",
    SCHEME_STAY_HOME: "Stay home on shooters",
    SCHEME_SWITCH: "Switch perimeter actions",
    SCHEME_MATCH_SIZE: "Match size and control the glass",
}

MAX_DEFENSIVE_SUPPRESSION_POINTS = 0.65


@dataclass(frozen=True)
class OpponentThreatProfile:
    version: str
    team: str
    creation: float
    multi_handler_creation: float
    spacing: float
    rim_pressure: float
    glass_size: float
    interior_hub: float
    primary_threat_player_id: str
    primary_threat_player_name: str
    primary_threat_score: float


@dataclass(frozen=True)
class DefensiveTacticalDecision:
    version: str
    defending_team: str
    opponent_team: str
    scheme: str
    scheme_label: str
    suppression_points: float
    personnel_capacity: float
    coach_execution: float
    matchup_utility: float
    explanation: str


@dataclass(frozen=True)
class MatchupTacticalReport:
    version: str
    home_team: str
    away_team: str
    home_defense: DefensiveTacticalDecision
    away_defense: DefensiveTacticalDecision
    home_rating_offset: float
    away_rating_offset: float


@dataclass(frozen=True)
class CoachTendencyProfile:
    version: str
    team: str
    head_coach_name: str
    head_traits: tuple[str, ...]
    assistant_traits: tuple[str, ...]
    scheme_biases: tuple[tuple[str, float], ...]
    style_notes: tuple[str, ...]


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed if math.isfinite(parsed) else float(default)


def _clamp(value: float, low: float, high: float) -> float:
    return max(float(low), min(float(high), float(value)))


def _normalized_threat(value: float) -> float:
    return _clamp((float(value) - 58.0) / 32.0, 0.0, 1.0)


def _normalized_capacity(value: float) -> float:
    return _clamp((float(value) - 52.0) / 38.0, 0.20, 1.0)


def _plan_player_ids(plan: Any) -> tuple[str, ...]:
    return tuple(str(value) for value in tuple(getattr(plan, "player_ids", ()) or ()))


def _plan_minutes(plan: Any) -> dict[str, float]:
    return {
        str(player_id): max(0.0, _number(minutes))
        for player_id, minutes in dict(getattr(plan, "minutes", {}) or {}).items()
    }


def _minute_weights(plan: Any) -> dict[str, float]:
    player_ids = _plan_player_ids(plan)
    minutes = _plan_minutes(plan)
    total = sum(minutes.get(player_id, 0.0) for player_id in player_ids)
    if total <= 0.0:
        if not player_ids:
            return {}
        equal = 1.0 / len(player_ids)
        return {player_id: equal for player_id in player_ids}
    return {
        player_id: minutes.get(player_id, 0.0) / total
        for player_id in player_ids
    }


def _weighted_role_average(state: Any, plan: Any, role: str) -> float:
    weights = _minute_weights(plan)
    if not weights:
        return 50.0
    value = 0.0
    observed = 0.0
    for player_id, weight in weights.items():
        try:
            score = functional_role_profile_v1(state, player_id).scores.get(role, 50.0)
        except Exception:
            continue
        value += float(score) * float(weight)
        observed += float(weight)
    if observed <= 0:
        return 50.0
    return _clamp(value / observed, 0.0, 100.0)


def _top_role_score(state: Any, plan: Any, roles: Iterable[str]) -> tuple[str, str, float]:
    best_id = ""
    best_name = ""
    best_score = -1.0
    weights = _minute_weights(plan)
    players = getattr(state, "players", {}) or {}

    for player_id in _plan_player_ids(plan):
        try:
            profile = functional_role_profile_v1(state, player_id)
        except Exception:
            continue
        role_values = [float(profile.scores.get(role, 50.0)) for role in roles]
        role_score = sum(role_values) / max(1, len(role_values))
        minute_presence = _clamp(weights.get(player_id, 0.0) / 0.14, 0.55, 1.15)
        score = role_score * minute_presence
        if score > best_score:
            best_id = player_id
            best_name = _clean(getattr(players.get(player_id), "player_name", "")) or player_id
            best_score = score

    return best_id, best_name, _clamp(best_score, 0.0, 100.0)


def opponent_threat_profile_v1(
    state: Any,
    plan: Any,
) -> OpponentThreatProfile:
    primary = _weighted_role_average(state, plan, ROLE_PRIMARY_CREATOR)
    secondary = _weighted_role_average(state, plan, ROLE_SECONDARY_CREATOR)
    handler = _weighted_role_average(state, plan, ROLE_BALL_HANDLER)
    spacer = _weighted_role_average(state, plan, ROLE_SPACER)
    rim = _weighted_role_average(state, plan, ROLE_RIM_PRESSURE)
    rebound = _weighted_role_average(state, plan, ROLE_REBOUNDER)
    interior = _weighted_role_average(state, plan, ROLE_INTERIOR_DEFENDER)

    creation = (
        primary * 0.46
        + secondary * 0.29
        + handler * 0.25
    )
    multi_handler = (
        secondary * 0.45
        + handler * 0.45
        + primary * 0.10
    )
    glass_size = rebound * 0.76 + interior * 0.24

    threat_id, threat_name, star_score = _top_role_score(
        state,
        plan,
        (
            ROLE_PRIMARY_CREATOR,
            ROLE_RIM_PRESSURE,
            ROLE_REBOUNDER,
        ),
    )
    interior_hub = (
        star_score * 0.60
        + rim * 0.20
        + rebound * 0.20
    )

    return OpponentThreatProfile(
        version=COACHING_MATCHUP_TACTICS_VERSION,
        team=_clean(getattr(plan, "team_abbreviation", "")).upper(),
        creation=round(_clamp(creation, 0.0, 100.0), 2),
        multi_handler_creation=round(_clamp(multi_handler, 0.0, 100.0), 2),
        spacing=round(_clamp(spacer, 0.0, 100.0), 2),
        rim_pressure=round(_clamp(rim, 0.0, 100.0), 2),
        glass_size=round(_clamp(glass_size, 0.0, 100.0), 2),
        interior_hub=round(_clamp(interior_hub, 0.0, 100.0), 2),
        primary_threat_player_id=threat_id,
        primary_threat_player_name=threat_name,
        primary_threat_score=round(star_score, 2),
    )


def _personnel_capacities(state: Any, plan: Any) -> dict[str, float]:
    poa = _weighted_role_average(state, plan, ROLE_POA_DEFENDER)
    wing = _weighted_role_average(state, plan, ROLE_WING_STOPPER)
    rim = _weighted_role_average(state, plan, ROLE_RIM_PROTECTOR)
    interior = _weighted_role_average(state, plan, ROLE_INTERIOR_DEFENDER)
    rebound = _weighted_role_average(state, plan, ROLE_REBOUNDER)
    connector = _weighted_role_average(state, plan, ROLE_CONNECTOR)

    return {
        SCHEME_LOAD_CREATOR: _clamp(
            poa * 0.54 + wing * 0.38 + connector * 0.08,
            0.0,
            100.0,
        ),
        SCHEME_PACK_PAINT: _clamp(
            rim * 0.42 + interior * 0.34 + rebound * 0.24,
            0.0,
            100.0,
        ),
        SCHEME_STAY_HOME: _clamp(
            wing * 0.54 + poa * 0.38 + connector * 0.08,
            0.0,
            100.0,
        ),
        SCHEME_SWITCH: _clamp(
            poa * 0.36 + wing * 0.36 + interior * 0.16 + connector * 0.12,
            0.0,
            100.0,
        ),
        SCHEME_MATCH_SIZE: _clamp(
            rebound * 0.42 + interior * 0.36 + rim * 0.22,
            0.0,
            100.0,
        ),
        SCHEME_BALANCED: 70.0,
    }



_HEAD_TRAIT_SCHEME_BIASES = {
    "Adaptive": {
        SCHEME_LOAD_CREATOR: 0.025,
        SCHEME_PACK_PAINT: 0.025,
        SCHEME_STAY_HOME: 0.025,
        SCHEME_SWITCH: 0.035,
        SCHEME_MATCH_SIZE: 0.025,
    },
    "Player-first": {
        SCHEME_LOAD_CREATOR: -0.010,
        SCHEME_PACK_PAINT: -0.010,
        SCHEME_STAY_HOME: 0.005,
        SCHEME_SWITCH: -0.010,
        SCHEME_MATCH_SIZE: 0.005,
    },
    "Discipline": {
        SCHEME_LOAD_CREATOR: 0.020,
        SCHEME_PACK_PAINT: 0.015,
        SCHEME_STAY_HOME: 0.035,
        SCHEME_SWITCH: -0.005,
        SCHEME_MATCH_SIZE: 0.015,
    },
    "Veteran trust": {
        SCHEME_LOAD_CREATOR: 0.015,
        SCHEME_PACK_PAINT: 0.010,
        SCHEME_STAY_HOME: 0.010,
        SCHEME_SWITCH: -0.005,
        SCHEME_MATCH_SIZE: 0.025,
    },
    "Youth trust": {
        SCHEME_SWITCH: 0.030,
        SCHEME_STAY_HOME: 0.005,
        SCHEME_PACK_PAINT: -0.005,
        SCHEME_MATCH_SIZE: -0.005,
    },
    "Half-court detail": {
        SCHEME_LOAD_CREATOR: 0.050,
        SCHEME_PACK_PAINT: 0.020,
        SCHEME_STAY_HOME: 0.040,
        SCHEME_SWITCH: 0.010,
        SCHEME_MATCH_SIZE: 0.020,
    },
    "Tempo control": {
        SCHEME_LOAD_CREATOR: 0.010,
        SCHEME_PACK_PAINT: 0.040,
        SCHEME_STAY_HOME: 0.015,
        SCHEME_SWITCH: -0.010,
        SCHEME_MATCH_SIZE: 0.040,
    },
    "Defensive edge": {
        SCHEME_LOAD_CREATOR: 0.040,
        SCHEME_PACK_PAINT: 0.035,
        SCHEME_STAY_HOME: 0.020,
        SCHEME_SWITCH: 0.040,
        SCHEME_MATCH_SIZE: 0.020,
    },
}

_ASSISTANT_TRAIT_SCHEME_BIASES = {
    "Opponent prep": {
        SCHEME_LOAD_CREATOR: 0.030,
        SCHEME_PACK_PAINT: 0.030,
        SCHEME_STAY_HOME: 0.030,
        SCHEME_SWITCH: 0.030,
        SCHEME_MATCH_SIZE: 0.030,
    },
    "Rotation detail": {
        SCHEME_LOAD_CREATOR: 0.010,
        SCHEME_PACK_PAINT: 0.010,
        SCHEME_STAY_HOME: 0.010,
        SCHEME_SWITCH: 0.020,
        SCHEME_MATCH_SIZE: 0.025,
    },
    "Shooting development": {
        SCHEME_PACK_PAINT: -0.010,
        SCHEME_STAY_HOME: 0.025,
        SCHEME_SWITCH: 0.010,
        SCHEME_MATCH_SIZE: -0.005,
    },
    "Defense lab": {
        SCHEME_LOAD_CREATOR: 0.025,
        SCHEME_PACK_PAINT: 0.040,
        SCHEME_STAY_HOME: 0.025,
        SCHEME_SWITCH: 0.050,
        SCHEME_MATCH_SIZE: 0.020,
    },
    "Communication": {
        SCHEME_LOAD_CREATOR: 0.010,
        SCHEME_PACK_PAINT: 0.010,
        SCHEME_STAY_HOME: 0.010,
        SCHEME_SWITCH: 0.010,
        SCHEME_MATCH_SIZE: 0.010,
    },
    "Analytics": {
        SCHEME_LOAD_CREATOR: 0.015,
        SCHEME_PACK_PAINT: 0.010,
        SCHEME_STAY_HOME: 0.025,
        SCHEME_SWITCH: 0.030,
        SCHEME_MATCH_SIZE: 0.005,
    },
}

_MAX_TENDENCY_BIAS = 0.085


def coach_tendency_profile_v1(state: Any, team: str) -> CoachTendencyProfile:
    code = _clean(team).upper()
    head_name = "Head coach"
    head_traits = ()
    assistant_traits = ()

    try:
        staff_state = team_staff(state, code, ensure=False)
        if staff_state is not None:
            head = staff_state.members.get(ROLE_HEAD_COACH)
            assistant = staff_state.members.get(ROLE_ASSISTANT_COACH)
            if head is not None:
                head_name = _clean(getattr(head, "name", "")) or head_name
                head_traits = tuple(
                    _clean(value)
                    for value in tuple(getattr(head, "traits", ()) or ())
                    if _clean(value)
                )
            if assistant is not None:
                assistant_traits = tuple(
                    _clean(value)
                    for value in tuple(getattr(assistant, "traits", ()) or ())
                    if _clean(value)
                )
    except Exception:
        pass

    biases = {
        scheme: 0.0
        for scheme in (
            SCHEME_LOAD_CREATOR,
            SCHEME_PACK_PAINT,
            SCHEME_STAY_HOME,
            SCHEME_SWITCH,
            SCHEME_MATCH_SIZE,
        )
    }

    for trait in head_traits:
        for scheme, value in _HEAD_TRAIT_SCHEME_BIASES.get(trait, {}).items():
            biases[scheme] += float(value)

    for trait in assistant_traits:
        for scheme, value in _ASSISTANT_TRAIT_SCHEME_BIASES.get(trait, {}).items():
            biases[scheme] += float(value)

    biases = {
        scheme: round(
            _clamp(value, -_MAX_TENDENCY_BIAS, _MAX_TENDENCY_BIAS),
            4,
        )
        for scheme, value in biases.items()
    }

    notes = []
    if "Adaptive" in head_traits:
        notes.append("more willing to change coverages game to game")
    if "Half-court detail" in head_traits:
        notes.append("leans toward targeted half-court counters")
    if "Tempo control" in head_traits:
        notes.append("prefers structure, size, and paint control")
    if "Defensive edge" in head_traits:
        notes.append("is more comfortable with aggressive defensive adjustments")
    if "Opponent prep" in assistant_traits:
        notes.append("assistant staff adds matchup-specific preparation")
    if "Defense lab" in assistant_traits:
        notes.append("assistant staff favors technical coverage solutions")
    if "Analytics" in assistant_traits:
        notes.append("assistant staff is more receptive to spacing and matchup signals")
    if not notes:
        notes.append("uses a relatively neutral tactical preference profile")

    return CoachTendencyProfile(
        version=COACHING_MATCHUP_TACTICS_VERSION,
        team=code,
        head_coach_name=head_name,
        head_traits=tuple(head_traits),
        assistant_traits=tuple(assistant_traits),
        scheme_biases=tuple(
            sorted(
                biases.items(),
                key=lambda item: (-abs(float(item[1])), item[0]),
            )
        ),
        style_notes=tuple(notes),
    )


def _tendency_bias_for_scheme(profile: CoachTendencyProfile, scheme: str) -> float:
    return float(dict(profile.scheme_biases).get(scheme, 0.0))


def _coach_execution(state: Any, team: str) -> float:
    defense = 70.0
    adaptability = 70.0
    try:
        effects = team_staff_effects(state, team, ensure=False)
        defense = _number(getattr(effects, "defense_index", 70.0), 70.0)
    except Exception:
        pass

    try:
        staff_state = team_staff(state, team, ensure=False)
        if staff_state is not None:
            head = staff_state.members.get(ROLE_HEAD_COACH)
            assistant = staff_state.members.get(ROLE_ASSISTANT_COACH)
            head_adapt = _number(getattr(head, "adaptability_rating", 70.0), 70.0)
            assistant_adapt = _number(getattr(assistant, "adaptability_rating", 70.0), 70.0)
            adaptability = head_adapt * 0.68 + assistant_adapt * 0.32
    except Exception:
        pass

    return _clamp(
        0.84
        + (defense - 70.0) * 0.0045
        + (adaptability - 70.0) * 0.0035,
        0.70,
        1.12,
    )


def _scheme_utility(profile: OpponentThreatProfile, scheme: str) -> float:
    creation = _normalized_threat(profile.creation)
    multi = _normalized_threat(profile.multi_handler_creation)
    spacing = _normalized_threat(profile.spacing)
    rim = _normalized_threat(profile.rim_pressure)
    glass = _normalized_threat(profile.glass_size)
    hub = _normalized_threat(profile.interior_hub)

    if scheme == SCHEME_LOAD_CREATOR:
        return creation * 1.00 + multi * 0.18 + hub * 0.12 - spacing * 0.46
    if scheme == SCHEME_PACK_PAINT:
        return rim * 1.00 + glass * 0.30 + hub * 0.22 - spacing * 0.72
    if scheme == SCHEME_STAY_HOME:
        return spacing * 1.00 + multi * 0.20 - rim * 0.58
    if scheme == SCHEME_SWITCH:
        return (
            multi * 0.66
            + creation * 0.40
            + spacing * 0.32
            - glass * 0.48
            - hub * 0.16
        )
    if scheme == SCHEME_MATCH_SIZE:
        return (
            glass * 0.72
            + hub * 0.50
            + rim * 0.30
            - spacing * 0.44
        )
    return 0.0


def _threat_phrase(profile: OpponentThreatProfile) -> str:
    dimensions = [
        ("creation", profile.creation),
        ("multi-handler creation", profile.multi_handler_creation),
        ("spacing", profile.spacing),
        ("rim pressure", profile.rim_pressure),
        ("size/rebounding", profile.glass_size),
        ("interior hub play", profile.interior_hub),
    ]
    dimensions.sort(key=lambda item: (-float(item[1]), item[0]))
    return ", ".join(name for name, _ in dimensions[:2])


def choose_defensive_tactical_counter_v1(
    state: Any,
    defending_plan: Any,
    opponent_plan: Any,
) -> DefensiveTacticalDecision:
    defending_team = _clean(getattr(defending_plan, "team_abbreviation", "")).upper()
    opponent_team = _clean(getattr(opponent_plan, "team_abbreviation", "")).upper()
    profile = opponent_threat_profile_v1(state, opponent_plan)
    capacities = _personnel_capacities(state, defending_plan)
    coach_execution = _coach_execution(state, defending_team)
    tendency = coach_tendency_profile_v1(state, defending_team)

    candidates = []
    for scheme in (
        SCHEME_LOAD_CREATOR,
        SCHEME_PACK_PAINT,
        SCHEME_STAY_HOME,
        SCHEME_SWITCH,
        SCHEME_MATCH_SIZE,
    ):
        raw_utility = _scheme_utility(profile, scheme)
        tendency_bias = (
            _tendency_bias_for_scheme(tendency, scheme)
            if raw_utility > 0.0
            else 0.0
        )
        utility = raw_utility + tendency_bias
        capacity = capacities[scheme]
        execution = (
            max(0.0, utility)
            * _normalized_capacity(capacity)
            * coach_execution
        )
        candidates.append(
            (
                execution,
                utility,
                capacity,
                scheme,
                raw_utility,
                tendency_bias,
            )
        )

    candidates.sort(
        key=lambda item: (
            -float(item[0]),
            -float(item[1]),
            -float(item[2]),
            item[3],
        )
    )
    (
        execution,
        utility,
        capacity,
        scheme,
        raw_utility,
        tendency_bias,
    ) = candidates[0]

    # A low-confidence matchup stays balanced rather than forcing a tactic.
    if execution < 0.12 or utility <= 0.0:
        scheme = SCHEME_BALANCED
        utility = 0.0
        raw_utility = 0.0
        tendency_bias = 0.0
        capacity = capacities[SCHEME_BALANCED]
        suppression = 0.0
    else:
        suppression = _clamp(
            execution * 0.44,
            0.0,
            MAX_DEFENSIVE_SUPPRESSION_POINTS,
        )

    threat_name = profile.primary_threat_player_name or opponent_team
    if scheme == SCHEME_BALANCED:
        explanation = (
            f"{defending_team} stays balanced against {opponent_team}. The opponent's "
            f"main pressure points are {_threat_phrase(profile)}, but no specialized "
            "counter has enough personnel-and-coach advantage to justify the tradeoff."
        )
    else:
        tendency_copy = (
            f" {tendency.head_coach_name}'s simulated staff tendency adds "
            f"{tendency_bias:+.03f} matchup utility to this already-plausible counter."
            if abs(tendency_bias) >= 0.005
            else ""
        )
        explanation = (
            f"{defending_team} selects {SCHEME_LABELS[scheme].lower()} against "
            f"{opponent_team}. {threat_name} anchors a threat profile led by "
            f"{_threat_phrase(profile)}. The roster grades {capacity:.0f}/100 for "
            f"executing this counter, with coach execution at {coach_execution:.2f}x."
            f"{tendency_copy} "
            f"The bounded modeled suppression is {suppression:.2f} points."
        )

    return DefensiveTacticalDecision(
        version=COACHING_MATCHUP_TACTICS_VERSION,
        defending_team=defending_team,
        opponent_team=opponent_team,
        scheme=scheme,
        scheme_label=SCHEME_LABELS[scheme],
        suppression_points=round(float(suppression), 4),
        personnel_capacity=round(float(capacity), 2),
        coach_execution=round(float(coach_execution), 4),
        matchup_utility=round(float(utility), 4),
        explanation=explanation,
    )


def _rating_offsets_for_defensive_suppression(
    *,
    home_defensive_suppression: float,
    away_defensive_suppression: float,
    offense_rating_weight: float,
    opponent_rating_weight: float,
) -> tuple[float, float]:
    offense = float(offense_rating_weight)
    opponent = float(opponent_rating_weight)
    determinant = offense * offense - opponent * opponent
    if abs(determinant) < 1e-9:
        return 0.0, 0.0

    # regulation_score_expectations uses:
    #   home += offense*h_rating - opponent*a_rating
    #   away += offense*a_rating - opponent*h_rating
    #
    # Solve the two-equation system so the tactical rating offsets produce
    # exactly:
    #   home expected score change = -away defensive suppression
    #   away expected score change = -home defensive suppression
    home_offset = -(
        offense * float(away_defensive_suppression)
        + opponent * float(home_defensive_suppression)
    ) / determinant
    away_offset = -(
        opponent * float(away_defensive_suppression)
        + offense * float(home_defensive_suppression)
    ) / determinant
    return home_offset, away_offset


def apply_matchup_tactical_counters_v1(
    state: Any,
    home_plan: Any,
    away_plan: Any,
    *,
    offense_rating_weight: float,
    opponent_rating_weight: float,
) -> tuple[Any, Any, MatchupTacticalReport]:
    home_decision = choose_defensive_tactical_counter_v1(
        state,
        home_plan,
        away_plan,
    )
    away_decision = choose_defensive_tactical_counter_v1(
        state,
        away_plan,
        home_plan,
    )

    home_offset, away_offset = _rating_offsets_for_defensive_suppression(
        home_defensive_suppression=home_decision.suppression_points,
        away_defensive_suppression=away_decision.suppression_points,
        offense_rating_weight=offense_rating_weight,
        opponent_rating_weight=opponent_rating_weight,
    )

    adjusted_home = replace(
        home_plan,
        weighted_team_rating=round(
            float(getattr(home_plan, "weighted_team_rating", 0.0))
            + home_offset,
            4,
        ),
    )
    adjusted_away = replace(
        away_plan,
        weighted_team_rating=round(
            float(getattr(away_plan, "weighted_team_rating", 0.0))
            + away_offset,
            4,
        ),
    )

    return (
        adjusted_home,
        adjusted_away,
        MatchupTacticalReport(
            version=COACHING_MATCHUP_TACTICS_VERSION,
            home_team=_clean(getattr(home_plan, "team_abbreviation", "")).upper(),
            away_team=_clean(getattr(away_plan, "team_abbreviation", "")).upper(),
            home_defense=home_decision,
            away_defense=away_decision,
            home_rating_offset=round(home_offset, 4),
            away_rating_offset=round(away_offset, 4),
        ),
    )


__all__ = [
    "COACHING_MATCHUP_TACTICS_VERSION",
    "MAX_DEFENSIVE_SUPPRESSION_POINTS",
    "SCHEME_BALANCED",
    "SCHEME_LOAD_CREATOR",
    "SCHEME_PACK_PAINT",
    "SCHEME_STAY_HOME",
    "SCHEME_SWITCH",
    "SCHEME_MATCH_SIZE",
    "OpponentThreatProfile",
    "DefensiveTacticalDecision",
    "MatchupTacticalReport",
    "CoachTendencyProfile",
    "coach_tendency_profile_v1",
    "opponent_threat_profile_v1",
    "choose_defensive_tactical_counter_v1",
    "apply_matchup_tactical_counters_v1",
]
