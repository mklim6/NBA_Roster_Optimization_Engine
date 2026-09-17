from __future__ import annotations

import ast
import importlib.util
import json
import py_compile
from pathlib import Path
from types import SimpleNamespace


VERSION = "franchise-game-day-broadcast-center-v2-validator-2026-09-11"
ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "franchise_game_day_broadcast_v1.py"
PAGE_PATH = ROOT / "pages" / "5_Franchise_Mode.py"


def _player(player_id: str, team: str, name: str, ovr: float) -> SimpleNamespace:
    return SimpleNamespace(
        player_id=player_id,
        player_name=name,
        team_abbreviation=team,
        position="G",
        overall_rating=ovr,
        potential_rating=ovr + 2,
    )


def _box(player_id: str, team: str, *, pts: int, reb: int, ast: int, fgm: int, fga: int, tpm: int, tpa: int, ftm: int, fta: int, tov: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        player_id=player_id,
        team_abbreviation=team,
        points=pts,
        rebounds=reb,
        assists=ast,
        steals=1,
        blocks=0,
        turnovers=tov,
        field_goals_made=fgm,
        field_goals_attempted=fga,
        three_pointers_made=tpm,
        three_pointers_attempted=tpa,
        free_throws_made=ftm,
        free_throws_attempted=fta,
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
    except Exception as exc:  # pragma: no cover
        compile_error = str(exc)
    try:
        spec = importlib.util.spec_from_file_location("franchise_game_day_broadcast_v1", MODULE_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to load broadcast module")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover
        import_error = str(exc)

    helper_checks = {
        "featured_player_uses_real_rotation": False,
        "postgame_headline_uses_real_result": False,
        "team_stat_totals_use_box_score": False,
        "next_matchup_comes_from_schedule": False,
    }
    if module is not None:
        players = {
            "1": _player("1", "AAA", "Alpha Star", 91),
            "2": _player("2", "AAA", "Alpha Two", 82),
            "11": _player("11", "BBB", "Beta Star", 89),
            "12": _player("12", "BBB", "Beta Two", 81),
        }
        state = SimpleNamespace(
            players=players,
            teams={
                "AAA": SimpleNamespace(rotation=SimpleNamespace(starter_ids=("1", "2"), rotation_player_ids=("1", "2"))),
                "BBB": SimpleNamespace(rotation=SimpleNamespace(starter_ids=("11", "12"), rotation_player_ids=("11", "12"))),
            },
            standings={
                "AAA": SimpleNamespace(games_played=10, wins=7, losses=3, points_for=1140, points_against=1090, streak_type="W", streak_length=3),
                "BBB": SimpleNamespace(games_played=10, wins=5, losses=5, points_for=1100, points_against=1100, streak_type="L", streak_length=1),
            },
            injuries={},
            player_season_totals={
                "1": SimpleNamespace(games_played=10, points=250, rebounds=60, assists=80),
                "11": SimpleNamespace(games_played=10, points=220, rebounds=50, assists=50),
            },
            schedule={
                "G1": SimpleNamespace(game_id="G1", day_index=4, home_team="BBB", away_team="AAA"),
                "G2": SimpleNamespace(game_id="G2", day_index=7, home_team="AAA", away_team="CCC"),
            },
            completed_games={},
        )
        completed = SimpleNamespace(
            game_id="G1",
            home_team="BBB",
            away_team="AAA",
            home_score=106,
            away_score=109,
            overtime_periods=0,
            player_box_scores=(
                _box("1", "AAA", pts=31, reb=7, ast=9, fgm=11, fga=20, tpm=4, tpa=8, ftm=5, fta=6, tov=2),
                _box("2", "AAA", pts=12, reb=5, ast=2, fgm=5, fga=10, tpm=1, tpa=3, ftm=1, fta=2, tov=1),
                _box("11", "BBB", pts=28, reb=6, ast=4, fgm=10, fga=21, tpm=3, tpa=9, ftm=5, fta=5, tov=3),
                _box("12", "BBB", pts=15, reb=8, ast=3, fgm=6, fga=12, tpm=1, tpa=4, ftm=2, fta=2, tov=2),
            ),
        )
        state.completed_games = {"G1": completed}
        headline, _ = module._broadcast_headline(completed, lambda code: {"AAA": "Alpha", "BBB": "Beta"}.get(code, code))
        totals = module._team_box_totals(completed, "AAA")
        next_game = module._next_game_for_team(state, "AAA", "G1")
        featured = module._featured_player(state, "AAA")
        helper_checks = {
            "featured_player_uses_real_rotation": bool(featured and featured["player_id"] == "1" and featured["season"]["ppg"] == 25.0),
            "postgame_headline_uses_real_result": "Alpha" in headline and "Beta" in headline and "one-possession" in headline,
            "team_stat_totals_use_box_score": totals["fgm"] == 16 and totals["reb"] == 12 and totals["ast"] == 11,
            "next_matchup_comes_from_schedule": next_game is state.schedule["G2"],
        }

    checks = {
        "module_exists": MODULE_PATH.exists(),
        "page_exists": PAGE_PATH.exists(),
        "module_and_page_compile": not compile_error,
        "module_imports": not import_error,
        "v1_api_version_preserved": "franchise-game-day-broadcast-v1.0-2026-09-11" in module_text,
        "v2_center_version_current": "franchise-game-day-broadcast-center-v2.0-2026-09-11" in module_text,
        "cinematic_matchup_scoreboard_exists": "BROADCAST CENTER" in module_text and "fgb-scoreboard" in module_text,
        "player_spotlight_exists": "PLAYER SPOTLIGHT" in module_text and "_featured_player" in module_text,
        "season_average_spotlight_exists": "PPG" in module_text and "RPG" in module_text and "APG" in module_text,
        "matchup_profile_meter_exists": "fgb-edge-track" in module_text and "not a win probability" in module_text,
        "projected_starters_preserved": "Projected starting lineups" in module_text,
        "keys_to_game_preserved": "_keys_to_game" in module_text,
        "postgame_headline_exists": "POSTGAME · BROADCAST RECAP" in module_text and "_broadcast_headline" in module_text,
        "postgame_team_comparison_exists": "fgb-poststats" in module_text and "FG%" in module_text and "3PT%" in module_text,
        "box_score_leaders_preserved": "_leader_rows" in module_text and "GAME LEADER" in module_text,
        "next_matchup_handoff_exists": "NEXT UP" in module_text and "_next_game_for_team" in module_text,
        "page_passes_active_team_to_final": "active_team=active_team" in page_text,
        "page_passes_real_date_to_next_game": "game_date_resolver=lambda day_index" in page_text,
        "duplicate_final_score_metrics_removed": 'st.markdown("### Latest committed result")' not in page_text,
        "full_box_score_is_collapsed": '"Full box score & medical report"' in page_text and "expanded=False" in page_text,
        "pregame_medical_detail_is_collapsible": '"Medical & workload report"' in page_text,
        "presentation_layer_does_not_write_files": ".write_text(" not in module_text and "open(" not in module_text,
        "presentation_layer_does_not_commit_game": "commit_game" not in module_text and "set_franchise_state" not in module_text,
        "responsive_rules_exist": "@media(max-width:600px)" in module_text,
        "reduced_motion_rules_exist": "prefers-reduced-motion" in module_text,
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
    print("\nFRANCHISE GAME DAY BROADCAST CENTER V2 VALIDATOR PASSED")


if __name__ == "__main__":
    main()
