from __future__ import annotations

import copy
import time
from typing import Any, Callable, Iterable

SYNC_VERSION = "franchise-game-day-league-calendar-sync-v1-2026-09-17"
SYNC_PERFORMANCE_VERSION = (
    "franchise-game-day-league-calendar-sync-v1-perf-v7-2026-09-17"
)


class LeagueCalendarSyncError(RuntimeError):
    """Raised when Franchise Game Day cannot synchronize the league calendar."""


def _clean_team(value: Any) -> str:
    return str(value or "").strip().upper()


def _status_value(game: Any) -> str:
    value = getattr(game, "status", "")
    return str(getattr(value, "value", value)).strip().lower()


def _scheduled_games(state: Any) -> list[Any]:
    return sorted(
        [
            game
            for game in (getattr(state, "schedule", {}) or {}).values()
            if _status_value(game) == "scheduled"
        ],
        key=lambda game: (
            int(getattr(game, "day_index", 0)),
            str(getattr(game, "game_id", "")),
        ),
    )


def _controlled_set(
    state: Any,
    controlled_teams: Iterable[str],
) -> set[str]:
    available = {
        str(key).strip().upper()
        for key in (getattr(state, "teams", {}) or {}).keys()
    }
    return {
        _clean_team(team)
        for team in controlled_teams
        if _clean_team(team) and _clean_team(team) in available
    }


def _is_controlled_game(
    game: Any,
    controlled: set[str],
) -> bool:
    return bool(
        controlled.intersection(
            {
                _clean_team(getattr(game, "home_team", "")),
                _clean_team(getattr(game, "away_team", "")),
            }
        )
    )


def league_calendar_sync_status_v1(
    state: Any,
    *,
    controlled_teams: Iterable[str],
) -> dict[str, Any]:
    controlled = _controlled_set(state, controlled_teams)
    scheduled = _scheduled_games(state)
    current_day = int(getattr(state, "current_day_index", 0) or 0)

    controlled_games = [
        game
        for game in scheduled
        if _is_controlled_game(game, controlled)
    ]
    next_controlled = controlled_games[0] if controlled_games else None

    cpu_games = [
        game
        for game in scheduled
        if not _is_controlled_game(game, controlled)
    ]
    overdue_cpu = [
        game
        for game in cpu_games
        if int(getattr(game, "day_index", 0)) <= current_day
    ]

    if next_controlled is not None:
        next_day = int(getattr(next_controlled, "day_index", 0))
        cpu_before_next = [
            game
            for game in cpu_games
            if int(getattr(game, "day_index", 0)) < next_day
        ]
    else:
        next_day = None
        cpu_before_next = list(cpu_games)

    return {
        "version": SYNC_VERSION,
        "performance_version": SYNC_PERFORMANCE_VERSION,
        "current_day": current_day,
        "controlled_teams": tuple(sorted(controlled)),
        "scheduled_games": len(scheduled),
        "next_controlled_game_id": (
            str(getattr(next_controlled, "game_id", ""))
            if next_controlled is not None
            else ""
        ),
        "next_controlled_day": next_day,
        "overdue_cpu_games": len(overdue_cpu),
        "cpu_games_before_next_controlled": len(cpu_before_next),
        "oldest_pending_cpu_day": min(
            (int(getattr(game, "day_index", 0)) for game in cpu_games),
            default=None,
        ),
        "ready_for_next_controlled_game": len(cpu_before_next) == 0,
    }


def _cpu_games_to_catch_up(
    state: Any,
    *,
    controlled: set[str],
    next_controlled_day: int | None,
) -> list[Any]:
    return [
        game
        for game in _scheduled_games(state)
        if not _is_controlled_game(game, controlled)
        and (
            next_controlled_day is None
            or int(getattr(game, "day_index", 0)) < int(next_controlled_day)
        )
    ]


def catch_up_cpu_schedule_v1(
    state: Any,
    *,
    controlled_teams: Iterable[str],
    private_transactional_state: bool = False,
    _simulate_game: Callable[..., Any] | None = None,
    _state_validator: Callable[[Any], Any] | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Simulate CPU games chronologically up to the next user decision.

    Game Day may pass private_transactional_state=True because
    commit_game_transactionally() already produced a private deepcopy. This
    removes a second full-franchise copy. Default callers remain source-safe.
    """
    started = time.perf_counter()
    before = league_calendar_sync_status_v1(
        state,
        controlled_teams=controlled_teams,
    )

    if (
        before["scheduled_games"] == 0
        or before["cpu_games_before_next_controlled"] == 0
    ):
        return state, {
            "version": SYNC_VERSION,
            "performance_version": SYNC_PERFORMANCE_VERSION,
            "changed": False,
            "games_simulated": 0,
            "before": before,
            "after": before,
            "selected_game_id": before["next_controlled_game_id"],
            "private_transactional_state": bool(private_transactional_state),
            "elapsed_seconds": round(time.perf_counter() - started, 4),
            "message": "League calendar already synchronized.",
        }

    controlled = set(before["controlled_teams"])
    working = (
        state
        if private_transactional_state
        else copy.deepcopy(state)
    )

    if _simulate_game is None:
        try:
            from single_game_simulator_v1 import simulate_scheduled_game
        except Exception as exc:
            raise LeagueCalendarSyncError(
                f"Could not load the single-game simulator: {exc}"
            ) from exc
        simulate_game = simulate_scheduled_game
    else:
        simulate_game = _simulate_game

    if _state_validator is None:
        try:
            from simulation_league_state_v1 import (
                validate_simulation_league_state,
            )
        except Exception as exc:
            raise LeagueCalendarSyncError(
                f"Could not load league-state validation: {exc}"
            ) from exc
        state_validator = validate_simulation_league_state
    else:
        state_validator = _state_validator

    target_games = _cpu_games_to_catch_up(
        working,
        controlled=controlled,
        next_controlled_day=before["next_controlled_day"],
    )

    simulated_count = 0
    try:
        for game in target_games:
            simulate_game(
                working,
                str(getattr(game, "game_id", "")),
                seed=None,
                commit=True,
                _private_working_state=True,
                _defer_global_state_validation=True,
            )
            simulated_count += 1

        # One authoritative validation after the complete CPU batch.
        state_validator(working)
    except Exception as exc:
        raise LeagueCalendarSyncError(
            f"League calendar catch-up failed: {exc}"
        ) from exc

    after = league_calendar_sync_status_v1(
        working,
        controlled_teams=controlled_teams,
    )
    if after["cpu_games_before_next_controlled"] != 0:
        raise LeagueCalendarSyncError(
            "League catch-up finished with computer-managed games still "
            "scheduled before the next controlled matchup."
        )

    elapsed = time.perf_counter() - started
    return working, {
        "version": SYNC_VERSION,
        "performance_version": SYNC_PERFORMANCE_VERSION,
        "changed": bool(simulated_count),
        "games_simulated": simulated_count,
        "before": before,
        "after": after,
        "selected_game_id": after["next_controlled_game_id"],
        "private_transactional_state": bool(private_transactional_state),
        "elapsed_seconds": round(elapsed, 4),
        "games_per_second": (
            round(simulated_count / elapsed, 3)
            if simulated_count and elapsed > 0
            else None
        ),
        "message": (
            f"Synchronized {simulated_count} CPU game(s) before the next "
            "controlled matchup."
        ),
    }
