from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
# The validator exercises the pure read-only data builder. Streamlit is not
# required for this test environment, so provide a harmless import stub.
if "streamlit" not in sys.modules:
    sys.modules["streamlit"] = ModuleType("streamlit")
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_timeline_trophy_room_v1 import (  # noqa: E402
    FRANCHISE_TIMELINE_TROPHY_ROOM_VERSION,
    build_franchise_legacy_snapshot_v1,
)


def box(pid: str, team: str, pts: int, reb: int = 0, ast: int = 0):
    return SimpleNamespace(
        player_id=pid,
        team_abbreviation=team,
        points=pts,
        rebounds=reb,
        assists=ast,
    )


def game(gid: str, home: str, away: str, hs: int, as_: int, boxes):
    return SimpleNamespace(
        game_id=gid,
        home_team=home,
        away_team=away,
        home_score=hs,
        away_score=as_,
        player_box_scores=tuple(boxes),
    )


def schedule(day: int):
    return SimpleNamespace(day_index=day)


def fingerprint(value) -> str:
    def normalize(obj):
        if isinstance(obj, dict):
            return {str(k): normalize(v) for k, v in sorted(obj.items(), key=lambda x: str(x[0]))}
        if isinstance(obj, (list, tuple)):
            return [normalize(v) for v in obj]
        if hasattr(obj, "__dict__"):
            return normalize(vars(obj))
        return obj
    payload = json.dumps(normalize(value), sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    archived_game = game(
        "A1", "CHI", "BOS", 121, 109,
        [box("1", "CHI", 31, 8, 7), box("2", "CHI", 24, 4, 11), box("9", "BOS", 28)],
    )
    current_game = game(
        "C1", "NYK", "CHI", 103, 116,
        [box("1", "CHI", 29, 6, 9), box("3", "CHI", 26, 10, 3), box("8", "NYK", 27)],
    )
    archive = SimpleNamespace(
        season_label="2026-27",
        standings={"CHI": SimpleNamespace(wins=55, losses=27)},
        schedule={"A1": schedule(140)},
        completed_games={"A1": archived_game},
        champion="CHI",
        runner_up="BOS",
        conference_champions={"East": "CHI", "West": "BOS"},
        postseason_state=SimpleNamespace(champion="CHI"),
    )
    state = SimpleNamespace(
        settings=SimpleNamespace(season_label="2027-28"),
        standings={"CHI": SimpleNamespace(wins=2, losses=0)},
        schedule={"C1": schedule(3)},
        completed_games={"C1": current_game},
        season_history=[archive],
        players={
            "1": SimpleNamespace(player_name="Alpha Guard"),
            "2": SimpleNamespace(player_name="Beta Wing"),
            "3": SimpleNamespace(player_name="Gamma Big"),
            "4": SimpleNamespace(player_name="Delta Rookie"),
        },
        franchise_draft_history_v1=[
            {
                "draft_year": 2027,
                "source_season": "2026-27",
                "target_season": "2027-28",
                "draft_order": [
                    {
                        "owner_team": "CHI",
                        "overall_pick": 18,
                        "player_name": "Delta Rookie",
                        "position": "F",
                        "school": "Illinois",
                    }
                ],
            }
        ],
        franchise_transaction_history_v1=[
            {
                "season_label": "2027-28",
                "day_index": 2,
                "team_a": "CHI",
                "team_b": "LAL",
                "side_a_player_ids": ["2"],
                "side_b_player_ids": ["3"],
                "side_a_pick_asset_ids": [],
                "side_b_pick_asset_ids": ["PICK-2029-LAL-1"],
            }
        ],
        free_agency_transaction_history=[
            {
                "team_abbreviation": "CHI",
                "player_id": "4",
                "player_name": "Delta Rookie",
                "annual_salary": 9_500_000,
                "years": 3,
            }
        ],
        retirement_history=[],
    )
    before = fingerprint(state)
    payload = build_franchise_legacy_snapshot_v1(
        state=state,
        trade_state=SimpleNamespace(transaction_history=[]),
        active_team="CHI",
        team_name_resolver=lambda code: {
            "CHI": "Chicago Bulls",
            "BOS": "Boston Celtics",
            "NYK": "New York Knicks",
            "LAL": "Los Angeles Lakers",
        }.get(code, code),
    )
    after = fingerprint(state)

    checks = {
        "version_present": payload["version"] == FRANCHISE_TIMELINE_TROPHY_ROOM_VERSION,
        "championship_detected": payload["championship_count"] == 1,
        "finals_detected": payload["finals_count"] == 1,
        "best_season_real": payload["best_season"]["wins"] == 55,
        "games_aggregated": len(payload["games"]) == 2,
        "all_time_record": (payload["total_wins"], payload["total_losses"]) == (2, 0),
        "franchise_icons_real_boxes": payload["player_totals"][0]["player_name"] == "Alpha Guard",
        "timeline_has_season": any(e["category"] == "Season" for e in payload["timeline"]),
        "timeline_has_draft": any(e["category"] == "Draft" for e in payload["timeline"]),
        "timeline_has_trade": any(e["category"] == "Trade" for e in payload["timeline"]),
        "timeline_has_signing": any(e["category"] == "Signing" for e in payload["timeline"]),
        "builder_read_only": before == after,
    }

    page = (ROOT / "pages" / "5_Franchise_Mode.py").read_text(encoding="utf-8")
    checks.update(
        {
            "legacy_nav_present": '"Franchise Legacy"' in page,
            "legacy_renderer_wired": "render_franchise_timeline_trophy_room_v1(" in page,
            "home_preview_wired": "render_franchise_legacy_preview_v1(" in page,
            "legacy_css_wired": "inject_franchise_legacy_visuals_v1(" in page,
            "game_navigation_preserved": "FRANCHISE_GAME_NAVIGATION_V1" in page,
            "runtime_bridge_preserved": "franchise_game_flow_runtime_bridge_v1" in page,
        }
    )

    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        print("FRANCHISE TIMELINE + TROPHY ROOM V1 VALIDATOR FAILED")
        for name in failed:
            print(f"  FAIL: {name}")
        return 2

    print("FRANCHISE TIMELINE + TROPHY ROOM V1 VALIDATOR PASSED")
    print(f"Version: {FRANCHISE_TIMELINE_TROPHY_ROOM_VERSION}")
    print("Durable season history -> trophy room: YES")
    print("Draft / trade / signing timeline: YES")
    print("Franchise records from saved game results: YES")
    print("Franchise icons from saved player box scores: YES")
    print("Command Center legacy preview: YES")
    print("Game Navigation V1 preserved: YES")
    print("Simulation / save mutation: NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
