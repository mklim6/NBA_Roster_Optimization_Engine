from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAVE_MANAGER = ROOT / "godot_client/scripts/save_manager_v3.gd"
V3 = ROOT / "outputs/runtime/v3_godot_working_checkpoint.pkl.gz"
V2 = ROOT / "outputs/runtime/franchise_mode_checkpoint_v1.pkl.gz"
VERSION = "v3-batch20m-save-manager-v1.0.0-2026-10-03"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"


def save_hashes() -> dict[str, str]:
    return {"v3": sha256(V3), "v2": sha256(V2)}


def main() -> int:
    before = save_hashes()
    results: dict[str, bool] = {}
    text = SAVE_MANAGER.read_text(encoding="utf-8") if SAVE_MANAGER.exists() else ""

    results["shared_design_system_and_team_branding"] = (
        'preload("res://scripts/design_system_v3.gd")' in text
        and 'preload("res://scripts/team_branding_v3.gd")' in text
        and "func apply_team_brand" in text
    )
    results["stale_confirmation_target_captured_and_revalidated"] = (
        "pending_confirm_slot_id = selected_slot_id" in text
        and "var confirmed_slot_id := pending_confirm_slot_id" in text
        and "_slot_by_id(confirmed_slot_id)" in text
        and '{"slot_id": confirmed_slot_id}' in text
    )
    results["confirmation_cancel_clears_pending_intent"] = (
        "func _on_confirm_cancelled()" in text
        and "confirm_dialog.canceled.connect(_on_confirm_cancelled)" in text
    )

    godot = Path(os.environ.get("USERPROFILE", "")) / "Downloads/Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console

    with tempfile.TemporaryDirectory(prefix="v3_save_manager_smoke_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "save_manager.gd"
        test_page = Path(scratch) / "recording_save_manager.gd"
        test_page.write_text('extends "res://scripts/save_manager_v3.gd"\nvar recorded_actions: Array = []\nfunc _post_action(action: String, url: String, body: Dictionary) -> void:\n\trecorded_actions.append({"action": action, "url": url, "body": body.duplicate(true)})\n', encoding="utf-8")
        script.write_text(
            """extends SceneTree
func _initialize():
    var page = load(TEST_PAGE_PATH).new()
    root.add_child(page)
    await process_frame

    assert(page._safe_display(null) == "--")
    assert(page._safe_display("<null>") == "--")
    assert(page._safe_display("  BOS  ") == "BOS")

    page.apply_team_brand("LAL", Color("fdb927"), Color("552583"))
    assert(page.brand_color == Color("fdb927"))
    assert(page.bootstrap_button.get_theme_color("font_color") == Color("0a0d12"))

    page.payload = {
        "initialized": true,
        "active_slot_id": "slot1",
        "slot_count": 2,
        "bootstrap_available": false,
        "working_save_unchanged": true,
        "active_v2_unchanged": true,
        "live_session_ahead_of_snapshot": false,
        "new_franchise_teams": [
            {"team": "LAL", "team_name": "Los Angeles Lakers"},
            {"team": "BOS", "team_name": "Boston Celtics"}
        ],
        "slots": [
            {"slot_id": "slot1", "name": "Lakers Main", "team": "LAL", "team_name": "Los Angeles Lakers", "season": "2026-27", "record": "12-5", "phase": "regular_season", "day_index": 38, "active": true, "healthy": true},
            {"slot_id": "slot2", "name": "Celtics Test", "team": "BOS", "team_name": "Boston Celtics", "season": null, "record": null, "phase": null, "day_index": null, "active": false, "healthy": true}
        ]
    }
    page._render_summary()
    await process_frame

    assert(page.active_slot_value.text == "Lakers Main")
    assert(page.franchise_value.text == "LAL")
    assert(page.season_value.text == "2026-27")
    assert(page.slots_box.get_child_count() == 2)
    assert(page.slots_box.get_child(0).name == "SaveSlot_slot1")
    assert(page.slots_box.get_child(0).get_theme_stylebox("panel").border_color == Color(Color("fdb927"), 0.78))

    page._select_slot("slot2")
    await process_frame
    assert(page.selected_slot_id == "slot2")
    assert(page.pending_action == "")
    assert(page.action_request.get_http_client_status() == HTTPClient.STATUS_DISCONNECTED)
    assert("<null>" not in page.selected_detail.text)
    assert("STORED FRANCHISE SNAPSHOT" in page.selected_detail.text)

    page.pending_confirm_action = "delete"
    page.pending_confirm_slot_id = "slot2"
    page.pending_new_franchise_body = {"team": "BOS", "name": "Temp"}
    page._on_confirm_cancelled()
    assert(page.pending_confirm_action == "")
    assert(page.pending_confirm_slot_id == "")
    assert(page.pending_new_franchise_body.is_empty())

    page.pending_confirm_action = "load"
    page.pending_confirm_slot_id = "slot2"
    page.selected_slot_id = "slot1"
    page._on_confirmed()
    assert(page.recorded_actions.size() == 1)
    assert(page.recorded_actions[0].body.slot_id == "slot2")
    assert(page.pending_confirm_action == "")
    page.pending_confirm_action = "delete"
    page.pending_confirm_slot_id = "slot2"
    page.payload.slots[1].active = true
    page._on_confirmed()
    assert(page.recorded_actions.size() == 1)
    assert("DELETE BLOCKED" in page.status_label.text)
    page.payload.slots[1].active = false
    page.payload.slots[1].healthy = false
    page.pending_confirm_action = "load"
    page.pending_confirm_slot_id = "slot2"
    page._on_confirmed()
    assert(page.recorded_actions.size() == 1)
    assert("LOAD BLOCKED" in page.status_label.text)
    page.desktop_preferences.confirm_delete = null
    assert(page._confirmation_preference("confirm_delete"))
    page.desktop_preferences.confirm_delete = false
    assert(not page._confirmation_preference("confirm_delete"))
    page._on_confirm_cancelled()

    page.selected_slot_id = "slot2"
    page.payload.slots = [page.payload.slots[0]]
    page._render_summary()
    await process_frame
    assert(page.selected_slot_id == "slot1")

    var row_text := [""]
    collect_text(page.slots_box.get_child(0), row_text)
    assert("ACTIVE" in row_text[0])
    assert("VERIFIED" in row_text[0])

    assert(page.delete_button.disabled)
    assert(page.action_request.get_http_client_status() == HTTPClient.STATUS_DISCONNECTED)
    assert(page.summary_request.get_http_client_status() == HTTPClient.STATUS_DISCONNECTED)

    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({
        "active_save_visually_identifiable": true,
        "missing_metadata_truthful": true,
        "selection_and_render_are_read_only": true,
        "cancel_clears_confirmation_state": true,
        "confirmed_target_and_changed_slot_checks": true,
        "stale_selection_invalidated_on_refresh": true,
        "active_save_delete_protected": true,
        "bright_team_branding_readable": true
    }))
    output.close()
    quit(0)

func collect_text(node: Node, result: Array) -> void:
    if node is Label:
        result[0] += node.text + " "
    if node is Button:
        result[0] += node.text + " "
    for child in node.get_children():
        collect_text(child, result)
""".replace("MARKER_PATH", json.dumps(marker.as_posix())).replace("TEST_PAGE_PATH", json.dumps(test_page.as_posix())),
            encoding="utf-8",
        )

        try:
            proc = subprocess.run(
                [str(godot), "--headless", "--path", "godot_client", "--script", str(script)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
            bad = ("script error", "parse error", "assertion failed", "failed to load script")
            results["godot_runtime_completed"] = (
                proc.returncode == 0 and marker.exists() and not any(token in combined.lower() for token in bad)
            )
            if results["godot_runtime_completed"]:
                results.update(json.loads(marker.read_text(encoding="utf-8")))
            else:
                print(combined[-7000:])
        except (subprocess.TimeoutExpired, OSError) as exc:
            results["godot_runtime_completed"] = False
            print(exc)

    results["active_v3_and_protected_v2_unchanged"] = save_hashes() == before

    output = ROOT / "outputs/v3_batch20m_save_manager_presentation"
    output.mkdir(parents=True, exist_ok=True)
    (output / "validation.json").write_text(
        json.dumps({"version": VERSION, "results": results}, indent=2),
        encoding="utf-8",
    )

    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    passed = all(results.values())
    print("V3 BATCH 20M VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
