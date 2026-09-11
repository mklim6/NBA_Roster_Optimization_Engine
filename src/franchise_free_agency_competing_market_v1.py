from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Sequence

from franchise_offseason_market_season_v1 import resolve_offseason_market_season
from franchise_free_agency_player_decision_v1 import (
    FREE_AGENCY_PLAYER_DECISION_VERSION,
    FreeAgencyPlayerDecision,
    FreeAgencyPlayerDecisionError,
    PlayerAcceptedLiveSigningResult,
    commit_player_accepted_free_agency_preview_live,
    decision_matches_preview,
    evaluate_free_agent_offer_decision,
)

FREE_AGENCY_COMPETING_MARKET_VERSION = (
    "franchise-free-agency-competing-offer-market-v1-2026-08-14"
)
FREE_AGENCY_COMPETING_MARKET_SCOPE = (
    "multiple_explicit_legal_offers_player_choice_no_cpu_offer_generation"
)


class FreeAgencyCompetingMarketError(RuntimeError):
    """Raised when a competing free-agent market cannot be evaluated safely."""


@dataclass(frozen=True)
class CompetingOfferEvaluation:
    team_abbreviation: str
    offer_id: str
    annual_salary: float
    years: int
    guaranteed: bool
    option_type: str
    utility_score: float
    acceptance_threshold: float
    player_decision_status: str
    decision_fingerprint: str
    source_fingerprint: str
    accepted: bool
    rank: int
    utility_gap_to_winner: float | None


@dataclass(frozen=True)
class FreeAgencyCompetingMarketResult:
    version: str
    scope: str
    status: str
    player_id: str
    player_name: str
    season_label: str
    offer_count: int
    backend_pass_offer_count: int
    accepted_offer_count: int
    winner_team_abbreviation: str | None
    winner_offer_id: str | None
    winner_decision_fingerprint: str | None
    winner_utility_score: float | None
    runner_up_team_abbreviation: str | None
    runner_up_utility_score: float | None
    winning_margin: float | None
    best_counter_team_abbreviation: str | None
    best_counter_salary: float | None
    evaluations: tuple[CompetingOfferEvaluation, ...]
    rationale: tuple[str, ...]
    market_fingerprint: str

    @property
    def has_winner(self) -> bool:
        return self.status == "winner_selected" and bool(self.winner_team_abbreviation)


@dataclass(frozen=True)
class CompetingMarketLiveSigningResult:
    version: str
    market_fingerprint: str
    winner_team_abbreviation: str
    winner_decision_fingerprint: str
    player_decision_result: PlayerAcceptedLiveSigningResult


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _season_label(state: Any) -> str:
    return resolve_offseason_market_season(state)


def _offer(preview: Any) -> Any:
    return getattr(preview, "offer", None)


def _offer_sort_value(decision: FreeAgencyPlayerDecision) -> tuple[float, float, int, int, str]:
    # Utility controls destination choice. Contract value/security are deterministic
    # tie-breakers only and never override a meaningful utility difference.
    total = decision.annual_salary * max(decision.years, 0)
    guaranteed_flag = 1 if decision.guaranteed else 0
    return (
        float(decision.utility_score),
        float(total),
        guaranteed_flag,
        int(decision.years),
        _team(decision.team_abbreviation),
    )


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize_previews(previews: Iterable[Any]) -> tuple[Any, ...]:
    values = tuple(previews)
    if not values:
        raise FreeAgencyCompetingMarketError(
            "A competing free-agent market requires at least one explicit offer preview."
        )
    return values


def _validate_market_shape(previews: Sequence[Any]) -> tuple[str, tuple[str, ...]]:
    player_ids: list[str] = []
    teams: list[str] = []
    for preview in previews:
        offer = _offer(preview)
        if offer is None:
            raise FreeAgencyCompetingMarketError(
                "Every competing market entry must contain a free-agent offer."
            )
        player_id = _clean(getattr(offer, "player_id", ""))
        team = _team(getattr(offer, "team_abbreviation", ""))
        if not player_id or not team:
            raise FreeAgencyCompetingMarketError(
                "Every competing market offer requires a player and team."
            )
        player_ids.append(player_id)
        teams.append(team)

    unique_players = set(player_ids)
    if len(unique_players) != 1:
        raise FreeAgencyCompetingMarketError(
            "A competing market can compare offers for only one player at a time."
        )
    if len(teams) != len(set(teams)):
        raise FreeAgencyCompetingMarketError(
            "A competing market cannot contain multiple active offers from the same team."
        )
    return player_ids[0], tuple(teams)


def evaluate_competing_offer_market(
    state: Any,
    previews: Iterable[Any],
) -> FreeAgencyCompetingMarketResult:
    """Rank multiple explicit legal offers using the locked player decision model.

    V1 deliberately does not fabricate CPU offers. Each preview must already exist and
    must clear its own structural/CBA/financial gate before it can become an accepted
    destination. Non-PASS previews may be present for audit visibility, but they can
    never win the market.
    """
    values = _normalize_previews(previews)
    player_id, _ = _validate_market_shape(values)

    decisions: list[tuple[Any, FreeAgencyPlayerDecision]] = []
    for preview in values:
        decision = evaluate_free_agent_offer_decision(state, preview)
        decisions.append((preview, decision))

    player_names = {_clean(decision.player_name) for _, decision in decisions if _clean(decision.player_name)}
    player_name = sorted(player_names)[0] if player_names else player_id

    accepted = [
        (preview, decision)
        for preview, decision in decisions
        if decision.status == "accept"
        and _clean(getattr(preview, "status", "")).lower() == "pass"
        and bool(getattr(preview, "can_commit", False))
    ]
    accepted.sort(
        key=lambda pair: (
            -_offer_sort_value(pair[1])[0],
            -_offer_sort_value(pair[1])[1],
            -_offer_sort_value(pair[1])[2],
            -_offer_sort_value(pair[1])[3],
            _offer_sort_value(pair[1])[4],
        )
    )

    winner_preview: Any | None = None
    winner: FreeAgencyPlayerDecision | None = None
    runner_up: FreeAgencyPlayerDecision | None = None
    if accepted:
        winner_preview, winner = accepted[0]
        if len(accepted) > 1:
            runner_up = accepted[1][1]

    counter_candidates = [
        decision for _, decision in decisions
        if decision.status == "counter" and decision.counter_salary is not None
    ]
    # Lower requested counter is the most reachable counter, then higher present
    # utility and team abbreviation provide stable tie-breaks.
    counter_candidates.sort(
        key=lambda item: (
            float(item.counter_salary or math.inf),
            -float(item.utility_score),
            _team(item.team_abbreviation),
        )
    )
    best_counter = counter_candidates[0] if counter_candidates else None

    if winner is not None:
        status = "winner_selected"
        if runner_up is not None:
            rationale = (
                f"{winner.team_abbreviation} is the player's preferred accepted destination at utility {winner.utility_score:.1f}.",
                f"{runner_up.team_abbreviation} is the accepted runner-up at utility {runner_up.utility_score:.1f}.",
                "The player chooses the highest total destination utility, not automatically the highest salary.",
            )
        else:
            rationale = (
                f"{winner.team_abbreviation} is the only currently accepted destination.",
                "Other offers remain counters, declines, or are not backend-eligible.",
            )
    elif best_counter is not None:
        status = "counter_market"
        rationale = (
            "No submitted offer currently clears the player's acceptance threshold.",
            f"The most reachable counter is {best_counter.team_abbreviation} at approximately ${best_counter.counter_salary:,.0f} per year on its existing structure.",
        )
    else:
        status = "no_acceptable_offer"
        rationale = (
            "No submitted offer currently clears the player's acceptance threshold and no reachable counter is available.",
        )

    winner_utility = winner.utility_score if winner is not None else None
    evaluations: list[CompetingOfferEvaluation] = []
    ranked = sorted(
        [decision for _, decision in decisions],
        key=lambda item: (
            -float(item.utility_score),
            -float(item.annual_salary * max(item.years, 0)),
            _team(item.team_abbreviation),
        ),
    )
    for rank, decision in enumerate(ranked, start=1):
        evaluations.append(
            CompetingOfferEvaluation(
                team_abbreviation=decision.team_abbreviation,
                offer_id=decision.offer_id,
                annual_salary=decision.annual_salary,
                years=decision.years,
                guaranteed=decision.guaranteed,
                option_type=decision.option_type,
                utility_score=decision.utility_score,
                acceptance_threshold=decision.acceptance_threshold,
                player_decision_status=decision.status,
                decision_fingerprint=decision.decision_fingerprint,
                source_fingerprint=decision.preview_source_fingerprint,
                accepted=decision.status == "accept",
                rank=rank,
                utility_gap_to_winner=(
                    round(float(winner_utility - decision.utility_score), 3)
                    if winner_utility is not None
                    else None
                ),
            )
        )

    backend_pass_count = sum(
        1
        for preview, _ in decisions
        if _clean(getattr(preview, "status", "")).lower() == "pass"
        and bool(getattr(preview, "can_commit", False))
    )
    margin = (
        round(float(winner.utility_score - runner_up.utility_score), 3)
        if winner is not None and runner_up is not None
        else None
    )

    fingerprint_payload = {
        "version": FREE_AGENCY_COMPETING_MARKET_VERSION,
        "scope": FREE_AGENCY_COMPETING_MARKET_SCOPE,
        "season": _season_label(state),
        "player_id": player_id,
        "decisions": [
            {
                "team": evaluation.team_abbreviation,
                "decision_fingerprint": evaluation.decision_fingerprint,
                "source_fingerprint": evaluation.source_fingerprint,
            }
            for evaluation in sorted(evaluations, key=lambda item: item.team_abbreviation)
        ],
        "status": status,
        "winner_team": winner.team_abbreviation if winner is not None else None,
        "winner_decision": winner.decision_fingerprint if winner is not None else None,
        "best_counter_team": best_counter.team_abbreviation if best_counter is not None else None,
        "best_counter_salary": best_counter.counter_salary if best_counter is not None else None,
    }

    return FreeAgencyCompetingMarketResult(
        version=FREE_AGENCY_COMPETING_MARKET_VERSION,
        scope=FREE_AGENCY_COMPETING_MARKET_SCOPE,
        status=status,
        player_id=player_id,
        player_name=player_name,
        season_label=_season_label(state),
        offer_count=len(values),
        backend_pass_offer_count=backend_pass_count,
        accepted_offer_count=len(accepted),
        winner_team_abbreviation=(winner.team_abbreviation if winner is not None else None),
        winner_offer_id=(winner.offer_id if winner is not None else None),
        winner_decision_fingerprint=(winner.decision_fingerprint if winner is not None else None),
        winner_utility_score=(winner.utility_score if winner is not None else None),
        runner_up_team_abbreviation=(runner_up.team_abbreviation if runner_up is not None else None),
        runner_up_utility_score=(runner_up.utility_score if runner_up is not None else None),
        winning_margin=margin,
        best_counter_team_abbreviation=(best_counter.team_abbreviation if best_counter is not None else None),
        best_counter_salary=(best_counter.counter_salary if best_counter is not None else None),
        evaluations=tuple(evaluations),
        rationale=rationale,
        market_fingerprint=_fingerprint(fingerprint_payload),
    )


def market_matches_previews(
    state: Any,
    previews: Iterable[Any],
    result: Any,
) -> bool:
    if not isinstance(result, FreeAgencyCompetingMarketResult):
        return False
    try:
        current = evaluate_competing_offer_market(state, previews)
    except Exception:
        return False
    return current.market_fingerprint == result.market_fingerprint


def winner_preview_and_decision(
    state: Any,
    previews: Iterable[Any],
    result: FreeAgencyCompetingMarketResult,
) -> tuple[Any, FreeAgencyPlayerDecision]:
    values = _normalize_previews(previews)
    if not isinstance(result, FreeAgencyCompetingMarketResult) or not result.has_winner:
        raise FreeAgencyCompetingMarketError("The market does not contain an accepted winner.")
    if not market_matches_previews(state, values, result):
        raise FreeAgencyCompetingMarketError(
            "The competing market is stale relative to the current offers or franchise state."
        )

    for preview in values:
        decision = evaluate_free_agent_offer_decision(state, preview)
        if (
            decision.team_abbreviation == result.winner_team_abbreviation
            and decision.decision_fingerprint == result.winner_decision_fingerprint
        ):
            if not decision.accepted:
                break
            return preview, decision
    raise FreeAgencyCompetingMarketError(
        "The market winner could not be reconciled to a current accepted offer."
    )


def commit_competing_market_winner_live(
    previews: Iterable[Any],
    result: FreeAgencyCompetingMarketResult,
    *,
    hypothetical: bool = False,
) -> CompetingMarketLiveSigningResult:
    """Commit the market winner through the locked player-accepted live signing path.

    The existing Live Signing backend remains the authority for user-controlled-team,
    offseason, stale-state, checkpoint, Trade Machine sync, and recovery checks.
    CPU winners therefore cannot be silently committed by this V1 wrapper.
    """
    if hypothetical:
        raise FreeAgencyCompetingMarketError(
            "A hypothetical competing market can never be committed."
        )
    if not isinstance(result, FreeAgencyCompetingMarketResult) or not result.has_winner:
        raise FreeAgencyCompetingMarketError(
            "Only a competing market with an accepted winner can be committed."
        )

    from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint

    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise FreeAgencyCompetingMarketError("The durable franchise checkpoint is unavailable.")
    state = getattr(checkpoint, "simulation_state", None)
    values = _normalize_previews(previews)
    current = evaluate_competing_offer_market(state, values)
    if current.market_fingerprint != result.market_fingerprint:
        raise FreeAgencyCompetingMarketError(
            "The competing market is stale relative to the durable franchise state."
        )
    preview, decision = winner_preview_and_decision(state, values, current)

    try:
        signed = commit_player_accepted_free_agency_preview_live(
            preview,
            decision,
            hypothetical=False,
        )
    except FreeAgencyPlayerDecisionError:
        raise
    except Exception as exc:
        raise FreeAgencyCompetingMarketError(str(exc)) from exc

    return CompetingMarketLiveSigningResult(
        version=FREE_AGENCY_COMPETING_MARKET_VERSION,
        market_fingerprint=current.market_fingerprint,
        winner_team_abbreviation=_team(current.winner_team_abbreviation),
        winner_decision_fingerprint=_clean(current.winner_decision_fingerprint),
        player_decision_result=signed,
    )
