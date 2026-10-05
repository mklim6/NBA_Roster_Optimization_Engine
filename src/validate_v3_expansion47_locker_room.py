from __future__ import annotations
import asyncio,copy,hashlib,json,pickle,subprocess,sys,tempfile
from pathlib import Path
from types import SimpleNamespace as N
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from desktop_bridge.locker_room import locker_room_board,build_locker_room_candidate
from franchise_morale_chemistry_v1 import MORALE_STATE_ATTR,update_morale_after_game_v1,role_expectation_v1
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint,save_franchise_checkpoint,DEFAULT_CHECKPOINT_PATH
from single_game_simulator_v1 import simulate_scheduled_game
from starlette.requests import Request

def main():
    paths=[ROOT/'outputs/runtime/v3_godot_working_checkpoint.pkl.gz',Path(DEFAULT_CHECKPOINT_PATH)]
    hashes=lambda:[hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
    protected=hashes()
    original=load_franchise_checkpoint(path=paths[0]);team=original.preferences['franchise_pref_active_team']
    cp=copy.deepcopy(original);cp.simulation_state.phase='regular_season'
    # Start with a fresh player meeting history, exclusively in a copied state.
    if hasattr(cp.simulation_state,MORALE_STATE_ATTR):delattr(cp.simulation_state,MORALE_STATE_ATTR)
    before=pickle.dumps(cp)
    board=locker_room_board(cp,team)
    assert pickle.dumps(cp)==before and board==locker_room_board(cp,team)
    pid=cp.simulation_state.teams[team].roster_player_ids[0]
    ratings={p:(v.overall_rating,copy.deepcopy(v.skill_ratings)) for p,v in cp.simulation_state.players.items()}
    rotations=pickle.dumps({t:v.rotation for t,v in cp.simulation_state.teams.items()})
    meeting=dict(kind='meeting',player_id=pid,meeting='Reassure and listen')
    candidate,after,effect=build_locker_room_candidate(cp,team,meeting)
    assert pickle.dumps(cp)==before
    assert effect['after']['meeting_cooldown_games']==3
    assert abs(effect['after']['score']-effect['before']['score']-1.5)<.15
    assert len(effect['after']['history'])==1
    try:build_locker_room_candidate(candidate,team,meeting)
    except ValueError:pass
    else:raise AssertionError('Meeting cooldown bypassed')
    promise=dict(kind='promise',player_id=pid,role='Featured starter',review_games=3)
    promised,promise_board,promise_effect=build_locker_room_candidate(cp,team,promise)
    assert promise_effect['after']['promise']['promise_status']=='active'
    assert promise_effect['after']['promise']['minutes']==32
    try:build_locker_room_candidate(promised,team,promise)
    except ValueError:pass
    else:raise AssertionError('Active promise overwritten')
    reset,_,reset_effect=build_locker_room_candidate(promised,team,dict(meeting,meeting='Reset expectations honestly'))
    assert not reset_effect['after']['promise']['promise_active']
    assert reset_effect['after']['meeting_cooldown_games']==2
    patience,_,patience_effect=build_locker_room_candidate(cp,team,dict(meeting,meeting='Ask for patience'))
    assert patience_effect['after']['patience_games']==3
    assert ratings=={p:(v.overall_rating,v.skill_ratings) for p,v in candidate.simulation_state.players.items()}
    assert rotations==pickle.dumps({t:v.rotation for t,v in candidate.simulation_state.teams.items()})
    unchanged=copy.deepcopy(candidate.simulation_state)
    delattr(unchanged,MORALE_STATE_ATTR)
    assert pickle.dumps(unchanged)==pickle.dumps(cp.simulation_state)
    assert candidate.preferences==cp.preferences
    assert pickle.dumps(candidate.trade_state)==pickle.dumps(cp.trade_state)
    for met in [True,False]:
        trial=copy.deepcopy(promised)
        for i in range(3):
            game=N(game_id=f'promise-test-{i}',home_team=team,away_team='SAS' if team!='SAS' else 'BOS',home_score=100,away_score=90,player_box_scores=(N(player_id=pid,team_abbreviation=team,minutes=32. if met else 0.,started=met),))
            update_morale_after_game_v1(trial.simulation_state,game)
        reviewed=role_expectation_v1(trial.simulation_state,team,pid)
        assert reviewed['promise_status']==('kept' if met else 'broken')
        assert reviewed['games_since_set']==3
        update_morale_after_game_v1(trial.simulation_state,game)
        assert role_expectation_v1(trial.simulation_state,team,pid)==reviewed
    # Actual production commit hook must advance the promise on the copied state.
    trial=copy.deepcopy(promised)
    next_game=sorted([g for g in trial.simulation_state.schedule.values() if team in (g.home_team,g.away_team) and g.game_id not in trial.simulation_state.completed_games],key=lambda g:(g.day_index,g.game_id))[0]
    simulate_scheduled_game(trial.simulation_state,next_game.game_id,seed=4701,commit=True)
    assert role_expectation_v1(trial.simulation_state,team,pid)['games_since_set']==1
    for bad in [dict(meeting,player_id='unknown'),dict(meeting,meeting='instant trust'),dict(promise,role='unknown'),dict(promise,role=[]),dict(promise,review_games=True),dict(promise,review_games=4),dict(meeting,kind='unknown')]:
        try:build_locker_room_candidate(cp,team,bad)
        except ValueError:pass
        else:raise AssertionError('Invalid locker action accepted')
    offseason=copy.deepcopy(cp);offseason.simulation_state.phase='offseason'
    assert not locker_room_board(offseason,team)['writable']
    try:build_locker_room_candidate(offseason,team,meeting)
    except ValueError:pass
    else:raise AssertionError('Phase gate bypassed')
    with tempfile.TemporaryDirectory() as temp:
        folder=Path(temp);staged=folder/'working.pkl.gz'
        save_franchise_checkpoint(cp.simulation_state,cp.trade_state,preferences=cp.preferences,path=staged,reason='Locker test source',copy_payload=False,force_replace=True)
        from desktop_bridge import server
        old_path,old_root=server.V3_WORKING_CHECKPOINT_PATH,server.REPO_ROOT
        server.V3_WORKING_CHECKPOINT_PATH,server.REPO_ROOT=staged,folder
        async def invoke(body=None):
            async def receive():return {'type':'http.request','body':json.dumps(body).encode(),'more_body':False}
            return await server.locker_room(Request({'type':'http','method':'POST' if body else 'GET','path':'/v3/locker-room','headers':[]},receive))
        try:
            sha=hashlib.sha256(staged.read_bytes()).hexdigest()
            assert asyncio.run(invoke()).status_code==200
            body={**meeting,'action':'preview','expected_working_save_sha256':sha}
            response=asyncio.run(invoke(body));assert response.status_code==200,response.body
            assert hashlib.sha256(staged.read_bytes()).hexdigest()==sha
            assert asyncio.run(invoke(dict(body,action='execute',expected_working_save_sha256='stale'))).status_code==409
            execution=asyncio.run(invoke(dict(body,action='execute')));assert execution.status_code==200,execution.body
            restored=load_franchise_checkpoint(path=staged)
            assert locker_room_board(restored,team)['players']==after['players']
            assert json.loads(execution.body)['effect']==json.loads(response.body)['effect']
            assert asyncio.run(invoke(dict(body,action='execute'))).status_code==409
            assert (folder/'outputs/runtime/v3_locker_room_recovery'/f'{sha}.pkl.gz').exists()
            reloaded=json.loads(asyncio.run(invoke()).body)
            assert reloaded['working_save_sha256']!=sha
            assert asyncio.run(invoke(dict(body,action='execute',expected_working_save_sha256=reloaded['working_save_sha256']))).status_code==409
        finally:server.V3_WORKING_CHECKPOINT_PATH,server.REPO_ROOT=old_path,old_root
        gd='''extends SceneTree
func _initialize():call_deferred("run")
func run():
    var page = load("res://scripts/locker_room_v3.gd").new()
    root.add_child(page)
    page.size = Vector2(880,850)
    page.configure(BOARD)
    assert(page.player_picker.item_count > 0)
    assert(page.meeting_picker.item_count == 3)
    assert(page.role_picker.item_count == 7)
    assert(page._draft("promise").review_games == 5)
    page.preview_ready = true
    page.confirm_button.visible = true
    page.role_picker.select(1)
    page.role_picker.item_selected.emit(1)
    assert(not page.preview_ready and not page.confirm_button.visible)
    page._render_effect(EFFECT)
    assert(page.review_box.get_child_count() == 1)
    page.configure(AFTER)
    page._select_player(INDEX)
    assert(page.meeting_button.disabled)
    var main = load("res://scripts/main.gd").new()
    var nav = main._nav_button("LOCKER ROOM")
    main.add_child(nav)
    assert(main.nav_buttons.has("LOCKER ROOM"))
    main.locker_page = page
    assert(main._page_control("LOCKER ROOM") == page)
    assert(page in main._all_page_controls())
    main.free()
    page.queue_free()
    await process_frame
    await process_frame
    print("LOCKER47_RUNTIME_PASS")
    quit()
'''.replace('BOARD',json.dumps(board)).replace('EFFECT',json.dumps(effect)).replace('AFTER',json.dumps(after)).replace('INDEX',str(next(i for i,r in enumerate(after['players']) if r['player_id']==pid)))
        script=folder/'locker47.gd';script.write_text(gd,encoding='utf-8')
        try:
            proc=subprocess.run([str(Path.home()/'Downloads/Godot_v4.0-stable_win64.exe'),'--headless','--path',str(ROOT/'godot_client'),'--script',str(script)],capture_output=True,text=True,timeout=20)
        except subprocess.TimeoutExpired as exc:
            print(exc.stdout,exc.stderr,flush=True)
            raise
        output=proc.stdout+proc.stderr;print(output)
        assert proc.returncode==0 and 'LOCKER47_RUNTIME_PASS' in output and 'SCRIPT ERROR' not in output
    assert hashes()==protected
    print('PASS: read-only snapshots, existing meetings/roles, cooldowns, kept/broken/idempotent reviews, production game hook, invalid/phase/stale/replayed actions, atomic reload/recovery, unchanged ratings/rotations, Godot choices/preview/navigation, protected saves')

if __name__=='__main__':main()
