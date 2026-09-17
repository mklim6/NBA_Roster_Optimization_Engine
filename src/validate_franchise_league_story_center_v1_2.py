from __future__ import annotations

import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src" / "franchise_league_story_center_v1.py"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"


def main() -> int:
    text = MODULE.read_text(encoding="utf-8", errors="replace")
    page = PAGE.read_text(encoding="utf-8", errors="replace") if PAGE.is_file() else ""
    checks = {
        "story_module_exists": MODULE.is_file(),
        "version_v1_2": "franchise-league-story-center-v1.2-2026-09-11" in text,
        "player_game_reads_home_team": 'home_team = _team(getattr(game, "home_team", ""))' in text,
        "player_game_reads_away_team": 'away_team = _team(getattr(game, "away_team", ""))' in text,
        "opponent_context_added": 'opponent_context = (' in text,
        "home_uses_vs": 'opponent_prefix = "vs"' in text,
        "away_uses_at": 'opponent_prefix = "at"' in text,
        "player_story_records_opponent": "opponent=opponent," in text,
        "opponent_precedes_statline": "detail_bits.append(opponent_context)" in text,
        "story_workspace_preserved": 'if active_section == "League Stories":' in page,
        "premium_roster_preserved": "render_franchise_premium_roster_v1(" in page,
        "native_navigation_preserved": "franchise_game_navigation_native_v2_2" in page,
    }
    compile_error = ""
    try:
        py_compile.compile(str(MODULE), doraise=True)
        checks["python_compile"] = True
    except Exception as exc:
        checks["python_compile"] = False
        compile_error = str(exc)
    failed = [k for k, v in checks.items() if not v]
    print({"checks": checks, "failed_checks": failed, "compile_error": compile_error, "passed": not failed})
    if failed:
        raise SystemExit("FRANCHISE LEAGUE STORY CENTER V1.2 VALIDATOR FAILED")
    print("FRANCHISE LEAGUE STORY CENTER V1.2 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
