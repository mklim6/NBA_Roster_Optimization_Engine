from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v3-batch20d-game-day-v1.0.0-2026-10-03"


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
    with tempfile.TemporaryDirectory(prefix="v3_game_day_smoke_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "game_day.gd"
        script.write_text("""extends SceneTree
func _initialize():
    var page = load("res://scripts/game_day_center_v3.gd").new()
    root.add_child(page)
    await process_frame
    page.game_payload = {
        "team": "BOS", "team_name": "Boston Celtics", "season": "2026-27", "phase": "regular_season",
        "next_game": {"opponent": "SAS", "opponent_name": "San Antonio Spurs", "is_home": true, "day_index": 2},
        "unavailable_players": [{"name": "Fixture", "status": "out"}],
        "coaching_alerts": [{"title": "Workload", "severity": "warning"}],
        "rotation": {"starter_ids": [], "rotation_player_ids": ["fixture"], "total_minutes": 240, "minutes_targets": {"fixture": 24}}
    }
    page._render_game_day()
    assert(page.matchup_label.text == "BOS  VS  SAS")
    assert(page.readiness_values["UNAVAILABLE"].text == "1")
    assert(page.readiness_values["COACHING ALERTS"].text == "1")
    assert(page.readiness_values["ROTATION"].text == "1")
    assert(page.readiness_values["TARGET MINUTES"].text == "240")
    assert(not page.simulation_button.disabled)
    page.apply_team_brand("BOS", Color("007a33"), Color("ffffff"))
    assert(page.team_brand_panel.get_theme_stylebox("panel").bg_color == Color("007a33"))
    assert(page.simulation_button.get_theme_stylebox("normal").bg_color == Color("007a33"))
    page.apply_team_brand("LAL", Color("fdb927"), Color("552583"))
    assert(page.team_badge.get_theme_color("font_color") == Color("0a0d12"))
    page._on_simulate_pressed()
    assert(page.simulate_armed)
    assert(page.simulation_button.text == "CONFIRM & SIMULATE")
    assert(page.simulate_request.get_http_client_status() == HTTPClient.STATUS_DISCONNECTED)
    page._reset_simulate_arm()
    assert(not page.simulate_armed)
    page.game_payload = {"team": "BOS", "phase": "regular_season"}
    page._render_game_day()
    assert(page.simulation_button.disabled)
    assert(page.matchup_label.text == "NO GAME SCHEDULED")
    for value in page.readiness_values.values():
        assert(value.text == "N/A")
    assert("Data unavailable" in page.availability_label.text)
    assert(page.availability_label.get_theme_color("font_color") == page.MUTED)
    assert("Data unavailable" in page.alerts_label.text)
    page.game_payload["unavailable_players"] = []
    page.game_payload["coaching_alerts"] = []
    page._render_readiness()
    assert(page.readiness_values["UNAVAILABLE"].text == "0")
    assert(page.readiness_values["COACHING ALERTS"].text == "0")
    var shell = load("res://scripts/main.gd").new()
    root.add_child(shell)
    await process_frame
    assert(shell._page_control("GAME DAY") == shell.game_day_page)
    shell._show_page("GAME DAY")
    assert(shell.game_day_page.visible)
    assert(not shell.home_page.visible)
    shell._show_page("HOME")
    assert(shell.home_page.visible)
    assert(not shell.game_day_page.visible)
    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({"shell_navigation_visibility": true, "readiness_metrics_match_payload": true, "brand_and_foreground_update": true, "simulation_confirmation_preserved_without_writes": true, "no_game_and_unknown_data_safe": true, "known_zero_counts_preserved": true}))
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
    output = ROOT / "outputs/v3_batch20d_game_day_presentation"
    output.mkdir(parents=True, exist_ok=True)
    (output / "validation.json").write_text(json.dumps({"version": VERSION, "results": results}, indent=2), encoding="utf-8")
    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    passed = all(results.values())
    print("V3 BATCH 20D VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
