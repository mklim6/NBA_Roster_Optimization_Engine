from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEAGUE = ROOT / "godot_client/scripts/league_intelligence_center_v3.gd"
V3 = ROOT / "outputs/runtime/v3_godot_working_checkpoint.pkl.gz"
V2 = ROOT / "outputs/runtime/franchise_mode_checkpoint_v1.pkl.gz"
VERSION = "v3-batch35.1-opening-standings-polish-v1.0.0-2026-10-04"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"


def hashes() -> dict[str, str]:
    return {"v3": digest(V3), "v2": digest(V2)}


def main() -> int:
    before = hashes()
    results: dict[str, bool] = {}

    league_text = LEAGUE.read_text(encoding="utf-8")
    results["opening_rank_neutral_static_contract"] = all(
        token in league_text
        for token in [
            "func _standings_are_level(rows: Array) -> bool:",
            'var rank_text = "—" if opening_field else _s(row.get("rank"), "N/A")',
            'var rank_text = "—" if opening_field else str(_i(row.get("rank")))',
        ]
    )

    godot = Path(os.environ.get("USERPROFILE", "")) / "Downloads/Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console

    if not godot.is_file():
        print(f"[FAIL] Godot executable not found: {godot}")
        results["godot_opening_standings_runtime_completed"] = False
    else:
        with tempfile.TemporaryDirectory(prefix="v3_batch35_1_") as scratch:
            marker = Path(scratch) / "passed.json"
            script = Path(scratch) / "smoke.gd"

            gdscript = r'''extends SceneTree

func fail_now(label: String) -> void:
    print("BATCH35_1_FAIL::" + label)
    quit(2)


func collect_rank_column(table: GridContainer) -> Array[String]:
    var values: Array[String] = []
    var children = table.get_children()
    if children.size() < 6:
        return values
    var index = 6
    while index < children.size():
        var child = children[index]
        if child is Label:
            values.append(str(child.text))
        index += 6
    return values


func opening_payload() -> Dictionary:
    return {
        "season": {"label": "2026-27", "phase": "regular_season"},
        "schedule": {
            "completed_games": 0,
            "total_games": 1230,
            "remaining_games": 1230,
            "recent_results": [],
            "upcoming_games": [
                {"away_team": "BOS", "home_team": "SAS", "day_index": 2},
            ],
        },
        "active_team_standing": {
            "team": "BOS",
            "conference": "East",
            "record": "0-0",
            "rank": 13,
        },
        "standings": {
            "east": [
                {"team": "WAS", "rank": 1, "record": "0-0", "point_diff": 0, "streak": "N/A"},
                {"team": "BOS", "rank": 13, "record": "0-0", "point_diff": 0, "streak": "N/A"},
                {"team": "BKN", "rank": 14, "record": "0-0", "point_diff": 0, "streak": "N/A"},
            ],
            "west": [
                {"team": "UTA", "rank": 1, "record": "0-0", "point_diff": 0, "streak": "N/A"},
                {"team": "SAS", "rank": 2, "record": "0-0", "point_diff": 0, "streak": "N/A"},
            ],
        },
        "playoff_picture": {"east": [], "west": []},
        "leaders": {},
        "award_watch": {},
        "postseason": {"active": false},
        "season_history": [],
    }


func live_payload() -> Dictionary:
    var payload = opening_payload()
    payload["schedule"]["completed_games"] = 10
    payload["schedule"]["remaining_games"] = 1220
    payload["active_team_standing"]["record"] = "2-1"
    payload["active_team_standing"]["rank"] = 3
    payload["standings"]["east"] = [
        {"team": "WAS", "rank": 1, "record": "3-0", "point_diff": 18, "streak": "W3"},
        {"team": "TOR", "rank": 2, "record": "2-0", "point_diff": 11, "streak": "W2"},
        {"team": "BOS", "rank": 3, "record": "2-1", "point_diff": 7, "streak": "W1"},
    ]
    return payload


func _initialize() -> void:
    root.size = Vector2i(1280, 720)

    var league = load("res://scripts/league_intelligence_center_v3.gd").new()
    root.add_child(league)
    league.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    await process_frame

    league._render(opening_payload())
    await process_frame
    await process_frame

    if league.standings_tables.size() != 2:
        fail_now("standings_tables_missing")
        return

    var east_opening = collect_rank_column(league.standings_tables[0])
    var west_opening = collect_rank_column(league.standings_tables[1])

    for value in east_opening:
        if value != "—":
            fail_now("east_opening_rank_not_neutral")
            return
    for value in west_opening:
        if value != "—":
            fail_now("west_opening_rank_not_neutral")
            return

    league._render(live_payload())
    await process_frame
    await process_frame

    var east_live = collect_rank_column(league.standings_tables[0])
    if east_live.size() < 3:
        fail_now("live_ranks_missing")
        return
    if east_live[0] != "1" or east_live[1] != "2" or east_live[2] != "3":
        fail_now("real_ranks_do_not_return")
        return

    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({
        "opening_east_ranks_neutral_runtime": true,
        "opening_west_ranks_neutral_runtime": true,
        "real_ranks_return_runtime": true
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
                print(combined[-9000:])

            results["godot_opening_standings_runtime_completed"] = (
                proc.returncode == 0
                and marker.exists()
                and "BATCH35_1_FAIL::" not in combined
                and "parse error" not in combined.lower()
                and "parser error" not in combined.lower()
            )
            if results["godot_opening_standings_runtime_completed"]:
                results.update(json.loads(marker.read_text(encoding="utf-8")))

    results["active_v3_and_protected_v2_unchanged"] = hashes() == before

    out = ROOT / "outputs/v3_batch35_1_opening_standings_polish"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(
        json.dumps({"version": VERSION, "results": results}, indent=2),
        encoding="utf-8",
    )

    for key, passed in results.items():
        print(f"{key}: {'PASS' if passed else 'FAIL'}")

    passed = all(results.values())
    print("V3 BATCH 35.1 OPENING STANDINGS POLISH " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
