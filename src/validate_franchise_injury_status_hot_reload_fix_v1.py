from __future__ import annotations

import ast
from enum import Enum
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import simulation_league_state_v1 as league_state
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint


class PreviousModuleAvailabilityStatus(str, Enum):
    HEALTHY = "healthy"
    PROBABLE = "probable"
    QUESTIONABLE = "questionable"
    DOUBTFUL = "doubtful"
    DAY_TO_DAY = "day_to_day"
    OUT = "out"


def main() -> int:
    source_path = SRC / "simulation_league_state_v1.py"
    source = source_path.read_text(encoding="utf-8")
    checks = {}

    try:
        ast.parse(source)
        checks["league_state_compiles"] = True
    except Exception:
        checks["league_state_compiles"] = False

    checks["fix_version_present"] = (
        "franchise-injury-status-hot-reload-fix-v1-2026-09-12" in source
    )
    checks["validator_uses_value_contract"] = (
        "availability_status_value_is_current(" in source
    )
    checks["strict_identity_contract_removed"] = (
        "isinstance(\n                injury.status,\n                AvailabilityStatus,"
        not in source
    )
    checks["current_enum_values_pass"] = all(
        league_state.availability_status_value_is_current(item)
        for item in league_state.AvailabilityStatus
    )
    checks["valid_strings_pass"] = all(
        league_state.availability_status_value_is_current(item.value)
        for item in league_state.AvailabilityStatus
    )
    checks["prior_module_generation_enum_passes"] = all(
        league_state.availability_status_value_is_current(item)
        for item in PreviousModuleAvailabilityStatus
    )
    checks["prior_generation_is_distinct_class"] = (
        type(PreviousModuleAvailabilityStatus.HEALTHY)
        is not type(league_state.AvailabilityStatus.HEALTHY)
    )
    checks["unknown_values_still_fail"] = all(
        not league_state.availability_status_value_is_current(value)
        for value in ("injured_forever", "invalid_status", "", None, object())
    )

    checkpoint = load_franchise_checkpoint()
    if checkpoint is not None:
        league_state.validate_simulation_league_state(
            checkpoint.simulation_state
        )
    checks["live_checkpoint_validation"] = True

    failed = [name for name, ok in checks.items() if not ok]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE INJURY STATUS HOT-RELOAD FIX V1 VALIDATOR FAILED")
        return 1
    print("FRANCHISE INJURY STATUS HOT-RELOAD FIX V1 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
