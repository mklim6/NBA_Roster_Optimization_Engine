from __future__ import annotations

import py_compile
from pathlib import Path

VERSION = "franchise-trade-war-room-v1-validator-2026-09-12"
ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
MODULE = ROOT / "src" / "franchise_trade_war_room_v1.py"


def _contains(path: Path, text: str) -> bool:
    return path.is_file() and text in path.read_text(encoding="utf-8")


def main() -> int:
    page_text = PAGE.read_text(encoding="utf-8") if PAGE.is_file() else ""
    module_text = MODULE.read_text(encoding="utf-8") if MODULE.is_file() else ""
    checks = {
        "war_room_module_exists": MODULE.is_file(),
        "page_imports_war_room": "from franchise_trade_war_room_v1 import" in page_text,
        "trade_center_uses_war_room": "render_franchise_trade_war_room_v1(" in page_text,
        "headshot_resolver_wired": "player_headshot_resolver=player_headshot_url" in page_text,
        "live_asset_ledger_remains_available": "render_live_asset_ledger" in module_text,
        "side_by_side_live_players": "team_player_rows" in module_text and "st.columns(2" in module_text,
        "draft_pick_timeline": "Draft-pick timeline" in module_text and "twr-timeline" in module_text,
        "salary_readout": "Financial bridge" in module_text and "listed salary" in module_text,
        "ai_team_value_model": "build_team_trade_ai_profiles" in module_text and "player_value_for_team" in module_text and "pick_value_for_team" in module_text,
        "team_fit_signal": "_fit_signal" in module_text and "biggest current need" in module_text,
        "authoritative_legality_preview": "build_franchise_trade_preview" in module_text and "draft_right_bridge_status" in module_text,
        "transaction_commit_gate": "commit_live_franchise_trade" in module_text and "Approve & commit live trade" in module_text,
        "franchise_state_updated_after_commit": 'st.session_state["franchise_simulation_league_state"] = result.committed_state' in module_text,
        "standalone_game_simulator_not_mutated": 'st.session_state["game_simulator_league_state"]' not in module_text,
        "safe_widget_pending_mutation": "_franchise_trade_war_room_pending_clear_v1" in module_text and "_franchise_trade_war_room_pending_workspace_v1" in module_text,
        "story_center_preserved": "render_league_story_center_v1" in page_text and "render_league_story_preview_v1" in page_text,
        "legacy_preserved": "render_franchise_timeline_trophy_room_v1" in page_text,
        "native_game_navigation_preserved": "franchise_game_navigation_native_v2_2" in page_text,
        "premium_roster_preserved": "render_franchise_premium_roster_v1" in page_text,
        "module_version_current": 'franchise-trade-war-room-v1.0-2026-09-12' in module_text,
    }
    compile_error = ""
    try:
        py_compile.compile(str(MODULE), doraise=True)
        py_compile.compile(str(PAGE), doraise=True)
        checks["python_compile"] = True
    except Exception as exc:
        checks["python_compile"] = False
        compile_error = str(exc)

    failed = [name for name, passed in checks.items() if not passed]
    result = {
        "version": VERSION,
        "checks": checks,
        "failed_checks": failed,
        "compile_error": compile_error,
        "passed": not failed,
    }
    print(result)
    if failed:
        print("FRANCHISE TRADE WAR ROOM V1 VALIDATOR FAILED")
        return 1
    print("FRANCHISE TRADE WAR ROOM V1 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
