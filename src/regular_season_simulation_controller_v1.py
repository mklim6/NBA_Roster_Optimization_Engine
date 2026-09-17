from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import (  # noqa: E402
    load_runtime_data,
)
from mutable_league_state_v1 import (  # noqa: E402
    create_league_state,
)
from regular_season_schedule_v1 import (  # noqa: E402
    LEAGUE_GAME_COUNT,
    generate_regular_season_schedule,
    install_regular_season_schedule,
)
from simulation_league_state_v1 import (  # noqa: E402
    GameStatus,
    LeaguePhase,
    SimulationLeagueState,
    SimulationLeagueStateError,
    create_simulation_league_state,
    validate_simulation_league_state,
)
from simulation_injury_fatigue_v1 import (  # noqa: E402
    INJURY_FATIGUE_VERSION,
    injury_fatigue_state_payload,
)
from single_game_simulator_v1 import (  # noqa: E402
    SingleGameSimulationError,
    simulate_scheduled_game,
)
from state_runtime_adapter_v1 import (  # noqa: E402
    build_state_runtime,
)


CONTROLLER_VERSION = (
    "regular-season-simulation-controller-v1-2026-08-08"
)
SELF_TEST_REPORT = (
    OUTPUTS
    / "regular_season_simulation_controller_v1_self_test.json"
)

ProgressCallback = Callable[
    [int, int, str, int],
    None,
]


class RegularSeasonSimulationControllerError(
    RuntimeError
):
    """Raised when a regular-season simulation request is invalid."""


class SimulationScope(str, Enum):
    NEXT_GAME = "next_game"
    NEXT_DAY = "next_day"
    NEXT_WEEK = "next_week"
    THROUGH_DAY = "through_day"
    REMAINDER = "remainder"


@dataclass(frozen=True)
class RegularSeasonSimulationPlan:
    controller_version: str
    scope: SimulationScope
    season_label: str
    source_fingerprint: str
    source_current_day: int
    source_completed_games: int
    start_day: int
    target_day: int
    game_ids: tuple[str, ...]
    day_indices: tuple[int, ...]
    planned_games: int
    planned_days: int


@dataclass(frozen=True)
class SimulatedRegularSeasonGame:
    game_id: str
    day_index: int
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    winner: str
    overtime_periods: int
    seed: int


@dataclass(frozen=True)
class RegularSeasonSimulationResult:
    controller_version: str
    scope: SimulationScope
    season_label: str
    source_current_day: int
    final_current_day: int
    target_day: int
    games_simulated: int
    days_simulated: int
    completed_games_before: int
    completed_games_after: int
    remaining_games_after: int
    regular_season_complete: bool
    first_game_id: str
    last_game_id: str
    game_results: tuple[
        SimulatedRegularSeasonGame,
        ...,
    ]
    source_fingerprint: str
    final_fingerprint: str


def normalize_scope(
    scope: SimulationScope | str,
) -> SimulationScope:
    try:
        return SimulationScope(scope)
    except ValueError as exc:
        raise (
            RegularSeasonSimulationControllerError(
                f"Unknown simulation scope: {scope!r}."
            )
        ) from exc


def scheduled_unplayed_games(
    state: SimulationLeagueState,
) -> tuple[Any, ...]:
    return tuple(
        sorted(
            (
                game
                for game in state.schedule.values()
                if game.status
                == GameStatus.SCHEDULED
            ),
            key=lambda game: (
                int(game.day_index),
                game.game_id,
            ),
        )
    )


def completed_regular_season_games(
    state: SimulationLeagueState,
) -> int:
    return sum(
        game.status == GameStatus.COMPLETED
        for game in state.schedule.values()
    )


def regular_season_progress(
    state: SimulationLeagueState,
) -> dict[str, Any]:
    validate_simulation_league_state(state)
    unplayed = scheduled_unplayed_games(state)
    completed = completed_regular_season_games(
        state
    )
    total = len(state.schedule)
    next_game = (
        unplayed[0]
        if unplayed
        else None
    )

    return {
        "season_label": (
            state.settings.season_label
        ),
        "phase": state.phase.value,
        "current_day_index": (
            state.current_day_index
        ),
        "scheduled_games": total,
        "completed_games": completed,
        "remaining_games": len(unplayed),
        "completion_percentage": round(
            (
                100.0 * completed / total
                if total
                else 0.0
            ),
            3,
        ),
        "next_game_id": (
            next_game.game_id
            if next_game is not None
            else ""
        ),
        "next_game_day": (
            int(next_game.day_index)
            if next_game is not None
            else None
        ),
        "next_home_team": (
            next_game.home_team
            if next_game is not None
            else ""
        ),
        "next_away_team": (
            next_game.away_team
            if next_game is not None
            else ""
        ),
        "regular_season_complete": bool(
            total
            and completed == total
        ),
    }


def regular_season_state_payload(
    state: SimulationLeagueState,
) -> dict[str, Any]:
    return {
        "state_version": state.state_version,
        "season_label": (
            state.settings.season_label
        ),
        "phase": state.phase.value,
        "current_day_index": (
            state.current_day_index
        ),
        "source_league_state_revision": (
            state.source_league_state_revision
        ),
        "source_transaction_count": (
            state.source_transaction_count
        ),
        "settings": asdict(state.settings),
        "players": {
            player_id: {
                "team_abbreviation": (
                    player.team_abbreviation
                ),
                "roster_status": (
                    player.roster_status
                ),
                "overall_rating": round(
                    float(
                        player.overall_rating
                    ),
                    6,
                ),
                "position": player.position,
                "stat_factors": dict(
                    sorted(
                        getattr(
                            player,
                            "stat_factors",
                            {},
                        ).items()
                    )
                ),
            }
            for player_id, player
            in sorted(state.players.items())
        },
        "teams": {
            team: {
                "roster_player_ids": list(
                    team_state.roster_player_ids
                ),
                "starter_ids": list(
                    team_state.rotation.starter_ids
                ),
                "rotation_player_ids": list(
                    team_state.rotation
                    .rotation_player_ids
                ),
                "minutes_targets": dict(
                    sorted(
                        team_state.rotation
                        .minutes_targets.items()
                    )
                ),
                "active_player_ids": list(
                    team_state.active_player_ids
                ),
                "inactive_player_ids": list(
                    team_state.inactive_player_ids
                ),
            }
            for team, team_state
            in sorted(state.teams.items())
        },
        "injuries": {
            player_id: asdict(injury)
            for player_id, injury
            in sorted(state.injuries.items())
        },
        "injury_fatigue": (
            injury_fatigue_state_payload(
                state
            )
        ),
        "schedule": {
            game_id: {
                "day_index": int(
                    game.day_index
                ),
                "home_team": game.home_team,
                "away_team": game.away_team,
                "status": game.status.value,
            }
            for game_id, game
            in sorted(state.schedule.items())
        },
        "completed_games": {
            game_id: {
                "home_team": game.home_team,
                "away_team": game.away_team,
                "home_score": game.home_score,
                "away_score": game.away_score,
                "overtime_periods": (
                    game.overtime_periods
                ),
            }
            for game_id, game
            in sorted(
                state.completed_games.items()
            )
        },
        "standings": {
            team: asdict(standing)
            for team, standing
            in sorted(state.standings.items())
        },
        "player_season_totals": {
            player_id: asdict(totals)
            for player_id, totals
            in sorted(
                state.player_season_totals.items()
            )
        },
    }


def regular_season_state_fingerprint(
    state: SimulationLeagueState,
) -> str:
    payload = regular_season_state_payload(
        state
    )
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def ensure_regular_season_ready(
    state: SimulationLeagueState,
) -> None:
    validate_simulation_league_state(state)

    if not state.schedule:
        raise (
            RegularSeasonSimulationControllerError(
                "No regular-season schedule is installed."
            )
        )

    if len(state.schedule) != LEAGUE_GAME_COUNT:
        raise (
            RegularSeasonSimulationControllerError(
                "The installed regular-season schedule "
                f"contains {len(state.schedule)} games, "
                f"not {LEAGUE_GAME_COUNT}."
            )
        )

    if state.phase != LeaguePhase.REGULAR_SEASON:
        raise (
            RegularSeasonSimulationControllerError(
                "Regular-season games can only be "
                "simulated during the regular season."
            )
        )


def select_games_for_scope(
    state: SimulationLeagueState,
    *,
    scope: SimulationScope | str,
    target_day: int | None = None,
) -> tuple[Any, ...]:
    ensure_regular_season_ready(state)
    resolved_scope = normalize_scope(scope)
    unplayed = scheduled_unplayed_games(state)

    if not unplayed:
        raise (
            RegularSeasonSimulationControllerError(
                "The regular season is already complete."
            )
        )

    start_day = int(
        unplayed[0].day_index
    )

    if (
        resolved_scope
        == SimulationScope.NEXT_GAME
    ):
        return (unplayed[0],)

    if (
        resolved_scope
        == SimulationScope.NEXT_DAY
    ):
        return tuple(
            game
            for game in unplayed
            if int(game.day_index)
            == start_day
        )

    if (
        resolved_scope
        == SimulationScope.NEXT_WEEK
    ):
        resolved_target_day = (
            start_day + 6
        )
        return tuple(
            game
            for game in unplayed
            if int(game.day_index)
            <= resolved_target_day
        )

    if (
        resolved_scope
        == SimulationScope.THROUGH_DAY
    ):
        if target_day is None:
            raise (
                RegularSeasonSimulationControllerError(
                    "A target day is required for "
                    "through-day simulation."
                )
            )

        resolved_target_day = int(
            target_day
        )

        if resolved_target_day < start_day:
            raise (
                RegularSeasonSimulationControllerError(
                    "The target day cannot be earlier "
                    "than the next unplayed game day."
                )
            )

        selected = tuple(
            game
            for game in unplayed
            if int(game.day_index)
            <= resolved_target_day
        )

        if not selected:
            raise (
                RegularSeasonSimulationControllerError(
                    "No unplayed games fall within "
                    "the requested day range."
                )
            )

        return selected

    if (
        resolved_scope
        == SimulationScope.REMAINDER
    ):
        return unplayed

    raise (
        RegularSeasonSimulationControllerError(
            f"Unsupported simulation scope: "
            f"{resolved_scope.value}."
        )
    )


def build_regular_season_simulation_plan(
    state: SimulationLeagueState,
    *,
    scope: SimulationScope | str,
    target_day: int | None = None,
) -> RegularSeasonSimulationPlan:
    before = regular_season_state_fingerprint(
        state
    )
    resolved_scope = normalize_scope(scope)
    selected = select_games_for_scope(
        state,
        scope=resolved_scope,
        target_day=target_day,
    )
    days = tuple(
        sorted(
            {
                int(game.day_index)
                for game in selected
            }
        )
    )
    after = regular_season_state_fingerprint(
        state
    )

    if after != before:
        raise (
            RegularSeasonSimulationControllerError(
                "Building a simulation plan "
                "unexpectedly mutated the live state."
            )
        )

    return RegularSeasonSimulationPlan(
        controller_version=(
            CONTROLLER_VERSION
        ),
        scope=resolved_scope,
        season_label=(
            state.settings.season_label
        ),
        source_fingerprint=before,
        source_current_day=(
            state.current_day_index
        ),
        source_completed_games=len(
            state.completed_games
        ),
        start_day=days[0],
        target_day=days[-1],
        game_ids=tuple(
            game.game_id
            for game in selected
        ),
        day_indices=days,
        planned_games=len(selected),
        planned_days=len(days),
    )


def validate_plan(
    plan: RegularSeasonSimulationPlan,
) -> None:
    if not isinstance(
        plan,
        RegularSeasonSimulationPlan,
    ):
        raise (
            RegularSeasonSimulationControllerError(
                "The regular-season simulation plan "
                "has an invalid type."
            )
        )

    if (
        plan.controller_version
        != CONTROLLER_VERSION
    ):
        raise (
            RegularSeasonSimulationControllerError(
                "The simulation plan was created by "
                "a different controller version."
            )
        )

    if not plan.game_ids:
        raise (
            RegularSeasonSimulationControllerError(
                "A simulation plan must contain "
                "at least one game."
            )
        )

    if (
        plan.planned_games
        != len(plan.game_ids)
    ):
        raise (
            RegularSeasonSimulationControllerError(
                "The simulation plan game count "
                "does not reconcile."
            )
        )

    if (
        plan.planned_days
        != len(plan.day_indices)
    ):
        raise (
            RegularSeasonSimulationControllerError(
                "The simulation plan day count "
                "does not reconcile."
            )
        )


def plan_matches_state(
    state: SimulationLeagueState,
    plan: RegularSeasonSimulationPlan,
) -> bool:
    try:
        validate_plan(plan)
        ensure_regular_season_ready(state)
    except (
        RegularSeasonSimulationControllerError,
        SimulationLeagueStateError,
    ):
        return False

    if (
        plan.season_label
        != state.settings.season_label
        or plan.source_fingerprint
        != regular_season_state_fingerprint(
            state
        )
    ):
        return False

    for game_id in plan.game_ids:
        game = state.schedule.get(game_id)

        if (
            game is None
            or game.status
            != GameStatus.SCHEDULED
        ):
            return False

    ordered = tuple(
        game.game_id
        for game in sorted(
            (
                state.schedule[game_id]
                for game_id in plan.game_ids
            ),
            key=lambda game: (
                int(game.day_index),
                game.game_id,
            ),
        )
    )
    return ordered == plan.game_ids


def _game_result_record(
    state: SimulationLeagueState,
    game_id: str,
    seed: int,
) -> SimulatedRegularSeasonGame:
    completed = state.completed_games[
        game_id
    ]
    scheduled = state.schedule[game_id]
    winner = (
        completed.home_team
        if completed.home_score
        > completed.away_score
        else completed.away_team
    )

    return SimulatedRegularSeasonGame(
        game_id=game_id,
        day_index=int(
            scheduled.day_index
        ),
        home_team=completed.home_team,
        away_team=completed.away_team,
        home_score=completed.home_score,
        away_score=completed.away_score,
        winner=winner,
        overtime_periods=(
            completed.overtime_periods
        ),
        seed=seed,
    )


def commit_regular_season_simulation_plan(
    state: SimulationLeagueState,
    plan: RegularSeasonSimulationPlan,
    *,
    progress_callback: (
        ProgressCallback | None
    ) = None,
) -> tuple[
    SimulationLeagueState,
    RegularSeasonSimulationResult,
]:
    validate_plan(plan)

    if not plan_matches_state(
        state,
        plan,
    ):
        raise (
            RegularSeasonSimulationControllerError(
                "The live regular season changed "
                "after this plan was created. "
                "Build a new simulation plan."
            )
        )

    source_fingerprint = (
        regular_season_state_fingerprint(
            state
        )
    )
    trial_state = copy.deepcopy(state)
    results: list[
        SimulatedRegularSeasonGame
    ] = []
    total = len(plan.game_ids)

    try:
        for index, game_id in enumerate(
            plan.game_ids,
            start=1,
        ):
            simulated = simulate_scheduled_game(
                trial_state,
                game_id,
                seed=None,
                commit=True,
                # FRANCHISE_GAME_DAY_PERFORMANCE_V7:
                # this transaction validates the complete league once after
                # the full batch, so per-game global validation is redundant.
                _defer_global_state_validation=True,
            )
            results.append(
                _game_result_record(
                    trial_state,
                    game_id,
                    simulated.metadata.seed,
                )
            )

            if progress_callback is not None:
                progress_callback(
                    index,
                    total,
                    game_id,
                    int(
                        trial_state.schedule[
                            game_id
                        ].day_index
                    ),
                )
    except (
        SingleGameSimulationError,
        SimulationLeagueStateError,
        ValueError,
        KeyError,
    ) as exc:
        raise (
            RegularSeasonSimulationControllerError(
                "The transactional regular-season "
                f"simulation failed: {exc}"
            )
        ) from exc

    validate_simulation_league_state(
        trial_state
    )

    if (
        regular_season_state_fingerprint(
            state
        )
        != source_fingerprint
    ):
        raise (
            RegularSeasonSimulationControllerError(
                "The transactional simulation mutated "
                "its source state."
            )
        )

    remaining = len(
        scheduled_unplayed_games(
            trial_state
        )
    )
    final_fingerprint = (
        regular_season_state_fingerprint(
            trial_state
        )
    )
    result = RegularSeasonSimulationResult(
        controller_version=(
            CONTROLLER_VERSION
        ),
        scope=plan.scope,
        season_label=plan.season_label,
        source_current_day=(
            plan.source_current_day
        ),
        final_current_day=(
            trial_state.current_day_index
        ),
        target_day=plan.target_day,
        games_simulated=len(results),
        days_simulated=plan.planned_days,
        completed_games_before=(
            plan.source_completed_games
        ),
        completed_games_after=len(
            trial_state.completed_games
        ),
        remaining_games_after=remaining,
        regular_season_complete=(
            remaining == 0
        ),
        first_game_id=(
            results[0].game_id
        ),
        last_game_id=(
            results[-1].game_id
        ),
        game_results=tuple(results),
        source_fingerprint=(
            source_fingerprint
        ),
        final_fingerprint=(
            final_fingerprint
        ),
    )

    return trial_state, result


def simulate_regular_season_scope(
    state: SimulationLeagueState,
    *,
    scope: SimulationScope | str,
    target_day: int | None = None,
    progress_callback: (
        ProgressCallback | None
    ) = None,
) -> tuple[
    SimulationLeagueState,
    RegularSeasonSimulationResult,
]:
    plan = build_regular_season_simulation_plan(
        state,
        scope=scope,
        target_day=target_day,
    )
    return commit_regular_season_simulation_plan(
        state,
        plan,
        progress_callback=progress_callback,
    )


def completed_score_signature(
    state: SimulationLeagueState,
) -> tuple[
    tuple[str, int, int, int],
    ...,
]:
    return tuple(
        (
            game_id,
            game.home_score,
            game.away_score,
            game.overtime_periods,
        )
        for game_id, game
        in sorted(state.completed_games.items())
    )


def standings_signature(
    state: SimulationLeagueState,
) -> tuple[
    tuple[str, int, int, int, int],
    ...,
]:
    return tuple(
        (
            team,
            standing.games_played,
            standing.wins,
            standing.losses,
            standing.points_for
            - standing.points_against,
        )
        for team, standing
        in sorted(state.standings.items())
    )


def build_installed_state(
    *,
    seed: int,
) -> SimulationLeagueState:
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
    schedule = generate_regular_season_schedule(
        state,
        seed=seed,
    )
    install_regular_season_schedule(
        state,
        schedule,
    )
    return state


def run_self_test(
    *,
    seed: int = 20260808,
) -> dict[str, Any]:
    base_state = build_installed_state(
        seed=seed
    )
    source_fingerprint = (
        regular_season_state_fingerprint(
            base_state
        )
    )

    next_game_plan = (
        build_regular_season_simulation_plan(
            base_state,
            scope=SimulationScope.NEXT_GAME,
        )
    )
    next_game_state, next_game_result = (
        commit_regular_season_simulation_plan(
            base_state,
            next_game_plan,
        )
    )

    stale_plan_blocked = False
    try:
        commit_regular_season_simulation_plan(
            next_game_state,
            next_game_plan,
        )
    except (
        RegularSeasonSimulationControllerError
    ):
        stale_plan_blocked = True

    next_day_state, next_day_result = (
        simulate_regular_season_scope(
            base_state,
            scope=SimulationScope.NEXT_DAY,
        )
    )
    next_week_state, next_week_result = (
        simulate_regular_season_scope(
            base_state,
            scope=SimulationScope.NEXT_WEEK,
        )
    )

    first_unplayed_day = (
        scheduled_unplayed_games(
            base_state
        )[0].day_index
    )
    through_state, through_result = (
        simulate_regular_season_scope(
            base_state,
            scope=SimulationScope.THROUGH_DAY,
            target_day=(
                int(first_unplayed_day) + 13
            ),
        )
    )

    checks = {
        "controller_version_is_current": (
            next_game_result
            .controller_version
            == CONTROLLER_VERSION
        ),
        "plan_build_does_not_mutate_state": (
            regular_season_state_fingerprint(
                base_state
            )
            == source_fingerprint
        ),
        "next_game_plan_contains_one_game": (
            next_game_plan.planned_games
            == 1
        ),
        "next_game_commit_returns_replacement": (
            next_game_state
            is not base_state
        ),
        "next_game_commit_does_not_mutate_source": (
            regular_season_state_fingerprint(
                base_state
            )
            == source_fingerprint
        ),
        "next_game_commit_records_one_game": (
            next_game_result.games_simulated
            == 1
            and len(
                next_game_state.completed_games
            )
            == 1
        ),
        "stale_plan_cannot_be_reused": (
            stale_plan_blocked
        ),
        "next_day_simulates_one_calendar_day": (
            next_day_result.days_simulated
            == 1
            and next_day_result
            .final_current_day
            == next_day_result.target_day
        ),
        "next_day_completes_all_games_on_day": all(
            game.status
            == GameStatus.COMPLETED
            for game
            in next_day_state.schedule.values()
            if game.day_index
            == next_day_result.target_day
        ),
        "next_week_uses_seven_day_window": (
            next_week_result.target_day
            - next_week_result
            .game_results[0].day_index
            <= 6
        ),
        "through_day_respects_target": (
            through_result.final_current_day
            <= through_result.target_day
            and all(
                game.status
                == GameStatus.COMPLETED
                for game
                in through_state.schedule.values()
                if game.day_index
                <= through_result.target_day
            )
        ),
        "all_partial_states_remain_valid": all(
            bool(
                validate_simulation_league_state(
                    state
                )
            )
            for state in (
                next_game_state,
                next_day_state,
                next_week_state,
                through_state,
            )
        ),
    }
    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]
    report = {
        "script": CONTROLLER_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "season_label": (
                base_state.settings
                .season_label
            ),
            "schedule_games": len(
                base_state.schedule
            ),
            "next_game": asdict(
                next_game_result
            ),
            "next_day_games": (
                next_day_result
                .games_simulated
            ),
            "next_week_games": (
                next_week_result
                .games_simulated
            ),
            "through_day_games": (
                through_result
                .games_simulated
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
            "Regular-season simulation controller "
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
            "\nREGULAR SEASON SIMULATION "
            "CONTROLLER V1 SELF-TEST PASSED"
        )
        return 0

    print(
        json.dumps(
            {
                "script": (
                    CONTROLLER_VERSION
                ),
                "message": (
                    "Use --self-test to validate "
                    "transactional season simulation "
                    "scopes."
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
