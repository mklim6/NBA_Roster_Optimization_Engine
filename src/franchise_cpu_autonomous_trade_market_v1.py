from __future__ import annotations

import copy
import math
from dataclasses import asdict, dataclass
from statistics import median
from typing import Any, Callable, Iterable

from franchise_command_center_v1 import (
    position_family,
    team_needs_rows,
)
from franchise_morale_trade_market_v1 import (
    morale_trade_market_rows_v1,
)
from franchise_trade_finder_ai_v1 import (
    GOAL_BEST_AVAILABLE,
    FranchiseTradeFinderProposal,
    build_trade_finder_search_context,
    generate_trade_finder_proposals,
)
from franchise_trade_transaction_v1 import (
    FranchiseTradeTransactionError,
    commit_live_franchise_trade,
)

CPU_AUTONOMOUS_TRADE_MARKET_VERSION = (
    "franchise-cpu-autonomous-trade-market-v6a-2026-09-17"
)
CPU_AUTONOMOUS_TRADE_MARKET_PERFORMANCE_VERSION = (
    "franchise-cpu-autonomous-trade-market-v6a-perf-v6-0-1-2026-09-17"
)
STATE_ATTRIBUTE = "franchise_cpu_autonomous_trade_market_v1"

MIN_MEDIAN_GAMES = 12
TRADE_DEADLINE_MEDIAN_GAMES = 55
TICK_COOLDOWN_DAYS = 7
MAX_MORALE_DRIVEN_CPU_TRADES_PER_SEASON = 8
MAX_SELLERS_PER_TICK = 2
MAX_BUYERS_PER_SELLER = 3


class CPUAutonomousTradeMarketError(RuntimeError):
    """Raised when the autonomous CPU trade-market layer cannot run safely."""


@dataclass(frozen=True)
class CPUAutonomousTradeTickResult:
    version: str
    state: Any
    ran: bool
    changed: bool
    committed: bool
    transaction_id: str
    buyer_team: str
    seller_team: str
    target_player_id: str
    target_player_name: str
    cpu_response: str
    reason: str
    current_day: int
    median_games_played: float
    market_players_considered: int
    buyers_considered: int
    proposals_considered: int

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("state", None)
        return payload


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _phase(state: Any) -> str:
    raw = getattr(state, "phase", "")
    value = getattr(raw, "value", raw)
    return _clean(value).lower()


def _season(state: Any) -> str:
    return _clean(
        getattr(
            getattr(state, "settings", None),
            "season_label",
            "",
        )
    )


def _games_played(state: Any) -> list[int]:
    standings = getattr(state, "standings", {}) or {}
    values: list[int] = []
    for row in standings.values():
        gp = getattr(row, "games_played", None)
        if gp is None:
            gp = int(getattr(row, "wins", 0) or 0) + int(
                getattr(row, "losses", 0) or 0
            )
        try:
            values.append(max(0, int(gp)))
        except (TypeError, ValueError):
            continue
    return values


def _median_games_played(state: Any) -> float:
    values = _games_played(state)
    return float(median(values)) if values else 0.0


def _ensure_market_state(state: Any) -> dict[str, Any]:
    season = _season(state)
    payload = getattr(state, STATE_ATTRIBUTE, None)

    if not isinstance(payload, dict) or payload.get("season") != season:
        payload = {
            "version": CPU_AUTONOMOUS_TRADE_MARKET_VERSION,
            "season": season,
            "last_tick_day": -10_000,
            "trades_completed": 0,
            "history": [],
        }
        setattr(state, STATE_ATTRIBUTE, payload)

    payload.setdefault("version", CPU_AUTONOMOUS_TRADE_MARKET_VERSION)
    payload.setdefault("season", season)
    payload.setdefault("last_tick_day", -10_000)
    payload.setdefault("trades_completed", 0)
    payload.setdefault("history", [])
    return payload


def _player_name(state: Any, player_id: str) -> str:
    player = (getattr(state, "players", {}) or {}).get(str(player_id))
    return (
        _clean(getattr(player, "player_name", ""))
        or str(player_id)
    )


def _player_position_family(state: Any, player_id: str) -> str:
    player = (getattr(state, "players", {}) or {}).get(str(player_id))
    return position_family(
        getattr(player, "position", "")
    )


def _buyer_need_score(
    state: Any,
    buyer: str,
    family: str,
) -> float:
    if not family:
        return 0.0
    rows = team_needs_rows(state, buyer)
    for row in rows:
        if _clean(row.get("Position Group")) == family:
            try:
                return float(row.get("Need Score") or 0.0)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _buyer_order(
    state: Any,
    *,
    seller_team: str,
    target_player_id: str,
    controlled_teams: Iterable[str],
) -> list[str]:
    controlled = {_team(team) for team in controlled_teams if _team(team)}
    seller = _team(seller_team)
    family = _player_position_family(state, target_player_id)

    scored: list[tuple[float, str]] = []
    for team in sorted((getattr(state, "teams", {}) or {}).keys()):
        resolved = _team(team)
        if (
            not resolved
            or resolved == seller
            or resolved in controlled
        ):
            continue

        standing = (getattr(state, "standings", {}) or {}).get(resolved)
        wins = int(getattr(standing, "wins", 0) or 0)
        losses = int(getattr(standing, "losses", 0) or 0)
        gp = wins + losses
        win_pct = wins / gp if gp else 0.5

        need = _buyer_need_score(state, resolved, family)

        # Buyers with a clear positional need are most likely to call.
        # Competitive teams get a small tie-break bonus, but rebuilders can
        # still buy when the fit is strong.
        score = 1.6 * need + 8.0 * win_pct
        scored.append((score, resolved))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [team for _, team in scored[:MAX_BUYERS_PER_SELLER]]


def _market_priority(row: dict[str, Any]) -> tuple:
    posture = _clean(row.get("Market posture"))
    request = _clean(row.get("Request"))
    risk = float(row.get("Risk %") or 0.0)
    posture_rank = 2 if posture == "Actively market" else 1 if posture == "Listen to offers" else 0
    request_rank = 1 if request == "Requested trade" else 0
    return (-posture_rank, -request_rank, -risk, _clean(row.get("Team")), _clean(row.get("Player")))


def _market_rows(
    state: Any,
    *,
    controlled_teams: Iterable[str],
) -> list[dict[str, Any]]:
    controlled = {_team(team) for team in controlled_teams if _team(team)}
    rows = morale_trade_market_rows_v1(
        state,
        controlled_teams=controlled,
    )

    active = [
        dict(row)
        for row in rows
        if _team(row.get("Team")) not in controlled
        and _clean(row.get("Market posture")) in {
            "Listen to offers",
            "Actively market",
        }
    ]
    active.sort(key=_market_priority)
    return active[:MAX_SELLERS_PER_TICK]


def _proposal_target_matches(
    proposal: FranchiseTradeFinderProposal,
    target_player_id: str,
) -> bool:
    return str(proposal.target_player_id) == str(target_player_id)


def _proposal_is_actionable(
    proposal: FranchiseTradeFinderProposal,
) -> bool:
    return proposal.cpu_response in {"accept", "counter"}


def _proposal_order(
    proposal: FranchiseTradeFinderProposal,
) -> tuple:
    response_rank = 0 if proposal.cpu_response == "accept" else 1
    return (
        response_rank,
        -float(proposal.ranking_score),
        -float(proposal.user_value_delta),
        -float(proposal.cpu_value_delta),
        proposal.proposal_id,
    )


def _resolve_traded_player_grievance(
    state: Any,
    player_id: str,
    *,
    new_team: str,
    transaction_id: str,
) -> None:
    payload = getattr(state, "franchise_morale_chemistry_v1", None)
    if not isinstance(payload, dict):
        return

    pid = str(player_id)
    player_row = (payload.get("players") or {}).get(pid)
    if isinstance(player_row, dict):
        current = float(player_row.get("score", 55.0) or 55.0)
        reset = max(55.0, min(72.0, current + 12.0))
        player_row["previous_score"] = round(reset, 1)
        player_row["score"] = round(reset, 1)
        player_row["low_morale_games"] = 0
        player_row["high_risk_games"] = 0
        player_row["trade_request_active"] = False
        player_row["trade_request_status"] = "Resolved by trade"
        player_row["trade_request_risk"] = 0.0
        player_row["recent_games"] = []
        player_row["last_trade_resolution"] = {
            "transaction_id": transaction_id,
            "new_team": _team(new_team),
        }

    for key in (
        "role_promises",
        "trade_responses",
        "meetings",
    ):
        mapping = payload.get(key)
        if isinstance(mapping, dict):
            mapping.pop(pid, None)

    history = payload.setdefault("event_history", [])
    if isinstance(history, list):
        history.append(
            {
                "event": "trade_request_resolved_by_trade",
                "player_id": pid,
                "team": _team(new_team),
                "transaction_id": transaction_id,
            }
        )


def _append_inbox_event(
    state: Any,
    *,
    transaction_id: str,
    buyer: str,
    seller: str,
    player_id: str,
    player_name: str,
) -> None:
    try:
        from franchise_league_events_v1 import _append_event
    except Exception:
        return

    try:
        _append_event(
            state,
            dedupe_key=f"cpu-trade-{transaction_id}",
            category="transaction",
            event_type="cpu_trade",
            severity="info",
            title=f"CPU trade completed: {player_name} to {buyer}",
            detail=(
                f"{buyer} and {seller} completed a CPU-to-CPU trade. "
                f"The deal passed the same live financial, contract, draft-right, "
                f"Stepien and canonical transaction checks used by Franchise Trade Center."
            ),
            action_section="Trade Center",
            blocking=False,
            team=buyer,
            player_id=str(player_id),
            metadata={
                "transaction_id": transaction_id,
                "buyer_team": buyer,
                "seller_team": seller,
                "target_player_id": str(player_id),
            },
        )
    except Exception:
        # An informational event must never make a legal CPU trade fail.
        return


def _history_record(
    *,
    state: Any,
    outcome: str,
    reason: str,
    market_players: int,
    buyers: int,
    proposals: int,
    transaction_id: str = "",
    buyer_team: str = "",
    seller_team: str = "",
    target_player_id: str = "",
    target_player_name: str = "",
    cpu_response: str = "",
) -> dict[str, Any]:
    return {
        "version": CPU_AUTONOMOUS_TRADE_MARKET_VERSION,
        "season": _season(state),
        "day_index": int(getattr(state, "current_day_index", 0) or 0),
        "median_games_played": round(_median_games_played(state), 1),
        "outcome": outcome,
        "reason": reason,
        "market_players_considered": int(market_players),
        "buyers_considered": int(buyers),
        "proposals_considered": int(proposals),
        "transaction_id": transaction_id,
        "buyer_team": buyer_team,
        "seller_team": seller_team,
        "target_player_id": str(target_player_id),
        "target_player_name": target_player_name,
        "cpu_response": cpu_response,
    }


def run_cpu_autonomous_trade_market_v1(
    runtime: Any,
    state: Any,
    trade_state: Any,
    *,
    controlled_teams: Iterable[str] = (),
    proposal_generator: Callable[..., Any] = generate_trade_finder_proposals,
    trade_committer: Callable[..., Any] = commit_live_franchise_trade,
    market_rows_builder: Callable[..., list[dict[str, Any]]] | None = None,
    buyer_order_builder: Callable[..., list[str]] | None = None,
    private_transactional_state: bool = False,
) -> CPUAutonomousTradeTickResult:
    """Bounded morale-driven CPU trade tick with cheap preflight guards."""
    working = state
    day = int(getattr(state, "current_day_index", 0) or 0)
    median_games = _median_games_played(state)
    controlled = tuple(sorted({_team(team) for team in controlled_teams if _team(team)}))

    def result(*, ran: bool, changed: bool, committed: bool = False,
               transaction_id: str = "", buyer_team: str = "", seller_team: str = "",
               target_player_id: str = "", target_player_name: str = "",
               cpu_response: str = "", reason: str,
               market_players: int = 0, buyers: int = 0, proposals: int = 0):
        return CPUAutonomousTradeTickResult(
            version=CPU_AUTONOMOUS_TRADE_MARKET_VERSION,
            state=working,
            ran=ran,
            changed=changed,
            committed=committed,
            transaction_id=transaction_id,
            buyer_team=buyer_team,
            seller_team=seller_team,
            target_player_id=str(target_player_id),
            target_player_name=target_player_name,
            cpu_response=cpu_response,
            reason=reason,
            current_day=day,
            median_games_played=round(median_games, 1),
            market_players_considered=market_players,
            buyers_considered=buyers,
            proposals_considered=proposals,
        )

    # V6.0.1: all cheap guards happen before the expensive franchise deepcopy.
    if _phase(state) != "regular_season":
        return result(ran=False, changed=False, reason="Autonomous CPU trading is limited to the regular season.")
    if median_games < MIN_MEDIAN_GAMES:
        return result(ran=False, changed=False, reason=f"Trade market has not opened yet. Median team games: {median_games:.1f}/{MIN_MEDIAN_GAMES}.")
    if median_games >= TRADE_DEADLINE_MEDIAN_GAMES:
        return result(ran=False, changed=False, reason="Morale-driven CPU trading is closed after the regular-season trade-deadline guard.")

    existing = getattr(state, STATE_ATTRIBUTE, None)
    if not isinstance(existing, dict) or existing.get("season") != _season(state):
        trades_completed, last_tick = 0, -10_000
    else:
        trades_completed = int(existing.get("trades_completed", 0) or 0)
        last_tick = int(existing.get("last_tick_day", -10_000) or -10_000)

    if trades_completed >= MAX_MORALE_DRIVEN_CPU_TRADES_PER_SEASON:
        return result(ran=False, changed=False, reason="Season cap for morale-driven autonomous CPU trades has been reached.")
    if day - last_tick < TICK_COOLDOWN_DAYS:
        return result(ran=False, changed=False, reason=f"CPU trade market is on cooldown for {TICK_COOLDOWN_DAYS - (day - last_tick)} more day(s).")

    # FRANCHISE_TRADE_MARKET_PERFORMANCE_V7_4
    # Only an actually due market pass needs an isolated working universe.
    # Game Day already owns one through commit_game_transactionally(), so an
    # explicit private-state caller can safely reuse it. Other callers retain
    # the original defensive deepcopy.
    working = state if private_transactional_state else copy.deepcopy(state)
    market_state = _ensure_market_state(working)
    market_state["last_tick_day"] = day
    market_state["version"] = CPU_AUTONOMOUS_TRADE_MARKET_VERSION

    builder = market_rows_builder or _market_rows
    rows = builder(working, controlled_teams=controlled)
    buyers_considered = 0
    proposals_considered = 0

    if not rows:
        record = _history_record(
            state=working,
            outcome="no_market_players",
            reason="No CPU player is currently in a market-active morale posture.",
            market_players=0,
            buyers=0,
            proposals=0,
        )
        market_state["history"].append(record)
        return result(ran=True, changed=True, reason=record["reason"])

    order_builder = buyer_order_builder or _buyer_order
    # FRANCHISE_TRADE_MARKET_PERFORMANCE_V7_1
    # Build the expensive Trade Finder context only if a full finder search is
    # actually reached, then reuse it for every buyer on this unchanged state.
    search_context = None

    for seller_row in rows[:MAX_SELLERS_PER_TICK]:
        seller = _team(seller_row.get("Team"))
        target_name = _clean(seller_row.get("Player"))
        target_id = ""
        for pid, player in (getattr(working, "players", {}) or {}).items():
            if (_clean(getattr(player, "player_name", "")) == target_name
                and _team(getattr(player, "team_abbreviation", seller)) in {"", seller}):
                target_id = str(pid)
                break
        if not target_id:
            roster = tuple(getattr((getattr(working, "teams", {}) or {}).get(seller), "roster_player_ids", ()) or ())
            for pid in roster:
                if _player_name(working, str(pid)) == target_name:
                    target_id = str(pid)
                    break
        if not target_id:
            continue

        buyers = order_builder(
            working,
            seller_team=seller,
            target_player_id=target_id,
            controlled_teams=controlled,
        )
        for buyer in buyers[:MAX_BUYERS_PER_SELLER]:
            buyer = _team(buyer)
            if not buyer or buyer == seller or buyer in controlled or seller in controlled:
                continue
            buyers_considered += 1
            try:
                if proposal_generator is generate_trade_finder_proposals:
                    if search_context is None:
                        search_context = build_trade_finder_search_context(
                            runtime,
                            working,
                            trade_state,
                            trusted_read_only_state=private_transactional_state,
                        )
                    finder_result = proposal_generator(
                        runtime, working, trade_state,
                        active_team=buyer,
                        goal=GOAL_BEST_AVAILABLE,
                        partner_team=seller,
                        include_picks=True,
                        max_results=3,
                        max_partners=1,
                        max_targets_per_partner=3,
                        max_package_evaluations=5,
                        max_financial_prechecks=100,
                        search_context=search_context,
                    )
                else:
                    finder_result = proposal_generator(
                        runtime, working, trade_state,
                        active_team=buyer,
                        goal=GOAL_BEST_AVAILABLE,
                        partner_team=seller,
                        include_picks=True,
                        max_results=3,
                        max_partners=1,
                        max_targets_per_partner=3,
                        max_package_evaluations=5,
                        max_financial_prechecks=100,
                    )
            except Exception:
                continue

            candidates = [
                proposal for proposal in tuple(getattr(finder_result, "proposals", ()) or ())
                if _proposal_target_matches(proposal, target_id)
                and _proposal_is_actionable(proposal)
            ]
            proposals_considered += len(candidates)
            if not candidates:
                continue
            candidates.sort(key=_proposal_order)
            proposal = candidates[0]
            fingerprint = _clean((proposal.preview_payload or {}).get("package_fingerprint"))
            if not fingerprint:
                continue

            try:
                commit = trade_committer(
                    runtime, working, trade_state,
                    team_a=buyer,
                    team_b=seller,
                    side_a_player_ids=tuple(proposal.side_a_player_ids),
                    side_b_player_ids=tuple(proposal.side_b_player_ids),
                    side_a_pick_asset_ids=tuple(proposal.side_a_pick_asset_ids),
                    side_b_pick_asset_ids=tuple(proposal.side_b_pick_asset_ids),
                    expected_fingerprint=fingerprint,
                )
            except FranchiseTradeTransactionError:
                continue
            except Exception:
                continue

            working = commit.committed_state
            market_state = _ensure_market_state(working)
            transaction_id = _clean(getattr(commit, "transaction_id", ""))
            market_state["last_tick_day"] = day
            market_state["trades_completed"] = int(market_state.get("trades_completed", 0) or 0) + 1
            _resolve_traded_player_grievance(working, target_id, new_team=buyer, transaction_id=transaction_id)
            _append_inbox_event(working, transaction_id=transaction_id, buyer=buyer, seller=seller, player_id=target_id, player_name=target_name)
            record = _history_record(
                state=working,
                outcome="trade_committed",
                reason="A market-active morale case produced a mutually acceptable CPU-to-CPU package and passed the live transaction engine.",
                market_players=len(rows), buyers=buyers_considered, proposals=proposals_considered,
                transaction_id=transaction_id, buyer_team=buyer, seller_team=seller,
                target_player_id=target_id, target_player_name=target_name,
                cpu_response=proposal.cpu_response,
            )
            market_state["history"].append(record)
            return result(
                ran=True, changed=True, committed=True,
                transaction_id=transaction_id, buyer_team=buyer, seller_team=seller,
                target_player_id=target_id, target_player_name=target_name,
                cpu_response=proposal.cpu_response, reason=record["reason"],
                market_players=len(rows), buyers=buyers_considered, proposals=proposals_considered,
            )

    record = _history_record(
        state=working,
        outcome="no_acceptable_trade",
        reason="CPU teams explored the live market, but no exact market-active target produced a mutually acceptable legal package this tick.",
        market_players=len(rows), buyers=buyers_considered, proposals=proposals_considered,
    )
    market_state["history"].append(record)
    return result(
        ran=True, changed=True, reason=record["reason"],
        market_players=len(rows), buyers=buyers_considered, proposals=proposals_considered,
    )

def cpu_autonomous_trade_market_snapshot_v1(
    state: Any,
) -> dict[str, Any]:
    payload = _ensure_market_state(state)
    history = list(payload.get("history", ()) or ())
    latest = history[-1] if history else {}
    return {
        "version": CPU_AUTONOMOUS_TRADE_MARKET_VERSION,
        "season": _season(state),
        "phase": _phase(state),
        "current_day": int(getattr(state, "current_day_index", 0) or 0),
        "median_games_played": round(_median_games_played(state), 1),
        "last_tick_day": int(payload.get("last_tick_day", -10_000) or -10_000),
        "trades_completed": int(payload.get("trades_completed", 0) or 0),
        "latest": latest,
        "history": history,
        "trade_window_open": (
            _phase(state) == "regular_season"
            and MIN_MEDIAN_GAMES <= _median_games_played(state) < TRADE_DEADLINE_MEDIAN_GAMES
        ),
    }


def render_cpu_autonomous_trade_market_v1(
    state: Any,
    *,
    controlled_teams: Iterable[str] = (),
) -> None:
    import pandas as pd
    import streamlit as st

    snapshot = cpu_autonomous_trade_market_snapshot_v1(state)
    market_rows = _market_rows(
        state,
        controlled_teams=controlled_teams,
    )

    st.markdown("### Autonomous CPU trade market")
    st.caption(
        "CPU teams can now turn sustained morale/trade-request pressure into "
        "real CPU-to-CPU transactions. The system runs on a seven-day cadence, "
        "commits at most one trade per tick, never includes a user-controlled "
        "team, and uses the normal Trade Finder plus full live transaction gates."
    )

    cols = st.columns(4)
    cols[0].metric(
        "CPU trades",
        snapshot["trades_completed"],
    )
    cols[1].metric(
        "Market-active",
        len(market_rows),
    )
    cols[2].metric(
        "Median GP",
        f'{snapshot["median_games_played"]:.1f}',
    )
    cols[3].metric(
        "Trade window",
        "Open" if snapshot["trade_window_open"] else "Closed",
    )

    latest = snapshot.get("latest") or {}
    if latest:
        if latest.get("outcome") == "trade_committed":
            st.success(
                f'{latest.get("buyer_team")} acquired '
                f'{latest.get("target_player_name")} from '
                f'{latest.get("seller_team")} in '
                f'{latest.get("transaction_id")}.'
            )
        else:
            st.info(
                f'Last CPU market tick: {latest.get("reason", "No action.")}'
            )

    history = list(snapshot.get("history", ()))
    if history:
        display = pd.DataFrame(history[-12:])
        preferred = [
            "day_index",
            "outcome",
            "buyer_team",
            "seller_team",
            "target_player_name",
            "cpu_response",
            "market_players_considered",
            "buyers_considered",
            "proposals_considered",
            "transaction_id",
        ]
        display = display[
            [column for column in preferred if column in display.columns]
        ]
        st.dataframe(
            display.iloc[::-1],
            hide_index=True,
            width="stretch",
        )


__all__ = [
    "CPU_AUTONOMOUS_TRADE_MARKET_VERSION",
    "CPUAutonomousTradeMarketError",
    "CPUAutonomousTradeTickResult",
    "run_cpu_autonomous_trade_market_v1",
    "cpu_autonomous_trade_market_snapshot_v1",
    "render_cpu_autonomous_trade_market_v1",
]
