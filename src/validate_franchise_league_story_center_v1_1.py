from __future__ import annotations

import json
import py_compile
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
MODULE = ROOT / "src" / "franchise_league_story_center_v1.py"
VERSION = "franchise-league-story-center-v1.1-validator-2026-09-11"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def main() -> int:
    page = _text(PAGE)
    module = _text(MODULE)
    checks = {
        "story_module_exists": MODULE.is_file(),
        "module_version_v1_1": "franchise-league-story-center-v1.1-2026-09-11" in module,
        "page_imports_story_center": "from franchise_league_story_center_v1 import" in page,
        "home_story_preview_exists": "render_league_story_preview_v1(" in page,
        "dedicated_story_center_exists": 'if active_section == "League Stories":' in page,
        "league_stat_strip_exists": "fm-league-metric-strip" in module and "_league_snapshot_metrics_v1" in module,
        "player_shooting_specificity": all(token in module for token in ("field_goals_made", "three_pointers_made", "_true_shooting")),
        "story_stat_chips_exist": "fm-story-metrics" in module and "metrics: tuple[tuple[str, str]" in module,
        "standings_context_specificity": "_conference_rank" in module and "allowed" in module and "PPG" in module,
        "preview_story_diversity": "_select_preview_stories_v1" in module and "used_categories" in module,
        "league_pulse_compacted": "padding: .78rem .9rem .72rem .9rem" in module,
        "top_franchise_hero_compacted": "min-height:300px !important" in module and ".fxv2-team-hero" in module,
        "uses_saved_game_results": "completed_games" in module and "player_box_scores" in module,
        "uses_saved_player_totals": "player_season_totals" in module,
        "uses_saved_standings": "standings" in module and "streak_length" in module,
        "uses_saved_injuries": "injuries" in module,
        "uses_committed_trade_history": "franchise_transaction_history_v1" in module,
        "uses_committed_fa_history": "free_agency_transaction_history" in module,
        "does_not_use_randomness": "random." not in module and "import random" not in module,
        "does_not_mutate_simulation_state": "setattr(state" not in module and "state.completed_games[" not in module and "state.standings[" not in module,
        "premium_roster_preserved": "render_franchise_premium_roster_v1(" in page,
        "legacy_preserved": "render_franchise_timeline_trophy_room_v1(" in page,
        "native_navigation_preserved": "franchise_game_navigation_native_v2_2" in page,
    }

    compile_error = ""
    try:
        py_compile.compile(str(PAGE), doraise=True)
        py_compile.compile(str(MODULE), doraise=True)
        checks["python_compile"] = True
    except Exception as exc:
        checks["python_compile"] = False
        compile_error = str(exc)

    fresh_import = (
        "import sys, types; sys.modules.setdefault(\'streamlit\', types.ModuleType(\'streamlit\')); "
        f"sys.path.insert(0, {str((ROOT / 'src').resolve())!r}); "
        "import franchise_league_story_center_v1 as m; "
        "assert m.FRANCHISE_LEAGUE_STORY_CENTER_VERSION == 'franchise-league-story-center-v1.1-2026-09-11'; "
        "assert callable(m.build_league_stories_v1); "
        "assert callable(m.render_league_story_center_v1); "
        "print('FRESH STORY V1.1 IMPORT OK')"
    )
    proc = subprocess.run([sys.executable, "-c", fresh_import], cwd=str(ROOT), text=True, capture_output=True)
    checks["fresh_process_module_import"] = proc.returncode == 0

    mock_test = r'''
from types import SimpleNamespace as NS
from franchise_league_story_center_v1 import build_league_stories_v1, _league_snapshot_metrics_v1, _select_preview_stories_v1
players={
 'p1':NS(player_name='Alpha Guard',team_abbreviation='CHI'),
 'p2':NS(player_name='Beta Wing',team_abbreviation='BOS'),
 'p3':NS(player_name='Gamma Star',team_abbreviation='HOU'),
}
teams={'CHI':NS(conference='East'),'BOS':NS(conference='East'),'HOU':NS(conference='West')}
standings={
 'CHI':NS(team_abbreviation='CHI',games_played=5,wins=2,losses=3,points_for=560,points_against=575,streak_type='L',streak_length=2),
 'BOS':NS(team_abbreviation='BOS',games_played=5,wins=4,losses=1,points_for=590,points_against=530,streak_type='W',streak_length=3),
 'HOU':NS(team_abbreviation='HOU',games_played=5,wins=5,losses=0,points_for=610,points_against=550,streak_type='W',streak_length=5),
}
schedule={'g1':NS(game_id='g1',day_index=4,home_team='CHI',away_team='BOS',status='completed')}
box=(NS(player_id='p1',team_abbreviation='CHI',points=34,rebounds=7,assists=10,steals=1,blocks=0,field_goals_made=12,field_goals_attempted=21,three_pointers_made=4,three_pointers_attempted=9,free_throws_made=6,free_throws_attempted=7),)
completed={'g1':NS(game_id='g1',home_team='CHI',away_team='BOS',home_score=121,away_score=118,overtime_periods=1,player_box_scores=box)}
totals={
 'p1':NS(games_played=5,points=155,rebounds=35,assists=46,field_goals_made=55,field_goals_attempted=105),
 'p2':NS(games_played=5,points=125,rebounds=30,assists=25,field_goals_made=45,field_goals_attempted=95),
 'p3':NS(games_played=5,points=165,rebounds=28,assists=31,field_goals_made=60,field_goals_attempted=108),
}
injuries={'p2':NS(status='out',games_remaining=2,injury_type='ankle sprain')}
state=NS(players=players,teams=teams,standings=standings,schedule=schedule,completed_games=completed,player_season_totals=totals,injuries=injuries,current_day_index=4,settings=NS(season_label='2026-27'),franchise_transaction_history_v1=[],free_agency_transaction_history=[])
stories=build_league_stories_v1(state,active_team='CHI',team_name_resolver=lambda t:t)
assert stories
player_story=next(s for s in stories if s.category=='Players' and s.game_id=='g1')
assert any(label=='TS%' for label,value in player_story.metrics)
assert 'FG' in player_story.detail and 'TS%' in player_story.detail
streak_story=next(s for s in stories if s.story_id.startswith('streak:HOU'))
assert any(label=='CONF' for label,value in streak_story.metrics)
metrics=_league_snapshot_metrics_v1(state,team_name_resolver=lambda t:t)
assert len(metrics) >= 4
assert any(label=='Scoring leader' for label,value,detail in metrics)
preview=_select_preview_stories_v1(stories,limit=3)
assert len(preview)==3
assert len({s.category for s in preview}) >= 2
print(len(stories), metrics)
'''
    proc2 = subprocess.run(
        [sys.executable, "-c", "import sys, types; sys.modules.setdefault(\'streamlit\', types.ModuleType(\'streamlit\')); sys.path.insert(0, %r); %s" % (str((ROOT / 'src').resolve()), mock_test)],
        cwd=str(ROOT), text=True, capture_output=True,
    )
    checks["specific_stat_mock_generation"] = proc2.returncode == 0

    failed = [name for name, value in checks.items() if not value]
    report = {
        "version": VERSION,
        "checks": checks,
        "failed_checks": failed,
        "compile_error": compile_error,
        "fresh_import_stderr": proc.stderr.strip(),
        "mock_test_stderr": proc2.stderr.strip(),
        "passed": not failed,
    }
    print(json.dumps(report, indent=2))
    if failed:
        raise SystemExit(1)
    print("FRANCHISE LEAGUE STORY CENTER V1.1 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
