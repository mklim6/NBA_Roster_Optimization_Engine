from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import load_runtime_data  # noqa: E402
from mutable_league_state_v1 import create_league_state  # noqa: E402
from simulation_injury_fatigue_v1 import (  # noqa: E402
    HEALTH_STATE_ATTRIBUTE,
    InjuryFatigueConfig,
    ensure_injury_fatigue_state,
    health_events,
    player_health_report_rows,
)
from simulation_league_state_v1 import (  # noqa: E402
    AvailabilityStatus,
    SimulationLeagueState,
    create_simulation_league_state,
)
from state_runtime_adapter_v1 import build_state_runtime  # noqa: E402


LEAGUE_HEALTH_AUDIT_VERSION = (
    "league-health-audit-v1.1-2026-08-09"
)
SELF_TEST_REPORT = (
    OUTPUTS / "league_health_audit_v1_self_test.json"
)
MILESTONES = (10, 20, 40, 82)


@dataclass(frozen=True)
class LeagueHealthAudit:
    version: str
    season_label: str
    current_day: int
    average_team_games: float
    maximum_team_games: int
    player_games: int
    injury_events: int
    expected_base_events: float
    event_frequency_ratio: float | None
    active_injuries: int
    unavailable_players: int
    limited_players: int
    games_missed_recorded: int
    back_to_back_events: int
    major_events: int
    average_fatigue: float
    maximum_fatigue: float
    heavy_workload_players: int
    heavy_workload_low_fatigue_players: int
    heavy_workload_low_fatigue_share: float
    injury_frequency_status: str
    fatigue_calibration_status: str
    overall_status: str
    explanation: str


def _status_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").strip().lower()


def _season_events(
    state: SimulationLeagueState,
) -> list[dict[str, Any]]:
    season = state.settings.season_label
    return [
        dict(event)
        for event in health_events(state)
        if str(event.get("season_label", "")) == season
    ]


def _team_games(state: SimulationLeagueState) -> list[int]:
    return [
        int(getattr(standing, "games_played", 0) or 0)
        for standing in state.standings.values()
    ]


def _fatigue_snapshot(
    state: SimulationLeagueState,
) -> tuple[list[float], int, int]:
    ensure_injury_fatigue_state(state)
    profiles = getattr(state, HEALTH_STATE_ATTRIBUTE)
    fatigue_values: list[float] = []
    heavy = 0
    heavy_low = 0

    for player_id, profile in profiles.items():
        fatigue = float(getattr(profile, "fatigue", 0.0) or 0.0)
        fatigue_values.append(fatigue)
        recent = tuple(
            float(value or 0.0)
            for value in (
                getattr(profile, "recent_minutes", ()) or ()
            )[-4:]
        )
        recent_total = sum(recent)
        if recent_total >= 60.0:
            heavy += 1
            if fatigue < 2.0:
                heavy_low += 1

    return fatigue_values, heavy, heavy_low


def _injury_frequency_status(
    *,
    average_team_games: float,
    observed: int,
    expected: float,
) -> tuple[str, float | None]:
    ratio = (
        observed / expected
        if expected > 1e-9
        else None
    )

    if average_team_games < 5.0:
        return "insufficient_sample", ratio
    if average_team_games >= 10.0 and observed == 0:
        return "too_quiet", ratio
    if expected >= 3.0 and ratio is not None and ratio < 0.35:
        return "too_quiet", ratio
    if ratio is not None and ratio > 4.0:
        return "too_high", ratio
    return "plausible", ratio


def _fatigue_status(
    *,
    average_team_games: float,
    heavy: int,
    heavy_low: int,
    maximum_fatigue: float,
) -> tuple[str, float]:
    share = heavy_low / heavy if heavy else 0.0

    if average_team_games < 5.0 or heavy < 20:
        return "insufficient_sample", share
    if share >= 0.70 and maximum_fatigue < 8.0:
        return "recovery_too_aggressive", share
    if maximum_fatigue > 92.0:
        return "fatigue_too_high", share
    return "plausible", share


def league_health_audit(
    state: SimulationLeagueState,
) -> LeagueHealthAudit:
    ensure_injury_fatigue_state(state)
    events = _season_events(state)
    team_games = _team_games(state)
    average_team_games = (
        mean(team_games) if team_games else 0.0
    )
    maximum_team_games = max(team_games, default=0)
    player_games = sum(
        int(getattr(total, "games_played", 0) or 0)
        for total in state.player_season_totals.values()
    )

    config = InjuryFatigueConfig()
    expected_base_events = (
        player_games * config.base_player_game_injury_risk
    )
    frequency_status, frequency_ratio = (
        _injury_frequency_status(
            average_team_games=average_team_games,
            observed=len(events),
            expected=expected_base_events,
        )
    )

    active_rows: list[dict[str, Any]] = []
    unavailable = 0
    limited = 0
    for player_id, injury in state.injuries.items():
        status = _status_value(injury.status)
        if status != AvailabilityStatus.HEALTHY.value:
            active_rows.append(
                {
                    "player_id": player_id,
                    "status": status,
                }
            )
        if status in {
            AvailabilityStatus.OUT.value,
            AvailabilityStatus.DOUBTFUL.value,
        }:
            unavailable += 1
        elif status in {
            AvailabilityStatus.PROBABLE.value,
            AvailabilityStatus.QUESTIONABLE.value,
            AvailabilityStatus.DAY_TO_DAY.value,
        }:
            limited += 1

    profiles = getattr(state, HEALTH_STATE_ATTRIBUTE)
    games_missed = sum(
        int(getattr(profile, "season_games_missed", 0) or 0)
        for profile in profiles.values()
    )
    fatigue_values, heavy, heavy_low = _fatigue_snapshot(state)
    average_fatigue = (
        mean(fatigue_values) if fatigue_values else 0.0
    )
    maximum_fatigue = max(fatigue_values, default=0.0)
    fatigue_status, low_share = _fatigue_status(
        average_team_games=average_team_games,
        heavy=heavy,
        heavy_low=heavy_low,
        maximum_fatigue=maximum_fatigue,
    )

    if frequency_status == "too_high" or fatigue_status == "fatigue_too_high":
        overall_status = "needs_reduction"
    elif frequency_status == "too_quiet" or fatigue_status == "recovery_too_aggressive":
        overall_status = "needs_more_health_pressure"
    elif "insufficient_sample" in {frequency_status, fatigue_status}:
        overall_status = "monitoring"
    else:
        overall_status = "plausible"

    explanation_parts: list[str] = []
    if frequency_status == "too_quiet":
        explanation_parts.append(
            "Injury events are materially below the engine's own base-rate expectation."
        )
    elif frequency_status == "too_high":
        explanation_parts.append(
            "Injury events are far above the engine's base-rate expectation."
        )
    elif frequency_status == "plausible":
        explanation_parts.append(
            "Injury-event frequency is within a broad internal calibration band."
        )
    else:
        explanation_parts.append(
            "The season is still too early for a stable injury-frequency judgment."
        )

    if fatigue_status == "recovery_too_aggressive":
        explanation_parts.append(
            "Most high-workload players are returning to near-zero fatigue, so recovery is likely too aggressive."
        )
    elif fatigue_status == "fatigue_too_high":
        explanation_parts.append(
            "At least one player is carrying extreme fatigue and may need a lower accumulation rate."
        )
    elif fatigue_status == "plausible":
        explanation_parts.append(
            "The current fatigue distribution is not triggering the broad calibration guardrails."
        )

    return LeagueHealthAudit(
        version=LEAGUE_HEALTH_AUDIT_VERSION,
        season_label=state.settings.season_label,
        current_day=int(state.current_day_index),
        average_team_games=round(average_team_games, 2),
        maximum_team_games=maximum_team_games,
        player_games=player_games,
        injury_events=len(events),
        expected_base_events=round(expected_base_events, 2),
        event_frequency_ratio=(
            round(frequency_ratio, 3)
            if frequency_ratio is not None
            else None
        ),
        active_injuries=len(active_rows),
        unavailable_players=unavailable,
        limited_players=limited,
        games_missed_recorded=games_missed,
        back_to_back_events=sum(
            bool(event.get("back_to_back"))
            for event in events
        ),
        major_events=sum(
            str(event.get("severity", "")).lower() == "major"
            for event in events
        ),
        average_fatigue=round(average_fatigue, 2),
        maximum_fatigue=round(maximum_fatigue, 2),
        heavy_workload_players=heavy,
        heavy_workload_low_fatigue_players=heavy_low,
        heavy_workload_low_fatigue_share=round(low_share, 3),
        injury_frequency_status=frequency_status,
        fatigue_calibration_status=fatigue_status,
        overall_status=overall_status,
        explanation=" ".join(explanation_parts),
    )


def active_injury_rows(
    state: SimulationLeagueState,
) -> list[dict[str, Any]]:
    ensure_injury_fatigue_state(state)
    profiles = getattr(state, HEALTH_STATE_ATTRIBUTE)
    rows: list[dict[str, Any]] = []

    for player_id, injury in state.injuries.items():
        status = _status_value(injury.status)
        if status == AvailabilityStatus.HEALTHY.value:
            continue
        player = state.players[player_id]
        profile = profiles[player_id]
        rows.append(
            {
                "player_id": player_id,
                "player": player.player_name,
                "team": player.team_abbreviation,
                "position": player.position,
                "age": player.age,
                "status": status.replace("_", " ").title(),
                "injury": injury.injury_type or "Undisclosed",
                "games_remaining": int(injury.games_remaining or 0),
                "expected_return_day": int(
                    getattr(profile, "expected_return_day", 0) or 0
                ),
                "games_missed": int(
                    getattr(profile, "season_games_missed", 0) or 0
                ),
                "fatigue": round(float(getattr(profile, "fatigue", 0.0) or 0.0), 1),
            }
        )

    severity_order = {
        "Out": 0,
        "Doubtful": 1,
        "Questionable": 2,
        "Day To Day": 3,
        "Probable": 4,
    }
    rows.sort(
        key=lambda row: (
            severity_order.get(row["status"], 9),
            -row["games_remaining"],
            row["team"],
            row["player"],
        )
    )
    return rows


def team_health_rows(
    state: SimulationLeagueState,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for team in sorted(state.teams):
        player_rows = player_health_report_rows(state, team)
        rows.append(
            {
                "team": team,
                "games": int(state.standings[team].games_played),
                "active_injuries": sum(row["status"] != "Healthy" for row in player_rows),
                "unavailable": sum(row["status"] in {"Out", "Doubtful"} for row in player_rows),
                "elevated_high_risk": sum(row["risk"] in {"Elevated", "High"} for row in player_rows),
                "average_fatigue": round(
                    mean(float(row["current_fatigue"]) for row in player_rows),
                    1,
                ) if player_rows else 0.0,
                "maximum_fatigue": round(
                    max(
                        (float(row["current_fatigue"]) for row in player_rows),
                        default=0.0,
                    ),
                    1,
                ),
                "projected_average_fatigue": round(
                    mean(float(row["projected_fatigue"]) for row in player_rows),
                    1,
                ) if player_rows else 0.0,
                "projected_maximum_fatigue": round(
                    max(
                        (float(row["projected_fatigue"]) for row in player_rows),
                        default=0.0,
                    ),
                    1,
                ),
                "projection_day": (
                    int(player_rows[0]["fatigue_projection_day"])
                    if player_rows
                    else int(state.current_day_index)
                ),
            }
        )
    rows.sort(
        key=lambda row: (
            -row["unavailable"],
            -row["active_injuries"],
            -row["maximum_fatigue"],
            row["team"],
        )
    )
    return rows


def reached_health_milestones(
    audit: LeagueHealthAudit,
) -> tuple[int, ...]:
    return tuple(
        milestone
        for milestone in MILESTONES
        if audit.average_team_games >= milestone
    )


def run_self_test() -> dict[str, Any]:
    runtime_base = load_runtime_data()
    trade_state = create_league_state(runtime_base)
    runtime = build_state_runtime(runtime_base, trade_state)
    state = create_simulation_league_state(runtime, trade_state)
    profiles = ensure_injury_fatigue_state(state)

    for standing in state.standings.values():
        standing.games_played = 20
        standing.wins = 10
        standing.losses = 10

    for team in state.teams.values():
        for player_id in team.rotation.rotation_player_ids:
            state.player_season_totals[player_id].games_played = 20
            profiles[player_id].recent_minutes = (30.0, 31.0, 29.0, 32.0)
            profiles[player_id].fatigue = 0.5

    quiet = league_health_audit(state)

    sample_id = next(iter(state.players))
    sample_player = state.players[sample_id]
    state.injuries[sample_id].status = AvailabilityStatus.OUT
    state.injuries[sample_id].injury_type = "ankle sprain"
    state.injuries[sample_id].games_remaining = 5
    events = health_events(state)
    for index in range(10):
        events.append(
            {
                "season_label": state.settings.season_label,
                "game_id": f"TEST-{index}",
                "day_index": index + 1,
                "player_id": sample_id,
                "player_name": sample_player.player_name,
                "team": sample_player.team_abbreviation,
                "injury_type": "ankle sprain",
                "severity": "minor",
                "status": "out",
                "estimated_games_missed": 2,
                "back_to_back": index % 3 == 0,
            }
        )
    plausible = league_health_audit(state)

    checks = {
        "version_is_current": quiet.version == LEAGUE_HEALTH_AUDIT_VERSION,
        "twenty_game_zero_event_sample_is_flagged": quiet.injury_frequency_status == "too_quiet",
        "aggressive_recovery_is_detected": quiet.fatigue_calibration_status == "recovery_too_aggressive",
        "active_injury_is_counted": plausible.active_injuries == 1,
        "injury_events_are_counted": plausible.injury_events == 10,
        "milestones_reach_10_and_20": reached_health_milestones(plausible) == (10, 20),
        "team_rows_cover_30_teams": len(team_health_rows(state)) == 30,
        "active_injury_rows_include_sample": any(row["player_id"] == sample_id for row in active_injury_rows(state)),
    }
    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "script": LEAGUE_HEALTH_AUDIT_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "quiet_audit": asdict(quiet),
        "plausible_audit": asdict(plausible),
        "passed": not failed,
    }
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    SELF_TEST_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if failed:
        raise AssertionError(
            "League health audit self-test failed: " + ", ".join(failed)
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(run_self_test(), indent=2))
        print("\nLEAGUE HEALTH AUDIT V1 SELF-TEST PASSED")
        return 0
    raise SystemExit("Use --self-test.")


if __name__ == "__main__":
    raise SystemExit(main())
