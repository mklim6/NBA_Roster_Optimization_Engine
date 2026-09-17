from __future__ import annotations
import importlib.util,json,sys
from pathlib import Path
from types import SimpleNamespace

def load(path):
 spec=importlib.util.spec_from_file_location('morale_v302_test',path); mod=importlib.util.module_from_spec(spec); sys.modules[spec.name]=mod; spec.loader.exec_module(mod); return mod

def main():
 root=Path.cwd(); mod=load(root/'src'/'franchise_morale_chemistry_v1.py')
 state=SimpleNamespace(settings=SimpleNamespace(season_label='2027-28'),current_day_index=7,teams={'CHI':SimpleNamespace(roster_player_ids=('p1','p2','p3'))})
 setattr(state,mod.MORALE_STATE_ATTR,{})
 game=SimpleNamespace(game_id='G-DNP-1',home_team='CHI',away_team='BOS',home_score=101,away_score=99,player_box_scores=(SimpleNamespace(team_abbreviation='CHI',player_id='p1',minutes=31.0,started=True),SimpleNamespace(team_abbreviation='CHI',player_id='p2',minutes=0.0,started=False),SimpleNamespace(team_abbreviation='BOS',player_id='x',minutes=22.0,started=False)))
 mod._append_game_context(state,game,'CHI'); players=mod.ensure_morale_state_v1(state)['players']; p1=players['p1']['recent_games'][-1]; p2=players['p2']['recent_games'][-1]; p3=players['p3']['recent_games'][-1]
 before={p:len(players[p]['recent_games']) for p in ('p1','p2','p3')}; mod._append_game_context(state,game,'CHI'); after={p:len(players[p]['recent_games']) for p in ('p1','p2','p3')}
 checks={'played_minutes':p1['minutes']==31.0 and p1['dnp'] is False,'explicit_zero_box':p2['minutes']==0.0 and p2['dnp'] is False,'omitted_roster_is_dnp':p3['minutes']==0.0 and p3['dnp'] is True,'dnp_recent_mpg_zero':mod._recent_minutes(players['p3'])[0]==0.0,'idempotent':before==after,'opponent_not_added':'x' not in players}
 pyarrow_checked=False; pyarrow_ok=True
 try:
  import pandas as pd
  df=pd.DataFrame([{'Recent MIN':mod._num(v,float('nan'))} for v in (0.0,18.5,None)])
  checks['recent_min_numeric']=str(df['Recent MIN'].dtype).startswith(('float','int'))
  try:
   import pyarrow as pa; pyarrow_checked=True; pa.Table.from_pandas(df)
  except ImportError: pass
  except Exception: pyarrow_ok=False
 except Exception: checks['recent_min_numeric']=False; pyarrow_ok=False
 checks['pyarrow_serialization']=pyarrow_ok
 failed=[k for k,v in checks.items() if not v]; print(json.dumps({'checks':checks,'pyarrow_checked':pyarrow_checked,'failed_checks':failed,'passed':not failed},indent=2))
 if failed: raise SystemExit('FRANCHISE MORALE V3.0.2 DNP + UI HOTFIX REGRESSION FAILED')
 print('FRANCHISE MORALE V3.0.2 DNP + UI HOTFIX REGRESSION PASSED'); return 0
if __name__=='__main__': raise SystemExit(main())
