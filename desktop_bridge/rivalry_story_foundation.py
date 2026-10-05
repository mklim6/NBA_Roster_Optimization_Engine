"""Expansion 48: evidence-based rivalries and league storylines.

All storylines are reconstructed from saved simulation state. This module never writes
a checkpoint and never invents historical NBA results that are not present in the save.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, is_dataclass
from typing import Any, Mapping
import math

RIVALRY_STORY_FOUNDATION_VERSION = "v3-rivalries-league-stories-expansion-48-v1.0.0-2026-10-05"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _enum(value: Any) -> str:
    return _clean(getattr(value, "value", value)).lower()


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


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return _clean(value)
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
    if hasattr(value, "__dict__"):
        return {
            str(key): _json_safe(item, depth=depth + 1)
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }
    return _clean(value)


def _name(names: Mapping[str, str], abbreviation: str) -> str:
    key = _team(abbreviation)
    return str(names.get(key, key))


def _season_key(label: str) -> int:
    text = _clean(label)
    try:
        return int(text.split("-")[0])
    except (TypeError, ValueError):
        return 0


def _postseason_games(postseason: Any) -> list[Any]:
    if postseason is None:
        return []
    completed = getattr(postseason, "completed_games", None)
    if isinstance(completed, Mapping):
        return list(completed.values())
    if isinstance(completed, (list, tuple)):
        return list(completed)
    games = getattr(postseason, "games", None)
    if isinstance(games, Mapping):
        return [
            game
            for game in games.values()
            if _enum(getattr(game, "status", "")) == "completed"
        ]
    return []


def _game_row(game: Any, season: str, *, playoff: bool, day: int | None = None) -> dict[str, Any] | None:
    if game is None:
        return None
    home = _team(getattr(game, "home_team", ""))
    away = _team(getattr(game, "away_team", ""))
    if not home or not away:
        return None
    home_score = _safe_int(getattr(game, "home_score", 0))
    away_score = _safe_int(getattr(game, "away_score", 0))
    return {
        "game_id": _clean(getattr(game, "game_id", "")),
        "season": _clean(season),
        "season_key": _season_key(season),
        "day": day,
        "home_team": home,
        "away_team": away,
        "home_score": home_score,
        "away_score": away_score,
        "margin": abs(home_score - away_score),
        "overtime_periods": _safe_int(getattr(game, "overtime_periods", 0)),
        "is_playoff": bool(playoff),
        "winner": home if home_score > away_score else away if away_score > home_score else "",
    }


def _all_completed_games(state: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, bool]] = set()

    for archive in list(getattr(state, "season_history", []) or []):
        season = _clean(getattr(archive, "season_label", ""))
        for game in dict(getattr(archive, "completed_games", {}) or {}).values():
            row = _game_row(game, season, playoff=False)
            if row is None:
                continue
            key = (season, row["game_id"], False)
            if key not in seen:
                seen.add(key)
                row["sequence"] = len(rows)
                rows.append(row)

        postseason = getattr(archive, "postseason_state", None)
        for game in _postseason_games(postseason):
            row = _game_row(game, season, playoff=True)
            if row is None:
                continue
            key = (season, row["game_id"], True)
            if key not in seen:
                seen.add(key)
                row["sequence"] = len(rows)
                rows.append(row)

    live_season = _clean(getattr(getattr(state, "settings", None), "season_label", ""))
    schedule = dict(getattr(state, "schedule", {}) or {})
    for game_id, game in dict(getattr(state, "completed_games", {}) or {}).items():
        scheduled = schedule.get(str(game_id)) or schedule.get(game_id)
        day = (
            _safe_int(getattr(scheduled, "day_index", 0))
            if scheduled is not None
            else None
        )
        row = _game_row(game, live_season, playoff=False, day=day)
        if row is None:
            continue
        key = (live_season, row["game_id"], False)
        if key not in seen:
            seen.add(key)
            row["sequence"] = len(rows)
            rows.append(row)

    for game in _postseason_games(getattr(state, "postseason_state", None)):
        row = _game_row(game, live_season, playoff=True)
        if row is None:
            continue
        key = (live_season, row["game_id"], True)
        if key not in seen:
            seen.add(key)
            row["sequence"] = len(rows)
            rows.append(row)

    rows.sort(
        key=lambda row: (
            row["season_key"],
            int(row.get("sequence", 0)),
        )
    )
    return rows


def _league_history(state: Any) -> list[dict[str, Any]]:
    rows = []
    for archive in list(getattr(state, "season_history", []) or []):
        champion = _team(getattr(archive, "champion", ""))
        runner_up = _team(getattr(archive, "runner_up", ""))
        rows.append(
            {
                "season": _clean(getattr(archive, "season_label", "")),
                "champion": champion,
                "runner_up": runner_up,
            }
        )
    rows.sort(key=lambda row: _season_key(row["season"]))
    return rows


def _upcoming_games(state: Any, names: Mapping[str, str]) -> list[dict[str, Any]]:
    rows = []
    current_day = _safe_int(getattr(state, "current_day_index", 0))
    for game_id, game in dict(getattr(state, "schedule", {}) or {}).items():
        if _enum(getattr(game, "status", "")) != "scheduled":
            continue
        home = _team(getattr(game, "home_team", ""))
        away = _team(getattr(game, "away_team", ""))
        day = _safe_int(getattr(game, "day_index", 0))
        if not home or not away or day < current_day:
            continue
        rows.append(
            {
                "game_id": str(game_id),
                "day": day,
                "days_away": max(0, day - current_day),
                "home_team": home,
                "home_name": _name(names, home),
                "away_team": away,
                "away_name": _name(names, away),
            }
        )
    rows.sort(key=lambda row: (row["day"], row["game_id"]))
    return rows


def _standing_context(state: Any, team: str) -> dict[str, Any]:
    standing = dict(getattr(state, "standings", {}) or {}).get(team)
    if standing is None:
        return {
            "games": 0,
            "wins": 0,
            "losses": 0,
            "record": "0-0",
            "win_pct": 0.0,
            "streak": "",
            "streak_length": 0,
        }
    games = _safe_int(getattr(standing, "games_played", 0))
    wins = _safe_int(getattr(standing, "wins", 0))
    losses = _safe_int(getattr(standing, "losses", 0))
    streak_type = _clean(getattr(standing, "streak_type", ""))
    streak_length = _safe_int(getattr(standing, "streak_length", 0))
    return {
        "games": games,
        "wins": wins,
        "losses": losses,
        "record": f"{wins}-{losses}",
        "win_pct": round(wins / games, 4) if games else 0.0,
        "streak": f"{streak_type}{streak_length}" if streak_type else "",
        "streak_length": streak_length,
    }


def _current_roster_ids(state: Any, team: str) -> list[str]:
    team_state = dict(getattr(state, "teams", {}) or {}).get(team)
    if team_state is None:
        return []
    return [str(value) for value in list(getattr(team_state, "roster_player_ids", ()) or ())]


def _player_line(state: Any, player_id: str) -> dict[str, Any]:
    player = dict(getattr(state, "players", {}) or {}).get(player_id)
    if player is None:
        return {
            "player_id": player_id,
            "name": player_id,
            "team": "",
            "position": "",
            "age": None,
            "overall": None,
            "ppg": None,
            "rpg": None,
            "apg": None,
        }
    totals = dict(getattr(state, "player_season_totals", {}) or {}).get(player_id)
    games = _safe_int(getattr(totals, "games_played", 0)) if totals is not None else 0

    def per_game(field: str) -> float | None:
        if totals is None or games <= 0:
            return None
        return round(_safe_float(getattr(totals, field, 0.0)) / games, 1)

    return {
        "player_id": player_id,
        "name": _clean(getattr(player, "player_name", player_id)),
        "team": _team(getattr(player, "team_abbreviation", "")),
        "position": _clean(getattr(player, "position", "")),
        "age": _safe_float(getattr(player, "age", 0.0)),
        "overall": round(_safe_float(getattr(player, "overall_rating", 0.0)), 1),
        "ppg": per_game("points"),
        "rpg": per_game("rebounds"),
        "apg": per_game("assists"),
    }


def _team_star(state: Any, team: str) -> dict[str, Any] | None:
    rows = [_player_line(state, pid) for pid in _current_roster_ids(state, team)]
    if not rows:
        return None
    rows.sort(
        key=lambda row: (
            -_safe_float(row.get("overall")),
            -_safe_float(row.get("ppg")),
            row.get("name", ""),
        )
    )
    return rows[0]


def _finals_pairs(history: list[dict[str, Any]]) -> dict[tuple[str, str], list[str]]:
    pairs: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in history:
        champion = _team(row.get("champion"))
        runner_up = _team(row.get("runner_up"))
        if not champion or not runner_up:
            continue
        key = tuple(sorted((champion, runner_up)))
        pairs[key].append(_clean(row.get("season")))
    return pairs


def _series_history(
    opponent: str,
    games: list[dict[str, Any]],
    active_team: str,
) -> list[dict[str, Any]]:
    by_season: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for game in games:
        if not game["is_playoff"]:
            continue
        if {game["home_team"], game["away_team"]} != {active_team, opponent}:
            continue
        by_season[game["season"]].append(game)

    rows = []
    for season, season_games in by_season.items():
        team_wins = sum(game["winner"] == active_team for game in season_games)
        opponent_wins = sum(game["winner"] == opponent for game in season_games)
        winner = ""
        if team_wins >= 4 and team_wins > opponent_wins:
            winner = active_team
        elif opponent_wins >= 4 and opponent_wins > team_wins:
            winner = opponent
        rows.append(
            {
                "season": season,
                "games": len(season_games),
                "team_wins": team_wins,
                "opponent_wins": opponent_wins,
                "record": f"{team_wins}-{opponent_wins}",
                "winner": winner,
                "complete_best_of_seven": bool(winner),
            }
        )
    rows.sort(key=lambda row: _season_key(row["season"]), reverse=True)
    return rows


def _head_to_head_streak(timeline: list[dict[str, Any]]) -> dict[str, Any]:
    if not timeline:
        return {"result": "", "count": 0}
    latest = timeline[-1]["result"]
    count = 0
    for row in reversed(timeline):
        if row["result"] != latest:
            break
        count += 1
    return {"result": latest, "count": count}


def _tier(score: float) -> str:
    if score >= 70:
        return "HISTORIC"
    if score >= 45:
        return "MAJOR"
    if score >= 25:
        return "HEATED"
    if score >= 12:
        return "EMERGING"
    return "HISTORY BUILDING"


def _rivalry_profiles(
    state: Any,
    active_team: str,
    names: Mapping[str, str],
    games: list[dict[str, Any]],
    history: list[dict[str, Any]],
    upcoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    finals = _finals_pairs(history)
    by_opponent: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for game in games:
        if active_team not in {game["home_team"], game["away_team"]}:
            continue
        opponent = game["away_team"] if game["home_team"] == active_team else game["home_team"]
        by_opponent[opponent].append(game)

    # Every future opponent gets a truthful "history building" profile even if
    # no completed V3 matchup has occurred yet.
    for game in upcoming:
        if active_team in {game["home_team"], game["away_team"]}:
            opponent = game["away_team"] if game["home_team"] == active_team else game["home_team"]
            by_opponent.setdefault(opponent, [])

    profiles = []
    for opponent, opponent_games in by_opponent.items():
        opponent_games.sort(
            key=lambda row: (
                row["season_key"],
                int(row.get("sequence", 0)),
            )
        )
        timeline = []
        wins = losses = playoff_games = overtime_games = close_games = 0
        season_results: dict[str, dict[str, int]] = defaultdict(lambda: {"wins": 0, "losses": 0})

        for game in opponent_games:
            is_home = game["home_team"] == active_team
            team_score = game["home_score"] if is_home else game["away_score"]
            opp_score = game["away_score"] if is_home else game["home_score"]
            result = "W" if team_score > opp_score else "L" if team_score < opp_score else "T"
            if result == "W":
                wins += 1
                season_results[game["season"]]["wins"] += 1
            elif result == "L":
                losses += 1
                season_results[game["season"]]["losses"] += 1
            if game["is_playoff"]:
                playoff_games += 1
            if game["overtime_periods"] > 0:
                overtime_games += 1
            if game["margin"] <= 5:
                close_games += 1
            timeline.append(
                {
                    "season": game["season"],
                    "day": game["day"],
                    "game_id": game["game_id"],
                    "result": result,
                    "team_score": team_score,
                    "opponent_score": opp_score,
                    "margin": abs(team_score - opp_score),
                    "is_playoff": game["is_playoff"],
                    "overtime_periods": game["overtime_periods"],
                }
            )

        pair_key = tuple(sorted((active_team, opponent)))
        finals_seasons = list(finals.get(pair_key, []))
        series = _series_history(opponent, games, active_team)
        playoff_meetings = len(series)
        eliminations_for = sum(row["winner"] == active_team for row in series)
        eliminations_against = sum(row["winner"] == opponent for row in series)

        score = (
            len(opponent_games)
            + playoff_games * 3.5
            + playoff_meetings * 5.0
            + overtime_games * 1.5
            + close_games * 0.75
            + len(finals_seasons) * 15.0
            + (eliminations_for + eliminations_against) * 4.0
        )
        score = round(score, 2)

        next_games = [
            row for row in upcoming
            if {row["home_team"], row["away_team"]} == {active_team, opponent}
        ]
        next_meeting = next_games[0] if next_games else None
        latest = timeline[-1] if timeline else None
        streak = _head_to_head_streak(timeline)

        if timeline:
            narrative = (
                f"{_name(names, active_team)} leads the saved V3 series {wins}-{losses}."
                if wins > losses
                else (
                    f"{_name(names, opponent)} leads the saved V3 series {losses}-{wins}."
                    if losses > wins
                    else f"The saved V3 series is even at {wins}-{losses}."
                )
            )
        else:
            narrative = "No completed V3 meeting yet. The first chapter is still waiting."

        profiles.append(
            {
                "opponent": opponent,
                "opponent_name": _name(names, opponent),
                "games": len(opponent_games),
                "wins": wins,
                "losses": losses,
                "record": f"{wins}-{losses}",
                "playoff_games": playoff_games,
                "playoff_meetings": playoff_meetings,
                "finals_meetings": len(finals_seasons),
                "finals_seasons": finals_seasons,
                "overtime_games": overtime_games,
                "close_games": close_games,
                "eliminations_for": eliminations_for,
                "eliminations_against": eliminations_against,
                "heat_score": score,
                "tier": _tier(score),
                "latest": latest,
                "next_meeting": next_meeting,
                "head_to_head_streak": streak,
                "series_history": series,
                "timeline": list(reversed(timeline[-16:])),
                "season_results": [
                    {
                        "season": season,
                        "wins": result["wins"],
                        "losses": result["losses"],
                        "record": f"{result['wins']}-{result['losses']}",
                    }
                    for season, result in sorted(
                        season_results.items(),
                        key=lambda item: _season_key(item[0]),
                        reverse=True,
                    )
                ],
                "narrative": narrative,
            }
        )

    profiles.sort(
        key=lambda row: (
            -row["heat_score"],
            -row["playoff_meetings"],
            -row["games"],
            row["opponent"],
        )
    )
    return profiles


def _departed_players(checkpoint: Any, active_team: str) -> dict[str, set[str]]:
    """Map current opponent -> players previously sent away by active team."""
    state = checkpoint.simulation_state
    departed: set[str] = set()

    for row in list(getattr(state, "franchise_transaction_history_v1", []) or []):
        if not isinstance(row, Mapping) or row.get("status") != "committed":
            continue
        team_a = _team(row.get("team_a"))
        team_b = _team(row.get("team_b"))
        if active_team == team_a:
            departed.update(str(value) for value in row.get("side_a_player_ids", []) or [])
        elif active_team == team_b:
            departed.update(str(value) for value in row.get("side_b_player_ids", []) or [])

    trade_state = getattr(checkpoint, "trade_state", None)
    for record in list(getattr(trade_state, "transaction_history", []) or []):
        team_a = _team(getattr(record, "team_a", ""))
        team_b = _team(getattr(record, "team_b", ""))
        if active_team == team_a:
            departed.update(
                str(value) for value in list(getattr(record, "team_a_player_ids", ()) or ())
            )
        elif active_team == team_b:
            departed.update(
                str(value) for value in list(getattr(record, "team_b_player_ids", ()) or ())
            )

    by_team: dict[str, set[str]] = defaultdict(set)
    for player_id in departed:
        player = dict(getattr(state, "players", {}) or {}).get(player_id)
        current_team = _team(getattr(player, "team_abbreviation", "")) if player else ""
        if current_team and current_team != active_team:
            by_team[current_team].add(player_id)
    return dict(by_team)


def _former_player_returns(
    checkpoint: Any,
    active_team: str,
    names: Mapping[str, str],
    upcoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    state = checkpoint.simulation_state
    departed = _departed_players(checkpoint, active_team)
    rows = []
    for opponent, ids in departed.items():
        next_game = next(
            (
                game for game in upcoming
                if {game["home_team"], game["away_team"]} == {active_team, opponent}
            ),
            None,
        )
        if next_game is None:
            continue
        for player_id in sorted(ids):
            player = _player_line(state, player_id)
            rows.append(
                {
                    "player_id": player_id,
                    "name": player["name"],
                    "opponent": opponent,
                    "opponent_name": _name(names, opponent),
                    "day": next_game["day"],
                    "days_away": next_game["days_away"],
                    "game_id": next_game["game_id"],
                    "overall": player["overall"],
                    "position": player["position"],
                    "evidence": "Committed franchise transaction history + current roster assignment",
                }
            )
    rows.sort(key=lambda row: (row["day"], -_safe_float(row["overall"]), row["name"]))
    return rows


def _star_matchup(state: Any, active_team: str, opponent: str) -> dict[str, Any]:
    left = _team_star(state, active_team)
    right = _team_star(state, opponent)
    return {
        "active": left,
        "opponent": right,
        "available": left is not None and right is not None,
        "evidence": "Current roster ratings and recorded season totals",
    }


def _story(
    category: str,
    title: str,
    detail: str,
    destination: str,
    evidence: str,
    priority: int,
    *,
    opponent: str = "",
    player_id: str = "",
    game_id: str = "",
    day: int | None = None,
) -> dict[str, Any]:
    return {
        "category": category,
        "title": title,
        "detail": detail,
        "destination": destination,
        "evidence": evidence,
        "priority": priority,
        "opponent": opponent,
        "player_id": player_id,
        "game_id": game_id,
        "day": day,
    }


def _active_stories(
    state: Any,
    checkpoint: Any,
    active_team: str,
    names: Mapping[str, str],
    profiles: list[dict[str, Any]],
    upcoming: list[dict[str, Any]],
    returns: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    stories: list[dict[str, Any]] = []
    next_game = next(
        (
            game for game in upcoming
            if active_team in {game["home_team"], game["away_team"]}
        ),
        None,
    )
    profile_by_opponent = {row["opponent"]: row for row in profiles}

    featured = None
    if next_game is not None:
        opponent = (
            next_game["away_team"]
            if next_game["home_team"] == active_team
            else next_game["home_team"]
        )
        profile = profile_by_opponent.get(opponent, {})
        opponent_name = _name(names, opponent)
        reasons: list[str] = []
        headline = f"NEXT UP • {opponent_name}"
        category = "MATCHUP WATCH"

        if _safe_int(profile.get("finals_meetings")) > 0:
            headline = f"FINALS REMATCH • {opponent_name}"
            category = "FINALS REMATCH"
            reasons.append(
                f"{profile['finals_meetings']} saved V3 Finals meeting(s)"
            )
        elif _safe_int(profile.get("playoff_meetings")) > 0:
            headline = f"PLAYOFF REMATCH • {opponent_name}"
            category = "PLAYOFF REMATCH"
            reasons.append(
                f"{profile['playoff_meetings']} saved V3 playoff meeting(s)"
            )
        elif _safe_float(profile.get("heat_score")) >= 25:
            headline = f"{profile.get('tier', 'HEATED')} RIVALRY • {opponent_name}"
            category = "RIVALRY"
            reasons.append(
                f"Rivalry heat {float(profile.get('heat_score', 0.0)):.1f}"
            )

        latest = profile.get("latest")
        if isinstance(latest, Mapping) and latest.get("result") == "L":
            reasons.append("Your franchise lost the most recent saved meeting")
            stories.append(
                _story(
                    "REVENGE GAME",
                    f"Revenge opportunity against {opponent_name}",
                    (
                        f"The last saved meeting ended {latest.get('team_score')}-"
                        f"{latest.get('opponent_score')}. The rematch is scheduled for "
                        f"league day {next_game['day']}."
                    ),
                    "GAME DAY",
                    "Saved head-to-head result + current schedule",
                    0,
                    opponent=opponent,
                    game_id=next_game["game_id"],
                    day=next_game["day"],
                )
            )

        matchup_returns = [row for row in returns if row["opponent"] == opponent]
        if matchup_returns:
            reasons.append(
                f"{len(matchup_returns)} former franchise player(s) now on the opponent"
            )

        star = _star_matchup(state, active_team, opponent)
        if star["available"]:
            left = star["active"]
            right = star["opponent"]
            stories.append(
                _story(
                    "STAR MATCHUP",
                    f"{left['name']} vs {right['name']}",
                    (
                        f"Current roster leaders by overall rating: "
                        f"{left['name']} {left['overall']:.1f} OVR and "
                        f"{right['name']} {right['overall']:.1f} OVR."
                    ),
                    "STORIES",
                    star["evidence"],
                    2,
                    opponent=opponent,
                    game_id=next_game["game_id"],
                    day=next_game["day"],
                )
            )

        active_standing = _standing_context(state, active_team)
        opponent_standing = _standing_context(state, opponent)
        if (
            active_standing["games"] >= 10
            and opponent_standing["games"] >= 10
            and active_standing["win_pct"] >= 0.60
            and opponent_standing["win_pct"] >= 0.60
        ):
            reasons.append("Both clubs are currently playing at a .600+ pace")
            stories.append(
                _story(
                    "CONTENDER CLASH",
                    f"{_name(names, active_team)} and {opponent_name} collide",
                    (
                        f"{active_standing['record']} vs {opponent_standing['record']} "
                        f"on league day {next_game['day']}."
                    ),
                    "GAME DAY",
                    "Current standings + current schedule",
                    1,
                    opponent=opponent,
                    game_id=next_game["game_id"],
                    day=next_game["day"],
                )
            )

        is_home = next_game["home_team"] == active_team
        featured = {
            **next_game,
            "opponent": opponent,
            "opponent_name": opponent_name,
            "is_home": is_home,
            "headline": headline,
            "category": category,
            "reasons": reasons,
            "rivalry": profile,
            "star_matchup": star,
            "former_player_returns": matchup_returns,
        }

        if _safe_float(profile.get("heat_score")) >= 12:
            stories.append(
                _story(
                    "RIVALRY",
                    f"{profile.get('tier', 'EMERGING')} • {opponent_name}",
                    (
                        f"Saved V3 head-to-head {profile.get('record', '0-0')} • "
                        f"{profile.get('playoff_games', 0)} playoff game(s) • "
                        f"{profile.get('close_games', 0)} close finish(es)."
                    ),
                    "STORIES",
                    "Archived and current saved game results",
                    1,
                    opponent=opponent,
                    game_id=next_game["game_id"],
                    day=next_game["day"],
                )
            )

    for row in returns[:8]:
        stories.append(
            _story(
                "RETURN GAME",
                f"{row['name']} returns with {row['opponent_name']}",
                (
                    f"A player previously traded away by the franchise is now scheduled "
                    f"to face you on league day {row['day']}."
                ),
                "LOCKER ROOM",
                row["evidence"],
                1,
                opponent=row["opponent"],
                player_id=row["player_id"],
                game_id=row["game_id"],
                day=row["day"],
            )
        )

    stories.sort(
        key=lambda row: (
            row["priority"],
            row["day"] if row["day"] is not None else 999999,
            row["category"],
            row["title"],
        )
    )
    return stories, featured


def _league_story_wire(
    state: Any,
    names: Mapping[str, str],
    history: list[dict[str, Any]],
    upcoming: list[dict[str, Any]],
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    finals = _finals_pairs(history)
    stories = []

    for game in upcoming:
        home = game["home_team"]
        away = game["away_team"]
        pair = tuple(sorted((home, away)))
        home_standing = _standing_context(state, home)
        away_standing = _standing_context(state, away)
        reasons = []
        weight = 99

        finals_seasons = finals.get(pair, [])
        if finals_seasons:
            reasons.append(
                f"Finals rematch from {', '.join(finals_seasons[-2:])}"
            )
            weight = min(weight, 0)

        if (
            home_standing["games"] >= 10
            and away_standing["games"] >= 10
            and home_standing["win_pct"] >= 0.60
            and away_standing["win_pct"] >= 0.60
        ):
            reasons.append(
                f"Contender clash • {home_standing['record']} vs {away_standing['record']}"
            )
            weight = min(weight, 1)

        if max(home_standing["streak_length"], away_standing["streak_length"]) >= 5:
            streak_team = (
                home if home_standing["streak_length"] >= away_standing["streak_length"] else away
            )
            streak = (
                home_standing["streak"]
                if streak_team == home
                else away_standing["streak"]
            )
            reasons.append(f"{_name(names, streak_team)} carries a {streak} streak")
            weight = min(weight, 2)

        if not reasons:
            continue

        stories.append(
            {
                "category": "LEAGUE STORY",
                "title": f"{_name(names, away)} at {_name(names, home)}",
                "detail": " • ".join(reasons),
                "day": game["day"],
                "days_away": game["days_away"],
                "game_id": game["game_id"],
                "home_team": home,
                "away_team": away,
                "home_name": _name(names, home),
                "away_name": _name(names, away),
                "priority": weight,
                "evidence": "Current schedule, standings, streaks, and saved Finals history",
            }
        )

    stories.sort(
        key=lambda row: (row["priority"], row["day"], row["game_id"])
    )
    return stories[:limit]


def _pulse_cards(stories: list[dict[str, Any]], profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards = []
    for story in stories[:2]:
        cards.append(
            {
                "id": "story:" + story["category"].lower().replace(" ", "-") + ":" + str(story.get("game_id", "")),
                "category": story["category"],
                "title": story["title"],
                "detail": story["detail"],
                "destination": "STORIES",
                "evidence": story["evidence"],
                "priority": min(2, int(story["priority"])),
                "player_id": story.get("player_id", ""),
                "opponent": story.get("opponent", ""),
            }
        )

    if not cards and profiles:
        top = profiles[0]
        if top["games"] > 0:
            cards.append(
                {
                    "id": "story:rivalry:" + top["opponent"],
                    "category": "RIVALRY WATCH",
                    "title": f"{top['tier']} • {top['opponent_name']}",
                    "detail": (
                        f"Saved V3 head-to-head {top['record']} with "
                        f"{top['playoff_games']} playoff game(s) and "
                        f"{top['close_games']} close finish(es)."
                    ),
                    "destination": "STORIES",
                    "evidence": "Saved franchise matchup history",
                    "priority": 2,
                    "player_id": "",
                    "opponent": top["opponent"],
                }
            )
    return cards


def build_rivalry_story_universe(
    checkpoint: Any,
    active_team: str,
    names: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    names = dict(names or {})
    state = checkpoint.simulation_state
    active_team = _team(active_team)
    if not active_team:
        raise ValueError("Select an active franchise before loading league stories.")

    games = _all_completed_games(state)
    history = _league_history(state)
    upcoming = _upcoming_games(state, names)
    profiles = _rivalry_profiles(
        state,
        active_team,
        names,
        games,
        history,
        upcoming,
    )
    returns = _former_player_returns(
        checkpoint,
        active_team,
        names,
        upcoming,
    )
    stories, featured = _active_stories(
        state,
        checkpoint,
        active_team,
        names,
        profiles,
        upcoming,
        returns,
    )
    league_wire = _league_story_wire(state, names, history, upcoming)

    current_day = _safe_int(getattr(state, "current_day_index", 0))
    season = _clean(getattr(getattr(state, "settings", None), "season_label", ""))
    phase = _enum(getattr(state, "phase", ""))

    return {
        "foundation_version": RIVALRY_STORY_FOUNDATION_VERSION,
        "read_only": True,
        "working_save_write_performed": False,
        "active_v2_read_only": True,
        "team": active_team,
        "team_name": _name(names, active_team),
        "season": season,
        "phase": phase,
        "day": current_day,
        "featured_matchup": featured,
        "rivalries": profiles[:12],
        "active_stories": stories[:16],
        "former_player_returns": returns[:12],
        "league_story_wire": league_wire,
        "pulse_cards": _pulse_cards(stories, profiles),
        "archive": {
            "completed_game_count": len(games),
            "season_history_count": len(history),
            "upcoming_game_count": len(upcoming),
        },
        "scope": {
            "evidence_only": True,
            "note": (
                "Rivalries are reconstructed from this save's completed games, playoff history, "
                "Finals history, transaction history, current rosters, standings, streaks, and schedule. "
                "No historical NBA rivalry is assumed when the V3 universe has not recorded it."
            ),
            "series_note": (
                "A playoff elimination is only credited when one side has at least four saved wins "
                "against the other in that postseason meeting."
            ),
        },
    }
