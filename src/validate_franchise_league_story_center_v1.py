from __future__ import annotations

import json
import py_compile
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
MODULE = ROOT / "src" / "franchise_league_story_center_v1.py"
VERSION = "franchise-league-story-center-v1-validator-2026-09-11"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def main() -> int:
    page = _text(PAGE)
    module = _text(MODULE)
    checks = {
        "story_module_exists": MODULE.is_file(),
        "page_imports_story_center": "from franchise_league_story_center_v1 import" in page,
        "page_injects_story_visuals": "inject_franchise_league_story_visuals_v1(" in page,
        "story_nav_section_exists": '"League Stories"' in page,
        "story_nav_label_exists": '"League Stories": "Stories"' in page,
        "home_story_preview_exists": "render_league_story_preview_v1(" in page,
        "dedicated_story_center_exists": 'if active_section == "League Stories":' in page and "render_league_story_center_v1(" in page,
        "uses_saved_game_results": "completed_games" in module and "player_box_scores" in module,
        "uses_saved_player_totals": "player_season_totals" in module,
        "uses_saved_standings": "standings" in module and "streak_length" in module,
        "uses_saved_injuries": "injuries" in module and "games_remaining" in module,
        "uses_committed_trade_history": "franchise_transaction_history_v1" in module,
        "uses_committed_fa_history": "free_agency_transaction_history" in module,
        "uses_postseason_state": "postseason_state" in module,
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
        "import sys; "
        f"sys.path.insert(0, {str((ROOT / 'src').resolve())!r}); "
        "import franchise_league_story_center_v1 as m; "
        "assert m.FRANCHISE_LEAGUE_STORY_CENTER_VERSION == 'franchise-league-story-center-v1.0-2026-09-11'; "
        "assert callable(m.build_league_stories_v1); "
        "assert callable(m.render_league_story_center_v1); "
        "print('FRESH STORY IMPORT OK')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", fresh_import],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
    )
    checks["fresh_process_module_import"] = proc.returncode == 0

    mock_test = r'''
from types import SimpleNamespace as NS
from franchise_league_story_center_v1 import build_league_stories_v1
players={
 'p1':NS(player_name='Alpha Guard',team_abbreviation='CHI'),
 'p2':NS(player_name='Beta Wing',team_abbreviation='BOS'),
}
teams={'CHI':NS(conference='East'),'BOS':NS(conference='East')}
standings={
 'CHI':NS(team_abbreviation='CHI',games_played=3,wins=2,losses=1,points_for=330,points_against=320,streak_type='W',streak_length=2),
 'BOS':NS(team_abbreviation='BOS',games_played=3,wins=3,losses=0,points_for=350,points_against=310,streak_type='W',streak_length=3),
}
schedule={'g1':NS(game_id='g1',day_index=2,home_team='CHI',away_team='BOS',status='completed')}
box=(NS(player_id='p1',team_abbreviation='CHI',points=34,rebounds=7,assists=10,steals=1,blocks=0),)
completed={'g1':NS(game_id='g1',home_team='CHI',away_team='BOS',home_score=121,away_score=118,overtime_periods=1,player_box_scores=box)}
totals={'p1':NS(games_played=3,points=90,rebounds=21,assists=27),'p2':NS(games_played=3,points=75,rebounds=18,assists=15)}
injuries={'p2':NS(status='out',games_remaining=2,injury_type='ankle sprain')}
state=NS(players=players,teams=teams,standings=standings,schedule=schedule,completed_games=completed,player_season_totals=totals,injuries=injuries,current_day_index=2,settings=NS(season_label='2026-27'),franchise_transaction_history_v1=[{'transaction_id':'FTX-0001','team_a':'CHI','team_b':'BOS','side_a_player_ids':['p1'],'side_b_player_ids':['p2'],'side_a_pick_asset_ids':[],'side_b_pick_asset_ids':[],'day_index':2}],free_agency_transaction_history=[])
stories=build_league_stories_v1(state,active_team='CHI',team_name_resolver=lambda t:t)
assert stories
assert any(s.category == 'Games' for s in stories)
assert any(s.category == 'Players' for s in stories)
assert any(s.category == 'Standings' for s in stories)
assert any(s.category == 'Health' for s in stories)
assert any(s.category == 'Transactions' for s in stories)
print(len(stories))
'''
    proc2 = subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0, %r); %s" % (str((ROOT / 'src').resolve()), mock_test)],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
    )
    checks["deterministic_mock_story_generation"] = proc2.returncode == 0

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
    print("FRANCHISE LEAGUE STORY CENTER V1 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
