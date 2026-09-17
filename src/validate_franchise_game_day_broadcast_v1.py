from __future__ import annotations

import ast
import importlib.util
import json
import py_compile
from pathlib import Path
from types import SimpleNamespace


VERSION = "franchise-game-day-broadcast-v1-validator-2026-09-11"
ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "franchise_game_day_broadcast_v1.py"
PAGE_PATH = ROOT / "pages" / "5_Franchise_Mode.py"


def _player(player_id: str, team: str, rating: float) -> SimpleNamespace:
    return SimpleNamespace(
        player_id=player_id,
        player_name=f"Player {player_id}",
        team_abbreviation=team,
        position="G",
        overall_rating=rating,
    )


def main() -> None:
    module_text = MODULE_PATH.read_text(encoding="utf-8")
    page_text = PAGE_PATH.read_text(encoding="utf-8")
    compile_error = ""
    import_error = ""
    module = None
    try:
        ast.parse(module_text)
        py_compile.compile(str(MODULE_PATH), doraise=True)
        py_compile.compile(str(PAGE_PATH), doraise=True)
    except Exception as exc:  # pragma: no cover - validator reporting
        compile_error = str(exc)
    try:
        spec = importlib.util.spec_from_file_location("franchise_game_day_broadcast_v1", MODULE_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to load broadcast module")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - validator reporting
        import_error = str(exc)

    helper_checks = {
        "fixture_builds_five_starters": False,
        "fixture_calculates_real_record": False,
        "fixture_uses_real_box_score_leaders": False,
    }
    if module is not None:
        players = {
            **{str(index): _player(str(index), "AAA", 90 - index) for index in range(1, 9)},
            **{str(index): _player(str(index), "BBB", 88 - index) for index in range(11, 19)},
        }
        rotation_a = SimpleNamespace(starter_ids=("1", "2", "3", "4", "5"), rotation_player_ids=tuple(str(index) for index in range(1, 9)))
        rotation_b = SimpleNamespace(starter_ids=("11", "12", "13", "14", "15"), rotation_player_ids=tuple(str(index) for index in range(11, 19)))
        state = SimpleNamespace(
            players=players,
            teams={"AAA": SimpleNamespace(rotation=rotation_a), "BBB": SimpleNamespace(rotation=rotation_b)},
            standings={
                "AAA": SimpleNamespace(games_played=10, wins=6, losses=4, points_for=1120, points_against=1090, streak_type="W", streak_length=2),
                "BBB": SimpleNamespace(games_played=10, wins=5, losses=5, points_for=1100, points_against=1110, streak_type="L", streak_length=1),
            },
            injuries={},
            schedule={},
            completed_games={},
        )
        completed = SimpleNamespace(
            player_box_scores=(
                SimpleNamespace(player_id="1", team_abbreviation="AAA", points=30, rebounds=8, assists=7, steals=1, blocks=0),
                SimpleNamespace(player_id="11", team_abbreviation="BBB", points=22, rebounds=4, assists=5, steals=0, blocks=1),
            )
        )
        helper_checks = {
            "fixture_builds_five_starters": len(module._team_profile(state, "AAA")["starters"]) == 5,
            "fixture_calculates_real_record": module._team_record(state, "AAA")["record"] == "6-4" and module._team_record(state, "AAA")["margin"] == 3.0,
            "fixture_uses_real_box_score_leaders": module._leader_rows(state, completed)[0]["player_id"] == "1",
        }

    checks = {
        "module_exists": MODULE_PATH.exists(),
        "page_exists": PAGE_PATH.exists(),
        "module_and_page_compile": not compile_error,
        "module_imports": not import_error,
        "version_is_current": "franchise-game-day-broadcast-v1.0-2026-09-11" in module_text,
        "page_imports_broadcast_layer": "from franchise_game_day_broadcast_v1 import" in page_text,
        "page_injects_broadcast_visuals": "inject_game_day_broadcast_visuals_v1()" in page_text,
        "page_renders_pregame_broadcast": "render_game_day_broadcast_v1(" in page_text,
        "page_renders_committed_final": "render_game_day_final_v1(" in page_text,
        "broadcast_scoreboard_exists": "fgb-scoreboard" in module_text,
        "projected_lineups_exist": "Projected starting lineups" in module_text,
        "tale_of_tape_exists": "Tale of the tape" in module_text,
        "keys_to_game_exist": "_keys_to_game" in module_text,
        "recent_form_exists": "_form_html" in module_text,
        "postgame_leaders_exist": "_leader_rows" in module_text,
        "responsive_rules_exist": "@media(max-width:600px)" in module_text,
        "reduced_motion_rules_exist": "prefers-reduced-motion" in module_text,
        "presentation_layer_does_not_import_checkpoint": "checkpoint" not in module_text.lower(),
        "presentation_layer_does_not_write_files": ".write_text(" not in module_text and "open(" not in module_text,
        "presentation_layer_does_not_commit": "commit_game" not in module_text and "set_franchise_state" not in module_text,
        **helper_checks,
    }
    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "version": VERSION,
        "checks": checks,
        "compile_error": compile_error,
        "import_error": import_error,
        "failed_checks": failed,
        "passed": not failed,
    }
    print(json.dumps(report, indent=2))
    if failed:
        raise SystemExit(1)
    print("\nFRANCHISE GAME DAY BROADCAST V1 VALIDATOR PASSED")


if __name__ == "__main__":
    main()

