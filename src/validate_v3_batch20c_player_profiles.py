from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v3-batch20c-player-profiles-v1.0.0-2026-10-03"


def save_hashes() -> dict[str, str]:
    return {name: hashlib.sha256((ROOT / "outputs/runtime" / name).read_bytes()).hexdigest()
            for name in ("v3_godot_working_checkpoint.pkl.gz", "franchise_mode_checkpoint_v1.pkl.gz")}


def main() -> int:
    before = save_hashes()
    godot = Path(os.environ.get("USERPROFILE", "")) / "Downloads/Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console
    results = {}
    with tempfile.TemporaryDirectory(prefix="v3_profile_smoke_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "profiles.gd"
        script.write_text("""extends SceneTree
func _initialize():
    var shell = load("res://scripts/main.gd").new()
    root.add_child(shell)
    await process_frame
    var player = {
        "player_id": "offline_profile", "name": "Profile Fixture", "overall": 91.0,
        "potential": 94.0, "health": {"status": "healthy", "display": "Healthy"},
        "season_stats": {"ppg": 25.0, "rpg": 7.0, "apg": 5.0, "games_played": 8},
        "skills": {"scoring_rating": 91.0, "shooting_rating": 82.0}
    }
    shell._show_player_detail(player)
    await process_frame
    await process_frame
    var overlay = shell.player_detail_overlay
    assert(overlay.find_child("ProfileStatPPG", true, false) != null)
    assert(overlay.find_child("ProfileStatRPG", true, false) != null)
    assert(overlay.find_child("ProfileStatAPG", true, false) != null)
    assert(overlay.find_child("ProfileSkillScoring", true, false).value == 91.0)
    assert(overlay.find_child("ProfileSkillShooting", true, false).value == 82.0)
    assert(overlay.find_child("ProfileSkillDefense", true, false) == null)
    var cancel = InputEventAction.new()
    cancel.action = "ui_cancel"
    cancel.pressed = true
    shell._unhandled_key_input(cancel)
    await process_frame
    assert(shell.player_detail_overlay == null)
    shell._show_player_detail({"player_id": "offline_sparse", "name": "Sparse Fixture", "contract": {"salary_display": null}})
    await process_frame
    await process_frame
    var labels = []
    collect_labels(shell.player_detail_overlay, labels)
    assert("Status   Not evaluated" in labels)
    assert("Morale has not been evaluated for this player." in labels)
    assert("Salary   N/A" in labels)
    assert(shell.player_detail_overlay.find_child("ProfileSkillScoring", true, false) == null)
    for text in labels:
        assert(not "<null>" in text)
        assert(not "N/A%" in text)
    shell._close_player_detail()
    await process_frame
    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({"populated_profile_stats_and_skills": true, "escape_closes_profile": true, "sparse_profile_keeps_unknown_data_unknown": true, "profile_reopens_and_closes_cleanly": true}))
    output.close()
    quit(0)
func collect_labels(node, found):
    if node is Label:
        found.append(node.text)
    for child in node.get_children():
        collect_labels(child, found)
""".replace("MARKER_PATH", json.dumps(marker.as_posix())), encoding="utf-8")
        try:
            proc = subprocess.run([str(godot), "--headless", "--path", "godot_client", "--script", str(script)],
                                  cwd=ROOT, capture_output=True, text=True, timeout=30)
            combined = proc.stdout + "\n" + proc.stderr
            bad = ("script error", "parse error", "assertion failed", "failed to load script")
            results["godot_runtime_completed"] = proc.returncode == 0 and marker.exists() and not any(m in combined.lower() for m in bad)
            if results["godot_runtime_completed"]:
                results.update(json.loads(marker.read_text(encoding="utf-8")))
            else:
                print(combined[-7000:])
        except (subprocess.TimeoutExpired, OSError) as exc:
            results["godot_runtime_completed"] = False
            print(exc)
    results["active_v3_and_protected_v2_unchanged"] = save_hashes() == before
    output = ROOT / "outputs/v3_batch20c_player_profiles"
    output.mkdir(parents=True, exist_ok=True)
    (output / "validation.json").write_text(json.dumps({"version": VERSION, "results": results}, indent=2), encoding="utf-8")
    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    passed = all(results.values())
    print("V3 BATCH 20C VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
