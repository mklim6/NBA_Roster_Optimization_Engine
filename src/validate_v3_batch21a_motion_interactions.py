from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UX = ROOT / "godot_client/scripts/ux_polish_v3.gd"
MAIN = ROOT / "godot_client/scripts/main.gd"
V3 = ROOT / "outputs/runtime/v3_godot_working_checkpoint.pkl.gz"
V2 = ROOT / "outputs/runtime/franchise_mode_checkpoint_v1.pkl.gz"
VERSION = "v3-batch21a-motion-interactions-v1.0.0-2026-10-04"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"


def saves() -> dict[str, str]:
    return {"v3": digest(V3), "v2": digest(V2)}


def main() -> int:
    before = saves()
    results: dict[str, bool] = {}

    ux_text = UX.read_text(encoding="utf-8") if UX.exists() else ""
    main_text = MAIN.read_text(encoding="utf-8") if MAIN.exists() else ""

    results["motion_system_present"] = all(
        token in ux_text for token in [
            "install_button_motion",
            "attach_button_motion",
            "animate_page_in",
            "animate_overlay_in",
            "BUTTON_HOVER_SCALE",
            "BUTTON_PRESS_SCALE",
        ]
    )
    results["main_installs_motion_without_backend_changes"] = all(
        token in main_text for token in [
            '# Batch 21A motion interaction system',
            'call_deferred("_install_motion_interactions")',
            "UxPolishV3.install_button_motion(target_page)",
            "/v3/franchise-summary",
            "/v3/roster",
            "/v3/game-day",
        ]
    )
    results["batch20q_visuals_preserved"] = all(
        token in main_text for token in [
            'preload("res://scripts/team_logo_v3.gd")',
            "FranchiseHeroArtV3.new()",
            "MatchupBannerV3.new()",
            "team_logo.configure",
        ]
    )

    godot = Path(os.environ.get("USERPROFILE", "")) / "Downloads/Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console

    with tempfile.TemporaryDirectory(prefix="v3_batch21a_motion_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "motion_smoke.gd"
        script.write_text(
            """extends SceneTree
func _initialize():
    var ux = load("res://scripts/ux_polish_v3.gd")

    var holder = Control.new()
    root.add_child(holder)
    holder.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

    var button = Button.new()
    button.text = "MOTION TEST"
    button.custom_minimum_size = Vector2(180, 44)
    holder.add_child(button)
    await process_frame

    ux.attach_button_motion(button)
    assert(button.has_meta("ux_motion_attached"))

    button.mouse_entered.emit()
    await create_timer(0.14).timeout
    assert(button.scale.x > 1.0)

    button.button_down.emit()
    await create_timer(0.14).timeout
    assert(button.scale.x < 1.0)

    button.mouse_exited.emit()
    await create_timer(0.14).timeout
    assert(abs(button.scale.x - 1.0) < 0.01)

    var page = Control.new()
    holder.add_child(page)
    page.position = Vector2(25, 15)
    var target_position = page.position
    ux.animate_page_in(page)
    await create_timer(0.24).timeout
    assert(abs(page.modulate.a - 1.0) < 0.01)
    assert(page.position.distance_to(target_position) < 0.5)

    var overlay = Control.new()
    overlay.custom_minimum_size = Vector2(400, 240)
    holder.add_child(overlay)
    ux.animate_overlay_in(overlay)
    await create_timer(0.24).timeout
    assert(abs(overlay.modulate.a - 1.0) < 0.01)
    assert(abs(overlay.scale.x - 1.0) < 0.01)

    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({
        "button_hover_motion": true,
        "button_press_motion": true,
        "page_slide_fade": true,
        "overlay_scale_fade": true
    }))
    output.close()
    quit(0)
""".replace("MARKER_PATH", json.dumps(marker.as_posix())),
            encoding="utf-8",
        )

        try:
            proc = subprocess.run(
                [str(godot), "--headless", "--path", "godot_client", "--script", str(script)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
            bad = (
                "script error",
                "parse error",
                "parser error",
                "assertion failed",
                "failed to load script",
            )
            results["godot_runtime_completed"] = (
                proc.returncode == 0
                and marker.exists()
                and not any(token in combined.lower() for token in bad)
            )
            if results["godot_runtime_completed"]:
                results.update(json.loads(marker.read_text(encoding="utf-8")))
            else:
                print(combined[-7000:])
        except (subprocess.TimeoutExpired, OSError) as exc:
            results["godot_runtime_completed"] = False
            print(exc)

    results["active_v3_and_protected_v2_unchanged"] = saves() == before

    output = ROOT / "outputs/v3_batch21a_motion_interactions"
    output.mkdir(parents=True, exist_ok=True)
    (output / "validation.json").write_text(
        json.dumps({"version": VERSION, "results": results}, indent=2),
        encoding="utf-8",
    )

    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")

    passed = all(results.values())
    print("V3 BATCH 21A VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
