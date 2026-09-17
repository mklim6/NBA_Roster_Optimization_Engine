from __future__ import annotations

import ast
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    module_path = root / "src" / "franchise_free_agency_cpu_execution_v1.py"
    page_path = root / "pages" / "5_Franchise_Mode.py"
    module = module_path.read_text(encoding="utf-8")
    page = page_path.read_text(encoding="utf-8")

    checks = {}
    try:
        ast.parse(module)
        ast.parse(page)
        checks["module_and_page_compile"] = True
    except Exception:
        checks["module_and_page_compile"] = False

    checks["bridge_function_present"] = "def execute_cpu_roster_floor_bridge_durably(" in module
    checks["bridge_version_present"] = "franchise-next-season-roster-floor-bridge-v1-2026-09-16" in module
    checks["bridge_uses_certified_rescue_builder"] = "build_cpu_roster_floor_rescue_opportunity(" in module
    checks["bridge_uses_certified_rescue_commit"] = "_commit_cpu_roster_floor_rescue_durably(" in module
    checks["bridge_excludes_controlled_teams"] = "controlled_teams_from_durable_checkpoint" in module
    checks["page_runs_bridge_after_post_draft_trim"] = (
        "FRANCHISE_CPU_POST_DRAFT_ROSTER_TRIM_LIVE_UI_WIRING_V1" in page
        and "FRANCHISE_NEXT_SEASON_ROSTER_FLOOR_BRIDGE_UI_V1" in page
        and page.index("FRANCHISE_CPU_POST_DRAFT_ROSTER_TRIM_LIVE_UI_WIRING_V1")
            < page.index("FRANCHISE_NEXT_SEASON_ROSTER_FLOOR_BRIDGE_UI_V1")
            < page.index("advance_to_next_season_with_schedule(state)", page.index("FRANCHISE_NEXT_SEASON_ROSTER_FLOOR_BRIDGE_UI_V1"))
    )
    checks["page_reloads_durable_checkpoint_after_bridge"] = "after the CPU roster-floor bridge" in page
    checks["page_reports_remaining_deficits"] = "_season_boundary_remaining_deficits" in page
    checks["atomic_boundary_commit_preserved"] = "commit_atomic_season_boundary_live(" in page
    checks["no_relaxed_roster_validator"] = "minimum_game_players = 5" not in page and "all_team_rosters_playable" not in page

    failed = [name for name, ok in checks.items() if not ok]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE NEXT-SEASON ROSTER-FLOOR BRIDGE V1 VALIDATOR FAILED")
        return 1
    print("FRANCHISE NEXT-SEASON ROSTER-FLOOR BRIDGE V1 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
