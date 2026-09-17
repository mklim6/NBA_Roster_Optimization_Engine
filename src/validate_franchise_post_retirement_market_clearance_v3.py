from __future__ import annotations

import ast
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    path = root / "src" / "franchise_free_agency_cpu_execution_v1.py"
    source = path.read_text(encoding="utf-8")

    checks = {}
    try:
        ast.parse(source)
        checks["module_compiles"] = True
    except Exception:
        checks["module_compiles"] = False

    checks["v2_bridge_preserved"] = (
        "FRANCHISE_POST_RETIREMENT_ROSTER_FLOOR_IN_MEMORY_BRIDGE_V2"
        in source
    )
    checks["v3_market_clearance_present"] = (
        "FRANCHISE_POST_RETIREMENT_MARKET_CLEARANCE_V3" in source
        and "def _build_cpu_roster_compliance_market_clearance_v3(" in source
    )
    checks["normal_rescue_runs_first"] = (
        source.index("build_cpu_roster_floor_rescue_opportunity(")
        < source.index("_build_cpu_roster_compliance_market_clearance_v3(", source.index("def execute_cpu_roster_floor_bridge_in_memory_v2("))
    )
    checks["minimum_contract_only"] = (
        "years=1" in source
        and "guaranteed=True" in source
        and "minimum_salary_floor_for_state(" in source
    )
    checks["replacement_guardrail_present"] = (
        "overall <= 76.0 or market_ratio <= 1.75" in source
        and "overall <= 79.0 and market_ratio <= 2.50" in source
    )
    checks["financial_gate_preserved"] = (
        "financial_gate=evaluate_rights_exception_financial_gate" in source
    )
    checks["controlled_teams_still_excluded"] = (
        "_cpu_roster_floor_deficits(working, controlled)" in source
    )
    checks["strict_final_validation_preserved"] = (
        "validate_simulation_league_state(working)" in source
    )

    failed = [name for name, ok in checks.items() if not ok]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE POST-RETIREMENT MARKET CLEARANCE V3 VALIDATOR FAILED")
        return 1

    print("FRANCHISE POST-RETIREMENT MARKET CLEARANCE V3 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
