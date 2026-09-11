from __future__ import annotations

import copy
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_staff_system_v1 import (  # noqa: E402
    ROLE_DEVELOPMENT_COACH,
    ROLE_HEAD_COACH,
    ROLE_MEDICAL_DIRECTOR,
    STAFF_ROLES,
    STAFF_STATE_ATTRIBUTE,
    STAFF_SYSTEM_VERSION,
    build_team_staff,
    ensure_franchise_staff_state,
    scouting_error_band,
    team_staff_effects,
)
from player_development_engine_v1 import project_player_development  # noqa: E402
from simulation_franchise_checkpoint_v1 import (  # noqa: E402
    CHECKPOINT_VERSION,
    FranchiseCheckpoint,
    decode_checkpoint,
    encode_checkpoint,
)
from simulation_player_stat_profiles_v1 import load_player_stat_profiles  # noqa: E402

REPORT = OUTPUTS / "franchise_staff_foundation_v1_validation.json"


def _fake_state(teams=("ATL", "BOS", "CHI", "OKC")):
    return SimpleNamespace(
        settings=SimpleNamespace(season_label="2026-27"),
        teams={team: SimpleNamespace(team_abbreviation=team) for team in teams},
    )


def _find_profile() -> dict:
    profiles = load_player_stat_profiles()
    for profile in profiles.values():
        age = profile.get("age_2026_27", profile.get("age"))
        if age is not None and 19 <= float(age) <= 24:
            return dict(profile)
    return dict(next(iter(profiles.values())))


def main() -> int:
    state = _fake_state()
    staff_state = ensure_franchise_staff_state(state)
    repeated = _fake_state()
    repeated_state = ensure_franchise_staff_state(repeated)

    checks: dict[str, bool] = {}
    checks["staff_state_attached"] = getattr(state, STAFF_STATE_ATTRIBUTE, None) is staff_state
    checks["staff_version_current"] = staff_state.version == STAFF_SYSTEM_VERSION
    checks["all_teams_have_complete_staff"] = all(
        set(team_state.members) == set(STAFF_ROLES)
        for team_state in staff_state.teams.values()
    ) and len(staff_state.teams) == len(state.teams)
    checks["generation_is_deterministic"] = (
        staff_state.teams["CHI"].members[ROLE_HEAD_COACH].name
        == repeated_state.teams["CHI"].members[ROLE_HEAD_COACH].name
        and staff_state.teams["CHI"].members[ROLE_HEAD_COACH].overall_rating
        == repeated_state.teams["CHI"].members[ROLE_HEAD_COACH].overall_rating
    )

    all_members = [member for team_state in staff_state.teams.values() for member in team_state.members.values()]
    checks["ratings_are_bounded"] = all(
        45.0 <= float(value) <= 96.0
        for member in all_members
        for value in (
            member.overall_rating,
            member.offense_rating,
            member.defense_rating,
            member.rotation_management_rating,
            member.player_development_rating,
            member.scouting_current_rating,
            member.scouting_potential_rating,
            member.medical_prevention_rating,
            member.medical_recovery_rating,
        )
    )
    checks["contracts_are_valid"] = all(
        1 <= member.contract_years_remaining <= 5
        and member.annual_salary_millions > 0
        for member in all_members
    )

    neutral = _fake_state(("CHI",))
    neutral_effects = team_staff_effects(neutral, "CHI", ensure=False)
    checks["old_uninitialized_state_is_neutral"] = (
        neutral_effects.development_modifier == 0.0
        and neutral_effects.injury_risk_multiplier == 1.0
        and neutral_effects.recovery_multiplier == 1.0
    )

    # Controlled comparison: same team, only staff ratings change.
    high = _fake_state(("CHI",))
    low = _fake_state(("CHI",))
    ensure_franchise_staff_state(high)
    ensure_franchise_staff_state(low)
    for test_state, rating in ((high, 95.0), (low, 45.0)):
        members = getattr(test_state, STAFF_STATE_ATTRIBUTE).teams["CHI"].members
        members[ROLE_HEAD_COACH].player_development_rating = rating
        members[ROLE_DEVELOPMENT_COACH].player_development_rating = rating
        members[ROLE_MEDICAL_DIRECTOR].medical_prevention_rating = rating
        members[ROLE_MEDICAL_DIRECTOR].medical_recovery_rating = rating

    high_effects = team_staff_effects(high, "CHI")
    low_effects = team_staff_effects(low, "CHI")
    checks["staff_quality_changes_development"] = high_effects.development_modifier > low_effects.development_modifier
    checks["staff_quality_changes_injury_risk"] = high_effects.injury_risk_multiplier < low_effects.injury_risk_multiplier
    checks["staff_quality_changes_recovery"] = high_effects.recovery_multiplier > low_effects.recovery_multiplier
    checks["scouting_band_is_imperfect_and_bounded"] = all(
        3.0 <= scouting_error_band(state, team, potential=potential) <= 11.0
        for team in state.teams
        for potential in (False, True)
    )

    profile = _find_profile()
    baseline_a = project_player_development(profile)
    baseline_b = project_player_development(profile, development_modifier=0.0)
    checks["development_default_is_backward_compatible"] = baseline_a == baseline_b
    high_projection = project_player_development(profile, development_modifier=0.30)
    low_projection = project_player_development(profile, development_modifier=-0.30)
    checks["development_modifier_reaches_engine"] = high_projection.overall_delta > low_projection.overall_delta

    checkpoint = FranchiseCheckpoint(
        version=CHECKPOINT_VERSION,
        saved_at_utc="2026-09-09T00:00:00+00:00",
        simulation_state=state,
        trade_state=SimpleNamespace(revision=1),
        preferences={},
        reason="staff-foundation-validator",
    )
    restored = decode_checkpoint(encode_checkpoint(checkpoint))
    restored_staff = getattr(restored.simulation_state, STAFF_STATE_ATTRIBUTE, None)
    checks["staff_survives_checkpoint_roundtrip"] = (
        restored_staff is not None
        and restored_staff.teams["CHI"].members[ROLE_HEAD_COACH].staff_id
        == staff_state.teams["CHI"].members[ROLE_HEAD_COACH].staff_id
    )

    page_text = (ROOT / "pages" / "5_Franchise_Mode.py").read_text(encoding="utf-8")
    injury_text = (SRC / "simulation_injury_fatigue_v1.py").read_text(encoding="utf-8")
    transition_text = (SRC / "simulation_season_transition_v1.py").read_text(encoding="utf-8")
    checks["franchise_mode_has_staff_workspace"] = (
        '"Staff": "Staff"' in page_text
        and 'active_section == "Staff"' in page_text
        and "ensure_franchise_staff_state(state)" in page_text
    )
    checks["medical_engine_consumes_staff"] = (
        "staff_medical_factor" in injury_text
        and "team_injury_risk_multiplier" in injury_text
        and "team_recovery_multiplier" in injury_text
    )
    checks["season_transition_consumes_staff"] = "team_development_modifier" in transition_text and "staff_system_version" in transition_text

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "version": "franchise-staff-foundation-v1.0-2026-09-09",
        "staff_system_version": STAFF_SYSTEM_VERSION,
        "team_count": len(staff_state.teams),
        "staff_member_count": len(all_members),
        "sample_team_effects": {team: team_staff_effects(state, team).__dict__ for team in state.teams},
        "checks": checks,
        "failed_checks": failed,
        "passed": not failed,
    }
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print()
    print("FRANCHISE STAFF FOUNDATION V1 " + ("PASSED" if not failed else "FAILED"))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
