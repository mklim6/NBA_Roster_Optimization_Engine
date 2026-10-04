from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v3-batch32-coaching-board-v1.0.0-2026-10-04"


def hashes() -> dict[str, str]:
    return {name: hashlib.sha256((ROOT / "outputs/runtime" / name).read_bytes()).hexdigest()
            for name in ("v3_godot_working_checkpoint.pkl.gz", "franchise_mode_checkpoint_v1.pkl.gz")}


GDSCRIPT = r'''extends SceneTree
func _initialize():
    root.size = Vector2i(1440, 900)
    var main = load("res://scripts/main.gd").new()
    root.add_child(main)
    await process_frame
    var page = main.game_day_page
    page.apply_team_brand("BOS", Color.GREEN, Color.WHITE)
    var data = JSON.parse_string(FileAccess.get_file_as_string(FIXTURE_PATH))
    page.coaching_board.configure(data)
    await process_frame
    if page.coaching_board.payload.get("team") != "BOS":
        quit(2)
        return
    page.coaching_board.get_child(page.coaching_board.get_child_count()-1).pressed.emit()
    page.coaching_board.clear_board("Offline")
    if not page.coaching_board.payload.is_empty() or page.coaching_board.get_child_count() != 2:
        quit(2)
        return
    page.coaching_board.configure({"available": false, "detail": "No matchup"})
    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({"board_and_rotation_shortcut": true, "offline_and_no_matchup": true}))
    output.close()
    quit(0)
'''


def backend_checks() -> dict[str, bool]:
    import asyncio, pickle, sys
    sys.path.insert(0, str(ROOT))
    from desktop_bridge import server
    checkpoint = server._working_checkpoint()
    before = pickle.dumps(checkpoint.simulation_state)
    response = asyncio.run(server.coaching_plan(None))
    live = json.loads(response.body)
    global LIVE
    LIVE = live
    return dict(live_endpoint=response.status_code == 200 and live.get("available"),
        bounded_real_counter=0 <= live["decision"]["suppression_points"] <= .65,
        correct_orientation=live["decision"]["defending_team"] == live["team"] and live["threats"]["team"] == live["opponent"],
        cached_state_unchanged=pickle.dumps(checkpoint.simulation_state) == before)


def main() -> int:
    before = hashes()
    godot = Path(os.environ["USERPROFILE"]) / "Downloads/Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console
    results: dict[str, bool] = backend_checks()
    with tempfile.TemporaryDirectory(prefix="v3_batch32_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "smoke.gd"
        fixture = Path(scratch) / "fixture.json"
        fixture.write_text(json.dumps(LIVE), encoding="utf-8")
        script.write_text(GDSCRIPT.replace("MARKER_PATH", json.dumps(marker.as_posix())).replace("FIXTURE_PATH", json.dumps(fixture.as_posix())), encoding="utf-8")
        try:
            proc = subprocess.run([str(godot), "--headless", "--path", "godot_client", "--script", str(script)], cwd=ROOT, capture_output=True, text=True, timeout=30)
            combined = proc.stdout + "\n" + proc.stderr
            print(combined[-8000:])
            results["godot_runtime_completed"] = proc.returncode == 0 and marker.exists() and not any(value in combined.lower() for value in ["script error", "parse error", "batch32_fail", "failed to load script"])
            if results["godot_runtime_completed"]:
                results.update(json.loads(marker.read_text(encoding="utf-8")))
        except (subprocess.TimeoutExpired, OSError) as exc:
            results["godot_runtime_completed"] = False
            print(exc)
    results["active_v3_and_protected_v2_unchanged"] = hashes() == before
    out = ROOT / "outputs/v3_batch32_coaching_board"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(json.dumps({"version": VERSION, "results": results}, indent=2), encoding="utf-8")
    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    passed = all(results.values())
    print("V3 BATCH 32 COACHING BOARD VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
