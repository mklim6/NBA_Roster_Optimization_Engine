from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "godot_client" / "scripts" / "main.gd"
PORTRAIT = ROOT / "godot_client" / "scripts" / "player_portrait_v3.gd"
V3 = ROOT / "outputs" / "runtime" / "v3_godot_working_checkpoint.pkl.gz"
V2 = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"
VERSION = "v3-batch21a1-roster-portrait-scale-v1.0.0-2026-10-04"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"


def save_hashes() -> dict[str, str]:
    return {"v3": sha256(V3), "v2": sha256(V2)}


def main() -> int:
    before = save_hashes()
    results: dict[str, bool] = {}

    main_text = MAIN.read_text(encoding="utf-8") if MAIN.exists() else ""

    results["portrait_scale_marker_present"] = (
        "# Batch 21A.1 roster portrait scale polish" in main_text
    )
    results["roster_row_and_portrait_sizes_updated"] = all(
        token in main_text
        for token in [
            "panel.custom_minimum_size = Vector2(0, 108)",
            "player_identity.custom_minimum_size = Vector2(310, 88)",
            "portrait.custom_minimum_size = Vector2(120, 88)",
        ]
    )
    results["full_profile_portrait_preserved"] = (
        "profile_portrait.custom_minimum_size = Vector2(164, 120)" in main_text
    )
    results["lazy_portrait_contract_preserved"] = (
        'load("res://scripts/player_portrait_v3.gd")' in main_text
        and PORTRAIT.is_file()
    )

    godot = Path(os.environ.get("USERPROFILE", "")) / "Downloads" / "Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console

    with tempfile.TemporaryDirectory(prefix="v3_batch21a1_portrait_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "portrait_scale_smoke.gd"
        script.write_text(
            """extends SceneTree
func _initialize():
    var shell = load("res://scripts/main.gd").new()
    root.add_child(shell)
    await process_frame

    var fixture = {
        "player_id": "offline_fixture",
        "name": "Portrait Scale Fixture",
        "position": "SG",
        "overall": 82,
        "potential": 86,
        "age": 24,
        "role": "Starter",
        "target_minutes": 32,
        "is_starter": true,
        "in_rotation": true,
        "development_direction": "balanced",
        "morale": {"status": "Happy"},
        "health": {"status": "healthy", "display": "Healthy"},
        "contract": {"salary_display": "$12.0M"},
        "season_stats": {"ppg": 18.2}
    }

    var portrait_script = load("res://scripts/player_portrait_v3.gd")
    var row = shell._roster_row(fixture)
    root.add_child(row)
    await process_frame

    assert(row.custom_minimum_size.y >= 108.0)

    var row_portraits: Array = []
    collect_portraits(row, portrait_script, row_portraits)
    assert(row_portraits.size() == 1)
    assert(row_portraits[0].custom_minimum_size.x >= 120.0)
    assert(row_portraits[0].custom_minimum_size.y >= 88.0)

    shell._show_player_detail(fixture)
    await process_frame
    await process_frame

    var all_portraits: Array = []
    collect_portraits(root, portrait_script, all_portraits)
    assert(all_portraits.size() >= 2)

    var found_profile := false
    for portrait in all_portraits:
        if portrait.custom_minimum_size.x >= 160.0 and portrait.custom_minimum_size.y >= 120.0:
            found_profile = true
    assert(found_profile)

    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({
        "roster_row_height_108": true,
        "roster_portrait_120x88": true,
        "profile_portrait_preserved": true,
        "portrait_component_runtime_healthy": true
    }))
    output.close()
    quit(0)

func collect_portraits(node: Node, script, found: Array) -> void:
    if node.get_script() == script:
        found.append(node)
    for child in node.get_children():
        collect_portraits(child, script, found)
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

    results["active_v3_and_protected_v2_unchanged"] = save_hashes() == before

    out = ROOT / "outputs" / "v3_batch21a1_roster_portrait_scale"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(
        json.dumps({"version": VERSION, "results": results}, indent=2),
        encoding="utf-8",
    )

    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")

    passed = all(results.values())
    print("V3 BATCH 21A.1 VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
