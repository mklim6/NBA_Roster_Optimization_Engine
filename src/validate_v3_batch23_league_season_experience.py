from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEAGUE = ROOT / "godot_client/scripts/league_intelligence_center_v3.gd"
SEASON = ROOT / "godot_client/scripts/season_lifecycle_center_v3.gd"
LEAGUE_SHOWCASE = ROOT / "godot_client/scripts/league_media_showcase_v3.gd"
SEASON_SHOWCASE = ROOT / "godot_client/scripts/season_experience_v3.gd"
V3 = ROOT / "outputs/runtime/v3_godot_working_checkpoint.pkl.gz"
V2 = ROOT / "outputs/runtime/franchise_mode_checkpoint_v1.pkl.gz"
VERSION = "v3-batch23-league-season-experience-v1.0.0-2026-10-04"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"


def save_hashes() -> dict[str, str]:
    return {"v3": digest(V3), "v2": digest(V2)}


def main() -> int:
    before = save_hashes()
    results: dict[str, bool] = {}

    league_text = LEAGUE.read_text(encoding="utf-8") if LEAGUE.exists() else ""
    season_text = SEASON.read_text(encoding="utf-8") if SEASON.exists() else ""

    results["league_showcase_component_present"] = LEAGUE_SHOWCASE.is_file()
    results["season_showcase_component_present"] = SEASON_SHOWCASE.is_file()
    results["league_macro_hooks_present"] = all(
        token in league_text for token in [
            "# Batch 23 league + season experience macro",
            "LeagueMediaShowcaseV3",
            "league_showcase.configure",
            "TeamLogoV3",
            "table.columns = 6",
        ]
    )
    results["season_macro_hooks_present"] = all(
        token in season_text for token in [
            "# Batch 23 league + season experience macro",
            "SeasonExperienceV3",
            "season_showcase.configure",
            "PageIdentityV3",
            "SEASON COMMAND",
        ]
    )
    results["lifecycle_safety_contracts_preserved"] = all(
        token in season_text for token in [
            "expected_action_fingerprint",
            "expected_working_save_sha256",
            "persisted_after_reload",
            "active_v2_unchanged",
            "recovery_checkpoint_path",
        ]
    )

    godot = Path(os.environ.get("USERPROFILE", "")) / "Downloads/Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console

    with tempfile.TemporaryDirectory(prefix="v3_batch23_league_season_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "league_season_smoke.gd"
        script.write_text(
            """extends SceneTree
func _initialize():
    var league = load("res://scripts/league_intelligence_center_v3.gd").new()
    root.add_child(league)
    await process_frame
    league.apply_team_brand("BOS", Color("007a33"), Color("ba9653"))

    var league_payload = {
        "season": {"label": "2026-27", "phase": "regular_season"},
        "schedule": {
            "completed_games": 24,
            "total_games": 82,
            "remaining_games": 58,
            "recent_results": [
                {"day_index": 22, "away_team": "BOS", "home_team": "NYK", "away_score": 112, "home_score": 105},
                {"day_index": 23, "away_team": "MIL", "home_team": "BOS", "away_score": 101, "home_score": 109}
            ],
            "upcoming_games": [
                {"day_index": 25, "away_team": "SAS", "home_team": "BOS"},
                {"day_index": 27, "away_team": "BOS", "home_team": "MIA"}
            ]
        },
        "active_team_standing": {"team": "BOS", "rank": 2, "conference": "East", "record": "18-6"},
        "standings": {
            "east": [
                {"rank": 1, "team": "CLE", "team_name": "Cleveland Cavaliers", "record": "19-5", "point_diff": 8, "streak": "W4"},
                {"rank": 2, "team": "BOS", "team_name": "Boston Celtics", "record": "18-6", "point_diff": 7, "streak": "W2"}
            ],
            "west": [
                {"rank": 1, "team": "OKC", "team_name": "Oklahoma City Thunder", "record": "20-4", "point_diff": 10, "streak": "W5"},
                {"rank": 2, "team": "DEN", "team_name": "Denver Nuggets", "record": "17-7", "point_diff": 5, "streak": "W1"}
            ]
        },
        "leaders": {
            "scoring": [{"rank": 1, "player_id": "fixture_scoring", "generated_prospect": true, "name": "Scoring Fixture", "team": "BOS", "ppg": 31.2}],
            "rebounds": [{"rank": 1, "player_id": "fixture_rebound", "generated_prospect": true, "name": "Rebound Fixture", "team": "DEN", "rpg": 13.4}],
            "assists": [{"rank": 1, "player_id": "fixture_assist", "generated_prospect": true, "name": "Assist Fixture", "team": "ATL", "apg": 11.1}],
            "steals": [],
            "blocks": []
        },
        "leader_minimum_games": 10,
        "award_watch": {
            "projection_note": "Fixture projection",
            "mvp_watch": [{"rank": 1, "player_id": "fixture_mvp", "generated_prospect": true, "name": "MVP Fixture", "team": "BOS", "ppg": 29.0, "rpg": 8.0, "apg": 7.0}],
            "dpoy_watch": [{"rank": 1, "player_id": "fixture_dpoy", "generated_prospect": true, "name": "DPOY Fixture", "team": "SAS", "ppg": 20.0, "rpg": 11.0, "apg": 3.0}]
        },
        "playoff_picture": {
            "east": [
                {"seed": 1, "team": "CLE", "record": "19-5", "zone": "playoff"},
                {"seed": 2, "team": "BOS", "record": "18-6", "zone": "playoff"},
                {"seed": 7, "team": "MIA", "record": "12-12", "zone": "play_in"}
            ],
            "west": [
                {"seed": 1, "team": "OKC", "record": "20-4", "zone": "playoff"},
                {"seed": 2, "team": "DEN", "record": "17-7", "zone": "playoff"},
                {"seed": 7, "team": "LAL", "record": "13-11", "zone": "play_in"}
            ]
        },
        "postseason": {"active": false, "stage": "", "champion": "", "runner_up": ""},
        "season_history": [
            {"season": "2025-26", "champion": "OKC", "runner_up": "IND"}
        ]
    }
    league._render(league_payload)
    await process_frame
    await process_frame

    assert(league.league_showcase != null)
    assert(league.league_showcase.name == "LeagueMediaShowcase")
    assert(league.standings_tables.size() == 2)
    assert(league.standings_tables[0].columns == 6)
    assert(league.league_showcase.get_child_count() >= 4)

    var logo_script = load("res://scripts/team_logo_v3.gd")
    var portrait_script = load("res://scripts/player_portrait_v3.gd")
    var league_logos: Array = []
    var league_portraits: Array = []
    collect_script_nodes(league, logo_script, league_logos)
    collect_script_nodes(league, portrait_script, league_portraits)
    assert(league_logos.size() >= 12)
    assert(league_portraits.size() >= 5)

    var season = load("res://scripts/season_lifecycle_center_v3.gd").new()
    root.add_child(season)
    await process_frame
    season.apply_team_brand("BOS", Color("007a33"), Color("ba9653"))
    season.summary_payload = {
        "season": {"label": "2026-27", "phase": "regular_season"},
        "schedule": {"total": 82, "completed": 24},
        "postseason": {"initialized": false, "stage": "", "completed_games": 0},
        "draft": {"initialized": false, "phase": "", "pick_count": 0},
        "cpu_free_agency": {"deficit_team_count": 0, "total_deficit": 0},
        "next_action": "",
        "next_action_label": "NO ACTION AVAILABLE",
        "blockers": [],
        "stage": "regular_season",
        "timeline": [
            {"key": "regular_season", "label": "Regular Season", "status": "current"},
            {"key": "postseason", "label": "Postseason", "status": "locked"},
            {"key": "contract_closeout", "label": "Contract Closeout", "status": "locked"},
            {"key": "draft_lottery", "label": "Draft Lottery", "status": "locked"}
        ],
        "engine_versions": {
            "postseason": "production",
            "closeout": "production",
            "draft": "production",
            "post_draft_trim": "production",
            "season_boundary": "production"
        }
    }
    season._render_summary()
    await process_frame

    assert(season.page_identity != null)
    assert(season.page_identity.team == "BOS")
    assert(season.season_showcase != null)
    assert(season.season_showcase.name == "SeasonExperienceShowcase")
    assert(season.season_showcase.get_child_count() >= 3)

    var season_logos: Array = []
    collect_script_nodes(season, logo_script, season_logos)
    assert(season_logos.size() >= 2)

    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({
        "league_media_showcase_runtime": true,
        "league_schedule_cards_runtime": true,
        "league_leader_portraits_runtime": true,
        "league_team_logo_standings_runtime": true,
        "season_command_runtime": true,
        "season_milestone_runtime": true,
        "season_team_identity_runtime": true
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
                timeout=60,
            )
            combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
            bad = (
                "script error", "parse error", "parser error",
                "assertion failed", "failed to load script",
            )
            results["godot_macro_runtime_completed"] = (
                proc.returncode == 0
                and marker.exists()
                and not any(token in combined.lower() for token in bad)
            )
            if results["godot_macro_runtime_completed"]:
                results.update(json.loads(marker.read_text(encoding="utf-8")))
            else:
                print(combined[-12000:])
        except (subprocess.TimeoutExpired, OSError) as exc:
            results["godot_macro_runtime_completed"] = False
            print(exc)

    results["active_v3_and_protected_v2_unchanged"] = save_hashes() == before

    out = ROOT / "outputs/v3_batch23_league_season_experience"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(
        json.dumps({"version": VERSION, "results": results}, indent=2),
        encoding="utf-8",
    )

    for key, passed in results.items():
        print(f"{key}: {'PASS' if passed else 'FAIL'}")

    passed = all(results.values())
    print("V3 BATCH 23 MACRO VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
