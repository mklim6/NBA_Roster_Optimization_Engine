from __future__ import annotations
import asyncio,copy,hashlib,json,pickle,subprocess,sys,tempfile
from dataclasses import replace
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from desktop_bridge.game_night_theater import build_game_night_theater,theater_game
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint,save_franchise_checkpoint,DEFAULT_CHECKPOINT_PATH
from single_game_simulator_v1 import simulate_scheduled_game
from starlette.requests import Request

def main():
    paths=[ROOT/'outputs/runtime/v3_godot_working_checkpoint.pkl.gz',Path(DEFAULT_CHECKPOINT_PATH)]
    hashes=lambda:[hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
    protected=hashes()
    original=load_franchise_checkpoint(path=paths[0])
    team=original.preferences['franchise_pref_active_team']
    cp=copy.deepcopy(original)
    state=cp.simulation_state
    pending=sorted([g for g in state.schedule.values() if team in (g.home_team,g.away_team) and str(g.game_id) not in state.completed_games],key=lambda g:(g.day_index,g.game_id))[0]
    source=pickle.dumps(state)
    simulated=simulate_scheduled_game(state,str(pending.game_id),seed=4601,commit=False)
    assert pickle.dumps(state)==source
    state.completed_games={str(pending.game_id):simulated.game}
    before=pickle.dumps(cp)
    board=build_game_night_theater(cp,team)
    game=board['games'][0]
    assert board['available_count']==1 and board['read_only']
    assert game['home_score']==simulated.game.home_score and game['away_score']==simulated.game.away_score
    assert game['totals'][game['home_team']]['points']==game['home_score']
    assert game['totals'][game['away_team']]['points']==game['away_score']
    assert len([r for r in game['players'] if r['starter']])==10
    assert len(game['chapters'])==6 and not game['possession_replay_available']
    assert build_game_night_theater(cp,team)==board and pickle.dumps(cp)==before
    partial=theater_game(state,replace(simulated.game,box_score_complete=False))
    assert not partial['totals'] and not partial['box_score_complete']
    undated=copy.deepcopy(state);undated.schedule.pop(str(pending.game_id))
    assert theater_game(undated,simulated.game)['day'] is None
    many=copy.deepcopy(cp)
    many.simulation_state.completed_games={str(i):replace(simulated.game,game_id=str(i)) for i in range(14)}
    assert len(build_game_night_theater(many,team)['games'])==12
    assert not build_game_night_theater(cp,'UNKNOWN')['games']
    from desktop_bridge import server
    loader=server._working_checkpoint
    try:
        server._working_checkpoint=lambda:cp
        response=asyncio.run(server.game_night_theater(Request({'type':'http','method':'GET','path':'/v3/game-night-theater','headers':[]})))
        assert response.status_code==200,response.body
        assert json.loads(response.body)['games'][0]['home_score']==game['home_score']
        server._working_checkpoint=lambda:None
        assert asyncio.run(server.game_night_theater(Request({'type':'http','method':'GET','path':'/v3/game-night-theater','headers':[]}))).status_code==409
    finally:server._working_checkpoint=loader
    with tempfile.TemporaryDirectory() as temp:
        folder=Path(temp)
        save_franchise_checkpoint(state,cp.trade_state,preferences=cp.preferences,path=folder/'game.pkl.gz',reason='Theater isolated validation',copy_payload=False,force_replace=True)
        assert build_game_night_theater(load_franchise_checkpoint(path=folder/'game.pkl.gz'),team)==board
        gd='''extends SceneTree
func _initialize():
    call_deferred("run")
func run():
    var page = load("res://scripts/game_night_theater_v3.gd").new()
    root.add_child(page)
    page.size = Vector2(880,850)
    page.configure(BOARD)
    var alternate = page.games[0].duplicate(true)
    alternate.game_id = "alternate-recorded-result"
    alternate.home_score += 1
    page.games.append(alternate)
    page._select_game(1)
    assert(page.game.game_id == "alternate-recorded-result")
    page._select_game(0)
    assert(page.court.tokens.size() == 10)
    var score = page.scoreboard.text
    page._toggle_play()
    page._process(6.1)
    assert(page.chapter_index == 1)
    page.speed = 4.0
    page._process(1.6)
    assert(page.chapter_index == 2)
    assert(page.scoreboard.text == score)
    assert(page.chapter_body.get_child_count() == 1)
    page.seek.value = 4
    assert(page.chapter_index == 4)
    assert(page.chapter_body.get_child_count() == 4)
    page._show_chapter(5)
    page._process(6.1)
    assert(not page.playing)
    page._toggle_play()
    assert(page.chapter_index == 0 and page.playing)
    page._play_sting()
    assert(page.audio_player.stream.data.size() == 13230)
    page.audio_player.stop()
    var main = load("res://scripts/main.gd").new()
    var nav = main._nav_button("THEATER")
    main.add_child(nav)
    assert(main.nav_buttons.has("THEATER"))
    main.theater_page = page
    assert(main._page_control("THEATER") == page)
    assert(page in main._all_page_controls())
    var game_day = load("res://scripts/game_day_center_v3.gd").new()
    assert(game_day.has_signal("navigate_requested"))
    game_day.free()
    main.free()
    page.configure({"games":[],"season":"2026-27"})
    assert(page.game.is_empty() and not page.playing)
    page.queue_free()
    await process_frame
    await process_frame
    print("THEATER46_RUNTIME_PASS")
    quit()
'''.replace('BOARD',json.dumps(board))
        script=folder/'theater46.gd';script.write_text(gd,encoding='utf-8')
        proc=subprocess.run([str(Path.home()/'Downloads/Godot_v4.0-stable_win64.exe'),'--headless','--path',str(ROOT/'godot_client'),'--script',str(script)],capture_output=True,text=True,timeout=40)
        output=proc.stdout+proc.stderr;print(output)
        assert proc.returncode==0 and 'THEATER46_RUNTIME_PASS' in output and 'SCRIPT ERROR' not in output
    assert hashes()==protected
    print('PASS: real simulator preview, box score reconciliation, deterministic read-only chapters, partial/undated results, archive cap, API, scratch reload, Godot lineup/playback/seek/speed/audio/navigation, protected saves')

if __name__=='__main__':main()
