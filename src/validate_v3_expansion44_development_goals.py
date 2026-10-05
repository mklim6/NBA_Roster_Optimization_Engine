from __future__ import annotations
import asyncio
import copy
from dataclasses import replace
import hashlib
import json
import pickle
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as N

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT),str(ROOT/"src")]
from desktop_bridge.development_goals import goals_board, build_goals_candidate, KEY
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint, save_franchise_checkpoint, DEFAULT_CHECKPOINT_PATH
from starlette.requests import Request


def main():
    paths = [ROOT/"outputs/runtime/v3_godot_working_checkpoint.pkl.gz",Path(DEFAULT_CHECKPOINT_PATH)]
    hashes = lambda: [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
    protected_before = hashes()
    original = load_franchise_checkpoint(path=paths[0])
    real = copy.deepcopy(original)
    real.preferences.pop(KEY,None)
    real.simulation_state.phase = "regular_season"
    team = real.preferences["franchise_pref_active_team"]
    players = goals_board(real,team)["players"]
    pid, other = players[0]["player_id"],players[1]["player_id"]
    real.simulation_state.players[pid].skill_ratings["shooting_rating"] = 70.
    selections = [{"player_id":pid,"metric":"shooting","delta":2},{"player_id":other,"metric":"opportunity","target":15}]
    state_before = pickle.dumps(real.simulation_state)
    candidate = build_goals_candidate(real,team,selections)
    assert pickle.dumps(real.simulation_state) == state_before
    assert pickle.dumps(candidate.simulation_state) == state_before
    board = goals_board(candidate,team)
    assert board["committed"] and len(board["goals"]) == 2 and not board["can_commit"]
    from desktop_bridge.training_camp_foundation import camp_summary
    assert camp_summary(candidate,team)["development_goals"][0]["target"] == 72.
    grown = copy.deepcopy(candidate)
    grown.simulation_state.players[pid].skill_ratings["shooting_rating"] = 72.
    grown.simulation_state.player_season_totals[other] = N(games_played=9,minutes=180.)
    assert goals_board(grown,team)["goals"][0]["status"] == "target_met"
    assert goals_board(grown,team)["goals"][1]["status"] == "in_progress"
    grown.simulation_state.player_season_totals[other].games_played = 10
    assert goals_board(grown,team)["goals"][1]["status"] == "target_met"
    previous_season = grown.simulation_state.settings.season_label
    grown.simulation_state.settings = replace(grown.simulation_state.settings,season_label="2099-00")
    grown.simulation_state.season_history.append(N(season_label=previous_season,player_season_totals={other:N(games_played=10,minutes=180.)}))
    assert goals_board(grown,team)["archive"][0]["status"] == "unverified"
    grown.simulation_state.players[pid].development_history.append({"source_season":previous_season,"skill_deltas":{"shooting_rating":2.5}})
    archive = goals_board(grown,team)["archive"]
    assert archive[0]["status"] == "achieved" and archive[0]["current"] == 72.5
    assert archive[1]["status"] == "achieved"
    assert goals_board(grown,team)["can_commit"]
    for invalid in [[],selections*2,[{"player_id":"missing","metric":"shooting","delta":1}],[{"player_id":pid,"metric":"unknown","delta":1}],[{"player_id":pid,"metric":"shooting","delta":float("nan")}]]:
        try:
            build_goals_candidate(real,team,invalid)
            raise AssertionError("Invalid goals accepted")
        except ValueError:
            pass
    try:
        build_goals_candidate(candidate,team,selections)
        raise AssertionError("Committed plan overwritten")
    except ValueError:
        pass
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        staged = folder/"working.pkl.gz"
        save_franchise_checkpoint(real.simulation_state,real.trade_state,preferences=real.preferences,path=staged,reason="Goal test source",copy_payload=False,force_replace=True)
        from desktop_bridge import server
        old_path,old_v2,old_root = server.V3_WORKING_CHECKPOINT_PATH,server.DEFAULT_CHECKPOINT_PATH,server.REPO_ROOT
        server.V3_WORKING_CHECKPOINT_PATH,server.DEFAULT_CHECKPOINT_PATH,server.REPO_ROOT = staged,paths[1],folder
        async def invoke(body):
            async def receive():
                return {"type":"http.request","body":json.dumps(body).encode(),"more_body":False}
            return await server.development_goals(Request({"type":"http","method":"POST","path":"/v3/development-goals","headers":[]},receive))
        try:
            before = hashlib.sha256(staged.read_bytes()).hexdigest()
            body = {"action":"preview","selections":selections,"expected_working_save_sha256":before}
            response = asyncio.run(invoke(body))
            assert response.status_code == 200,response.body
            assert hashlib.sha256(staged.read_bytes()).hexdigest() == before
            assert asyncio.run(invoke({**body,"expected_working_save_sha256":"stale","action":"execute"})).status_code == 409
            execution = asyncio.run(invoke({**body,"action":"execute"}))
            assert execution.status_code == 200,execution.body
            assert json.loads(response.body)["goals"] == json.loads(execution.body)["goals"]
            restored = load_franchise_checkpoint(path=staged)
            assert goals_board(restored,team)["committed"]
            assert restored.simulation_state.players[pid].skill_ratings["shooting_rating"] == 70.
            assert asyncio.run(invoke({**body,"action":"execute"})).status_code == 409
        finally:
            server.V3_WORKING_CHECKPOINT_PATH,server.DEFAULT_CHECKPOINT_PATH,server.REPO_ROOT = old_path,old_v2,old_root
        gd = '''extends SceneTree
func _initialize():
    call_deferred("run")
func run():
    var page = load("res://scripts/development_command_center_v3.gd").new()
    root.add_child(page)
    page.size = Vector2(900,850)
    page.configure(EMPTY_BOARD)
    assert(page.forms.size() == 3)
    page.forms[0].player.select(1)
    page.forms[0].player.item_selected.emit(1)
    assert(page._selections().size() == 1)
    page.forms[0].metric.select(4)
    page.forms[0].metric.item_selected.emit(4)
    assert(page._selections()[0].target == 10)
    page.forms[2].player.select(3)
    page.forms[2].player.item_selected.emit(3)
    assert(page._selections().size() == 2)
    assert(page._selections()[1].player_id == page.board.players[2].player_id)
    page.configure(COMMITTED_BOARD)
    assert(page.find_child("GoalProgress_PLAYERID",true,false) != null)
    assert(page.forms.is_empty())
    var main_script = load("res://scripts/main.gd")
    assert(main_script != null)
    var main = main_script.new()
    var nav = main._nav_button("DEVELOPMENT")
    main.add_child(nav)
    assert(main.nav_buttons.has("DEVELOPMENT"))
    assert(nav.get_signal_connection_list("pressed").size() > 0)
    main.development_page = page
    assert(main._page_control("DEVELOPMENT") == page)
    assert(page in main._all_page_controls())
    main.free()
    page.queue_free()
    await process_frame
    await process_frame
    print("GOALS44_RUNTIME_PASS")
    quit()
'''.replace("EMPTY_BOARD",json.dumps(goals_board(real,team))).replace("COMMITTED_BOARD",json.dumps(board)).replace("PLAYERID",pid)
        script = folder/"goals44.gd"
        script.write_text(gd,encoding="utf-8")
        proc = subprocess.run([str(Path.home()/"Downloads/Godot_v4.0-stable_win64.exe"),"--headless","--path",str(ROOT/"godot_client"),"--script",str(script)],capture_output=True,text=True,timeout=30)
        output = proc.stdout+proc.stderr
        print(output)
        assert proc.returncode == 0 and "GOALS44_RUNTIME_PASS" in output and "SCRIPT ERROR" not in output
    assert hashes() == protected_before
    print("PASS: fixed season commitments, actual progress and appearance threshold, archival evidence, invalid/stale/repeated requests, durable reload, ratings unchanged, Godot forms/cards/navigation, protected saves")


if __name__ == "__main__":
    main()
