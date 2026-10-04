"""Read-only current-season momentum derived from scheduled, saved games."""
from __future__ import annotations
from typing import Any


def build_season_momentum(state: Any, team: str) -> dict[str, Any]:
    standing = state.standings.get(team)
    wins = int(getattr(standing, "wins", 0)) if standing is not None else None
    rows = []
    for game_id, game in state.completed_games.items():
        scheduled = state.schedule.get(str(game_id))
        if scheduled is None or team not in (game.home_team, game.away_team):
            continue
        home = team == game.home_team
        scored = int(game.home_score if home else game.away_score)
        allowed = int(game.away_score if home else game.home_score)
        rows.append(dict(game_id=str(game_id), day_index=int(scheduled.day_index),
            opponent=str(game.away_team if home else game.home_team),
            venue="HOME" if home else "AWAY", scored=scored, allowed=allowed,
            margin=scored-allowed, result="W" if scored > allowed else "L" if scored < allowed else "T"))
    rows.sort(key=lambda row: (row["day_index"], row["game_id"]))
    cumulative = 0
    for index, row in enumerate(rows):
        cumulative += row["margin"]
        row["game_number"] = index + 1
        row["cumulative_margin"] = cumulative
    scheduled_rows = []
    for game in state.schedule.values():
        status = getattr(game, "status", None)
        if str(getattr(status, "value", status)).lower() != "scheduled":
            continue
        if team not in (game.home_team, game.away_team):
            continue
        home = team == game.home_team
        scheduled_rows.append(dict(game_id=str(game.game_id), day_index=int(game.day_index),
            opponent=str(game.away_team if home else game.home_team),
            venue="HOME" if home else "AWAY"))
    scheduled_rows.sort(key=lambda row: (row["day_index"], row["game_id"]))
    previous_day = rows[-1]["day_index"] if rows else None
    next_games = []
    for game in scheduled_rows[:5]:
        gap = game["day_index"] - previous_day if previous_day is not None else None
        game.update(days_until=game["day_index"]-int(getattr(state,"current_day_index",0)),
            rest_days=max(0,gap-1) if gap is not None else None,
            back_to_back=gap == 1)
        next_games.append(game)
        previous_day = game["day_index"]
    milestones = [dict(target=target, title=title, achieved=wins is not None and wins >= target,
        progress=min(wins, target) if wins is not None else None)
        for target, title in ((1,"First victory"),(10,"Finding momentum"),(25,"Building a contender"),(40,"Forty-win season"))]
    upcoming = next((item for item in milestones if not item["achieved"]), None)
    return dict(team=team, season=str(state.settings.season_label), wins=wins,
        next_games=next_games, games_tracked=len(rows), recent=rows[-5:], trend=rows,
        milestones=milestones, next_target=upcoming,
        recent_wins=sum(row["result"] == "W" for row in rows[-5:]),
        cumulative_margin=cumulative if rows else None,
        read_only=True, scope="Current season games linked to the saved regular-season schedule")
