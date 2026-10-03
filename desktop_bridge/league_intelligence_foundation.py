from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Mapping


LEAGUE_INTELLIGENCE_FOUNDATION_VERSION = (
    "v3-league-intelligence-foundation-batch-12-2026-10-03"
)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _enum_value(value: Any) -> str:
    return _clean(getattr(value, "value", value))


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, (str, int, float, bool)):
        return enum_value
    if hasattr(value, "__dict__"):
        return {
            str(key): _json_safe(item)
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }
    return str(value)


def _active_team(checkpoint: Any) -> str:
    preferences = dict(getattr(checkpoint, "preferences", {}) or {})
    return _clean(preferences.get("franchise_pref_active_team", "")).upper()


def _team_name(team_names: Mapping[str, str], abbreviation: str) -> str:
    return str(team_names.get(abbreviation, abbreviation))


def _standing_row(state: Any, abbreviation: str, rank: int, team_names: Mapping[str, str]) -> dict[str, Any]:
    standing = state.standings.get(abbreviation)
    team = state.teams.get(abbreviation)
    if standing is None:
        return {}
    games = _safe_int(getattr(standing, "games_played", 0))
    wins = _safe_int(getattr(standing, "wins", 0))
    losses = _safe_int(getattr(standing, "losses", 0))
    points_for = _safe_int(getattr(standing, "points_for", 0))
    points_against = _safe_int(getattr(standing, "points_against", 0))
    streak_type = _clean(getattr(standing, "streak_type", ""))
    streak_length = _safe_int(getattr(standing, "streak_length", 0))
    return {
        "rank": rank,
        "team": abbreviation,
        "name": _team_name(team_names, abbreviation),
        "conference": _clean(getattr(team, "conference", "")),
        "division": _clean(getattr(team, "division", "")),
        "games_played": games,
        "wins": wins,
        "losses": losses,
        "record": f"{wins}-{losses}",
        "win_pct": round(wins / games, 4) if games else 0.0,
        "home": f"{_safe_int(getattr(standing, 'home_wins', 0))}-{_safe_int(getattr(standing, 'home_losses', 0))}",
        "away": f"{_safe_int(getattr(standing, 'away_wins', 0))}-{_safe_int(getattr(standing, 'away_losses', 0))}",
        "point_diff": points_for - points_against,
        "streak": f"{streak_type}{streak_length}" if streak_type else "",
    }


def _conference_standings(state: Any, conference: str, team_names: Mapping[str, str]) -> list[dict[str, Any]]:
    teams = [
        str(abbreviation)
        for abbreviation, team in state.teams.items()
        if _clean(getattr(team, "conference", "")).lower() == conference.lower()
    ]

    def ranking_key(abbreviation: str) -> tuple[float, int, int, str]:
        standing = state.standings.get(abbreviation)
        if standing is None:
            return (0.0, 0, 0, abbreviation)
        games = max(_safe_int(getattr(standing, "games_played", 0)), 1)
        wins = _safe_int(getattr(standing, "wins", 0))
        point_diff = _safe_int(getattr(standing, "points_for", 0)) - _safe_int(
            getattr(standing, "points_against", 0)
        )
        return (wins / games, wins, point_diff, abbreviation)

    ordered = sorted(teams, key=ranking_key, reverse=True)
    return [
        row
        for rank, abbreviation in enumerate(ordered, start=1)
        if (row := _standing_row(state, abbreviation, rank, team_names))
    ]


def _playoff_picture(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    picture: list[dict[str, Any]] = []
    for row in rows[:10]:
        seed = _safe_int(row.get("rank"))
        entry = dict(row)
        entry["seed"] = seed
        entry["zone"] = "playoff" if seed <= 6 else "play_in"
        picture.append(entry)
    return picture


def _player_stat_rows(state: Any) -> tuple[list[dict[str, Any]], int]:
    team_games = [
        _safe_int(getattr(standing, "games_played", 0))
        for standing in state.standings.values()
    ]
    max_team_games = max(team_games, default=0)
    # Mirrors the prior bridge's 10-game gate once the season is underway,
    # but still gives early-season checkpoints useful league context.
    minimum_games = min(10, max(1, max_team_games // 4)) if max_team_games else 1

    rows: list[dict[str, Any]] = []
    for player_id, totals in state.player_season_totals.items():
        games = _safe_int(getattr(totals, "games_played", 0))
        if games < minimum_games:
            continue
        player = state.players.get(player_id)
        if player is None:
            continue

        def per_game(field: str) -> float:
            return round(_safe_float(getattr(totals, field, 0)) / games, 1) if games else 0.0

        fgm = _safe_int(getattr(totals, "field_goals_made", 0))
        fga = _safe_int(getattr(totals, "field_goals_attempted", 0))
        tpm = _safe_int(getattr(totals, "three_pointers_made", 0))
        tpa = _safe_int(getattr(totals, "three_pointers_attempted", 0))
        ftm = _safe_int(getattr(totals, "free_throws_made", 0))
        fta = _safe_int(getattr(totals, "free_throws_attempted", 0))
        rows.append(
            {
                "player_id": str(player_id),
                "name": _clean(getattr(player, "player_name", player_id)),
                "team": _clean(getattr(player, "team_abbreviation", "")),
                "position": _clean(getattr(player, "position", "")),
                "age": _safe_float(getattr(player, "age", 0.0)),
                "games": games,
                "ppg": per_game("points"),
                "rpg": per_game("rebounds"),
                "apg": per_game("assists"),
                "spg": per_game("steals"),
                "bpg": per_game("blocks"),
                "fg_pct": round(100.0 * fgm / fga, 1) if fga else 0.0,
                "three_pct": round(100.0 * tpm / tpa, 1) if tpa else 0.0,
                "ft_pct": round(100.0 * ftm / fta, 1) if fta else 0.0,
            }
        )
    return rows, minimum_games


def _leaders(state: Any, limit: int = 5) -> tuple[dict[str, list[dict[str, Any]]], int]:
    rows, minimum_games = _player_stat_rows(state)

    def top(metric: str) -> list[dict[str, Any]]:
        ordered = sorted(
            rows,
            key=lambda row: (-_safe_float(row.get(metric)), _clean(row.get("name"))),
        )
        return [
            {"rank": index, **dict(row)}
            for index, row in enumerate(ordered[:limit], start=1)
        ]

    return {
        "scoring": top("ppg"),
        "rebounds": top("rpg"),
        "assists": top("apg"),
        "steals": top("spg"),
        "blocks": top("bpg"),
    }, minimum_games


def _award_watch(state: Any, stat_rows: list[dict[str, Any]], limit: int = 5) -> dict[str, Any]:
    # V2 does not expose a single canonical live-voting object through the
    # simulation dataclass. Preserve any attached award authority if present;
    # otherwise provide clearly labeled read-only watch projections.
    attached: dict[str, Any] = {}
    for key, value in vars(state).items():
        if "award" in str(key).lower() and value not in (None, {}, [], (), ""):
            attached[str(key)] = _json_safe(value)

    standings = state.standings

    def team_win_pct(team: str) -> float:
        standing = standings.get(team)
        if standing is None:
            return 0.0
        games = max(_safe_int(getattr(standing, "games_played", 0)), 1)
        return _safe_int(getattr(standing, "wins", 0)) / games

    def mvp_score(row: dict[str, Any]) -> float:
        return (
            _safe_float(row.get("ppg"))
            + 0.70 * _safe_float(row.get("rpg"))
            + 0.85 * _safe_float(row.get("apg"))
            + 1.35 * _safe_float(row.get("spg"))
            + 1.35 * _safe_float(row.get("bpg"))
            + 7.0 * team_win_pct(_clean(row.get("team")))
        )

    def dpoy_score(row: dict[str, Any]) -> float:
        return (
            2.4 * _safe_float(row.get("bpg"))
            + 2.1 * _safe_float(row.get("spg"))
            + 0.18 * _safe_float(row.get("rpg"))
            + 2.0 * team_win_pct(_clean(row.get("team")))
        )

    def projected(score_fn: Any) -> list[dict[str, Any]]:
        ordered = sorted(stat_rows, key=lambda row: (-score_fn(row), _clean(row.get("name"))))
        return [
            {
                "rank": index,
                "player_id": row["player_id"],
                "name": row["name"],
                "team": row["team"],
                "ppg": row["ppg"],
                "rpg": row["rpg"],
                "apg": row["apg"],
                "spg": row["spg"],
                "bpg": row["bpg"],
                "watch_score": round(score_fn(row), 2),
            }
            for index, row in enumerate(ordered[:limit], start=1)
        ]

    return {
        "official_state_available": bool(attached),
        "official_state": attached,
        "projection_only": not bool(attached),
        "projection_note": (
            "Live award authority attached to this checkpoint."
            if attached
            else "Read-only watch projection from current production season totals; not an official award vote."
        ),
        "mvp_watch": projected(mvp_score),
        "dpoy_watch": projected(dpoy_score),
    }


def _schedule_context(state: Any, team_names: Mapping[str, str], limit: int = 12) -> dict[str, Any]:
    completed_rows: list[tuple[int, str, dict[str, Any]]] = []
    upcoming_rows: list[tuple[int, str, dict[str, Any]]] = []
    completed_games = getattr(state, "completed_games", {}) or {}

    for game_id, game in (getattr(state, "schedule", {}) or {}).items():
        status = _enum_value(getattr(game, "status", "")).lower()
        day_index = _safe_int(getattr(game, "day_index", 0))
        home = _clean(getattr(game, "home_team", ""))
        away = _clean(getattr(game, "away_team", ""))
        base = {
            "game_id": str(game_id),
            "day_index": day_index,
            "home_team": home,
            "home_name": _team_name(team_names, home),
            "away_team": away,
            "away_name": _team_name(team_names, away),
            "status": status,
        }
        if status == "completed":
            completed = completed_games.get(str(game_id)) or completed_games.get(game_id)
            if completed is not None:
                base.update(
                    {
                        "home_score": _safe_int(getattr(completed, "home_score", 0)),
                        "away_score": _safe_int(getattr(completed, "away_score", 0)),
                        "overtime_periods": _safe_int(getattr(completed, "overtime_periods", 0)),
                    }
                )
            completed_rows.append((day_index, str(game_id), base))
        elif status == "scheduled":
            upcoming_rows.append((day_index, str(game_id), base))

    completed_rows.sort(key=lambda item: (item[0], item[1]), reverse=True)
    upcoming_rows.sort(key=lambda item: (item[0], item[1]))
    schedule_size = len(getattr(state, "schedule", {}) or {})
    return {
        "total_games": schedule_size,
        "completed_games": len(completed_rows),
        "remaining_games": len(upcoming_rows),
        "recent_results": [item[2] for item in completed_rows[:limit]],
        "upcoming_games": [item[2] for item in upcoming_rows[:limit]],
    }


def _postseason_context(state: Any) -> dict[str, Any]:
    postseason = getattr(state, "postseason_state", None)
    if postseason is None:
        return {
            "active": False,
            "stage": "",
            "champion": "",
            "runner_up": "",
            "conference_champions": {},
            "state": {},
        }
    return {
        "active": True,
        "stage": _enum_value(getattr(postseason, "stage", "")),
        "champion": _clean(getattr(postseason, "champion", "")),
        "runner_up": _clean(getattr(postseason, "runner_up", "")),
        "conference_champions": _json_safe(getattr(postseason, "conference_champions", {})),
        "state": _json_safe(postseason),
    }


def _season_history(state: Any, team_names: Mapping[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for archive in list(getattr(state, "season_history", []) or []):
        champion = _clean(getattr(archive, "champion", ""))
        runner_up = _clean(getattr(archive, "runner_up", ""))
        rows.append(
            {
                "season": _clean(getattr(archive, "season_label", "")),
                "champion": champion,
                "champion_name": _team_name(team_names, champion) if champion else "",
                "runner_up": runner_up,
                "runner_up_name": _team_name(team_names, runner_up) if runner_up else "",
                "conference_champions": _json_safe(getattr(archive, "conference_champions", {})),
                "postseason_games_completed": _safe_int(
                    getattr(archive, "postseason_games_completed", 0)
                ),
            }
        )
    return rows[-10:][::-1]


def build_league_intelligence_payload(
    checkpoint: Any,
    *,
    team_names: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    state = checkpoint.simulation_state
    resolved_team_names: Mapping[str, str] = team_names or {}
    active_team = _active_team(checkpoint)

    east = _conference_standings(state, "East", resolved_team_names)
    west = _conference_standings(state, "West", resolved_team_names)
    leaders, minimum_games = _leaders(state, limit=5)
    stat_rows, _ = _player_stat_rows(state)
    schedule = _schedule_context(state, resolved_team_names)

    active_row: dict[str, Any] = {}
    for row in east + west:
        if row.get("team") == active_team:
            active_row = dict(row)
            break

    return {
        "foundation_version": LEAGUE_INTELLIGENCE_FOUNDATION_VERSION,
        "read_only": True,
        "working_save_only": True,
        "active_v2_read_only": True,
        "team": active_team,
        "team_name": _team_name(resolved_team_names, active_team),
        "season": {
            "label": _clean(getattr(getattr(state, "settings", None), "season_label", "")),
            "phase": _enum_value(getattr(state, "phase", "")),
            "day_index": _safe_int(getattr(state, "current_day_index", 0)),
        },
        "active_team_standing": active_row,
        "standings": {"east": east, "west": west},
        "playoff_picture": {
            "east": _playoff_picture(east),
            "west": _playoff_picture(west),
            "note": "Seeds 1-6 are playoff positions; 7-10 are play-in positions. Ordering mirrors the current V3 standings presentation tiebreak (win percentage, wins, point differential).",
        },
        "leaders": leaders,
        "leader_minimum_games": minimum_games,
        "award_watch": _award_watch(state, stat_rows),
        "schedule": schedule,
        "postseason": _postseason_context(state),
        "season_history": _season_history(state, resolved_team_names),
        "league_counts": {
            "teams": len(getattr(state, "teams", {}) or {}),
            "players": len(getattr(state, "players", {}) or {}),
            "free_agents": len(getattr(state, "free_agent_player_ids", ()) or ()),
            "source_transaction_count": _safe_int(getattr(state, "source_transaction_count", 0)),
        },
    }
