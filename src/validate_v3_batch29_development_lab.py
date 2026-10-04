from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v3-batch29-trade-experience-v1.0.0-2026-10-04"


def hashes() -> dict[str, str]:
    return {name: hashlib.sha256((ROOT / "outputs/runtime" / name).read_bytes()).hexdigest()
            for name in ("v3_godot_working_checkpoint.pkl.gz", "franchise_mode_checkpoint_v1.pkl.gz")}


GDSCRIPT = r'''extends SceneTree
func check(condition: bool, label: String) -> bool:
    if not condition:
        print("BATCH29_FAIL::" + label)
        quit(2)
    return condition
func _initialize():
    root.size = Vector2i(1440, 900)
    var page = load("res://scripts/front_office_center_v3.gd").new()
    root.add_child(page)
    page.size = Vector2(1126, 900)
    await process_frame
    var lab = page.development_lab
    var players = [{"player_id": "a", "name": "Alpha", "age": 28, "overall": 80, "potential": 85, "future_outlook": 84, "direction": "Stable", "history_entries": 0}, {"player_id": "b", "name": "Beta", "age": 22, "overall": 70, "potential": 90, "future_outlook": 88, "direction": "Rising"}, {"player_id": "c", "name": "Unknown", "age": null, "overall": null, "potential": null, "future_outlook": null, "direction": "Unknown"}]
    lab.configure({"full_roster": players})
    if not check(lab.visible_ids == ["b", "a", "c"] and lab.selected_id == "b", "future_sort_known_before_unknown"):
        return
    if not check(lab.find_child("DevelopmentPortrait_b", true, false).custom_minimum_size.y >= 110, "readable_portraits"):
        return
    lab.find_child("DevelopmentSelect_a", true, false).pressed.emit()
    if not check(lab.selected_id == "a" and "Alpha" in lab.selected_detail.get_child(0).get_child(0).get_child(0).text, "selection_updates_detail"):
        return
    lab.sort_selector.select(1)
    lab.sort_selector.item_selected.emit(1)
    if not check(lab.visible_ids == ["b", "a", "c"], "potential_gap_sort"):
        return
    lab.sort_selector.select(2)
    lab.sort_selector.item_selected.emit(2)
    if not check(lab.visible_ids == ["b", "a", "c"], "age_sort"):
        return
    lab.direction_selector.select(1)
    lab.direction_selector.item_selected.emit(1)
    if not check(lab.visible_ids == ["b"] and lab.selected_id == "b", "filter_resets_hidden_selection"):
        return
    lab.direction_selector.select(3)
    lab.direction_selector.item_selected.emit(3)
    if not check(lab.visible_ids.is_empty() and lab.selected_id == "", "empty_filter"):
        return
    lab.direction_selector.select(0)
    lab.configure({"full_roster": [players[2]]})
    var detail = lab.selected_detail.get_child(0).get_child(0)
    if not check(detail.get_child_count() == 6, "missing_ratings_do_not_draw_fake_bars"):
        return
    lab.configure({"full_roster": players})
    for frame in range(10):
        await process_frame
    if not check(lab.size.x <= page.size.x and lab.cards.get_child_count() == 3, "grid_fits_page"):
        return
    if not check(lab.count_label.size.x >= 180 and lab.sort_selector.size.y <= 50, "filter_row_does_not_collapse"):
        return
    lab.clear_report()
    if not check(lab.rows.is_empty() and lab.visible_ids.is_empty() and lab.selected_id == "", "refresh_clears_old_team"):
        return
    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({"portrait_cards": true, "sorting_and_filtering": true, "selection_and_empty_states": true, "unknown_values_preserved": true, "refresh_safety": true, "grid_layout": true}))
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
    with tempfile.TemporaryDirectory(prefix="v3_batch29_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "smoke.gd"
        script.write_text(GDSCRIPT.replace("MARKER_PATH", json.dumps(marker.as_posix())), encoding="utf-8")
        try:
            proc = subprocess.run([str(godot), "--headless", "--path", "godot_client", "--script", str(script)], cwd=ROOT, capture_output=True, text=True, timeout=30)
            combined = proc.stdout + "\n" + proc.stderr
            print(combined[-8000:])
            results["godot_runtime_completed"] = proc.returncode == 0 and marker.exists() and not any(value in combined.lower() for value in ["script error", "parse error", "batch29_fail", "failed to load script"])
            if results["godot_runtime_completed"]:
                results.update(json.loads(marker.read_text(encoding="utf-8")))
        except (subprocess.TimeoutExpired, OSError) as exc:
            results["godot_runtime_completed"] = False
            print(exc)
    results["active_v3_and_protected_v2_unchanged"] = hashes() == before
    out = ROOT / "outputs/v3_batch29_development_lab"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(json.dumps({"version": VERSION, "results": results}, indent=2), encoding="utf-8")
    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    passed = all(results.values())
    print("V3 BATCH 29 DEVELOPMENT LAB VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
