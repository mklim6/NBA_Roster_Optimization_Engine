from __future__ import annotations

import math
from dataclasses import dataclass, fields, is_dataclass, replace
from typing import Any, Iterable

from franchise_cpu_morale_response_v1 import (
    cpu_trade_willingness_modifier_v1,
)
from franchise_morale_chemistry_v1 import (
    morale_snapshot_v1,
    trade_response_v1,
)

MORALE_TRADE_MARKET_VERSION = (
    "franchise-morale-trade-market-bridge-v5a-2026-09-16"
)
MORALE_TRADE_MARKET_SNAPSHOT_REUSE_VERSION = (
    "franchise-morale-trade-market-snapshot-reuse-v1-2026-09-25"
)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _num(
    value: Any,
    default: float = 0.0,
) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    return (
        result
        if math.isfinite(result)
        else float(default)
    )


def _player(
    state: Any,
    player_id: str,
) -> Any | None:
    return (
        getattr(state, "players", {})
        or {}
    ).get(str(player_id))


def _is_core_player_v1(
    state: Any,
    player_id: str,
) -> bool:
    player = _player(
        state,
        player_id,
    )
    if player is None:
        return False

    overall = _num(
        getattr(
            player,
            "overall_rating",
            0.0,
        )
    )
    potential = _num(
        getattr(
            player,
            "potential_rating",
            overall,
        ),
        overall,
    )
    age = _num(
        getattr(
            player,
            "age",
            27.0,
        ),
        27.0,
    )

    # Keep this definition aligned with the V4
    # CPU morale-response protection rule.
    return bool(
        overall >= 86.0
        or (
            age <= 24.0
            and potential >= 89.0
        )
    )


def _morale_row(
    state: Any,
    team: str,
    player_id: str,
    *,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if snapshot is None:
        snapshot = morale_snapshot_v1(
            state,
            team,
        )
    return next(
        (
            row
            for row
            in snapshot.get(
                "players",
                [],
            )
            if str(
                row.get("player_id")
            )
            == str(player_id)
        ),
        {},
    )


def _willingness_from_context_v1(
    *,
    response: str,
    request_active: bool,
    core_player: bool,
) -> float:
    """Exact planning-only willingness formula from CPU morale response V1."""
    modifier = {
        "Keep internal": 0.92,
        "Listening to offers": 1.10,
        "On trade block": 1.22,
    }.get(response, 1.0)
    if request_active:
        modifier += 0.08
    if core_player:
        modifier -= 0.08
    return round(
        max(
            0.78,
            min(
                1.35,
                modifier,
            ),
        ),
        3,
    )


@dataclass(frozen=True)
class MoraleTradeMarketContext:
    version: str
    team: str
    player_id: str
    player_name: str
    morale: float
    trade_risk: float
    request_status: str
    request_active: bool
    front_office_response: str
    core_player: bool
    willingness_modifier: float
    seller_ask_multiplier: float
    market_posture: str
    should_market: bool
    rationale: tuple[str, ...]


def morale_trade_market_context_v1(
    state: Any,
    team: str,
    player_id: str,
    *,
    _snapshot: dict[str, Any] | None = None,
) -> MoraleTradeMarketContext:
    resolved_team = _team(team)
    pid = str(player_id)
    row = _morale_row(
        state,
        resolved_team,
        pid,
        snapshot=_snapshot,
    )
    player = _player(
        state,
        pid,
    )

    response = trade_response_v1(
        state,
        resolved_team,
        pid,
    )
    request_active = bool(
        row.get(
            "trade_request_active",
            False,
        )
    )
    request_status = _clean(
        row.get(
            "trade_request_status",
            "None",
        )
    ) or "None"
    risk = _num(
        row.get(
            "trade_request_risk",
            0.0,
        )
    )
    morale = _num(
        row.get(
            "score",
            row.get(
                "morale",
                70.0,
            ),
        ),
        70.0,
    )
    core = _is_core_player_v1(
        state,
        pid,
    )
    if _snapshot is None:
        willingness = (
            cpu_trade_willingness_modifier_v1(
                state,
                resolved_team,
                pid,
            )
        )
    else:
        # The batched front-office path already has the exact morale row,
        # response and core-player result. Reuse them rather than rebuilding
        # the same team morale snapshot a second time for this player.
        willingness = _willingness_from_context_v1(
            response=response,
            request_active=request_active,
            core_player=core,
        )

    reasons: list[str] = []
    should_market = False

    if response == "On trade block":
        should_market = True
        posture = "Actively market"
        reasons.append(
            "CPU front office placed the player "
            "on the trade block after sustained "
            "morale pressure."
        )
    elif response == "Listening to offers":
        posture = "Listen to offers"
        should_market = (
            request_active
            or not core
        )
        reasons.append(
            "CPU front office is willing to "
            "listen because the morale system "
            "has escalated beyond an internal hold."
        )
    else:
        posture = "Keep internal"
        reasons.append(
            "CPU front office is still prioritizing "
            "internal resolution over trade-market "
            "availability."
        )

    if request_active:
        reasons.append(
            "The player has an active trade request."
        )
    elif request_status not in {
        "",
        "None",
        "No request",
    }:
        reasons.append(
            f"Trade-pressure stage: "
            f"{request_status}."
        )

    if core:
        reasons.append(
            "Core-player protection preserves a "
            "premium asking price even when offers "
            "are heard."
        )

    # This is a seller-side asking-price context, not a
    # change to intrinsic player value. Buyer valuation,
    # ratings and CBA legality stay untouched.
    if response == "Keep internal":
        seller_ask = (
            1.10
            if core
            else 1.05
        )
    elif response == "Listening to offers":
        seller_ask = (
            1.02
            if core
            else 0.98
        )
    elif response == "On trade block":
        seller_ask = (
            0.98
            if core
            else 0.93
        )
    else:
        seller_ask = 1.00

    if request_active and not core:
        seller_ask -= 0.01

    floor = (
        0.98
        if core
        else 0.90
    )
    seller_ask = round(
        max(
            floor,
            min(
                1.12,
                seller_ask,
            ),
        ),
        3,
    )

    return MoraleTradeMarketContext(
        version=(
            MORALE_TRADE_MARKET_VERSION
        ),
        team=resolved_team,
        player_id=pid,
        player_name=_clean(
            getattr(
                player,
                "player_name",
                pid,
            )
        )
        or pid,
        morale=round(
            morale,
            1,
        ),
        trade_risk=round(
            risk,
            1,
        ),
        request_status=request_status,
        request_active=request_active,
        front_office_response=response,
        core_player=core,
        willingness_modifier=round(
            willingness,
            3,
        ),
        seller_ask_multiplier=(
            seller_ask
        ),
        market_posture=posture,
        should_market=bool(
            should_market
        ),
        rationale=tuple(
            reasons
        ),
    )


def _decision_field_names(
    decision: Any,
) -> set[str]:
    if is_dataclass(decision):
        return {
            field.name
            for field
            in fields(decision)
        }

    if hasattr(
        decision,
        "__dict__",
    ):
        return set(
            vars(decision)
        )

    return set()


def _replace_decision(
    decision: Any,
    *,
    asset_policy: str,
) -> Any:
    names = _decision_field_names(
        decision
    )
    if (
        "asset_policy"
        not in names
    ):
        return decision

    if is_dataclass(decision):
        return replace(
            decision,
            asset_policy=(
                asset_policy
            ),
        )

    try:
        import copy

        cloned = copy.copy(
            decision
        )
        setattr(
            cloned,
            "asset_policy",
            asset_policy,
        )
        return cloned
    except Exception:
        return decision


def apply_cpu_morale_trade_market_to_decisions_v1(
    state: Any,
    team: str,
    decisions: Iterable[Any],
    *,
    controlled_teams: Iterable[str] = (),
) -> tuple[Any, ...]:
    """Adjust CPU trade availability without changing player value.

    The existing CPU front-office engine remains the authority for
    talent/value tiers, roster fit and legal trade construction. This
    bridge only allows a V4 morale escalation to promote a player into
    the existing ``Market`` asset-policy lane.
    """
    rows = tuple(
        decisions
    )
    resolved_team = _team(
        team
    )
    controlled = {
        _team(value)
        for value
        in controlled_teams
        if _team(value)
    }

    if (
        not rows
        or resolved_team in controlled
    ):
        return rows

    # Every player context on this team reads the same immutable planning
    # snapshot during one front-office plan build. The previous path rebuilt
    # the complete team morale snapshot twice per player.
    snapshot = morale_snapshot_v1(
        state,
        resolved_team,
    )

    adjusted: list[Any] = []

    for decision in rows:
        pid = _clean(
            getattr(
                decision,
                "player_id",
                "",
            )
        )
        policy = _clean(
            getattr(
                decision,
                "asset_policy",
                "",
            )
        )

        if (
            not pid
            or not policy
        ):
            adjusted.append(
                decision
            )
            continue

        context = (
            morale_trade_market_context_v1(
                state,
                resolved_team,
                pid,
                _snapshot=snapshot,
            )
        )

        if not context.should_market:
            adjusted.append(
                decision
            )
            continue

        # A normal "Untouchable" designation still wins over
        # mere dissatisfaction. A real active trade request,
        # however, can move even a protected core player into
        # a listen-only market posture. The asking-price layer
        # keeps that player expensive.
        if (
            policy == "Untouchable"
            and not context.request_active
        ):
            adjusted.append(
                decision
            )
            continue

        adjusted.append(
            _replace_decision(
                decision,
                asset_policy="Market",
            )
        )

    return tuple(
        adjusted
    )


def morale_trade_market_rows_v1(
    state: Any,
    *,
    controlled_teams: Iterable[str] = (),
    include_quiet: bool = False,
) -> list[dict[str, Any]]:
    controlled = {
        _team(value)
        for value
        in controlled_teams
        if _team(value)
    }
    rows: list[
        dict[str, Any]
    ] = []

    for team, team_state in sorted(
        (
            getattr(
                state,
                "teams",
                {},
            )
            or {}
        ).items()
    ):
        resolved_team = _team(
            team
        )
        if (
            not resolved_team
            or resolved_team
            in controlled
        ):
            continue

        for raw_pid in tuple(
            getattr(
                team_state,
                "roster_player_ids",
                (),
            )
            or ()
        ):
            context = (
                morale_trade_market_context_v1(
                    state,
                    resolved_team,
                    str(raw_pid),
                )
            )

            if (
                not include_quiet
                and not (
                    context.should_market
                    or context.request_active
                    or context.trade_risk
                    >= 40.0
                    or context.request_status
                    not in {
                        "",
                        "None",
                        "No request",
                    }
                )
            ):
                continue

            rows.append(
                {
                    "Team": (
                        context.team
                    ),
                    "Player": (
                        context.player_name
                    ),
                    "Morale": (
                        context.morale
                    ),
                    "Risk %": (
                        context.trade_risk
                    ),
                    "Request": (
                        context.request_status
                    ),
                    "CPU response": (
                        context
                        .front_office_response
                    ),
                    "Market posture": (
                        context
                        .market_posture
                    ),
                    "Willingness": (
                        context
                        .willingness_modifier
                    ),
                    "Seller ask": (
                        context
                        .seller_ask_multiplier
                    ),
                    "Core": (
                        "Yes"
                        if context.core_player
                        else "No"
                    ),
                    "Why": " ".join(
                        context.rationale
                    ),
                }
            )

    rows.sort(
        key=lambda row: (
            -float(
                row["Risk %"]
            ),
            row["Team"],
            row["Player"],
        )
    )
    return rows


def render_morale_trade_market_audit_v1(
    state: Any,
    *,
    controlled_teams: Iterable[str] = (),
) -> None:
    import pandas as pd
    import streamlit as st

    rows = morale_trade_market_rows_v1(
        state,
        controlled_teams=(
            controlled_teams
        ),
    )

    st.markdown(
        "### Morale-adjusted trade market"
    )
    st.caption(
        "Morale can change whether a CPU team listens to offers, "
        "but it does not change player ratings, intrinsic market "
        "value, CBA legality, or force a transaction. Seller ask "
        "is a planning context for the next Trade Finder bridge."
    )

    marketed = sum(
        row["Market posture"]
        != "Keep internal"
        for row in rows
    )
    requests = sum(
        row["Request"]
        == "Requested trade"
        for row in rows
    )
    listening = sum(
        row["CPU response"]
        == "Listening to offers"
        for row in rows
    )
    blocked = sum(
        row["CPU response"]
        == "On trade block"
        for row in rows
    )

    metric_cols = st.columns(
        4
    )
    metric_cols[0].metric(
        "Market-active",
        marketed,
    )
    metric_cols[1].metric(
        "Trade requests",
        requests,
    )
    metric_cols[2].metric(
        "Listening",
        listening,
    )
    metric_cols[3].metric(
        "Trade block",
        blocked,
    )

    if not rows:
        st.info(
            "No CPU player currently has enough morale or "
            "trade-request pressure to alter trade-market posture."
        )
        return

    st.dataframe(
        pd.DataFrame(
            rows
        ),
        hide_index=True,
        width="stretch",
        column_config={
            "Morale": (
                st.column_config
                .NumberColumn(
                    format="%.1f"
                )
            ),
            "Risk %": (
                st.column_config
                .NumberColumn(
                    format="%.1f"
                )
            ),
            "Willingness": (
                st.column_config
                .NumberColumn(
                    format="%.3f"
                )
            ),
            "Seller ask": (
                st.column_config
                .NumberColumn(
                    format="%.3f"
                )
            ),
        },
    )
