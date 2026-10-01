from __future__ import annotations

import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

SEASON = SRC / "simulation_season_transition_v1.py"
TWO_WAY = SRC / "franchise_cpu_two_way_roster_completion_v1.py"
BOUNDARY = SRC / "franchise_season_boundary_durable_transition_v1.py"
TRACE = SRC / "run_franchise_v2_roster_lifecycle_trace_v1.py"
ACTIVE = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

EXPECTED_SEASON_SHA = "b30bc87b655629d4696c7239d30b0e1205eb43f9cab988cd55fc57b197c96d15"
EXPECTED_TWO_WAY_SHA = "964e35d02f90b60c985313cc8fd9399a55534fed10754d33274a56dc856aaa44"
EXPECTED_BOUNDARY_SHA = "99dd17f937239fecf25a7d8e30bf494f3620a758c65c4dfd2a15fbaff4702bdf"
EXPECTED_TRACE_SHA = "cd28bafd38172ed9f13f089ae6a6945d014597546482555c1837985b589247f4"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    active_before = sha(ACTIVE) if ACTIVE.is_file() else ""
    source = SEASON.read_text(encoding="utf-8")
    ast.parse(source, filename=str(SEASON))

    clock = source.split(
        "def advance_rostered_contract_clock_v1(", 1
    )[1].split("\ndef ", 1)[0]

    checks = {
        "exact_patched_season_transition": sha(SEASON) == EXPECTED_SEASON_SHA,
        "two_way_completion_hotfix_unchanged": sha(TWO_WAY) == EXPECTED_TWO_WAY_SHA,
        "season_boundary_integration_unchanged": sha(BOUNDARY) == EXPECTED_BOUNDARY_SHA,
        "lifecycle_trace_unchanged": sha(TRACE) == EXPECTED_TRACE_SHA,
        "two_way_expiry_detected_from_flag": 'bool(getattr(player, "two_way", False))' in clock,
        "two_way_expiry_detected_from_roster_status": 'getattr(player, "roster_status", "")' in clock,
        "two_way_expiry_detected_from_contract_status": 'getattr(contract, "status", "")' in clock,
        "expired_two_way_flag_cleared": "player.two_way = False" in clock,
        "free_agent_roster_status_preserved": 'player.roster_status = "free_agent"' in clock,
        "free_agent_pool_status_preserved": 'status="free_agent_pool"' in clock,
        "free_agent_pool_membership_preserved": "free_agents.add(player_id)" in clock,
        "two_way_salary_cleared": "updated_contract.salary = None" in clock,
        "two_way_option_cleared": 'updated_contract.option_type = ""' in clock,
        "two_way_guarantee_cleared": "updated_contract.guaranteed = None" in clock,
        "not_under_contract_metadata_written": '"not_under_contract"' in clock,
        "expired_two_way_diagnostic_added": '"expired_two_way_count": len(expired_two_way)' in clock,
        "standard_multi_year_decrement_preserved": "years_remaining=years_remaining - 1" in clock,
        "rookie_pending_guard_preserved": '"rookie_scale_pending"' in clock,
        "synthetic_cleanup_preserved": '"simulation_replacement"' in clock,
    }

    active_after = sha(ACTIVE) if ACTIVE.is_file() else ""
    checks["active_checkpoint_unchanged"] = active_before == active_after

    print("FRANCHISE V2 TWO-WAY EXPIRY REENTRY HOTFIX V1.0.1 STATIC VALIDATION")
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
