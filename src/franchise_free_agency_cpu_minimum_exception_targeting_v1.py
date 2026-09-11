from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from franchise_free_agency_player_decision_v1 import (
    FREE_AGENCY_PLAYER_DECISION_VERSION,
    evaluate_free_agent_offer_decision,
)

CPU_FREE_AGENCY_MINIMUM_EXCEPTION_TARGETING_VERSION = (
    "franchise-free-agency-cpu-minimum-exception-targeting-v1-2026-08-14"
)
CPU_FREE_AGENCY_MINIMUM_EXCEPTION_TARGETING_SCOPE = (
    "deterministic_opening_market_credibility_gate_for_exact_one_year_minimum_exception_bids"
)

ALLOW = "allow"
SKIP = "skip"


@dataclass(frozen=True)
class CPUMinimumExceptionTargetingResult:
    version: str
    scope: str
    status: str
    reason_code: str
    reason: str
    credibility_score: float
    player_decision_status: str
    interest_score: float
    acceptance_threshold: float
    gap_to_acceptance: float
    market_salary_reference: float
    salary_to_market_ratio: float
    player_overall: float
    player_age: float
    target_fit_score: float
    role_score: float
    winning_score: float
    security_score: float
    career_fit_score: float
    strategic_requested_years: int
    team_direction: str
    hard_reject: bool
    fingerprint: str

    @property
    def allowed(self) -> bool:
        return self.status == ALLOW


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if math.isfinite(number) else float(default)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _context_component(*, age: float, direction: str, fit: float, role: float) -> float:
    """Small strategic-context bonus. It can never overcome a severe market mismatch by itself."""
    text = _clean(direction).casefold()
    value = 0.0
    if age >= 30.0 and fit >= 65.0 and ("championship" in text or "contend" in text):
        value = max(value, 8.0)
    if age <= 25.0 and role >= 80.0 and ("develop" in text or "rebuild" in text):
        value = max(value, 6.0)
    if fit >= 75.0:
        value = min(8.0, value + 2.0)
    return value


def _credibility_score(
    *,
    gap: float,
    market_ratio: float,
    fit: float,
    role: float,
    age: float,
    direction: str,
) -> float:
    # Interest is intentionally the largest input. An offer that a player is nowhere
    # close to considering should not become "credible" merely because the CPU likes him.
    interest_component = 40.0 * _clamp((gap + 15.0) / 15.0)
    market_component = 30.0 * _clamp(market_ratio / 0.85)
    fit_component = 12.0 * _clamp(fit / 100.0)
    role_component = 10.0 * _clamp(role / 100.0)
    context_component = _context_component(age=age, direction=direction, fit=fit, role=role)
    return round(_clamp(interest_component + market_component + fit_component + role_component + context_component, 0.0, 100.0), 3)


def evaluate_minimum_exception_targeting(
    state: Any,
    preview: Any,
    *,
    target_fit_score: float,
    team_direction: str,
    strategic_requested_years: int,
) -> CPUMinimumExceptionTargetingResult:
    """Decide whether an exact one-year MSE bid is strategically credible enough to submit.

    This is not a legality gate. The preview must already have cleared the locked CBA backend.
    The gate only prevents CPU teams from spamming technically legal but implausible minimum
    offers to players whose market, interest, and strategic context make the bid non-credible.
    """
    decision = evaluate_free_agent_offer_decision(state, preview)
    offer = getattr(preview, "offer", None)
    player = getattr(state, "players", {}).get(_clean(getattr(offer, "player_id", "")))

    annual_salary = _finite(getattr(offer, "annual_salary", 0.0))
    market_reference = max(_finite(getattr(decision, "market_salary_reference", 0.0), 1.0), 1.0)
    market_ratio = annual_salary / market_reference
    interest = _finite(getattr(decision, "utility_score", 0.0))
    threshold = _finite(getattr(decision, "acceptance_threshold", 0.0))
    gap = interest - threshold
    status = _clean(getattr(decision, "status", "")).lower()
    overall = _finite(getattr(player, "overall_rating", 72.0), 72.0)
    age = _finite(getattr(player, "age", 27.0), 27.0)
    fit = _finite(target_fit_score)
    role = _finite(getattr(decision, "role_score", 0.0))
    winning = _finite(getattr(decision, "winning_score", 0.0))
    security = _finite(getattr(decision, "security_score", 0.0))
    career = _finite(getattr(decision, "career_fit_score", 0.0))
    requested_years = max(1, int(strategic_requested_years or 1))

    score = _credibility_score(
        gap=gap,
        market_ratio=market_ratio,
        fit=fit,
        role=role,
        age=age,
        direction=team_direction,
    )

    allowed = False
    hard_reject = False
    reason_code = "minimum_exception_not_credible"
    reason = "Exact-minimum offer is legal but not strategically credible in the current market."

    # A player who actually accepts the exact minimum is always a credible target.
    if status == "accept":
        allowed = True
        reason_code = "player_accepts_exact_minimum"
        reason = "Player decision model accepts the exact one-year minimum offer."
    # No opening-market spam when interest is nowhere close to the player's acceptance line.
    elif gap <= -12.0:
        hard_reject = True
        reason_code = "interest_far_below_acceptance"
        reason = f"Player interest is {abs(gap):.1f} points below the acceptance line."
    # Premium players should not receive token minimum offers when their market is far above it.
    elif overall >= 83.0 and market_ratio < 0.45:
        hard_reject = True
        reason_code = "premium_player_market_mismatch"
        reason = f"{overall:.1f} OVR player minimum is only {100.0 * market_ratio:.1f}% of modeled market value."
    elif overall >= 80.0 and market_ratio < 0.55:
        hard_reject = True
        reason_code = "premium_player_market_mismatch"
        reason = f"{overall:.1f} OVR player minimum is only {100.0 * market_ratio:.1f}% of modeled market value."
    elif overall >= 78.0 and market_ratio < 0.30:
        hard_reject = True
        reason_code = "severe_market_underpay"
        reason = f"Minimum is only {100.0 * market_ratio:.1f}% of modeled market value."
    elif market_ratio < 0.42:
        reason_code = "minimum_too_far_below_market"
        reason = f"Minimum is only {100.0 * market_ratio:.1f}% of modeled market value."
    # Borderline declines are allowed only when the total credibility score supports a real pitch.
    elif gap >= -8.0 and score >= 62.0:
        allowed = True
        reason_code = "credible_minimum_pitch"
        reason = "Offer is close enough to the player threshold and supported by market value, fit, and role context."
    else:
        reason_code = "credibility_score_below_gate"
        reason = f"Minimum credibility score {score:.1f}/100 does not clear the 62.0 opening-market gate."

    result_status = ALLOW if allowed else SKIP
    payload = {
        "version": CPU_FREE_AGENCY_MINIMUM_EXCEPTION_TARGETING_VERSION,
        "player_decision_version": FREE_AGENCY_PLAYER_DECISION_VERSION,
        "status": result_status,
        "reason_code": reason_code,
        "credibility_score": score,
        "decision_status": status,
        "interest": round(interest, 3),
        "threshold": round(threshold, 3),
        "gap": round(gap, 3),
        "market_reference": round(market_reference, 2),
        "market_ratio": round(market_ratio, 6),
        "overall": round(overall, 3),
        "age": round(age, 3),
        "fit": round(fit, 3),
        "role": round(role, 3),
        "winning": round(winning, 3),
        "security": round(security, 3),
        "career": round(career, 3),
        "requested_years": requested_years,
        "direction": _clean(team_direction),
        "preview_source_fingerprint": _clean(getattr(preview, "source_fingerprint", "")),
    }
    return CPUMinimumExceptionTargetingResult(
        version=CPU_FREE_AGENCY_MINIMUM_EXCEPTION_TARGETING_VERSION,
        scope=CPU_FREE_AGENCY_MINIMUM_EXCEPTION_TARGETING_SCOPE,
        status=result_status,
        reason_code=reason_code,
        reason=reason,
        credibility_score=score,
        player_decision_status=status,
        interest_score=round(interest, 3),
        acceptance_threshold=round(threshold, 3),
        gap_to_acceptance=round(gap, 3),
        market_salary_reference=round(market_reference, 2),
        salary_to_market_ratio=round(market_ratio, 6),
        player_overall=round(overall, 3),
        player_age=round(age, 3),
        target_fit_score=round(fit, 3),
        role_score=round(role, 3),
        winning_score=round(winning, 3),
        security_score=round(security, 3),
        career_fit_score=round(career, 3),
        strategic_requested_years=requested_years,
        team_direction=_clean(team_direction),
        hard_reject=hard_reject,
        fingerprint=_fingerprint(payload),
    )


def targeting_contract_report() -> dict[str, Any]:
    return {
        "version": CPU_FREE_AGENCY_MINIMUM_EXCEPTION_TARGETING_VERSION,
        "scope": CPU_FREE_AGENCY_MINIMUM_EXCEPTION_TARGETING_SCOPE,
        "player_decision_version": FREE_AGENCY_PLAYER_DECISION_VERSION,
        "changes_legality": False,
        "autonomous_commit_enabled": False,
        "exact_one_year_minimum_only": True,
        "interest_is_probability": False,
        "hard_reject_gap_points": -12.0,
        "credibility_gate": 62.0,
        "borderline_gap_floor": -8.0,
        "market_ratio_floor": 0.42,
    }
