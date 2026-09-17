from __future__ import annotations

import importlib.util
import json
import py_compile
from pathlib import Path

VERSION = "franchise-onboarding-progression-v2.0-validator-2026-09-11"
ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
MODULE = ROOT / "src" / "franchise_onboarding_progression_v1.py"

page = PAGE.read_text(encoding="utf-8") if PAGE.exists() else ""
module = MODULE.read_text(encoding="utf-8") if MODULE.exists() else ""

compile_ok = True
compile_error = None
try:
    py_compile.compile(str(MODULE), doraise=True)
    py_compile.compile(str(PAGE), doraise=True)
except Exception as exc:
    compile_ok = False
    compile_error = f"{type(exc).__name__}: {exc}"

import_ok = False
callable_ok = False
legacy_alias_ok = False
import_error = None
if MODULE.exists():
    try:
        spec = importlib.util.spec_from_file_location("franchise_onboarding_progression_v1", MODULE)
        loaded = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(loaded)
        import_ok = True
        callable_ok = callable(getattr(loaded, "render_franchise_progress_coach_v1", None))
        legacy_alias_ok = callable(getattr(loaded, "render_progress_coach_v1", None))
    except Exception as exc:
        import_error = f"{type(exc).__name__}: {exc}"

checks = {
    "module_exists": MODULE.exists(),
    "page_exists": PAGE.exists(),
    "page_and_module_compile": compile_ok,
    "module_imports_cleanly": import_ok,
    "expected_progress_coach_symbol_is_callable": callable_ok,
    "legacy_progress_coach_alias_is_callable": legacy_alias_ok,
    "page_imports_onboarding_module": "from franchise_onboarding_progression_v1 import" in page,
    "page_imports_expected_progress_coach": "render_franchise_progress_coach_v1," in page,
    "page_injects_onboarding_visuals": "inject_franchise_onboarding_visuals_v1(" in page,
    "page_renders_progress_coach": "render_franchise_progress_coach_v1(" in page,
    "page_renders_first_time_tutorial": "render_first_time_tutorial_v1(" in page,
    "page_renders_section_masthead": "render_section_masthead_v1(" in page,
    "sidebar_replay_help_exists": "How to play" in module,
    "guidance_toggle_exists": "Show progression guide" in module,
    "season_journey_replaced_by_control_hud": "Season control" in module,
    "recommended_next_action_exists": "Recommended next action" in module,
    "rookie_gm_walkthrough_exists": "Rookie GM walkthrough" in module,
    "walkthrough_is_four_steps": "1} of 4" in module,
    "persistent_season_control_exists": "Season control" in module,
    "section_risk_labels_exist": "SECTION_EXPERIENCE" in module,
    "team_logo_visuals_exist": "team_logo_url" in module,
    "tutorial_explains_safe_explore": "Safe to explore" in module,
    "tutorial_explains_time_advancement": "Advances the universe" in module,
    "reduced_motion_rules_present": "prefers-reduced-motion:reduce" in module,
    "module_does_not_import_checkpoint": "simulation_franchise_checkpoint" not in module,
    "module_does_not_write_files": ".write_" not in module and "open(" not in module,
}
failed = [k for k, v in checks.items() if not v]
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
    raise SystemExit(1)
print("\nFRANCHISE ONBOARDING + PROGRESSION V2 VALIDATOR PASSED")
