from __future__ import annotations
import copy, json, sys
from dataclasses import dataclass
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; SRC=ROOT/'src'; sys.path.insert(0,str(SRC))
from franchise_cpu_morale_response_v1 import run_cpu_morale_reactions_v1, cpu_trade_willingness_modifier_v1
from franchise_morale_chemistry_v1 import ensure_morale_state_v1, morale_snapshot_v1

@dataclass
class Settings: season_label:str='2027-28'
@dataclass
class Contract: years_remaining:int=2
@dataclass
class Player:
    player_id:str; player_name:str; overall_rating:float; potential_rating:float; age:float; contract:Contract
    rookie_season:str=''; draft_pick:int=0
@dataclass
class Rotation:
    starter_ids:tuple[str,...]; rotation_player_ids:tuple[str,...]; minutes_targets:dict[str,float]
@dataclass
class Team:
    roster_player_ids:tuple[str,...]; rotation:Rotation; active_player_ids:tuple[str,...]
@dataclass
class Totals: games_played:int=3; minutes:float=60.0
@dataclass
class Standing: wins:int=2; losses:int=8; streak_type:str='L'; streak_length:int=3
class State: pass

def make_team_players(prefix:int, ratings:list[int]):
    out={}
    for i,rating in enumerate(ratings):
        pid=str(prefix+i)
        out[pid]=Player(pid,f'Player {pid}',float(rating),float(rating+3),24.0 if i==0 else 27.0,Contract(1 if i>=6 else 2))
    return out

def build_state():
    s=State(); s.settings=Settings(); s.current_day_index=20
    chi=make_team_players(1,[88,85,82,80,78,76,74,72,70,68])
    lal=make_team_players(11,[87,84,82,80,78,76,74,72,70,68])
    s.players={**chi,**lal}
    chi_ids=tuple(chi); lal_ids=tuple(lal)
    chi_minutes={pid:mins for pid,mins in zip(chi_ids,[34,32,31,30,29,24,22,16,12,10])}
    lal_rot=lal_ids[1:]  # top player is frozen out despite being the best player
    lal_minutes={pid:mins for pid,mins in zip(lal_rot,[34,32,31,30,29,25,22,20,17])}
    # exact 240 correction
    lal_minutes[lal_rot[0]] += 240-sum(lal_minutes.values())
    s.teams={
      'CHI':Team(chi_ids,Rotation(chi_ids[:5],chi_ids,chi_minutes),chi_ids),
      'LAL':Team(lal_ids,Rotation(lal_rot[:5],lal_rot,lal_minutes),lal_ids),
    }
    s.player_season_totals={pid:Totals() for pid in s.players}
    s.standings={'CHI':Standing(7,3,'W',2),'LAL':Standing(2,8,'L',4)}
    s.franchise_morale_chemistry_v1={'version':'franchise-morale-chemistry-v1.3-2026-09-16','season':'2027-28','players':{},'teams':{},'processed_game_ids':[],'role_promises':{},'trade_request_history':[],'event_history':[],'rotation_emphasis':{},'meetings':{},'trade_responses':{}}
    p=ensure_morale_state_v1(s)
    # User-controlled CHI also has a concern; it must never be CPU-managed.
    p['players']['1']={'score':40.0,'previous_score':41.0,'low_morale_games':4,'high_risk_games':3,'trade_request_status':'Considering request','trade_request_active':False,'recent_games':[{'game_id':'CHI-020','day':20,'minutes':5.0,'started':False,'won':False}]}
    # CPU star: pressure building and frozen out. CPU should repair role before shopping the core.
    p['players']['11']={'score':42.0,'previous_score':43.0,'low_morale_games':3,'high_risk_games':2,'trade_request_status':'Pressure building','trade_request_active':False,'recent_games':[{'game_id':'LAL-020','day':20,'minutes':0.0,'started':False,'won':False}]}
    # CPU non-core veteran with an active request should be made available.
    p['players']['18']={'score':35.0,'previous_score':36.0,'low_morale_games':6,'high_risk_games':5,'trade_request_status':'Requested trade','trade_request_active':True,'recent_games':[{'game_id':'LAL-020','day':20,'minutes':8.0,'started':False,'won':False}]}
    for pid in lal_ids:
        if pid not in p['players']:
            p['players'][pid]={'score':70.0,'previous_score':70.0,'recent_games':[{'game_id':'LAL-020','day':20,'minutes':20.0,'started':False,'won':False}]}
    return s

def main():
    s=build_state(); checks={}
    chi_before=copy.deepcopy(s.teams['CHI'].rotation)
    lal_before=copy.deepcopy(s.teams['LAL'].rotation)
    result=run_cpu_morale_reactions_v1(s,controlled_teams=('CHI',))
    checks['cpu_teams_processed']=result['teams_processed']==1
    checks['controlled_team_rotation_untouched']=s.teams['CHI'].rotation==chi_before
    checks['cpu_rotation_changes']=s.teams['LAL'].rotation!=lal_before
    checks['cpu_rotation_stays_240']=abs(sum(s.teams['LAL'].rotation.minutes_targets.values())-240.0)<0.11
    checks['frozen_core_gets_rotation_repair']='11' in s.teams['LAL'].rotation.rotation_player_ids
    snap=morale_snapshot_v1(s,'LAL'); by={r['player_id']:r for r in snap['players']}
    checks['core_not_dumped_early']=by['11']['trade_response']=='Keep internal'
    checks['active_noncore_request_is_available']=by['18']['trade_response'] in {'Listening to offers','On trade block'}
    checks['trade_willingness_rises_for_request']=cpu_trade_willingness_modifier_v1(s,'LAL','18')>1.0
    checks['cpu_meeting_can_fire']=bool((ensure_morale_state_v1(s).get('meetings') or {}).get('11'))
    before=copy.deepcopy(ensure_morale_state_v1(s).get('cpu_morale_reactions'))
    result2=run_cpu_morale_reactions_v1(s,controlled_teams=('CHI',))
    after=ensure_morale_state_v1(s).get('cpu_morale_reactions')
    checks['same_game_is_idempotent']=not result2['changed'] and before==after
    checks['no_trade_history_created']=not hasattr(s,'transaction_history') and not hasattr(s,'franchise_transactions')
    failed=[k for k,v in checks.items() if not v]
    report={'checks':checks,'failed_checks':failed,'passed':not failed,'actions':result['actions']}
    print(json.dumps(report,indent=2))
    if failed: raise SystemExit('FRANCHISE CPU MORALE REACTIONS V4 REGRESSION FAILED')
    print('FRANCHISE CPU MORALE REACTIONS V4 REGRESSION PASSED')
    return 0
if __name__=='__main__': raise SystemExit(main())
