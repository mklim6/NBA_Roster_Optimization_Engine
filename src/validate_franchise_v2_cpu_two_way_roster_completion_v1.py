from __future__ import annotations

import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
BOUNDARY = SRC / "franchise_season_boundary_durable_transition_v1.py"
MODULE = SRC / "franchise_cpu_two_way_roster_completion_v1.py"
LIVE = SRC / "franchise_free_agency_live_signing_v1.py"
FINANCIAL = SRC / "franchise_financial_cba_bridge_v1.py"
TRACE = SRC / "run_franchise_v2_roster_lifecycle_trace_v1.py"
ACTIVE = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

EXPECTED_BOUNDARY_SHA = "99dd17f937239fecf25a7d8e30bf494f3620a758c65c4dfd2a15fbaff4702bdf"
EXPECTED_MODULE_SHA = "964e35d02f90b60c985313cc8fd9399a55534fed10754d33274a56dc856aaa44"
EXPECTED_LIVE_SHA = "3dc47f982c66cec32d974f0dbe90975db435de350294c5883d16a635c580b1ce"
EXPECTED_FINANCIAL_SHA = "ca77b3fb3f7719755122b41ab2d9863d37f290864567b3dc53a42b22485f6fb6"
EXPECTED_TRACE_SHA = "cd28bafd38172ed9f13f089ae6a6945d014597546482555c1837985b589247f4"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    active_before = sha(ACTIVE) if ACTIVE.is_file() else ""
    boundary = BOUNDARY.read_text(encoding="utf-8")
    module = MODULE.read_text(encoding="utf-8")
    ast.parse(boundary, filename=str(BOUNDARY))
    ast.parse(module, filename=str(MODULE))

    checks = {
        "exact_boundary_source": sha(BOUNDARY) == EXPECTED_BOUNDARY_SHA,
        "exact_two_way_module": sha(MODULE) == EXPECTED_MODULE_SHA,
        "live_signing_dependency_unchanged": sha(LIVE) == EXPECTED_LIVE_SHA,
        "financial_dependency_unchanged": sha(FINANCIAL) == EXPECTED_FINANCIAL_SHA,
        "trace_dependency_unchanged": sha(TRACE) == EXPECTED_TRACE_SHA,
        "project_two_way_max_reused": "from franchise_financial_cba_bridge_v1 import TWO_WAY_MAX" in module,
        "controlled_team_agency_preserved": "team_code not in controlled_set" in module,
        "standard_fa_not_reused": "franchise_free_agency_transaction_v1" not in module,
        "two_way_flag_written": "player.two_way = True" in module,
        "two_way_status_written": 'player.roster_status = "two_way"' in module,
        "two_way_contract_written": 'contract.status = "two_way"' in module,
        "zero_cap_salary_written": "contract.salary = 0.0" in module,
        "one_year_contract_clock": "contract.years_remaining = 1" in module,
        "free_agent_pool_removed": "state.free_agent_player_ids = tuple(free_agents)" in module,
        "rotation_untouched": (
            "team_state.active_player_ids =" not in module
            and "team_state.rotation =" not in module
            and ".starter_ids =" not in module
            and ".rotation_player_ids =" not in module
            and ".minutes_targets =" not in module
        ),
        "population_ecology_precedes_undrafted_and_two_way": (
            boundary.find("apply_free_agent_population_ecology_at_boundary(")
            < boundary.find("materialize_undrafted_rookie_free_agents_after_transition(")
            < boundary.find("complete_cpu_two_way_rosters_at_boundary(")
        ),
        "boundary_calls_completion_before_reconcile": (
            boundary.find("complete_cpu_two_way_rosters_at_boundary(")
            < boundary.find("reconcile_trade_state_after_season_boundary(")
        ),
        "reconcile_uses_completed_state": "reconcile_trade_state_after_season_boundary(\n            two_way_state," in boundary,
        "developmental_guardrail": "overall > 80.0" in module and "age > 27.0" in module,
        "state_validation_preserved": "validate_simulation_league_state(candidate)" in module,
    }

    active_after = sha(ACTIVE) if ACTIVE.is_file() else ""
    checks["active_checkpoint_unchanged"] = active_before == active_after

    print("FRANCHISE V2 CPU TWO-WAY ROSTER COMPLETION V1 STATIC VALIDATION")
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        print("VALIDATION FAILED")
        for name in failed:
            print(f"  - {name}")
        return 1
    print("VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
