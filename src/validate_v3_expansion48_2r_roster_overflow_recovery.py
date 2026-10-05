from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V3 = ROOT / "outputs/runtime/v3_godot_working_checkpoint.pkl.gz"

try:
    from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH
    V2 = Path(DEFAULT_CHECKPOINT_PATH)
except Exception:
    V2 = ROOT / "outputs/runtime/franchise_checkpoint.pkl.gz"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"


def hashes() -> dict[str, str]:
    return {"v3": digest(V3), "v2": digest(V2)}


def main() -> int:
    before = hashes()

    main_text = (ROOT / "godot_client/scripts/main.gd").read_text(encoding="utf-8")
    experience = (ROOT / "godot_client/scripts/roster_experience_v3.gd").read_text(encoding="utf-8")
    court = (ROOT / "godot_client/scripts/rotation_court_v3.gd").read_text(encoding="utf-8")

    checks = {
        "roster_root_horizontal_scroll_disabled": (
            "EXP48_2R_ROSTER_OVERFLOW_RECOVERY" in main_text
            and 'page_scroll.name = "RosterPageScroll"' in main_text
            and "page_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED" in main_text
            and "page_scroll.vertical_scroll_mode = ScrollContainer.SCROLL_MODE_AUTO" in main_text
        ),
        "roster_layout_minimum_widths_fit": (
            "court.custom_minimum_size = Vector2(640, 540)" in experience
            and "depth.custom_minimum_size = Vector2(320, 350)" in experience
            and "main_row.size_flags_horizontal = Control.SIZE_EXPAND_FILL" in experience
        ),
        "rotation_court_component_width_matches_parent": (
            "custom_minimum_size = Vector2(640, 540)" in court
            and "custom_minimum_size = Vector2(700, 540)" not in court
        ),
        "roster_outer_vertical_contract": (
            "outer.size_flags_vertical = Control.SIZE_SHRINK_BEGIN" in main_text
            and "column.size_flags_vertical = Control.SIZE_SHRINK_BEGIN" in main_text
        ),
    }

    godot = Path(os.environ.get("USERPROFILE", "")) / "Downloads/Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console

    checks["godot_roster_scripts_load"] = False
    if godot.is_file():
        with tempfile.TemporaryDirectory(prefix="v3_exp48_2r_") as td:
            script = Path(td) / "smoke.gd"
            gd = '''extends SceneTree
func _initialize() -> void:
    if load("res://scripts/main.gd") == null:
        print("EXP48_2R_FAIL::main")
        quit(2)
        return
    if load("res://scripts/roster_experience_v3.gd") == null:
        print("EXP48_2R_FAIL::experience")
        quit(2)
        return
    if load("res://scripts/rotation_court_v3.gd") == null:
        print("EXP48_2R_FAIL::court")
        quit(2)
        return
    print("EXP48_2R_COMPLETE")
    quit(0)
'''
            script.write_text(gd, encoding="utf-8")
            proc = subprocess.run(
                [str(godot), "--headless", "--path", "godot_client", "--script", str(script)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
            if combined.strip():
                print(combined[-8000:])
            checks["godot_roster_scripts_load"] = (
                proc.returncode == 0
                and "EXP48_2R_COMPLETE" in combined
                and "EXP48_2R_FAIL::" not in combined
                and "parse error" not in combined.lower()
                and "parser error" not in combined.lower()
            )

    checks["active_v3_and_protected_v2_unchanged"] = hashes() == before

    for key, passed in checks.items():
        print(f"{key}: {'PASS' if passed else 'FAIL'}")

    ok = all(checks.values())
    print("V3 EXPANSION 48.2R ROSTER OVERFLOW RECOVERY " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
