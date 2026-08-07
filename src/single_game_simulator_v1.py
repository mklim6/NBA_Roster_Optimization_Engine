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
from state_runtime_adapter_v1 import (  # noqa: E402
    build_state_runtime,
)


ENGINE_VERSION = "single-game-simulator-v1-2026-08-08"
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

    if injury.status == AvailabilityStatus.OUT:
        return 0.0

    multiplier = (
        injury.performance_multiplier
        if injury.status
        == AvailabilityStatus.DAY_TO_DAY
        else 1.0
    )
    return round(
        player.overall_rating * multiplier,
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
        if injury.status == AvailabilityStatus.OUT:
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


def allocate_minutes(
    state: SimulationLeagueState,
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
    starter_set = set(starter_ids)
    ratings = {
        player_id: effective_player_rating(
            state,
            player_id,
        )
        for player_id in rotation_ids
    }
    team_average = (
        sum(ratings.values()) / len(ratings)
    )
    weights = {}

    for player_id in rotation_ids:
        role_weight = (
            1.36
            if player_id in starter_set
            else 0.74
        )
        rating_weight = clamp(
            1.0
            + (
                ratings[player_id]
                - team_average
            )
            * 0.025,
            0.72,
            1.30,
        )
        weights[player_id] = (
            role_weight * rating_weight
        )

    minute_tenths = allocate_integer_units(
        int(total_minutes * 10),
        rotation_ids,
        weights,
    )
    return {
        player_id: minute_tenths[
            player_id
        ]
        / 10.0
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


def usage_weights(
    rng: random.Random,
    plan: TeamGamePlan,
) -> dict[str, float]:
    starter_set = set(plan.starter_ids)
    minute_weighted_average = (
        sum(
            plan.minutes[player_id]
            * plan.effective_ratings[player_id]
            for player_id in plan.player_ids
        )
        / sum(plan.minutes.values())
    )
    weights = {}

    for player_id in plan.player_ids:
        rating_edge = (
            plan.effective_ratings[player_id]
            - minute_weighted_average
        )
        role_weight = (
            1.08
            if player_id in starter_set
            else 0.93
        )
        variation = rng.uniform(0.84, 1.16)
        weights[player_id] = (
            plan.minutes[player_id]
            * clamp(
                1.0 + rating_edge * 0.065,
                0.40,
                2.10,
            )
            * role_weight
            * variation
        )

    return weights


def scoring_components(
    rng: random.Random,
    *,
    points: int,
    position: str,
    overall_rating: float,
) -> tuple[int, int, int, int, int, int]:
    if points < 0:
        raise SingleGameSimulationError(
            "Player points cannot be negative."
        )

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

    three_miss_rate = clamp(
        0.85 - (overall_rating - 67.0) * 0.018,
        0.35,
        0.95,
    )
    two_miss_rate = clamp(
        0.72 - (overall_rating - 67.0) * 0.016,
        0.28,
        0.82,
    )
    free_throw_miss_rate = clamp(
        0.30 - (overall_rating - 67.0) * 0.007,
        0.06,
        0.30,
    )

    three_misses = max(
        0,
        round(
            three_made * three_miss_rate
            + rng.uniform(0.0, 1.4)
        ),
    )
    two_misses = max(
        0,
        round(
            two_made * two_miss_rate
            + rng.uniform(0.0, 1.4)
        ),
    )
    free_throw_misses = max(
        0,
        round(
            free_throws_made
            * free_throw_miss_rate
            + (
                rng.uniform(0.0, 0.8)
                if free_throws_made
                else 0.0
            )
        ),
    )

    field_goals_made = (
        two_made + three_made
    )
    three_attempted = (
        three_made + three_misses
    )
    field_goals_attempted = (
        field_goals_made
        + two_misses
        + three_misses
    )
    free_throws_attempted = (
        free_throws_made
        + free_throw_misses
    )

    return (
        field_goals_made,
        field_goals_attempted,
        three_made,
        three_attempted,
        free_throws_made,
        free_throws_attempted,
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


def build_player_box_scores(
    rng: random.Random,
    state: SimulationLeagueState,
    plan: TeamGamePlan,
    *,
    team_score: int,
) -> tuple[PlayerBoxScore, ...]:
    point_allocation = allocate_integer_units(
        team_score,
        plan.player_ids,
        usage_weights(rng, plan),
    )
    starter_set = set(plan.starter_ids)
    lines: list[PlayerBoxScore] = []

    for player_id in plan.player_ids:
        player = state.players[player_id]
        minutes = plan.minutes[player_id]
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
        )

        guard = any(
            token in player.position
            for token in ("PG", "SG")
        )
        wing = "SF" in player.position
        big = any(
            token in player.position
            for token in ("PF", "C")
        )
        minute_share = minutes / 36.0
        rating_factor = clamp(
            (
                plan.effective_ratings[player_id]
                - 67.0
            )
            / 18.0,
            0.25,
            1.55,
        )

        rebounds = noisy_count(
            rng,
            minute_share
            * (
                3.1
                + 3.5 * int(big)
                + 0.9 * int(wing)
            ),
            maximum=22,
        )
        assists = noisy_count(
            rng,
            minute_share
            * (
                2.1
                + 3.8 * int(guard)
                + 0.8 * rating_factor
            ),
            maximum=18,
        )
        steals = noisy_count(
            rng,
            minute_share * 0.95,
            maximum=7,
        )
        blocks = noisy_count(
            rng,
            minute_share
            * (
                0.35
                + 1.15 * int(big)
            ),
            maximum=8,
        )
        turnovers = noisy_count(
            rng,
            minute_share
            * (
                1.0
                + points / 24.0
                + 0.65 * int(guard)
            ),
            maximum=9,
        )
        fouls = noisy_count(
            rng,
            minute_share
            * (
                1.65
                + 0.45 * int(big)
            ),
            maximum=6,
        )

        lines.append(
            PlayerBoxScore(
                player_id=player_id,
                team_abbreviation=(
                    plan.team_abbreviation
                ),
                started=(
                    player_id in starter_set
                ),
                minutes=minutes,
                points=points,
                rebounds=rebounds,
                assists=assists,
                steals=steals,
                blocks=blocks,
                turnovers=turnovers,
                fouls=fouls,
                field_goals_made=(
                    field_goals_made
                ),
                field_goals_attempted=(
                    field_goals_attempted
                ),
                three_pointers_made=(
                    three_pointers_made
                ),
                three_pointers_attempted=(
                    three_pointers_attempted
                ),
                free_throws_made=(
                    free_throws_made
                ),
                free_throws_attempted=(
                    free_throws_attempted
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
) -> SimulatedGame:
    resolved_config = (
        config or GameSimulationConfig()
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

    sit_ids = {
        normalize_player_id(player_id)
        for player_id in sit_player_ids
        if normalize_player_id(player_id)
    }
    resolved_seed = stable_seed(
        state,
        game_id,
        seed,
    )
    rng = random.Random(resolved_seed)

    home_regulation_plan = build_team_game_plan(
        state,
        scheduled.home_team,
        sit_player_ids=sit_ids,
        overtime_periods=0,
        config=resolved_config,
    )
    away_regulation_plan = build_team_game_plan(
        state,
        scheduled.away_team,
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

    home_plan = build_team_game_plan(
        state,
        scheduled.home_team,
        sit_player_ids=sit_ids,
        overtime_periods=overtime_periods,
        config=resolved_config,
    )
    away_plan = build_team_game_plan(
        state,
        scheduled.away_team,
        sit_player_ids=sit_ids,
        overtime_periods=overtime_periods,
        config=resolved_config,
    )

    home_lines = build_player_box_scores(
        rng,
        state,
        home_plan,
        team_score=home_score,
    )
    away_lines = build_player_box_scores(
        rng,
        state,
        away_plan,
        team_score=away_score,
    )
    game = CompletedGame(
        game_id=game_id,
        home_team=scheduled.home_team,
        away_team=scheduled.away_team,
        home_score=home_score,
        away_score=away_score,
        overtime_periods=overtime_periods,
        player_box_scores=(
            *home_lines,
            *away_lines,
        ),
        box_score_complete=True,
    )

    validate_completed_game(state, game)

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
        home_team=scheduled.home_team,
        away_team=scheduled.away_team,
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
            state,
            game,
        )

    return SimulatedGame(
        game=game,
        metadata=metadata,
        committed=commit,
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