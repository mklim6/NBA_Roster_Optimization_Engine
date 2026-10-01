from __future__ import annotations

import hashlib
import py_compile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
ACTIVE = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

EXPECTED = {'franchise_coaching_matchup_tactics_v1.py': '3aff0b031fadabb4a8aca6fb5cf862788e8d453aeecf5db8d13d4e32d4b84a26', 'franchise_coaching_game_day_ui_v1.py': '5abb572ea910bef312089100a855134df058dccf13bd16b7fd050b6e494c37a3', '5_Franchise_Mode.py': 'd2c1e07b11797d988c341659a979863c510880e716e7cf3feab19b3aebf74514', 'single_game_simulator_v1.py': '84a192ad6243240fa566a4df1e7e2f1ab6a7ae5898176ee8db754564accc60ec', 'franchise_coaching_role_rotation_v1.py': '871554483ccc0fad20ebd53af37eeba8c640a6ffbd5913da2f58bd894a16f6a8', 'franchise_staff_system_v1.py': 'c76edaf317cc3371868e9fdc833b57c3b917da7aefbd88f4ae8f42847fd554ab', 'validate_franchise_v2_coaching_identity_game_day_v1.py': '327bab70adcdfee3bf034cec83c72a3f1a4e03b3dd71a1a471fa5901b6fa9970'}
RUNNER_SHA = "bd4eea0932b8fe0ea85030fcbd2bf111121acb57a85ba992125737b1b66e744f"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    active_before = sha(ACTIVE) if ACTIVE.is_file() else ""

    paths = {
        "franchise_coaching_matchup_tactics_v1.py": SRC / "franchise_coaching_matchup_tactics_v1.py",
        "franchise_coaching_game_day_ui_v1.py": SRC / "franchise_coaching_game_day_ui_v1.py",
        "5_Franchise_Mode.py": PAGE,
        "single_game_simulator_v1.py": SRC / "single_game_simulator_v1.py",
        "franchise_coaching_role_rotation_v1.py": SRC / "franchise_coaching_role_rotation_v1.py",
        "franchise_staff_system_v1.py": SRC / "franchise_staff_system_v1.py",
        "validate_franchise_v2_coaching_identity_game_day_v1.py":
            SRC / "validate_franchise_v2_coaching_identity_game_day_v1.py",
    }
    runner = SRC / "run_franchise_v2_coaching_counterfactual_audit_v1.py"
    text = runner.read_text(encoding="utf-8")

    checks = {
        "all_m4_production_sources_are_exact": all(
            path.is_file() and sha(path) == EXPECTED[name]
            for name, path in paths.items()
        ),
        "exact_counterfactual_runner": sha(runner) == RUNNER_SHA,
        "four_distinct_staff_archetypes_present": (
            '"switch_aggressive"' in text
            and '"paint_size_control"' in text
            and '"shooter_discipline"' in text
            and '"creator_detail"' in text
        ),
        "same_personnel_and_ratings_are_held_constant": (
            "staff_ratings_are_held_constant" in text
            and "source_plans" in text
        ),
        "close_call_gate_present": (
            "CLOSE_CALL_EXECUTION_GAP = 0.040" in text
            and "close_calls_show_staff_identity_differentiation" in text
        ),
        "strong_call_stability_gate_present": (
            "STRONG_CALL_EXECUTION_GAP = 0.120" in text
            and "MIN_STRONG_CALL_STABILITY = 0.95" in text
        ),
        "negative_raw_utility_guard_present": (
            "no_negative_raw_utility_scheme_is_selected" in text
        ),
        "suppression_cap_guard_present": (
            "all_tactical_suppression_remains_bounded" in text
            and "MAX_DEFENSIVE_SUPPRESSION_POINTS" in text
        ),
        "active_checkpoint_hash_guard_present": (
            "active_checkpoint_unchanged" in text
        ),
        "audit_writes_only_a_report_output": (
            'outputs"\n        / "v2_coaching_counterfactual_audit_v1"' in text
            and "save_franchise_checkpoint" not in text
            and "commit_game_transactionally" not in text
        ),
    }

    for path in list(paths.values()) + [runner]:
        py_compile.compile(str(path), doraise=True)

    active_after = sha(ACTIVE) if ACTIVE.is_file() else ""
    checks["static_validator_does_not_touch_checkpoint"] = active_before == active_after

    print("FRANCHISE V2 COACHING COUNTERFACTUAL AUDIT V1 STATIC VALIDATION")
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
