from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"
REFERENCE = ROOT / "app_data" / "nba_real_staff_reference_2026_09_07.json"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_staff_system_v1 import (  # noqa: E402
    REAL_STAFF_REFERENCE_VERSION,
    ROLE_HEAD_COACH,
    STAFF_STATE_ATTRIBUTE,
    ensure_franchise_staff_state,
    team_staff_effects,
)

EXPECTED = {
    "ATL": "Quin Snyder", "BOS": "Joe Mazzulla", "BKN": "Jordi Fernandez", "CHA": "Charles Lee",
    "CHI": "Tiago Splitter", "CLE": "Kenny Atkinson", "DAL": "Dusty May", "DEN": "David Adelman",
    "DET": "J. B. Bickerstaff", "GSW": "Steve Kerr", "HOU": "Ime Udoka", "IND": "Rick Carlisle",
    "LAC": "Tyronn Lue", "LAL": "JJ Redick", "MEM": "Tuomas Iisalo", "MIA": "Erik Spoelstra",
    "MIL": "Taylor Jenkins", "MIN": "Chris Finch", "NOP": "Jamahl Mosley", "NYK": "Mike Brown",
    "OKC": "Mark Daigneault", "ORL": "Sean Sweeney", "PHI": "Nick Nurse", "PHX": "Jordan Ott",
    "POR": "Micah Nori", "SAC": "Doug Christie", "SAS": "Mitch Johnson", "TOR": "Darko Rajakovic",
    "UTA": "Will Hardy", "WAS": "Brian Keefe",
}

NEW_2026 = {
    "CHI": "Tiago Splitter", "DAL": "Dusty May", "MIL": "Taylor Jenkins",
    "NOP": "Jamahl Mosley", "ORL": "Sean Sweeney", "POR": "Micah Nori",
}


def fake_state():
    return SimpleNamespace(
        settings=SimpleNamespace(season_label="2026-27"),
        teams={team: SimpleNamespace(team_abbreviation=team) for team in EXPECTED},
    )


def main() -> int:
    checks: dict[str, bool] = {}
    payload = json.loads(REFERENCE.read_text(encoding="utf-8"))
    checks["reference_version_current"] = payload.get("version") == REAL_STAFF_REFERENCE_VERSION
    checks["reference_is_sep7_2026"] = payload.get("as_of_date") == "2026-09-07"
    checks["reference_has_all_30_teams"] = set(payload.get("teams", {})) == set(EXPECTED) and len(EXPECTED) == 30

    state = fake_state()
    staff = ensure_franchise_staff_state(state)
    actual = {team: staff.teams[team].members[ROLE_HEAD_COACH].name for team in EXPECTED}
    checks["all_30_head_coaches_match_reference"] = actual == EXPECTED
    checks["six_2026_changes_are_current"] = all(actual[team] == name for team, name in NEW_2026.items())
    checks["bulls_head_coach_is_tiago_splitter"] = actual["CHI"] == "Tiago Splitter"
    checks["real_head_coaches_are_labeled_real"] = all(
        staff.teams[team].members[ROLE_HEAD_COACH].source
        == "nba_real_world_head_coach_sep7_2026_simulated_attributes_v1"
        for team in EXPECTED
    )
    checks["supporting_staff_remain_sim_generated"] = all(
        member.source == "generated_staff_foundation_v1"
        for team_state in staff.teams.values()
        for role, member in team_state.members.items()
        if role != ROLE_HEAD_COACH
    )

    # Migration safety: identity changes, gameplay attributes/effects do not.
    migrated = fake_state()
    ensure_franchise_staff_state(migrated)
    before_effects = team_staff_effects(migrated, "CHI")
    head = getattr(migrated, STAFF_STATE_ATTRIBUTE).teams["CHI"].members[ROLE_HEAD_COACH]
    preserved = {
        name: copy.deepcopy(getattr(head, name))
        for name in (
            "overall_rating", "offense_rating", "defense_rating", "rotation_management_rating",
            "player_development_rating", "scouting_current_rating", "scouting_potential_rating",
            "medical_prevention_rating", "medical_recovery_rating", "communication_rating",
            "adaptability_rating", "traits", "contract_years_remaining", "annual_salary_millions",
            "years_experience", "staff_id",
        )
    }
    head.name = "Sean Parker"
    head.age = 47
    head.source = "generated_staff_foundation_v1"
    ensure_franchise_staff_state(migrated)
    migrated_head = getattr(migrated, STAFF_STATE_ATTRIBUTE).teams["CHI"].members[ROLE_HEAD_COACH]
    after_effects = team_staff_effects(migrated, "CHI")
    checks["existing_save_identity_migrates"] = migrated_head.name == "Tiago Splitter" and migrated_head.age == 41
    checks["existing_save_gameplay_attributes_preserved"] = all(
        getattr(migrated_head, name) == value for name, value in preserved.items()
    )
    checks["existing_save_team_effects_preserved"] = before_effects == after_effects

    ui_text = (SRC / "franchise_staff_ui_v1.py").read_text(encoding="utf-8")
    checks["ui_explains_real_vs_simulated_fields"] = (
        "Head coaches are seeded from the real NBA as of Sep. 7, 2026" in ui_text
        and '"personnel_basis": "Personnel"' in ui_text
    )

    failed = [name for name, ok in checks.items() if not ok]
    report = {
        "version": "franchise-real-staff-seed-v1-validator-2026-09-11",
        "reference_version": payload.get("version"),
        "team_count": len(actual),
        "sample": {team: actual[team] for team in ("CHI", "DAL", "MIL", "NOP", "ORL", "POR")},
        "checks": checks,
        "failed_checks": failed,
        "passed": not failed,
    }
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    (OUTPUTS / "franchise_real_staff_seed_v1_validation.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    print()
    print("FRANCHISE REAL STAFF SEED V1 " + ("PASSED" if not failed else "FAILED"))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
