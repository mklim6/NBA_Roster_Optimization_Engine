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

VERSION = "franchise-season-boundary-owner-normalization-hotfix-validator-v1.2-generated-player-registry-2026-09-10"


def _player(*, team: str, status: str, years: int, synthetic: bool = False):
    return SimpleNamespace(
        synthetic=synthetic,
        team_abbreviation=team,
        roster_status=status,
        contract=SimpleNamespace(years_remaining=years),
    )


def main() -> int:
    # Keep this validator narrowly focused on TradeState ownership semantics. The
    # production reconciliation's SimulationLeagueState validation is exercised
    # by the protected lifecycle regression with the full runtime.
    original_validate = reconciliation_api.validate_simulation_league_state
    reconciliation_api.validate_simulation_league_state = lambda state: None
    try:
        state = SimpleNamespace(
            players={
                "EXP": _player(team="", status="free_agent", years=0),
                "TEAM": _player(team="ATL", status="active", years=2),
                "FA1": _player(team="", status="free_agent", years=1),
                "GEN-ROSTER": _player(team="ATL", status="active_roster", years=3),
                "GEN-FA": _player(team="", status="free_agent", years=0),
                "SYN": _player(team="", status="free_agent", years=0, synthetic=True),
            },
            free_agent_player_ids=("EXP", "FA1", "GEN-FA", "SYN"),
            source_league_state_revision=7,
            source_transaction_count=2,
        )
        from mutable_league_state_v1 import StateSnapshot, TeamFinancialState

        def _fin(team: str):
            return TeamFinancialState(team, 100_000_000.0, 100_000_000.0, 12, 0, False, "none")

        trade = SimpleNamespace(
            player_team_by_id={
                "EXP": "BOS",
                "TEAM": "ATL",
                "FA1": "CHI",
                "SYN": "MIA",
            },
            pick_team_by_id={"PICK": "BOS"},
            team_financials={team: _fin(team) for team in ("ATL", "BOS", "CHI", "MIA")},
            acquired_player_ids=set(),
            transaction_history=[{"id": 1}, {"id": 2}],
            undo_stack=[StateSnapshot({"EXP": "BOS", "TEAM": "ATL", "FA1": "CHI", "SYN": "MIA"}, {"PICK": "BOS"}, {team: _fin(team) for team in ("ATL", "BOS", "CHI", "MIA")}, set())],
            initial_snapshot=StateSnapshot({"EXP": "BOS", "TEAM": "ATL", "FA1": "CHI", "SYN": "MIA"}, {"PICK": "BOS"}, {team: _fin(team) for team in ("ATL", "BOS", "CHI", "MIA")}, set()),
            state_revision=7,
        )
        updated_state, updated_trade, result = reconciliation_api.reconcile_trade_state_after_season_boundary(
            state, trade
        )

        source = (SRC / "simulation_season_boundary_trade_reconciliation_v1.py").read_text(encoding="utf-8")
        checks = {
            "implementation_version_is_v1_3": reconciliation_api.SEASON_BOUNDARY_TRADE_RECONCILIATION_VERSION == "season-boundary-trade-reconciliation-v1.3-generated-player-registry-2026-09-10",
            "missing_rostered_player_is_registered": updated_trade.player_team_by_id["GEN-ROSTER"] == "ATL",
            "missing_free_agent_is_registered_blank": updated_trade.player_team_by_id["GEN-FA"] == "",
            "registered_players_are_reported": tuple(result.registered_player_ids) == ("GEN-FA", "GEN-ROSTER"),
            "rebased_snapshot_contains_registered_players": (
                updated_trade.initial_snapshot.player_team_by_id["GEN-ROSTER"] == "ATL"
                and updated_trade.initial_snapshot.player_team_by_id["GEN-FA"] == ""
            ),
            "expired_free_agent_owner_is_canonical_blank_string": updated_trade.player_team_by_id["EXP"] == "",
            "released_owner_is_not_none": updated_trade.player_team_by_id["EXP"] is not None,
            "eligible_expired_player_is_reported_released": tuple(result.released_player_ids) == ("EXP",),
            "revision_increments_once_for_release_batch": result.source_revision == 7 and result.target_revision == 8 and updated_trade.state_revision == 8,
            "transaction_history_is_unchanged": len(updated_trade.transaction_history) == 2 and result.source_transaction_count == result.target_transaction_count == 2,
            "rostered_player_owner_is_preserved": updated_trade.player_team_by_id["TEAM"] == "ATL",
            "nonexpired_free_agent_trade_owner_is_not_released": updated_trade.player_team_by_id["FA1"] == "CHI",
            "synthetic_player_trade_owner_is_not_released": updated_trade.player_team_by_id["SYN"] == "MIA",
            "simulation_revision_metadata_is_aligned": updated_state.source_league_state_revision == 8 and updated_state.source_transaction_count == 2,
            "source_state_is_not_mutated": state.source_league_state_revision == 7,
            "source_trade_state_is_not_mutated": trade.player_team_by_id["EXP"] == "BOS" and trade.state_revision == 7,
            "source_contains_no_none_release_assignment": "updated_map[player_id] = None" not in source,
            "source_explicitly_uses_blank_release_assignment": 'updated_map[player_id] = ""' in source,
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
        print("FRANCHISE SEASON BOUNDARY OWNER NORMALIZATION HOTFIX V1 FAILED")
        return 1
    print("FRANCHISE SEASON BOUNDARY OWNER NORMALIZATION HOTFIX V1 PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
