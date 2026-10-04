from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v3-batch27-trade-experience-v1.0.0-2026-10-04"


def hashes() -> dict[str, str]:
    return {name: hashlib.sha256((ROOT / "outputs/runtime" / name).read_bytes()).hexdigest()
            for name in ("v3_godot_working_checkpoint.pkl.gz", "franchise_mode_checkpoint_v1.pkl.gz")}


GDSCRIPT = r'''extends SceneTree
func check(condition: bool, label: String) -> bool:
    if not condition:
        print("BATCH27_FAIL::" + label)
        quit(2)
    return condition
func _initialize():
    root.size = Vector2i(1440, 900)
    var main = load("res://scripts/main.gd").new()
    root.add_child(main)
    main.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    await process_frame
    var summary = {"team": {"abbreviation": "BOS", "name": "Boston Celtics"}, "season": {"label": "2026-27", "phase": "regular_season"}, "record": {"games_played": 0, "wins": 0, "display": "0-0"}, "next_game": {"opponent_name": "Spurs", "opponent": "SAS", "is_home": true}, "financial": {"cap_space_display": "-$30.8M", "is_estimate": true}, "draft": {"draft_year": 2027}}
    main._apply_franchise_summary(summary)
    var hq = main.hq_story
    if not check(hq.get_child(1).text == "A new chapter starts here", "opening_briefing"):
        return
    var routed = []
    hq.navigate.connect(func(page): routed.append(page))
    var next_button = hq.get_child(4).get_child(0).get_child(2)
    next_button.pressed.emit()
    if not check(routed == ["GAME DAY"], "next_move_routes_without_simulating"):
        return
    hq.configure_intelligence({"team": "BOS", "front_office": {"injured_players": [{"name": "Player"}], "rotation": {"starters": 5, "total_minutes": 240}}, "league": {"recent_results": []}})
    if not check("availability" in hq.get_child(4).get_child(0).get_child(0).text, "injury_priority"):
        return
    hq.configure_intelligence({"team": "BOS", "front_office": {"rotation": {"starters": 4, "total_minutes": 200}}, "league": {"recent_results": [{"away_team": "BOS", "away_score": 110, "home_team": "SAS", "home_score": 100}]}})
    if not check("Check your rotation" in hq.get_child(4).get_child(0).get_child(0).text, "rotation_priority"):
        return
    if not check("110" in hq.get_child(hq.get_child_count()-1).get_child(0).get_child(1).text, "actual_result_rendered"):
        return
    summary.team = {"abbreviation": "LAL", "name": "Lakers"}
    summary.next_game = {}
    summary.season.phase = "offseason"
    hq.configure(summary)
    if not check(hq.intelligence.is_empty() and hq.get_child(1).text == "Build the next chapter", "team_switch_clears_old_intelligence"):
        return
    hq.configure_intelligence({"team": "BOS", "front_office": {}})
    if not check(hq.intelligence.is_empty(), "late_other_team_response_ignored"):
        return
    for frame in range(10):
        await process_frame
    var scroll = main.home_page
    if not check(scroll is ScrollContainer and scroll.get_child(0).size.x <= scroll.size.x + 1, "hq_fits_width"):
        return
    scroll.scroll_vertical = int(scroll.get_v_scroll_bar().max_value)
    await process_frame
    if not check(scroll.get_global_rect().intersects(hq.get_child(hq.get_child_count()-1).get_global_rect()), "last_card_reachable"):
        return
    hq.set_unavailable("offline")
    if not check(hq.summary.is_empty() and hq.intelligence.is_empty() and hq.get_child_count() == 2, "offline_clears_stale_briefing"):
        return
    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({"briefing_and_phase": true, "action_navigation": true, "injury_and_rotation_priority": true, "real_results": true, "save_switch_safety": true, "scroll_layout": true, "offline_state": true}))
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
    with tempfile.TemporaryDirectory(prefix="v3_batch27_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "smoke.gd"
        script.write_text(GDSCRIPT.replace("MARKER_PATH", json.dumps(marker.as_posix())), encoding="utf-8")
        try:
            proc = subprocess.run([str(godot), "--headless", "--path", "godot_client", "--script", str(script)], cwd=ROOT, capture_output=True, text=True, timeout=30)
            combined = proc.stdout + "\n" + proc.stderr
            print(combined[-8000:])
            results["godot_runtime_completed"] = proc.returncode == 0 and marker.exists() and not any(value in combined.lower() for value in ["script error", "parse error", "batch27_fail", "failed to load script"])
            if results["godot_runtime_completed"]:
                results.update(json.loads(marker.read_text(encoding="utf-8")))
        except (subprocess.TimeoutExpired, OSError) as exc:
            results["godot_runtime_completed"] = False
            print(exc)
    results["active_v3_and_protected_v2_unchanged"] = hashes() == before
    out = ROOT / "outputs/v3_batch27_franchise_hq"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(json.dumps({"version": VERSION, "results": results}, indent=2), encoding="utf-8")
    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    passed = all(results.values())
    print("V3 BATCH 27 FRANCHISE HQ VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
