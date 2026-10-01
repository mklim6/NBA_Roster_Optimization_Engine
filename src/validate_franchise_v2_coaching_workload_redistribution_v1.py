from __future__ import annotations

import ast
import hashlib
import py_compile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ACTIVE = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

ROLE = SRC / "franchise_coaching_role_rotation_v1.py"
SIM = SRC / "single_game_simulator_v1.py"
M1_VALIDATOR = SRC / "validate_franchise_v2_coaching_roles_injury_rotation_v1.py"

EXPECTED_ROLE_SHA = "871554483ccc0fad20ebd53af37eeba8c640a6ffbd5913da2f58bd894a16f6a8"
EXPECTED_SIM_SHA = "84a192ad6243240fa566a4df1e7e2f1ab6a7ae5898176ee8db754564accc60ec"
EXPECTED_M1_VALIDATOR_SHA = "ba7bc33be87abeae19c8ce5e5a124a167a0e7c7d23d11fd096bd4bf174928dfe"

EXPECTED_SCORE_FUNCTION_HASHES = {'regulation_score_expectations': 'f7f68e49d24ba9e3e62c09d52cc979e7247741d847d1a512eb825d7b0bc13754', 'simulate_scores': '88238c9964236d83cc4b8a53508e9fa06fcbcb53f47f0015d73574e859de37c8', 'scoring_components': 'd258c8b6777cf142ef73708c232572b8ab8fe769f3b07d06217ec6d9d6be1146'}


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

    role = ROLE.read_text(encoding="utf-8")
    sim = SIM.read_text(encoding="utf-8")

    checks = {
        "exact_role_module": sha(ROLE) == EXPECTED_ROLE_SHA,
        "exact_simulator": sha(SIM) == EXPECTED_SIM_SHA,
        "milestone1_validator_refreshed": (
            M1_VALIDATOR.is_file()
            and sha(M1_VALIDATOR) == EXPECTED_M1_VALIDATOR_SHA
        ),
        "workload_version_present": (
            "COACHING_WORKLOAD_REDISTRIBUTION_VERSION" in role
            and "COACHING_INTELLIGENCE_WORKLOAD_VERSION" in sim
        ),
        "healthy_minute_multiplier_identity_present": (
            "if not missing:" in role
            and "return {player_id: 1.0 for player_id in rotation}" in role
        ),
        "minute_multiplier_is_bounded": (
            "MINUTE_MULTIPLIER_FLOOR = 0.90" in role
            and "MINUTE_MULTIPLIER_CEILING = 1.16" in role
        ),
        "minute_reweight_occurs_before_medical_caps": (
            sim.find("coaching_minute_weight_multipliers_v1(")
            < sim.find("upper_bounds = {")
            < sim.find("player_minutes_cap(")
        ),
        "medical_cap_path_preserved": "player_minutes_cap(" in sim,
        "exact_team_minute_reconciliation_preserved": (
            "allocate_bounded_integer_units(" in sim
            and "required_tenths = int(" in sim
            and "round(total_minutes * 10)" in sim
        ),
        "scoring_responsibility_bounded": (
            '"scoring": (0.92, 1.12)' in role
            and 'channel="scoring"' in sim
        ),
        "creation_responsibility_bounded": (
            '"creation": (0.90, 1.15)' in role
            and '"assists": "creation"' in sim
        ),
        "rebounding_responsibility_bounded": (
            '"rebounding": (0.93, 1.10)' in role
            and '"rebounds": "rebounding"' in sim
        ),
        "defensive_event_responsibility_bounded": (
            '"rim_defense": (0.93, 1.10)' in role
            and '"perimeter_defense": (0.93, 1.10)' in role
            and '"blocks": "rim_defense"' in sim
            and '"steals": "perimeter_defense"' in sim
        ),
        "team_points_still_exactly_allocated": (
            "point_allocation = allocate_integer_units(" in sim
            and "team_score," in sim[
                sim.find("point_allocation = allocate_integer_units("):
                sim.find("point_allocation = allocate_integer_units(") + 250
            ]
        ),
        "turnover_adjustment_is_damped": (
            'if stat_name == "turnovers":' in sim
            and "* 0.55" in sim
        ),
        "workload_explanation_report_present": (
            "WorkloadRedistributionReport" in role
            and "while preserving medical caps and the fixed team-minute total" in role
        ),
        "generated_players_still_supported": (
            "functional_role_profile_v1" in role
            and "_baseline(" in role
            and "_skill(" in role
        ),
        "score_expectation_function_unchanged": (
            function_sha(sim, "regulation_score_expectations")
            == EXPECTED_SCORE_FUNCTION_HASHES["regulation_score_expectations"]
        ),
        "score_simulation_function_unchanged": (
            function_sha(sim, "simulate_scores")
            == EXPECTED_SCORE_FUNCTION_HASHES["simulate_scores"]
        ),
        "shooting_component_function_unchanged": (
            function_sha(sim, "scoring_components")
            == EXPECTED_SCORE_FUNCTION_HASHES["scoring_components"]
        ),
    }

    ast.parse(role)
    ast.parse(sim)
    py_compile.compile(str(ROLE), doraise=True)
    py_compile.compile(str(SIM), doraise=True)
    py_compile.compile(str(M1_VALIDATOR), doraise=True)

    active_after = sha(ACTIVE) if ACTIVE.is_file() else ""
    checks["active_checkpoint_unchanged"] = active_before == active_after

    print("FRANCHISE V2 COACHING WORKLOAD REDISTRIBUTION V1 STATIC VALIDATION")
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
