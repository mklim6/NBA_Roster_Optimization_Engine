from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

from franchise_free_agency_player_decision_v1 import evaluate_free_agent_offer_decision

CPU_FREE_AGENCY_OFFER_ECONOMIC_INTELLIGENCE_VERSION = (
    "franchise-free-agency-cpu-offer-economic-intelligence-v1-2026-08-14"
)
CPU_FREE_AGENCY_OFFER_ECONOMIC_INTELLIGENCE_SCOPE = (
    "deterministic_non_mse_offer_credibility_using_market_value_player_interest_and_contextual_discount_tolerance"
)

ROUTE_MINIMUM = "minimum_salary_exception"
BIRD_FAMILY_ROUTES = {"bird_exception", "early_bird_exception", "non_bird_exception"}


@dataclass(frozen=True)
class CPUOfferEconomicIntelligenceResult:
    version: str
    status: str
    allowed: bool
    tier: str
    reason_code: str
    financial_route: str
    annual_salary: float
    market_salary_reference: float
    salary_to_market_ratio: float
    minimum_credible_market_ratio: float
    player_interest: float | None
    acceptance_threshold: float | None
    gap_to_acceptance: float | None
    player_decision_status: str
    player_overall: float
    player_age: float
    money_weight: float
    role_weight: float
    winning_weight: float
    career_fit_weight: float
    market_patience: float
    role_score: float | None
    winning_score: float | None
    career_fit_score: float | None
    roster_construction_score: float
    roster_projected_role: str
    discount_support_score: float
    economic_credibility_score: float
    rationale: tuple[str, ...]
    fingerprint: str


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _fingerprint(payload: Mapping[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _profile(decision: Any) -> Any:
    return getattr(decision, "preference_profile", None) or getattr(decision, "profile", None)


def _weight(profile: Any, name: str, default: float) -> float:
    value = _finite(getattr(profile, name, None)) if profile is not None else None
    return default if value is None else value


def _minimum_credible_ratio(
    *,
    overall: float,
    age: float,
    money_weight: float,
    role_weight: float,
    winning_weight: float,
    career_fit_weight: float,
    market_patience: float,
    role_score: float | None,
    winning_score: float | None,
    career_fit_score: float | None,
    roster_score: float,
    projected_role: str,
    financial_route: str,
) -> tuple[float, float]:
    """Return contextual market-ratio floor and discount-support score.

    The floor is intentionally not a universal percentage. Premium/young players,
    money-focused players and patient markets require stronger financial pitches.
    Strong role, winning and career fit can support a modest discount. Bird-family
    continuity receives a small prior-team allowance, but never bypasses player
    interest or turns a token offer into a credible pitch.
    """
    floor = 0.52
    if overall >= 88.0:
        floor += 0.10
    elif overall >= 84.0:
        floor += 0.08
    elif overall >= 80.0:
        floor += 0.05
    elif overall >= 76.0:
        floor += 0.02

    if age <= 26.0 and overall >= 80.0:
        floor += 0.05
    elif age >= 33.0:
        floor -= 0.03

    floor += max(-0.02, min(0.05, (money_weight - 0.34) * 0.30))
    floor += max(0.0, min(0.04, market_patience * 0.04))

    role = 50.0 if role_score is None else _clamp(role_score)
    winning = 50.0 if winning_score is None else _clamp(winning_score)
    career = 50.0 if career_fit_score is None else _clamp(career_fit_score)
    role_support = max(0.0, role - 70.0) / 30.0 * role_weight * 0.10
    winning_support = max(0.0, winning - 70.0) / 30.0 * winning_weight * 0.12
    career_support = max(0.0, career - 70.0) / 30.0 * career_fit_weight * 0.08
    roster_support = max(0.0, roster_score - 82.0) / 18.0 * 0.025
    starter_support = 0.015 if projected_role in {"clear_starter_upgrade", "starter_upgrade", "starter_level"} else 0.0
    continuity_support = 0.035 if _clean(financial_route) in BIRD_FAMILY_ROUTES else 0.0
    support = min(0.16, role_support + winning_support + career_support + roster_support + starter_support + continuity_support)
    floor -= support
    return round(max(0.42, min(0.82, floor)), 6), round(_clamp(support / 0.16 * 100.0), 3)


def evaluate_cpu_offer_economic_intelligence(
    state: Any,
    player: Any,
    preview: Any,
    *,
    market_salary_reference: float,
    financial_route: str,
    roster_construction_score: float,
    roster_projected_role: str,
) -> CPUOfferEconomicIntelligenceResult:
    offer = getattr(preview, "offer", None)
    salary = _finite(getattr(offer, "annual_salary", None)) or 0.0
    reference = _finite(market_salary_reference) or 0.0
    ratio = salary / reference if reference > 0.0 else 1.0
    route = _clean(financial_route)
    overall = _finite(getattr(player, "overall_rating", None)) or 70.0
    age = _finite(getattr(player, "age", None)) or 27.0
    roster_score = _clamp(roster_construction_score)

    decision_status = "evaluation_unavailable"
    interest = threshold = gap = None
    money_weight, role_weight, winning_weight, career_weight, patience = 0.40, 0.20, 0.15, 0.10, 0.50
    role_score = winning_score = career_score = None
    try:
        decision = evaluate_free_agent_offer_decision(state, preview)
        decision_status = _clean(getattr(decision, "status", "")).lower() or "evaluation_unavailable"
        interest = _finite(getattr(decision, "utility_score", None))
        threshold = _finite(getattr(decision, "acceptance_threshold", None))
        profile = _profile(decision)
        if threshold is None:
            threshold = _finite(getattr(profile, "acceptance_threshold", None))
        if interest is not None and threshold is not None:
            gap = interest - threshold
        money_weight = _weight(profile, "money_weight", money_weight)
        role_weight = _weight(profile, "role_weight", role_weight)
        winning_weight = _weight(profile, "winning_weight", winning_weight)
        career_weight = _weight(profile, "career_fit_weight", career_weight)
        patience = _weight(profile, "market_patience", patience)
        role_score = _finite(getattr(decision, "role_score", None))
        winning_score = _finite(getattr(decision, "winning_score", None))
        career_score = _finite(getattr(decision, "career_fit_score", None))
    except Exception:
        pass

    floor, support_score = _minimum_credible_ratio(
        overall=overall,
        age=age,
        money_weight=money_weight,
        role_weight=role_weight,
        winning_weight=winning_weight,
        career_fit_weight=career_weight,
        market_patience=patience,
        role_score=role_score,
        winning_score=winning_score,
        career_fit_score=career_score,
        roster_score=roster_score,
        projected_role=_clean(roster_projected_role),
        financial_route=route,
    )

    allowed = True
    reason = "credible_opening_offer"
    rationale: list[str] = []

    # MSE has a dedicated upstream targeting model. Economic Intelligence records
    # it but does not second-guess a route-specific bid that already survived.
    if route == ROUTE_MINIMUM:
        reason = "minimum_exception_targeting_authoritative"
        rationale.append("Minimum Salary Exception credibility remains owned by Minimum-Exception Targeting V1.0.1.")
    elif decision_status == "accept":
        reason = "player_accepts_offer"
        rationale.append("The exact Player Decisions model already accepts this offer.")
    elif ratio < 0.35:
        allowed = False
        reason = "token_offer_vs_market"
        rationale.append("The offer is below 35% of the player's current model market reference.")
    elif decision_status == "counter":
        # A player counter is itself evidence that negotiation is economically
        # live. Preserve imperfect/opening offers unless they are token bids.
        reason = "player_counter_keeps_market_live"
        rationale.append("The player is willing to counter, so the opening bid remains a credible negotiation.")
    elif ratio + 1e-9 < floor:
        allowed = False
        reason = "market_discount_exceeds_player_context"
        rationale.append(f"Offer ratio {ratio:.3f} is below contextual credibility floor {floor:.3f}.")
    elif decision_status == "decline" and gap is not None and gap <= -18.0 and ratio < 0.82:
        allowed = False
        reason = "interest_gap_too_large_for_discount"
        rationale.append("Player interest is at least 18 points below acceptance while the offer is materially discounted.")
    elif decision_status == "decline" and gap is not None and gap <= -28.0 and ratio < 0.92:
        allowed = False
        reason = "severe_interest_gap"
        rationale.append("The player is far outside the viable negotiation range at the offered economics.")
    else:
        rationale.append("The offer is financially credible enough to enter the player's market despite not being an immediate acceptance.")

    market_component = _clamp(ratio * 100.0)
    if decision_status == "accept":
        decision_component = 100.0
    elif decision_status == "counter":
        decision_component = 78.0
    elif decision_status == "decline":
        decision_component = 38.0
    else:
        decision_component = 45.0
    interest_component = 50.0 if interest is None else _clamp(interest)
    floor_component = _clamp(50.0 + (ratio - floor) * 125.0)
    credibility = _clamp(
        0.34 * market_component
        + 0.24 * decision_component
        + 0.18 * interest_component
        + 0.14 * roster_score
        + 0.10 * floor_component
    )

    if credibility >= 80.0:
        tier = "strong"
    elif credibility >= 65.0:
        tier = "credible"
    elif credibility >= 52.0:
        tier = "borderline"
    else:
        tier = "weak"

    payload = {
        "version": CPU_FREE_AGENCY_OFFER_ECONOMIC_INTELLIGENCE_VERSION,
        "player_id": _clean(getattr(player, "player_id", "")),
        "team": _clean(getattr(offer, "team_abbreviation", "")).upper(),
        "route": route,
        "salary": round(salary, 2),
        "reference": round(reference, 2),
        "ratio": round(ratio, 6),
        "floor": floor,
        "interest": None if interest is None else round(interest, 3),
        "threshold": None if threshold is None else round(threshold, 3),
        "gap": None if gap is None else round(gap, 3),
        "decision": decision_status,
        "overall": round(overall, 3),
        "age": round(age, 3),
        "money_weight": round(money_weight, 6),
        "role_weight": round(role_weight, 6),
        "winning_weight": round(winning_weight, 6),
        "career_weight": round(career_weight, 6),
        "patience": round(patience, 6),
        "role_score": None if role_score is None else round(role_score, 3),
        "winning_score": None if winning_score is None else round(winning_score, 3),
        "career_score": None if career_score is None else round(career_score, 3),
        "roster_score": round(roster_score, 3),
        "projected_role": _clean(roster_projected_role),
        "discount_support": support_score,
        "credibility": round(credibility, 3),
        "allowed": allowed,
        "reason": reason,
    }
    return CPUOfferEconomicIntelligenceResult(
        version=CPU_FREE_AGENCY_OFFER_ECONOMIC_INTELLIGENCE_VERSION,
        status="pass" if allowed else "filtered",
        allowed=allowed,
        tier=tier,
        reason_code=reason,
        financial_route=route,
        annual_salary=round(salary, 2),
        market_salary_reference=round(reference, 2),
        salary_to_market_ratio=round(ratio, 6),
        minimum_credible_market_ratio=floor,
        player_interest=None if interest is None else round(interest, 3),
        acceptance_threshold=None if threshold is None else round(threshold, 3),
        gap_to_acceptance=None if gap is None else round(gap, 3),
        player_decision_status=decision_status,
        player_overall=round(overall, 3),
        player_age=round(age, 3),
        money_weight=round(money_weight, 6),
        role_weight=round(role_weight, 6),
        winning_weight=round(winning_weight, 6),
        career_fit_weight=round(career_weight, 6),
        market_patience=round(patience, 6),
        role_score=None if role_score is None else round(role_score, 3),
        winning_score=None if winning_score is None else round(winning_score, 3),
        career_fit_score=None if career_score is None else round(career_score, 3),
        roster_construction_score=round(roster_score, 3),
        roster_projected_role=_clean(roster_projected_role),
        discount_support_score=support_score,
        economic_credibility_score=round(credibility, 3),
        rationale=tuple(rationale),
        fingerprint=_fingerprint(payload),
    )


def offer_economic_intelligence_contract_report() -> dict[str, Any]:
    return {
        "version": CPU_FREE_AGENCY_OFFER_ECONOMIC_INTELLIGENCE_VERSION,
        "scope": CPU_FREE_AGENCY_OFFER_ECONOMIC_INTELLIGENCE_SCOPE,
        "score_range": [0.0, 100.0],
        "market_ratio_floor_is_contextual": True,
        "uses_exact_player_decision_interest": True,
        "uses_player_preference_weights": True,
        "uses_roster_construction_context": True,
        "minimum_exception_targeting_remains_authoritative": True,
        "bird_family_continuity_is_discount_support_not_legality": True,
        "player_counter_is_preserved_as_live_negotiation": True,
        "changes_cba_legality": False,
        "autonomous_commit_enabled": False,
    }
