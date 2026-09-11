from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from franchise_free_agency_player_decision_v1 import evaluate_free_agent_offer_decision

CPU_FREE_AGENCY_ROSTER_CONSTRUCTION_VERSION = (
    "franchise-free-agency-cpu-roster-construction-intelligence-v1-2026-08-14"
)
CPU_FREE_AGENCY_ROSTER_CONSTRUCTION_SCOPE = (
    "deterministic_roster_need_role_upgrade_timeline_redundancy_and_development_runway"
)


@dataclass(frozen=True)
class CPURosterConstructionTargetResult:
    version: str
    status: str
    allowed: bool
    score: float
    tier: str
    reason_code: str
    team_abbreviation: str
    team_direction: str
    position_family: str
    projected_role: str
    positional_need_score: float
    role_upgrade_score: float
    timeline_fit_score: float
    upside_fit_score: float
    redundancy_risk: float
    prospect_blocking_risk: float
    marginal_overall_vs_best: float
    marginal_overall_vs_second: float
    roster_count_at_family: int
    rotation_count_at_family: int
    young_upside_count_at_family: int
    target_fit_score: float
    spending_multiplier: float
    rationale: tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True)
class CPURosterConstructionOfferResult:
    version: str
    status: str
    allowed: bool
    reason_code: str
    roster_score: float
    financial_route: str
    annual_salary: float
    market_salary_reference: float
    salary_to_market_ratio: float
    player_interest: float | None
    acceptance_threshold: float | None
    gap_to_acceptance: float | None
    player_decision_status: str
    economic_pursuit_score: float
    fingerprint: str


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


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _value(obj: Any, names: Sequence[str], default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        for name in names:
            if name in obj:
                return obj[name]
        return default
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "__dict__"):
        return vars(value)
    return {}


def _fingerprint(payload: Mapping[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _position_family(position: Any, explicit: Any = "") -> str:
    direct = _clean(explicit)
    normalized = direct.casefold().replace("_", " ").replace("-", " ")
    if direct:
        if "center" in normalized or normalized in {"big", "bigs"}:
            return "Center"
        if "guard" in normalized:
            return "Guard"
        if "wing" in normalized or "forward" in normalized:
            return "Wing/Forward"
    text = _clean(position).upper().replace("-", "/")
    tokens = {token.strip() for token in text.split("/") if token.strip()}
    if "C" in tokens and not ({"PG", "SG", "G"} & tokens):
        return "Center"
    if {"PG", "SG", "G"} & tokens:
        return "Guard"
    if {"SF", "PF", "F"} & tokens:
        return "Wing/Forward"
    if "C" in text:
        return "Center"
    if "PG" in text or "SG" in text:
        return "Guard"
    return "Wing/Forward"


def _position_profile(team_plan: Any, family: str) -> Mapping[str, Any]:
    profiles = _value(team_plan, ("position_profiles", "position_profile", "depth_profiles"), {})
    if not isinstance(profiles, Mapping):
        return {}
    if family in profiles:
        return _mapping(profiles[family])
    wanted = family.casefold()
    for key, value in profiles.items():
        normalized = _clean(key).casefold()
        if wanted == normalized:
            return _mapping(value)
        if family == "Wing/Forward" and ("wing" in normalized or "forward" in normalized):
            return _mapping(value)
        if family == "Center" and ("center" in normalized or "big" in normalized):
            return _mapping(value)
        if family == "Guard" and "guard" in normalized:
            return _mapping(value)
    return {}


def _target_lane(target: Any) -> str:
    return _clean(_value(target, ("target_lane", "lane", "priority_lane", "role_lane"), ""))


def _target_family(target: Any, player: Any) -> str:
    explicit = _value(target, ("position_family", "family"), "")
    return _position_family(getattr(player, "position", ""), explicit)


def _lane_need_floor(lane: str) -> float:
    text = _clean(lane).casefold()
    if "primary" in text:
        return 68.0
    if "secondary" in text:
        return 52.0
    if "upside" in text:
        return 40.0
    if "value" in text or "depth" in text:
        return 35.0
    return 30.0


def _role_projection(overall: float, profile: Mapping[str, Any]) -> tuple[float, str, float, float]:
    top = _finite(_value(profile, ("top_overall", "best_overall"), None))
    second = _finite(_value(profile, ("second_overall", "second_best_overall"), None))
    top = 0.0 if top is None else top
    if second is None or second <= 0.0:
        second = max(0.0, top - 4.0)
    delta_top = overall - top if top > 0 else 0.0
    delta_second = overall - second if second > 0 else 0.0

    if top <= 0.0:
        score = 70.0
        role = "rotation_upgrade"
    elif delta_top >= 4.0:
        score, role = 100.0, "clear_starter_upgrade"
    elif delta_top >= 1.5:
        score, role = 92.0, "starter_upgrade"
    elif delta_top >= -1.0:
        score, role = 82.0, "starter_level"
    elif delta_second >= 4.0:
        score, role = 78.0, "rotation_upgrade"
    elif delta_second >= 1.0:
        score, role = 70.0, "rotation_upgrade"
    elif delta_second >= -2.0:
        score, role = 60.0, "rotation"
    else:
        score = _clamp(42.0 + (delta_second + 4.0) * 3.0, 25.0, 58.0)
        role = "depth"

    rotation_count = int(_finite(_value(profile, ("rotation_count",), 0)) or 0)
    if rotation_count < 3 and overall >= 76.0:
        score = _clamp(score + 8.0)
    return round(score, 3), role, round(delta_top, 3), round(delta_second, 3)


def _timeline_fit(direction: str, age: float, overall: float, potential: float) -> float:
    text = _clean(direction).casefold()
    if "develop" in text or "rebuild" in text:
        score = 95.0 if age <= 23 else 88.0 if age <= 25 else 70.0 if age <= 28 else 45.0 if age <= 31 else 25.0
        score += min(10.0, max(0.0, (potential - overall) * 1.5))
    elif "championship" in text or "contend" in text or "win now" in text:
        score = 95.0 if overall >= 85 else 85.0 if overall >= 80 else 72.0 if overall >= 76 else 55.0
        if age >= 35:
            score -= 20.0
        elif age >= 32:
            score -= 7.0
        elif age <= 24 and potential >= 84:
            score += 5.0
    elif "retool" in text:
        score = 85.0 if age < 22 else 92.0 if age <= 27 else 80.0 if age <= 30 else 60.0 if age <= 33 else 42.0
        score += min(8.0, max(0.0, potential - overall))
    else:
        score = 75.0
    return round(_clamp(score), 3)


def _upside_fit(age: float, overall: float, potential: float) -> float:
    age_bonus = 12.0 if age <= 23 else 8.0 if age <= 25 else 3.0 if age <= 28 else -6.0 if age >= 32 else 0.0
    return round(_clamp(45.0 + max(-8.0, potential - overall) * 4.0 + age_bonus), 3)


def _redundancy_risk(profile: Mapping[str, Any], need_score: float, role_score: float) -> float:
    surplus = _finite(_value(profile, ("surplus_score",), 0.0)) or 0.0
    count = int(_finite(_value(profile, ("count",), 0)) or 0)
    rotation_count = int(_finite(_value(profile, ("rotation_count",), 0)) or 0)
    risk = surplus * 2.0
    if count >= 5:
        risk += 15.0
    if rotation_count >= 4:
        risk += 10.0
    if need_score < 35.0:
        risk += 15.0
    if role_score < 55.0:
        risk += 20.0
    if role_score >= 92.0:
        risk -= 30.0
    return round(_clamp(risk), 3)


def _prospect_blocking_risk(
    team_plan: Any,
    *,
    family: str,
    direction: str,
    player_age: float,
    player_overall: float,
    player_potential: float,
    role_score: float,
    projected_role: str,
) -> float:
    development_ids = {
        _clean(value)
        for value in (_value(team_plan, ("development_player_ids", "prospect_ids"), ()) or ())
        if _clean(value)
    }
    decisions = _value(team_plan, ("player_decisions", "roster_player_decisions"), ()) or ()
    if not development_ids or not isinstance(decisions, (list, tuple)):
        return 0.0

    max_risk = 0.0
    for decision in decisions:
        player_id = _clean(_value(decision, ("player_id", "id"), ""))
        if player_id not in development_ids:
            continue
        decision_family = _position_family(
            _value(decision, ("position",), ""),
            _value(decision, ("position_family", "family"), ""),
        )
        if decision_family != family:
            continue
        prospect_age = _finite(_value(decision, ("age",), None)) or 30.0
        prospect_overall = _finite(_value(decision, ("overall", "overall_rating"), None)) or 70.0
        prospect_potential = _finite(_value(decision, ("potential", "potential_rating"), None)) or prospect_overall

        # A similarly young, similarly high-upside addition is competition for the
        # development core, not automatically harmful prospect blocking.
        if player_age <= 25.0 and player_potential >= prospect_potential - 3.0:
            risk = 15.0
        else:
            risk = 10.0
            if player_age >= 28.0:
                risk += 20.0
            elif player_age >= 26.0:
                risk += 8.0
            if player_potential <= prospect_potential - 4.0:
                risk += 20.0
            elif player_potential < prospect_potential:
                risk += 8.0
            if player_overall <= prospect_overall + 2.0:
                risk += 20.0
            elif player_overall <= prospect_overall + 5.0:
                risk += 5.0
            direction_text = _clean(direction).casefold()
            if "develop" in direction_text or "rebuild" in direction_text:
                risk += 15.0
            if projected_role in {"starter_level", "rotation_upgrade", "rotation"}:
                risk += 10.0
        if role_score >= 92.0:
            risk -= 30.0
        max_risk = max(max_risk, _clamp(risk))
    return round(max_risk, 3)


def evaluate_roster_construction_target(
    state: Any,
    player: Any,
    team_plan: Any,
    target: Any,
    *,
    team_abbreviation: str,
    team_direction: str,
    target_fit_score: float,
) -> CPURosterConstructionTargetResult:
    del state  # The front-office plan is the audited roster-context snapshot for V1.
    team = _team(team_abbreviation)
    family = _target_family(target, player)
    profile = _position_profile(team_plan, family)
    overall = _finite(getattr(player, "overall_rating", None)) or _finite(_value(target, ("overall",), None)) or 72.0
    potential = _finite(getattr(player, "potential_rating", None)) or _finite(_value(target, ("potential",), None)) or overall
    age = _finite(getattr(player, "age", None)) or _finite(_value(target, ("age",), None)) or 27.0

    raw_need = _finite(_value(profile, ("need_score",), None))
    raw_need = 0.0 if raw_need is None else raw_need
    need_score = _clamp(max(raw_need, _lane_need_floor(_target_lane(target))))
    role_score, projected_role, delta_best, delta_second = _role_projection(overall, profile)
    timeline_score = _timeline_fit(team_direction, age, overall, potential)
    upside_score = _upside_fit(age, overall, potential)
    redundancy = _redundancy_risk(profile, need_score, role_score)
    blocking = _prospect_blocking_risk(
        team_plan,
        family=family,
        direction=team_direction,
        player_age=age,
        player_overall=overall,
        player_potential=potential,
        role_score=role_score,
        projected_role=projected_role,
    )

    target_fit = _clamp(target_fit_score)
    score = (
        0.22 * need_score
        + 0.25 * role_score
        + 0.17 * timeline_score
        + 0.10 * upside_score
        + 0.10 * (100.0 - redundancy)
        + 0.10 * (100.0 - blocking)
        + 0.06 * target_fit
    )
    score = round(_clamp(score), 3)

    allowed = True
    reason = "roster_fit_supported"
    direction_text = _clean(team_direction).casefold()
    if (
        blocking >= 80.0
        and ("develop" in direction_text or "rebuild" in direction_text)
        and role_score < 65.0
        and age >= 27.0
    ):
        allowed = False
        reason = "protect_development_runway"
    elif redundancy >= 80.0 and role_score < 65.0 and need_score < 45.0:
        allowed = False
        reason = "severe_position_redundancy"
    elif score < 35.0:
        allowed = False
        reason = "low_roster_construction_value"

    if score >= 82.0:
        tier = "Elite roster fit"
    elif score >= 70.0:
        tier = "Strong roster fit"
    elif score >= 58.0:
        tier = "Useful roster fit"
    elif score >= 45.0:
        tier = "Marginal roster fit"
    else:
        tier = "Poor roster fit"

    # Keep salary influence deliberately modest in V1. The new layer should
    # sharpen team behavior without overpowering the existing market model.
    spending_multiplier = round(_clamp(0.94 + score * 0.0012, 0.94, 1.06), 6)
    rationale: list[str] = []
    if need_score >= 65.0:
        rationale.append("fills a primary or high-severity roster need")
    if role_score >= 92.0:
        rationale.append("projects as a clear starter-level upgrade")
    elif role_score >= 70.0:
        rationale.append("projects as a meaningful rotation upgrade")
    elif projected_role == "depth":
        rationale.append("projects primarily as depth")
    if timeline_score >= 88.0:
        rationale.append("fits the current competitive/development timeline")
    if blocking >= 65.0:
        rationale.append("carries meaningful development-runway blocking risk")
    if redundancy >= 65.0:
        rationale.append("adds to a crowded position family")
    if not rationale:
        rationale.append("neutral roster-construction fit")

    payload = {
        "version": CPU_FREE_AGENCY_ROSTER_CONSTRUCTION_VERSION,
        "team": team,
        "direction": _clean(team_direction),
        "player_id": _clean(getattr(player, "player_id", "")),
        "family": family,
        "score": score,
        "tier": tier,
        "reason": reason,
        "need": round(need_score, 3),
        "role": round(role_score, 3),
        "timeline": round(timeline_score, 3),
        "upside": round(upside_score, 3),
        "redundancy": round(redundancy, 3),
        "blocking": round(blocking, 3),
        "delta_best": delta_best,
        "delta_second": delta_second,
        "fit": round(target_fit, 3),
        "multiplier": spending_multiplier,
    }
    return CPURosterConstructionTargetResult(
        version=CPU_FREE_AGENCY_ROSTER_CONSTRUCTION_VERSION,
        status="pass" if allowed else "filtered",
        allowed=allowed,
        score=score,
        tier=tier,
        reason_code=reason,
        team_abbreviation=team,
        team_direction=_clean(team_direction),
        position_family=family,
        projected_role=projected_role,
        positional_need_score=round(need_score, 3),
        role_upgrade_score=round(role_score, 3),
        timeline_fit_score=round(timeline_score, 3),
        upside_fit_score=round(upside_score, 3),
        redundancy_risk=round(redundancy, 3),
        prospect_blocking_risk=round(blocking, 3),
        marginal_overall_vs_best=delta_best,
        marginal_overall_vs_second=delta_second,
        roster_count_at_family=int(_finite(_value(profile, ("count",), 0)) or 0),
        rotation_count_at_family=int(_finite(_value(profile, ("rotation_count",), 0)) or 0),
        young_upside_count_at_family=int(_finite(_value(profile, ("young_upside_count",), 0)) or 0),
        target_fit_score=round(target_fit, 3),
        spending_multiplier=spending_multiplier,
        rationale=tuple(rationale),
        fingerprint=_fingerprint(payload),
    )


def evaluate_roster_construction_offer(
    state: Any,
    player: Any,
    preview: Any,
    target_result: CPURosterConstructionTargetResult,
    *,
    market_salary_reference: float,
    financial_route: str,
) -> CPURosterConstructionOfferResult:
    offer = getattr(preview, "offer", None)
    salary = _finite(getattr(offer, "annual_salary", None)) or 0.0
    reference = _finite(market_salary_reference) or 0.0
    ratio = salary / reference if reference > 0.0 else 1.0
    decision_status = ""
    interest = threshold = gap = None
    try:
        decision = evaluate_free_agent_offer_decision(state, preview)
        decision_status = _clean(getattr(decision, "status", "")).lower()
        interest = _finite(getattr(decision, "utility_score", None))
        threshold = _finite(getattr(getattr(decision, "profile", None), "acceptance_threshold", None))
        if threshold is None:
            threshold = _finite(getattr(decision, "acceptance_threshold", None))
        if interest is not None and threshold is not None:
            gap = interest - threshold
    except Exception:
        decision_status = "evaluation_unavailable"

    allowed = bool(target_result.allowed)
    reason = target_result.reason_code if not allowed else "roster_offer_supported"
    route = _clean(financial_route)

    # MSE has its own dedicated credibility gate. Do not second-guess an offer
    # that survived that stricter route-specific logic.
    if allowed and route != "minimum_salary_exception":
        if (
            target_result.projected_role == "depth"
            and target_result.target_fit_score < 45.0
            and ratio >= 0.95
            and target_result.positional_need_score < 55.0
        ):
            allowed = False
            reason = "near_market_price_for_depth_fit"
        elif (
            ratio < 0.45
            and decision_status == "decline"
            and gap is not None
            and gap <= -15.0
        ):
            allowed = False
            reason = "noncompetitive_cap_limited_offer"

    market_alignment = 100.0 - min(abs(1.0 - ratio) * 100.0, 100.0)
    interest_component = 50.0 if interest is None else _clamp(interest)
    economic_score = round(_clamp(0.55 * target_result.score + 0.25 * market_alignment + 0.20 * interest_component), 3)

    payload = {
        "version": CPU_FREE_AGENCY_ROSTER_CONSTRUCTION_VERSION,
        "target_fingerprint": target_result.fingerprint,
        "player_id": _clean(getattr(player, "player_id", "")),
        "team": target_result.team_abbreviation,
        "route": route,
        "salary": round(salary, 2),
        "reference": round(reference, 2),
        "ratio": round(ratio, 6),
        "interest": None if interest is None else round(interest, 3),
        "threshold": None if threshold is None else round(threshold, 3),
        "gap": None if gap is None else round(gap, 3),
        "decision": decision_status,
        "allowed": allowed,
        "reason": reason,
        "economic_score": economic_score,
    }
    return CPURosterConstructionOfferResult(
        version=CPU_FREE_AGENCY_ROSTER_CONSTRUCTION_VERSION,
        status="pass" if allowed else "filtered",
        allowed=allowed,
        reason_code=reason,
        roster_score=target_result.score,
        financial_route=route,
        annual_salary=round(salary, 2),
        market_salary_reference=round(reference, 2),
        salary_to_market_ratio=round(ratio, 6),
        player_interest=None if interest is None else round(interest, 3),
        acceptance_threshold=None if threshold is None else round(threshold, 3),
        gap_to_acceptance=None if gap is None else round(gap, 3),
        player_decision_status=decision_status,
        economic_pursuit_score=economic_score,
        fingerprint=_fingerprint(payload),
    )


def roster_construction_contract_report() -> dict[str, Any]:
    return {
        "version": CPU_FREE_AGENCY_ROSTER_CONSTRUCTION_VERSION,
        "scope": CPU_FREE_AGENCY_ROSTER_CONSTRUCTION_SCOPE,
        "score_range": [0.0, 100.0],
        "components": [
            "positional_need",
            "role_upgrade",
            "timeline_fit",
            "upside_fit",
            "redundancy_risk",
            "prospect_blocking_risk",
            "existing_front_office_target_fit",
        ],
        "hard_filters": [
            "protect_development_runway",
            "severe_position_redundancy",
            "low_roster_construction_value",
            "near_market_price_for_depth_fit",
            "noncompetitive_cap_limited_offer",
        ],
        "minimum_exception_targeting_remains_authoritative": True,
        "cba_legality_changed": False,
        "autonomous_commit_enabled": False,
    }
