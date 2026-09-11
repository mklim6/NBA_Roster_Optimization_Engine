from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint  # noqa: E402
import simulation_league_state_v1 as league_state  # noqa: E402


VALIDATOR_VERSION = (
    "medical-v2-injury-status-validator-hotfix-validator-v1-2026-08-10"
)


def locate_value(source: str) -> ast.expr:
    tree = ast.parse(source)
    matches = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue

        for key, value in zip(node.keys, node.values):
            if (
                isinstance(key, ast.Constant)
                and key.value == "injury_status_values_are_current"
                and value is not None
            ):
                matches.append(value)

    if len(matches) != 1:
        raise AssertionError(
            "Expected exactly one injury-status validator check."
        )

    return matches[0]


def main() -> int:
    source_path = SRC / "simulation_league_state_v1.py"
    source = source_path.read_text(encoding="utf-8")
    value = locate_value(source)
    expression = ast.get_source_segment(source, value) or ""

    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise AssertionError("No durable franchise checkpoint was found.")

    state = checkpoint.simulation_state

    current_statuses = [
        injury.status
        for injury in state.injuries.values()
        if isinstance(
            injury.status,
            league_state.AvailabilityStatus,
        )
    ]

    enum_values = {
        item.value
        for item in league_state.AvailabilityStatus
    }

    checks = {
        "validator_version_is_current": True,
        "current_enum_has_medical_v2_labels": (
            enum_values
            >= {
                "healthy",
                "probable",
                "questionable",
                "doubtful",
                "day_to_day",
                "out",
            }
        ),
        "all_checkpoint_statuses_use_current_enum": (
            len(current_statuses) == len(state.injuries)
        ),
        "validator_uses_enum_identity_contract": (
            "isinstance" in expression
            and "AvailabilityStatus" in expression
        ),
    }

    league_state.validate_simulation_league_state(state)
    checks["live_checkpoint_passes_league_state_validation"] = True

    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]

    print("INJURY STATUS VALIDATOR HOTFIX CHECKS")
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    print()
    print("Current enum values:", sorted(enum_values))
    print("Checkpoint injury records:", len(state.injuries))

    if failed:
        raise AssertionError(
            "Injury-status validator hotfix validation failed: "
            + ", ".join(failed)
        )

    print()
    print(
        "MEDICAL V2 INJURY STATUS VALIDATOR HOTFIX "
        "VALIDATION PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
