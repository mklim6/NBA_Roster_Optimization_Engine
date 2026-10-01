from __future__ import annotations

import hashlib
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
ACTIVE = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

EXPECTED_MODULE_SHA = "00a654546dfa085bcc7ba956bfe5b477cbf16ea731c60c2346140d082466fa78"
EXPECTED_PAGE_SHA = "d2c1e07b11797d988c341659a979863c510880e716e7cf3feab19b3aebf74514"
EXPECTED_CORE = {'franchise_cpu_two_way_roster_completion_v1.py': '964e35d02f90b60c985313cc8fd9399a55534fed10754d33274a56dc856aaa44', 'franchise_financial_cba_bridge_v1.py': 'ca77b3fb3f7719755122b41ab2d9863d37f290864567b3dc53a42b22485f6fb6', 'simulation_league_state_v1.py': '8d99fd44353373f63bcfc1bc69877a62e601eb35ab459c30f2eeafcfcc1e0efb', 'simulation_franchise_checkpoint_v1.py': '08020e5c6315844ca99d70654c528dc6150411b2b26d5f5c42a420c87060fca9', 'mutable_league_state_v1.py': '919e278900dec762a344004be247bd164b4a31d820c65cdd037b22d88d050020'}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    active_before = sha(ACTIVE) if ACTIVE.is_file() else ""

    module_path = SRC / "franchise_user_two_way_management_v1.py"
    module = module_path.read_text(encoding="utf-8")
    page = PAGE.read_text(encoding="utf-8")

    checks = {
        "exact_user_two_way_module": sha(module_path) == EXPECTED_MODULE_SHA,
        "exact_franchise_page": sha(PAGE) == EXPECTED_PAGE_SHA,
        "page_renders_two_way_management": (
            "FRANCHISE_V2_USER_TWO_WAY_MANAGEMENT_V1" in page
            and "render_user_two_way_management_v1(" in page
            and "trade_state=trade_state" in page
            and "controlled_teams=controlled_teams" in page
        ),
        "project_two_way_max_reused": "TWO_WAY_MAX" in module,
        "regular_standard_max_reused": "REGULAR_SEASON_STANDARD_MAX" in module,
        "offseason_total_max_reused": "OFFSEASON_TOTAL_MAX" in module,
        "controlled_team_gate_present": "is not a user-controlled franchise" in module,
        "playoff_transaction_lock_present": (
            'ALLOWED_TWO_WAY_PHASES = frozenset(' in module
            and '{"preseason", "regular_season", "offseason"}' in module
            and "Two-way roster moves are locked" in module
        ),
        "cpu_eligibility_overall_floor_mirrored": "overall < 55.0" in module,
        "cpu_eligibility_overall_ceiling_mirrored": "overall > 80.0" in module,
        "cpu_eligibility_age_ceiling_mirrored": "age > 27.0" in module,
        "cpu_eligibility_unknown_age_guard_mirrored": (
            "age is None and overall > 74.0" in module
        ),
        "cpu_eligibility_potential_floor_mirrored": "potential < 62.0" in module,
        "standard_count_separate_from_two_way": (
            "standard_contract_count_v1" in module
            and "not _player_is_two_way" in module
        ),
        "sign_sets_two_way_flag": 'player.two_way = True' in module,
        "sign_sets_two_way_status": 'player.roster_status = "two_way"' in module,
        "sign_sets_one_year_zero_salary_contract": (
            'contract.status = "two_way"' in module
            and "contract.salary = 0.0" in module
            and "contract.years_remaining = 1" in module
            and "contract.guaranteed = False" in module
        ),
        "sign_removes_free_agent_membership": (
            "candidate.free_agent_player_ids = tuple(" in module
        ),
        "release_clears_two_way_flag": "player.two_way = False" in module,
        "release_returns_player_to_free_agent": (
            'player.roster_status = "free_agent"' in module
            and 'contract.status = "free_agent_pool"' in module
            and "contract.years_remaining = 0" in module
        ),
        "release_removes_rotation_membership": "_remove_from_rotation(team_state, pid)" in module,
        "trade_ownership_sync_present": "ownership[player_id] = team_code if signing else \"\"" in module,
        "trade_two_way_count_sync_present": (
            "financial.two_way_contract_count = int(two_way_count_after)" in module
        ),
        "two_way_does_not_change_salary": (
            "Two-way transaction changed team salary." in module
            and "Two-way transaction changed apron salary." in module
        ),
        "trade_snapshots_rebased": (
            "for snapshot in list(getattr(candidate, \"undo_stack\"" in module
            and "_sync_trade_snapshot(" in module
            and "initial_snapshot" in module
        ),
        "release_snapshot_keeps_financial_team_separate_from_blank_owner": (
            "owner_code=team_code if signing else \"\"" in module
            and "financial_team_code=team_code" in module
            and "ownership[player_id] = owner_code" in module
            and "financials[financial_team_code].two_way_contract_count" in module
        ),
        "trade_revision_increments": "candidate.state_revision = revision_before + 1" in module,
        "simulation_trade_revision_realigns": "_align_simulation_source" in module,
        "stale_checkpoint_sha_guard_present": (
            "_expected_existing_sha256=source_sha256" in module
            and "_existing_checkpoint=source_checkpoint" in module
        ),
        "stale_team_view_fingerprint_present": (
            "authority_fingerprint_v1" in module
            and "durable franchise changed after this Team Management view loaded" in module
        ),
        "user_transaction_history_present": "franchise_user_two_way_transaction_history_v1" in module,
        "team_management_slot_metrics_present": (
            '"Standard roster"' in module
            and '"Two-way roster"' in module
            and '"Open two-way slots"' in module
        ),
        "sign_and_release_actions_present": (
            '"Sign to two-way contract"' in module
            and '"Release two-way player"' in module
        ),
        "eligibility_explanation_present": (
            "Exact NBA " in module
            and "years-of-service eligibility is a future realism upgrade." in module
        ),
    }

    for name, expected in EXPECTED_CORE.items():
        path = SRC / name
        checks[f"core_{name}_unchanged"] = path.is_file() and sha(path) == expected

    py_compile.compile(str(module_path), doraise=True)
    py_compile.compile(str(PAGE), doraise=True)

    active_after = sha(ACTIVE) if ACTIVE.is_file() else ""
    checks["active_checkpoint_unchanged"] = active_before == active_after

    print("FRANCHISE V2 USER TWO-WAY MANAGEMENT V1 STATIC VALIDATION")
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
