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

PAGE_PATH = (
    PAGES / "5_Franchise_Mode.py"
)
BACKEND_PATH = (
    SRC
    / "franchise_command_center_v1.py"
)
REPORT_PATH = (
    OUTPUTS
    / "franchise_command_center_validation_v1.json"
)

VALIDATOR_VERSION = (
    "franchise-command-center-validator-v1.3-2026-08-09"
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

    checks["franchise_page_exists"] = (
        PAGE_PATH.exists()
    )
    checks["command_center_backend_exists"] = (
        BACKEND_PATH.exists()
    )

    page_text = (
        PAGE_PATH.read_text(
            encoding="utf-8"
        )
        if PAGE_PATH.exists()
        else ""
    )
    backend_text = (
        BACKEND_PATH.read_text(
            encoding="utf-8"
        )
        if BACKEND_PATH.exists()
        else ""
    )

    page_markers = {
        "shared_permanent_state": (
            '"franchise_simulation_league_state"'
        ),
        "controlled_team_selector": (
            '"franchise_pref_controlled_teams"'
        ),
        "active_team_selector": (
            '"franchise_pref_active_team"'
        ),
        "simulation_policy_selector": (
            '"franchise_pref_simulation_policy"'
        ),
        "cross_page_state_guard": (
            "FRANCHISE_TRADE_AUTHORITY_V1"
        ),
        "cross_page_preference_restore": (
            "initialize_persistent_widget("
        ),
        "canonical_alignment_imported": (
            "apply_nba_team_alignment"
        ),
        "transactional_trade_sync_imported": (
            "synchronize_simulation_with_trade_state"
        ),
        "trade_sync_action": (
            "Build and commit live franchise trades"
        ),
        "trade_sync_preservation_copy": (
            "checkpoint-owned"
        ),
        "command_center_tab": (
            '"Command Center"'
        ),
        "calendar_tab": (
            '"Calendar"'
        ),
        "team_management_tab": (
            '"Team Management"'
        ),
        "game_day_tab": (
            '"Game Day"'
        ),
        "stats_tab": (
            '"Stats & Standings"'
        ),
        "trade_center_tab": (
            '"Trade Center"'
        ),
        "offseason_tab": (
            '"League & Offseason"'
        ),
        "team_logo_header": (
            "fm-team-logo"
        ),
        "logo_calendar": (
            "calendar_with_logos_html"
        ),
        "next_day_control": (
            '"Next day"'
        ),
        "next_week_control": (
            '"Next week"'
        ),
        "season_end_control": (
            'key="franchise_season_end"'
        ),
        "rotation_editor": (
            "st.data_editor("
        ),
        "rotation_save": (
            "Save rotation and minutes"
        ),
        "rotation_240_copy": (
            "exactly 240 total minutes"
        ),
        "persistent_workspace_navigation": (
            "FRANCHISE_SECTION_KEY"
        ),
        "one_way_game_simulation": (
            '"Simulate game"'
        ),
        "game_day_final_broadcast": (
            "render_game_day_final_v1("
        ),
        "automatic_next_game": (
            '"Open next game"'
        ),
        "standings_tables": (
            "standings_rows("
        ),
        "player_leaders": (
            '"Regular Season Leaders"'
        ),
        "trade_war_room": (
            "render_franchise_trade_war_room_v1("
        ),
        "trade_center_route": (
            '"Trade Center"'
        ),
        "draft_strength_setting": (
            "Generated draft-class strength"
        ),
        "current_width_api": (
            'width="stretch"'
        ),
    }
    missing_page = [
        name
        for name, marker
        in page_markers.items()
        if marker not in page_text
    ]
    checks[
        "all_franchise_page_markers_present"
    ] = not missing_page
    details[
        "missing_page_markers"
    ] = missing_page
    details[
        "page_marker_count"
    ] = len(page_markers)

    backend_markers = {
        "four_simulation_policies": (
            "class FranchiseSimulationPolicy"
        ),
        "rotation_plan_contract": (
            "class RotationPlan"
        ),
        "rotation_validation": (
            "def validate_rotation_plan("
        ),
        "transactional_rotation_apply": (
            "def apply_rotation_plan("
        ),
        "coaching_alerts": (
            "def coaching_alerts_for_game("
        ),
        "decision_policy": (
            "def game_requires_decision("
        ),
        "team_snapshot": (
            "def build_team_snapshot("
        ),
        "canonical_conference_filter": (
            "conference_for_team("
        ),
        "canonical_division_snapshot": (
            "division_for_team("
        ),
        "transactional_advance": (
            "def advance_franchise_scope("
        ),
        "official_logo_cdn": (
            "https://cdn.nba.com/logos/nba/"
        ),
        "all_30_logo_ids": (
            "NBA_TEAM_IDS"
        ),
        "standings_rows": (
            "def standings_rows("
        ),
        "player_leader_rows": (
            "def player_leader_rows("
        ),
        "team_needs_rows": (
            "def team_needs_rows("
        ),
        "logo_calendar_html": (
            "def calendar_with_logos_html("
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
        "all_command_center_backend_markers_present"
    ] = not missing_backend
    details[
        "missing_backend_markers"
    ] = missing_backend
    details[
        "backend_marker_count"
    ] = len(backend_markers)

    checks["deprecated_width_api_absent"] = (
        "use_container_width"
        not in page_text
    )
    checks[
        "page_uses_transactional_rotation_backend"
    ] = (
        "apply_rotation_plan("
        in page_text
        and ".rotation = RotationState"
        not in page_text
    )
    checks[
        "page_uses_transactional_game_commit"
    ] = (
        "commit_game_transactionally("
        in page_text
        and "copy.deepcopy("
        in page_text
    )
    checks[
        "page_uses_transactional_batch_advance"
    ] = (
        "advance_franchise_scope("
        in page_text
        and "set_franchise_state("
        in page_text
    )
    checks[
        "advanced_what_if_ui_removed"
    ] = (
        "Advanced What-If Lab" not in page_text
        and "Run what-if simulation" not in page_text
        and "What-if result only" not in page_text
        and "What-if preview" not in page_text
        and "What-if next game" not in page_text
        and "simulate_postseason_game(" not in page_text
        and "commit=False" not in page_text
    )

    page_compiles, page_error = (
        compile_path(PAGE_PATH)
        if PAGE_PATH.exists()
        else (False, "Page missing")
    )
    backend_compiles, backend_error = (
        compile_path(BACKEND_PATH)
        if BACKEND_PATH.exists()
        else (False, "Backend missing")
    )
    checks["franchise_page_compiles"] = (
        page_compiles
    )
    checks["command_center_backend_compiles"] = (
        backend_compiles
    )
    details["page_compile_error"] = (
        page_error
    )
    details["backend_compile_error"] = (
        backend_error
    )

    failed = [
        name
        for name, passed
        in checks.items()
        if not passed
    ]
    report = {
        "script": VALIDATOR_VERSION,
        "page": str(PAGE_PATH),
        "backend": str(BACKEND_PATH),
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
            "Franchise command-center "
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
        "\nFRANCHISE COMMAND CENTER "
        "VALIDATION PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
