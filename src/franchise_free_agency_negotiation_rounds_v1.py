from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from franchise_free_agency_competing_market_v1 import (
    FREE_AGENCY_COMPETING_MARKET_VERSION,
    FreeAgencyCompetingMarketResult,
    commit_competing_market_winner_live,
    evaluate_competing_offer_market,
)
from franchise_free_agency_contract_salary_legality_v1_3 import (
    FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION,
    build_contract_legal_free_agency_preview,
)
from franchise_free_agency_cpu_offer_generation_v1 import (
    CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
    CPUFreeAgencyGeneratedOffer,
    CPUFreeAgencyOfferBoard,
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
    preference_profile,
)
from franchise_free_agency_shared_market_v1 import (
    FREE_AGENCY_SHARED_MARKET_VERSION,
)
from franchise_free_agency_transaction_v1 import (
    FreeAgencyOffer,
    free_agency_state_fingerprint,
)

FREE_AGENCY_NEGOTIATION_ROUNDS_VERSION = (
    "franchise-free-agency-negotiation-market-rounds-v1-2026-08-14"
)
FREE_AGENCY_NEGOTIATION_ROUNDS_UI_VERSION = (
    "franchise-free-agency-negotiation-market-rounds-ui-v1-2026-08-14"
)
FREE_AGENCY_NEGOTIATION_ROUNDS_SCOPE = (
    "explicit_user_advanced_shared_market_rounds_cpu_bids_can_raise_hold_or_withdraw_no_background_commit"
)
MAX_FREE_AGENCY_NEGOTIATION_ROUNDS = 5

ROUND_LABELS = {
    1: "Opening market",
    2: "Early negotiation",
    3: "Mid-market",
    4: "Decision window",
    5: "Final decision",
}


class FreeAgencyNegotiationRoundsError(RuntimeError):
    """Raised when a negotiation round cannot be built or committed safely."""


@dataclass(frozen=True)
class NegotiatedCPUOffer:
    team_abbreviation: str
    action: str
    action_reason: str
    prior_salary: float
    annual_salary: float
    years: int
    target_fit_score: float
    team_direction: str
    salary_posture: str
    minimum_salary_floor: float
    maximum_initial_salary: float
    cap_space_before: float
    preview: Any
    offer_fingerprint: str


@dataclass(frozen=True)
class NegotiationRoundSnapshot:
    round_number: int
    round_label: str
    player_response: str
    winner_team_abbreviation: str | None
    winner_utility_score: float | None
    winning_margin: float | None
    active_cpu_offer_count: int
    increased_cpu_offer_count: int
    withdrawn_cpu_offer_count: int
    market_fingerprint: str


@dataclass(frozen=True)
class FreeAgencyNegotiationRoundResult:
    version: str
    scope: str
    season_label: str
    player_id: str
    player_name: str
    user_team_abbreviation: str
    controlled_teams: tuple[str, ...]
    round_number: int
    max_rounds: int
    round_label: str
    required_decision_round: int
    player_response: str
    player_response_reason: str
    source_state_fingerprint: str
    user_preview_source_fingerprint: str
    user_offer_fingerprint: str
    base_cpu_board_fingerprint: str
    cpu_offers: tuple[NegotiatedCPUOffer, ...]
    previews: tuple[Any, ...]
    user_decision: FreeAgencyPlayerDecision
    market: FreeAgencyCompetingMarketResult
    history: tuple[NegotiationRoundSnapshot, ...]
    negotiation_fingerprint: str

    @property
    def user_is_winner(self) -> bool:
        return (
            bool(self.market.has_winner)
            and _team(self.market.winner_team_abbreviation)
            == self.user_team_abbreviation
        )

    @property
    def ready_to_sign(self) -> bool:
        return self.player_response == "ready_to_sign" and bool(self.market.has_winner)

    @property
    def user_can_commit(self) -> bool:
        return self.ready_to_sign and self.user_is_winner


@dataclass(frozen=True)
class NegotiatedUserLiveSigningResult:
    version: str
    negotiation_fingerprint: str
    round_number: int
    market_fingerprint: str
    winner_team_abbreviation: str
    live_signing_result: Any


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _season(state: Any) -> str:
    return _clean(getattr(getattr(state, "settings", None), "season_label", ""))


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


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
        raise FreeAgencyNegotiationRoundsError(
            "The negotiation entry does not contain a free-agency offer."
        )
    return offer


def _user_offer_fingerprint(preview: Any) -> str:
    offer = _preview_offer(preview)
    return _fingerprint({
        "player": _clean(getattr(offer, "player_id", "")),
        "team": _team(getattr(offer, "team_abbreviation", "")),
        "salary": round(float(getattr(offer, "annual_salary", 0.0) or 0.0), 2),
        "years": int(getattr(offer, "years", 0) or 0),
        "guaranteed": bool(getattr(offer, "guaranteed", False)),
        "option_type": _clean(getattr(offer, "option_type", "")).lower(),
        "source": _clean(getattr(preview, "source_fingerprint", "")),
    })


def _assert_legal_user_preview(preview: Any) -> None:
    if (
        _clean(getattr(preview, "status", "")).lower() != "pass"
        or not bool(getattr(preview, "can_commit", False))
    ):
        raise FreeAgencyNegotiationRoundsError(
            "A user offer must clear every locked free-agency backend gate before entering negotiation rounds."
        )


def _cpu_offers_for_player(
    board: CPUFreeAgencyOfferBoard,
    player_id: str,
) -> tuple[CPUFreeAgencyGeneratedOffer, ...]:
    rows = [row for row in board.offers if _clean(row.player_id) == player_id]
    rows.sort(
        key=lambda row: (
            -float(row.target_fit_score),
            -float(row.annual_salary),
            _team(row.team_abbreviation),
            row.offer_fingerprint,
        )
    )
    return tuple(rows)


def _round_salary(value: float) -> float:
    return round(max(float(value), 0.0) / 50_000.0) * 50_000.0


def _direction_pressure(direction: str) -> float:
    text = _clean(direction).casefold()
    if "championship" in text or "title" in text:
        return 0.012
    if "contend" in text or "win now" in text or "win-now" in text:
        return 0.009
    if "retool" in text:
        return 0.005
    if "develop" in text:
        return 0.001
    if "rebuild" in text:
        return -0.003
    return 0.004


def _evaluation_by_team(market: FreeAgencyCompetingMarketResult) -> dict[str, Any]:
    return {_team(row.team_abbreviation): row for row in market.evaluations}


def _decision_for_preview(state: Any, preview: Any) -> FreeAgencyPlayerDecision:
    return evaluate_free_agent_offer_decision(state, preview)


def _build_adjusted_cpu_preview(
    state: Any,
    row: CPUFreeAgencyGeneratedOffer,
    salary: float,
    *,
    preview_builder: Any,
) -> Any:
    offer = FreeAgencyOffer(
        player_id=row.player_id,
        team_abbreviation=row.team_abbreviation,
        annual_salary=round(float(salary), 2),
        years=int(row.years),
        guaranteed=bool(row.guaranteed),
        option_type=_clean(row.option_type),
    )
    preview = preview_builder(state, offer)
    if (
        _clean(getattr(preview, "status", "")).lower() != "pass"
        or not bool(getattr(preview, "can_commit", False))
    ):
        raise FreeAgencyNegotiationRoundsError(
            f"Negotiated CPU offer for {_team(row.team_abbreviation)} no longer clears the locked backend."
        )
    return preview


def _next_cpu_offer(
    state: Any,
    base_row: CPUFreeAgencyGeneratedOffer,
    prior: NegotiatedCPUOffer,
    prior_market: FreeAgencyCompetingMarketResult,
    *,
    next_round: int,
    preview_builder: Any,
) -> NegotiatedCPUOffer | None:
    team = _team(base_row.team_abbreviation)
    evaluation = _evaluation_by_team(prior_market).get(team)
    decision = _decision_for_preview(state, prior.preview)
    current = float(prior.annual_salary)
    ceiling = min(
        float(base_row.maximum_initial_salary),
        float(base_row.cap_space_before),
    )
    floor = float(base_row.minimum_salary_floor)
    fit = float(base_row.target_fit_score)
    pressure = _direction_pressure(base_row.team_direction)
    gap = (
        float(getattr(evaluation, "utility_gap_to_winner", 0.0) or 0.0)
        if evaluation is not None
        else 0.0
    )
    is_winner = _team(prior_market.winner_team_abbreviation) == team

    if (
        next_round >= 3
        and decision.status == "decline"
        and fit < 74.0
    ):
        return None
    if (
        next_round >= 4
        and not is_winner
        and gap > 8.0
        and fit < 80.0
    ):
        return None
    if (
        next_round >= 5
        and decision.status != "accept"
        and fit < 84.0
    ):
        return None

    target = current
    reason = "Holding the current offer while the market develops."
    if decision.status == "counter" and decision.counter_salary is not None:
        counter = min(float(decision.counter_salary), ceiling)
        step_pct = 0.025 + pressure + max(0.0, (fit - 80.0) * 0.0004)
        max_step = max(250_000.0, current * max(0.015, step_pct))
        target = min(counter, current + max_step)
        reason = "Moving toward the player counter while staying inside verified cap space and salary legality."
    elif decision.status == "decline":
        step_pct = 0.032 + pressure + max(0.0, (fit - 82.0) * 0.0005)
        target = current + max(250_000.0, current * max(0.018, step_pct))
        reason = "Improving a rejected offer because the player remains a meaningful target."
    elif decision.status == "accept":
        if is_winner and (prior_market.winning_margin is None or float(prior_market.winning_margin) >= 3.0):
            target = current
            reason = "The team already leads the accepted market and holds its offer."
        else:
            step_pct = 0.010 + pressure + min(0.018, gap * 0.0015)
            target = current + max(250_000.0, current * max(0.008, step_pct))
            reason = "Increasing an accepted but vulnerable/trailing offer to improve destination utility."

    target = max(floor, min(ceiling, _round_salary(target)))
    if target <= current + 1.0:
        return NegotiatedCPUOffer(
            team_abbreviation=team,
            action="hold",
            action_reason=(
                "Offer is already at its legal/verified budget ceiling."
                if ceiling <= current + 1.0
                else reason
            ),
            prior_salary=current,
            annual_salary=current,
            years=int(base_row.years),
            target_fit_score=fit,
            team_direction=base_row.team_direction,
            salary_posture=base_row.salary_posture,
            minimum_salary_floor=floor,
            maximum_initial_salary=float(base_row.maximum_initial_salary),
            cap_space_before=float(base_row.cap_space_before),
            preview=prior.preview,
            offer_fingerprint=prior.offer_fingerprint,
        )

    try:
        preview = _build_adjusted_cpu_preview(
            state,
            base_row,
            target,
            preview_builder=preview_builder,
        )
    except Exception:
        # Fail closed to the previous legal offer rather than inventing a new route.
        return NegotiatedCPUOffer(
            team_abbreviation=team,
            action="hold",
            action_reason="A larger bid did not clear the locked backend, so the prior legal offer is retained.",
            prior_salary=current,
            annual_salary=current,
            years=int(base_row.years),
            target_fit_score=fit,
            team_direction=base_row.team_direction,
            salary_posture=base_row.salary_posture,
            minimum_salary_floor=floor,
            maximum_initial_salary=float(base_row.maximum_initial_salary),
            cap_space_before=float(base_row.cap_space_before),
            preview=prior.preview,
            offer_fingerprint=prior.offer_fingerprint,
        )

    payload = {
        "version": FREE_AGENCY_NEGOTIATION_ROUNDS_VERSION,
        "player": base_row.player_id,
        "team": team,
        "round": next_round,
        "salary": round(float(target), 2),
        "years": int(base_row.years),
        "source": _clean(getattr(preview, "source_fingerprint", "")),
        "base_offer": base_row.offer_fingerprint,
    }
    return NegotiatedCPUOffer(
        team_abbreviation=team,
        action="increase",
        action_reason=reason,
        prior_salary=current,
        annual_salary=round(float(target), 2),
        years=int(base_row.years),
        target_fit_score=fit,
        team_direction=base_row.team_direction,
        salary_posture=base_row.salary_posture,
        minimum_salary_floor=floor,
        maximum_initial_salary=float(base_row.maximum_initial_salary),
        cap_space_before=float(base_row.cap_space_before),
        preview=preview,
        offer_fingerprint=_fingerprint(payload),
    )


def _opening_cpu_offer(row: CPUFreeAgencyGeneratedOffer) -> NegotiatedCPUOffer:
    return NegotiatedCPUOffer(
        team_abbreviation=_team(row.team_abbreviation),
        action="open",
        action_reason="Opening bid from the current CPU Front Office target board.",
        prior_salary=float(row.annual_salary),
        annual_salary=float(row.annual_salary),
        years=int(row.years),
        target_fit_score=float(row.target_fit_score),
        team_direction=row.team_direction,
        salary_posture=row.salary_posture,
        minimum_salary_floor=float(row.minimum_salary_floor),
        maximum_initial_salary=float(row.maximum_initial_salary),
        cap_space_before=float(row.cap_space_before),
        preview=row.preview,
        offer_fingerprint=row.offer_fingerprint,
    )


def _required_decision_round(state: Any, player_id: str) -> int:
    player = getattr(state, "players", {}).get(player_id)
    if player is None:
        return 2
    profile = preference_profile(state, player)
    # Maps deterministic market patience to rounds 1-4. The final fifth round is
    # always a hard decision window when an accepted winner exists.
    return max(1, min(4, 1 + int(float(profile.market_patience) * 4.0)))


def _player_response(
    state: Any,
    player_id: str,
    market: FreeAgencyCompetingMarketResult,
    round_number: int,
) -> tuple[str, str, int]:
    required_round = _required_decision_round(state, player_id)
    player = getattr(state, "players", {}).get(player_id)
    profile = preference_profile(state, player) if player is not None else None
    patience = float(profile.market_patience) if profile is not None else 0.5

    if market.has_winner:
        margin = float(market.winning_margin or 0.0)
        convincing_margin = 9.0 - 4.0 * patience
        if (
            round_number >= MAX_FREE_AGENCY_NEGOTIATION_ROUNDS
            or round_number >= required_round
            or margin >= convincing_margin
        ):
            return (
                "ready_to_sign",
                "The player is ready to choose the current preferred accepted destination.",
                required_round,
            )
        return (
            "hold",
            "The player views at least one offer as acceptable but is holding the market open for another negotiation round.",
            required_round,
        )

    if market.status == "counter_market":
        if round_number < MAX_FREE_AGENCY_NEGOTIATION_ROUNDS:
            return (
                "counter_market",
                "No destination has cleared the acceptance threshold yet; the market remains open around reachable counters.",
                required_round,
            )
        return (
            "no_acceptable_offer",
            "The final decision window closed without an accepted offer.",
            required_round,
        )

    if round_number < MAX_FREE_AGENCY_NEGOTIATION_ROUNDS:
        return (
            "exploring_market",
            "The player has no acceptable offer yet and remains on the market for another round.",
            required_round,
        )
    return (
        "no_acceptable_offer",
        "The final decision window closed without an acceptable destination.",
        required_round,
    )


def _snapshot(
    round_number: int,
    response: str,
    market: FreeAgencyCompetingMarketResult,
    cpu_offers: tuple[NegotiatedCPUOffer, ...],
    withdrawn_count: int,
) -> NegotiationRoundSnapshot:
    return NegotiationRoundSnapshot(
        round_number=round_number,
        round_label=ROUND_LABELS[round_number],
        player_response=response,
        winner_team_abbreviation=(
            _team(market.winner_team_abbreviation)
            if market.winner_team_abbreviation
            else None
        ),
        winner_utility_score=(
            float(market.winner_utility_score)
            if market.winner_utility_score is not None
            else None
        ),
        winning_margin=(
            float(market.winning_margin)
            if market.winning_margin is not None
            else None
        ),
        active_cpu_offer_count=len(cpu_offers),
        increased_cpu_offer_count=sum(row.action == "increase" for row in cpu_offers),
        withdrawn_cpu_offer_count=int(withdrawn_count),
        market_fingerprint=market.market_fingerprint,
    )


def build_free_agency_negotiation_round(
    state: Any,
    user_preview: Any,
    *,
    controlled_teams: Iterable[str],
    round_number: int = 1,
    front_office_plan: Any | None = None,
    max_targets_per_team: int = 5,
    cpu_offer_board: CPUFreeAgencyOfferBoard | None = None,
    preview_builder: Any | None = None,
) -> FreeAgencyNegotiationRoundResult:
    """Build a deterministic multi-round user + CPU free-agent negotiation.

    The function is read-only. CPU offers may increase, hold, or withdraw as the
    explicitly advanced round number changes. No CPU or user signing occurs here.
    """
    _assert_legal_user_preview(user_preview)
    if not 1 <= int(round_number) <= MAX_FREE_AGENCY_NEGOTIATION_ROUNDS:
        raise FreeAgencyNegotiationRoundsError(
            f"round_number must be between 1 and {MAX_FREE_AGENCY_NEGOTIATION_ROUNDS}."
        )

    offer = _preview_offer(user_preview)
    player_id = _clean(getattr(offer, "player_id", ""))
    user_team = _team(getattr(offer, "team_abbreviation", ""))
    if not player_id or not user_team:
        raise FreeAgencyNegotiationRoundsError(
            "The user negotiation offer requires both player and signing team."
        )

    controlled = tuple(
        sorted({_team(value) for value in controlled_teams if _team(value)})
    )
    if user_team not in set(controlled):
        raise FreeAgencyNegotiationRoundsError(
            "Negotiation rounds can be opened only for a user-controlled signing team."
        )

    board = cpu_offer_board or build_cpu_free_agency_offer_board(
        state,
        controlled_teams=controlled,
        front_office_plan=front_office_plan,
        max_targets_per_team=max_targets_per_team,
    )
    base_rows = _cpu_offers_for_player(board, player_id)
    if any(_team(row.team_abbreviation) in set(controlled) for row in base_rows):
        raise FreeAgencyNegotiationRoundsError(
            "A user-controlled team appeared in the CPU negotiation board."
        )

    builder = preview_builder or build_contract_legal_free_agency_preview
    current_cpu = tuple(_opening_cpu_offer(row) for row in base_rows)
    history: list[NegotiationRoundSnapshot] = []
    user_decision = evaluate_free_agent_offer_decision(state, user_preview)
    final_market: FreeAgencyCompetingMarketResult | None = None
    final_response = ""
    final_reason = ""
    required_round = _required_decision_round(state, player_id)

    for current_round in range(1, int(round_number) + 1):
        withdrawn = 0
        if current_round > 1:
            assert final_market is not None
            prior_by_team = {row.team_abbreviation: row for row in current_cpu}
            next_cpu: list[NegotiatedCPUOffer] = []
            for base_row in base_rows:
                team = _team(base_row.team_abbreviation)
                prior = prior_by_team.get(team)
                if prior is None:
                    # Withdrawals are final for this negotiation snapshot.
                    continue
                evolved = _next_cpu_offer(
                    state,
                    base_row,
                    prior,
                    final_market,
                    next_round=current_round,
                    preview_builder=builder,
                )
                if evolved is None:
                    withdrawn += 1
                    continue
                next_cpu.append(evolved)
            current_cpu = tuple(sorted(next_cpu, key=lambda row: row.team_abbreviation))

        previews = (user_preview, *(row.preview for row in current_cpu))
        final_market = evaluate_competing_offer_market(state, previews)
        final_response, final_reason, required_round = _player_response(
            state,
            player_id,
            final_market,
            current_round,
        )
        history.append(
            _snapshot(
                current_round,
                final_response,
                final_market,
                current_cpu,
                withdrawn,
            )
        )

    assert final_market is not None
    player_name = _clean(user_decision.player_name) or player_id
    source_state_fingerprint = free_agency_state_fingerprint(state)
    user_source = _clean(getattr(user_preview, "source_fingerprint", ""))
    user_offer_fingerprint = _user_offer_fingerprint(user_preview)
    payload = {
        "version": FREE_AGENCY_NEGOTIATION_ROUNDS_VERSION,
        "scope": FREE_AGENCY_NEGOTIATION_ROUNDS_SCOPE,
        "season": _season(state),
        "player": player_id,
        "user_team": user_team,
        "controlled": list(controlled),
        "round": int(round_number),
        "source_state_fingerprint": source_state_fingerprint,
        "user_preview_source_fingerprint": user_source,
        "user_offer_fingerprint": user_offer_fingerprint,
        "base_cpu_board_fingerprint": board.board_fingerprint,
        "cpu_offers": [
            {
                "team": row.team_abbreviation,
                "action": row.action,
                "salary": row.annual_salary,
                "offer_fingerprint": row.offer_fingerprint,
            }
            for row in current_cpu
        ],
        "response": final_response,
        "market_fingerprint": final_market.market_fingerprint,
        "history": [
            {
                "round": row.round_number,
                "response": row.player_response,
                "winner": row.winner_team_abbreviation,
                "market": row.market_fingerprint,
                "active_cpu": row.active_cpu_offer_count,
                "increased_cpu": row.increased_cpu_offer_count,
                "withdrawn_cpu": row.withdrawn_cpu_offer_count,
            }
            for row in history
        ],
    }
    return FreeAgencyNegotiationRoundResult(
        version=FREE_AGENCY_NEGOTIATION_ROUNDS_VERSION,
        scope=FREE_AGENCY_NEGOTIATION_ROUNDS_SCOPE,
        season_label=_season(state),
        player_id=player_id,
        player_name=player_name,
        user_team_abbreviation=user_team,
        controlled_teams=controlled,
        round_number=int(round_number),
        max_rounds=MAX_FREE_AGENCY_NEGOTIATION_ROUNDS,
        round_label=ROUND_LABELS[int(round_number)],
        required_decision_round=required_round,
        player_response=final_response,
        player_response_reason=final_reason,
        source_state_fingerprint=source_state_fingerprint,
        user_preview_source_fingerprint=user_source,
        user_offer_fingerprint=user_offer_fingerprint,
        base_cpu_board_fingerprint=board.board_fingerprint,
        cpu_offers=current_cpu,
        previews=previews,
        user_decision=user_decision,
        market=final_market,
        history=tuple(history),
        negotiation_fingerprint=_fingerprint(payload),
    )


def negotiation_round_matches_state_and_preview(
    state: Any,
    user_preview: Any,
    result: Any,
    *,
    controlled_teams: Iterable[str] | None = None,
) -> bool:
    if not isinstance(result, FreeAgencyNegotiationRoundResult):
        return False
    try:
        offer = _preview_offer(user_preview)
    except Exception:
        return False
    if (
        result.source_state_fingerprint != free_agency_state_fingerprint(state)
        or result.player_id != _clean(getattr(offer, "player_id", ""))
        or result.user_team_abbreviation
        != _team(getattr(offer, "team_abbreviation", ""))
        or result.user_preview_source_fingerprint
        != _clean(getattr(user_preview, "source_fingerprint", ""))
        or result.user_offer_fingerprint != _user_offer_fingerprint(user_preview)
    ):
        return False
    if controlled_teams is not None:
        controlled = tuple(
            sorted({_team(value) for value in controlled_teams if _team(value)})
        )
        if result.controlled_teams != controlled:
            return False
    return True


def commit_negotiated_user_winner_live(
    user_preview: Any,
    result: FreeAgencyNegotiationRoundResult,
    *,
    hypothetical: bool = False,
) -> NegotiatedUserLiveSigningResult:
    """Commit a user winner only after the player is ready to sign this round."""
    if hypothetical:
        raise FreeAgencyNegotiationRoundsError(
            "A hypothetical free-agency negotiation can never be committed."
        )
    if not isinstance(result, FreeAgencyNegotiationRoundResult):
        raise FreeAgencyNegotiationRoundsError("The negotiation result is invalid.")
    if not result.ready_to_sign:
        raise FreeAgencyNegotiationRoundsError(
            "The player is not ready to sign in the current negotiation round."
        )
    if not result.user_is_winner:
        raise FreeAgencyNegotiationRoundsError(
            "The user-controlled team is not the current negotiation winner."
        )

    from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint

    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise FreeAgencyNegotiationRoundsError(
            "The durable franchise checkpoint is unavailable."
        )
    state = getattr(checkpoint, "simulation_state", None)
    controlled = controlled_teams_from_durable_checkpoint(checkpoint)
    if result.user_team_abbreviation not in set(controlled):
        raise FreeAgencyNegotiationRoundsError(
            "The negotiation winner is no longer a user-controlled team."
        )

    current = build_free_agency_negotiation_round(
        state,
        user_preview,
        controlled_teams=controlled,
        round_number=result.round_number,
    )
    if current.negotiation_fingerprint != result.negotiation_fingerprint:
        raise FreeAgencyNegotiationRoundsError(
            "The negotiation round is stale relative to the durable franchise state, CPU bids, or user offer."
        )
    if not current.user_can_commit:
        raise FreeAgencyNegotiationRoundsError(
            "The user offer no longer wins a ready-to-sign durable negotiation market."
        )

    signed = commit_competing_market_winner_live(
        current.previews,
        current.market,
        hypothetical=False,
    )
    live = signed.player_decision_result.live_signing_result
    return NegotiatedUserLiveSigningResult(
        version=FREE_AGENCY_NEGOTIATION_ROUNDS_VERSION,
        negotiation_fingerprint=current.negotiation_fingerprint,
        round_number=current.round_number,
        market_fingerprint=current.market.market_fingerprint,
        winner_team_abbreviation=current.user_team_abbreviation,
        live_signing_result=live,
    )


def negotiation_rounds_contract_report() -> dict[str, Any]:
    return {
        "version": FREE_AGENCY_NEGOTIATION_ROUNDS_VERSION,
        "scope": FREE_AGENCY_NEGOTIATION_ROUNDS_SCOPE,
        "shared_market_version": FREE_AGENCY_SHARED_MARKET_VERSION,
        "cpu_offer_generation_version": CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
        "competing_market_version": FREE_AGENCY_COMPETING_MARKET_VERSION,
        "player_decision_version": FREE_AGENCY_PLAYER_DECISION_VERSION,
        "salary_legality_version": FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION,
        "live_signing_version": FREE_AGENCY_LIVE_SIGNING_VERSION,
        "max_rounds": MAX_FREE_AGENCY_NEGOTIATION_ROUNDS,
        "explicit_advance_required": True,
        "background_autonomy_enabled": False,
        "cpu_offer_actions": ("open", "hold", "increase", "withdraw"),
        "cpu_winner_silent_commit_enabled": False,
        "user_commit_requires_ready_to_sign": True,
        "user_commit_requires_market_win": True,
    }
