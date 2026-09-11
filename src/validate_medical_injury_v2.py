from __future__ import annotations

import argparse
import copy
import json
import py_compile
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGES = ROOT / "pages"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import load_runtime_data  # noqa: E402
from mutable_league_state_v1 import create_league_state  # noqa: E402
from simulation_league_state_v1 import (  # noqa: E402
    AvailabilityStatus,
    create_simulation_league_state,
    validate_simulation_league_state,
)
from state_runtime_adapter_v1 import build_state_runtime  # noqa: E402
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint  # noqa: E402
from simulation_injury_fatigue_v1 import (  # noqa: E402
    ensure_injury_fatigue_state,
    player_health_report_rows,
    prepare_health_for_game,
)
from simulation_medical_injury_v2 import (  # noqa: E402
    MEDICAL_INJURY_CATALOG,
    MEDICAL_INJURY_V2_VERSION,
    MedicalInjuryOutcome,
    advance_medical_case_after_appearance,
    ensure_medical_injury_v2_state,
    medical_case_snapshot,
    medical_risk_multiplier,
    register_medical_injury,
)


VALIDATOR_VERSION = "medical-injury-v2-validator-v1-2026-08-10"
REPORT = OUTPUTS / "medical_injury_v2_validation_v1.json"
PAGE = PAGES / "5_Franchise_Mode.py"
ENGINE = SRC / "simulation_injury_fatigue_v1.py"
MEDICAL = SRC / "simulation_medical_injury_v2.py"
EVENTS = SRC / "franchise_league_events_v1.py"


def _compile(path: Path) -> str:
    try:
        py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as exc:
        return str(exc)
    return ""


def _build_state():
    runtime_base = load_runtime_data()
    league_state = create_league_state(runtime_base)
    runtime = build_state_runtime(runtime_base, league_state)
    state = create_simulation_league_state(runtime, league_state)
    ensure_injury_fatigue_state(state)
    ensure_medical_injury_v2_state(state)
    return state


def _player(state):
    return next(
        player_id
        for player_id, player in state.players.items()
        if not player.synthetic and player.team_abbreviation in state.teams
    )


def _install_case(
    state,
    player_id: str,
    outcome: MedicalInjuryOutcome,
    *,
    day_index: int,
    event_kind: str = "injury",
) -> None:
    injury = state.injuries[player_id]
    injury.status = outcome.status
    injury.injury_type = outcome.injury_type
    injury.performance_multiplier = outcome.performance_multiplier
    injury.aggravation_risk = outcome.aggravation_risk
    injury.notes = "Medical/Injury V2 validation case."
    profile = ensure_injury_fatigue_state(state)[player_id]
    profile.expected_return_day = day_index + outcome.days
    profile.injury_severity = outcome.severity
    profile.minutes_limit = outcome.minutes_limit
    profile.status_reason = injury.notes
    register_medical_injury(
        state,
        player_id,
        outcome,
        day_index=day_index,
        event_kind=event_kind,
    )


def run_validation() -> dict[str, Any]:
    state = _build_state()
    player_id = _player(state)
    team = state.players[player_id].team_abbreviation
    cases = ensure_medical_injury_v2_state(state)

    moderate = MedicalInjuryOutcome(
        injury_type="hamstring strain",
        body_region="hamstring",
        severity="moderate",
        grade="grade II",
        status=AvailabilityStatus.OUT,
        days=20,
        performance_multiplier=1.0,
        aggravation_risk=0.20,
        minutes_limit=None,
    )
    _install_case(state, player_id, moderate, day_index=10)

    acute_state = copy.deepcopy(state)
    prepare_health_for_game(acute_state, day_index=14, teams=(team,))
    acute_case = ensure_medical_injury_v2_state(acute_state)[player_id]

    rtp_state = copy.deepcopy(state)
    prepare_health_for_game(rtp_state, day_index=27, teams=(team,))
    rtp_case = ensure_medical_injury_v2_state(rtp_state)[player_id]

    return_state = copy.deepcopy(state)
    prepare_health_for_game(return_state, day_index=30, teams=(team,))
    return_case = ensure_medical_injury_v2_state(return_state)[player_id]
    return_phase = str(return_case.rehab_phase)
    first_limit = ensure_injury_fatigue_state(return_state)[player_id].minutes_limit
    return_status = return_state.injuries[player_id].status
    for offset in range(3):
        advance_medical_case_after_appearance(
            return_state,
            player_id,
            day_index=30 + offset,
        )
    cleared_case = ensure_medical_injury_v2_state(return_state)[player_id]
    cleared_injury = return_state.injuries[player_id]

    recurrence_state = _build_state()
    ankle = MedicalInjuryOutcome(
        injury_type="moderate ankle sprain",
        body_region="ankle",
        severity="moderate",
        grade="grade II",
        status=AvailabilityStatus.OUT,
        days=18,
        performance_multiplier=1.0,
        aggravation_risk=0.22,
        minutes_limit=None,
    )
    _install_case(recurrence_state, player_id, ankle, day_index=5, event_kind="injury")
    _install_case(recurrence_state, player_id, ankle, day_index=20, event_kind="setback")
    recurrence_case = ensure_medical_injury_v2_state(recurrence_state)[player_id]

    report_rows = player_health_report_rows(recurrence_state, team, day_index=21)
    player_row = next(row for row in report_rows if row["player_id"] == player_id)
    medical_snapshot = medical_case_snapshot(recurrence_state, player_id, day_index=21)

    checkpoint = load_franchise_checkpoint()
    checkpoint_result = {
        "found": checkpoint is not None,
        "medical_profiles": 0,
        "state_valid": True,
        "report_fields_present": True,
    }
    if checkpoint is not None:
        checkpoint_state = copy.deepcopy(checkpoint.simulation_state)
        ensure_injury_fatigue_state(checkpoint_state)
        checkpoint_cases = ensure_medical_injury_v2_state(checkpoint_state)
        checkpoint_result["medical_profiles"] = len(checkpoint_cases)
        checkpoint_result["state_valid"] = bool(
            validate_simulation_league_state(checkpoint_state)
        )
        checkpoint_rows = []
        for checkpoint_team in sorted(checkpoint_state.teams)[:2]:
            checkpoint_rows.extend(
                player_health_report_rows(checkpoint_state, checkpoint_team)
            )
        checkpoint_result["report_fields_present"] = all(
            "medical_phase" in row and "recovery_progress" in row
            for row in checkpoint_rows
        )

    page_text = PAGE.read_text(encoding="utf-8")
    engine_text = ENGINE.read_text(encoding="utf-8")
    events_text = EVENTS.read_text(encoding="utf-8")
    compile_errors = {
        str(path.relative_to(ROOT)): _compile(path)
        for path in (PAGE, ENGINE, MEDICAL, EVENTS, Path(__file__))
    }

    checks = {
        "medical_version_is_current": MEDICAL_INJURY_V2_VERSION.endswith("2026-08-10"),
        "catalog_is_substantial": len(MEDICAL_INJURY_CATALOG) >= 18,
        "medical_cases_cover_all_players": set(cases) == set(state.players),
        "acute_phase_remains_unavailable": acute_case.rehab_phase == "acute" and acute_state.injuries[player_id].status == AvailabilityStatus.OUT,
        "late_rehab_moves_to_return_to_play": rtp_case.rehab_phase == "return_to_play" and rtp_state.injuries[player_id].status == AvailabilityStatus.DOUBTFUL,
        "return_day_starts_minutes_ramp": return_phase == "return_ramp" and return_status in {AvailabilityStatus.QUESTIONABLE, AvailabilityStatus.PROBABLE} and first_limit is not None and first_limit <= 30.0,
        "return_ramp_eventually_clears": cleared_injury.status == AvailabilityStatus.HEALTHY and cleared_case.rehab_phase == "cleared" and cleared_case.return_ramp_games_remaining == 0,
        "history_survives_clearance": bool(cleared_case.history),
        "setback_is_tracked": recurrence_case.setback_count >= 1 and recurrence_case.last_event_kind == "setback",
        "recurrence_history_is_tracked": recurrence_case.recurrence_count >= 1 and len(recurrence_case.history) >= 2,
        "medical_history_raises_risk_modifier": medical_risk_multiplier(recurrence_state, player_id) > 1.0,
        "health_rows_expose_medical_fields": all(key in player_row for key in ("medical_phase", "recovery_progress", "body_region", "injury_grade", "reinjury_risk", "recurrence_count", "setback_count")),
        "medical_snapshot_is_bounded": 0.0 <= float(medical_snapshot["recovery_progress"]) <= 100.0 and 0.0 <= float(medical_snapshot["reinjury_risk"]) <= 65.0,
        "page_exposes_rehab_ui": all(marker in page_text for marker in ("Rehab / return", "Recovery %", "Reinjury %", "Medical phase", "Same-region recurrences")),
        "base_engine_delegates_to_medical_v2": all(marker in engine_text for marker in ("medical_risk_multiplier", "prepare_medical_cases_for_game", "choose_medical_injury_outcome", "register_medical_injury", "advance_medical_case_after_appearance")),
        "event_inbox_supports_setbacks": "event_kind == \"setback\"" in events_text and "Same-region recurrence count" in events_text,
        "state_remains_valid": bool(validate_simulation_league_state(return_state)) and bool(validate_simulation_league_state(recurrence_state)),
        "live_checkpoint_migrates_when_present": (
            not checkpoint_result["found"]
            or (
                checkpoint_result["medical_profiles"] > 0
                and checkpoint_result["state_valid"]
                and checkpoint_result["report_fields_present"]
            )
        ),
        "all_modified_files_compile": not any(compile_errors.values()),
    }
    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "script": VALIDATOR_VERSION,
        "medical_version": MEDICAL_INJURY_V2_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "sample": {
            "player_id": player_id,
            "team": team,
            "acute_phase": acute_case.rehab_phase,
            "return_to_play_phase": rtp_case.rehab_phase,
            "return_status": return_status.value,
            "initial_return_limit": first_limit,
            "cleared_phase": cleared_case.rehab_phase,
            "setbacks": recurrence_case.setback_count,
            "recurrences": recurrence_case.recurrence_count,
            "medical_row": player_row,
        },
        "checkpoint": checkpoint_result,
        "compile_errors": compile_errors,
        "passed": not failed,
    }
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    if failed:
        raise AssertionError("Medical/Injury V2 validation failed: " + ", ".join(failed))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260810)
    parser.parse_args()
    print(json.dumps(run_validation(), indent=2, default=str))
    print("\nMEDICAL / INJURY V2 VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
