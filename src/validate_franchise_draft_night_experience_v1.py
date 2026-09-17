from __future__ import annotations
import py_compile, subprocess, sys
from pathlib import Path

VERSION = "franchise-draft-night-experience-v1-validator-2026-09-12"
ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
MODULE = ROOT / "src" / "franchise_draft_night_experience_v1.py"


def main() -> int:
    page = PAGE.read_text(encoding="utf-8") if PAGE.is_file() else ""
    module = MODULE.read_text(encoding="utf-8") if MODULE.is_file() else ""
    checks = {
        "module_exists": MODULE.is_file(),
        "page_runtime_loads_new_module": "franchise_draft_night_experience_v1.py" in page,
        "unique_runtime_module_name": "_franchise_draft_night_experience_v1_live" in page,
        "legacy_draft_phases_preserved": "_legacy_render_draft_room_v1(" in module,
        "live_draft_override": 'current.get("phase") == "draft_in_progress"' in module,
        "on_clock_presentation": "dnx-clock" in module and "ON THE CLOCK" in module,
        "live_pick_ticker": "dnx-ticker" in module and "_ticker_html" in module,
        "prospect_portraits": "player_image_url" in module and "dnx-prospect-img" in module,
        "hidden_ratings_not_exposed": "hidden_overall" not in module and "hidden_potential" not in module,
        "scouting_context": "scouted_overall" in module and "scouted_potential" in module and "scouting_confidence" in module,
        "team_needs": "top_team_needs" in module and "_needs_html" in module,
        "user_draft_capital": "remaining_user_picks" in module and "_capital_html" in module,
        "commissioner_announcement": "THE PICK IS IN" in module and "Announce Selection" in module,
        "board_value_reaction": "_board_value_reaction" in module and "Board value:" in module,
        "real_draft_engine_selection": "make_selection(" in module,
        "real_draft_clock": "catch_up_expired_ai_picks" in module and "clock_remaining" in module,
        "simulation_shortcuts_preserved": "simulate_to_next_user_pick" in module and "simulate_to_next_round" in module and "simulate_rest_of_draft" in module,
        "trade_war_room_preserved": "render_franchise_trade_war_room_v1" in page,
        "story_center_preserved": "render_league_story_center_v1" in page,
        "legacy_preserved": "render_franchise_timeline_trophy_room_v1" in page,
        "premium_roster_preserved": "render_franchise_premium_roster_v1" in page,
        "native_navigation_preserved": "franchise_game_navigation_native_v2_2" in page,
        "module_version_current": "franchise-draft-night-experience-v1.0-2026-09-12" in module,
    }
    compile_error = ""
    try:
        py_compile.compile(str(MODULE), doraise=True)
        py_compile.compile(str(PAGE), doraise=True)
        checks["python_compile"] = True
    except Exception as exc:
        checks["python_compile"] = False
        compile_error = str(exc)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "py_compile", str(MODULE), str(PAGE)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        checks["fresh_process_compile_contract"] = proc.returncode == 0
        if proc.returncode != 0:
            compile_error += " | fresh compile: " + (proc.stderr or proc.stdout).strip()
    except Exception as exc:
        checks["fresh_process_compile_contract"] = False
        compile_error += " | fresh compile exception: " + str(exc)

    failed = [name for name, passed in checks.items() if not passed]
    print({"version": VERSION, "checks": checks, "failed_checks": failed, "compile_error": compile_error, "passed": not failed})
    if failed:
        print("FRANCHISE DRAFT NIGHT EXPERIENCE V1 VALIDATOR FAILED")
        return 1
    print("FRANCHISE DRAFT NIGHT EXPERIENCE V1 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
