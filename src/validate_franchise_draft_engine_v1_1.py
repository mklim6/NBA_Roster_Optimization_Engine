from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "src" / "franchise_draft_engine_v1.py"
UI = ROOT / "src" / "franchise_draft_ui_v1.py"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
HOME = ROOT / "Home.py"
VERSION = "franchise-draft-engine-v1.1-validator-sprint-d-authority-2026-08-18"


def main() -> int:
    engine = ENGINE.read_text(encoding="utf-8")
    ui = UI.read_text(encoding="utf-8")
    page = PAGE.read_text(encoding="utf-8")
    home = HOME.read_text(encoding="utf-8") if HOME.is_file() else ""

    checks = {
        "engine_v1_1_active": (
            "franchise-draft-engine-v1.1-2026-08-11" in engine
        ),
        "ui_v1_1_active": (
            "franchise-draft-ui-v1.1-2026-08-11" in ui
        ),
        "resume_pending_clock": "clock_resume_pending" in engine,
        "sim_to_next_pick_label": '"Sim to Next Pick"' in ui,
        "conditional_next_user_pick": "later_user_picks" in ui,
        "team_depth_chart": (
            "team_depth_chart_rows" in engine
            and "Roster needs before you pick" in ui
        ),
        "team_fit_recommendations": (
            "fit_reason" in engine
            and "team_need_score" in engine
        ),
        "csv_exports": (
            "Download lottery CSV" in ui
            and "Download draft order CSV" in ui
            and "Download scouting CSV" in ui
            and "Download all draft CSVs" in ui
        ),
        "draft_complete_routes_to_authoritative_boundary": (
            "Return to Season Boundary" in ui
            and "draft_complete_open_next_season_v1_1" not in ui
        ),
        "page_does_not_inject_direct_transition_callback": (
            "advance_next_season=advance_to_next_season_with_schedule"
            not in page
        ),
        "single_authoritative_open_next_season_button": (
            page.count('"Open next season"') == 1
        ),
        "page_navigation_callback": (
            "set_section=set_franchise_section" in page
        ),
        "home_franchise_flagship": (
            not home
            or "FRANCHISE MODE" in home
            or "Franchise Mode" in home
        ),
    }

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "script": VERSION,
        "checks": checks,
        "failed_checks": failed,
        "passed": not failed,
    }
    print(json.dumps(report, indent=2))
    if failed:
        raise AssertionError(
            "Draft Engine V1.1 validation failed: "
            + ", ".join(failed)
        )

    print()
    print("FRANCHISE DRAFT ENGINE V1.1 VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
