from __future__ import annotations

import dataclasses
import inspect
from types import SimpleNamespace

from franchise_staff_system_v1 import (
    FranchiseStaffState,
    ensure_franchise_staff_state,
    scout_market_candidates,
    scouting_error_band_for_rating,
)
from franchise_onboarding_progression_v1 import render_first_time_tutorial_v1


def main() -> int:
    checks: dict[str, bool] = {}
    legacy = FranchiseStaffState.__new__(FranchiseStaffState)
    legacy.version = "legacy"
    legacy.season_label = "2027-28"
    legacy.teams = {}
    try:
        values = [getattr(legacy, field.name) for field in dataclasses.fields(legacy)]
        checks["legacy_dataclass_rebind_shape"] = (
            len(values) >= 4 and values[-1] is None
        )
    except Exception:
        checks["legacy_dataclass_rebind_shape"] = False

    fake = SimpleNamespace(
        settings=SimpleNamespace(season_label="2027-28"),
        teams={},
        franchise_staff_state_v1=legacy,
    )
    migrated = ensure_franchise_staff_state(fake)
    checks["legacy_staff_state_migrates_history"] = isinstance(
        migrated.scouting_history, list
    )
    checks["scout_market_still_available"] = (
        len(scout_market_candidates(fake, "CHI")) == 8
    )
    band = float(scouting_error_band_for_rating(89.0))
    checks["error_band_still_bounded"] = 0.5 <= band <= 12.0
    checks["tutorial_signature_compatible"] = (
        "persist_preferences"
        in inspect.signature(render_first_time_tutorial_v1).parameters
    )

    failed = [name for name, passed in checks.items() if not passed]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        raise SystemExit(
            "FRANCHISE SCOUT MANAGEMENT + TUTORIAL V1.0.1 COMPAT REGRESSION FAILED: "
            + ", ".join(failed)
        )
    print("FRANCHISE SCOUT MANAGEMENT + TUTORIAL V1.0.1 COMPAT REGRESSION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
