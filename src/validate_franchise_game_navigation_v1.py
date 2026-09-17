from __future__ import annotations

import importlib.util
import json
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
NAV = SRC / "franchise_game_navigation_v1.py"

VERSION = "franchise-game-navigation-v1-validator-2026-09-11"


def _load_nav():
    spec = importlib.util.spec_from_file_location("_franchise_game_navigation_validation", NAV)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load franchise_game_navigation_v1.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    page = PAGE.read_text(encoding="utf-8")
    nav = NAV.read_text(encoding="utf-8")
    checks = {
        "navigation_module_exists": NAV.exists(),
        "page_imports_navigation_layer": "from franchise_game_navigation_v1 import (" in page,
        "page_injects_navigation_visuals": "inject_franchise_game_navigation_visuals_v1()" in page,
        "command_center_uses_clickable_rail": page.count("render_schedule_ribbon_v4(") >= 2 and "render_interactive_schedule_ribbon_v1 as render_schedule_ribbon_v4" in page,
        "month_calendar_is_clickable": "calendar_with_clickable_games_html_v1(" in page,
        "query_route_is_consumed": "_franchise_requested_game_v1 = requested_game_id_v1()" in page,
        "completed_game_archive_session_exists": "FRANCHISE_GAME_ARCHIVE_SESSION_KEY" in page,
        "completed_game_opens_archive": 'set_franchise_section("Game Day")' in page and 'state.completed_games' in page,
        "archive_box_score_expands": "expanded=bool(archive_game_id)" in page,
        "archive_return_control_exists": "Return to upcoming matchup" in page,
        "schedule_cards_link_to_games": "fx4-game-link" in nav and "?{FRANCHISE_GAME_QUERY_KEY}=" in nav,
        "completed_cards_offer_box_score": "View box score" in nav,
        "upcoming_cards_offer_game_day": "Open Game Day" in nav,
        "monthly_games_are_links": "fgn-game-day" in nav and "VIEW BOX SCORE" in nav,
        "game_day_scale_pass_exists": "Game Day V2.1 scale pass" in nav,
        "scoreboard_logo_size_increased": "width:132px!important" in nav,
        "starter_portrait_size_increased": "height:86px!important" in nav,
        "simulation_engine_untouched_by_module": "advance_franchise_scope" not in nav and "commit_game_transactionally" not in nav,
    }

    try:
        py_compile.compile(str(PAGE), doraise=True)
        py_compile.compile(str(NAV), doraise=True)
        checks["python_compiles"] = True
    except Exception:
        checks["python_compiles"] = False

    try:
        module = _load_nav()
        checks["href_encoding_works"] = module.game_href("REG-001") == "?fgame=REG-001"
        checks["module_version_current"] = module.FRANCHISE_GAME_NAVIGATION_V1_VERSION == "franchise-game-navigation-v1.0-2026-09-11"
    except Exception:
        checks["href_encoding_works"] = False
        checks["module_version_current"] = False

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "version": VERSION,
        "checks": checks,
        "failed_checks": failed,
        "passed": not failed,
    }
    print(json.dumps(report, indent=2))
    print()
    if failed:
        print("FRANCHISE GAME NAVIGATION V1 VALIDATOR FAILED")
        return 1
    print("FRANCHISE GAME NAVIGATION V1 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
