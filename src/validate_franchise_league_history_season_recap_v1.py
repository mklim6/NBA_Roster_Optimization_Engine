from __future__ import annotations
import ast
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    module_path = root / "src" / "franchise_league_history_season_recap_v1.py"
    page_path = root / "pages" / "5_Franchise_Mode.py"
    source = module_path.read_text(encoding="utf-8")
    page = page_path.read_text(encoding="utf-8")
    checks = {}
    try:
        tree = ast.parse(source)
        ast.parse(page)
        checks["module_and_page_compile"] = True
    except Exception:
        tree = None
        checks["module_and_page_compile"] = False

    checks["version_is_v1"] = "franchise-league-history-season-recap-v1.0-2026-09-16" in source
    checks["page_import_present"] = "FRANCHISE_LEAGUE_HISTORY_SEASON_RECAP_V1_IMPORT" in page
    checks["page_render_present"] = "FRANCHISE_LEAGUE_HISTORY_SEASON_RECAP_V1_RENDER" in page
    checks["legacy_renderer_preserved"] = "render_franchise_timeline_trophy_room_v1(" in page
    checks["completed_season_live_path_present"] = "games >= 82" in source and "current completed season appears here immediately" in source
    checks["award_engine_reused"] = "build_regular_awards_v2" in source and "build_playoff_honors_v2" in source
    checks["legacy_snapshot_reused"] = "build_franchise_legacy_snapshot_v1" in source
    checks["championship_archive_present"] = "def _championship_rows(" in source
    checks["draft_history_present"] = "franchise_draft_history_v1" in source
    checks["transaction_history_present"] = "Recent roster moves" in source
    checks["season_recap_tab_present"] = "🏆 Season Recap" in source
    checks["league_history_tab_present"] = "📚 League History" in source
    checks["awards_tab_present"] = "🏅 Awards & Honors" in source
    checks["draft_moves_tab_present"] = "🧾 Draft & Moves" in source
    checks["no_checkpoint_write"] = "save_franchise_checkpoint" not in source and "commit_franchise_checkpoint" not in source
    checks["no_state_assignment"] = "state.phase =" not in source and "state.season_history.append" not in source
    checks["responsive_css_present"] = "@media(max-width:1050px)" in source and "@media(max-width:650px)" in source
    checks["render_function_defined"] = "def render_league_history_season_recap_v1(" in source
    checks["build_function_defined"] = "def build_league_history_season_recap_v1(" in source

    # Structural AST verification: the module must define both public V1 functions.
    if tree is not None:
        funcs = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        checks["ast_public_functions_present"] = {
            "build_league_history_season_recap_v1",
            "render_league_history_season_recap_v1",
        }.issubset(funcs)
    else:
        checks["ast_public_functions_present"] = False

    failed = [k for k,v in checks.items() if not v]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE LEAGUE HISTORY + SEASON RECAP V1 VALIDATOR FAILED")
        return 1
    print("FRANCHISE LEAGUE HISTORY + SEASON RECAP V1 VALIDATOR PASSED")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
