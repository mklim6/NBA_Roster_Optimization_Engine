from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v3-batch20o-matchup-v1.0.0-2026-10-03"


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
    var payload = {"team": {"abbreviation": "BOS", "name": "Boston Celtics"}, "season": {"phase": "regular_season"}, "record": {}, "chemistry": {}, "financial": {}, "draft": {}, "next_game": {"opponent": "LAL", "is_home": true, "days_away": 2}}
    page._apply_franchise_summary(payload)
    assert(page.matchup_banner.visible)
    assert(not page.next_game_matchup.visible)
    assert(page.matchup_banner.franchise == "BOS")
    assert(page.matchup_banner.opponent == "LAL")
    assert(page.matchup_banner.is_home)
    assert(page.matchup_phase.text == "REGULAR SEASON")
    assert("In 2 days" in page.next_game_detail.text)
    payload.team.abbreviation = "LAL"
    payload.next_game = {"opponent": "SAS", "is_home": false}
    page._apply_franchise_summary(payload)
    assert(page.matchup_banner.franchise == "LAL")
    assert(page.matchup_banner.opponent == "SAS")
    assert(not page.matchup_banner.is_home)
    assert("Date pending" in page.next_game_detail.text)
    for width in [330, 520, 680]:
        page.matchup_banner.size = Vector2(width, 100)
        page.matchup_banner.queue_redraw()
        await process_frame
    assert(page.matchup_banner.mouse_filter == Control.MOUSE_FILTER_IGNORE)
    payload.next_game = null
    page._apply_franchise_summary(payload)
    assert(not page.matchup_banner.visible)
    assert(page.next_game_matchup.visible)
    assert(page.next_game_matchup.text == "NO GAME SCHEDULED")
    payload.next_game = {"opponent": "BOS", "is_home": true, "days_away": 0}
    page._apply_franchise_summary(payload)
    assert(page.matchup_banner.visible)
    assert("Today" in page.next_game_detail.text)
    page._set_live_data_error("Offline fixture")
    assert(not page.matchup_banner.visible)
    assert(page.next_game_matchup.visible)
    assert(page.matchup_phase.text == "OFFLINE")
    assert(page.next_game_matchup.text == "DATA OFFLINE")
    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({"live_matchup_and_venue": true, "team_switch_and_resize": true, "missing_date_is_not_today": true, "empty_and_offline_clear_stale_matchup": true, "banner_does_not_capture_mouse": true}))
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
    output = ROOT / "outputs/v3_batch20o_home_hero"
    output.mkdir(parents=True, exist_ok=True)
    (output / "validation.json").write_text(json.dumps({"version": VERSION, "results": results}, indent=2), encoding="utf-8")
    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    passed = all(results.values())
    print("V3 BATCH 20O VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
