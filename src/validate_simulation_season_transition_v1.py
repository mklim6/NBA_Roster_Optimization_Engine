from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict
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
from player_development_engine_v1 import (  # noqa: E402
    DevelopmentConfig,
)
from simulation_league_state_v1 import (  # noqa: E402
    LeaguePhase,
    ScheduledGame,
    add_scheduled_games,
    create_simulation_league_state,
    validate_simulation_league_state,
)
from franchise_offseason_market_season_v1 import (  # noqa: E402
    COMPLETED_SEASON_CLOSEOUT_ATTR,
    next_season_label as next_offseason_market_season_label,
)
from simulation_season_transition_v1 import (  # noqa: E402
    TRANSITION_VERSION,
    advance_simulation_season,
)
from single_game_simulator_v1 import (  # noqa: E402
    ENGINE_VERSION as GAME_ENGINE_VERSION,
    GameSimulationConfig,
    moderated_player_stat_factor,
    simulate_scheduled_game,
    team_box_score_reconciles,
)
from state_runtime_adapter_v1 import (  # noqa: E402
    build_state_runtime,
)


SCRIPT_VERSION = (
    "simulation-season-transition-validator-v1.4.2-observable-preclosed-fixture-2026-08-18"
)
REPORT_PATH = (
    OUTPUTS
    / "simulation_season_transition_validation_v1.json"
)


def find_player_id(
    state: Any,
    player_name: str,
) -> str:
    target = " ".join(
        player_name.lower().split()
    )
    for player_id, player in (
        state.players.items()
    ):
        name = " ".join(
            player.player_name.lower().split()
        )
        if name == target:
            return player_id
    return ""


def mark_transition_fixture_preclosed(state: Any) -> None:
    """Mark validator fixtures as already closed before Open Next Season.

    Contract expiry/TradeState reconciliation is validated by the dedicated
    completed-season/legacy-contract continuity validators. This validator owns
    development, archive, reset, and next-season behavior, so its fixture must
    enter the modern transition path after completed-season closeout rather than
    invoke the legacy late-clock fallback.
    """
    source_season = str(state.settings.season_label).strip()
    setattr(
        state,
        COMPLETED_SEASON_CLOSEOUT_ATTR,
        {
            "status": "applied",
            "source_season": source_season,
            "target_market_season": next_offseason_market_season_label(source_season),
            "validator_fixture_only": True,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--seed",
        type=int,
        default=20260808,
    )
    args = parser.parse_args()

    base_runtime = load_runtime_data()
    trade_state = create_league_state(
        base_runtime
    )
    runtime = build_state_runtime(
        base_runtime,
        trade_state,
    )
    state = create_simulation_league_state(
        runtime,
        trade_state,
    )

    wemby_id = find_player_id(
        state,
        "Victor Wembanyama",
    )
    curry_id = find_player_id(
        state,
        "Stephen Curry",
    )
    jokic_id = (
        find_player_id(state, "Nikola Jokić")
        or find_player_id(
            state,
            "Nikola Jokic",
        )
    )

    sample_ids = {
        "Victor Wembanyama": wemby_id,
        "Stephen Curry": curry_id,
        "Nikola Jokic": jokic_id,
    }
    missing_samples = [
        name
        for name, player_id
        in sample_ids.items()
        if not player_id
    ]
    if missing_samples:
        raise AssertionError(
            "Missing sample players: "
            + ", ".join(missing_samples)
        )

    pre = {
        player_id: {
            "age": state.players[player_id].age,
            "overall_rating": (
                state.players[
                    player_id
                ].overall_rating
            ),
            "points_factor": (
                state.players[
                    player_id
                ].stat_factors["points"]
            ),
            "assists_factor": (
                state.players[
                    player_id
                ].stat_factors["assists"]
            ),
            "blocks_factor": (
                state.players[
                    player_id
                ].stat_factors["blocks"]
            ),
        }
        for player_id in sample_ids.values()
    }

    preclosed_contract_years = {
        player_id: getattr(
            getattr(player, "contract", None),
            "years_remaining",
            None,
        )
        for player_id, player in state.players.items()
    }
    preclosed_rosters = {
        team_code: tuple(team_state.roster_player_ids)
        for team_code, team_state in state.teams.items()
    }
    preclosed_free_agents = tuple(sorted(state.free_agent_player_ids))

    from types import SimpleNamespace

    state.phase = LeaguePhase.OFFSEASON
    state.postseason_state = SimpleNamespace(
        stage="complete",
        champion="CHI",
        runner_up="HOU",
        conference_champions={
            "East": "CHI",
            "West": "HOU",
        },
        completed_games={
            "NBA-FINALS-G1": {
                "winner": "CHI",
            }
        },
        postseason_player_totals={
            wemby_id: {
                "games": 1,
            }
        },
    )
    mark_transition_fixture_preclosed(state)
    transition = advance_simulation_season(
        state,
        performance_signals={
            wemby_id: 0.45,
            curry_id: -0.45,
            jokic_id: 0.0,
        },
        development_config=DevelopmentConfig(
            random_seed=args.seed,
            random_variance_scale=0.55,
        ),
    )

    post = {
        player_id: {
            "age": state.players[player_id].age,
            "overall_rating": (
                state.players[
                    player_id
                ].overall_rating
            ),
            "points_factor": (
                state.players[
                    player_id
                ].stat_factors["points"]
            ),
            "assists_factor": (
                state.players[
                    player_id
                ].stat_factors["assists"]
            ),
            "blocks_factor": (
                state.players[
                    player_id
                ].stat_factors["blocks"]
            ),
        }
        for player_id in sample_ids.values()
    }

    # Verify that age remains cumulative across multiple committed league
    # years rather than being reloaded from the original 2026-27 profile.
    age_state = create_simulation_league_state(
        runtime,
        trade_state,
    )
    age_lebron_id = find_player_id(
        age_state,
        "LeBron James",
    )
    if not age_lebron_id:
        raise AssertionError(
            "LeBron James was not found for the multi-year age check."
        )
    source_lebron_age = float(
        age_state.players[age_lebron_id].age
    )
    for season_step in range(2):
        age_state.phase = LeaguePhase.OFFSEASON
        mark_transition_fixture_preclosed(age_state)
        advance_simulation_season(
            age_state,
            performance_signals={
                age_lebron_id: 0.0,
            },
            development_config=DevelopmentConfig(
                random_seed=args.seed + season_step + 100,
                random_variance_scale=0.0,
            ),
        )
    two_year_lebron_age = float(
        age_state.players[age_lebron_id].age
    )

    sas = state.players[
        wemby_id
    ].team_abbreviation
    gsw = state.players[
        curry_id
    ].team_abbreviation
    add_scheduled_games(
        state,
        [
            ScheduledGame(
                game_id="TRANSITION-TEST-0001",
                day_index=1,
                home_team=sas,
                away_team=gsw,
            )
        ],
    )
    game = simulate_scheduled_game(
        state,
        "TRANSITION-TEST-0001",
        seed=args.seed,
        commit=False,
    )
    config = GameSimulationConfig()

    state_wemby_block = (
        moderated_player_stat_factor(
            wemby_id,
            "blocks",
            state=state,
        )
    )
    static_wemby_block = (
        moderated_player_stat_factor(
            wemby_id,
            "blocks",
        )
    )
    state_curry_points = (
        moderated_player_stat_factor(
            curry_id,
            "points",
            state=state,
        )
    )
    static_curry_points = (
        moderated_player_stat_factor(
            curry_id,
            "points",
        )
    )

    checks = {
        "transition_version_is_current": (
            TRANSITION_VERSION
            == "simulation-season-transition-v1.1-2026-08-09"
        ),
        "validator_fixture_uses_modern_preclosed_transition_path": (
            all(
                getattr(
                    getattr(state.players[player_id], "contract", None),
                    "years_remaining",
                    None,
                )
                == years_before
                for player_id, years_before in preclosed_contract_years.items()
                if player_id in state.players
            )
            and {
                team_code: tuple(team_state.roster_player_ids)
                for team_code, team_state in state.teams.items()
            }
            == preclosed_rosters
            and tuple(sorted(state.free_agent_player_ids))
            == preclosed_free_agents
        ),
        "game_engine_reads_permanent_state": (
            GAME_ENGINE_VERSION
            == "single-game-simulator-v1.6-2026-08-08"
        ),
        "all_582_players_projected": (
            transition.players_projected == 582
        ),
        "season_advanced_to_2027_28": (
            transition.source_season
            == "2026-27"
            and transition.target_season
            == "2027-28"
            and state.settings.season_label
            == "2027-28"
        ),
        "transition_archive_created": (
            state.transition_count == 1
            and len(state.season_history) == 1
            and state.season_history[
                0
            ].season_label
            == "2026-27"
        ),
        "postseason_is_archived_completely": (
            state.season_history[0].champion == "CHI"
            and state.season_history[0].runner_up == "HOU"
            and state.season_history[0]
            .conference_champions
            == {
                "East": "CHI",
                "West": "HOU",
            }
            and state.season_history[0]
            .postseason_games_completed
            == 1
            and state.season_history[0]
            .postseason_state
            .champion
            == "CHI"
        ),
        "new_preseason_clears_live_postseason": (
            not hasattr(state, "postseason_state")
        ),
        "transition_result_reports_archived_finals": (
            transition.archived_champion == "CHI"
            and transition.archived_runner_up == "HOU"
            and transition.archived_postseason_games == 1
        ),
        "player_ages_advanced": all(
            math.isclose(
                float(post[player_id]["age"]),
                float(pre[player_id]["age"])
                + 1.0,
                abs_tol=1e-9,
            )
            for player_id in sample_ids.values()
        ),
        "player_age_is_cumulative_across_two_transitions": (
            age_state.settings.season_label == "2028-29"
            and age_state.transition_count == 2
            and math.isclose(
                two_year_lebron_age,
                source_lebron_age + 2.0,
                abs_tol=1e-9,
            )
            and len(
                age_state.players[
                    age_lebron_id
                ].development_history
            )
            == 2
        ),
        "wembanyama_improves": (
            post[wemby_id]["overall_rating"]
            > pre[wemby_id]["overall_rating"]
        ),
        "curry_declines": (
            post[curry_id]["overall_rating"]
            < pre[curry_id]["overall_rating"]
        ),
        "jokic_decline_is_controlled": (
            -1.75
            <= (
                post[jokic_id]["overall_rating"]
                - pre[jokic_id]["overall_rating"]
            )
            <= 0.25
        ),
        "state_stat_factors_changed": (
            post[wemby_id]["blocks_factor"]
            != pre[wemby_id]["blocks_factor"]
            and post[curry_id]["points_factor"]
            != pre[curry_id]["points_factor"]
        ),
        "simulator_uses_transitioned_wemby_factor": (
            math.isclose(
                state_wemby_block,
                1.0
                + 0.90
                * (
                    post[wemby_id][
                        "blocks_factor"
                    ]
                    - 1.0
                ),
                abs_tol=1e-9,
            )
            and not math.isclose(
                state_wemby_block,
                static_wemby_block,
                abs_tol=1e-6,
            )
        ),
        "simulator_uses_transitioned_curry_factor": (
            math.isclose(
                state_curry_points,
                1.0
                + 0.55
                * (
                    post[curry_id][
                        "points_factor"
                    ]
                    - 1.0
                ),
                abs_tol=1e-9,
            )
            and not math.isclose(
                state_curry_points,
                static_curry_points,
                abs_tol=1e-6,
            )
        ),
        "post_transition_game_has_winner": (
            game.game.home_score
            != game.game.away_score
        ),
        "post_transition_home_box_reconciles": (
            team_box_score_reconciles(
                game.game,
                game.game.home_team,
                regulation_minutes=(
                    config.regulation_minutes
                    if hasattr(
                        config,
                        "regulation_minutes",
                    )
                    else state.settings.regulation_minutes
                ),
                overtime_minutes=(
                    state.settings.overtime_minutes
                ),
            )
        ),
        "post_transition_away_box_reconciles": (
            team_box_score_reconciles(
                game.game,
                game.game.away_team,
                regulation_minutes=(
                    state.settings.regulation_minutes
                ),
                overtime_minutes=(
                    state.settings.overtime_minutes
                ),
            )
        ),
        "transitioned_state_remains_valid": bool(
            validate_simulation_league_state(
                state
            )
        ),
    }

    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]
    report = {
        "script": SCRIPT_VERSION,
        "transition": asdict(transition),
        "checks": checks,
        "failed_checks": failed,
        "sample_players": {
            name: {
                "before": pre[player_id],
                "after": post[player_id],
            }
            for name, player_id
            in sample_ids.items()
        },
        "simulator_factor_signals": {
            "wembanyama_static_block": (
                static_wemby_block
            ),
            "wembanyama_state_block": (
                state_wemby_block
            ),
            "curry_static_points": (
                static_curry_points
            ),
            "curry_state_points": (
                state_curry_points
            ),
        },
        "game": {
            "game_id": game.game.game_id,
            "home_team": game.game.home_team,
            "away_team": game.game.away_team,
            "home_score": game.game.home_score,
            "away_score": game.game.away_score,
            "engine": (
                game.metadata.engine_version
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

    print("=" * 88)
    print("SIMULATION SEASON TRANSITION VALIDATION")
    print("=" * 88)
    print(
        f"{transition.source_season} -> "
        f"{transition.target_season}"
    )
    print(
        f"Players projected: "
        f"{transition.players_projected}"
    )
    print(
        f"Average OVR delta: "
        f"{transition.average_overall_delta:+.3f}"
    )
    print(
        f"Improved: {transition.improved_players} | "
        f"Stable: {transition.stable_players} | "
        f"Declined: {transition.declined_players}"
    )
    print(
        f"Post-transition game: "
        f"{game.game.away_team} "
        f"{game.game.away_score}, "
        f"{game.game.home_team} "
        f"{game.game.home_score}"
    )

    print("\nSAMPLE PLAYERS")
    for name, player_id in sample_ids.items():
        print(
            f"{name:22s} | "
            f"age {pre[player_id]['age']:.0f}"
            f" -> {post[player_id]['age']:.0f} | "
            f"OVR "
            f"{pre[player_id]['overall_rating']:.2f}"
            f" -> "
            f"{post[player_id]['overall_rating']:.2f}"
        )

    print("\nCHECKS")
    for name, passed in checks.items():
        print(
            f"{'PASS' if passed else 'FAIL':4s}  "
            f"{name}"
        )

    print(f"\nReport: {REPORT_PATH}")

    if failed:
        print(
            "\nSIMULATION SEASON TRANSITION "
            "VALIDATION FAILED"
        )
        return 1

    print(
        "\nSIMULATION SEASON TRANSITION "
        "VALIDATION PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
