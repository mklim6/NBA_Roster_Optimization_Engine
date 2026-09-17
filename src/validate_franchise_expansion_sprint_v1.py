from __future__ import annotations

import ast
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    files = {
        "morale": root / "src" / "franchise_morale_chemistry_v1.py",
        "roster_hq": root / "src" / "franchise_roster_rotation_headquarters_v1.py",
        "scouting": root / "src" / "franchise_scouting_discovery_v1.py",
        "history": root / "src" / "franchise_history_awards_archive_v1.py",
        "sim": root / "src" / "simulation_league_state_v1.py",
        "engine": root / "src" / "franchise_draft_engine_v1.py",
        "draft_ui": root / "src" / "franchise_draft_ui_v1.py",
        "transition": root / "src" / "simulation_season_transition_v1.py",
        "page": root / "pages" / "5_Franchise_Mode.py",
    }
    source = {key: path.read_text(encoding="utf-8") for key, path in files.items()}
    checks = {}
    try:
        for text in source.values():
            ast.parse(text)
        checks["all_patched_files_compile"] = True
    except Exception:
        checks["all_patched_files_compile"] = False

    checks["morale_module_present"] = "franchise-morale-chemistry-v1.0-2026-09-16" in source["morale"]
    checks["morale_game_hook_present"] = "FRANCHISE_MORALE_GAME_HOOK_V1" in source["sim"]
    checks["roster_hq_present"] = "franchise-roster-rotation-headquarters-v1.0-2026-09-16" in source["roster_hq"]
    checks["roster_hq_page_wired"] = "FRANCHISE_ROSTER_ROTATION_HQ_UI_V1" in source["page"]
    checks["rotation_philosophies_present"] = all(value in source["roster_hq"] for value in ("Balanced", "Win Now", "Development"))
    checks["scouting_module_present"] = "franchise-scouting-discovery-v1.0-2026-09-16" in source["scouting"]
    checks["staff_drives_scouting"] = "scouting_error_band" in source["scouting"] and "team_staff_effects" in source["scouting"]
    checks["draft_ui_wired"] = "FRANCHISE_SCOUTING_DISCOVERY_UI_V1" in source["draft_ui"]
    checks["cpu_imperfect_scouting_wired"] = "FRANCHISE_AI_IMPERFECT_SCOUTING_V1" in source["engine"]
    checks["cpu_no_longer_scores_hidden_potential_directly"] = 'float(prospect["hidden_potential"]) * 0.08' not in source["engine"]
    checks["history_archive_module_present"] = "franchise-history-awards-archive-v1.0-2026-09-16" in source["history"]
    checks["history_archive_hook_present"] = "FRANCHISE_HISTORY_AWARDS_ARCHIVE_HOOK_V1" in source["transition"]
    checks["history_archive_failure_safe"] = "Historical presentation must never block" in source["history"]
    checks["morale_hook_failure_safe"] = "franchise_morale_last_error_v1" in source["sim"]
    checks["ai_scouting_failure_safe"] = "public noisy" in source["engine"]
    checks["season_archive_structure_preserved"] = "archive = SeasonArchive(" in source["transition"] and "state.season_history.append(archive)" in source["transition"]
    checks["no_forced_trade_requests"] = "commit_trade" not in source["morale"] and "trade_request_risk" in source["morale"]

    failed = [name for name, ok in checks.items() if not ok]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE EXPANSION SPRINT V1 VALIDATOR FAILED")
        return 1
    print("FRANCHISE EXPANSION SPRINT V1 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
