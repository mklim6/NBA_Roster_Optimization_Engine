from __future__ import annotations
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as N

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/"src")]
from desktop_bridge.player_career_history import career_history
from desktop_bridge.front_office_foundation import _player_development_rows
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint, DEFAULT_CHECKPOINT_PATH


def main():
    paths = [ROOT/"outputs/runtime/v3_godot_working_checkpoint.pkl.gz", Path(DEFAULT_CHECKPOINT_PATH)]
    hashes = lambda: [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
    before = hashes()
    player = N(development_history=[dict(source_season="2026-27",target_season="2027-28",current_overall_rating=72.1,projected_overall_rating=75.,skill_deltas={"shooting_rating":2.3}),dict(source_season="2027-28",target_season="2028-29",current_overall_rating=75.,projected_overall_rating=74.5,skill_deltas={"defense_rating":-.8})],
               training_camp_history=[dict(season="2026-27",focus="shooting",gain=1.2,overall_before=72.,overall_after=72.1,tradeoff="playmaking",tradeoff_before=70.,tradeoff_after=69.75)])
    original = copy.deepcopy(player)
    history = career_history(player)
    assert player == original
    assert [row["kind"] for row in history["events"]] == ["camp", "season", "season"]
    assert history["total_events"] == 3 and history["recorded_change"] == 2.5
    assert history["events"][0]["skills"]["playmaking"] == -.25
    assert career_history(N())["recorded_change"] is None
    partial = career_history(N(development_history=[{"current_overall_rating":float("nan"), "skill_deltas":None}]))
    assert partial["events"][0]["delta"] is None
    json.dumps(partial, allow_nan=False)
    long = career_history(N(development_history=player.development_history * 30))
    assert len(long["events"]) == 40 and long["total_events"] == 60
    checkpoint = load_franchise_checkpoint(path=paths[0])
    state = checkpoint.simulation_state
    team = checkpoint.preferences["franchise_pref_active_team"]
    rows = _player_development_rows(state, team)
    assert rows and all("career_history" in row for row in rows)
    gd = '''extends SceneTree
func _initialize():
    call_deferred("run")
func run():
    root.size = Vector2i(1100,850)
    var lab = load("res://scripts/development_lab_v3.gd").new()
    root.add_child(lab)
    lab.size = Vector2(800,850)
    lab.configure({"full_roster":[{"player_id":"fixture","name":"Career Player","age":23,"overall":74.5,"potential":86,"career_history":HISTORY}]})
    var career = lab.find_child("PlayerCareerHistory",true,false)
    assert(career != null)
    assert(career.timeline.get_child_count() == 3)
    var chart = career.find_child("CareerChangeChart",true,false)
    assert(chart.events.size() == 3)
    var body = career.timeline.get_child(0).get_child(0)
    assert(not body.get_child(3).visible)
    body.get_child(2).pressed.emit()
    assert(body.get_child(3).visible)
    body.get_child(2).pressed.emit()
    assert(not body.get_child(3).visible)
    career.configure({"total_events":0})
    assert(career.get_child_count() == 2)
    lab.clear_report()
    assert(lab.find_child("PlayerCareerHistory",true,false) == null)
    lab.queue_free()
    await process_frame
    await process_frame
    print("CAREER42_RUNTIME_PASS")
    quit()
'''.replace("HISTORY", json.dumps(history))
    with tempfile.TemporaryDirectory() as directory:
        script = Path(directory)/"career42.gd"
        script.write_text(gd,encoding="utf-8")
        proc = subprocess.run([str(Path.home()/"Downloads/Godot_v4.0-stable_win64.exe"), "--headless", "--path", str(ROOT/"godot_client"), "--script",str(script)],capture_output=True,text=True,timeout=30)
        output = proc.stdout + proc.stderr
        print(output)
        assert proc.returncode == 0 and "CAREER42_RUNTIME_PASS" in output and "SCRIPT ERROR" not in output
    assert hashes() == before
    print("PASS: recorded event mapping/order, missing/invalid ratings, camp costs, bounded history, real roster integration, timeline interaction, empty and refresh states, protected saves")


if __name__ == "__main__":
    main()
