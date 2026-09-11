from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from mutable_league_state_v1 import capture_snapshot

from simulation_league_state_v1 import (
    SimulationLeagueState,
    validate_simulation_league_state,
)

SEASON_BOUNDARY_TRADE_RECONCILIATION_VERSION = (
    "season-boundary-trade-reconciliation-v1.3-generated-player-registry-2026-09-10"
)


class SeasonBoundaryTradeReconciliationError(RuntimeError):
    pass


@dataclass(frozen=True)
class SeasonBoundaryTradeReconciliationResult:
    version: str
    source_revision: int
    target_revision: int
    source_transaction_count: int
    target_transaction_count: int
    registered_player_ids: tuple[str, ...]
    released_player_ids: tuple[str, ...]
    affected_teams: tuple[str, ...]


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _years_remaining(player: Any) -> int | None:
    contract = getattr(player, "contract", None)
    if contract is None:
        return None
    raw = getattr(contract, "years_remaining", None)
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def reconcile_trade_state_after_season_boundary(
    state: SimulationLeagueState,
    trade_state: Any,
) -> tuple[
    SimulationLeagueState,
    Any,
    SeasonBoundaryTradeReconciliationResult,
]:
    """
    Reconcile SimulationState player ownership into TradeState.

    Narrow authority:
    - register non-synthetic players added by the Draft/career lifecycle that
      do not yet exist in TradeState, using their canonical SimulationState
      team or blank free-agent owner;
    - only non-synthetic players who are free agents in SimulationState,
      have exactly 0 years remaining, and are still team-owned in TradeState
      are released from TradeState;
    - no transaction-history row is added;
    - TradeState revision increments once iff at least one release occurs;
    - prior-season Trade Machine undo snapshots are cleared at the boundary;
    - initial_snapshot is rebased to the reconciled offseason baseline so
      later Free Agency/Trade Machine reset operations cannot resurrect
      prior-season ownership or financial state;
    - SimulationState source revision/count are aligned to the resulting
      TradeState metadata;
    - transaction history and live ownership/financial maps are otherwise
      preserved by deepcopy.
    """
    validate_simulation_league_state(state)

    mapping = getattr(trade_state, "player_team_by_id", None)
    if not isinstance(mapping, dict):
        raise SeasonBoundaryTradeReconciliationError(
            "TradeState has no mutable player_team_by_id mapping."
        )

    history = getattr(trade_state, "transaction_history", None)
    if history is None:
        raise SeasonBoundaryTradeReconciliationError(
            "TradeState has no transaction_history."
        )

    try:
        source_revision = int(getattr(trade_state, "state_revision"))
        source_transaction_count = len(history)
    except (TypeError, ValueError, AttributeError) as exc:
        raise SeasonBoundaryTradeReconciliationError(
            "TradeState revision/transaction metadata is invalid."
        ) from exc

    updated_state = copy.deepcopy(state)
    updated_trade = copy.deepcopy(trade_state)
    updated_map = getattr(updated_trade, "player_team_by_id")

    registered: list[str] = []
    released: list[str] = []
    affected: set[str] = set()

    free_agents = {
        _clean(player_id)
        for player_id in getattr(
            updated_state,
            "free_agent_player_ids",
            (),
        ) or ()
        if _clean(player_id)
    }

    for raw_player_id, player in updated_state.players.items():
        player_id = _clean(raw_player_id)
        if not player_id or bool(getattr(player, "synthetic", False)):
            continue

        simulation_team = _clean(getattr(player, "team_abbreviation", ""))
        roster_status = _clean(getattr(player, "roster_status", "")).lower()

        # Draft-generated players enter SimulationState after the initial
        # TradeState player registry is built. Register them at the atomic
        # boundary so their eventual free agency can use the same dual-state
        # transaction path as every original player. The freshly captured
        # boundary snapshot below makes the expanded registry the new exact
        # reset/undo baseline.
        if player_id not in updated_map:
            if simulation_team:
                updated_map[player_id] = simulation_team
                affected.add(simulation_team)
            elif player_id in free_agents and roster_status == "free_agent":
                updated_map[player_id] = ""
            else:
                raise SeasonBoundaryTradeReconciliationError(
                    "A non-synthetic SimulationState player is missing from "
                    "TradeState without a canonical roster or free-agent owner: "
                    f"{player_id}."
                )
            registered.append(player_id)

        trade_team = _clean(updated_map.get(player_id, ""))

        if not trade_team:
            continue
        if simulation_team:
            continue
        if player_id not in free_agents:
            continue
        if roster_status != "free_agent":
            continue
        if _years_remaining(player) != 0:
            continue

        # TradeState canonically represents an unowned/free-agent player with
        # the empty string.  None violates mutable_league_state_v1.validate_state().
        updated_map[player_id] = ""
        released.append(player_id)
        affected.add(trade_team)

    target_revision = source_revision + (1 if registered or released else 0)
    setattr(updated_trade, "state_revision", target_revision)

    # A season boundary is also an undo/reset boundary. Historical Trade
    # Machine snapshots may still contain last season's player ownership and
    # salary state. Carrying those snapshots into Free Agency can make a
    # correctly released player appear team-owned when a signing attempts to
    # rebase undo/reset state. Preserve the transaction ledger, but start a new
    # undo baseline from the reconciled live state.
    undo_stack = getattr(updated_trade, "undo_stack", None)
    if not isinstance(undo_stack, list):
        raise SeasonBoundaryTradeReconciliationError(
            "TradeState undo_stack is unavailable or invalid at the season boundary."
        )
    if not hasattr(updated_trade, "initial_snapshot"):
        raise SeasonBoundaryTradeReconciliationError(
            "TradeState initial_snapshot is unavailable at the season boundary."
        )
    undo_stack.clear()
    updated_trade.initial_snapshot = capture_snapshot(updated_trade)

    # This is a season-boundary state reconciliation, not a user transaction.
    # Transaction history is intentionally unchanged.
    target_transaction_count = len(
        getattr(updated_trade, "transaction_history")
    )
    if target_transaction_count != source_transaction_count:
        raise SeasonBoundaryTradeReconciliationError(
            "Season-boundary reconciliation changed transaction history."
        )

    updated_state.source_league_state_revision = target_revision
    updated_state.source_transaction_count = target_transaction_count

    validate_simulation_league_state(updated_state)

    return (
        updated_state,
        updated_trade,
        SeasonBoundaryTradeReconciliationResult(
            version=SEASON_BOUNDARY_TRADE_RECONCILIATION_VERSION,
            source_revision=source_revision,
            target_revision=target_revision,
            source_transaction_count=source_transaction_count,
            target_transaction_count=target_transaction_count,
            registered_player_ids=tuple(sorted(registered)),
            released_player_ids=tuple(sorted(released)),
            affected_teams=tuple(sorted(affected)),
        ),
    )
