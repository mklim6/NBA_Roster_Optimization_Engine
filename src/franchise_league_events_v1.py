from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import load_runtime_data  # noqa: E402
from league_health_audit_v1 import (  # noqa: E402
    league_health_audit,
    reached_health_milestones,
)
from mutable_league_state_v1 import create_league_state  # noqa: E402
from simulation_injury_fatigue_v1 import (  # noqa: E402
    HEALTH_STATE_ATTRIBUTE,
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


FRANCHISE_EVENT_VERSION = (
    "franchise-league-events-v1-2026-08-09"
)
EVENTS_ATTRIBUTE = "franchise_league_events_v1"
EVENT_SETTINGS_ATTRIBUTE = "franchise_event_settings_v1"
EVENT_SYNC_MARKER_ATTRIBUTE = "_franchise_event_sync_marker_v1"
SELF_TEST_REPORT = OUTPUTS / "franchise_league_events_v1_self_test.json"

DEFAULT_EVENT_SETTINGS = {
    "pause_on_controlled_injury": True,
    "pause_on_high_workload": False,
    "pause_on_health_calibration": False,
    "show_ai_injuries": True,
    "show_high_workload_alerts": True,
    "show_health_milestones": True,
}

VALID_EVENT_STATUSES = {"unread", "read", "resolved", "expired"}


def _clean_team(value: Any) -> str:
    return str(value or "").strip().upper()


def _event_id(*parts: Any) -> str:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return "EVT_" + hashlib.sha256(payload).hexdigest()[:18].upper()


def ensure_event_state(
    state: SimulationLeagueState,
) -> tuple[list[dict[str, Any]], dict[str, bool]]:
    events = getattr(state, EVENTS_ATTRIBUTE, None)
    if not isinstance(events, list):
        events = []
    normalized_events: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw in events:
        if not isinstance(raw, dict):
            continue
        event = dict(raw)
        event_id = str(event.get("event_id", "")).strip()
        if not event_id:
            event_id = _event_id(
                event.get("season_label"),
                event.get("category"),
                event.get("title"),
                event.get("created_day"),
                len(normalized_events),
            )
            event["event_id"] = event_id
        if event_id in seen:
            continue
        seen.add(event_id)
        status = str(event.get("status", "unread")).lower()
        event["status"] = status if status in VALID_EVENT_STATUSES else "unread"
        event["blocking"] = bool(event.get("blocking", False))
        event["severity"] = str(event.get("severity", "info")).lower()
        event["team"] = _clean_team(event.get("team"))
        normalized_events.append(event)

    settings = getattr(state, EVENT_SETTINGS_ATTRIBUTE, None)
    if not isinstance(settings, dict):
        settings = {}
    normalized_settings = {
        key: bool(settings.get(key, default))
        for key, default in DEFAULT_EVENT_SETTINGS.items()
    }

    if isinstance(events, list):
        events[:] = normalized_events
        normalized_events = events
    setattr(state, EVENTS_ATTRIBUTE, normalized_events)
    setattr(state, EVENT_SETTINGS_ATTRIBUTE, normalized_settings)
    return normalized_events, normalized_settings


def event_settings(state: SimulationLeagueState) -> dict[str, bool]:
    return ensure_event_state(state)[1]


def update_event_settings(
    state: SimulationLeagueState,
    **changes: bool,
) -> dict[str, bool]:
    _, settings = ensure_event_state(state)
    for key, value in changes.items():
        if key in DEFAULT_EVENT_SETTINGS:
            settings[key] = bool(value)
    return dict(settings)


def _append_event(
    state: SimulationLeagueState,
    *,
    dedupe_key: str,
    category: str,
    event_type: str,
    severity: str,
    title: str,
    detail: str,
    action_section: str,
    blocking: bool,
    team: str = "",
    player_id: str = "",
    created_day: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    events, _ = ensure_event_state(state)
    season = state.settings.season_label
    event_id = _event_id(season, dedupe_key)
    if any(event.get("event_id") == event_id for event in events):
        return None

    event = {
        "version": FRANCHISE_EVENT_VERSION,
        "event_id": event_id,
        "dedupe_key": dedupe_key,
        "season_label": season,
        "category": category,
        "event_type": event_type,
        "severity": severity,
        "title": title,
        "detail": detail,
        "action_section": action_section,
        "blocking": bool(blocking),
        "status": "unread",
        "team": _clean_team(team),
        "player_id": str(player_id or ""),
        "created_day": int(
            state.current_day_index if created_day is None else created_day
        ),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "resolved_at_utc": "",
        "metadata": copy.deepcopy(metadata or {}),
    }
    events.append(event)
    return event


def _injury_events(
    state: SimulationLeagueState,
    controlled: set[str],
    settings: dict[str, bool],
) -> int:
    created = 0
    for injury_event in health_events(state):
        if str(injury_event.get("season_label", "")) != state.settings.season_label:
            continue
        team = _clean_team(injury_event.get("team"))
        if team not in controlled and not settings["show_ai_injuries"]:
            continue
        player_id = str(injury_event.get("player_id", ""))
        player_name = str(injury_event.get("player_name", player_id))
        severity = str(injury_event.get("severity", "minor")).lower()
        status = str(injury_event.get("status", "out")).replace("_", " ").title()
        injury_type = str(injury_event.get("injury_type", "injury"))
        estimated = int(injury_event.get("estimated_games_missed", 0) or 0)
        event_kind = str(injury_event.get("event_kind", "injury") or "injury").lower()
        body_region = str(injury_event.get("body_region", "") or "")
        injury_grade = str(injury_event.get("injury_grade", "") or "")
        recurrence_count = int(injury_event.get("recurrence_count", 0) or 0)
        medical_context = ""
        if body_region or injury_grade:
            descriptors = [value for value in (body_region.title(), injury_grade) if value]
            medical_context = " Medical: " + ", ".join(descriptors) + "."
        if recurrence_count > 0:
            medical_context += f" Same-region recurrence count: {recurrence_count}."
        controlled_event = team in controlled
        event = _append_event(
            state,
            dedupe_key=(
                "injury|"
                + str(injury_event.get("game_id", ""))
                + "|"
                + player_id
            ),
            category="Medical",
            event_type="player_injury",
            severity=(
                "critical" if severity == "major" else "warning"
            ),
            title=(
                f"{player_name}: {injury_type}"
                + (" setback" if event_kind == "setback" else "")
            ),
            detail=(
                f"{team} lists {player_name} as {status}. "
                f"Estimated absence: {estimated} game(s)."
                f"{medical_context}"
            ),
            action_section="Inbox & League Health",
            blocking=(
                controlled_event
                and settings["pause_on_controlled_injury"]
            ),
            team=team,
            player_id=player_id,
            created_day=int(injury_event.get("day_index", state.current_day_index) or 0),
            metadata=dict(injury_event),
        )
        created += event is not None
    return created


def _active_injury_backfill(
    state: SimulationLeagueState,
    controlled: set[str],
    settings: dict[str, bool],
) -> int:
    created = 0
    ensure_injury_fatigue_state(state)
    profiles = getattr(state, HEALTH_STATE_ATTRIBUTE)
    history_pairs = {
        (
            str(event.get("player_id", "")),
            str(event.get("injury_type", "")),
        )
        for event in health_events(state)
        if str(event.get("season_label", ""))
        == state.settings.season_label
    }
    for player_id, injury in state.injuries.items():
        status = str(getattr(injury.status, "value", injury.status)).lower()
        if status == AvailabilityStatus.HEALTHY.value:
            continue
        if (
            player_id,
            str(injury.injury_type),
        ) in history_pairs:
            continue
        player = state.players[player_id]
        team = _clean_team(player.team_abbreviation)
        if team not in controlled and not settings["show_ai_injuries"]:
            continue
        profile = profiles[player_id]
        event = _append_event(
            state,
            dedupe_key=(
                "active-injury|"
                + player_id
                + "|"
                + str(injury.injury_type)
                + "|"
                + str(getattr(profile, "expected_return_day", 0))
            ),
            category="Medical",
            event_type="active_injury_status",
            severity="warning",
            title=f"{player.player_name} remains unavailable",
            detail=(
                f"{team}: {str(injury.injury_type or 'Undisclosed injury')}. "
                f"Status {status.replace('_', ' ').title()}, "
                f"{int(injury.games_remaining or 0)} game(s) remaining."
            ),
            action_section="Inbox & League Health",
            blocking=(
                team in controlled
                and settings["pause_on_controlled_injury"]
            ),
            team=team,
            player_id=player_id,
            metadata={
                "status": status,
                "injury_type": injury.injury_type,
                "games_remaining": injury.games_remaining,
            },
        )
        created += event is not None
    return created


def _workload_events(
    state: SimulationLeagueState,
    controlled: set[str],
    settings: dict[str, bool],
) -> int:
    if not settings["show_high_workload_alerts"]:
        return 0
    created = 0
    for team in sorted(controlled):
        if team not in state.teams:
            continue
        for row in player_health_report_rows(state, team):
            if row["risk"] not in {"Elevated", "High"}:
                continue
            player_id = str(row["player_id"])
            profile = getattr(state, HEALTH_STATE_ATTRIBUTE)[player_id]
            workload_anchor = (
                getattr(profile, "last_updated_game_id", "")
                or f"day-{state.current_day_index}"
            )
            event = _append_event(
                state,
                dedupe_key=f"workload|{player_id}|{workload_anchor}|{row['risk']}",
                category="Performance",
                event_type="high_workload",
                severity="warning" if row["risk"] == "High" else "info",
                title=f"Workload review: {row['player']}",
                detail=(
                    f"{row['risk']} next-game risk, {row['fatigue']:.1f}/100 fatigue, "
                    f"{row['recent_minutes']:.1f} minutes across the recent window. "
                    f"{row['explanation']}"
                ),
                action_section="Team Management",
                blocking=settings["pause_on_high_workload"],
                team=team,
                player_id=player_id,
                metadata=dict(row),
            )
            created += event is not None
    return created


def _health_milestone_events(
    state: SimulationLeagueState,
    settings: dict[str, bool],
) -> int:
    if not settings["show_health_milestones"]:
        return 0
    audit = league_health_audit(state)
    created = 0
    for milestone in reached_health_milestones(audit):
        event = _append_event(
            state,
            dedupe_key=f"health-milestone|{milestone}",
            category="League Health",
            event_type="health_calibration_milestone",
            severity=(
                "warning"
                if audit.overall_status in {
                    "needs_more_health_pressure",
                    "needs_reduction",
                }
                else "info"
            ),
            title=f"League health audit: {milestone}-game checkpoint",
            detail=(
                f"{audit.injury_events} injury event(s), {audit.active_injuries} active injury case(s), "
                f"{audit.maximum_fatigue:.1f}/100 maximum fatigue. {audit.explanation}"
            ),
            action_section="Inbox & League Health",
            blocking=settings["pause_on_health_calibration"],
            metadata=asdict_safe(audit),
        )
        created += event is not None
    return created


def asdict_safe(value: Any) -> dict[str, Any]:
    fields = getattr(value, "__dataclass_fields__", None)
    if fields:
        return {name: copy.deepcopy(getattr(value, name)) for name in fields}
    if isinstance(value, dict):
        return copy.deepcopy(value)
    return {"value": copy.deepcopy(value)}


def synchronize_franchise_events(
    state: SimulationLeagueState,
    *,
    controlled_teams: Sequence[str] = (),
) -> dict[str, Any]:
    events, settings = ensure_event_state(state)
    controlled = {
        _clean_team(team)
        for team in controlled_teams
        if _clean_team(team) in state.teams
    }
    before = len(events)
    created = {
        "injury": _injury_events(state, controlled, settings),
        "active_injury": _active_injury_backfill(state, controlled, settings),
        "workload": _workload_events(state, controlled, settings),
        "health_milestone": _health_milestone_events(state, settings),
    }
    marker = (
        FRANCHISE_EVENT_VERSION,
        state.settings.season_label,
        int(state.current_day_index),
        len(state.completed_games),
        len(health_events(state)),
        len(events),
    )
    setattr(state, EVENT_SYNC_MARKER_ATTRIBUTE, marker)
    return {
        "version": FRANCHISE_EVENT_VERSION,
        "created": sum(created.values()),
        "created_by_type": created,
        "events_before": before,
        "events_after": len(events),
        "unread": len(unread_events(state)),
        "blocking": len(blocking_events(state)),
        "marker": marker,
    }


def franchise_events(
    state: SimulationLeagueState,
    *,
    statuses: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    events, _ = ensure_event_state(state)
    allowed = (
        {str(status).lower() for status in statuses}
        if statuses is not None
        else None
    )
    selected = [
        event
        for event in events
        if allowed is None or event["status"] in allowed
    ]
    return sorted(
        selected,
        key=lambda event: (
            event["status"] not in {"unread", "read"},
            not bool(event["blocking"]),
            -int(event.get("created_day", 0) or 0),
            event["event_id"],
        ),
    )


def unread_events(state: SimulationLeagueState) -> list[dict[str, Any]]:
    return franchise_events(state, statuses={"unread"})


def blocking_events(state: SimulationLeagueState) -> list[dict[str, Any]]:
    return [
        event
        for event in franchise_events(state, statuses={"unread", "read"})
        if bool(event.get("blocking"))
    ]


def mark_event_read(
    state: SimulationLeagueState,
    event_id: str,
) -> bool:
    events, _ = ensure_event_state(state)
    for event in events:
        if event["event_id"] == event_id:
            if event["status"] == "unread":
                event["status"] = "read"
            return True
    return False


def resolve_event(
    state: SimulationLeagueState,
    event_id: str,
) -> bool:
    events, _ = ensure_event_state(state)
    for event in events:
        if event["event_id"] == event_id:
            event["status"] = "resolved"
            event["resolved_at_utc"] = datetime.now(timezone.utc).isoformat()
            return True
    return False


def resolve_all_nonblocking(state: SimulationLeagueState) -> int:
    count = 0
    for event in franchise_events(state, statuses={"unread", "read"}):
        if not bool(event.get("blocking")) and resolve_event(state, event["event_id"]):
            count += 1
    return count


def event_inbox_rows(state: SimulationLeagueState) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in franchise_events(state):
        rows.append(
            {
                "event_id": event["event_id"],
                "status": event["status"].title(),
                "blocking": "Yes" if event["blocking"] else "No",
                "day": event["created_day"],
                "category": event["category"],
                "severity": event["severity"].title(),
                "team": event["team"] or "League",
                "title": event["title"],
                "detail": event["detail"],
                "destination": event["action_section"],
            }
        )
    return rows


def run_self_test() -> dict[str, Any]:
    runtime_base = load_runtime_data()
    trade_state = create_league_state(runtime_base)
    runtime = build_state_runtime(runtime_base, trade_state)
    state = create_simulation_league_state(runtime, trade_state)
    profiles = ensure_injury_fatigue_state(state)
    controlled = ("CHI",)

    chi_player = next(iter(state.teams["CHI"].rotation.rotation_player_ids))
    player = state.players[chi_player]
    state.injuries[chi_player].status = AvailabilityStatus.OUT
    state.injuries[chi_player].injury_type = "ankle sprain"
    state.injuries[chi_player].games_remaining = 4
    profiles[chi_player].expected_return_day = 9
    health_events(state).append(
        {
            "season_label": state.settings.season_label,
            "game_id": "TEST-GAME",
            "day_index": 4,
            "player_id": chi_player,
            "player_name": player.player_name,
            "team": "CHI",
            "injury_type": "ankle sprain",
            "severity": "minor",
            "status": "out",
            "estimated_games_missed": 4,
            "back_to_back": False,
        }
    )

    first = synchronize_franchise_events(state, controlled_teams=controlled)
    second = synchronize_franchise_events(state, controlled_teams=controlled)
    blocking = blocking_events(state)
    selected = blocking[0]
    read_ok = mark_event_read(state, selected["event_id"])
    still_blocking_after_read = bool(blocking_events(state))
    resolve_ok = resolve_event(state, selected["event_id"])

    checks = {
        "version_is_current": first["version"] == FRANCHISE_EVENT_VERSION,
        "injury_event_is_created": first["created"] >= 1,
        "synchronization_is_idempotent": second["created"] == 0,
        "controlled_injury_blocks": bool(blocking),
        "read_does_not_silently_resolve_blocker": read_ok and still_blocking_after_read,
        "resolve_clears_blocker": resolve_ok and not blocking_events(state),
        "plain_dict_event_contract": all(isinstance(event, dict) for event in franchise_events(state)),
        "settings_round_trip": update_event_settings(state, pause_on_high_workload=True)["pause_on_high_workload"],
        "inbox_rows_exist": bool(event_inbox_rows(state)),
    }
    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "script": FRANCHISE_EVENT_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "first_sync": first,
        "second_sync": second,
        "event_count": len(franchise_events(state)),
        "passed": not failed,
    }
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    SELF_TEST_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if failed:
        raise AssertionError(
            "Franchise event self-test failed: " + ", ".join(failed)
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(run_self_test(), indent=2))
        print("\nFRANCHISE LEAGUE EVENTS V1 SELF-TEST PASSED")
        return 0
    raise SystemExit("Use --self-test.")


if __name__ == "__main__":
    raise SystemExit(main())
