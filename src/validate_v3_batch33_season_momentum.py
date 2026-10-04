from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v3-batch33-season-momentum-v1.0.0-2026-10-04"


def hashes() -> dict[str, str]:
    return {name: hashlib.sha256((ROOT / "outputs/runtime" / name).read_bytes()).hexdigest()
            for name in ("v3_godot_working_checkpoint.pkl.gz", "franchise_mode_checkpoint_v1.pkl.gz")}


GDSCRIPT = r'''extends SceneTree
func check(condition: bool, label: String) -> bool:
    if not condition:
        print("BATCH33_FAIL::" + label)
        quit(2)
    return condition
func _initialize():
    root.size = Vector2i(1440,900)
    var host = Control.new()
    host.size = Vector2(1000,850)
    root.add_child(host)
    var board = load("res://scripts/season_momentum_v3.gd").new()
    board.size = Vector2(980,800)
    host.add_child(board)
    var data = JSON.parse_string(FileAccess.get_file_as_string(FIXTURE_PATH))
    board.configure(data, Color("008348"))
    await process_frame
    if not check(board.milestone_cards.size() == 4 and board.result_cards.size() == 5 and board.chart.values.size() == 6, "saved_result_rendering"):
        return
    if not check(board.chart.values[-1] == 15 and board.chart.size.x <= 980, "chart_values_and_width"):
        return
    board.configure({"wins":0,"milestones":data.milestones,"recent":[]}, Color.GREEN)
    if not check(board.chart == null and board.result_cards.is_empty(), "empty_season_clears_previous_results"):
        return
    board.configure({}, Color.GREEN, "Offline")
    if not check(board.payload.is_empty() and board.get_child_count() == 2, "offline_clears_previous_progress"):
        return
    var output = FileAccess.open(MARKER_PATH,FileAccess.WRITE)
    output.store_string(JSON.stringify({"results_milestones_and_chart":true,"opening_and_offline_states":true}))
    output.close()
    quit(0)
'''


def backend_checks() -> dict[str,bool]:
    import asyncio, pickle, sys
    from types import SimpleNamespace as N
    sys.path.insert(0,str(ROOT))
    from desktop_bridge.season_momentum import build_season_momentum
    from desktop_bridge import server
    margins = [10,-5,20,-10,5,-5]
    games = {str(i):N(home_team="BOS" if i%2==0 else "SAS",away_team="SAS" if i%2==0 else "BOS",home_score=100+m if i%2==0 else 100,away_score=100 if i%2==0 else 100+m) for i,m in enumerate(margins)}
    state = N(settings=N(season_label="2026-27"), standings={"BOS":N(wins=10)},schedule={str(i):N(day_index=i) for i in range(6)},completed_games=games)
    original = pickle.dumps(state)
    global LIVE
    LIVE = build_season_momentum(state,"BOS")
    checks = dict(home_away_scoring=LIVE["cumulative_margin"]==15 and [r["margin"] for r in LIVE["trend"]]==margins,
        milestones=LIVE["milestones"][1]["achieved"] and LIVE["next_target"]["target"]==25,
        recent_five=len(LIVE["recent"])==5 and LIVE["recent"][0]["game_id"]=="1",
        builder_immutable=pickle.dumps(state)==original)
    state.completed_games["archive"] = games["0"]
    state.completed_games["other"] = N(home_team="LAL",away_team="MIA",home_score=110,away_score=100)
    state.schedule["other"] = N(day_index=7)
    checks["unlinked_and_other_teams_excluded"] = build_season_momentum(state,"BOS")["games_tracked"]==6
    state.standings["BOS"].wins = 40
    checks["all_milestones_reached"] = build_season_momentum(state,"BOS")["next_target"] is None
    state.standings.clear()
    checks["missing_record_unknown"] = build_season_momentum(state,"BOS")["wins"] is None
    empty = N(settings=state.settings,standings={"BOS":N(wins=0)},schedule={},completed_games={})
    opening = build_season_momentum(empty,"BOS")
    checks["opening_season_no_fabricated_margin"] = opening["cumulative_margin"] is None and opening["trend"] == [] and opening["next_target"]["target"] == 1
    negative = N(settings=state.settings,standings=empty.standings,schedule={"1":N(day_index=1)},completed_games={"1":N(home_team="BOS",away_team="SAS",home_score=90,away_score=110)})
    checks["negative_margin_preserved"] = build_season_momentum(negative,"BOS")["trend"][0]["cumulative_margin"] == -20
    checkpoint=server._working_checkpoint()
    before=pickle.dumps(checkpoint.simulation_state)
    response=asyncio.run(server.franchise_intelligence(None))
    payload=json.loads(response.body)
    checks["live_endpoint_and_cached_state"] = response.status_code==200 and payload["momentum"]["team"]==payload["team"] and pickle.dumps(checkpoint.simulation_state)==before
    return checks


def main() -> int:
    before = hashes()
    godot = Path(os.environ["USERPROFILE"]) / "Downloads/Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console
    results: dict[str, bool] = backend_checks()
    with tempfile.TemporaryDirectory(prefix="v3_batch33_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "smoke.gd"
        fixture = Path(scratch) / "fixture.json"
        fixture.write_text(json.dumps(LIVE), encoding="utf-8")
        script.write_text(GDSCRIPT.replace("MARKER_PATH", json.dumps(marker.as_posix())).replace("FIXTURE_PATH", json.dumps(fixture.as_posix())), encoding="utf-8")
        try:
            proc = subprocess.run([str(godot), "--headless", "--path", "godot_client", "--script", str(script)], cwd=ROOT, capture_output=True, text=True, timeout=30)
            combined = proc.stdout + "\n" + proc.stderr
            print(combined[-8000:])
            results["godot_runtime_completed"] = proc.returncode == 0 and marker.exists() and not any(value in combined.lower() for value in ["script error", "parse error", "batch33_fail", "failed to load script"])
            if results["godot_runtime_completed"]:
                results.update(json.loads(marker.read_text(encoding="utf-8")))
        except (subprocess.TimeoutExpired, OSError) as exc:
            results["godot_runtime_completed"] = False
            print(exc)
    results["active_v3_and_protected_v2_unchanged"] = hashes() == before
    out = ROOT / "outputs/v3_batch33_season_momentum"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(json.dumps({"version": VERSION, "results": results}, indent=2), encoding="utf-8")
    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    passed = all(results.values())
    print("V3 BATCH 33 SEASON MOMENTUM VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
