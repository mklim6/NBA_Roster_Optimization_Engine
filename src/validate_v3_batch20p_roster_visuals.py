from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v3-batch20p-roster-v1.0.0-2026-10-03"


def save_hashes() -> dict[str, str]:
    return {name: hashlib.sha256((ROOT / "outputs/runtime" / name).read_bytes()).hexdigest()
            for name in ("v3_godot_working_checkpoint.pkl.gz", "franchise_mode_checkpoint_v1.pkl.gz")}


def main() -> int:
    before = save_hashes()
    godot = Path(os.environ.get("USERPROFILE", "")) / "Downloads/Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console
    results = {}
    with tempfile.TemporaryDirectory(prefix="v3_home_hero_smoke_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "game_day.gd"
        script.write_text("""extends SceneTree
func _initialize():
    var page = load("res://scripts/main.gd").new()
    root.add_child(page)
    await process_frame
    for team in ["BOS", "LAL", "SAS"]:
        page._apply_active_team_brand(team)
        assert(page.roster_brand_accents[0].color == page.active_team_primary)
        var row = page._roster_row({"name": "Very Long Player Name For Layout Verification", "is_starter": true, "overall": 91, "morale": null, "health": null, "contract": null, "season_stats": null})
        root.add_child(row)
        await process_frame
        assert(row.get_combined_minimum_size().x <= 980)
        var resting = row.get_theme_stylebox("panel")
        assert(resting.border_width_left == 3)
        assert(resting.border_color == page.active_team_primary.lightened(0.18))
        row.mouse_entered.emit()
        assert(row.get_theme_stylebox("panel").bg_color == page.PANEL_ALT.lerp(page.active_team_primary, 0.16))
        row.mouse_exited.emit()
        assert(row.get_theme_stylebox("panel") == resting)
        assert(row.get_signal_connection_list("gui_input").size() == 1)
        var labels = labels_in(row)
        assert("Unknown" in labels)
        assert("N/A" in labels)
        assert(not "<null>" in labels)
        row.queue_free()
        await process_frame
    var reserve = page._roster_row({"name": "Reserve Fixture", "overall": 0, "target_minutes": 0, "season_stats": {"ppg": 0}, "health": {"display": "Healthy", "status": "healthy"}})
    root.add_child(reserve)
    await process_frame
    assert(reserve.get_theme_stylebox("panel").border_width_left == 1)
    var zero_labels = labels_in(reserve)
    assert("0" in zero_labels)
    assert("0.0" in zero_labels)
    page._apply_roster_payload({"team": {"abbreviation": "BOS"}, "players": []})
    assert(page.active_team_abbreviation == "BOS")
    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({"normal_window_row_width": true, "brand_and_hover_restore": true, "null_sections_and_zero_stats": true, "profile_input_connection_preserved": true, "roster_payload_drives_brand": true}))
    output.close()
    quit(0)
func labels_in(node) -> Array:
    var labels: Array = []
    if node is Label:
        labels.append(node.text)
    for child in node.get_children():
        labels.append_array(labels_in(child))
    return labels
""".replace("MARKER_PATH", json.dumps(marker.as_posix())), encoding="utf-8")
        try:
            proc = subprocess.run([str(godot), "--headless", "--path", "godot_client", "--script", str(script)],
                                  cwd=ROOT, capture_output=True, text=True, timeout=30)
            combined = proc.stdout + "\n" + proc.stderr
            bad = ("script error", "parse error", "assertion failed", "failed to load script")
            results["godot_runtime_completed"] = proc.returncode == 0 and marker.exists() and not any(m in combined.lower() for m in bad)
            if results["godot_runtime_completed"]:
                results.update(json.loads(marker.read_text(encoding="utf-8")))
            else:
                print(combined[-7000:])
        except (subprocess.TimeoutExpired, OSError) as exc:
            results["godot_runtime_completed"] = False
            print(exc)
    results["active_v3_and_protected_v2_unchanged"] = save_hashes() == before
    output = ROOT / "outputs/v3_batch20p_home_hero"
    output.mkdir(parents=True, exist_ok=True)
    (output / "validation.json").write_text(json.dumps({"version": VERSION, "results": results}, indent=2), encoding="utf-8")
    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    passed = all(results.values())
    print("V3 BATCH 20P VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
