from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
VERSION = "franchise-experience-v2-validator-v1.0.3-2026-08-10"


def main() -> int:
    text = PAGE.read_text(encoding="utf-8")
    checks = {
        "experience_version": "franchise-experience-v2-redesign-v1.0.3-2026-08-10" in text,
        "original_section_architecture_preserved": "FRANCHISE_SECTIONS = (" in text,
        "display_navigation_map_present": "FRANCHISE_SECTION_DISPLAY" in text,
        "home_label_present": '"Command Center": "Home"' in text,
        "health_label_present": '"Inbox & League Health": "Health"' in text,
        "schedule_label_present": '"Calendar": "Schedule"' in text,
        "roster_label_present": '"Team Management": "Roster"' in text,
        "stats_label_present": '"Stats & Standings": "Stats"' in text,
        "transactions_label_present": '"Trade Center": "Transactions"' in text,
        "league_hub_label_present": '"League & Offseason": "League Hub"' in text,
        "radio_uses_display_labels": "format_func=lambda section" in text,
        "official_nba_headshots": "https://cdn.nba.com/headshots/nba/latest/" in text,
        "photographic_team_hero": "render_team_hero(" in text,
        "player_spotlight_cards": "render_franchise_core(" in text,
        "additive_visual_system": "\ninject_franchise_experience_v2_styles()\n" in text,
        "routine_health_auto_processing": "auto_process_routine_franchise_events(" in text,
        "regular_season_action_renamed": '"Sim regular season"' in text,
        "automatic_postseason_creation": "auto_postseason_created = False" in text,
        "next_season_flow": "advance_to_next_season_with_schedule(" in text,
        "next_season_button": '"Open next season"' in text,
        "health_realism_exports_preserved": "player_availability_audit_rows" in text,
        "health_event_history_preserved": "injury_event_history_rows" in text,
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
            "Franchise Experience V2 validation failed: " + ", ".join(failed)
        )
    print()
    print("FRANCHISE EXPERIENCE V2 V1.0.3 VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
