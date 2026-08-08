from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any


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
    ALL_TEAMS,
    AWAY_GAMES_PER_TEAM,
    HOME_GAMES_PER_TEAM,
    LEAGUE_GAME_COUNT,
    REGULAR_SEASON_GAMES_PER_TEAM,
    SCHEDULE_ENGINE_VERSION,
    generate_regular_season_schedule,
    install_regular_season_schedule,
    schedule_relationship_signature,
    team_game_rows,
    validate_generated_schedule,
    write_schedule_csv,
)
from simulation_league_state_v1 import (  # noqa: E402
    GameStatus,
    LeaguePhase,
    create_simulation_league_state,
    validate_simulation_league_state,
)
from single_game_simulator_v1 import (  # noqa: E402
    simulate_scheduled_game,
)
from state_runtime_adapter_v1 import (  # noqa: E402
    build_state_runtime,
)


VALIDATOR_VERSION = (
    "regular-season-schedule-validator-v1-2026-08-08"
)
REPORT_PATH = (
    OUTPUTS
    / "regular_season_schedule_validation_v1.json"
)
SCHEDULE_PATH = (
    OUTPUTS
    / "regular_season_schedule_validation_v1.csv"
)


def run_validation(
    *,
    seed: int = 20260808,
) -> dict[str, Any]:
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
    repeated = generate_regular_season_schedule(
        state,
        seed=seed,
    )
    alternate = generate_regular_season_schedule(
        state,
        seed=seed + 1,
    )
    schedule_validation = (
        validate_generated_schedule(
            schedule
        )
    )
    team_rows = team_game_rows(schedule)

    installed_state = copy.deepcopy(state)
    install_regular_season_schedule(
        installed_state,
        schedule,
    )

    first_day = min(
        game.day_index
        for game in schedule.games
    )
    first_day_games = [
        game
        for game in schedule.games
        if game.day_index == first_day
    ]
    previewed_scores: list[str] = []

    for game_index, game in enumerate(
        first_day_games,
        start=1,
    ):
        preview = simulate_scheduled_game(
            installed_state,
            game.game_id,
            seed=seed + game_index,
            commit=False,
        )
        committed = simulate_scheduled_game(
            installed_state,
            game.game_id,
            seed=seed + game_index,
            commit=True,
        )

        if preview.game != committed.game:
            raise AssertionError(
                "Committed first-day game did not "
                "match its deterministic preview."
            )

        previewed_scores.append(
            f"{game.away_team} "
            f"{committed.game.away_score}, "
            f"{game.home_team} "
            f"{committed.game.home_score}"
        )

    first_day_team_count = len(
        {
            team
            for game in first_day_games
            for team in (
                game.home_team,
                game.away_team,
            )
        }
    )
    standings_games_recorded = sum(
        standing.games_played
        for standing in (
            installed_state.standings.values()
        )
    )
    completed_status_count = sum(
        game.status == GameStatus.COMPLETED
        for game in (
            installed_state.schedule.values()
        )
    )
    sample_teams = (
        "BOS",
        "CHI",
        "LAL",
        "SAS",
    )
    sample_team_summary = {
        team: {
            "games": len(team_rows[team]),
            "home": sum(
                location == "H"
                for _, location, _
                in team_rows[team]
            ),
            "away": sum(
                location == "A"
                for _, location, _
                in team_rows[team]
            ),
            "first_game_day": (
                team_rows[team][0][0]
            ),
            "last_game_day": (
                team_rows[team][-1][0]
            ),
        }
        for team in sample_teams
    }

    checks = {
        "validator_version_is_current": (
            VALIDATOR_VERSION.endswith(
                "2026-08-08"
            )
        ),
        "schedule_engine_version_is_current": (
            schedule.engine_version
            == SCHEDULE_ENGINE_VERSION
        ),
        "schedule_validation_passes": (
            schedule_validation["passed"]
        ),
        "same_seed_is_deterministic": (
            schedule.signature
            == repeated.signature
        ),
        "different_seed_changes_calendar": (
            schedule.signature
            != alternate.signature
        ),
        "different_seed_preserves_matchup_matrix": (
            schedule_relationship_signature(
                schedule
            )
            == schedule_relationship_signature(
                alternate
            )
        ),
        "all_30_teams_are_present": (
            set(team_rows) == set(ALL_TEAMS)
        ),
        "every_team_plays_82_games": all(
            len(rows)
            == REGULAR_SEASON_GAMES_PER_TEAM
            for rows in team_rows.values()
        ),
        "every_team_has_41_home_games": all(
            sum(
                location == "H"
                for _, location, _ in rows
            )
            == HOME_GAMES_PER_TEAM
            for rows in team_rows.values()
        ),
        "every_team_has_41_away_games": all(
            sum(
                location == "A"
                for _, location, _ in rows
            )
            == AWAY_GAMES_PER_TEAM
            for rows in team_rows.values()
        ),
        "installation_adds_1230_games": (
            len(installed_state.schedule)
            == LEAGUE_GAME_COUNT
        ),
        "installation_activates_regular_season": (
            installed_state.phase
            == LeaguePhase.REGULAR_SEASON
        ),
        "first_day_has_unique_teams": (
            first_day_team_count
            == len(first_day_games) * 2
        ),
        "first_day_games_preview_and_commit": (
            len(previewed_scores)
            == len(first_day_games)
        ),
        "first_day_schedule_statuses_complete": (
            completed_status_count
            == len(first_day_games)
        ),
        "first_day_completed_games_persist": (
            len(
                installed_state.completed_games
            )
            == len(first_day_games)
        ),
        "standings_reconcile_after_first_day": (
            standings_games_recorded
            == len(first_day_games) * 2
        ),
        "unplayed_schedule_remains_available": (
            sum(
                game.status
                == GameStatus.SCHEDULED
                for game
                in installed_state.schedule.values()
            )
            == (
                LEAGUE_GAME_COUNT
                - len(first_day_games)
            )
        ),
        "installed_state_remains_valid": bool(
            validate_simulation_league_state(
                installed_state
            )
        ),
    }
    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]
    report = {
        "script": VALIDATOR_VERSION,
        "engine": schedule.engine_version,
        "checks": checks,
        "failed_checks": failed,
        "schedule": {
            "season_label": (
                schedule.season_label
            ),
            "seed": schedule.seed,
            "construction_seed": (
                schedule.construction_seed
            ),
            "generation_attempt": (
                schedule.generation_attempt
            ),
            "signature": (
                schedule.signature
            ),
            **schedule_validation["metrics"],
        },
        "first_day": {
            "day_index": first_day,
            "games": len(first_day_games),
            "scores": previewed_scores,
        },
        "sample_teams": sample_team_summary,
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
    write_schedule_csv(
        schedule,
        SCHEDULE_PATH,
    )

    if failed:
        raise AssertionError(
            "Regular-season schedule validation "
            "failed: "
            + ", ".join(failed)
        )

    return report


def print_report(
    report: dict[str, Any],
) -> None:
    schedule = report["schedule"]
    print("=" * 88)
    print(
        "REGULAR SEASON SCHEDULE VALIDATION"
    )
    print("=" * 88)
    print(
        f"Games: {schedule['game_count']} | "
        f"Teams: {len(ALL_TEAMS)} | "
        "Per team: 82"
    )
    print(
        f"Home/Away: 41/41 | "
        f"Rounds: {schedule['round_count']} | "
        f"Calendar days: "
        f"{schedule['calendar_days']}"
    )
    print(
        f"Active days: {schedule['active_days']} | "
        f"Daily games: "
        f"{schedule['minimum_games_on_active_day']}"
        "-"
        f"{schedule['maximum_games_on_active_day']}"
    )
    print(
        f"Back-to-backs: "
        f"{schedule['back_to_back_minimum']}"
        "-"
        f"{schedule['back_to_back_maximum']} "
        f"(avg "
        f"{schedule['back_to_back_average']:.2f})"
    )
    print(
        f"Max home/away streak: "
        f"{schedule['maximum_home_away_streak']} | "
        f"Minimum rematch gap: "
        f"{schedule['minimum_rematch_gap_days']} days"
    )
    print(
        f"Generation attempt: "
        f"{schedule['generation_attempt']} | "
        f"Signature: "
        f"{schedule['signature'][:16]}..."
    )

    print("\nCHECKS")
    for name, passed in report[
        "checks"
    ].items():
        print(
            f"{'PASS' if passed else 'FAIL':4s}  "
            f"{name}"
        )

    print("\nFIRST DAY")
    for score in report["first_day"][
        "scores"
    ]:
        print(f"  {score}")

    print(f"\nReport: {REPORT_PATH}")
    print(f"CSV:    {SCHEDULE_PATH}")


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
        "\nREGULAR SEASON SCHEDULE "
        "VALIDATION PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())