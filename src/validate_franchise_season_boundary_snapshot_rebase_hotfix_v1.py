from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import simulation_season_boundary_trade_reconciliation_v1 as reconciliation_api
from franchise_free_agency_live_signing_v1 import (
    FreeAgencyLiveSigningError,
    build_trade_state_free_agency_candidate,
)
from franchise_free_agency_transaction_v1 import FreeAgencyOffer
from mutable_league_state_v1 import StateSnapshot, TeamFinancialState

VERSION = "franchise-season-boundary-snapshot-rebase-hotfix-validator-v1.0-2026-09-10"


def _player(*, team: str, status: str, years: int, synthetic: bool = False):
    return SimpleNamespace(
        synthetic=synthetic,
        team_abbreviation=team,
        roster_status=status,
        contract=SimpleNamespace(years_remaining=years),
    )


def _financial(team: str, salary: float = 100_000_000.0) -> TeamFinancialState:
    return TeamFinancialState(
        team_abbreviation=team,
        team_salary=salary,
        apron_salary=salary,
        standard_contract_count=12,
        two_way_contract_count=0,
        hard_cap_active=False,
        hard_cap_level="none",
    )


def _snapshot(owner: str) -> StateSnapshot:
    return StateSnapshot(
        player_team_by_id={
            "EXP": owner,
            "TEAM": "ATL",
            "FA1": "CHI",
            "SYN": "MIA",
        },
        pick_team_by_id={"PICK": "BOS"},
        team_financials={
            "ATL": _financial("ATL", 100_000_000.0),
            "BOS": _financial("BOS", 110_000_000.0),
            "CHI": _financial("CHI", 105_000_000.0),
            "MIA": _financial("MIA", 108_000_000.0),
        },
        acquired_player_ids={"EXP"},
    )


def main() -> int:
    original_validate = reconciliation_api.validate_simulation_league_state
    reconciliation_api.validate_simulation_league_state = lambda state: None
    try:
        state = SimpleNamespace(
            players={
                "EXP": _player(team="", status="free_agent", years=0),
                "TEAM": _player(team="ATL", status="active", years=2),
                "FA1": _player(team="", status="free_agent", years=1),
                "SYN": _player(team="", status="free_agent", years=0, synthetic=True),
            },
            free_agent_player_ids=("EXP", "FA1", "SYN"),
            source_league_state_revision=7,
            source_transaction_count=2,
        )
        stale_undo = _snapshot("BOS")
        stale_initial = _snapshot("BOS")
        trade = SimpleNamespace(
            player_team_by_id={
                "EXP": "BOS",
                "TEAM": "ATL",
                "FA1": "CHI",
                "SYN": "MIA",
            },
            pick_team_by_id={"PICK": "BOS"},
            team_financials={
                "ATL": _financial("ATL", 100_000_000.0),
                "BOS": _financial("BOS", 110_000_000.0),
                "CHI": _financial("CHI", 105_000_000.0),
                "MIA": _financial("MIA", 108_000_000.0),
            },
            acquired_player_ids={"EXP"},
            transaction_history=[{"id": 1}, {"id": 2}],
            undo_stack=[stale_undo],
            initial_snapshot=stale_initial,
            state_revision=7,
        )
        source_trade = copy.deepcopy(trade)

        updated_state, updated_trade, result = (
            reconciliation_api.reconcile_trade_state_after_season_boundary(state, trade)
        )

        source = (SRC / "simulation_season_boundary_trade_reconciliation_v1.py").read_text(
            encoding="utf-8"
        )

        # This was the exact lifecycle failure: after closeout the live owner is
        # blank, but a stale prior-season initial/undo snapshot still says BOS.
        # A post-boundary Free Agency signing must now be able to rebase cleanly.
        signing_offer = FreeAgencyOffer(
            player_id="EXP",
            team_abbreviation="ATL",
            annual_salary=1_000_000.0,
            years=1,
            guaranteed=True,
            option_type="",
        )
        signing_ok = True
        signing_candidate = None
        try:
            signing_candidate, _ = build_trade_state_free_agency_candidate(
                updated_trade,
                signing_offer,
                transaction_id="FATX-SNAPSHOT-REBASE-TEST",
                validate=False,
            )
        except FreeAgencyLiveSigningError:
            signing_ok = False

        checks = {
            "implementation_version_is_v1_3": (
                reconciliation_api.SEASON_BOUNDARY_TRADE_RECONCILIATION_VERSION
                == "season-boundary-trade-reconciliation-v1.3-generated-player-registry-2026-09-10"
            ),
            "expired_free_agent_owner_remains_canonical_blank_string": (
                updated_trade.player_team_by_id["EXP"] == ""
            ),
            "prior_season_undo_stack_is_cleared": updated_trade.undo_stack == [],
            "initial_snapshot_is_rebased": updated_trade.initial_snapshot is not None,
            "rebased_initial_snapshot_uses_current_free_agent_owner": (
                updated_trade.initial_snapshot.player_team_by_id.get("EXP") == ""
            ),
            "rebased_initial_snapshot_preserves_current_pick_owner": (
                updated_trade.initial_snapshot.pick_team_by_id.get("PICK") == "BOS"
            ),
            "rebased_initial_snapshot_matches_live_financial_baseline": (
                float(updated_trade.initial_snapshot.team_financials["ATL"].team_salary)
                == float(updated_trade.team_financials["ATL"].team_salary)
            ),
            "transaction_history_is_preserved": (
                len(updated_trade.transaction_history) == 2
                and result.source_transaction_count == result.target_transaction_count == 2
            ),
            "revision_semantics_are_preserved": (
                result.source_revision == 7
                and result.target_revision == 8
                and updated_trade.state_revision == 8
            ),
            "simulation_revision_metadata_is_aligned": (
                updated_state.source_league_state_revision == 8
                and updated_state.source_transaction_count == 2
            ),
            "source_trade_is_not_mutated": (
                source_trade.player_team_by_id["EXP"] == "BOS"
                and len(source_trade.undo_stack) == 1
                and source_trade.initial_snapshot.player_team_by_id["EXP"] == "BOS"
            ),
            "post_boundary_free_agency_signing_no_longer_hits_historical_snapshot_conflict": signing_ok,
            "post_boundary_signing_rebases_new_initial_snapshot": (
                signing_ok
                and signing_candidate.initial_snapshot.player_team_by_id.get("EXP") == "ATL"
            ),
            "source_contains_explicit_undo_boundary": "undo_stack.clear()" in source,
            "source_rebases_initial_snapshot_from_live_trade_state": (
                "updated_trade.initial_snapshot = capture_snapshot(updated_trade)" in source
            ),
            "source_preserves_blank_owner_normalization": 'updated_map[player_id] = ""' in source,
        }
    finally:
        reconciliation_api.validate_simulation_league_state = original_validate

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "version": VERSION,
        "checks": checks,
        "failed_checks": failed,
        "passed": not failed,
    }
    print(json.dumps(report, indent=2))
    print()
    if failed:
        print("FRANCHISE SEASON BOUNDARY SNAPSHOT REBASE HOTFIX V1 FAILED")
        return 1
    print("FRANCHISE SEASON BOUNDARY SNAPSHOT REBASE HOTFIX V1 PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
