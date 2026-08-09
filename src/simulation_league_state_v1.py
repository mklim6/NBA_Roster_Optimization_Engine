from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import (  # noqa: E402
    RuntimeData,
    load_runtime_data,
    normalize_player_id,
    normalize_team,
    to_float,
)
from mutable_league_state_v1 import (  # noqa: E402
    LeagueState,
    create_league_state,
)
from simulation_roster_validator_v1 import (  # noqa: E402
    RosterValidationConfig,
    SimulationPlayer,
    SimulationRosterSnapshot,
    build_simulation_roster_snapshot,
    simulation_player_from_runtime,
)
from state_runtime_adapter_v1 import (  # noqa: E402
    build_state_runtime,
)
from simulation_player_stat_profiles_v1 import (  # noqa: E402
    load_player_stat_profiles,
)
from simulation_player_minutes_v1 import (  # noqa: E402
    build_historical_minutes_plan,
)


SIMULATION_STATE_VERSION = (
    "simulation-league-state-v1.2-2026-08-08"
)
MINUTES_MODEL_VERSION = (
    "simulation-player-minutes-v1-2026-08-08"
)
SELF_TEST_REPORT = (
    OUTPUTS / "simulation_league_state_v1_self_test.json"
)
INITIAL_STATE_REPORT = (
    OUTPUTS / "simulation_league_state_v1_initial.json"
)

DEVELOPMENT_SKILL_FIELDS = (
    "scoring_rating",
    "shooting_rating",
    "playmaking_rating",
    "rebounding_rating",
    "defense_rating",
    "efficiency_rating",
    "availability_rating",
)

DEVELOPMENT_STAT_FACTORS = (
    "points",
    "rebounds",
    "assists",
    "steals",
    "blocks",
    "turnovers",
    "fouls",
    "three_attempts",
    "free_throw_attempts",
)

BASELINE_PER_36_FIELDS = (
    "points_per_36",
    "rebounds_per_36",
    "assists_per_36",
    "steals_per_36",
    "blocks_per_36",
    "turnovers_per_36",
    "fouls_per_36",
    "three_attempts_per_36",
    "free_throw_attempts_per_36",
)


class SimulationLeagueStateError(RuntimeError):
    """Raised when the simulation league state is invalid."""


class LeaguePhase(str, Enum):
    PRESEASON = "preseason"
    REGULAR_SEASON = "regular_season"
    PLAY_IN = "play_in"
    PLAYOFFS = "playoffs"
    OFFSEASON = "offseason"


class GameStatus(str, Enum):
    SCHEDULED = "scheduled"
    COMPLETED = "completed"


class AvailabilityStatus(str, Enum):
    HEALTHY = "healthy"
    DAY_TO_DAY = "day_to_day"
    OUT = "out"


@dataclass(frozen=True)
class SimulationSettings:
    season_label: str = "2026-27"
    regular_season_games_per_team: int = 82
    regulation_minutes: int = 48
    overtime_minutes: int = 5
    rotation_size: int = 10
    minimum_game_players: int = 8
    injuries_enabled: bool = True
    play_in_enabled: bool = True
    random_seed: int = 20260808


@dataclass
class ContractState:
    status: str
    salary: float | None
    years_remaining: int | None = None
    option_type: str = ""
    guaranteed: bool | None = None


@dataclass
class SimulationPlayerState:
    player_id: str
    player_name: str
    team_abbreviation: str
    roster_status: str
    overall_rating: float
    position: str
    synthetic: bool
    rating_source: str
    two_way: bool
    contract: ContractState
    age: float | None = None
    potential_rating: float | None = None
    future_outlook_rating: float | None = None
    development_direction: str = "Stable"
    profile_reliability: float = 0.5
    skill_ratings: dict[str, float] = field(
        default_factory=dict
    )
    stat_factors: dict[str, float] = field(
        default_factory=dict
    )
    baseline_per_36: dict[str, float] = field(
        default_factory=dict
    )
    development_history: list[dict[str, Any]] = field(
        default_factory=list
    )


@dataclass
class RotationState:
    starter_ids: tuple[str, ...]
    rotation_player_ids: tuple[str, ...]
    minutes_targets: dict[str, float]


@dataclass
class SimulationTeamState:
    team_abbreviation: str
    roster_player_ids: tuple[str, ...]
    rotation: RotationState
    active_player_ids: tuple[str, ...]
    inactive_player_ids: tuple[str, ...] = ()
    conference: str = ""
    division: str = ""


@dataclass
class TeamStanding:
    team_abbreviation: str
    games_played: int = 0
    wins: int = 0
    losses: int = 0
    home_wins: int = 0
    home_losses: int = 0
    away_wins: int = 0
    away_losses: int = 0
    points_for: int = 0
    points_against: int = 0
    streak_type: str = ""
    streak_length: int = 0


@dataclass
class InjuryState:
    player_id: str
    status: AvailabilityStatus = AvailabilityStatus.HEALTHY
    injury_type: str = ""
    games_remaining: int = 0
    performance_multiplier: float = 1.0
    aggravation_risk: float = 0.0
    notes: str = ""


@dataclass
class PlayerSeasonTotals:
    player_id: str
    games_played: int = 0
    games_started: int = 0
    minutes: float = 0.0
    points: int = 0
    rebounds: int = 0
    assists: int = 0
    steals: int = 0
    blocks: int = 0
    turnovers: int = 0
    fouls: int = 0
    field_goals_made: int = 0
    field_goals_attempted: int = 0
    three_pointers_made: int = 0
    three_pointers_attempted: int = 0
    free_throws_made: int = 0
    free_throws_attempted: int = 0


@dataclass(frozen=True)
class PlayerBoxScore:
    player_id: str
    team_abbreviation: str
    started: bool
    minutes: float
    points: int
    rebounds: int = 0
    assists: int = 0
    steals: int = 0
    blocks: int = 0
    turnovers: int = 0
    fouls: int = 0
    field_goals_made: int = 0
    field_goals_attempted: int = 0
    three_pointers_made: int = 0
    three_pointers_attempted: int = 0
    free_throws_made: int = 0
    free_throws_attempted: int = 0


@dataclass
class ScheduledGame:
    game_id: str
    day_index: int
    home_team: str
    away_team: str
    status: GameStatus = GameStatus.SCHEDULED


@dataclass(frozen=True)
class CompletedGame:
    game_id: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    overtime_periods: int
    player_box_scores: tuple[PlayerBoxScore, ...]
    box_score_complete: bool = True


@dataclass
class SeasonArchive:
    season_label: str
    standings: dict[str, TeamStanding]
    player_season_totals: dict[
        str,
        PlayerSeasonTotals,
    ]
    schedule: dict[str, ScheduledGame]
    completed_games: dict[str, CompletedGame]
    transition_engine_version: str = ""
    development_summary: dict[str, Any] = field(
        default_factory=dict
    )


@dataclass
class SimulationLeagueState:
    state_version: str
    source_league_state_revision: int
    source_transaction_count: int
    phase: LeaguePhase
    current_day_index: int
    settings: SimulationSettings
    players: dict[str, SimulationPlayerState]
    teams: dict[str, SimulationTeamState]
    free_agent_player_ids: tuple[str, ...]
    standings: dict[str, TeamStanding]
    injuries: dict[str, InjuryState]
    player_season_totals: dict[str, PlayerSeasonTotals]
    schedule: dict[str, ScheduledGame] = field(
        default_factory=dict
    )
    completed_games: dict[str, CompletedGame] = field(
        default_factory=dict
    )
    transition_count: int = 0
    season_history: list[SeasonArchive] = field(
        default_factory=list
    )


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def finite_profile_float(
    value: Any,
    default: float | None = None,
) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default

    return number if math.isfinite(number) else default


def normalized_profile_position(
    profile: dict[str, Any],
    fallback: str,
) -> str:
    position = clean_text(
        profile.get("position")
    ).upper()
    if position and position != "UNK":
        return position

    fallback = clean_text(fallback).upper()
    return fallback or "UNK"


def listed_salary(
    runtime: RuntimeData,
    player_id: str,
) -> float | None:
    player_id = normalize_player_id(player_id)
    record = runtime.trade_by_id.get(player_id, {})
    return to_float(
        record.get("trade_salary_2026_27")
    )


def minutes_targets(
    rotation_ids: tuple[str, ...],
    starter_ids: tuple[str, ...],
    *,
    regulation_minutes: int,
) -> dict[str, float]:
    profiles = load_player_stat_profiles()
    plan = build_historical_minutes_plan(
        rotation_ids,
        starter_ids,
        profiles,
        regulation_minutes=regulation_minutes,
    )
    return dict(plan.targets)


def contract_state_for_player(
    runtime: RuntimeData,
    player: SimulationPlayer,
    roster_status: str,
) -> ContractState:
    if player.synthetic:
        return ContractState(
            status="simulation_replacement",
            salary=0.0,
            years_remaining=0,
            guaranteed=False,
        )

    salary = listed_salary(
        runtime,
        player.player_id,
    )
    status = (
        "under_contract"
        if roster_status == "active_roster"
        else "free_agent_pool"
    )
    return ContractState(
        status=status,
        salary=salary,
    )


def player_state_from_simulation_player(
    runtime: RuntimeData,
    player: SimulationPlayer,
    *,
    roster_status: str,
    profile: dict[str, Any] | None = None,
) -> SimulationPlayerState:
    resolved_profile = profile or {}
    overall = float(player.overall_rating)

    skill_ratings = {
        field_name: float(
            finite_profile_float(
                resolved_profile.get(field_name),
                overall,
            )
            or overall
        )
        for field_name in DEVELOPMENT_SKILL_FIELDS
    }

    raw_factors = resolved_profile.get(
        "stat_factors"
    )
    if not isinstance(raw_factors, dict):
        raw_factors = {}

    stat_factors = {
        factor_name: float(
            finite_profile_float(
                raw_factors.get(factor_name),
                1.0,
            )
            or 1.0
        )
        for factor_name in DEVELOPMENT_STAT_FACTORS
    }
    baseline_per_36 = {
        field_name: float(
            finite_profile_float(
                resolved_profile.get(field_name),
                0.0,
            )
            or 0.0
        )
        for field_name in BASELINE_PER_36_FIELDS
    }

    age = finite_profile_float(
        resolved_profile.get("age_2026_27"),
        finite_profile_float(
            resolved_profile.get("age"),
        ),
    )
    potential = finite_profile_float(
        resolved_profile.get("potential_rating"),
        overall,
    )
    future = finite_profile_float(
        resolved_profile.get(
            "future_outlook_rating"
        ),
        overall,
    )
    reliability = finite_profile_float(
        resolved_profile.get(
            "profile_reliability"
        ),
        0.5,
    )

    return SimulationPlayerState(
        player_id=player.player_id,
        player_name=player.player_name,
        team_abbreviation=normalize_team(
            player.team_abbreviation
        ),
        roster_status=roster_status,
        overall_rating=overall,
        position=normalized_profile_position(
            resolved_profile,
            player.position,
        ),
        synthetic=player.synthetic,
        rating_source=player.rating_source,
        two_way=player.two_way,
        contract=contract_state_for_player(
            runtime,
            player,
            roster_status,
        ),
        age=age,
        potential_rating=potential,
        future_outlook_rating=future,
        development_direction=(
            clean_text(
                resolved_profile.get(
                    "development_direction"
                )
            )
            or "Stable"
        ),
        profile_reliability=float(
            reliability
            if reliability is not None
            else 0.5
        ),
        skill_ratings=skill_ratings,
        stat_factors=stat_factors,
        baseline_per_36=baseline_per_36,
    )


def create_simulation_league_state(
    runtime: RuntimeData,
    league_state: LeagueState,
    *,
    settings: SimulationSettings | None = None,
    roster_config: RosterValidationConfig | None = None,
) -> SimulationLeagueState:
    resolved_settings = settings or SimulationSettings()
    config = roster_config or RosterValidationConfig(
        minimum_game_players=(
            resolved_settings.minimum_game_players
        ),
        target_rotation_size=(
            resolved_settings.rotation_size
        ),
    )
    roster_snapshot = (
        build_simulation_roster_snapshot(
            runtime,
            league_state,
            config=config,
        )
    )

    if not roster_snapshot.ready:
        failed = [
            name
            for name, passed
            in roster_snapshot.checks.items()
            if not passed
        ]
        raise SimulationLeagueStateError(
            "Simulation rosters are not ready: "
            + ", ".join(failed)
        )

    player_profiles = load_player_stat_profiles()
    players: dict[str, SimulationPlayerState] = {}
    teams: dict[str, SimulationTeamState] = {}

    for team, roster in sorted(
        roster_snapshot.teams.items()
    ):
        for player in roster.simulation_players:
            status = (
                "emergency_replacement"
                if player.synthetic
                else "active_roster"
            )
            players[player.player_id] = (
                player_state_from_simulation_player(
                    runtime,
                    player,
                    roster_status=status,
                    profile=player_profiles.get(
                        player.player_id
                    ),
                )
            )

        teams[team] = SimulationTeamState(
            team_abbreviation=team,
            roster_player_ids=tuple(
                player.player_id
                for player in roster.simulation_players
            ),
            rotation=RotationState(
                starter_ids=roster.starting_five_ids,
                rotation_player_ids=(
                    roster.rotation_player_ids
                ),
                minutes_targets=minutes_targets(
                    roster.rotation_player_ids,
                    roster.starting_five_ids,
                    regulation_minutes=(
                        resolved_settings.regulation_minutes
                    ),
                ),
            ),
            active_player_ids=(
                roster.rotation_player_ids
            ),
        )

    active_real_ids = {
        player_id
        for player_id, player in players.items()
        if not player.synthetic
    }
    free_agent_ids = tuple(
        sorted(
            player_id
            for player_id, team
            in league_state.player_team_by_id.items()
            if (
                not normalize_team(team)
                and player_id not in active_real_ids
            )
        )
    )

    for player_id in free_agent_ids:
        free_agent_player = (
            simulation_player_from_runtime(
                runtime,
                player_id=player_id,
                team="",
                config=config,
            )
        )
        players[player_id] = (
            player_state_from_simulation_player(
                runtime,
                free_agent_player,
                roster_status="free_agent",
                profile=player_profiles.get(
                    player_id
                ),
            )
        )

    standings = {
        team: TeamStanding(
            team_abbreviation=team
        )
        for team in teams
    }
    injuries = {
        player_id: InjuryState(
            player_id=player_id
        )
        for player_id in players
    }
    player_totals = {
        player_id: PlayerSeasonTotals(
            player_id=player_id
        )
        for player_id in players
    }

    state = SimulationLeagueState(
        state_version=SIMULATION_STATE_VERSION,
        source_league_state_revision=(
            league_state.state_revision
        ),
        source_transaction_count=len(
            league_state.transaction_history
        ),
        phase=LeaguePhase.PRESEASON,
        current_day_index=0,
        settings=resolved_settings,
        players=players,
        teams=teams,
        free_agent_player_ids=free_agent_ids,
        standings=standings,
        injuries=injuries,
        player_season_totals=player_totals,
    )
    validate_simulation_league_state(state)
    return state


def validate_box_score_line(
    line: PlayerBoxScore,
) -> None:
    if line.minutes < 0:
        raise SimulationLeagueStateError(
            f"{line.player_id} has negative minutes."
        )

    nonnegative = {
        "points": line.points,
        "rebounds": line.rebounds,
        "assists": line.assists,
        "steals": line.steals,
        "blocks": line.blocks,
        "turnovers": line.turnovers,
        "fouls": line.fouls,
        "field_goals_made": (
            line.field_goals_made
        ),
        "field_goals_attempted": (
            line.field_goals_attempted
        ),
        "three_pointers_made": (
            line.three_pointers_made
        ),
        "three_pointers_attempted": (
            line.three_pointers_attempted
        ),
        "free_throws_made": (
            line.free_throws_made
        ),
        "free_throws_attempted": (
            line.free_throws_attempted
        ),
    }

    for name, value in nonnegative.items():
        if value < 0:
            raise SimulationLeagueStateError(
                f"{line.player_id} has negative {name}."
            )

    if (
        line.field_goals_made
        > line.field_goals_attempted
        or line.three_pointers_made
        > line.three_pointers_attempted
        or line.free_throws_made
        > line.free_throws_attempted
        or line.three_pointers_made
        > line.field_goals_made
    ):
        raise SimulationLeagueStateError(
            f"{line.player_id} has impossible shooting totals."
        )

    calculated_points = (
        2
        * (
            line.field_goals_made
            - line.three_pointers_made
        )
        + 3 * line.three_pointers_made
        + line.free_throws_made
    )
    if calculated_points != line.points:
        raise SimulationLeagueStateError(
            f"{line.player_id} points do not reconcile "
            "with made shots."
        )


def validate_completed_game(
    state: SimulationLeagueState,
    game: CompletedGame,
) -> None:
    scheduled = state.schedule.get(game.game_id)

    if scheduled is None:
        raise SimulationLeagueStateError(
            f"Game {game.game_id} is not scheduled."
        )

    if scheduled.status != GameStatus.SCHEDULED:
        raise SimulationLeagueStateError(
            f"Game {game.game_id} is already completed."
        )

    if (
        normalize_team(game.home_team)
        != scheduled.home_team
        or normalize_team(game.away_team)
        != scheduled.away_team
    ):
        raise SimulationLeagueStateError(
            f"Game {game.game_id} teams do not match "
            "the schedule."
        )

    if game.home_score == game.away_score:
        raise SimulationLeagueStateError(
            "Completed games cannot end in a tie."
        )

    if (
        game.home_score < 0
        or game.away_score < 0
        or game.overtime_periods < 0
    ):
        raise SimulationLeagueStateError(
            "Game score or overtime count is invalid."
        )

    seen_players: set[str] = set()
    team_lines = {
        game.home_team: [],
        game.away_team: [],
    }

    for line in game.player_box_scores:
        validate_box_score_line(line)
        player_id = normalize_player_id(
            line.player_id
        )
        team = normalize_team(
            line.team_abbreviation
        )

        if player_id in seen_players:
            raise SimulationLeagueStateError(
                f"Player {player_id} appears twice."
            )
        seen_players.add(player_id)

        if player_id not in state.players:
            raise SimulationLeagueStateError(
                f"Player {player_id} is not in simulation state."
            )

        if team not in team_lines:
            raise SimulationLeagueStateError(
                f"Player {player_id} is assigned to a "
                "non-participating team."
            )

        if (
            state.players[player_id].team_abbreviation
            != team
        ):
            raise SimulationLeagueStateError(
                f"Player {player_id} does not belong to {team}."
            )

        if (
            state.injuries[player_id].status
            == AvailabilityStatus.OUT
        ):
            raise SimulationLeagueStateError(
                f"Player {player_id} is unavailable."
            )

        team_lines[team].append(line)

    if game.box_score_complete:
        expected_minutes = (
            state.settings.regulation_minutes * 5
            + state.settings.overtime_minutes
            * 5
            * game.overtime_periods
        )
        expected_scores = {
            game.home_team: game.home_score,
            game.away_team: game.away_score,
        }

        for team, lines in team_lines.items():
            if not lines:
                raise SimulationLeagueStateError(
                    f"{team} has no box-score lines."
                )

            minutes = sum(
                line.minutes
                for line in lines
            )
            if not math.isclose(
                minutes,
                expected_minutes,
                abs_tol=0.1,
            ):
                raise SimulationLeagueStateError(
                    f"{team} player minutes total {minutes}, "
                    f"expected {expected_minutes}."
                )

            points = sum(
                line.points
                for line in lines
            )
            if points != expected_scores[team]:
                raise SimulationLeagueStateError(
                    f"{team} player points total {points}, "
                    f"expected {expected_scores[team]}."
                )

            starter_count = sum(
                line.started
                for line in lines
            )
            if starter_count != 5:
                raise SimulationLeagueStateError(
                    f"{team} has {starter_count} starters, "
                    "expected 5."
                )


def validate_simulation_league_state(
    state: SimulationLeagueState,
) -> dict[str, bool]:
    team_ids = set(state.teams)
    player_ids = set(state.players)
    roster_ids = [
        player_id
        for team in state.teams.values()
        for player_id
        in team.roster_player_ids
    ]
    free_agent_ids = set(
        state.free_agent_player_ids
    )

    checks = {
        "state_version_matches": (
            state.state_version
            == SIMULATION_STATE_VERSION
        ),
        "exactly_30_teams": (
            len(state.teams) == 30
        ),
        "standings_cover_all_teams": (
            set(state.standings) == team_ids
        ),
        "injuries_cover_all_players": (
            set(state.injuries) == player_ids
        ),
        "season_totals_cover_all_players": (
            set(state.player_season_totals)
            == player_ids
        ),
        "team_roster_ids_unique": (
            len(roster_ids)
            == len(set(roster_ids))
        ),
        "free_agents_not_on_rosters": (
            not free_agent_ids.intersection(
                roster_ids
            )
        ),
        "free_agents_exist": (
            free_agent_ids.issubset(
                player_ids
            )
        ),
        "all_team_rosters_playable": all(
            len(team.roster_player_ids)
            >= state.settings.minimum_game_players
            for team in state.teams.values()
        ),
        "rotations_are_roster_subsets": all(
            set(team.rotation.rotation_player_ids)
            .issubset(team.roster_player_ids)
            and set(team.rotation.starter_ids)
            .issubset(
                team.rotation.rotation_player_ids
            )
            for team in state.teams.values()
        ),
        "all_teams_have_five_starters": all(
            len(team.rotation.starter_ids)
            == 5
            for team in state.teams.values()
        ),
        "rotation_minutes_reconcile": all(
            math.isclose(
                sum(
                    team.rotation.minutes_targets.values()
                ),
                state.settings.regulation_minutes * 5,
                abs_tol=0.1,
            )
            for team in state.teams.values()
        ),
        "schedule_teams_are_valid": all(
            game.home_team in team_ids
            and game.away_team in team_ids
            and game.home_team != game.away_team
            for game in state.schedule.values()
        ),
        "completed_games_are_scheduled": (
            set(state.completed_games)
            .issubset(state.schedule)
        ),
        "season_label_is_present": bool(
            clean_text(state.settings.season_label)
        ),
        "all_real_players_have_resolved_positions": all(
            player.synthetic
            or (
                clean_text(player.position).upper()
                not in {"", "UNK"}
            )
            for player in state.players.values()
        ),
        "all_real_players_have_development_profiles": all(
            player.synthetic
            or (
                player.age is not None
                and 18 <= player.age <= 50
                and set(player.skill_ratings)
                == set(DEVELOPMENT_SKILL_FIELDS)
                and set(player.stat_factors)
                == set(DEVELOPMENT_STAT_FACTORS)
                and set(player.baseline_per_36)
                == set(BASELINE_PER_36_FIELDS)
                and 0
                <= player.profile_reliability
                <= 1
            )
            for player in state.players.values()
        ),
        "development_values_are_finite": all(
            all(
                math.isfinite(float(value))
                for value in (
                    player.overall_rating,
                    *player.skill_ratings.values(),
                    *player.stat_factors.values(),
                    *player.baseline_per_36.values(),
                )
            )
            for player in state.players.values()
        ),
        "season_history_matches_transition_count": (
            len(state.season_history)
            == state.transition_count
        ),
    }

    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]

    if failed:
        raise SimulationLeagueStateError(
            "Simulation league-state validation failed: "
            + ", ".join(failed)
        )

    return checks


def add_scheduled_games(
    state: SimulationLeagueState,
    games: Iterable[ScheduledGame],
) -> None:
    prepared = list(games)
    seen = set(state.schedule)

    for game in prepared:
        game_id = clean_text(game.game_id)
        home_team = normalize_team(
            game.home_team
        )
        away_team = normalize_team(
            game.away_team
        )

        if not game_id:
            raise SimulationLeagueStateError(
                "Scheduled games require a game ID."
            )

        if game_id in seen:
            raise SimulationLeagueStateError(
                f"Duplicate game ID: {game_id}."
            )
        seen.add(game_id)

        if (
            home_team not in state.teams
            or away_team not in state.teams
            or home_team == away_team
        ):
            raise SimulationLeagueStateError(
                f"Game {game_id} has invalid teams."
            )

        if game.day_index < 1:
            raise SimulationLeagueStateError(
                f"Game {game_id} has an invalid day index."
            )

        if game.status != GameStatus.SCHEDULED:
            raise SimulationLeagueStateError(
                "New schedule entries must be scheduled."
            )

    for game in prepared:
        game_id = clean_text(game.game_id)
        state.schedule[game_id] = ScheduledGame(
            game_id=game_id,
            day_index=int(game.day_index),
            home_team=normalize_team(
                game.home_team
            ),
            away_team=normalize_team(
                game.away_team
            ),
            status=GameStatus.SCHEDULED,
        )

    if prepared:
        state.phase = LeaguePhase.REGULAR_SEASON

    validate_simulation_league_state(state)


def update_streak(
    standing: TeamStanding,
    *,
    won: bool,
) -> None:
    result = "W" if won else "L"

    if standing.streak_type == result:
        standing.streak_length += 1
    else:
        standing.streak_type = result
        standing.streak_length = 1


def add_player_totals(
    totals: PlayerSeasonTotals,
    line: PlayerBoxScore,
) -> None:
    totals.games_played += 1
    totals.games_started += int(line.started)
    totals.minutes = round(
        totals.minutes + line.minutes,
        1,
    )
    totals.points += line.points
    totals.rebounds += line.rebounds
    totals.assists += line.assists
    totals.steals += line.steals
    totals.blocks += line.blocks
    totals.turnovers += line.turnovers
    totals.fouls += line.fouls
    totals.field_goals_made += (
        line.field_goals_made
    )
    totals.field_goals_attempted += (
        line.field_goals_attempted
    )
    totals.three_pointers_made += (
        line.three_pointers_made
    )
    totals.three_pointers_attempted += (
        line.three_pointers_attempted
    )
    totals.free_throws_made += (
        line.free_throws_made
    )
    totals.free_throws_attempted += (
        line.free_throws_attempted
    )


def record_completed_game(
    state: SimulationLeagueState,
    game: CompletedGame,
) -> None:
    validate_completed_game(state, game)

    home = state.standings[game.home_team]
    away = state.standings[game.away_team]
    home_won = game.home_score > game.away_score

    home.games_played += 1
    away.games_played += 1
    home.points_for += game.home_score
    home.points_against += game.away_score
    away.points_for += game.away_score
    away.points_against += game.home_score

    if home_won:
        home.wins += 1
        home.home_wins += 1
        away.losses += 1
        away.away_losses += 1
    else:
        away.wins += 1
        away.away_wins += 1
        home.losses += 1
        home.home_losses += 1

    update_streak(home, won=home_won)
    update_streak(away, won=not home_won)

    for line in game.player_box_scores:
        add_player_totals(
            state.player_season_totals[
                line.player_id
            ],
            line,
        )

    state.schedule[game.game_id].status = (
        GameStatus.COMPLETED
    )
    state.completed_games[game.game_id] = game
    state.current_day_index = max(
        state.current_day_index,
        state.schedule[
            game.game_id
        ].day_index,
    )

    validate_simulation_league_state(state)


def set_player_injury(
    state: SimulationLeagueState,
    player_id: str,
    *,
    status: AvailabilityStatus | str,
    injury_type: str = "",
    games_remaining: int = 0,
    performance_multiplier: float = 1.0,
    aggravation_risk: float = 0.0,
    notes: str = "",
) -> None:
    player_id = normalize_player_id(
        player_id
    )

    if player_id not in state.players:
        raise SimulationLeagueStateError(
            f"Unknown simulation player: {player_id}."
        )

    resolved_status = AvailabilityStatus(status)

    if games_remaining < 0:
        raise SimulationLeagueStateError(
            "Games remaining cannot be negative."
        )

    if not 0 < performance_multiplier <= 1:
        raise SimulationLeagueStateError(
            "Performance multiplier must be above 0 "
            "and at most 1."
        )

    if not 0 <= aggravation_risk <= 1:
        raise SimulationLeagueStateError(
            "Aggravation risk must be between 0 and 1."
        )

    if resolved_status == AvailabilityStatus.HEALTHY:
        injury_type = ""
        games_remaining = 0
        performance_multiplier = 1.0
        aggravation_risk = 0.0
        notes = ""

    state.injuries[player_id] = InjuryState(
        player_id=player_id,
        status=resolved_status,
        injury_type=clean_text(injury_type),
        games_remaining=int(games_remaining),
        performance_multiplier=float(
            performance_multiplier
        ),
        aggravation_risk=float(
            aggravation_risk
        ),
        notes=clean_text(notes),
    )


def initial_state_summary(
    state: SimulationLeagueState,
) -> dict[str, Any]:
    rostered = sum(
        len(team.roster_player_ids)
        for team in state.teams.values()
    )
    synthetic = sum(
        player.synthetic
        for player in state.players.values()
    )
    return {
        "script": SIMULATION_STATE_VERSION,
        "source_league_state_revision": (
            state.source_league_state_revision
        ),
        "teams": len(state.teams),
        "players": len(state.players),
        "rostered_players": rostered,
        "free_agents": len(
            state.free_agent_player_ids
        ),
        "synthetic_players": synthetic,
        "scheduled_games": len(
            state.schedule
        ),
        "completed_games": len(
            state.completed_games
        ),
        "phase": state.phase.value,
        "season_label": state.settings.season_label,
        "transition_count": state.transition_count,
        "archived_seasons": len(
            state.season_history
        ),
        "checks": validate_simulation_league_state(
            state
        ),
    }


def make_box_score_lines(
    state: SimulationLeagueState,
    team: str,
    *,
    point_values: tuple[int, ...],
) -> tuple[PlayerBoxScore, ...]:
    team_state = state.teams[team]
    player_ids = (
        team_state.rotation.rotation_player_ids[:8]
    )
    minute_values = (
        36.0,
        34.0,
        32.0,
        30.0,
        28.0,
        26.0,
        24.0,
        30.0,
    )

    if len(player_ids) != 8:
        raise AssertionError(
            f"{team} does not have eight rotation players."
        )

    if len(point_values) != 8:
        raise AssertionError(
            "Self-test point values require eight players."
        )

    lines: list[PlayerBoxScore] = []

    for index, (
        player_id,
        minutes,
        points,
    ) in enumerate(
        zip(
            player_ids,
            minute_values,
            point_values,
        )
    ):
        three_made = points // 3
        remainder = points - 3 * three_made

        if remainder == 1 and three_made > 0:
            three_made -= 1
            two_made = 2
            free_throws = 0
        else:
            two_made = remainder // 2
            free_throws = remainder % 2

        field_goals_made = (
            three_made + two_made
        )
        lines.append(
            PlayerBoxScore(
                player_id=player_id,
                team_abbreviation=team,
                started=(
                    player_id
                    in team_state.rotation.starter_ids
                ),
                minutes=minutes,
                points=points,
                rebounds=3 + index,
                assists=2 + index % 5,
                steals=index % 3,
                blocks=index % 2,
                turnovers=1 + index % 3,
                fouls=1 + index % 4,
                field_goals_made=(
                    field_goals_made
                ),
                field_goals_attempted=(
                    field_goals_made + 4
                ),
                three_pointers_made=three_made,
                three_pointers_attempted=(
                    three_made + 2
                ),
                free_throws_made=free_throws,
                free_throws_attempted=free_throws,
            )
        )

    return tuple(lines)


def source_signature(
    runtime: RuntimeData,
    league_state: LeagueState,
) -> dict[str, Any]:
    return {
        "league_revision": (
            league_state.state_revision
        ),
        "league_players": tuple(
            sorted(
                league_state
                .player_team_by_id.items()
            )
        ),
        "runtime_trade_ids": tuple(
            sorted(runtime.trade_by_id)
        ),
        "runtime_rating_ids": tuple(
            sorted(runtime.ratings_by_id)
        ),
    }


def run_self_test() -> dict[str, Any]:
    base_runtime = load_runtime_data()
    league_state = create_league_state(
        base_runtime
    )
    runtime = build_state_runtime(
        base_runtime,
        league_state,
    )
    source_before = source_signature(
        runtime,
        league_state,
    )

    state = create_simulation_league_state(
        runtime,
        league_state,
    )
    checks: dict[str, bool] = {}

    checks["initial_state_valid"] = bool(
        validate_simulation_league_state(state)
    )
    checks["initial_has_30_teams"] = (
        len(state.teams) == 30
    )
    checks["all_582_real_players_preserved"] = (
        len(
            [
                player
                for player in state.players.values()
                if not player.synthetic
            ]
        )
        == 582
    )
    checks["player_development_profiles_loaded"] = all(
        player.synthetic
        or (
            player.age is not None
            and player.position != "UNK"
            and len(player.skill_ratings)
            == len(DEVELOPMENT_SKILL_FIELDS)
            and len(player.stat_factors)
            == len(DEVELOPMENT_STAT_FACTORS)
        )
        for player in state.players.values()
    )
    checks["active_and_free_agent_counts_reconcile"] = (
        sum(
            len(team.roster_player_ids)
            for team in state.teams.values()
            if team.roster_player_ids
        )
        + len(state.free_agent_player_ids)
        == len(state.players)
    )
    checks["all_rotations_have_240_minutes"] = (
        all(
            math.isclose(
                sum(
                    team.rotation
                    .minutes_targets.values()
                ),
                240.0,
                abs_tol=0.1,
            )
            for team in state.teams.values()
        )
    )
    all_minute_targets = [
        target
        for team in state.teams.values()
        for target
        in team.rotation.minutes_targets.values()
    ]
    checks["historical_minutes_model_is_active"] = (
        MINUTES_MODEL_VERSION
        == (
            "simulation-player-minutes-v1-2026-08-08"
        )
    )
    checks["rotation_minutes_are_not_flat"] = (
        len(
            {
                round(value, 1)
                for value
                in all_minute_targets
            }
        )
        >= 12
    )

    player_id_by_name = {
        player.player_name: player_id
        for player_id, player
        in state.players.items()
    }
    for star_name in (
        "Shai Gilgeous-Alexander",
        "Luka Dončić",
    ):
        player_id = player_id_by_name.get(
            star_name
        )
        if player_id is None:
            checks[
                "historical_star_minutes_are_above_30"
            ] = False
            break

        team = state.players[
            player_id
        ].team_abbreviation
        target = (
            state.teams[
                team
            ].rotation.minutes_targets.get(
                player_id,
                0.0,
            )
        )
        if target <= 30.0:
            checks[
                "historical_star_minutes_are_above_30"
            ] = False
            break
    else:
        checks[
            "historical_star_minutes_are_above_30"
        ] = True

    teams = sorted(state.teams)
    home_team = teams[0]
    away_team = teams[1]
    add_scheduled_games(
        state,
        [
            ScheduledGame(
                game_id="TEST-GAME-0001",
                day_index=1,
                home_team=home_team,
                away_team=away_team,
            ),
            ScheduledGame(
                game_id="TEST-GAME-0002",
                day_index=2,
                home_team=teams[2],
                away_team=teams[3],
            ),
        ],
    )
    checks["schedule_registration_succeeds"] = (
        len(state.schedule) == 2
        and state.phase
        == LeaguePhase.REGULAR_SEASON
    )

    home_points = (
        22,
        18,
        16,
        14,
        12,
        10,
        8,
        6,
    )
    away_points = (
        20,
        17,
        15,
        13,
        11,
        9,
        7,
        5,
    )
    home_score = sum(home_points)
    away_score = sum(away_points)
    game = CompletedGame(
        game_id="TEST-GAME-0001",
        home_team=home_team,
        away_team=away_team,
        home_score=home_score,
        away_score=away_score,
        overtime_periods=0,
        player_box_scores=(
            *make_box_score_lines(
                state,
                home_team,
                point_values=home_points,
            ),
            *make_box_score_lines(
                state,
                away_team,
                point_values=away_points,
            ),
        ),
    )
    record_completed_game(state, game)

    checks["game_recorded"] = (
        "TEST-GAME-0001"
        in state.completed_games
        and state.schedule[
            "TEST-GAME-0001"
        ].status
        == GameStatus.COMPLETED
    )
    checks["standings_updated"] = (
        state.standings[home_team].wins == 1
        and state.standings[home_team].losses == 0
        and state.standings[away_team].wins == 0
        and state.standings[away_team].losses == 1
        and state.standings[
            home_team
        ].points_for
        == home_score
        and state.standings[
            away_team
        ].points_for
        == away_score
    )

    first_home_player = (
        state.teams[home_team]
        .rotation.rotation_player_ids[0]
    )
    first_totals = (
        state.player_season_totals[
            first_home_player
        ]
    )
    checks["player_totals_updated"] = (
        first_totals.games_played == 1
        and first_totals.games_started == 1
        and first_totals.minutes == 36.0
        and first_totals.points == 22
    )

    injured_player = (
        state.teams[away_team]
        .rotation.rotation_player_ids[0]
    )
    set_player_injury(
        state,
        injured_player,
        status=AvailabilityStatus.DAY_TO_DAY,
        injury_type="ankle soreness",
        games_remaining=1,
        performance_multiplier=0.94,
        aggravation_risk=0.12,
        notes="Self-test coaching decision case.",
    )
    checks["injury_state_updates"] = (
        state.injuries[
            injured_player
        ].status
        == AvailabilityStatus.DAY_TO_DAY
        and state.injuries[
            injured_player
        ].aggravation_risk
        == 0.12
    )

    set_player_injury(
        state,
        injured_player,
        status=AvailabilityStatus.HEALTHY,
    )
    checks["injury_state_clears"] = (
        state.injuries[
            injured_player
        ].status
        == AvailabilityStatus.HEALTHY
        and state.injuries[
            injured_player
        ].games_remaining
        == 0
    )

    duplicate_game_blocked = False
    try:
        add_scheduled_games(
            state,
            [
                ScheduledGame(
                    game_id="TEST-GAME-0002",
                    day_index=3,
                    home_team=teams[4],
                    away_team=teams[5],
                )
            ],
        )
    except SimulationLeagueStateError:
        duplicate_game_blocked = True
    checks["duplicate_game_id_blocked"] = (
        duplicate_game_blocked
    )

    same_team_blocked = False
    try:
        add_scheduled_games(
            state,
            [
                ScheduledGame(
                    game_id="TEST-GAME-BAD",
                    day_index=3,
                    home_team=teams[4],
                    away_team=teams[4],
                )
            ],
        )
    except SimulationLeagueStateError:
        same_team_blocked = True
    checks["same_team_game_blocked"] = (
        same_team_blocked
    )

    duplicate_result_blocked = False
    try:
        record_completed_game(state, game)
    except SimulationLeagueStateError:
        duplicate_result_blocked = True
    checks["duplicate_game_result_blocked"] = (
        duplicate_result_blocked
    )

    checks["state_still_valid"] = bool(
        validate_simulation_league_state(state)
    )
    checks["source_state_and_runtime_not_mutated"] = (
        source_signature(runtime, league_state)
        == source_before
    )

    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]
    report = {
        "script": SIMULATION_STATE_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "teams": len(state.teams),
            "players": len(state.players),
            "free_agents": len(
                state.free_agent_player_ids
            ),
            "scheduled_games": len(
                state.schedule
            ),
            "completed_games": len(
                state.completed_games
            ),
            "home_team": home_team,
            "away_team": away_team,
            "final_score": (
                f"{home_team} {home_score}, "
                f"{away_team} {away_score}"
            ),
            "current_day_index": (
                state.current_day_index
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
            "Simulation League State V1 self-test "
            "failed: "
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
        report = run_self_test()
        print(
            json.dumps(
                report,
                indent=2,
            )
        )
        print(
            "\nSIMULATION LEAGUE STATE V1 "
            "SELF-TEST PASSED"
        )
        return 0

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
    report = initial_state_summary(state)

    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )
    INITIAL_STATE_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                **report,
                "output": str(
                    INITIAL_STATE_REPORT
                ),
            },
            indent=2,
        )
    )
    print(
        "\nSIMULATION LEAGUE STATE V1 INITIALIZED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
