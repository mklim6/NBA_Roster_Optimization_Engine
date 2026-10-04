from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v3-batch25-free-agency-experience-v1.0.0-2026-10-04"


def save_hashes() -> dict[str, str]:
    return {
        name: hashlib.sha256((ROOT / "outputs/runtime" / name).read_bytes()).hexdigest()
        for name in ("v3_godot_working_checkpoint.pkl.gz", "franchise_mode_checkpoint_v1.pkl.gz")
    }


GDSCRIPT = r'''extends SceneTree

func check(condition: bool, label: String) -> bool:
    if not condition:
        print("BATCH25_FAIL::" + label)
        quit(2)
    return condition

func player(id: String, name_value: String, position: String, rating, salary, age) -> Dictionary:
    return {"player_id": id, "name": name_value, "position": position, "overall": rating, "potential": null, "salary": salary, "age": age}

func market(page, pool: Array) -> void:
    var payload = {"players": pool, "season": {"label": "2026-27", "phase": "regular_season", "day_index": 0}, "working_save_unchanged": true, "active_v2_unchanged": true}
    page._on_market_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(payload).to_utf8_buffer())

func first_id(page) -> String:
    return str(page.market_rows.get_child(0).get_meta("player_id", ""))

func _initialize():
    print("BATCH25_STAGE::construct")
    var page = load("res://scripts/free_agency_center_v3.gd").new()
    root.size = Vector2i(1440, 900)
    root.add_child(page)
    page.size = Vector2(1126, 900)
    await process_frame
    var pool: Array = []
    for i in range(85):
        pool.append(player("fixture-%s" % i, "Market Player %02d" % i, "C", 70.0, 6000000, 27))
    var alpha = player("alpha", "Alpha Guard", "PG/SG", 90.0, 0, 35)
    var beta = player("beta", "Beta Forward", "PF", 84.0, 5000000, 19)
    var unknown = player("unknown", "Unknown Wing", "SF", null, null, null)
    pool.append(alpha)
    pool.append(beta)
    pool.append(unknown)
    market(page, pool)
    print("BATCH25_STAGE::pagination")
    if not check(page.market_rows.get_child_count() == 80 and page.load_more_button.visible, "initial_page_limit"):
        return
    page.load_more_button.pressed.emit()
    if not check(page.market_rows.get_child_count() == 88 and not page.load_more_button.visible, "all_players_accessible"):
        return
    if not check("88 AVAILABLE" in page.market_summary.text and "TOP OVR 90" in page.market_summary.text, "market_snapshot"):
        return

    print("BATCH25_STAGE::sort_and_filter")
    for sort_index in [1, 2, 3]:
        page.sort_selector.select(sort_index)
        page._on_position_filter_changed(sort_index)
        page._load_more_players()
        var expected = "beta" if sort_index == 3 else "alpha"
        if not check(first_id(page) == expected and str(page.market_rows.get_child(87).get_meta("player_id")) == "unknown", "sort_order_and_unknowns_%s" % sort_index):
            return
    page.salary_filter.select(1)
    page._on_position_filter_changed(1)
    if not check(page.market_rows.get_child_count() == 2, "salary_ceiling_includes_zero_excludes_unknown"):
        return
    page.position_filter.select(1)
    page._on_position_filter_changed(1)
    if not check(page.market_rows.get_child_count() == 1 and first_id(page) == "alpha", "combined_filters_secondary_position"):
        return
    page.position_filter.select(0)
    page.salary_filter.select(4)
    page._on_position_filter_changed(4)
    if not check(page.market_rows.get_child_count() == 1 and first_id(page) == "unknown", "unknown_salary_filter"):
        return
    page.salary_filter.select(0)
    page.search_box.text = "not a player"
    page._on_filter_changed("")
    if not check(page.market_count.text == "Showing 0 of 0 matches" and not page.load_more_button.visible, "empty_filter_state"):
        return
    page.search_box.text = "beta"
    page._on_filter_changed("")
    page.market_rows.get_child(0).pressed.emit()
    if not check(page.selected_portrait.configured_player_id == "beta" and "Beta Forward" in page.selection_label.text and page.sign_button.disabled, "player_card_selection"):
        return
    var portrait = page.market_rows.get_child(0).find_child("MarketPortrait", true, false)
    if not check(portrait != null and portrait.custom_minimum_size.x >= 100, "market_portrait_scale"):
        return
    # Start a request without waiting for a response, then switch to an offline ID.
    # No server is needed: cancellation must leave the portrait disconnected.
    page.selected_portrait.request.request("http://127.0.0.1:9/portrait-fixture")
    page.selected_portrait.configure(alpha)
    if not check(page.selected_portrait.configured_player_id == "alpha" and page.selected_portrait.request.get_http_client_status() == HTTPClient.STATUS_DISCONNECTED, "portrait_switch_cancels_previous_request"):
        return
    page.selected_portrait.configure(beta)

    print("BATCH25_STAGE::offer_safety")
    var preview = {"working_save_unchanged": true, "active_v2_unchanged": true, "working_save_sha256": "fixture-sha", "contract_cba_gate": {"status": "pass"}, "transaction_preview": {"status": "pass", "can_commit": true, "candidate_fingerprint": "fixture-token"}}
    page.pending_preview_request_payload = page._current_offer_request_payload().duplicate(true)
    page._on_preview_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(preview).to_utf8_buffer())
    if not check(not page.sign_button.disabled, "valid_preview_enables_confirmation"):
        return
    page.offer_salary.text = "7000000"
    page._on_offer_changed("")
    if not check(page.sign_button.disabled and page.latest_preview_fingerprint == "", "offer_edit_invalidates_preview"):
        return
    market(page, [alpha])
    if not check(page.selected_player.is_empty() and page.preview_button.disabled and page.sign_button.disabled, "removed_player_clears_selection"):
        return
    if not check(page.execute_request.get_http_client_status() == HTTPClient.STATUS_DISCONNECTED, "no_signing_request_sent"):
        return

    print("BATCH25_STAGE::scroll_layout")
    page.search_box.text = ""
    page._on_filter_changed("")
    market(page, pool)
    page._load_more_players()
    for frame in range(10):
        await process_frame
    var page_scroll = page.find_child("FreeAgencyPageScroll", true, false)
    var market_scroll = page.find_child("FreeAgencyMarketScroll", true, false)
    if not check(page_scroll.get_child(0).size.x <= page_scroll.size.x + 1, "page_width_fits_viewport"):
        return
    if not check(market_scroll.size.y >= 400, "market_list_has_usable_height"):
        return
    page_scroll.scroll_vertical = int(page_scroll.get_v_scroll_bar().max_value)
    market_scroll.scroll_vertical = int(market_scroll.get_v_scroll_bar().max_value)
    for frame in range(3):
        await process_frame
    var last = page.market_rows.get_child(87)
    if not check(market_scroll.get_global_rect().intersects(last.get_global_rect()), "last_market_player_reachable"):
        return
    page.apply_team_brand("BOS", Color("007a33"), Color("ba9653"))
    if not check(page.market_snapshot_panel.get_theme_stylebox("panel").border_color == Color(Color("007a33"), 0.42), "market_snapshot_team_brand"):
        return
    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({"complete_market_pagination": true, "numeric_sort_and_unknown_values": true, "combined_search_position_salary_filters": true, "portrait_card_selection": true, "portrait_switch_cancels_previous_request": true, "stale_selection_and_offer_preview_safety": true, "market_scroll_and_layout": true, "team_branding": true, "no_signing_request_sent": true}))
    output.close()
    print("BATCH25_STAGE::complete")
    quit(0)
'''


def main() -> int:
    before = save_hashes()
    godot = Path(os.environ["USERPROFILE"]) / "Downloads/Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console
    results: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="v3_batch25_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "smoke.gd"
        script.write_text(GDSCRIPT.replace("MARKER_PATH", json.dumps(marker.as_posix())), encoding="utf-8")
        try:
            proc = subprocess.run([str(godot), "--headless", "--path", "godot_client", "--script", str(script)], cwd=ROOT, capture_output=True, text=True, timeout=30)
            combined = proc.stdout + "\n" + proc.stderr
            print(combined[-8000:])
            results["godot_runtime_completed"] = proc.returncode == 0 and marker.exists() and not any(value in combined.lower() for value in ["script error", "parse error", "batch25_fail", "failed to load script"])
            if results["godot_runtime_completed"]:
                results.update(json.loads(marker.read_text(encoding="utf-8")))
        except (subprocess.TimeoutExpired, OSError) as exc:
            results["godot_runtime_completed"] = False
            print(exc)
    results["active_v3_and_protected_v2_unchanged"] = save_hashes() == before
    out = ROOT / "outputs/v3_batch25_free_agency_experience"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(json.dumps({"version": VERSION, "results": results}, indent=2), encoding="utf-8")
    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    passed = all(results.values())
    print("V3 BATCH 25 FREE AGENCY EXPERIENCE VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
