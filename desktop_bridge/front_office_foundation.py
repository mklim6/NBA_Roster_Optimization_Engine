from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Mapping
from desktop_bridge.player_career_history import career_history


FRONT_OFFICE_FOUNDATION_VERSION = (
    "v3-front-office-foundation-batch-13-health-development-2026-10-03"
)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        return _text(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value):
        return _json_safe(asdict(value), depth=depth + 1)
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item, depth=depth + 1) for item in value]
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, (str, int, float, bool)):
        return enum_value
    return _text(value)


def _conference_rank(state: Any, active_team: str) -> tuple[int | None, str]:
    team_state = getattr(state, "teams", {}).get(active_team)
    if team_state is None:
        return None, ""
    conference = _text(getattr(team_state, "conference", ""))
    teams = [
        team
        for team, row in getattr(state, "teams", {}).items()
        if _text(getattr(row, "conference", "")) == conference
    ]

    def key(team: str) -> tuple[float, int, int]:
        standing = getattr(state, "standings", {}).get(team)
        if standing is None:
            return (0.0, 0, 0)
        games = max(_integer(getattr(standing, "games_played", 0)), 1)
        wins = _integer(getattr(standing, "wins", 0))
        diff = _integer(getattr(standing, "points_for", 0)) - _integer(
            getattr(standing, "points_against", 0)
        )
        return (wins / games, wins, diff)

    ordered = sorted(teams, key=key, reverse=True)
    try:
        return ordered.index(active_team) + 1, conference
    except ValueError:
        return None, conference


def _player_development_rows(state: Any, active_team: str) -> list[dict[str, Any]]:
    team = getattr(state, "teams", {}).get(active_team)
    if team is None:
        return []

    rows: list[dict[str, Any]] = []
    for player_id in getattr(team, "roster_player_ids", ()):
        player = getattr(state, "players", {}).get(player_id)
        if player is None:
            continue
        age = _number(getattr(player, "age", None))
        overall = _number(getattr(player, "overall_rating", None))
        potential = _number(getattr(player, "potential_rating", None))
        future = _number(getattr(player, "future_outlook_rating", None))
        history = getattr(player, "development_history", ()) or ()
        rows.append(
            {
                "player_id": _text(player_id),
                "name": _text(getattr(player, "player_name", player_id)),
                "position": _text(getattr(player, "position", "")),
                "age": round(age, 1) if age is not None else None,
                "overall": round(overall, 1) if overall is not None else None,
                "potential": round(potential, 1) if potential is not None else None,
                "future_outlook": round(future, 1) if future is not None else None,
                "direction": _text(getattr(player, "development_direction", "Stable")) or "Stable",
                "profile_reliability": _number(
                    getattr(player, "profile_reliability", None)
                ),
                "history_entries": len(history),
                "career_history": career_history(player),
            }
        )

    rows.sort(
        key=lambda row: (
            -float(row.get("future_outlook") or 0.0),
            -float(row.get("potential") or 0.0),
            float(row.get("age") if row.get("age") is not None else 99.0),
            str(row.get("name", "")),
        )
    )
    return rows


def _workload_rows(roster_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in roster_rows:
        health = _mapping(raw.get("health"))
        fatigue = _number(health.get("fatigue"))
        durability = _number(health.get("durability"))
        rows.append(
            {
                "player_id": _text(raw.get("player_id")),
                "name": _text(raw.get("name")),
                "role": _text(raw.get("role")),
                "target_minutes": _number(raw.get("target_minutes")) or 0.0,
                "fatigue": round(fatigue, 1) if fatigue is not None else None,
                "durability": round(durability, 1) if durability is not None else None,
                "health_status": _text(health.get("display") or health.get("status")),
                "risk_tier": _text(health.get("risk_tier")),
                "season_games_missed": _integer(health.get("season_games_missed", 0)),
            }
        )

    rows.sort(
        key=lambda row: (
            -float(row.get("fatigue") or 0.0),
            -float(row.get("target_minutes") or 0.0),
            str(row.get("name", "")),
        )
    )
    return rows


def _injury_rows(roster_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in roster_rows:
        health = _mapping(raw.get("health"))
        status = _text(health.get("status")).lower()
        if status in {"", "healthy", "unknown"}:
            continue
        rows.append(
            {
                "player_id": _text(raw.get("player_id")),
                "name": _text(raw.get("name")),
                "status": _text(health.get("display") or health.get("status")),
                "injury_type": _text(health.get("injury_type")),
                "games_remaining": _integer(health.get("games_remaining", 0)),
                "expected_return_day": _integer(health.get("expected_return_day", 0)),
                "risk_tier": _text(health.get("risk_tier")),
                "risk_explanation": _text(health.get("risk_explanation")),
            }
        )
    return rows


def _morale_rows(roster_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    status_weight = {
        "demanding trade": 5,
        "angry": 4,
        "frustrated": 3,
        "uneasy": 2,
    }
    rows: list[dict[str, Any]] = []
    for raw in roster_rows:
        morale = _mapping(raw.get("morale"))
        status = _text(morale.get("status"))
        risk = _number(morale.get("trade_request_risk"))
        satisfaction = _number(morale.get("role_satisfaction"))
        rows.append(
            {
                "player_id": _text(raw.get("player_id")),
                "name": _text(raw.get("name")),
                "role": _text(raw.get("role")),
                "status": status,
                "score": _number(morale.get("score")),
                "role_satisfaction": (
                    round(satisfaction, 1) if satisfaction is not None else None
                ),
                "trade_request_risk": round(risk, 3) if risk is not None else None,
                "trade_request_status": _text(morale.get("trade_request_status")),
                "expected_role": _text(morale.get("expected_role")),
                "actual_minutes": _number(morale.get("actual_minutes")),
                "recent_minutes": _number(morale.get("recent_minutes")),
                "reasons": list(morale.get("reasons", []) or []),
                "attention_weight": status_weight.get(status.lower(), 0),
            }
        )
    rows.sort(
        key=lambda row: (
            -int(row.get("attention_weight", 0)),
            -float(row.get("trade_request_risk") or 0.0),
            float(
                row.get("role_satisfaction")
                if row.get("role_satisfaction") is not None
                else 999.0
            ),
            str(row.get("name", "")),
        )
    )
    return rows


def _find_key(value: Any, candidates: set[str], *, depth: int = 0) -> Any:
    if depth > 4:
        return None
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _text(key).lower() in candidates and item not in (None, "", [], {}):
                return item
        for item in value.values():
            found = _find_key(item, candidates, depth=depth + 1)
            if found not in (None, "", [], {}):
                return found
    elif isinstance(value, (list, tuple)):
        for item in value:
            found = _find_key(item, candidates, depth=depth + 1)
            if found not in (None, "", [], {}):
                return found
    return None


def _staff_payload(state: Any) -> dict[str, Any]:
    authority_names = (
        "franchise_staff_state_v1",
        "franchise_staff_v1",
        "staff_state",
        "staff",
    )
    exposed_name = ""
    exposed_value: Any = None
    for name in authority_names:
        value = getattr(state, name, None)
        if value not in (None, {}, [], ()):
            exposed_name = name
            exposed_value = value
            break

    scouting_sources = [
        getattr(state, "franchise_scouting_state_v1", None),
        getattr(state, "franchise_draft_state_v1", None),
    ]
    lead_scout = None
    for source in scouting_sources:
        if source in (None, {}, [], ()):
            continue
        lead_scout = _find_key(
            _json_safe(source),
            {"lead_scout", "lead_scout_name", "scout_name", "assigned_scout"},
        )
        if lead_scout not in (None, "", [], {}):
            break

    return {
        "standalone_authority_exposed": bool(exposed_name),
        "authority_name": exposed_name,
        "authority_snapshot": _json_safe(exposed_value) if exposed_name else None,
        "lead_scout": _json_safe(lead_scout),
        "write_actions_enabled": False,
        "status": (
            "Production staff state is exposed read-only in this checkpoint."
            if exposed_name
            else "Standalone production staff-management authority is not exposed in the current V3 checkpoint."
        ),
    }


def build_front_office_intelligence_payload(
    state: Any,
    active_team: str,
    roster_payload: Mapping[str, Any],
    *,
    team_names: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build a read-only front-office snapshot from mature franchise state."""
    team_names = dict(team_names or {})
    roster = dict(roster_payload or {})
    roster_rows = [dict(row) for row in roster.get("players", []) if isinstance(row, Mapping)]
    team_payload = _mapping(roster.get("team"))
    chemistry = _mapping(roster.get("chemistry"))
    financial = _mapping(roster.get("financial"))

    standing = getattr(state, "standings", {}).get(active_team)
    rank, conference = _conference_rank(state, active_team)
    wins = _integer(getattr(standing, "wins", 0)) if standing is not None else 0
    losses = _integer(getattr(standing, "losses", 0)) if standing is not None else 0

    team_state = getattr(state, "teams", {}).get(active_team)
    rotation = getattr(team_state, "rotation", None) if team_state is not None else None
    starter_ids = list(getattr(rotation, "starter_ids", ()) or ()) if rotation is not None else []
    rotation_ids = list(getattr(rotation, "rotation_player_ids", ()) or ()) if rotation is not None else []
    minute_targets = dict(getattr(rotation, "minutes_targets", {}) or {}) if rotation is not None else {}

    development_rows = _player_development_rows(state, active_team)
    workload_rows = _workload_rows(roster_rows)
    injuries = _injury_rows(roster_rows)
    morale_rows = _morale_rows(roster_rows)

    attention = [
        row
        for row in morale_rows
        if int(row.get("attention_weight", 0)) > 0
        or float(row.get("trade_request_risk") or 0.0) >= 0.25
    ]

    return {
        "foundation_version": FRONT_OFFICE_FOUNDATION_VERSION,
        "source": "v3_working_checkpoint",
        "read_only": True,
        "working_save_only": True,
        "active_v2_read_only": True,
        "write_actions_enabled": False,
        "team": {
            **team_payload,
            "abbreviation": active_team,
            "name": team_names.get(active_team, active_team),
        },
        "season": {
            "label": _text(getattr(getattr(state, "settings", None), "season_label", "")),
            "phase": _text(getattr(getattr(state, "phase", ""), "value", getattr(state, "phase", ""))),
            "day_index": _integer(getattr(state, "current_day_index", 0)),
        },
        "competitive": {
            "record": f"{wins}-{losses}",
            "wins": wins,
            "losses": losses,
            "conference_rank": rank,
            "conference": conference,
        },
        "chemistry": chemistry,
        "financial": financial,
        "rotation": {
            "starters": len(starter_ids),
            "rotation_players": len(rotation_ids),
            "total_target_minutes": round(
                sum(float(value) for value in minute_targets.values()), 1
            ),
        },
        "team_health": {
            "injured_count": len(injuries),
            "injuries": injuries,
            "workload_watch": workload_rows[:8],
        },
        "morale": {
            "attention_count": len(attention),
            "attention": attention[:8],
            "full_roster": morale_rows,
        },
        "development": {
            "core": development_rows[:8],
            "full_roster": development_rows,
        },
        "staff": _staff_payload(state),
    }
