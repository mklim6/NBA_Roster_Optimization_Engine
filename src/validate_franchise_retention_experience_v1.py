from __future__ import annotations

import importlib.util
import json
import py_compile
from pathlib import Path
from types import SimpleNamespace


VERSION = "franchise-retention-experience-v1-validator-2026-09-11"
ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src" / "franchise_retention_experience_v1.py"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"


def main() -> int:
    module_text = MODULE.read_text(encoding="utf-8") if MODULE.exists() else ""
    page_text = PAGE.read_text(encoding="utf-8") if PAGE.exists() else ""
    checks: dict[str, bool] = {
        "module_exists": MODULE.exists(),
        "page_exists": PAGE.exists(),
    }
    compile_error = ""
    try:
        py_compile.compile(str(MODULE), doraise=True)
        py_compile.compile(str(PAGE), doraise=True)
        checks["module_and_page_compile"] = True
    except Exception as exc:
        checks["module_and_page_compile"] = False
        compile_error = f"{type(exc).__name__}: {exc}"

    loaded = None
    import_error = ""
    try:
        spec = importlib.util.spec_from_file_location("franchise_retention_experience_v1", MODULE)
        loaded = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(loaded)
        checks["module_imports"] = True
    except Exception as exc:
        checks["module_imports"] = False
        import_error = f"{type(exc).__name__}: {exc}"

    checks.update(
        {
            "version_is_current": "franchise-retention-experience-v1.0-2026-09-11" in module_text,
            "page_imports_retention_layer": "from franchise_retention_experience_v1 import" in page_text,
            "page_injects_retention_visuals": "inject_franchise_retention_visuals_v1(" in page_text,
            "page_renders_retention_hub": "render_franchise_retention_hub_v1(" in page_text,
            "welcome_back_briefing_exists": "Welcome back, GM" in module_text,
            "gm_paths_exist": all(path in module_text for path in ("Balanced", "Builder", "Win Now", "Deal Maker")),
            "gm_path_survives_section_navigation": all(
                token in module_text
                for token in ("persistent_path_key", "widget_path_key", "on_change=_remember_gm_path")
            ),
            "gm_path_uses_existing_durable_ui_preferences": (
                '"franchise_gm_path_v1"' in page_text
                and "persist_gm_path=_save_franchise_ui_preferences_v1_6" in page_text
                and "persist_gm_path()" in module_text
            ),
            "quest_board_exists": "Season quest board" in module_text,
            "milestone_cabinet_exists": "Milestone cabinet" in module_text,
            "universe_story_feed_exists": "Around your universe" in module_text,
            "responsive_rules_exist": "@media(max-width:650px)" in module_text,
            "reduced_motion_rules_exist": "prefers-reduced-motion:reduce" in module_text,
            "presentation_layer_does_not_import_checkpoint": "simulation_franchise_checkpoint" not in module_text,
            "presentation_layer_does_not_write_files": ".write_" not in module_text and "open(" not in module_text,
            "presentation_layer_does_not_commit": "commit_" not in module_text and "save_franchise" not in module_text,
        }
    )

    if loaded is not None:
        fixture_profile = {
            "young_core": 4,
            "rotation_ready": True,
            "unavailable": 0,
        }
        goals = loaded._goal_set(
            phase="regular_season",
            history_count=0,
            games=12,
            wins=6,
            moves=1,
            profile=fixture_profile,
            path="Builder",
        )
        checks["goal_fixture_has_four_quests"] = len(goals) == 4
        checks["goal_fixture_unlocks_real_progress"] = all(goal["complete"] for goal in goals)
        fixture_state = SimpleNamespace(
            season_history=[SimpleNamespace(champion="CHI"), SimpleNamespace(champion="BOS")]
        )
        checks["championship_milestone_is_team_scoped"] = loaded._championship_count(fixture_state, "CHI") == 1

    failed = [name for name, passed in checks.items() if not passed]
    result = {
        "version": VERSION,
        "checks": checks,
        "compile_error": compile_error,
        "import_error": import_error,
        "failed_checks": failed,
        "passed": not failed,
    }
    print(json.dumps(result, indent=2))
    if failed:
        return 1
    print("\nFRANCHISE RETENTION EXPERIENCE V1 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
