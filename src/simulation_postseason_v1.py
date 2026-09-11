from __future__ import annotations

import argparse
import copy
import json
import math
import sys
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_command_center_v1 import (  # noqa: E402
    FranchiseSimulationPolicy,
    game_requires_decision,
)
from simulation_league_alignment_v1 import (  # noqa: E402
    conference_for_team,
)
from simulation_league_state_v1 import (  # noqa: E402
    CompletedGame,
    GameStatus,
    LeaguePhase,
    PlayerSeasonTotals,
    ScheduledGame,
    SimulationLeagueState,
    SimulationLeagueStateError,
    add_player_totals,
    validate_simulation_league_state,
)
from simulation_injury_fatigue_v1 import (  # noqa: E402
    INJURY_FATIGUE_VERSION,
)
from single_game_simulator_v1 import (  # noqa: E402
    SimulatedGame,
    simulate_scheduled_game,
)


POSTSEASON_VERSION = (
    "simulation-postseason-v1-2026-08-08"
)
POSTSEASON_INTERFACE_VERSION = (
    "postseason-command-game-center-v1.1-2026-08-08"
)
POSTSEASON_EXECUTION_VERSION = (
    "postseason-batch-performance-v1-2026-08-09"
)
SELF_TEST_REPORT = (
    OUTPUTS
    / "simulation_postseason_v1_self_test.json"
)

HOME_COURT_PATTERN = (
    "higher",
    "higher",
    "lower",
    "lower",
    "higher",
    "lower",
    "higher",
)


class SimulationPostseasonError(
    RuntimeError
):
    """Raised when the postseason state or transition is invalid."""


class PostseasonStage(str, Enum):
    NOT_STARTED = "not_started"
    PLAY_IN_OPENING = "play_in_opening"
    PLAY_IN_FINAL = "play_in_final"
    FIRST_ROUND = "first_round"
    CONFERENCE_SEMIFINALS = (
        "conference_semifinals"
    )
    CONFERENCE_FINALS = (
        "conference_finals"
    )
    NBA_FINALS = "nba_finals"
    COMPLETE = "complete"


class PostseasonGameStatus(str, Enum):
    SCHEDULED = "scheduled"
    COMPLETED = "completed"


class PostseasonSimulationScope(str, Enum):
    NEXT_GAME = "next_game"
    NEXT_CONTROLLED_GAME = "next_controlled_game"
    CURRENT_STAGE = "current_stage"
    TO_CHAMPION = "to_champion"


@dataclass
class PostseasonGame:
    game_id: str
    day_index: int
    stage: PostseasonStage
    conference: str
    round_label: str
    series_id: str
    game_number: int
    home_team: str
    away_team: str
    home_seed: int | None
    away_seed: int | None
    status: PostseasonGameStatus = (
        PostseasonGameStatus.SCHEDULED
    )
    winner: str = ""
    loser: str = ""
    home_score: int | None = None
    away_score: int | None = None
    overtime_periods: int = 0


@dataclass
class PostseasonSeries:
    series_id: str
    stage: PostseasonStage
    conference: str
    round_label: str
    higher_seed_team: str
    lower_seed_team: str
    higher_seed_rank: int
    lower_seed_rank: int
    higher_seed_wins: int = 0
    lower_seed_wins: int = 0
    game_ids: list[str] = field(
        default_factory=list
    )
    winner: str = ""
    loser: str = ""


@dataclass
class SimulationPostseasonState:
    version: str
    season_label: str
    initialized: bool
    stage: PostseasonStage
    seed_order: dict[str, tuple[str, ...]]
    seed_by_team: dict[str, int]
    games: dict[str, PostseasonGame]
    completed_games: dict[
        str,
        CompletedGame,
    ]
    series: dict[str, PostseasonSeries]
    postseason_player_totals: dict[
        str,
        PlayerSeasonTotals,
    ]
    conference_champions: dict[str, str]
    champion: str
    runner_up: str
    created_day_index: int
    next_day_index: int
    game_sequence: int
    bracket_created: bool = False


@dataclass(frozen=True)
class PostseasonAdvanceResult:
    version: str
    scope: PostseasonSimulationScope
    games_simulated: int
    game_ids: tuple[str, ...]
    paused_before_game_id: str
    stage_before: PostseasonStage
    stage_after: PostseasonStage
    champion: str
    stopped_at_game_limit: bool


@dataclass(frozen=True)
class PostseasonTeamStatus:
    team: str
    seed: int | None
    stage: PostseasonStage
    alive: bool
    eliminated: bool
    champion: bool
    runner_up: bool
    current_series_id: str
    current_round: str
    series_wins: int
    series_losses: int
    next_game_id: str


def clean_team(
    value: Any,
) -> str:
    return str(value or "").strip().upper()


def postseason_state_is_compatible(
    postseason: Any,
) -> bool:
    required = (
        "version",
        "season_label",
        "initialized",
        "stage",
        "seed_order",
        "seed_by_team",
        "games",
        "completed_games",
        "series",
        "postseason_player_totals",
        "conference_champions",
        "champion",
        "runner_up",
        "created_day_index",
        "next_day_index",
        "game_sequence",
    )
    return bool(
        postseason is not None
        and all(
            hasattr(
                postseason,
                name,
            )
            for name in required
        )
        and str(
            postseason.version
        )
        == POSTSEASON_VERSION
        and isinstance(
            postseason.games,
            dict,
        )
        and isinstance(
            postseason.series,
            dict,
        )
    )


def postseason_attached(
    state: SimulationLeagueState,
) -> bool:
    return postseason_state_is_compatible(
        getattr(
            state,
            "postseason_state",
            None,
        )
    )


def get_postseason_state(
    state: SimulationLeagueState,
    *,
    required: bool = True,
) -> SimulationPostseasonState | None:
    postseason = getattr(
        state,
        "postseason_state",
        None,
    )

    if postseason_state_is_compatible(
        postseason
    ):
        return postseason

    if required:
        raise SimulationPostseasonError(
            "The postseason has not been initialized."
        )

    return None


def regular_season_is_complete(
    state: SimulationLeagueState,
) -> bool:
    expected = (
        state.settings
        .regular_season_games_per_team
    )
    return bool(
        len(state.standings) == 30
        and all(
            standing.games_played
            == expected
            and standing.wins
            + standing.losses
            == expected
            for standing
            in state.standings.values()
        )
    )


def game_winner(
    completed: CompletedGame,
) -> str:
    return (
        completed.home_team
        if completed.home_score
        > completed.away_score
        else completed.away_team
    )


def game_loser(
    completed: CompletedGame,
) -> str:
    winner = game_winner(completed)
    return (
        completed.away_team
        if winner == completed.home_team
        else completed.home_team
    )


def regular_completed_games(
    state: SimulationLeagueState,
) -> tuple[CompletedGame, ...]:
    return tuple(
        game
        for game_id, game
        in state.completed_games.items()
        if (
            game_id.startswith("REG-")
            or not game_id.startswith(
                ("PI-", "PO-")
            )
        )
    )


def head_to_head_percentage(
    state: SimulationLeagueState,
    team: str,
    tied_teams: set[str],
) -> float:
    wins = 0
    losses = 0

    for completed in regular_completed_games(
        state
    ):
        participants = {
            completed.home_team,
            completed.away_team,
        }

        if (
            team not in participants
            or not participants.issubset(
                tied_teams
            )
        ):
            continue

        if game_winner(completed) == team:
            wins += 1
        else:
            losses += 1

    games = wins + losses
    return (
        wins / games
        if games
        else 0.0
    )


def conference_percentage(
    state: SimulationLeagueState,
    team: str,
) -> float:
    conference = conference_for_team(
        team
    )
    wins = 0
    losses = 0

    for completed in regular_completed_games(
        state
    ):
        participants = {
            completed.home_team,
            completed.away_team,
        }

        if team not in participants:
            continue

        opponent = next(
            participant
            for participant in participants
            if participant != team
        )

        if (
            conference_for_team(
                opponent
            )
            != conference
        ):
            continue

        if game_winner(completed) == team:
            wins += 1
        else:
            losses += 1

    games = wins + losses
    return (
        wins / games
        if games
        else 0.0
    )


def point_differential(
    state: SimulationLeagueState,
    team: str,
) -> int:
    standing = state.standings[team]
    return (
        standing.points_for
        - standing.points_against
    )


def conference_seed_order(
    state: SimulationLeagueState,
    conference: str,
) -> tuple[str, ...]:
    teams = [
        team
        for team in state.teams
        if conference_for_team(
            team
        )
        == conference
    ]
    groups: dict[
        tuple[int, int],
        list[str],
    ] = {}

    for team in teams:
        standing = state.standings[
            team
        ]
        groups.setdefault(
            (
                standing.wins,
                standing.losses,
            ),
            [],
        ).append(team)

    ordered: list[str] = []

    for record in sorted(
        groups,
        key=lambda item: (
            -item[0],
            item[1],
        ),
    ):
        tied = groups[record]
        tied_set = set(tied)
        ordered.extend(
            sorted(
                tied,
                key=lambda team: (
                    -head_to_head_percentage(
                        state,
                        team,
                        tied_set,
                    ),
                    -conference_percentage(
                        state,
                        team,
                    ),
                    -point_differential(
                        state,
                        team,
                    ),
                    team,
                ),
            )
        )

    if len(ordered) != 15:
        raise SimulationPostseasonError(
            f"{conference} seed order has "
            f"{len(ordered)} teams, expected 15."
        )

    return tuple(ordered)


def overall_home_court_key(
    state: SimulationLeagueState,
    team: str,
) -> tuple[Any, ...]:
    standing = state.standings[team]
    return (
        -standing.wins,
        standing.losses,
        -point_differential(
            state,
            team,
        ),
        team,
    )


def create_postseason_game(
    postseason: SimulationPostseasonState,
    *,
    stage: PostseasonStage,
    conference: str,
    round_label: str,
    series_id: str,
    game_number: int,
    home_team: str,
    away_team: str,
    home_seed: int | None,
    away_seed: int | None,
    day_index: int | None = None,
) -> PostseasonGame:
    postseason.game_sequence += 1
    prefix = (
        "PI"
        if stage
        in {
            PostseasonStage.PLAY_IN_OPENING,
            PostseasonStage.PLAY_IN_FINAL,
        }
        else "PO"
    )
    game_id = (
        f"{prefix}-"
        f"{postseason.season_label.replace('-', '')}-"
        f"{postseason.game_sequence:03d}"
    )

    if game_id in postseason.games:
        raise SimulationPostseasonError(
            f"Duplicate postseason game ID: {game_id}."
        )

    resolved_day = (
        int(day_index)
        if day_index is not None
        else int(
            postseason.next_day_index
        )
    )
    postseason.next_day_index = max(
        postseason.next_day_index,
        resolved_day + 1,
    )
    game = PostseasonGame(
        game_id=game_id,
        day_index=resolved_day,
        stage=stage,
        conference=conference,
        round_label=round_label,
        series_id=series_id,
        game_number=game_number,
        home_team=clean_team(
            home_team
        ),
        away_team=clean_team(
            away_team
        ),
        home_seed=home_seed,
        away_seed=away_seed,
    )
    postseason.games[game_id] = game
    return game


def create_opening_play_in_games(
    postseason: SimulationPostseasonState,
) -> None:
    base_day = postseason.next_day_index

    for offset, conference in enumerate(
        ("East", "West")
    ):
        seeds = postseason.seed_order[
            conference
        ]
        create_postseason_game(
            postseason,
            stage=(
                PostseasonStage
                .PLAY_IN_OPENING
            ),
            conference=conference,
            round_label="Play-In 7 vs 8",
            series_id="",
            game_number=1,
            home_team=seeds[6],
            away_team=seeds[7],
            home_seed=7,
            away_seed=8,
            day_index=base_day + offset,
        )
        create_postseason_game(
            postseason,
            stage=(
                PostseasonStage
                .PLAY_IN_OPENING
            ),
            conference=conference,
            round_label="Play-In 9 vs 10",
            series_id="",
            game_number=1,
            home_team=seeds[8],
            away_team=seeds[9],
            home_seed=9,
            away_seed=10,
            day_index=base_day + offset,
        )

    postseason.next_day_index = (
        base_day + 3
    )


def initialize_postseason(
    state: SimulationLeagueState,
) -> SimulationPostseasonState:
    validate_simulation_league_state(
        state
    )

    if not regular_season_is_complete(
        state
    ):
        raise SimulationPostseasonError(
            "The regular season must be complete "
            "before creating the postseason."
        )

    existing = get_postseason_state(
        state,
        required=False,
    )
    if existing is not None:
        return existing

    seed_order = {
        conference: (
            conference_seed_order(
                state,
                conference,
            )
        )
        for conference in (
            "East",
            "West",
        )
    }
    seed_by_team = {
        team: seed
        for conference, teams
        in seed_order.items()
        for seed, team
        in enumerate(
            teams,
            start=1,
        )
    }
    created_day = max(
        int(state.current_day_index),
        max(
            (
                int(game.day_index)
                for game
                in state.schedule.values()
            ),
            default=0,
        ),
    )
    postseason = SimulationPostseasonState(
        version=POSTSEASON_VERSION,
        season_label=(
            state.settings.season_label
        ),
        initialized=True,
        stage=(
            PostseasonStage
            .PLAY_IN_OPENING
            if state.settings.play_in_enabled
            else PostseasonStage.FIRST_ROUND
        ),
        seed_order=seed_order,
        seed_by_team=seed_by_team,
        games={},
        completed_games={},
        series={},
        postseason_player_totals={
            player_id: PlayerSeasonTotals(
                player_id=player_id
            )
            for player_id
            in state.players
        },
        conference_champions={},
        champion="",
        runner_up="",
        created_day_index=created_day,
        next_day_index=created_day + 4,
        game_sequence=0,
    )
    state.postseason_state = postseason

    if state.settings.play_in_enabled:
        create_opening_play_in_games(
            postseason
        )
        state.phase = LeaguePhase.PLAY_IN
    else:
        create_first_round(
            state,
            postseason,
            direct_seeds=True,
        )
        state.phase = LeaguePhase.PLAYOFFS

    validate_postseason_state(
        state
    )
    return postseason


def scheduled_postseason_games(
    postseason: SimulationPostseasonState,
) -> tuple[PostseasonGame, ...]:
    return tuple(
        sorted(
            (
                game
                for game
                in postseason.games.values()
                if game.status
                == (
                    PostseasonGameStatus
                    .SCHEDULED
                )
            ),
            key=lambda game: (
                game.day_index,
                game.game_id,
            ),
        )
    )


def next_postseason_game(
    state: SimulationLeagueState,
) -> PostseasonGame | None:
    postseason = get_postseason_state(
        state
    )
    games = scheduled_postseason_games(
        postseason
    )
    return games[0] if games else None


def controlled_postseason_games(
    state: SimulationLeagueState,
    controlled_teams: Sequence[str],
) -> tuple[PostseasonGame, ...]:
    postseason = get_postseason_state(
        state
    )
    controlled = {
        clean_team(team)
        for team in controlled_teams
        if clean_team(team)
    }

    if not controlled:
        return ()

    return tuple(
        game
        for game in scheduled_postseason_games(
            postseason
        )
        if controlled.intersection(
            {
                game.home_team,
                game.away_team,
            }
        )
    )


def completed_postseason_games(
    state: SimulationLeagueState,
    *,
    teams: Sequence[str] = (),
) -> tuple[
    tuple[PostseasonGame, CompletedGame],
    ...,
]:
    postseason = get_postseason_state(
        state
    )
    selected_teams = {
        clean_team(team)
        for team in teams
        if clean_team(team)
    }
    rows: list[
        tuple[
            PostseasonGame,
            CompletedGame,
        ]
    ] = []

    for game_id, completed in (
        postseason.completed_games.items()
    ):
        game = postseason.games.get(
            game_id
        )

        if game is None:
            continue

        if (
            selected_teams
            and not selected_teams.intersection(
                {
                    game.home_team,
                    game.away_team,
                }
            )
        ):
            continue

        rows.append(
            (
                game,
                completed,
            )
        )

    rows.sort(
        key=lambda item: (
            -int(item[0].day_index),
            -int(item[0].game_number),
            item[0].game_id,
        )
    )
    return tuple(rows)


def postseason_team_status(
    state: SimulationLeagueState,
    team: str,
) -> PostseasonTeamStatus:
    postseason = get_postseason_state(
        state
    )
    resolved_team = clean_team(team)

    if resolved_team not in state.teams:
        raise SimulationPostseasonError(
            f"Unknown team: {resolved_team}."
        )

    current_series = next(
        (
            series
            for series
            in postseason.series.values()
            if (
                not series.winner
                and resolved_team
                in {
                    series.higher_seed_team,
                    series.lower_seed_team,
                }
            )
        ),
        None,
    )
    next_game = next(
        (
            game
            for game
            in scheduled_postseason_games(
                postseason
            )
            if resolved_team
            in {
                game.home_team,
                game.away_team,
            }
        ),
        None,
    )
    seed = postseason.seed_by_team.get(
        resolved_team
    )
    qualification_cutoff = (
        10
        if state.settings.play_in_enabled
        else 8
    )
    eliminated = bool(
        seed is not None
        and seed > qualification_cutoff
    ) or any(
        series.loser == resolved_team
        for series
        in postseason.series.values()
    )

    for game in postseason.games.values():
        if (
            game.status
            != PostseasonGameStatus.COMPLETED
            or game.loser
            != resolved_team
        ):
            continue

        if game.round_label in {
            "Play-In 9 vs 10",
            "Play-In Final",
        }:
            eliminated = True

    champion = (
        postseason.champion
        == resolved_team
    )
    runner_up = (
        postseason.runner_up
        == resolved_team
    )
    alive = bool(
        champion
        or (
            not eliminated
            and (
                postseason.stage
                != PostseasonStage.COMPLETE
            )
        )
    )
    series_wins = 0
    series_losses = 0
    current_series_id = ""
    current_round = (
        next_game.round_label
        if next_game is not None
        else ""
    )

    if current_series is not None:
        current_series_id = (
            current_series.series_id
        )
        current_round = (
            current_series.round_label
        )

        if (
            resolved_team
            == current_series
            .higher_seed_team
        ):
            series_wins = (
                current_series
                .higher_seed_wins
            )
            series_losses = (
                current_series
                .lower_seed_wins
            )
        else:
            series_wins = (
                current_series
                .lower_seed_wins
            )
            series_losses = (
                current_series
                .higher_seed_wins
            )

    return PostseasonTeamStatus(
        team=resolved_team,
        seed=seed,
        stage=postseason.stage,
        alive=alive,
        eliminated=eliminated,
        champion=champion,
        runner_up=runner_up,
        current_series_id=(
            current_series_id
        ),
        current_round=current_round,
        series_wins=series_wins,
        series_losses=series_losses,
        next_game_id=(
            next_game.game_id
            if next_game is not None
            else ""
        ),
    )


def scratch_state_for_game(
    state: SimulationLeagueState,
    game: PostseasonGame,
) -> SimulationLeagueState:
    """Compatibility helper for callers that explicitly need a preview copy."""
    scratch = copy.deepcopy(state)
    scratch.schedule[game.game_id] = ScheduledGame(
        game_id=game.game_id,
        day_index=game.day_index,
        home_team=game.home_team,
        away_team=game.away_team,
        status=GameStatus.SCHEDULED,
    )
    return scratch


def _simulate_postseason_game_on_private_state(
    state: SimulationLeagueState,
    game: PostseasonGame,
    *,
    seed: int | None = None,
    sit_player_ids: Iterable[str] = (),
) -> SimulatedGame:
    """Simulate on a caller-owned private transaction without another copy."""
    existing_schedule_entry = state.schedule.get(game.game_id)
    state.schedule[game.game_id] = ScheduledGame(
        game_id=game.game_id,
        day_index=game.day_index,
        home_team=game.home_team,
        away_team=game.away_team,
        status=GameStatus.SCHEDULED,
    )
    try:
        return simulate_scheduled_game(
            state,
            game.game_id,
            seed=seed,
            commit=False,
            sit_player_ids=sit_player_ids,
            _private_working_state=True,
        )
    finally:
        if existing_schedule_entry is None:
            state.schedule.pop(game.game_id, None)
        else:
            state.schedule[game.game_id] = existing_schedule_entry


def simulate_postseason_game(
    state: SimulationLeagueState,
    game_id: str,
    *,
    seed: int | None = None,
    sit_player_ids: Iterable[str] = (),
) -> SimulatedGame:
    postseason = get_postseason_state(state)
    game = postseason.games.get(str(game_id).strip())

    if game is None:
        raise SimulationPostseasonError(
            f"Unknown postseason game: {game_id}."
        )

    if game.status != PostseasonGameStatus.SCHEDULED:
        raise SimulationPostseasonError(
            f"Postseason game {game_id} is already completed."
        )

    # Public previews remain nonmutating, but now require only one full copy.
    scratch = copy.deepcopy(state)
    scratch_game = get_postseason_state(scratch).games[game.game_id]
    return _simulate_postseason_game_on_private_state(
        scratch,
        scratch_game,
        seed=seed,
        sit_player_ids=sit_player_ids,
    )


def opening_game(
    postseason: SimulationPostseasonState,
    conference: str,
    label: str,
) -> PostseasonGame:
    matches = [
        game
        for game
        in postseason.games.values()
        if (
            game.conference
            == conference
            and game.round_label
            == label
        )
    ]

    if len(matches) != 1:
        raise SimulationPostseasonError(
            f"Expected one {conference} "
            f"{label} game, found {len(matches)}."
        )

    return matches[0]


def create_play_in_finals(
    postseason: SimulationPostseasonState,
) -> None:
    if any(
        game.stage
        == PostseasonStage.PLAY_IN_FINAL
        for game in postseason.games.values()
    ):
        return

    base_day = postseason.next_day_index

    for offset, conference in enumerate(
        ("East", "West")
    ):
        game_78 = opening_game(
            postseason,
            conference,
            "Play-In 7 vs 8",
        )
        game_910 = opening_game(
            postseason,
            conference,
            "Play-In 9 vs 10",
        )

        if (
            game_78.status
            != PostseasonGameStatus.COMPLETED
            or game_910.status
            != PostseasonGameStatus.COMPLETED
        ):
            raise SimulationPostseasonError(
                "Opening play-in games are incomplete."
            )

        create_postseason_game(
            postseason,
            stage=(
                PostseasonStage
                .PLAY_IN_FINAL
            ),
            conference=conference,
            round_label="Play-In Final",
            series_id="",
            game_number=1,
            home_team=game_78.loser,
            away_team=game_910.winner,
            home_seed=(
                postseason.seed_by_team[
                    game_78.loser
                ]
            ),
            away_seed=(
                postseason.seed_by_team[
                    game_910.winner
                ]
            ),
            day_index=base_day + offset,
        )

    postseason.next_day_index = (
        base_day + 3
    )
    postseason.stage = (
        PostseasonStage.PLAY_IN_FINAL
    )


def series_home_team(
    series: PostseasonSeries,
    game_number: int,
) -> str:
    try:
        venue = HOME_COURT_PATTERN[
            game_number - 1
        ]
    except IndexError as exc:
        raise SimulationPostseasonError(
            "Best-of-seven series cannot "
            f"schedule Game {game_number}."
        ) from exc

    return (
        series.higher_seed_team
        if venue == "higher"
        else series.lower_seed_team
    )


def schedule_series_game(
    postseason: SimulationPostseasonState,
    series: PostseasonSeries,
    *,
    game_number: int,
    day_index: int | None = None,
) -> PostseasonGame:
    home_team = series_home_team(
        series,
        game_number,
    )
    away_team = (
        series.lower_seed_team
        if home_team
        == series.higher_seed_team
        else series.higher_seed_team
    )
    home_seed = (
        series.higher_seed_rank
        if home_team
        == series.higher_seed_team
        else series.lower_seed_rank
    )
    away_seed = (
        series.lower_seed_rank
        if away_team
        == series.lower_seed_team
        else series.higher_seed_rank
    )
    game = create_postseason_game(
        postseason,
        stage=series.stage,
        conference=series.conference,
        round_label=series.round_label,
        series_id=series.series_id,
        game_number=game_number,
        home_team=home_team,
        away_team=away_team,
        home_seed=home_seed,
        away_seed=away_seed,
        day_index=day_index,
    )
    series.game_ids.append(
        game.game_id
    )
    return game


def create_series(
    postseason: SimulationPostseasonState,
    *,
    series_id: str,
    stage: PostseasonStage,
    conference: str,
    round_label: str,
    team_a: str,
    team_b: str,
    seed_a: int,
    seed_b: int,
    day_index: int | None = None,
) -> PostseasonSeries:
    if series_id in postseason.series:
        raise SimulationPostseasonError(
            f"Duplicate series ID: {series_id}."
        )

    if seed_a <= seed_b:
        higher_team = team_a
        higher_seed = seed_a
        lower_team = team_b
        lower_seed = seed_b
    else:
        higher_team = team_b
        higher_seed = seed_b
        lower_team = team_a
        lower_seed = seed_a

    series = PostseasonSeries(
        series_id=series_id,
        stage=stage,
        conference=conference,
        round_label=round_label,
        higher_seed_team=higher_team,
        lower_seed_team=lower_team,
        higher_seed_rank=higher_seed,
        lower_seed_rank=lower_seed,
    )
    postseason.series[
        series_id
    ] = series
    schedule_series_game(
        postseason,
        series,
        game_number=1,
        day_index=day_index,
    )
    return series


def play_in_seed_winners(
    postseason: SimulationPostseasonState,
    conference: str,
) -> tuple[str, str]:
    game_78 = opening_game(
        postseason,
        conference,
        "Play-In 7 vs 8",
    )
    final = opening_game(
        postseason,
        conference,
        "Play-In Final",
    )

    if (
        game_78.status
        != PostseasonGameStatus.COMPLETED
        or final.status
        != PostseasonGameStatus.COMPLETED
    ):
        raise SimulationPostseasonError(
            f"{conference} play-in is incomplete."
        )

    return game_78.winner, final.winner


def create_first_round(
    state: SimulationLeagueState,
    postseason: SimulationPostseasonState,
    *,
    direct_seeds: bool = False,
) -> None:
    if any(
        series.stage
        == PostseasonStage.FIRST_ROUND
        for series in postseason.series.values()
    ):
        return

    base_day = postseason.next_day_index

    for conference_index, conference in enumerate(
        ("East", "West")
    ):
        seeds = list(
            postseason.seed_order[
                conference
            ][:8]
        )

        if (
            state.settings.play_in_enabled
            and not direct_seeds
        ):
            seed_7, seed_8 = (
                play_in_seed_winners(
                    postseason,
                    conference,
                )
            )
            seeds[6] = seed_7
            seeds[7] = seed_8
            postseason.seed_by_team[
                seed_7
            ] = 7
            postseason.seed_by_team[
                seed_8
            ] = 8

        pairings = (
            ("A", 1, 8),
            ("B", 4, 5),
            ("C", 2, 7),
            ("D", 3, 6),
        )

        for pairing_index, (
            slot,
            high_seed,
            low_seed,
        ) in enumerate(pairings):
            create_series(
                postseason,
                series_id=(
                    f"{conference[0]}-R1-"
                    f"{slot}"
                ),
                stage=(
                    PostseasonStage
                    .FIRST_ROUND
                ),
                conference=conference,
                round_label=(
                    f"{conference} First Round"
                ),
                team_a=seeds[
                    high_seed - 1
                ],
                team_b=seeds[
                    low_seed - 1
                ],
                seed_a=high_seed,
                seed_b=low_seed,
                day_index=(
                    base_day
                    + conference_index
                    + pairing_index
                    * 2
                ),
            )

    postseason.next_day_index = (
        base_day + 9
    )
    postseason.bracket_created = True
    postseason.stage = (
        PostseasonStage.FIRST_ROUND
    )
    state.phase = LeaguePhase.PLAYOFFS


def stage_series(
    postseason: SimulationPostseasonState,
    stage: PostseasonStage,
    *,
    conference: str | None = None,
) -> tuple[PostseasonSeries, ...]:
    return tuple(
        sorted(
            (
                series
                for series
                in postseason.series.values()
                if (
                    series.stage == stage
                    and (
                        conference is None
                        or series.conference
                        == conference
                    )
                )
            ),
            key=lambda series: (
                series.conference,
                series.series_id,
            ),
        )
    )


def completed_series_winner(
    postseason: SimulationPostseasonState,
    series_id: str,
) -> str:
    series = postseason.series[
        series_id
    ]

    if not series.winner:
        raise SimulationPostseasonError(
            f"Series {series_id} is incomplete."
        )

    return series.winner


def create_conference_semifinals(
    postseason: SimulationPostseasonState,
) -> None:
    if stage_series(
        postseason,
        PostseasonStage.CONFERENCE_SEMIFINALS,
    ):
        return

    base_day = postseason.next_day_index

    for offset, conference in enumerate(
        ("East", "West")
    ):
        prefix = conference[0]
        create_series(
            postseason,
            series_id=f"{prefix}-SF-A",
            stage=(
                PostseasonStage
                .CONFERENCE_SEMIFINALS
            ),
            conference=conference,
            round_label=(
                f"{conference} Semifinals"
            ),
            team_a=completed_series_winner(
                postseason,
                f"{prefix}-R1-A",
            ),
            team_b=completed_series_winner(
                postseason,
                f"{prefix}-R1-B",
            ),
            seed_a=postseason.seed_by_team[
                completed_series_winner(
                    postseason,
                    f"{prefix}-R1-A",
                )
            ],
            seed_b=postseason.seed_by_team[
                completed_series_winner(
                    postseason,
                    f"{prefix}-R1-B",
                )
            ],
            day_index=base_day + offset,
        )
        create_series(
            postseason,
            series_id=f"{prefix}-SF-B",
            stage=(
                PostseasonStage
                .CONFERENCE_SEMIFINALS
            ),
            conference=conference,
            round_label=(
                f"{conference} Semifinals"
            ),
            team_a=completed_series_winner(
                postseason,
                f"{prefix}-R1-C",
            ),
            team_b=completed_series_winner(
                postseason,
                f"{prefix}-R1-D",
            ),
            seed_a=postseason.seed_by_team[
                completed_series_winner(
                    postseason,
                    f"{prefix}-R1-C",
                )
            ],
            seed_b=postseason.seed_by_team[
                completed_series_winner(
                    postseason,
                    f"{prefix}-R1-D",
                )
            ],
            day_index=base_day + offset + 2,
        )

    postseason.next_day_index = (
        base_day + 5
    )
    postseason.stage = (
        PostseasonStage
        .CONFERENCE_SEMIFINALS
    )


def create_conference_finals(
    postseason: SimulationPostseasonState,
) -> None:
    if stage_series(
        postseason,
        PostseasonStage.CONFERENCE_FINALS,
    ):
        return

    base_day = postseason.next_day_index

    for offset, conference in enumerate(
        ("East", "West")
    ):
        prefix = conference[0]
        team_a = completed_series_winner(
            postseason,
            f"{prefix}-SF-A",
        )
        team_b = completed_series_winner(
            postseason,
            f"{prefix}-SF-B",
        )
        create_series(
            postseason,
            series_id=f"{prefix}-CF",
            stage=(
                PostseasonStage
                .CONFERENCE_FINALS
            ),
            conference=conference,
            round_label=(
                f"{conference} Finals"
            ),
            team_a=team_a,
            team_b=team_b,
            seed_a=postseason.seed_by_team[
                team_a
            ],
            seed_b=postseason.seed_by_team[
                team_b
            ],
            day_index=base_day + offset,
        )

    postseason.next_day_index = (
        base_day + 3
    )
    postseason.stage = (
        PostseasonStage
        .CONFERENCE_FINALS
    )


def create_nba_finals(
    state: SimulationLeagueState,
    postseason: SimulationPostseasonState,
) -> None:
    if stage_series(
        postseason,
        PostseasonStage.NBA_FINALS,
    ):
        return

    east = completed_series_winner(
        postseason,
        "E-CF",
    )
    west = completed_series_winner(
        postseason,
        "W-CF",
    )
    postseason.conference_champions = {
        "East": east,
        "West": west,
    }

    if (
        overall_home_court_key(
            state,
            east,
        )
        <= overall_home_court_key(
            state,
            west,
        )
    ):
        higher = east
        lower = west
    else:
        higher = west
        lower = east

    create_series(
        postseason,
        series_id="NBA-FINALS",
        stage=PostseasonStage.NBA_FINALS,
        conference="NBA",
        round_label="NBA Finals",
        team_a=higher,
        team_b=lower,
        seed_a=1,
        seed_b=2,
        day_index=(
            postseason.next_day_index
        ),
    )
    postseason.next_day_index += 2
    postseason.stage = (
        PostseasonStage.NBA_FINALS
    )


def all_series_complete(
    postseason: SimulationPostseasonState,
    stage: PostseasonStage,
) -> bool:
    series = stage_series(
        postseason,
        stage,
    )
    return bool(
        series
        and all(
            item.winner
            for item in series
        )
    )


def advance_bracket_structure(
    state: SimulationLeagueState,
) -> None:
    postseason = get_postseason_state(
        state
    )

    if scheduled_postseason_games(
        postseason
    ):
        return

    if (
        postseason.stage
        == PostseasonStage.PLAY_IN_OPENING
    ):
        create_play_in_finals(
            postseason
        )
        return

    if (
        postseason.stage
        == PostseasonStage.PLAY_IN_FINAL
    ):
        create_first_round(
            state,
            postseason,
        )
        return

    if (
        postseason.stage
        == PostseasonStage.FIRST_ROUND
        and all_series_complete(
            postseason,
            PostseasonStage.FIRST_ROUND,
        )
    ):
        create_conference_semifinals(
            postseason
        )
        return

    if (
        postseason.stage
        == (
            PostseasonStage
            .CONFERENCE_SEMIFINALS
        )
        and all_series_complete(
            postseason,
            (
                PostseasonStage
                .CONFERENCE_SEMIFINALS
            ),
        )
    ):
        create_conference_finals(
            postseason
        )
        return

    if (
        postseason.stage
        == PostseasonStage.CONFERENCE_FINALS
        and all_series_complete(
            postseason,
            PostseasonStage.CONFERENCE_FINALS,
        )
    ):
        create_nba_finals(
            state,
            postseason,
        )
        return

    if (
        postseason.stage
        == PostseasonStage.NBA_FINALS
        and all_series_complete(
            postseason,
            PostseasonStage.NBA_FINALS,
        )
    ):
        finals = postseason.series[
            "NBA-FINALS"
        ]
        postseason.champion = (
            finals.winner
        )
        postseason.runner_up = (
            finals.loser
        )
        postseason.stage = (
            PostseasonStage.COMPLETE
        )
        state.phase = LeaguePhase.OFFSEASON


def _regular_season_sections_match(
    source: SimulationLeagueState,
    updated: SimulationLeagueState,
) -> bool:
    return bool(
        source.standings == updated.standings
        and source.player_season_totals == updated.player_season_totals
        and source.schedule == updated.schedule
        and source.completed_games == updated.completed_games
    )


def _commit_postseason_game_in_place(
    state: SimulationLeagueState,
    game_id: str,
    *,
    seed: int | None = None,
    sit_player_ids: Iterable[str] = (),
    validate_full_state: bool = False,
) -> SimulatedGame:
    """Commit one playoff game inside an already-private transaction."""
    postseason = get_postseason_state(state)
    game = postseason.games.get(str(game_id).strip())

    if game is None:
        raise SimulationPostseasonError(
            f"Unknown postseason game: {game_id}."
        )
    if game.status != PostseasonGameStatus.SCHEDULED:
        raise SimulationPostseasonError(
            f"Postseason game {game_id} is already completed."
        )

    simulated = _simulate_postseason_game_on_private_state(
        state,
        game,
        seed=seed,
        sit_player_ids=sit_player_ids,
    )
    completed = simulated.game
    game.status = PostseasonGameStatus.COMPLETED
    game.winner = game_winner(completed)
    game.loser = game_loser(completed)
    game.home_score = completed.home_score
    game.away_score = completed.away_score
    game.overtime_periods = completed.overtime_periods
    postseason.completed_games[game.game_id] = completed

    for line in completed.player_box_scores:
        add_player_totals(
            postseason.postseason_player_totals[line.player_id],
            line,
        )

    if game.series_id:
        series = postseason.series[game.series_id]
        if game.winner == series.higher_seed_team:
            series.higher_seed_wins += 1
        elif game.winner == series.lower_seed_team:
            series.lower_seed_wins += 1
        else:
            raise SimulationPostseasonError(
                "Series winner is not a participating team."
            )

        if series.higher_seed_wins >= 4 or series.lower_seed_wins >= 4:
            series.winner = (
                series.higher_seed_team
                if series.higher_seed_wins > series.lower_seed_wins
                else series.lower_seed_team
            )
            series.loser = (
                series.lower_seed_team
                if series.winner == series.higher_seed_team
                else series.higher_seed_team
            )
        else:
            schedule_series_game(
                postseason,
                series,
                game_number=game.game_number + 1,
                day_index=game.day_index + 2,
            )

    state.current_day_index = max(
        int(state.current_day_index),
        int(game.day_index),
    )
    advance_bracket_structure(state)
    validate_postseason_state(state)
    if validate_full_state:
        validate_simulation_league_state(state)
    return simulated


def commit_postseason_game(
    state: SimulationLeagueState,
    game_id: str,
    *,
    seed: int | None = None,
    sit_player_ids: Iterable[str] = (),
) -> tuple[SimulationLeagueState, SimulatedGame]:
    # A user-controlled single game remains fully transactional. Only one
    # complete state copy is needed, rather than source + updated + scratch.
    updated = copy.deepcopy(state)
    simulated = _commit_postseason_game_in_place(
        updated,
        game_id,
        seed=seed,
        sit_player_ids=sit_player_ids,
        validate_full_state=True,
    )
    if not _regular_season_sections_match(state, updated):
        raise SimulationPostseasonError(
            "Postseason commit changed regular-season standings, "
            "schedule, or statistics."
        )
    return updated, simulated


def postseason_game_requires_pause(
    state: SimulationLeagueState,
    game: PostseasonGame,
    controlled_teams: Sequence[str],
    policy: FranchiseSimulationPolicy,
) -> bool:
    controlled = {
        clean_team(team)
        for team in controlled_teams
        if clean_team(team)
    }
    participates = bool(
        controlled.intersection(
            {
                game.home_team,
                game.away_team,
            }
        )
    )

    if not participates:
        return False

    if (
        policy
        == (
            FranchiseSimulationPolicy
            .STOP_EVERY_CONTROLLED_GAME
        )
    ):
        return True

    if (
        policy
        == (
            FranchiseSimulationPolicy
            .STOP_FOR_DECISIONS
        )
    ):
        scheduled = ScheduledGame(
            game_id=game.game_id,
            day_index=game.day_index,
            home_team=game.home_team,
            away_team=game.away_team,
            status=GameStatus.SCHEDULED,
        )
        return game_requires_decision(
            state,
            scheduled,
            tuple(controlled),
        )

    return False


def advance_postseason(
    state: SimulationLeagueState,
    *,
    scope: PostseasonSimulationScope | str,
    controlled_teams: Sequence[str] = (),
    policy: FranchiseSimulationPolicy | str = (
        FranchiseSimulationPolicy
        .FREE_SIMULATION
    ),
    seed: int | None = None,
    max_games: int = 140,
    progress_callback: Callable[
        [
            SimulationLeagueState,
            int,
            PostseasonGame,
        ],
        None,
    ] | None = None,
) -> tuple[
    SimulationLeagueState,
    PostseasonAdvanceResult,
]:
    resolved_scope = (
        scope
        if isinstance(
            scope,
            PostseasonSimulationScope,
        )
        else PostseasonSimulationScope(
            str(scope)
        )
    )
    resolved_policy = (
        policy
        if isinstance(
            policy,
            FranchiseSimulationPolicy,
        )
        else FranchiseSimulationPolicy(
            str(policy)
        )
    )
    game_limit = max(
        1,
        int(max_games),
    )
    controlled = {
        clean_team(team)
        for team in controlled_teams
        if clean_team(team)
    }
    updated = copy.deepcopy(state)
    postseason = get_postseason_state(
        updated
    )
    stage_before = postseason.stage
    simulated_ids: list[str] = []
    paused_before = ""
    stopped_at_limit = False

    while True:
        if (
            len(simulated_ids)
            >= game_limit
        ):
            stopped_at_limit = True
            break

        next_game = next_postseason_game(
            updated
        )

        if next_game is None:
            structure_before = (
                postseason.stage,
                len(
                    postseason
                    .completed_games
                ),
                len(postseason.series),
            )
            advance_bracket_structure(
                updated
            )
            postseason = (
                get_postseason_state(
                    updated
                )
            )
            next_game = next_postseason_game(
                updated
            )

            if next_game is None:
                if (
                    postseason.stage
                    == PostseasonStage.COMPLETE
                ):
                    break

                structure_after = (
                    postseason.stage,
                    len(
                        postseason
                        .completed_games
                    ),
                    len(postseason.series),
                )
                raise SimulationPostseasonError(
                    "The postseason bracket stalled "
                    "without a scheduled next game. "
                    f"Before: {structure_before}; "
                    f"after: {structure_after}."
                )

        if (
            simulated_ids
            and resolved_scope
            == (
                PostseasonSimulationScope
                .NEXT_GAME
            )
        ):
            break

        if (
            simulated_ids
            and resolved_scope
            == (
                PostseasonSimulationScope
                .CURRENT_STAGE
            )
            and next_game.stage
            != stage_before
        ):
            break

        next_is_controlled = bool(
            controlled.intersection(
                {
                    next_game.home_team,
                    next_game.away_team,
                }
            )
        )

        if (
            resolved_scope
            == (
                PostseasonSimulationScope
                .NEXT_CONTROLLED_GAME
            )
            and next_is_controlled
        ):
            paused_before = (
                next_game.game_id
            )
            break

        if postseason_game_requires_pause(
            updated,
            next_game,
            controlled_teams,
            resolved_policy,
        ):
            paused_before = (
                next_game.game_id
            )
            break

        game_seed = (
            None
            if seed is None
            else int(seed)
            + len(simulated_ids)
        )
        completed_before = len(
            postseason.completed_games
        )
        committed_game_id = (
            next_game.game_id
        )
        stage_before_game = postseason.stage
        _commit_postseason_game_in_place(
            updated,
            committed_game_id,
            seed=game_seed,
            validate_full_state=False,
        )
        postseason = get_postseason_state(updated)
        if postseason.stage != stage_before_game:
            # Full validation at round boundaries catches structural errors
            # without rescanning the complete 1,230-game season after every
            # playoff game.
            validate_simulation_league_state(updated)
        completed_after = len(
            postseason.completed_games
        )

        if (
            completed_after
            != completed_before + 1
        ):
            raise SimulationPostseasonError(
                "Postseason advancement did not "
                "commit exactly one game."
            )

        simulated_ids.append(
            committed_game_id
        )

        if progress_callback is not None:
            committed_game = (
                postseason.games[
                    committed_game_id
                ]
            )

            try:
                progress_callback(
                    updated,
                    len(simulated_ids),
                    committed_game,
                )
            except Exception as exc:
                raise SimulationPostseasonError(
                    "Postseason progress checkpoint "
                    "failed after "
                    f"{len(simulated_ids)} game(s)."
                ) from exc

        if (
            postseason.stage
            == PostseasonStage.COMPLETE
        ):
            break

    validate_simulation_league_state(updated)
    if not _regular_season_sections_match(state, updated):
        raise SimulationPostseasonError(
            "Bulk postseason advancement changed regular-season standings, "
            "schedule, or statistics."
        )
    final_postseason = get_postseason_state(updated)
    result = PostseasonAdvanceResult(
        version=POSTSEASON_VERSION,
        scope=resolved_scope,
        games_simulated=len(
            simulated_ids
        ),
        game_ids=tuple(
            simulated_ids
        ),
        paused_before_game_id=(
            paused_before
        ),
        stage_before=stage_before,
        stage_after=(
            final_postseason.stage
        ),
        champion=(
            final_postseason.champion
        ),
        stopped_at_game_limit=(
            stopped_at_limit
        ),
    )
    return updated, result


def postseason_series_rows(
    state: SimulationLeagueState,
) -> list[dict[str, Any]]:
    postseason = get_postseason_state(
        state
    )
    rows = []

    for series in sorted(
        postseason.series.values(),
        key=lambda item: (
            list(
                PostseasonStage
            ).index(
                item.stage
            ),
            item.conference,
            item.series_id,
        ),
    ):
        rows.append(
            {
                "Stage": (
                    series.round_label
                ),
                "Series": (
                    series.series_id
                ),
                "Higher Seed": (
                    f"{series.higher_seed_rank}. "
                    f"{series.higher_seed_team}"
                ),
                "Lower Seed": (
                    f"{series.lower_seed_rank}. "
                    f"{series.lower_seed_team}"
                ),
                "Score": (
                    f"{series.higher_seed_wins}-"
                    f"{series.lower_seed_wins}"
                ),
                "Winner": (
                    series.winner
                ),
                "Games": len(
                    series.game_ids
                ),
            }
        )

    return rows


def postseason_seed_rows(
    state: SimulationLeagueState,
    conference: str,
) -> list[dict[str, Any]]:
    postseason = get_postseason_state(
        state
    )
    return [
        {
            "Seed": seed,
            "Team": team,
            "Record": (
                f"{state.standings[team].wins}-"
                f"{state.standings[team].losses}"
            ),
            "Point Differential": (
                point_differential(
                    state,
                    team,
                )
            ),
        }
        for seed, team
        in enumerate(
            postseason.seed_order[
                conference
            ],
            start=1,
        )
    ]


PLAYOFF_STAT_STAGES = {
    PostseasonStage.FIRST_ROUND,
    PostseasonStage.CONFERENCE_SEMIFINALS,
    PostseasonStage.CONFERENCE_FINALS,
    PostseasonStage.NBA_FINALS,
}


def scoped_postseason_player_totals(
    state: SimulationLeagueState,
    *,
    include_play_in: bool = True,
) -> dict[str, PlayerSeasonTotals]:
    postseason = get_postseason_state(
        state
    )

    if include_play_in:
        return postseason.postseason_player_totals

    totals_by_player: dict[
        str,
        PlayerSeasonTotals,
    ] = {}

    for game_id, completed in (
        postseason.completed_games.items()
    ):
        game = postseason.games.get(
            game_id
        )
        if (
            game is None
            or game.stage
            not in PLAYOFF_STAT_STAGES
        ):
            continue

        for line in completed.player_box_scores:
            totals = totals_by_player.setdefault(
                line.player_id,
                PlayerSeasonTotals(
                    player_id=line.player_id,
                ),
            )
            add_player_totals(
                totals,
                line,
            )

    return totals_by_player


def shooting_percentage(
    made: int,
    attempted: int,
) -> float:
    if attempted <= 0:
        return 0.0
    return round(
        100.0 * made / attempted,
        1,
    )


def postseason_player_rows(
    state: SimulationLeagueState,
    *,
    minimum_games: int = 1,
    limit: int = 50,
    include_play_in: bool = True,
) -> list[dict[str, Any]]:
    totals_by_player = (
        scoped_postseason_player_totals(
            state,
            include_play_in=include_play_in,
        )
    )
    rows: list[dict[str, Any]] = []

    for player_id, totals in (
        totals_by_player.items()
    ):
        if totals.games_played < minimum_games:
            continue

        player = state.players[player_id]
        games = totals.games_played
        rows.append(
            {
                "Player": player.player_name,
                "Team": player.team_abbreviation,
                "Pos": player.position,
                "GP": games,
                "MIN": round(
                    totals.minutes / games,
                    1,
                ),
                "PTS": round(
                    totals.points / games,
                    1,
                ),
                "REB": round(
                    totals.rebounds / games,
                    1,
                ),
                "AST": round(
                    totals.assists / games,
                    1,
                ),
                "STL": round(
                    totals.steals / games,
                    1,
                ),
                "BLK": round(
                    totals.blocks / games,
                    1,
                ),
                "TO": round(
                    totals.turnovers / games,
                    1,
                ),
                "PF": round(
                    totals.fouls / games,
                    1,
                ),
                "FG%": shooting_percentage(
                    totals.field_goals_made,
                    totals.field_goals_attempted,
                ),
                "3P%": shooting_percentage(
                    totals.three_pointers_made,
                    totals.three_pointers_attempted,
                ),
                "FT%": shooting_percentage(
                    totals.free_throws_made,
                    totals.free_throws_attempted,
                ),
            }
        )

    rows.sort(
        key=lambda row: (
            -row["PTS"],
            -row["AST"],
            row["Player"],
        )
    )
    return rows[: int(limit)]


def postseason_team_rows(
    state: SimulationLeagueState,
    *,
    include_play_in: bool = False,
    limit: int = 30,
) -> list[dict[str, Any]]:
    postseason = get_postseason_state(
        state
    )
    stage_order = {
        stage: index
        for index, stage in enumerate(
            PostseasonStage
        )
    }
    records: dict[str, dict[str, Any]] = {}

    def row_for(team: str) -> dict[str, Any]:
        return records.setdefault(
            team,
            {
                "team": team,
                "games": 0,
                "wins": 0,
                "losses": 0,
                "points_for": 0,
                "points_against": 0,
                "furthest_stage": (
                    PostseasonStage.NOT_STARTED
                ),
                "furthest_round": "",
            },
        )

    for game_id, completed in (
        postseason.completed_games.items()
    ):
        game = postseason.games.get(
            game_id
        )
        if game is None:
            continue
        if (
            not include_play_in
            and game.stage
            not in PLAYOFF_STAT_STAGES
        ):
            continue

        for team, points_for, points_against in (
            (
                completed.home_team,
                completed.home_score,
                completed.away_score,
            ),
            (
                completed.away_team,
                completed.away_score,
                completed.home_score,
            ),
        ):
            record = row_for(team)
            record["games"] += 1
            record["points_for"] += points_for
            record["points_against"] += (
                points_against
            )
            if points_for > points_against:
                record["wins"] += 1
            else:
                record["losses"] += 1

            if (
                stage_order[game.stage]
                >= stage_order[
                    record["furthest_stage"]
                ]
            ):
                record["furthest_stage"] = (
                    game.stage
                )
                record["furthest_round"] = (
                    game.round_label
                )

    rows: list[dict[str, Any]] = []
    for team, record in records.items():
        games = int(record["games"])
        wins = int(record["wins"])
        losses = int(record["losses"])
        points_for = int(record["points_for"])
        points_against = int(
            record["points_against"]
        )
        rows.append(
            {
                "Seed": postseason.seed_by_team.get(
                    team
                ),
                "Team": team,
                "Conf": conference_for_team(team),
                "GP": games,
                "W": wins,
                "L": losses,
                "Win%": round(
                    wins / games,
                    3,
                ),
                "PF": round(
                    points_for / games,
                    1,
                ),
                "PA": round(
                    points_against / games,
                    1,
                ),
                "Diff": round(
                    (
                        points_for
                        - points_against
                    ) / games,
                    1,
                ),
                "Furthest Round": (
                    "NBA Champion"
                    if team == postseason.champion
                    else record["furthest_round"]
                ),
            }
        )

    rows.sort(
        key=lambda row: (
            -row["W"],
            -row["Diff"],
            row["Seed"]
            if row["Seed"] is not None
            else 99,
            row["Team"],
        )
    )
    return rows[: int(limit)]


def validate_postseason_state(
    state: SimulationLeagueState,
) -> dict[str, bool]:
    postseason = get_postseason_state(
        state
    )
    checks = {
        "postseason_version_matches": (
            postseason.version
            == POSTSEASON_VERSION
        ),
        "season_label_matches": (
            postseason.season_label
            == state.settings.season_label
        ),
        "both_conferences_have_15_seeds": (
            set(
                postseason.seed_order
            )
            == {"East", "West"}
            and all(
                len(teams) == 15
                for teams
                in postseason
                .seed_order.values()
            )
        ),
        "all_30_teams_have_seed_metadata": (
            len(
                postseason.seed_by_team
            )
            == 30
        ),
        "game_teams_are_valid": all(
            game.home_team in state.teams
            and game.away_team in state.teams
            and game.home_team
            != game.away_team
            for game
            in postseason.games.values()
        ),
        "completed_games_match_game_status": all(
            (
                game.game_id
                in postseason.completed_games
            )
            == (
                game.status
                == (
                    PostseasonGameStatus
                    .COMPLETED
                )
            )
            for game
            in postseason.games.values()
        ),
        "series_wins_are_valid": all(
            0
            <= series.higher_seed_wins
            <= 4
            and 0
            <= series.lower_seed_wins
            <= 4
            and len(
                series.game_ids
            )
            <= 7
            for series
            in postseason.series.values()
        ),
        "series_game_ids_are_valid": all(
            game_id in postseason.games
            and postseason.games[
                game_id
            ].series_id
            == series.series_id
            for series
            in postseason.series.values()
            for game_id
            in series.game_ids
        ),
        "postseason_totals_cover_all_players": (
            set(
                postseason
                .postseason_player_totals
            )
            == set(state.players)
        ),
        "champion_only_when_complete": (
            bool(postseason.champion)
            == (
                postseason.stage
                == PostseasonStage.COMPLETE
            )
        ),
        "regular_season_standings_remain_82_games": (
            all(
                standing.games_played
                == (
                    state.settings
                    .regular_season_games_per_team
                )
                for standing
                in state.standings.values()
            )
        ),
    }
    failed = [
        name
        for name, passed
        in checks.items()
        if not passed
    ]

    if failed:
        raise SimulationPostseasonError(
            "Postseason validation failed: "
            + ", ".join(failed)
        )

    return checks


def run_self_test(
    *,
    seed: int = 20260808,
) -> dict[str, Any]:
    from regular_season_simulation_controller_v1 import (
        SimulationScope,
        build_installed_state,
        simulate_regular_season_scope,
    )

    state = build_installed_state(
        seed=seed
    )
    state, regular = (
        simulate_regular_season_scope(
            state,
            scope=SimulationScope.REMAINDER,
        )
    )
    regular_standings = copy.deepcopy(
        state.standings
    )
    regular_totals = copy.deepcopy(
        state.player_season_totals
    )
    regular_schedule = copy.deepcopy(
        state.schedule
    )
    initialize_postseason(
        state
    )

    opening_games = tuple(
        game.game_id
        for game
        in scheduled_postseason_games(
            get_postseason_state(
                state
            )
        )
    )
    east_seven = (
        get_postseason_state(
            state
        ).seed_order["East"][6]
    )
    controlled_opening = (
        controlled_postseason_games(
            state,
            (east_seven,),
        )
    )
    controlled_status = (
        postseason_team_status(
            state,
            east_seven,
        )
    )
    missed_team = (
        get_postseason_state(
            state
        ).seed_order["East"][10]
    )
    missed_status = (
        postseason_team_status(
            state,
            missed_team,
        )
    )
    stopped_state, stopped_result = (
        advance_postseason(
            state,
            scope=(
                PostseasonSimulationScope
                .NEXT_CONTROLLED_GAME
            ),
            controlled_teams=(
                east_seven,
            ),
            policy=(
                FranchiseSimulationPolicy
                .FREE_SIMULATION
            ),
            seed=seed,
        )
    )
    east_one = (
        get_postseason_state(
            state
        ).seed_order["East"][0]
    )
    checkpoint_counts: list[int] = []
    bounded_state, bounded_result = (
        advance_postseason(
            state,
            scope=(
                PostseasonSimulationScope
                .NEXT_CONTROLLED_GAME
            ),
            controlled_teams=(
                east_one,
            ),
            policy=(
                FranchiseSimulationPolicy
                .FREE_SIMULATION
            ),
            seed=seed,
            max_games=2,
            progress_callback=(
                lambda current_state, count, game: (
                    checkpoint_counts.append(
                        count
                    )
                )
            ),
        )
    )
    deterministic_preview_a = (
        simulate_postseason_game(
            state,
            opening_games[0],
            seed=seed,
        )
    )
    deterministic_preview_b = (
        simulate_postseason_game(
            state,
            opening_games[0],
            seed=seed,
        )
    )

    postseason_started = time.perf_counter()
    state, result = advance_postseason(
        state,
        scope=(
            PostseasonSimulationScope
            .TO_CHAMPION
        ),
        policy=(
            FranchiseSimulationPolicy
            .FREE_SIMULATION
        ),
        seed=seed,
    )
    postseason_runtime_seconds = round(
        time.perf_counter() - postseason_started,
        3,
    )
    postseason = get_postseason_state(
        state
    )
    total_postseason_games = len(
        postseason.completed_games
    )
    play_in_games = [
        game
        for game
        in postseason.games.values()
        if game.stage
        in {
            PostseasonStage
            .PLAY_IN_OPENING,
            PostseasonStage
            .PLAY_IN_FINAL,
        }
    ]
    series_by_stage = {
        stage.value: len(
            stage_series(
                postseason,
                stage,
            )
        )
        for stage in (
            PostseasonStage.FIRST_ROUND,
            PostseasonStage
            .CONFERENCE_SEMIFINALS,
            PostseasonStage
            .CONFERENCE_FINALS,
            PostseasonStage.NBA_FINALS,
        )
    }
    postseason_games_played = sum(
        totals.games_played
        for totals
        in postseason
        .postseason_player_totals.values()
    )
    playoff_player_rows = postseason_player_rows(
        state,
        minimum_games=1,
        limit=600,
        include_play_in=False,
    )
    playoff_team_rows = postseason_team_rows(
        state,
        include_play_in=False,
        limit=30,
    )

    checks = {
        "postseason_version_is_current": (
            postseason.version
            == POSTSEASON_VERSION
        ),
        "postseason_uses_structural_compatibility": (
            postseason_state_is_compatible(
                postseason
            )
        ),
        "regular_season_completed_1230_games": (
            regular.games_simulated
            == 1230
        ),
        "opening_play_in_has_four_games": (
            len(opening_games) == 4
        ),
        "controlled_postseason_games_find_team_game": (
            len(controlled_opening) == 1
            and east_seven
            in {
                controlled_opening[0].home_team,
                controlled_opening[0].away_team,
            }
        ),
        "team_status_reports_seed_and_next_game": (
            controlled_status.seed == 7
            and bool(
                controlled_status.next_game_id
            )
        ),
        "team_status_marks_seed_11_as_eliminated": (
            missed_status.seed == 11
            and missed_status.eliminated
            and not missed_status.alive
        ),
        "advance_to_next_controlled_game_pauses_before_it": (
            stopped_result.games_simulated
            >= 0
            and bool(
                stopped_result.paused_before_game_id
            )
            and get_postseason_state(
                stopped_state
            ).games[
                stopped_result
                .paused_before_game_id
            ].status
            == PostseasonGameStatus.SCHEDULED
        ),
        "bounded_advance_stops_at_game_limit": (
            bounded_result.games_simulated == 2
            and bounded_result.stopped_at_game_limit
            and len(
                get_postseason_state(
                    bounded_state
                ).completed_games
            )
            == 2
        ),
        "progress_callback_runs_after_each_game": (
            checkpoint_counts
            == [1, 2]
        ),
        "preview_is_deterministic": (
            deterministic_preview_a.game
            == deterministic_preview_b.game
        ),
        "play_in_has_six_completed_games": (
            len(play_in_games) == 6
            and all(
                game.status
                == (
                    PostseasonGameStatus
                    .COMPLETED
                )
                for game in play_in_games
            )
        ),
        "series_counts_match_nba_bracket": (
            series_by_stage
            == {
                "first_round": 8,
                "conference_semifinals": 4,
                "conference_finals": 2,
                "nba_finals": 1,
            }
        ),
        "all_series_end_with_four_wins": all(
            max(
                series.higher_seed_wins,
                series.lower_seed_wins,
            )
            == 4
            for series
            in postseason.series.values()
        ),
        "all_series_use_at_most_seven_games": all(
            len(series.game_ids) <= 7
            for series
            in postseason.series.values()
        ),
        "postseason_game_count_is_plausible": (
            66
            <= total_postseason_games
            <= 111
        ),
        "champion_is_crowned": (
            postseason.stage
            == PostseasonStage.COMPLETE
            and postseason.champion
            in state.teams
            and postseason.runner_up
            in state.teams
            and postseason.champion
            != postseason.runner_up
        ),
        "conference_champions_are_recorded": (
            set(
                postseason
                .conference_champions
            )
            == {"East", "West"}
        ),
        "regular_standings_are_unchanged": (
            state.standings
            == regular_standings
        ),
        "regular_player_totals_are_unchanged": (
            state.player_season_totals
            == regular_totals
        ),
        "regular_schedule_is_unchanged": (
            state.schedule
            == regular_schedule
        ),
        "postseason_player_totals_are_populated": (
            postseason_games_played
            > 0
        ),
        "playoff_player_rows_exclude_play_in_and_have_full_stats": (
            bool(playoff_player_rows)
            and all(
                {
                    "Player",
                    "Team",
                    "Pos",
                    "GP",
                    "MIN",
                    "PTS",
                    "REB",
                    "AST",
                    "STL",
                    "BLK",
                    "TO",
                    "PF",
                    "FG%",
                    "3P%",
                    "FT%",
                }.issubset(row)
                for row in playoff_player_rows
            )
        ),
        "playoff_team_rows_reconcile": (
            bool(playoff_team_rows)
            and all(
                row["GP"]
                == row["W"] + row["L"]
                for row in playoff_team_rows
            )
            and sum(
                row["GP"]
                for row in playoff_team_rows
            )
            == 2 * sum(
                1
                for game_id
                in postseason.completed_games
                if postseason.games[game_id].stage
                in PLAYOFF_STAT_STAGES
            )
        ),
        "completed_game_history_exposes_box_scores": (
            bool(
                completed_postseason_games(
                    state
                )
            )
            and bool(
                completed_postseason_games(
                    state
                )[0][1]
                .player_box_scores
            )
        ),
        "state_advances_to_offseason_phase": (
            state.phase
            == LeaguePhase.OFFSEASON
        ),
        "advance_result_reports_champion": (
            result.champion
            == postseason.champion
        ),
        "batch_postseason_runtime_is_interactive": (
            postseason_runtime_seconds < 15.0
        ),
    }
    checks.update(
        {
            f"state_{name}": passed
            for name, passed
            in validate_postseason_state(
                state
            ).items()
        }
    )
    failed = [
        name
        for name, passed
        in checks.items()
        if not passed
    ]
    report = {
        "script": POSTSEASON_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "champion": (
                postseason.champion
            ),
            "runner_up": (
                postseason.runner_up
            ),
            "conference_champions": (
                postseason
                .conference_champions
            ),
            "postseason_games": (
                total_postseason_games
            ),
            "postseason_runtime_seconds": postseason_runtime_seconds,
            "postseason_games_per_second": round(
                total_postseason_games
                / max(postseason_runtime_seconds, 0.001),
                2,
            ),
            "execution_version": POSTSEASON_EXECUTION_VERSION,
            "series_count": len(
                postseason.series
            ),
            "series_by_stage": (
                series_by_stage
            ),
            "top_postseason_players": (
                postseason_player_rows(
                    state,
                    minimum_games=4,
                    limit=10,
                )
            ),
            "top_playoff_players": (
                postseason_player_rows(
                    state,
                    minimum_games=4,
                    limit=10,
                    include_play_in=False,
                )
            ),
            "playoff_team_records": (
                postseason_team_rows(
                    state,
                    include_play_in=False,
                    limit=30,
                )
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
            default=str,
        ),
        encoding="utf-8",
    )

    if failed:
        raise AssertionError(
            "Postseason self-test failed: "
            + ", ".join(failed)
        )

    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20260808,
    )
    args = parser.parse_args()

    if args.self_test:
        report = run_self_test(
            seed=args.seed
        )
        print(
            json.dumps(
                report,
                indent=2,
                default=str,
            )
        )
        print(
            "\nSIMULATION POSTSEASON V1 "
            "SELF-TEST PASSED"
        )
        return 0

    print(
        json.dumps(
            {
                "script": (
                    POSTSEASON_VERSION
                ),
                "message": (
                    "Use --self-test to validate "
                    "the full play-in and playoff bracket."
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
