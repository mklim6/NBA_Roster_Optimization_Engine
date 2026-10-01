from __future__ import annotations

import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
MODULE = SRC / "franchise_cpu_two_way_roster_completion_v1.py"
BOUNDARY = SRC / "franchise_season_boundary_durable_transition_v1.py"
ACTIVE = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

EXPECTED_MODULE_SHA = "964e35d02f90b60c985313cc8fd9399a55534fed10754d33274a56dc856aaa44"
EXPECTED_BOUNDARY_SHA = "99dd17f937239fecf25a7d8e30bf494f3620a758c65c4dfd2a15fbaff4702bdf"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    active_before = sha(ACTIVE) if ACTIVE.is_file() else ""
    source = MODULE.read_text(encoding="utf-8")
    ast.parse(source, filename=str(MODULE))

    allocation = source.split("cpu_teams = tuple(", 1)[1].split(
        "history = list(getattr(candidate, TWO_WAY_HISTORY_ATTR", 1
    )[0]

    checks = {
        "exact_hotfix_module": sha(MODULE) == EXPECTED_MODULE_SHA,
        "boundary_source_unchanged": sha(BOUNDARY) == EXPECTED_BOUNDARY_SHA,
        "round_robin_slot_tiers": "for desired_count in range(1, target + 1):" in allocation,
        "cpu_team_order_still_deterministic": "sorted(_team(value) for value in teams)" in allocation,
        "controlled_team_skip_preserved": "team_code not in controlled_set" in allocation,
        "existing_two_way_counts_respected": "_two_way_count(candidate, team_code) >= desired_count" in allocation,
        "same_development_score_preserved": "_development_score(candidate, team_code, players[player_id])" in allocation,
        "same_conversion_path_preserved": "_convert_to_two_way(" in allocation,
        "finite_pool_respected": "if not available:" in allocation,
        "three_slot_project_limit_preserved": "target_slots_per_team: int = TWO_WAY_MAX" in source,
        "eligibility_guardrails_unchanged": "overall > 80.0" in source and "age > 27.0" in source,
        "two_way_salary_unchanged": "contract.salary = 0.0" in source,
        "one_year_clock_unchanged": "contract.years_remaining = 1" in source,
    }

    active_after = sha(ACTIVE) if ACTIVE.is_file() else ""
    checks["active_checkpoint_unchanged"] = active_before == active_after

    print("FRANCHISE V2 CPU TWO-WAY ROSTER COMPLETION HOTFIX V1.0.1 STATIC VALIDATION")
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
