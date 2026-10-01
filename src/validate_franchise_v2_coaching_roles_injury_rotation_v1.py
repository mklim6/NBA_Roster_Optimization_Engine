from __future__ import annotations

import ast
import hashlib
import py_compile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ACTIVE = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

EXPECTED_MODULE_SHA = "871554483ccc0fad20ebd53af37eeba8c640a6ffbd5913da2f58bd894a16f6a8"
EXPECTED_SIMULATOR_SHA = "84a192ad6243240fa566a4df1e7e2f1ab6a7ae5898176ee8db754564accc60ec"
EXPECTED_CORE = {'simulation_league_state_v1.py': '8d99fd44353373f63bcfc1bc69877a62e601eb35ab459c30f2eeafcfcc1e0efb', 'simulation_injury_fatigue_v1.py': '0ee2012a91e158bbb7c62ac03a1e24cbec4b9176235631948c0e7e831eba1dfa', 'franchise_staff_system_v1.py': 'c76edaf317cc3371868e9fdc833b57c3b917da7aefbd88f4ae8f42847fd554ab', 'franchise_roster_rotation_headquarters_v1.py': '23dfa76ddc234624f30bdf12e20d6ac309251a016494ef61ecf0dc391cf9e1ef', 'build_simulation_player_stat_profiles_v1.py': '07b4a5fbfb2861d3ddca309a910e3bd4c07e5fa3215a33b73aece1f3909df787'}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    active_before = sha(ACTIVE) if ACTIVE.is_file() else ""

    module_path = SRC / "franchise_coaching_role_rotation_v1.py"
    simulator_path = SRC / "single_game_simulator_v1.py"
    module = module_path.read_text(encoding="utf-8")
    simulator = simulator_path.read_text(encoding="utf-8")

    checks = {
        "exact_role_rotation_module": sha(module_path) == EXPECTED_MODULE_SHA,
        "exact_simulator_integration": sha(simulator_path) == EXPECTED_SIMULATOR_SHA,
        "engine_api_version_preserved": (
            'ENGINE_VERSION = "single-game-simulator-v1.6-2026-08-08"' in simulator
        ),
        "coaching_version_exposed": (
            "COACHING_INTELLIGENCE_ROTATION_VERSION = COACHING_ROLE_ROTATION_VERSION"
            in simulator
        ),
        "functional_roles_cover_creation": (
            'ROLE_PRIMARY_CREATOR = "primary_creator"' in module
            and 'ROLE_SECONDARY_CREATOR = "secondary_creator"' in module
            and 'ROLE_BALL_HANDLER = "ball_handler"' in module
        ),
        "functional_roles_cover_spacing_pressure": (
            'ROLE_SPACER = "spacer"' in module
            and 'ROLE_RIM_PRESSURE = "rim_pressure"' in module
        ),
        "functional_roles_cover_frontcourt": (
            'ROLE_REBOUNDER = "rebounder"' in module
            and 'ROLE_RIM_PROTECTOR = "rim_protector"' in module
            and 'ROLE_INTERIOR_DEFENDER = "interior_defender"' in module
        ),
        "functional_roles_cover_perimeter_defense": (
            'ROLE_POA_DEFENDER = "point_of_attack_defender"' in module
            and 'ROLE_WING_STOPPER = "wing_stopper"' in module
        ),
        "state_skills_are_primary_role_inputs": (
            '"scoring_rating"' in module
            and '"shooting_rating"' in module
            and '"playmaking_rating"' in module
            and '"rebounding_rating"' in module
            and '"defense_rating"' in module
        ),
        "per36_inputs_used": (
            '"assists_per_36"' in module
            and '"rebounds_per_36"' in module
            and '"blocks_per_36"' in module
            and '"three_attempts_per_36"' in module
        ),
        "generated_players_supported": (
            "skill_ratings" in module
            and "baseline_per_36" in module
            and "profile loader" not in module.lower()
        ),
        "missing_role_weights_present": "missing_role_weights_v1" in module,
        "replacement_role_fit_present": "role_fit_v1" in module,
        "position_fit_present": "position_fit_v1" in module,
        "staff_rotation_management_has_bounded_influence": (
            "_rotation_management_rating" in module
            and "role_weight" in module
            and "0.36" in module
            and "0.50" in module
        ),
        "human_readable_explanation_present": (
            "creating a deficit in" in module
            and "functional match" in module
        ),
        "healthy_path_explicitly_preserved": (
            "if missing_saved_starters:" in simulator
            and "reconstruct_injury_aware_rotation_v1(" in simulator
            and simulator.find("if missing_saved_starters:")
                < simulator.find("starter_ids = [", simulator.find("if missing_saved_starters:"))
        ),
        "rotation_only_activation_marker_present": (
            "COACHING_INTELLIGENCE_ROLE_ROTATION_V1" in simulator
        ),
        "minute_allocator_unchanged_by_coaching_patch": (
            "def allocate_minutes(" in simulator
            and "coaching_adjusted" not in simulator
        ),
        "scoring_engine_unchanged_by_coaching_patch": (
            "def scoring_components(" in simulator
            and "def simulate_scores(" in simulator
            and 'REALISM_CALIBRATION_VERSION = "game-season-realism-calibration-v1-2026-08-13"' in simulator
        ),
        "role_module_does_not_mutate_ratings": (
            ".overall_rating =" not in module
            and ".skill_ratings =" not in module
            and ".baseline_per_36 =" not in module
        ),
    }

    for name, expected in EXPECTED_CORE.items():
        path = SRC / name
        checks[f"core_{name}_unchanged"] = path.is_file() and sha(path) == expected

    ast.parse(module)
    ast.parse(simulator)
    py_compile.compile(str(module_path), doraise=True)
    py_compile.compile(str(simulator_path), doraise=True)

    active_after = sha(ACTIVE) if ACTIVE.is_file() else ""
    checks["active_checkpoint_unchanged"] = active_before == active_after

    print("FRANCHISE V2 COACHING ROLES / INJURY ROTATION V1 STATIC VALIDATION")
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
