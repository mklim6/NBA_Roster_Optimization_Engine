from __future__ import annotations

import argparse
import json
import py_compile
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGES = ROOT / "pages"
OUTPUTS = ROOT / "outputs"
APP_DATA = ROOT / "app_data"
HOME = ROOT / "Home.py"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import (  # noqa: E402
    Status,
    load_runtime_data,
    normalize_player_id,
    normalize_team,
)
from league_scenario_store_v1 import (  # noqa: E402
    delete_scenario,
    list_scenarios,
    load_scenario,
    operational_signature,
    save_scenario,
)
from mutable_league_state_v1 import (  # noqa: E402
    apply_passed_trade,
    create_league_state,
    find_pass_player_trade,
    reset_league_state,
    undo_last_trade,
    validate_state,
)
from state_runtime_adapter_v1 import (  # noqa: E402
    build_state_runtime,
    validate_state_runtime,
)
from trade_mode_policy_v1 import (  # noqa: E402
    SandboxDisposition,
    TradeMode,
    apply_trade_in_mode,
    classify_trade,
    find_forceable_blocked_trade,
    find_missing_cba_manual_trade,
)
from simulation_roster_validator_v1 import (  # noqa: E402
    POSITION_DATA_PATH,
    VALIDATOR_VERSION as ROSTER_VALIDATOR_VERSION,
    build_simulation_roster_snapshot,
    load_position_records,
    snapshot_report,
)
from simulation_league_state_v1 import (  # noqa: E402
    create_simulation_league_state,
    initial_state_summary,
    validate_simulation_league_state,
)
from simulation_player_stat_profiles_v1 import (  # noqa: E402
    PROFILE_DATA_PATH,
    PROFILE_LOADER_VERSION,
    load_player_stat_profiles,
    player_id_by_name,
    player_stat_factor,
)
from single_game_simulator_v1 import (  # noqa: E402
    ENGINE_VERSION as GAME_ENGINE_VERSION,
    position_stat_multiplier,
    profile_adjusted_stat_multiplier,
    simulate_scheduled_game,
    team_box_score_reconciles,
)
from simulation_league_state_v1 import (  # noqa: E402
    ScheduledGame,
    add_scheduled_games,
)


VALIDATOR_VERSION = (
    "project-validation-runner-v1.15-2026-08-08"
)
QUICK_REPORT = (
    OUTPUTS / "project_validation_quick_v1.json"
)
FULL_REPORT = (
    OUTPUTS / "project_validation_full_v1.json"
)


class ProjectValidationError(RuntimeError):
    """Raised when a project validation check fails."""


def elapsed_seconds(started: float) -> float:
    return round(time.perf_counter() - started, 3)


def runtime_signature(runtime: Any) -> dict[str, Any]:
    return {
        "players": tuple(
            sorted(
                (
                    player_id,
                    normalize_team(
                        record.get(
                            "current_team_2026_27"
                        )
                    ),
                )
                for player_id, record in (
                    runtime.trade_by_id.items()
                )
            )
        ),
        "draft_rights": tuple(
            sorted(
                (
                    pick_right_id,
                    normalize_team(
                        record.get("candidate_team")
                    ),
                )
                for pick_right_id, record in (
                    runtime.pick_by_id.items()
                )
            )
        ),
        "team_salaries": tuple(
            sorted(
                (
                    team,
                    record.get(
                        "verified_team_salary_value"
                    ),
                    record.get(
                        (
                            "verified_apron_"
                            "team_salary_value"
                        )
                    ),
                    record.get("hard_cap_level"),
                )
                for team, record in (
                    runtime.team_cba_by_team.items()
                )
            )
        ),
    }


def record_check(
    checks: list[dict[str, Any]],
    *,
    phase: str,
    name: str,
    passed: bool,
    details: str = "",
    seconds: float = 0.0,
) -> None:
    checks.append(
        {
            "phase": phase,
            "name": name,
            "passed": bool(passed),
            "seconds": round(seconds, 3),
            "details": details,
        }
    )


def require(
    checks: list[dict[str, Any]],
    *,
    phase: str,
    name: str,
    condition: bool,
    details: str = "",
    seconds: float = 0.0,
) -> None:
    record_check(
        checks,
        phase=phase,
        name=name,
        passed=condition,
        details=details,
        seconds=seconds,
    )

    if not condition:
        raise ProjectValidationError(
            f"{phase}/{name} failed"
            + (f": {details}" if details else "")
        )


def python_sources() -> list[Path]:
    sources: list[Path] = []

    if HOME.exists():
        sources.append(HOME)

    if SRC.exists():
        sources.extend(
            sorted(SRC.glob("*.py"))
        )

    if PAGES.exists():
        sources.extend(
            sorted(PAGES.glob("*.py"))
        )

    return sources


def compile_project(
    checks: list[dict[str, Any]],
) -> None:
    started = time.perf_counter()
    sources = python_sources()
    failures: list[str] = []

    for path in sources:
        try:
            py_compile.compile(
                str(path),
                doraise=True,
            )
        except py_compile.PyCompileError as exc:
            failures.append(
                f"{path.relative_to(ROOT)}: {exc}"
            )

    require(
        checks,
        phase="compile",
        name="all_project_python_compiles",
        condition=not failures,
        details=(
            f"{len(sources)} file(s) checked"
            if not failures
            else " | ".join(failures)
        ),
        seconds=elapsed_seconds(started),
    )


def validate_required_files(
    checks: list[dict[str, Any]],
) -> None:
    required = [
        HOME,
        PAGES / "3_Trade_Machine.py",
        PAGES / "4_Game_Simulator.py",
        APP_DATA / "player_positions_2026_27_v1.json",
        APP_DATA
        / "simulation_player_stat_profiles_2026_27_v1.json",
        SRC / "build_player_positions_v1.py",
        SRC
        / "build_simulation_player_stat_profiles_v1.py",
        SRC
        / "diagnose_player_stat_profile_sources_v1.py",
        SRC / "simulation_player_stat_profiles_v1.py",
        SRC / "player_development_engine_v1.py",
        SRC / "validate_player_development_curves_v1.py",
        SRC / "simulation_season_transition_v1.py",
        SRC
        / "simulation_season_transition_controller_v1.py",
        SRC / "validate_simulation_season_transition_v1.py",
        SRC
        / "validate_game_simulator_season_management_ui_v1.py",
        SRC / "regular_season_schedule_v1.py",
        SRC / "validate_regular_season_schedule_v1.py",
        SRC
        / "regular_season_simulation_controller_v1.py",
        SRC
        / (
            "validate_regular_season_simulation_"
            "controller_v1.py"
        ),
        SRC / "simulation_module_bootstrap_v1.py",
        SRC / "franchise_calendar_v1.py",
        SRC / "validate_franchise_calendar_ui_v1.py",
        SRC / "validate_position_aware_game_stats_v4.py",
        SRC / "freeform_trade_machine_engine_v3.py",
        SRC / "mutable_league_state_v1.py",
        SRC / "state_runtime_adapter_v1.py",
        SRC / "league_scenario_store_v1.py",
        SRC / "trade_mode_policy_v1.py",
        SRC / "simulation_roster_validator_v1.py",
        SRC / "simulation_league_state_v1.py",
        SRC / "single_game_simulator_v1.py",
        SRC
        / "validate_mutable_league_state_integration_v1.py",
    ]
    missing = [
        str(path.relative_to(ROOT))
        for path in required
        if not path.exists()
    ]

    require(
        checks,
        phase="structure",
        name="required_foundation_files_exist",
        condition=not missing,
        details=(
            f"{len(required)} required file(s)"
            if not missing
            else "Missing: " + ", ".join(missing)
        ),
    )


def validate_ui_contract(
    checks: list[dict[str, Any]],
) -> None:
    page = PAGES / "3_Trade_Machine.py"
    text = page.read_text(encoding="utf-8")

    markers = {
        "mutable_state_panel": (
            "trade_machine_league_state"
        ),
        "stale_audit_guard": "audited_revision",
        "same_team_guard": (
            "disabled=(team_a == team_b)"
        ),
        "revision_widget_keys": (
            "r{league_state.state_revision}"
        ),
        "scenario_save": "Save current league",
        "scenario_load": "Load scenario",
        "scenario_export": "Export scenario JSON",
        "scenario_import": "Import and load scenario",
        "scenario_delete": (
            "trade_machine_delete_scenario"
        ),
        "unsaved_changes_label": "unsaved changes",
        "sandbox_mode_selector": "Sandbox Mode",
        "realism_mode_selector": "Realism Mode",
        "sandbox_apply": "Apply sandbox trade",
        "force_trade": "Force trade",
        "mode_policy_session": (
            "trade_machine_last_policy"
        ),
        "mode_policy_apply": "apply_trade_in_mode",
    }

    missing = [
        name
        for name, marker in markers.items()
        if marker not in text
    ]

    require(
        checks,
        phase="ui_contract",
        name="trade_machine_foundation_markers_present",
        condition=not missing,
        details=(
            f"{len(markers)} marker(s)"
            if not missing
            else "Missing: " + ", ".join(missing)
        ),
    )

    gitignore = ROOT / ".gitignore"
    ignored = (
        gitignore.exists()
        and (
            "app_data/league_scenarios/*.json"
            in gitignore.read_text(
                encoding="utf-8"
            )
        )
    )
    require(
        checks,
        phase="ui_contract",
        name="scenario_json_files_are_gitignored",
        condition=ignored,
        details=(
            "Scenario ignore rule present"
            if ignored
            else (
                "Missing app_data/league_scenarios/"
                "*.json from .gitignore"
            )
        ),
    )

    simulator_page = PAGES / "4_Game_Simulator.py"
    simulator_text = simulator_page.read_text(
        encoding="utf-8"
    )
    simulator_markers = {
        "shared_simulation_state": (
            "game_simulator_league_state"
        ),
        "position_refresh_signature": (
            "game_simulator_position_signature"
        ),
        "direct_position_application": (
            "apply_latest_player_positions"
        ),
        "local_validator_loader": (
            "load_local_roster_validator"
        ),
        "unlocked_seed_control": "Lock seed",
        "fresh_seed_copy": (
            "Fresh result each time you click Simulate game."
        ),
        "pregame_win_chance": (
            'f"Pregame {home_team} win chance"'
        ),
        "top_performers_tab": '"Top Performers"',
        "top_performers_steals": '"STL": line.steals',
        "top_performers_blocks": '"BLK": line.blocks',
        "top_performers_turnovers": (
            '"TO": line.turnovers'
        ),
        "top_performers_fouls": '"PF": line.fouls',
        "total_schedule_entries": (
            '"Total schedule entries"'
        ),
        "season_management_controller": (
            "simulation_season_transition_controller_v1"
        ),
        "season_transition_preview": (
            "build_season_transition_preview"
        ),
        "season_transition_commit": (
            "commit_season_transition_preview"
        ),
        "season_transition_confirmation": (
            "I understand this archives"
        ),
        "season_transition_risers": (
            '"Biggest Risers"'
        ),
        "season_transition_fallers": (
            '"Biggest Fallers"'
        ),
        "archived_season_history": (
            "Archived season history"
        ),
        "transition_state_freshness_guard": (
            "preview_matches_state"
        ),
        "simulation_module_bootstrap": (
            "from simulation_module_bootstrap_v1 import"
        ),
        "simulation_module_bootstrap_call": (
            "ensure_current_simulation_modules()"
        ),
        "franchise_calendar_backend": (
            "from franchise_calendar_v1 import"
        ),
        "controlled_team_selection": (
            '"game_simulator_controlled_teams"'
        ),
        "calendar_month_grid": (
            "build_team_month_calendar"
        ),
        "generated_schedule_install": (
            "install_regular_season_schedule"
        ),
        "calendar_game_preparation": (
            "Prepare matchup"
        ),
        "calendar_next_day": (
            "Sim next day"
        ),
        "calendar_next_week": (
            "Sim next week"
        ),
        "calendar_remainder": (
            "Sim to season end"
        ),
        "controlled_team_pause": (
            "controlled_team_pause"
        ),
        "scheduled_game_mode": (
            '"existing_schedule_game"'
        ),
        "stretch_width_api": 'width="stretch"',
    }
    missing_simulator_markers = [
        name
        for name, marker in simulator_markers.items()
        if marker not in simulator_text
    ]

    require(
        checks,
        phase="ui_contract",
        name="game_simulator_markers_present",
        condition=not missing_simulator_markers,
        details=(
            f"{len(simulator_markers)} marker(s)"
            if not missing_simulator_markers
            else (
                "Missing: "
                + ", ".join(missing_simulator_markers)
            )
        ),
    )
    require(
        checks,
        phase="ui_contract",
        name="game_simulator_uses_current_width_api",
        condition=(
            "use_container_width" not in simulator_text
        ),
        details=(
            "No deprecated use_container_width calls"
            if "use_container_width" not in simulator_text
            else (
                "Deprecated use_container_width remains "
                "in pages/4_Game_Simulator.py"
            )
        ),
    )


def quick_runtime_validation(
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    started = time.perf_counter()
    runtime = load_runtime_data()
    load_seconds = elapsed_seconds(started)

    require(
        checks,
        phase="runtime",
        name="base_runtime_loaded",
        condition=(
            len(runtime.trade_by_id) > 0
            and len(runtime.pick_by_id) > 0
            and len(runtime.team_cba_by_team) == 30
        ),
        details=(
            f"players={len(runtime.trade_by_id)}; "
            f"draft_rights={len(runtime.pick_by_id)}; "
            f"teams={len(runtime.team_cba_by_team)}"
        ),
        seconds=load_seconds,
    )

    base_signature_before = runtime_signature(runtime)
    state = create_league_state(runtime)

    state_checks = validate_state(
        state,
        runtime,
    )
    require(
        checks,
        phase="runtime",
        name="initial_mutable_state_valid",
        condition=all(state_checks.values()),
        details=(
            "all checks passed"
            if all(state_checks.values())
            else ", ".join(
                name
                for name, passed
                in state_checks.items()
                if not passed
            )
        ),
    )

    adapted_initial = build_state_runtime(
        runtime,
        state,
    )
    adapter_checks = validate_state_runtime(
        runtime,
        adapted_initial,
        state,
    )
    require(
        checks,
        phase="runtime",
        name="initial_state_runtime_adapter_valid",
        condition=all(adapter_checks.values()),
        details=(
            "all checks passed"
            if all(adapter_checks.values())
            else ", ".join(
                name
                for name, passed
                in adapter_checks.items()
                if not passed
            )
        ),
    )

    roster_started = time.perf_counter()
    roster_snapshot = build_simulation_roster_snapshot(
        adapted_initial,
        state,
    )
    roster_report = snapshot_report(
        roster_snapshot
    )

    require(
        checks,
        phase="simulation_rosters",
        name="all_30_teams_ready_for_game",
        condition=(
            roster_snapshot.ready
            and len(roster_snapshot.teams) == 30
            and roster_report["summary"]["ready_teams"] == 30
        ),
        details=(
            f"ready={roster_report['summary']['ready_teams']}; "
            f"teams={roster_report['summary']['teams']}"
        ),
        seconds=elapsed_seconds(roster_started),
    )
    require(
        checks,
        phase="simulation_rosters",
        name="baseline_needs_no_emergency_replacements",
        condition=(
            roster_report["summary"]["replacement_players"] == 0
        ),
        details=(
            "replacement_players="
            f"{roster_report['summary']['replacement_players']}"
        ),
    )
    require(
        checks,
        phase="simulation_rosters",
        name="baseline_has_no_missing_ratings",
        condition=(
            roster_report["summary"]["fallback_rating_players"] == 0
        ),
        details=(
            "fallback_rating_players="
            f"{roster_report['summary']['fallback_rating_players']}"
        ),
    )

    position_records = load_position_records()
    real_roster_players = [
        player
        for roster in roster_snapshot.teams.values()
        for player in roster.real_players
    ]
    unresolved_positions = [
        f"{player.player_name} ({player.player_id})"
        for player in real_roster_players
        if player.position == "UNK"
    ]
    require(
        checks,
        phase="simulation_rosters",
        name="position_layer_covers_runtime_players",
        condition=(
            POSITION_DATA_PATH.exists()
            and len(position_records)
            >= len(runtime.ratings_by_id)
        ),
        details=(
            f"validator={ROSTER_VALIDATOR_VERSION}; "
            f"records={len(position_records)}; "
            f"runtime_players={len(runtime.ratings_by_id)}; "
            f"path={POSITION_DATA_PATH.relative_to(ROOT)}"
        ),
    )
    require(
        checks,
        phase="simulation_rosters",
        name="all_real_roster_players_have_positions",
        condition=not unresolved_positions,
        details=(
            f"resolved={len(real_roster_players)}"
            if not unresolved_positions
            else (
                f"unresolved={len(unresolved_positions)}; "
                + ", ".join(unresolved_positions[:8])
            )
        ),
    )

    player_profiles = load_player_stat_profiles()
    profile_position_mismatches = [
        player_id
        for player_id, profile
        in player_profiles.items()
        if (
            player_id not in position_records
            or str(
                position_records[player_id].get(
                    "position"
                )
                or ""
            ).strip().upper()
            != str(
                profile.get("position") or ""
            ).strip().upper()
        )
    ]
    require(
        checks,
        phase="player_profiles",
        name="player_stat_profile_layer_covers_runtime",
        condition=(
            PROFILE_DATA_PATH.exists()
            and len(player_profiles) == 582
            and set(player_profiles)
            == set(runtime.ratings_by_id)
        ),
        details=(
            f"loader={PROFILE_LOADER_VERSION}; "
            f"profiles={len(player_profiles)}; "
            f"runtime_players={len(runtime.ratings_by_id)}"
        ),
    )
    require(
        checks,
        phase="player_profiles",
        name="player_stat_profiles_match_positions",
        condition=not profile_position_mismatches,
        details=(
            "582 profile positions match"
            if not profile_position_mismatches
            else (
                "mismatched="
                f"{len(profile_position_mismatches)}; "
                + ", ".join(
                    profile_position_mismatches[:8]
                )
            )
        ),
    )

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
    require(
        checks,
        phase="player_profiles",
        name="player_specific_exception_signals_present",
        condition=bool(
            jokic_id
            and curry_id
            and wemby_id
            and player_stat_factor(
                jokic_id,
                "assists",
            )
            >= 2.50
            and player_stat_factor(
                jokic_id,
                "rebounds",
            )
            >= 1.05
            and player_stat_factor(
                wemby_id,
                "blocks",
            )
            >= 2.00
        ),
        details=(
            f"Jokic AST="
            f"{player_stat_factor(jokic_id, 'assists') if jokic_id else 'missing'}; "
            f"Jokic REB="
            f"{player_stat_factor(jokic_id, 'rebounds') if jokic_id else 'missing'}; "
            f"Wemby BLK="
            f"{player_stat_factor(wemby_id, 'blocks') if wemby_id else 'missing'}"
        ),
    )

    simulation_state_started = time.perf_counter()
    simulation_state = create_simulation_league_state(
        adapted_initial,
        state,
    )
    simulation_checks = (
        validate_simulation_league_state(
            simulation_state
        )
    )
    simulation_summary = initial_state_summary(
        simulation_state
    )

    require(
        checks,
        phase="simulation_state",
        name="simulation_league_state_valid",
        condition=all(simulation_checks.values()),
        details=(
            f"teams={simulation_summary['teams']}; "
            f"players={simulation_summary['players']}; "
            f"free_agents={simulation_summary['free_agents']}"
        ),
        seconds=elapsed_seconds(
            simulation_state_started
        ),
    )
    require(
        checks,
        phase="simulation_state",
        name="simulation_player_population_reconciles",
        condition=(
            simulation_summary["players"] == 582
            and simulation_summary["rostered_players"] == 395
            and simulation_summary["free_agents"] == 187
            and simulation_summary["synthetic_players"] == 0
        ),
        details=(
            f"players={simulation_summary['players']}; "
            f"rostered={simulation_summary['rostered_players']}; "
            f"free_agents={simulation_summary['free_agents']}; "
            f"synthetic={simulation_summary['synthetic_players']}"
        ),
    )
    state_unresolved_positions = [
        f"{player.player_name} ({player.player_id})"
        for player in simulation_state.players.values()
        if not player.synthetic
        and player.position == "UNK"
    ]
    require(
        checks,
        phase="simulation_state",
        name="permanent_state_preserves_positions",
        condition=not state_unresolved_positions,
        details=(
            f"resolved={len(simulation_state.players)}"
            if not state_unresolved_positions
            else (
                f"unresolved={len(state_unresolved_positions)}; "
                + ", ".join(state_unresolved_positions[:8])
            )
        ),
    )
    require(
        checks,
        phase="simulation_state",
        name="simulation_starts_clean",
        condition=(
            simulation_summary["scheduled_games"] == 0
            and simulation_summary["completed_games"] == 0
            and simulation_summary["phase"] == "preseason"
        ),
        details=(
            f"scheduled={simulation_summary['scheduled_games']}; "
            f"completed={simulation_summary['completed_games']}; "
            f"phase={simulation_summary['phase']}"
        ),
    )

    game_started = time.perf_counter()
    game_teams = sorted(simulation_state.teams)
    preview_state_signature = {
        "completed_games": len(
            simulation_state.completed_games
        ),
        "games_played": sum(
            standing.games_played
            for standing in simulation_state.standings.values()
        ),
    }
    add_scheduled_games(
        simulation_state,
        [
            ScheduledGame(
                game_id="QUICK-SIM-0001",
                day_index=1,
                home_team=game_teams[0],
                away_team=game_teams[1],
            )
        ],
    )
    preview = simulate_scheduled_game(
        simulation_state,
        "QUICK-SIM-0001",
        seed=20260808,
        commit=False,
    )
    preview_signature_after = {
        "completed_games": len(
            simulation_state.completed_games
        ),
        "games_played": sum(
            standing.games_played
            for standing in simulation_state.standings.values()
        ),
    }

    require(
        checks,
        phase="single_game",
        name="preview_simulation_reconciles",
        condition=(
            preview.game.home_score
            != preview.game.away_score
            and team_box_score_reconciles(
                preview.game,
                preview.game.home_team,
                regulation_minutes=(
                    simulation_state.settings.regulation_minutes
                ),
                overtime_minutes=(
                    simulation_state.settings.overtime_minutes
                ),
            )
            and team_box_score_reconciles(
                preview.game,
                preview.game.away_team,
                regulation_minutes=(
                    simulation_state.settings.regulation_minutes
                ),
                overtime_minutes=(
                    simulation_state.settings.overtime_minutes
                ),
            )
        ),
        details=(
            f"{preview.game.away_team} "
            f"{preview.game.away_score}, "
            f"{preview.game.home_team} "
            f"{preview.game.home_score}"
        ),
        seconds=elapsed_seconds(game_started),
    )
    require(
        checks,
        phase="single_game",
        name="preview_simulation_does_not_mutate_results",
        condition=(
            preview_state_signature
            == preview_signature_after
        ),
        details=(
            "completed_games=0; standings_games=0"
        ),
    )

    require(
        checks,
        phase="single_game",
        name="position_aware_stat_engine_active",
        condition=(
            GAME_ENGINE_VERSION
            == "single-game-simulator-v1.4-2026-08-08"
            and position_stat_multiplier(
                "C",
                "rebounds",
            )
            > position_stat_multiplier(
                "PG",
                "rebounds",
            )
            and position_stat_multiplier(
                "PG",
                "assists",
            )
            > position_stat_multiplier(
                "C",
                "assists",
            )
            and position_stat_multiplier(
                "C",
                "blocks",
            )
            > position_stat_multiplier(
                "PG",
                "blocks",
            )
            and position_stat_multiplier(
                "PG/SG",
                "blocks",
            )
            > 0.30
            and jokic_id
            and curry_id
            and profile_adjusted_stat_multiplier(
                jokic_id,
                player_profiles[jokic_id][
                    "position"
                ],
                "assists",
            )
            > profile_adjusted_stat_multiplier(
                curry_id,
                player_profiles[curry_id][
                    "position"
                ],
                "assists",
            )
        ),
        details=(
            f"{GAME_ENGINE_VERSION}; "
            f"Jokic adjusted AST="
            f"{profile_adjusted_stat_multiplier(jokic_id, player_profiles[jokic_id]['position'], 'assists') if jokic_id else 'missing'}; "
            f"Curry adjusted AST="
            f"{profile_adjusted_stat_multiplier(curry_id, player_profiles[curry_id]['position'], 'assists') if curry_id else 'missing'}"
        ),
    )

    preview_lines_by_team = {
        team: [
            line
            for line in preview.game.player_box_scores
            if line.team_abbreviation == team
        ]
        for team in (
            preview.game.home_team,
            preview.game.away_team,
        )
    }
    plausible_secondary_totals = all(
        30 <= sum(
            line.rebounds
            for line in lines
        ) <= 60
        and 2 <= sum(
            line.steals
            for line in lines
        ) <= 16
        and 0 <= sum(
            line.blocks
            for line in lines
        ) <= 14
        and 6 <= sum(
            line.turnovers
            for line in lines
        ) <= 24
        and 9 <= sum(
            line.fouls
            for line in lines
        ) <= 30
        and sum(
            line.assists
            for line in lines
        )
        <= sum(
            line.field_goals_made
            for line in lines
        )
        for lines in preview_lines_by_team.values()
    )
    secondary_details = "; ".join(
        (
            f"{team}: "
            f"REB={sum(line.rebounds for line in lines)}, "
            f"AST={sum(line.assists for line in lines)}, "
            f"STL={sum(line.steals for line in lines)}, "
            f"BLK={sum(line.blocks for line in lines)}, "
            f"TO={sum(line.turnovers for line in lines)}, "
            f"PF={sum(line.fouls for line in lines)}"
        )
        for team, lines in preview_lines_by_team.items()
    )
    require(
        checks,
        phase="single_game",
        name="position_aware_team_totals_are_plausible",
        condition=plausible_secondary_totals,
        details=secondary_details,
    )

    committed = simulate_scheduled_game(
        simulation_state,
        "QUICK-SIM-0001",
        seed=20260808,
        commit=True,
    )
    require(
        checks,
        phase="single_game",
        name="committed_simulation_updates_state",
        condition=(
            committed.game == preview.game
            and len(
                simulation_state.completed_games
            )
            == 1
            and sum(
                standing.games_played
                for standing
                in simulation_state.standings.values()
            )
            == 2
        ),
        details=(
            f"game_id={committed.game.game_id}; "
            f"completed={len(simulation_state.completed_games)}"
        ),
    )

    trade_started = time.perf_counter()
    request, result = find_pass_player_trade(
        adapted_initial
    )
    require(
        checks,
        phase="transaction",
        name="deterministic_pass_trade_found",
        condition=result.status == Status.PASS,
        details=(
            f"{request.side_a.team_abbreviation} ↔ "
            f"{request.side_b.team_abbreviation}; "
            f"status={result.status.value}"
        ),
        seconds=elapsed_seconds(trade_started),
    )

    verified_policy = classify_trade(
        adapted_initial,
        request,
        mode=TradeMode.SANDBOX,
    )
    require(
        checks,
        phase="trade_modes",
        name="strict_pass_remains_sandbox_verified",
        condition=(
            verified_policy.disposition
            == SandboxDisposition.VERIFIED
            and verified_policy.can_apply_without_force
            and not verified_policy.force_allowed
        ),
        details=verified_policy.verification_label,
    )

    manual_request, manual_policy = (
        find_missing_cba_manual_trade(
            adapted_initial
        )
    )
    require(
        checks,
        phase="trade_modes",
        name="missing_cba_trade_is_playable_with_warning",
        condition=(
            manual_policy.disposition
            == SandboxDisposition.PLAYABLE_WITH_WARNING
            and manual_policy.can_apply_without_force
            and "player_cba_evidence_missing"
            in manual_policy.manual_review_codes
        ),
        details=(
            f"{manual_request.side_a.team_abbreviation} ↔ "
            f"{manual_request.side_b.team_abbreviation}"
        ),
    )

    sandbox_state = create_league_state(runtime)
    sandbox_runtime = build_state_runtime(
        runtime,
        sandbox_state,
    )
    sandbox_applied = apply_trade_in_mode(
        sandbox_state,
        sandbox_runtime,
        manual_request,
        mode=TradeMode.SANDBOX,
    )
    sandbox_adapted = build_state_runtime(
        runtime,
        sandbox_state,
    )
    require(
        checks,
        phase="trade_modes",
        name="sandbox_warning_trade_mutates_valid_state",
        condition=(
            sandbox_applied.transaction.transaction_id
            == "TXN-0001"
            and all(
                validate_state(
                    sandbox_state,
                    runtime,
                ).values()
            )
            and all(
                validate_state_runtime(
                    runtime,
                    sandbox_adapted,
                    sandbox_state,
                ).values()
            )
        ),
        details=(
            sandbox_applied.policy.verification_label
        ),
    )

    force_request, force_policy = (
        find_forceable_blocked_trade(
            adapted_initial
        )
    )
    require(
        checks,
        phase="trade_modes",
        name="nonstructural_block_requires_force",
        condition=(
            force_policy.disposition
            == SandboxDisposition.FORCE_REQUIRED
            and force_policy.requires_force
            and force_policy.force_allowed
            and not force_policy.structural_codes
        ),
        details=(
            f"{force_request.side_a.team_abbreviation} ↔ "
            f"{force_request.side_b.team_abbreviation}"
        ),
    )

    record = apply_passed_trade(
        state,
        adapted_initial,
        request,
        result,
    )
    adapted_after_trade = build_state_runtime(
        runtime,
        state,
    )

    team_a = normalize_team(
        request.side_a.team_abbreviation
    )
    team_b = normalize_team(
        request.side_b.team_abbreviation
    )
    moved_players = (
        all(
            state.player_team_by_id[
                normalize_player_id(player_id)
            ]
            == team_b
            for player_id
            in request.side_a.player_ids
        )
        and all(
            state.player_team_by_id[
                normalize_player_id(player_id)
            ]
            == team_a
            for player_id
            in request.side_b.player_ids
        )
    )

    require(
        checks,
        phase="transaction",
        name="passed_trade_mutates_rosters",
        condition=moved_players,
        details=record.transaction_id,
    )

    posttrade_checks = validate_state_runtime(
        runtime,
        adapted_after_trade,
        state,
    )
    require(
        checks,
        phase="transaction",
        name="runtime_valid_after_trade",
        condition=all(posttrade_checks.values()),
        details=(
            f"revision={state.state_revision}; "
            f"transactions={len(state.transaction_history)}"
        ),
    )

    scenario_summary: dict[str, Any] = {}

    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )
    with tempfile.TemporaryDirectory(
        prefix="project_validation_quick_",
        dir=OUTPUTS,
    ) as temporary:
        directory = Path(temporary)
        saved = save_scenario(
            state,
            runtime,
            "Quick Validation Universe",
            notes=(
                "Temporary project validation scenario."
            ),
            directory=directory,
        )
        loaded, loaded_summary = load_scenario(
            saved.name,
            runtime,
            directory=directory,
        )

        require(
            checks,
            phase="scenario",
            name="scenario_round_trip_exact",
            condition=(
                operational_signature(loaded)
                == operational_signature(state)
            ),
            details=loaded_summary.name,
        )

        listed = list_scenarios(
            runtime,
            directory=directory,
        )
        require(
            checks,
            phase="scenario",
            name="scenario_library_lists_saved_universe",
            condition=(
                len(listed) == 1
                and listed[0].valid
                and listed[0].name
                == "Quick Validation Universe"
            ),
            details=f"listed={len(listed)}",
        )

        removed = undo_last_trade(
            loaded,
            runtime,
        )
        require(
            checks,
            phase="scenario",
            name="loaded_undo_stack_operates",
            condition=(
                removed.transaction_id
                == record.transaction_id
                and not loaded.transaction_history
            ),
            details=removed.transaction_id,
        )

        loaded_again, _ = load_scenario(
            saved.name,
            runtime,
            directory=directory,
        )
        before_reset_revision = (
            loaded_again.state_revision
        )
        reset_league_state(
            loaded_again,
            runtime,
        )
        require(
            checks,
            phase="scenario",
            name="loaded_reset_operates",
            condition=(
                not loaded_again.transaction_history
                and not loaded_again.undo_stack
                and loaded_again.state_revision
                == before_reset_revision + 1
                and all(
                    validate_state(
                        loaded_again,
                        runtime,
                    ).values()
                )
            ),
            details=(
                f"revision={loaded_again.state_revision}"
            ),
        )

        deleted = delete_scenario(
            saved.name,
            directory=directory,
        )
        require(
            checks,
            phase="scenario",
            name="scenario_delete_operates",
            condition=not deleted.exists(),
            details=deleted.name,
        )

        scenario_summary = asdict(loaded_summary)

    require(
        checks,
        phase="immutability",
        name="base_runtime_not_mutated",
        condition=(
            runtime_signature(runtime)
            == base_signature_before
        ),
        details="Static runtime signature unchanged",
    )

    return {
        "trade": {
            "transaction_id": record.transaction_id,
            "team_a": team_a,
            "team_b": team_b,
            "side_a_player_ids": list(
                request.side_a.player_ids
            ),
            "side_b_player_ids": list(
                request.side_b.player_ids
            ),
        },
        "scenario": scenario_summary,
        "trade_modes": {
            "verified_label": (
                verified_policy.verification_label
            ),
            "manual_warning_matchup": (
                f"{manual_request.side_a.team_abbreviation} ↔ "
                f"{manual_request.side_b.team_abbreviation}"
            ),
            "force_matchup": (
                f"{force_request.side_a.team_abbreviation} ↔ "
                f"{force_request.side_b.team_abbreviation}"
            ),
        },
        "simulation_rosters": roster_report["summary"],
        "player_stat_profiles": {
            "loader_version": PROFILE_LOADER_VERSION,
            "profiles": len(player_profiles),
            "jokic_assist_factor": (
                player_stat_factor(
                    jokic_id,
                    "assists",
                )
                if jokic_id
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
        },
        "simulation_state": {
            "teams": simulation_summary["teams"],
            "players": simulation_summary["players"],
            "rostered_players": (
                simulation_summary["rostered_players"]
            ),
            "free_agents": simulation_summary["free_agents"],
            "synthetic_players": (
                simulation_summary["synthetic_players"]
            ),
            "phase": simulation_summary["phase"],
        },
        "single_game": {
            "game_id": committed.game.game_id,
            "home_team": committed.game.home_team,
            "away_team": committed.game.away_team,
            "home_score": committed.game.home_score,
            "away_score": committed.game.away_score,
            "overtime_periods": (
                committed.game.overtime_periods
            ),
        },
    }


def run_subprocess_suite(
    checks: list[dict[str, Any]],
    *,
    name: str,
    command: list[str],
) -> None:
    started = time.perf_counter()
    print(
        "\n"
        + "=" * 88
        + f"\nRUNNING FULL SUITE: {name}\n"
        + "=" * 88
    )
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
    )
    seconds = elapsed_seconds(started)

    require(
        checks,
        phase="full_suite",
        name=name,
        condition=completed.returncode == 0,
        details=(
            "exit_code="
            f"{completed.returncode}; "
            f"command={' '.join(command)}"
        ),
        seconds=seconds,
    )


def run_quick() -> dict[str, Any]:
    started = time.perf_counter()
    checks: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}

    validate_required_files(checks)
    compile_project(checks)
    validate_ui_contract(checks)
    summary = quick_runtime_validation(checks)

    failed = [
        check
        for check in checks
        if not check["passed"]
    ]
    report = {
        "script": VALIDATOR_VERSION,
        "mode": "quick",
        "elapsed_seconds": elapsed_seconds(started),
        "checks": checks,
        "failed_checks": failed,
        "summary": summary,
        "passed": not failed,
    }

    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )
    QUICK_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
        ),
        encoding="utf-8",
    )

    if failed:
        raise ProjectValidationError(
            "Quick project validation failed."
        )

    return report


def run_full() -> dict[str, Any]:
    started = time.perf_counter()
    quick_report = run_quick()
    checks = list(quick_report["checks"])

    run_subprocess_suite(
        checks,
        name="trade_machine_v3_integration",
        command=[
            sys.executable,
            str(
                SRC
                / (
                    "validate_trade_machine_"
                    "v3_integration_v1.py"
                )
            ),
            "--sample-size",
            "500",
        ],
    )
    run_subprocess_suite(
        checks,
        name="mutable_league_state_integration",
        command=[
            sys.executable,
            str(
                SRC
                / (
                    "validate_mutable_league_"
                    "state_integration_v1.py"
                )
            ),
        ],
    )
    run_subprocess_suite(
        checks,
        name="scenario_store_self_test",
        command=[
            sys.executable,
            str(
                SRC / "league_scenario_store_v1.py"
            ),
            "--self-test",
        ],
    )
    run_subprocess_suite(
        checks,
        name="trade_mode_policy_self_test",
        command=[
            sys.executable,
            str(
                SRC / "trade_mode_policy_v1.py"
            ),
            "--self-test",
        ],
    )
    run_subprocess_suite(
        checks,
        name="simulation_roster_validator_self_test",
        command=[
            sys.executable,
            str(
                SRC / "simulation_roster_validator_v1.py"
            ),
            "--self-test",
        ],
    )
    run_subprocess_suite(
        checks,
        name="simulation_league_state_self_test",
        command=[
            sys.executable,
            str(
                SRC / "simulation_league_state_v1.py"
            ),
            "--self-test",
        ],
    )
    run_subprocess_suite(
        checks,
        name="player_stat_profile_builder_self_test",
        command=[
            sys.executable,
            str(
                SRC
                / "build_simulation_player_stat_profiles_v1.py"
            ),
            "--self-test",
        ],
    )
    run_subprocess_suite(
        checks,
        name="player_stat_profile_loader_self_test",
        command=[
            sys.executable,
            str(
                SRC
                / "simulation_player_stat_profiles_v1.py"
            ),
            "--self-test",
        ],
    )
    run_subprocess_suite(
        checks,
        name="player_development_engine_self_test",
        command=[
            sys.executable,
            str(
                SRC / "player_development_engine_v1.py"
            ),
            "--self-test",
        ],
    )
    run_subprocess_suite(
        checks,
        name="player_development_curve_validation",
        command=[
            sys.executable,
            str(
                SRC
                / "validate_player_development_curves_v1.py"
            ),
            "--seed",
            "20260808",
            "--variance-scale",
            "0.55",
        ],
    )
    run_subprocess_suite(
        checks,
        name="simulation_season_transition_self_test",
        command=[
            sys.executable,
            str(
                SRC
                / "simulation_season_transition_v1.py"
            ),
            "--self-test",
        ],
    )
    run_subprocess_suite(
        checks,
        name="simulation_season_transition_validation",
        command=[
            sys.executable,
            str(
                SRC
                / "validate_simulation_season_transition_v1.py"
            ),
            "--seed",
            "20260808",
        ],
    )
    run_subprocess_suite(
        checks,
        name="season_transition_controller_self_test",
        command=[
            sys.executable,
            str(
                SRC
                / (
                    "simulation_season_transition_"
                    "controller_v1.py"
                )
            ),
            "--self-test",
        ],
    )
    run_subprocess_suite(
        checks,
        name="season_management_ui_validation",
        command=[
            sys.executable,
            str(
                SRC
                / (
                    "validate_game_simulator_"
                    "season_management_ui_v1.py"
                )
            ),
        ],
    )
    run_subprocess_suite(
        checks,
        name="regular_season_schedule_self_test",
        command=[
            sys.executable,
            str(
                SRC
                / "regular_season_schedule_v1.py"
            ),
            "--self-test",
            "--seed",
            "20260808",
        ],
    )
    run_subprocess_suite(
        checks,
        name="regular_season_schedule_validation",
        command=[
            sys.executable,
            str(
                SRC
                / "validate_regular_season_schedule_v1.py"
            ),
            "--seed",
            "20260808",
        ],
    )
    run_subprocess_suite(
        checks,
        name=(
            "regular_season_simulation_"
            "controller_self_test"
        ),
        command=[
            sys.executable,
            str(
                SRC
                / (
                    "regular_season_simulation_"
                    "controller_v1.py"
                )
            ),
            "--self-test",
            "--seed",
            "20260808",
        ],
    )
    run_subprocess_suite(
        checks,
        name=(
            "regular_season_simulation_"
            "controller_validation"
        ),
        command=[
            sys.executable,
            str(
                SRC
                / (
                    "validate_regular_season_"
                    "simulation_controller_v1.py"
                )
            ),
            "--seed",
            "20260808",
        ],
    )
    run_subprocess_suite(
        checks,
        name="simulation_module_bootstrap_self_test",
        command=[
            sys.executable,
            str(
                SRC / "simulation_module_bootstrap_v1.py"
            ),
            "--self-test",
        ],
    )
    run_subprocess_suite(
        checks,
        name="franchise_calendar_self_test",
        command=[
            sys.executable,
            str(
                SRC / "franchise_calendar_v1.py"
            ),
            "--self-test",
            "--seed",
            "20260808",
        ],
    )
    run_subprocess_suite(
        checks,
        name="franchise_calendar_ui_validation",
        command=[
            sys.executable,
            str(
                SRC
                / "validate_franchise_calendar_ui_v1.py"
            ),
        ],
    )
    run_subprocess_suite(
        checks,
        name="single_game_simulator_self_test",
        command=[
            sys.executable,
            str(
                SRC / "single_game_simulator_v1.py"
            ),
            "--self-test",
        ],
    )
    run_subprocess_suite(
        checks,
        name="player_specific_game_stat_validation",
        command=[
            sys.executable,
            str(
                SRC
                / "validate_position_aware_game_stats_v4.py"
            ),
            "--games",
            "180",
            "--seed",
            "20260808",
        ],
    )

    failed = [
        check
        for check in checks
        if not check["passed"]
    ]
    report = {
        "script": VALIDATOR_VERSION,
        "mode": "full",
        "elapsed_seconds": elapsed_seconds(started),
        "checks": checks,
        "failed_checks": failed,
        "quick_summary": quick_report["summary"],
        "passed": not failed,
    }

    FULL_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
        ),
        encoding="utf-8",
    )

    if failed:
        raise ProjectValidationError(
            "Full project validation failed."
        )

    return report


def print_report(report: dict[str, Any]) -> None:
    print("\n" + "=" * 88)
    print(
        f"PROJECT VALIDATION: "
        f"{report['mode'].upper()}"
    )
    print("=" * 88)

    for check in report["checks"]:
        status = (
            "PASS"
            if check["passed"]
            else "FAIL"
        )
        print(
            f"{status:<4}  "
            f"{check['phase']:<16}  "
            f"{check['name']:<45}  "
            f"{check['seconds']:>8.3f}s"
        )
        if check["details"]:
            print(
                "      "
                + str(check["details"])
            )

    print("-" * 88)
    print(
        f"Checks: {len(report['checks'])} | "
        f"Failed: {len(report['failed_checks'])} | "
        f"Elapsed: "
        f"{report['elapsed_seconds']:.3f}s"
    )

    if report["passed"]:
        print(
            "\nPROJECT VALIDATION PASSED"
        )
    else:
        print(
            "\nPROJECT VALIDATION FAILED"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--quick",
        action="store_true",
        help=(
            "Compile the project and run one fast "
            "end-to-end foundation smoke test."
        ),
    )
    mode.add_argument(
        "--full",
        action="store_true",
        help=(
            "Run the quick suite plus the expensive "
            "Trade Machine and mutable-state validators."
        ),
    )
    args = parser.parse_args()

    try:
        report = (
            run_full()
            if args.full
            else run_quick()
        )
    except (
        ProjectValidationError,
        FileNotFoundError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        print(
            f"\nPROJECT VALIDATION FAILED: {exc}",
            file=sys.stderr,
        )
        return 1

    print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())