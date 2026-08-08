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
    "game-simulator-season-management-ui-validator-v1-2026-08-08"
)
REPORT_PATH = (
    OUTPUTS
    / "game_simulator_season_management_ui_validation_v1.json"
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
        "controller_imported": (
            "simulation_season_transition_controller_v1"
        ),
        "transition_preview_builder_used": (
            "build_season_transition_preview"
        ),
        "transactional_commit_used": (
            "commit_season_transition_preview"
        ),
        "source_state_freshness_guard": (
            "preview_matches_state"
        ),
        "incomplete_schedule_guard": (
            "incomplete_scheduled_game_ids"
        ),
        "transition_preview_session_state": (
            "game_simulator_season_transition_preview"
        ),
        "season_management_section": (
            "04 · Season management"
        ),
        "preview_transition_button": (
            "Preview transition"
        ),
        "explicit_acknowledgement": (
            "I understand this archives"
        ),
        "typed_confirmation": (
            "to confirm"
        ),
        "advance_transition_button": (
            '"Advance to "'
        ),
        "development_risers": (
            '"Biggest Risers"'
        ),
        "development_fallers": (
            '"Biggest Fallers"'
        ),
        "archive_summary": (
            "archived_season_summary_dataframe"
        ),
        "archive_standings": (
            "archived_standings_dataframe"
        ),
        "archive_player_leaders": (
            "archived_player_leaders_dataframe"
        ),
        "archive_history_section": (
            "Archived season history"
        ),
        "season_metric": (
            '"Season"'
        ),
        "phase_metric": (
            '"Phase"'
        ),
        "archived_seasons_metric": (
            '"Archived seasons"'
        ),
        "transition_notice": (
            "Projected "
        ),
        "transition_preview_clearer": (
            "clear_season_transition_preview"
        ),
        "stretch_width_api": (
            'width="stretch"'
        ),
    }

    missing = [
        name
        for name, marker in markers.items()
        if marker not in text
    ]
    checks["all_season_management_markers_present"] = (
        not missing
    )
    details["missing_markers"] = missing
    details["marker_count"] = len(markers)

    checks["deprecated_width_api_absent"] = (
        "use_container_width" not in text
    )
    checks["preview_is_not_direct_live_mutation"] = (
        "simulation_state.phase = "
        not in text
    )
    checks["commit_replaces_session_state"] = (
        'st.session_state[\n'
        '                "game_simulator_league_state"\n'
        "            ] = transitioned_state"
        in text
    )
    checks["transition_commit_clears_game_preview"] = (
        "clear_game_preview()\n"
        "            clear_season_transition_preview()"
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
            "Game Simulator season-management UI "
            "validation failed: "
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
        "\nGAME SIMULATOR SEASON MANAGEMENT "
        "UI VALIDATION PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())