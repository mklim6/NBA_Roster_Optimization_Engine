from __future__ import annotations

import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
NAV = ROOT / "src" / "franchise_game_navigation_v1.py"

page = PAGE.read_text(encoding="utf-8")
nav = NAV.read_text(encoding="utf-8")

checks = {
    "native_ribbon_buttons": "fgn_native_rail_" in nav and "st.button(" in nav,
    "native_month_buttons": (
        "def render_clickable_month_calendar_v2" in nav
        and "fgn_native_month_" in nav
    ),
    "no_ribbon_anchor_navigation": '<a class="fx4-game-link"' not in nav,
    "no_month_anchor_navigation": 'fgn-game-day\" href=' not in nav,
    "page_imports_native_month_renderer": "render_clickable_month_calendar_v2," in page,
    "page_uses_native_month_renderer": "render_clickable_month_calendar_v2(" in page,
    "page_filters_postgame_signature": (
        "_game_day_final_supported_v2" in page
        and "_game_day_final_signature_v2" in page
    ),
    "page_keeps_legacy_workspace": "render_franchise_timeline_trophy_room_v1" in page,
    "page_keeps_runtime_bridge": "franchise_game_flow_runtime_bridge_v1" in page,
    "archive_return_control_preserved": "Return to upcoming matchup" in page,
}

compile_ok = True
compile_error = ""
try:
    py_compile.compile(str(PAGE), doraise=True)
    py_compile.compile(str(NAV), doraise=True)
except Exception as exc:
    compile_ok = False
    compile_error = f"{type(exc).__name__}: {exc}"
checks["python_compile"] = compile_ok

failed = [name for name, ok in checks.items() if not ok]
print({"checks": checks, "failed_checks": failed, "compile_error": compile_error, "passed": not failed})
if failed:
    raise SystemExit("FRANCHISE GAME NAVIGATION NATIVE HOTFIX V2.1 VALIDATOR FAILED")
print("FRANCHISE GAME NAVIGATION NATIVE HOTFIX V2.1 VALIDATOR PASSED")
