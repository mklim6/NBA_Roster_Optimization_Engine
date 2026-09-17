from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_staff_system_v1 import ensure_franchise_staff_state, ROLE_HEAD_COACH
from run_franchise_protected_multi_season_soak_v1 import _staff_personnel_signature
from run_franchise_protected_lifecycle_boundary_regression_v1 import _staff_signature

VERSION = "franchise-protected-multi-season-soak-staff-invariant-regression-v1-2026-09-17"
TEAM_CODES = (
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
)


def main() -> int:
    state = SimpleNamespace(
        settings=SimpleNamespace(season_label="2026-27"),
        teams={team: SimpleNamespace() for team in TEAM_CODES},
    )
    staff = ensure_franchise_staff_state(state)
    baseline_personnel = _staff_personnel_signature(state)
    baseline_full = _staff_signature(state)

    metadata_only = copy.deepcopy(state)
    metadata_staff = ensure_franchise_staff_state(metadata_only)
    metadata_only.settings.season_label = "2027-28"
    metadata_staff = ensure_franchise_staff_state(metadata_only)
    metadata_staff.scouting_history.append({
        "version": "synthetic-regression",
        "draft_year": 2027,
        "team": "CHI",
        "mean_ovr_error": 2.5,
    })

    personnel_changed = copy.deepcopy(metadata_only)
    changed_staff = ensure_franchise_staff_state(personnel_changed)
    changed_staff.teams["CHI"].members[ROLE_HEAD_COACH].contract_years_remaining += 1

    checks = {
        "initializes_30_staff_teams": len(staff.teams) == 30,
        "baseline_personnel_signature_present": bool(baseline_personnel),
        "metadata_progression_changes_full_signature": _staff_signature(metadata_only) != baseline_full,
        "metadata_progression_preserves_personnel_signature": _staff_personnel_signature(metadata_only) == baseline_personnel,
        "season_label_progressed": metadata_staff.season_label == "2027-28",
        "scouting_history_progressed": len(metadata_staff.scouting_history or []) == 1,
        "real_personnel_change_breaks_personnel_signature": _staff_personnel_signature(personnel_changed) != baseline_personnel,
    }
    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "version": VERSION,
        "checks": checks,
        "failed_checks": failed,
        "passed": not failed,
    }
    print(json.dumps(report, indent=2))
    print()
    if failed:
        print("FRANCHISE MULTI-SEASON STAFF INVARIANT REGRESSION FAILED")
        return 1
    print("FRANCHISE MULTI-SEASON STAFF INVARIANT REGRESSION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
