from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v3-batch20f-game-day-v1.0.0-2026-10-03"


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
    with tempfile.TemporaryDirectory(prefix="v3_season_smoke_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "game_day.gd"
        script.write_text("""extends SceneTree
func _initialize():
    var page = load("res://scripts/season_lifecycle_center_v3.gd").new()
    root.add_child(page)
    await process_frame
    page.summary_payload = {"season": {"label": "2026-27", "phase": "regular_season"}, "schedule": {"total": 100, "completed": 25}, "next_action": "", "next_action_label": "CONTINUE REGULAR SEASON"}
    page._render_summary()
    assert(page.season_value.text == "2026-27")
    assert(page.season_progress.visible)
    assert(page.season_progress.value == 25)
    assert("75 remaining" in page.season_progress_label.text)
    assert(page.preview_button.disabled)
    assert(page.execute_button.disabled)
    page.latest_action_fingerprint = "stale"
    page.latest_working_sha = "stale"
    page.summary_payload.schedule.completed = 150
    page._render_summary()
    assert(page.season_progress.value == 100)
    assert("0 remaining" in page.season_progress_label.text)
    assert(page.latest_action_fingerprint == "")
    assert(page.latest_working_sha == "")
    page.summary_payload = {"season": null, "schedule": null, "postseason": null, "draft": null, "cpu_free_agency": null, "blockers": null, "timeline": null, "engine_versions": null, "next_action_label": null}
    page._render_summary()
    assert(page.season_value.text == "N/A")
    assert(page.progress_value.text == "N/A")
    assert(not page.season_progress.visible)
    assert(page.season_progress.value == 0)
    assert(page.gate_value.text == "NO ACTION AVAILABLE")
    assert(page.preview_button.disabled)
    assert(page.execute_button.disabled)
    page.summary_payload = {"season": {"phase": "offseason"}, "postseason": {"stage": "complete"}, "next_action": "draft_lottery", "next_action_label": "DRAFT LOTTERY"}
    page._render_summary()
    assert(page.progress_value.text == "POSTSEASON COMPLETE")
    assert(not page.preview_button.disabled)
    assert(page.execute_button.disabled)
    assert(page.execute_request.get_http_client_status() == HTTPClient.STATUS_DISCONNECTED)
    page.apply_team_brand("LAL", Color("fdb927"), Color("552583"))
    assert(page.season_progress.get_theme_stylebox("fill").bg_color == Color("fdb927"))
    assert(page.execute_button.get_theme_stylebox("normal").bg_color == Color("fdb927"))
    assert(page.execute_button.get_theme_color("font_color") == Color("0a0d12"))
    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({"schedule_progress_and_clamping": true, "null_summary_safe": true, "postseason_gate_display": true, "preview_invalidation_and_no_execution": true, "active_team_branding": true}))
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
    results["active_v3_and_protected_v2_unchanged"] = save_hashes() == before
    output = ROOT / "outputs/v3_batch20f_season_presentation"
    output.mkdir(parents=True, exist_ok=True)
    (output / "validation.json").write_text(json.dumps({"version": VERSION, "results": results}, indent=2), encoding="utf-8")
    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    passed = all(results.values())
    print("V3 BATCH 20F VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
