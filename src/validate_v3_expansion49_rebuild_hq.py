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

from desktop_bridge.rebuild_experience_foundation import (
    REBUILD_EXPERIENCE_VERSION,
    build_rebuild_hq_payload,
    load_rebuild_experience,
    update_rebuild_experience,
)
from desktop_bridge.front_office_foundation import build_front_office_intelligence_payload
from desktop_bridge.development_goals import goals_board
from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH, load_franchise_checkpoint

V3 = ROOT / "outputs/runtime/v3_godot_working_checkpoint.pkl.gz"
V2 = Path(DEFAULT_CHECKPOINT_PATH)


def digest(path: Path) -> str:
    if not path.exists():
        return "missing"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_hashes() -> dict[str, str]:
    return {"v3": digest(V3), "v2": digest(V2)}


def player(name: str, age: float, overall: float, potential: float, position: str) -> Any:
    return SimpleNamespace(
        player_name=name,
        age=age,
        overall_rating=overall,
        potential_rating=potential,
        future_outlook_rating=potential,
        development_direction="Improving",
        profile_reliability=0.9,
        development_history=[],
        training_camp_history=[],
        position=position,
        synthetic=False,
        skill_ratings={
            "shooting_rating": overall - 1,
            "playmaking_rating": overall - 2,
            "defense_rating": overall,
            "rebounding_rating": overall - 3,
        },
    )


def synthetic_checkpoint() -> Any:
    players = {
        "p1": player("Young Guard", 20, 74, 88, "PG"),
        "p2": player("Young Wing", 22, 77, 85, "SF"),
        "p3": player("Young Big", 23, 75, 82, "C"),
        "p4": player("Veteran Star", 29, 91, 92, "SG"),
    }
    team_state = SimpleNamespace(
        roster_player_ids=("p1", "p2", "p3", "p4"),
        conference="East",
        rotation=SimpleNamespace(
            starter_ids=("p1", "p2", "p3", "p4", "p5"),
            rotation_player_ids=("p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8"),
            minutes_targets={
                "p1": 30.0, "p2": 30.0, "p3": 28.0, "p4": 36.0,
                "p5": 32.0, "p6": 30.0, "p7": 28.0, "p8": 26.0,
            },
        ),
    )
    standing = SimpleNamespace(
        wins=2, losses=3, games_played=5, points_for=550, points_against=560
    )
    state = SimpleNamespace(
        settings=SimpleNamespace(season_label="2027-28"),
        phase="regular_season",
        current_day_index=7,
        season_history=[],
        teams={"BOS": team_state},
        players=players,
        standings={"BOS": standing},
        player_season_totals={},
        franchise_transaction_history_v1=[],
    )
    return SimpleNamespace(
        simulation_state=state,
        preferences={"franchise_pref_active_team": "BOS"},
        trade_state=SimpleNamespace(),
    )


def synthetic_inputs(checkpoint: Any) -> tuple[dict, dict, dict, dict, dict]:
    roster = {
        "players": [
            {"player_id": pid, "name": checkpoint.simulation_state.players[pid].player_name}
            for pid in checkpoint.simulation_state.teams["BOS"].roster_player_ids
        ],
        "team": {},
        "financial": {
            "cap_room_estimate": -10_000_000,
            "cap_room_estimate_display": "-$10.0M",
        },
        "chemistry": {},
    }

    office = {
        "development": {
            "full_roster": [
                {"player_id":"p1","name":"Young Guard","position":"PG","age":20,"overall":74,"potential":88,"future_outlook":88,"direction":"Improving"},
                {"player_id":"p2","name":"Young Wing","position":"SF","age":22,"overall":77,"potential":85,"future_outlook":85,"direction":"Improving"},
                {"player_id":"p3","name":"Young Big","position":"C","age":23,"overall":75,"potential":82,"future_outlook":82,"direction":"Improving"},
                {"player_id":"p4","name":"Veteran Star","position":"SG","age":29,"overall":91,"potential":92,"future_outlook":91,"direction":"Stable"},
            ]
        },
        "development_goals": {
            "committed": False,
            "can_commit": True,
            "goals": [],
            "slots": 3,
            "rules": "Synthetic development rules.",
        },
        "rotation": {
            "starters": 5,
            "rotation_players": 8,
            "total_target_minutes": 240.0,
        },
        "financial": {
            "cap_room_estimate": -10_000_000,
            "cap_room_estimate_display": "-$10.0M",
        },
        "morale": {"attention_count": 0},
        "team_health": {"injured_count": 0},
    }

    game_day = {
        "record": {
            "wins": 2, "losses": 3, "games_played": 5, "display": "2-3"
        },
        "next_game": {
            "day_index": 8,
            "opponent": "MIA",
            "opponent_name": "Miami Heat",
        },
    }

    scouting = {
        "draft_initialized": True,
        "summary": {
            "weeks_completed": 0,
            "average_confidence": 42.0,
            "focus_ids": [],
        },
        "draft": {
            "draft_year": 2028,
            "phase": "season_scouting",
            "available_prospect_count": 80,
        },
        "lead_scout": {"name": "Scout One", "overall": 77.0},
    }

    transactions = {
        "draft_assets": {
            "owned_count": 3,
            "engine_ready_count": 3,
            "manual_review_count": 0,
            "owned": [
                {"asset_id":"BOS_2028_R1","draft_year":2028,"round":1,"origin_team":"BOS"},
                {"asset_id":"BOS_2028_R2","draft_year":2028,"round":2,"origin_team":"BOS"},
                {"asset_id":"BOS_2029_R1","draft_year":2029,"round":1,"origin_team":"BOS"},
            ],
        }
    }
    return roster, office, game_day, scouting, transactions


def validate_synthetic(results: dict[str, bool]) -> None:
    checkpoint = synthetic_checkpoint()
    roster, office, game_day, scouting, transactions = synthetic_inputs(checkpoint)

    with tempfile.TemporaryDirectory(prefix="exp49_meta_") as temp:
        meta_path = Path(temp) / "rebuild.json"
        experience = load_rebuild_experience(meta_path, checkpoint, "BOS")

        payload = build_rebuild_hq_payload(
            checkpoint,
            "BOS",
            roster_payload=roster,
            office_payload=office,
            game_day_payload=game_day,
            scouting_payload=scouting,
            transaction_payload=transactions,
            experience=experience,
            team_names={"BOS": "Boston Celtics", "MIA": "Miami Heat"},
        )

        results["synthetic_development_first"] = (
            payload["next_moves"][0]["destination"] == "DEVELOPMENT"
            and payload["feature_guides"][0]["destination"] == "DEVELOPMENT"
            and payload["development"]["committed"] is False
        )
        results["synthetic_young_core"] = (
            len(payload["young_core"]) == 3
            and payload["young_core"][0]["name"] == "Young Guard"
            and payload["young_core"][0]["growth_gap"] == 14.0
        )
        results["synthetic_strategy_recommendation"] = (
            payload["strategy"]["recommended"] == "develop_young_core"
            and payload["strategy"]["active"] == "develop_young_core"
            and payload["strategy"]["source"] == "recommended"
        )
        results["synthetic_journey_evidence"] = (
            payload["journey"]["total"] >= 10
            and payload["journey"]["completed"] >= 2
            and any(
                task["id"] == "development_goals" and not task["complete"]
                for stage in payload["journey"]["stages"]
                for task in stage["tasks"]
            )
        )
        results["synthetic_navigation_reduction"] = (
            "REBUILD HQ" in payload["navigation"]["primary_sidebar"]
            and "PULSE" in payload["navigation"]["contextual_only"]
            and "THEATER" in payload["navigation"]["contextual_only"]
            and "STORIES" in payload["navigation"]["contextual_only"]
        )
        results["synthetic_scope_no_gameplay_mutation"] = all(
            payload["scope"][key] is False
            for key in [
                "ratings_changed",
                "rotation_changed",
                "transaction_executed",
                "franchise_checkpoint_written",
            ]
        )

        update = update_rebuild_experience(
            meta_path,
            checkpoint,
            "BOS",
            {"action": "set_strategy", "strategy": "draft_rebuild"},
        )
        results["synthetic_strategy_metadata_persistence"] = (
            update["strategy"] == "draft_rebuild"
            and update["metadata_write_performed"] is True
            and load_rebuild_experience(meta_path, checkpoint, "BOS")["strategy"]
            == "draft_rebuild"
        )

        completed = update_rebuild_experience(
            meta_path,
            checkpoint,
            "BOS",
            {"action": "complete_onboarding"},
        )
        results["synthetic_onboarding_metadata_persistence"] = (
            completed["onboarding_completed"] is True
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
    state = checkpoint.simulation_state
    team_state = state.teams.get(team)

    roster = {
        "players": [
            {"player_id": str(pid)}
            for pid in list(getattr(team_state, "roster_player_ids", ()) or ())
        ],
        "team": {},
        "financial": {},
        "chemistry": {},
    }
    office = build_front_office_intelligence_payload(
        state, team, roster, team_names={}
    )
    office["development_goals"] = goals_board(checkpoint, team)

    standing = state.standings.get(team)
    wins = int(getattr(standing, "wins", 0) or 0) if standing else 0
    losses = int(getattr(standing, "losses", 0) or 0) if standing else 0
    games = (
        int(getattr(standing, "games_played", wins + losses) or 0)
        if standing else 0
    )

    game_day = {
        "record": {
            "wins": wins,
            "losses": losses,
            "games_played": games,
            "display": f"{wins}-{losses}",
        },
        "next_game": {},
    }

    with tempfile.TemporaryDirectory(prefix="exp49_real_meta_") as temp:
        experience = load_rebuild_experience(
            Path(temp) / "rebuild.json", checkpoint, team
        )
        payload = build_rebuild_hq_payload(
            checkpoint,
            team,
            roster_payload=roster,
            office_payload=office,
            game_day_payload=game_day,
            scouting_payload={},
            transaction_payload={"draft_assets": {"owned": []}},
            experience=experience,
            team_names={},
        )

    results["real_payload_major_sections"] = all(
        key in payload
        for key in [
            "strategy",
            "young_core",
            "development",
            "next_moves",
            "journey",
            "feature_guides",
            "navigation",
            "scope",
        ]
    )
    results["real_payload_development_is_first_guide"] = (
        payload["feature_guides"][0]["destination"] == "DEVELOPMENT"
    )
    results["real_foundation_did_not_mutate_saves"] = save_hashes() == before


def validate_static(results: dict[str, bool]) -> None:
    server = (ROOT / "desktop_bridge/server.py").read_text(encoding="utf-8")
    main = (ROOT / "godot_client/scripts/main.gd").read_text(encoding="utf-8")
    page = (ROOT / "godot_client/scripts/rebuild_hq_v3.gd").read_text(encoding="utf-8")
    settings = (ROOT / "godot_client/scripts/settings_tutorial_v3.gd").read_text(encoding="utf-8")
    launcher = (ROOT / "scripts/run_v3_desktop.ps1").read_text(encoding="utf-8")
    foundation = (ROOT / "desktop_bridge/rebuild_experience_foundation.py").read_text(encoding="utf-8")

    results["server_rebuild_endpoint_contract"] = all(
        token in server
        for token in [
            'API_VERSION = "0.26.0"',
            "build_rebuild_hq_payload",
            "async def rebuild_hq",
            'Route("/v3/rebuild-hq", rebuild_hq, methods=["GET", "POST"])',
            "V3_REBUILD_EXPERIENCE_PATH",
        ]
    )
    results["main_rebuild_navigation_contract"] = all(
        token in main
        for token in [
            "RebuildHQV3",
            "var rebuild_page: Control",
            'column.add_child(_nav_button("REBUILD HQ"))',
            '"REBUILD HQ":',
            'elif page_name == "REBUILD HQ":',
            'rebuild_page.call("refresh")',
            '_show_page("REBUILD HQ")',
        ]
    )
    results["sidebar_information_architecture"] = (
        'sidebar_group_label("BUILD YOUR TEAM")' in main
        and 'sidebar_group_label("SEASON")' in main
        and 'sidebar_group_label("BUILD THE FUTURE")' in main
        and 'column.add_child(_nav_button("PULSE"))' not in main
        and 'column.add_child(_nav_button("THEATER"))' not in main
        and 'column.add_child(_nav_button("STORIES"))' not in main
        and 'column.add_child(_nav_button("FRONT OFFICE"))' not in main
    )
    results["rebuild_ui_major_sections"] = all(
        token in page
        for token in [
            "RebuildHQHero",
            "RebuildHQYoungCore",
            "RebuildHQNextMoves",
            "RebuildHQStrategy",
            "RebuildHQJourney",
            "RebuildHQFeatureAcademy",
            "RebuildHQSystemMap",
            "RebuildHQScope",
            "RebuildOnboardingOverlay",
        ]
    )
    results["development_first_tutorial_contract"] = (
        "START WITH PLAYER DEVELOPMENT" in page
        and "BUILD YOUR CORE" in page
        and "FIRST PRIORITY • BUILD YOUR CORE" in page
        and "REBUILDING STARTS WITH DEVELOPMENT" in settings
    )
    results["settings_tutorial_expanded"] = (
        "NINE-STEP" in settings.upper()
        and "PLAYER DEVELOPMENT" in settings
        and "PULSE + STORIES + LEGACY" in settings
    )
    results["launcher_warms_rebuild_hq"] = '"/v3/rebuild-hq"' in launcher
    results["rebuild_foundation_has_no_checkpoint_write"] = all(
        token not in foundation
        for token in [
            "save_franchise_checkpoint",
            "force_replace",
            "commit_free_agency",
            "commit_trade",
            "simulate_scheduled_game",
        ]
    )


def validate_python_compile(results: dict[str, bool]) -> None:
    try:
        for path in [
            ROOT / "desktop_bridge/rebuild_experience_foundation.py",
            ROOT / "desktop_bridge/server.py",
            ROOT / "src/validate_v3_expansion49_rebuild_hq.py",
        ]:
            py_compile.compile(str(path), doraise=True)
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
        results["godot_expansion49_runtime"] = False
        return

    with tempfile.TemporaryDirectory(prefix="v3_exp49_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "smoke.gd"

        gdscript = r'''extends SceneTree

func fail_now(label: String) -> void:
    print("EXP49_FAIL::" + label)
    quit(2)


func all_text(node: Node) -> String:
    var result = ""
    if node is Label:
        result += str(node.text) + "
"
    if node is Button:
        result += str(node.text) + "
"
    for child in node.get_children():
        result += all_text(child)
    return result


func fixture() -> Dictionary:
    return {
        "team":"BOS",
        "team_name":"Boston Celtics",
        "season":"2027-28",
        "phase":"regular_season",
        "day":7,
        "record":{"wins":2,"losses":3,"games":5,"display":"2-3","win_pct":0.4},
        "strategy":{
            "active":"develop_young_core",
            "source":"recommended",
            "recommended":"develop_young_core",
            "recommendation_reason":"Three young players have runway.",
            "choices":[
                {"id":"develop_young_core","label":"DEVELOP THE YOUNG CORE","short":"Develop","detail":"Grow the core.","selected":true,"recommended":true},
                {"id":"contend_now","label":"CONTEND NOW","short":"Contend","detail":"Win now.","selected":false,"recommended":false},
                {"id":"draft_rebuild","label":"REBUILD THROUGH THE DRAFT","short":"Draft","detail":"Draft.","selected":false,"recommended":false},
                {"id":"cap_flexibility","label":"CREATE CAP FLEXIBILITY","short":"Cap","detail":"Cap.","selected":false,"recommended":false},
                {"id":"balanced","label":"BALANCED FRONT OFFICE","short":"Balanced","detail":"Balance.","selected":false,"recommended":false}
            ]
        },
        "young_core":[
            {"player_id":"p1","name":"Young Guard","position":"PG","age":20,"overall":74.0,"potential":88.0,"growth_gap":14.0,"goal_active":false},
            {"player_id":"p2","name":"Young Wing","position":"SF","age":22,"overall":77.0,"potential":85.0,"growth_gap":8.0,"goal_active":false},
            {"player_id":"p3","name":"Young Big","position":"C","age":23,"overall":75.0,"potential":82.0,"growth_gap":7.0,"goal_active":false}
        ],
        "development":{"committed":false,"can_commit":true,"active_goal_count":0,"slots":3},
        "scouting":{"initialized":true,"weeks_completed":0,"available_prospects":80,"focus_count":0},
        "draft_assets":{"owned_count":3,"first_round_count":2},
        "roster":{"count":15,"rotation":{"starters":5,"rotation_players":8,"total_target_minutes":240.0}},
        "next_moves":[
            {"rank":1,"category":"BUILD YOUR CORE","title":"Set development goals first","detail":"Young players need a plan.","destination":"DEVELOPMENT","action":"OPEN DEVELOPMENT HQ"},
            {"rank":2,"category":"BUILD THE FUTURE","title":"Start scouting","detail":"80 prospects.","destination":"SCOUTING","action":"OPEN SCOUTING"},
            {"rank":3,"category":"NEXT GAME","title":"Prepare for Miami","detail":"League day 8.","destination":"GAME DAY","action":"OPEN GAME PLAN"}
        ],
        "journey":{
            "completed":3,"total":11,"progress":0.273,
            "stages":[
                {"title":"FOUNDATION","subtitle":"Know the roster.","completed":2,"total":2,"tasks":[
                    {"id":"roster_loaded","title":"Review roster","complete":true,"destination":"ROSTER","evidence":"15 players"},
                    {"id":"rotation_ready","title":"Set rotation","complete":true,"destination":"ROSTER","evidence":"240 minutes"}
                ]},
                {"title":"BUILD YOUR CORE","subtitle":"Develop.","completed":0,"total":2,"tasks":[
                    {"id":"development_goals","title":"Commit goals","complete":false,"destination":"DEVELOPMENT","evidence":"No goals"},
                    {"id":"development_sample","title":"Ten-game sample","complete":false,"destination":"DEVELOPMENT","evidence":"5/10 games"}
                ]}
            ]
        },
        "feature_guides":[
            {"id":"development","destination":"DEVELOPMENT","eyebrow":"START HERE","title":"DEVELOPMENT COMMAND CENTER","why":"Build the core.","action":"BUILD YOUR CORE","status":"RECOMMENDED FIRST STOP"},
            {"id":"scouting","destination":"SCOUTING","eyebrow":"BUILD THE FUTURE","title":"SCOUTING + DRAFT","why":"Scout.","action":"SCOUT THE FUTURE","status":"0 WEEKS"},
            {"id":"trades","destination":"TRADES","eyebrow":"CHANGE THE CORE","title":"TRADE CENTER","why":"Trade.","action":"EXPLORE TRADES","status":"AVAILABLE"},
            {"id":"free_agency","destination":"FREE AGENCY","eyebrow":"USE THE MARKET","title":"FREE AGENCY","why":"Market.","action":"OPEN FREE AGENCY","status":"AVAILABLE"}
        ],
        "scope":{"note":"Guidance only."}
    }


func _initialize() -> void:
    var page_script = load("res://scripts/rebuild_hq_v3.gd")
    if page_script == null:
        fail_now("page_script")
        return
    if load("res://scripts/main.gd") == null:
        fail_now("main_script")
        return
    if load("res://scripts/settings_tutorial_v3.gd") == null:
        fail_now("settings_script")
        return

    var page = page_script.new()
    get_root().add_child(page)
    page.configure(fixture())

    var lab = load("res://scripts/rebuild_opportunity_v3.gd").new()
    get_root().add_child(lab)
    var lab_fixture = {"planned_total":240,"young_core_minutes":16,"players":[{"name":"Veteran","planned_minutes":32,"minutes_per_game":30,"games":6,"young_core":false},{"name":"Prospect","planned_minutes":16,"minutes_per_game":12,"games":6,"young_core":true}]}
    var lab_before = JSON.stringify(lab_fixture)
    lab.configure(lab_fixture)
    lab.donor.select(1)
    lab.recipient.select(2)
    lab.amount.value = 8
    lab._update()
    if lab.result.text.find("32.0 → 24.0") < 0 or lab.result.text.find("16.0 → 24.0") < 0 or lab.result.text.find("Total stays 240.0") < 0:
        fail_now("opportunity_transfer")
        return
    lab.amount.value = 40
    lab._update()
    if lab.result.text.find("exceeds") < 0:
        fail_now("opportunity_bounds")
        return
    lab.recipient.select(1)
    lab._update()
    if lab.result.text.find("different players") < 0 or JSON.stringify(lab_fixture) != lab_before:
        fail_now("opportunity_read_only")
        return
    lab.free()

    var development = load("res://scripts/development_command_center_v3.gd").new()
    get_root().add_child(development)
    var development_fixture = {"season":"2026-27", "phase":"regular_season", "team":"BOS", "committed":false, "can_commit":true, "players":[{"player_id":"p1","name":"Young Guard","overall":74,"games":6,"minutes_per_game":14,"skills":{"shooting":70,"playmaking":72,"defense":68,"rebounding":50}},{"player_id":"p2","name":"Young Wing","overall":75,"games":6,"minutes_per_game":12,"skills":{"shooting":71}}],"archive":[]}
    development.focus_player("p1")
    development.configure(development_fixture)
    if development.find_child("DraftFocusedPlayerGoal", true, false) == null:
        fail_now("focused_player_review")
        return
    development.forms[0].player.select(2)
    development._update_form(0)
    development._draft_focused_player()
    if development.forms[0].player.selected != 2 or development.forms[1].player.selected != 1:
        fail_now("draft_preserves_other_players")
        return
    development.forms[1].metric.select(4)
    development._update_form(1)
    development._draft_focused_player()
    if development.forms[1].metric.selected != 4 or development.forms[2].player.selected != 0 or development.confirm_button.visible:
        fail_now("repeat_preserves_draft_and_no_commit")
        return
    development_fixture["committed"] = true
    development_fixture["can_commit"] = false
    development.configure(development_fixture)
    if not development.forms.is_empty() or development.find_child("DraftFocusedPlayerGoal", true, false) != null:
        fail_now("committed_plan_read_only")
        return
    development.focus_player("departed")
    development.configure(development_fixture)
    if not development.focused_player_id.is_empty():
        fail_now("departed_focus_cleared")
        return
    development.free()

    var guide = load("res://scripts/feature_guide_v3.gd").new()
    guide.preferences_path = MARKER_PATH + ".guides.cfg"
    get_root().add_child(guide)
    var destinations = []
    guide.navigate_requested.connect(func(destination): destinations.append(destination))
    for destination in guide.GUIDES.keys():
        guide.show_page(destination)
        if not guide.visible or guide.expanded:
            fail_now("guide_initial_state")
            return
        guide.expanded = true
        guide._render()
        for index in range(guide.GUIDES[destination].size()):
            if guide.step != index or guide.find_child("FeatureGuideDetails", true, false) == null:
                fail_now("guide_step")
                return
            guide._next()
        if guide.expanded or not guide.preferences.get_value("read", destination, false):
            fail_now("guide_complete")
            return
    guide.show_page("DEVELOPMENT")
    guide.step = guide.GUIDES["DEVELOPMENT"].size() - 1
    guide.expanded = true
    guide._render()
    var guide_controls = guide.detail.get_child(2)
    guide_controls.get_child(2).pressed.emit()
    if destinations != ["OFFSEASON"]:
        fail_now("guide_contextual_navigation")
        return
    var saved = ConfigFile.new()
    if saved.load(guide.preferences_path) != OK or not saved.get_value("read", "DEVELOPMENT", false):
        fail_now("guide_preferences_reload")
        return
    guide.show_page("HOME")
    if guide.visible:
        fail_now("guide_unsupported_page")
        return
    guide.free()
    var fold = page.find_child("RebuildFoldTEAM", true, false)
    if fold == null or fold.get_parent().get_child(1).visible:
        fail_now("fold_initial_state")
        return
    fold.pressed.emit()
    if not fold.get_parent().get_child(1).visible:
        fail_now("fold_expand")
        return

    for name in [
        "RebuildHQScroll",
        "RebuildHQHero",
        "RebuildHQYoungCore",
        "RebuildHQNextMoves",
        "RebuildHQStrategy",
        "RebuildHQJourney",
        "RebuildHQFeatureAcademy",
        "RebuildHQSystemMap",
        "RebuildHQScope",
        "RebuildHQBottomSafeArea"
    ]:
        if page.find_child(name, true, false) == null:
            page.free()
            fail_now("missing_" + name)
            return

    var text = all_text(page)
    for required in [
        "REBUILD HQ",
        "FIRST PRIORITY • BUILD YOUR CORE",
        "WHAT SHOULD I CARE ABOUT RIGHT NOW?",
        "CHOOSE YOUR DIRECTION",
        "YOUR FRANCHISE JOURNEY",
        "FEATURE ACADEMY",
        "DEVELOPMENT COMMAND CENTER"
    ]:
        if text.find(required) < 0:
            page.free()
            fail_now("text_" + required)
            return

    page.start_onboarding(false)
    if page.find_child("RebuildOnboardingOverlay", true, false) == null:
        page.free()
        fail_now("onboarding_overlay")
        return

    var completions = []
    page.onboarding_finished.connect(func(startup): completions.append(startup))
    page._skip_onboarding()
    if not completions.is_empty() or page.onboarding_overlay != null:
        fail_now("skip_must_only_close")
        return
    page.start_onboarding(false)
    page.pending_action = "complete_onboarding"
    page.pending_onboarding_finish = true
    page._on_action_completed(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), JSON.stringify(fixture()).to_utf8_buffer())
    if completions != [false] or page.onboarding_overlay != null:
        fail_now("manual_completion_signal")
        return

    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({
        "rebuild_page_constructed":true,
        "young_core_runtime":true,
        "journey_runtime":true,
        "feature_academy_runtime":true,
        "onboarding_runtime":true,
        "onboarding_skip_and_manual_completion":true,
        "feature_guides_navigation_persistence":true,
        "rebuild_section_folding":true,
        "player_development_handoff_safe_drafts":true,
        "opportunity_lab_transfer_bounds_read_only":true,
        "main_script_loaded":true,
        "settings_script_loaded":true
    }))
    output.close()

    page.free()
    print("EXP49_COMPLETE")
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
                timeout=40,
            )
            combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
            if combined.strip():
                print(combined[-16000:])
            results["godot_expansion49_runtime"] = (
                proc.returncode == 0
                and marker.exists()
                and "EXP49_COMPLETE" in combined
                and "EXP49_FAIL::" not in combined
                and "parse error" not in combined.lower()
                and "parser error" not in combined.lower()
                and "!is_inside_tree()" not in combined
                and "ERR_UNCONFIGURED" not in combined
            )
            if marker.exists():
                results.update(json.loads(marker.read_text(encoding="utf-8")))
        except subprocess.TimeoutExpired:
            results["godot_expansion49_runtime"] = False


def main() -> int:
    before = save_hashes()
    results: dict[str, bool] = {}

    print("=" * 112)
    print("V3 EXPANSION 49 — REBUILD HQ + GUIDED FRANCHISE VALIDATION")
    print("=" * 112)
    print(f"Foundation: {REBUILD_EXPERIENCE_VERSION}")

    validate_python_compile(results)
    validate_static(results)
    validate_synthetic(results)
    validate_real_checkpoint(results)
    validate_godot(results)
    results["active_v3_and_protected_v2_unchanged"] = save_hashes() == before

    for key, passed in results.items():
        print(f"{key}: {'PASS' if passed else 'FAIL'}")

    ok = all(results.values())
    print()
    print(
        "V3 EXPANSION 49 REBUILD HQ + GUIDED FRANCHISE "
        + ("PASSED" if ok else "FAILED")
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
