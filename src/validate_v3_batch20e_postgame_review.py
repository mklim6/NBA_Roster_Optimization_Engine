from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v3-batch20e-game-day-v1.0.0-2026-10-03"


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
    with tempfile.TemporaryDirectory(prefix="v3_postgame_smoke_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "game_day.gd"
        script.write_text("""extends SceneTree
func _initialize():
    var page = load("res://scripts/game_day_center_v3.gd").new()
    root.add_child(page)
    await process_frame
    page.active_team = "BOS"
    var bos = {"team": "BOS", "name": "Fixture A", "points": 30, "rebounds": 8, "assists": 4, "turnovers": 2, "field_goals_made": 10, "field_goals_attempted": 20, "three_pointers_made": 3, "three_pointers_attempted": 7}
    var second = bos.duplicate()
    second.name = "Fixture B"
    second.points = 20
    var sas = bos.duplicate()
    sas.team = "SAS"
    sas.name = "Opponent"
    sas.points = 40
    var fixture = {"home_team": "BOS", "away_team": "SAS", "home_score": 110, "away_score": 102, "day_index": 2, "overtime_periods": 1, "player_box_scores": [bos, second, sas]}
    page._render_postgame(fixture)
    assert(page.postgame_result_label.text == "POSTGAME REVIEW • WIN")
    assert("1 OT" in page.postgame_meta_label.text)
    assert(page.postgame_active_box.get_child(1).text == "TEAM TOTALS • REB 16 • AST 8 • TO 4")
    assert(page.postgame_active_box.get_child(2).text == "SHOOTING • FG 20/40 • 3PT 6/14")
    assert(page.postgame_active_box.get_child(3).text == "SCORING LEADER • Fixture A • 30 PTS")
    assert("Opponent" in page.postgame_opponent_box.get_child(3).text)
    var count = page.postgame_active_box.get_child_count()
    page._render_postgame(fixture)
    assert(page.postgame_active_box.get_child_count() == count)
    page.active_team = "SAS"
    page._render_postgame(fixture)
    assert(page.postgame_result_label.text == "POSTGAME REVIEW • LOSS")
    assert("Opponent" in page.postgame_active_box.get_child(3).text)
    fixture.away_score = 110
    page._render_postgame(fixture)
    assert(page.postgame_result_label.text == "POSTGAME REVIEW • TIED RESULT")
    second.points = 30
    assert("Fixture A / Fixture B" in page._scoring_leader([bos, second]))
    assert(page._box_total([], "rebounds") == "N/A")
    assert(page._box_total([{"rebounds": null}], "rebounds") == "N/A")
    assert(page._box_total([{"rebounds": 0}], "rebounds") == "0")
    assert(page._scoring_leader([{}]) == "SCORING LEADER • N/A")
    fixture.player_box_scores = []
    page._render_postgame(fixture)
    assert("N/A" in page.postgame_active_box.get_child(1).text)
    page.game_payload = {"team": "BOS", "phase": "regular_season"}
    page._render_game_day()
    assert(page.postgame_result_label.text == "POSTGAME REVIEW")
    assert(page.postgame_active_box.get_child_count() == 2)
    assert(page.postgame_active_box.get_child(1).text == "No completed game loaded.")
    page.apply_team_brand("BOS", Color("007a33"), Color("ffffff"))
    assert(page.postgame_active_card.get_theme_stylebox("panel").border_color == Color(Color("007a33"), 0.48))
    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({"home_and_away_results": true, "overtime_and_ties": true, "team_totals_and_leaders": true, "missing_and_zero_stats": true, "repeat_render_and_empty_reset": true, "postgame_team_brand": true}))
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
    output = ROOT / "outputs/v3_batch20e_postgame_review"
    output.mkdir(parents=True, exist_ok=True)
    (output / "validation.json").write_text(json.dumps({"version": VERSION, "results": results}, indent=2), encoding="utf-8")
    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    passed = all(results.values())
    print("V3 BATCH 20E VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
