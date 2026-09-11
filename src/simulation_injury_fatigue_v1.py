from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import random
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import (  # noqa: E402
    load_runtime_data,
    normalize_player_id,
)
from mutable_league_state_v1 import (  # noqa: E402
    create_league_state,
)
from simulation_league_state_v1 import (  # noqa: E402
    AvailabilityStatus,
    CompletedGame,
    GameStatus,
    ScheduledGame,
    SimulationLeagueState,
    validate_simulation_league_state,
)
from state_runtime_adapter_v1 import (  # noqa: E402
    build_state_runtime,
)


INJURY_FATIGUE_VERSION = (
    "simulation-injury-fatigue-v1-2026-08-09"
)
SELF_TEST_REPORT = (
    OUTPUTS / "simulation_injury_fatigue_v1_self_test.json"
)
HEALTH_STATE_ATTRIBUTE = "injury_fatigue_profiles"
EVENT_HISTORY_ATTRIBUTE = "injury_fatigue_events"
HEALTH_NORMALIZATION_MARKER_ATTRIBUTE = (
    "_injury_fatigue_normalization_marker_v1"
)
HEALTH_WORKLOAD_REBUILD_MARKER_ATTRIBUTE = (
    "_injury_fatigue_workload_rebuild_marker_v1"
)
HEALTH_PERSISTENCE_REPAIR_VERSION = (
    "franchise-health-persistence-repair-v1-2026-08-09"
)

UNAVAILABLE_STATUSES = {
    AvailabilityStatus.OUT,
    AvailabilityStatus.DOUBTFUL,
}

PLAYABLE_INJURY_STATUSES = {
    AvailabilityStatus.PROBABLE,
    AvailabilityStatus.QUESTIONABLE,
    AvailabilityStatus.DAY_TO_DAY,
}

INJURY_TYPES = {
    "soreness": (
        "ankle soreness",
        "knee soreness",
        "lower-back tightness",
        "calf tightness",
        "hip soreness",
    ),
    "minor": (
        "mild ankle sprain",
        "wrist sprain",
        "back strain",
        "quad contusion",
        "shoulder bruise",
    ),
    "moderate": (
        "hamstring strain",
        "moderate ankle sprain",
        "knee sprain",
        "calf strain",
        "shoulder sprain",
    ),
    "major": (
        "severe ankle sprain",
        "major hamstring strain",
        "knee ligament injury",
        "foot fracture",
        "shoulder dislocation",
    ),
}


@dataclass(frozen=True)
class InjuryFatigueConfig:
    base_player_game_injury_risk: float = 0.00380
    fatigue_recovery_on_next_day: float = 9.0
    fatigue_recovery_per_extra_day: float = 18.0
    fatigue_per_minute: float = 0.82
    back_to_back_fatigue_bonus: float = 5.0
    overtime_fatigue_bonus: float = 2.0
    maximum_event_probability: float = 0.035
    recent_window_games: int = 6


@dataclass
class PlayerHealthState:
    player_id: str
    season_label: str
    fatigue: float = 0.0
    durability: float = 0.90
    last_game_day: int = 0
    last_recovery_day: int = 0
    recent_game_days: tuple[int, ...] = ()
    recent_minutes: tuple[float, ...] = ()
    expected_return_day: int = 0
    injury_severity: str = ""
    minutes_limit: float | None = None
    status_reason: str = ""
    season_games_missed: int = 0
    injuries_suffered: int = 0
    last_injury_risk: float = 0.0
    last_risk_tier: str = "Low"
    last_risk_explanation: str = "No recent workload."
    last_updated_game_id: str = ""


@dataclass(frozen=True)
class PlayerRiskAssessment:
    player_id: str
    probability: float
    risk_tier: str
    fatigue: float
    planned_minutes: float
    back_to_back: bool
    three_in_four: bool
    four_in_six: bool
    recent_minutes: float
    durability: float
    explanation: str


@dataclass(frozen=True)
class InjuryEvent:
    version: str
    season_label: str
    game_id: str
    day_index: int
    player_id: str
    player_name: str
    team: str
    injury_type: str
    severity: str
    status: str
    expected_return_day: int
    estimated_games_missed: int
    probability: float
    fatigue_before_game: float
    minutes_played: float
    back_to_back: bool
    explanation: str


@dataclass(frozen=True)
class GameHealthUpdate:
    version: str
    game_id: str
    day_index: int
    injury_events: tuple[InjuryEvent, ...]
    recovered_player_ids: tuple[str, ...]
    high_risk_player_ids: tuple[str, ...]
    average_pregame_fatigue: float
    maximum_pregame_fatigue: float


def clamp(
    value: float,
    minimum: float,
    maximum: float,
) -> float:
    return max(minimum, min(maximum, value))


def stable_fraction(*parts: Any) -> float:
    payload = "|".join(
        str(part)
        for part in parts
    ).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(
        digest[:8],
        "big",
    ) / float(2**64 - 1)


def player_durability(
    state: SimulationLeagueState,
    player_id: str,
) -> float:
    player = state.players[player_id]
    availability = float(
        player.skill_ratings.get(
            "availability_rating",
            75.0,
        )
        or 75.0
    )
    age = float(
        player.age
        if player.age is not None
        else 27.0
    )
    deterministic_variation = (
        stable_fraction(
            state.settings.random_seed,
            player_id,
            "durability",
        )
        - 0.5
    ) * 0.10
    age_penalty = max(
        0.0,
        age - 30.0,
    ) * 0.006
    return round(
        clamp(
            0.88
            + (availability - 75.0) / 180.0
            + deterministic_variation
            - age_penalty,
            0.62,
            1.08,
        ),
        4,
    )


def default_health_state(
    state: SimulationLeagueState,
    player_id: str,
) -> PlayerHealthState:
    injury = state.injuries[player_id]
    status_reason = (
        injury.notes
        if injury.status
        != AvailabilityStatus.HEALTHY
        else ""
    )
    return PlayerHealthState(
        player_id=player_id,
        season_label=(
            state.settings.season_label
        ),
        durability=player_durability(
            state,
            player_id,
        ),
        injury_severity=(
            "legacy"
            if injury.status
            != AvailabilityStatus.HEALTHY
            else ""
        ),
        minutes_limit=(
            30.0
            if injury.status
            in PLAYABLE_INJURY_STATUSES
            else None
        ),
        status_reason=status_reason,
    )


def structurally_migrate_health_profile(
    state: SimulationLeagueState,
    player_id: str,
    source: Any,
) -> PlayerHealthState:
    """Rebind a persisted profile to the current hot-reload class.

    Streamlit can preserve the franchise object while reloading this module.
    In that case the old profile has the right fields but a different Python
    class identity. Field-by-field migration preserves workload rather than
    replacing the profile with an empty default.
    """
    current_season = state.settings.season_label
    if source is None:
        return default_health_state(state, player_id)

    source_season = str(
        getattr(source, "season_label", "")
        or ""
    )
    if source_season and source_season != current_season:
        return default_health_state(state, player_id)

    migrated = default_health_state(state, player_id)
    for item in fields(PlayerHealthState):
        if item.name in {"player_id", "season_label"}:
            continue
        if hasattr(source, item.name):
            setattr(
                migrated,
                item.name,
                copy.deepcopy(getattr(source, item.name)),
            )

    migrated.player_id = player_id
    migrated.season_label = current_season
    migrated.fatigue = round(
        clamp(float(migrated.fatigue or 0.0), 0.0, 100.0),
        2,
    )
    migrated.durability = round(
        clamp(
            float(
                migrated.durability
                if migrated.durability is not None
                else player_durability(state, player_id)
            ),
            0.50,
            1.15,
        ),
        4,
    )
    migrated.last_game_day = max(0, int(migrated.last_game_day or 0))
    migrated.last_recovery_day = max(
        0,
        int(migrated.last_recovery_day or 0),
    )
    migrated.recent_game_days = tuple(
        int(value)
        for value in tuple(migrated.recent_game_days or ())[-6:]
    )
    migrated.recent_minutes = tuple(
        round(float(value), 1)
        for value in tuple(migrated.recent_minutes or ())[-6:]
    )
    migrated.expected_return_day = max(
        0,
        int(migrated.expected_return_day or 0),
    )
    migrated.season_games_missed = max(
        0,
        int(migrated.season_games_missed or 0),
    )
    migrated.injuries_suffered = max(
        0,
        int(migrated.injuries_suffered or 0),
    )
    migrated.last_injury_risk = clamp(
        float(migrated.last_injury_risk or 0.0),
        0.0,
        1.0,
    )
    if migrated.minutes_limit is not None:
        migrated.minutes_limit = round(
            clamp(float(migrated.minutes_limit), 0.0, 48.0),
            1,
        )
    return migrated


def workload_history_is_blank(
    profiles: dict[str, PlayerHealthState],
) -> bool:
    return not any(
        profile.last_updated_game_id
        or profile.recent_game_days
        or profile.recent_minutes
        or profile.last_game_day > 0
        or profile.fatigue > 0.0
        for profile in profiles.values()
    )


def rebuild_workload_from_completed_games(
    state: SimulationLeagueState,
    profiles: dict[str, PlayerHealthState],
    *,
    config: InjuryFatigueConfig | None = None,
) -> int:
    """Recover workload from committed box scores without rerolling injuries."""
    resolved = config or InjuryFatigueConfig()
    completed_rows: list[tuple[ScheduledGame, CompletedGame]] = []
    for game_id, completed in state.completed_games.items():
        scheduled = state.schedule.get(game_id)
        if scheduled is None:
            continue
        completed_rows.append((scheduled, completed))

    completed_rows.sort(
        key=lambda pair: (
            int(pair[0].day_index),
            pair[0].game_id,
        )
    )
    if not completed_rows:
        return 0

    for profile in profiles.values():
        profile.fatigue = 0.0
        profile.last_game_day = 0
        profile.last_recovery_day = 0
        profile.recent_game_days = ()
        profile.recent_minutes = ()
        profile.last_updated_game_id = ""

    appearances = 0
    for scheduled, completed in completed_rows:
        day_index = int(scheduled.day_index)
        for line in completed.player_box_scores:
            profile = profiles.get(line.player_id)
            if profile is None:
                continue
            profile.fatigue = recovered_fatigue(
                profile,
                day_index,
                config=resolved,
            )
            back_to_back = bool(
                profile.recent_game_days
                and int(profile.recent_game_days[-1])
                == day_index - 1
            )
            fatigue_added = (
                float(line.minutes) * resolved.fatigue_per_minute
                + (
                    resolved.back_to_back_fatigue_bonus
                    if back_to_back
                    else 0.0
                )
                + resolved.overtime_fatigue_bonus
                * int(completed.overtime_periods)
            )
            profile.fatigue = round(
                clamp(profile.fatigue + fatigue_added, 0.0, 100.0),
                2,
            )
            profile.last_game_day = day_index
            profile.last_recovery_day = day_index
            profile.recent_game_days = tuple(
                (*profile.recent_game_days, day_index)[
                    -resolved.recent_window_games:
                ]
            )
            profile.recent_minutes = tuple(
                (
                    *profile.recent_minutes,
                    round(float(line.minutes), 1),
                )[-resolved.recent_window_games:]
            )
            profile.last_updated_game_id = scheduled.game_id
            appearances += 1

    setattr(
        state,
        HEALTH_WORKLOAD_REBUILD_MARKER_ATTRIBUTE,
        (
            HEALTH_PERSISTENCE_REPAIR_VERSION,
            state.settings.season_label,
            len(state.completed_games),
            appearances,
        ),
    )
    return appearances


def ensure_injury_fatigue_state(
    state: SimulationLeagueState,
) -> dict[str, PlayerHealthState]:
    profiles = getattr(state, HEALTH_STATE_ATTRIBUTE, None)
    current_season = state.settings.season_label
    normalization_marker = (
        INJURY_FATIGUE_VERSION,
        HEALTH_PERSISTENCE_REPAIR_VERSION,
        current_season,
        len(state.players),
        id(state.players),
        id(PlayerHealthState),
    )

    if (
        isinstance(profiles, dict)
        and getattr(
            state,
            HEALTH_NORMALIZATION_MARKER_ATTRIBUTE,
            None,
        )
        == normalization_marker
    ):
        events = getattr(state, EVENT_HISTORY_ATTRIBUTE, None)
        if not isinstance(events, list):
            setattr(state, EVENT_HISTORY_ATTRIBUTE, [])
        return profiles

    if not isinstance(profiles, dict):
        profiles = {}

    normalized: dict[str, PlayerHealthState] = {}
    for player_id in state.players:
        normalized[player_id] = structurally_migrate_health_profile(
            state,
            player_id,
            profiles.get(player_id),
        )

    if (
        state.completed_games
        and workload_history_is_blank(normalized)
    ):
        rebuild_workload_from_completed_games(
            state,
            normalized,
        )

    setattr(state, HEALTH_STATE_ATTRIBUTE, normalized)
    setattr(
        state,
        HEALTH_NORMALIZATION_MARKER_ATTRIBUTE,
        normalization_marker,
    )

    events = getattr(state, EVENT_HISTORY_ATTRIBUTE, None)
    if not isinstance(events, list):
        setattr(state, EVENT_HISTORY_ATTRIBUTE, [])

    return normalized

def health_events(
    state: SimulationLeagueState,
) -> list[dict[str, Any]]:
    ensure_injury_fatigue_state(state)
    return getattr(
        state,
        EVENT_HISTORY_ATTRIBUTE,
    )


def recovered_fatigue(
    profile: PlayerHealthState,
    day_index: int,
    *,
    config: InjuryFatigueConfig | None = None,
) -> float:
    resolved = config or InjuryFatigueConfig()
    recovery_anchor = max(
        int(
            getattr(
                profile,
                "last_game_day",
                0,
            )
        ),
        int(
            getattr(
                profile,
                "last_recovery_day",
                0,
            )
        ),
    )
    if recovery_anchor <= 0:
        return round(
            clamp(profile.fatigue, 0.0, 100.0),
            2,
        )

    elapsed = max(
        0,
        int(day_index)
        - recovery_anchor,
    )
    if elapsed <= 0:
        return round(profile.fatigue, 2)

    recovery = (
        resolved.fatigue_recovery_on_next_day
        + max(
            0,
            elapsed - 1,
        )
        * resolved.fatigue_recovery_per_extra_day
    )
    return round(
        clamp(
            profile.fatigue - recovery,
            0.0,
            100.0,
        ),
        2,
    )


def projected_fatigue(
    state: SimulationLeagueState,
    player_id: str,
    day_index: int,
) -> float:
    profiles = ensure_injury_fatigue_state(
        state
    )
    profile = profiles[player_id]
    baseline = recovered_fatigue(
        profile,
        day_index,
    )
    # FRANCHISE_STAFF_FOUNDATION_V1
    # Medical/performance staff can modestly accelerate or slow recovery in
    # an initialized Franchise staff state. Uninitialized callers stay neutral.
    try:
        from franchise_staff_system_v1 import team_recovery_multiplier
        player = state.players[player_id]
        recovery_multiplier = team_recovery_multiplier(
            state,
            player.team_abbreviation,
        )
    except (ImportError, KeyError, AttributeError, TypeError, ValueError):
        recovery_multiplier = 1.0

    stored = float(profile.fatigue)
    recovered_amount = max(0.0, stored - float(baseline))
    if recovered_amount <= 0.0 or abs(recovery_multiplier - 1.0) <= 1e-12:
        return baseline
    return round(
        clamp(
            stored - recovered_amount * recovery_multiplier,
            0.0,
            100.0,
        ),
        2,
    )


def team_game_days_before(
    state: SimulationLeagueState,
    team: str,
    day_index: int,
) -> tuple[int, ...]:
    return tuple(
        sorted(
            int(game.day_index)
            for game in state.schedule.values()
            if (
                game.status
                == GameStatus.COMPLETED
                and int(game.day_index)
                < int(day_index)
                and team
                in {
                    game.home_team,
                    game.away_team,
                }
            )
        )
    )


def schedule_density_flags(
    state: SimulationLeagueState,
    team: str,
    day_index: int,
    *,
    player_id: str | None = None,
) -> tuple[bool, bool, bool]:
    # Injury risk follows the player's actual workload rather than merely
    # the team's schedule. This correctly treats a rested player as rested
    # and also carries schedule-density effects into postseason games, which
    # are not stored in the regular-season schedule mapping.
    if player_id is not None:
        normalized_player_id = normalize_player_id(
            player_id
        )
        profile = ensure_injury_fatigue_state(
            state
        )[normalized_player_id]
        prior_days = tuple(
            sorted(
                {
                    int(value)
                    for value
                    in profile.recent_game_days
                    if int(value)
                    < int(day_index)
                }
            )
        )
    else:
        prior_days = team_game_days_before(
            state,
            team,
            day_index,
        )
    back_to_back = bool(
        prior_days
        and int(day_index)
        - prior_days[-1]
        == 1
    )
    games_last_three_days = sum(
        1
        for day in prior_days
        if int(day_index) - day <= 3
    )
    games_last_five_days = sum(
        1
        for day in prior_days
        if int(day_index) - day <= 5
    )
    return (
        back_to_back,
        games_last_three_days >= 2,
        games_last_five_days >= 3,
    )


def injury_status_is_unavailable(
    status: AvailabilityStatus | str,
) -> bool:
    try:
        resolved = AvailabilityStatus(
            status
        )
    except ValueError:
        return False
    return resolved in UNAVAILABLE_STATUSES


def fatigue_performance_multiplier(
    state: SimulationLeagueState,
    player_id: str,
    *,
    day_index: int | None = None,
) -> float:
    profile = ensure_injury_fatigue_state(
        state
    )[player_id]
    fatigue = (
        projected_fatigue(
            state,
            player_id,
            day_index,
        )
        if day_index is not None
        else profile.fatigue
    )
    if fatigue <= 35.0:
        return 1.0
    penalty = (
        (fatigue - 35.0)
        / 65.0
        * 0.075
    )
    return round(
        clamp(
            1.0 - penalty,
            0.91,
            1.0,
        ),
        4,
    )


def player_minutes_cap(
    state: SimulationLeagueState,
    player_id: str,
    *,
    day_index: int,
    default_maximum: float,
) -> float:
    profile = ensure_injury_fatigue_state(
        state
    )[player_id]
    fatigue = projected_fatigue(
        state,
        player_id,
        day_index,
    )
    cap = float(default_maximum)

    if profile.minutes_limit is not None:
        cap = min(
            cap,
            float(profile.minutes_limit),
        )

    # Fatigue alone informs risk and performance, but does not silently
    # override a saved coaching plan. A cap is applied only when a medical
    # status explicitly carries a minutes restriction.
    return round(
        max(8.0, cap),
        1,
    )


def player_risk_assessment(
    state: SimulationLeagueState,
    player_id: str,
    *,
    day_index: int,
    planned_minutes: float,
    config: InjuryFatigueConfig | None = None,
) -> PlayerRiskAssessment:
    resolved = config or InjuryFatigueConfig()
    player_id = normalize_player_id(
        player_id
    )
    player = state.players[player_id]
    profile = ensure_injury_fatigue_state(
        state
    )[player_id]
    fatigue = projected_fatigue(
        state,
        player_id,
        day_index,
    )
    (
        back_to_back,
        three_in_four,
        four_in_six,
    ) = schedule_density_flags(
        state,
        player.team_abbreviation,
        day_index,
        player_id=player_id,
    )
    recent_minutes = round(
        sum(
            float(value)
            for value in profile.recent_minutes[-4:]
        ),
        1,
    )
    minute_factor = clamp(
        0.48
        + float(planned_minutes) / 34.0,
        0.55,
        1.72,
    )
    fatigue_factor = (
        1.0
        + max(
            0.0,
            fatigue - 25.0,
        )
        / 75.0
        * 1.25
    )
    schedule_factor = (
        (1.55 if back_to_back else 1.0)
        * (1.24 if three_in_four else 1.0)
        * (1.15 if four_in_six else 1.0)
    )
    age = float(
        player.age
        if player.age is not None
        else 27.0
    )
    age_factor = (
        0.88
        if age < 24.0
        else 1.0
        if age <= 29.0
        else clamp(
            1.0
            + (age - 29.0) * 0.035,
            1.0,
            1.42,
        )
    )
    durability_factor = (
        1.0
        / max(
            profile.durability,
            0.55,
        )
        ** 2.35
    )
    injury = state.injuries[player_id]
    aggravation_factor = (
        1.0
        + float(
            injury.aggravation_risk
        )
        * 1.60
    )
    # Medical/Injury V2 adds recurrence and return-to-play context without
    # replacing the calibrated workload/fatigue risk model above.
    try:
        from simulation_medical_injury_v2 import (
            medical_risk_multiplier,
        )
        medical_factor = medical_risk_multiplier(
            state,
            player_id,
        )
    except (ImportError, KeyError, AttributeError, TypeError, ValueError):
        medical_factor = 1.0
    # FRANCHISE_STAFF_FOUNDATION_V1
    # Only an initialized live franchise staff state changes risk. Standalone
    # simulation validators and old callers remain exactly neutral.
    try:
        from franchise_staff_system_v1 import team_injury_risk_multiplier
        staff_medical_factor = team_injury_risk_multiplier(
            state,
            player.team_abbreviation,
        )
    except (ImportError, KeyError, AttributeError, TypeError, ValueError):
        staff_medical_factor = 1.0
    probability = clamp(
        resolved.base_player_game_injury_risk
        * minute_factor
        * fatigue_factor
        * schedule_factor
        * age_factor
        * durability_factor
        * aggravation_factor
        * medical_factor
        * staff_medical_factor,
        0.00015,
        resolved.maximum_event_probability,
    )

    if probability >= 0.008:
        tier = "High"
    elif probability >= 0.005:
        tier = "Elevated"
    elif probability >= 0.0028:
        tier = "Moderate"
    else:
        tier = "Low"

    reasons: list[str] = []
    if back_to_back:
        reasons.append(
            "back-to-back schedule"
        )
    if three_in_four:
        reasons.append(
            "third game in four days"
        )
    if four_in_six:
        reasons.append(
            "fourth game in six days"
        )
    if fatigue >= 70.0:
        reasons.append(
            f"very high fatigue ({fatigue:.0f}/100)"
        )
    elif fatigue >= 55.0:
        reasons.append(
            f"elevated fatigue ({fatigue:.0f}/100)"
        )
    if planned_minutes >= 36.0:
        reasons.append(
            f"heavy {planned_minutes:.1f}-minute assignment"
        )
    if recent_minutes >= 130.0:
        reasons.append(
            f"{recent_minutes:.0f} minutes over the last four appearances"
        )
    if age >= 33.0:
        reasons.append(
            f"age {age:.0f} in "
            f"{state.settings.season_label} recovery modifier"
        )
    if profile.durability < 0.78:
        reasons.append(
            "below-average durability profile"
        )
    if injury.status in PLAYABLE_INJURY_STATUSES:
        reasons.append(
            "aggravation risk from an existing issue"
        )
    if medical_factor > 1.20:
        reasons.append(
            "medical return/recurrence modifier"
        )
    explanation = (
        "; ".join(reasons)
        if reasons
        else (
            "Normal workload, rest, and durability "
            "produce a low modeled risk."
        )
    )

    return PlayerRiskAssessment(
        player_id=player_id,
        probability=round(
            probability,
            6,
        ),
        risk_tier=tier,
        fatigue=round(
            fatigue,
            1,
        ),
        planned_minutes=round(
            float(planned_minutes),
            1,
        ),
        back_to_back=back_to_back,
        three_in_four=three_in_four,
        four_in_six=four_in_six,
        recent_minutes=recent_minutes,
        durability=profile.durability,
        explanation=explanation,
    )


def synchronize_injury_profile(
    state: SimulationLeagueState,
    player_id: str,
) -> None:
    profile = ensure_injury_fatigue_state(
        state
    )[player_id]
    injury = state.injuries[player_id]
    if injury.status == AvailabilityStatus.HEALTHY:
        profile.injury_severity = ""
        profile.minutes_limit = None
        profile.expected_return_day = 0
        profile.status_reason = ""
    elif not profile.status_reason:
        profile.status_reason = (
            injury.notes
            or injury.injury_type
        )


def clear_player_injury(
    state: SimulationLeagueState,
    player_id: str,
) -> None:
    injury = state.injuries[player_id]
    injury.status = AvailabilityStatus.HEALTHY
    injury.injury_type = ""
    injury.games_remaining = 0
    injury.performance_multiplier = 1.0
    injury.aggravation_risk = 0.0
    injury.notes = ""
    profile = ensure_injury_fatigue_state(
        state
    )[player_id]
    profile.expected_return_day = 0
    profile.injury_severity = ""
    profile.minutes_limit = None
    profile.status_reason = ""


def prepare_health_for_game(
    state: SimulationLeagueState,
    *,
    day_index: int,
    teams: Iterable[str],
) -> tuple[str, ...]:
    profiles = ensure_injury_fatigue_state(
        state
    )
    recovered: list[str] = []
    team_set = {
        str(team).strip().upper()
        for team in teams
    }

    # Medical/Injury V2 owns staged rehab and return-to-play for cases it
    # created. Legacy injuries still use the original automatic return path.
    try:
        from simulation_medical_injury_v2 import (
            medical_case_is_active,
            prepare_medical_cases_for_game,
        )
        recovered.extend(
            prepare_medical_cases_for_game(
                state,
                day_index=day_index,
                teams=team_set,
            )
        )
        medical_v2_available = True
    except ImportError:
        medical_case_is_active = None
        medical_v2_available = False

    for player_id, player in state.players.items():
        if (
            player.team_abbreviation
            not in team_set
        ):
            continue

        profile = profiles[player_id]
        profile.fatigue = recovered_fatigue(
            profile,
            day_index,
        )
        profile.last_recovery_day = int(
            day_index
        )
        injury = state.injuries[player_id]

        if (
            medical_v2_available
            and medical_case_is_active is not None
            and medical_case_is_active(
                state,
                player_id,
            )
        ):
            synchronize_injury_profile(
                state,
                player_id,
            )
            continue

        if (
            injury.status
            != AvailabilityStatus.HEALTHY
            and profile.expected_return_day > 0
        ):
            remaining_days = max(
                0,
                profile.expected_return_day
                - int(day_index),
            )
            injury.games_remaining = int(
                math.ceil(
                    remaining_days / 2.0
                )
            )

            if (
                int(day_index)
                >= profile.expected_return_day
            ):
                clear_player_injury(
                    state,
                    player_id,
                )
                recovered.append(player_id)
                continue

        synchronize_injury_profile(
            state,
            player_id,
        )

    return tuple(dict.fromkeys(recovered))


def team_available_count(
    state: SimulationLeagueState,
    team: str,
) -> int:
    return sum(
        1
        for player_id
        in state.teams[
            team
        ].roster_player_ids
        if not injury_status_is_unavailable(
            state.injuries[
                player_id
            ].status
        )
    )


def choose_injury_outcome(
    rng: random.Random,
    *,
    existing_issue: bool,
) -> tuple[
    str,
    str,
    AvailabilityStatus,
    int,
    float,
    float,
    float | None,
]:
    roll = rng.random()
    if existing_issue:
        roll = min(1.0, roll + 0.12)

    if roll < 0.56:
        severity = "soreness"
        status = (
            AvailabilityStatus.PROBABLE
            if rng.random() < 0.35
            else AvailabilityStatus.QUESTIONABLE
        )
        days = rng.randint(1, 3)
        performance = rng.uniform(0.94, 0.98)
        aggravation = rng.uniform(0.12, 0.22)
        limit = rng.uniform(27.0, 33.0)
    elif roll < 0.86:
        severity = "minor"
        status = AvailabilityStatus.DOUBTFUL
        days = rng.randint(2, 6)
        performance = rng.uniform(0.91, 0.95)
        aggravation = rng.uniform(0.10, 0.18)
        limit = rng.uniform(24.0, 29.0)
    elif roll < 0.975:
        severity = "moderate"
        status = AvailabilityStatus.OUT
        days = rng.randint(9, 24)
        performance = 1.0
        aggravation = rng.uniform(0.10, 0.20)
        limit = None
    else:
        severity = "major"
        status = AvailabilityStatus.OUT
        days = rng.randint(25, 70)
        performance = 1.0
        aggravation = rng.uniform(0.12, 0.25)
        limit = None

    injury_type = rng.choice(
        INJURY_TYPES[severity]
    )
    return (
        injury_type,
        severity,
        status,
        days,
        performance,
        aggravation,
        limit,
    )


def process_completed_game_health(
    state: SimulationLeagueState,
    scheduled: ScheduledGame,
    game: CompletedGame,
    *,
    seed: int,
    config: InjuryFatigueConfig | None = None,
) -> GameHealthUpdate:
    resolved = config or InjuryFatigueConfig()
    profiles = ensure_injury_fatigue_state(
        state
    )
    recovered = prepare_health_for_game(
        state,
        day_index=scheduled.day_index,
        teams=(
            scheduled.home_team,
            scheduled.away_team,
        ),
    )
    played_ids = {
        line.player_id
        for line in game.player_box_scores
    }
    pregame_fatigue = {
        player_id: profiles[
            player_id
        ].fatigue
        for player_id in played_ids
    }
    assessments: dict[
        str,
        PlayerRiskAssessment,
    ] = {}
    injury_events: list[InjuryEvent] = []

    for line in game.player_box_scores:
        player_id = line.player_id
        player = state.players[player_id]
        profile = profiles[player_id]
        assessment = player_risk_assessment(
            state,
            player_id,
            day_index=scheduled.day_index,
            planned_minutes=line.minutes,
            config=resolved,
        )
        assessments[player_id] = assessment
        profile.last_injury_risk = (
            assessment.probability
        )
        profile.last_risk_tier = (
            assessment.risk_tier
        )
        profile.last_risk_explanation = (
            assessment.explanation
        )

        fatigue_added = (
            float(line.minutes)
            * resolved.fatigue_per_minute
            + (
                resolved.back_to_back_fatigue_bonus
                if assessment.back_to_back
                else 0.0
            )
            + (
                resolved.overtime_fatigue_bonus
                * game.overtime_periods
            )
        )
        profile.fatigue = round(
            clamp(
                profile.fatigue
                + fatigue_added,
                0.0,
                100.0,
            ),
            2,
        )
        profile.last_game_day = int(
            scheduled.day_index
        )
        profile.last_recovery_day = int(
            scheduled.day_index
        )
        profile.recent_game_days = tuple(
            (
                *profile.recent_game_days,
                int(scheduled.day_index),
            )[-resolved.recent_window_games:]
        )
        profile.recent_minutes = tuple(
            (
                *profile.recent_minutes,
                round(float(line.minutes), 1),
            )[-resolved.recent_window_games:]
        )
        profile.last_updated_game_id = (
            scheduled.game_id
        )

        existing_issue_before_game = (
            state.injuries[player_id].status
            in PLAYABLE_INJURY_STATUSES
        )
        preferred_region = ""
        try:
            from simulation_medical_injury_v2 import (
                advance_medical_case_after_appearance,
                ensure_medical_injury_v2_state,
            )
            medical_case_before = ensure_medical_injury_v2_state(
                state
            )[player_id]
            preferred_region = str(
                medical_case_before.body_region or ""
            )
            advance_medical_case_after_appearance(
                state,
                player_id,
                day_index=scheduled.day_index,
            )
        except (ImportError, KeyError, AttributeError):
            pass

        if not state.settings.injuries_enabled:
            continue

        rng = random.Random(
            int(
                hashlib.sha256(
                    (
                        f"{seed}|{scheduled.game_id}|"
                        f"{player_id}|injury"
                    ).encode("utf-8")
                ).hexdigest()[:16],
                16,
            )
        )
        if rng.random() >= assessment.probability:
            continue

        medical_metadata: dict[str, Any] = {}
        v2_outcome = None
        try:
            from simulation_medical_injury_v2 import (
                MedicalInjuryOutcome,
                choose_medical_injury_outcome,
                register_medical_injury,
                team_games_between,
            )
            v2_outcome = choose_medical_injury_outcome(
                rng,
                existing_issue=existing_issue_before_game,
                preferred_region=preferred_region,
            )
            injury_type = v2_outcome.injury_type
            severity = v2_outcome.severity
            status = v2_outcome.status
            days = v2_outcome.days
            performance = v2_outcome.performance_multiplier
            aggravation = v2_outcome.aggravation_risk
            minutes_limit = v2_outcome.minutes_limit
            body_region = v2_outcome.body_region
            injury_grade = v2_outcome.grade
            medical_v2_available = True
        except ImportError:
            (
                injury_type,
                severity,
                status,
                days,
                performance,
                aggravation,
                minutes_limit,
            ) = choose_injury_outcome(
                rng,
                existing_issue=existing_issue_before_game,
            )
            body_region = ""
            injury_grade = ""
            medical_v2_available = False

        # Avoid creating an unplayable roster. The event still appears as a
        # questionable condition, but the team keeps enough bodies to play.
        if (
            status in UNAVAILABLE_STATUSES
            and team_available_count(
                state,
                player.team_abbreviation,
            )
            <= state.settings.minimum_game_players
        ):
            status = (
                AvailabilityStatus.QUESTIONABLE
            )
            days = min(days, 3)
            performance = 0.95
            aggravation = max(
                aggravation,
                0.18,
            )
            minutes_limit = 28.0
            injury_type = (
                "managed " + injury_type
            )
            severity = "soreness"

        expected_return = (
            int(scheduled.day_index)
            + int(days)
        )
        if status in PLAYABLE_INJURY_STATUSES:
            estimated_games = 0
        elif medical_v2_available:
            estimated_games = max(
                1,
                team_games_between(
                    state,
                    player.team_abbreviation,
                    int(scheduled.day_index),
                    expected_return,
                ),
            )
        else:
            estimated_games = max(
                1,
                int(math.ceil(days / 2.0)),
            )

        injury = state.injuries[player_id]
        injury.status = status
        injury.injury_type = injury_type
        injury.games_remaining = (
            estimated_games
        )
        injury.performance_multiplier = round(
            performance,
            4,
        )
        injury.aggravation_risk = round(
            aggravation,
            4,
        )
        injury.notes = (
            f"{severity.title()} issue after "
            f"{assessment.explanation}. "
            f"Estimated return around day "
            f"{expected_return}."
        )
        profile.expected_return_day = (
            expected_return
        )
        profile.injury_severity = severity
        profile.minutes_limit = (
            round(minutes_limit, 1)
            if minutes_limit is not None
            else None
        )
        profile.status_reason = (
            injury.notes
        )
        profile.injuries_suffered += 1

        if medical_v2_available and v2_outcome is not None:
            adjusted_outcome = MedicalInjuryOutcome(
                injury_type=injury_type,
                body_region=body_region,
                severity=severity,
                grade=injury_grade,
                status=status,
                days=int(days),
                performance_multiplier=float(performance),
                aggravation_risk=float(aggravation),
                minutes_limit=(
                    float(minutes_limit)
                    if minutes_limit is not None
                    else None
                ),
            )
            medical_metadata = register_medical_injury(
                state,
                player_id,
                adjusted_outcome,
                day_index=int(scheduled.day_index),
                event_kind=(
                    "setback"
                    if existing_issue_before_game
                    else "injury"
                ),
            )

        event = InjuryEvent(
            version=INJURY_FATIGUE_VERSION,
            season_label=(
                state.settings.season_label
            ),
            game_id=scheduled.game_id,
            day_index=int(
                scheduled.day_index
            ),
            player_id=player_id,
            player_name=player.player_name,
            team=player.team_abbreviation,
            injury_type=injury_type,
            severity=severity,
            status=status.value,
            expected_return_day=(
                expected_return
            ),
            estimated_games_missed=(
                estimated_games
            ),
            probability=(
                assessment.probability
            ),
            fatigue_before_game=round(
                pregame_fatigue[
                    player_id
                ],
                1,
            ),
            minutes_played=round(
                float(line.minutes),
                1,
            ),
            back_to_back=(
                assessment.back_to_back
            ),
            explanation=(
                assessment.explanation
            ),
        )
        injury_events.append(event)
        event_payload = asdict(event)
        event_payload.update(medical_metadata)
        health_events(state).append(
            event_payload
        )


    for team in (
        scheduled.home_team,
        scheduled.away_team,
    ):
        for player_id in state.teams[
            team
        ].roster_player_ids:
            if (
                player_id not in played_ids
                and injury_status_is_unavailable(
                    state.injuries[
                        player_id
                    ].status
                )
            ):
                profiles[
                    player_id
                ].season_games_missed += 1

    fatigue_values = list(
        pregame_fatigue.values()
    )
    return GameHealthUpdate(
        version=INJURY_FATIGUE_VERSION,
        game_id=scheduled.game_id,
        day_index=int(
            scheduled.day_index
        ),
        injury_events=tuple(
            injury_events
        ),
        recovered_player_ids=tuple(
            recovered
        ),
        high_risk_player_ids=tuple(
            sorted(
                player_id
                for player_id, assessment
                in assessments.items()
                if assessment.risk_tier
                in {"High", "Elevated"}
            )
        ),
        average_pregame_fatigue=round(
            sum(fatigue_values)
            / len(fatigue_values),
            2,
        )
        if fatigue_values
        else 0.0,
        maximum_pregame_fatigue=round(
            max(fatigue_values),
            2,
        )
        if fatigue_values
        else 0.0,
    )


def next_team_game_day(
    state: SimulationLeagueState,
    team: str,
) -> int:
    candidates = [
        int(game.day_index)
        for game in state.schedule.values()
        if (
            game.status
            == GameStatus.SCHEDULED
            and team
            in {
                game.home_team,
                game.away_team,
            }
        )
    ]
    return (
        min(candidates)
        if candidates
        else int(state.current_day_index)
    )


def player_health_report_rows(
    state: SimulationLeagueState,
    team: str,
    *,
    day_index: int | None = None,
) -> list[dict[str, Any]]:
    ensure_injury_fatigue_state(state)
    resolved_day = (
        int(day_index)
        if day_index is not None
        else next_team_game_day(
            state,
            team,
        )
    )
    team_state = state.teams[team]
    planned = (
        team_state.rotation.minutes_targets
    )
    rows: list[dict[str, Any]] = []

    for player_id in team_state.roster_player_ids:
        injury = state.injuries[player_id]
        profile = getattr(
            state,
            HEALTH_STATE_ATTRIBUTE,
        )[player_id]
        planned_minutes = float(
            planned.get(
                player_id,
                0.0,
            )
            or 0.0
        )
        assessment = player_risk_assessment(
            state,
            player_id,
            day_index=resolved_day,
            planned_minutes=planned_minutes,
        )
        stored_fatigue = round(
            clamp(float(profile.fatigue or 0.0), 0.0, 100.0),
            2,
        )
        current_fatigue = recovered_fatigue(
            profile,
            max(
                int(state.current_day_index),
                int(profile.last_recovery_day or 0),
            ),
        )
        projected_game_fatigue = round(
            clamp(float(assessment.fatigue or 0.0), 0.0, 100.0),
            2,
        )
        try:
            from simulation_medical_injury_v2 import (
                medical_case_snapshot,
            )
            medical = medical_case_snapshot(
                state,
                player_id,
                day_index=resolved_day,
            )
        except (ImportError, KeyError, AttributeError, TypeError, ValueError):
            medical = {
                "medical_phase": "Healthy",
                "recovery_progress": 100.0,
                "body_region": "—",
                "injury_grade": "—",
                "return_ramp_games": 0,
                "recurrence_count": 0,
                "setback_count": 0,
                "reinjury_risk": 0.0,
            }
        rows.append(
            {
                "player_id": player_id,
                "player": state.players[
                    player_id
                ].player_name,
                "position": state.players[
                    player_id
                ].position,
                "age": state.players[
                    player_id
                ].age,
                "status": (
                    injury.status.value
                    .replace("_", " ")
                    .title()
                ),
                "injury": (
                    injury.injury_type
                    or "None"
                ),
                # `fatigue` remains the primary display field and now means
                # load recovered through the current league day. The raw
                # postgame value and the next-game projection remain available
                # separately, so recovery is transparent rather than appearing
                # to erase accumulated workload.
                "fatigue": current_fatigue,
                "stored_fatigue": stored_fatigue,
                "current_fatigue": current_fatigue,
                "projected_fatigue": projected_game_fatigue,
                "projected_recovery": round(
                    current_fatigue - projected_game_fatigue,
                    2,
                ),
                "fatigue_projection_day": resolved_day,
                "risk": (
                    assessment.risk_tier
                ),
                "risk_probability": round(
                    assessment.probability
                    * 100.0,
                    2,
                ),
                "planned_minutes": (
                    planned_minutes
                ),
                "minutes_limit": (
                    profile.minutes_limit
                ),
                "recent_minutes": (
                    assessment.recent_minutes
                ),
                "games_missed": (
                    profile.season_games_missed
                ),
                "expected_return_day": (
                    profile.expected_return_day
                    if profile.expected_return_day
                    else medical.get("expected_return_day")
                ),
                "medical_phase": medical.get("medical_phase", "Healthy"),
                "recovery_progress": float(medical.get("recovery_progress", 100.0)),
                "body_region": medical.get("body_region", "—"),
                "injury_grade": medical.get("injury_grade", "—"),
                "return_ramp_games": int(medical.get("return_ramp_games", 0) or 0),
                "recurrence_count": int(medical.get("recurrence_count", 0) or 0),
                "setback_count": int(medical.get("setback_count", 0) or 0),
                "reinjury_risk": float(medical.get("reinjury_risk", 0.0) or 0.0),
                "explanation": (
                    assessment.explanation
                ),
            }
        )

    risk_order = {
        "High": 0,
        "Elevated": 1,
        "Moderate": 2,
        "Low": 3,
    }
    rows.sort(
        key=lambda row: (
            0
            if row["status"]
            != "Healthy"
            else 1,
            risk_order.get(
                row["risk"],
                9,
            ),
            -float(row["fatigue"]),
            row["player"],
        )
    )
    return rows


def team_health_summary(
    state: SimulationLeagueState,
    team: str,
    *,
    day_index: int | None = None,
) -> dict[str, Any]:
    rows = player_health_report_rows(
        state,
        team,
        day_index=day_index,
    )
    return {
        "team": team,
        "available": sum(
            row["status"]
            not in {"Out", "Doubtful"}
            for row in rows
        ),
        "out": sum(
            row["status"]
            in {"Out", "Doubtful"}
            for row in rows
        ),
        "limited": sum(
            row["status"]
            in {
                "Probable",
                "Questionable",
                "Day To Day",
            }
            for row in rows
        ),
        "rehab_or_return": sum(
            row.get("medical_phase")
            in {"Acute", "Rehab", "Return To Play", "Return Ramp"}
            for row in rows
        ),
        "return_ramp": sum(
            int(row.get("return_ramp_games", 0) or 0) > 0
            for row in rows
        ),
        "high_risk": sum(
            row["risk"]
            in {"High", "Elevated"}
            for row in rows
        ),
        "average_fatigue": round(
            sum(
                float(row["current_fatigue"])
                for row in rows
            )
            / max(len(rows), 1),
            1,
        ),
        "maximum_fatigue": round(
            max(
                (
                    float(row["current_fatigue"])
                    for row in rows
                ),
                default=0.0,
            ),
            1,
        ),
        "projected_average_fatigue": round(
            sum(
                float(row["projected_fatigue"])
                for row in rows
            )
            / max(len(rows), 1),
            1,
        ),
        "projected_maximum_fatigue": round(
            max(
                (
                    float(row["projected_fatigue"])
                    for row in rows
                ),
                default=0.0,
            ),
            1,
        ),
        "projection_day": (
            int(rows[0]["fatigue_projection_day"])
            if rows
            else int(state.current_day_index)
        ),
    }


def recommended_rest_player_ids(
    state: SimulationLeagueState,
    team: str,
    *,
    day_index: int,
    maximum_players: int = 2,
) -> tuple[str, ...]:
    rows = player_health_report_rows(
        state,
        team,
        day_index=day_index,
    )
    recommendations = [
        row["player_id"]
        for row in rows
        if (
            row["status"]
            not in {"Out", "Doubtful"}
            and (
                row["risk"] == "High"
                or (
                    row["risk"] == "Elevated"
                    and float(
                        row["fatigue"]
                    )
                    >= 65.0
                )
            )
        )
    ]
    return tuple(
        recommendations[
            :maximum_players
        ]
    )


def injury_fatigue_state_payload(
    state: SimulationLeagueState,
) -> dict[str, Any]:
    profiles = ensure_injury_fatigue_state(
        state
    )
    return {
        "version": INJURY_FATIGUE_VERSION,
        "profiles": {
            player_id: {
                "fatigue": round(
                    profile.fatigue,
                    2,
                ),
                "last_game_day": (
                    profile.last_game_day
                ),
                "last_recovery_day": (
                    profile.last_recovery_day
                ),
                "expected_return_day": (
                    profile.expected_return_day
                ),
                "minutes_limit": (
                    profile.minutes_limit
                ),
                "games_missed": (
                    profile.season_games_missed
                ),
                "injuries_suffered": (
                    profile.injuries_suffered
                ),
            }
            for player_id, profile
            in sorted(profiles.items())
        },
        "event_count": len(
            health_events(state)
        ),
    }


def league_injury_summary(
    state: SimulationLeagueState,
) -> dict[str, Any]:
    ensure_injury_fatigue_state(state)
    current_events = [
        event
        for event in health_events(state)
        if event.get("season_label")
        == state.settings.season_label
    ]
    return {
        "version": INJURY_FATIGUE_VERSION,
        "season_label": (
            state.settings.season_label
        ),
        "injury_events": len(
            current_events
        ),
        "players_out": sum(
            injury_status_is_unavailable(
                injury.status
            )
            for injury in state.injuries.values()
        ),
        "players_limited": sum(
            injury.status
            in PLAYABLE_INJURY_STATUSES
            for injury in state.injuries.values()
        ),
        "back_to_back_events": sum(
            bool(
                event.get(
                    "back_to_back",
                    False,
                )
            )
            for event in current_events
        ),
        "major_events": sum(
            event.get("severity")
            == "major"
            for event in current_events
        ),
    }


def run_self_test() -> dict[str, Any]:
    runtime_base = load_runtime_data()
    league_state = create_league_state(
        runtime_base
    )
    runtime = build_state_runtime(
        runtime_base,
        league_state,
    )
    from simulation_league_state_v1 import (
        create_simulation_league_state,
    )

    state = create_simulation_league_state(
        runtime,
        league_state,
    )
    profiles = ensure_injury_fatigue_state(
        state
    )
    fast_path_profiles = (
        ensure_injury_fatigue_state(
            state
        )
    )
    player_id = next(
        player_id
        for player_id, player
        in state.players.items()
        if not player.synthetic
        and player.team_abbreviation
    )
    team = state.players[
        player_id
    ].team_abbreviation
    profiles[player_id].fatigue = 72.0
    profiles[player_id].last_game_day = 10
    profiles[player_id].recent_game_days = (
        7,
        9,
        10,
    )
    profiles[player_id].recent_minutes = (
        34.0,
        36.0,
        37.0,
    )

    rested = copy.deepcopy(state)
    b2b = copy.deepcopy(state)
    rested_assessment = (
        player_risk_assessment(
            rested,
            player_id,
            day_index=13,
            planned_minutes=36.0,
        )
    )
    b2b_assessment = (
        player_risk_assessment(
            b2b,
            player_id,
            day_index=11,
            planned_minutes=36.0,
        )
    )
    low_minutes = player_risk_assessment(
        b2b,
        player_id,
        day_index=11,
        planned_minutes=20.0,
    )

    checks = {
        "version_is_current": (
            INJURY_FATIGUE_VERSION.endswith(
                "2026-08-09"
            )
        ),
        "health_profiles_cover_all_players": (
            set(profiles)
            == set(state.players)
        ),
        "health_fast_path_reuses_mapping": (
            fast_path_profiles is profiles
        ),
        "fatigue_is_bounded": all(
            0.0 <= profile.fatigue <= 100.0
            for profile in profiles.values()
        ),
        "durability_is_bounded": all(
            0.50 <= profile.durability <= 1.15
            for profile in profiles.values()
        ),
        "back_to_back_risk_exceeds_rested_risk": (
            b2b_assessment.probability
            > rested_assessment.probability
        ),
        "heavy_minutes_raise_risk": (
            b2b_assessment.probability
            > low_minutes.probability
        ),
        "risk_explanation_names_schedule": (
            "back-to-back"
            in b2b_assessment.explanation
        ),
        "fatigue_recovers_with_rest": (
            projected_fatigue(
                state,
                player_id,
                13,
            )
            < projected_fatigue(
                state,
                player_id,
                11,
            )
        ),
        "state_remains_valid": bool(
            validate_simulation_league_state(
                state
            )
        ),
        "team_summary_is_available": (
            team_health_summary(
                state,
                team,
                day_index=11,
            )["available"]
            >= state.settings.minimum_game_players
        ),
    }
    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]
    report = {
        "script": INJURY_FATIGUE_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "sample": {
            "player_id": player_id,
            "team": team,
            "rested": asdict(
                rested_assessment
            ),
            "back_to_back": asdict(
                b2b_assessment
            ),
            "low_minutes": asdict(
                low_minutes
            ),
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
            "Injury and fatigue self-test failed: "
            + ", ".join(failed)
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    args = parser.parse_args()

    if args.self_test:
        print(
            json.dumps(
                run_self_test(),
                indent=2,
            )
        )
        print(
            "\nSIMULATION INJURY AND FATIGUE "
            "V1 SELF-TEST PASSED"
        )
        return 0

    print(
        json.dumps(
            {
                "script": (
                    INJURY_FATIGUE_VERSION
                )
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
