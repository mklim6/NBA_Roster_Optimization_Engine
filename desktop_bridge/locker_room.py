"""V3 locker-room actions backed by the existing morale and promise engine."""
from __future__ import annotations
import copy
from franchise_morale_chemistry_v1 import (MORALE_STATE_ATTR,ROLE_PRESETS,MEETING_ACTIONS,
    morale_snapshot_v1,role_expectation_v1,refresh_team_morale_v1,
    hold_player_meeting_v1,set_player_role_expectation_v1)

MEETINGS={
    'Reassure and listen':'Listen to the concern. Adds short-term support and a three-game meeting cooldown.',
    'Ask for patience':'Ask for time to resolve the role. Adds temporary patience and a three-game meeting cooldown.',
    'Reset expectations honestly':'Withdraw the role promise and return to automatic expectations. Includes an immediate morale cost and a two-game meeting cooldown.'}


def _dialogue(row,games):
    if row['trade_request_active']:
        return 'I need a clear conversation about my future with this team.'
    if row['broken_promise_games']>0:
        return 'Our agreement did not work out. I want clarity about what comes next.'
    if games==0:
        return f"Before we play, I want to understand my role as a {row['expected_role']}."
    if row['minute_gap'] <= -4:
        return f"My playing time has been below my {row['expected_role']} expectations. Can we talk about the plan?"
    if row['promise_active']:
        return 'We have a role agreement. I want us to follow through on it.'
    return 'I want to know how I fit into the next stretch of our season.'


def locker_room_board(checkpoint,team):
    # The legacy snapshot initializer migrates morale in place, so all reads use
    # an isolated state. No read, refresh or preview can alter the source.
    state=copy.deepcopy(checkpoint.simulation_state)
    snapshot=morale_snapshot_v1(state,team)
    phase=str(getattr(state.phase,'value',state.phase))
    rows=[]
    memory=getattr(state,MORALE_STATE_ATTR,{})
    for raw in snapshot['players']:
        player=state.players[raw['player_id']]
        if getattr(player,'synthetic',False):
            continue
        row=copy.deepcopy(raw)
        pid=row['player_id']
        totals=getattr(state,'player_season_totals',{}).get(pid)
        games=int(getattr(totals,'games_played',0) or 0)
        rotation=state.teams[team].rotation
        promise=role_expectation_v1(state,team,pid)
        history=[copy.deepcopy(e) for e in memory.get('event_history',[]) if e.get('team')==team and e.get('player_id')==pid][-20:]
        row.update(name=str(player.player_name),age=float(player.age),overall=float(player.overall_rating),
                   games=games,planned_minutes=float(rotation.minutes_targets.get(pid,0)),promise=promise,history=list(reversed(history)),
                   dialogue=_dialogue(row,games),usage_basis='Season and recent-game usage' if games else 'Planned rotation; no season appearances yet',
                   can_meet=phase=='regular_season' and row['meeting_cooldown_games']==0,
                   can_promise=phase=='regular_season' and promise['promise_status']!='active',
                   meeting_support_games=int(memory.get('players',{}).get(pid,{}).get('meeting_support_games',0)),
                   patience_games=int(memory.get('players',{}).get(pid,{}).get('patience_games',0)))
        rows.append(row)
    return dict(team=team,season=str(state.settings.season_label),phase=phase,players=rows,
                chemistry=snapshot['chemistry'],roles=[dict(role=role,minutes=value[1]) for role,value in ROLE_PRESETS.items() if role!='Auto'],
                meetings=[dict(action=action,detail=MEETINGS[action]) for action in MEETING_ACTIONS],reviews=[3,5,10],
                writable=phase=='regular_season',read_only=True,
                rules='Meetings and role agreements are available during the regular season. Role promises are reviewed after games. Adjust actual minutes in Game Day.')


def build_locker_room_candidate(checkpoint,team,body):
    if not isinstance(body,dict):
        raise ValueError('Choose a locker-room action.')
    board=locker_room_board(checkpoint,team)
    if not board['writable']:
        raise ValueError('Locker-room actions open during the regular season.')
    pid=body.get('player_id')
    row=next((r for r in board['players'] if r['player_id']==pid),None)
    if row is None:
        raise ValueError('Choose a current roster player.')
    kind=body.get('kind')
    if kind=='meeting':
        if body.get('meeting') not in MEETING_ACTIONS:
            raise ValueError('Choose a supported conversation response.')
        if not row['can_meet']:
            raise ValueError('Wait for the remaining meeting cooldown games.')
    elif kind=='promise':
        if not row['can_promise']:
            raise ValueError('An active promise must reach review or be reset honestly before a new agreement.')
        role=body.get('role')
        if not isinstance(role,str) or role not in ROLE_PRESETS or role=='Auto':
            raise ValueError('Choose a supported role agreement.')
        review=body.get('review_games')
        if type(review) is not int or review not in {3,5,10}:
            raise ValueError('Choose a review after three, five or ten games.')
    else:
        raise ValueError('Choose a meeting or role promise.')
    candidate=copy.deepcopy(checkpoint)
    state=candidate.simulation_state
    refresh_team_morale_v1(state,team,blend=0.0,reason='locker-room-initialize')
    if kind=='meeting':
        record=hold_player_meeting_v1(state,team,pid,action=body['meeting'])
    else:
        record=set_player_role_expectation_v1(state,team,pid,role=body['role'],minutes=ROLE_PRESETS[body['role']][1],review_games=body['review_games'])
    result_board=locker_room_board(candidate,team)
    after=next(r for r in result_board['players'] if r['player_id']==pid)
    review_after=after['promise']['review_after_games']
    note=MEETINGS[body['meeting']] if kind=='meeting' else f"{body['role']} / {ROLE_PRESETS[body['role']][1]:.0f} minutes. Review after {review_after} team games; at least 60% must meet the agreement, with a minimum of two. Minutes allow a three-minute tolerance; starter promises also require a start."
    effect=dict(player_id=pid,name=row['name'],kind=kind,before=row,after=after,record=record,
                detail=note,chemistry_before=board['chemistry'],chemistry_after=result_board['chemistry'])
    return candidate,result_board,effect
