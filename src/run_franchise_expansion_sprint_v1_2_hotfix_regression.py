from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


class Box:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    checks: dict[str, bool] = {}

    # Load new sprint modules against the real project dependencies when present.
    roster = _load("roster_v12_regression", root / "src" / "franchise_roster_rotation_headquarters_v1.py")
    scouting = _load("scouting_v12_regression", root / "src" / "franchise_scouting_discovery_v1.py")

    # Rotation remains exact after the duplicate-display hotfix.
    state = Box(settings=Box(season_label="2027-28"), players={}, player_season_totals={}, standings={"CHI": Box(wins=0, losses=0)})
    positions = ["PG", "SG", "SF", "PF", "C", "PG", "SG", "SF", "PF", "C", "SG"]
    rows = []
    for idx in range(11):
        pid = f"P{idx+1}"
        overall = 90 - idx * 2
        player = Box(
            player_id=pid,
            player_name=f"Player {idx+1}",
            overall_rating=float(overall),
            potential_rating=float(min(96, overall + 5)),
            position=positions[idx],
            age=float(21 + idx),
            draft_pick=(idx + 1 if idx < 2 else None),
            rookie_season=("2027-28" if idx < 2 else ""),
            contract=Box(years_remaining=2),
        )
        state.players[pid] = player
        state.player_season_totals[pid] = Box(games_played=1, minutes=20.0)
        rows.append({
            "player_id": pid,
            "player": player.player_name,
            "position": player.position,
            "age": player.age,
            "overall": player.overall_rating,
            "starter": idx < 5,
            "in_rotation": idx < 10,
            "minutes": [34, 32, 31, 30, 29, 24, 22, 16, 12, 10, 0][idx],
            "rotation_order": idx + 1 if idx < 10 else 99,
            "availability": "healthy",
            "fatigue": 0.0,
        })
    state.teams = {"CHI": Box(roster_player_ids=tuple(state.players), rotation=Box(starter_ids=(), rotation_player_ids=(), minutes_targets={}))}
    rec = roster.build_rotation_recommendation_v1(state, "CHI", rows, philosophy="Balanced")
    checks["rotation_still_exact_240"] = abs(sum(row["minutes"] for row in rec if row["in_rotation"]) - 240.0) < 0.11
    checks["rotation_still_five_starters"] = sum(bool(row["starter"]) for row in rec) == 5

    # Season-long scouting phase is accepted and advances normally.
    scouting.team_staff_effects = lambda state, team, ensure=True: Box(
        scouting_current_accuracy=82.0,
        scouting_potential_accuracy=80.0,
    )
    scouting.scouting_error_band = lambda state, team, potential=False: 5.2 if not potential else 5.6
    prospects = [
        {
            "prospect_id": f"GEN-2028-{idx+1:03d}",
            "player_name": f"Prospect {idx+1}",
            "position": positions[idx % len(positions)],
            "age": 19.0 + idx * 0.2,
            "school": "Illinois",
            "archetype": "Two-Way Wing",
            "hidden_overall": 66.0 + idx,
            "hidden_potential": 80.0 + idx,
            "big_board_rank": idx + 1,
            "projected_range": "Lottery",
            "drafted": False,
        }
        for idx in range(8)
    ]
    state.franchise_draft_state_v1 = {"draft_year": 2028, "phase": "season_scouting", "prospects": prospects}
    before = scouting.scouting_board_rows_v1(state, "CHI")
    scouting.set_scouting_focus_v1(state, "CHI", [prospects[0]["prospect_id"]])
    scouting.advance_scouting_week_v1(state, "CHI")
    after = scouting.scouting_board_rows_v1(state, "CHI")
    b = {row["prospect_id"]: row for row in before}
    a = {row["prospect_id"]: row for row in after}
    checks["season_scouting_board_populates"] = len(after) == len(prospects)
    checks["season_scouting_confidence_advances"] = a[prospects[0]["prospect_id"]]["Confidence"] > b[prospects[0]["prospect_id"]]["Confidence"]

    # Load the Draft engine with only its forfeiture dependency stubbed if the
    # full project dependency is unavailable. This exercises the new state flow.
    if "franchise_draft_forfeitures_v1" not in sys.modules:
        try:
            __import__("franchise_draft_forfeitures_v1")
        except Exception:
            stub = types.ModuleType("franchise_draft_forfeitures_v1")
            stub.expected_draft_pick_count = lambda *args, **kwargs: 60
            stub.is_forfeited_source_asset = lambda *args, **kwargs: False
            sys.modules["franchise_draft_forfeitures_v1"] = stub
    engine = _load("draft_engine_v12_regression", root / "src" / "franchise_draft_engine_v1.py")

    draft_state = Box(
        settings=Box(season_label="2027-28", random_seed=1234),
        season_history=[Box(season_label="2026-27")],
    )
    current = engine.initialize_regular_season_scouting_state(
        draft_state,
        controlled_teams=("CHI",),
        class_strength=5,
    )
    checks["regular_season_draft_class_created"] = current.get("phase") == "season_scouting" and len(current.get("prospects", [])) == engine.DRAFT_CLASS_SIZE
    checks["regular_season_draft_year_correct"] = int(current.get("draft_year", -1)) == 2028
    checks["lottery_not_prematurely_resolved"] = not current.get("lottery_order") and not current.get("draft_order")

    # Static box-score contract: makes-attempts and percentages are both present.
    page_text = (root / "pages" / "5_Franchise_Mode.py").read_text(encoding="utf-8")
    checks["box_score_has_fg_verification_columns"] = '"FG": f"{field_goals_made}-{field_goals_attempted}"' in page_text and '"FG%": fg_pct' in page_text
    checks["box_score_has_3pt_verification_columns"] = '"3PT": f"{three_pointers_made}-{three_pointers_attempted}"' in page_text and '"3PT%": three_pct' in page_text

    failed = [name for name, ok in checks.items() if not ok]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE EXPANSION SPRINT V1.2 HOTFIX REGRESSION FAILED")
        return 1
    print("FRANCHISE EXPANSION SPRINT V1.2 HOTFIX REGRESSION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
