from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / "godot_client/scripts/game_day_center_v3.gd"
ARENA = ROOT / "godot_client/scripts/game_day_arena_experience_v3.gd"
V3 = ROOT / "outputs/runtime/v3_godot_working_checkpoint.pkl.gz"
V2 = ROOT / "outputs/runtime/franchise_mode_checkpoint_v1.pkl.gz"
VERSION = "v3-batch36-game-day-arena-v1.0.0-2026-10-04"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"


def hashes() -> dict[str, str]:
    return {"v3": digest(V3), "v2": digest(V2)}


def main() -> int:
    before = hashes()
    results: dict[str, bool] = {}

    game_text = GAME.read_text(encoding="utf-8")
    arena_text = ARENA.read_text(encoding="utf-8") if ARENA.exists() else ""

    results["arena_component_static_contract"] = all(
        token in arena_text
        for token in [
            "STARTING FIVE + ROTATION CHECK",
            "YOUR STARTING FIVE",
            "ArenaStarterPortrait_",
            "ArenaRotationPulse",
            "FRANCHISE NETWORK • GAME NIGHT",
        ]
    )

    results["game_day_integration_static_contract"] = all(
        token in game_text
        for token in [
            "GameDayArenaExperienceV3",
            'arena_experience.name = "GameDayArenaExperience"',
            "func _refresh_arena_experience() -> void:",
            "\t_refresh_arena_experience()\n\t_render_rotation_editor()",
        ]
    )

    results["existing_write_safety_preserved"] = all(
        token in game_text
        for token in [
            'ROTATION_PREVIEW_URL := "http://127.0.0.1:8765/v3/rotation/preview"',
            'ROTATION_APPLY_URL := "http://127.0.0.1:8765/v3/rotation/apply"',
            "simulate_armed",
            "_rotation_local_validation",
        ]
    )

    godot = Path(os.environ.get("USERPROFILE", "")) / "Downloads/Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console

    if not godot.is_file():
        print(f"[FAIL] Godot executable not found: {godot}")
        results["godot_batch36_runtime_completed"] = False
    else:
        with tempfile.TemporaryDirectory(prefix="v3_batch36_arena_") as scratch:
            marker = Path(scratch) / "passed.json"
            script = Path(scratch) / "smoke.gd"

            gdscript = r'''extends SceneTree

func fail_now(label: String) -> void:
    print("BATCH36_FAIL::" + label)
    quit(2)


func make_player(index: int, player_name: String, position: String, overall: float, minutes: int) -> Dictionary:
    return {
        "player_id": "arena_%d" % index,
        "name": player_name,
        "generated_prospect": false,
        "position": position,
        "overall": overall,
        "potential": overall + 2.0,
        "age": 26,
        "role": "Starter",
        "target_minutes": minutes,
        "is_starter": true,
        "in_rotation": true,
        "health": {
            "status": "healthy",
            "display": "Healthy",
            "fatigue": 0.0,
            "durability": 0.9,
            "risk_tier": "low"
        }
    }


func game_payload() -> Dictionary:
    return {
        "team": "BOS",
        "team_name": "Boston Celtics",
        "season": "2026-27",
        "phase": "regular_season",
        "day_index": 2,
        "record": {"display": "1-0"},
        "opponent_record": {"display": "0-1"},
        "next_game": {
            "opponent": "SAS",
            "opponent_name": "San Antonio Spurs",
            "is_home": true,
            "day_index": 2
        }
    }


func roster_payload() -> Dictionary:
    return {
        "editable": true,
        "active_v2_read_only": true,
        "players": [
            make_player(1, "Derrick White", "PG", 87.2, 33),
            make_player(2, "Payton Pritchard", "SG", 84.0, 31),
            make_player(3, "Jayson Tatum", "SF", 90.6, 33),
            make_player(4, "Paul George", "PF", 83.0, 29),
            make_player(5, "Neemias Queta", "C", 82.0, 25)
        ],
        "rotation_rules": {
            "required_starters": 5,
            "minimum_game_players": 8,
            "maximum_rotation_players": 15,
            "required_total_minutes": 240.0,
            "maximum_player_minutes": 48.0
        }
    }


func _initialize() -> void:
    root.size = Vector2i(1440, 900)

    var arena = load("res://scripts/game_day_arena_experience_v3.gd").new()
    root.add_child(arena)
    arena.custom_minimum_size = Vector2(1120, 0)
    arena.configure(game_payload(), roster_payload(), "BOS", "SAS")
    await process_frame
    await process_frame

    var game_strip = arena.find_child("ArenaGameNightStrip", true, false)
    if game_strip == null:
        fail_now("arena_game_night_strip_missing")
        return

    var compact_context = arena.find_child("ArenaCompactGameContext", true, false)
    if compact_context == null or str(compact_context.text).find("DAY 2") < 0:
        fail_now("arena_game_day_context_wrong")
        return

    var grid = arena.find_child("ArenaStartingFiveGrid", true, false)
    if grid == null or grid.get_child_count() != 5:
        fail_now("starting_five_grid_wrong_count")
        return

    for index in range(5):
        var portrait = arena.find_child("ArenaStarterPortrait_%d" % index, true, false)
        if portrait == null:
            fail_now("starter_portrait_missing_%d" % index)
            return
        if portrait.custom_minimum_size.x < 100.0 or portrait.custom_minimum_size.y < 88.0:
            fail_now("starter_portrait_too_small_%d" % index)
            return

    var pulse = arena.find_child("ArenaRotationPulse", true, false)
    if pulse == null or pulse.get_child_count() != 4:
        fail_now("rotation_pulse_missing")
        return

    arena.queue_free()
    await process_frame

    var game_day = load("res://scripts/game_day_center_v3.gd").new()
    root.add_child(game_day)
    game_day.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    await process_frame

    var integrated = game_day.find_child("GameDayArenaExperience", true, false)
    if integrated == null:
        fail_now("integrated_arena_missing")
        return

    game_day.game_payload = game_payload()
    game_day.roster_payload = roster_payload()
    game_day.active_team = "BOS"
    game_day.active_opponent = "SAS"
    game_day._refresh_arena_experience()
    await process_frame
    await process_frame

    var integrated_grid = integrated.find_child("ArenaStartingFiveGrid", true, false)
    if integrated_grid == null or integrated_grid.get_child_count() != 5:
        fail_now("integrated_starting_five_missing")
        return

    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({
        "arena_game_night_strip_runtime": true,
        "arena_team_identity_runtime": true,
        "five_large_starter_portraits_runtime": true,
        "rotation_pulse_runtime": true,
        "game_day_arena_integration_runtime": true
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

                results["godot_batch36_runtime_completed"] = (
                    proc.returncode == 0
                    and marker.exists()
                    and "BATCH36_FAIL::" not in combined
                    and "parse error" not in combined.lower()
                    and "parser error" not in combined.lower()
                )
                if results["godot_batch36_runtime_completed"]:
                    results.update(json.loads(marker.read_text(encoding="utf-8")))
            except subprocess.TimeoutExpired as exc:
                print("[FAIL] Batch 36 Godot runtime timed out.")
                if exc.stdout:
                    print(str(exc.stdout)[-6000:])
                if exc.stderr:
                    print(str(exc.stderr)[-6000:])
                results["godot_batch36_runtime_completed"] = False

    results["active_v3_and_protected_v2_unchanged"] = hashes() == before

    out = ROOT / "outputs/v3_batch36_game_day_arena"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(
        json.dumps({"version": VERSION, "results": results}, indent=2),
        encoding="utf-8",
    )

    for key, passed in results.items():
        print(f"{key}: {'PASS' if passed else 'FAIL'}")

    passed = all(results.values())
    print("V3 BATCH 36 GAME DAY ARENA OVERHAUL " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
