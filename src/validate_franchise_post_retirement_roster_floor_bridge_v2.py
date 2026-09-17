from __future__ import annotations

import ast
from pathlib import Path

CAREER_MARKER = "FRANCHISE_POST_RETIREMENT_ROSTER_FLOOR_DEFERRED_VALIDATION_V2"
CPU_MARKER = "FRANCHISE_POST_RETIREMENT_ROSTER_FLOOR_IN_MEMORY_BRIDGE_V2"
PAGE_MARKER = "FRANCHISE_POST_RETIREMENT_ROSTER_FLOOR_UI_V2"


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    career = (root / "src" / "career_lifecycle_transition_adapter_v1.py").read_text(encoding="utf-8")
    cpu = (root / "src" / "franchise_free_agency_cpu_execution_v1.py").read_text(encoding="utf-8")
    page = (root / "pages" / "5_Franchise_Mode.py").read_text(encoding="utf-8")

    checks = {}
    try:
        ast.parse(career)
        ast.parse(cpu)
        ast.parse(page)
        checks["all_patched_files_compile"] = True
    except Exception:
        checks["all_patched_files_compile"] = False

    checks["career_deferred_validation_present"] = CAREER_MARKER in career
    checks["career_preview_uses_deferred_validation"] = (
        "_validate_post_retirement_transition_state_v2(trial_state)" in career
    )
    checks["career_commit_uses_deferred_validation"] = (
        "_validate_post_retirement_transition_state_v2(transitioned_state)" in career
    )
    checks["cpu_in_memory_bridge_present"] = (
        CPU_MARKER in cpu
        and "def execute_cpu_roster_floor_bridge_in_memory_v2(" in cpu
    )
    checks["cpu_bridge_reuses_rescue_offer_builder"] = (
        "build_cpu_roster_floor_rescue_opportunity(" in cpu
    )
    checks["cpu_bridge_reuses_financial_gate"] = (
        "evaluate_rights_exception_financial_gate" in cpu
        and "commit_free_agency_preview(" in cpu
    )
    checks["page_bridge_present"] = PAGE_MARKER in page
    checks["page_bridge_after_rookie_activation"] = (
        page.index("activate_drafted_rookies_after_transition(")
        < page.index(PAGE_MARKER)
    )
    checks["page_bridge_before_schedule_install"] = (
        page.index(PAGE_MARKER)
        < page.index("if not transitioned.schedule:", page.index(PAGE_MARKER))
    )
    checks["final_validator_still_present"] = (
        "validate_simulation_league_state(" in page
    )
    checks["atomic_boundary_commit_preserved"] = (
        "commit_atomic_season_boundary_live(" in page
    )

    failed = [name for name, ok in checks.items() if not ok]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE POST-RETIREMENT ROSTER-FLOOR BRIDGE V2 VALIDATOR FAILED")
        return 1
    print("FRANCHISE POST-RETIREMENT ROSTER-FLOOR BRIDGE V2 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
