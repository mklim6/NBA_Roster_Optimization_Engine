from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v3-batch31-trade-experience-v1.0.0-2026-10-04"


def hashes() -> dict[str, str]:
    return {name: hashlib.sha256((ROOT / "outputs/runtime" / name).read_bytes()).hexdigest()
            for name in ("v3_godot_working_checkpoint.pkl.gz", "franchise_mode_checkpoint_v1.pkl.gz")}


GDSCRIPT = r'''extends SceneTree
func check(condition: bool, label: String) -> bool:
    if not condition:
        print("BATCH31_FAIL::" + label)
        quit(2)
    return condition
func _initialize():
    root.size = Vector2i(1440, 900)
    var main = load("res://scripts/main.gd").new()
    root.add_child(main)
    main.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    await process_frame
    var page = main.inbox_page
    page.apply_team_brand("BOS", Color("008348"), Color.WHITE)
    var cards = [{"id": "injury:a", "category": "Availability", "priority": "Action", "title": "Player unavailable", "detail": "Review minutes", "destination": "ROSTER", "player_id": "a", "name": "Fixture Player"}, {"id": "next_game", "category": "Game preparation", "priority": "Next", "title": "Prepare for SAS", "detail": "League day 2", "destination": "GAME DAY", "player_id": ""}]
    var payload = {"team": "BOS", "season": "2026-27", "day_index": 0, "cards": cards, "offer_queue_status": "not_initialized", "working_save_unchanged": true, "active_v2_unchanged": true}
    page._on_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(payload).to_utf8_buffer())
    if not check(page.visible_ids.size() == 2 and "1 ACTION" in page.counts.text and "not initialized" in page.status.text, "counts_and_unknown_offer_queue"):
        return
    var routed = []
    page.navigate.connect(func(destination): routed.append(destination))
    page.rows.get_child(0).get_child(0).get_child(2).pressed.emit()
    if not check(routed == ["ROSTER"] and main.current_page == "ROSTER", "routes_to_existing_tool"):
        return
    page.filter.select(1)
    page.filter.item_selected.emit(1)
    if not check(page.visible_ids.is_empty(), "empty_category_filter"):
        return
    page.apply_team_brand("LAL", Color.PURPLE, Color.WHITE)
    page._on_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(payload).to_utf8_buffer())
    if not check(page.payload.is_empty() and page.rows.get_child_count() == 0, "late_other_team_ignored"):
        return
    page.apply_team_brand("BOS", Color.GREEN, Color.WHITE)
    page.filter.select(0)
    page._on_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(payload).to_utf8_buffer())
    main.nav_buttons.INBOX.pressed.emit()
    if not check(main.current_page == "INBOX" and page.visible, "sidebar_opens_inbox"):
        return
    if not check(page.payload.is_empty() and page.rows.get_child_count() == 0, "refresh_clears_stale_cards"):
        return
    page.request.cancel_request()
    page._on_completed(HTTPRequest.RESULT_CANT_CONNECT, 0, PackedStringArray(), PackedByteArray())
    if not check("unavailable" in page.status.text, "offline_state"):
        return
    page._on_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(payload).to_utf8_buffer())
    for frame in range(10):
        await process_frame
    var scroll = page.get_child(0)
    if not check(scroll.get_child(0).size.x <= scroll.size.x + 1, "viewport_width"):
        return
    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({"counts_filters_and_portraits": true, "navigation": true, "refresh_and_team_safety": true, "offline_state": true, "layout": true}))
    output.close()
    quit(0)
'''


def backend_checks() -> dict[str, bool]:
    import asyncio
    import copy
    import sys
    from types import SimpleNamespace
    sys.path.insert(0, str(ROOT))
    from desktop_bridge.decision_inbox import build_decision_inbox
    from desktop_bridge import server
    state = SimpleNamespace(settings=SimpleNamespace(season_label="2026-27"), current_day_index=10)
    offer = dict(offer_id="good", season="2026-27", status="pending", user_team="BOS", cpu_team="SAS", expires_day=10, cpu_sends_names=["Incoming"], user_sends_names=["Outgoing"])
    state.franchise_cpu_incoming_trade_offers_v1 = dict(season="2026-27", offers=[offer, dict(offer, offer_id="expired", expires_day=9), dict(offer, offer_id="other", user_team="LAL"), dict(offer, offer_id="old", season="2025-26"), dict(offer, offer_id="resolved", status="accepted")])
    original = copy.deepcopy(state.__dict__)
    office = dict(team_health=dict(injuries=[dict(player_id="a", name="Player", status="Injured")]), morale=dict(attention=[]), rotation=dict(starters=4, total_target_minutes=200))
    result = build_decision_inbox(state, "BOS", office, dict(coaching_alerts=[], next_game={}), {})
    ids = [card["id"] for card in result["cards"]]
    checks = dict(saved_offer_filtering=ids.count("offer:good") == 1 and len([x for x in ids if x.startswith("offer:")]) == 1, builder_does_not_mutate_queue=state.__dict__ == original, injury_and_rotation_decisions="injury:a" in ids and "rotation" in ids)
    empty = build_decision_inbox(SimpleNamespace(settings=state.settings, current_day_index=0), "BOS", {}, {}, {})
    checks["uninitialized_distinct_from_empty"] = empty["offer_queue_status"] == "not_initialized" and empty["cards"] == []
    response = asyncio.run(server.decision_inbox(None))
    live = json.loads(response.body)
    checks["live_read_only_endpoint"] = response.status_code == 200 and live.get("working_save_unchanged") and live.get("active_v2_unchanged") and not live.get("working_save_write_performed")
    return checks


def main() -> int:
    before = hashes()
    godot = Path(os.environ["USERPROFILE"]) / "Downloads/Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console
    results: dict[str, bool] = backend_checks()
    with tempfile.TemporaryDirectory(prefix="v3_batch31_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "smoke.gd"
        script.write_text(GDSCRIPT.replace("MARKER_PATH", json.dumps(marker.as_posix())), encoding="utf-8")
        try:
            proc = subprocess.run([str(godot), "--headless", "--path", "godot_client", "--script", str(script)], cwd=ROOT, capture_output=True, text=True, timeout=30)
            combined = proc.stdout + "\n" + proc.stderr
            print(combined[-8000:])
            results["godot_runtime_completed"] = proc.returncode == 0 and marker.exists() and not any(value in combined.lower() for value in ["script error", "parse error", "batch31_fail", "failed to load script"])
            if results["godot_runtime_completed"]:
                results.update(json.loads(marker.read_text(encoding="utf-8")))
        except (subprocess.TimeoutExpired, OSError) as exc:
            results["godot_runtime_completed"] = False
            print(exc)
    results["active_v3_and_protected_v2_unchanged"] = hashes() == before
    out = ROOT / "outputs/v3_batch31_decision_inbox"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(json.dumps({"version": VERSION, "results": results}, indent=2), encoding="utf-8")
    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    passed = all(results.values())
    print("V3 BATCH 31 DECISION INBOX VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
