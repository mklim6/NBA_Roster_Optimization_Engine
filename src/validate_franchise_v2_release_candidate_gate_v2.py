from __future__ import annotations

import hashlib
import py_compile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
ACTIVE = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

RUNNER = SRC / "run_franchise_v2_release_candidate_gate_v2.py"
USER_TW = SRC / "validate_franchise_v2_user_two_way_management_v1.py"
WHATIF = SRC / "validate_franchise_v2_what_if_lab_removal_v1.py"

EXPECTED_PAGE_SHA = "d2c1e07b11797d988c341659a979863c510880e716e7cf3feab19b3aebf74514"
EXPECTED_RUNNER_SHA = "1054b1bfd69d735eeb3d432f48e9be504366265f025e3352318d67518e1c3359"
EXPECTED_USER_TW_SHA = "c93a1e5e61fbdab5411b101f43d35bc1bee514fcc8b30d8c3e4765da6662d6ab"
EXPECTED_WHATIF_SHA = "306c7a4322cab69e0522f00c305e632d74b215f8b2b2f9807c9cc4b70e14ce43"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    active_before = sha(ACTIVE) if ACTIVE.is_file() else ""

    runner = RUNNER.read_text(encoding="utf-8")
    page = PAGE.read_text(encoding="utf-8")

    checks = {
        "accepted_m4_page_exact": sha(PAGE) == EXPECTED_PAGE_SHA,
        "release_gate_runner_exact": sha(RUNNER) == EXPECTED_RUNNER_SHA,
        "user_two_way_validator_synced": sha(USER_TW) == EXPECTED_USER_TW_SHA,
        "what_if_validator_synced": sha(WHATIF) == EXPECTED_WHATIF_SHA,
        "user_two_way_ui_still_present": (
            "FRANCHISE_V2_USER_TWO_WAY_MANAGEMENT_V1" in page
            and "render_user_two_way_management_v1(" in page
        ),
        "coaching_game_day_ui_still_present": (
            "FRANCHISE_COACHING_GAME_DAY_UI_V1" in page
            and "render_game_day_coaching_plan_v1(" in page
        ),
        "what_if_ui_still_absent": (
            "Advanced What-If Lab" not in page
            and "Run what-if simulation" not in page
            and "commit=False" not in page
        ),
        "gate_has_fast_mode": '"--fast"' in runner,
        "gate_has_full_mode": '"--full"' in runner,
        "gate_has_deep_mode": '"--deep"' in runner,
        "gate_compiles_src_and_pages": '"compileall"' in runner,
        "gate_runs_population_ecology": (
            "validate_franchise_v2_player_population_ecology_v1.py" in runner
            and "run_franchise_v2_player_population_ecology_validation_v1.py" in runner
        ),
        "gate_runs_user_two_way": (
            "validate_franchise_v2_user_two_way_management_v1.py" in runner
            and "run_franchise_v2_user_two_way_management_validation_v1.py" in runner
        ),
        "gate_runs_all_coaching_milestones": (
            "validate_franchise_v2_coaching_roles_injury_rotation_v1.py" in runner
            and "validate_franchise_v2_coaching_workload_redistribution_v1.py" in runner
            and "validate_franchise_v2_coaching_matchup_tactics_v1.py" in runner
            and "validate_franchise_v2_coaching_identity_game_day_v1.py" in runner
            and "validate_franchise_v2_coaching_counterfactual_audit_v1.py" in runner
        ),
        "gate_full_runs_long_realism_checks": (
            "validate_injury_fatigue_v1.py" in runner
            and "validate_franchise_simulation_realism_v1.py" in runner
        ),
        "gate_deep_runs_eight_season_trace": (
            "run_franchise_v2_roster_lifecycle_trace_v1.py" in runner
            and '"--seasons", "8"' in runner
            and "audit_franchise_v2_player_population_ecology_trace_v1.py" in runner
        ),
        "checkpoint_family_guard_present": (
            "_checkpoint_family" in runner
            and "active_checkpoint_family_unchanged" in runner
        ),
        "gate_writes_machine_readable_report": (
            "latest_report.json" in runner
            and "latest_summary.txt" in runner
        ),
    }

    for path in (RUNNER, USER_TW, WHATIF, PAGE):
        py_compile.compile(str(path), doraise=True)

    active_after = sha(ACTIVE) if ACTIVE.is_file() else ""
    checks["static_validation_does_not_touch_checkpoint"] = active_before == active_after

    print("FRANCHISE V2 RELEASE CANDIDATE GATE V2 STATIC VALIDATION")
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
