from __future__ import annotations

import hashlib
import json
import os
import py_compile
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from desktop_bridge.franchise_legacy_foundation import (
    FRANCHISE_LEGACY_FOUNDATION_VERSION,
    build_franchise_legacy_payload,
)
from simulation_franchise_checkpoint_v1 import (
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)

V3 = ROOT / "outputs/runtime/v3_godot_working_checkpoint.pkl.gz"
V2 = Path(DEFAULT_CHECKPOINT_PATH)
VERSION = "v3-expansion39-franchise-universe-legacy-v1.0.0-2026-10-04"


def digest(path: Path) -> str:
    if not path.exists():
        return "missing"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_hashes() -> dict[str, str]:
    return {"v3": digest(V3), "v2": digest(V2)}


def line(player_id: str, team: str, points: int, rebounds: int, assists: int, *, threes: int = 0) -> Any:
    return SimpleNamespace(
        player_id=player_id,
        team_abbreviation=team,
        points=points,
        rebounds=rebounds,
        assists=assists,
        steals=1,
        blocks=1,
        three_pointers_made=threes,
    )


def game(game_id: str, home: str, away: str, home_score: int, away_score: int, rows: list[Any], *, overtime: int = 0) -> Any:
    return SimpleNamespace(
        game_id=game_id,
        home_team=home,
        away_team=away,
        home_score=home_score,
        away_score=away_score,
        overtime_periods=overtime,
        player_box_scores=tuple(rows),
    )


def standing(wins: int, losses: int, pf: int, pa: int) -> Any:
    return SimpleNamespace(
        wins=wins,
        losses=losses,
        games_played=wins + losses,
        points_for=pf,
        points_against=pa,
    )


def synthetic_checkpoint() -> Any:
    state = SimpleNamespace(
        settings=SimpleNamespace(season_label="2028-29"),
        standings={"BOS": standing(12, 5, 2040, 1920)},
        players={
            "tatum": SimpleNamespace(player_name="Jayson Tatum", team_abbreviation="BOS", overall_rating=95.0),
            "brown": SimpleNamespace(player_name="Jaylen Brown", team_abbreviation="BOS", overall_rating=91.0),
            "rookie": SimpleNamespace(player_name="Niko Jovanovic", team_abbreviation="BOS", overall_rating=82.0),
            "wemby": SimpleNamespace(player_name="Victor Wembanyama", team_abbreviation="SAS", overall_rating=97.0),
        },
        completed_games={
            "G4": game(
                "G4", "BOS", "SAS", 126, 120,
                [
                    line("tatum", "BOS", 35, 8, 8, threes=5),
                    line("rookie", "BOS", 18, 5, 3, threes=2),
                    line("wemby", "SAS", 38, 14, 4, threes=2),
                ],
            )
        },
        postseason_state=None,
    )

    archive_2026 = SimpleNamespace(
        season_label="2026-27",
        standings={
            "BOS": standing(61, 21, 9800, 9200),
            "SAS": standing(56, 26, 9650, 9310),
        },
        completed_games={
            "G1": game(
                "G1", "BOS", "SAS", 121, 114,
                [
                    line("tatum", "BOS", 39, 8, 6, threes=5),
                    line("brown", "BOS", 26, 6, 4, threes=2),
                    line("wemby", "SAS", 33, 12, 4, threes=2),
                ],
            ),
            "G2": game(
                "G2", "SAS", "BOS", 105, 129,
                [
                    line("tatum", "BOS", 31, 7, 7, threes=4),
                    line("brown", "BOS", 24, 5, 3, threes=3),
                    line("wemby", "SAS", 29, 13, 5, threes=1),
                ],
            ),
        },
        postseason_state=SimpleNamespace(
            seed_by_team={"BOS": 1, "SAS": 2},
            completed_games={
                "P1": game(
                    "P1", "BOS", "SAS", 117, 115,
                    [
                        line("tatum", "BOS", 44, 10, 5, threes=6),
                        line("brown", "BOS", 22, 7, 4, threes=2),
                        line("wemby", "SAS", 40, 15, 3, threes=3),
                    ],
                    overtime=1,
                )
            },
        ),
        champion="BOS",
        runner_up="SAS",
        conference_champions={"East": "BOS", "West": "SAS"},
        postseason_games_completed=22,
    )

    archive_2027 = SimpleNamespace(
        season_label="2027-28",
        standings={
            "BOS": standing(54, 28, 9600, 9340),
            "NYK": standing(57, 25, 9700, 9290),
        },
        completed_games={
            "G3": game(
                "G3", "BOS", "NYK", 112, 118,
                [
                    line("tatum", "BOS", 28, 9, 5, threes=3),
                    line("brown", "BOS", 21, 4, 4, threes=2),
                ],
            )
        },
        postseason_state=SimpleNamespace(seed_by_team={"BOS": 3, "NYK": 2}, completed_games={}),
        champion="NYK",
        runner_up="DEN",
        conference_champions={"East": "NYK", "West": "DEN"},
        postseason_games_completed=18,
    )

    state.season_history = [archive_2026, archive_2027]
    state.franchise_draft_history_v1 = [
        {
            "draft_year": 2028,
            "source_season": "2027-28",
            "target_season": "2028-29",
            "draft_order": [
                {
                    "overall_pick": 22,
                    "round": 1,
                    "round_pick": 22,
                    "owner_team": "BOS",
                    "prospect_id": "rookie",
                    "player_name": "Niko Jovanovic",
                }
            ],
            "prospects": [
                {
                    "prospect_id": "rookie",
                    "player_name": "Niko Jovanovic",
                    "position": "SG",
                    "school": "Duke",
                    "archetype": "Shot-Making Wing",
                }
            ],
        }
    ]

    trade_state = SimpleNamespace(
        transaction_history=[
            SimpleNamespace(
                transaction_id="TXN-0001",
                state_revision=1,
                trade_date="2028-02-07",
                team_a="BOS",
                team_b="PHX",
                team_a_player_ids=("brown",),
                team_b_player_ids=("rookie",),
                team_a_pick_right_ids=(),
                team_b_pick_right_ids=("2030-PHX-R1",),
                evaluation_status="PASS",
            )
        ]
    )

    return SimpleNamespace(
        simulation_state=state,
        trade_state=trade_state,
        preferences={"franchise_pref_active_team": "BOS"},
    )


def validate_synthetic_foundation(results: dict[str, bool]) -> None:
    payload = build_franchise_legacy_payload(
        synthetic_checkpoint(),
        team_names={
            "BOS": "Boston Celtics",
            "SAS": "San Antonio Spurs",
            "NYK": "New York Knicks",
            "DEN": "Denver Nuggets",
            "PHX": "Phoenix Suns",
        },
    )

    results["synthetic_identity"] = payload["team"] == "BOS" and payload["team_name"] == "Boston Celtics"
    results["synthetic_trophy_room"] = payload["trophy_room"]["championships"] == 1
    results["synthetic_season_timeline"] = len(payload["season_timeline"]) == 3 and any(row["is_current"] for row in payload["season_timeline"])
    results["synthetic_record_book"] = (
        payload["records"]["best_season"]["season"] == "2026-27"
        and payload["records"]["career_points"]["name"] == "Jayson Tatum"
        and payload["records"]["single_game"]["points"]["value"] == 44
    )
    results["synthetic_legends"] = bool(payload["legends"]) and payload["legends"][0]["name"] == "Jayson Tatum"
    results["synthetic_greatest_games"] = bool(payload["greatest_games"]) and any(row["is_playoff"] for row in payload["greatest_games"])
    results["synthetic_draft_archive"] = len(payload["draft_history"]) == 1 and payload["draft_history"][0]["name"] == "Niko Jovanovic"
    results["synthetic_trade_archive"] = len(payload["trade_history"]) == 1 and payload["trade_history"][0]["partner"] == "PHX"
    results["synthetic_event_ledger"] = (
        any(row["event_type"] == "CHAMPIONSHIP" for row in payload["event_ledger"])
        and any(row["event_type"] == "DRAFT" for row in payload["event_ledger"])
        and any(row["event_type"] == "TRADE" for row in payload["event_ledger"])
    )
    results["synthetic_rivalry_history"] = bool(payload["rivalries"]) and payload["rivalries"][0]["opponent"] == "SAS"
    results["synthetic_league_history"] = len(payload["league_history"]) == 2 and payload["league_history"][1]["champion"] == "BOS"
    results["synthetic_gm_resume"] = (
        payload["tenure"]["gm_resume"]["completed_seasons"] == 2
        and payload["tenure"]["gm_resume"]["championships"] == 1
        and payload["tenure"]["gm_resume"]["draft_selections"] == 1
        and payload["tenure"]["gm_resume"]["trades_completed"] == 1
    )


def validate_real_checkpoint(results: dict[str, bool]) -> None:
    if not V3.exists():
        results["real_v3_checkpoint_found"] = False
        return

    before = save_hashes()
    checkpoint = load_franchise_checkpoint(path=V3, allow_backup=False)
    results["real_v3_checkpoint_found"] = checkpoint is not None
    if checkpoint is None:
        return

    payload = build_franchise_legacy_payload(checkpoint, team_names={})
    results["real_payload_read_only_contract"] = (
        payload.get("read_only") is True
        and payload.get("working_save_only") is True
        and payload.get("active_v2_read_only") is True
        and bool(payload.get("team"))
    )
    results["real_payload_sections"] = all(
        key in payload
        for key in [
            "tenure",
            "trophy_room",
            "season_timeline",
            "records",
            "legends",
            "greatest_games",
            "draft_history",
            "trade_history",
            "event_ledger",
            "rivalries",
            "league_history",
        ]
    )
    results["real_foundation_did_not_mutate_saves"] = save_hashes() == before


def validate_static_integration(results: dict[str, bool]) -> None:
    main_text = (ROOT / "godot_client/scripts/main.gd").read_text(encoding="utf-8")
    server_text = (ROOT / "desktop_bridge/server.py").read_text(encoding="utf-8")
    ui_text = (ROOT / "godot_client/scripts/franchise_legacy_center_v3.gd").read_text(encoding="utf-8")
    foundation_text = (ROOT / "desktop_bridge/franchise_legacy_foundation.py").read_text(encoding="utf-8")

    results["server_endpoint_integration"] = all(
        token in server_text
        for token in [
            "build_franchise_legacy_payload",
            "async def franchise_legacy",
            'Route("/v3/franchise-legacy", franchise_legacy, methods=["GET"])',
            "read_only_franchise_legacy_changed_checkpoint",
        ]
    )
    results["main_navigation_integration"] = all(
        token in main_text
        for token in [
            "FranchiseLegacyCenterV3",
            "var legacy_page: Control",
            'column.add_child(_nav_button("LEGACY"))',
            '"LEGACY":',
            'elif page_name == "LEGACY":',
            'legacy_page.call("refresh")',
        ]
    )
    results["legacy_nav_button_click_wired"] = (
        '\t\t"LEAGUE",\n\t\t"LEGACY",\n\t\t"FRONT OFFICE",' in main_text
        and 'button.pressed.connect(_show_page.bind(text_value))' in main_text
    )
    results["legacy_ui_major_sections"] = all(
        token in ui_text
        for token in [
            "LegacyHero",
            "LegacyTrophyRoom",
            "LegacySeasonTimeline",
            "LegacyRecordBook",
            "LegacyLegends",
            "LegacyGreatestGames",
            "LegacyRivalries",
            "LegacyDraftHistory",
            "LegacyTransactionHistory",
            "LegacyEventLedger",
            "LegacyLeagueHistory",
            "THE NEXT CHAPTER STARTS HERE",
            "LegacyBannerEmptyState",
            "FIRST SEASON",
            "TextServer.AUTOWRAP_OFF",
        ]
    )
    results["legacy_endpoint_is_read_only"] = "save_franchise_checkpoint" not in foundation_text and "commit_" not in foundation_text
    results["legacy_ui_no_write_route"] = (
        "HTTPClient.METHOD_POST" not in ui_text
        and "HTTPClient.METHOD_PUT" not in ui_text
        and "HTTPClient.METHOD_DELETE" not in ui_text
    )


def validate_python_compile(results: dict[str, bool]) -> None:
    try:
        for target in [
            ROOT / "desktop_bridge/franchise_legacy_foundation.py",
            ROOT / "desktop_bridge/server.py",
            ROOT / "src/validate_v3_expansion39_franchise_universe_legacy.py",
        ]:
            py_compile.compile(str(target), doraise=True)
        results["python_compile"] = True
    except Exception as exc:
        print(f"[FAIL] Python compile: {type(exc).__name__}: {exc}")
        results["python_compile"] = False


def validate_godot(results: dict[str, bool]) -> None:
    godot = Path(os.environ.get("USERPROFILE", "")) / "Downloads/Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console

    if not godot.is_file():
        print(f"[FAIL] Godot executable not found: {godot}")
        results["godot_expansion39_runtime"] = False
        return

    with tempfile.TemporaryDirectory(prefix="v3_exp39_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "smoke.gd"

        gdscript = r'''extends SceneTree

func fail_now(label: String) -> void:
    print("EXP39_FAIL::" + label)
    quit(2)


func all_text(node: Node) -> String:
    var output = ""
    if node is Label:
        output += str(node.text) + "\n"
    for child in node.get_children():
        output += all_text(child)
    return output


func fixture() -> Dictionary:
    return {
        "foundation_version": "fixture",
        "team": "BOS",
        "team_name": "Boston Celtics",
        "current_season": "2028-29",
        "tenure": {
            "era": {"label": "CHAMPIONSHIP ERA", "description": "Fixture era description."},
            "gm_resume": {
                "completed_seasons": 2,
                "career_record": "115-49",
                "career_wins": 115,
                "championships": 1,
                "finals_appearances": 1,
                "playoff_appearances": 2,
                "draft_selections": 1
            }
        },
        "trophy_room": {
            "championships": 1,
            "championship_seasons": ["2026-27"],
            "finals_appearances": 1,
            "finals_seasons": ["2026-27"],
            "conference_titles": 1,
            "conference_title_seasons": ["2026-27"],
            "playoff_appearances": 2,
            "playoff_seasons": ["2026-27", "2027-28"]
        },
        "season_timeline": [
            {"season": "2028-29", "record": "12-5", "point_diff": 120, "result": "IN PROGRESS", "is_current": true},
            {"season": "2026-27", "record": "61-21", "point_diff": 600, "result": "NBA CHAMPION", "is_current": false}
        ],
        "records": {
            "best_season": {"season": "2026-27", "record": "61-21", "result": "NBA CHAMPION"},
            "largest_win": {"margin": 24, "opponent": "SAS", "season": "2026-27"},
            "highest_team_score": {"team_score": 129, "opponent": "SAS", "season": "2026-27"},
            "career_points": {"name": "Jayson Tatum", "value": 177, "games": 5},
            "career_rebounds": {"name": "Jayson Tatum", "value": 42},
            "career_assists": {"name": "Jayson Tatum", "value": 31},
            "career_threes": {"name": "Jayson Tatum", "value": 23},
            "single_game": {"points": {"name": "Jayson Tatum", "value": 44, "season": "2026-27", "opponent": "SAS"}}
        },
        "legends": [],
        "greatest_games": [
            {
                "season": "2026-27",
                "opponent": "SAS",
                "team_score": 117,
                "opponent_score": 115,
                "result": "W",
                "is_playoff": true,
                "overtime_periods": 1,
                "top_player": "Jayson Tatum",
                "top_points": 44
            }
        ],
        "rivalries": [
            {"opponent": "SAS", "tier": "RIVAL", "wins": 3, "losses": 0, "games": 3, "playoff_games": 1, "finals_meetings": 1}
        ],
        "draft_history": [
            {
                "draft_year": 2028,
                "overall_pick": 22,
                "round": 1,
                "name": "Niko Jovanovic",
                "position": "SG",
                "school": "Duke",
                "archetype": "Shot-Making Wing",
                "current_team": "BOS",
                "current_overall": 82,
                "still_in_league": true
            }
        ],
        "trade_history": [
            {
                "partner": "PHX",
                "transaction_id": "TXN-0001",
                "incoming_players": ["Niko Jovanovic"],
                "incoming_picks": ["2030 PHX 1st"],
                "outgoing_players": ["Jaylen Brown"],
                "outgoing_picks": []
            }
        ],
        "event_ledger": [
            {"season": "2026-27", "event_type": "CHAMPIONSHIP", "title": "NBA Championship", "detail": "Boston won the NBA championship."}
        ],
        "league_history": [
            {"season": "2026-27", "champion": "BOS", "runner_up": "SAS"}
        ],
        "empty_state": {
            "has_completed_history": true,
            "headline": "THE FRANCHISE HAS A HISTORY",
            "detail": "History exists."
        }
    }


func _initialize() -> void:
    var legacy_script = load("res://scripts/franchise_legacy_center_v3.gd")
    if legacy_script == null:
        fail_now("legacy_script_load")
        return

    var main_script = load("res://scripts/main.gd")
    if main_script == null:
        fail_now("main_script_load")
        return

    var center = legacy_script.new()
    if center == null:
        fail_now("legacy_construct")
        return

    center.configure(fixture())

    for node_name in [
        "LegacyHero",
        "LegacyTrophyRoom",
        "LegacySeasonTimeline",
        "LegacyRecordBook",
        "LegacyLegends",
        "LegacyGreatestGames",
        "LegacyRivalries",
        "LegacyDraftHistory",
        "LegacyTransactionHistory",
        "LegacyEventLedger",
        "LegacyLeagueHistory"
    ]:
        if center.find_child(node_name, true, false) == null:
            center.free()
            fail_now("missing_" + node_name)
            return

    var text = all_text(center)
    for required in [
        "FRANCHISE LEGACY",
        "THE TROPHY ROOM",
        "YOUR FRANCHISE THROUGH THE YEARS",
        "FRANCHISE RECORD BOOK",
        "FRANCHISE LEGENDS",
        "GREATEST GAMES",
        "RIVALRY HISTORY",
        "DRAFT HISTORY",
        "FRONT OFFICE TRANSACTION ARCHIVE",
        "FRANCHISE STORY ARCHIVE",
        "LEAGUE HISTORY"
    ]:
        if text.find(required) < 0:
            center.free()
            fail_now("missing_text_" + required)
            return

    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({
        "legacy_component_constructed": true,
        "legacy_major_sections_present": true,
        "legacy_main_script_parse_loaded": true
    }))
    output.close()
    center.free()
    print("EXP39_COMPLETE")
    quit(0)
'''
        gdscript = gdscript.replace("MARKER_PATH", json.dumps(marker.as_posix()))
        script.write_text(gdscript, encoding="utf-8")

        try:
            proc = subprocess.run(
                [str(godot), "--headless", "--path", "godot_client", "--script", str(script)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
            if combined.strip():
                print(combined[-16000:])

            results["godot_expansion39_runtime"] = (
                proc.returncode == 0
                and marker.exists()
                and "EXP39_COMPLETE" in combined
                and "EXP39_FAIL::" not in combined
                and "parse error" not in combined.lower()
                and "parser error" not in combined.lower()
            )
            if marker.exists():
                results.update(json.loads(marker.read_text(encoding="utf-8")))
        except subprocess.TimeoutExpired as exc:
            print("[FAIL] Expansion 39 Godot smoke timed out.")
            if exc.stdout:
                print(str(exc.stdout)[-6000:])
            if exc.stderr:
                print(str(exc.stderr)[-6000:])
            results["godot_expansion39_runtime"] = False


def main() -> int:
    before = save_hashes()
    results: dict[str, bool] = {}

    print("=" * 108)
    print("V3 EXPANSION 39 — FRANCHISE UNIVERSE + LEGACY VALIDATION")
    print("=" * 108)
    print(f"Foundation: {FRANCHISE_LEGACY_FOUNDATION_VERSION}")

    validate_python_compile(results)
    validate_static_integration(results)
    validate_synthetic_foundation(results)
    validate_real_checkpoint(results)
    validate_godot(results)

    results["active_v3_and_protected_v2_unchanged"] = save_hashes() == before

    out = ROOT / "outputs/v3_expansion39_franchise_universe_legacy"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(
        json.dumps(
            {
                "version": VERSION,
                "foundation_version": FRANCHISE_LEGACY_FOUNDATION_VERSION,
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    for key, passed in results.items():
        print(f"{key}: {'PASS' if passed else 'FAIL'}")

    passed = all(results.values())
    print()
    print("V3 EXPANSION 39 FRANCHISE UNIVERSE + LEGACY " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
