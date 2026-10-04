from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "godot_client/scripts/settings_tutorial_v3.gd"
LEAGUE = ROOT / "godot_client/scripts/league_intelligence_center_v3.gd"
MEDIA = ROOT / "godot_client/scripts/league_media_showcase_v3.gd"
FRONT = ROOT / "godot_client/scripts/front_office_center_v3.gd"
WATCH = ROOT / "godot_client/scripts/league_competition_watch_v3.gd"
V3 = ROOT / "outputs/runtime/v3_godot_working_checkpoint.pkl.gz"
V2 = ROOT / "outputs/runtime/franchise_mode_checkpoint_v1.pkl.gz"
VERSION = "v3-batch35-living-league-ui-v1.0.0-2026-10-04"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"


def hashes() -> dict[str, str]:
    return {"v3": digest(V3), "v2": digest(V2)}


def main() -> int:
    before = hashes()
    results: dict[str, bool] = {}

    settings_text = SETTINGS.read_text(encoding="utf-8")
    league_text = LEAGUE.read_text(encoding="utf-8")
    media_text = MEDIA.read_text(encoding="utf-8")
    front_text = FRONT.read_text(encoding="utf-8")
    watch_text = WATCH.read_text(encoding="utf-8") if WATCH.exists() else ""

    results["settings_responsive_contract"] = all(
        token in settings_text
        for token in [
            'content.name = "SettingsResponsiveStack"',
            'tutorial_card.name = "GuidedHelpCard"',
            'tutorial_card.custom_minimum_size = Vector2(0, 320)',
        ]
    ) and 'var content := HBoxContainer.new()' not in settings_text

    results["living_league_component_present"] = all(
        token in watch_text
        for token in [
            "LIVING LEAGUE • COMPETITION WATCH",
            "OPENING WEEK",
            "CONFERENCE PRESSURE",
            "NEXT LEAGUE TEST",
            "AROUND YOU",
        ]
    )

    results["league_integration_present"] = all(
        token in league_text
        for token in [
            "LeagueCompetitionWatchV3",
            'competition_watch.name = "LeagueCompetitionWatch"',
            'active_seed_label.text = "%s • %s • OPENING"',
        ]
    )

    results["opening_week_semantics_present"] = all(
        token in media_text
        for token in [
            "LEAGUE PREVIEW + OPENING WEEK",
            "CONFERENCE OUTLOOK",
            "seeding begins after completed games",
            "UPCOMING • %s at %s • Day %d",
        ]
    )

    results["front_office_opening_position_neutral"] = (
        'position_value.text = "%s • %s • OPENING"' in front_text
    )

    godot = Path(os.environ.get("USERPROFILE", "")) / "Downloads/Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console

    if not godot.is_file():
        print(f"[FAIL] Godot executable not found at expected path: {godot}")
        results["godot_batch35_runtime_completed"] = False
    else:
        with tempfile.TemporaryDirectory(prefix="v3_batch35_runtime_") as scratch:
            marker = Path(scratch) / "batch35_passed.json"
            script = Path(scratch) / "batch35_smoke.gd"

            gdscript = r'''extends SceneTree

func fail_now(label: String) -> void:
    print("BATCH35_FAIL::" + label)
    quit(2)


func all_label_text(node: Node) -> String:
    var output = ""
    if node is Label:
        output += str(node.text) + "\n"
    for child in node.get_children():
        output += all_label_text(child)
    return output


func opening_payload() -> Dictionary:
    return {
        "season": {
            "label": "2026-27",
            "phase": "regular_season",
        },
        "schedule": {
            "completed_games": 0,
            "total_games": 1230,
            "remaining_games": 1230,
            "recent_results": [],
            "upcoming_games": [
                {"away_team": "BOS", "home_team": "SAS", "day_index": 2},
                {"away_team": "BKN", "home_team": "NOP", "day_index": 1},
                {"away_team": "NYK", "home_team": "MEM", "day_index": 1},
            ],
        },
        "active_team_standing": {
            "team": "BOS",
            "conference": "East",
            "record": "0-0",
            "rank": 13,
        },
        "standings": {
            "east": [
                {"team": "WAS", "rank": 1, "record": "0-0", "point_diff": 0, "streak": "N/A"},
                {"team": "BOS", "rank": 13, "record": "0-0", "point_diff": 0, "streak": "N/A"},
                {"team": "BKN", "rank": 14, "record": "0-0", "point_diff": 0, "streak": "N/A"},
            ],
            "west": [
                {"team": "SAS", "rank": 2, "record": "0-0", "point_diff": 0, "streak": "N/A"},
            ],
        },
        "playoff_picture": {"east": [], "west": []},
        "leaders": {},
        "award_watch": {},
        "postseason": {"active": false},
        "season_history": [],
    }


func _initialize() -> void:
    root.size = Vector2i(1280, 720)

    var settings = load("res://scripts/settings_tutorial_v3.gd").new()
    root.add_child(settings)
    settings.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    await process_frame
    await process_frame

    var help_card = settings.find_child("GuidedHelpCard", true, false)
    if help_card == null:
        fail_now("guided_help_card_missing")
        return

    var responsive_stack = settings.find_child("SettingsResponsiveStack", true, false)
    if responsive_stack == null:
        fail_now("settings_responsive_stack_missing")
        return

    if help_card.global_position.x + help_card.size.x > settings.global_position.x + settings.size.x + 2.0:
        fail_now("guided_help_card_overflows_viewport")
        return

    settings.queue_free()
    await process_frame

    var watch = load("res://scripts/league_competition_watch_v3.gd").new()
    root.add_child(watch)
    watch.custom_minimum_size = Vector2(1050, 0)
    watch.configure(opening_payload(), "BOS", Color("007A33"), Color("BA9653"))
    await process_frame

    var watch_text = all_label_text(watch)
    if watch_text.find("OPENING WEEK") < 0:
        fail_now("competition_watch_opening_state_missing")
        return
    if watch_text.find("NEXT LEAGUE TEST") < 0:
        fail_now("competition_watch_next_test_missing")
        return
    if watch_text.find("#13") >= 0:
        fail_now("competition_watch_exposes_fake_opening_seed")
        return

    watch.queue_free()
    await process_frame

    var league = load("res://scripts/league_intelligence_center_v3.gd").new()
    root.add_child(league)
    league.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    await process_frame
    league._render(opening_payload())
    await process_frame
    await process_frame

    if league.active_seed_label.text.find("#13") >= 0:
        fail_now("league_metric_exposes_fake_opening_seed")
        return
    if league.active_seed_label.text.find("OPENING") < 0:
        fail_now("league_metric_opening_semantics_missing")
        return

    var league_text = all_label_text(league)
    if league_text.find("LEAGUE PREVIEW + OPENING WEEK") < 0:
        fail_now("league_preview_opening_section_missing")
        return
    if league_text.find("seeding begins after completed games") < 0:
        fail_now("league_wire_opening_truthfulness_missing")
        return

    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({
        "settings_help_fits_runtime": true,
        "competition_watch_opening_runtime": true,
        "league_opening_seed_neutral_runtime": true,
        "league_preview_runtime": true
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
                results["godot_batch35_runtime_completed"] = (
                    proc.returncode == 0
                    and marker.exists()
                    and "BATCH35_FAIL::" not in combined
                    and "parse error" not in combined.lower()
                    and "parser error" not in combined.lower()
                )
                if results["godot_batch35_runtime_completed"]:
                    results.update(json.loads(marker.read_text(encoding="utf-8")))
            except subprocess.TimeoutExpired as exc:
                print("[FAIL] Batch 35 Godot runtime timed out.")
                if exc.stdout:
                    print(str(exc.stdout)[-6000:])
                if exc.stderr:
                    print(str(exc.stderr)[-6000:])
                results["godot_batch35_runtime_completed"] = False

    results["active_v3_and_protected_v2_unchanged"] = hashes() == before

    out = ROOT / "outputs/v3_batch35_living_league_ui"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(
        json.dumps({"version": VERSION, "results": results}, indent=2),
        encoding="utf-8",
    )

    for key, passed in results.items():
        print(f"{key}: {'PASS' if passed else 'FAIL'}")

    passed = all(results.values())
    print("V3 BATCH 35 LIVING LEAGUE + UI RELIABILITY " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
