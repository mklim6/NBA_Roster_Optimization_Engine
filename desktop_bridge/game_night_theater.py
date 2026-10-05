"""Read-only cinematic chapters from recorded final scores and box scores."""
from __future__ import annotations


def theater_game(state, game, names=None):
    names = names or {}
    scheduled = getattr(state,'schedule',{}).get(str(game.game_id))
    lines=[]
    for line in game.player_box_scores:
        player = state.players.get(str(line.player_id))
        lines.append(dict(player_id=str(line.player_id),name=str(getattr(player,'player_name',line.player_id)),
                          team=str(line.team_abbreviation),starter=bool(line.started),minutes=round(float(line.minutes),1),
                          **{key:int(getattr(line,key,0)) for key in ['points','rebounds','assists','steals','blocks','turnovers','field_goals_made','field_goals_attempted','three_pointers_made','three_pointers_attempted']}))
    complete=bool(getattr(game,'box_score_complete',False))
    home,away=str(game.home_team),str(game.away_team)
    chapters=[dict(kind='opening',title='THE FINAL BUZZER',detail='A postgame recap of the saved final score and player box score.'),
              dict(kind='lineups',title='THE STARTING CAST',detail='Recorded starters, shown in a lineup diagram. Positions on the court are illustrative.')]
    totals={}
    for team in [home,away]:
        played=[r for r in lines if r['team']==team and r['minutes']>0]
        leader=sorted(played,key=lambda r:(-r['points'],-r['assists'],-r['rebounds'],r['player_id']))
        if leader:
            row=leader[0]
            chapters.append(dict(kind='spotlight',title=names.get(team,team)+' SPOTLIGHT',team=team,player=row,
                                 detail=f"{row['name']} • {row['points']} PTS / {row['rebounds']} REB / {row['assists']} AST"))
        if complete:
            totals[team]={key:sum(r[key] for r in lines if r['team']==team) for key in ['points','rebounds','assists','turnovers','field_goals_made','field_goals_attempted','three_pointers_made','three_pointers_attempted']}
    chapters.append(dict(kind='comparison',title='BY THE NUMBERS',detail='Recorded team box-score totals.' if complete else 'Full team totals are unavailable for this legacy result.'))
    winner=home if game.home_score>game.away_score else away if game.away_score>game.home_score else None
    chapters.append(dict(kind='closing',title='GAME IN THE BOOKS',detail=(names.get(winner,winner)+' takes the win.' if winner else 'No winner recorded.')+' Return to Franchise Pulse to plan your next move.'))
    return dict(game_id=str(game.game_id),day=getattr(scheduled,'day_index',None),home_team=home,away_team=away,
                home_name=names.get(home,home),away_name=names.get(away,away),home_score=int(game.home_score),away_score=int(game.away_score),
                overtime_periods=int(game.overtime_periods),winner=winner,players=lines,totals=totals,chapters=chapters,
                box_score_complete=complete,evidence='Saved final score and player box score',possession_replay_available=False)


def build_game_night_theater(checkpoint,team,names=None):
    state=checkpoint.simulation_state
    games=[theater_game(state,g,names) for g in getattr(state,'completed_games',{}).values() if team in (g.home_team,g.away_team)]
    games.sort(key=lambda g:(g['day'] if g['day'] is not None else -1,g['game_id']),reverse=True)
    return dict(team=team,season=str(state.settings.season_label),games=games[:12],available_count=len(games),read_only=True,
                mode='recorded_postgame_broadcast',detail='Recorded postgame broadcasts. Explore the final result, starting cast and player performances.')
