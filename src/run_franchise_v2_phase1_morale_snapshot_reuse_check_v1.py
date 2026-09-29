from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import franchise_morale_trade_market_v1 as market


def main() -> int:
    # Formula equivalence with the CPU morale response V1 implementation.
    responses = ("Keep internal", "Listening to offers", "On trade block", "Other")
    for response in responses:
        for active in (False, True):
            for core in (False, True):
                modifier = {
                    "Keep internal": 0.92,
                    "Listening to offers": 1.10,
                    "On trade block": 1.22,
                }.get(response, 1.0)
                if active:
                    modifier += 0.08
                if core:
                    modifier -= 0.08
                expected = round(max(0.78, min(1.35, modifier)), 3)
                observed = market._willingness_from_context_v1(
                    response=response,
                    request_active=active,
                    core_player=core,
                )
                assert observed == expected, (response, active, core, observed, expected)

    snapshot_calls = {"count": 0}
    willingness_calls = {"count": 0}
    original_snapshot = market.morale_snapshot_v1
    original_willingness = market.cpu_trade_willingness_modifier_v1
    original_response = market.trade_response_v1
    original_core = market._is_core_player_v1

    players = {
        "P1": SimpleNamespace(player_id="P1", player_name="One", overall_rating=75, potential_rating=78, age=28),
        "P2": SimpleNamespace(player_id="P2", player_name="Two", overall_rating=74, potential_rating=76, age=27),
        "P3": SimpleNamespace(player_id="P3", player_name="Three", overall_rating=73, potential_rating=75, age=26),
    }
    state = SimpleNamespace(players=players)
    rows = [
        {
            "player_id": pid,
            "score": 45.0 if pid == "P1" else 70.0,
            "trade_request_risk": 70.0 if pid == "P1" else 10.0,
            "trade_request_status": "Considering request" if pid == "P1" else "None",
            "trade_request_active": False,
        }
        for pid in players
    ]

    def fake_snapshot(_state, _team):
        snapshot_calls["count"] += 1
        return {"players": rows}

    def fake_willingness(_state, _team, _pid):
        willingness_calls["count"] += 1
        return 0.92

    try:
        market.morale_snapshot_v1 = fake_snapshot
        market.cpu_trade_willingness_modifier_v1 = fake_willingness
        market.trade_response_v1 = lambda _state, _team, _pid: (
            "Listening to offers" if _pid == "P1" else "Keep internal"
        )
        market._is_core_player_v1 = lambda _state, _pid: False

        decisions = tuple(
            SimpleNamespace(player_id=pid, asset_policy="Keep")
            for pid in players
        )
        result = market.apply_cpu_morale_trade_market_to_decisions_v1(
            state,
            "CHI",
            decisions,
        )
        assert len(result) == 3
        assert snapshot_calls["count"] == 1, snapshot_calls
        assert willingness_calls["count"] == 0, willingness_calls

        # Public one-player context without a supplied snapshot retains the
        # legacy external willingness path.
        market.morale_trade_market_context_v1(state, "CHI", "P2")
        assert snapshot_calls["count"] == 2, snapshot_calls
        assert willingness_calls["count"] == 1, willingness_calls
    finally:
        market.morale_snapshot_v1 = original_snapshot
        market.cpu_trade_willingness_modifier_v1 = original_willingness
        market.trade_response_v1 = original_response
        market._is_core_player_v1 = original_core

    print("FRANCHISE V2 PHASE 1 MORALE SNAPSHOT REUSE CHECK PASSED")
    print("Trade willingness formula equivalence: PASS")
    print("Batched team planning morale snapshots for 3 players: 1")
    print("Redundant CPU willingness snapshot calls in batch: 0")
    print("Public single-player context legacy path: PRESERVED")
    print("No franchise checkpoint was loaded or mutated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
