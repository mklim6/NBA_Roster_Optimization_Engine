from __future__ import annotations

import importlib.util
import sys
import types
from dataclasses import dataclass
from pathlib import Path


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Box:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))

    morale = _load("morale_regression", root / "src" / "franchise_morale_chemistry_v1.py")
    roster = _load("roster_regression", root / "src" / "franchise_roster_rotation_headquarters_v1.py")
    scouting = _load("scouting_regression", root / "src" / "franchise_scouting_discovery_v1.py")

    checks = {}

    # ---------------- synthetic roster / morale state ----------------
    state = Box()
    state.settings = Box(season_label="2027-28")
    state.current_day_index = 12
    state.players = {}
    state.player_season_totals = {}
    state.standings = {"CHI": Box(wins=6, losses=4)}
    rows = []
    positions = ["PG", "SG", "SF", "PF", "C", "PG", "SG", "SF", "PF", "C", "SG"]
    for idx in range(11):
        pid = f"P{idx+1}"
        overall = 90 - idx * 2
        age = 21 + idx
        player = Box(
            player_id=pid,
            player_name=f"Player {idx+1}",
            team_abbreviation="CHI",
            overall_rating=float(overall),
            potential_rating=float(min(96, overall + (8 if idx < 5 else 4))),
            position=positions[idx],
            age=float(age),
            draft_pick=(idx + 1 if idx < 3 else None),
            rookie_season=("2027-28" if idx < 2 else ""),
            contract=Box(years_remaining=(1 if idx in {3, 7} else 3)),
        )
        state.players[pid] = player
        state.player_season_totals[pid] = Box(games_played=10, minutes=(32 - idx * 1.5) * 10)
        rows.append({
            "player_id": pid,
            "player": player.player_name,
            "position": player.position,
            "age": age,
            "overall": overall,
            "starter": idx < 5,
            "in_rotation": idx < 10,
            "minutes": [34,32,31,30,29,24,22,16,12,10,0][idx],
            "rotation_order": idx + 1 if idx < 10 else 99,
            "availability": "healthy",
            "fatigue": 10 + idx,
        })
    state.teams = {
        "CHI": Box(
            roster_player_ids=tuple(state.players),
            rotation=Box(
                starter_ids=tuple(f"P{i}" for i in range(1, 6)),
                rotation_player_ids=tuple(f"P{i}" for i in range(1, 11)),
                minutes_targets={f"P{i+1}": [34,32,31,30,29,24,22,16,12,10][i] for i in range(10)},
            ),
        )
    }

    rec_bal = roster.build_rotation_recommendation_v1(state, "CHI", rows, philosophy="Balanced")
    rec_dev = roster.build_rotation_recommendation_v1(state, "CHI", rows, philosophy="Development")
    checks["balanced_exact_240"] = abs(sum(r["minutes"] for r in rec_bal if r["in_rotation"]) - 240.0) < 0.11
    checks["balanced_five_starters"] = sum(r["starter"] for r in rec_bal) == 5
    starter_minutes = sorted([r["minutes"] for r in rec_bal if r["starter"]], reverse=True)
    bench_minutes = sorted([r["minutes"] for r in rec_bal if r["in_rotation"] and not r["starter"]], reverse=True)
    checks["starters_receive_starter_minutes"] = min(starter_minutes) >= max(bench_minutes) if bench_minutes else True
    checks["balanced_at_least_eight_rotation"] = sum(r["in_rotation"] for r in rec_bal) >= 8
    checks["development_exact_240"] = abs(sum(r["minutes"] for r in rec_dev if r["in_rotation"]) - 240.0) < 0.11

    snapshot = morale.morale_snapshot_v1(state, "CHI")
    checks["morale_snapshot_has_all_players"] = len(snapshot["players"]) == 11
    checks["chemistry_bounded"] = 10.0 <= snapshot["chemistry"] <= 96.0
    before = {row["player_id"]: row["score"] for row in snapshot["players"]}
    game = Box(game_id="G1", home_team="CHI", away_team="NYK")
    # Add a minimal opponent so update can run both teams.
    state.teams["NYK"] = Box(roster_player_ids=(), rotation=Box(starter_ids=(), rotation_player_ids=(), minutes_targets={}))
    state.standings["NYK"] = Box(wins=4, losses=6)
    morale.update_morale_after_game_v1(state, game)
    payload = getattr(state, morale.MORALE_STATE_ATTR)
    checks["morale_persists_after_game"] = bool(payload["players"]) and "G1" in payload["processed_game_ids"]
    morale.update_morale_after_game_v1(state, game)
    checks["morale_game_hook_idempotent"] = payload["processed_game_ids"].count("G1") == 1

    # ---------------- scouting synthetic state ----------------
    # Stub staff system functions to deterministic values before direct calls.
    scouting.team_staff_effects = lambda state, team, ensure=True: Box(
        scouting_current_accuracy=82.0,
        scouting_potential_accuracy=80.0,
    )
    scouting.scouting_error_band = lambda state, team, potential=False: 5.2 if not potential else 5.6
    prospects = []
    for idx in range(8):
        prospects.append({
            "prospect_id": f"GEN-2028-{idx+1:03d}",
            "player_name": f"Prospect {idx+1}",
            "position": positions[idx % len(positions)],
            "age": 19.0 + idx * 0.3,
            "school": "Illinois",
            "archetype": "Two-Way Wing",
            "hidden_overall": 66.0 + idx,
            "hidden_potential": 80.0 + idx,
            "big_board_rank": idx + 1,
            "projected_range": "Lottery",
            "drafted": False,
        })
    state.franchise_draft_state_v1 = {
        "draft_year": 2028,
        "phase": "scouting",
        "prospects": prospects,
    }
    initial = scouting.scouting_board_rows_v1(state, "CHI")
    scouting.set_scouting_focus_v1(state, "CHI", [prospects[0]["prospect_id"], prospects[1]["prospect_id"]])
    for _ in range(3):
        scouting.advance_scouting_week_v1(state, "CHI")
    later = scouting.scouting_board_rows_v1(state, "CHI")
    by_id_initial = {row["prospect_id"]: row for row in initial}
    by_id_later = {row["prospect_id"]: row for row in later}
    focus_id = prospects[0]["prospect_id"]
    checks["focused_confidence_increases"] = by_id_later[focus_id]["Confidence"] > by_id_initial[focus_id]["Confidence"]
    checks["scouting_week_persists"] = scouting.scouting_summary_v1(state, "CHI")["weeks_completed"] == 3
    ai_est = scouting.ai_scouted_estimate_v1(state, "CHI", prospects[0])
    checks["ai_scouting_is_bounded"] = 45 <= ai_est["overall"] <= 99 and 45 <= ai_est["potential"] <= 99

    failed = [name for name, ok in checks.items() if not ok]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE EXPANSION SPRINT V1 REGRESSION FAILED")
        return 1
    print("FRANCHISE EXPANSION SPRINT V1 REGRESSION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
