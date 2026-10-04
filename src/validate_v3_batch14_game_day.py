from __future__ import annotations

import hashlib
import json
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from simulation_franchise_checkpoint_v1 import (  # noqa: E402
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)
from desktop_bridge.server import (  # noqa: E402
    V3_WORKING_CHECKPOINT_PATH,
    _active_team_from_checkpoint,
    _game_day_payload,
    _roster_payload,
)


REPORT_DIR = ROOT / "outputs" / "v3_batch14_game_day"
REPORT_PATH = REPORT_DIR / "validation.json"


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check(name: str, condition: Any, results: dict[str, bool]) -> None:
    results[name] = bool(condition)
    print(f"  {name}: {'PASS' if condition else 'FAIL'}")


def compile_files(results: dict[str, bool]) -> None:
    ok = True
    for path in [ROOT / "src" / "validate_v3_batch14_game_day.py"]:
        try:
            py_compile.compile(str(path), doraise=True)
        except Exception as exc:
            ok = False
            print(f"    compile failure: {path}: {type(exc).__name__}: {exc}")
    check("modified_python_files_compile", ok, results)


def git_path_unchanged(path: str) -> bool:
    proc = subprocess.run(
        ["git", "diff", "--quiet", "--", path],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


def static_checks(results: dict[str, bool]) -> dict[str, Any]:
    main_path = ROOT / "godot_client" / "scripts" / "main.gd"
    game_day_path = ROOT / "godot_client" / "scripts" / "game_day_center_v3.gd"
    server_path = ROOT / "desktop_bridge" / "server.py"

    main = main_path.read_text(encoding="utf-8")
    game_day = game_day_path.read_text(encoding="utf-8")
    server = server_path.read_text(encoding="utf-8")

    check(
        "game_day_center_preloaded",
        'GameDayCenterV3 = preload("res://scripts/game_day_center_v3.gd")' in main,
        results,
    )
    check(
        "game_day_center_instantiated",
        "game_day_page = GameDayCenterV3.new()" in main,
        results,
    )
    check(
        "game_day_center_visibility_wired",
        'game_day_page.visible = page_name == "GAME DAY"' in main
        or all(token in main for token in (
            '"GAME DAY":\n\t\t\treturn game_day_page',
            'var target_page = _page_control(page_name)',
            'for page in _all_page_controls():',
            'page.visible = page == target_page',
        )),
        results,
    )
    check(
        "game_day_sidebar_uses_page_navigation",
        '"GAME DAY",' in main
        and 'button.pressed.connect(_show_page.bind(text_value))' in main
        and 'button.pressed.connect(_open_game_day_overlay)' not in main,
        results,
    )
    check(
        "home_game_day_shortcut_uses_page_navigation",
        'open_game_day.pressed.connect(_show_page.bind("GAME DAY"))' in main,
        results,
    )
    check(
        "game_day_page_refresh_wired",
        'page_name == "GAME DAY"' in main
        and 'game_day_page.has_method("refresh")' in main,
        results,
    )
    check(
        "game_day_live_endpoints_reused",
        all(
            token in game_day
            for token in (
                'GAME_DAY_URL := "http://127.0.0.1:8765/v3/game-day"',
                'GAME_DAY_SIMULATE_URL := "http://127.0.0.1:8765/v3/game-day/simulate"',
                'ROSTER_URL := "http://127.0.0.1:8765/v3/roster"',
                'ROTATION_PREVIEW_URL := "http://127.0.0.1:8765/v3/rotation/preview"',
                'ROTATION_APPLY_URL := "http://127.0.0.1:8765/v3/rotation/apply"',
            )
        ),
        results,
    )
    check(
        "simulation_requires_explicit_confirmation",
        "CONFIRM & SIMULATE" in game_day and "simulate_armed" in game_day,
        results,
    )
    check(
        "simulation_accepts_only_verified_commit",
        all(
            token in game_day
            for token in (
                'parsed.get("status"',
                'parsed.get("persisted_after_reload"',
                'parsed.get("active_v2_unchanged"',
            )
        ),
        results,
    )
    check(
        "rotation_requires_preview_before_apply",
        "rotation_validated_body" in game_day
        and "Preview validation is required again before Apply." in game_day
        and "ENGINE PREVIEW PASSED" in game_day,
        results,
    )
    check(
        "rotation_rules_match_production_contract",
        all(
            token in game_day
            for token in (
                'required_starters',
                'minimum_game_players',
                'maximum_rotation_players',
                'required_total_minutes',
                'maximum_player_minutes',
            )
        ),
        results,
    )
    check(
        "full_box_score_ui_present",
        all(
            token in game_day
            for token in (
                'player_box_scores',
                'field_goals_made',
                'field_goals_attempted',
                'three_pointers_made',
                'three_pointers_attempted',
                'turnovers',
                'rebounds',
                'assists',
                'steals',
                'blocks',
            )
        ),
        results,
    )
    check(
        "postgame_horizontal_scroll_disabled",
        "scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED" in game_day,
        results,
    )
    check(
        "postgame_two_team_width_budget_compact",
        all(
            token in game_day
            for token in (
                '_box_cell("PLAYER", 126, MUTED)',
                '_box_cell("FG", 50, MUTED, HORIZONTAL_ALIGNMENT_CENTER)',
                '_box_cell("3PT", 50, MUTED, HORIZONTAL_ALIGNMENT_CENTER)',
                'teams.add_theme_constant_override("separation", 10)',
                'postgame_active_box = _card_body(active_card, 10)',
                'postgame_opponent_box = _card_body(opponent_card, 10)',
            )
        )
        and '_box_cell("PLAYER", 145, MUTED)' not in game_day
        and '_box_cell("3PT", 64, MUTED, HORIZONTAL_ALIGNMENT_CENTER)' not in game_day,
        results,
    )
    check(
        "production_game_day_routes_unchanged",
        all(
            token in server
            for token in (
                'Route("/v3/game-day", game_day_summary, methods=["GET"])',
                'Route("/v3/game-day/simulate", game_day_simulate, methods=["POST"])',
                'Route("/v3/rotation/preview", rotation_preview, methods=["POST"])',
                'Route("/v3/rotation/apply", rotation_apply, methods=["POST"])',
            )
        ),
        results,
    )
    check(
        "production_simulation_safety_contract_present",
        all(
            token in server
            for token in (
                "copy.deepcopy(state)",
                "simulate_scheduled_game(",
                "catch_up_cpu_schedule_v1(",
                "validate_simulation_league_state(updated)",
                '"persisted_after_reload": True',
                '"active_v2_unchanged": True',
            )
        ),
        results,
    )
    check(
        "batch14_bridge_contract_preserved_after_later_batches",
        git_path_unchanged("desktop_bridge/server.py")
        or (
            'Route("/v3/game-day", game_day_summary, methods=["GET"])' in server
            and 'Route("/v3/game-day/simulate", game_day_simulate, methods=["POST"])' in server
            and 'Route("/v3/rotation/preview", rotation_preview, methods=["POST"])' in server
            and 'Route("/v3/rotation/apply", rotation_apply, methods=["POST"])' in server
        ),
        results,
    )
    check(
        "batch14_did_not_modify_single_game_engine",
        git_path_unchanged("src/single_game_simulator_v1.py"),
        results,
    )
    check(
        "batch14_did_not_modify_calendar_sync_engine",
        git_path_unchanged("src/franchise_game_day_league_calendar_sync_v1.py"),
        results,
    )
    compile_files(results)

    return {
        "main_path": str(main_path),
        "game_day_path": str(game_day_path),
        "server_path": str(server_path),
    }


def dynamic_checks(results: dict[str, bool]) -> dict[str, Any]:
    working = Path(V3_WORKING_CHECKPOINT_PATH)
    v2 = Path(DEFAULT_CHECKPOINT_PATH)
    working_before = sha256(working)
    v2_before = sha256(v2)
    detail: dict[str, Any] = {}

    try:
        checkpoint = load_franchise_checkpoint(path=working, allow_backup=False)
        if checkpoint is None:
            raise RuntimeError("V3 working checkpoint could not be loaded.")

        team = _active_team_from_checkpoint(checkpoint)
        if not team:
            raise RuntimeError("Active franchise team is missing from the V3 checkpoint.")

        state = checkpoint.simulation_state
        game_day = _game_day_payload(state, team)
        roster = _roster_payload(
            state,
            team,
            source="v3_working_checkpoint",
            editable=True,
        )

        check(
            "dynamic_game_day_uses_v3_working_save",
            game_day.get("source") == "v3_working_checkpoint"
            and game_day.get("working_save_only") is True,
            results,
        )
        check(
            "dynamic_game_day_protects_v2",
            game_day.get("active_v2_read_only") is True,
            results,
        )
        check(
            "dynamic_roster_is_v3_editable_only",
            roster.get("source") == "v3_working_checkpoint"
            and roster.get("editable") is True
            and roster.get("active_v2_read_only") is True,
            results,
        )
        check(
            "dynamic_rotation_rules_exposed",
            dict(roster.get("rotation_rules", {}) or {}).get("required_starters") == 5
            and float(
                dict(roster.get("rotation_rules", {}) or {}).get(
                    "required_total_minutes", 0.0
                )
            )
            == 240.0,
            results,
        )
        check(
            "dynamic_roster_rows_present",
            len(list(roster.get("players", []) or [])) > 0,
            results,
        )

        next_game = game_day.get("next_game")
        if isinstance(next_game, dict):
            rotation = dict(game_day.get("rotation", {}) or {})
            check(
                "dynamic_next_game_rotation_present",
                len(list(rotation.get("rotation_player_ids", []) or [])) > 0
                and abs(float(rotation.get("total_minutes", 0.0)) - 240.0) <= 0.1,
                results,
            )
            check(
                "dynamic_game_plan_context_present",
                "coaching_alerts" in game_day and "unavailable_players" in game_day,
                results,
            )
        else:
            check("dynamic_next_game_rotation_present", True, results)
            check("dynamic_game_plan_context_present", True, results)

        last_game = game_day.get("last_game")
        if isinstance(last_game, dict):
            box_rows = list(last_game.get("player_box_scores", []) or [])
            box_contract_ok = bool(box_rows)
            if box_rows:
                required = {
                    "name",
                    "team",
                    "minutes",
                    "points",
                    "rebounds",
                    "assists",
                    "steals",
                    "blocks",
                    "turnovers",
                    "field_goals_made",
                    "field_goals_attempted",
                    "three_pointers_made",
                    "three_pointers_attempted",
                }
                box_contract_ok = required.issubset(set(box_rows[0].keys()))
            check("dynamic_full_box_score_contract", box_contract_ok, results)
        else:
            check("dynamic_full_box_score_contract", True, results)

        detail = {
            "season": game_day.get("season"),
            "phase": game_day.get("phase"),
            "team": team,
            "record": dict(game_day.get("record", {}) or {}).get("display"),
            "next_game": next_game,
            "last_game_id": (
                last_game.get("game_id") if isinstance(last_game, dict) else None
            ),
            "last_game_box_rows": (
                len(list(last_game.get("player_box_scores", []) or []))
                if isinstance(last_game, dict)
                else 0
            ),
            "roster_rows": len(list(roster.get("players", []) or [])),
            "rotation_rules": roster.get("rotation_rules", {}),
        }
    except Exception as exc:
        for name in (
            "dynamic_game_day_uses_v3_working_save",
            "dynamic_game_day_protects_v2",
            "dynamic_roster_is_v3_editable_only",
            "dynamic_rotation_rules_exposed",
            "dynamic_roster_rows_present",
            "dynamic_next_game_rotation_present",
            "dynamic_game_plan_context_present",
            "dynamic_full_box_score_contract",
        ):
            if name not in results:
                check(name, False, results)
        detail = {
            "exception_type": type(exc).__name__,
            "failure_reason": str(exc),
        }

    working_after = sha256(working)
    v2_after = sha256(v2)
    check(
        "validator_never_changes_working_save",
        working_before is not None and working_before == working_after,
        results,
    )
    check(
        "validator_never_changes_v2_checkpoint",
        v2_before is not None and v2_before == v2_after,
        results,
    )
    return detail


def godot_parser_check(results: dict[str, bool]) -> dict[str, Any]:
    executable = shutil.which("godot4") or shutil.which("godot")
    if not executable:
        print("Godot parser: SKIP (Godot CLI not on PATH; static wiring checks only)")
        return {"status": "skipped", "reason": "Godot CLI not on PATH"}

    try:
        proc = subprocess.run(
            [
                executable,
                "--headless",
                "--path",
                str(ROOT / "godot_client"),
                "--editor",
                "--quit",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        ok = proc.returncode == 0
        check("godot_project_parses", ok, results)
        if not ok:
            print("Godot parser stderr tail:")
            print((proc.stderr or proc.stdout or "")[-2000:])
        return {
            "status": "passed" if ok else "failed",
            "returncode": proc.returncode,
            "output_tail": (proc.stderr or proc.stdout or "")[-2000:],
        }
    except Exception as exc:
        check("godot_project_parses", False, results)
        return {
            "status": "failed",
            "exception_type": type(exc).__name__,
            "detail": str(exc),
        }


def main() -> int:
    print("=" * 88)
    print("V3 BATCH 14.0.1 GAME DAY + BOX SCORE LAYOUT VALIDATION")
    print("=" * 88)
    results: dict[str, bool] = {}
    static_detail = static_checks(results)
    dynamic_detail = dynamic_checks(results)

    print(
        "\nDynamic live probe: "
        + ("PASS" if results.get("dynamic_game_day_uses_v3_working_save") else "FAIL")
    )
    if "failure_reason" in dynamic_detail:
        print(f"  Failure reason: {dynamic_detail['failure_reason']}")
        print(f"  Exception type: {dynamic_detail.get('exception_type', '')}")
    else:
        print(f"  Season: {dynamic_detail.get('season')}")
        print(f"  Phase: {dynamic_detail.get('phase')}")
        print(f"  Team: {dynamic_detail.get('team')} ({dynamic_detail.get('record')})")
        next_game = dynamic_detail.get("next_game")
        if isinstance(next_game, dict):
            print(
                "  Next game: "
                f"{next_game.get('matchup')} • Day {next_game.get('day_index')}"
            )
        else:
            print("  Next game: none scheduled")
        print(f"  Roster rows: {dynamic_detail.get('roster_rows')}")
        print(f"  Latest box-score rows: {dynamic_detail.get('last_game_box_rows')}")

    parser_detail = godot_parser_check(results)

    passed = all(results.values())
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(
            {
                "passed": passed,
                "checks": results,
                "static": static_detail,
                "dynamic": dynamic_detail,
                "godot_parser": parser_detail,
            },
            indent=2,
            sort_keys=True,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"Report: {REPORT_PATH}")
    print()
    print("BATCH 14.0.1 VALIDATION PASSED" if passed else "BATCH 14.0.1 VALIDATION FAILED")
    print("No game, rotation, or other franchise action was durably executed by this validator.")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
