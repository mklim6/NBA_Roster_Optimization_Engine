from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from typing import Any, Iterable

from simulation_injury_fatigue_v1 import (
    ensure_injury_fatigue_state,
    health_events,
    player_health_report_rows,
)


HEALTH_REALISM_EXPORT_VERSION = "franchise-health-realism-export-v1-2026-08-10"


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return float(default)
    return parsed


def _current_season_events(state: Any) -> list[dict[str, Any]]:
    season = str(state.settings.season_label)
    return [
        dict(event)
        for event in health_events(state)
        if str(event.get("season_label", "")) == season
    ]


def _roster_player_ids(state: Any) -> tuple[str, ...]:
    ids: set[str] = set()
    for team in state.teams.values():
        ids.update(str(pid) for pid in team.roster_player_ids)
    return tuple(sorted(ids))


def _reference_games(state: Any) -> int:
    played = [int(row.games_played or 0) for row in state.standings.values()]
    current_max = max(played, default=0)
    season_max = int(getattr(state.settings, "regular_season_games_per_team", 82) or 82)
    return max(0, min(season_max, current_max))


def player_availability_audit_rows(state: Any) -> list[dict[str, Any]]:
    """Return one diagnostic row per currently rostered player.

    `games_not_played_reference` is exact at the end of a normal 82-game
    regular season. During an in-progress season it is a league-progress
    reference rather than a tenure-adjusted DNP count. The export therefore
    also exposes the engine's independently tracked medical missed-game count.
    """
    profiles = ensure_injury_fatigue_state(state)
    events = _current_season_events(state)
    events_by_player: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        events_by_player[str(event.get("player_id", ""))].append(event)

    reference_games = _reference_games(state)
    rows: list[dict[str, Any]] = []

    for player_id in _roster_player_ids(state):
        player = state.players[player_id]
        totals = state.player_season_totals[player_id]
        injury = state.injuries[player_id]
        profile = profiles[player_id]
        player_events = sorted(
            events_by_player.get(player_id, []),
            key=lambda event: (
                int(event.get("day_index", 0) or 0),
                str(event.get("game_id", "")),
            ),
        )
        severities = Counter(
            str(event.get("severity", "")).lower() for event in player_events
        )
        event_kinds = Counter(
            str(event.get("event_kind", "injury")).lower()
            for event in player_events
        )
        gp = int(totals.games_played or 0)
        games_not_played = max(0, reference_games - gp)
        medical_missed = max(0, int(profile.season_games_missed or 0))
        current_team = str(getattr(player, "team_abbreviation", "") or "")
        health_row: dict[str, Any] = {}
        if current_team in state.teams:
            try:
                health_row = next(
                    row
                    for row in player_health_report_rows(state, current_team)
                    if str(row.get("player_id")) == player_id
                )
            except (StopIteration, KeyError, TypeError, ValueError):
                health_row = {}

        availability_rating = _finite(
            getattr(player, "skill_ratings", {}).get("availability_rating", 75.0),
            75.0,
        )
        last_event = player_events[-1] if player_events else {}
        minutes = _finite(totals.minutes)
        rows.append(
            {
                "season": str(state.settings.season_label),
                "player_id": player_id,
                "player": str(player.player_name),
                "team": current_team,
                "position": str(player.position),
                "age": round(_finite(player.age, 0.0), 1),
                "roster_status": str(getattr(player, "roster_status", "")),
                "reference_team_games": reference_games,
                "GP": gp,
                "GS": int(totals.games_started or 0),
                "games_not_played_reference": games_not_played,
                "availability_pct_reference": (
                    round(100.0 * gp / reference_games, 1)
                    if reference_games
                    else 0.0
                ),
                "minutes": round(minutes, 1),
                "MPG": round(minutes / gp, 2) if gp else 0.0,
                "medical_games_missed_recorded": medical_missed,
                "nonmedical_or_unreconciled_missed_games": max(
                    0, games_not_played - medical_missed
                ),
                "injury_events": len(player_events),
                "injuries_suffered_counter": max(
                    0, int(profile.injuries_suffered or 0)
                ),
                "estimated_games_missed_from_events": sum(
                    max(0, int(event.get("estimated_games_missed", 0) or 0))
                    for event in player_events
                ),
                "soreness_events": severities.get("soreness", 0),
                "minor_events": severities.get("minor", 0),
                "moderate_events": severities.get("moderate", 0),
                "major_events": severities.get("major", 0),
                "setback_events": event_kinds.get("setback", 0),
                "recurrence_events": event_kinds.get("recurrence", 0),
                "back_to_back_injury_events": sum(
                    bool(event.get("back_to_back", False))
                    for event in player_events
                ),
                "current_status": str(
                    health_row.get("status")
                    or getattr(injury.status, "value", injury.status)
                ),
                "current_injury": str(
                    health_row.get("injury") or injury.injury_type or "None"
                ),
                "current_body_region": str(health_row.get("body_region", "—")),
                "current_injury_grade": str(health_row.get("injury_grade", "—")),
                "current_medical_phase": str(
                    health_row.get("medical_phase", "Healthy")
                ),
                "recovery_progress_pct": round(
                    _finite(health_row.get("recovery_progress"), 100.0), 1
                ),
                "current_expected_return_day": health_row.get(
                    "expected_return_day"
                ),
                "current_minutes_limit": health_row.get("minutes_limit"),
                "current_reinjury_risk_pct": round(
                    _finite(health_row.get("reinjury_risk")), 1
                ),
                "recurrence_count": int(
                    health_row.get("recurrence_count", 0) or 0
                ),
                "setback_count": int(health_row.get("setback_count", 0) or 0),
                "current_fatigue": round(
                    _finite(health_row.get("current_fatigue", profile.fatigue)), 2
                ),
                "projected_next_game_fatigue": round(
                    _finite(health_row.get("projected_fatigue", profile.fatigue)), 2
                ),
                "last_injury_risk_pct": round(
                    100.0 * _finite(profile.last_injury_risk), 2
                ),
                "last_risk_tier": str(profile.last_risk_tier),
                "durability": round(_finite(profile.durability), 4),
                "availability_rating": round(availability_rating, 1),
                "last_event_day": (
                    int(last_event.get("day_index", 0) or 0) if last_event else ""
                ),
                "last_event_kind": (
                    str(last_event.get("event_kind", "")) if last_event else ""
                ),
                "last_event_injury": (
                    str(last_event.get("injury_type", "")) if last_event else ""
                ),
                "last_event_severity": (
                    str(last_event.get("severity", "")) if last_event else ""
                ),
                "last_event_status": (
                    str(last_event.get("status", "")) if last_event else ""
                ),
            }
        )

    rows.sort(key=lambda row: (row["team"], row["player"]))
    return rows


def injury_event_history_rows(state: Any) -> list[dict[str, Any]]:
    rows = _current_season_events(state)
    preferred = [
        "season_label",
        "game_id",
        "day_index",
        "player_id",
        "player_name",
        "team",
        "event_kind",
        "injury_type",
        "body_region",
        "severity",
        "injury_grade",
        "status",
        "expected_return_day",
        "estimated_games_missed",
        "probability",
        "fatigue_before_game",
        "minutes_played",
        "back_to_back",
        "rehab_phase",
        "recovery_progress",
        "recurrence_count",
        "setback_count",
        "return_ramp_games",
        "explanation",
        "version",
        "medical_version",
    ]
    normalized: list[dict[str, Any]] = []
    for event in sorted(
        rows,
        key=lambda row: (
            int(row.get("day_index", 0) or 0),
            str(row.get("game_id", "")),
        ),
    ):
        normalized.append({key: event.get(key, "") for key in preferred})
    return normalized


def rows_to_csv_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    materialized = list(rows)
    if not materialized:
        return b""
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in materialized:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=fieldnames,
        extrasaction="ignore",
    )
    writer.writeheader()
    writer.writerows(materialized)
    return output.getvalue().encode("utf-8-sig")
