from __future__ import annotations

import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ACTIVE = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

EXPECTED_PRODUCTION = {'franchise_free_agency_cpu_execution_v1.py': '6a9162dc06acf2f512c95ec7161f4cad4b2a7aac2409b5f9b1d38068a8631878', 'franchise_cpu_post_draft_roster_trim_live_v1.py': '0b3f4852bade2e7d66778c0bb0b972bfc9a45d2d24c7c7dcbc061b63bfa96aa2', 'franchise_cpu_two_way_roster_completion_v1.py': '964e35d02f90b60c985313cc8fd9399a55534fed10754d33274a56dc856aaa44', 'franchise_season_boundary_durable_transition_v1.py': '99dd17f937239fecf25a7d8e30bf494f3620a758c65c4dfd2a15fbaff4702bdf', 'simulation_season_transition_v1.py': 'b30bc87b655629d4696c7239d30b0e1205eb43f9cab988cd55fc57b197c96d15', 'franchise_undrafted_rookie_free_agent_v1.py': 'ab15bfe55ee09c73fe4ea82c9294d1d44fe866c9a2313ab857347d8ad80e6538', 'run_franchise_v2_roster_lifecycle_trace_v1.py': 'cd28bafd38172ed9f13f089ae6a6945d014597546482555c1837985b589247f4'}
EXPECTED_VALIDATORS = {'validate_franchise_v2_cpu_fa_durable_batch_hotfix_v1_0_1.py': 'db3d402d9dd6f311f542fa1065e096f48046471c188332045f89ea10973248c8', 'validate_franchise_v2_post_draft_trim_checkpoint_reuse_v1.py': 'de0f37f52fd3048ddaf6b6539bb7b31f44b40aa47e2b34983440588b88c4f196', 'validate_franchise_v2_cpu_two_way_roster_completion_hotfix_v1_0_1.py': '22cbdc82e5b2e9951929666341c99dcd4401ca93abf39630a4cf880bd768ac3f', 'validate_franchise_v2_cpu_two_way_roster_completion_v1.py': '66bc8daccd1b1582a71d2adfa7eaf26a2321a2c8ae864f8c535352cd8aef35f4', 'validate_franchise_v2_two_way_expiry_reentry_hotfix_v1_0_1.py': 'd42c2d15f981367ad75f9ed53d5695baf30eadf55e3a5195a5da5f8757857044'}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    active_before = sha(ACTIVE) if ACTIVE.is_file() else ""

    checks: dict[str, bool] = {}

    for name, expected in EXPECTED_PRODUCTION.items():
        path = SRC / name
        checks[f"production_{name}"] = path.is_file() and sha(path) == expected
        if path.is_file():
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    for name, expected in EXPECTED_VALIDATORS.items():
        path = SRC / name
        checks[f"validator_{name}"] = path.is_file() and sha(path) == expected
        if path.is_file():
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    fa = (SRC / "franchise_free_agency_cpu_execution_v1.py").read_text(encoding="utf-8")
    trim = (SRC / "franchise_cpu_post_draft_roster_trim_live_v1.py").read_text(encoding="utf-8")
    two_way = (SRC / "franchise_cpu_two_way_roster_completion_v1.py").read_text(encoding="utf-8")
    boundary = (SRC / "franchise_season_boundary_durable_transition_v1.py").read_text(encoding="utf-8")
    season = (SRC / "simulation_season_transition_v1.py").read_text(encoding="utf-8")

    checks.update({
        "fa_batch_size_5_preserved":
            "CPU_FREE_AGENCY_DURABLE_BATCH_SIZE = 5" in fa,
        "fa_stale_write_guard_preserved":
            "_expected_existing_sha256=durable_hash" in fa,
        "fa_final_semantic_reload_preserved":
            "semantic = load_franchise_checkpoint(path=checkpoint_path, allow_backup=False)" in fa,
        "post_draft_checkpoint_reuse_preserved":
            "_existing_checkpoint=checkpoint" in trim
            and "_expected_existing_sha256=source_hash" in trim
            and "_return_verified=True" in trim,
        "controlled_team_exclusion_preserved":
            "team_code not in controlled_set" in two_way,
        "two_way_round_robin_preserved":
            "for desired_count in range(1, target + 1):" in two_way,
        "two_way_max_three_preserved":
            "target_slots_per_team: int = TWO_WAY_MAX" in two_way,
        "expiry_reentry_flag_clear_preserved":
            "player.two_way = False" in season,
        "population_ecology_before_undrafted_preserved":
            boundary.find("apply_free_agent_population_ecology_at_boundary(")
            < boundary.find("materialize_undrafted_rookie_free_agents_after_transition("),
        "undrafted_bridge_before_two_way_preserved":
            boundary.find("materialize_undrafted_rookie_free_agents_after_transition(")
            < boundary.find("complete_cpu_two_way_rosters_at_boundary("),
        "two_way_before_trade_reconciliation_preserved":
            boundary.find("complete_cpu_two_way_rosters_at_boundary(")
            < boundary.find("reconcile_trade_state_after_season_boundary("),
    })

    active_after = sha(ACTIVE) if ACTIVE.is_file() else ""
    checks["active_checkpoint_unchanged"] = active_before == active_after

    print("FRANCHISE V2 VALIDATOR CONSOLIDATION V1")
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
