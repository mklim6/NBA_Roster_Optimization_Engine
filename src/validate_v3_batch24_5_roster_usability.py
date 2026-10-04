from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "godot_client/scripts/main.gd"
COURT = ROOT / "godot_client/scripts/rotation_court_v3.gd"
ROSTER_EXPERIENCE = ROOT / "godot_client/scripts/roster_experience_v3.gd"
V3 = ROOT / "outputs/runtime/v3_godot_working_checkpoint.pkl.gz"
V2 = ROOT / "outputs/runtime/franchise_mode_checkpoint_v1.pkl.gz"
VERSION = "v3-batch24.5-roster-usability-v1.0.1-2026-10-04"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"


def save_hashes() -> dict[str, str]:
    return {"v3": digest(V3), "v2": digest(V2)}


def main() -> int:
    before = save_hashes()
    results: dict[str, bool] = {}

    main_text = MAIN.read_text(encoding="utf-8")
    court_text = COURT.read_text(encoding="utf-8")
    roster_text = ROSTER_EXPERIENCE.read_text(encoding="utf-8")

    results["page_scroll_contract_present"] = all(
        token in main_text
        for token in [
            'page_scroll.name = "RosterPageScroll"',
            'database_scroll.name = "PlayerDatabaseScroll"',
            'database_scroll.custom_minimum_size = Vector2(0, 445)',
            'return page_scroll',
        ]
    )
    results["starting_five_portraits_enlarged"] = all(
        token in court_text
        for token in [
            'card.custom_minimum_size = Vector2(184, 174)',
            'card.size = Vector2(184, 174)',
            'portrait.name = "CourtPortrait_" + slot',
            'portrait.custom_minimum_size = Vector2(160, 102)',
        ]
    )
    results["depth_chart_portraits_enlarged"] = all(
        token in roster_text
        for token in [
            'row.custom_minimum_size = Vector2(0, 76)',
            'portrait.name = "DepthPortrait_" + position',
            'portrait.custom_minimum_size = Vector2(80, 64)',
        ]
    )

    godot = Path(os.environ.get("USERPROFILE", "")) / "Downloads/Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console

    with tempfile.TemporaryDirectory(prefix="v3_batch24_5_roster_usability_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "smoke.gd"

        gdscript = r'''extends SceneTree

func fail_now(label: String) -> void:
    print("BATCH24_5_FAIL::" + label)
    quit(2)

func make_player(player_id: String, player_name: String, position: String, starter: bool) -> Dictionary:
    return {
        "player_id": player_id,
        "name": player_name,
        "generated_prospect": false,
        "position": position,
        "overall": 86.0,
        "potential": 89.0,
        "future_outlook": 88.0,
        "age": 26,
        "role": "Starter" if starter else "Rotation",
        "target_minutes": 30 if starter else 18,
        "is_starter": starter,
        "in_rotation": true,
        "development_direction": "stable",
        "rotation_order": position,
        "contract": {"salary_display": "$10.0M", "years_remaining": 2, "status": "guaranteed", "option_type": ""},
        "morale": {"status": "Happy", "score": 80.0, "role_satisfaction": 80.0, "expected_role": "starter", "recent_minutes": 30, "trade_request_risk": 0.0, "reasons": []},
        "health": {"status": "healthy", "display": "Healthy", "fatigue": 0.0, "durability": 0.9, "risk_tier": "low", "season_games_missed": 0, "injuries_suffered": 0},
        "season_stats": {"ppg": 0.0, "rpg": 0.0, "apg": 0.0, "games_played": 0, "games_started": 0, "mpg": 0.0, "spg": 0.0, "bpg": 0.0, "fg_pct": null, "three_pct": null, "ft_pct": null},
        "skills": {"scoring_rating": 85.0, "shooting_rating": 84.0, "playmaking_rating": 83.0, "rebounding_rating": 82.0, "defense_rating": 81.0, "efficiency_rating": 80.0, "availability_rating": 90.0}
    }

func _initialize():
    var shell = load("res://scripts/main.gd").new()
    root.add_child(shell)
    await process_frame

    var players: Array = [
        make_player("u1", "Point Guard", "PG", true),
        make_player("u2", "Shooting Guard", "SG", true),
        make_player("u3", "Small Forward", "SF", true),
        make_player("u4", "Power Forward", "PF", true),
        make_player("u5", "Center", "C", true),
        make_player("u6", "Bench Guard", "PG/SG", false),
        make_player("u7", "Bench Wing", "SG/SF", false),
        make_player("u8", "Bench Forward", "SF/PF", false),
        make_player("u9", "Bench Big", "PF/C", false),
        make_player("u10", "Reserve", "PG", false)
    ]

    var payload = {
        "source": "v3_working_checkpoint",
        "editable": true,
        "team": {"abbreviation": "BOS", "name": "Boston Celtics", "roster_size": 10, "active_players": 10, "inactive_players": 0, "starters": 5, "rotation_players": 10, "injured_players": 0},
        "season": {"label": "2026-27", "day_index": 0},
        "financial": {"payroll_display": "$0", "cap_room_estimate_display": "$0"},
        "chemistry": {"score": null},
        "rotation_rules": {"required_starters": 5, "minimum_game_players": 8, "maximum_rotation_players": 15, "required_total_minutes": 240.0, "maximum_player_minutes": 48.0},
        "players": players
    }

    root.size = Vector2i(1440, 900)
    shell.size = Vector2(1440, 900)
    for page in shell._all_page_controls():
        page.visible = page == shell.roster_page
    shell._apply_roster_payload(payload)
    await process_frame
    await process_frame

    if not (shell.roster_page is ScrollContainer):
        fail_now("roster_page_not_scroll_container")
        return
    if shell.roster_page.name != "RosterPageScroll":
        fail_now("roster_page_wrong_name")
        return

    var database_scroll = shell.roster_page.find_child("PlayerDatabaseScroll", true, false)
    if database_scroll == null:
        fail_now("player_database_scroll_missing")
        return
    if database_scroll.custom_minimum_size.y < 440.0:
        fail_now("player_database_scroll_too_short")
        return

    var roster_experience = shell.roster_experience
    if roster_experience == null:
        fail_now("roster_experience_missing")
        return

    var court_portrait = roster_experience.find_child("CourtPortrait_PG", true, false)
    if court_portrait == null:
        fail_now("court_portrait_missing")
        return
    if court_portrait.custom_minimum_size.x < 150.0:
        fail_now("court_portrait_too_small")
        return

    var depth_portrait = roster_experience.find_child("DepthPortrait_PG", true, false)
    if depth_portrait == null:
        fail_now("depth_portrait_missing")
        return
    if depth_portrait.custom_minimum_size.x < 78.0:
        fail_now("depth_portrait_too_small")
        return

    # Check actual layout after containers settle, including the minimum court width.
    for frame in range(8):
        await process_frame
    var court = roster_experience.court
    for width in [700.0, court.size.x]:
        court.size.x = width
        court._layout_player_cards()
        var bounds = Rect2(Vector2.ZERO, court.size)
        for i in range(court.player_cards.size()):
            var card = court.player_cards[i]["node"]
            var rect = Rect2(card.position, card.size)
            if not bounds.encloses(rect):
                fail_now("court_card_clipped")
                return
            for j in range(i + 1, court.player_cards.size()):
                var other = court.player_cards[j]["node"]
                if rect.intersects(Rect2(other.position, other.size)):
                    fail_now("court_cards_overlap")
                    return

    var page_bar = shell.roster_page.get_v_scroll_bar()
    var database_bar = database_scroll.get_v_scroll_bar()
    if page_bar.max_value <= page_bar.page:
        fail_now("roster_page_has_no_scroll_range")
        return
    shell.roster_page.scroll_vertical = int(page_bar.max_value)
    for frame in range(3):
        await process_frame
    if shell.roster_page.scroll_vertical <= 0:
        fail_now("roster_page_does_not_scroll")
        return
    var viewport_rect = shell.roster_page.get_global_rect()
    if not viewport_rect.intersects(database_scroll.get_global_rect()):
        print("LAYOUT::", viewport_rect, " database=", database_scroll.get_global_rect(), " page=", page_bar.max_value, "/", page_bar.page, " scroll=", shell.roster_page.scroll_vertical)
        fail_now("database_unreachable")
        return
    if database_bar.max_value <= database_bar.page:
        fail_now("database_has_no_scroll_range")
        return
    database_scroll.scroll_vertical = int(database_bar.max_value)
    await process_frame
    var last_row = shell.roster_rows.get_child(shell.roster_rows.get_child_count() - 1)
    if not database_scroll.get_global_rect().intersects(last_row.get_global_rect()):
        fail_now("last_player_unreachable")
        return

    shell._show_rotation_editor()
    for frame in range(8):
        await process_frame
    var lab_scroll = shell.rotation_overlay.find_child("RotationLabScroll", true, false)
    var controls_scroll = shell.rotation_overlay.find_child("RotationControlsScroll", true, false)
    if lab_scroll == null or controls_scroll == null:
        fail_now("rotation_lab_scroll_missing")
        return
    if controls_scroll.size.y < 260.0:
        fail_now("rotation_controls_collapsed")
        return
    lab_scroll.scroll_vertical = int(lab_scroll.get_v_scroll_bar().max_value)
    await process_frame
    if not lab_scroll.get_global_rect().intersects(controls_scroll.get_global_rect()):
        fail_now("rotation_controls_unreachable")
        return
    shell._close_rotation_editor()

    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({
        "roster_page_scroll_runtime": true,
        "player_database_scroll_runtime": true,
        "court_portrait_scale_runtime": true,
        "depth_portrait_scale_runtime": true,
        "court_cards_visible_without_overlap": true,
        "roster_page_scrolls_to_database": true,
        "database_scrolls_to_last_player": true,
        "rotation_controls_remain_reachable": true
    }))
    output.close()
    quit(0)
'''
        gdscript = gdscript.replace("MARKER_PATH", json.dumps(marker.as_posix()))
        script.write_text(gdscript, encoding="utf-8")

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

        results["godot_usability_runtime_completed"] = (
            proc.returncode == 0
            and marker.exists()
            and "BATCH24_5_FAIL::" not in combined
            and "parse error" not in combined.lower()
            and "parser error" not in combined.lower()
        )
        if results["godot_usability_runtime_completed"]:
            results.update(json.loads(marker.read_text(encoding="utf-8")))

    results["active_v3_and_protected_v2_unchanged"] = save_hashes() == before

    out = ROOT / "outputs/v3_batch24_5_roster_usability"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(
        json.dumps({"version": VERSION, "results": results}, indent=2),
        encoding="utf-8",
    )

    for key, passed in results.items():
        print(f"{key}: {'PASS' if passed else 'FAIL'}")

    passed = all(results.values())
    print("V3 BATCH 24.5 ROSTER USABILITY VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
