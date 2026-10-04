from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAME_DAY = ROOT / "godot_client/scripts/game_day_center_v3.gd"
V3 = ROOT / "outputs/runtime/v3_godot_working_checkpoint.pkl.gz"
V2 = ROOT / "outputs/runtime/franchise_mode_checkpoint_v1.pkl.gz"
VERSION = "v3-batch21b-game-day-broadcast-v1.0.0-2026-10-04"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"


def save_hashes() -> dict[str, str]:
    return {"v3": digest(V3), "v2": digest(V2)}


def main() -> int:
    before = save_hashes()
    results: dict[str, bool] = {}
    text = GAME_DAY.read_text(encoding="utf-8") if GAME_DAY.exists() else ""

    results["broadcast_marker_present"] = "# Batch 21B Game Day broadcast spectacle" in text
    results["team_logo_integration_present"] = all(
        token in text
        for token in [
            'preload("res://scripts/team_logo_v3.gd")',
            "PregameTeamLogo",
            "PregameOpponentLogo",
            "logo.configure(team)",
        ]
    )
    results["broadcast_pregame_and_postgame_components_present"] = all(
        token in text
        for token in [
            "BroadcastMatchupHero",
            "BroadcastPregameStrip",
            "PostgameBroadcastScoreboard",
            "PostgameBroadcastScore",
            "_animate_postgame_reveal",
        ]
    )
    results["simulation_safety_contract_preserved"] = all(
        token in text
        for token in [
            'GAME_DAY_SIMULATE_URL',
            "if not simulate_armed:",
            'simulation_button.text = "CONFIRM & SIMULATE"',
            'persisted_after_reload',
            'active_v2_unchanged',
            'working_save_only',
        ]
    )

    godot = Path(os.environ.get("USERPROFILE", "")) / "Downloads/Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console

    with tempfile.TemporaryDirectory(prefix="v3_batch21b_broadcast_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "broadcast_smoke.gd"
        script.write_text(
            """extends SceneTree
func _initialize():
    var page = load("res://scripts/game_day_center_v3.gd").new()
    root.add_child(page)
    await process_frame

    page.apply_team_brand("BOS", Color("007a33"), Color("ba9653"))

    page.game_payload = {
        "working_save_only": true,
        "active_v2_read_only": true,
        "team": "BOS",
        "team_name": "Boston Celtics",
        "season": "2026-27",
        "phase": "regular_season",
        "day_index": 2,
        "record": {"display": "0-0"},
        "opponent_record": {"display": "0-0"},
        "next_game": {
            "opponent": "SAS",
            "opponent_name": "San Antonio Spurs",
            "day_index": 2,
            "is_home": true
        },
        "unavailable_players": [],
        "coaching_alerts": [],
        "rotation": {
            "rotation_player_ids": [],
            "starter_ids": [],
            "minutes_targets": {},
            "total_minutes": 240
        },
        "league_sync": {}
    }
    page._render_game_day()
    await process_frame

    assert(page.matchup_card != null)
    assert(page.matchup_card.name == "BroadcastMatchupHero")
    assert(page.matchup_card.custom_minimum_size.y >= 320.0)
    assert(page.team_logo_control != null)
    assert(page.opponent_logo_control != null)
    assert(page.team_logo_control.team == "BOS")
    assert(page.opponent_logo_control.team == "SAS")
    assert(page.opponent_brand_panel != null)
    assert(page.broadcast_context_label.text.find("HOME COURT") >= 0)
    assert(page.simulation_button != null)
    assert(not page.simulate_armed)

    var game = {
        "home_team": "BOS",
        "away_team": "SAS",
        "home_team_name": "Boston Celtics",
        "away_team_name": "San Antonio Spurs",
        "home_score": 112,
        "away_score": 104,
        "day_index": 2,
        "overtime_periods": 0,
        "player_box_scores": [
            {
                "team": "BOS",
                "name": "Home Fixture",
                "starter": true,
                "minutes": 34,
                "points": 28,
                "rebounds": 8,
                "assists": 6,
                "steals": 1,
                "blocks": 1,
                "turnovers": 2,
                "field_goals_made": 10,
                "field_goals_attempted": 18,
                "three_pointers_made": 4,
                "three_pointers_attempted": 8
            },
            {
                "team": "SAS",
                "name": "Road Fixture",
                "starter": true,
                "minutes": 35,
                "points": 25,
                "rebounds": 7,
                "assists": 5,
                "steals": 1,
                "blocks": 0,
                "turnovers": 3,
                "field_goals_made": 9,
                "field_goals_attempted": 19,
                "three_pointers_made": 3,
                "three_pointers_attempted": 9
            }
        ]
    }

    page._render_postgame(game)
    await process_frame

    assert(page.postgame_scoreboard_panel != null)
    assert(page.postgame_scoreboard_panel.name == "PostgameBroadcastScoreboard")
    assert(page.postgame_title_label.get_theme_font_size("font_size") >= 50)

    var logo_script = load("res://scripts/team_logo_v3.gd")
    var logos: Array = []
    collect_script_nodes(page, logo_script, logos)
    assert(logos.size() >= 6)

    var saw_bos := false
    var saw_sas := false
    for logo in logos:
        if logo.team == "BOS":
            saw_bos = true
        elif logo.team == "SAS":
            saw_sas = true
    assert(saw_bos)
    assert(saw_sas)

    await create_timer(0.25).timeout
    assert(abs(page.postgame_scoreboard_panel.modulate.a - 1.0) < 0.02)
    assert(abs(page.postgame_title_label.scale.x - 1.0) < 0.02)

    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({
        "pregame_broadcast_hero_runtime": true,
        "pregame_team_logos_runtime": true,
        "opponent_team_brand_runtime": true,
        "postgame_broadcast_scoreboard_runtime": true,
        "postgame_team_logos_runtime": true,
        "postgame_reveal_animation_runtime": true,
        "simulation_stays_unarmed_during_render": true
    }))
    output.close()
    quit(0)

func collect_script_nodes(node: Node, script, found: Array) -> void:
    if node.get_script() == script:
        found.append(node)
    for child in node.get_children():
        collect_script_nodes(child, script, found)
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
                print(combined[-8000:])
        except (subprocess.TimeoutExpired, OSError) as exc:
            results["godot_runtime_completed"] = False
            print(exc)

    results["active_v3_and_protected_v2_unchanged"] = save_hashes() == before

    out = ROOT / "outputs/v3_batch21b_game_day_broadcast"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(
        json.dumps({"version": VERSION, "results": results}, indent=2),
        encoding="utf-8",
    )

    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")

    passed = all(results.values())
    print("V3 BATCH 21B VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
