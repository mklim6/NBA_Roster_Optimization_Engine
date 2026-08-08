from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from regular_season_schedule_v1 import (  # noqa: E402
    LEAGUE_GAME_COUNT,
)
from regular_season_simulation_controller_v1 import (  # noqa: E402
    CONTROLLER_VERSION,
    RegularSeasonSimulationControllerError,
    SimulationScope,
    build_installed_state,
    build_regular_season_simulation_plan,
    commit_regular_season_simulation_plan,
    completed_score_signature,
    plan_matches_state,
    regular_season_progress,
    regular_season_state_fingerprint,
    simulate_regular_season_scope,
    standings_signature,
)
from simulation_league_state_v1 import (  # noqa: E402
    GameStatus,
    LeaguePhase,
    validate_simulation_league_state,
)


VALIDATOR_VERSION = (
    "regular-season-simulation-controller-validator-v1-2026-08-08"
)
REPORT_PATH = (
    OUTPUTS
    / "regular_season_simulation_controller_validation_v1.json"
)


def standings_leaders(
    state: Any,
    count: int = 8,
) -> list[dict[str, Any]]:
    ordered = sorted(
        state.standings.values(),
        key=lambda standing: (
            -standing.wins,
            standing.losses,
            -(
                standing.points_for
                - standing.points_against
            ),
            standing.team_abbreviation,
        ),
    )
    return [
        {
            "team": (
                standing.team_abbreviation
            ),
            "wins": standing.wins,
            "losses": standing.losses,
            "point_differential": (
                standing.points_for
                - standing.points_against
            ),
        }
        for standing in ordered[:count]
    ]


def run_validation(
    *,
    seed: int = 20260808,
) -> dict[str, Any]:
    source_state = build_installed_state(
        seed=seed
    )
    source_fingerprint = (
        regular_season_state_fingerprint(
            source_state
        )
    )
    fresh_remainder_plan = (
        build_regular_season_simulation_plan(
            source_state,
            scope=SimulationScope.REMAINDER,
        )
    )

    segmented_state, first_day_result = (
        simulate_regular_season_scope(
            source_state,
            scope=SimulationScope.NEXT_DAY,
        )
    )
    segmented_state, week_result = (
        simulate_regular_season_scope(
            segmented_state,
            scope=SimulationScope.NEXT_WEEK,
        )
    )

    direct_partial_state, direct_partial_result = (
        simulate_regular_season_scope(
            source_state,
            scope=SimulationScope.THROUGH_DAY,
            target_day=week_result.target_day,
        )
    )
    segmented_partial_scores = (
        completed_score_signature(
            segmented_state
        )
    )
    direct_partial_scores = (
        completed_score_signature(
            direct_partial_state
        )
    )
    segmented_partial_standings = (
        standings_signature(
            segmented_state
        )
    )
    direct_partial_standings = (
        standings_signature(
            direct_partial_state
        )
    )

    progress_events: list[
        tuple[int, int, str, int]
    ] = []

    def capture_progress(
        completed: int,
        total: int,
        game_id: str,
        day_index: int,
    ) -> None:
        progress_events.append(
            (
                completed,
                total,
                game_id,
                day_index,
            )
        )

    remainder_plan = (
        build_regular_season_simulation_plan(
            segmented_state,
            scope=SimulationScope.REMAINDER,
        )
    )
    full_started = time.perf_counter()
    full_state, remainder_result = (
        commit_regular_season_simulation_plan(
            segmented_state,
            remainder_plan,
            progress_callback=(
                capture_progress
            ),
        )
    )
    full_elapsed = (
        time.perf_counter()
        - full_started
    )

    completed_plan_blocked = False
    try:
        build_regular_season_simulation_plan(
            full_state,
            scope=SimulationScope.NEXT_GAME,
        )
    except (
        RegularSeasonSimulationControllerError
    ):
        completed_plan_blocked = True

    stale_plan_blocked = False
    try:
        commit_regular_season_simulation_plan(
            segmented_state,
            fresh_remainder_plan,
        )
    except (
        RegularSeasonSimulationControllerError
    ):
        stale_plan_blocked = True

    full_progress = regular_season_progress(
        full_state
    )
    source_progress = (
        regular_season_progress(
            source_state
        )
    )
    max_scheduled_day = max(
        game.day_index
        for game in full_state.schedule.values()
    )
    standings_games = sum(
        standing.games_played
        for standing
        in full_state.standings.values()
    )
    wins = sum(
        standing.wins
        for standing
        in full_state.standings.values()
    )
    losses = sum(
        standing.losses
        for standing
        in full_state.standings.values()
    )
    all_team_records = {
        team: (
            standing.games_played,
            standing.wins,
            standing.losses,
        )
        for team, standing
        in full_state.standings.items()
    }
    ordered_completed = [
        (
            full_state.schedule[game_id],
            game,
        )
        for game_id, game
        in full_state.completed_games.items()
    ]
    ordered_completed.sort(
        key=lambda item: (
            item[0].day_index,
            item[0].game_id,
        )
    )

    def result_summary(
        item: tuple[Any, Any],
    ) -> dict[str, Any]:
        scheduled, game = item
        winner = (
            game.home_team
            if game.home_score
            > game.away_score
            else game.away_team
        )
        return {
            "game_id": game.game_id,
            "day_index": (
                scheduled.day_index
            ),
            "away_team": game.away_team,
            "away_score": game.away_score,
            "home_team": game.home_team,
            "home_score": game.home_score,
            "winner": winner,
        }

    first_five_results = [
        result_summary(item)
        for item in ordered_completed[:5]
    ]
    last_five_results = [
        result_summary(item)
        for item in ordered_completed[-5:]
    ]
    partial_games = (
        first_day_result.games_simulated
        + week_result.games_simulated
    )

    checks = {
        "validator_version_is_current": (
            VALIDATOR_VERSION.endswith(
                "2026-08-08"
            )
        ),
        "controller_version_is_current": (
            remainder_result
            .controller_version
            == CONTROLLER_VERSION
        ),
        "fresh_remainder_plan_has_1230_games": (
            fresh_remainder_plan
            .planned_games
            == LEAGUE_GAME_COUNT
        ),
        "fresh_remainder_plan_matches_source": (
            plan_matches_state(
                source_state,
                fresh_remainder_plan,
            )
        ),
        "all_commits_return_replacement_states": (
            segmented_state
            is not source_state
            and direct_partial_state
            is not source_state
            and full_state
            is not segmented_state
        ),
        "simulation_does_not_mutate_source": (
            regular_season_state_fingerprint(
                source_state
            )
            == source_fingerprint
            and source_progress[
                "completed_games"
            ]
            == 0
        ),
        "progress_callback_fires_for_every_remainder_game": (
            len(progress_events)
            == remainder_result
            .games_simulated
            and progress_events[0][0] == 1
            and progress_events[-1][0]
            == remainder_result
            .games_simulated
            and all(
                event[1]
                == remainder_result
                .games_simulated
                for event in progress_events
            )
        ),
        "partial_scope_counts_reconcile": (
            len(
                segmented_state
                .completed_games
            )
            == partial_games
            and direct_partial_result
            .games_simulated
            == partial_games
        ),
        "segmented_and_direct_partial_scores_match": (
            segmented_partial_scores
            == direct_partial_scores
        ),
        "segmented_and_direct_partial_standings_match": (
            segmented_partial_standings
            == direct_partial_standings
        ),
        "all_1230_games_complete": (
            len(full_state.completed_games)
            == LEAGUE_GAME_COUNT
            and partial_games
            + remainder_result
            .games_simulated
            == LEAGUE_GAME_COUNT
            and all(
                game.status
                == GameStatus.COMPLETED
                for game
                in full_state.schedule.values()
            )
        ),
        "regular_season_completion_flag_set": (
            remainder_result
            .regular_season_complete
            and remainder_result
            .remaining_games_after
            == 0
        ),
        "progress_snapshot_reaches_100_percent": (
            full_progress[
                "regular_season_complete"
            ]
            and full_progress[
                "completion_percentage"
            ]
            == 100.0
            and full_progress[
                "remaining_games"
            ]
            == 0
        ),
        "current_day_reaches_last_schedule_day": (
            full_state.current_day_index
            == max_scheduled_day
            and remainder_result
            .final_current_day
            == max_scheduled_day
        ),
        "every_team_finishes_82_games": all(
            games_played == 82
            and wins_for_team
            + losses_for_team
            == 82
            for (
                games_played,
                wins_for_team,
                losses_for_team,
            ) in all_team_records.values()
        ),
        "league_standings_totals_reconcile": (
            standings_games
            == LEAGUE_GAME_COUNT * 2
            and wins == LEAGUE_GAME_COUNT
            and losses == LEAGUE_GAME_COUNT
        ),
        "full_state_remains_valid": bool(
            validate_simulation_league_state(
                full_state
            )
        ),
        "partial_states_remain_valid": (
            bool(
                validate_simulation_league_state(
                    segmented_state
                )
            )
            and bool(
                validate_simulation_league_state(
                    direct_partial_state
                )
            )
        ),
        "stale_plan_is_rejected": (
            stale_plan_blocked
        ),
        "completed_season_rejects_new_plan": (
            completed_plan_blocked
        ),
        "season_remains_regular_season_pending_postseason": (
            full_state.phase
            == LeaguePhase.REGULAR_SEASON
        ),
        "partial_scopes_are_nonempty": (
            first_day_result.games_simulated
            > 0
            and week_result.games_simulated
            > 0
            and remainder_result.games_simulated
            > 0
        ),
    }
    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]
    report = {
        "script": VALIDATOR_VERSION,
        "controller": CONTROLLER_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "season_label": (
                full_state.settings
                .season_label
            ),
            "games_simulated_total": (
                len(
                    full_state.completed_games
                )
            ),
            "calendar_days_completed": (
                len(
                    {
                        game.day_index
                        for game
                        in full_state
                        .schedule.values()
                    }
                )
            ),
            "final_day_index": (
                full_state.current_day_index
            ),
            "remainder_runtime_seconds": round(
                full_elapsed,
                3,
            ),
            "segmented_scopes": {
                "first_day_games": (
                    first_day_result
                    .games_simulated
                ),
                "next_week_games": (
                    week_result.games_simulated
                ),
                "remainder_games": (
                    remainder_result
                    .games_simulated
                ),
            },
            "top_standings": (
                standings_leaders(
                    full_state
                )
            ),
            "first_five_results": (
                first_five_results
            ),
            "last_five_results": (
                last_five_results
            ),
        },
        "passed": not failed,
    }

    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )
    REPORT_PATH.write_text(
        json.dumps(
            report,
            indent=2,
        ),
        encoding="utf-8",
    )

    if failed:
        raise AssertionError(
            "Regular-season simulation controller "
            "validation failed: "
            + ", ".join(failed)
        )

    return report


def print_report(
    report: dict[str, Any],
) -> None:
    summary = report["summary"]
    print("=" * 88)
    print(
        "REGULAR SEASON SIMULATION "
        "CONTROLLER VALIDATION"
    )
    print("=" * 88)
    print(
        f"Season: "
        f"{summary['season_label']} | "
        f"Games simulated: "
        f"{summary['games_simulated_total']} | "
        f"Final day: "
        f"{summary['final_day_index']}"
    )
    print(
        f"Remainder runtime: "
        f"{summary['remainder_runtime_seconds']:.3f}s"
    )
    segmented = summary[
        "segmented_scopes"
    ]
    print(
        "Segmented path: "
        f"day={segmented['first_day_games']} "
        f"| week={segmented['next_week_games']} "
        f"| remainder="
        f"{segmented['remainder_games']}"
    )

    print("\nCHECKS")
    for name, passed in report[
        "checks"
    ].items():
        print(
            f"{'PASS' if passed else 'FAIL':4s}  "
            f"{name}"
        )

    print("\nTOP STANDINGS")
    for row in summary["top_standings"]:
        print(
            f"  {row['team']} "
            f"{row['wins']}-{row['losses']} "
            f"({row['point_differential']:+d})"
        )

    print(f"\nReport: {REPORT_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--seed",
        type=int,
        default=20260808,
    )
    args = parser.parse_args()

    report = run_validation(
        seed=args.seed
    )
    print_report(report)
    print(
        "\nREGULAR SEASON SIMULATION "
        "CONTROLLER VALIDATION PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())