from __future__ import annotations

from enum import Enum
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint
import simulation_league_state_v1 as league_state


class PriorGenerationStatus(str, Enum):
    HEALTHY = "healthy"
    PROBABLE = "probable"
    QUESTIONABLE = "questionable"
    DOUBTFUL = "doubtful"
    DAY_TO_DAY = "day_to_day"
    OUT = "out"


def main() -> int:
    checkpoint = load_franchise_checkpoint()
    checks = {
        "current_enum_has_expected_labels": {
            item.value for item in league_state.AvailabilityStatus
        } >= {
            "healthy", "probable", "questionable",
            "doubtful", "day_to_day", "out",
        },
        "validator_uses_value_contract": hasattr(
            league_state, "availability_status_value_is_current"
        ),
        "hot_reload_fixture_is_accepted": all(
            league_state.availability_status_value_is_current(item)
            for item in PriorGenerationStatus
        ),
        "unknown_label_is_rejected": not league_state.availability_status_value_is_current(
            "unknown_medical_status"
        ),
    }

    if checkpoint is not None:
        state = checkpoint.simulation_state
        checks["checkpoint_status_values_are_valid"] = all(
            league_state.availability_status_value_is_current(injury.status)
            for injury in state.injuries.values()
        )
        league_state.validate_simulation_league_state(state)
    else:
        checks["checkpoint_status_values_are_valid"] = True

    failed = [name for name, ok in checks.items() if not ok]
    print("INJURY STATUS VALIDATOR HOTFIX CHECKS")
    for name, ok in checks.items():
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")
    if failed:
        raise AssertionError(
            "Injury-status validator hotfix failed: " + ", ".join(failed)
        )
    print("MEDICAL V2 INJURY STATUS VALIDATOR HOTFIX VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
