from __future__ import annotations

import argparse
import copy
import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import load_runtime_data  # noqa: E402
from mutable_league_state_v1 import create_league_state  # noqa: E402
from simulation_league_state_v1 import (  # noqa: E402
    ScheduledGame,
    add_scheduled_games,
    create_simulation_league_state,
)
from single_game_simulator_v1 import (  # noqa: E402
    ENGINE_VERSION,
    profile_adjusted_stat_multiplier,
    simulate_scheduled_game,
)
from simulation_player_stat_profiles_v1 import (  # noqa: E402
    load_player_stat_profiles,
    player_id_by_name,
    player_stat_factor,
)
from state_runtime_adapter_v1 import build_state_runtime  # noqa: E402


SCRIPT_VERSION = "player-specific-game-stat-validator-v1-2026-08-08"
JSON_REPORT = OUTPUTS / "player_specific_game_stat_validation_v1.json"
CSV_REPORT = OUTPUTS / "player_specific_game_stat_profiles_v1.csv"


def per_36(total: float, minutes: float) -> float:
    if minutes <= 0:
        return 0.0
    return 36.0 * total / minutes


def exact_position(position: str) -> str:
    value = str(position or "").strip().upper()
    return value if value else "UNK"


def create_base_state():
    base_runtime = load_runtime_data()
    league_state = create_league_state(base_runtime)
    runtime = build_state_runtime(
        base_runtime,
        league_state,
    )
    state = create_simulation_league_state(
        runtime,
        league_state,
    )
    return state


def simulate_sample(
    games: int,
    seed: int,
) -> tuple[
    dict[str, dict[str, float]],
    dict[str, float],
]:
    if games < 30:
        raise ValueError(
            "Use at least 30 games for a meaningful profile check."
        )

    state = create_base_state()
    teams = sorted(state.teams)
    matchup_rng = random.Random(seed)

    position_totals: dict[
        str,
        dict[str, float],
    ] = defaultdict(
        lambda: defaultdict(float)
    )
    team_totals: dict[
        str,
        float,
    ] = defaultdict(float)

    for game_number in range(1, games + 1):
        home_team, away_team = matchup_rng.sample(
            teams,
            2,
        )
        game_id = f"POSITION-VALIDATION-{game_number:04d}"

        trial_state = copy.deepcopy(state)
        add_scheduled_games(
            trial_state,
            [
                ScheduledGame(
                    game_id=game_id,
                    day_index=game_number,
                    home_team=home_team,
                    away_team=away_team,
                )
            ],
        )
        result = simulate_scheduled_game(
            trial_state,
            game_id,
            seed=seed + game_number * 7919,
            commit=False,
        )

        for team in (home_team, away_team):
            lines = [
                line
                for line in result.game.player_box_scores
                if line.team_abbreviation == team
            ]
            team_totals["team_games"] += 1
            team_totals["rebounds"] += sum(
                line.rebounds for line in lines
            )
            team_totals["assists"] += sum(
                line.assists for line in lines
            )
            team_totals["steals"] += sum(
                line.steals for line in lines
            )
            team_totals["blocks"] += sum(
                line.blocks for line in lines
            )
            team_totals["turnovers"] += sum(
                line.turnovers for line in lines
            )
            team_totals["fouls"] += sum(
                line.fouls for line in lines
            )

        for line in result.game.player_box_scores:
            player = trial_state.players[line.player_id]
            position = exact_position(player.position)
            bucket = position_totals[position]
            bucket["appearances"] += 1
            bucket["minutes"] += line.minutes
            bucket["points"] += line.points
            bucket["rebounds"] += line.rebounds
            bucket["assists"] += line.assists
            bucket["steals"] += line.steals
            bucket["blocks"] += line.blocks
            bucket["turnovers"] += line.turnovers
            bucket["fouls"] += line.fouls
            bucket["three_attempts"] += (
                line.three_pointers_attempted
            )

    return position_totals, team_totals


def position_rows(
    position_totals: dict[
        str,
        dict[str, float],
    ],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for position, totals in sorted(
        position_totals.items()
    ):
        minutes = totals["minutes"]
        rows.append(
            {
                "position": position,
                "appearances": int(
                    totals["appearances"]
                ),
                "minutes": round(minutes, 1),
                "points_per_36": round(
                    per_36(totals["points"], minutes),
                    3,
                ),
                "rebounds_per_36": round(
                    per_36(totals["rebounds"], minutes),
                    3,
                ),
                "assists_per_36": round(
                    per_36(totals["assists"], minutes),
                    3,
                ),
                "steals_per_36": round(
                    per_36(totals["steals"], minutes),
                    3,
                ),
                "blocks_per_36": round(
                    per_36(totals["blocks"], minutes),
                    3,
                ),
                "turnovers_per_36": round(
                    per_36(totals["turnovers"], minutes),
                    3,
                ),
                "fouls_per_36": round(
                    per_36(totals["fouls"], minutes),
                    3,
                ),
                "three_attempts_per_36": round(
                    per_36(
                        totals["three_attempts"],
                        minutes,
                    ),
                    3,
                ),
            }
        )

    return rows


def row_by_position(
    rows: list[dict[str, Any]],
    position: str,
) -> dict[str, Any]:
    for row in rows:
        if row["position"] == position:
            return row
    raise AssertionError(
        f"Expected position group {position!r} "
        "was not present in the sample."
    )


def validate_profiles(
    rows: list[dict[str, Any]],
    team_totals: dict[str, float],
) -> dict[str, Any]:
    guard = row_by_position(rows, "PG/SG")
    combo_big = row_by_position(rows, "PF/C")
    center = row_by_position(rows, "C")

    profiles = load_player_stat_profiles()
    jokic_id = (
        player_id_by_name("Nikola Jokić")
        or player_id_by_name("Nikola Jokic")
    )
    curry_id = player_id_by_name(
        "Stephen Curry"
    )
    wemby_id = player_id_by_name(
        "Victor Wembanyama"
    )
    trae_id = player_id_by_name(
        "Trae Young"
    )

    team_games = team_totals["team_games"]
    team_averages = {
        stat: round(
            team_totals[stat] / team_games,
            3,
        )
        for stat in (
            "rebounds",
            "assists",
            "steals",
            "blocks",
            "turnovers",
            "fouls",
        )
    }

    checks = {
        "engine_version_is_player_specific": (
            ENGINE_VERSION
            == "single-game-simulator-v1.3-2026-08-08"
        ),
        "profile_layer_has_582_players": (
            len(profiles) == 582
        ),
        "jokic_assist_profile_overrides_position": bool(
            jokic_id
            and curry_id
            and profile_adjusted_stat_multiplier(
                jokic_id,
                profiles[jokic_id]["position"],
                "assists",
            )
            > profile_adjusted_stat_multiplier(
                curry_id,
                profiles[curry_id]["position"],
                "assists",
            )
        ),
        "jokic_rebound_profile_is_above_center_baseline": bool(
            jokic_id
            and player_stat_factor(
                jokic_id,
                "rebounds",
            )
            >= 1.05
        ),
        "wembanyama_block_profile_is_exceptional": bool(
            wemby_id
            and player_stat_factor(
                wemby_id,
                "blocks",
            )
            >= 2.00
        ),
        "trae_assist_profile_is_exceptional": bool(
            trae_id
            and player_stat_factor(
                trae_id,
                "assists",
            )
            >= 1.40
        ),
        "guards_average_more_assists_than_centers": (
            guard["assists_per_36"]
            > center["assists_per_36"]
        ),
        "guards_average_more_assists_than_combo_bigs": (
            guard["assists_per_36"]
            > combo_big["assists_per_36"]
        ),
        "centers_average_more_rebounds_than_guards": (
            center["rebounds_per_36"]
            > guard["rebounds_per_36"]
        ),
        "combo_bigs_average_more_rebounds_than_guards": (
            combo_big["rebounds_per_36"]
            > guard["rebounds_per_36"]
        ),
        "centers_average_more_blocks_than_guards": (
            center["blocks_per_36"]
            > guard["blocks_per_36"]
        ),
        "combo_bigs_average_more_blocks_than_guards": (
            combo_big["blocks_per_36"]
            > guard["blocks_per_36"]
        ),
        "guards_record_nonzero_blocks": (
            0.05 <= guard["blocks_per_36"] <= 0.60
        ),
        "centers_keep_clear_block_advantage": (
            center["blocks_per_36"]
            >= 3.0 * guard["blocks_per_36"]
        ),
        "team_rebounds_average_plausible": (
            37.0 <= team_averages["rebounds"] <= 49.0
        ),
        "team_assists_average_plausible": (
            23.0 <= team_averages["assists"] <= 28.5
        ),
        "team_steals_average_plausible": (
            5.0 <= team_averages["steals"] <= 10.0
        ),
        "team_blocks_average_plausible": (
            3.0 <= team_averages["blocks"] <= 7.5
        ),
        "team_turnovers_average_plausible": (
            10.0 <= team_averages["turnovers"] <= 17.0
        ),
        "team_fouls_average_plausible": (
            15.0 <= team_averages["fouls"] <= 24.0
        ),
    }

    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]

    return {
        "script": SCRIPT_VERSION,
        "engine": ENGINE_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "team_averages": team_averages,
        "position_profiles": rows,
        "player_specific_signals": {
            "jokic_assist_factor": (
                player_stat_factor(
                    jokic_id,
                    "assists",
                )
                if jokic_id
                else None
            ),
            "jokic_adjusted_assist_multiplier": (
                profile_adjusted_stat_multiplier(
                    jokic_id,
                    profiles[jokic_id]["position"],
                    "assists",
                )
                if jokic_id
                else None
            ),
            "curry_adjusted_assist_multiplier": (
                profile_adjusted_stat_multiplier(
                    curry_id,
                    profiles[curry_id]["position"],
                    "assists",
                )
                if curry_id
                else None
            ),
            "wembanyama_block_factor": (
                player_stat_factor(
                    wemby_id,
                    "blocks",
                )
                if wemby_id
                else None
            ),
            "trae_assist_factor": (
                player_stat_factor(
                    trae_id,
                    "assists",
                )
                if trae_id
                else None
            ),
        },
        "passed": not failed,
    }


def write_reports(report: dict[str, Any]) -> None:
    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )
    JSON_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
        ),
        encoding="utf-8",
    )

    rows = report["position_profiles"]
    with CSV_REPORT.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--games",
        type=int,
        default=180,
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20260808,
    )
    args = parser.parse_args()

    position_totals, team_totals = simulate_sample(
        games=args.games,
        seed=args.seed,
    )
    rows = position_rows(position_totals)
    report = validate_profiles(
        rows,
        team_totals,
    )
    report["games_simulated"] = args.games
    report["team_games"] = int(
        team_totals["team_games"]
    )

    write_reports(report)

    print(
        json.dumps(
            report,
            indent=2,
        )
    )
    print("")
    print(f"JSON report: {JSON_REPORT}")
    print(f"CSV report:  {CSV_REPORT}")

    if not report["passed"]:
        print("")
        print(
            "PLAYER-SPECIFIC GAME STAT VALIDATION FAILED"
        )
        return 1

    print("")
    print(
        "PLAYER-SPECIFIC GAME STAT VALIDATION PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())