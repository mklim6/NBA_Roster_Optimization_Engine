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

from desktop_bridge.offseason_command_foundation import (
    OFFSEASON_COMMAND_FOUNDATION_VERSION,
    _draft_watch,
    build_offseason_command_payload,
)
from simulation_franchise_checkpoint_v1 import (
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)

V3 = ROOT / "outputs/runtime/v3_godot_working_checkpoint.pkl.gz"
V2 = Path(DEFAULT_CHECKPOINT_PATH)
VERSION = "v3-expansion40-complete-offseason-v1.0.0-2026-10-04"


def digest(path: Path) -> str:
    if not path.exists():
        return "missing"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_hashes() -> dict[str, str]:
    return {"v3": digest(V3), "v2": digest(V2)}


def contract(
    salary: float,
    years: int,
    *,
    guaranteed: bool = True,
    two_way: bool = False,
) -> Any:
    return SimpleNamespace(
        salary=salary,
        years_remaining=years,
        guaranteed=guaranteed,
        option_type="",
        contract_type="two_way" if two_way else "standard",
        two_way=two_way,
    )


def player(
    name: str,
    team: str,
    position: str,
    age: float,
    overall: float,
    potential: float,
    salary: float,
    years: int,
    *,
    guaranteed: bool = True,
    two_way: bool = False,
) -> Any:
    return SimpleNamespace(
        player_name=name,
        team_abbreviation=team,
        position=position,
        age=age,
        overall_rating=overall,
        potential_rating=potential,
        future_outlook_rating=max(overall, potential - 1.0),
        development_direction="Improving" if age <= 24 else "Stable",
        contract=contract(
            salary,
            years,
            guaranteed=guaranteed,
            two_way=two_way,
        ),
    )


def standing(wins: int, losses: int) -> Any:
    return SimpleNamespace(
        wins=wins,
        losses=losses,
        games_played=wins + losses,
        points_for=9400,
        points_against=9150,
    )


def synthetic_checkpoint() -> Any:
    players: dict[str, Any] = {
        "p1": player("Jayson Tatum", "BOS", "SF/PF", 28, 95, 96, 55_000_000, 4),
        "p2": player("Jaylen Brown", "BOS", "SG/SF", 29, 91, 92, 52_000_000, 3),
        "p3": player("Young Guard", "BOS", "PG", 21, 77, 88, 6_000_000, 3),
        "p4": player("Young Wing", "BOS", "SG", 22, 75, 86, 4_500_000, 2),
        "p5": player("Young Forward", "BOS", "PF", 23, 74, 84, 3_800_000, 2),
        "p6": player("Starting Center", "BOS", "C", 27, 84, 85, 21_000_000, 2),
        "p7": player("Backup Point", "BOS", "PG", 26, 78, 79, 9_000_000, 1),
        "p8": player("Backup Wing", "BOS", "SF", 25, 76, 78, 7_000_000, 1),
        "p9": player("Backup Big", "BOS", "C", 30, 75, 75, 5_000_000, 1),
        "p10": player("Stretch Four", "BOS", "PF", 27, 73, 74, 4_000_000, 1),
        "p11": player("Bench Guard", "BOS", "SG", 29, 71, 71, 3_000_000, 1),
        "p12": player("Bubble Wing", "BOS", "SF", 31, 68, 68, 2_000_000, 1, guaranteed=False),
        "p13": player("Depth Center", "BOS", "C", 28, 70, 70, 2_200_000, 1),
        "p14": player("Two Way Guard", "BOS", "PG", 20, 67, 81, 600_000, 1, two_way=True),
        "fa1": player("Market Star", "", "PG", 27, 88, 89, 0, 0),
        "fa2": player("Market Wing", "", "SF", 25, 82, 84, 0, 0),
        "fa3": player("Market Big", "", "C", 29, 79, 80, 0, 0),
    }

    roster_ids = tuple(f"p{i}" for i in range(1, 15))
    team_state = SimpleNamespace(
        roster_player_ids=roster_ids,
        rotation=SimpleNamespace(
            rotation_player_ids=tuple(f"p{i}" for i in range(1, 10)),
            starter_ids=("p1", "p2", "p3", "p5", "p6"),
            minutes_targets={
                "p1": 36.0,
                "p2": 35.0,
                "p3": 31.0,
                "p4": 24.0,
                "p5": 30.0,
                "p6": 31.0,
                "p7": 20.0,
                "p8": 18.0,
                "p9": 15.0,
            },
        ),
    )

    archive = SimpleNamespace(
        season_label="2026-27",
        standings={"BOS": standing(58, 24), "OKC": standing(61, 21)},
        champion="OKC",
        runner_up="BOS",
        conference_champions={"East": "BOS", "West": "OKC"},
        postseason_state=SimpleNamespace(seed_by_team={"BOS": 2, "OKC": 1}),
    )

    state = SimpleNamespace(
        settings=SimpleNamespace(season_label="2027-28"),
        phase="offseason",
        current_day_index=0,
        teams={"BOS": team_state},
        players=players,
        free_agent_player_ids=("fa1", "fa2", "fa3"),
        standings={"BOS": standing(0, 0)},
        season_history=[archive],
        schedule={},
        postseason_state=None,
    )

    return SimpleNamespace(
        simulation_state=state,
        trade_state=SimpleNamespace(),
        preferences={
            "franchise_pref_active_team": "BOS",
            "franchise_pref_controlled_teams": ("BOS",),
        },
    )


def validate_synthetic(results: dict[str, bool]) -> None:
    payload = build_offseason_command_payload(
        synthetic_checkpoint(),
        team_names={"BOS": "Boston Celtics", "OKC": "Oklahoma City Thunder"},
    )

    roster = payload["roster"]
    camp = payload["camp_readiness"]
    roadmap = payload["roadmap"]

    results["synthetic_identity"] = (
        payload["team"] == "BOS"
        and payload["team_name"] == "Boston Celtics"
        and payload["season"]["phase"] == "offseason"
    )
    results["synthetic_roster_construction"] = (
        roster["roster_count"] == 14
        and roster["standard_count"] == 13
        and roster["two_way_count"] == 1
        and roster["open_standard_slots"] == 2
        and roster["open_two_way_slots"] == 2
    )
    results["synthetic_young_core"] = (
        len(payload["young_core"]) >= 3
        and payload["young_core"][0]["age"] <= 24
        and "development_priority_score" in payload["young_core"][0]
    )
    results["synthetic_roster_battles"] = (
        bool(payload["roster_battles"])
        and any(
            row["competition_tier"] in {"BUBBLE", "CUT WATCH", "NON-GUARANTEED"}
            for row in payload["roster_battles"]
        )
    )
    results["synthetic_market_fallback"] = (
        payload["market_watch"]["total_available"] >= 3
        and payload["market_watch"]["top_available"][0]["name"] == "Market Star"
    )
    results["synthetic_complete_roadmap"] = (
        len(roadmap) == 11
        and [row["key"] for row in roadmap]
        == [
            "season_recap",
            "contract_closeout",
            "cpu_market",
            "draft_lottery",
            "scouting",
            "draft_night",
            "post_draft",
            "user_free_agency",
            "summer_development",
            "camp",
            "opening_night",
        ]
    )
    results["synthetic_camp_readiness"] = (
        0 <= camp["score"] <= 100
        and camp["grade"] in {"A", "B", "C", "D", "F"}
        and "prediction" in camp["model_note"].lower()
    )
    results["synthetic_decision_board"] = (
        bool(payload["decision_checklist"])
        and any(
            "ROSTER SLOT" in row["title"]
            for row in payload["decision_checklist"]
        )
    )
    results["synthetic_scope_truthful"] = (
        payload["system_scope"]["summer_league_simulation_available"] is False
        and payload["system_scope"]["training_camp_simulation_available"] is True
        and payload["system_scope"]["planning_surfaces_available"] is True
    )
    results["synthetic_last_season_recap"] = (
        payload["last_season"]["available"] is True
        and payload["last_season"]["result"] == "NBA FINALS"
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

    payload = build_offseason_command_payload(
        checkpoint,
        team_names={},
    )

    results["real_payload_read_only_contract"] = (
        payload.get("read_only") is True
        and payload.get("working_save_only") is True
        and payload.get("working_save_write_performed") is False
        and payload.get("active_v2_read_only") is True
        and bool(payload.get("team"))
    )
    results["real_payload_major_sections"] = all(
        key in payload
        for key in [
            "command",
            "roadmap",
            "lifecycle",
            "roster",
            "camp_readiness",
            "young_core",
            "roster_battles",
            "market_watch",
            "draft_watch",
            "last_season",
            "decision_checklist",
            "shortcuts",
            "system_scope",
        ]
    )
    results["real_complete_roadmap_contract"] = len(
        payload.get("roadmap", [])
    ) == 11
    results["real_foundation_did_not_mutate_saves"] = (
        save_hashes() == before
    )


def validate_static(results: dict[str, bool]) -> None:
    foundation_text = (
        ROOT / "desktop_bridge/offseason_command_foundation.py"
    ).read_text(encoding="utf-8")
    server_text = (
        ROOT / "desktop_bridge/server.py"
    ).read_text(encoding="utf-8")
    main_text = (
        ROOT / "godot_client/scripts/main.gd"
    ).read_text(encoding="utf-8")
    center_text = (
        ROOT / "godot_client/scripts/offseason_command_center_v3.gd"
    ).read_text(encoding="utf-8")
    timeline_text = (
        ROOT / "godot_client/scripts/offseason_timeline_v3.gd"
    ).read_text(encoding="utf-8")
    roster_text = (
        ROOT / "godot_client/scripts/offseason_roster_war_room_v3.gd"
    ).read_text(encoding="utf-8")

    results["server_read_only_endpoint_integration"] = all(
        token in server_text
        for token in [
            "build_offseason_command_payload",
            "async def offseason_command",
            'Route("/v3/offseason-command", offseason_command, methods=["GET"])',
            "read_only_offseason_command_changed_checkpoint",
        ]
    )

    results["main_offseason_navigation_integration"] = all(
        token in main_text
        for token in [
            "OffseasonCommandCenterV3",
            "var offseason_page: Control",
            'column.add_child(_nav_button("OFFSEASON"))',
            '"OFFSEASON":',
            'elif page_name == "OFFSEASON":',
            'offseason_page.call("refresh")',
            'offseason_page.connect("navigate_requested", _show_page)',
            '\t\t"OFFSEASON",\n\t\t"TRADES",',
        ]
    )

    results["offseason_major_ui_sections"] = all(
        token in center_text
        for token in [
            "OffseasonHero",
            "OffseasonShortcuts",
            "OffseasonMissionControl",
            "OffseasonRoadmapSection",
            "OffseasonDraftMarketSplit",
            "OffseasonRosterWarRoomSection",
            "OffseasonDecisionBoard",
            "OffseasonScopeDisclosure",
            "SCOUTING WAR ROOM",
            "FREE-AGENCY WAR ROOM",
            "GENERAL MANAGER DECISION BOARD",
        ]
    )

    results["offseason_subsystems_present"] = all(
        token in timeline_text
        for token in [
            "OffseasonRoadmap",
            "OFFSEASON ROADMAP",
            "CURRENT FOCUS",
            "destination_requested",
        ]
    ) and all(
        token in roster_text
        for token in [
            "OffseasonRosterWarRoom",
            "OPENING-NIGHT WAR ROOM",
            "SUMMER DEVELOPMENT BOARD",
            "TRAINING CAMP • ROSTER BATTLES",
            "TRAINING CAMP READINESS MODEL",
        ]
    )

    results["offseason_hub_has_no_write_method"] = (
        "HTTPClient.METHOD_POST" not in center_text
        and "HTTPClient.METHOD_PUT" not in center_text
        and "HTTPClient.METHOD_DELETE" not in center_text
        and "HTTPRequest" not in timeline_text
        and "HTTPRequest" not in roster_text
    )

    results["offseason_foundation_has_no_checkpoint_write"] = (
        "save_franchise_checkpoint" not in foundation_text
        and "commit_season_transition_preview" not in foundation_text
        and "commit_free_agency_preview" not in foundation_text
        and "METHOD_POST" not in foundation_text
    )

    results["existing_write_boundaries_still_present"] = all(
        token in server_text
        for token in [
            'Route("/v3/lifecycle/preview", lifecycle_preview, methods=["POST"])',
            'Route("/v3/lifecycle/execute", lifecycle_execute, methods=["POST"])',
            'Route("/v3/free-agency/preview", free_agency_preview, methods=["POST"])',
            'Route("/v3/free-agency/execute", free_agency_execute, methods=["POST"])',
            'Route("/v3/draft/selection/preview", draft_selection_preview, methods=["POST"])',
            'Route("/v3/draft/selection/execute", draft_selection_execute, methods=["POST"])',
            'Route("/v3/draft/roster-cut/preview", post_draft_roster_cut_preview, methods=["POST"])',
            'Route("/v3/draft/roster-cut/execute", post_draft_roster_cut_execute, methods=["POST"])',
        ]
    )

    results["truthful_scope_contract"] = all(
        token in foundation_text
        for token in [
            '"summer_league_simulation_available": False',
            '"training_camp_simulation_available": True',
            '"planning_surfaces_available": True',
            "Summer League games are not simulated",
        ]
    )


def validate_visual_qa_regressions(results: dict[str, bool]) -> None:
    center_text = (
        ROOT / "godot_client/scripts/offseason_command_center_v3.gd"
    ).read_text(encoding="utf-8")
    roster_text = (
        ROOT / "godot_client/scripts/offseason_roster_war_room_v3.gd"
    ).read_text(encoding="utf-8")

    results["responsive_width_contract"] = all(
        token in center_text
        for token in [
            "ScrollContainer.SCROLL_MODE_AUTO",
            "row.columns = 3",
            "var row = VBoxContainer.new()",
            "OffseasonDraftMarketSplit",
        ]
    )
    results["bottom_scroll_safe_area_contract"] = (
        'spacer.name = "OffseasonBottomSafeArea"' in center_text
        and "Vector2(0, 180)" in center_text
    )
    results["summer_development_width_contract"] = (
        "young_grid.columns = 3" in roster_text
        and "AUTOWRAP_WORD_SMART" in roster_text
    )

    production_board = {
        "board": [
            {
                "prospect_id": "prod-1",
                "Rank": 1,
                "Prospect": "Production Prospect",
                "Pos": "SG",
                "Archetype": "Two-Way Creator",
                "Scouted OVR": 79.4,
                "Scouted POT": 92.1,
                "Confidence": 57.5,
            }
        ],
        "draft_initialized": True,
        "draft": {
            "draft_year": 2027,
            "phase": "season_scouting",
            "available_prospect_count": 80,
        },
        "summary": {"weeks_completed": 0, "average_confidence": 57.5},
        "lead_scout": {"name": "Test Scout", "overall": 75.0},
        "post_draft_roster": {},
    }
    watch = _draft_watch(production_board, limit=5)
    top = watch.get("top_prospects", [{}])[0]
    results["production_scouting_display_schema_runtime"] = (
        top.get("name") == "Production Prospect"
        and top.get("position") == "SG"
        and top.get("archetype") == "Two-Way Creator"
        and top.get("scouted_overall") == 79.4
        and top.get("scouted_potential") == 92.1
        and top.get("confidence") == 57.5
    )


def validate_python_compile(results: dict[str, bool]) -> None:
    targets = [
        ROOT / "desktop_bridge/offseason_command_foundation.py",
        ROOT / "desktop_bridge/server.py",
        ROOT / "src/validate_v3_expansion40_complete_offseason.py",
    ]
    try:
        for target in targets:
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
        results["godot_expansion40_runtime"] = False
        return

    with tempfile.TemporaryDirectory(prefix="v3_exp40_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "smoke.gd"

        gdscript = r'''extends SceneTree

func fail_now(label: String) -> void:
    print("EXP40_FAIL::" + label)
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
        "foundation_version": "fixture",
        "read_only": true,
        "working_save_only": true,
        "active_v2_read_only": true,
        "working_save_unchanged": true,
        "active_v2_unchanged": true,
        "team": "BOS",
        "team_name": "Boston Celtics",
        "season": {
            "label": "2028-29",
            "phase": "offseason",
            "day_index": 0,
            "offseason_active": true
        },
        "command": {
            "headline": "OFFSEASON COMMAND CENTER",
            "current_stage": {
                "label": "PRE-DRAFT SCOUTING",
                "kicker": "WAR ROOM",
                "detail": "Scout the class before Draft Night."
            },
            "next_certified_action": "draft_lottery",
            "next_certified_action_label": "RUN DRAFT LOTTERY",
            "lifecycle_stage": "draft_lottery_ready",
            "blockers": []
        },
        "roadmap": [
            {"key":"season_recap","label":"SEASON RECAP","kicker":"YEAR IN REVIEW","status":"complete","detail":"Review history.","destination":"LEGACY","index":0,"current_focus":false},
            {"key":"contract_closeout","label":"CONTRACT CLOSEOUT","kicker":"EXPIRING DEALS","status":"complete","detail":"Close contracts.","destination":"SEASON","index":1,"current_focus":false},
            {"key":"cpu_market","label":"LEAGUE ROSTER MARKET","kicker":"CPU FREE AGENCY","status":"complete","detail":"CPU roster construction.","destination":"SEASON","index":2,"current_focus":false},
            {"key":"draft_lottery","label":"DRAFT LOTTERY","kicker":"ORDER REVEAL","status":"current","detail":"Reveal order.","destination":"SEASON","index":3,"current_focus":true},
            {"key":"scouting","label":"PRE-DRAFT SCOUTING","kicker":"WAR ROOM","status":"available","detail":"Scout class.","destination":"SCOUTING","index":4,"current_focus":false},
            {"key":"draft_night","label":"DRAFT NIGHT","kicker":"ON THE CLOCK","status":"locked","detail":"Draft players.","destination":"SCOUTING","index":5,"current_focus":false},
            {"key":"post_draft","label":"POST-DRAFT ROSTER","kicker":"ROOKIE INTEGRATION","status":"locked","detail":"Resolve roster.","destination":"ROSTER","index":6,"current_focus":false},
            {"key":"user_free_agency","label":"FREE AGENCY","kicker":"PLAYER MARKET","status":"current","detail":"Sign free agents.","destination":"FREE AGENCY","index":7,"current_focus":false},
            {"key":"summer_development","label":"SUMMER DEVELOPMENT","kicker":"YOUNG CORE","status":"planning","detail":"Develop youth.","destination":"ROSTER","index":8,"current_focus":false},
            {"key":"camp","label":"TRAINING CAMP","kicker":"ROSTER BATTLES","status":"planning","detail":"Set roster.","destination":"ROSTER","index":9,"current_focus":false},
            {"key":"opening_night","label":"OPENING NIGHT","kicker":"NEXT SEASON","status":"locked","detail":"Begin season.","destination":"SEASON","index":10,"current_focus":false}
        ],
        "lifecycle": {
            "stage": "draft_lottery_ready",
            "next_action": "draft_lottery"
        },
        "roster": {
            "roster_count": 15,
            "standard_count": 14,
            "two_way_count": 1,
            "standard_target": 15,
            "two_way_target": 3,
            "open_standard_slots": 1,
            "open_two_way_slots": 2,
            "rotation_count": 9,
            "starter_count": 5,
            "position_counts": {"PG":3,"SG":3,"SF":3,"PF":3,"C":2},
            "top_roster": []
        },
        "camp_readiness": {
            "score": 88,
            "grade": "B",
            "label": "ONE OR TWO DECISIONS AWAY",
            "covered_positions": 5,
            "position_counts": {"PG":3,"SG":3,"SF":3,"PF":3,"C":2},
            "model_note": "Planning grade only; not a prediction of team quality."
        },
        "young_core": [
            {
                "player_id":"young1",
                "name":"Young Guard",
                "position":"PG",
                "age":21,
                "overall":77,
                "potential":88,
                "future_outlook":87,
                "development_priority_score":87.4,
                "growth_gap":11,
                "development_direction":"Improving"
            }
        ],
        "roster_battles": [
            {
                "player_id":"bubble1",
                "name":"Bubble Wing",
                "position":"SF",
                "age":31,
                "overall":68,
                "competition_tier":"NON-GUARANTEED",
                "reason":"Non-guaranteed contract"
            }
        ],
        "market_watch": {
            "total_available": 3,
            "market_source":"production_free_agency_market",
            "top_available":[
                {"player_id":"fa1","name":"Market Star","position":"PG","age":27,"overall":88,"potential":89,"salary":30000000}
            ]
        },
        "draft_watch": {
            "initialized":true,
            "draft_year":2029,
            "phase":"scouting",
            "available_prospect_count":60,
            "weeks_completed":3,
            "average_confidence":72,
            "lead_scout":{"name":"Lead Scout","overall":84},
            "top_prospects":[
                {"prospect_id":"d1","name":"Elite Prospect","position":"SG","archetype":"Two-Way Creator","confidence":78,"scouted_overall":80,"scouted_potential":94}
            ],
            "post_draft_roster":{}
        },
        "last_season": {
            "available":true,
            "season":"2027-28",
            "record":"54-28",
            "result":"NBA FINALS",
            "champion":"OKC",
            "champion_name":"Oklahoma City Thunder"
        },
        "decision_checklist": [
            {"priority":"CRITICAL","title":"RUN DRAFT LOTTERY","detail":"Certified next lifecycle boundary.","destination":"SEASON","status":"ACTIONABLE"},
            {"priority":"MEDIUM","title":"FILL 1 STANDARD ROSTER SLOT","detail":"Roster construction remains.","destination":"FREE AGENCY","status":"OPEN"}
        ],
        "shortcuts": [
            {"label":"SEASON COMMAND","detail":"Lifecycle boundaries.","destination":"SEASON"},
            {"label":"SCOUTING & DRAFT","detail":"Draft operations.","destination":"SCOUTING"},
            {"label":"FREE AGENCY","detail":"Player market.","destination":"FREE AGENCY"},
            {"label":"ROSTER","detail":"Roster planning.","destination":"ROSTER"},
            {"label":"LEGACY","detail":"Season history.","destination":"LEGACY"}
        ],
        "system_scope": {
            "summer_league_simulation_available":false,
            "training_camp_simulation_available":false,
            "planning_surfaces_available":true,
            "note":"Summer Development and Training Camp are planning/readiness surfaces in this release; they do not fabricate games, ratings changes, or transactions."
        },
        "diagnostics":[]
    }


func _initialize() -> void:
    var center_script = load("res://scripts/offseason_command_center_v3.gd")
    if center_script == null:
        fail_now("command_center_script_load")
        return

    var timeline_script = load("res://scripts/offseason_timeline_v3.gd")
    if timeline_script == null:
        fail_now("timeline_script_load")
        return

    var roster_script = load("res://scripts/offseason_roster_war_room_v3.gd")
    if roster_script == null:
        fail_now("roster_war_room_script_load")
        return

    var main_script = load("res://scripts/main.gd")
    if main_script == null:
        fail_now("main_script_load")
        return

    var center = center_script.new()
    if center == null:
        fail_now("command_center_construct")
        return

    center.configure(fixture())

    for node_name in [
        "OffseasonHero",
        "OffseasonShortcuts",
        "OffseasonMissionControl",
        "OffseasonRoadmapSection",
        "OffseasonDraftMarketSplit",
        "OffseasonRosterWarRoomSection",
        "OffseasonDecisionBoard",
        "OffseasonScopeDisclosure",
        "OffseasonRoadmap",
        "OffseasonRosterWarRoom",
        "OffseasonBottomSafeArea"
    ]:
        if center.find_child(node_name, true, false) == null:
            center.free()
            fail_now("missing_" + node_name)
            return

    var text = all_text(center)
    for required in [
        "OFFSEASON COMMAND CENTER",
        "FRONT OFFICE MISSION CONTROL",
        "THE COMPLETE OFFSEASON",
        "SCOUTING WAR ROOM",
        "FREE-AGENCY WAR ROOM",
        "SUMMER DEVELOPMENT BOARD",
        "TRAINING CAMP",
        "GENERAL MANAGER DECISION BOARD",
        "SYSTEM SCOPE",
        "NO DUPLICATE WRITES"
    ]:
        if text.find(required) < 0:
            center.free()
            fail_now("missing_text_" + required)
            return

    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({
        "offseason_command_component_constructed": true,
        "offseason_subcomponents_constructed": true,
        "offseason_major_sections_present": true,
        "offseason_main_script_parse_loaded": true
    }))
    output.close()

    center.free()
    print("EXP40_COMPLETE")
    quit(0)
'''
        gdscript = gdscript.replace(
            "MARKER_PATH",
            json.dumps(marker.as_posix()),
        )
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
                timeout=35,
            )
            combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
            if combined.strip():
                print(combined[-18000:])

            results["godot_expansion40_runtime"] = (
                proc.returncode == 0
                and marker.exists()
                and "EXP40_COMPLETE" in combined
                and "EXP40_FAIL::" not in combined
                and "parse error" not in combined.lower()
                and "parser error" not in combined.lower()
            )
            if marker.exists():
                results.update(
                    json.loads(marker.read_text(encoding="utf-8"))
                )
        except subprocess.TimeoutExpired as exc:
            print("[FAIL] Expansion 40 Godot smoke timed out.")
            if exc.stdout:
                print(str(exc.stdout)[-6000:])
            if exc.stderr:
                print(str(exc.stderr)[-6000:])
            results["godot_expansion40_runtime"] = False


def main() -> int:
    before = save_hashes()
    results: dict[str, bool] = {}

    print("=" * 110)
    print("V3 EXPANSION 40 — COMPLETE NBA OFFSEASON VALIDATION")
    print("=" * 110)
    print(f"Foundation: {OFFSEASON_COMMAND_FOUNDATION_VERSION}")

    validate_python_compile(results)
    validate_static(results)
    validate_synthetic(results)
    validate_real_checkpoint(results)
    validate_visual_qa_regressions(results)
    validate_godot(results)

    results["active_v3_and_protected_v2_unchanged"] = (
        save_hashes() == before
    )

    out = ROOT / "outputs/v3_expansion40_complete_offseason"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(
        json.dumps(
            {
                "version": VERSION,
                "foundation_version": OFFSEASON_COMMAND_FOUNDATION_VERSION,
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
        "V3 EXPANSION 40 COMPLETE NBA OFFSEASON "
        + ("PASSED" if passed else "FAILED")
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
