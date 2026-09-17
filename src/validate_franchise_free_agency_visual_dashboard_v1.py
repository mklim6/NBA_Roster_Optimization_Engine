from __future__ import annotations

import ast
import importlib.util
import json
import py_compile
from pathlib import Path


VERSION = "franchise-free-agency-visual-dashboard-v1-validator-2026-09-12"
ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src" / "franchise_free_agency_visual_dashboard_v1.py"
WORKSPACE = ROOT / "src" / "franchise_free_agency_workspace_v1.py"


def main() -> None:
    module_text = MODULE.read_text(encoding="utf-8")
    workspace_text = WORKSPACE.read_text(encoding="utf-8")
    compile_error = ""
    import_error = ""
    module = None
    try:
        ast.parse(module_text)
        py_compile.compile(str(MODULE), doraise=True)
        py_compile.compile(str(WORKSPACE), doraise=True)
    except Exception as exc:  # pragma: no cover - diagnostic reporting
        compile_error = str(exc)
    try:
        spec = importlib.util.spec_from_file_location("franchise_free_agency_visual_dashboard_v1", MODULE)
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to load visual dashboard module")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - diagnostic reporting
        import_error = str(exc)

    helpers = {
        "money_format_is_compact": False,
        "top_targets_use_actual_overall": False,
    }
    if module is not None:
        rows = [
            {"player_id": "1", "player_name": "Third", "overall": 81.0, "potential": 90.0},
            {"player_id": "2", "player_name": "First", "overall": 94.0, "potential": 94.0},
            {"player_id": "3", "player_name": "Second", "overall": 88.0, "potential": 89.0},
        ]
        helpers = {
            "money_format_is_compact": module._money(55_900_000) == "$55.9M",
            "top_targets_use_actual_overall": module._top_targets(rows)[0]["player_name"] == "First",
        }

    checks = {
        "module_exists": MODULE.exists(),
        "workspace_exists": WORKSPACE.exists(),
        "module_and_workspace_compile": not compile_error,
        "module_imports": not import_error,
        "version_current": "franchise-free-agency-visual-dashboard-v1.0-2026-09-12" in module_text,
        "workspace_version_current": "v1.3-visual-command-desk-2026-09-12" in workspace_text,
        "workspace_imports_dashboard": "from franchise_free_agency_visual_dashboard_v1 import" in workspace_text,
        "workspace_renders_dashboard": "render_free_agency_visual_dashboard_v1(" in workspace_text,
        "real_payroll_is_used": "team_guaranteed_payroll(" in workspace_text,
        "real_calendar_snapshot_is_used": "free_agency_calendar_snapshot(state)" in workspace_text,
        "command_desk_exists": "Free Agency Command Desk" in module_text,
        "market_spotlights_exist": "fav-target" in module_text,
        "financial_ledger_exists": "Base cap margin" in module_text,
        "cap_margin_has_boundary_copy": "Before holds / exceptions" in module_text,
        "roster_and_negotiation_context_exists": "Live talks" in module_text and "Rostered" in module_text,
        "offseason_progress_rail_exists": "Draft bridge" in module_text,
        "responsive_rules_exist": "@media(max-width:620px)" in module_text,
        "reduced_motion_rules_exist": "prefers-reduced-motion" in module_text,
        "offer_builder_preserved": 'st.markdown("### Offer builder")' in workspace_text,
        "negotiation_suite_preserved": "render_negotiation_room_intro_v1(" in workspace_text,
        "presentation_layer_does_not_load_checkpoint": "checkpoint" not in module_text.lower(),
        "presentation_layer_does_not_write_files": ".write_text(" not in module_text and "open(" not in module_text,
        "presentation_layer_does_not_commit": "commit_" not in module_text and "set_franchise_state" not in module_text,
        **helpers,
    }
    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "version": VERSION,
        "checks": checks,
        "compile_error": compile_error,
        "import_error": import_error,
        "failed_checks": failed,
        "passed": not failed,
    }
    print(json.dumps(report, indent=2))
    if failed:
        raise SystemExit(1)
    print("\nFRANCHISE FREE AGENCY VISUAL DASHBOARD V1 VALIDATOR PASSED")


if __name__ == "__main__":
    main()

