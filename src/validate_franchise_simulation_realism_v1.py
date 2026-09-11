from __future__ import annotations

import argparse
import json
import math
import statistics
from dataclasses import replace
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_command_center_v1 import (  # noqa: E402
    ordered_standings,
)
from regular_season_simulation_controller_v1 import (  # noqa: E402
    SimulationScope,
    build_installed_state,
    simulate_regular_season_scope,
)
from simulation_league_alignment_v1 import (  # noqa: E402
    CONFERENCE_TEAMS,
    alignment_is_complete,
    apply_nba_team_alignment,
)
from simulation_league_state_v1 import (  # noqa: E402
    MINUTES_MODEL_VERSION,
    validate_simulation_league_state,
)
from single_game_simulator_v1 import (  # noqa: E402
    ENGINE_VERSION,
)


VALIDATOR_VERSION = (
    "franchise-simulation-realism-validator-v1.1-2026-08-08"
)
REPORT_PATH = (
    OUTPUTS
    / "franchise_simulation_realism_validation_v1.json"
)


def qualified_player_rows(
    state: Any,
    *,
    minimum_games: int = 58,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for player_id, totals in (
        state.player_season_totals.items()
    ):
        games = int(
            totals.games_played
        )

        if games < minimum_games:
            continue

        player = state.players[
            player_id
        ]
        rows.append(
            {
                "player_id": player_id,
                "player": (
                    player.player_name
                ),
                "team": (
                    player.team_abbreviation
                ),
                "games": games,
                "minutes": (
                    totals.minutes / games
                ),
                "points": (
                    totals.points / games
                ),
                "rebounds": (
                    totals.rebounds / games
                ),
                "assists": (
                    totals.assists / games
                ),
                "steals": (
                    totals.steals / games
                ),
                "blocks": (
                    totals.blocks / games
                ),
            }
        )

    rows.sort(
        key=lambda row: (
            -row["points"],
            row["player"],
        )
    )
    return rows


def team_scoring_rows(
    state: Any,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for standing in (
        state.standings.values()
    ):
        games = max(
            1,
            standing.games_played,
        )
        rows.append(
            {
                "team": (
                    standing
                    .team_abbreviation
                ),
                "games": (
                    standing.games_played
                ),
                "points_for_per_game": (
                    standing.points_for
                    / games
                ),
                "points_against_per_game": (
                    standing.points_against
                    / games
                ),
            }
        )

    rows.sort(
        key=lambda row: (
            -row[
                "points_for_per_game"
            ],
            row["team"],
        )
    )
    return rows


def run_validation(
    *,
    seed: int = 20260808,
) -> dict[str, Any]:
    state = build_installed_state(
        seed=seed
    )
    # This validator isolates scoring and minute-allocation calibration.
    # Injury behavior is validated separately by validate_injury_fatigue_v1.
    state.settings = replace(
        state.settings,
        injuries_enabled=False,
    )
    apply_nba_team_alignment(
        state
    )
    state, simulation = (
        simulate_regular_season_scope(
            state,
            scope=SimulationScope.REMAINDER,
        )
    )
    validate_simulation_league_state(
        state
    )
    apply_nba_team_alignment(
        state
    )

    players = qualified_player_rows(
        state
    )
    teams = team_scoring_rows(
        state
    )
    top_ten = players[:10]
    leader = (
        players[0]
        if players
        else {}
    )
    max_minutes = max(
        (
            row["minutes"]
            for row in players
        ),
        default=0.0,
    )
    max_points = max(
        (
            row["points"]
            for row in players
        ),
        default=0.0,
    )
    max_rebounds = max(
        (
            row["rebounds"]
            for row in players
        ),
        default=0.0,
    )
    max_assists = max(
        (
            row["assists"]
            for row in players
        ),
        default=0.0,
    )
    minute_standard_deviation = (
        statistics.pstdev(
            row["minutes"]
            for row in players
        )
        if len(players) >= 2
        else 0.0
    )
    player_rows_by_name = {
        row["player"]: row
        for row in players
    }
    star_minute_results: dict[
        str,
        dict[str, float],
    ] = {}
    for star_name in (
        "Shai Gilgeous-Alexander",
        "Luka Dončić",
    ):
        row = player_rows_by_name.get(
            star_name
        )
        if row is None:
            continue

        player_id = row["player_id"]
        team = state.players[
            player_id
        ].team_abbreviation
        target = state.teams[
            team
        ].rotation.minutes_targets.get(
            player_id,
            0.0,
        )
        star_minute_results[
            star_name
        ] = {
            "simulated_mpg": (
                row["minutes"]
            ),
            "rotation_target": (
                target
            ),
        }
    top_ten_points = (
        statistics.mean(
            row["points"]
            for row in top_ten
        )
        if top_ten
        else 0.0
    )
    league_team_ppg = (
        statistics.mean(
            row[
                "points_for_per_game"
            ]
            for row in teams
        )
        if teams
        else 0.0
    )
    maximum_team_ppg = max(
        (
            row[
                "points_for_per_game"
            ]
            for row in teams
        ),
        default=0.0,
    )
    minimum_team_ppg = min(
        (
            row[
                "points_for_per_game"
            ]
            for row in teams
        ),
        default=0.0,
    )

    east = ordered_standings(
        state,
        conference="East",
    )
    west = ordered_standings(
        state,
        conference="West",
    )

    checks = {
        "validator_version_is_current": (
            VALIDATOR_VERSION.endswith(
                "2026-08-08"
            )
        ),
        "engine_version_is_realism_calibrated": (
            ENGINE_VERSION
            == (
                "single-game-simulator-"
                "v1.6-2026-08-08"
            )
        ),
        "full_season_simulates_1230_games": (
            simulation.games_simulated
            == 1230
            and len(
                state.completed_games
            )
            == 1230
        ),
        "all_teams_finish_82_games": all(
            standing.games_played == 82
            and standing.wins
            + standing.losses
            == 82
            for standing
            in state.standings.values()
        ),
        "canonical_alignment_is_complete": (
            alignment_is_complete(
                state
            )
        ),
        "east_has_15_standings_rows": (
            len(east) == 15
            and len(
                CONFERENCE_TEAMS[
                    "East"
                ]
            )
            == 15
        ),
        "west_has_15_standings_rows": (
            len(west) == 15
            and len(
                CONFERENCE_TEAMS[
                    "West"
                ]
            )
            == 15
        ),
        "qualified_player_pool_is_large": (
            len(players) >= 150
        ),
        "historical_minutes_model_is_current": (
            MINUTES_MODEL_VERSION
            == (
                "simulation-player-minutes-v1-2026-08-08"
            )
        ),
        "minute_distribution_is_not_flat": (
            minute_standard_deviation
            >= 4.0
        ),
        "sga_and_luka_exceed_32_mpg": (
            set(
                star_minute_results
            )
            == {
                "Shai Gilgeous-Alexander",
                "Luka Dončić",
            }
            and all(
                result[
                    "simulated_mpg"
                ]
                > 32.0
                for result
                in star_minute_results.values()
            )
        ),
        "star_minutes_match_rotation_targets": (
            bool(
                star_minute_results
            )
            and all(
                abs(
                    result[
                        "simulated_mpg"
                    ]
                    - result[
                        "rotation_target"
                    ]
                )
                <= 0.2
                for result
                in star_minute_results.values()
            )
        ),
        "minutes_leader_is_realistic": (
            33.0
            <= max_minutes
            <= 38.8
        ),
        "scoring_leader_is_not_inflated": (
            25.0
            <= max_points
            <= 38.5
        ),
        "top_ten_scoring_is_plausible": (
            23.0
            <= top_ten_points
            <= 35.0
        ),
        "rebounding_leader_is_plausible": (
            max_rebounds <= 19.0
        ),
        "assist_leader_is_plausible": (
            max_assists <= 15.5
        ),
        "league_team_scoring_is_plausible": (
            104.0
            <= league_team_ppg
            <= 121.0
        ),
        "team_scoring_range_is_plausible": (
            minimum_team_ppg >= 94.0
            and maximum_team_ppg
            <= 132.0
        ),
        "all_player_rates_are_finite": all(
            all(
                math.isfinite(
                    float(
                        row[field]
                    )
                )
                for field in (
                    "minutes",
                    "points",
                    "rebounds",
                    "assists",
                    "steals",
                    "blocks",
                )
            )
            for row in players
        ),
    }
    failed = [
        name
        for name, passed
        in checks.items()
        if not passed
    ]
    report = {
        "script": VALIDATOR_VERSION,
        "engine": ENGINE_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "games_simulated": (
                simulation.games_simulated
            ),
            "qualified_players": len(
                players
            ),
            "scoring_leader": leader,
            "max_minutes": round(
                max_minutes,
                3,
            ),
            "minute_standard_deviation": round(
                minute_standard_deviation,
                3,
            ),
            "star_minute_results": (
                star_minute_results
            ),
            "top_ten_ppg_average": round(
                top_ten_points,
                3,
            ),
            "max_rebounds": round(
                max_rebounds,
                3,
            ),
            "max_assists": round(
                max_assists,
                3,
            ),
            "league_team_ppg": round(
                league_team_ppg,
                3,
            ),
            "minimum_team_ppg": round(
                minimum_team_ppg,
                3,
            ),
            "maximum_team_ppg": round(
                maximum_team_ppg,
                3,
            ),
            "top_ten_scorers": top_ten,
            "top_five_offenses": (
                teams[:5]
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
            "Franchise simulation realism "
            "validation failed: "
            + ", ".join(failed)
        )

    return report


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
    print(
        json.dumps(
            report,
            indent=2,
        )
    )
    print(
        "\nFRANCHISE SIMULATION REALISM "
        "VALIDATION PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
