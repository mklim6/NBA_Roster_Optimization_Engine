from __future__ import annotations

import argparse
import json
import py_compile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "pages"
OUTPUTS = ROOT / "outputs"
PAGE_PATH = PAGES / "4_Game_Simulator.py"

VALIDATOR_VERSION = (
    "franchise-calendar-ui-validator-v1.3-2026-08-08"
)
REPORT_PATH = (
    OUTPUTS
    / "franchise_calendar_ui_validation_v1.json"
)


def run_validation() -> dict[str, Any]:
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}

    checks["game_simulator_page_exists"] = (
        PAGE_PATH.exists()
    )

    text = (
        PAGE_PATH.read_text(
            encoding="utf-8"
        )
        if PAGE_PATH.exists()
        else ""
    )

    markers = {
        "simulation_bootstrap_imported": (
            "from simulation_module_bootstrap_v1 import"
        ),
        "simulation_bootstrap_runs_before_state_imports": (
            "ensure_current_simulation_modules()"
        ),
        "bootstrap_version_visible": (
            "BOOTSTRAP_VERSION"
        ),
        "realism_engine_version_imported": (
            "ENGINE_VERSION"
        ),
        "realism_engine_guard_present": (
            "EXPECTED_REALISM_ENGINE_VERSION"
        ),
        "realism_engine_v1_5_required": (
            "single-game-simulator-v1.6-2026-08-08"
        ),
        "calendar_backend_imported": (
            "from franchise_calendar_v1 import"
        ),
        "schedule_engine_imported": (
            "generate_regular_season_schedule"
        ),
        "schedule_installer_imported": (
            "install_regular_season_schedule"
        ),
        "season_controller_imported": (
            "simulate_regular_season_scope"
        ),
        "controlled_team_selector": (
            '"franchise_pref_controlled_teams"'
        ),
        "controlled_team_widget_shadow": (
            '"_game_simulator_controlled_teams_widget"'
        ),
        "viewed_team_selector": (
            '"franchise_pref_active_team"'
        ),
        "viewed_team_widget_shadow": (
            '"_game_simulator_viewed_team_widget"'
        ),
        "calendar_month_selector": (
            '"franchise_pref_calendar_month"'
        ),
        "calendar_month_widget_shadow": (
            '"_game_simulator_calendar_month_widget"'
        ),
        "persistent_selected_game": (
            '"game_simulator_selected_schedule_game_id"'
        ),
        "franchise_calendar_section": (
            "00 · Franchise calendar"
        ),
        "generated_schedule_button": (
            "Generate schedule"
        ),
        "generated_schedule_disclaimer": (
            "Generated simulation schedule."
        ),
        "monthly_calendar_builder": (
            "build_team_month_calendar"
        ),
        "monthly_calendar_renderer": (
            "calendar_html"
        ),
        "home_calendar_style": (
            ".fc-day.home"
        ),
        "away_calendar_style": (
            ".fc-day.away"
        ),
        "current_day_style": (
            ".fc-day.current"
        ),
        "calendar_game_preparation": (
            "Prepare matchup"
        ),
        "calendar_next_day_control": (
            "Sim next day"
        ),
        "calendar_next_week_control": (
            "Sim next week"
        ),
        "calendar_remainder_control": (
            "Sim to season end"
        ),
        "controlled_pause_policy": (
            "controlled_team_pause"
        ),
        "controlled_pause_copy": (
            "stops before the first day"
        ),
        "scheduled_game_preview_mode": (
            '"existing_schedule_game"'
        ),
        "full_schedule_custom_game_guard": (
            "full_schedule_active"
        ),
        "scheduled_game_commit_guard": (
            "if not preview_request.get("
        ),
        "selected_game_cleared_after_commit": (
            "clear_franchise_game_selection()"
        ),
        "current_width_api": (
            'width="stretch"'
        ),
    }
    missing = [
        name
        for name, marker in markers.items()
        if marker not in text
    ]
    checks[
        "all_franchise_calendar_markers_present"
    ] = not missing
    details["missing_markers"] = missing
    details["marker_count"] = len(markers)

    checks["deprecated_width_api_absent"] = (
        "use_container_width" not in text
    )
    checks[
        "calendar_does_not_replace_permanent_state_directly"
    ] = (
        "simulation_state.schedule =" not in text
    )
    checks[
        "schedule_install_uses_replacement_state"
    ] = (
        "scheduled_state = copy.deepcopy("
        in text
        and (
            '"game_simulator_league_state"\n'
            "            ] = scheduled_state"
            in text
        )
    )
    checks[
        "batch_simulation_uses_replacement_state"
    ] = (
        '"game_simulator_league_state"\n'
        "            ] = advanced_state"
        in text
    )
    checks[
        "controlled_game_selection_sets_both_teams"
    ] = (
        '"game_simulator_away_team"'
        in text
        and '"game_simulator_home_team"'
        in text
        and "prepare_scheduled_game("
        in text
    )

    compile_passed = False
    compile_error = ""

    if PAGE_PATH.exists():
        try:
            py_compile.compile(
                str(PAGE_PATH),
                doraise=True,
            )
            compile_passed = True
        except py_compile.PyCompileError as exc:
            compile_error = str(exc)

    checks["game_simulator_page_compiles"] = (
        compile_passed
    )
    details["compile_error"] = compile_error

    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]
    report = {
        "script": VALIDATOR_VERSION,
        "page": str(PAGE_PATH),
        "checks": checks,
        "failed_checks": failed,
        "details": details,
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
            "Franchise calendar UI validation "
            "failed: "
            + ", ".join(failed)
        )

    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()

    report = run_validation()
    print(
        json.dumps(
            report,
            indent=2,
        )
    )
    print(
        "\nFRANCHISE CALENDAR UI "
        "VALIDATION PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
