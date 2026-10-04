from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v3-batch20i-game-day-v1.0.0-2026-10-03"


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
    with tempfile.TemporaryDirectory(prefix="v3_trade_smoke_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "game_day.gd"
        script.write_text("""extends SceneTree
func _initialize():
    var page = load("res://scripts/trade_center_v3.gd").new()
    root.add_child(page)
    await process_frame
    page.active_team = "BOS"
    page.partner_selector.add_item("SAS")
    page.partner_selector.add_item("LAL")
    page.foundation_payload = {"trade_assets": {"players": [{"player_id": "a", "name": "Outgoing Player", "overall": null}]}, "draft_assets": {"owned": [{"asset_id": "pick", "display_name": "2028 BOS first"}]}}
    page.partner_payload = {"team": "SAS", "players": [{"player_id": "b", "name": "Incoming Player"}], "picks": []}
    page._render_active_assets()
    page._render_partner_assets()
    page._on_asset_toggled(true, "active_player", "a")
    page._on_asset_toggled(true, "active_pick", "pick")
    page._on_asset_toggled(true, "partner_player", "b")
    assert("Outgoing Player" in page.outgoing_assets_label.text)
    assert("2028 BOS first" in page.outgoing_assets_label.text)
    assert("Incoming Player" in page.incoming_assets_label.text)
    assert(not page.preview_button.disabled)
    assert(page.execute_button.disabled)
    assert(page.package_state.text == "PACKAGE NEEDS PREVIEW")
    var preview = {"working_save_unchanged": true, "active_v2_unchanged": true, "working_save_sha256": "fixture-sha", "preview": {"status": "pass", "can_commit": true, "package_fingerprint": "fixture-token", "side_a": null, "side_b": null, "checks": null}}
    page.pending_preview_request_payload = page._current_trade_request_payload().duplicate(true)
    page._on_preview_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(preview).to_utf8_buffer())
    assert(not page.execute_button.disabled)
    assert(page.package_state.text == "READY TO CONFIRM")
    page._on_asset_toggled(false, "active_pick", "pick")
    assert(page.execute_button.disabled)
    assert(page.latest_preview_fingerprint == "")
    page._on_preview_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(preview).to_utf8_buffer())
    assert(page.execute_button.disabled)
    assert("while preview was running" in page.preview_label.text)
    page.pending_preview_request_payload = page._current_trade_request_payload().duplicate(true)
    page.partner_selector.select(1)
    page._on_preview_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(preview).to_utf8_buffer())
    assert(page.execute_button.disabled)
    page.partner_selector.select(0)
    page.pending_preview_request_payload = page._current_trade_request_payload().duplicate(true)
    preview.preview.status = "blocked"
    page._on_preview_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(preview).to_utf8_buffer())
    assert(page.execute_button.disabled)
    assert(page.package_state.text == "PREVIEW REJECTED")
    page.pending_preview_request_payload = page._current_trade_request_payload().duplicate(true)
    preview.preview.status = "pass"
    preview.preview.package_fingerprint = null
    page._on_preview_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(preview).to_utf8_buffer())
    assert(page.execute_button.disabled)
    page.pending_preview_request_payload = page._current_trade_request_payload().duplicate(true)
    preview.active_v2_unchanged = false
    page._on_preview_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(preview).to_utf8_buffer())
    assert(page.execute_button.disabled)
    assert("SAFETY FAILURE" in page.preview_label.text)
    page.latest_preview_fingerprint = "old"
    page.latest_preview_working_sha = "old"
    page.execute_button.disabled = false
    page._on_foundation_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify({"working_save_unchanged": false}).to_utf8_buffer())
    assert(page.execute_button.disabled)
    assert(page.preview_button.disabled)
    assert(page.latest_preview_fingerprint == "")
    page._on_partner_assets_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify({"active_v2_unchanged": false}).to_utf8_buffer())
    assert(page.execute_button.disabled)
    assert(page.preview_button.disabled)
    page._clear_package()
    assert(page.preview_button.disabled)
    assert(page.outgoing_assets_label.text == "SEND • None selected")
    assert(page.incoming_assets_label.text == "GET • None selected")
    page.foundation_payload = {"trade_assets": null, "draft_assets": null}
    page.partner_payload = {"players": null, "picks": null}
    page._render_active_assets()
    page._render_partner_assets()
    assert(page._selected_asset_names({"missing": true}, {}, [], []) == "missing")
    assert(page._money_text("bad") == "N/A")
    page.apply_team_brand("LAL", Color("fdb927"), Color("552583"))
    assert(page.preview_button.get_theme_color("font_color") == Color("0a0d12"))
    page.execute_in_flight = true
    page._update_package_state()
    assert(page.package_state.text == "TRADE IN PROGRESS")
    assert(page.execute_request.get_http_client_status() == HTTPClient.STATUS_DISCONNECTED)
    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({"named_package_assets": true, "asset_and_partner_changes_invalidate_preview": true, "late_preview_rejected": true, "rejections_and_missing_tokens_safe": true, "null_assets_and_clear_package": true, "team_brand_and_trade_state": true, "no_execution_request_sent": true}))
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
    output = ROOT / "outputs/v3_batch20i_trade_presentation"
    output.mkdir(parents=True, exist_ok=True)
    (output / "validation.json").write_text(json.dumps({"version": VERSION, "results": results}, indent=2), encoding="utf-8")
    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    passed = all(results.values())
    print("V3 BATCH 20I VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
