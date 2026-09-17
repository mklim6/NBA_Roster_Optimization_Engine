from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("returning_gm_validator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load returning-GM module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    module_path = root / "src" / "franchise_returning_gm_v1.py"
    page_path = root / "pages" / "5_Franchise_Mode.py"
    module_source = module_path.read_text(encoding="utf-8")
    page_source = page_path.read_text(encoding="utf-8")
    module = _load(module_path)

    checks = {}
    try:
        ast.parse(module_source)
        ast.parse(page_source)
        checks["module_and_page_compile"] = True
    except Exception:
        checks["module_and_page_compile"] = False

    checks["version_is_current"] = module.RETURNING_GM_VERSION == "franchise-returning-gm-v1.0-2026-09-15"
    checks["snapshot_persists_in_ui_preferences"] = '"franchise_retention_snapshot_v1"' in page_source
    checks["existing_retention_hub_preserved"] = "render_franchise_retention_hub_v1(" in page_source
    checks["returning_gm_render_wired"] = "render_returning_gm_v1(" in page_source
    checks["returning_gm_visuals_wired"] = "inject_returning_gm_visuals_v1(" in page_source
    checks["no_checkpoint_write_in_module"] = (
        "save_franchise_checkpoint" not in module_source
        and "commit_franchise_checkpoint" not in module_source
    )
    checks["gm_path_still_drives_identity"] = 'st.session_state.get("franchise_gm_path_v1"' in module_source
    checks["mobile_layout_present"] = "@media(max-width:1050px)" in module_source and "@media(max-width:650px)" in module_source

    previous = {
        "team": "CHI", "season": "2026-27", "phase": "regular_season",
        "wins": 2, "losses": 2, "moves": 1, "roster_count": 15,
        "championships": 0, "milestones": ["Tip-Off", "First Win"],
    }
    current = {
        "team": "CHI", "season": "2026-27", "phase": "regular_season",
        "wins": 5, "losses": 3, "moves": 2, "roster_count": 14,
        "championships": 0, "milestones": ["Tip-Off", "First Win", "Deal Maker"],
    }
    changes = module.returning_changes(previous, current)
    checks["detects_game_results"] = any("since your last visit" in item["title"] for item in changes)
    checks["detects_transactions"] = any("roster move" in item["title"] for item in changes)
    checks["detects_roster_change"] = any("Roster shrunk" in item["title"] for item in changes)
    checks["detects_new_milestone"] = any(item["kind"] == "milestone" for item in changes)

    career = module.gm_career_profile(wins=45, games=82, moves=6, seasons=2, championships=1, milestones=5)
    checks["gm_career_progresses"] = career["xp"] > 0 and career["label"] != "Rookie GM"
    checks["builder_identity_contextual"] = module.franchise_identity("Builder", young_core=4, wins=20, losses=30, moves=1)[0] == "Development Program"

    failed = [name for name, ok in checks.items() if not ok]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE RETURNING GM V1 VALIDATOR FAILED")
        return 1
    print("FRANCHISE RETURNING GM V1 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
