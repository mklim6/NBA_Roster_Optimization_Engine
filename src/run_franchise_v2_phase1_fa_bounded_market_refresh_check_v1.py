from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import franchise_free_agency_cpu_execution_v1 as execution


def main() -> int:
    report = execution.cpu_execution_contract_report()

    assert report["board_rebuilt_after_each_signing"] is False
    assert report["full_plan_refresh_interval"] == 5
    assert report["queued_offers_from_changed_teams_discarded"] is True
    assert report["queued_player_market_rebuilt_through_current_cba_gate"] is True
    assert report["queued_player_decision_market_recomputed"] is True
    assert report["winning_offer_full_preview_revalidated_before_commit"] is True
    assert report["roster_floor_rescue_prioritized_before_standard_market"] is True
    assert report["sustainable_completion_preserves_locked_financial_gate"] is True
    assert report["sustainable_completion_requires_player_acceptance"] is True

    # Focused pure regression check for the queued-player revalidation helper.
    original_fp = execution.free_agency_state_fingerprint
    original_builder = execution.build_rights_exception_free_agency_preview
    original_market = execution.evaluate_competing_offer_market
    seen_teams = []

    try:
        execution.free_agency_state_fingerprint = lambda state: "state-fp"

        def fake_builder(state, offer, **kwargs):
            seen_teams.append(str(offer.team_abbreviation))
            return SimpleNamespace(
                offer=offer,
                status="pass",
                can_commit=True,
                source_fingerprint="state-fp",
            )

        execution.build_rights_exception_free_agency_preview = fake_builder
        execution.evaluate_competing_offer_market = lambda state, previews: SimpleNamespace(
            has_winner=True,
            previews=tuple(previews),
        )

        offer_a = SimpleNamespace(
            player_id="P1",
            team_abbreviation="AAA",
            annual_salary=2_000_000.0,
            years=1,
            guaranteed=True,
            option_type="",
        )
        offer_b = SimpleNamespace(
            player_id="P1",
            team_abbreviation="BBB",
            annual_salary=2_000_000.0,
            years=1,
            guaranteed=True,
            option_type="",
        )
        plan = SimpleNamespace(
            board=SimpleNamespace(
                offers=(
                    SimpleNamespace(
                        player_id="P1",
                        team_abbreviation="AAA",
                        preview=SimpleNamespace(offer=offer_a),
                    ),
                    SimpleNamespace(
                        player_id="P1",
                        team_abbreviation="BBB",
                        preview=SimpleNamespace(offer=offer_b),
                    ),
                )
            )
        )
        state = SimpleNamespace(free_agent_player_ids=("P1",))

        result = execution._revalidate_queued_player_market(
            plan,
            player_id="P1",
            state=state,
            eligible_teams=("AAA", "BBB"),
            changed_teams=("AAA",),
        )
        assert result is not None
        assert seen_teams == ["BBB"], seen_teams
    finally:
        execution.free_agency_state_fingerprint = original_fp
        execution.build_rights_exception_free_agency_preview = original_builder
        execution.evaluate_competing_offer_market = original_market

    print("FRANCHISE V2 PHASE 1 FA BOUNDED MARKET REFRESH CHECK PASSED")
    print("Full-board rebuild after every ordinary signing: DISABLED")
    print("Full-plan refresh interval: 5")
    print("Changed-team stale offers excluded: PASS")
    print("Queued player current CBA preview rebuild: PASS")
    print("Queued player current decision market recomputation: PASS")
    print("Durable winner full-preview revalidation: PRESERVED")
    print("Emergency floor rescue: PRESERVED")
    print("Sustainable roster completion gates: PRESERVED")
    print("No franchise checkpoint was loaded or mutated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
