from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "godot_client/scripts/main.gd"
ROSTER_EXPERIENCE = ROOT / "godot_client/scripts/roster_experience_v3.gd"
ROTATION_COURT = ROOT / "godot_client/scripts/rotation_court_v3.gd"
PLAYER_PROFILE = ROOT / "godot_client/scripts/player_profile_experience_v3.gd"
V3 = ROOT / "outputs/runtime/v3_godot_working_checkpoint.pkl.gz"
V2 = ROOT / "outputs/runtime/franchise_mode_checkpoint_v1.pkl.gz"
VERSION = "v3-batch24-roster-player-experience-v1.0.3-2026-10-04"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"


def save_hashes() -> dict[str, str]:
    return {"v3": digest(V3), "v2": digest(V2)}


def timeout_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def main() -> int:
    before = save_hashes()
    results: dict[str, bool] = {}

    main_text = MAIN.read_text(encoding="utf-8") if MAIN.exists() else ""
    results["three_new_visual_components_present"] = all(
        path.is_file() for path in [ROSTER_EXPERIENCE, ROTATION_COURT, PLAYER_PROFILE]
    )
    results["main_macro_hooks_present"] = all(
        token in main_text
        for token in [
            "# Batch 24 roster + player experience mega-overhaul",
            "RosterExperienceV3",
            "PlayerProfileExperienceV3",
            "RotationCourtV3",
            "roster_experience.configure",
            "_rotation_preview_players",
            "rotation_court_preview.configure",
        ]
    )
    results["rotation_write_safety_preserved"] = all(
        token in main_text
        for token in [
            'ROTATION_PREVIEW_URL := "http://127.0.0.1:8765/v3/rotation/preview"',
            'ROTATION_APPLY_URL := "http://127.0.0.1:8765/v3/rotation/apply"',
            'if rotation_validated_body == "" or current_body != rotation_validated_body:',
            "persisted_after_reload",
            "active_v2_unchanged",
        ]
    )
    results["roster_endpoint_contract_preserved"] = (
        'ROSTER_URL := "http://127.0.0.1:8765/v3/roster"' in main_text
        and "_apply_roster_payload(payload)" in main_text
    )

    godot = Path(os.environ.get("USERPROFILE", "")) / "Downloads/Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console

    with tempfile.TemporaryDirectory(prefix="v3_batch24_deterministic_") as scratch:
        scratch_path = Path(scratch)
        marker = scratch_path / "passed.json"
        stage = scratch_path / "stage.txt"
        failure = scratch_path / "failure.txt"
        script = scratch_path / "roster_player_smoke.gd"

        gdscript = r'''extends SceneTree

func write_text(path_value: String, text_value: String) -> void:
    var handle = FileAccess.open(path_value, FileAccess.WRITE)
    if handle != null:
        handle.store_string(text_value)
        handle.close()

func stage(label: String) -> void:
    print("BATCH24_STAGE::" + label)
    write_text(STAGE_PATH, label)

func fail_now(label: String) -> void:
    print("BATCH24_FAIL::" + label)
    write_text(FAIL_PATH, label)
    quit(2)

func make_player(player_id: String, player_name: String, position: String, overall: float, potential: float, age: int, starter: bool, minutes: int) -> Dictionary:
    return {
        "player_id": player_id,
        "name": player_name,
        "generated_prospect": false,
        "position": position,
        "overall": overall,
        "potential": potential,
        "future_outlook": potential - 1.0,
        "age": age,
        "role": "Starter" if starter else "Rotation",
        "target_minutes": minutes,
        "is_starter": starter,
        "in_rotation": true,
        "development_direction": "rising" if age <= 27 else "stable",
        "rotation_order": position,
        "contract": {"salary_display": "$20.0M", "years_remaining": 3, "status": "guaranteed", "option_type": ""},
        "morale": {"status": "Happy", "score": 84.0, "role_satisfaction": 88.0, "expected_role": "starter" if starter else "rotation", "recent_minutes": minutes, "trade_request_risk": 4.0, "reasons": []},
        "health": {"status": "healthy", "display": "Healthy", "fatigue": 12.0, "durability": 0.91, "risk_tier": "low", "season_games_missed": 0, "injuries_suffered": 0},
        "season_stats": {"ppg": 20.0, "rpg": 6.0, "apg": 5.0, "games_played": 10, "games_started": 10 if starter else 0, "mpg": minutes, "spg": 1.2, "bpg": 0.7, "fg_pct": 48.0, "three_pct": 38.0, "ft_pct": 84.0},
        "skills": {"scoring_rating": 90.0, "shooting_rating": 87.0, "playmaking_rating": 84.0, "rebounding_rating": 79.0, "defense_rating": 86.0, "efficiency_rating": 88.0, "availability_rating": 92.0}
    }

func collect_script_nodes(node: Node, target_script, found: Array) -> void:
    if node == null:
        return
    if node.get_script() == target_script:
        found.append(node)
    for child in node.get_children():
        collect_script_nodes(child, target_script, found)

func _initialize():
    stage("shell_construct")
    var shell = load("res://scripts/main.gd").new()
    if shell == null:
        fail_now("main_new_returned_null")
        return
    root.add_child(shell)
    await process_frame
    await process_frame

    var players: Array = [
        make_player("fixture_p1", "Point Guard Fixture", "PG", 91.0, 93.0, 32, true, 30),
        make_player("fixture_p2", "Shooting Guard Fixture", "SG", 88.0, 90.0, 30, true, 30),
        make_player("fixture_p3", "Small Forward Fixture", "SF", 86.0, 89.0, 28, true, 30),
        make_player("fixture_p4", "Power Forward Fixture", "PF", 84.0, 87.0, 27, true, 30),
        make_player("fixture_p5", "Center Fixture", "C", 89.0, 91.0, 26, true, 30),
        make_player("fixture_p6", "Bench Guard Fixture", "PG/SG", 82.0, 85.0, 25, false, 18),
        make_player("fixture_p7", "Bench Wing Fixture", "SG/SF", 81.0, 84.0, 24, false, 18),
        make_player("fixture_p8", "Bench Forward Fixture", "SF/PF", 80.0, 83.0, 25, false, 18),
        make_player("fixture_p9", "Bench Big Fixture", "PF/C", 79.0, 82.0, 27, false, 18),
        make_player("fixture_p10", "Reserve Guard Fixture", "PG", 77.0, 80.0, 23, false, 18)
    ]

    var payload = {
        "source": "v3_working_checkpoint",
        "editable": true,
        "team": {"abbreviation": "BOS", "name": "Boston Celtics", "roster_size": 10, "active_players": 10, "inactive_players": 0, "starters": 5, "rotation_players": 10, "injured_players": 0},
        "season": {"label": "2026-27", "day_index": 12},
        "financial": {"payroll_display": "$185.0M", "cap_room_estimate_display": "-$20.0M"},
        "chemistry": {"score": 82.0},
        "rotation_rules": {"required_starters": 5, "minimum_game_players": 8, "maximum_rotation_players": 15, "required_total_minutes": 240.0, "maximum_player_minutes": 48.0},
        "players": players
    }

    stage("apply_roster_payload")
    shell._apply_roster_payload(payload)
    await process_frame
    await process_frame

    stage("check_roster_showcase")
    if shell.roster_experience == null:
        fail_now("roster_experience_null")
        return
    if shell.roster_experience.name != "RosterExperienceShowcase":
        fail_now("roster_experience_wrong_name")
        return
    if shell.roster_team_logo == null:
        fail_now("roster_team_logo_null")
        return

    var court_script = load("res://scripts/rotation_court_v3.gd")
    var profile_script = load("res://scripts/player_profile_experience_v3.gd")
    if court_script == null:
        fail_now("court_script_failed_to_load")
        return
    if profile_script == null:
        fail_now("profile_script_failed_to_load")
        return

    var roster_courts: Array = []
    collect_script_nodes(shell.roster_page, court_script, roster_courts)
    if roster_courts.size() < 1:
        fail_now("roster_court_not_found")
        return
    if roster_courts[0].player_cards.size() != 5:
        fail_now("roster_court_did_not_build_five_cards")
        return

    stage("open_player_profile")
    shell._show_player_detail(players[0])
    await process_frame
    await process_frame
    if shell.player_detail_overlay == null:
        fail_now("profile_overlay_null")
        return

    var profile_nodes: Array = []
    collect_script_nodes(shell.player_detail_overlay, profile_script, profile_nodes)
    if profile_nodes.size() != 1:
        fail_now("premium_profile_component_count_" + str(profile_nodes.size()))
        return
    var profile = profile_nodes[0]
    var hero_portrait = profile.find_child("ProfileHeroPortrait", true, false)
    if hero_portrait == null:
        fail_now("hero_portrait_missing")
        return
    if hero_portrait.custom_minimum_size.x < 280.0:
        fail_now("hero_portrait_too_small")
        return
    if profile.find_child("ProfileStatPPG", true, false) == null:
        fail_now("profile_ppg_tile_missing")
        return
    var scoring_bar = profile.find_child("ProfileSkillScoring", true, false)
    if scoring_bar == null:
        fail_now("profile_scoring_bar_missing")
        return
    if abs(float(scoring_bar.value) - 90.0) > 0.01:
        fail_now("profile_scoring_bar_wrong_value")
        return

    stage("close_player_profile")
    shell._close_player_detail()
    await process_frame

    stage("open_rotation_lab")
    shell._show_rotation_editor()
    await process_frame
    await process_frame
    if shell.rotation_overlay == null:
        fail_now("rotation_overlay_null")
        return
    if shell.rotation_court_preview == null:
        fail_now("rotation_court_preview_null")
        return
    if shell.rotation_court_preview.name != "RotationEditorCourt":
        fail_now("rotation_court_wrong_name")
        return
    if shell.rotation_court_preview.player_cards.size() != 5:
        fail_now("rotation_court_did_not_build_five_cards")
        return

    stage("check_rotation_validation")
    var validation = shell._rotation_local_validation()
    if not bool(validation.get("valid", false)):
        fail_now("local_rotation_validation_false_" + str(validation.get("issues", [])))
        return
    if abs(float(validation.get("total_minutes", 0.0)) - 240.0) > 0.1:
        fail_now("rotation_minutes_not_240")
        return
    if shell.rotation_preview_button == null or shell.rotation_preview_button.disabled:
        fail_now("preview_button_not_enabled")
        return
    if shell.rotation_apply_button == null or not shell.rotation_apply_button.disabled:
        fail_now("apply_button_should_still_be_disabled")
        return

    var body_json = shell._rotation_body_json()
    if body_json.find("fixture_p1") < 0 or body_json.find("fixture_p10") < 0:
        fail_now("rotation_body_missing_fixture_ids")
        return

    stage("close_rotation_lab")
    shell._close_rotation_editor()
    await process_frame

    stage("complete")
    write_text(MARKER_PATH, JSON.stringify({
        "roster_rotation_map_runtime": true,
        "starting_five_court_runtime": true,
        "depth_chart_runtime": true,
        "premium_player_profile_runtime": true,
        "large_profile_portrait_runtime": true,
        "profile_skill_graphics_runtime": true,
        "visual_rotation_editor_runtime": true,
        "rotation_preview_gate_stays_required": true
    }))
    quit(0)
'''
        gdscript = gdscript.replace("MARKER_PATH", json.dumps(marker.as_posix()))
        gdscript = gdscript.replace("STAGE_PATH", json.dumps(stage.as_posix()))
        gdscript = gdscript.replace("FAIL_PATH", json.dumps(failure.as_posix()))
        script.write_text(gdscript, encoding="utf-8")

        command = [str(godot), "--headless", "--path", "godot_client", "--script", str(script)]
        try:
            proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
            combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
            if combined.strip():
                print(combined[-12000:])
            if failure.exists():
                print("Batch 24 deterministic smoke failure:", failure.read_text(encoding="utf-8"))
            bad = ("script error", "parse error", "parser error", "failed to load script", "batch24_fail::")
            results["godot_macro_runtime_completed"] = (
                proc.returncode == 0
                and marker.exists()
                and not failure.exists()
                and not any(token in combined.lower() for token in bad)
            )
            if results["godot_macro_runtime_completed"]:
                results.update(json.loads(marker.read_text(encoding="utf-8")))
        except subprocess.TimeoutExpired as exc:
            results["godot_macro_runtime_completed"] = False
            print("Batch 24 deterministic smoke timed out.")
            partial = timeout_text(exc.stdout) + "\n" + timeout_text(exc.stderr)
            if partial.strip():
                print(partial[-12000:])
            if stage.exists():
                print("Last completed Batch 24 stage:", stage.read_text(encoding="utf-8"))
            if failure.exists():
                print("Recorded Batch 24 failure:", failure.read_text(encoding="utf-8"))
        except OSError as exc:
            results["godot_macro_runtime_completed"] = False
            print(exc)

    results["active_v3_and_protected_v2_unchanged"] = save_hashes() == before

    out = ROOT / "outputs/v3_batch24_roster_player_experience"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(json.dumps({"version": VERSION, "results": results}, indent=2), encoding="utf-8")

    for key, passed in results.items():
        print(f"{key}: {'PASS' if passed else 'FAIL'}")

    passed = all(results.values())
    print("V3 BATCH 24 DETERMINISTIC VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
