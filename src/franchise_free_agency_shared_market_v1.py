from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from franchise_offseason_market_season_v1 import resolve_offseason_market_season
from franchise_free_agency_competing_market_v1 import (
    FREE_AGENCY_COMPETING_MARKET_VERSION,
    FreeAgencyCompetingMarketResult,
    commit_competing_market_winner_live,
    evaluate_competing_offer_market,
)
from franchise_free_agency_cpu_offer_generation_v1 import (
    CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
    CPUFreeAgencyOfferBoard,
    CPUFreeAgencyGeneratedOffer,
    build_cpu_free_agency_offer_board,
)
from franchise_free_agency_live_signing_v1 import (
    FREE_AGENCY_LIVE_SIGNING_VERSION,
    controlled_teams_from_durable_checkpoint,
)
from franchise_free_agency_player_decision_v1 import (
    FREE_AGENCY_PLAYER_DECISION_VERSION,
    FreeAgencyPlayerDecision,
    evaluate_free_agent_offer_decision,
)
from franchise_free_agency_transaction_v1 import free_agency_state_fingerprint

FREE_AGENCY_SHARED_MARKET_VERSION = (
    "franchise-free-agency-user-cpu-shared-market-v1-2026-08-14"
)
FREE_AGENCY_SHARED_MARKET_SCOPE = (
    "user_offer_plus_real_cpu_target_board_bids_same_player_no_silent_cpu_commit"
)
FREE_AGENCY_SHARED_MARKET_UI_VERSION = (
    "franchise-free-agency-user-cpu-shared-market-ui-v1-2026-08-14"
)


class FreeAgencySharedMarketError(RuntimeError):
    """Raised when a user + CPU shared market cannot be evaluated safely."""


@dataclass(frozen=True)
class SharedMarketCPUOfferSummary:
    team_abbreviation: str
    annual_salary: float
    years: int
    target_fit_score: float
    team_direction: str
    salary_posture: str
    cap_space_before: float
    offer_fingerprint: str


@dataclass(frozen=True)
class FreeAgencyUserCPUSharedMarketResult:
    version: str
    scope: str
    season_label: str
    player_id: str
    player_name: str
    user_team_abbreviation: str
    controlled_teams: tuple[str, ...]
    source_state_fingerprint: str
    user_preview_source_fingerprint: str
    cpu_board_fingerprint: str
    cpu_offer_count: int
    cpu_offers: tuple[SharedMarketCPUOfferSummary, ...]
    previews: tuple[Any, ...]
    user_decision: FreeAgencyPlayerDecision
    market: FreeAgencyCompetingMarketResult
    shared_market_fingerprint: str

    @property
    def has_cpu_competition(self) -> bool:
        return self.cpu_offer_count > 0

    @property
    def user_is_winner(self) -> bool:
        return (
            bool(self.market.has_winner)
            and _team(self.market.winner_team_abbreviation)
            == self.user_team_abbreviation
        )


@dataclass(frozen=True)
class SharedMarketUserLiveSigningResult:
    version: str
    shared_market_fingerprint: str
    market_fingerprint: str
    winner_team_abbreviation: str
    live_signing_result: Any


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _season(state: Any) -> str:
    return resolve_offseason_market_season(state)


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _preview_offer(preview: Any) -> Any:
    offer = getattr(preview, "offer", None)
    if offer is None:
        raise FreeAgencySharedMarketError(
            "The user market entry does not contain a free-agency offer."
        )
    return offer


def _assert_user_preview_is_legal(preview: Any) -> None:
    if (
        _clean(getattr(preview, "status", "")).lower() != "pass"
        or not bool(getattr(preview, "can_commit", False))
    ):
        raise FreeAgencySharedMarketError(
            "The user offer must clear every locked free-agency backend gate before entering the shared market."
        )


def _cpu_offers_for_player(
    board: CPUFreeAgencyOfferBoard,
    player_id: str,
) -> tuple[CPUFreeAgencyGeneratedOffer, ...]:
    offers = [
        row
        for row in board.offers
        if _clean(row.player_id) == player_id
    ]
    offers.sort(
        key=lambda row: (
            -float(row.target_fit_score),
            -float(row.annual_salary),
            _team(row.team_abbreviation),
            row.offer_fingerprint,
        )
    )
    return tuple(offers)


def build_user_cpu_shared_market(
    state: Any,
    user_preview: Any,
    *,
    controlled_teams: Iterable[str],
    front_office_plan: Any | None = None,
    max_targets_per_team: int = 5,
    cpu_offer_board: CPUFreeAgencyOfferBoard | None = None,
) -> FreeAgencyUserCPUSharedMarketResult:
    """Build one player's market from the user's legal offer plus real CPU bids.

    CPU bids come only from CPU Offer Generation V1 and therefore only from the
    existing CPU Front Office target boards. User-controlled teams are passed into
    that generator and excluded from CPU bidding. This function is read-only.
    """
    _assert_user_preview_is_legal(user_preview)
    offer = _preview_offer(user_preview)
    player_id = _clean(getattr(offer, "player_id", ""))
    user_team = _team(getattr(offer, "team_abbreviation", ""))
    if not player_id or not user_team:
        raise FreeAgencySharedMarketError(
            "The user offer requires both a player and signing team."
        )

    controlled = tuple(
        sorted({_team(value) for value in controlled_teams if _team(value)})
    )
    if user_team not in set(controlled):
        raise FreeAgencySharedMarketError(
            "The shared user market can be opened only for a user-controlled signing team."
        )

    board = cpu_offer_board or build_cpu_free_agency_offer_board(
        state,
        controlled_teams=controlled,
        front_office_plan=front_office_plan,
        max_targets_per_team=max_targets_per_team,
    )
    cpu_offers = _cpu_offers_for_player(board, player_id)
    if any(_team(row.team_abbreviation) in set(controlled) for row in cpu_offers):
        raise FreeAgencySharedMarketError(
            "CPU Offer Generation returned a bid from a user-controlled team."
        )
    if any(
        _clean(getattr(row.preview, "status", "")).lower() != "pass"
        or not bool(getattr(row.preview, "can_commit", False))
        for row in cpu_offers
    ):
        raise FreeAgencySharedMarketError(
            "Every CPU bid in a shared market must be a locked backend PASS preview."
        )

    previews = (user_preview, *(row.preview for row in cpu_offers))
    market = evaluate_competing_offer_market(state, previews)
    user_decision = evaluate_free_agent_offer_decision(state, user_preview)
    player_name = _clean(user_decision.player_name) or player_id
    source_state_fingerprint = free_agency_state_fingerprint(state)
    user_source = _clean(getattr(user_preview, "source_fingerprint", ""))

    summaries = tuple(
        SharedMarketCPUOfferSummary(
            team_abbreviation=_team(row.team_abbreviation),
            annual_salary=float(row.annual_salary),
            years=int(row.years),
            target_fit_score=float(row.target_fit_score),
            team_direction=_clean(row.team_direction),
            salary_posture=_clean(row.salary_posture),
            cap_space_before=float(row.cap_space_before),
            offer_fingerprint=row.offer_fingerprint,
        )
        for row in cpu_offers
    )
    payload = {
        "version": FREE_AGENCY_SHARED_MARKET_VERSION,
        "scope": FREE_AGENCY_SHARED_MARKET_SCOPE,
        "season": _season(state),
        "player_id": player_id,
        "user_team": user_team,
        "controlled_teams": list(controlled),
        "source_state_fingerprint": source_state_fingerprint,
        "user_preview_source_fingerprint": user_source,
        "cpu_board_fingerprint": board.board_fingerprint,
        "cpu_offer_fingerprints": [row.offer_fingerprint for row in cpu_offers],
        "market_fingerprint": market.market_fingerprint,
    }
    return FreeAgencyUserCPUSharedMarketResult(
        version=FREE_AGENCY_SHARED_MARKET_VERSION,
        scope=FREE_AGENCY_SHARED_MARKET_SCOPE,
        season_label=_season(state),
        player_id=player_id,
        player_name=player_name,
        user_team_abbreviation=user_team,
        controlled_teams=controlled,
        source_state_fingerprint=source_state_fingerprint,
        user_preview_source_fingerprint=user_source,
        cpu_board_fingerprint=board.board_fingerprint,
        cpu_offer_count=len(cpu_offers),
        cpu_offers=summaries,
        previews=tuple(previews),
        user_decision=user_decision,
        market=market,
        shared_market_fingerprint=_fingerprint(payload),
    )


def shared_market_matches_state_and_preview(
    state: Any,
    user_preview: Any,
    result: Any,
) -> bool:
    if not isinstance(result, FreeAgencyUserCPUSharedMarketResult):
        return False
    try:
        offer = _preview_offer(user_preview)
    except Exception:
        return False
    return (
        result.source_state_fingerprint == free_agency_state_fingerprint(state)
        and result.player_id == _clean(getattr(offer, "player_id", ""))
        and result.user_team_abbreviation == _team(getattr(offer, "team_abbreviation", ""))
        and result.user_preview_source_fingerprint
        == _clean(getattr(user_preview, "source_fingerprint", ""))
    )


def commit_user_shared_market_winner_live(
    user_preview: Any,
    result: FreeAgencyUserCPUSharedMarketResult,
    *,
    hypothetical: bool = False,
) -> SharedMarketUserLiveSigningResult:
    """Commit only when the user-controlled offer wins the current shared market.

    CPU winners are intentionally not committed here. CPU Execution V1 remains the
    explicit authority for durable CPU-only signing rounds.
    """
    if hypothetical:
        raise FreeAgencySharedMarketError(
            "A hypothetical user + CPU shared market can never be committed."
        )
    if not isinstance(result, FreeAgencyUserCPUSharedMarketResult):
        raise FreeAgencySharedMarketError("The shared market result is invalid.")
    if not result.user_is_winner:
        raise FreeAgencySharedMarketError(
            "The user-controlled offer is not the current shared-market winner."
        )

    from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint

    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise FreeAgencySharedMarketError(
            "The durable franchise checkpoint is unavailable."
        )
    state = getattr(checkpoint, "simulation_state", None)
    controlled = controlled_teams_from_durable_checkpoint(checkpoint, state)
    current = build_user_cpu_shared_market(
        state,
        user_preview,
        controlled_teams=controlled,
    )
    if current.shared_market_fingerprint != result.shared_market_fingerprint:
        raise FreeAgencySharedMarketError(
            "The shared market is stale relative to the durable franchise state or current CPU bids."
        )
    if not current.user_is_winner:
        raise FreeAgencySharedMarketError(
            "The user-controlled team no longer wins the current shared market."
        )

    signed = commit_competing_market_winner_live(
        current.previews,
        current.market,
        hypothetical=False,
    )
    live = signed.player_decision_result.live_signing_result
    return SharedMarketUserLiveSigningResult(
        version=FREE_AGENCY_SHARED_MARKET_VERSION,
        shared_market_fingerprint=current.shared_market_fingerprint,
        market_fingerprint=current.market.market_fingerprint,
        winner_team_abbreviation=current.user_team_abbreviation,
        live_signing_result=live,
    )


def shared_market_contract_report() -> dict[str, Any]:
    return {
        "version": FREE_AGENCY_SHARED_MARKET_VERSION,
        "scope": FREE_AGENCY_SHARED_MARKET_SCOPE,
        "cpu_offer_generation_version": CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
        "competing_market_version": FREE_AGENCY_COMPETING_MARKET_VERSION,
        "player_decision_version": FREE_AGENCY_PLAYER_DECISION_VERSION,
        "live_signing_version": FREE_AGENCY_LIVE_SIGNING_VERSION,
        "cpu_bids_are_real_target_board_bids": True,
        "user_controlled_teams_are_cpu_excluded": True,
        "cpu_winner_commit_enabled_here": False,
        "user_winner_commit_uses_competing_market_stack": True,
    }
