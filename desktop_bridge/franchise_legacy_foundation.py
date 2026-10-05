from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Mapping
from collections import defaultdict
import math

FRANCHISE_LEGACY_FOUNDATION_VERSION = (
    "v3-franchise-legacy-foundation-expansion-39-v1.0.0-2026-10-04"
)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _enum_value(value: Any) -> str:
    return _clean(getattr(value, "value", value))


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


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
    return _team(preferences.get("franchise_pref_active_team", ""))


def _team_name(team_names: Mapping[str, str], abbreviation: str) -> str:
    key = _team(abbreviation)
    return str(team_names.get(key, key))


def _season_key(label: str) -> int:
    text = _clean(label)
    if not text:
        return 0
    head = text.split("-")[0]
    return _safe_int(head, 0)


def _player_name(state: Any, player_id: str) -> str:
    player = getattr(state, "players", {}).get(player_id)
    if player is None:
        return str(player_id)
    return _clean(getattr(player, "player_name", player_id)) or str(player_id)


def _standing_payload(standing: Any) -> dict[str, Any]:
    if standing is None:
        return {
            "wins": 0,
            "losses": 0,
            "games": 0,
            "record": "0-0",
            "win_pct": 0.0,
            "point_diff": 0,
        }
    wins = _safe_int(getattr(standing, "wins", 0))
    losses = _safe_int(getattr(standing, "losses", 0))
    games = _safe_int(getattr(standing, "games_played", wins + losses))
    points_for = _safe_int(getattr(standing, "points_for", 0))
    points_against = _safe_int(getattr(standing, "points_against", 0))
    return {
        "wins": wins,
        "losses": losses,
        "games": games,
        "record": f"{wins}-{losses}",
        "win_pct": round(wins / games, 4) if games else 0.0,
        "point_diff": points_for - points_against,
    }


def _archive_result(
    archive: Any,
    active_team: str,
) -> tuple[str, int]:
    champion = _team(getattr(archive, "champion", ""))
    runner_up = _team(getattr(archive, "runner_up", ""))
    conference_champions = dict(
        getattr(archive, "conference_champions", {}) or {}
    )
    conference_values = {_team(value) for value in conference_champions.values()}

    if champion == active_team:
        return "NBA CHAMPION", 5
    if runner_up == active_team:
        return "NBA FINALS", 4
    if active_team in conference_values:
        return "CONFERENCE CHAMPION", 3

    postseason = getattr(archive, "postseason_state", None)
    seed_by_team = dict(getattr(postseason, "seed_by_team", {}) or {}) if postseason else {}
    if active_team in {_team(key) for key in seed_by_team}:
        return "PLAYOFFS", 2
    return "REGULAR SEASON", 1


def _season_rows(
    state: Any,
    active_team: str,
    team_names: Mapping[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    history = list(getattr(state, "season_history", []) or [])

    for archive in history:
        standings = dict(getattr(archive, "standings", {}) or {})
        standing = standings.get(active_team)
        record = _standing_payload(standing)
        result, tier = _archive_result(archive, active_team)
        champion = _team(getattr(archive, "champion", ""))
        runner_up = _team(getattr(archive, "runner_up", ""))
        rows.append(
            {
                "season": _clean(getattr(archive, "season_label", "")),
                "season_key": _season_key(_clean(getattr(archive, "season_label", ""))),
                "is_current": False,
                "record": record["record"],
                "wins": record["wins"],
                "losses": record["losses"],
                "games": record["games"],
                "win_pct": record["win_pct"],
                "point_diff": record["point_diff"],
                "result": result,
                "result_tier": tier,
                "champion": champion,
                "champion_name": _team_name(team_names, champion) if champion else "",
                "runner_up": runner_up,
                "runner_up_name": _team_name(team_names, runner_up) if runner_up else "",
                "postseason_games": _safe_int(
                    getattr(archive, "postseason_games_completed", 0)
                ),
            }
        )

    live_settings = getattr(state, "settings", None)
    live_label = _clean(getattr(live_settings, "season_label", ""))
    live_standing = getattr(state, "standings", {}).get(active_team)
    live_record = _standing_payload(live_standing)
    if live_label:
        rows.append(
            {
                "season": live_label,
                "season_key": _season_key(live_label),
                "is_current": True,
                "record": live_record["record"],
                "wins": live_record["wins"],
                "losses": live_record["losses"],
                "games": live_record["games"],
                "win_pct": live_record["win_pct"],
                "point_diff": live_record["point_diff"],
                "result": "IN PROGRESS",
                "result_tier": 0,
                "champion": "",
                "champion_name": "",
                "runner_up": "",
                "runner_up_name": "",
                "postseason_games": 0,
            }
        )

    rows.sort(key=lambda row: (row["season_key"], row["is_current"]))
    return rows


def _generic_game_payload(
    game: Any,
    *,
    season: str,
    is_playoff: bool,
) -> dict[str, Any] | None:
    if game is None:
        return None
    home = _team(getattr(game, "home_team", ""))
    away = _team(getattr(game, "away_team", ""))
    if not home or not away:
        return None

    return {
        "game_id": _clean(getattr(game, "game_id", "")),
        "season": season,
        "home_team": home,
        "away_team": away,
        "home_score": _safe_int(getattr(game, "home_score", 0)),
        "away_score": _safe_int(getattr(game, "away_score", 0)),
        "overtime_periods": _safe_int(getattr(game, "overtime_periods", 0)),
        "player_box_scores": list(getattr(game, "player_box_scores", ()) or ()),
        "is_playoff": bool(is_playoff),
    }


def _postseason_games(postseason: Any) -> list[Any]:
    if postseason is None:
        return []
    values = getattr(postseason, "completed_games", None)
    if isinstance(values, Mapping):
        return list(values.values())
    if isinstance(values, (list, tuple)):
        return list(values)
    values = getattr(postseason, "games", None)
    if isinstance(values, Mapping):
        completed: list[Any] = []
        for game in values.values():
            status = _enum_value(getattr(game, "status", "")).lower()
            if status == "completed":
                completed.append(game)
        return completed
    return []


def _all_games(state: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for archive in list(getattr(state, "season_history", []) or []):
        season = _clean(getattr(archive, "season_label", ""))
        for game in dict(getattr(archive, "completed_games", {}) or {}).values():
            row = _generic_game_payload(game, season=season, is_playoff=False)
            if row is None:
                continue
            key = (season, row["game_id"], "regular")
            if key not in seen:
                seen.add(key)
                output.append(row)

        postseason = getattr(archive, "postseason_state", None)
        for game in _postseason_games(postseason):
            row = _generic_game_payload(game, season=season, is_playoff=True)
            if row is None:
                continue
            key = (season, row["game_id"], "playoff")
            if key not in seen:
                seen.add(key)
                output.append(row)

    live_season = _clean(getattr(getattr(state, "settings", None), "season_label", ""))
    for game in dict(getattr(state, "completed_games", {}) or {}).values():
        row = _generic_game_payload(game, season=live_season, is_playoff=False)
        if row is None:
            continue
        key = (live_season, row["game_id"], "live")
        if key not in seen:
            seen.add(key)
            output.append(row)

    live_postseason = getattr(state, "postseason_state", None)
    for game in _postseason_games(live_postseason):
        row = _generic_game_payload(game, season=live_season, is_playoff=True)
        if row is None:
            continue
        key = (live_season, row["game_id"], "live_playoff")
        if key not in seen:
            seen.add(key)
            output.append(row)

    return output


def _line_team(line: Any) -> str:
    return _team(
        getattr(
            line,
            "team_abbreviation",
            getattr(line, "team", ""),
        )
    )


def _line_player_id(line: Any) -> str:
    return _clean(getattr(line, "player_id", ""))


def _franchise_player_aggregates(
    state: Any,
    active_team: str,
    games: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}

    title_seasons = {
        _clean(getattr(archive, "season_label", ""))
        for archive in list(getattr(state, "season_history", []) or [])
        if _team(getattr(archive, "champion", "")) == active_team
    }

    appearances_by_season: dict[str, set[str]] = defaultdict(set)
    for game in games:
        for line in game["player_box_scores"]:
            if _line_team(line) != active_team:
                continue
            player_id = _line_player_id(line)
            if not player_id:
                continue

            row = rows.setdefault(
                player_id,
                {
                    "player_id": player_id,
                    "name": _player_name(state, player_id),
                    "games": 0,
                    "points": 0,
                    "rebounds": 0,
                    "assists": 0,
                    "steals": 0,
                    "blocks": 0,
                    "threes": 0,
                    "seasons": set(),
                    "championships": 0,
                    "best_game_points": 0,
                },
            )
            row["games"] += 1
            row["points"] += _safe_int(getattr(line, "points", 0))
            row["rebounds"] += _safe_int(getattr(line, "rebounds", 0))
            row["assists"] += _safe_int(getattr(line, "assists", 0))
            row["steals"] += _safe_int(getattr(line, "steals", 0))
            row["blocks"] += _safe_int(getattr(line, "blocks", 0))
            row["threes"] += _safe_int(
                getattr(line, "three_pointers_made", 0)
            )
            row["best_game_points"] = max(
                row["best_game_points"],
                _safe_int(getattr(line, "points", 0)),
            )
            season = _clean(game["season"])
            if season:
                row["seasons"].add(season)
                appearances_by_season[season].add(player_id)

    for season in title_seasons:
        for player_id in appearances_by_season.get(season, set()):
            rows[player_id]["championships"] += 1

    for row in rows.values():
        row["seasons_count"] = len(row["seasons"])
        row["season_labels"] = sorted(row["seasons"], key=_season_key)
        row["legacy_score"] = round(
            row["points"] / 125.0
            + row["rebounds"] / 220.0
            + row["assists"] / 180.0
            + row["games"] * 0.18
            + row["championships"] * 25.0,
            2,
        )
        del row["seasons"]

    return rows


def _records(
    season_rows: list[dict[str, Any]],
    games: list[dict[str, Any]],
    active_team: str,
    player_rows: dict[str, dict[str, Any]],
    state: Any,
) -> dict[str, Any]:
    completed_seasons = [row for row in season_rows if not row["is_current"]]
    best_season = (
        max(
            completed_seasons,
            key=lambda row: (row["win_pct"], row["wins"], row["point_diff"]),
        )
        if completed_seasons
        else None
    )

    team_games = [
        game
        for game in games
        if active_team in {game["home_team"], game["away_team"]}
    ]

    largest_win: dict[str, Any] | None = None
    highest_score: dict[str, Any] | None = None
    player_game_records: dict[str, dict[str, Any] | None] = {
        "points": None,
        "rebounds": None,
        "assists": None,
        "steals": None,
        "blocks": None,
    }

    for game in team_games:
        is_home = game["home_team"] == active_team
        team_score = game["home_score"] if is_home else game["away_score"]
        opp_score = game["away_score"] if is_home else game["home_score"]
        opponent = game["away_team"] if is_home else game["home_team"]
        margin = team_score - opp_score

        game_ref = {
            "season": game["season"],
            "game_id": game["game_id"],
            "opponent": opponent,
            "team_score": team_score,
            "opponent_score": opp_score,
            "margin": margin,
            "is_playoff": game["is_playoff"],
        }
        if margin > 0 and (
            largest_win is None or margin > largest_win["margin"]
        ):
            largest_win = game_ref
        if highest_score is None or team_score > highest_score["team_score"]:
            highest_score = game_ref

        for line in game["player_box_scores"]:
            if _line_team(line) != active_team:
                continue
            player_id = _line_player_id(line)
            for key in player_game_records:
                value = _safe_int(getattr(line, key, 0))
                existing = player_game_records[key]
                if existing is None or value > existing["value"]:
                    player_game_records[key] = {
                        "stat": key,
                        "value": value,
                        "player_id": player_id,
                        "name": _player_name(state, player_id),
                        "season": game["season"],
                        "opponent": opponent,
                        "game_id": game["game_id"],
                    }

    def career_leader(field: str) -> dict[str, Any] | None:
        if not player_rows:
            return None
        row = max(
            player_rows.values(),
            key=lambda item: (item[field], item["games"], item["name"]),
        )
        return {
            "player_id": row["player_id"],
            "name": row["name"],
            "value": row[field],
            "games": row["games"],
        }

    return {
        "best_season": best_season,
        "largest_win": largest_win,
        "highest_team_score": highest_score,
        "career_points": career_leader("points"),
        "career_rebounds": career_leader("rebounds"),
        "career_assists": career_leader("assists"),
        "career_threes": career_leader("threes"),
        "single_game": player_game_records,
    }


def _greatest_games(
    games: list[dict[str, Any]],
    active_team: str,
    state: Any,
    limit: int = 12,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for game in games:
        if active_team not in {game["home_team"], game["away_team"]}:
            continue
        is_home = game["home_team"] == active_team
        team_score = game["home_score"] if is_home else game["away_score"]
        opp_score = game["away_score"] if is_home else game["home_score"]
        opponent = game["away_team"] if is_home else game["home_team"]
        margin = team_score - opp_score
        win = margin > 0

        top_player = ""
        top_points = -1
        for line in game["player_box_scores"]:
            if _line_team(line) != active_team:
                continue
            points = _safe_int(getattr(line, "points", 0))
            if points > top_points:
                top_points = points
                top_player = _player_name(state, _line_player_id(line))

        importance = 0.0
        importance += 18.0 if win else 2.0
        importance += 24.0 if game["is_playoff"] else 0.0
        importance += 8.0 * min(game["overtime_periods"], 3)
        importance += max(0.0, 9.0 - abs(margin)) if margin != 0 else 10.0
        importance += min(max(top_points, 0), 60) * 0.20
        if win and margin >= 20:
            importance += min(margin, 40) * 0.25

        rows.append(
            {
                "season": game["season"],
                "game_id": game["game_id"],
                "opponent": opponent,
                "team_score": team_score,
                "opponent_score": opp_score,
                "margin": margin,
                "result": "W" if win else "L",
                "is_playoff": game["is_playoff"],
                "overtime_periods": game["overtime_periods"],
                "top_player": top_player,
                "top_points": max(top_points, 0),
                "importance_score": round(importance, 2),
            }
        )

    rows.sort(
        key=lambda row: (
            -row["importance_score"],
            -_season_key(row["season"]),
            row["game_id"],
        )
    )
    return rows[:limit]


def _draft_history(
    state: Any,
    active_team: str,
) -> list[dict[str, Any]]:
    history = list(getattr(state, "franchise_draft_history_v1", []) or [])
    rows: list[dict[str, Any]] = []

    for archive in history:
        year = _safe_int(archive.get("draft_year", 0)) if isinstance(archive, dict) else 0
        order = list(archive.get("draft_order", []) or []) if isinstance(archive, dict) else []
        prospects = list(archive.get("prospects", []) or []) if isinstance(archive, dict) else []
        prospect_map = {
            _clean(row.get("prospect_id", "")): dict(row)
            for row in prospects
            if isinstance(row, dict) and _clean(row.get("prospect_id", ""))
        }

        for pick in order:
            if not isinstance(pick, dict):
                continue
            owner = _team(pick.get("owner_team", ""))
            if owner != active_team:
                continue
            prospect_id = _clean(pick.get("prospect_id", ""))
            prospect = prospect_map.get(prospect_id, {})
            player_name = _clean(
                pick.get(
                    "player_name",
                    prospect.get("player_name", prospect_id),
                )
            )
            current_player = getattr(state, "players", {}).get(prospect_id)
            current_team = _team(
                getattr(current_player, "team_abbreviation", "")
            ) if current_player is not None else ""
            current_overall = (
                _safe_float(getattr(current_player, "overall_rating", 0.0))
                if current_player is not None
                else None
            )

            rows.append(
                {
                    "draft_year": year,
                    "overall_pick": _safe_int(pick.get("overall_pick", 0)),
                    "round": _safe_int(pick.get("round", 0)),
                    "round_pick": _safe_int(pick.get("round_pick", 0)),
                    "prospect_id": prospect_id,
                    "name": player_name,
                    "position": _clean(prospect.get("position", "")),
                    "school": _clean(
                        prospect.get(
                            "school",
                            prospect.get("school_club", prospect.get("School / Club", "")),
                        )
                    ),
                    "archetype": _clean(prospect.get("archetype", "")),
                    "current_team": current_team,
                    "current_overall": current_overall,
                    "still_in_league": current_player is not None,
                }
            )

    rows.sort(key=lambda row: (-row["draft_year"], row["overall_pick"]))
    return rows


def _trade_history(
    state: Any,
    trade_state: Any,
    active_team: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in list(getattr(trade_state, "transaction_history", []) or []):
        team_a = _team(getattr(record, "team_a", ""))
        team_b = _team(getattr(record, "team_b", ""))
        if active_team not in {team_a, team_b}:
            continue

        if active_team == team_a:
            partner = team_b
            outgoing_players = list(getattr(record, "team_a_player_ids", ()) or ())
            incoming_players = list(getattr(record, "team_b_player_ids", ()) or ())
            outgoing_picks = list(getattr(record, "team_a_pick_right_ids", ()) or ())
            incoming_picks = list(getattr(record, "team_b_pick_right_ids", ()) or ())
        else:
            partner = team_a
            outgoing_players = list(getattr(record, "team_b_player_ids", ()) or ())
            incoming_players = list(getattr(record, "team_a_player_ids", ()) or ())
            outgoing_picks = list(getattr(record, "team_b_pick_right_ids", ()) or ())
            incoming_picks = list(getattr(record, "team_a_pick_right_ids", ()) or ())

        rows.append(
            {
                "transaction_id": _clean(getattr(record, "transaction_id", "")),
                "state_revision": _safe_int(getattr(record, "state_revision", 0)),
                "trade_date": _clean(getattr(record, "trade_date", "")),
                "partner": partner,
                "outgoing_player_ids": [str(value) for value in outgoing_players],
                "incoming_player_ids": [str(value) for value in incoming_players],
                "outgoing_players": [_player_name(state, str(value)) for value in outgoing_players],
                "incoming_players": [_player_name(state, str(value)) for value in incoming_players],
                "outgoing_picks": [str(value) for value in outgoing_picks],
                "incoming_picks": [str(value) for value in incoming_picks],
                "evaluation_status": _clean(
                    getattr(record, "evaluation_status", "")
                ),
            }
        )

    rows.sort(
        key=lambda row: (
            -row["state_revision"],
            row["transaction_id"],
        )
    )
    return rows


def _league_history(
    state: Any,
    team_names: Mapping[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for archive in list(getattr(state, "season_history", []) or []):
        champion = _team(getattr(archive, "champion", ""))
        runner_up = _team(getattr(archive, "runner_up", ""))
        rows.append(
            {
                "season": _clean(getattr(archive, "season_label", "")),
                "champion": champion,
                "champion_name": _team_name(team_names, champion) if champion else "",
                "runner_up": runner_up,
                "runner_up_name": _team_name(team_names, runner_up) if runner_up else "",
                "conference_champions": _json_safe(
                    getattr(archive, "conference_champions", {}) or {}
                ),
                "postseason_games": _safe_int(
                    getattr(archive, "postseason_games_completed", 0)
                ),
            }
        )
    rows.sort(key=lambda row: -_season_key(row["season"]))
    return rows


def _rivalries(
    games: list[dict[str, Any]],
    active_team: str,
    league_history: list[dict[str, Any]],
    limit: int = 8,
) -> list[dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}

    finals_pairs: set[tuple[str, str]] = set()
    for season in league_history:
        champion = _team(season["champion"])
        runner_up = _team(season["runner_up"])
        if champion and runner_up:
            finals_pairs.add((champion, runner_up))
            finals_pairs.add((runner_up, champion))

    for game in games:
        if active_team not in {game["home_team"], game["away_team"]}:
            continue
        opponent = (
            game["away_team"]
            if game["home_team"] == active_team
            else game["home_team"]
        )
        row = summary.setdefault(
            opponent,
            {
                "opponent": opponent,
                "games": 0,
                "wins": 0,
                "losses": 0,
                "playoff_games": 0,
                "overtime_games": 0,
                "close_games": 0,
                "finals_meetings": 0,
            },
        )
        row["games"] += 1
        is_home = game["home_team"] == active_team
        team_score = game["home_score"] if is_home else game["away_score"]
        opp_score = game["away_score"] if is_home else game["home_score"]
        if team_score > opp_score:
            row["wins"] += 1
        else:
            row["losses"] += 1
        if game["is_playoff"]:
            row["playoff_games"] += 1
        if game["overtime_periods"] > 0:
            row["overtime_games"] += 1
        if abs(team_score - opp_score) <= 5:
            row["close_games"] += 1

    for row in summary.values():
        if (active_team, row["opponent"]) in finals_pairs:
            row["finals_meetings"] = sum(
                1
                for season in league_history
                if {
                    _team(season["champion"]),
                    _team(season["runner_up"]),
                }
                == {active_team, row["opponent"]}
            )
        row["rivalry_score"] = round(
            row["games"]
            + row["playoff_games"] * 3.5
            + row["overtime_games"] * 1.5
            + row["close_games"] * 0.75
            + row["finals_meetings"] * 12.0,
            2,
        )
        score = row["rivalry_score"]
        if score >= 40:
            row["tier"] = "HEATED RIVALRY"
        elif score >= 24:
            row["tier"] = "RIVAL"
        elif score >= 12:
            row["tier"] = "EMERGING"
        else:
            row["tier"] = "HISTORY BUILDING"

    rows = list(summary.values())
    rows.sort(key=lambda row: (-row["rivalry_score"], row["opponent"]))
    return rows[:limit]


def _event_ledger(
    state: Any,
    active_team: str,
    season_rows: list[dict[str, Any]],
    draft_rows: list[dict[str, Any]],
    trade_rows: list[dict[str, Any]],
    team_names: Mapping[str, str],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    for season in season_rows:
        if season["is_current"]:
            continue
        season_label = season["season"]
        if season["result"] == "NBA CHAMPION":
            events.append(
                {
                    "season": season_label,
                    "event_type": "CHAMPIONSHIP",
                    "importance": 100,
                    "title": "NBA Championship",
                    "detail": (
                        f"{_team_name(team_names, active_team)} finished "
                        f"{season['record']} and won the NBA championship."
                    ),
                }
            )
        elif season["result"] == "NBA FINALS":
            events.append(
                {
                    "season": season_label,
                    "event_type": "FINALS",
                    "importance": 88,
                    "title": "NBA Finals Appearance",
                    "detail": (
                        f"{_team_name(team_names, active_team)} reached the NBA Finals "
                        f"after a {season['record']} season."
                    ),
                }
            )
        elif season["result"] == "CONFERENCE CHAMPION":
            events.append(
                {
                    "season": season_label,
                    "event_type": "CONFERENCE_TITLE",
                    "importance": 78,
                    "title": "Conference Championship",
                    "detail": (
                        f"{_team_name(team_names, active_team)} captured a conference title."
                    ),
                }
            )
        elif season["wins"] >= 55:
            events.append(
                {
                    "season": season_label,
                    "event_type": "ELITE_SEASON",
                    "importance": 60,
                    "title": "Elite Regular Season",
                    "detail": f"The franchise won {season['wins']} games.",
                }
            )

    for row in draft_rows:
        events.append(
            {
                "season": str(row["draft_year"]),
                "event_type": "DRAFT",
                "importance": 58 if row["round"] == 1 else 42,
                "title": f"Drafted {row['name']}",
                "detail": (
                    f"Selected {row['name']} at No. {row['overall_pick']} "
                    f"in the {row['draft_year']} Draft."
                ),
            }
        )

    for row in trade_rows:
        outgoing = ", ".join(row["outgoing_players"] + row["outgoing_picks"]) or "assets"
        incoming = ", ".join(row["incoming_players"] + row["incoming_picks"]) or "assets"
        events.append(
            {
                "season": row["trade_date"] or "FRANCHISE TENURE",
                "event_type": "TRADE",
                "importance": 64,
                "title": f"Trade with {row['partner']}",
                "detail": f"Sent {outgoing}; acquired {incoming}.",
            }
        )

    events.sort(
        key=lambda row: (
            -_season_key(row["season"]),
            -_safe_int(row["importance"]),
            row["event_type"],
            row["title"],
        )
    )
    return events


def _era_identity(
    season_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    completed = [row for row in season_rows if not row["is_current"]]
    titles = sum(row["result"] == "NBA CHAMPION" for row in completed)
    finals = sum(row["result"] in {"NBA CHAMPION", "NBA FINALS"} for row in completed)

    recent = completed[-5:]
    recent_titles = sum(row["result"] == "NBA CHAMPION" for row in recent)
    recent_finals = sum(row["result"] in {"NBA CHAMPION", "NBA FINALS"} for row in recent)
    recent_playoffs = sum(row["result_tier"] >= 2 for row in recent)

    current = next((row for row in reversed(season_rows) if row["is_current"]), None)
    current_pct = current["win_pct"] if current and current["games"] >= 10 else None

    if recent_titles >= 3:
        label = "DYNASTY"
        description = "Three or more championships across the latest five completed seasons."
        tier = 5
    elif recent_titles >= 2 or recent_finals >= 3:
        label = "CHAMPIONSHIP ERA"
        description = "Multiple titles or sustained Finals-level contention define this stretch."
        tier = 4
    elif recent_playoffs >= 4:
        label = "CONTENDER WINDOW"
        description = "The franchise has maintained a sustained postseason presence."
        tier = 3
    elif current_pct is not None and current_pct < 0.40:
        label = "REBUILDING ERA"
        description = "The current season profile points toward a rebuilding phase."
        tier = 1
    elif completed:
        label = "BUILDING ERA"
        description = "The franchise is building its current long-term identity."
        tier = 2
    else:
        label = "THE NEXT CHAPTER"
        description = "No completed V3 season has been archived yet."
        tier = 0

    return {
        "label": label,
        "tier": tier,
        "description": description,
        "career_titles": titles,
        "career_finals": finals,
        "recent_titles": recent_titles,
        "recent_finals": recent_finals,
        "recent_playoff_seasons": recent_playoffs,
    }


def _trophy_room(
    season_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    completed = [row for row in season_rows if not row["is_current"]]
    championship_seasons = [
        row["season"] for row in completed if row["result"] == "NBA CHAMPION"
    ]
    finals_seasons = [
        row["season"]
        for row in completed
        if row["result"] in {"NBA CHAMPION", "NBA FINALS"}
    ]
    conference_title_seasons = [
        row["season"]
        for row in completed
        if row["result"]
        in {"NBA CHAMPION", "NBA FINALS", "CONFERENCE CHAMPION"}
    ]
    playoff_seasons = [
        row["season"] for row in completed if row["result_tier"] >= 2
    ]

    return {
        "championships": len(championship_seasons),
        "championship_seasons": championship_seasons,
        "finals_appearances": len(finals_seasons),
        "finals_seasons": finals_seasons,
        "conference_titles": len(conference_title_seasons),
        "conference_title_seasons": conference_title_seasons,
        "playoff_appearances": len(playoff_seasons),
        "playoff_seasons": playoff_seasons,
    }


def _gm_resume(
    season_rows: list[dict[str, Any]],
    trophy_room: dict[str, Any],
    draft_rows: list[dict[str, Any]],
    trade_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    completed = [row for row in season_rows if not row["is_current"]]
    wins = sum(row["wins"] for row in completed)
    losses = sum(row["losses"] for row in completed)
    games = wins + losses
    return {
        "completed_seasons": len(completed),
        "career_wins": wins,
        "career_losses": losses,
        "career_record": f"{wins}-{losses}",
        "career_win_pct": round(wins / games, 4) if games else 0.0,
        "championships": trophy_room["championships"],
        "finals_appearances": trophy_room["finals_appearances"],
        "conference_titles": trophy_room["conference_titles"],
        "playoff_appearances": trophy_room["playoff_appearances"],
        "draft_selections": len(draft_rows),
        "trades_completed": len(trade_rows),
    }


def build_franchise_legacy_payload(
    checkpoint: Any,
    *,
    team_names: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    state = getattr(checkpoint, "simulation_state", None)
    trade_state = getattr(checkpoint, "trade_state", None)
    if state is None:
        raise RuntimeError("V3 working checkpoint has no simulation state.")
    if trade_state is None:
        raise RuntimeError("V3 working checkpoint has no durable trade state.")

    names: Mapping[str, str] = team_names or {}
    active_team = _active_team(checkpoint)
    if not active_team:
        raise RuntimeError("V3 working checkpoint has no active franchise team.")

    season_rows = _season_rows(state, active_team, names)
    games = _all_games(state)
    player_rows = _franchise_player_aggregates(state, active_team, games)
    legends = sorted(
        player_rows.values(),
        key=lambda row: (-row["legacy_score"], -row["points"], row["name"]),
    )[:12]
    draft_rows = _draft_history(state, active_team)
    trade_rows = _trade_history(state, trade_state, active_team)
    league_history = _league_history(state, names)
    trophy_room = _trophy_room(season_rows)
    era = _era_identity(season_rows)
    records = _records(
        season_rows,
        games,
        active_team,
        player_rows,
        state,
    )
    greatest_games = _greatest_games(
        games,
        active_team,
        state,
        limit=12,
    )
    rivalries = _rivalries(
        games,
        active_team,
        league_history,
        limit=8,
    )
    ledger = _event_ledger(
        state,
        active_team,
        season_rows,
        draft_rows,
        trade_rows,
        names,
    )
    gm_resume = _gm_resume(
        season_rows,
        trophy_room,
        draft_rows,
        trade_rows,
    )

    completed = [row for row in season_rows if not row["is_current"]]
    current = next((row for row in reversed(season_rows) if row["is_current"]), None)
    best_season = records.get("best_season")

    return {
        "foundation_version": FRANCHISE_LEGACY_FOUNDATION_VERSION,
        "read_only": True,
        "working_save_only": True,
        "active_v2_read_only": True,
        "team": active_team,
        "team_name": _team_name(names, active_team),
        "current_season": (
            current["season"] if current else _clean(
                getattr(getattr(state, "settings", None), "season_label", "")
            )
        ),
        "tenure": {
            "completed_seasons": len(completed),
            "current_season": current,
            "best_season": best_season,
            "era": era,
            "gm_resume": gm_resume,
        },
        "trophy_room": trophy_room,
        "season_timeline": list(reversed(season_rows)),
        "records": records,
        "legends": legends,
        "greatest_games": greatest_games,
        "draft_history": draft_rows,
        "trade_history": trade_rows,
        "event_ledger": ledger[:80],
        "rivalries": rivalries,
        "league_history": league_history,
        "counts": {
            "archived_seasons": len(completed),
            "franchise_games_indexed": sum(
                1
                for game in games
                if active_team in {game["home_team"], game["away_team"]}
            ),
            "legacy_players": len(player_rows),
            "draft_selections": len(draft_rows),
            "trades": len(trade_rows),
            "events": len(ledger),
            "rivalries": len(rivalries),
        },
        "empty_state": {
            "has_completed_history": bool(completed),
            "headline": (
                "THE NEXT CHAPTER STARTS HERE"
                if not completed
                else "THE FRANCHISE HAS A HISTORY"
            ),
            "detail": (
                "No completed V3 season has been archived yet. Championships, records, "
                "draft classes, rivalries, and front-office milestones will accumulate here."
                if not completed
                else "Completed seasons are now part of the permanent franchise legacy view."
            ),
        },
    }
