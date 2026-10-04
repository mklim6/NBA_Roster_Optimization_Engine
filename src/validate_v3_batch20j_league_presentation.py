from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v3-batch20j-game-day-v1.0.0-2026-10-03"


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
    with tempfile.TemporaryDirectory(prefix="v3_league_smoke_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "game_day.gd"
        script.write_text("""extends SceneTree
func _initialize():
    var page = load("res://scripts/league_intelligence_center_v3.gd").new()
    root.add_child(page)
    await process_frame
    var payload = {"season": {"label": "2026-27", "phase": "regular_season"}, "schedule": {"completed_games": 0, "total_games": 1230, "remaining_games": 1230, "recent_results": [], "upcoming_games": []}, "active_team_standing": {"team": "BOS", "rank": 3, "conference": "East", "record": "0-0"}, "standings": {"east": [{"team": "NYK", "rank": 1, "record": "2-0", "point_diff": 12, "streak": "W2"}, {"team": "BOS", "rank": 3, "record": "0-0", "point_diff": -2, "streak": "L1"}], "west": [{"team": "SAS", "rank": 1, "record": "0-0", "point_diff": 0}]}, "leaders": {"scoring": []}}
    page._render(payload)
    assert(page.progress_label.text == "0 / 1230 • 1230 LEFT")
    assert(page.standings_tables.size() == 2)
    var east = page.standings_tables[0]
    assert(east.get_child_count() == 15)
    assert(east.get_child(6).text == "NYK")
    assert(east.get_child(8).text == "+12")
    assert(east.get_child(11).text == "BOS • YOU")
    assert(east.get_child(13).text == "-2")
    assert("No qualifying players yet." in page.leaders_label.text)
    assert("Leaderboard unavailable." in page.leaders_label.text)
    page._render(payload)
    assert(east.get_child_count() == 15)
    page.apply_team_brand("BOS", Color("007a33"), Color("ffffff"))
    assert(east.get_child(11).get_theme_color("font_color") == page.standings_highlight)
    page.apply_team_brand("SAS", Color("c4ced4"), Color("000000"))
    assert(east.get_child(11).text == "BOS")
    assert(page.standings_tables[1].get_child(6).text == "SAS • YOU")
    page._render({"season": null, "schedule": null, "standings": null, "active_team_standing": null})
    assert(page.progress_label.text == "UNAVAILABLE")
    assert(page.active_seed_label.text == "UNAVAILABLE")
    assert(east.get_child_count() == 7)
    assert(east.get_child(6).text == "Unavailable")
    assert("Recent results unavailable." in page.schedule_label.text)
    assert("Upcoming schedule unavailable." in page.schedule_label.text)
    page._render_standings_table(east, [{"team": "BOS", "record": null, "point_diff": null}])
    assert(east.get_child(7).text == "N/A")
    assert(east.get_child(8).text == "N/A")
    page.apply_team_brand("LAL", Color("fdb927"), Color("552583"))
    assert(page.refresh_button.get_theme_color("font_color") == Color("0a0d12"))
    assert(page.league_request.get_http_client_status() == HTTPClient.STATUS_DISCONNECTED)
    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({"aligned_standings_and_signed_differentials": true, "active_team_and_brand_refresh": true, "repeated_render_clears_stale_rows": true, "missing_schedule_and_leaders_truthful": true, "null_standings_safe": true, "no_network_or_write_actions": true}))
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
    output = ROOT / "outputs/v3_batch20j_league_presentation"
    output.mkdir(parents=True, exist_ok=True)
    (output / "validation.json").write_text(json.dumps({"version": VERSION, "results": results}, indent=2), encoding="utf-8")
    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    passed = all(results.values())
    print("V3 BATCH 20J VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
