from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CENTER = ROOT / "godot_client/scripts/scouting_draft_center_v3.gd"
EVENT = ROOT / "godot_client/scripts/draft_night_event_v3.gd"
V3 = ROOT / "outputs/runtime/v3_godot_working_checkpoint.pkl.gz"
V2 = ROOT / "outputs/runtime/franchise_mode_checkpoint_v1.pkl.gz"
VERSION = "v3-batch37-draft-night-event-v1.0.0-2026-10-04"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"


def hashes() -> dict[str, str]:
    return {"v3": digest(V3), "v2": digest(V2)}


def main() -> int:
    before = hashes()
    results: dict[str, bool] = {}

    center_text = CENTER.read_text(encoding="utf-8")
    event_text = EVENT.read_text(encoding="utf-8") if EVENT.exists() else ""

    results["draft_event_component_present"] = all(
        token in event_text
        for token in [
            "ROAD TO DRAFT NIGHT",
            "ON THE CLOCK",
            "BEST AVAILABLE",
            "DraftSelectedProspectCard",
            "DraftOnClockOwnerLogo",
        ]
    )

    results["scouting_center_integration_present"] = all(
        token in center_text
        for token in [
            "DraftNightEventV3",
            'draft_night_event.name = "DraftNightEvent"',
            "func _refresh_draft_night_event() -> void:",
            "\t_refresh_draft_night_event()\n\t_render_board()",
        ]
    )

    results["draft_write_safety_preserved"] = all(
        token in center_text
        for token in [
            'DRAFT_PREVIEW_URL := "http://127.0.0.1:8765/v3/draft/selection/preview"',
            'DRAFT_EXECUTE_URL := "http://127.0.0.1:8765/v3/draft/selection/execute"',
            'DRAFT_ADVANCE_PREVIEW_URL := "http://127.0.0.1:8765/v3/draft/advance/preview"',
            'DRAFT_ADVANCE_EXECUTE_URL := "http://127.0.0.1:8765/v3/draft/advance/execute"',
            "latest_draft_fingerprint",
            "latest_draft_working_sha",
            "latest_cpu_draft_fingerprint",
        ]
    )

    results["no_new_backend_route_added"] = (
        event_text.find("http://") < 0
        and event_text.find("HTTPRequest") < 0
    )

    godot = Path(os.environ.get("USERPROFILE", "")) / "Downloads/Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console

    if not godot.is_file():
        print(f"[FAIL] Godot executable not found: {godot}")
        results["godot_batch37_runtime_completed"] = False
    else:
        with tempfile.TemporaryDirectory(prefix="v3_batch37_") as scratch:
            marker = Path(scratch) / "passed.json"
            script = Path(scratch) / "smoke.gd"

            gdscript = r'''extends SceneTree

func fail_now(label: String) -> void:
    print("BATCH37_FAIL::" + label)
    quit(2)


func all_label_text(node: Node) -> String:
    var output = ""
    if node is Label:
        output += str(node.text) + "\n"
    for child in node.get_children():
        output += all_label_text(child)
    return output


func prospects() -> Array:
    return [
        {
            "prospect_id": "p1",
            "Rank": 1,
            "Prospect": "Niko Jovanovic",
            "Pos": "SG",
            "School / Club": "Duke",
            "Archetype": "3-and-D Guard",
            "Scouted OVR": 74.5,
            "Scouted POT": 94.0,
            "Confidence": 71.0,
            "Projected": "Top 3"
        },
        {
            "prospect_id": "p2",
            "Rank": 2,
            "Prospect": "Micah Bennett",
            "Pos": "PG",
            "School / Club": "Marquette",
            "Archetype": "Scoring Guard",
            "Scouted OVR": 80.3,
            "Scouted POT": 91.0,
            "Confidence": 68.0,
            "Projected": "Top 5"
        },
        {
            "prospect_id": "p3",
            "Rank": 3,
            "Prospect": "Andre Vale",
            "Pos": "SF",
            "School / Club": "UCLA",
            "Archetype": "Two-Way Wing",
            "Scouted OVR": 76.0,
            "Scouted POT": 89.5,
            "Confidence": 65.0,
            "Projected": "Lottery"
        }
    ]


func scouting_payload() -> Dictionary:
    return {
        "team": "BOS",
        "draft": {
            "phase": "season_scouting",
            "draft_year": 2027,
            "source_season": "2026-27"
        },
        "summary": {
            "weeks_completed": 2,
            "weeks_remaining": 3,
            "average_confidence": 68.0
        },
        "board": prospects()
    }


func live_draft_payload() -> Dictionary:
    var payload = scouting_payload()
    payload["draft"] = {
        "phase": "draft_in_progress",
        "draft_year": 2027,
        "source_season": "2026-27",
        "current_pick": {
            "owner_team": "BOS",
            "overall_pick": 7,
            "round": 1,
            "round_pick": 7
        }
    }
    return payload


func _initialize() -> void:
    root.size = Vector2i(1440, 900)

    var event = load("res://scripts/draft_night_event_v3.gd").new()
    root.add_child(event)
    event.custom_minimum_size = Vector2(1120, 0)

    event.configure(
        scouting_payload(),
        prospects(),
        prospects()[0],
        "BOS",
        Color("007A33")
    )
    await process_frame
    await process_frame

    var scouting_text = all_label_text(event)
    if scouting_text.find("ROAD TO DRAFT NIGHT") < 0:
        fail_now("road_to_draft_night_missing")
        return
    if event.find_child("DraftRunwayTeamLogo", true, false) == null:
        fail_now("scouting_team_identity_missing")
        return
    if event.find_child("DraftSelectedProspectCard", true, false) == null:
        fail_now("selected_prospect_card_missing")
        return
    if scouting_text.find("Niko Jovanovic") < 0:
        fail_now("selected_prospect_not_rendered")
        return
    if scouting_text.find("BEST AVAILABLE") < 0:
        fail_now("best_available_missing")
        return

    event.configure(
        live_draft_payload(),
        prospects(),
        prospects()[1],
        "BOS",
        Color("007A33")
    )
    await process_frame
    await process_frame

    var live_text = all_label_text(event)
    if live_text.find("ON THE CLOCK") < 0:
        fail_now("on_the_clock_missing")
        return
    if live_text.find("PICK #7") < 0:
        fail_now("pick_number_missing")
        return
    if live_text.find("Micah Bennett") < 0:
        fail_now("live_selected_prospect_missing")
        return
    if event.find_child("DraftOnClockOwnerLogo", true, false) == null:
        fail_now("on_clock_team_logo_missing")
        return

    event.queue_free()
    await process_frame

    var center = load("res://scripts/scouting_draft_center_v3.gd").new()
    root.add_child(center)
    center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    await process_frame
    await process_frame

    if center.find_child("DraftNightEvent", true, false) == null:
        fail_now("integrated_draft_event_missing")
        return

    center.page_payload = live_draft_payload()
    center.prospects = prospects()
    center.selected_prospect = prospects()[0]
    center.brand_color = Color("007A33")
    center._refresh_draft_night_event()
    await process_frame
    await process_frame

    var integrated = center.find_child("DraftNightEvent", true, false)
    var integrated_text = all_label_text(integrated)
    if integrated_text.find("ON THE CLOCK") < 0:
        fail_now("integrated_live_draft_state_missing")
        return

    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({
        "road_to_draft_night_runtime": true,
        "selected_prospect_spotlight_runtime": true,
        "best_available_runtime": true,
        "on_the_clock_runtime": true,
        "pick_number_runtime": true,
        "draft_team_identity_runtime": true,
        "scouting_center_event_integration_runtime": true
    }))
    output.close()
    quit(0)
'''
            gdscript = gdscript.replace("MARKER_PATH", json.dumps(marker.as_posix()))
            script.write_text(gdscript, encoding="utf-8")

            try:
                proc = subprocess.run(
                    [str(godot), "--headless", "--path", "godot_client", "--script", str(script)],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=35,
                )
                combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
                if combined.strip():
                    print(combined[-12000:])

                results["godot_batch37_runtime_completed"] = (
                    proc.returncode == 0
                    and marker.exists()
                    and "BATCH37_FAIL::" not in combined
                    and "parse error" not in combined.lower()
                    and "parser error" not in combined.lower()
                )
                if results["godot_batch37_runtime_completed"]:
                    results.update(json.loads(marker.read_text(encoding="utf-8")))
            except subprocess.TimeoutExpired as exc:
                print("[FAIL] Batch 37 Godot runtime timed out.")
                if exc.stdout:
                    print(str(exc.stdout)[-6000:])
                if exc.stderr:
                    print(str(exc.stderr)[-6000:])
                results["godot_batch37_runtime_completed"] = False

    results["active_v3_and_protected_v2_unchanged"] = hashes() == before

    out = ROOT / "outputs/v3_batch37_draft_night_event"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(
        json.dumps({"version": VERSION, "results": results}, indent=2),
        encoding="utf-8",
    )

    for key, passed in results.items():
        print(f"{key}: {'PASS' if passed else 'FAIL'}")

    passed = all(results.values())
    print("V3 BATCH 37 DRAFT NIGHT EVENT OVERHAUL " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
