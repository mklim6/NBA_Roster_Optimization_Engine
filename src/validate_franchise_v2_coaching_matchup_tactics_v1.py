from __future__ import annotations

import ast
import hashlib
import py_compile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ACTIVE = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

TACTICS = SRC / "franchise_coaching_matchup_tactics_v1.py"
SIM = SRC / "single_game_simulator_v1.py"
ROLE = SRC / "franchise_coaching_role_rotation_v1.py"
STAFF = SRC / "franchise_staff_system_v1.py"
M1 = SRC / "validate_franchise_v2_coaching_roles_injury_rotation_v1.py"
M2 = SRC / "validate_franchise_v2_coaching_workload_redistribution_v1.py"

EXPECTED_TACTICS_SHA = "3aff0b031fadabb4a8aca6fb5cf862788e8d453aeecf5db8d13d4e32d4b84a26"
EXPECTED_SIM_SHA = "84a192ad6243240fa566a4df1e7e2f1ab6a7ae5898176ee8db754564accc60ec"
EXPECTED_ROLE_SHA = "871554483ccc0fad20ebd53af37eeba8c640a6ffbd5913da2f58bd894a16f6a8"
EXPECTED_STAFF_SHA = "c76edaf317cc3371868e9fdc833b57c3b917da7aefbd88f4ae8f42847fd554ab"
EXPECTED_M1_SHA = "ba7bc33be87abeae19c8ce5e5a124a167a0e7c7d23d11fd096bd4bf174928dfe"
EXPECTED_M2_SHA = "74a7185a98414b8405070fa9751223f0b8e474ded01ff88b18cebf9c35d13c3c"
PROTECTED_FUNCTIONS = {'regulation_score_expectations': 'f7f68e49d24ba9e3e62c09d52cc979e7247741d847d1a512eb825d7b0bc13754', 'simulate_scores': '88238c9964236d83cc4b8a53508e9fa06fcbcb53f47f0015d73574e859de37c8', 'scoring_components': 'd258c8b6777cf142ef73708c232572b8ab8fe769f3b07d06217ec6d9d6be1146'}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def function_sha(text: str, name: str) -> str:
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return hashlib.sha256(
                "".join(lines[node.lineno - 1:node.end_lineno]).encode("utf-8")
            ).hexdigest()
    return ""


def main() -> int:
    active_before = sha(ACTIVE) if ACTIVE.is_file() else ""

    tactics = TACTICS.read_text(encoding="utf-8")
    sim = SIM.read_text(encoding="utf-8")

    checks = {
        "exact_tactics_module": sha(TACTICS) == EXPECTED_TACTICS_SHA,
        "exact_simulator_integration": sha(SIM) == EXPECTED_SIM_SHA,
        "role_engine_unchanged": sha(ROLE) == EXPECTED_ROLE_SHA,
        "staff_system_unchanged": sha(STAFF) == EXPECTED_STAFF_SHA,
        "milestone1_validator_refreshed": sha(M1) == EXPECTED_M1_SHA,
        "milestone2_validator_refreshed": sha(M2) == EXPECTED_M2_SHA,
        "threat_profile_creation_present": (
            "creation:" in tactics
            and "multi_handler_creation:" in tactics
        ),
        "threat_profile_spacing_present": "spacing:" in tactics,
        "threat_profile_rim_present": "rim_pressure:" in tactics,
        "threat_profile_size_present": (
            "glass_size:" in tactics and "interior_hub:" in tactics
        ),
        "creator_counter_present": 'SCHEME_LOAD_CREATOR = "load_primary_creator"' in tactics,
        "paint_counter_present": 'SCHEME_PACK_PAINT = "pack_paint"' in tactics,
        "shooter_counter_present": 'SCHEME_STAY_HOME = "stay_home_on_shooters"' in tactics,
        "switch_counter_present": 'SCHEME_SWITCH = "switch_perimeter_actions"' in tactics,
        "size_counter_present": 'SCHEME_MATCH_SIZE = "match_size_and_glass"' in tactics,
        "balanced_fallback_present": (
            'SCHEME_BALANCED = "balanced"' in tactics
            and "stays balanced against" in tactics
        ),
        "personnel_capacity_matters": "_personnel_capacities" in tactics,
        "coach_defense_and_adaptability_matter": (
            "defense_index" in tactics
            and "adaptability_rating" in tactics
            and "_coach_execution" in tactics
        ),
        "tactical_suppression_is_tightly_bounded": (
            "MAX_DEFENSIVE_SUPPRESSION_POINTS = 0.65" in tactics
            and "0.0," in tactics
        ),
        "bad_matchup_does_not_force_specialized_scheme": (
            "if execution < 0.12 or utility <= 0.0:" in tactics
        ),
        "tradeoffs_are_encoded": (
            "spacing * 0.72" in tactics
            and "rim * 0.58" in tactics
            and "glass * 0.48" in tactics
        ),
        "rating_offset_solves_exact_score_equations": (
            "_rating_offsets_for_defensive_suppression" in tactics
            and "determinant = offense * offense - opponent * opponent" in tactics
        ),
        "regulation_integration_present": (
            "COACHING_INTELLIGENCE_MATCHUP_TACTICS_V1" in sim
            and "apply_matchup_tactical_counters_v1(" in sim
        ),
        "overtime_integration_present": "_overtime_coaching_matchup_tactical_report" in sim,
        "score_expectation_function_unchanged": (
            function_sha(sim, "regulation_score_expectations")
            == PROTECTED_FUNCTIONS["regulation_score_expectations"]
        ),
        "score_noise_function_unchanged": (
            function_sha(sim, "simulate_scores")
            == PROTECTED_FUNCTIONS["simulate_scores"]
        ),
        "shooting_component_function_unchanged": (
            function_sha(sim, "scoring_components")
            == PROTECTED_FUNCTIONS["scoring_components"]
        ),
    }

    for path in (TACTICS, SIM, ROLE, STAFF, M1, M2):
        py_compile.compile(str(path), doraise=True)

    active_after = sha(ACTIVE) if ACTIVE.is_file() else ""
    checks["active_checkpoint_unchanged"] = active_before == active_after

    print("FRANCHISE V2 COACHING MATCHUP TACTICS V1 STATIC VALIDATION")
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
