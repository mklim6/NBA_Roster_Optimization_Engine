from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v3-batch20h-game-day-v1.0.0-2026-10-03"


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
    with tempfile.TemporaryDirectory(prefix="v3_free_agency_smoke_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "game_day.gd"
        script.write_text("""extends SceneTree
func _initialize():
    var page = load("res://scripts/free_agency_center_v3.gd").new()
    root.add_child(page)
    await process_frame
    var pool: Array = []
    for i in range(85):
        pool.append({"player_id": str(i), "name": "Fixture %02d" % i, "position": "PG" if i < 10 else "C", "salary": 5000000, "overall": null, "age": 25})
    var market = {"players": pool, "season": null, "working_save_unchanged": true, "active_v2_unchanged": true}
    page._on_market_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(market).to_utf8_buffer())
    assert(page.market_count.text == "Showing 80 of 85 matches")
    assert(page.market_rows.get_child_count() == 80)
    page.position_filter.select(1)
    page._render_market_rows()
    assert(page.market_count.text == "Showing 10 of 10 matches")
    page.position_filter.select(0)
    page.search_box.text = "no such player"
    page._render_market_rows()
    assert(page.market_count.text == "Showing 0 of 0 matches")
    assert("No players match" in page.market_rows.get_child(0).text)
    page.search_box.text = ""
    page._select_player(pool[0])
    assert(page.offer_state.text == "OFFER NEEDS PREVIEW")
    assert(not "<null>" in page.selection_label.text)
    assert(page.market_rows.get_child(0).get_theme_stylebox("normal").border_color == page.brand_color)
    var preview = {"working_save_unchanged": true, "active_v2_unchanged": true, "working_save_sha256": "fixture-sha", "contract_cba_gate": {"status": "pass"}, "transaction_preview": {"status": "pass", "can_commit": true, "candidate_fingerprint": "fixture-token"}}
    page.pending_preview_request_payload = page._current_offer_request_payload().duplicate(true)
    page._on_preview_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(preview).to_utf8_buffer())
    assert(not page.sign_button.disabled)
    assert(page.offer_state.text == "READY TO CONFIRM")
    page.offer_salary.text = "6000000"
    page._on_offer_changed("")
    assert(page.sign_button.disabled)
    assert(page.latest_preview_fingerprint == "")
    page._on_preview_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(preview).to_utf8_buffer())
    assert(page.sign_button.disabled)
    assert("while preview was running" in page.preview_label.text)
    for option in [page.offer_years, page.offer_option]:
        page.pending_preview_request_payload = page._current_offer_request_payload().duplicate(true)
        page._on_preview_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(preview).to_utf8_buffer())
        option.select(1 if option.selected == 0 else 0)
        page._on_offer_option_changed(option.selected)
        assert(page.sign_button.disabled)
    page._select_player(pool[1])
    assert(page.latest_preview_fingerprint == "")
    assert(page.market_rows.get_child(1).get_theme_stylebox("normal").border_color == page.brand_color)
    assert(page.market_rows.get_child(0).get_theme_stylebox("normal").border_color == page.BORDER)
    page.pending_preview_request_payload = page._current_offer_request_payload().duplicate(true)
    preview.contract_cba_gate.status = "blocked"
    page._on_preview_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(preview).to_utf8_buffer())
    assert(page.sign_button.disabled)
    assert(page.offer_state.text == "PREVIEW REJECTED")
    market.players = [pool[0]]
    page._on_market_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(market).to_utf8_buffer())
    assert(page.market_count.text == "Showing 1 of 1 free agents")
    assert(page.market_rows.get_child_count() == 1)
    market.players = []
    page._on_market_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(market).to_utf8_buffer())
    assert(page.market_count.text == "Showing 0 of 0 free agents")
    assert("No free agents" in page.market_rows.get_child(0).text)
    market.players = null
    page._on_market_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(market).to_utf8_buffer())
    assert(page.market_count.text == "Market data unavailable")
    assert(page.sign_button.disabled)
    market.players = pool
    market.active_v2_unchanged = false
    page._on_market_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(market).to_utf8_buffer())
    assert(page.status_label.text == "FREE-AGENCY SAFETY CHECK FAILED")
    assert(page.sign_button.disabled)
    preview.contract_cba_gate.status = "pass"
    page._on_preview_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(preview).to_utf8_buffer())
    assert(page.sign_button.disabled)
    page.apply_team_brand("LAL", Color("fdb927"), Color("552583"))
    assert(page.preview_button.get_theme_color("font_color") == Color("0a0d12"))
    page.execute_in_flight = true
    page._update_preview_button()
    assert(page.offer_state.text == "SIGNING IN PROGRESS")
    assert(page.preview_button.disabled)
    assert(page.execute_request.get_http_client_status() == HTTPClient.STATUS_DISCONNECTED)
    assert(page._display(null) == "N/A")
    assert(page._display(0) == "0")
    assert(page._money_text("bad") == "N/A")
    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({"accurate_counts_and_filters": true, "null_and_empty_market": true, "selection_highlight_and_invalidation": true, "edited_offer_rejects_late_preview": true, "rejection_and_safety_failures_disable_signing": true, "brand_and_signing_state": true, "no_signing_request_sent": true}))
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
    output = ROOT / "outputs/v3_batch20h_free_agency_presentation"
    output.mkdir(parents=True, exist_ok=True)
    (output / "validation.json").write_text(json.dumps({"version": VERSION, "results": results}, indent=2), encoding="utf-8")
    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    passed = all(results.values())
    print("V3 BATCH 20H VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
