from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v3-batch20k-game-day-v1.0.0-2026-10-03"


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
    with tempfile.TemporaryDirectory(prefix="v3_scouting_smoke_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "game_day.gd"
        script.write_text("""extends SceneTree
func _initialize():
    var page = load("res://scripts/scouting_draft_center_v3.gd").new()
    root.add_child(page)
    await process_frame
    var pool: Array = []
    for i in range(55):
        pool.append({"prospect_id": str(i), "Prospect": "Fixture %02d" % i, "Pos": "PG", "School / Club": "Fixture School", "Archetype": "Playmaker", "Confidence": null, "Scouted OVR": null, "Scouted POT": null})
    var payload = {"board": pool, "summary": {"weeks_completed": 0, "weeks_remaining": 4, "average_confidence": 0, "focus_ids": []}, "draft": {"phase": "scouting", "current_pick": null}, "lead_scout": {"name": "Fixture Scout"}, "working_save_unchanged": true, "active_v2_unchanged": true, "scouting_execution_enabled": true, "draft_execution_enabled": false}
    page._on_summary_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(payload).to_utf8_buffer())
    assert(page.board_count.text == "Showing 50 of 55 matches")
    assert(page.board_rows.get_child_count() == 50)
    assert(page.confidence_value.text == "0%")
    assert(page.scouting_week_value.text == "0 / 4")
    page.search_box.text = "fixture 00"
    page._render_board()
    assert(page.board_count.text == "Showing 1 of 1 matches")
    page.search_box.text = "no such prospect"
    page._render_board()
    assert(page.board_count.text == "Showing 0 of 0 matches")
    page.search_box.text = ""
    page.latest_draft_fingerprint = "old"
    page.make_pick_button.disabled = false
    page._select_prospect(pool[0])
    assert(page.latest_draft_fingerprint == "")
    assert(page.make_pick_button.disabled)
    assert("N/A confidence" in page.selected_prospect_label.text)
    assert(not "<null>" in page.selected_prospect_label.text)
    assert(page.board_rows.get_child(0).get_theme_stylebox("panel").border_color == page.brand_color)
    page._select_prospect(pool[1])
    assert(page.board_rows.get_child(0).get_theme_stylebox("panel").border_color == page.BORDER)
    for i in range(7):
        page._on_focus_toggled(true, str(i))
    assert(page.focus_selected.size() == 6)
    assert(page.advance_week_button.disabled)
    page._on_focus_toggled(false, "0")
    assert(page.focus_selected.size() == 5)
    payload.board = []
    page._on_summary_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(payload).to_utf8_buffer())
    assert(page.board_count.text == "Showing 0 of 0 prospects")
    assert("No prospects are available" in page.board_rows.get_child(0).text)
    payload.board = null
    payload.summary = null
    payload.draft = null
    payload.lead_scout = null
    payload.scouting_execution_enabled = false
    page._on_summary_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(payload).to_utf8_buffer())
    assert(page.board_count.text == "Board data unavailable")
    assert(page.confidence_value.text == "N/A")
    assert(page.scouting_week_value.text == "N/A")
    assert(page.scout_value.text == "N/A")
    assert(page.preview_week_button.disabled)
    assert(page.preview_pick_button.disabled)
    page.apply_team_brand("LAL", Color("fdb927"), Color("552583"))
    assert(page.advance_week_button.get_theme_color("font_color") == Color("0a0d12"))
    assert(page._confidence_text(0) == "0%")
    assert(page._confidence_text(null) == "N/A")
    assert(page._rating_text(null) == "--")
    assert(page.scout_execute_request.get_http_client_status() == HTTPClient.STATUS_DISCONNECTED)
    assert(page.draft_execute_request.get_http_client_status() == HTTPClient.STATUS_DISCONNECTED)
    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({"board_limit_and_search_counts": true, "null_confidence_and_summary_safe": true, "selection_highlight_and_token_invalidation": true, "six_prospect_focus_limit": true, "phase_gates_and_team_brand": true, "no_scout_or_draft_execution_requested": true}))
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
    output = ROOT / "outputs/v3_batch20k_scouting_presentation"
    output.mkdir(parents=True, exist_ok=True)
    (output / "validation.json").write_text(json.dumps({"version": VERSION, "results": results}, indent=2), encoding="utf-8")
    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    passed = all(results.values())
    print("V3 BATCH 20K VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
