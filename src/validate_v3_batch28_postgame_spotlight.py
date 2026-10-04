from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v3-batch28-trade-experience-v1.0.0-2026-10-04"


def hashes() -> dict[str, str]:
    return {name: hashlib.sha256((ROOT / "outputs/runtime" / name).read_bytes()).hexdigest()
            for name in ("v3_godot_working_checkpoint.pkl.gz", "franchise_mode_checkpoint_v1.pkl.gz")}


GDSCRIPT = r'''extends SceneTree
func check(condition: bool, label: String) -> bool:
    if not condition:
        print("BATCH28_FAIL::" + label)
        quit(2)
    return condition
func _initialize():
    root.size = Vector2i(1440, 900)
    var page = load("res://scripts/game_day_center_v3.gd").new()
    root.add_child(page)
    page.size = Vector2(1126, 900)
    await process_frame
    page.active_team = "BOS"
    var game = {"home_team": "SAS", "away_team": "BOS", "home_score": 100, "away_score": 110, "player_box_scores": [{"team": "BOS", "player_id": "a", "name": "Alpha", "points": 30, "rebounds": 10, "assists": 5, "turnovers": 2, "three_pointers_made": 4}, {"team": "BOS", "player_id": "b", "name": "Beta", "points": 20, "rebounds": 8, "assists": 2, "turnovers": 1, "three_pointers_made": 1}, {"team": "SAS", "player_id": "c", "name": "Opponent", "points": 25, "rebounds": 7, "assists": 3, "turnovers": 4, "three_pointers_made": 2}]}
    page._render_postgame(game)
    var spotlight = page.postgame_spotlight
    if not check(spotlight.find_child("PostgameStar_BOS", true, false) != null and spotlight.find_child("PostgameStar_SAS", true, false) != null, "both_team_portraits"):
        return
    if not check(spotlight.comparisons.rebounds == [18.0, 7.0] and "WIN" in page.postgame_result_label.text, "away_team_orientation_and_totals"):
        return
    game.player_box_scores[1].rebounds = null
    spotlight.configure(game, "BOS")
    if not check(spotlight.comparisons.rebounds[0] == null, "missing_stat_not_zero"):
        return
    game.player_box_scores = []
    spotlight.configure(game, "BOS")
    if not check(spotlight.comparisons.assists == [null, null], "empty_team_stats_unavailable"):
        return
    page._render_postgame(game)
    for frame in range(8):
        await process_frame
    if not check(spotlight.size.x <= page.size.x and spotlight.get_child_count() == 3, "layout_and_no_stale_players"):
        return
    page._reset_postgame()
    if not check(spotlight.game.is_empty() and spotlight.comparisons.is_empty(), "reset_removes_previous_game"):
        return
    if not check(page.simulate_request.get_http_client_status() == HTTPClient.STATUS_DISCONNECTED and not page.simulate_armed, "no_simulation_sent"):
        return
    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({"portrait_stars": true, "team_stat_comparison": true, "away_orientation": true, "missing_stats": true, "reset_and_layout": true, "simulation_untouched": true}))
    output.close()
    quit(0)
'''


def main() -> int:
    before = hashes()
    godot = Path(os.environ["USERPROFILE"]) / "Downloads/Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console
    results: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="v3_batch28_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "smoke.gd"
        script.write_text(GDSCRIPT.replace("MARKER_PATH", json.dumps(marker.as_posix())), encoding="utf-8")
        try:
            proc = subprocess.run([str(godot), "--headless", "--path", "godot_client", "--script", str(script)], cwd=ROOT, capture_output=True, text=True, timeout=30)
            combined = proc.stdout + "\n" + proc.stderr
            print(combined[-8000:])
            results["godot_runtime_completed"] = proc.returncode == 0 and marker.exists() and not any(value in combined.lower() for value in ["script error", "parse error", "batch28_fail", "failed to load script"])
            if results["godot_runtime_completed"]:
                results.update(json.loads(marker.read_text(encoding="utf-8")))
        except (subprocess.TimeoutExpired, OSError) as exc:
            results["godot_runtime_completed"] = False
            print(exc)
    results["active_v3_and_protected_v2_unchanged"] = hashes() == before
    out = ROOT / "outputs/v3_batch28_postgame_spotlight"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(json.dumps({"version": VERSION, "results": results}, indent=2), encoding="utf-8")
    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    passed = all(results.values())
    print("V3 BATCH 28 POSTGAME SPOTLIGHT VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
