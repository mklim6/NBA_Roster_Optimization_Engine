"""Durable season commitments evaluated from recorded franchise outcomes."""
from __future__ import annotations
import copy
import math

KEY = "v3_development_goals"
SKILLS = {"shooting":"shooting_rating", "playmaking":"playmaking_rating", "defense":"defense_rating", "rebounding":"rebounding_rating"}
MIN_GAMES = 10


def number(value):
    if isinstance(value,bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def season(state):
    return str(state.settings.season_label)


def opportunity(totals):
    games = int(getattr(totals, "games_played", 0) or 0)
    minutes = number(getattr(totals, "minutes", 0))
    return (minutes/games if games and minutes is not None else 0.0), games


def player_rows(state, team):
    rows = []
    for pid in state.teams[team].roster_player_ids:
        player = state.players.get(pid)
        if player is None or getattr(player,"synthetic",False):
            continue
        skills = {name:number(getattr(player,"skill_ratings",{}).get(field)) for name,field in SKILLS.items()}
        mpg, games = opportunity(getattr(state,"player_season_totals",{}).get(pid))
        rows.append(dict(player_id=str(pid), name=str(player.player_name), age=number(player.age),
                         overall=number(player.overall_rating), skills=skills, minutes_per_game=round(mpg,2), games=games))
    return rows


def evaluate(state, goal):
    player = state.players.get(goal["player_id"])
    current = season(state) == goal["season"]
    games = 0
    value = None
    evidence = "Current saved roster ratings"
    if goal["metric"] == "opportunity":
        totals = getattr(state,"player_season_totals",{}) if current else None
        if not current:
            archive = next((a for a in getattr(state,"season_history",[]) if str(a.season_label)==goal["season"]),None)
            totals = getattr(archive,"player_season_totals",None)
        if totals is not None:
            value, games = opportunity(totals.get(goal["player_id"]))
        evidence = "Saved season minutes; at least ten appearances required"
    elif player is not None:
        field = SKILLS[goal["metric"]]
        if current:
            value = number(getattr(player,"skill_ratings",{}).get(field))
        else:
            # Only reconstruct an archived result when a closing annual record exists.
            yearly = list(getattr(player,"development_history",[]) or [])[goal["annual_offset"]:]
            yearly = [row for row in yearly if row.get("source_season")==goal["season"]]
            annual_deltas = [number(row.get("skill_deltas",{}).get(field)) for row in yearly]
            if yearly and all(delta is not None for delta in annual_deltas):
                value = goal["baseline"] + sum(annual_deltas)
                for row in list(getattr(player,"training_camp_history",[]) or [])[goal["camp_offset"]:]:
                    if row.get("season") != goal["season"]:
                        continue
                    if row.get("focus") == goal["metric"]:
                        before, after = number(row.get("before")), number(row.get("after"))
                    elif row.get("tradeoff") == goal["metric"]:
                        before, after = number(row.get("tradeoff_before")), number(row.get("tradeoff_after"))
                    else:
                        continue
                    if before is None or after is None:
                        value = None
                        break
                    value += after-before
            evidence = "Recorded camp deltas and closing annual development"
    met = value is not None and value >= goal["target"]-0.001 and (goal["metric"]!="opportunity" or games>=MIN_GAMES)
    status = "target_met" if met and current else "achieved" if met else "in_progress" if current and value is not None else "missed" if value is not None else "unverified"
    denominator = goal["target"] - goal["baseline"]
    progress = max(0.0,min(1.0,(value-goal["baseline"])/denominator)) if value is not None and denominator>0 else (1.0 if met else 0.0)
    if goal["metric"]=="opportunity":
        progress = min(1.0, value/goal["target"], games/MIN_GAMES) if value is not None else 0.0
    roster = state.teams.get(goal["team"])
    departed = roster is None or goal["player_id"] not in roster.roster_player_ids
    return {**goal, "current":None if value is None else round(value,3), "progress":round(progress,3),
            "status":status, "games":games, "departed":departed, "evidence":evidence}


def goals_board(checkpoint, team):
    state = checkpoint.simulation_state
    current_season = season(state)
    records = checkpoint.preferences.get(KEY,{})
    current = records.get(current_season,{}).get(team,[])
    archive = [evaluate(state,goal) for label,teams in sorted(records.items(),reverse=True) if label!=current_season
               for goal in teams.get(team,[])]
    phase = str(getattr(state.phase,"value",state.phase))
    return dict(team=team,season=current_season,phase=phase,committed=bool(current),
                can_commit=not current and phase in {"regular_season","offseason"},
                players=player_rows(state,team), goals=[evaluate(state,goal) for goal in current],
                archive=archive[:30], archived_count=len(archive), slots=3,
                rules="Commit one plan of up to three players per season. Skill goals require +1, +2 or +3 points. Opportunity goals require ten appearances. Goals track results; they do not grant ratings or change rotations.")


def build_goals_candidate(checkpoint, team, selections):
    board = goals_board(checkpoint,team)
    if not board["can_commit"]:
        raise ValueError("Season goals are already committed or this phase does not allow a new plan.")
    if not isinstance(selections,list) or not 1<=len(selections)<=3:
        raise ValueError("Choose one to three player goals.")
    roster = {row["player_id"]:row for row in board["players"]}
    goals, used = [], set()
    for selection in selections:
        if not isinstance(selection,dict):
            raise ValueError("Each goal must be an object.")
        pid, metric = selection.get("player_id"), selection.get("metric")
        if not isinstance(pid,str) or pid not in roster or pid in used:
            raise ValueError("Each goal must name a different current roster player.")
        if not isinstance(metric,str) or metric not in {*SKILLS,"opportunity"}:
            raise ValueError("Choose a supported skill or playing-opportunity goal.")
        row = roster[pid]
        if metric == "opportunity":
            target = number(selection.get("target"))
            if board["phase"] != "regular_season" or target not in {10.,15.,20.,25.,30.}:
                raise ValueError("Opportunity goals require regular season and a 10/15/20/25/30 minute target.")
            baseline = row["minutes_per_game"]
            if row["games"] >= MIN_GAMES and baseline>=target:
                raise ValueError("This player has already met that opportunity target.")
        else:
            delta = number(selection.get("delta"))
            baseline = row["skills"][metric]
            if baseline is None or not 0<=baseline<=99.9 or delta not in {1.,2.,3.} or baseline+delta>99.9:
                raise ValueError("Skill goals need a known rating and a +1/+2/+3 target below 99.9.")
            target = baseline+delta
        player = checkpoint.simulation_state.players[pid]
        goals.append(dict(player_id=pid,name=row["name"],team=team,season=board["season"],metric=metric,
                          baseline=baseline,target=target,annual_offset=len(getattr(player,"development_history",[]) or []),
                          camp_offset=len(getattr(player,"training_camp_history",[]) or [])))
        used.add(pid)
    candidate = copy.deepcopy(checkpoint)
    candidate.preferences.setdefault(KEY,{}).setdefault(board["season"],{})[team] = goals
    return candidate
