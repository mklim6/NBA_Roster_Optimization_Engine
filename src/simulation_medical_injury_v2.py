from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from simulation_league_state_v1 import (  # noqa: E402
    AvailabilityStatus,
    SimulationLeagueState,
)


MEDICAL_INJURY_V2_VERSION = "medical-injury-v2-2026-08-10"
MEDICAL_STATE_ATTRIBUTE = "medical_injury_v2_cases"
MEDICAL_NORMALIZATION_MARKER_ATTRIBUTE = "_medical_injury_v2_normalization_marker"
SELF_TEST_REPORT = OUTPUTS / "medical_injury_v2_self_test.json"

PLAYABLE_STATUSES = {
    AvailabilityStatus.PROBABLE,
    AvailabilityStatus.QUESTIONABLE,
    AvailabilityStatus.DAY_TO_DAY,
}
UNAVAILABLE_STATUSES = {
    AvailabilityStatus.OUT,
    AvailabilityStatus.DOUBTFUL,
}


@dataclass(frozen=True)
class MedicalInjurySpec:
    injury_type: str
    body_region: str
    severity: str
    grade: str
    minimum_days: int
    maximum_days: int
    performance_low: float
    performance_high: float
    aggravation_low: float
    aggravation_high: float
    minutes_low: float | None
    minutes_high: float | None
    weight: int = 1


@dataclass(frozen=True)
class MedicalInjuryOutcome:
    injury_type: str
    body_region: str
    severity: str
    grade: str
    status: AvailabilityStatus
    days: int
    performance_multiplier: float
    aggravation_risk: float
    minutes_limit: float | None


@dataclass
class MedicalCaseState:
    player_id: str
    season_label: str
    injury_type: str = ""
    body_region: str = ""
    severity: str = ""
    grade: str = ""
    onset_day: int = 0
    initial_expected_return_day: int = 0
    expected_return_day: int = 0
    rehab_phase: str = "healthy"
    recovery_progress: float = 100.0
    return_ramp_games_remaining: int = 0
    games_since_return: int = 0
    recurrence_count: int = 0
    setback_count: int = 0
    last_setback_day: int = 0
    last_clear_day: int = 0
    last_event_kind: str = ""
    history: tuple[dict[str, Any], ...] = ()


MEDICAL_INJURY_CATALOG: tuple[MedicalInjurySpec, ...] = (
    MedicalInjurySpec(
        "ankle soreness", "ankle", "soreness", "irritation",
        1, 3, 0.95, 0.99, 0.10, 0.18, 28.0, 34.0, 5,
    ),
    MedicalInjurySpec(
        "knee soreness", "knee", "soreness", "irritation",
        1, 4, 0.95, 0.99, 0.10, 0.19, 27.0, 33.0, 5,
    ),
    MedicalInjurySpec(
        "lower-back tightness", "back", "soreness", "tightness",
        1, 4, 0.94, 0.98, 0.12, 0.21, 26.0, 33.0, 4,
    ),
    MedicalInjurySpec(
        "calf tightness", "calf", "soreness", "tightness",
        1, 4, 0.94, 0.98, 0.13, 0.22, 25.0, 32.0, 4,
    ),
    MedicalInjurySpec(
        "hip soreness", "hip", "soreness", "irritation",
        1, 4, 0.95, 0.99, 0.10, 0.19, 27.0, 33.0, 4,
    ),
    MedicalInjurySpec(
        "mild ankle sprain", "ankle", "minor", "grade I",
        3, 9, 0.91, 0.96, 0.12, 0.21, 22.0, 29.0, 5,
    ),
    MedicalInjurySpec(
        "wrist sprain", "wrist", "minor", "grade I",
        3, 10, 0.92, 0.97, 0.10, 0.18, 24.0, 31.0, 3,
    ),
    MedicalInjurySpec(
        "back strain", "back", "minor", "grade I",
        4, 12, 0.91, 0.96, 0.13, 0.22, 22.0, 29.0, 4,
    ),
    MedicalInjurySpec(
        "quad contusion", "quadriceps", "minor", "contusion",
        2, 8, 0.92, 0.97, 0.09, 0.16, 24.0, 31.0, 4,
    ),
    MedicalInjurySpec(
        "shoulder bruise", "shoulder", "minor", "contusion",
        2, 7, 0.93, 0.98, 0.08, 0.15, 25.0, 32.0, 3,
    ),
    MedicalInjurySpec(
        "hamstring strain", "hamstring", "moderate", "grade II",
        14, 35, 1.0, 1.0, 0.14, 0.25, None, None, 5,
    ),
    MedicalInjurySpec(
        "moderate ankle sprain", "ankle", "moderate", "grade II",
        12, 30, 1.0, 1.0, 0.12, 0.23, None, None, 5,
    ),
    MedicalInjurySpec(
        "knee sprain", "knee", "moderate", "grade II",
        14, 38, 1.0, 1.0, 0.14, 0.25, None, None, 4,
    ),
    MedicalInjurySpec(
        "calf strain", "calf", "moderate", "grade II",
        14, 35, 1.0, 1.0, 0.15, 0.26, None, None, 4,
    ),
    MedicalInjurySpec(
        "shoulder sprain", "shoulder", "moderate", "grade II",
        10, 28, 1.0, 1.0, 0.11, 0.21, None, None, 3,
    ),
    MedicalInjurySpec(
        "concussion", "head", "moderate", "protocol",
        7, 21, 1.0, 1.0, 0.05, 0.12, None, None, 2,
    ),
    MedicalInjurySpec(
        "severe ankle sprain", "ankle", "major", "grade III",
        28, 60, 1.0, 1.0, 0.16, 0.28, None, None, 5,
    ),
    MedicalInjurySpec(
        "major hamstring strain", "hamstring", "major", "grade III",
        35, 75, 1.0, 1.0, 0.18, 0.31, None, None, 4,
    ),
    MedicalInjurySpec(
        "knee ligament injury", "knee", "major", "ligament",
        70, 220, 1.0, 1.0, 0.14, 0.26, None, None, 2,
    ),
    MedicalInjurySpec(
        "foot fracture", "foot", "major", "fracture",
        42, 100, 1.0, 1.0, 0.12, 0.23, None, None, 3,
    ),
    MedicalInjurySpec(
        "shoulder dislocation", "shoulder", "major", "dislocation",
        28, 70, 1.0, 1.0, 0.16, 0.29, None, None, 2,
    ),
)

_CATALOG_BY_NAME = {spec.injury_type: spec for spec in MEDICAL_INJURY_CATALOG}


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _default_case(state: SimulationLeagueState, player_id: str) -> MedicalCaseState:
    injury = state.injuries[player_id]
    if injury.status == AvailabilityStatus.HEALTHY:
        return MedicalCaseState(player_id=player_id, season_label=state.settings.season_label)
    spec = _CATALOG_BY_NAME.get(str(injury.injury_type or "").replace("managed ", "", 1))
    profile = getattr(state, "injury_fatigue_profiles", {}).get(player_id)
    expected = int(getattr(profile, "expected_return_day", 0) or 0) if profile is not None else 0
    current_day = int(getattr(state, "current_day_index", 0) or 0)
    if expected <= current_day:
        expected = current_day + max(1, int(getattr(injury, "games_remaining", 0) or 1) * 2)
    remaining_days = max(1, expected - current_day)
    onset = max(0, current_day - remaining_days)
    severity = (
        str(getattr(profile, "injury_severity", "") or "")
        if profile is not None
        else ""
    ) or (spec.severity if spec else "legacy")
    return MedicalCaseState(
        player_id=player_id,
        season_label=state.settings.season_label,
        injury_type=str(injury.injury_type or ""),
        body_region=spec.body_region if spec else "other",
        severity=severity,
        grade=spec.grade if spec else "legacy",
        onset_day=onset,
        initial_expected_return_day=expected,
        expected_return_day=expected,
        rehab_phase="rehab",
        recovery_progress=50.0,
    )


def _migrate_case(
    state: SimulationLeagueState,
    player_id: str,
    source: Any,
) -> MedicalCaseState:
    if source is None or str(getattr(source, "season_label", "") or "") not in {
        "", state.settings.season_label
    }:
        return _default_case(state, player_id)
    migrated = _default_case(state, player_id)
    for item in fields(MedicalCaseState):
        if item.name in {"player_id", "season_label"}:
            continue
        if hasattr(source, item.name):
            setattr(migrated, item.name, copy.deepcopy(getattr(source, item.name)))
    migrated.player_id = player_id
    migrated.season_label = state.settings.season_label
    migrated.onset_day = max(0, int(migrated.onset_day or 0))
    migrated.initial_expected_return_day = max(0, int(migrated.initial_expected_return_day or 0))
    migrated.expected_return_day = max(0, int(migrated.expected_return_day or 0))
    migrated.recovery_progress = round(clamp(float(migrated.recovery_progress or 0.0), 0.0, 100.0), 1)
    migrated.return_ramp_games_remaining = max(0, int(migrated.return_ramp_games_remaining or 0))
    migrated.games_since_return = max(0, int(migrated.games_since_return or 0))
    migrated.recurrence_count = max(0, int(migrated.recurrence_count or 0))
    migrated.setback_count = max(0, int(migrated.setback_count or 0))
    migrated.history = tuple(copy.deepcopy(tuple(migrated.history or ())[-12:]))
    return migrated


def ensure_medical_injury_v2_state(
    state: SimulationLeagueState,
) -> dict[str, MedicalCaseState]:
    cases = getattr(state, MEDICAL_STATE_ATTRIBUTE, None)
    marker = (
        MEDICAL_INJURY_V2_VERSION,
        state.settings.season_label,
        len(state.players),
        id(state.players),
        id(MedicalCaseState),
    )
    if isinstance(cases, dict) and getattr(
        state, MEDICAL_NORMALIZATION_MARKER_ATTRIBUTE, None
    ) == marker:
        return cases
    if not isinstance(cases, dict):
        cases = {}
    normalized = {
        player_id: _migrate_case(state, player_id, cases.get(player_id))
        for player_id in state.players
    }
    setattr(state, MEDICAL_STATE_ATTRIBUTE, normalized)
    setattr(state, MEDICAL_NORMALIZATION_MARKER_ATTRIBUTE, marker)
    return normalized


def injury_spec(injury_type: str) -> MedicalInjurySpec | None:
    return _CATALOG_BY_NAME.get(str(injury_type or "").replace("managed ", "", 1))


def _weighted_choice(rng: random.Random, specs: list[MedicalInjurySpec]) -> MedicalInjurySpec:
    expanded: list[MedicalInjurySpec] = []
    for spec in specs:
        expanded.extend([spec] * max(1, int(spec.weight)))
    return rng.choice(expanded)


def choose_medical_injury_outcome(
    rng: random.Random,
    *,
    existing_issue: bool,
    preferred_region: str = "",
) -> MedicalInjuryOutcome:
    roll = rng.random()
    if existing_issue:
        roll = min(1.0, roll + 0.10)
    # Availability calibration V1. The prior mix was too heavily
    # concentrated in zero-games-missed soreness events.
    if roll < 0.48:
        severity = "soreness"
    elif roll < 0.80:
        severity = "minor"
    elif roll < 0.965:
        severity = "moderate"
    else:
        severity = "major"

    candidates = [spec for spec in MEDICAL_INJURY_CATALOG if spec.severity == severity]
    if existing_issue and preferred_region:
        same_region = [spec for spec in candidates if spec.body_region == preferred_region]
        if same_region and rng.random() < 0.62:
            candidates = same_region
    spec = _weighted_choice(rng, candidates)
    days = rng.randint(spec.minimum_days, spec.maximum_days)

    if severity == "soreness":
        status = AvailabilityStatus.PROBABLE if rng.random() < 0.38 else AvailabilityStatus.QUESTIONABLE
    elif severity == "minor":
        status = AvailabilityStatus.DOUBTFUL if days >= 5 else AvailabilityStatus.QUESTIONABLE
    else:
        status = AvailabilityStatus.OUT

    performance = rng.uniform(spec.performance_low, spec.performance_high)
    aggravation = rng.uniform(spec.aggravation_low, spec.aggravation_high)
    minutes_limit = None
    if spec.minutes_low is not None and spec.minutes_high is not None:
        minutes_limit = rng.uniform(spec.minutes_low, spec.minutes_high)

    return MedicalInjuryOutcome(
        injury_type=spec.injury_type,
        body_region=spec.body_region,
        severity=spec.severity,
        grade=spec.grade,
        status=status,
        days=days,
        performance_multiplier=round(performance, 4),
        aggravation_risk=round(aggravation, 4),
        minutes_limit=round(minutes_limit, 1) if minutes_limit is not None else None,
    )


def team_games_between(
    state: SimulationLeagueState,
    team: str,
    start_day: int,
    end_day: int,
) -> int:
    count = sum(
        1
        for game in state.schedule.values()
        if int(start_day) < int(game.day_index) <= int(end_day)
        and team in {game.home_team, game.away_team}
    )
    if count:
        return count
    return max(0, int(round(max(0, end_day - start_day) / 2.0)))


def _history_recurrence_count(case: MedicalCaseState, body_region: str) -> int:
    return sum(
        1
        for row in case.history
        if str(row.get("body_region", "")) == body_region
    )


def register_medical_injury(
    state: SimulationLeagueState,
    player_id: str,
    outcome: MedicalInjuryOutcome,
    *,
    day_index: int,
    event_kind: str,
) -> dict[str, Any]:
    cases = ensure_medical_injury_v2_state(state)
    case = cases[player_id]
    previous_region = case.body_region
    prior_same_region = _history_recurrence_count(case, outcome.body_region)
    is_setback = event_kind == "setback"
    expected = int(day_index) + int(outcome.days)
    if is_setback:
        case.setback_count += 1
        case.last_setback_day = int(day_index)
    case.recurrence_count = max(case.recurrence_count, prior_same_region)
    case.injury_type = outcome.injury_type
    case.body_region = outcome.body_region
    case.severity = outcome.severity
    case.grade = outcome.grade
    case.onset_day = int(day_index)
    case.initial_expected_return_day = expected
    case.expected_return_day = expected
    case.rehab_phase = "acute"
    case.recovery_progress = 0.0
    case.return_ramp_games_remaining = 0
    case.games_since_return = 0
    case.last_event_kind = "setback" if is_setback else "injury"
    history_row = {
        "season_label": state.settings.season_label,
        "day_index": int(day_index),
        "injury_type": outcome.injury_type,
        "body_region": outcome.body_region,
        "severity": outcome.severity,
        "grade": outcome.grade,
        "event_kind": case.last_event_kind,
        "expected_return_day": expected,
    }
    case.history = tuple((*case.history, history_row)[-12:])
    case.recurrence_count = _history_recurrence_count(case, outcome.body_region) - 1
    return medical_event_metadata(state, player_id, day_index=day_index)


def _recovery_progress(case: MedicalCaseState, day_index: int) -> float:
    if not case.injury_type:
        return 100.0
    total = max(1, int(case.expected_return_day) - int(case.onset_day))
    elapsed = max(0, int(day_index) - int(case.onset_day))
    return round(clamp(elapsed / total * 100.0, 0.0, 100.0), 1)


def _return_limit(case: MedicalCaseState) -> float:
    if case.return_ramp_games_remaining >= 3:
        return 22.0
    if case.return_ramp_games_remaining == 2:
        return 26.0
    if case.return_ramp_games_remaining == 1:
        return 30.0
    return 34.0


def _clear_medical_case(
    state: SimulationLeagueState,
    player_id: str,
    *,
    day_index: int,
) -> None:
    case = ensure_medical_injury_v2_state(state)[player_id]
    injury = state.injuries[player_id]
    injury.status = AvailabilityStatus.HEALTHY
    injury.injury_type = ""
    injury.games_remaining = 0
    injury.performance_multiplier = 1.0
    injury.aggravation_risk = 0.0
    injury.notes = ""
    profile = getattr(state, "injury_fatigue_profiles", {}).get(player_id)
    if profile is not None:
        profile.expected_return_day = 0
        profile.injury_severity = ""
        profile.minutes_limit = None
        profile.status_reason = ""
    case.injury_type = ""
    case.body_region = ""
    case.severity = ""
    case.grade = ""
    case.onset_day = 0
    case.initial_expected_return_day = 0
    case.expected_return_day = 0
    case.rehab_phase = "cleared"
    case.recovery_progress = 100.0
    case.return_ramp_games_remaining = 0
    case.games_since_return = 0
    case.last_clear_day = int(day_index)
    case.last_event_kind = "cleared"


def prepare_medical_cases_for_game(
    state: SimulationLeagueState,
    *,
    day_index: int,
    teams: Iterable[str],
) -> tuple[str, ...]:
    cases = ensure_medical_injury_v2_state(state)
    team_set = {str(team).strip().upper() for team in teams}
    recovered: list[str] = []
    profiles = getattr(state, "injury_fatigue_profiles", {})

    for player_id, player in state.players.items():
        if player.team_abbreviation not in team_set:
            continue
        case = cases[player_id]
        injury = state.injuries[player_id]
        if not case.injury_type:
            continue

        progress = _recovery_progress(case, day_index)
        case.recovery_progress = progress
        profile = profiles.get(player_id)

        if progress < 55.0:
            case.rehab_phase = "acute"
            if case.severity in {"moderate", "major"}:
                injury.status = AvailabilityStatus.OUT
        elif progress < 82.0:
            case.rehab_phase = "rehab"
            if case.severity in {"moderate", "major"}:
                injury.status = AvailabilityStatus.OUT
        elif int(day_index) < int(case.expected_return_day):
            case.rehab_phase = "return_to_play"
            if case.severity in {"moderate", "major"}:
                injury.status = AvailabilityStatus.DOUBTFUL
                injury.performance_multiplier = min(float(injury.performance_multiplier or 1.0), 0.95)
                injury.aggravation_risk = max(float(injury.aggravation_risk or 0.0), 0.18)
                if profile is not None:
                    profile.minutes_limit = 24.0
            else:
                injury.status = AvailabilityStatus.QUESTIONABLE
                injury.performance_multiplier = min(float(injury.performance_multiplier or 1.0), 0.97)
                injury.aggravation_risk = max(float(injury.aggravation_risk or 0.0), 0.14)
                if profile is not None:
                    current_limit = getattr(profile, "minutes_limit", None)
                    profile.minutes_limit = min(float(current_limit or 30.0), 30.0)
        else:
            if case.return_ramp_games_remaining <= 0 and case.games_since_return <= 0:
                case.return_ramp_games_remaining = 3 if case.severity in {"moderate", "major"} else 2
            case.rehab_phase = "return_ramp"
            case.recovery_progress = 100.0
            injury.status = (
                AvailabilityStatus.QUESTIONABLE
                if case.return_ramp_games_remaining >= 2
                else AvailabilityStatus.PROBABLE
            )
            injury.performance_multiplier = 0.94 if case.return_ramp_games_remaining >= 2 else 0.97
            injury.aggravation_risk = max(float(injury.aggravation_risk or 0.0), 0.20 if case.return_ramp_games_remaining >= 2 else 0.14)
            limit = _return_limit(case)
            if profile is not None:
                profile.minutes_limit = limit
                profile.expected_return_day = int(case.expected_return_day)
                profile.injury_severity = case.severity
                profile.status_reason = (
                    f"{case.injury_type} return-to-play ramp: {limit:.0f}-minute medical cap, "
                    f"{case.return_ramp_games_remaining} ramp game(s) remaining."
                )
            injury.notes = (
                f"{case.injury_type.title()} return-to-play ramp. "
                f"Medical cap {limit:.0f} minutes; recurrence risk remains elevated."
            )

        remaining = team_games_between(
            state,
            player.team_abbreviation,
            int(day_index),
            int(case.expected_return_day),
        )
        injury.games_remaining = int(remaining)
        if profile is not None and case.rehab_phase not in {"return_ramp", "cleared"}:
            profile.expected_return_day = int(case.expected_return_day)
            profile.injury_severity = case.severity
            profile.status_reason = injury.notes or case.injury_type

    return tuple(recovered)


def medical_case_is_active(state: SimulationLeagueState, player_id: str) -> bool:
    case = ensure_medical_injury_v2_state(state)[player_id]
    return bool(case.injury_type and case.rehab_phase not in {"healthy", "cleared"})


def advance_medical_case_after_appearance(
    state: SimulationLeagueState,
    player_id: str,
    *,
    day_index: int,
) -> bool:
    case = ensure_medical_injury_v2_state(state)[player_id]
    if case.rehab_phase != "return_ramp" or case.return_ramp_games_remaining <= 0:
        return False
    case.games_since_return += 1
    case.return_ramp_games_remaining = max(0, case.return_ramp_games_remaining - 1)
    if case.return_ramp_games_remaining <= 0:
        _clear_medical_case(state, player_id, day_index=day_index)
        return True
    injury = state.injuries[player_id]
    injury.status = AvailabilityStatus.PROBABLE if case.return_ramp_games_remaining == 1 else AvailabilityStatus.QUESTIONABLE
    injury.performance_multiplier = 0.97 if case.return_ramp_games_remaining == 1 else 0.95
    injury.aggravation_risk = 0.14 if case.return_ramp_games_remaining == 1 else 0.18
    profile = getattr(state, "injury_fatigue_profiles", {}).get(player_id)
    if profile is not None:
        profile.minutes_limit = _return_limit(case)
    return False


def medical_risk_multiplier(state: SimulationLeagueState, player_id: str) -> float:
    case = ensure_medical_injury_v2_state(state)[player_id]
    history_burden = min(0.20, len(case.history) * 0.025)
    active = 0.0
    if case.rehab_phase == "return_to_play":
        active = 0.22
    elif case.rehab_phase == "return_ramp":
        active = 0.30 if case.return_ramp_games_remaining >= 2 else 0.16
    recurrence = min(0.20, max(0, case.recurrence_count) * 0.08)
    return round(1.0 + history_burden + active + recurrence, 4)


def medical_reinjury_probability(state: SimulationLeagueState, player_id: str) -> float:
    case = ensure_medical_injury_v2_state(state)[player_id]
    injury = state.injuries[player_id]
    if not case.injury_type:
        return 0.0
    base = float(injury.aggravation_risk or 0.0)
    if case.rehab_phase == "return_ramp":
        base += 0.08 if case.return_ramp_games_remaining >= 2 else 0.04
    base += min(0.12, case.recurrence_count * 0.04)
    return round(clamp(base, 0.0, 0.65), 3)


def medical_case_snapshot(
    state: SimulationLeagueState,
    player_id: str,
    *,
    day_index: int | None = None,
) -> dict[str, Any]:
    case = ensure_medical_injury_v2_state(state)[player_id]
    resolved_day = int(state.current_day_index if day_index is None else day_index)
    progress = _recovery_progress(case, resolved_day) if case.injury_type else 100.0
    return {
        "medical_version": MEDICAL_INJURY_V2_VERSION,
        "medical_phase": case.rehab_phase.replace("_", " ").title(),
        "recovery_progress": progress,
        "body_region": case.body_region.title() if case.body_region else "—",
        "injury_grade": case.grade or "—",
        "onset_day": case.onset_day or None,
        "expected_return_day": case.expected_return_day or None,
        "return_ramp_games": case.return_ramp_games_remaining,
        "games_since_return": case.games_since_return,
        "recurrence_count": case.recurrence_count,
        "setback_count": case.setback_count,
        "reinjury_risk": round(medical_reinjury_probability(state, player_id) * 100.0, 1),
    }


def medical_event_metadata(
    state: SimulationLeagueState,
    player_id: str,
    *,
    day_index: int,
) -> dict[str, Any]:
    case = ensure_medical_injury_v2_state(state)[player_id]
    return {
        "medical_version": MEDICAL_INJURY_V2_VERSION,
        "event_kind": case.last_event_kind or "injury",
        "body_region": case.body_region,
        "injury_grade": case.grade,
        "rehab_phase": case.rehab_phase,
        "recovery_progress": _recovery_progress(case, day_index),
        "recurrence_count": case.recurrence_count,
        "setback_count": case.setback_count,
        "return_ramp_games": case.return_ramp_games_remaining,
    }


def run_self_test() -> dict[str, Any]:
    catalog_names = [spec.injury_type for spec in MEDICAL_INJURY_CATALOG]
    catalog_regions = {spec.body_region for spec in MEDICAL_INJURY_CATALOG}
    rng = random.Random(20260810)
    outcomes = [
        choose_medical_injury_outcome(rng, existing_issue=False)
        for _ in range(120)
    ]
    checks = {
        "version_is_current": MEDICAL_INJURY_V2_VERSION.endswith("2026-08-10"),
        "catalog_has_unique_names": len(catalog_names) == len(set(catalog_names)),
        "catalog_covers_major_regions": {"ankle", "knee", "hamstring", "back", "calf", "shoulder"}.issubset(catalog_regions),
        "catalog_has_four_severity_bands": {spec.severity for spec in MEDICAL_INJURY_CATALOG} == {"soreness", "minor", "moderate", "major"},
        "outcomes_are_bounded": all(1 <= row.days <= 220 and 0.0 <= row.aggravation_risk <= 1.0 for row in outcomes),
        "major_injuries_are_unavailable": all(row.status == AvailabilityStatus.OUT for row in outcomes if row.severity == "major"),
        "moderate_injuries_are_unavailable": all(row.status == AvailabilityStatus.OUT for row in outcomes if row.severity == "moderate"),
    }
    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "script": MEDICAL_INJURY_V2_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "catalog_size": len(MEDICAL_INJURY_CATALOG),
        "sample_outcomes": [asdict(row) for row in outcomes[:8]],
        "passed": not failed,
    }
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    SELF_TEST_REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    if failed:
        raise AssertionError("Medical/Injury V2 self-test failed: " + ", ".join(failed))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(run_self_test(), indent=2, default=str))
        print("\nMEDICAL / INJURY V2 SELF-TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
