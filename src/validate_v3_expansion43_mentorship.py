from __future__ import annotations
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/"src")]
from validate_v3_expansion41_training_camp import fixture
from desktop_bridge.training_camp_foundation import build_camp_candidate, camp_summary, mentor_options
from desktop_bridge.player_career_history import career_history
from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH, load_franchise_checkpoint, save_franchise_checkpoint


def main():
    protected = [ROOT/"outputs/runtime/v3_godot_working_checkpoint.pkl.gz",Path(DEFAULT_CHECKPOINT_PATH)]
    hashes = lambda: [hashlib.sha256(p.read_bytes()).hexdigest() for p in protected]
    before = hashes()
    source = fixture()
    source.simulation_state.players["3"].age = 31
    source.simulation_state.players["3"].shooting_rating = 92
    source.simulation_state.players["7"].age = 32
    source.simulation_state.players["7"].shooting_rating = 94
    original = copy.deepcopy(source)
    plans = {"0":"shooting"}
    paired = build_camp_candidate(source,"BOS",plans,{"0":"3"})
    solo = build_camp_candidate(source,"BOS",plans)
    result = camp_summary(paired,"BOS")["results"][0]
    solo_result = camp_summary(solo,"BOS")["results"][0]
    assert result["gain"] >= solo_result["gain"] and result["gain"] <= 1.5
    assert result["unmentored_gain"] == solo_result["gain"]
    assert result["mentor_id"] == "3"
    assert paired.simulation_state.players["3"].mentorship_history[0]["learner_id"] == "0"
    assert not paired.simulation_state.players["3"].development_history
    veteran_history = career_history(paired.simulation_state.players["3"])
    assert veteran_history["mentor_events"] == 1 and veteran_history["events"][0]["delta"] == 0
    assert career_history(paired.simulation_state.players["0"])["events"][0]["mentor_name"] == "Player 3"
    assert any(row["mentor_id"] == "7" for row in camp_summary(paired,"LAL")["results"])
    assert source == original
    assert paired.preferences == build_camp_candidate(source,"BOS",plans,{"0":"3"}).preferences
    for assignments, mentors in [(plans,{"0":"0"}),(plans,{"0":"7"}),(plans,{"0":"1"}),({"0":"shooting","1":"shooting"},{"0":"3","1":"3"}),({"0":"shooting","3":"defense"},{"0":"3"}),(plans,{"1":"3"}),(plans,[])]:
        try:
            build_camp_candidate(source,"BOS",assignments,mentors)
            raise AssertionError("Invalid partnership accepted")
        except ValueError:
            pass
    older = copy.deepcopy(source)
    older.simulation_state.players["0"].age = 25
    assert not mentor_options(camp_summary(older,"BOS")["players"],"0","shooting")
    real = copy.deepcopy(load_franchise_checkpoint(path=protected[0]))
    real.simulation_state.phase = "offseason"
    real.preferences.pop("v3_training_camp_history",None)
    team = real.preferences["franchise_pref_active_team"]
    roster = camp_summary(real,team)["players"]
    learner_id, mentor_id = roster[0]["player_id"], roster[1]["player_id"]
    learner = real.simulation_state.players[learner_id]
    mentor = real.simulation_state.players[mentor_id]
    learner.age, mentor.age = 21, 31
    learner.skill_ratings["shooting_rating"], mentor.skill_ratings["shooting_rating"] = 65., 90.
    durable = build_camp_candidate(real,team,{learner_id:"shooting"},{learner_id:mentor_id})
    with tempfile.TemporaryDirectory() as directory:
        save_path = Path(directory)/"mentored.pkl.gz"
        save_franchise_checkpoint(durable.simulation_state,durable.trade_state,preferences=durable.preferences,
                                 path=save_path,reason="Mentorship validation fixture",copy_payload=False,force_replace=True)
        restored = load_franchise_checkpoint(path=save_path)
        assert restored.simulation_state.players[learner_id].training_camp_history[-1]["mentor_id"] == mentor_id
        assert restored.simulation_state.players[mentor_id].mentorship_history[-1]["learner_id"] == learner_id
        assert camp_summary(restored,team)["results"] == camp_summary(durable,team)["results"]
    history = camp_summary(paired,"BOS")
    report = camp_summary(source,"BOS")
    gd = '''extends SceneTree
func _initialize():
    call_deferred("run")
func run():
    var page = load("res://scripts/training_camp_v3.gd").new()
    root.add_child(page)
    page.request.cancel_request()
    page.report = REPORT
    page._render_roster()
    var choices = OptionButton.new()
    page.add_child(choices)
    page._choose(1,"0",choices)
    assert(page.mentor_choices["0"] == ["3"])
    page._choose_mentor(1,"0")
    assert(page.mentors["0"] == "3")
    page.preview_ready = true
    page._choose_mentor(0,"0")
    assert(not page.preview_ready and page.mentors.is_empty())
    page._choose_mentor(1,"0")
    page._render_results(RESULTS,false)
    assert("Player 3".to_upper() in page.results.get_child(0).get_child(0).get_child(3).text)
    page._choose(3,"3",choices)
    assert(page.mentors.is_empty())
    page.queue_free()
    await process_frame
    await process_frame
    print("MENTOR43_RUNTIME_PASS")
    quit()
'''.replace("REPORT",json.dumps(report)).replace("RESULTS",json.dumps(history["results"]))
    with tempfile.TemporaryDirectory() as directory:
        script = Path(directory)/"mentor43.gd"
        script.write_text(gd,encoding="utf-8")
        proc = subprocess.run([str(Path.home()/"Downloads/Godot_v4.0-stable_win64.exe"),"--headless","--path",str(ROOT/"godot_client"),"--script",str(script)],capture_output=True,text=True,timeout=30)
        output = proc.stdout+proc.stderr
        print(output)
        assert proc.returncode == 0 and "MENTOR43_RUNTIME_PASS" in output and "SCRIPT ERROR" not in output
    assert hashes() == before
    print("PASS: mentor eligibility/exclusivity, bounded deterministic benefit, CPU pairing, veteran/learner memory, source immutability, UI pairing and preview invalidation, protected saves")


if __name__ == "__main__":
    main()
