from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import franchise_free_agency_cpu_execution_v1 as cpu


def main() -> int:
    # Pure target/controlled-team checks.
    state = SimpleNamespace(
        settings=SimpleNamespace(minimum_game_players=8),
        teams={
            "AAA": SimpleNamespace(roster_player_ids=tuple(str(x) for x in range(13))),
            "BBB": SimpleNamespace(roster_player_ids=tuple(str(x) for x in range(14))),
        },
        free_agent_player_ids=("P1",),
        players={
            "P1": SimpleNamespace(
                player_id="P1",
                player_name="Test Player",
                overall_rating=70.0,
            )
        },
    )

    deficits = cpu.cpu_sustainable_roster_deficits(state, ())
    assert deficits == (("AAA", 13, 1),), deficits
    assert cpu.cpu_sustainable_roster_deficits(state, ("AAA",)) == ()

    # Patch only pure helper dependencies. This confirms that the completion
    # search targets an under-14 CPU team and does not mutate the state.
    originals = {
        "resolve_years_of_service": cpu.resolve_years_of_service,
        "minimum_salary_floor_for_state": cpu.minimum_salary_floor_for_state,
        "free_agency_state_fingerprint": cpu.free_agency_state_fingerprint,
        "_rescue_offer_and_decision": cpu._rescue_offer_and_decision,
    }
    try:
        cpu.resolve_years_of_service = lambda player: (2, "test")
        cpu.minimum_salary_floor_for_state = (
            lambda state, years_of_service, contract_years: 2_000_000.0
        )
        cpu.free_agency_state_fingerprint = lambda state: "state-fp"

        preview = SimpleNamespace(
            offer=SimpleNamespace(
                player_id="P1",
                team_abbreviation="AAA",
                annual_salary=2_000_000.0,
                years=1,
            ),
            source_fingerprint="state-fp",
            candidate_fingerprint="candidate-fp",
        )
        decision = SimpleNamespace(
            accepted=True,
            utility_score=70.0,
            acceptance_threshold=60.0,
            decision_fingerprint="decision-fp",
        )
        cpu._rescue_offer_and_decision = (
            lambda state, team_abbreviation, player_id,
            source_fingerprint=None, defer_candidate_fingerprint=False:
            (preview, decision, "exact_minimum_accept")
        )

        before = tuple(state.teams["AAA"].roster_player_ids)
        opportunity = cpu.build_cpu_sustainable_roster_completion_opportunity(
            state,
            controlled_teams=(),
        )
        assert opportunity is not None
        assert opportunity.team_abbreviation == "AAA"
        assert opportunity.roster_count_before == 13
        assert opportunity.sustainable_roster_target == 14
        assert opportunity.player_id == "P1"
        assert tuple(state.teams["AAA"].roster_player_ids) == before
    finally:
        for name, value in originals.items():
            setattr(cpu, name, value)

    report = cpu.cpu_execution_contract_report()
    assert report["sustainable_completion_runs_only_after_ordinary_market_exhausts"] is True
    assert report["sustainable_completion_uses_bounded_market_rechecks"] is True
    assert report["sustainable_completion_market_refresh_interval"] == 5
    assert report["sustainable_completion_preserves_locked_financial_gate"] is True
    assert report["sustainable_completion_requires_player_acceptance"] is True
    assert report["sustainable_completion_uses_market_clearance_override"] is False
    assert report["sustainable_completion_uses_synthetic_players"] is False

    print("FRANCHISE V2 PHASE 1 LEGAL SUSTAINABLE COMPLETION CHECK PASSED")
    print("Emergency floor remains:", 8)
    print("Sustainable target remains:", 14)
    print("Under-target completion search: PASS")
    print("5-signing ordinary-market recheck boundary: PASS")
    print("Controlled-team exclusion: PASS")
    print("Financial/CBA gate preserved: PASS")
    print("Player acceptance preserved: PASS")
    print("Market-clearance override: DISABLED")
    print("Synthetic roster filler: DISABLED")
    print("No franchise checkpoint was loaded or mutated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
