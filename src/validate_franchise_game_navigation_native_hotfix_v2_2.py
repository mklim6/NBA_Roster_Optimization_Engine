from __future__ import annotations

import py_compile
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
NAV = ROOT / "src" / "franchise_game_navigation_native_v2_2.py"

page = PAGE.read_text(encoding="utf-8")
nav = NAV.read_text(encoding="utf-8")

checks = {
    "page_uses_unique_navigation_module": "from franchise_game_navigation_native_v2_2 import (" in page,
    "page_no_longer_imports_navigation_from_v1": "from franchise_game_navigation_v1 import (" not in page,
    "unique_module_has_native_month_renderer": "def render_clickable_month_calendar_v2" in nav,
    "unique_module_has_native_ribbon_renderer": "def render_interactive_schedule_ribbon_v1" in nav,
    "unique_module_has_archive_key": "FRANCHISE_GAME_ARCHIVE_SESSION_KEY" in nav,
    "native_ribbon_buttons": "fgn_native_rail_" in nav and "st.button(" in nav,
    "native_month_buttons": "fgn_native_month_" in nav,
    "page_uses_native_month_renderer": "render_clickable_month_calendar_v2(" in page,
    "page_filters_postgame_signature": "_game_day_final_supported_v2" in page and "_game_day_final_signature_v2" in page,
    "page_keeps_legacy_workspace": "render_franchise_timeline_trophy_room_v1" in page,
    "page_keeps_runtime_bridge": "franchise_game_flow_runtime_bridge_v1" in page,
    "archive_return_control_preserved": "Return to upcoming matchup" in page,
}

compile_error = ""
try:
    py_compile.compile(str(PAGE), doraise=True)
    py_compile.compile(str(NAV), doraise=True)
    checks["python_compile"] = True
except Exception as exc:
    checks["python_compile"] = False
    compile_error = f"{type(exc).__name__}: {exc}"

# This is the important regression test V2.1 was missing: reproduce the exact
# style of import the Streamlit page performs, in a brand-new Python process.
import_test = (
    "import sys; "
    f"sys.path.insert(0, {str((ROOT / 'src').resolve())!r}); "
    "from franchise_game_navigation_native_v2_2 import ("
    "FRANCHISE_GAME_ARCHIVE_SESSION_KEY, calendar_with_clickable_games_html_v1, "
    "clear_requested_game_id_v1, inject_franchise_game_navigation_visuals_v1, "
    "render_interactive_schedule_ribbon_v1, render_clickable_month_calendar_v2, "
    "requested_game_id_v1); "
    "assert callable(render_clickable_month_calendar_v2); "
    "print('FRESH IMPORT OK')"
)
proc = subprocess.run(
    [sys.executable, "-c", import_test],
    cwd=str(ROOT),
    text=True,
    capture_output=True,
)
checks["fresh_process_page_import_contract"] = proc.returncode == 0 and "FRESH IMPORT OK" in proc.stdout

failed = [name for name, ok in checks.items() if not ok]
print({
    "checks": checks,
    "failed_checks": failed,
    "compile_error": compile_error,
    "fresh_import_stdout": proc.stdout.strip(),
    "fresh_import_stderr": proc.stderr.strip(),
    "passed": not failed,
})
if failed:
    raise SystemExit("FRANCHISE GAME NAVIGATION NATIVE HOTFIX V2.2 VALIDATOR FAILED")
print("FRANCHISE GAME NAVIGATION NATIVE HOTFIX V2.2 VALIDATOR PASSED")
