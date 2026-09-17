from __future__ import annotations

import copy
import json
import time


def _prepare_backlog_state(seed: int):
    from regular_season_simulation_controller_v1 import build_installed_state
    from single_game_simulator_v1 import simulate_scheduled_game

    state = build_installed_state(seed=seed)
    controlled = ("CHI",) if "CHI" in state.teams else (sorted(state.teams)[0],)
    controlled_set = set(controlled)
    controlled_games = sorted(
        [
            game
            for game in state.schedule.values()
            if controlled_set.intersection({game.home_team, game.away_team})
        ],
        key=lambda game: (int(game.day_index), game.game_id),
    )
    if len(controlled_games) < 6:
        raise RuntimeError("Regression requires at least six controlled-team games.")

    manual_games = controlled_games[:5]
    manual_scores = {}
    for game in manual_games:
        committed = simulate_scheduled_game(state, game.game_id, commit=True)
        manual_scores[game.game_id] = (
            committed.game.home_score,
            committed.game.away_score,
        )

    return state, controlled, controlled_games, manual_scores


def main() -> int:
    from franchise_game_day_league_calendar_sync_v1 import (
        SYNC_PERFORMANCE_VERSION,
        catch_up_cpu_schedule_v1,
        league_calendar_sync_status_v1,
    )
    from regular_season_simulation_controller_v1 import (
        regular_season_state_fingerprint,
    )
    from simulation_league_state_v1 import (
        GameStatus,
        validate_simulation_league_state,
    )

    state, controlled, controlled_games, manual_scores = _prepare_backlog_state(
        seed=20260917
    )

    before = league_calendar_sync_status_v1(state, controlled_teams=controlled)
    completed_before = len(state.completed_games)
    source_fingerprint = regular_season_state_fingerprint(state)

    started = time.perf_counter()
    advanced_safe, report_safe = catch_up_cpu_schedule_v1(
        state,
        controlled_teams=controlled,
    )
    safe_seconds = time.perf_counter() - started

    source_unchanged = (
        regular_season_state_fingerprint(state) == source_fingerprint
    )

    private_input = copy.deepcopy(state)
    private_identity = id(private_input)
    started = time.perf_counter()
    advanced_private, report_private = catch_up_cpu_schedule_v1(
        private_input,
        controlled_teams=controlled,
        private_transactional_state=True,
    )
    private_seconds = time.perf_counter() - started

    after = league_calendar_sync_status_v1(
        advanced_private,
        controlled_teams=controlled,
    )
    next_game_id = after["next_controlled_game_id"]
    next_day = after["next_controlled_day"]

    all_past_games_complete = True
    if next_day is not None:
        all_past_games_complete = all(
            game.status == GameStatus.COMPLETED
            for game in advanced_private.schedule.values()
            if int(game.day_index) < int(next_day)
        )

    manual_results_preserved = all(
        game_id in advanced_private.completed_games
        and (
            advanced_private.completed_games[game_id].home_score,
            advanced_private.completed_games[game_id].away_score,
        ) == score
        for game_id, score in manual_scores.items()
    )

    future_controlled_still_scheduled = all(
        game.game_id in manual_scores
        or advanced_private.schedule[game.game_id].status == GameStatus.SCHEDULED
        for game in controlled_games
    )

    standings_games = sum(
        standing.games_played
        for standing in advanced_private.standings.values()
    )

    safe_fp = regular_season_state_fingerprint(advanced_safe)
    private_fp = regular_season_state_fingerprint(advanced_private)

    checks = {
        "performance_version_is_v7": (
            SYNC_PERFORMANCE_VERSION
            == "franchise-game-day-league-calendar-sync-v1-perf-v7-2026-09-17"
        ),
        "serious_bug_reproduced_before_fix": (
            before["cpu_games_before_next_controlled"] > 0
        ),
        "safe_path_catches_up_cpu_backlog": (
            report_safe["games_simulated"] > 0
        ),
        "private_fast_path_catches_up_cpu_backlog": (
            report_private["games_simulated"] > 0
        ),
        "safe_default_does_not_mutate_source": source_unchanged,
        "private_fast_path_reuses_same_object": (
            id(advanced_private) == private_identity
        ),
        "safe_and_private_paths_are_exactly_equivalent": (
            safe_fp == private_fp
        ),
        "same_number_of_cpu_games_simulated": (
            report_safe["games_simulated"]
            == report_private["games_simulated"]
        ),
        "no_cpu_games_remain_before_next_controlled": (
            after["cpu_games_before_next_controlled"] == 0
        ),
        "every_game_before_next_controlled_day_is_complete": (
            all_past_games_complete
        ),
        "manual_controlled_results_are_preserved": (
            manual_results_preserved
        ),
        "next_controlled_game_remains_scheduled": (
            bool(next_game_id)
            and advanced_private.schedule[next_game_id].status
            == GameStatus.SCHEDULED
        ),
        "future_controlled_games_are_not_auto_simulated": (
            future_controlled_still_scheduled
        ),
        "completed_count_increases_by_reported_amount": (
            len(advanced_private.completed_games)
            == completed_before + report_private["games_simulated"]
        ),
        "standings_reconcile_with_completed_games": (
            standings_games == 2 * len(advanced_private.completed_games)
        ),
        "advanced_state_is_valid": bool(
            validate_simulation_league_state(advanced_private)
        ),
    }

    failed = [name for name, passed in checks.items() if not passed]
    print(json.dumps({
        "checks": checks,
        "failed_checks": failed,
        "passed": not failed,
        "summary": {
            "controlled_team": controlled[0],
            "cpu_backlog_before": before["cpu_games_before_next_controlled"],
            "cpu_games_simulated": report_private["games_simulated"],
            "safe_path_seconds": round(safe_seconds, 3),
            "private_fast_path_seconds": round(private_seconds, 3),
            "private_report_seconds": report_private.get("elapsed_seconds"),
            "private_games_per_second": report_private.get("games_per_second"),
            "next_controlled_game": next_game_id,
            "next_controlled_day": next_day,
        },
    }, indent=2))

    if failed:
        raise SystemExit(1)
    print("FRANCHISE GAME-DAY PERFORMANCE V7 REGRESSION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
