from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v3-batch20l-game-day-v1.0.0-2026-10-03"


def save_hashes() -> dict[str, str]:
    hashes = {name: hashlib.sha256((ROOT / "outputs/runtime" / name).read_bytes()).hexdigest()
            for name in ("v3_godot_working_checkpoint.pkl.gz", "franchise_mode_checkpoint_v1.pkl.gz")}
    preferences = ROOT / "outputs/runtime/v3_desktop_preferences.json"
    hashes["desktop_preferences"] = hashlib.sha256(preferences.read_bytes()).hexdigest() if preferences.exists() else "missing"
    return hashes


def main() -> int:
    before = save_hashes()
    godot = Path(os.environ.get("USERPROFILE", "")) / "Downloads/Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console
    results = {}
    with tempfile.TemporaryDirectory(prefix="v3_settings_smoke_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "game_day.gd"
        script.write_text("""extends SceneTree
func _initialize():
    var page = load("res://scripts/settings_tutorial_v3.gd").new()
    root.add_child(page)
    await process_frame
    page.apply_preferences({"confirm_load": null, "confirm_delete": "false", "confirm_new_franchise": false, "return_home_after_save_switch": true, "tutorial_completed": null})
    assert(page.confirm_load_toggle.button_pressed)
    assert(page.confirm_delete_toggle.button_pressed)
    assert(not page.confirm_new_franchise_toggle.button_pressed)
    assert("NOT COMPLETED" in page.tutorial_status_label.text)
    assert(page.changes_label.text == "SETTINGS MATCH SAVED PREFERENCES")
    page.confirm_load_toggle.button_pressed = false
    assert("UNSAVED CHANGES" in page.changes_label.text)
    page.confirm_load_toggle.button_pressed = true
    assert(page.changes_label.text == "SETTINGS MATCH SAVED PREFERENCES")
    page.return_home_toggle.button_pressed = false
    assert("UNSAVED CHANGES" in page.changes_label.text)
    page.apply_preferences({"return_home_after_save_switch": false})
    assert(page.changes_label.text == "SETTINGS MATCH SAVED PREFERENCES")
    page.apply_team_brand("LAL", Color("fdb927"), Color("552583"))
    assert(page.save_button.get_theme_color("font_color") == Color("0a0d12"))
    var button_count = page.primary_buttons.size()
    page.start_tutorial(false)
    assert(page.tutorial_back_button.disabled)
    assert(is_equal_approx(page.tutorial_progress.value, 100.0 / page.TUTORIAL_STEPS.size()))
    assert(page.tutorial_next_button.get_theme_stylebox("normal").bg_color == Color("fdb927"))
    page._tutorial_next()
    assert(not page.tutorial_back_button.disabled)
    page._tutorial_back()
    assert(page.tutorial_index == 0)
    for i in range(page.TUTORIAL_STEPS.size() - 1):
        page._tutorial_next()
    assert(page.tutorial_progress.value == 100)
    assert(page.tutorial_next_button.text == "FINISH")
    page.apply_team_brand("BOS", Color("007a33"), Color("ffffff"))
    assert(page.tutorial_progress.get_theme_stylebox("fill").bg_color == Color("007a33"))
    page._close_tutorial_overlay()
    await process_frame
    assert(page.primary_buttons.size() == button_count)
    assert(page.tutorial_progress == null)
    page.start_tutorial(false)
    assert(page.tutorial_index == 0)
    assert(page.primary_buttons.size() == button_count + 1)
    page._close_tutorial_overlay()
    assert(page.pending_action == "")
    assert(page.action_request.get_http_client_status() == HTTPClient.STATUS_DISCONNECTED)
    assert(page.summary_request.get_http_client_status() == HTTPClient.STATUS_DISCONNECTED)
    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({"invalid_boolean_preferences_use_safe_defaults": true, "dirty_settings_and_restore": true, "tutorial_progress_and_navigation": true, "repeated_tutorial_cleans_up_buttons": true, "bright_and_dark_team_branding": true, "no_preference_write_requested": true}))
    output.close()
    quit(0)
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
    results["v3_v2_and_desktop_preferences_unchanged"] = save_hashes() == before
    output = ROOT / "outputs/v3_batch20l_settings_presentation"
    output.mkdir(parents=True, exist_ok=True)
    (output / "validation.json").write_text(json.dumps({"version": VERSION, "results": results}, indent=2), encoding="utf-8")
    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    passed = all(results.values())
    print("V3 BATCH 20L VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
