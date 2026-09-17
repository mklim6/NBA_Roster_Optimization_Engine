from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from franchise_morale_trade_market_v1 import (
    morale_trade_market_context_v1,
)

MORALE_TRADE_FINDER_TERMS_VERSION = (
    "franchise-morale-trade-finder-terms-v5b-2026-09-16"
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
        return float(value)
    except (TypeError, ValueError):
        return float(default)


@dataclass(frozen=True)
class MoraleTradeFinderSellerTerms:
    version: str
    team: str
    player_id: str
    player_name: str
    material_context: bool
    market_posture: str
    front_office_response: str
    request_status: str
    request_active: bool
    trade_risk: float
    core_player: bool
    willingness_modifier: float
    seller_ask_multiplier: float
    base_accept_floor: float
    floor_adjustment: float
    adjusted_accept_floor: float
    search_priority_bonus: float
    override_untouchable: bool
    rationale: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def build_morale_trade_finder_terms_v1(
    state: Any,
    partner_team: str,
    target_row: dict[str, Any],
    *,
    base_accept_floor: float,
) -> MoraleTradeFinderSellerTerms:
    """Translate V5A morale posture into seller-side Trade Finder terms.

    This does not change intrinsic player value. It changes only:
    - whether an escalated requested player may enter the CPU market,
    - search priority among otherwise legal targets, and
    - the CPU seller's acceptance floor.
    """
    team = _team(partner_team)
    player_id = _clean(
        target_row.get("player_id")
    )

    context = morale_trade_market_context_v1(
        state,
        team,
        player_id,
    )

    request_status = _clean(
        context.request_status
    ) or "None"
    material = bool(
        context.should_market
        or context.request_active
        or float(context.trade_risk) >= 30.0
        or request_status
        not in {
            "",
            "None",
            "No request",
        }
        or context.front_office_response
        != "Keep internal"
    )

    base_floor = float(
        base_accept_floor
    )

    if material:
        # Seller ask is deliberately a *small* modifier on the
        # existing CPU delta threshold. A trade request can loosen
        # the ask, but it never rewrites the player's intrinsic value.
        raw_adjustment = (
            float(
                context.seller_ask_multiplier
            )
            - 1.0
        ) * 25.0
        floor_adjustment = max(
            -2.5,
            min(
                3.5,
                raw_adjustment,
            ),
        )
    else:
        floor_adjustment = 0.0

    adjusted_floor = round(
        base_floor
        + floor_adjustment,
        2,
    )

    if (
        context.market_posture
        == "Actively market"
    ):
        priority_bonus = 8.0
    elif (
        context.market_posture
        == "Listen to offers"
    ):
        priority_bonus = 5.0
    else:
        priority_bonus = 0.0

    if (
        context.request_active
        and priority_bonus > 0.0
    ):
        priority_bonus += 2.0

    # Only a genuine requested/block situation can unlock a player
    # whom the baseline Trade Finder classified as untouchable.
    override_untouchable = bool(
        context.should_market
        and (
            context.request_active
            or context.front_office_response
            == "On trade block"
        )
    )

    reasons = list(
        context.rationale
    )
    if material:
        if floor_adjustment < 0:
            reasons.append(
                "Morale pressure modestly lowers the CPU seller's "
                "acceptance threshold without discounting intrinsic value."
            )
        elif floor_adjustment > 0:
            reasons.append(
                "The CPU is still resisting a move, so the seller "
                "acceptance threshold remains above the neutral market."
            )
        else:
            reasons.append(
                "Morale pressure is visible but does not currently "
                "change the seller acceptance threshold."
            )

    return MoraleTradeFinderSellerTerms(
        version=(
            MORALE_TRADE_FINDER_TERMS_VERSION
        ),
        team=team,
        player_id=player_id,
        player_name=(
            context.player_name
        ),
        material_context=material,
        market_posture=(
            context.market_posture
        ),
        front_office_response=(
            context.front_office_response
        ),
        request_status=(
            request_status
        ),
        request_active=bool(
            context.request_active
        ),
        trade_risk=round(
            float(
                context.trade_risk
            ),
            1,
        ),
        core_player=bool(
            context.core_player
        ),
        willingness_modifier=round(
            float(
                context.willingness_modifier
            ),
            3,
        ),
        seller_ask_multiplier=round(
            float(
                context.seller_ask_multiplier
            ),
            3,
        ),
        base_accept_floor=round(
            base_floor,
            2,
        ),
        floor_adjustment=round(
            floor_adjustment,
            2,
        ),
        adjusted_accept_floor=(
            adjusted_floor
        ),
        search_priority_bonus=round(
            priority_bonus,
            2,
        ),
        override_untouchable=(
            override_untouchable
        ),
        rationale=tuple(
            reasons
        ),
    )


def morale_trade_finder_target_available_v1(
    state: Any,
    partner_team: str,
    target_row: dict[str, Any],
    *,
    base_untouchable: bool,
) -> bool:
    if not base_untouchable:
        return True

    terms = build_morale_trade_finder_terms_v1(
        state,
        partner_team,
        target_row,
        base_accept_floor=0.0,
    )
    return bool(
        terms.override_untouchable
    )


def morale_trade_finder_search_bonus_v1(
    state: Any,
    partner_team: str,
    target_row: dict[str, Any],
) -> float:
    terms = build_morale_trade_finder_terms_v1(
        state,
        partner_team,
        target_row,
        base_accept_floor=0.0,
    )
    return float(
        terms.search_priority_bonus
    )
