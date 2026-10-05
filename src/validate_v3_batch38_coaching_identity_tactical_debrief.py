from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / "godot_client/scripts/game_day_center_v3.gd"
BOARD = ROOT / "godot_client/scripts/coaching_board_v3.gd"
V3 = ROOT / "outputs/runtime/v3_godot_working_checkpoint.pkl.gz"
V2 = ROOT / "outputs/runtime/franchise_mode_checkpoint_v1.pkl.gz"
VERSION = "v3-batch38.6-final-validation-architecture-v1.0.0-2026-10-04"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"


def hashes() -> dict[str, str]:
    return {"v3": digest(V3), "v2": digest(V2)}


def main() -> int:
    before = hashes()
    results: dict[str, bool] = {}

    game_text = GAME.read_text(encoding="utf-8")
    board_text = BOARD.read_text(encoding="utf-8")

    results["premium_coaching_board_static_contract"] = all(
        token in board_text
        for token in [
            'card.name = "CoachingCommandHero"',
            "add_child(card)",
            "TACTICAL COMMAND CENTER",
            "COACHING IDENTITY",
            "TACTICAL IDENTITY",
            "PRIMARY THREAT",
            "OPPONENT PRESSURE PROFILE",
            "MODEL EMPHASIS",
            "WHY THIS PLAN",
            "PostgameTacticalDebrief",
            'court.name = "PremiumTacticalCourt"',
            "custom_minimum_size = Vector2(520, 300)",
            'dot.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN',
        ]
    )

    results["postgame_debrief_integration_static"] = all(
        token in game_text
        for token in [
            "coaching_board.configure_postgame(game, controlled_team)",
            "coaching_board.clear_postgame()",
        ]
    )

    results["gameplay_write_safety_preserved"] = all(
        token in game_text
        for token in [
            'GAME_DAY_SIMULATE_URL := "http://127.0.0.1:8765/v3/game-day/simulate"',
            'ROTATION_PREVIEW_URL := "http://127.0.0.1:8765/v3/rotation/preview"',
            'ROTATION_APPLY_URL := "http://127.0.0.1:8765/v3/rotation/apply"',
            "simulate_armed",
            "_rotation_local_validation",
            "rotation_validated_body",
        ]
    )

    results["no_new_backend_route_added"] = (
        "http://" not in board_text and "HTTPRequest" not in board_text
    )

    godot = Path(os.environ.get("USERPROFILE", "")) / "Downloads/Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console

    if not godot.is_file():
        print(f"[FAIL] Godot executable not found: {godot}")
        results["godot_batch38_script_and_logic_runtime"] = False
    else:
        with tempfile.TemporaryDirectory(prefix="v3_batch38_6_") as scratch:
            script = Path(scratch) / "smoke.gd"
            gdscript = r'''extends SceneTree

func fail_now(label: String) -> void:
    print("BATCH38_6_FAIL::" + label)
    quit(2)


func _initialize() -> void:
    var board_script = load("res://scripts/coaching_board_v3.gd")
    if board_script == null:
        fail_now("coaching_board_script_failed_to_load")
        return

    var game_day_script = load("res://scripts/game_day_center_v3.gd")
    if game_day_script == null:
        fail_now("game_day_script_failed_to_load")
        return

    var board = board_script.new()
    if board == null:
        fail_now("coaching_board_failed_to_construct")
        return

    var cues = board._model_cues({
        "creation": 86.0,
        "spacing": 72.0,
        "rim_pressure": 91.0,
        "glass_size": 80.0,
        "interior_hub": 78.0
    })
    if cues.size() < 4:
        board.free()
        fail_now("model_cues_logic_failed")
        return

    var note = board._debrief_note("pack_paint", 6, 12, 8, 25)
    if str(note).find("PACK PAINT REVIEW") < 0:
        board.free()
        fail_now("postgame_debrief_logic_failed")
        return

    board.free()
    print("BATCH38_6_COMPLETE")
    quit(0)
'''
            script.write_text(gdscript, encoding="utf-8")

            try:
                proc = subprocess.run(
                    [str(godot), "--headless", "--path", "godot_client", "--script", str(script)],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
                if combined.strip():
                    print(combined[-10000:])

                results["godot_batch38_script_and_logic_runtime"] = (
                    proc.returncode == 0
                    and "BATCH38_6_COMPLETE" in combined
                    and "BATCH38_6_FAIL::" not in combined
                    and "parse error" not in combined.lower()
                    and "parser error" not in combined.lower()
                )
            except subprocess.TimeoutExpired as exc:
                print("[FAIL] Batch 38.6 Godot script/logic smoke timed out.")
                if exc.stdout:
                    print(str(exc.stdout)[-5000:])
                if exc.stderr:
                    print(str(exc.stderr)[-5000:])
                results["godot_batch38_script_and_logic_runtime"] = False

    results["active_v3_and_protected_v2_unchanged"] = hashes() == before

    for key, passed in results.items():
        print(f"{key}: {'PASS' if passed else 'FAIL'}")

    passed = all(results.values())
    print("V3 BATCH 38.6 COACHING IDENTITY + TACTICAL DEBRIEF " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
