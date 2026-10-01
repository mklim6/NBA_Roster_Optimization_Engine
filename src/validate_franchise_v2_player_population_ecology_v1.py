from __future__ import annotations

import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ACTIVE = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

MODULE = SRC / "franchise_free_agent_population_ecology_v1.py"
BOUNDARY = SRC / "franchise_season_boundary_durable_transition_v1.py"
EXPECTED_MODULE_SHA = "c04b76b59f2ff1f85d9ca9a6538df408e485afda022361fb5a3db6a7cabd7aab"
EXPECTED_BOUNDARY_SHA = "99dd17f937239fecf25a7d8e30bf494f3620a758c65c4dfd2a15fbaff4702bdf"
EXPECTED_RETIREMENT_SHA = "377018f5eb4069fdbdbd7b2a9ff6ddcc7e296572c2de7b514b476b277b58b36e"
EXPECTED_LEAGUE_SHA = "8d99fd44353373f63bcfc1bc69877a62e601eb35ab459c30f2eeafcfcc1e0efb"
EXPECTED_TWO_WAY_SHA = "964e35d02f90b60c985313cc8fd9399a55534fed10754d33274a56dc856aaa44"
EXPECTED_UNDRAFTED_SHA = "ab15bfe55ee09c73fe4ea82c9294d1d44fe866c9a2313ab857347d8ad80e6538"
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
        "exact_population_module": sha(MODULE) == EXPECTED_MODULE_SHA,
        "exact_boundary_integration": sha(BOUNDARY) == EXPECTED_BOUNDARY_SHA,
        "retirement_engine_unchanged": sha(SRC / "franchise_career_lifecycle_v1.py") == EXPECTED_RETIREMENT_SHA,
        "league_state_unchanged": sha(SRC / "simulation_league_state_v1.py") == EXPECTED_LEAGUE_SHA,
        "cpu_two_way_unchanged": sha(SRC / "franchise_cpu_two_way_roster_completion_v1.py") == EXPECTED_TWO_WAY_SHA,
        "undrafted_bridge_unchanged": sha(SRC / "franchise_undrafted_rookie_free_agent_v1.py") == EXPECTED_UNDRAFTED_SHA,
        "lifecycle_trace_unchanged": sha(SRC / "run_franchise_v2_roster_lifecycle_trace_v1.py") == EXPECTED_TRACE_SHA,
        "soft_market_band_present": (
            "ACTIVE_FA_SOFT_MAX = 300" in module
            and "ACTIVE_FA_TARGET = 270" in module
            and "MINIMUM_FA_RESERVE = 150" in module
        ),
        "only_free_agents_are_candidates": (
            "for player_id in sorted(free_agents):" in module
            and "if player_id in rostered:" in module
        ),
        "young_developmental_protection_present": (
            "age <= 21.0 and unsigned_seasons <= 2" in module
            and "potential >= 80.0 and unsigned_seasons <= 3" in module
            and "undrafted_rookie" in module
        ),
        "fresh_two_way_expiry_protected": (
            '"expired_two_way_contract"' in module
            and "unsigned_seasons <= 0" in module
        ),
        "multi_market_unsigned_requirement_present": (
            "unsigned_seasons >= 2" in module
            and "age >= 30.0 and unsigned_seasons >= 1" in module
        ),
        "lowest_market_score_exits_first": (
            "Lowest market score leaves first" in module
            and "sorted(" in module
        ),
        "bounded_reentry_archive_present": (
            "MAX_INACTIVE_PROFESSIONAL_POOL = 72" in module
            and "MAX_REENTRIES_PER_BOUNDARY = 4" in module
            and "returned_to_nba_market" in module
        ),
        "departure_cleans_active_player_maps": (
            'getattr(state, "players", {}).pop(player_id, None)' in module
            and 'getattr(state, "injuries", {}).pop(player_id, None)' in module
            and 'getattr(state, "player_season_totals", {}).pop(player_id, None)' in module
            and "injury_fatigue_profiles" in module
        ),
        "state_validation_preserved": "validate_simulation_league_state(candidate)" in module,
        "boundary_ecology_before_undrafted": (
            boundary.find("apply_free_agent_population_ecology_at_boundary(")
            < boundary.find("materialize_undrafted_rookie_free_agents_after_transition(")
        ),
        "boundary_undrafted_before_two_way": (
            boundary.find("materialize_undrafted_rookie_free_agents_after_transition(")
            < boundary.find("complete_cpu_two_way_rosters_at_boundary(")
        ),
        "boundary_two_way_before_trade_reconcile": (
            boundary.find("complete_cpu_two_way_rosters_at_boundary(")
            < boundary.find("reconcile_trade_state_after_season_boundary(")
        ),
        "boundary_uses_disposable_fast_path": "copy_payload=False" in boundary,
    }

    active_after = sha(ACTIVE) if ACTIVE.is_file() else ""
    checks["active_checkpoint_unchanged"] = active_before == active_after

    print("FRANCHISE V2 PLAYER POPULATION ECOLOGY V1 STATIC VALIDATION")
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
