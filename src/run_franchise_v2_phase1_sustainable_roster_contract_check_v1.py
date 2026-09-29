from __future__ import annotations

import inspect
from types import SimpleNamespace

import franchise_free_agency_cpu_execution_v1 as execution
import franchise_free_agency_cpu_offer_generation_v1 as offer_generation


def _team_state(count: int) -> SimpleNamespace:
    return SimpleNamespace(
        roster_player_ids=tuple(f"P{i:02d}" for i in range(count))
    )


def main() -> int:
    state = SimpleNamespace(
        settings=SimpleNamespace(minimum_game_players=8),
        teams={
            "AAA": _team_state(8),
            "BBB": _team_state(13),
            "CCC": _team_state(14),
            "DDD": _team_state(15),
        },
    )

    target = execution.cpu_sustainable_roster_target(state)
    if target != 14:
        raise AssertionError(f"Expected sustainable target 14, observed {target}.")

    deficits = execution.cpu_sustainable_roster_deficits(state)
    observed = {team: (count, deficit) for team, count, deficit in deficits}
    expected = {
        "AAA": (8, 6),
        "BBB": (13, 1),
    }
    if observed != expected:
        raise AssertionError(
            f"Sustainable deficits mismatch. expected={expected}, observed={observed}"
        )

    controlled = execution.cpu_sustainable_roster_deficits(
        state,
        controlled_teams=("AAA",),
    )
    if any(team == "AAA" for team, _, _ in controlled):
        raise AssertionError("User-controlled teams must not be autonomously filled.")

    execution_sig = inspect.signature(
        execution.build_cpu_free_agency_execution_plan
    )
    board_sig = inspect.signature(
        offer_generation.build_cpu_free_agency_offer_board
    )
    if "eligible_teams" not in execution_sig.parameters:
        raise AssertionError("Execution plan is missing eligible_teams filtering.")
    if "eligible_teams" not in board_sig.parameters:
        raise AssertionError("Offer board is missing eligible_teams filtering.")

    report = execution.cpu_execution_contract_report()
    required = {
        "round_stops_when_roster_floor_complete": False,
        "round_stops_when_sustainable_roster_target_complete": True,
        "sustainable_roster_target": 14,
        "minimum_game_players_reserved_for_emergency_playability": True,
        "ordinary_market_restricted_to_under_target_cpu_teams": True,
    }
    for key, expected_value in required.items():
        observed_value = report.get(key)
        if observed_value != expected_value:
            raise AssertionError(
                f"Contract report mismatch for {key}: "
                f"expected={expected_value!r}, observed={observed_value!r}"
            )

    generation_report = offer_generation.generation_contract_report()
    if generation_report.get("eligible_team_filter_supported") is not True:
        raise AssertionError("Offer generation does not report eligible-team filtering.")

    print("FRANCHISE V2 PHASE 1 SUSTAINABLE ROSTER CONTRACT CHECK PASSED")
    print("Emergency game floor: 8")
    print("Normal CPU roster target: 14")
    print("Controlled-team exclusion: PASS")
    print("Eligible-team market filtering: PASS")
    print("No franchise state was loaded or mutated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
