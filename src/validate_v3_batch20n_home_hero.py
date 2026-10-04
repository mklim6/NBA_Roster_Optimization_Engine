from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v3-batch20n-game-day-v1.0.0-2026-10-03"


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
    with tempfile.TemporaryDirectory(prefix="v3_home_hero_smoke_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "game_day.gd"
        script.write_text("""extends SceneTree
func _initialize():
    var page = load("res://scripts/main.gd").new()
    root.add_child(page)
    await process_frame
    assert(page.franchise_hero_art != null)
    assert(page.franchise_hero_art.get_parent() == page.team_card_panel)
    assert(page.franchise_hero_art.mouse_filter == Control.MOUSE_FILTER_IGNORE)
    assert(page.team_card_panel.get_child(0) == page.franchise_hero_art)
    for team in ["BOS", "LAL", "SAS"]:
        page._apply_active_team_brand(team)
        assert(page.franchise_hero_art.team == team)
        assert(page.franchise_hero_art.primary == page.active_team_primary)
        assert(page.franchise_hero_art.secondary == page.active_team_secondary)
    page.franchise_hero_art.size = Vector2(330, 220)
    page.franchise_hero_art.queue_redraw()
    await process_frame
    page.franchise_hero_art.size = Vector2(620, 250)
    page.franchise_hero_art.queue_redraw()
    await process_frame
    page._show_page("FRANCHISES")
    assert(page.save_manager_page.visible)
    assert(not page.home_page.visible)
    page._show_page("HOME")
    assert(page.home_page.visible)
    assert(not page.save_manager_page.visible)
    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({"hero_art_layer_behind_live_content": true, "team_palette_switches": true, "resize_redraw_safe": true, "art_does_not_capture_mouse": true, "home_and_franchises_navigation": true}))
    output.close()
    quit(0)
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
    output = ROOT / "outputs/v3_batch20n_home_hero"
    output.mkdir(parents=True, exist_ok=True)
    (output / "validation.json").write_text(json.dumps({"version": VERSION, "results": results}, indent=2), encoding="utf-8")
    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    passed = all(results.values())
    print("V3 BATCH 20N VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
