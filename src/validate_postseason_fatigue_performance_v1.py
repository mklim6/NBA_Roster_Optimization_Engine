from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

import sys
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_command_center_v1 import FranchiseSimulationPolicy
from regular_season_simulation_controller_v1 import (
    SimulationScope,
    build_installed_state,
    simulate_regular_season_scope,
)
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint
from simulation_league_state_v1 import LeaguePhase
from simulation_injury_fatigue_v1 import (
    ensure_injury_fatigue_state,
    player_health_report_rows,
)
from simulation_postseason_v1 import (
    POSTSEASON_EXECUTION_VERSION,
    PostseasonSimulationScope,
    advance_postseason,
    get_postseason_state,
    initialize_postseason,
)
from single_game_simulator_v1 import simulate_scheduled_game

VALIDATOR_VERSION = "postseason-fatigue-performance-validator-v1.1.1-2026-08-10"
REPORT_PATH = OUTPUTS / "postseason_fatigue_performance_validation_v1.json"


def _state_for_validation() -> Any:
    checkpoint = load_franchise_checkpoint()
    if checkpoint is not None:
        state = checkpoint.simulation_state
        postseason = get_postseason_state(state, required=False)
        has_unplayed_regular_games = any(
            getattr(game.status, "value", game.status) == "scheduled"
            for game in state.schedule.values()
        )
        if (
            postseason is None
            and state.phase == LeaguePhase.REGULAR_SEASON
            and has_unplayed_regular_games
        ):
            return state

    # Full project validation must also work without a live save, with a
    # completed regular-season checkpoint that has not initialized the
    # postseason yet, or after the user's current postseason has finished.
    # Build a deterministic midseason state so fatigue is populated and the
    # same-day ordering check still has future scheduled games to compare.
    state = build_installed_state(seed=20260809)
    state, _ = simulate_regular_season_scope(
        state,
        scope=SimulationScope.THROUGH_DAY,
        target_day=57,
    )
    return state


def _profile_payload(state: Any) -> dict[str, tuple[float, int, int, tuple[int, ...], tuple[float, ...]]]:
    profiles = ensure_injury_fatigue_state(state)
    return {
        player_id: (
            round(float(profile.fatigue or 0.0), 4),
            int(profile.last_game_day or 0),
            int(profile.last_recovery_day or 0),
            tuple(profile.recent_game_days or ()),
            tuple(float(value) for value in (profile.recent_minutes or ())),
        )
        for player_id, profile in profiles.items()
    }


def _same_day_order_check(state: Any) -> dict[str, Any]:
    next_day = min(
        int(game.day_index)
        for game in state.schedule.values()
        if getattr(game.status, "value", game.status) == "scheduled"
    )
    games = sorted(
        [
            game
            for game in state.schedule.values()
            if int(game.day_index) == next_day
            and getattr(game.status, "value", game.status) == "scheduled"
        ],
        key=lambda game: game.game_id,
    )
    if len(games) < 2:
        return {"tested": False, "passed": True, "day": next_day}

    forward = copy.deepcopy(state)
    reverse = copy.deepcopy(state)
    for game in games[:2]:
        simulate_scheduled_game(forward, game.game_id, seed=2026080901, commit=True)
    for game in reversed(games[:2]):
        simulate_scheduled_game(reverse, game.game_id, seed=2026080901, commit=True)

    forward_payload = _profile_payload(forward)
    reverse_payload = _profile_payload(reverse)
    return {
        "tested": True,
        "passed": forward_payload == reverse_payload,
        "day": next_day,
        "game_ids": [game.game_id for game in games[:2]],
    }


def run_validation(max_seconds: float = 15.0) -> dict[str, Any]:
    source = _state_for_validation()
    profiles = ensure_injury_fatigue_state(source)
    nonzero_teams = []
    fatigue_display_checks = []
    for team in sorted(source.teams):
        rows = player_health_report_rows(source, team)
        current_max = max((float(row["current_fatigue"]) for row in rows), default=0.0)
        projected_max = max((float(row["projected_fatigue"]) for row in rows), default=0.0)
        if current_max > 0.0:
            nonzero_teams.append(team)
        fatigue_display_checks.append(
            all(
                float(row["projected_fatigue"])
                <= float(row["current_fatigue"]) + 1e-9
                <= float(row["stored_fatigue"]) + 1e-9
                for row in rows
            )
        )

    same_day = _same_day_order_check(source)
    transaction_source = copy.deepcopy(source)
    if any(
        getattr(game.status, "value", game.status) == "scheduled"
        for game in transaction_source.schedule.values()
    ):
        transaction_source, regular_result = simulate_regular_season_scope(
            transaction_source,
            scope=SimulationScope.REMAINDER,
        )
    else:
        regular_result = None

    regular_snapshot = (
        copy.deepcopy(transaction_source.standings),
        copy.deepcopy(transaction_source.player_season_totals),
        copy.deepcopy(transaction_source.schedule),
        copy.deepcopy(transaction_source.completed_games),
    )
    if get_postseason_state(transaction_source, required=False) is None:
        initialize_postseason(transaction_source)

    progress_counts: list[int] = []
    started = time.perf_counter()
    completed_state, result = advance_postseason(
        transaction_source,
        scope=PostseasonSimulationScope.TO_CHAMPION,
        policy=FranchiseSimulationPolicy.FREE_SIMULATION,
        seed=20260809,
        progress_callback=lambda current, count, game: progress_counts.append(count),
    )
    elapsed = round(time.perf_counter() - started, 3)
    postseason = get_postseason_state(completed_state)
    regular_unchanged = regular_snapshot == (
        completed_state.standings,
        completed_state.player_season_totals,
        completed_state.schedule,
        completed_state.completed_games,
    )

    checks = {
        "execution_version_is_current": POSTSEASON_EXECUTION_VERSION == "postseason-batch-performance-v1-2026-08-09",
        "postseason_completes": bool(postseason.champion) and result.games_simulated > 0,
        "postseason_runtime_is_interactive": elapsed < float(max_seconds),
        "progress_callback_is_complete": progress_counts == list(range(1, result.games_simulated + 1)),
        "regular_season_is_unchanged": regular_unchanged,
        "current_fatigue_is_visible": bool(nonzero_teams),
        "fatigue_timeline_is_monotonic_through_rest": all(fatigue_display_checks),
        "same_day_game_order_is_invariant": bool(same_day["passed"]),
    }
    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "script": VALIDATOR_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "source_completed_games": len(source.completed_games),
            "regular_games_simulated": getattr(regular_result, "games_simulated", 0),
            "postseason_games": result.games_simulated,
            "postseason_runtime_seconds": elapsed,
            "postseason_games_per_second": round(result.games_simulated / max(elapsed, 0.001), 2),
            "champion": postseason.champion,
            "teams_with_current_fatigue": nonzero_teams,
            "maximum_stored_fatigue": max((float(profile.fatigue or 0.0) for profile in profiles.values()), default=0.0),
            "same_day_order_check": same_day,
        },
        "passed": not failed,
    }
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    if failed:
        raise AssertionError(
            "Postseason/fatigue performance validation failed: " + ", ".join(failed)
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-seconds", type=float, default=15.0)
    args = parser.parse_args()
    run_validation(max_seconds=args.max_seconds)
    print("\nPOSTSEASON AND FATIGUE PERFORMANCE V1 VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
