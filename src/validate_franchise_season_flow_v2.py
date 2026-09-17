from __future__ import annotations

import json
import py_compile
from pathlib import Path
from types import SimpleNamespace


VERSION = "franchise-season-flow-v2-validator-2026-09-11"
ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
OPENING = ROOT / "src" / "franchise_opening_night_ux_v1.py"
FLOW = ROOT / "src" / "franchise_game_flow_v1.py"
SHOWCASE = ROOT / "src" / "franchise_visual_overhaul_v3.py"
CPU_UI = ROOT / "src" / "franchise_cpu_front_office_ui_v1.py"


def _compile(path: Path) -> bool:
    try:
        py_compile.compile(str(path), doraise=True)
        return True
    except Exception:
        return False


def main() -> int:
    page = PAGE.read_text(encoding="utf-8")
    opening = OPENING.read_text(encoding="utf-8")
    flow = FLOW.read_text(encoding="utf-8")
    showcase = SHOWCASE.read_text(encoding="utf-8")
    cpu = CPU_UI.read_text(encoding="utf-8")

    # Basic pure helper fixture for opening-state detection.
    import importlib.util
    spec = importlib.util.spec_from_file_location("opening_ux_fixture", OPENING)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    fixture = SimpleNamespace(
        phase=SimpleNamespace(value="offseason"),
        transition_count=0,
        season_history=[],
    )

    checks = {
        "all_changed_files_compile": all(_compile(p) for p in (PAGE, OPENING, FLOW, SHOWCASE, CPU_UI)),
        "opening_state_fixture_detected": bool(module.is_opening_offseason(fixture)),
        "opening_ux_imported": "from franchise_opening_night_ux_v1 import" in page,
        "opening_visuals_injected": "inject_opening_night_visuals_v1(" in page,
        "opening_launchpad_rendered_on_command_center": "render_opening_night_launchpad_v1(" in page,
        "opening_schedule_is_labeled_preview": "Opening week preview · season clock not started" in page,
        "normal_game_flow_suppressed_until_season_open": "if not _franchise_opening_setup_v2:" in page,
        "old_command_center_open_game_hidden_during_setup": "if snapshot.next_game_id and not _franchise_opening_setup_v2:" in page,
        "opening_uses_existing_certified_commit": "commit_opening_regular_season_live(" in opening,
        "opening_uses_existing_readiness_preview": "preview_opening_regular_season(" in opening,
        "opening_does_not_generate_fake_results": "simulate" not in opening.lower(),
        "game_flow_v2_marker": "franchise-game-flow-v2.0-season-sync-2026-09-11" in flow,
        "game_flow_receives_live_state": "state=state," in page and "player_headshot_resolver=player_headshot_url" in page,
        "matchup_focus_exists": "MATCHUP FOCUS" in flow and "Players to watch" in flow,
        "key_players_derive_from_rotation": "starter_ids" in flow and "overall_rating" in flow,
        "game_pending_state_prevents_noop_sim": '"Game pending" if controlled_game_is_next_event else "Sim next date"' in flow,
        "game_pending_explains_pause": "calendar simulation is paused by design" in flow,
        "open_game_day_label_is_clear": '"Open Game Day" if next_game_id else "Open schedule"' in flow,
        "existing_advance_engine_preserved": "advance_franchise_scope(" in page,
        "showcase_disables_game_day_before_start": "Game Day unlocks after season start" in showcase,
        "showcase_calls_schedule_a_preview": "Opening-week preview" in showcase,
        "league_hub_metrics_are_wider": "identity_top = st.columns(4)" in cpu and "identity_needs = st.columns(3)" in cpu,
        "active_save_replacement_not_added": "replace_active" not in opening and "replace_active" not in flow,
    }
    failed = [name for name, passed in checks.items() if not passed]
    result = {"version": VERSION, "checks": checks, "failed_checks": failed, "passed": not failed}
    print(json.dumps(result, indent=2))
    print()
    if failed:
        print("FRANCHISE SEASON FLOW V2 VALIDATOR FAILED")
        return 1
    print("FRANCHISE SEASON FLOW V2 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
