from __future__ import annotations
import asyncio,copy,hashlib,json,pickle,subprocess,sys,tempfile
from pathlib import Path
from types import SimpleNamespace as N
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from desktop_bridge.franchise_pulse import build_franchise_pulse
from desktop_bridge.development_goals import build_goals_candidate,KEY
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint,DEFAULT_CHECKPOINT_PATH
from starlette.requests import Request

def main():
    paths=[ROOT/'outputs/runtime/v3_godot_working_checkpoint.pkl.gz',Path(DEFAULT_CHECKPOINT_PATH)]
    hashes=lambda:[hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
    before=hashes()
    original=load_franchise_checkpoint(path=paths[0])
    team=original.preferences['franchise_pref_active_team']
    real=copy.deepcopy(original)
    state=real.simulation_state
    state.current_day_index=12
    state.phase='regular_season'
    state.completed_games={}
    state.schedule={}
    state.franchise_transaction_history_v1=[]
    for gid,d,home,score,against in [('a',6,True,90,100),('b',7,False,111,100),('c',12,True,100,101),('old',5,True,120,110),('future',13,True,120,110)]:
        state.schedule[gid]=N(day_index=d)
        state.completed_games[gid]=N(home_team=team if home else 'SAS',away_team='SAS' if home else team,home_score=score if home else against,away_score=against if home else score)
    state.completed_games['undated']=N(home_team=team,away_team='SAS',home_score=110,away_score=90)
    state.schedule['other']=N(day_index=12)
    state.completed_games['other']=N(home_team='LAL',away_team='SAS',home_score=120,away_score=100)
    real.preferences.pop(KEY,None)
    pid=state.teams[team].roster_player_ids[0]
    state.players[pid].skill_ratings['shooting_rating']=70.
    real=build_goals_candidate(real,team,[dict(player_id=pid,metric='shooting',delta=2)])
    state=real.simulation_state
    state.players[pid].skill_ratings['shooting_rating']=72.
    inbox={'cards':[dict(id='injury:test',category='Availability',priority='Action',title='Test availability',detail='Recorded availability concern',destination='ROSTER',player_id=pid)]}
    snapshot=pickle.dumps(real)
    board=build_franchise_pulse(real,team,inbox)
    assert [r['id'] for r in board['results']]==['c','b','a']
    assert (board['wins'],board['losses'])==(1,2)
    assert board['stories'][0]['id']=='decision:injury:test'
    assert any(s['id']=='goal:'+pid and 'reached' in s['title'] for s in board['stories'])
    assert build_franchise_pulse(real,team,inbox)==board
    assert pickle.dumps(real)==snapshot
    trade_copy=copy.deepcopy(real)
    trade_copy.simulation_state.franchise_transaction_history_v1=[
        dict(transaction_id='valid',status='committed',season_label=board['season'],day_index=7,team_a=team,team_b='SAS'),
        dict(transaction_id='old-season',status='committed',season_label='old',day_index=7,team_a=team,team_b='SAS'),
        dict(transaction_id='not-committed',status='preview',season_label=board['season'],day_index=7,team_a=team,team_b='SAS'),
        dict(transaction_id='undated',status='committed',season_label=board['season'],team_a=team,team_b='SAS')]
    trades=[s['id'] for s in build_franchise_pulse(trade_copy,team,inbox)['stories'] if s['id'].startswith('trade:')]
    assert trades==['trade:valid']
    opening=build_franchise_pulse(original,team,{'cards':[]})
    assert not opening['results'] and opening['stories']
    from desktop_bridge import server
    response=asyncio.run(server.franchise_pulse(Request({'type':'http','method':'GET','path':'/v3/franchise-pulse','headers':[]})))
    assert response.status_code==200,response.body
    assert json.loads(response.body)['read_only']
    assert 'LeaguePhase' not in json.loads(response.body)['phase']
    loader=server._working_checkpoint
    try:
        server._working_checkpoint=lambda: None
        missing=asyncio.run(server.franchise_pulse(Request({'type':'http','method':'GET','path':'/v3/franchise-pulse','headers':[]})))
        assert missing.status_code==409
    finally:
        server._working_checkpoint=loader
    assert any(r.path=='/v3/franchise-pulse' and r.methods=={'GET','HEAD'} for r in server.routes)
    with tempfile.TemporaryDirectory() as temp:
        gd='''extends SceneTree
func _initialize():
    call_deferred("run")
func run():
    var page = load("res://scripts/franchise_pulse_v3.gd").new()
    root.add_child(page)
    page.size = Vector2(880,850)
    page.configure(BOARD)
    assert(page.stories_box.get_child_count() == 3)
    page._set_filter("DEVELOPMENT")
    assert(page.stories_box.get_child_count() == 1)
    page._set_filter("DECISIONS")
    assert(page.stories_box.get_child_count() == 1)
    page._set_filter("ALL")
    var action = page.stories_box.get_child(0).get_child(0).get_children().back()
    assert(action.get_signal_connection_list("pressed").size() == 1)
    var destination = []
    page.navigate_requested.connect(func(target): destination.append(target))
    action.pressed.emit()
    assert(destination == ["ROSTER"])
    page._play_sting()
    assert(page.audio_player.stream.data.size() == 26460)
    page.audio_player.stop()
    var main = load("res://scripts/main.gd").new()
    var nav = main._nav_button("PULSE")
    main.add_child(nav)
    assert(main.nav_buttons.has("PULSE"))
    main.pulse_page = page
    assert(main._page_control("PULSE") == page)
    assert(page in main._all_page_controls())
    main.free()
    page.queue_free()
    await process_frame
    await process_frame
    print("PULSE45_RUNTIME_PASS")
    quit()
'''.replace('BOARD',json.dumps(board))
        script=Path(temp)/'pulse45.gd';script.write_text(gd,encoding='utf-8')
        proc=subprocess.run([str(Path.home()/'Downloads/Godot_v4.0-stable_win64.exe'),'--headless','--path',str(ROOT/'godot_client'),'--script',str(script)],capture_output=True,text=True,timeout=35)
        output=proc.stdout+proc.stderr;print(output)
        assert proc.returncode==0 and 'PULSE45_RUNTIME_PASS' in output and 'SCRIPT ERROR' not in output
    assert hashes()==before
    print('PASS: inclusive weekly window, home/away scores, absent dates, future/unrelated games excluded, truthful goals/decisions, deterministic snapshot, API read-only, Godot filters/navigation, protected saves')

if __name__=='__main__':main()
