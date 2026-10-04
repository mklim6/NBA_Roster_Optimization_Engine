from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v3-batch26-trade-experience-v1.0.0-2026-10-04"


def hashes() -> dict[str, str]:
    return {name: hashlib.sha256((ROOT / "outputs/runtime" / name).read_bytes()).hexdigest()
            for name in ("v3_godot_working_checkpoint.pkl.gz", "franchise_mode_checkpoint_v1.pkl.gz")}


GDSCRIPT = r'''extends SceneTree
func check(condition: bool, label: String) -> bool:
    if not condition:
        print("BATCH26_FAIL::" + label)
        quit(2)
    return condition

func _initialize():
    print("BATCH26_STAGE::construct")
    root.size = Vector2i(1440, 900)
    var page = load("res://scripts/trade_center_v3.gd").new()
    root.add_child(page)
    page.size = Vector2(1126, 900)
    await process_frame
    page.active_team = "BOS"
    page.partner_selector.add_item("SAS")
    page.partner_selector.add_item("LAL")
    var players: Array = []
    for i in range(15):
        players.append({"player_id": "a%s" % i, "name": "Outgoing Player %s" % i, "position": "SG/SF", "overall": 80.0, "age": 25, "salary": 10000000})
    var picks: Array = []
    for i in range(12):
        picks.append({"asset_id": "pick%s" % i, "display_name": "%s BOS first" % (2028 + i), "engine_ready": true})
    page.foundation_payload = {"trade_assets": {"players": players}, "draft_assets": {"owned": picks}}
    page.partner_payload = {"team": "SAS", "players": [{"player_id": "b", "name": "Incoming Player", "position": "C", "overall": 90.0, "salary": 15000000}], "picks": []}
    page._render_active_assets()
    page._render_partner_assets()
    page._update_package_summary()
    var active_card = page.active_assets_rows.find_child("TradePlayer_a0", true, false)
    var incoming_card = page.partner_assets_rows.find_child("TradePlayer_b", true, false)
    if not check(active_card is CheckBox and active_card.custom_minimum_size.y >= 100, "selectable_portrait_asset_card"):
        return
    active_card.button_pressed = true
    incoming_card.button_pressed = true
    var pick = page.active_assets_rows.find_child("TradePick_pick0", true, false)
    pick.button_pressed = true
    if not check(page.selected_active_players.has("a0") and page.selected_partner_players.has("b") and page.selected_active_picks.has("pick0"), "native_toggles_update_exact_asset_ids"):
        return
    var outgoing_portrait = page.package_stage.find_child("OutgoingPackagePortrait_a0", true, false)
    var incoming_portrait = page.package_stage.find_child("IncomingPackagePortrait_b", true, false)
    if not check(outgoing_portrait != null and incoming_portrait != null and outgoing_portrait.custom_minimum_size.x >= 128, "package_portraits"):
        return
    if not check(page.package_stage.find_child("OutgoingTeamLogo", true, false).team == "BOS" and page.package_stage.find_child("IncomingTeamLogo", true, false).team == "SAS", "two_team_logos"):
        return
    if not check("2028 BOS first" in page.package_stage.find_child("OutgoingPackagePicks", true, false).text, "selected_draft_rights_in_stage"):
        return
    if not check("+$5.0M" in page.package_stage.salary_difference.text, "salary_delta_known"):
        return
    var original_request = page._current_trade_request_payload().duplicate(true)
    if not check(original_request.side_a_player_ids == ["a0"] and original_request.side_b_player_ids == ["b"] and original_request.side_a_pick_asset_ids == ["pick0"], "request_contract_preserved"):
        return

    print("BATCH26_STAGE::preview_gate")
    var preview = {"working_save_unchanged": true, "active_v2_unchanged": true, "working_save_sha256": "fixture-sha", "preview": {"status": "pass", "can_commit": true, "package_fingerprint": "fixture-token", "side_a": null, "side_b": null, "checks": null}}
    page.pending_preview_request_payload = page._current_trade_request_payload().duplicate(true)
    page._on_preview_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(preview).to_utf8_buffer())
    if not check(not page.execute_button.disabled and page.package_stage.preview_state.text == "READY TO CONFIRM", "valid_preview_enables_confirmation"):
        return
    active_card.button_pressed = false
    if not check(page.execute_button.disabled and page.latest_preview_fingerprint == "" and page.package_stage.preview_state.text == "PACKAGE NEEDS PREVIEW" and page.package_stage.find_child("OutgoingPackagePortrait_a0", true, false) == null, "changed_card_invalidates_execution_and_stage"):
        return
    page._on_preview_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(preview).to_utf8_buffer())
    if not check(page.execute_button.disabled and "while preview was running" in page.preview_label.text, "late_preview_rejected"):
        return

    print("BATCH26_STAGE::proposal_and_unknown_salary")
    var proposal = {"partner_team": "SAS", "response_label": "Interested", "deal_type": "player_swap", "incoming": ["Incoming Player"], "outgoing": ["Outgoing Player 0"], "side_a_player_ids": ["a0"], "side_b_player_ids": ["b"], "side_a_pick_asset_ids": [], "side_b_pick_asset_ids": []}
    page.proposals = [proposal]
    page._render_proposals()
    page.proposal_rows.get_child(0).pressed.emit()
    if not check(page.selected_active_players.has("a0") and page.selected_partner_players.has("b") and "+$5.0M" in page.package_stage.salary_difference.text, "proposal_load_updates_stage"):
        return
    page.partner_payload.players[0].salary = null
    page._update_package_summary()
    if not check("Unavailable" in page.package_stage.salary_difference.text and "Unavailable" in page.package_stage.find_child("IncomingSalaryTotal", true, false).text, "unknown_salary_never_becomes_zero"):
        return
    for id in ["a1", "a2", "a3"]:
        page._on_asset_toggled(true, "active_player", id)
    for id in ["pick0", "pick1", "pick2"]:
        page._on_asset_toggled(true, "active_pick", id)
    var visible_players = page.package_stage.find_child("OutgoingSelectedPlayers", true, false)
    if not check(visible_players.get_child_count() == 3 and page._current_trade_request_payload().side_a_player_ids.size() == 4, "large_package_display_preserves_all_ids"):
        return

    print("BATCH26_STAGE::layout_and_scroll")
    for frame in range(10):
        await process_frame
    var outer_scroll = page.find_child("TradeCenterPageScroll", true, false)
    var asset_scroll = page.find_child("OutgoingAssetsScroll", true, false)
    if not check(outer_scroll.get_child(0).size.x <= outer_scroll.size.x + 1, "page_fits_viewport"):
        return
    if not check(asset_scroll.size.y >= 400, "asset_list_has_usable_height"):
        return
    var stage_rect = page.package_stage.get_global_rect()
    for tile in visible_players.get_children():
        if not check(stage_rect.encloses(tile.get_global_rect()), "selected_tiles_not_clipped"):
            return
    outer_scroll.scroll_vertical = int(outer_scroll.get_v_scroll_bar().max_value)
    asset_scroll.scroll_vertical = int(asset_scroll.get_v_scroll_bar().max_value)
    await process_frame
    var last_pick = page.active_assets_rows.find_child("TradePick_pick11", true, false)
    if not check(asset_scroll.get_global_rect().intersects(last_pick.get_global_rect()), "last_draft_right_reachable"):
        return
    if not check(outer_scroll.get_global_rect().intersects(page.proposal_rows.get_global_rect()), "trade_finder_reachable"):
        return
    page._clear_package()
    if not check(page.execute_button.disabled and page.preview_button.disabled and page.package_stage.find_child("OutgoingSelectedPlayers", true, false).get_child_count() == 1, "clear_package_restores_empty_stage"):
        return
    if not check(page.execute_request.get_http_client_status() == HTTPClient.STATUS_DISCONNECTED, "no_execution_request_sent"):
        return
    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({"portrait_asset_toggles": true, "two_team_package_stage": true, "draft_rights_and_salary_comparison": true, "unknown_salary_preserved": true, "large_packages_preserve_exact_ids": true, "proposal_load_and_clear": true, "preview_gate_and_late_response_safety": true, "scroll_and_unclipped_layout": true, "no_execution_request_sent": true}))
    output.close()
    print("BATCH26_STAGE::complete")
    quit(0)
'''


def main() -> int:
    before = hashes()
    godot = Path(os.environ["USERPROFILE"]) / "Downloads/Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console
    results: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="v3_batch26_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "smoke.gd"
        script.write_text(GDSCRIPT.replace("MARKER_PATH", json.dumps(marker.as_posix())), encoding="utf-8")
        try:
            proc = subprocess.run([str(godot), "--headless", "--path", "godot_client", "--script", str(script)], cwd=ROOT, capture_output=True, text=True, timeout=30)
            combined = proc.stdout + "\n" + proc.stderr
            print(combined[-8000:])
            results["godot_runtime_completed"] = proc.returncode == 0 and marker.exists() and not any(value in combined.lower() for value in ["script error", "parse error", "batch26_fail", "failed to load script"])
            if results["godot_runtime_completed"]:
                results.update(json.loads(marker.read_text(encoding="utf-8")))
        except (subprocess.TimeoutExpired, OSError) as exc:
            results["godot_runtime_completed"] = False
            print(exc)
    results["active_v3_and_protected_v2_unchanged"] = hashes() == before
    out = ROOT / "outputs/v3_batch26_trade_experience"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(json.dumps({"version": VERSION, "results": results}, indent=2), encoding="utf-8")
    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    passed = all(results.values())
    print("V3 BATCH 26 TRADE EXPERIENCE VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
