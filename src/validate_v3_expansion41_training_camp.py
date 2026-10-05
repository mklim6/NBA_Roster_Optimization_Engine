from __future__ import annotations
import copy
import asyncio
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as N

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from desktop_bridge.training_camp_foundation import camp_summary, build_camp_candidate, WEIGHTS
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint, save_franchise_checkpoint, DEFAULT_CHECKPOINT_PATH


def fixture():
    players = {str(i): N(player_name=f"Player {i}", age=21, overall_rating=72., potential_rating=86.,
                development_history=[], stat_factors={}, **{field: 72. for field in WEIGHTS}) for i in range(8)}
    return N(simulation_state=N(settings=N(season_label="2026-27"), phase="offseason", players=players,
                teams={"BOS": N(roster_player_ids=list(players)[:4]), "LAL": N(roster_player_ids=list(players)[4:])}), preferences={})


def main():
    protected = [ROOT / "outputs/runtime/v3_godot_working_checkpoint.pkl.gz", Path(DEFAULT_CHECKPOINT_PATH)]
    hashes = lambda: [hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None for p in protected]
    before = hashes()
    source = fixture()
    original = copy.deepcopy(source)
    plans = {"0": "shooting", "1": "defense"}
    candidate = build_camp_candidate(source, "BOS", plans)
    assert source == original, "Preview mutated source"
    assert candidate.preferences == build_camp_candidate(source, "BOS", plans).preferences
    assert len(camp_summary(candidate, "LAL")["results"]) == 3
    next_year = copy.deepcopy(candidate)
    next_year.simulation_state.settings.season_label = "2027-28"
    assert camp_summary(next_year, "BOS")["available"]
    injured = fixture()
    injured.simulation_state.injuries = {"0": N(status="injured")}
    assert "0" not in {p["player_id"] for p in camp_summary(injured, "BOS")["players"]}
    for p in candidate.simulation_state.players.values():
        assert p.potential_rating == 86 and p.age == 21
        assert not p.development_history
        if getattr(p, "training_camp_history", []):
            assert 0 <= p.training_camp_history[-1]["gain"] <= 1.5
            assert p.stat_factors
    for checkpoint, assignments in [(candidate, plans), (source, {"7": "shooting"}), (source, {"0": "invalid"}), (source, {}), (source, {str(i): "shooting" for i in range(4)})]:
        try:
            build_camp_candidate(checkpoint, "BOS", assignments)
            raise AssertionError("Invalid camp accepted")
        except ValueError:
            pass
    source.simulation_state.phase = "regular_season"
    try:
        build_camp_candidate(source, "BOS", plans)
        raise AssertionError("In-season camp accepted")
    except ValueError:
        pass
    # Real checkpoint preview and durable reload entirely in scratch storage.
    real = load_franchise_checkpoint(path=protected[0])
    if real:
        real = copy.deepcopy(real)
        real.simulation_state.phase = "offseason"
        real.preferences.pop("v3_training_camp_history", None)
        team = real.preferences["franchise_pref_active_team"]
        roster = camp_summary(real, team)["players"]
        assert roster
        updated = build_camp_candidate(real, team, {roster[0]["player_id"]: "shooting"})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "camp.pkl.gz"
            save_franchise_checkpoint(updated.simulation_state, updated.trade_state, preferences=updated.preferences,
                                     path=path, reason="Camp validation fixture", copy_payload=False, force_replace=True)
            reloaded = load_franchise_checkpoint(path=path)
            assert camp_summary(reloaded, team)["results"] == camp_summary(updated, team)["results"]
            # Exercise real bridge handler writes against temporary checkpoints.
            from desktop_bridge import server
            from starlette.requests import Request
            old_v3, old_v2 = server.V3_WORKING_CHECKPOINT_PATH, server.DEFAULT_CHECKPOINT_PATH
            old_root = server.REPO_ROOT
            server.V3_WORKING_CHECKPOINT_PATH = path
            server.DEFAULT_CHECKPOINT_PATH = protected[1]
            server.REPO_ROOT = Path(folder)
            save_franchise_checkpoint(real.simulation_state, real.trade_state, preferences=real.preferences,
                                     path=path, reason="Endpoint fixture", copy_payload=False, force_replace=True)
            async def invoke(body):
                async def receive():
                    return {"type":"http.request", "body":json.dumps(body).encode(), "more_body":False}
                return await server.training_camp(Request({"type":"http", "method":"POST", "path":"/v3/training-camp", "headers":[]}, receive))
            try:
                start_hash = hashlib.sha256(path.read_bytes()).hexdigest()
                body = {"action":"preview", "assignments":{roster[0]["player_id"]:"shooting"}, "expected_working_save_sha256":start_hash}
                preview = asyncio.run(invoke(body))
                assert preview.status_code == 200, preview.body
                assert hashlib.sha256(path.read_bytes()).hexdigest() == start_hash
                stale = asyncio.run(invoke({**body, "action":"execute", "expected_working_save_sha256":"stale"}))
                assert stale.status_code == 409
                execution = asyncio.run(invoke({**body, "action":"execute"}))
                assert execution.status_code == 200, execution.body
                assert json.loads(execution.body)["results"] == json.loads(preview.body)["results"]
                assert asyncio.run(invoke({**body, "action":"execute"})).status_code == 409
                assert list((Path(folder)/"outputs/runtime/v3_camp_recovery").glob("*.gz"))
            finally:
                server.V3_WORKING_CHECKPOINT_PATH, server.DEFAULT_CHECKPOINT_PATH = old_v3, old_v2
                server.REPO_ROOT = old_root
    work = ROOT / "work"
    work.mkdir(exist_ok=True)
    script = work / "camp41_runtime.gd"
    script.write_text('''extends SceneTree
func _initialize():
    call_deferred("run")
func run():
    var page = load("res://scripts/training_camp_v3.gd").new()
    root.add_child(page)
    page.request.cancel_request()
    page.report = {"available":true,"working_save_sha256":"fixture","focuses":["shooting","defense"],"players":[{"player_id":"0","name":"Camp Player","age":21,"overall":72,"potential":86,"skills":{"shooting":72,"defense":72}}]}
    page._render_roster()
    assert(page.grid.get_child_count() == 1)
    var choices = OptionButton.new()
    page.add_child(choices)
    page._choose(1,"0",choices)
    assert(page.plans["0"] == "shooting")
    page._render_results([{"name":"Camp Player","focus":"shooting","before":72,"after":73,"gain":1,"tradeoff":"defense","tradeoff_before":72,"tradeoff_after":71.75,"overall_before":72,"overall_after":72.1}],false)
    assert(page.results.get_child_count() == 1)
    page._play_chime()
    assert(page.audio_player.stream.data.size() == 22050)
    page.size.x = 600
    page._resize_cards()
    assert(page.grid.columns == 1)
    page.queue_free()
    await process_frame
    await process_frame
    print("CAMP41_RUNTIME_PASS")
    quit()
''', encoding="utf-8")
    proc = subprocess.run([str(Path.home()/"Downloads/Godot_v4.0-stable_win64.exe"), "--headless", "--path", str(ROOT/"godot_client"), "--script", str(script)], capture_output=True, text=True, timeout=30)
    output = proc.stdout + proc.stderr
    script.unlink(missing_ok=True)
    print(output)
    assert proc.returncode == 0 and "CAMP41_RUNTIME_PASS" in output and "SCRIPT ERROR" not in output
    assert hashes() == before, "Protected checkpoints changed"
    print("PASS: deterministic preview, validation, repeat protection, CPU parity, skill/stat integration, durable reload, Godot UI/audio, protected saves")


if __name__ == "__main__":
    main()
