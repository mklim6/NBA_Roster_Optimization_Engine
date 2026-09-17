from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from franchise_staff_system_v1 import (
    STAFF_SYSTEM_VERSION,
    archive_completed_scouting_accuracy,
    ensure_franchise_staff_state,
    hire_lead_scout,
    lead_scout_member,
    scout_market_candidates,
    scouting_error_band,
    scouting_track_record_rows,
)

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "outputs" / "franchise_scout_management_tutorial_v1_regression.json"
VERSION = "franchise-scout-management-tutorial-regression-v1.0-2026-09-16"


class State:
    pass


def fresh_state() -> State:
    state = State()
    state.settings = SimpleNamespace(season_label="2027-28")
    state.teams = {"CHI": object(), "BOS": object(), "OKC": object()}
    return state


def main() -> int:
    state = fresh_state()
    staff_state = ensure_franchise_staff_state(state)
    original = lead_scout_member(state, "CHI", ensure=True)
    candidates_a = scout_market_candidates(state, "CHI")
    candidates_b = scout_market_candidates(state, "CHI")
    before_current_band = scouting_error_band(state, "CHI")
    before_potential_band = scouting_error_band(state, "CHI", potential=True)

    # Pick the market candidate with the largest combined rating difference to guarantee a visible effect.
    candidate = max(
        candidates_a,
        key=lambda row: abs(row.scouting_current_rating - original.scouting_current_rating)
        + abs(row.scouting_potential_rating - original.scouting_potential_rating),
    )
    hired = hire_lead_scout(state, "CHI", candidate.staff_id)
    after_current_band = scouting_error_band(state, "CHI")
    after_potential_band = scouting_error_band(state, "CHI", potential=True)

    state.franchise_draft_state_v1 = {
        "phase": "draft_complete",
        "draft_year": 2028,
        "prospects": [
            {"prospect_id": "P1", "hidden_overall": 80.0, "hidden_potential": 88.0},
            {"prospect_id": "P2", "hidden_overall": 72.0, "hidden_potential": 78.0},
            {"prospect_id": "P3", "hidden_overall": 68.0, "hidden_potential": 82.0},
        ],
        "scouting_discovery_v1": {
            "teams": {
                "CHI": {
                    "reports": {
                        "P1": {"scouted_overall": 79.0, "scouted_potential": 85.0},
                        "P2": {"scouted_overall": 76.0, "scouted_potential": 80.0},
                        "P3": {"scouted_overall": 60.0, "scouted_potential": 69.0},
                    }
                }
            }
        },
    }
    first_archive = archive_completed_scouting_accuracy(state)
    second_archive = archive_completed_scouting_accuracy(state)
    history = scouting_track_record_rows(state, "CHI")
    record = history[0] if history else {}

    checks = {
        "staff_version_current": STAFF_SYSTEM_VERSION.endswith("2026-09-16"),
        "staff_state_attached": getattr(state, "franchise_staff_state_v1", None) is staff_state,
        "market_has_eight_candidates": len(candidates_a) == 8,
        "market_is_deterministic": [row.staff_id for row in candidates_a] == [row.staff_id for row in candidates_b]
        and [(row.scouting_current_rating, row.scouting_potential_rating) for row in candidates_a]
        == [(row.scouting_current_rating, row.scouting_potential_rating) for row in candidates_b],
        "candidate_contracts_valid": all(row.contract_years_remaining >= 1 and row.annual_salary_millions > 0 for row in candidates_a),
        "hire_replaces_lead_scout": lead_scout_member(state, "CHI").staff_id == candidate.staff_id
        and hired.team == "CHI",
        "hire_changes_uncertainty": (before_current_band, before_potential_band) != (after_current_band, after_potential_band),
        "archive_created_after_draft": len(first_archive) == 1 and len(history) == 1,
        "archive_is_idempotent": second_archive == [],
        "archive_math_overall_mae": abs(float(record.get("overall_mae", -1)) - (1 + 4 + 8) / 3) < 0.02,
        "archive_math_potential_mae": abs(float(record.get("potential_mae", -1)) - (3 + 2 + 13) / 3) < 0.02,
        "archive_counts_major_miss": int(record.get("major_misses", -1)) == 1,
        "archive_counts_strong_find": int(record.get("strong_finds", -1)) == 1,
        "history_records_scout": record.get("lead_scout") == hired.name,
    }
    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "version": VERSION,
        "checks": checks,
        "failed_checks": failed,
        "bands_before": [before_current_band, before_potential_band],
        "bands_after": [after_current_band, after_potential_band],
        "history": history,
        "passed": not failed,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(report)
    if failed:
        print("FRANCHISE SCOUT MANAGEMENT + TUTORIAL V1 REGRESSION FAILED")
        return 1
    print("FRANCHISE SCOUT MANAGEMENT + TUTORIAL V1 REGRESSION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
