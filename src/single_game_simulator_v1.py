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
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import (  # noqa: E402
    load_runtime_data,
    normalize_player_id,
    normalize_team,
)
from mutable_league_state_v1 import (  # noqa: E402
    create_league_state,
)
from simulation_league_state_v1 import (  # noqa: E402
    AvailabilityStatus,
    CompletedGame,
    GameStatus,
    PlayerBoxScore,
    ScheduledGame,
    SimulationLeagueState,
    SimulationLeagueStateError,
    add_scheduled_games,
    create_simulation_league_state,
    record_completed_game,
    set_player_injury,
    validate_completed_game,
    validate_simulation_league_state,
)
from simulation_injury_fatigue_v1 import (  # noqa: E402
    INJURY_FATIGUE_VERSION,
    fatigue_performance_multiplier,
    injury_status_is_unavailable,
    player_minutes_cap,
    prepare_health_for_game,
    process_completed_game_health,
)
from state_runtime_adapter_v1 import (  # noqa: E402
    build_state_runtime,
)
from simulation_player_stat_profiles_v1 import (  # noqa: E402
    PROFILE_LOADER_VERSION,
    load_player_stat_profiles,
    player_id_by_name,
    player_stat_factor,
)
from simulation_player_stat_fingerprints_v3 import (  # noqa: E402
    FINGERPRINT_VERSION,
    build_player_stat_fingerprint,
    expected_secondary_count,
)


ENGINE_VERSION = "single-game-simulator-v1.6-2026-08-08"
REALISM_CALIBRATION_VERSION = "game-season-realism-calibration-v1-2026-08-13"
POSTSEASON_REALISM_CALIBRATION_VERSION = "postseason-realism-environment-v1-2026-08-13"
PLAYER_STAT_FINGERPRINT_VERSION = FINGERPRINT_VERSION
SHOOTING_CALIBRATION_VERSION = (
    "shooting-efficiency-calibration-v1-2026-08-10"
)
SELF_TEST_REPORT = (
    OUTPUTS / "single_game_simulator_v1_self_test.json"
)
DEMO_REPORT = (
    OUTPUTS / "single_game_simulator_v1_demo.json"
)


class SingleGameSimulationError(RuntimeError):
    """Raised when a scheduled game cannot be simulated."""


@dataclass(frozen=True)
class GameSimulationConfig:
    base_points_per_team: float = 112.0
    neutral_rating: float = 77.0
    offense_rating_weight: float = 1.05
    opponent_rating_weight: float = 0.62
    home_court_points: float = 2.4
    base_pace: float = 99.0
    pace_standard_deviation: float = 3.0
    pace_point_weight: float = 0.58
    team_score_standard_deviation: float = 8.5
    minimum_regulation_score: int = 78
    maximum_regulation_score: int = 148
    minimum_rotation_players: int = 5
    maximum_rotation_players: int = 10


    # Evidence-calibrated box-score environment.
    free_throw_make_multiplier: float = 0.935
    three_make_multiplier: float = 1.000
    field_goal_attempt_multiplier: float = 0.988
    three_attempt_multiplier: float = 0.904
    free_throw_attempt_multiplier: float = 0.843
    rebound_environment_multiplier: float = 1.024
    assist_environment_multiplier: float = 0.928
    steal_environment_multiplier: float = 1.145
    block_environment_multiplier: float = 1.040
    turnover_environment_multiplier: float = 1.077
    foul_environment_multiplier: float = 1.034

def postseason_game_config() -> GameSimulationConfig:
    return GameSimulationConfig(
        base_points_per_team=103.35,
        free_throw_make_multiplier=0.940,
        three_make_multiplier=0.985,
        field_goal_attempt_multiplier=1.020,
        three_attempt_multiplier=1.000,
        free_throw_attempt_multiplier=0.862,
        rebound_environment_multiplier=1.000,
        assist_environment_multiplier=0.880,
        steal_environment_multiplier=1.080,
        block_environment_multiplier=1.130,
        turnover_environment_multiplier=1.076,
        foul_environment_multiplier=1.150,
    )


def resolve_game_environment_config(
    state: SimulationLeagueState,
    explicit_config: GameSimulationConfig | None,
) -> GameSimulationConfig:
    if explicit_config is not None:
        return explicit_config
    phase_object = getattr(state, "phase", "")
    phase = str(getattr(phase_object, "value", phase_object) or "").strip().lower()
    if phase in {"play_in", "playoffs"}:
        return postseason_game_config()
    return GameSimulationConfig()


@dataclass(frozen=True)
class TeamGamePlan:
    team_abbreviation: str
    player_ids: tuple[str, ...]
    starter_ids: tuple[str, ...]
    minutes: dict[str, float]
    effective_ratings: dict[str, float]
    weighted_team_rating: float


@dataclass(frozen=True)
class GameSimulationMetadata:
    engine_version: str
    seed: int
    game_id: str
    home_team: str
    away_team: str
    pace: float
    home_team_rating: float
    away_team_rating: float
    expected_home_score: float
    expected_away_score: float
    home_score: int
    away_score: int
    overtime_periods: int
    home_win_probability: float


@dataclass(frozen=True)
class SimulatedGame:
    game: CompletedGame
    metadata: GameSimulationMetadata
    committed: bool
    health_update: Any | None = None


@dataclass(frozen=True)
class PlayerScoringProfile:
    points: int
    field_goals_made: int
    field_goals_attempted: int
    three_pointers_made: int
    three_pointers_attempted: int
    free_throws_made: int
    free_throws_attempted: int


POSITION_STAT_MULTIPLIERS: dict[str, dict[str, float]] = {
    "PG": {
        "rebounds": 0.58,
        "assists": 2.00,
        "steals": 1.12,
        "blocks": 0.38,
        "turnovers": 1.22,
        "fouls": 0.78,
    },
    "SG": {
        "rebounds": 0.72,
        "assists": 1.34,
        "steals": 1.08,
        "blocks": 0.50,
        "turnovers": 1.05,
        "fouls": 0.88,
    },
    "SF": {
        "rebounds": 1.00,
        "assists": 0.96,
        "steals": 1.00,
        "blocks": 0.58,
        "turnovers": 0.96,
        "fouls": 1.00,
    },
    "PF": {
        "rebounds": 1.48,
        "assists": 0.72,
        "steals": 0.88,
        "blocks": 1.24,
        "turnovers": 0.88,
        "fouls": 1.18,
    },
    "C": {
        "rebounds": 1.78,
        "assists": 0.58,
        "steals": 0.76,
        "blocks": 1.72,
        "turnovers": 0.84,
        "fouls": 1.34,
    },
}


def clamp(
    value: float,
    minimum: float,
    maximum: float,
) -> float:
    return max(minimum, min(maximum, value))


def stable_seed(
    state: SimulationLeagueState,
    game_id: str,
    explicit_seed: int | None,
) -> int:
    if explicit_seed is not None:
        return int(explicit_seed)

    payload = (
        f"{state.settings.random_seed}|"
        f"{state.settings.season_label}|"
        f"{game_id}"
    ).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(
        digest[:8],
        byteorder="big",
        signed=False,
    )


def state_result_signature(
    state: SimulationLeagueState,
) -> dict[str, Any]:
    return {
        "phase": state.phase.value,
        "current_day_index": state.current_day_index,
        "schedule": tuple(
            sorted(
                (
                    game_id,
                    game.status.value,
                )
                for game_id, game
                in state.schedule.items()
            )
        ),
        "completed_games": tuple(
            sorted(state.completed_games)
        ),
        "standings": tuple(
            sorted(
                (
                    team,
                    standing.games_played,
                    standing.wins,
                    standing.losses,
                    standing.points_for,
                    standing.points_against,
                )
                for team, standing
                in state.standings.items()
            )
        ),
        "player_totals": tuple(
            sorted(
                (
                    player_id,
                    totals.games_played,
                    totals.games_started,
                    totals.minutes,
                    totals.points,
                )
                for player_id, totals
                in state.player_season_totals.items()
                if totals.games_played
            )
        ),
    }


def effective_player_rating(
    state: SimulationLeagueState,
    player_id: str,
) -> float:
    player_id = normalize_player_id(player_id)
    player = state.players[player_id]
    injury = state.injuries[player_id]

    if injury_status_is_unavailable(
        injury.status
    ):
        return 0.0

    injury_multiplier = (
        injury.performance_multiplier
        if injury.status
        != AvailabilityStatus.HEALTHY
        else 1.0
    )
    fatigue_multiplier = (
        fatigue_performance_multiplier(
            state,
            player_id,
            day_index=(
                getattr(
                    state,
                    "_active_simulation_day",
                    None,
                )
            ),
        )
    )
    return round(
        player.overall_rating
        * injury_multiplier
        * fatigue_multiplier,
        4,
    )


def rotation_priority(
    state: SimulationLeagueState,
    team: str,
) -> dict[str, int]:
    team_state = state.teams[team]
    ordered = [
        *team_state.rotation.rotation_player_ids,
        *team_state.roster_player_ids,
    ]
    result: dict[str, int] = {}

    for player_id in ordered:
        if player_id not in result:
            result[player_id] = len(result)

    return result


def available_team_players(
    state: SimulationLeagueState,
    team: str,
    sit_player_ids: set[str],
) -> list[str]:
    team = normalize_team(team)
    team_state = state.teams.get(team)

    if team_state is None:
        raise SingleGameSimulationError(
            f"Unknown simulation team: {team}."
        )

    priority = rotation_priority(state, team)
    available = []

    for player_id in team_state.roster_player_ids:
        if player_id in sit_player_ids:
            continue

        injury = state.injuries[player_id]
        if injury_status_is_unavailable(
            injury.status
        ):
            continue

        available.append(player_id)

    available.sort(
        key=lambda player_id: (
            priority.get(player_id, 10_000),
            -effective_player_rating(
                state,
                player_id,
            ),
            state.players[
                player_id
            ].player_name.casefold(),
            player_id,
        )
    )
    return available


def select_game_rotation(
    state: SimulationLeagueState,
    team: str,
    *,
    sit_player_ids: set[str],
    config: GameSimulationConfig,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    available = available_team_players(
        state,
        team,
        sit_player_ids,
    )

    if (
        len(available)
        < config.minimum_rotation_players
    ):
        raise SingleGameSimulationError(
            f"{team} has only {len(available)} available "
            "players. A game requires at least "
            f"{config.minimum_rotation_players}."
        )

    team_state = state.teams[team]
    original_starters = (
        team_state.rotation.starter_ids
    )
    starter_ids = [
        player_id
        for player_id in original_starters
        if player_id in available
    ]

    for player_id in available:
        if len(starter_ids) >= 5:
            break

        if player_id not in starter_ids:
            starter_ids.append(player_id)

    maximum_players = min(
        config.maximum_rotation_players,
        len(available),
    )
    rotation_ids = available[:maximum_players]

    for player_id in starter_ids:
        if player_id not in rotation_ids:
            rotation_ids.append(player_id)

    rotation_ids.sort(
        key=lambda player_id: (
            0 if player_id in starter_ids else 1,
            available.index(player_id),
        )
    )
    rotation_ids = rotation_ids[
        :config.maximum_rotation_players
    ]

    return (
        tuple(rotation_ids),
        tuple(starter_ids[:5]),
    )


def allocate_integer_units(
    total_units: int,
    ordered_ids: tuple[str, ...],
    weights: dict[str, float],
) -> dict[str, int]:
    if total_units < 0:
        raise SingleGameSimulationError(
            "Allocation total cannot be negative."
        )

    if not ordered_ids:
        if total_units:
            raise SingleGameSimulationError(
                "Cannot allocate a positive total "
                "without recipients."
            )
        return {}

    positive_weights = {
        player_id: max(
            float(weights.get(player_id, 0.0)),
            0.000001,
        )
        for player_id in ordered_ids
    }
    total_weight = sum(
        positive_weights.values()
    )
    raw = {
        player_id: (
            total_units
            * positive_weights[player_id]
            / total_weight
        )
        for player_id in ordered_ids
    }
    floors = {
        player_id: math.floor(value)
        for player_id, value in raw.items()
    }
    remaining = (
        total_units - sum(floors.values())
    )
    order = sorted(
        ordered_ids,
        key=lambda player_id: (
            -(
                raw[player_id]
                - floors[player_id]
            ),
            ordered_ids.index(player_id),
        ),
    )

    for player_id in order[:remaining]:
        floors[player_id] += 1

    return floors


def allocate_bounded_integer_units(
    total_units: int,
    ordered_ids: tuple[str, ...],
    weights: dict[str, float],
    caps: dict[str, int],
) -> dict[str, int]:
    if total_units > sum(
        max(
            0,
            int(
                caps.get(
                    player_id,
                    total_units,
                )
            ),
        )
        for player_id in ordered_ids
    ):
        raise SingleGameSimulationError(
            "Minute caps cannot absorb the "
            "required team total."
        )

    output = {
        player_id: 0
        for player_id in ordered_ids
    }
    remaining_ids = list(
        ordered_ids
    )
    remaining_units = int(
        total_units
    )

    while remaining_ids:
        proposed = allocate_integer_units(
            remaining_units,
            tuple(remaining_ids),
            {
                player_id: weights[
                    player_id
                ]
                for player_id
                in remaining_ids
            },
        )
        capped = [
            player_id
            for player_id in remaining_ids
            if proposed[player_id]
            > int(
                caps.get(
                    player_id,
                    total_units,
                )
            )
        ]

        if not capped:
            for player_id in remaining_ids:
                output[player_id] = (
                    proposed[player_id]
                )
            break

        for player_id in capped:
            player_cap = int(
                caps.get(
                    player_id,
                    total_units,
                )
            )
            output[player_id] = player_cap
            remaining_units -= player_cap
            remaining_ids.remove(
                player_id
            )

    if sum(output.values()) != total_units:
        raise SingleGameSimulationError(
            "Bounded allocation did not "
            "reconcile to the team total."
        )

    return output


def allocate_minutes(
    state: SimulationLeagueState,
    team: str,
    rotation_ids: tuple[str, ...],
    starter_ids: tuple[str, ...],
    *,
    overtime_periods: int,
) -> dict[str, float]:
    total_minutes = (
        state.settings.regulation_minutes * 5
        + state.settings.overtime_minutes
        * 5
        * overtime_periods
    )
    if not rotation_ids:
        raise SingleGameSimulationError(
            "Cannot allocate minutes without "
            "available rotation players."
        )

    starter_set = set(starter_ids)
    saved_targets = (
        state.teams[
            team
        ].rotation.minutes_targets
    )
    weights: dict[str, float] = {}

    for player_id in rotation_ids:
        saved = float(
            saved_targets.get(
                player_id,
                0.0,
            )
            or 0.0
        )
        fallback = (
            30.0
            if player_id in starter_set
            else 18.0
        )
        # A valid saved target already belongs to a 240-minute team
        # plan. Applying the starter/bench fallback as a floor would
        # inflate low-minute bench roles and proportionally reduce
        # stars. Use the fallback only when no saved target exists.
        weights[player_id] = (
            saved
            if saved > 0.0
            else max(
                fallback,
                1.0,
            )
        )

    # Normal rotations keep regular-season workloads below 38 minutes.
    # Emergency short-handed rotations may exceed that limit only when
    # required to reconcile the NBA team-minute total.
    average_required = (
        total_minutes
        / len(rotation_ids)
    )
    maximum_minutes = min(
        (
            state.settings
            .regulation_minutes
            + state.settings
            .overtime_minutes
            * overtime_periods
        ),
        max(
            38.0
            + 2.0 * overtime_periods,
            math.ceil(
                average_required
            )
            + 4.0,
        ),
    )
    day_index = int(
        getattr(
            state,
            "_active_simulation_day",
            state.current_day_index,
        )
    )
    upper_bounds = {
        player_id: int(
            round(
                player_minutes_cap(
                    state,
                    player_id,
                    day_index=day_index,
                    default_maximum=(
                        maximum_minutes
                    ),
                )
                * 10
            )
        )
        for player_id in rotation_ids
    }

    # A short-handed team may not have enough unrestricted minutes to
    # reconcile 240. Relax fatigue caps conservatively before failing.
    required_tenths = int(
        round(total_minutes * 10)
    )
    if sum(
        upper_bounds.values()
    ) < required_tenths:
        upper_bounds = {
            player_id: int(
                round(
                    maximum_minutes * 10
                )
            )
            for player_id in rotation_ids
        }

    minute_tenths = (
        allocate_bounded_integer_units(
            required_tenths,
            rotation_ids,
            weights,
            upper_bounds,
        )
    )
    return {
        player_id: (
            minute_tenths[
                player_id
            ]
            / 10.0
        )
        for player_id in rotation_ids
    }


def build_team_game_plan(
    state: SimulationLeagueState,
    team: str,
    *,
    sit_player_ids: set[str],
    overtime_periods: int,
    config: GameSimulationConfig,
) -> TeamGamePlan:
    rotation_ids, starter_ids = (
        select_game_rotation(
            state,
            team,
            sit_player_ids=sit_player_ids,
            config=config,
        )
    )
    minutes = allocate_minutes(
        state,
        team,
        rotation_ids,
        starter_ids,
        overtime_periods=overtime_periods,
    )
    effective_ratings = {
        player_id: effective_player_rating(
            state,
            player_id,
        )
        for player_id in rotation_ids
    }
    total_minutes = sum(minutes.values())
    weighted_rating = sum(
        minutes[player_id]
        * effective_ratings[player_id]
        for player_id in rotation_ids
    ) / total_minutes

    return TeamGamePlan(
        team_abbreviation=team,
        player_ids=rotation_ids,
        starter_ids=starter_ids,
        minutes=minutes,
        effective_ratings=effective_ratings,
        weighted_team_rating=round(
            weighted_rating,
            4,
        ),
    )


def logistic_win_probability(
    rating_difference: float,
    home_court_points: float,
) -> float:
    point_edge = (
        rating_difference * 1.55
        + home_court_points
    )
    return 1.0 / (
        1.0 + math.exp(-point_edge / 6.5)
    )


def regulation_score_expectations(
    home_plan: TeamGamePlan,
    away_plan: TeamGamePlan,
    *,
    pace: float,
    config: GameSimulationConfig,
) -> tuple[float, float]:
    pace_adjustment = (
        pace - config.base_pace
    ) * config.pace_point_weight
    home_rating = (
        home_plan.weighted_team_rating
        - config.neutral_rating
    )
    away_rating = (
        away_plan.weighted_team_rating
        - config.neutral_rating
    )

    expected_home = (
        config.base_points_per_team
        + config.home_court_points
        + config.offense_rating_weight
        * home_rating
        - config.opponent_rating_weight
        * away_rating
        + pace_adjustment
    )
    expected_away = (
        config.base_points_per_team
        + config.offense_rating_weight
        * away_rating
        - config.opponent_rating_weight
        * home_rating
        + pace_adjustment
    )
    return expected_home, expected_away


def simulate_scores(
    rng: random.Random,
    home_plan: TeamGamePlan,
    away_plan: TeamGamePlan,
    *,
    config: GameSimulationConfig,
) -> tuple[
    float,
    float,
    float,
    int,
    int,
    int,
]:
    pace = clamp(
        rng.gauss(
            config.base_pace,
            config.pace_standard_deviation,
        ),
        90.0,
        108.0,
    )
    expected_home, expected_away = (
        regulation_score_expectations(
            home_plan,
            away_plan,
            pace=pace,
            config=config,
        )
    )
    shared_game_environment = rng.gauss(
        0.0,
        3.2,
    )
    home_score = round(
        expected_home
        + shared_game_environment
        + rng.gauss(
            0.0,
            config.team_score_standard_deviation,
        )
    )
    away_score = round(
        expected_away
        + shared_game_environment
        + rng.gauss(
            0.0,
            config.team_score_standard_deviation,
        )
    )
    home_score = int(
        clamp(
            home_score,
            config.minimum_regulation_score,
            config.maximum_regulation_score,
        )
    )
    away_score = int(
        clamp(
            away_score,
            config.minimum_regulation_score,
            config.maximum_regulation_score,
        )
    )

    overtime_periods = 0
    while home_score == away_score:
        overtime_periods += 1
        home_score += rng.randint(7, 16)
        away_score += rng.randint(7, 16)

    return (
        round(pace, 2),
        round(expected_home, 2),
        round(expected_away, 2),
        home_score,
        away_score,
        overtime_periods,
    )


PROFILE_FACTOR_INFLUENCE: dict[str, float] = {
    "points": 0.55,
    "rebounds": 1.00,
    "assists": 1.00,
    "steals": 0.85,
    "blocks": 0.90,
    "turnovers": 0.75,
    "fouls": 0.50,
}


def moderated_player_stat_factor(
    player_id: str,
    stat_name: str,
    *,
    state: SimulationLeagueState | None = None,
) -> float:
    raw_factor = None

    if state is not None:
        player = state.players.get(
            normalize_player_id(player_id)
        )
        if player is not None:
            candidate = player.stat_factors.get(
                stat_name
            )
            if candidate is not None:
                try:
                    candidate = float(candidate)
                except (TypeError, ValueError):
                    candidate = None
                if (
                    candidate is not None
                    and math.isfinite(candidate)
                    and candidate > 0
                ):
                    raw_factor = candidate

    if raw_factor is None:
        raw_factor = player_stat_factor(
            player_id,
            stat_name,
            default=1.0,
        )
    influence = PROFILE_FACTOR_INFLUENCE.get(
        stat_name,
        1.0,
    )
    adjusted = 1.0 + influence * (
        raw_factor - 1.0
    )
    limits = {
        "points": (0.65, 1.55),
        "rebounds": (0.40, 2.25),
        "assists": (0.35, 3.50),
        "steals": (0.45, 2.10),
        "blocks": (0.30, 3.75),
        "turnovers": (0.55, 1.90),
        "fouls": (0.70, 1.45),
    }
    minimum, maximum = limits.get(
        stat_name,
        (0.35, 3.50),
    )
    return clamp(
        adjusted,
        minimum,
        maximum,
    )


def profile_adjusted_stat_multiplier(
    player_id: str,
    position: str,
    stat_name: str,
    *,
    state: SimulationLeagueState | None = None,
) -> float:
    return (
        position_stat_multiplier(
            position,
            stat_name,
        )
        * moderated_player_stat_factor(
            player_id,
            stat_name,
            state=state,
        )
    )


def baseline_points_per_36(
    state: SimulationLeagueState,
    player_id: str,
) -> float:
    player = state.players[
        player_id
    ]
    baseline = getattr(
        player,
        "baseline_per_36",
        {},
    )
    raw = (
        baseline.get(
            "points_per_36"
        )
        if isinstance(
            baseline,
            dict,
        )
        else None
    )

    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = (
            12.0
            + max(
                0.0,
                player.overall_rating
                - 70.0,
            )
            * 0.62
        )

    if not math.isfinite(value):
        value = 16.0

    return clamp(
        value,
        4.0,
        38.0,
    )


def usage_weights(
    rng: random.Random,
    plan: TeamGamePlan,
    *,
    state: SimulationLeagueState | None = None,
) -> dict[str, float]:
    if state is None:
        raise SingleGameSimulationError(
            "Player scoring allocation requires "
            "the permanent simulation state."
        )

    minute_weighted_average = (
        sum(
            plan.minutes[player_id]
            * plan.effective_ratings[player_id]
            for player_id
            in plan.player_ids
        )
        / sum(plan.minutes.values())
    )
    weights: dict[str, float] = {}

    for player_id in plan.player_ids:
        player = state.players[
            player_id
        ]
        rating_edge = (
            plan.effective_ratings[
                player_id
            ]
            - minute_weighted_average
        )
        baseline_expectation = (
            baseline_points_per_36(
                state,
                player_id,
            )
            * plan.minutes[
                player_id
            ]
            / 36.0
        )
        health_adjustment = clamp(
            plan.effective_ratings[
                player_id
            ]
            / max(
                player.overall_rating,
                1.0,
            ),
            0.82,
            1.05,
        )
        rating_adjustment = clamp(
            1.0
            + rating_edge * 0.006,
            0.90,
            1.10,
        )
        game_variation = rng.uniform(
            0.90,
            1.10,
        )
        weights[player_id] = max(
            0.25,
            baseline_expectation
            * health_adjustment
            * rating_adjustment
            * game_variation,
        )

    return weights


def _scoring_components_pre_realism_v1_0_3(
    rng: random.Random,
    *,
    points: int,
    position: str,
    overall_rating: float,
    player_id: str | None = None,
    state: SimulationLeagueState | None = None,
    minutes: float | None = None,
    pace_scale: float = 1.0,
) -> tuple[int, int, int, int, int, int]:
    if points < 0:
        raise SingleGameSimulationError(
            "Player points cannot be negative."
        )

    # Preserve the standalone V1 calibration path used by the existing
    # shooting validator. Live game simulation supplies player_id/state and
    # uses the persistent Player Statistical Fingerprint V2 path below.
    if state is None or player_id is None or player_id not in state.players:
        guard_or_wing = any(
            token in position
            for token in (
                "PG",
                "SG",
                "SF",
            )
        )
        center = "C" in position
        three_share = (
            0.35
            if guard_or_wing
            else 0.20
            if center
            else 0.28
        )
        desired_threes = int(
            round(
                points
                * three_share
                / 3.0
                + rng.uniform(-0.7, 0.7)
            )
        )
        three_made = max(
            0,
            min(points // 3, desired_threes),
        )
        remaining = points - 3 * three_made

        possible_free_throws = [
            value
            for value in range(
                remaining % 2,
                min(remaining, 10) + 1,
                2,
            )
        ]
        free_throws_made = (
            rng.choice(possible_free_throws)
            if possible_free_throws
            else 0
        )
        two_made = (
            remaining - free_throws_made
        ) // 2

        three_target = clamp(
            0.335
            + (overall_rating - 67.0) * 0.0022
            + (
                0.005
                if guard_or_wing
                else -0.010
                if center
                else 0.0
            ),
            0.28,
            0.445,
        )
        two_target = clamp(
            0.500
            + (overall_rating - 67.0) * 0.0035
            + (0.025 if center else 0.0),
            0.44,
            0.67,
        )
        free_throw_target = clamp(
            0.735
            + (overall_rating - 67.0) * 0.0040
            + (
                0.015
                if guard_or_wing
                else -0.020
                if center
                else 0.0
            ),
            0.62,
            0.94,
        )

        three_game_target = clamp(
            three_target + rng.uniform(-0.035, 0.035),
            0.24,
            0.50,
        )
        two_game_target = clamp(
            two_target + rng.uniform(-0.035, 0.035),
            0.40,
            0.72,
        )
        free_throw_game_target = clamp(
            free_throw_target + rng.uniform(-0.025, 0.025),
            0.55,
            0.97,
        )

        def attempts_from_makes(
            made: int,
            target_percentage: float,
            *,
            allow_zero_make_attempt: bool = False,
        ) -> int:
            if made <= 0:
                if (
                    allow_zero_make_attempt
                    and points >= 12
                    and rng.random() < 0.55
                ):
                    return 1
                return 0

            expected_attempts = made / target_percentage
            lower = math.floor(expected_attempts)
            fractional = expected_attempts - lower
            attempts = lower + int(rng.random() < fractional)
            return max(made, attempts)

        three_attempted = attempts_from_makes(
            three_made,
            three_game_target,
            allow_zero_make_attempt=True,
        )
        two_attempted = attempts_from_makes(
            two_made,
            two_game_target,
        )
        free_throws_attempted = attempts_from_makes(
            free_throws_made,
            free_throw_game_target,
        )
    else:
        player = state.players[player_id]
        fingerprint = build_player_stat_fingerprint(player)
        resolved_minutes = clamp(
            float(minutes if minutes is not None else 24.0),
            0.0,
            60.0,
        )
        resolved_pace = clamp(float(pace_scale), 0.82, 1.20)

        # Player identity drives shot mix. Historical/persistent per-36
        # attempt rates are the anchor, while game-level variation keeps
        # identical box scores from repeating mechanically.
        expected_three_attempts = (
            fingerprint.three_attempts_per_36
            * resolved_minutes
            / 36.0
            * resolved_pace
            * rng.uniform(0.82, 1.18)
        )
        expected_free_throw_attempts = (
            fingerprint.free_throw_attempts_per_36
            * resolved_minutes
            / 36.0
            * resolved_pace
            * rng.uniform(0.78, 1.22)
        )

        three_game_target = clamp(
            fingerprint.three_point_percentage
            + rng.uniform(-0.030, 0.030),
            0.18,
            0.62,
        )
        two_game_target = clamp(
            fingerprint.two_point_percentage
            + rng.uniform(-0.030, 0.030),
            0.34,
            0.78,
        )
        free_throw_game_target = clamp(
            fingerprint.free_throw_percentage
            + rng.uniform(-0.022, 0.022),
            0.40,
            0.99,
        )

        target_three_made = (
            expected_three_attempts
            * three_game_target
        )
        target_free_throws_made = (
            expected_free_throw_attempts
            * free_throw_game_target
        )
        target_two_made = max(
            0.0,
            (
                points
                - 3.0 * target_three_made
                - target_free_throws_made
            )
            / 2.0,
        )

        # Find an exact integer scoring decomposition that sums to the
        # already-allocated player points while remaining close to the
        # player's own 3-point and foul-drawing fingerprint.
        candidates: list[tuple[float, int, int, int]] = []
        maximum_three_made = min(points // 3, 12)
        maximum_ft_made = min(points, 18)
        for candidate_three in range(maximum_three_made + 1):
            remainder_after_three = points - 3 * candidate_three
            for candidate_ft in range(
                0,
                min(maximum_ft_made, remainder_after_three) + 1,
            ):
                remaining = remainder_after_three - candidate_ft
                if remaining < 0 or remaining % 2:
                    continue
                candidate_two = remaining // 2
                three_scale = max(1.0, math.sqrt(target_three_made + 0.5))
                ft_scale = max(1.0, math.sqrt(target_free_throws_made + 0.5))
                two_scale = max(1.0, math.sqrt(target_two_made + 0.5))
                cost = (
                    ((candidate_three - target_three_made) / three_scale) ** 2
                    + 0.90
                    * ((candidate_ft - target_free_throws_made) / ft_scale) ** 2
                    + 0.18
                    * ((candidate_two - target_two_made) / two_scale) ** 2
                    + rng.uniform(0.0, 0.025)
                )
                candidates.append(
                    (cost, candidate_three, candidate_ft, candidate_two)
                )

        if not candidates:
            three_made = 0
            free_throws_made = points % 2
            two_made = (points - free_throws_made) // 2
        else:
            _, three_made, free_throws_made, two_made = min(
                candidates,
                key=lambda item: item[0],
            )

        def volume_anchored_attempts(
            made: int,
            volume_target: float,
            pct_target: float,
            *,
            maximum: int,
            enforce_hot_shooting_guard: bool = True,
        ) -> int:
            efficiency_target = (
                made / max(pct_target, 0.08)
                if made > 0
                else 0.0
            )
            blended = (
                0.68 * max(0.0, volume_target)
                + 0.32 * efficiency_target
            )
            standard_deviation = max(
                0.65,
                math.sqrt(max(volume_target, 0.5)) * 0.32,
            )
            attempts = int(round(rng.gauss(blended, standard_deviation)))
            attempts = max(made, attempts)

            # The 72% hot-shooting guard is appropriate for field goals,
            # but it must not be applied to free throws. A player can
            # legitimately go 2-for-2, 4-for-4, etc. Applying the field-goal
            # guard to FTs forced high-skill shooters toward ~60-70% and
            # artificially inflated their attempt volume.
            if made > 0 and enforce_hot_shooting_guard:
                maximum_hot_pct = clamp(
                    pct_target + 0.19,
                    0.42,
                    0.72,
                )
                attempts = max(
                    attempts,
                    int(math.ceil(made / maximum_hot_pct)),
                )
            return int(clamp(attempts, made, maximum))

        three_attempted = volume_anchored_attempts(
            three_made,
            expected_three_attempts,
            three_game_target,
            maximum=18,
        )
        free_throws_attempted = volume_anchored_attempts(
            free_throws_made,
            expected_free_throw_attempts,
            free_throw_game_target,
            maximum=22,
            enforce_hot_shooting_guard=False,
        )
        two_attempted = volume_anchored_attempts(
            two_made,
            (
                two_made / max(two_game_target, 0.20)
                if two_made > 0
                else max(0.0, resolved_minutes / 14.0)
            ),
            two_game_target,
            maximum=28,
        )

    field_goals_made = (
        two_made + three_made
    )
    field_goals_attempted = (
        two_attempted + three_attempted
    )

    return (
        field_goals_made,
        field_goals_attempted,
        three_made,
        three_attempted,
        free_throws_made,
        free_throws_attempted,
    )


_REALISM_V103_SCORING_WRAPPER = True


def _realism_stochastic_round(value: float, rng) -> int:
    value = max(0.0, float(value))
    lower = int(value)
    fraction = value - lower
    if fraction <= 0:
        return lower
    try:
        draw = float(rng.random())
    except Exception:
        draw = 0.5
    return lower + int(draw < fraction)


def _realism_recompose_makes(
    *,
    points: int,
    original_three_made: int,
    original_free_throw_made: int,
    config: GameSimulationConfig,
    rng,
) -> tuple[int, int, int]:
    target_three = _realism_stochastic_round(
        original_three_made * float(config.three_make_multiplier),
        rng,
    )
    target_ft = _realism_stochastic_round(
        original_free_throw_made * float(config.free_throw_make_multiplier),
        rng,
    )
    best = None
    max_three = max(0, int(points) // 3)
    ft_upper = max(0, min(int(points), 16))
    for ft_made in range(ft_upper + 1):
        for three_made in range(max_three + 1):
            remaining = int(points) - ft_made - 3 * three_made
            if remaining < 0 or remaining % 2:
                continue
            two_made = remaining // 2
            score = (
                2.4 * abs(ft_made - target_ft)
                + 1.2 * abs(three_made - target_three)
                + 0.08 * abs(ft_made - original_free_throw_made)
                + 0.04 * abs(three_made - original_three_made)
            )
            candidate = (
                score,
                abs(ft_made - target_ft),
                abs(three_made - target_three),
                -two_made,
                two_made,
                three_made,
                ft_made,
            )
            if best is None or candidate < best:
                best = candidate
    if best is None:
        raise SingleGameSimulationError(
            "Realism calibration could not reconcile a player's scoring."
        )
    return int(best[4]), int(best[5]), int(best[6])


_PLAYER_SHOOTING_IDENTITY_PRESERVATION_V1_0_3 = True
PLAYER_SHOOTING_IDENTITY_VERSION = "player-shooting-identity-preservation-v1.0.3-2026-08-13"
REGULAR_THREE_IDENTITY_ODDS_SCALE_V1_0_3 = 0.975
REGULAR_FT_IDENTITY_ODDS_SCALE_V1_0_3 = 1.08
FT_ATTEMPT_ERROR_WEIGHT_V1_0_3 = 1.80
FT_ATTEMPT_UPWARD_PENALTY_V1_0_3 = 0.40


def _identity_safe_rate(made: int, attempted: int, fallback: float) -> float:
    attempted = int(attempted)
    if attempted <= 0:
        return float(fallback)
    return clamp(float(made) / float(attempted), 0.0, 1.0)


def _identity_odds_shift(probability: float, odds_scale: float) -> float:
    probability = clamp(float(probability), 0.001, 0.999)
    odds_scale = clamp(float(odds_scale), 0.80, 1.20)
    odds = probability / (1.0 - probability)
    shifted = odds * odds_scale
    return clamp(shifted / (1.0 + shifted), 0.001, 0.999)


def _identity_scaled_attempt(value: int, multiplier: float, rng) -> int:
    raw = max(0.0, float(value) * float(multiplier))
    lower = int(raw)
    fraction = raw - lower
    if fraction <= 0.0:
        return lower
    try:
        draw = float(rng.random())
    except Exception:
        draw = 0.5
    return lower + int(draw < fraction)


def _identity_candidate_values(target: int, radius: int, minimum: int = 0) -> tuple[int, ...]:
    target = max(int(minimum), int(target))
    lower = max(int(minimum), target - int(radius))
    upper = max(lower, target + int(radius))
    return tuple(range(lower, upper + 1))


_SHOOTING_IDENTITY_PERFORMANCE_OPTIMIZATION_V1 = True
SHOOTING_IDENTITY_PERFORMANCE_VERSION = "shooting-identity-performance-optimization-v1-2026-08-13"

# Statistical behavior is unchanged from Player Shooting Identity V1.0.3.
# Only the deterministic integer solver is memoized. RNG is consumed before
# cache lookup so same-seed streams remain identical.
import functools as _identity_functools_v1


def _identity_solve_scoring_line_reference_exhaustive_v1_0_3(
    *,
    points: int,
    original: tuple[int, int, int, int, int, int],
    original_two_made: int,
    original_two_pct: float,
    target_three_pct: float,
    target_ft_pct: float,
    target_three_attempted: int,
    target_ft_attempted: int,
    target_fga: int,
) -> tuple[int, int, int, int, int, int]:
    (
        original_fgm,
        original_fga,
        original_three_made,
        original_three_attempted,
        original_ft_made,
        original_ft_attempted,
    ) = tuple(int(value) for value in original)

    best = None
    three_attempt_values = _identity_candidate_values(
        target_three_attempted,
        2,
        0,
    )
    ft_attempt_values = _identity_candidate_values(
        target_ft_attempted,
        2,
        0,
    )
    fga_values = _identity_candidate_values(
        target_fga,
        3,
        0,
    )

    for three_attempted in three_attempt_values:
        for ft_attempted in ft_attempt_values:
            for fga in fga_values:
                if three_attempted > fga:
                    continue
                max_three_made = min(three_attempted, points // 3)
                max_ft_made = min(ft_attempted, points)
                for three_made in range(max_three_made + 1):
                    for ft_made in range(max_ft_made + 1):
                        remaining = points - 3 * three_made - ft_made
                        if remaining < 0 or remaining % 2:
                            continue
                        two_made = remaining // 2
                        two_attempted = fga - three_attempted
                        if two_attempted < two_made:
                            continue
                        fgm = two_made + three_made
                        if fgm > fga:
                            continue

                        three_pct = _identity_safe_rate(
                            three_made,
                            three_attempted,
                            target_three_pct,
                        )
                        ft_pct = _identity_safe_rate(
                            ft_made,
                            ft_attempted,
                            target_ft_pct,
                        )
                        two_pct = _identity_safe_rate(
                            two_made,
                            two_attempted,
                            original_two_pct,
                        )

                        attempt_error = (
                            1.80 * abs(fga - target_fga)
                            + 1.65 * abs(three_attempted - target_three_attempted)
                            + FT_ATTEMPT_ERROR_WEIGHT_V1_0_3 * abs(ft_attempted - target_ft_attempted)
                            + FT_ATTEMPT_UPWARD_PENALTY_V1_0_3 * max(0, ft_attempted - target_ft_attempted)
                        )
                        rate_error = (
                            34.0 * abs(three_pct - target_three_pct)
                            + 30.0 * abs(ft_pct - target_ft_pct)
                            + 15.0 * abs(two_pct - original_two_pct)
                        )

                        zero_volume_penalty = 0.0
                        if original_three_attempted <= 0:
                            zero_volume_penalty += 8.0 * three_attempted
                        if original_ft_attempted <= 0:
                            zero_volume_penalty += 5.0 * ft_attempted

                        make_shape_error = (
                            0.16 * abs(three_made - original_three_made)
                            + 0.12 * abs(ft_made - original_ft_made)
                            + 0.05 * abs(two_made - original_two_made)
                        )
                        score = (
                            attempt_error
                            + rate_error
                            + zero_volume_penalty
                            + make_shape_error
                        )
                        candidate = (
                            score,
                            attempt_error,
                            rate_error,
                            abs(three_attempted - target_three_attempted),
                            abs(ft_attempted - target_ft_attempted),
                            abs(fga - target_fga),
                            fga,
                            three_attempted,
                            ft_attempted,
                            fgm,
                            three_made,
                            ft_made,
                        )
                        if best is None or candidate < best:
                            best = candidate

    if best is None:
        return tuple(int(value) for value in original)

    return (
        int(best[9]),
        int(best[6]),
        int(best[10]),
        int(best[7]),
        int(best[11]),
        int(best[8]),
    )


_FRANCHISE_SIMULATION_PERFORMANCE_OPTIMIZATION_V2 = True
FRANCHISE_SIMULATION_PERFORMANCE_VERSION_V2 = "franchise-simulation-performance-optimization-v2-2026-08-13"


def _identity_solve_scoring_line_uncached_v1_0_3(
    *,
    points: int,
    original: tuple[int, int, int, int, int, int],
    original_two_made: int,
    original_two_pct: float,
    target_three_pct: float,
    target_ft_pct: float,
    target_three_attempted: int,
    target_ft_attempted: int,
    target_fga: int,
) -> tuple[int, int, int, int, int, int]:
    # Exact V1.0.3 objective and tie-breaking are preserved. The optimization
    # removes tens of millions of generic _identity_safe_rate()/clamp() calls
    # from cache misses and hoists invariant arithmetic out of the inner loops.
    (
        original_fgm,
        original_fga,
        original_three_made,
        original_three_attempted,
        original_ft_made,
        original_ft_attempted,
    ) = tuple(int(value) for value in original)

    points = int(points)
    target_three_attempted = int(target_three_attempted)
    target_ft_attempted = int(target_ft_attempted)
    target_fga = int(target_fga)
    original_two_made = int(original_two_made)
    original_two_pct = float(original_two_pct)
    target_three_pct = float(target_three_pct)
    target_ft_pct = float(target_ft_pct)

    best = None
    three_attempt_values = _identity_candidate_values(target_three_attempted, 2, 0)
    ft_attempt_values = _identity_candidate_values(target_ft_attempted, 2, 0)
    fga_values = _identity_candidate_values(target_fga, 3, 0)

    max_points_three = points // 3
    original_three_zero = original_three_attempted <= 0
    original_ft_zero = original_ft_attempted <= 0

    for three_attempted in three_attempt_values:
        max_three_made = min(three_attempted, max_points_three)
        if three_attempted > 0:
            three_pct_values = tuple(
                float(three_made) / float(three_attempted)
                for three_made in range(max_three_made + 1)
            )
        else:
            three_pct_values = (target_three_pct,)

        for ft_attempted in ft_attempt_values:
            max_ft_made = min(ft_attempted, points)
            if ft_attempted > 0:
                ft_pct_values = tuple(
                    float(ft_made) / float(ft_attempted)
                    for ft_made in range(max_ft_made + 1)
                )
            else:
                ft_pct_values = (target_ft_pct,)

            for fga in fga_values:
                if three_attempted > fga:
                    continue

                two_attempted = fga - three_attempted
                attempt_error = (
                    1.80 * abs(fga - target_fga)
                    + 1.65 * abs(three_attempted - target_three_attempted)
                    + FT_ATTEMPT_ERROR_WEIGHT_V1_0_3 * abs(ft_attempted - target_ft_attempted)
                    + FT_ATTEMPT_UPWARD_PENALTY_V1_0_3 * max(0, ft_attempted - target_ft_attempted)
                )

                zero_volume_penalty = 0.0
                if original_three_zero:
                    zero_volume_penalty += 8.0 * three_attempted
                if original_ft_zero:
                    zero_volume_penalty += 5.0 * ft_attempted

                for three_made in range(max_three_made + 1):
                    three_pct = three_pct_values[three_made]
                    remaining_before_ft = points - 3 * three_made
                    three_rate_error = 34.0 * abs(three_pct - target_three_pct)
                    three_make_shape_error = 0.16 * abs(three_made - original_three_made)

                    for ft_made in range(max_ft_made + 1):
                        remaining = remaining_before_ft - ft_made
                        if remaining < 0 or remaining % 2:
                            continue
                        two_made = remaining // 2
                        if two_attempted < two_made:
                            continue
                        fgm = two_made + three_made
                        if fgm > fga:
                            continue

                        ft_pct = ft_pct_values[ft_made]
                        if two_attempted > 0:
                            two_pct = float(two_made) / float(two_attempted)
                        else:
                            two_pct = original_two_pct

                        rate_error = (
                            three_rate_error
                            + 30.0 * abs(ft_pct - target_ft_pct)
                            + 15.0 * abs(two_pct - original_two_pct)
                        )

                        make_shape_error = (
                            three_make_shape_error
                            + 0.12 * abs(ft_made - original_ft_made)
                            + 0.05 * abs(two_made - original_two_made)
                        )
                        score = (
                            attempt_error
                            + rate_error
                            + zero_volume_penalty
                            + make_shape_error
                        )
                        candidate = (
                            score,
                            attempt_error,
                            rate_error,
                            abs(three_attempted - target_three_attempted),
                            abs(ft_attempted - target_ft_attempted),
                            abs(fga - target_fga),
                            fga,
                            three_attempted,
                            ft_attempted,
                            fgm,
                            three_made,
                            ft_made,
                        )
                        if best is None or candidate < best:
                            best = candidate

    if best is None:
        return tuple(int(value) for value in original)

    return (
        int(best[9]),
        int(best[6]),
        int(best[10]),
        int(best[7]),
        int(best[11]),
        int(best[8]),
    )


@_identity_functools_v1.lru_cache(maxsize=65536)
def _identity_solve_scoring_line_cached_v1(
    points: int,
    original: tuple[int, int, int, int, int, int],
    original_two_made: int,
    original_two_pct: float,
    target_three_pct: float,
    target_ft_pct: float,
    target_three_attempted: int,
    target_ft_attempted: int,
    target_fga: int,
) -> tuple[int, int, int, int, int, int]:
    return _identity_solve_scoring_line_uncached_v1_0_3(
        points=int(points),
        original=tuple(int(value) for value in original),
        original_two_made=int(original_two_made),
        original_two_pct=float(original_two_pct),
        target_three_pct=float(target_three_pct),
        target_ft_pct=float(target_ft_pct),
        target_three_attempted=int(target_three_attempted),
        target_ft_attempted=int(target_ft_attempted),
        target_fga=int(target_fga),
    )


def _identity_prepare_scoring_problem_v1_0_3(
    *,
    points: int,
    original: tuple[int, int, int, int, int, int],
    config: GameSimulationConfig,
    rng,
):
    (
        original_fgm,
        original_fga,
        original_three_made,
        original_three_attempted,
        original_ft_made,
        original_ft_attempted,
    ) = tuple(int(value) for value in original)

    points = int(points)
    original_tuple = (
        original_fgm,
        original_fga,
        original_three_made,
        original_three_attempted,
        original_ft_made,
        original_ft_attempted,
    )
    original_two_made = max(0, original_fgm - original_three_made)
    original_two_attempted = max(0, original_fga - original_three_attempted)

    original_three_pct = _identity_safe_rate(
        original_three_made,
        original_three_attempted,
        0.34,
    )
    original_ft_pct = _identity_safe_rate(
        original_ft_made,
        original_ft_attempted,
        0.76,
    )
    original_two_pct = _identity_safe_rate(
        original_two_made,
        original_two_attempted,
        0.52,
    )

    is_regular_environment = (
        abs(float(config.three_attempt_multiplier) - 0.904) < 1e-12
        and abs(float(config.free_throw_attempt_multiplier) - 0.843) < 1e-12
        and abs(float(config.field_goal_attempt_multiplier) - 0.988) < 1e-12
    )
    target_three_pct = _identity_odds_shift(
        original_three_pct,
        float(config.three_make_multiplier)
        * (
            REGULAR_THREE_IDENTITY_ODDS_SCALE_V1_0_3
            if is_regular_environment
            else 1.0
        ),
    )

    raw_ft_odds_scale = (
        float(config.free_throw_make_multiplier)
        / max(0.001, float(config.free_throw_attempt_multiplier))
    )
    base_ft_odds_scale = clamp(raw_ft_odds_scale, 0.94, 1.08)
    target_ft_pct = _identity_odds_shift(
        original_ft_pct,
        clamp(
            base_ft_odds_scale
            * (
                REGULAR_FT_IDENTITY_ODDS_SCALE_V1_0_3
                if is_regular_environment
                else 1.0
            ),
            0.80,
            1.20,
        ),
    )

    # Exactly the same three stochastic-rounding calls as V1.0.3, always
    # executed before cache lookup.
    target_three_attempted = _identity_scaled_attempt(
        original_three_attempted,
        float(config.three_attempt_multiplier),
        rng,
    )
    target_ft_attempted = _identity_scaled_attempt(
        original_ft_attempted,
        float(config.free_throw_attempt_multiplier),
        rng,
    )
    target_fga = _identity_scaled_attempt(
        original_fga,
        float(config.field_goal_attempt_multiplier),
        rng,
    )

    return (
        points,
        original_tuple,
        original_two_made,
        original_two_pct,
        target_three_pct,
        target_ft_pct,
        target_three_attempted,
        target_ft_attempted,
        target_fga,
    )


def _identity_preserved_scoring_line_reference_v1_0_3(
    *,
    points: int,
    original: tuple[int, int, int, int, int, int],
    config: GameSimulationConfig,
    rng,
) -> tuple[int, int, int, int, int, int]:
    if int(points) <= 0:
        return (0, 0, 0, 0, 0, 0)
    problem = _identity_prepare_scoring_problem_v1_0_3(
        points=int(points),
        original=original,
        config=config,
        rng=rng,
    )
    return _identity_solve_scoring_line_reference_exhaustive_v1_0_3(
        points=problem[0],
        original=problem[1],
        original_two_made=problem[2],
        original_two_pct=problem[3],
        target_three_pct=problem[4],
        target_ft_pct=problem[5],
        target_three_attempted=problem[6],
        target_ft_attempted=problem[7],
        target_fga=problem[8],
    )


def _identity_preserved_scoring_line(
    *,
    points: int,
    original: tuple[int, int, int, int, int, int],
    config: GameSimulationConfig,
    rng,
) -> tuple[int, int, int, int, int, int]:
    if int(points) <= 0:
        return (0, 0, 0, 0, 0, 0)
    problem = _identity_prepare_scoring_problem_v1_0_3(
        points=int(points),
        original=original,
        config=config,
        rng=rng,
    )
    return _identity_solve_scoring_line_cached_v1(*problem)


def _identity_scoring_cache_info_v1():
    return _identity_solve_scoring_line_cached_v1.cache_info()


def _identity_scoring_cache_clear_v1() -> None:
    _identity_solve_scoring_line_cached_v1.cache_clear()


def scoring_components(*args, config: GameSimulationConfig | None = None, **kwargs):
    resolved_config = config or GameSimulationConfig()
    original = _scoring_components_pre_realism_v1_0_3(*args, **kwargs)
    if len(original) != 6:
        raise SingleGameSimulationError("Unexpected scoring_components return shape.")
    points = kwargs.get("points")
    if points is None:
        raise SingleGameSimulationError("Identity-preserving scoring wrapper requires points=.")
    rng = args[0] if args else None
    return _identity_preserved_scoring_line(
        points=int(points),
        original=tuple(int(value) for value in original),
        config=resolved_config,
        rng=rng,
    )


def noisy_count(
    rng: random.Random,
    expected: float,
    *,
    maximum: int | None = None,
) -> int:
    standard_deviation = max(
        0.7,
        math.sqrt(max(expected, 0.0)) * 0.72,
    )
    value = max(
        0,
        round(
            rng.gauss(
                expected,
                standard_deviation,
            )
        ),
    )

    if maximum is not None:
        value = min(value, maximum)

    return int(value)


def position_tokens(position: str) -> tuple[str, ...]:
    tokens = tuple(
        token
        for token in str(position or "").upper().split("/")
        if token in POSITION_STAT_MULTIPLIERS
    )
    return tokens or ("SF",)


def position_stat_multiplier(
    position: str,
    stat_name: str,
) -> float:
    tokens = position_tokens(position)
    values = [
        POSITION_STAT_MULTIPLIERS[token][stat_name]
        for token in tokens
    ]
    return sum(values) / len(values)


def team_position_share(
    state: SimulationLeagueState,
    plan: TeamGamePlan,
    position_group: set[str],
) -> float:
    total_minutes = sum(plan.minutes.values())
    if total_minutes <= 0:
        return 0.0

    weighted = 0.0
    for player_id in plan.player_ids:
        tokens = position_tokens(
            state.players[player_id].position
        )
        overlap = (
            len(set(tokens).intersection(position_group))
            / len(tokens)
        )
        weighted += plan.minutes[player_id] * overlap

    return weighted / total_minutes


def allocate_capped_integer_units(
    total_units: int,
    ordered_ids: tuple[str, ...],
    weights: dict[str, float],
    caps: dict[str, int],
) -> dict[str, int]:
    if total_units > sum(
        max(0, int(caps.get(player_id, 0)))
        for player_id in ordered_ids
    ):
        raise SingleGameSimulationError(
            "Allocation total exceeds available player caps."
        )

    result = {
        player_id: 0
        for player_id in ordered_ids
    }
    remaining = int(total_units)

    while remaining > 0:
        eligible = tuple(
            player_id
            for player_id in ordered_ids
            if result[player_id]
            < max(0, int(caps.get(player_id, 0)))
        )
        if not eligible:
            raise SingleGameSimulationError(
                "No eligible recipients remain for allocation."
            )

        allocation = allocate_integer_units(
            remaining,
            eligible,
            {
                player_id: max(
                    0.0001,
                    float(weights.get(player_id, 0.0)),
                )
                for player_id in eligible
            },
        )

        overflow = 0
        progress = False
        for player_id in eligible:
            available = (
                max(0, int(caps.get(player_id, 0)))
                - result[player_id]
            )
            assigned = min(
                available,
                allocation[player_id],
            )
            if assigned:
                progress = True
            result[player_id] += assigned
            overflow += allocation[player_id] - assigned

        if not progress and remaining:
            first = eligible[0]
            result[first] += 1
            overflow = remaining - 1

        remaining = overflow

    return result


def randomized_team_total(
    rng: random.Random,
    expected: float,
    standard_deviation: float,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if maximum < minimum:
        maximum = minimum

    return int(
        round(
            clamp(
                rng.gauss(
                    expected,
                    standard_deviation,
                ),
                minimum,
                maximum,
            )
        )
    )


def secondary_stat_weights(
    state: SimulationLeagueState,
    plan: TeamGamePlan,
    scoring: dict[str, PlayerScoringProfile],
    stat_name: str,
) -> dict[str, float]:
    weights: dict[str, float] = {}

    for player_id in plan.player_ids:
        player = state.players[player_id]
        minutes = plan.minutes[player_id]
        fingerprint = build_player_stat_fingerprint(player)
        expected = expected_secondary_count(
            fingerprint,
            stat_name,
            minutes,
        )
        health_factor = clamp(
            plan.effective_ratings[player_id]
            / max(player.overall_rating, 1.0),
            0.84,
            1.04,
        )
        usage_factor = 1.0

        # Baseline per-36 rates already contain player identity. Keep only a
        # mild same-game usage adjustment so high-touch players can turn the
        # ball over or create a few extra assists without erasing the prior.
        if stat_name == "turnovers":
            usage_factor += scoring[player_id].points / 120.0
        elif stat_name == "assists":
            usage_factor += scoring[player_id].points / 210.0

        weights[player_id] = max(
            0.0001,
            expected
            * health_factor
            * usage_factor,
        )

    return weights


def _build_team_secondary_stat_allocations_pre_realism_v1_0_3(
    rng: random.Random,
    state: SimulationLeagueState,
    plan: TeamGamePlan,
    scoring: dict[str, PlayerScoringProfile],
    *,
    pace: float,
    config: GameSimulationConfig,
) -> dict[str, dict[str, int]]:
    total_minutes = sum(plan.minutes.values())
    game_length_scale = max(
        1.0,
        total_minutes / 240.0,
    )
    pace_scale = clamp(
        pace / config.base_pace,
        0.86,
        1.16,
    )
    guard_share = team_position_share(
        state,
        plan,
        {"PG", "SG"},
    )
    big_share = team_position_share(
        state,
        plan,
        {"PF", "C"},
    )
    field_goals_made = sum(
        profile.field_goals_made
        for profile in scoring.values()
    )
    rating_edge = clamp(
        (
            plan.weighted_team_rating
            - config.neutral_rating
        )
        / 10.0,
        -1.0,
        1.0,
    )

    rebound_expected = (
        42.8
        * pace_scale
        * game_length_scale
        + 3.0 * (big_share - 0.42)
    )
    assist_rate = clamp(
        0.64
        + 0.08 * guard_share
        + 0.025 * rating_edge,
        0.60,
        0.78,
    )
    assist_expected = field_goals_made * assist_rate

    minimum_assists = min(
        field_goals_made,
        int(round(8 * game_length_scale)),
    )
    maximum_assists = min(
        field_goals_made,
        int(round(38 * game_length_scale)),
    )

    totals = {
        "rebounds": randomized_team_total(
            rng,
            rebound_expected,
            3.1 * math.sqrt(game_length_scale),
            minimum=int(round(30 * game_length_scale)),
            maximum=int(round(60 * game_length_scale)),
        ),
        "assists": randomized_team_total(
            rng,
            assist_expected,
            2.4 * math.sqrt(game_length_scale),
            minimum=minimum_assists,
            maximum=maximum_assists,
        ),
        "steals": randomized_team_total(
            rng,
            7.3 * pace_scale * game_length_scale,
            1.7 * math.sqrt(game_length_scale),
            minimum=int(round(2 * game_length_scale)),
            maximum=int(round(16 * game_length_scale)),
        ),
        "blocks": randomized_team_total(
            rng,
            (
                3.8
                + 2.1 * big_share
            )
            * pace_scale
            * game_length_scale,
            1.5 * math.sqrt(game_length_scale),
            minimum=0,
            maximum=int(round(14 * game_length_scale)),
        ),
        "turnovers": randomized_team_total(
            rng,
            13.4 * pace_scale * game_length_scale,
            2.2 * math.sqrt(game_length_scale),
            minimum=int(round(6 * game_length_scale)),
            maximum=int(round(24 * game_length_scale)),
        ),
        "fouls": randomized_team_total(
            rng,
            (
                18.4
                + 2.2 * big_share
            )
            * game_length_scale,
            2.7 * math.sqrt(game_length_scale),
            minimum=int(round(9 * game_length_scale)),
            maximum=int(round(30 * game_length_scale)),
        ),
    }

    caps_by_stat = {
        "rebounds": 22,
        "assists": 18,
        "steals": 7,
        "blocks": 8,
        "turnovers": 9,
        "fouls": 6,
    }
    allocations: dict[str, dict[str, int]] = {}

    for stat_name, total in totals.items():
        allocations[stat_name] = (
            allocate_capped_integer_units(
                total,
                plan.player_ids,
                secondary_stat_weights(
                    state,
                    plan,
                    scoring,
                    stat_name,
                ),
                {
                    player_id: caps_by_stat[stat_name]
                    for player_id in plan.player_ids
                },
            )
        )

    return allocations


_REALISM_V103_SECONDARY_WRAPPER = True


def _realism_rescale_integer_distribution(
    values: dict[str, int],
    multiplier: float,
    *,
    maximum: int,
) -> dict[str, int]:
    ids = tuple(values)
    total = sum(max(0, int(values[player_id])) for player_id in ids)
    if total <= 0:
        return {player_id: 0 for player_id in ids}
    target = max(0, int(round(total * float(multiplier))))
    weights = {
        player_id: max(0.001, float(max(0, int(values[player_id]))))
        for player_id in ids
    }
    caps = {player_id: int(maximum) for player_id in ids}
    target = min(target, sum(caps.values()))
    return allocate_capped_integer_units(target, ids, weights, caps)


def build_team_secondary_stat_allocations(*args, **kwargs):
    result = _build_team_secondary_stat_allocations_pre_realism_v1_0_3(
        *args,
        **kwargs,
    )
    config = kwargs.get("config")
    if config is None:
        return result
    multipliers = {
        "rebounds": float(config.rebound_environment_multiplier),
        "assists": float(config.assist_environment_multiplier),
        "steals": float(config.steal_environment_multiplier),
        "blocks": float(config.block_environment_multiplier),
        "turnovers": float(config.turnover_environment_multiplier),
        "fouls": float(config.foul_environment_multiplier),
    }
    caps = {
        "rebounds": 22,
        "assists": 18,
        "steals": 7,
        "blocks": 8,
        "turnovers": 9,
        "fouls": 6,
    }
    calibrated = {}
    for stat_name, allocation in result.items():
        if stat_name in multipliers and isinstance(allocation, dict):
            calibrated[stat_name] = _realism_rescale_integer_distribution(
                allocation,
                multipliers[stat_name],
                maximum=caps[stat_name],
            )
        else:
            calibrated[stat_name] = allocation
    return calibrated


def build_player_box_scores(
    rng: random.Random,
    state: SimulationLeagueState,
    plan: TeamGamePlan,
    *,
    team_score: int,
    pace: float,
    config: GameSimulationConfig,
) -> tuple[PlayerBoxScore, ...]:
    point_allocation = allocate_integer_units(
        team_score,
        plan.player_ids,
        usage_weights(
            rng,
            plan,
            state=state,
        ),
    )
    scoring: dict[str, PlayerScoringProfile] = {}

    for player_id in plan.player_ids:
        player = state.players[player_id]
        points = point_allocation[player_id]
        (
            field_goals_made,
            field_goals_attempted,
            three_pointers_made,
            three_pointers_attempted,
            free_throws_made,
            free_throws_attempted,
        ) = scoring_components(
            rng,
            points=points,
            position=player.position,
            overall_rating=(
                plan.effective_ratings[player_id]
            ),
            player_id=player_id,
            state=state,
            minutes=plan.minutes[player_id],
            pace_scale=(
                pace / max(config.base_pace, 1.0)
            ),
        config=config,
        )
        scoring[player_id] = PlayerScoringProfile(
            points=points,
            field_goals_made=field_goals_made,
            field_goals_attempted=(
                field_goals_attempted
            ),
            three_pointers_made=(
                three_pointers_made
            ),
            three_pointers_attempted=(
                three_pointers_attempted
            ),
            free_throws_made=free_throws_made,
            free_throws_attempted=(
                free_throws_attempted
            ),
        )

    secondary = build_team_secondary_stat_allocations(
        rng,
        state,
        plan,
        scoring,
        pace=pace,
        config=config,
    )
    starter_set = set(plan.starter_ids)
    lines: list[PlayerBoxScore] = []

    for player_id in plan.player_ids:
        profile = scoring[player_id]
        lines.append(
            PlayerBoxScore(
                player_id=player_id,
                team_abbreviation=(
                    plan.team_abbreviation
                ),
                started=(
                    player_id in starter_set
                ),
                minutes=plan.minutes[player_id],
                points=profile.points,
                rebounds=secondary[
                    "rebounds"
                ][player_id],
                assists=secondary[
                    "assists"
                ][player_id],
                steals=secondary[
                    "steals"
                ][player_id],
                blocks=secondary[
                    "blocks"
                ][player_id],
                turnovers=secondary[
                    "turnovers"
                ][player_id],
                fouls=secondary[
                    "fouls"
                ][player_id],
                field_goals_made=(
                    profile.field_goals_made
                ),
                field_goals_attempted=(
                    profile.field_goals_attempted
                ),
                three_pointers_made=(
                    profile.three_pointers_made
                ),
                three_pointers_attempted=(
                    profile.three_pointers_attempted
                ),
                free_throws_made=(
                    profile.free_throws_made
                ),
                free_throws_attempted=(
                    profile.free_throws_attempted
                ),
            )
        )

    return tuple(lines)


def simulate_scheduled_game(
    state: SimulationLeagueState,
    game_id: str,
    *,
    seed: int | None = None,
    commit: bool = False,
    sit_player_ids: Iterable[str] = (),
    config: GameSimulationConfig | None = None,
    _private_working_state: bool = False,
    _defer_global_state_validation: bool = False,
) -> SimulatedGame:
    resolved_config = (
        resolve_game_environment_config(
            state,
            config,
        )
    )
    game_id = str(game_id).strip()
    scheduled = state.schedule.get(game_id)

    if scheduled is None:
        raise SingleGameSimulationError(
            f"Game {game_id!r} is not scheduled."
        )

    if scheduled.status != GameStatus.SCHEDULED:
        raise SingleGameSimulationError(
            f"Game {game_id} is already completed."
        )

    # Normal previews operate on a private state copy. Internal batch
    # transactions may pass an already-private state so postseason simulation
    # does not duplicate the complete franchise universe for every game.
    working_state = (
        state
        if commit or _private_working_state
        else copy.deepcopy(state)
    )
    working_scheduled = (
        working_state.schedule[game_id]
    )
    prepare_health_for_game(
        working_state,
        day_index=(
            working_scheduled.day_index
        ),
        teams=(
            working_scheduled.home_team,
            working_scheduled.away_team,
        ),
    )
    setattr(
        working_state,
        "_active_simulation_day",
        int(
            working_scheduled.day_index
        ),
    )

    sit_ids = {
        normalize_player_id(player_id)
        for player_id in sit_player_ids
        if normalize_player_id(player_id)
    }
    resolved_seed = stable_seed(
        working_state,
        game_id,
        seed,
    )
    rng = random.Random(resolved_seed)

    home_regulation_plan = build_team_game_plan(
        working_state,
        working_scheduled.home_team,
        sit_player_ids=sit_ids,
        overtime_periods=0,
        config=resolved_config,
    )
    away_regulation_plan = build_team_game_plan(
        working_state,
        working_scheduled.away_team,
        sit_player_ids=sit_ids,
        overtime_periods=0,
        config=resolved_config,
    )
    (
        pace,
        expected_home,
        expected_away,
        home_score,
        away_score,
        overtime_periods,
    ) = simulate_scores(
        rng,
        home_regulation_plan,
        away_regulation_plan,
        config=resolved_config,
    )

    # FRANCHISE_GAME_DAY_PERFORMANCE_V7:
    # Regulation plans are already the exact plans needed by the box-score
    # engine for non-overtime games. Rebuilding both teams a second time was
    # duplicate rotation/minute work with identical output.
    if overtime_periods:
        home_plan = build_team_game_plan(
            working_state,
            working_scheduled.home_team,
            sit_player_ids=sit_ids,
            overtime_periods=overtime_periods,
            config=resolved_config,
        )
        away_plan = build_team_game_plan(
            working_state,
            working_scheduled.away_team,
            sit_player_ids=sit_ids,
            overtime_periods=overtime_periods,
            config=resolved_config,
        )
    else:
        home_plan = home_regulation_plan
        away_plan = away_regulation_plan

    home_lines = build_player_box_scores(
        rng,
        working_state,
        home_plan,
        team_score=home_score,
        pace=pace,
        config=resolved_config,
    )
    away_lines = build_player_box_scores(
        rng,
        working_state,
        away_plan,
        team_score=away_score,
        pace=pace,
        config=resolved_config,
    )
    game = CompletedGame(
        game_id=game_id,
        home_team=working_scheduled.home_team,
        away_team=working_scheduled.away_team,
        home_score=home_score,
        away_score=away_score,
        overtime_periods=overtime_periods,
        player_box_scores=(
            *home_lines,
            *away_lines,
        ),
        box_score_complete=True,
    )

    validate_completed_game(
        working_state,
        game,
    )

    home_probability = logistic_win_probability(
        (
            home_regulation_plan
            .weighted_team_rating
            - away_regulation_plan
            .weighted_team_rating
        ),
        resolved_config.home_court_points,
    )
    metadata = GameSimulationMetadata(
        engine_version=ENGINE_VERSION,
        seed=resolved_seed,
        game_id=game_id,
        home_team=working_scheduled.home_team,
        away_team=working_scheduled.away_team,
        pace=pace,
        home_team_rating=round(
            home_regulation_plan
            .weighted_team_rating,
            2,
        ),
        away_team_rating=round(
            away_regulation_plan
            .weighted_team_rating,
            2,
        ),
        expected_home_score=expected_home,
        expected_away_score=expected_away,
        home_score=home_score,
        away_score=away_score,
        overtime_periods=overtime_periods,
        home_win_probability=round(
            home_probability,
            4,
        ),
    )

    if commit:
        record_completed_game(
            working_state,
            game,
            _completed_game_already_validated=True,
            _defer_global_state_validation=(
                _defer_global_state_validation
            ),
        )

    health_update = (
        process_completed_game_health(
            working_state,
            working_scheduled,
            game,
            seed=resolved_seed,
        )
    )

    if hasattr(
        working_state,
        "_active_simulation_day",
    ):
        delattr(
            working_state,
            "_active_simulation_day",
        )

    return SimulatedGame(
        game=game,
        metadata=metadata,
        committed=commit,
        health_update=health_update,
    )


def game_summary(
    state: SimulationLeagueState,
    result: SimulatedGame,
) -> dict[str, Any]:
    game = result.game
    winner = (
        game.home_team
        if game.home_score > game.away_score
        else game.away_team
    )
    sorted_lines = sorted(
        game.player_box_scores,
        key=lambda line: (
            -line.points,
            -line.assists,
            -line.rebounds,
            line.player_id,
        ),
    )
    leaders = [
        {
            "player_id": line.player_id,
            "player_name": (
                state.players[
                    line.player_id
                ].player_name
            ),
            "team_abbreviation": (
                line.team_abbreviation
            ),
            "minutes": line.minutes,
            "points": line.points,
            "rebounds": line.rebounds,
            "assists": line.assists,
        }
        for line in sorted_lines[:6]
    ]

    return {
        "engine": ENGINE_VERSION,
        "game_id": game.game_id,
        "committed": result.committed,
        "home_team": game.home_team,
        "away_team": game.away_team,
        "home_score": game.home_score,
        "away_score": game.away_score,
        "winner": winner,
        "overtime_periods": (
            game.overtime_periods
        ),
        "metadata": asdict(result.metadata),
        "leaders": leaders,
    }


def team_box_score_reconciles(
    game: CompletedGame,
    team: str,
    *,
    regulation_minutes: int,
    overtime_minutes: int,
) -> bool:
    team_lines = [
        line
        for line in game.player_box_scores
        if line.team_abbreviation == team
    ]
    expected_score = (
        game.home_score
        if team == game.home_team
        else game.away_score
    )
    expected_minutes = (
        regulation_minutes * 5
        + overtime_minutes
        * 5
        * game.overtime_periods
    )
    return bool(
        sum(
            line.points
            for line in team_lines
        )
        == expected_score
        and math.isclose(
            sum(
                line.minutes
                for line in team_lines
            ),
            expected_minutes,
            abs_tol=0.1,
        )
        and sum(
            line.started
            for line in team_lines
        )
        == 5
    )


def strongest_and_weakest_teams(
    state: SimulationLeagueState,
    config: GameSimulationConfig,
) -> tuple[str, str]:
    ratings = {}

    for team in state.teams:
        plan = build_team_game_plan(
            state,
            team,
            sit_player_ids=set(),
            overtime_periods=0,
            config=config,
        )
        ratings[team] = (
            plan.weighted_team_rating
        )

    strongest = max(
        ratings,
        key=lambda team: (
            ratings[team],
            team,
        ),
    )
    weakest = min(
        ratings,
        key=lambda team: (
            ratings[team],
            team,
        ),
    )
    return strongest, weakest


def run_self_test() -> dict[str, Any]:
    base_runtime = load_runtime_data()
    league_state = create_league_state(
        base_runtime
    )
    runtime = build_state_runtime(
        base_runtime,
        league_state,
    )
    state = create_simulation_league_state(
        runtime,
        league_state,
    )
    teams = sorted(state.teams)
    home_team = teams[0]
    away_team = teams[1]
    config = GameSimulationConfig()

    add_scheduled_games(
        state,
        [
            ScheduledGame(
                game_id="SIM-TEST-0001",
                day_index=1,
                home_team=home_team,
                away_team=away_team,
            ),
            ScheduledGame(
                game_id="SIM-TEST-0002",
                day_index=2,
                home_team=away_team,
                away_team=home_team,
            ),
        ],
    )
    checks: dict[str, bool] = {}
    profiles = load_player_stat_profiles()
    jokic_id = (
        player_id_by_name("Nikola Jokić")
        or player_id_by_name("Nikola Jokic")
    )
    curry_id = player_id_by_name(
        "Stephen Curry"
    )
    wemby_id = player_id_by_name(
        "Victor Wembanyama"
    )

    checks["player_profile_layer_loaded"] = (
        len(profiles) == 582
    )
    checks[
        "jokic_profile_overrides_center_assist_prior"
    ] = bool(
        jokic_id
        and curry_id
        and profile_adjusted_stat_multiplier(
            jokic_id,
            profiles[jokic_id]["position"],
            "assists",
        )
        > profile_adjusted_stat_multiplier(
            curry_id,
            profiles[curry_id]["position"],
            "assists",
        )
    )
    checks[
        "wembanyama_profile_amplifies_blocks"
    ] = bool(
        wemby_id
        and moderated_player_stat_factor(
            wemby_id,
            "blocks",
        )
        >= 2.0
    )
    checks[
        "permanent_state_stat_factors_are_active"
    ] = bool(
        wemby_id
        and math.isclose(
            moderated_player_stat_factor(
                wemby_id,
                "blocks",
                state=state,
            ),
            moderated_player_stat_factor(
                wemby_id,
                "blocks",
            ),
            abs_tol=1e-9,
        )
    )

    before_preview = state_result_signature(
        state
    )

    preview_one = simulate_scheduled_game(
        state,
        "SIM-TEST-0001",
        seed=881144,
        commit=False,
    )
    preview_two = simulate_scheduled_game(
        state,
        "SIM-TEST-0001",
        seed=881144,
        commit=False,
    )
    checks["same_seed_is_deterministic"] = (
        asdict(preview_one.game)
        == asdict(preview_two.game)
        and asdict(preview_one.metadata)
        == asdict(preview_two.metadata)
    )
    checks["preview_does_not_mutate_state"] = (
        state_result_signature(state)
        == before_preview
    )
    checks["injury_fatigue_engine_is_active"] = (
        INJURY_FATIGUE_VERSION
        == "simulation-injury-fatigue-v1-2026-08-09"
        and preview_one.health_update is not None
    )
    checks["preview_health_is_deterministic"] = (
        asdict(
            preview_one.health_update
        )
        == asdict(
            preview_two.health_update
        )
    )
    checks["preview_score_has_winner"] = (
        preview_one.game.home_score
        != preview_one.game.away_score
    )
    checks[
        "home_box_score_reconciles"
    ] = team_box_score_reconciles(
        preview_one.game,
        home_team,
        regulation_minutes=(
            state.settings.regulation_minutes
        ),
        overtime_minutes=(
            state.settings.overtime_minutes
        ),
    )
    checks[
        "away_box_score_reconciles"
    ] = team_box_score_reconciles(
        preview_one.game,
        away_team,
        regulation_minutes=(
            state.settings.regulation_minutes
        ),
        overtime_minutes=(
            state.settings.overtime_minutes
        ),
    )
    checks["all_shooting_lines_reconcile"] = all(
        line.points
        == (
            2
            * (
                line.field_goals_made
                - line.three_pointers_made
            )
            + 3 * line.three_pointers_made
            + line.free_throws_made
        )
        and line.field_goals_made
        <= line.field_goals_attempted
        and line.three_pointers_made
        <= line.three_pointers_attempted
        and line.free_throws_made
        <= line.free_throws_attempted
        for line in (
            preview_one.game.player_box_scores
        )
    )

    checks["position_profiles_are_directional"] = (
        position_stat_multiplier(
            "C",
            "rebounds",
        )
        > position_stat_multiplier(
            "PG",
            "rebounds",
        )
        and position_stat_multiplier(
            "PG",
            "assists",
        )
        > position_stat_multiplier(
            "C",
            "assists",
        )
        and position_stat_multiplier(
            "C",
            "blocks",
        )
        > position_stat_multiplier(
            "PG",
            "blocks",
        )
        and position_stat_multiplier(
            "PG/SG",
            "blocks",
        )
        > 0.30
    )

    preview_team_lines = {
        team: [
            line
            for line in preview_one.game.player_box_scores
            if line.team_abbreviation == team
        ]
        for team in (home_team, away_team)
    }
    preview_minutes = [
        line.minutes
        for line
        in preview_one.game.player_box_scores
    ]
    checks[
        "saved_rotation_minutes_anchor_game_plan"
    ] = all(
        max(
            line.minutes
            for line
            in preview_team_lines[team]
        )
        <= 38.0
        for team in (
            home_team,
            away_team,
        )
    )
    checks[
        "historical_minute_targets_create_role_variation"
    ] = all(
        len(
            {
                round(
                    line.minutes,
                    1,
                )
                for line
                in preview_team_lines[team]
            }
        )
        >= 5
        for team in (
            home_team,
            away_team,
        )
    )
    checks[
        "normal_rotation_averages_do_not_create_40_minute_stars"
    ] = (
        max(preview_minutes) <= 38.0
    )
    checks[
        "single_game_scoring_has_no_forced_50_point_outlier"
    ] = (
        max(
            line.points
            for line
            in preview_one.game.player_box_scores
        )
        <= 49
    )

    checks["team_secondary_totals_are_plausible"] = all(
        30 <= sum(line.rebounds for line in lines) <= 60
        and 2 <= sum(line.steals for line in lines) <= 16
        and 0 <= sum(line.blocks for line in lines) <= 14
        and 6 <= sum(line.turnovers for line in lines) <= 24
        and 9 <= sum(line.fouls for line in lines) <= 30
        for lines in preview_team_lines.values()
    )
    checks["team_assists_respect_made_shots"] = all(
        sum(line.assists for line in lines)
        <= sum(
            line.field_goals_made
            for line in lines
        )
        for lines in preview_team_lines.values()
    )
    checks["individual_secondary_caps_hold"] = all(
        line.rebounds <= 22
        and line.assists <= 18
        and line.steals <= 7
        and line.blocks <= 8
        and line.turnovers <= 9
        and line.fouls <= 6
        for line in preview_one.game.player_box_scores
    )

    committed = simulate_scheduled_game(
        state,
        "SIM-TEST-0001",
        seed=881144,
        commit=True,
    )
    checks["committed_game_matches_preview"] = (
        asdict(committed.game)
        == asdict(preview_one.game)
    )
    checks["commit_updates_schedule"] = (
        state.schedule[
            "SIM-TEST-0001"
        ].status
        == GameStatus.COMPLETED
        and "SIM-TEST-0001"
        in state.completed_games
    )
    winner = (
        home_team
        if committed.game.home_score
        > committed.game.away_score
        else away_team
    )
    loser = (
        away_team
        if winner == home_team
        else home_team
    )
    checks["commit_updates_standings"] = (
        state.standings[winner].wins == 1
        and state.standings[loser].losses == 1
        and state.standings[
            winner
        ].games_played
        == 1
        and state.standings[
            loser
        ].games_played
        == 1
    )
    active_box_score_ids = {
        line.player_id
        for line in committed.game.player_box_scores
    }
    checks["commit_updates_player_totals"] = all(
        state.player_season_totals[
            player_id
        ].games_played
        == 1
        for player_id in active_box_score_ids
    )

    duplicate_blocked = False
    try:
        simulate_scheduled_game(
            state,
            "SIM-TEST-0001",
            seed=881144,
            commit=True,
        )
    except SingleGameSimulationError:
        duplicate_blocked = True
    checks["duplicate_simulation_blocked"] = (
        duplicate_blocked
    )

    unavailable_player = (
        state.teams[away_team]
        .rotation.rotation_player_ids[0]
    )
    set_player_injury(
        state,
        unavailable_player,
        status=AvailabilityStatus.OUT,
        injury_type="self-test injury",
        games_remaining=1,
    )
    injury_preview = simulate_scheduled_game(
        state,
        "SIM-TEST-0002",
        seed=991255,
        commit=False,
    )
    checks["out_player_is_excluded"] = (
        unavailable_player
        not in {
            line.player_id
            for line
            in injury_preview.game.player_box_scores
        }
    )
    checks[
        "injury_replacement_still_has_five_starters"
    ] = (
        sum(
            line.started
            for line
            in injury_preview.game.player_box_scores
            if line.team_abbreviation
            == away_team
        )
        == 5
    )
    checks["injury_preview_reconciles"] = (
        team_box_score_reconciles(
            injury_preview.game,
            home_team,
            regulation_minutes=(
                state.settings.regulation_minutes
            ),
            overtime_minutes=(
                state.settings.overtime_minutes
            ),
        )
        and team_box_score_reconciles(
            injury_preview.game,
            away_team,
            regulation_minutes=(
                state.settings.regulation_minutes
            ),
            overtime_minutes=(
                state.settings.overtime_minutes
            ),
        )
    )

    set_player_injury(
        state,
        unavailable_player,
        status=AvailabilityStatus.HEALTHY,
    )
    sit_player = (
        state.teams[home_team]
        .rotation.rotation_player_ids[0]
    )
    coach_preview = simulate_scheduled_game(
        state,
        "SIM-TEST-0002",
        seed=991255,
        commit=False,
        sit_player_ids=(sit_player,),
    )
    checks["coach_sit_decision_is_honored"] = (
        sit_player
        not in {
            line.player_id
            for line
            in coach_preview.game.player_box_scores
        }
    )

    checks["simulation_state_remains_valid"] = bool(
        validate_simulation_league_state(
            state
        )
    )

    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]
    report = {
        "script": ENGINE_VERSION,
        "profile_loader": PROFILE_LOADER_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "preview_score": (
                f"{preview_one.game.away_team} "
                f"{preview_one.game.away_score}, "
                f"{preview_one.game.home_team} "
                f"{preview_one.game.home_score}"
            ),
            "committed_game_id": (
                committed.game.game_id
            ),
            "winner": winner,
            "overtime_periods": (
                committed.game.overtime_periods
            ),
            "box_score_lines": len(
                committed.game.player_box_scores
            ),
            "standings_games_recorded": sum(
                standing.games_played
                for standing
                in state.standings.values()
            ),
            "injury_replacement_player": (
                unavailable_player
            ),
            "coach_sit_player": sit_player,
            "home_secondary_totals": {
                "rebounds": sum(
                    line.rebounds
                    for line in preview_one.game.player_box_scores
                    if line.team_abbreviation == home_team
                ),
                "assists": sum(
                    line.assists
                    for line in preview_one.game.player_box_scores
                    if line.team_abbreviation == home_team
                ),
                "steals": sum(
                    line.steals
                    for line in preview_one.game.player_box_scores
                    if line.team_abbreviation == home_team
                ),
                "blocks": sum(
                    line.blocks
                    for line in preview_one.game.player_box_scores
                    if line.team_abbreviation == home_team
                ),
                "turnovers": sum(
                    line.turnovers
                    for line in preview_one.game.player_box_scores
                    if line.team_abbreviation == home_team
                ),
                "fouls": sum(
                    line.fouls
                    for line in preview_one.game.player_box_scores
                    if line.team_abbreviation == home_team
                ),
            },
            "profile_examples": {
                "jokic_assist_multiplier": (
                    profile_adjusted_stat_multiplier(
                        jokic_id,
                        profiles[jokic_id]["position"],
                        "assists",
                    )
                    if jokic_id
                    else None
                ),
                "curry_assist_multiplier": (
                    profile_adjusted_stat_multiplier(
                        curry_id,
                        profiles[curry_id]["position"],
                        "assists",
                    )
                    if curry_id
                    else None
                ),
                "wembanyama_block_factor": (
                    moderated_player_stat_factor(
                        wemby_id,
                        "blocks",
                    )
                    if wemby_id
                    else None
                ),
                "wembanyama_state_block_factor": (
                    moderated_player_stat_factor(
                        wemby_id,
                        "blocks",
                        state=state,
                    )
                    if wemby_id
                    else None
                ),
            },
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
            "Single Game Simulator V1 self-test "
            "failed: "
            + ", ".join(failed)
        )

    return report


def run_demo(seed: int | None) -> dict[str, Any]:
    base_runtime = load_runtime_data()
    league_state = create_league_state(
        base_runtime
    )
    runtime = build_state_runtime(
        base_runtime,
        league_state,
    )
    state = create_simulation_league_state(
        runtime,
        league_state,
    )
    config = GameSimulationConfig()
    strongest, weakest = (
        strongest_and_weakest_teams(
            state,
            config,
        )
    )

    add_scheduled_games(
        state,
        [
            ScheduledGame(
                game_id="DEMO-GAME-0001",
                day_index=1,
                home_team=weakest,
                away_team=strongest,
            )
        ],
    )
    result = simulate_scheduled_game(
        state,
        "DEMO-GAME-0001",
        seed=seed,
        commit=True,
        config=config,
    )
    summary = game_summary(
        state,
        result,
    )
    summary["standings"] = {
        team: {
            "wins": state.standings[
                team
            ].wins,
            "losses": state.standings[
                team
            ].losses,
            "points_for": (
                state.standings[
                    team
                ].points_for
            ),
            "points_against": (
                state.standings[
                    team
                ].points_against
            ),
        }
        for team in (
            weakest,
            strongest,
        )
    }

    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )
    DEMO_REPORT.write_text(
        json.dumps(
            summary,
            indent=2,
        ),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
    )
    args = parser.parse_args()

    if args.self_test:
        report = run_self_test()
        print(
            json.dumps(
                report,
                indent=2,
        ))
        print(
            "\nSINGLE GAME SIMULATOR V1 "
            "SELF-TEST PASSED"
        )
        return 0

    summary = run_demo(args.seed)
    print(
        json.dumps(
            summary,
            indent=2,
        ))
    print(
        "\nSINGLE GAME SIMULATOR V1 DEMO PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
