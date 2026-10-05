from __future__ import annotations

import hashlib
import json
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

VERSION = "v3-expansion40.3.1-free-agency-scroll-validator-v1.0.0-2026-10-04"


def digest(path: Path) -> str:
    if not path.exists():
        return "missing"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes() -> dict[str, str]:
    return {"v3": digest(V3), "v2": digest(V2)}


def validate_static(results: dict[str, bool]) -> None:
    source = (
        ROOT / "godot_client/scripts/free_agency_center_v3.gd"
    ).read_text(encoding="utf-8-sig")

    results["root_vertical_scroll_contract"] = all(
        token in source for token in [
            "page_scroll.vertical_scroll_mode = ScrollContainer.SCROLL_MODE_AUTO",
            'outer.name = "FreeAgencyOuterMargin"',
            "outer.size_flags_vertical = Control.SIZE_SHRINK_BEGIN",
            'column.name = "FreeAgencyPageColumn"',
            "column.size_flags_vertical = Control.SIZE_SHRINK_BEGIN",
        ]
    )
    results["nested_market_scroll_contract"] = all(
        token in source for token in [
            "market_scroll.vertical_scroll_mode = ScrollContainer.SCROLL_MODE_AUTO",
            "market_scroll.mouse_force_pass_scroll_events = true",
        ]
    )
    results["bottom_safe_area_contract"] = all(
        token in source for token in [
            'page_bottom_spacer.name = "FreeAgencyBottomSafeArea"',
            "page_bottom_spacer.custom_minimum_size = Vector2(0, 180)",
        ]
    )
    results["free_agency_write_paths_preserved"] = all(
        token in source for token in [
            'const PREVIEW_URL := "http://127.0.0.1:8765/v3/free-agency/preview"',
            'const EXECUTE_URL := "http://127.0.0.1:8765/v3/free-agency/execute"',
            "preview_button.pressed.connect(_request_preview)",
            "sign_button.pressed.connect(_confirm_sign_player)",
        ]
    )


def validate_godot(results: dict[str, bool]) -> None:
    godot = (
        Path(os.environ.get("USERPROFILE", ""))
        / "Downloads/Godot_v4.0-stable_win64.exe"
    )
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console

    if not godot.is_file():
        print(f"[FAIL] Godot executable not found: {godot}")
        results["godot_free_agency_scroll_runtime"] = False
        return

    with tempfile.TemporaryDirectory(prefix="v3_exp40_3_1_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "smoke.gd"

        gdscript = r'''extends SceneTree

func fail_now(label: String) -> void:
    print("EXP40_3_1_FAIL::" + label)
    quit(2)


func _initialize() -> void:
    var page_script = load("res://scripts/free_agency_center_v3.gd")
    if page_script == null:
        fail_now("script_load")
        return

    var page = page_script.new()
    if page == null:
        fail_now("construct")
        return

    page.call("_build_ui")

    var root_scroll = page.find_child("FreeAgencyPageScroll", true, false)
    var outer = page.find_child("FreeAgencyOuterMargin", true, false)
    var column = page.find_child("FreeAgencyPageColumn", true, false)
    var market_scroll = page.find_child("FreeAgencyMarketScroll", true, false)
    var safe_area = page.find_child("FreeAgencyBottomSafeArea", true, false)

    if root_scroll == null:
        page.free()
        fail_now("root_scroll_missing")
        return
    if root_scroll.vertical_scroll_mode != ScrollContainer.SCROLL_MODE_AUTO:
        page.free()
        fail_now("root_scroll_mode")
        return
    if outer == null or outer.size_flags_vertical != Control.SIZE_SHRINK_BEGIN:
        page.free()
        fail_now("outer_contract")
        return
    if column == null or column.size_flags_vertical != Control.SIZE_SHRINK_BEGIN:
        page.free()
        fail_now("column_contract")
        return
    if market_scroll == null:
        page.free()
        fail_now("market_scroll_missing")
        return
    if market_scroll.vertical_scroll_mode != ScrollContainer.SCROLL_MODE_AUTO:
        page.free()
        fail_now("market_scroll_mode")
        return
    if not market_scroll.mouse_force_pass_scroll_events:
        page.free()
        fail_now("market_scroll_pass")
        return
    if safe_area == null or safe_area.custom_minimum_size.y < 180.0:
        page.free()
        fail_now("safe_area")
        return

    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({
        "free_agency_component_constructed": true,
        "root_scroll_runtime": true,
        "nested_market_scroll_runtime": true,
        "bottom_safe_area_runtime": true
    }))
    output.close()

    page.free()
    print("EXP40_3_1_COMPLETE")
    quit(0)
'''
        gdscript = gdscript.replace("MARKER_PATH", json.dumps(marker.as_posix()))
        script.write_text(gdscript, encoding="utf-8")

        proc = subprocess.run(
            [
                str(godot),
                "--headless",
                "--path",
                "godot_client",
                "--script",
                str(script),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        if combined.strip():
            print(combined[-12000:])

        results["godot_free_agency_scroll_runtime"] = (
            proc.returncode == 0
            and marker.exists()
            and "EXP40_3_1_COMPLETE" in combined
            and "EXP40_3_1_FAIL::" not in combined
            and "parse error" not in combined.lower()
            and "parser error" not in combined.lower()
        )
        if marker.exists():
            results.update(json.loads(marker.read_text(encoding="utf-8")))


def main() -> int:
    before = hashes()
    results: dict[str, bool] = {}

    print("=" * 110)
    print("V3 EXPANSION 40.3.1 — FREE AGENCY SCROLL VALIDATOR RECOVERY")
    print("=" * 110)

    validate_static(results)
    validate_godot(results)
    results["active_v3_and_protected_v2_unchanged"] = hashes() == before

    for key, passed in results.items():
        print(f"{key}: {'PASS' if passed else 'FAIL'}")

    ok = all(results.values())
    print(
        "V3 EXPANSION 40.3.1 FREE AGENCY SCROLL "
        + ("PASSED" if ok else "FAILED")
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
