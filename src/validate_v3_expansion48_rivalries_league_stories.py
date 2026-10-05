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

from desktop_bridge.rivalry_story_foundation import (
    RIVALRY_STORY_FOUNDATION_VERSION,
    build_rivalry_story_universe,
)
from simulation_franchise_checkpoint_v1 import (
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)

V3 = ROOT / "outputs/runtime/v3_godot_working_checkpoint.pkl.gz"
V2 = Path(DEFAULT_CHECKPOINT_PATH)
VERSION = "v3-expansion48-rivalries-league-stories-v1.0.0-2026-10-05"


def digest(path: Path) -> str:
    if not path.exists():
        return "missing"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_hashes() -> dict[str, str]:
    return {"v3": digest(V3), "v2": digest(V2)}


def standing(wins: int, losses: int, streak_type: str = "", streak_length: int = 0) -> Any:
    return SimpleNamespace(
        wins=wins,
        losses=losses,
        games_played=wins + losses,
        points_for=1200,
        points_against=1100,
        streak_type=streak_type,
        streak_length=streak_length,
    )


def player(name: str, team: str, overall: float, position: str = "SG", age: float = 25.0) -> Any:
    return SimpleNamespace(
        player_name=name,
        team_abbreviation=team,
        overall_rating=overall,
        position=position,
        age=age,
    )


def totals(games: int, points: int, rebounds: int, assists: int) -> Any:
    return SimpleNamespace(
        games_played=games,
        points=points,
        rebounds=rebounds,
        assists=assists,
    )


def completed_game(
    game_id: str,
    home: str,
    away: str,
    home_score: int,
    away_score: int,
    *,
    overtime: int = 0,
) -> Any:
    return SimpleNamespace(
        game_id=game_id,
        home_team=home,
        away_team=away,
        home_score=home_score,
        away_score=away_score,
        overtime_periods=overtime,
    )


def scheduled_game(game_id: str, day: int, home: str, away: str, status: str = "scheduled") -> Any:
    return SimpleNamespace(
        game_id=game_id,
        day_index=day,
        home_team=home,
        away_team=away,
        status=status,
    )


def synthetic_checkpoint() -> Any:
    postseason_games = {
        "P1": completed_game("P1", "BOS", "LAL", 108, 104),
        "P2": completed_game("P2", "LAL", "BOS", 111, 105),
        "P3": completed_game("P3", "BOS", "LAL", 119, 116, overtime=1),
        "P4": completed_game("P4", "LAL", "BOS", 101, 98),
        "P5": completed_game("P5", "BOS", "LAL", 110, 112),
        "P6": completed_game("P6", "LAL", "BOS", 103, 106),
        "P7": completed_game("P7", "BOS", "LAL", 115, 109),
    }
    archive = SimpleNamespace(
        season_label="2026-27",
        completed_games={
            "R1": completed_game("R1", "BOS", "LAL", 121, 118),
            "R2": completed_game("R2", "LAL", "BOS", 114, 109),
        },
        postseason_state=SimpleNamespace(completed_games=postseason_games),
        champion="BOS",
        runner_up="LAL",
    )

    players = {
        "bos_star": player("Boston Star", "BOS", 94.0, "SF"),
        "bos_2": player("Boston Guard", "BOS", 86.0, "PG"),
        "lal_star": player("Los Angeles Star", "LAL", 95.0, "PF"),
        "former1": player("Former Celtic", "LAL", 82.0, "SG"),
        "nyk_star": player("New York Star", "NYK", 92.0, "PG"),
        "mil_star": player("Milwaukee Star", "MIL", 91.0, "PF"),
    }
    teams = {
        "BOS": SimpleNamespace(roster_player_ids=("bos_star", "bos_2")),
        "LAL": SimpleNamespace(roster_player_ids=("lal_star", "former1")),
        "NYK": SimpleNamespace(roster_player_ids=("nyk_star",)),
        "MIL": SimpleNamespace(roster_player_ids=("mil_star",)),
    }
    schedule = {
        "G_NEXT": scheduled_game("G_NEXT", 3, "BOS", "LAL"),
        "G_WIRE": scheduled_game("G_WIRE", 4, "NYK", "MIL"),
    }

    state = SimpleNamespace(
        settings=SimpleNamespace(season_label="2027-28"),
        current_day_index=0,
        phase="regular_season",
        season_history=[archive],
        completed_games={},
        postseason_state=None,
        schedule=schedule,
        standings={
            "BOS": standing(9, 3, "W", 4),
            "LAL": standing(8, 4, "W", 5),
            "NYK": standing(8, 4, "W", 6),
            "MIL": standing(9, 3, "W", 3),
        },
        players=players,
        teams=teams,
        player_season_totals={
            "bos_star": totals(12, 360, 96, 72),
            "lal_star": totals(12, 372, 120, 60),
            "nyk_star": totals(12, 330, 60, 96),
            "mil_star": totals(12, 324, 132, 48),
        },
        franchise_transaction_history_v1=[
            {
                "status": "committed",
                "team_a": "BOS",
                "team_b": "LAL",
                "side_a_player_ids": ["former1"],
                "side_b_player_ids": [],
            }
        ],
    )

    trade_state = SimpleNamespace(transaction_history=[])
    return SimpleNamespace(
        simulation_state=state,
        trade_state=trade_state,
        preferences={"franchise_pref_active_team": "BOS"},
    )


def validate_synthetic(results: dict[str, bool]) -> None:
    payload = build_rivalry_story_universe(
        synthetic_checkpoint(),
        "BOS",
        {
            "BOS": "Boston Celtics",
            "LAL": "Los Angeles Lakers",
            "NYK": "New York Knicks",
            "MIL": "Milwaukee Bucks",
        },
    )

    results["synthetic_read_only_identity"] = (
        payload["read_only"] is True
        and payload["working_save_write_performed"] is False
        and payload["active_v2_read_only"] is True
        and payload["team"] == "BOS"
    )

    profiles = payload["rivalries"]
    lal = next(row for row in profiles if row["opponent"] == "LAL")
    results["synthetic_persistent_rivalry_profile"] = (
        lal["games"] == 9
        and lal["wins"] == 5
        and lal["losses"] == 4
        and lal["playoff_games"] == 7
        and lal["playoff_meetings"] == 1
        and lal["finals_meetings"] == 1
        and lal["eliminations_for"] == 1
        and lal["tier"] in {"MAJOR", "HISTORIC"}
    )
    results["synthetic_playoff_series_evidence"] = (
        lal["series_history"][0]["record"] == "4-3"
        and lal["series_history"][0]["winner"] == "BOS"
        and lal["series_history"][0]["complete_best_of_seven"] is True
    )
    results["synthetic_featured_finals_rematch"] = (
        payload["featured_matchup"]["opponent"] == "LAL"
        and payload["featured_matchup"]["category"] == "FINALS REMATCH"
        and payload["featured_matchup"]["day"] == 3
    )
    results["synthetic_star_matchup"] = (
        payload["featured_matchup"]["star_matchup"]["available"] is True
        and payload["featured_matchup"]["star_matchup"]["active"]["name"] == "Boston Star"
        and payload["featured_matchup"]["star_matchup"]["opponent"]["name"] == "Los Angeles Star"
    )
    results["synthetic_former_player_return"] = (
        len(payload["former_player_returns"]) == 1
        and payload["former_player_returns"][0]["name"] == "Former Celtic"
        and payload["former_player_returns"][0]["opponent"] == "LAL"
    )
    results["synthetic_story_feed"] = any(
        row["category"] == "RETURN GAME"
        for row in payload["active_stories"]
    ) and any(
        row["category"] == "STAR MATCHUP"
        for row in payload["active_stories"]
    )
    results["synthetic_league_story_wire"] = any(
        row["home_team"] == "NYK" and row["away_team"] == "MIL"
        for row in payload["league_story_wire"]
    )
    results["synthetic_pulse_handoff"] = (
        bool(payload["pulse_cards"])
        and all(row["destination"] == "STORIES" for row in payload["pulse_cards"])
    )
    results["synthetic_scope_truthful"] = (
        payload["scope"]["evidence_only"] is True
        and "No historical NBA rivalry is assumed" in payload["scope"]["note"]
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

    team = str(
        dict(getattr(checkpoint, "preferences", {}) or {}).get(
            "franchise_pref_active_team", ""
        )
    ).upper()
    payload = build_rivalry_story_universe(checkpoint, team, {})

    results["real_payload_major_sections"] = all(
        key in payload
        for key in [
            "featured_matchup",
            "rivalries",
            "active_stories",
            "former_player_returns",
            "league_story_wire",
            "pulse_cards",
            "archive",
            "scope",
        ]
    )
    results["real_payload_read_only_contract"] = (
        payload["read_only"] is True
        and payload["working_save_write_performed"] is False
        and payload["active_v2_read_only"] is True
    )
    results["real_foundation_did_not_mutate_saves"] = save_hashes() == before


def validate_static(results: dict[str, bool]) -> None:
    foundation = (
        ROOT / "desktop_bridge/rivalry_story_foundation.py"
    ).read_text(encoding="utf-8")
    server = (
        ROOT / "desktop_bridge/server.py"
    ).read_text(encoding="utf-8")
    main = (
        ROOT / "godot_client/scripts/main.gd"
    ).read_text(encoding="utf-8")
    page = (
        ROOT / "godot_client/scripts/rivalry_story_center_v3.gd"
    ).read_text(encoding="utf-8")
    pulse = (
        ROOT / "desktop_bridge/franchise_pulse.py"
    ).read_text(encoding="utf-8")
    pulse_ui = (
        ROOT / "godot_client/scripts/franchise_pulse_v3.gd"
    ).read_text(encoding="utf-8")

    results["server_read_only_story_endpoint"] = all(
        token in server
        for token in [
            "build_rivalry_story_universe",
            "async def rivalry_stories",
            'Route("/v3/rivalry-stories", rivalry_stories, methods=["GET"])',
            "rivalry_stories_checkpoint_changed",
        ]
    )
    results["story_foundation_has_no_write_path"] = all(
        token not in foundation
        for token in [
            "save_franchise_checkpoint",
            "os.replace",
            "METHOD_POST",
            "force_replace",
        ]
    )
    results["main_story_navigation_integration"] = all(
        token in main
        for token in [
            "RivalryStoryCenterV3",
            "var stories_page: Control",
            '"STORIES":',
            'elif page_name == "STORIES":',
            "stories_page.refresh()",
        ]
    )
    results["story_ui_major_sections"] = all(
        token in page
        for token in [
            "RivalryStoryHeroCard",
            "RivalryFeaturedMatchup",
            "RivalryHeatBoard",
            "RivalryDossier",
            "RivalryActiveStoryFeed",
            "RivalryReturnGames",
            "RivalryLeagueStoryWire",
            "RivalryStoryScope",
            "RivalryStoryBottomSafeArea",
        ]
    )
    results["story_visual_node_lifecycle_contract"] = (
        "EXP48_1_NODE_LIFECYCLE" in page
        and page.find("body.add_child(portrait)\n\tportrait.configure") >= 0
        and page.find("body.add_child(portrait)\n\t\tportrait.configure") >= 0
    )
    results["pulse_story_handoff_integration"] = (
        "build_rivalry_story_universe" in pulse
        and '"STORIES"' in pulse_ui
        and 'destination == "STORIES"' in pulse_ui
    )
    results["existing_write_boundaries_preserved"] = all(
        token in server
        for token in [
            'Route("/v3/locker-room", locker_room, methods=["GET", "POST"])',
            'Route("/v3/development-goals", development_goals, methods=["GET", "POST"])',
            'Route("/v3/free-agency/execute", free_agency_execute, methods=["POST"])',
            'Route("/v3/trade/execute", trade_execute, methods=["POST"])',
        ]
    )
    from desktop_bridge.server import API_VERSION
    results["api_version_at_least_025"] = tuple(map(int, API_VERSION.split("."))) >= (0, 25, 0)


def validate_python_compile(results: dict[str, bool]) -> None:
    try:
        for target in [
            ROOT / "desktop_bridge/rivalry_story_foundation.py",
            ROOT / "desktop_bridge/franchise_pulse.py",
            ROOT / "desktop_bridge/server.py",
            ROOT / "src/validate_v3_expansion48_rivalries_league_stories.py",
        ]:
            py_compile.compile(str(target), doraise=True)
        results["python_compile"] = True
    except Exception as exc:
        print(f"[FAIL] Python compile: {type(exc).__name__}: {exc}")
        results["python_compile"] = False


def validate_godot(results: dict[str, bool]) -> None:
    godot = (
        Path(os.environ.get("USERPROFILE", ""))
        / "Downloads/Godot_v4.0-stable_win64.exe"
    )
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console
    if not godot.is_file():
        print(f"[FAIL] Godot executable not found: {godot}")
        results["godot_expansion48_runtime"] = False
        return

    with tempfile.TemporaryDirectory(prefix="v3_exp48_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "smoke.gd"

        gdscript = r'''extends SceneTree

func fail_now(label: String) -> void:
    print("EXP48_FAIL::" + label)
    quit(2)


func all_text(node: Node) -> String:
    var output = ""
    if node is Label:
        output += str(node.text) + "\n"
    if node is Button:
        output += str(node.text) + "\n"
    for child in node.get_children():
        output += all_text(child)
    return output


func fixture() -> Dictionary:
    return {
        "foundation_version":"fixture",
        "read_only":true,
        "working_save_write_performed":false,
        "active_v2_read_only":true,
        "team":"BOS",
        "team_name":"Boston Celtics",
        "season":"2027-28",
        "phase":"regular_season",
        "day":12,
        "archive":{"completed_game_count":25,"season_history_count":1,"upcoming_game_count":8},
        "featured_matchup":{
            "game_id":"g1","day":15,"days_away":3,
            "home_team":"BOS","home_name":"Boston Celtics",
            "away_team":"LAL","away_name":"Los Angeles Lakers",
            "opponent":"LAL","opponent_name":"Los Angeles Lakers",
            "is_home":true,"headline":"FINALS REMATCH • Los Angeles Lakers","category":"FINALS REMATCH",
            "reasons":["1 saved V3 Finals meeting(s)"],
            "rivalry":{"tier":"MAJOR","heat_score":55.0},
            "star_matchup":{
                "available":true,
                "active":{"player_id":"p1","name":"Boston Star","position":"SF","overall":94.0,"ppg":28.4,"rpg":8.2,"apg":5.9},
                "opponent":{"player_id":"p2","name":"Los Angeles Star","position":"PF","overall":95.0,"ppg":29.1,"rpg":9.4,"apg":4.8}
            },
            "former_player_returns":[]
        },
        "rivalries":[{
            "opponent":"LAL","opponent_name":"Los Angeles Lakers","games":9,"wins":5,"losses":4,"record":"5-4",
            "playoff_games":7,"playoff_meetings":1,"finals_meetings":1,"overtime_games":1,"close_games":5,
            "eliminations_for":1,"eliminations_against":0,"heat_score":55.0,"tier":"MAJOR",
            "latest":{"season":"2026-27","result":"W","team_score":115,"opponent_score":109},
            "next_meeting":{"day":15},"head_to_head_streak":{"result":"W","count":1},
            "series_history":[{"season":"2026-27","record":"4-3","winner":"BOS","complete_best_of_seven":true}],
            "timeline":[
                {"season":"2026-27","day":null,"game_id":"P7","result":"W","team_score":115,"opponent_score":109,"margin":6,"is_playoff":true,"overtime_periods":0}
            ],
            "narrative":"Boston Celtics leads the saved V3 series 5-4."
        }],
        "active_stories":[
            {"category":"STAR MATCHUP","title":"Boston Star vs Los Angeles Star","detail":"Current roster leaders.","destination":"STORIES","evidence":"Current roster ratings","priority":2},
            {"category":"RIVALRY","title":"MAJOR • Los Angeles Lakers","detail":"Saved V3 head-to-head 5-4.","destination":"STORIES","evidence":"Saved franchise matchup history","priority":1}
        ],
        "former_player_returns":[
            {"player_id":"p3","name":"Former Celtic","opponent":"LAL","opponent_name":"Los Angeles Lakers","day":15,"days_away":3,"overall":82.0,"position":"SG"}
        ],
        "league_story_wire":[
            {"title":"Milwaukee Bucks at New York Knicks","detail":"Contender clash","day":16,"days_away":4,"home_team":"NYK","away_team":"MIL"}
        ],
        "pulse_cards":[],
        "scope":{
            "evidence_only":true,
            "note":"No historical NBA rivalry is assumed when the V3 universe has not recorded it.",
            "series_note":"A playoff elimination is only credited when one side has at least four saved wins."
        }
    }


func _initialize() -> void:
    var page_script = load("res://scripts/rivalry_story_center_v3.gd")
    if page_script == null:
        fail_now("story_page_script_load")
        return

    var main_script = load("res://scripts/main.gd")
    if main_script == null:
        fail_now("main_script_load")
        return

    var page = page_script.new()
    page.call("_ready")
    page.configure(fixture())

    for node_name in [
        "RivalryStoryScroll",
        "RivalryStoryHeroCard",
        "RivalryFeaturedMatchup",
        "RivalryMatchupPoster",
        "RivalryHeatBoard",
        "RivalryDossier",
        "RivalryActiveStoryFeed",
        "RivalryReturnGames",
        "RivalryLeagueStoryWire",
        "RivalryStoryScope",
        "RivalryStoryBottomSafeArea"
    ]:
        if page.find_child(node_name, true, false) == null:
            page.free()
            fail_now("missing_" + node_name)
            return

    var text = all_text(page)
    for required in [
        "RIVALRIES + LEAGUE STORIES",
        "FINALS REMATCH",
        "RIVALRY HEAT BOARD",
        "RIVALRY DOSSIER",
        "POSTSEASON CHAPTERS",
        "RIVALRY TIMELINE",
        "FORMER PLAYER RETURN WATCH",
        "LEAGUE STORY WIRE",
        "NO FABRICATED HISTORY"
    ]:
        if text.find(required) < 0:
            page.free()
            fail_now("missing_text_" + required)
            return

    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({
        "story_page_constructed":true,
        "featured_matchup_runtime":true,
        "rivalry_dossier_runtime":true,
        "return_watch_runtime":true,
        "league_wire_runtime":true,
        "main_script_loaded":true
    }))
    output.close()

    page.free()
    print("EXP48_COMPLETE")
    quit(0)
'''
        gdscript = gdscript.replace("MARKER_PATH", json.dumps(marker.as_posix()))
        script.write_text(gdscript, encoding="utf-8")

        try:
            proc = subprocess.run(
                [
                    str(godot),
                    "--headless",
                    "--path",
                    "godot_client",
                    "--script",
                    str(script),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=40,
            )
            combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
            if combined.strip():
                print(combined[-16000:])
            results["godot_expansion48_runtime"] = (
                proc.returncode == 0
                and marker.exists()
                and "EXP48_COMPLETE" in combined
                and "EXP48_FAIL::" not in combined
                and "parse error" not in combined.lower()
                and "parser error" not in combined.lower()
                and "!is_inside_tree()" not in combined
                and "ERR_UNCONFIGURED" not in combined
            )
            if marker.exists():
                results.update(json.loads(marker.read_text(encoding="utf-8")))
        except subprocess.TimeoutExpired as exc:
            print("[FAIL] Expansion 48 Godot smoke timed out.")
            if exc.stdout:
                print(str(exc.stdout)[-6000:])
            if exc.stderr:
                print(str(exc.stderr)[-6000:])
            results["godot_expansion48_runtime"] = False


def main() -> int:
    before = save_hashes()
    results: dict[str, bool] = {}

    print("=" * 112)
    print("V3 EXPANSION 48 — RIVALRIES + LEAGUE STORIES VALIDATION")
    print("=" * 112)
    print(f"Foundation: {RIVALRY_STORY_FOUNDATION_VERSION}")

    validate_python_compile(results)
    validate_static(results)
    validate_synthetic(results)
    validate_real_checkpoint(results)
    validate_godot(results)

    results["active_v3_and_protected_v2_unchanged"] = save_hashes() == before

    out = ROOT / "outputs/v3_expansion48_rivalries_league_stories"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(
        json.dumps(
            {
                "version": VERSION,
                "foundation_version": RIVALRY_STORY_FOUNDATION_VERSION,
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
    print(
        "V3 EXPANSION 48 RIVALRIES + LEAGUE STORIES "
        + ("PASSED" if passed else "FAILED")
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
