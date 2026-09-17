from __future__ import annotations

import ast
from pathlib import Path


def _compile(path: Path) -> bool:
    try:
        ast.parse(path.read_text(encoding="utf-8"))
        return True
    except Exception:
        return False


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    page = root / "pages" / "5_Franchise_Mode.py"
    roster = root / "src" / "franchise_roster_rotation_headquarters_v1.py"
    scout = root / "src" / "franchise_scouting_discovery_v1.py"
    engine = root / "src" / "franchise_draft_engine_v1.py"
    ui = root / "src" / "franchise_draft_ui_v1.py"
    paths = (page, roster, scout, engine, ui)

    texts = {path.name: path.read_text(encoding="utf-8") for path in paths}
    roster_text = texts[roster.name]
    scout_text = texts[scout.name]
    engine_text = texts[engine.name]
    ui_text = texts[ui.name]
    page_text = texts[page.name]

    checks = {
        "patched_files_compile": all(_compile(path) for path in paths),
        "duplicate_premium_roster_call_removed_from_new_hq": "render_franchise_premium_roster_v1(" not in roster_text,
        "locker_room_uses_full_morale_roster": 'morale["players"]' in roster_text and "lowest morale first" in roster_text,
        "season_scouting_allowed_by_scouting_ui": '{"season_scouting", "scouting"}' in scout_text,
        "season_long_engine_initializer_present": "def initialize_regular_season_scouting_state(" in engine_text,
        "season_long_lottery_promotion_present": "def promote_regular_season_scouting_to_lottery(" in engine_text,
        "season_long_class_phase_present": '"phase": "season_scouting"' in engine_text,
        "season_long_ui_marker_present": "FRANCHISE_SEASON_LONG_SCOUTING_UI_V1_2" in ui_text,
        "season_long_board_visible_pre_finals": "Scout the next class all season" in ui_text,
        "scouting_preserved_into_lottery": "prospect reports and confidence will not reset" in ui_text,
        "box_score_marker_present": "FRANCHISE_BOX_SCORE_SHOOTING_PERCENTAGES_V1_2" in page_text,
        "box_score_fg_percentage_present": '"FG%": fg_pct' in page_text,
        "box_score_three_percentage_present": '"3PT%": three_pct' in page_text,
        "box_score_attempt_lines_present": '"FG": f"{field_goals_made}-{field_goals_attempted}"' in page_text and '"3PT": f"{three_pointers_made}-{three_pointers_attempted}"' in page_text,
    }
    failed = [name for name, ok in checks.items() if not ok]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE EXPANSION SPRINT V1.2 HOTFIX VALIDATOR FAILED")
        return 1
    print("FRANCHISE EXPANSION SPRINT V1.2 HOTFIX VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
