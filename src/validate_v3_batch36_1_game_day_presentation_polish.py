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


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"


def hashes() -> dict[str, str]:
    return {"v3": digest(V3), "v2": digest(V2)}


def main() -> int:
    before = hashes()
    results: dict[str, bool] = {}

    arena_text = ARENA.read_text(encoding="utf-8")
    game_text = GAME.read_text(encoding="utf-8")

    results["compact_game_night_strip_static"] = all(
        token in arena_text
        for token in [
            'card.name = "ArenaGameNightStrip"',
            'matchup_panel.name = "ArenaCompactMatchup"',
            'context.name = "ArenaCompactGameContext"',
            'display_day = _i(next_game.get("day_index"), display_day)',
        ]
    )
    results["duplicate_full_arena_hero_removed"] = (
        'card.name = "ArenaStage"' not in arena_text
        and 'func _build_arena_header' not in arena_text
    )
    results["starting_five_preserved"] = all(
        token in arena_text
        for token in [
            "YOUR STARTING FIVE",
            "ArenaStartingFiveGrid",
            "ArenaStarterPortrait_",
            "ArenaRotationPulse",
        ]
    )
    results["write_safety_preserved"] = all(
        token in game_text
        for token in [
            "simulate_armed",
            "ROTATION_PREVIEW_URL",
            "ROTATION_APPLY_URL",
            "_rotation_local_validation",
        ]
    )

    godot = Path(os.environ.get("USERPROFILE", "")) / "Downloads/Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console

    with tempfile.TemporaryDirectory(prefix="v3_batch36_1_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "smoke.gd"

        gdscript = r'''extends SceneTree

func fail_now(label: String) -> void:
    print("BATCH36_1_FAIL::" + label)
    quit(2)


func make_player(index: int, player_name: String, position: String, overall: float, minutes: int) -> Dictionary:
    return {
        "player_id": "polish_%d" % index,
        "name": player_name,
        "generated_prospect": false,
        "position": position,
        "overall": overall,
        "target_minutes": minutes,
        "is_starter": true,
        "in_rotation": true,
        "health": {"status": "healthy", "display": "Healthy"}
    }


func _initialize() -> void:
    root.size = Vector2i(1440, 900)

    var game_payload = {
        "team": "BOS",
        "season": "2026-27",
        "phase": "regular_season",
        "day_index": 0,
        "next_game": {
            "opponent": "SAS",
            "opponent_name": "San Antonio Spurs",
            "is_home": true,
            "day_index": 2
        }
    }

    var roster_payload = {
        "players": [
            make_player(1, "Derrick White", "PG", 87.2, 33),
            make_player(2, "Payton Pritchard", "SG", 84.0, 31),
            make_player(3, "Jayson Tatum", "SF", 90.6, 33),
            make_player(4, "Paul George", "PF", 83.0, 29),
            make_player(5, "Neemias Queta", "C", 82.0, 25)
        ]
    }

    var arena = load("res://scripts/game_day_arena_experience_v3.gd").new()
    root.add_child(arena)
    arena.custom_minimum_size = Vector2(1120, 0)
    arena.configure(game_payload, roster_payload, "BOS", "SAS")
    await process_frame
    await process_frame

    if arena.find_child("ArenaStage", true, false) != null:
        fail_now("duplicate_full_arena_stage_still_present")
        return

    var strip = arena.find_child("ArenaGameNightStrip", true, false)
    if strip == null:
        fail_now("game_night_strip_missing")
        return

    var context = arena.find_child("ArenaCompactGameContext", true, false)
    if context == null:
        fail_now("compact_game_context_missing")
        return
    if str(context.text).find("DAY 2") < 0:
        fail_now("next_game_day_not_used")
        return
    if str(context.text).find("DAY 0") >= 0:
        fail_now("stale_page_day_visible")
        return

    var grid = arena.find_child("ArenaStartingFiveGrid", true, false)
    if grid == null or grid.get_child_count() != 5:
        fail_now("starting_five_not_preserved")
        return

    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({
        "compact_game_night_strip_runtime": true,
        "next_game_day_runtime": true,
        "starting_five_runtime_preserved": true
    }))
    output.close()
    quit(0)
'''
        gdscript = gdscript.replace("MARKER_PATH", json.dumps(marker.as_posix()))
        script.write_text(gdscript, encoding="utf-8")

        proc = subprocess.run(
            [str(godot), "--headless", "--path", "godot_client", "--script", str(script)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        if combined.strip():
            print(combined[-9000:])

        results["godot_batch36_1_runtime_completed"] = (
            proc.returncode == 0
            and marker.exists()
            and "BATCH36_1_FAIL::" not in combined
            and "parse error" not in combined.lower()
            and "parser error" not in combined.lower()
        )
        if results["godot_batch36_1_runtime_completed"]:
            results.update(json.loads(marker.read_text(encoding="utf-8")))

    results["active_v3_and_protected_v2_unchanged"] = hashes() == before

    for key, passed in results.items():
        print(f"{key}: {'PASS' if passed else 'FAIL'}")

    passed = all(results.values())
    print("V3 BATCH 36.1 GAME DAY PRESENTATION POLISH " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
