from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v3-batch30-trade-experience-v1.0.0-2026-10-04"


def hashes() -> dict[str, str]:
    return {name: hashlib.sha256((ROOT / "outputs/runtime" / name).read_bytes()).hexdigest()
            for name in ("v3_godot_working_checkpoint.pkl.gz", "franchise_mode_checkpoint_v1.pkl.gz")}


GDSCRIPT = r'''extends SceneTree
func check(condition: bool, label: String) -> bool:
    if not condition:
        print("BATCH30_FAIL::" + label)
        quit(2)
    return condition
func _initialize():
    root.size = Vector2i(1440, 900)
    var page = load("res://scripts/scouting_draft_center_v3.gd").new()
    root.add_child(page)
    page.size = Vector2(1126, 900)
    await process_frame
    var pool: Array = []
    for i in range(80):
        pool.append({"prospect_id": "p%s" % i, "Rank": i+1, "Prospect": "Prospect With Readable Name %02d" % i, "Pos": "SG", "School / Club": "Fixture University", "Archetype": "3-and-D Guard", "Scouted OVR": 74.5, "Scouted POT": 90.0, "Confidence": 37.0, "Report": "Preliminary", "Projected": "Lottery", "Drafted": false, "True OVR": 99})
    var payload = {"team": "BOS", "board": pool, "summary": {"weeks_completed": 0, "weeks_remaining": 4, "focus_ids": []}, "draft": {"draft_year": 2027, "phase": "season_scouting", "current_pick": {}}, "lead_scout": {}, "working_save_unchanged": true, "active_v2_unchanged": true, "scouting_execution_enabled": true, "draft_execution_enabled": false}
    page._on_summary_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(payload).to_utf8_buffer())
    page._select_prospect(pool[0])
    page._pin_comparison()
    if not check(page.pin_button.text == "REPORT PINNED", "pin_feedback"):
        return
    page.latest_draft_fingerprint = "old"
    page.make_pick_button.disabled = false
    page._select_prospect(pool[1])
    if not check(page.prospect_dossier.selected.prospect_id == "p1" and page.prospect_dossier.reference.prospect_id == "p0" and page.prospect_dossier.get_child(1).get_child_count() == 2, "two_dossier_comparison"):
        return
    if not check(page.make_pick_button.disabled and page.latest_draft_fingerprint == "", "selection_invalidates_commit"):
        return
    if not check(page.prospect_dossier.find_child("Confidence_p1", true, false).value == 37, "report_confidence_correct"):
        return
    page.load_more_button.pressed.emit()
    if not check(page.board_rows.get_child_count() == 80 and not page.load_more_button.visible, "full_class_reachable"):
        return
    for frame in range(10):
        await process_frame
    page.board_scroll.scroll_vertical = int(page.board_scroll.get_v_scroll_bar().max_value)
    await process_frame
    if not check(page.board_scroll.get_global_rect().intersects(page.board_rows.get_child(79).get_global_rect()), "last_prospect_reachable"):
        return
    page.search_box.text = "name 79"
    page._on_search_changed(page.search_box.text)
    if not check(page.board_rows.get_child_count() == 1 and page.board_limit == 50, "search_load_limit_reset"):
        return
    var missing = pool[2].duplicate(true)
    missing.Confidence = null
    missing["Scouted OVR"] = null
    page._select_prospect(missing)
    if not check(page.prospect_dossier.find_child("Confidence_p2", true, false) == null, "unknown_confidence_has_no_fake_bar"):
        return
    page.page_payload.draft = {"draft_year": 2027, "phase": "draft_in_progress", "current_pick": {"owner_team": "SAS", "overall_pick": 7}}
    page._update_dossier()
    if not check("SAS ON THE CLOCK" in page.prospect_dossier.stage_text.text, "clock_uses_pick_owner"):
        return
    page.page_payload.draft.phase = "draft_complete"
    page._update_dossier()
    if not check(page.prospect_dossier.stage_text.text == "THE CLASS IS SELECTED", "completed_stage"):
        return
    for frame in range(10):
        await process_frame
    var scroll = page.get_child(0)
    if not check(scroll.get_child(0).size.x <= scroll.size.x+1 and page.board_scroll.size.y >= 480, "wide_board_fits_and_scroll_height"):
        return
    if not check(page.find_child("ScoutingOperationsCard", true, false).size.x >= 450 and page.find_child("DraftNightDeskCard", true, false).size.x >= 450, "actions_use_available_width"):
        return
    page.search_box.text = ""
    page._on_summary_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(payload).to_utf8_buffer())
    if not check(page.selected_prospect.is_empty() and page.comparison_prospect.is_empty() and page.pin_button.disabled, "refresh_clears_stale_reports"):
        return
    if not check(page.draft_execute_request.get_http_client_status() == HTTPClient.STATUS_DISCONNECTED and page.scout_execute_request.get_http_client_status() == HTTPClient.STATUS_DISCONNECTED, "no_write_requests"):
        return
    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({"comparison_dossiers": true, "confidence_and_missing_data": true, "phase_stage": true, "full_class_and_search": true, "selection_safety": true, "refresh_safety": true, "layout_bounds": true, "no_write_requests": true}))
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
    with tempfile.TemporaryDirectory(prefix="v3_batch30_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "smoke.gd"
        script.write_text(GDSCRIPT.replace("MARKER_PATH", json.dumps(marker.as_posix())), encoding="utf-8")
        try:
            proc = subprocess.run([str(godot), "--headless", "--path", "godot_client", "--script", str(script)], cwd=ROOT, capture_output=True, text=True, timeout=30)
            combined = proc.stdout + "\n" + proc.stderr
            print(combined[-8000:])
            results["godot_runtime_completed"] = proc.returncode == 0 and marker.exists() and not any(value in combined.lower() for value in ["script error", "parse error", "batch30_fail", "failed to load script"])
            if results["godot_runtime_completed"]:
                results.update(json.loads(marker.read_text(encoding="utf-8")))
        except (subprocess.TimeoutExpired, OSError) as exc:
            results["godot_runtime_completed"] = False
            print(exc)
    results["active_v3_and_protected_v2_unchanged"] = hashes() == before
    out = ROOT / "outputs/v3_batch30_scouting_dossiers"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(json.dumps({"version": VERSION, "results": results}, indent=2), encoding="utf-8")
    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    passed = all(results.values())
    print("V3 BATCH 30 SCOUTING DOSSIERS VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
