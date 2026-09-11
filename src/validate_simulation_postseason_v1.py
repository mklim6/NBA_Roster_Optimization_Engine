from __future__ import annotations

import argparse
import json
import py_compile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "pages"
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

POSTSEASON_PATH = (
    SRC / "simulation_postseason_v1.py"
)
FRANCHISE_PAGE = (
    PAGES / "5_Franchise_Mode.py"
)
REPORT_PATH = (
    OUTPUTS
    / "simulation_postseason_validation_v1.json"
)

VALIDATOR_VERSION = (
    "simulation-postseason-validator-v1.1.3-2026-08-09"
)


def compile_path(
    path: Path,
) -> tuple[bool, str]:
    try:
        py_compile.compile(
            str(path),
            doraise=True,
        )
    except py_compile.PyCompileError as exc:
        return False, str(exc)

    return True, ""


def run_validation() -> dict[str, Any]:
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}

    checks["postseason_backend_exists"] = (
        POSTSEASON_PATH.exists()
    )
    checks["franchise_page_exists"] = (
        FRANCHISE_PAGE.exists()
    )

    backend_text = (
        POSTSEASON_PATH.read_text(
            encoding="utf-8"
        )
        if POSTSEASON_PATH.exists()
        else ""
    )
    page_text = (
        FRANCHISE_PAGE.read_text(
            encoding="utf-8"
        )
        if FRANCHISE_PAGE.exists()
        else ""
    )

    backend_markers = {
        "official_play_in_opening": (
            '"Play-In 7 vs 8"'
        ),
        "official_play_in_elimination": (
            '"Play-In 9 vs 10"'
        ),
        "official_play_in_final": (
            '"Play-In Final"'
        ),
        "best_of_seven_home_pattern": (
            "HOME_COURT_PATTERN"
        ),
        "first_round_creation": (
            "def create_first_round("
        ),
        "conference_semifinals": (
            "def create_conference_semifinals("
        ),
        "conference_finals": (
            "def create_conference_finals("
        ),
        "nba_finals": (
            "def create_nba_finals("
        ),
        "transactional_commit": (
            "def commit_postseason_game("
        ),
        "regular_stats_preserved": (
            "Postseason commit changed regular-season "
        ),
        "postseason_player_totals": (
            "postseason_player_totals"
        ),
        "controlled_team_pause": (
            "def postseason_game_requires_pause("
        ),
        "full_postseason_advance": (
            "def advance_postseason("
        ),
        "next_controlled_game_scope": (
            'NEXT_CONTROLLED_GAME = "next_controlled_game"'
        ),
        "controlled_game_lookup": (
            "def controlled_postseason_games("
        ),
        "batch_transaction_helper": (
            "_commit_postseason_game_in_place"
        ),
        "batch_execution_version": (
            "postseason-batch-performance-v1-2026-08-09"
        ),
        "private_working_state": (
            "_private_working_state=True"
        ),
        "completed_game_history": (
            "def completed_postseason_games("
        ),
        "team_postseason_status": (
            "def postseason_team_status("
        ),
        "champion_crowned": (
            "postseason.champion"
        ),
        "self_test": (
            "def run_self_test("
        ),
    }
    missing_backend = [
        name
        for name, marker
        in backend_markers.items()
        if marker not in backend_text
    ]
    checks[
        "all_postseason_backend_markers_present"
    ] = not missing_backend
    details[
        "missing_backend_markers"
    ] = missing_backend
    details[
        "backend_marker_count"
    ] = len(backend_markers)

    page_markers = {
        "postseason_import": (
            "from simulation_postseason_v1 import"
        ),
        "create_bracket_action": (
            "Create play-in and playoff bracket"
        ),
        "eastern_seeds": (
            '"Eastern Seeds"'
        ),
        "western_seeds": (
            '"Western Seeds"'
        ),
        "bracket_view": (
            '"Bracket"'
        ),
        "postseason_leaders": (
            '"Postseason Leaders"'
        ),
        "what_if_preview": (
            "What-if preview"
        ),
        "committed_simulation": (
            "Simulate & commit"
        ),
        "what_if_is_sandbox_only": (
            "Sandbox result only."
        ),
        "simulate_stage": (
            "Sim current stage"
        ),
        "simulate_to_champion": (
            "Sim to champion"
        ),
        "champion_display": (
            "won the NBA championship."
        ),
        "postseason_version_visible": (
            "POSTSEASON_VERSION"
        ),
        "command_center_postseason_renderer": (
            "def render_postseason_command_center("
        ),
        "command_center_begin_action": (
            "Begin NBA postseason"
        ),
        "advance_to_controlled_game_action": (
            "Advance to my next game"
        ),
        "postseason_game_day_renderer": (
            "def render_postseason_game_day("
        ),
        "game_day_switches_after_regular_season": (
            "render_postseason_game_day("
        ),
        "completed_postseason_selector": (
            "Completed postseason game"
        ),
        "completed_box_score_renderer": (
            "def render_completed_postseason_game("
        ),
        "postseason_top_performers": (
            "def postseason_top_performers_dataframe("
        ),
        "league_game_log_tab": (
            '"Game Log"'
        ),
    }
    missing_page = [
        name
        for name, marker
        in page_markers.items()
        if marker not in page_text
    ]
    checks[
        "all_postseason_page_markers_present"
    ] = not missing_page
    details[
        "missing_page_markers"
    ] = missing_page
    details[
        "page_marker_count"
    ] = len(page_markers)

    backend_compiles, backend_error = (
        compile_path(
            POSTSEASON_PATH
        )
        if POSTSEASON_PATH.exists()
        else (
            False,
            "Postseason backend missing",
        )
    )
    page_compiles, page_error = (
        compile_path(
            FRANCHISE_PAGE
        )
        if FRANCHISE_PAGE.exists()
        else (
            False,
            "Franchise page missing",
        )
    )
    checks[
        "postseason_backend_compiles"
    ] = backend_compiles
    checks[
        "franchise_page_compiles"
    ] = page_compiles
    details[
        "backend_compile_error"
    ] = backend_error
    details[
        "page_compile_error"
    ] = page_error

    checks[
        "page_uses_transactional_postseason_commit"
    ] = (
        "commit_postseason_game("
        in page_text
        and "set_franchise_state("
        in page_text
    )
    checks[
        "page_supports_controlled_team_policy"
    ] = (
        "controlled_teams="
        in page_text
        and "FranchiseSimulationPolicy("
        in page_text
    )
    checks[
        "postseason_command_center_imports_conference_lookup"
    ] = (
        "from simulation_league_alignment_v1 import ("
        in page_text
        and "conference_for_team,"
        in page_text
    )

    checks[
        "postseason_does_not_use_regular_game_commit"
    ] = (
        "record_completed_game("
        not in backend_text
    )
    checks[
        "command_center_starts_postseason_transactionally"
    ] = (
        "render_postseason_command_center("
        in page_text
        and "initialize_postseason("
        in page_text
        and "set_franchise_state("
        in page_text
    )
    checks[
        "game_day_supports_sandbox_what_if_and_commit"
    ] = (
        "render_postseason_game_day("
        in page_text
        and "What-if preview"
        in page_text
        and "Sandbox result only."
        in page_text
        and "Simulate & commit"
        in page_text
        and "simulate_postseason_game("
        in page_text
        and "commit_postseason_game("
        in page_text
    )
    checks[
        "completed_postseason_box_scores_use_stored_games"
    ] = (
        "completed_postseason_games("
        in page_text
        and "box_score_dataframe("
        in page_text
        and "player_box_scores"
        in page_text
    )

    failed = [
        name
        for name, passed
        in checks.items()
        if not passed
    ]
    report = {
        "script": VALIDATOR_VERSION,
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
            "Postseason validation failed: "
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
        "\nSIMULATION POSTSEASON "
        "VALIDATION PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
