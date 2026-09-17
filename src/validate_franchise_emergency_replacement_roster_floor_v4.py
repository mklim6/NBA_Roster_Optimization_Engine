from __future__ import annotations

import ast
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    cpu = (
        root / "src" / "franchise_free_agency_cpu_execution_v1.py"
    ).read_text(encoding="utf-8")
    clock = (
        root / "src" / "simulation_season_transition_v1.py"
    ).read_text(encoding="utf-8")

    checks = {}
    try:
        ast.parse(cpu)
        ast.parse(clock)
        checks["patched_modules_compile"] = True
    except Exception:
        checks["patched_modules_compile"] = False

    checks["v3_preserved"] = (
        "FRANCHISE_POST_RETIREMENT_MARKET_CLEARANCE_V3" in cpu
    )
    checks["v4_emergency_helper_present"] = (
        "FRANCHISE_SYNTHETIC_EMERGENCY_REPLACEMENT_V4" in cpu
        and "def _add_synthetic_emergency_replacement_v4(" in cpu
    )
    checks["normal_rescue_precedes_emergency"] = (
        cpu.index("build_cpu_roster_floor_rescue_opportunity(")
        < cpu.index("_add_synthetic_emergency_replacement_v4(",
                    cpu.index("def execute_cpu_roster_floor_bridge_in_memory_v2("))
    )
    checks["market_clearance_precedes_emergency"] = (
        cpu.index("_build_cpu_roster_compliance_market_clearance_v3(",
                  cpu.index("def execute_cpu_roster_floor_bridge_in_memory_v2("))
        < cpu.index("_add_synthetic_emergency_replacement_v4(",
                    cpu.index("def execute_cpu_roster_floor_bridge_in_memory_v2("))
    )
    checks["replacement_uses_established_status"] = (
        'status="simulation_replacement"' in cpu
        and 'roster_status="emergency_replacement"' in cpu
        and "overall_rating=66.0" in cpu
    )
    checks["replacement_is_synthetic"] = "synthetic=True" in cpu
    checks["medical_state_is_synced"] = "ensure_injury_fatigue_state(state)" in cpu
    checks["cleanup_marker_present"] = (
        "FRANCHISE_SYNTHETIC_EMERGENCY_REPLACEMENT_CLEANUP_V4" in clock
    )
    checks["cleanup_removes_player_maps"] = (
        "state.players.pop(player_id, None)" in clock
        and "state.injuries.pop(player_id, None)" in clock
        and "state.player_season_totals.pop(player_id, None)" in clock
    )
    checks["strict_final_validation_still_present"] = (
        "validate_simulation_league_state(working)" in cpu
    )

    failed = [name for name, ok in checks.items() if not ok]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE EMERGENCY REPLACEMENT ROSTER-FLOOR V4 VALIDATOR FAILED")
        return 1

    print("FRANCHISE EMERGENCY REPLACEMENT ROSTER-FLOOR V4 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
