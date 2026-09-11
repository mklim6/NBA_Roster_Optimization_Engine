from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
DRAFT_UI = ROOT / "src" / "franchise_draft_ui_v1.py"
GAME_PAGE = ROOT / "pages" / "4_Game_Simulator.py"
VERSION = "franchise-lifecycle-authority-validator-v1-2026-08-18"


def _function_source(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    lines = text.splitlines()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            end = getattr(node, "end_lineno", None)
            if end is None:
                raise RuntimeError(f"Could not resolve end line for {name}.")
            return "\n".join(lines[node.lineno - 1 : end])
    raise RuntimeError(f"Function {name} was not found in {path}.")


def main() -> int:
    page = PAGE.read_text(encoding="utf-8")
    draft_ui = DRAFT_UI.read_text(encoding="utf-8")
    game_page = GAME_PAGE.read_text(encoding="utf-8")
    render_transition = _function_source(PAGE, "render_franchise_season_transition")
    advance_wrapper = _function_source(PAGE, "advance_to_next_season_with_schedule")
    render_draft = _function_source(DRAFT_UI, "render_draft_room_v1")

    closeout_pos = page.find("# COMPLETED_SEASON_CONTRACT_CLOSEOUT_V1")
    render_call_pos = page.rfind("render_franchise_season_transition(")
    trim_pos = page.find("commit_atomic_cpu_post_draft_trim_live(")
    transition_pos = page.find("advance_to_next_season_with_schedule(state)", trim_pos)
    boundary_pos = page.find("commit_atomic_season_boundary_live(", transition_pos)

    checks = {
        "completed_season_closeout_precedes_franchise_ui": (
            closeout_pos >= 0 and render_call_pos > closeout_pos
        ),
        "opening_regular_season_authority_preserved": (
            "render_opening_regular_season_control_v1(state)" in render_transition
            and "commit_opening_regular_season_live(" in page
        ),
        "old_postseason_preview_button_removed": '"Preview next season"' not in page,
        "old_postseason_preview_session_key_removed": "franchise_build_season_transition_" not in page,
        "old_postseason_commit_session_key_removed": "franchise_commit_season_transition_" not in page,
        "old_postseason_direct_state_commit_removed": "franchise-season-transition" not in page,
        "season_boundary_renderer_is_status_only": (
            "commit_season_transition_preview(" not in render_transition
            and "set_franchise_state(" not in render_transition
            and "Return to Season Boundary" not in render_transition
        ),
        "single_authoritative_open_next_season_button": page.count('"Open next season"') == 1,
        "authoritative_boundary_sequence_exact": (
            0 <= trim_pos < transition_pos < boundary_pos
        ),
        "authoritative_boundary_reloads_post_trim_checkpoint": (
            "after the CPU post-Draft roster trim" in page
            and "target_fingerprint" in page[trim_pos:boundary_pos]
        ),
        "authoritative_boundary_refreshes_both_live_states": (
            page.count('st.session_state[\n                            "franchise_simulation_league_state"') >= 2
            and page.count('st.session_state[\n                            "franchise_trade_league_state"') >= 2
        ),
        "next_season_wrapper_requires_draft_complete": (
            "_draft_transition_status_v1_1_6(" in advance_wrapper
            and "The NBA Draft must be completed before the next " in advance_wrapper
            and "season can open. Draft-state diagnostic:" in advance_wrapper
        ),
        "next_season_wrapper_requires_completed_closeout": (
            "FRANCHISE_LIFECYCLE_AUTHORITY_CONSOLIDATION_V1" in advance_wrapper
            and "completed_season_closeout_applied" in advance_wrapper
            and "Completed-season contract closeout must be committed" in advance_wrapper
        ),
        "draft_ui_direct_transition_callback_removed_from_signature": (
            "advance_next_season" not in render_draft.split(") -> None:", 1)[0]
        ),
        "draft_ui_direct_open_button_removed": "draft_complete_open_next_season_v1_1" not in draft_ui,
        "draft_ui_direct_transition_call_removed": "advance_next_season(state)" not in draft_ui,
        "draft_ui_direct_next_season_checkpoint_commit_removed": "draft-room-next-season" not in draft_ui,
        "draft_ui_routes_to_authoritative_boundary": (
            "Return to Season Boundary" in draft_ui
            and 'set_section("League & Offseason")' in draft_ui
        ),
        "franchise_page_does_not_inject_direct_draft_transition_callback": (
            "advance_next_season=advance_to_next_season_with_schedule" not in page
        ),
        "boundary_exception_detail_interpolates_real_error": (
            'f"Detail: {_season_boundary_exc}"' in page
            and '{{_season_boundary_exc}}' not in page
        ),
        "standalone_game_simulator_transition_controller_preserved": (
            "build_season_transition_preview" in game_page
            and "commit_season_transition_preview" in game_page
        ),
        "generic_transition_fallback_explicitly_non_franchise": (
            "fallback for legacy/non-Franchise callers" in (
                ROOT / "src" / "simulation_season_transition_v1.py"
            ).read_text(encoding="utf-8")
        ),
    }

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "version": VERSION,
        "classification": (
            "franchise_lifecycle_authority_consolidated_v1"
            if not failed
            else "franchise_lifecycle_authority_validation_blocked"
        ),
        "checks": checks,
        "failed_checks": failed,
        "passed": not failed,
        "authority": {
            "opening_2026_27": "franchise_opening_regular_season_transition_v1",
            "completed_season_closeout": "franchise_completed_season_contract_closeout_v1",
            "draft_completion": "franchise_draft_engine_v1",
            "post_draft_cpu_trim": "franchise_cpu_post_draft_roster_trim_live_v1",
            "next_season_transition": "advance_to_next_season_with_schedule",
            "durable_boundary": "franchise_season_boundary_durable_transition_v1",
            "single_ui_entry": "pages/5_Franchise_Mode.py :: Open next season",
        },
    }
    print(json.dumps(report, indent=2))
    if failed:
        raise AssertionError(
            "Franchise lifecycle authority validation failed: " + ", ".join(failed)
        )
    print()
    print("FRANCHISE LIFECYCLE AUTHORITY V1 VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
