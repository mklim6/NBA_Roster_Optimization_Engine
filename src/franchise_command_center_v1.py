from __future__ import annotations

import argparse
import copy
import html
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from simulation_league_alignment_v1 import (  # noqa: E402
    apply_nba_team_alignment,
    conference_for_team,
    division_for_team,
)
from franchise_calendar_v1 import (  # noqa: E402
    TeamMonthCalendar,
    controlled_team_pause,
    date_for_day_index,
    normalize_controlled_teams,
    team_schedule_games,
)
from regular_season_simulation_controller_v1 import (  # noqa: E402
    SimulationScope,
    build_installed_state,
    build_regular_season_simulation_plan,
    regular_season_progress,
    regular_season_state_fingerprint,
    simulate_regular_season_scope,
)
from simulation_league_state_v1 import (  # noqa: E402
    AvailabilityStatus,
    GameStatus,
    RotationState,
    SimulationLeagueState,
    validate_simulation_league_state,
)


COMMAND_CENTER_VERSION = (
    "franchise-command-center-v1.1-2026-08-08"
)
SELF_TEST_REPORT = (
    OUTPUTS
    / "franchise_command_center_v1_self_test.json"
)

NBA_TEAM_IDS: dict[str, int] = {
    "ATL": 1610612737,
    "BOS": 1610612738,
    "CLE": 1610612739,
    "NOP": 1610612740,
    "CHI": 1610612741,
    "DAL": 1610612742,
    "DEN": 1610612743,
    "GSW": 1610612744,
    "HOU": 1610612745,
    "LAC": 1610612746,
    "LAL": 1610612747,
    "MIA": 1610612748,
    "MIL": 1610612749,
    "MIN": 1610612750,
    "BKN": 1610612751,
    "NYK": 1610612752,
    "ORL": 1610612753,
    "IND": 1610612754,
    "PHI": 1610612755,
    "PHX": 1610612756,
    "POR": 1610612757,
    "SAC": 1610612758,
    "SAS": 1610612759,
    "OKC": 1610612760,
    "TOR": 1610612761,
    "UTA": 1610612762,
    "MEM": 1610612763,
    "WAS": 1610612764,
    "DET": 1610612765,
    "CHA": 1610612766,
}

TEAM_NAMES: dict[str, str] = {
    "ATL": "Atlanta Hawks",
    "BOS": "Boston Celtics",
    "BKN": "Brooklyn Nets",
    "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls",
    "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks",
    "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors",
    "HOU": "Houston Rockets",
    "IND": "Indiana Pacers",
    "LAC": "LA Clippers",
    "LAL": "Los Angeles Lakers",
    "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks",
    "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans",
    "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers",
    "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers",
    "SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors",
    "UTA": "Utah Jazz",
    "WAS": "Washington Wizards",
}

TEAM_COLORS: dict[str, tuple[str, str]] = {
    "ATL": ("#E03A3E", "#C1D32F"),
    "BOS": ("#007A33", "#BA9653"),
    "BKN": ("#000000", "#FFFFFF"),
    "CHA": ("#1D1160", "#00788C"),
    "CHI": ("#CE1141", "#000000"),
    "CLE": ("#860038", "#FDBB30"),
    "DAL": ("#00538C", "#B8C4CA"),
    "DEN": ("#0E2240", "#FEC524"),
    "DET": ("#C8102E", "#1D42BA"),
    "GSW": ("#1D428A", "#FFC72C"),
    "HOU": ("#CE1141", "#000000"),
    "IND": ("#002D62", "#FDBB30"),
    "LAC": ("#C8102E", "#1D428A"),
    "LAL": ("#552583", "#FDB927"),
    "MEM": ("#5D76A9", "#12173F"),
    "MIA": ("#98002E", "#F9A01B"),
    "MIL": ("#00471B", "#EEE1C6"),
    "MIN": ("#0C2340", "#78BE20"),
    "NOP": ("#0C2340", "#C8102E"),
    "NYK": ("#006BB6", "#F58426"),
    "OKC": ("#007AC1", "#EF3B24"),
    "ORL": ("#0077C0", "#C4CED4"),
    "PHI": ("#006BB6", "#ED174C"),
    "PHX": ("#1D1160", "#E56020"),
    "POR": ("#E03A3E", "#000000"),
    "SAC": ("#5A2D81", "#63727A"),
    "SAS": ("#C4CED4", "#000000"),
    "TOR": ("#CE1141", "#000000"),
    "UTA": ("#002B5C", "#F9A01B"),
    "WAS": ("#002B5C", "#E31837"),
}


class FranchiseCommandCenterError(RuntimeError):
    """Raised when a franchise command cannot be completed."""


class FranchiseSimulationPolicy(str, Enum):
    STOP_EVERY_CONTROLLED_GAME = (
        "stop_every_controlled_game"
    )
    STOP_FOR_DECISIONS = "stop_for_decisions"
    AUTO_SAVED_ROTATIONS = "auto_saved_rotations"
    FREE_SIMULATION = "free_simulation"


POLICY_LABELS: dict[
    FranchiseSimulationPolicy,
    str,
] = {
    FranchiseSimulationPolicy.STOP_EVERY_CONTROLLED_GAME: (
        "Stop before every controlled-team game"
    ),
    FranchiseSimulationPolicy.STOP_FOR_DECISIONS: (
        "Stop only for coaching or medical decisions"
    ),
    FranchiseSimulationPolicy.AUTO_SAVED_ROTATIONS: (
        "Auto-sim controlled teams with saved rotations"
    ),
    FranchiseSimulationPolicy.FREE_SIMULATION: (
        "Simulate freely through the requested range"
    ),
}


@dataclass(frozen=True)
class RotationPlan:
    version: str
    team: str
    starter_ids: tuple[str, ...]
    rotation_player_ids: tuple[str, ...]
    minutes_targets: dict[str, float]
    total_minutes: float


@dataclass(frozen=True)
class CoachingAlert:
    severity: str
    category: str
    title: str
    detail: str
    player_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TeamCommandSnapshot:
    version: str
    team: str
    team_name: str
    logo_url: str
    primary_color: str
    secondary_color: str
    conference: str
    division: str
    wins: int
    losses: int
    win_percentage: float
    point_differential: int
    league_rank: int
    conference_rank: int
    recent_form: str
    streak: str
    season_completion_percentage: float
    next_game_id: str
    next_game_day: int | None
    next_game_date: str
    next_opponent: str
    next_location: str
    opponent_wins: int
    opponent_losses: int
    rest_days: int | None
    back_to_back: bool
    alerts: tuple[CoachingAlert, ...]


@dataclass(frozen=True)
class FranchiseAdvanceResult:
    version: str
    policy: FranchiseSimulationPolicy
    requested_scope: SimulationScope
    games_simulated: int
    final_day: int
    paused: bool
    pause_day: int | None
    pause_game_ids: tuple[str, ...]
    selected_game_id: str
    message: str


def team_name(team: str) -> str:
    resolved = str(team).strip().upper()
    return TEAM_NAMES.get(resolved, resolved)


def team_logo_url(
    team: str,
    *,
    variant: str = "global",
) -> str:
    resolved = str(team).strip().upper()

    if resolved not in NBA_TEAM_IDS:
        raise FranchiseCommandCenterError(
            f"Unknown NBA team: {resolved}."
        )

    asset_group = (
        "global"
        if variant == "global"
        else "primary"
    )
    return (
        "https://cdn.nba.com/logos/nba/"
        f"{NBA_TEAM_IDS[resolved]}/"
        f"{asset_group}/L/logo.svg"
    )


def team_colors(
    team: str,
) -> tuple[str, str]:
    return TEAM_COLORS.get(
        str(team).strip().upper(),
        ("#175CD3", "#E4E7EC"),
    )


def normalize_policy(
    policy: FranchiseSimulationPolicy | str,
) -> FranchiseSimulationPolicy:
    try:
        return FranchiseSimulationPolicy(
            policy
        )
    except ValueError as exc:
        raise FranchiseCommandCenterError(
            f"Unknown franchise simulation policy: {policy!r}."
        ) from exc


def standing_win_percentage(
    standing: Any,
) -> float:
    return (
        standing.wins
        / standing.games_played
        if standing.games_played
        else 0.0
    )


def standing_sort_key(
    standing: Any,
) -> tuple[Any, ...]:
    return (
        -standing_win_percentage(standing),
        -standing.wins,
        standing.losses,
        -(
            standing.points_for
            - standing.points_against
        ),
        standing.team_abbreviation,
    )


def ordered_standings(
    state: SimulationLeagueState,
    *,
    conference: str | None = None,
) -> tuple[Any, ...]:
    standings = list(
        state.standings.values()
    )

    if conference:
        standings = [
            standing
            for standing in standings
            if conference_for_team(
                standing.team_abbreviation
            )
            == conference
        ]

    return tuple(
        sorted(
            standings,
            key=standing_sort_key,
        )
    )


def recent_team_results(
    state: SimulationLeagueState,
    team: str,
    *,
    limit: int = 10,
) -> tuple[str, ...]:
    resolved_team = str(team).strip().upper()
    completed_rows: list[
        tuple[int, str, str]
    ] = []

    for game_id, completed in (
        state.completed_games.items()
    ):
        if resolved_team not in {
            completed.home_team,
            completed.away_team,
        }:
            continue

        scheduled = state.schedule[
            game_id
        ]
        team_score = (
            completed.home_score
            if completed.home_team
            == resolved_team
            else completed.away_score
        )
        opponent_score = (
            completed.away_score
            if completed.home_team
            == resolved_team
            else completed.home_score
        )
        completed_rows.append(
            (
                int(scheduled.day_index),
                game_id,
                (
                    "W"
                    if team_score
                    > opponent_score
                    else "L"
                ),
            )
        )

    completed_rows.sort(
        key=lambda row: (
            row[0],
            row[1],
        )
    )
    return tuple(
        row[2]
        for row in completed_rows[
            -int(limit) :
        ]
    )


def previous_team_game_day(
    state: SimulationLeagueState,
    team: str,
    *,
    before_day: int,
) -> int | None:
    days = [
        int(game.day_index)
        for game in state.schedule.values()
        if (
            int(game.day_index)
            < int(before_day)
            and team
            in {
                game.home_team,
                game.away_team,
            }
        )
    ]
    return max(days) if days else None


def next_team_game(
    state: SimulationLeagueState,
    team: str,
) -> Any | None:
    games = [
        game
        for game in team_schedule_games(
            state,
            team,
        )
        if game.status
        == GameStatus.SCHEDULED
    ]
    return games[0] if games else None


def build_rotation_plan(
    state: SimulationLeagueState,
    team: str,
) -> RotationPlan:
    resolved_team = str(team).strip().upper()

    if resolved_team not in state.teams:
        raise FranchiseCommandCenterError(
            f"Unknown team: {resolved_team}."
        )

    rotation = state.teams[
        resolved_team
    ].rotation
    return RotationPlan(
        version=COMMAND_CENTER_VERSION,
        team=resolved_team,
        starter_ids=tuple(
            rotation.starter_ids
        ),
        rotation_player_ids=tuple(
            rotation.rotation_player_ids
        ),
        minutes_targets={
            player_id: round(
                float(minutes),
                1,
            )
            for player_id, minutes
            in rotation.minutes_targets.items()
        },
        total_minutes=round(
            sum(
                rotation.minutes_targets.values()
            ),
            1,
        ),
    )


def rotation_plan_from_rows(
    state: SimulationLeagueState,
    team: str,
    rows: Sequence[Mapping[str, Any]],
) -> RotationPlan:
    resolved_team = str(team).strip().upper()
    starter_ids: list[str] = []
    rotation_ids: list[str] = []
    minutes_targets: dict[
        str,
        float,
    ] = {}

    for row in rows:
        player_id = str(
            row.get("player_id", "")
        ).strip()

        if not player_id:
            continue

        in_rotation = bool(
            row.get("in_rotation", False)
        )
        is_starter = bool(
            row.get("starter", False)
        )
        minutes = float(
            row.get("minutes", 0.0)
            or 0.0
        )

        if is_starter:
            in_rotation = True
            starter_ids.append(player_id)

        if in_rotation:
            rotation_ids.append(player_id)
            minutes_targets[
                player_id
            ] = round(minutes, 1)

    plan = RotationPlan(
        version=COMMAND_CENTER_VERSION,
        team=resolved_team,
        starter_ids=tuple(starter_ids),
        rotation_player_ids=tuple(
            rotation_ids
        ),
        minutes_targets=minutes_targets,
        total_minutes=round(
            sum(
                minutes_targets.values()
            ),
            1,
        ),
    )
    validate_rotation_plan(
        state,
        plan,
    )
    return plan


def validate_rotation_plan(
    state: SimulationLeagueState,
    plan: RotationPlan,
) -> dict[str, bool]:
    if plan.team not in state.teams:
        raise FranchiseCommandCenterError(
            f"Unknown rotation-plan team: {plan.team}."
        )

    team_state = state.teams[
        plan.team
    ]
    roster_ids = set(
        team_state.roster_player_ids
    )
    starter_ids = tuple(
        plan.starter_ids
    )
    rotation_ids = tuple(
        plan.rotation_player_ids
    )
    minute_ids = set(
        plan.minutes_targets
    )
    out_ids = {
        player_id
        for player_id, injury
        in state.injuries.items()
        if injury.status
        == AvailabilityStatus.OUT
    }
    checks = {
        "plan_version_is_current": (
            plan.version
            == COMMAND_CENTER_VERSION
        ),
        "exactly_five_starters": (
            len(starter_ids) == 5
            and len(set(starter_ids))
            == 5
        ),
        "rotation_size_is_playable": (
            state.settings
            .minimum_game_players
            <= len(rotation_ids)
            <= 15
        ),
        "rotation_ids_are_unique": (
            len(rotation_ids)
            == len(set(rotation_ids))
        ),
        "starters_are_in_rotation": (
            set(starter_ids)
            .issubset(rotation_ids)
        ),
        "rotation_is_roster_subset": (
            set(rotation_ids)
            .issubset(roster_ids)
        ),
        "minute_keys_match_rotation": (
            minute_ids
            == set(rotation_ids)
        ),
        "minutes_are_bounded": all(
            0.0 < float(minutes) <= 48.0
            for minutes
            in plan.minutes_targets.values()
        ),
        "minutes_total_240": math.isclose(
            plan.total_minutes,
            240.0,
            abs_tol=0.1,
        ),
        "out_players_are_not_in_rotation": (
            not set(rotation_ids)
            .intersection(out_ids)
        ),
    }
    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]

    if failed:
        raise FranchiseCommandCenterError(
            "Rotation plan validation failed: "
            + ", ".join(failed)
        )

    return checks


def apply_rotation_plan(
    state: SimulationLeagueState,
    plan: RotationPlan,
) -> SimulationLeagueState:
    validate_rotation_plan(
        state,
        plan,
    )
    source_fingerprint = (
        regular_season_state_fingerprint(
            state
        )
    )
    updated = copy.deepcopy(state)
    updated.teams[
        plan.team
    ].rotation = RotationState(
        starter_ids=tuple(
            plan.starter_ids
        ),
        rotation_player_ids=tuple(
            plan.rotation_player_ids
        ),
        minutes_targets=dict(
            plan.minutes_targets
        ),
    )
    validate_simulation_league_state(
        updated
    )

    if (
        regular_season_state_fingerprint(
            state
        )
        != source_fingerprint
    ):
        raise FranchiseCommandCenterError(
            "Applying a rotation plan mutated "
            "the source state."
        )

    return updated


def rotation_management_rows(
    state: SimulationLeagueState,
    team: str,
) -> list[dict[str, Any]]:
    resolved_team = str(team).strip().upper()
    team_state = state.teams[
        resolved_team
    ]
    rotation = team_state.rotation
    rotation_index = {
        player_id: index
        for index, player_id
        in enumerate(
            rotation.rotation_player_ids
        )
    }
    starter_set = set(
        rotation.starter_ids
    )

    return [
        {
            "player_id": player_id,
            "player": (
                state.players[
                    player_id
                ].player_name
            ),
            "position": (
                state.players[
                    player_id
                ].position
            ),
            "age": (
                state.players[
                    player_id
                ].age
            ),
            "overall": round(
                state.players[
                    player_id
                ].overall_rating,
                1,
            ),
            "starter": (
                player_id
                in starter_set
            ),
            "in_rotation": (
                player_id
                in rotation_index
            ),
            "minutes": round(
                rotation.minutes_targets.get(
                    player_id,
                    0.0,
                ),
                1,
            ),
            "rotation_order": (
                rotation_index.get(
                    player_id,
                    len(
                        team_state
                        .roster_player_ids
                    ),
                )
                + 1
            ),
            "availability": (
                state.injuries[
                    player_id
                ].status.value
            ),
        }
        for player_id
        in sorted(
            team_state.roster_player_ids,
            key=lambda pid: (
                rotation_index.get(
                    pid,
                    999,
                ),
                -state.players[
                    pid
                ].overall_rating,
                state.players[
                    pid
                ].player_name,
            ),
        )
    ]


def coaching_alerts_for_game(
    state: SimulationLeagueState,
    game: Any,
    controlled_team: str,
) -> tuple[CoachingAlert, ...]:
    team = str(
        controlled_team
    ).strip().upper()

    if team not in {
        game.home_team,
        game.away_team,
    }:
        return ()

    alerts: list[CoachingAlert] = []
    team_state = state.teams[team]
    rotation = team_state.rotation
    game_day = int(
        game.day_index
    )
    previous_day = previous_team_game_day(
        state,
        team,
        before_day=game_day,
    )
    rest_days = (
        game_day - previous_day - 1
        if previous_day is not None
        else None
    )
    unavailable = [
        player_id
        for player_id
        in rotation.rotation_player_ids
        if state.injuries[
            player_id
        ].status
        != AvailabilityStatus.HEALTHY
    ]

    if unavailable:
        names = ", ".join(
            state.players[
                player_id
            ].player_name
            for player_id in unavailable
        )
        alerts.append(
            CoachingAlert(
                severity="critical",
                category="availability",
                title=(
                    "Rotation availability requires review"
                ),
                detail=(
                    f"{names} are not fully healthy "
                    "but remain in the saved rotation."
                ),
                player_ids=tuple(
                    unavailable
                ),
            )
        )

    if rest_days == 0:
        heavy = tuple(
            player_id
            for player_id, minutes
            in rotation.minutes_targets.items()
            if float(minutes) >= 35.0
        )
        alerts.append(
            CoachingAlert(
                severity=(
                    "warning"
                    if heavy
                    else "info"
                ),
                category="rest",
                title="Back-to-back game",
                detail=(
                    "Consider lowering the largest "
                    "minute assignments before tipoff."
                    if heavy
                    else (
                        "The team is playing on "
                        "consecutive days."
                    )
                ),
                player_ids=heavy,
            )
        )
    elif rest_days == 1:
        alerts.append(
            CoachingAlert(
                severity="info",
                category="rest",
                title="One rest day",
                detail=(
                    "The team has one full day "
                    "between games."
                ),
            )
        )

    total_minutes = sum(
        rotation.minutes_targets.values()
    )
    if not math.isclose(
        total_minutes,
        240.0,
        abs_tol=0.1,
    ):
        alerts.append(
            CoachingAlert(
                severity="critical",
                category="rotation",
                title="Rotation minutes do not reconcile",
                detail=(
                    f"Saved minutes total "
                    f"{total_minutes:.1f}, not 240."
                ),
            )
        )

    opponent = (
        game.away_team
        if game.home_team == team
        else game.home_team
    )
    opponent_standing = state.standings[
        opponent
    ]

    if (
        opponent_standing.games_played
        >= 10
        and standing_win_percentage(
            opponent_standing
        )
        >= 0.600
    ):
        alerts.append(
            CoachingAlert(
                severity="info",
                category="opponent",
                title="High-performing opponent",
                detail=(
                    f"{opponent} enters at "
                    f"{opponent_standing.wins}-"
                    f"{opponent_standing.losses}."
                ),
            )
        )

    return tuple(alerts)


def game_requires_decision(
    state: SimulationLeagueState,
    game: Any,
    controlled_teams: Sequence[str],
) -> bool:
    controlled = normalize_controlled_teams(
        controlled_teams,
        available_teams=state.teams,
    )

    return any(
        alert.severity
        in {"critical", "warning"}
        for team in controlled
        for alert
        in coaching_alerts_for_game(
            state,
            game,
            team,
        )
    )


def next_controlled_game(
    state: SimulationLeagueState,
    controlled_teams: Sequence[str],
) -> Any | None:
    controlled = set(
        normalize_controlled_teams(
            controlled_teams,
            available_teams=state.teams,
        )
    )

    if not controlled:
        return None

    candidates = [
        game
        for game in state.schedule.values()
        if (
            game.status
            == GameStatus.SCHEDULED
            and controlled.intersection(
                {
                    game.home_team,
                    game.away_team,
                }
            )
        )
    ]

    return (
        min(
            candidates,
            key=lambda game: (
                int(game.day_index),
                game.game_id,
            ),
        )
        if candidates
        else None
    )


def build_team_snapshot(
    state: SimulationLeagueState,
    team: str,
) -> TeamCommandSnapshot:
    validate_simulation_league_state(
        state
    )
    apply_nba_team_alignment(
        state
    )
    resolved_team = str(team).strip().upper()

    if resolved_team not in state.teams:
        raise FranchiseCommandCenterError(
            f"Unknown command-center team: {resolved_team}."
        )

    team_state = state.teams[
        resolved_team
    ]
    standing = state.standings[
        resolved_team
    ]
    league = ordered_standings(state)
    conference = ordered_standings(
        state,
        conference=team_state.conference,
    )
    league_rank = (
        league.index(standing) + 1
    )
    conference_rank = (
        conference.index(standing) + 1
    )
    recent = recent_team_results(
        state,
        resolved_team,
    )
    next_game = next_team_game(
        state,
        resolved_team,
    )
    next_game_id = ""
    next_game_day: int | None = None
    next_game_date = ""
    next_opponent = ""
    next_location = ""
    opponent_wins = 0
    opponent_losses = 0
    rest_days: int | None = None
    back_to_back = False
    alerts: tuple[
        CoachingAlert,
        ...,
    ] = ()

    if next_game is not None:
        next_game_id = (
            next_game.game_id
        )
        next_game_day = int(
            next_game.day_index
        )
        next_game_date = (
            date_for_day_index(
                state.settings.season_label,
                next_game_day,
            ).strftime("%b %d, %Y")
        )
        is_home = (
            next_game.home_team
            == resolved_team
        )
        next_opponent = (
            next_game.away_team
            if is_home
            else next_game.home_team
        )
        next_location = (
            "HOME"
            if is_home
            else "AWAY"
        )
        opponent_standing = (
            state.standings[
                next_opponent
            ]
        )
        opponent_wins = (
            opponent_standing.wins
        )
        opponent_losses = (
            opponent_standing.losses
        )
        previous_day = (
            previous_team_game_day(
                state,
                resolved_team,
                before_day=(
                    next_game_day
                ),
            )
        )
        rest_days = (
            next_game_day
            - previous_day
            - 1
            if previous_day is not None
            else None
        )
        back_to_back = (
            rest_days == 0
        )
        alerts = (
            coaching_alerts_for_game(
                state,
                next_game,
                resolved_team,
            )
        )

    progress = regular_season_progress(
        state
    )
    primary, secondary = (
        team_colors(resolved_team)
    )

    return TeamCommandSnapshot(
        version=COMMAND_CENTER_VERSION,
        team=resolved_team,
        team_name=team_name(
            resolved_team
        ),
        logo_url=team_logo_url(
            resolved_team
        ),
        primary_color=primary,
        secondary_color=secondary,
        conference=conference_for_team(
            resolved_team
        ),
        division=division_for_team(
            resolved_team
        ),
        wins=standing.wins,
        losses=standing.losses,
        win_percentage=(
            standing_win_percentage(
                standing
            )
        ),
        point_differential=(
            standing.points_for
            - standing.points_against
        ),
        league_rank=league_rank,
        conference_rank=(
            conference_rank
        ),
        recent_form=(
            "".join(recent)
            if recent
            else "No games"
        ),
        streak=(
            (
                f"{standing.streak_type}"
                f"{standing.streak_length}"
            )
            if standing.streak_type
            else "-"
        ),
        season_completion_percentage=float(
            progress[
                "completion_percentage"
            ]
        ),
        next_game_id=next_game_id,
        next_game_day=next_game_day,
        next_game_date=next_game_date,
        next_opponent=next_opponent,
        next_location=next_location,
        opponent_wins=opponent_wins,
        opponent_losses=(
            opponent_losses
        ),
        rest_days=rest_days,
        back_to_back=back_to_back,
        alerts=alerts,
    )


def _simulate_before_day(
    state: SimulationLeagueState,
    pause_day: int,
) -> tuple[
    SimulationLeagueState,
    int,
]:
    unplayed_before = [
        game
        for game in state.schedule.values()
        if (
            game.status
            == GameStatus.SCHEDULED
            and int(game.day_index)
            < int(pause_day)
        )
    ]

    if not unplayed_before:
        return state, 0

    target_day = max(
        int(game.day_index)
        for game in unplayed_before
    )
    advanced, result = (
        simulate_regular_season_scope(
            state,
            scope=(
                SimulationScope.THROUGH_DAY
            ),
            target_day=target_day,
        )
    )
    return (
        advanced,
        result.games_simulated,
    )


def advance_franchise_scope(
    state: SimulationLeagueState,
    *,
    controlled_teams: Sequence[str],
    policy: (
        FranchiseSimulationPolicy | str
    ),
    scope: SimulationScope | str,
    target_day: int | None = None,
) -> tuple[
    SimulationLeagueState,
    FranchiseAdvanceResult,
]:
    resolved_policy = normalize_policy(
        policy
    )
    resolved_scope = SimulationScope(
        scope
    )
    controlled = normalize_controlled_teams(
        controlled_teams,
        available_teams=state.teams,
    )
    source_fingerprint = (
        regular_season_state_fingerprint(
            state
        )
    )
    plan = (
        build_regular_season_simulation_plan(
            state,
            scope=resolved_scope,
            target_day=target_day,
        )
    )
    pause_day: int | None = None
    pause_game_ids: tuple[str, ...] = ()

    if (
        resolved_policy
        == FranchiseSimulationPolicy
        .STOP_EVERY_CONTROLLED_GAME
    ):
        pause = controlled_team_pause(
            state,
            controlled_teams=controlled,
            scope=resolved_scope,
            target_day=target_day,
        )
        pause_day = pause.pause_day
        pause_game_ids = (
            pause.pause_game_ids
        )

    elif (
        resolved_policy
        == FranchiseSimulationPolicy
        .STOP_FOR_DECISIONS
        and controlled
    ):
        controlled_set = set(
            controlled
        )
        planned_games = [
            state.schedule[game_id]
            for game_id in plan.game_ids
        ]
        decision_games = [
            game
            for game in planned_games
            if (
                controlled_set.intersection(
                    {
                        game.home_team,
                        game.away_team,
                    }
                )
                and game_requires_decision(
                    state,
                    game,
                    controlled,
                )
            )
        ]

        if decision_games:
            pause_day = min(
                int(game.day_index)
                for game in decision_games
            )
            pause_game_ids = tuple(
                game.game_id
                for game in decision_games
                if int(game.day_index)
                == pause_day
            )

    if pause_day is not None:
        advanced, simulated_count = (
            _simulate_before_day(
                state,
                pause_day,
            )
        )
        selected_game_id = (
            pause_game_ids[0]
            if pause_game_ids
            else ""
        )
        result = FranchiseAdvanceResult(
            version=(
                COMMAND_CENTER_VERSION
            ),
            policy=resolved_policy,
            requested_scope=(
                resolved_scope
            ),
            games_simulated=(
                simulated_count
            ),
            final_day=(
                advanced
                .current_day_index
            ),
            paused=True,
            pause_day=pause_day,
            pause_game_ids=(
                pause_game_ids
            ),
            selected_game_id=(
                selected_game_id
            ),
            message=(
                (
                    f"Simulated {simulated_count} "
                    "computer-managed game(s). "
                )
                if simulated_count
                else ""
            )
            + (
                "Paused before the next "
                "controlled-team decision."
            ),
        )
    else:
        advanced, simulation = (
            simulate_regular_season_scope(
                state,
                scope=resolved_scope,
                target_day=target_day,
            )
        )
        next_game = next_controlled_game(
            advanced,
            controlled,
        )
        result = FranchiseAdvanceResult(
            version=(
                COMMAND_CENTER_VERSION
            ),
            policy=resolved_policy,
            requested_scope=(
                resolved_scope
            ),
            games_simulated=(
                simulation.games_simulated
            ),
            final_day=(
                advanced
                .current_day_index
            ),
            paused=False,
            pause_day=None,
            pause_game_ids=(),
            selected_game_id=(
                next_game.game_id
                if next_game is not None
                else ""
            ),
            message=(
                f"Simulated "
                f"{simulation.games_simulated} "
                f"game(s) through day "
                f"{advanced.current_day_index}."
            ),
        )

    if (
        regular_season_state_fingerprint(
            state
        )
        != source_fingerprint
    ):
        raise FranchiseCommandCenterError(
            "Franchise advancement mutated "
            "the source state."
        )

    validate_simulation_league_state(
        advanced
    )
    return advanced, result


def standings_rows(
    state: SimulationLeagueState,
    *,
    conference: str | None = None,
) -> list[dict[str, Any]]:
    return [
        {
            "Rank": rank,
            "Team": (
                standing
                .team_abbreviation
            ),
            "W": standing.wins,
            "L": standing.losses,
            "Win%": round(
                standing_win_percentage(
                    standing
                ),
                3,
            ),
            "Home": (
                f"{standing.home_wins}-"
                f"{standing.home_losses}"
            ),
            "Away": (
                f"{standing.away_wins}-"
                f"{standing.away_losses}"
            ),
            "Diff": (
                standing.points_for
                - standing.points_against
            ),
            "Streak": (
                (
                    f"{standing.streak_type}"
                    f"{standing.streak_length}"
                )
                if standing.streak_type
                else "-"
            ),
        }
        for rank, standing
        in enumerate(
            ordered_standings(
                state,
                conference=conference,
            ),
            start=1,
        )
    ]


def player_leader_rows(
    state: SimulationLeagueState,
    *,
    minimum_games: int = 1,
    limit: int = 25,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for player_id, totals in (
        state.player_season_totals.items()
    ):
        if totals.games_played < minimum_games:
            continue

        player = state.players[
            player_id
        ]
        games = totals.games_played
        rows.append(
            {
                "Player": (
                    player.player_name
                ),
                "Team": (
                    player.team_abbreviation
                ),
                "Pos": player.position,
                "GP": games,
                "MIN": round(
                    totals.minutes
                    / games,
                    1,
                ),
                "PTS": round(
                    totals.points
                    / games,
                    1,
                ),
                "REB": round(
                    totals.rebounds
                    / games,
                    1,
                ),
                "AST": round(
                    totals.assists
                    / games,
                    1,
                ),
                "STL": round(
                    totals.steals
                    / games,
                    1,
                ),
                "BLK": round(
                    totals.blocks
                    / games,
                    1,
                ),
            }
        )

    rows.sort(
        key=lambda row: (
            -row["PTS"],
            -row["AST"],
            -row["REB"],
            row["Player"],
        )
    )
    return rows[: int(limit)]


def position_family(
    position: str,
) -> str:
    primary = str(position).split(
        "/",
        maxsplit=1,
    )[0].upper()

    if primary in {"PG", "SG"}:
        return "Guard"
    if primary in {"SF", "PF"}:
        return "Wing/Forward"
    if primary == "C":
        return "Center"
    return "Other"


def team_needs_rows(
    state: SimulationLeagueState,
    team: str,
) -> list[dict[str, Any]]:
    resolved_team = str(team).strip().upper()
    groups: dict[
        str,
        list[Any],
    ] = defaultdict(list)

    for player_id in state.teams[
        resolved_team
    ].roster_player_ids:
        player = state.players[
            player_id
        ]
        groups[
            position_family(
                player.position
            )
        ].append(player)

    rows: list[dict[str, Any]] = []

    for family in (
        "Guard",
        "Wing/Forward",
        "Center",
    ):
        players = groups.get(
            family,
            [],
        )

        if not players:
            average_overall = 0.0
            average_age = 0.0
            top_overall = 0.0
        else:
            average_overall = sum(
                player.overall_rating
                for player in players
            ) / len(players)
            ages = [
                float(player.age)
                for player in players
                if player.age is not None
            ]
            average_age = (
                sum(ages) / len(ages)
                if ages
                else 0.0
            )
            top_overall = max(
                player.overall_rating
                for player in players
            )

        need_score = (
            max(
                0.0,
                82.0 - average_overall,
            )
            + max(
                0,
                3 - len(players),
            )
            * 4.0
        )
        rows.append(
            {
                "Position Group": family,
                "Players": len(players),
                "Average OVR": round(
                    average_overall,
                    1,
                ),
                "Top OVR": round(
                    top_overall,
                    1,
                ),
                "Average Age": round(
                    average_age,
                    1,
                ),
                "Need Score": round(
                    need_score,
                    1,
                ),
            }
        )

    rows.sort(
        key=lambda row: (
            -row["Need Score"],
            row["Position Group"],
        )
    )
    return rows


def calendar_with_logos_html(
    month_calendar: TeamMonthCalendar,
) -> str:
    def esc(value: Any) -> str:
        return html.escape(
            str(value)
        )

    weekdays = "".join(
        (
            '<div class="fm-weekday">'
            f"{esc(label)}"
            "</div>"
        )
        for label in (
            month_calendar
            .weekday_labels
        )
    )
    cells: list[str] = []

    for week in month_calendar.weeks:
        for cell in week:
            classes = ["fm-day"]

            if not cell.in_month:
                classes.append("outside")
            if cell.is_current_day:
                classes.append("current")
            if cell.is_past_day:
                classes.append("past")

            body = (
                '<div class="fm-rest">'
                "REST"
                "</div>"
            )

            if not cell.in_month:
                body = (
                    '<div class="fm-rest">'
                    "OUTSIDE"
                    "</div>"
                )
            elif cell.game is not None:
                game = cell.game
                classes.append(
                    "home"
                    if game.location == "HOME"
                    else "away"
                )
                logo = team_logo_url(
                    game.opponent
                )
                location = (
                    "VS"
                    if game.location == "HOME"
                    else "AT"
                )
                outcome = (
                    (
                        '<div class="fm-result">'
                        f"{esc(game.result)} "
                        f"{game.team_score}-"
                        f"{game.opponent_score}"
                        "</div>"
                    )
                    if game.result
                    else (
                        '<div class="fm-upcoming">'
                        "UPCOMING"
                        "</div>"
                    )
                )
                body = (
                    '<div class="fm-game">'
                    '<img class="fm-game-logo" '
                    f'src="{esc(logo)}" '
                    f'alt="{esc(game.opponent)} logo">'
                    '<div class="fm-matchup">'
                    f"{location} "
                    f"{esc(game.opponent)}"
                    "</div>"
                    f"{outcome}"
                    "</div>"
                )

            cells.append(
                (
                    f'<div class="{" ".join(classes)}">'
                    '<div class="fm-date">'
                    f"{cell.calendar_date.day}"
                    "</div>"
                    f"{body}"
                    "</div>"
                )
            )

    return (
        '<div class="fm-calendar">'
        f"{weekdays}"
        f"{''.join(cells)}"
        "</div>"
    )


def run_self_test(
    *,
    seed: int = 20260808,
) -> dict[str, Any]:
    state = build_installed_state(
        seed=seed
    )
    source_fingerprint = (
        regular_season_state_fingerprint(
            state
        )
    )
    plan = build_rotation_plan(
        state,
        "CHI",
    )
    checks_rotation = (
        validate_rotation_plan(
            state,
            plan,
        )
    )
    modified_minutes = dict(
        plan.minutes_targets
    )
    first_id = plan.rotation_player_ids[
        0
    ]
    second_id = plan.rotation_player_ids[
        1
    ]
    modified_minutes[first_id] = round(
        modified_minutes[first_id] + 1.0,
        1,
    )
    modified_minutes[second_id] = round(
        modified_minutes[second_id] - 1.0,
        1,
    )
    modified_plan = RotationPlan(
        version=COMMAND_CENTER_VERSION,
        team="CHI",
        starter_ids=(
            plan.starter_ids
        ),
        rotation_player_ids=(
            plan.rotation_player_ids
        ),
        minutes_targets=(
            modified_minutes
        ),
        total_minutes=240.0,
    )
    updated_state = apply_rotation_plan(
        state,
        modified_plan,
    )
    snapshot = build_team_snapshot(
        state,
        "CHI",
    )
    pause_state, pause_result = (
        advance_franchise_scope(
            state,
            controlled_teams=("CHI",),
            policy=(
                FranchiseSimulationPolicy
                .STOP_EVERY_CONTROLLED_GAME
            ),
            scope=SimulationScope.NEXT_WEEK,
        )
    )
    auto_state, auto_result = (
        advance_franchise_scope(
            state,
            controlled_teams=("CHI",),
            policy=(
                FranchiseSimulationPolicy
                .AUTO_SAVED_ROTATIONS
            ),
            scope=SimulationScope.NEXT_DAY,
        )
    )
    invalid_rotation_blocked = False

    try:
        invalid = RotationPlan(
            version=(
                COMMAND_CENTER_VERSION
            ),
            team="CHI",
            starter_ids=(
                plan.starter_ids[:4]
            ),
            rotation_player_ids=(
                plan.rotation_player_ids
            ),
            minutes_targets=(
                plan.minutes_targets
            ),
            total_minutes=(
                plan.total_minutes
            ),
        )
        validate_rotation_plan(
            state,
            invalid,
        )
    except FranchiseCommandCenterError:
        invalid_rotation_blocked = True

    checks = {
        "command_center_version_is_current": (
            snapshot.version
            == COMMAND_CENTER_VERSION
        ),
        "all_30_team_logo_ids_are_present": (
            len(NBA_TEAM_IDS) == 30
        ),
        "all_team_logo_urls_use_nba_cdn": all(
            team_logo_url(team).startswith(
                "https://cdn.nba.com/logos/nba/"
            )
            for team in NBA_TEAM_IDS
        ),
        "default_rotation_plan_is_valid": all(
            checks_rotation.values()
        ),
        "rotation_plan_totals_240": (
            math.isclose(
                plan.total_minutes,
                240.0,
                abs_tol=0.1,
            )
        ),
        "rotation_apply_returns_replacement": (
            updated_state is not state
        ),
        "rotation_apply_does_not_mutate_source": (
            regular_season_state_fingerprint(
                state
            )
            == source_fingerprint
        ),
        "rotation_apply_persists_new_minutes": (
            updated_state.teams[
                "CHI"
            ].rotation.minutes_targets
            == modified_minutes
        ),
        "invalid_rotation_is_blocked": (
            invalid_rotation_blocked
        ),
        "snapshot_contains_next_game": (
            bool(snapshot.next_game_id)
        ),
        "snapshot_contains_ranking": (
            1 <= snapshot.league_rank <= 30
            and 1
            <= snapshot.conference_rank
            <= 15
        ),
        "snapshot_contains_canonical_alignment": (
            snapshot.conference == "East"
            and snapshot.division == "Central"
        ),
        "east_standings_have_15_teams": (
            len(
                standings_rows(
                    state,
                    conference="East",
                )
            )
            == 15
        ),
        "west_standings_have_15_teams": (
            len(
                standings_rows(
                    state,
                    conference="West",
                )
            )
            == 15
        ),
        "stop_policy_pauses": (
            pause_result.paused
            and bool(
                pause_result
                .pause_game_ids
            )
        ),
        "auto_policy_advances": (
            not auto_result.paused
            and auto_result
            .games_simulated
            > 0
        ),
        "policy_operations_do_not_mutate_source": (
            regular_season_state_fingerprint(
                state
            )
            == source_fingerprint
        ),
        "policy_result_states_are_valid": (
            bool(
                validate_simulation_league_state(
                    pause_state
                )
            )
            and bool(
                validate_simulation_league_state(
                    auto_state
                )
            )
        ),
        "standings_rows_cover_30_teams": (
            len(
                standings_rows(state)
            )
            == 30
        ),
        "team_needs_are_generated": (
            len(
                team_needs_rows(
                    state,
                    "CHI",
                )
            )
            >= 3
        ),
    }
    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]
    report = {
        "script": COMMAND_CENTER_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "snapshot": asdict(
                snapshot
            ),
            "rotation_players": len(
                plan.rotation_player_ids
            ),
            "pause_result": asdict(
                pause_result
            ),
            "auto_result": asdict(
                auto_result
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
            "Franchise command center "
            "self-test failed: "
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
            "\nFRANCHISE COMMAND CENTER "
            "V1 SELF-TEST PASSED"
        )
        return 0

    print(
        json.dumps(
            {
                "script": (
                    COMMAND_CENTER_VERSION
                ),
                "message": (
                    "Use --self-test to validate "
                    "franchise policies, rotations, "
                    "team snapshots, and logo assets."
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
