from __future__ import annotations

import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

MODULE = SRC / "franchise_undrafted_rookie_free_agent_v1.py"
BOUNDARY = SRC / "franchise_season_boundary_durable_transition_v1.py"
DRAFT = SRC / "franchise_draft_engine_v1.py"
LEAGUE = SRC / "simulation_league_state_v1.py"
TWO_WAY = SRC / "franchise_cpu_two_way_roster_completion_v1.py"
SEASON = SRC / "simulation_season_transition_v1.py"
TRACE = SRC / "run_franchise_v2_roster_lifecycle_trace_v1.py"
ACTIVE = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

EXPECTED_MODULE_SHA = "ab15bfe55ee09c73fe4ea82c9294d1d44fe866c9a2313ab857347d8ad80e6538"
EXPECTED_BOUNDARY_SHA = "99dd17f937239fecf25a7d8e30bf494f3620a758c65c4dfd2a15fbaff4702bdf"
EXPECTED_DRAFT_SHA = "cb3e8db42511fbff17b73fe6fa034bad71085ad1f740917a22e44e870d7724e6"
EXPECTED_LEAGUE_SHA = "8d99fd44353373f63bcfc1bc69877a62e601eb35ab459c30f2eeafcfcc1e0efb"
EXPECTED_TWO_WAY_SHA = "964e35d02f90b60c985313cc8fd9399a55534fed10754d33274a56dc856aaa44"
EXPECTED_SEASON_SHA = "b30bc87b655629d4696c7239d30b0e1205eb43f9cab988cd55fc57b197c96d15"
EXPECTED_TRACE_SHA = "cd28bafd38172ed9f13f089ae6a6945d014597546482555c1837985b589247f4"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    active_before = sha(ACTIVE) if ACTIVE.is_file() else ""
    module = MODULE.read_text(encoding="utf-8")
    boundary = BOUNDARY.read_text(encoding="utf-8")
    ast.parse(module, filename=str(MODULE))
    ast.parse(boundary, filename=str(BOUNDARY))

    checks = {
        "exact_bridge_module": sha(MODULE) == EXPECTED_MODULE_SHA,
        "exact_boundary_integration": sha(BOUNDARY) == EXPECTED_BOUNDARY_SHA,
        "draft_engine_unchanged": sha(DRAFT) == EXPECTED_DRAFT_SHA,
        "league_state_unchanged": sha(LEAGUE) == EXPECTED_LEAGUE_SHA,
        "two_way_hotfix_unchanged": sha(TWO_WAY) == EXPECTED_TWO_WAY_SHA,
        "expiry_reentry_hotfix_unchanged": sha(SEASON) == EXPECTED_SEASON_SHA,
        "lifecycle_trace_unchanged": sha(TRACE) == EXPECTED_TRACE_SHA,
        "requires_completed_draft": '"draft_complete"' in module,
        "requires_target_season_match": "target != live_season" in module,
        "uses_only_undrafted_prospects": 'not bool(row.get("drafted", False))' in module,
        "materializes_real_free_agents": 'roster_status="free_agent"' in module,
        "free_agent_contract_state": 'status="free_agent_pool"' in module,
        "undrafted_not_two_way_by_default": "two_way=False" in module,
        "created_post_transition_as_nonsynthetic": "synthetic=False" in module,
        "zero_service_years": 'setattr(player, "years_of_service", 0)' in module,
        "rookie_metadata_present": 'setattr(player, "undrafted_rookie", True)' in module,
        "injury_profile_synchronized": "synchronize_injury_profile(candidate" not in module and "synchronize_injury_profile(state, player_id)" in module,
        "free_agent_pool_membership": "state.free_agent_player_ids = tuple(free_agents)" in module,
        "population_ecology_before_undrafted": (
            boundary.find("apply_free_agent_population_ecology_at_boundary(")
            < boundary.find("materialize_undrafted_rookie_free_agents_after_transition(")
        ),
        "boundary_bridge_before_two_way": (
            boundary.find("materialize_undrafted_rookie_free_agents_after_transition(")
            < boundary.find("complete_cpu_two_way_rosters_at_boundary(")
        ),
        "two_way_uses_undrafted_state": "complete_cpu_two_way_rosters_at_boundary(\n        undrafted_state," in boundary,
        "trade_reconcile_still_after_two_way": (
            boundary.find("complete_cpu_two_way_rosters_at_boundary(")
            < boundary.find("reconcile_trade_state_after_season_boundary(")
        ),
    }

    active_after = sha(ACTIVE) if ACTIVE.is_file() else ""
    checks["active_checkpoint_unchanged"] = active_before == active_after

    print("FRANCHISE V2 UNDRAFTED ROOKIE FREE AGENT BRIDGE V1 STATIC VALIDATION")
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
