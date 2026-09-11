from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from franchise_free_agency_live_signing_v1 import (
    FREE_AGENCY_LIVE_SIGNING_VERSION,
    FreeAgencyLiveSigningError,
    commit_contract_legal_free_agency_preview_live,
)

FREE_AGENCY_PLAYER_DECISION_VERSION = (
    "franchise-free-agency-player-decision-v1-2026-08-14"
)
FREE_AGENCY_PLAYER_DECISION_UI_VERSION = (
    "franchise-free-agency-player-decision-ui-v1-2026-08-14"
)
FREE_AGENCY_PLAYER_DECISION_SCOPE = "single_offer_deterministic_no_competing_market"


class FreeAgencyPlayerDecisionError(RuntimeError):
    """Raised when a player-decision-backed signing cannot be released safely."""


@dataclass(frozen=True)
class PlayerPreferenceProfile:
    version: str
    player_id: str
    season_label: str
    archetype: str
    money_weight: float
    role_weight: float
    winning_weight: float
    security_weight: float
    career_fit_weight: float
    acceptance_threshold: float
    market_patience: float


@dataclass(frozen=True)
class FreeAgencyPlayerDecision:
    version: str
    scope: str
    status: str
    player_id: str
    player_name: str
    team_abbreviation: str
    offer_id: str
    annual_salary: float
    years: int
    guaranteed: bool
    option_type: str
    utility_score: float
    acceptance_threshold: float
    market_salary_reference: float
    minimum_salary_floor: float | None
    maximum_legal_salary: float | None
    maximum_affordable_salary: float | None
    salary_score: float
    role_score: float
    winning_score: float
    security_score: float
    career_fit_score: float
    counter_salary: float | None
    rationale: tuple[str, ...]
    preference_profile: PlayerPreferenceProfile
    preview_source_fingerprint: str
    decision_fingerprint: str

    @property
    def accepted(self) -> bool:
        return self.status == "accept"


@dataclass(frozen=True)
class PlayerAcceptedLiveSigningResult:
    version: str
    decision_fingerprint: str
    player_decision_status: str
    live_signing_result: Any


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


def _season_label(state: Any) -> str:
    return _clean(getattr(getattr(state, "settings", None), "season_label", ""))


def _stable_unit(seed: str, index: int) -> float:
    digest = hashlib.sha256(f"{seed}|{index}".encode("utf-8")).digest()
    integer = int.from_bytes(digest[:8], "big")
    return integer / float((1 << 64) - 1)


def _player(state: Any, player_id: str) -> Any | None:
    return getattr(state, "players", {}).get(_clean(player_id))


def _offer(preview: Any) -> Any:
    return getattr(preview, "offer", None)


def _financial_payload(preview: Any) -> dict[str, Any]:
    gate = getattr(preview, "financial_gate", None)
    payload = getattr(gate, "payload", None)
    return dict(payload) if isinstance(payload, Mapping) else {}


def _contract_legality_payload(preview: Any) -> dict[str, Any]:
    payload = _financial_payload(preview)
    contract = payload.get("contract_salary_legality")
    return dict(contract) if isinstance(contract, Mapping) else {}


def _position_family(position: Any) -> str:
    text = _clean(position).upper().replace("-", "/")
    tokens = {token.strip() for token in text.split("/") if token.strip()}
    if not tokens:
        return "unknown"
    if tokens <= {"PG", "SG", "G"}:
        return "guard"
    if tokens <= {"SF", "PF", "F"}:
        return "wing"
    if "C" in tokens and not ({"PG", "SG", "G"} & tokens):
        return "big"
    if ({"PG", "SG", "G"} & tokens) and ({"SF", "PF", "F"} & tokens):
        return "guard_wing"
    if ({"SF", "PF", "F"} & tokens) and "C" in tokens:
        return "forward_big"
    if "PG" in text or "SG" in text:
        return "guard"
    if "C" in text:
        return "big"
    if "SF" in text or "PF" in text:
        return "wing"
    return "unknown"


def _family_compatible(left: str, right: str) -> bool:
    if "unknown" in {left, right}:
        return False
    if left == right:
        return True
    compatibility = {
        "guard_wing": {"guard", "wing"},
        "forward_big": {"wing", "big"},
    }
    return right in compatibility.get(left, set()) or left in compatibility.get(right, set())


def _team_roster_players(state: Any, team: str) -> list[Any]:
    team_state = getattr(state, "teams", {}).get(_team(team))
    if team_state is None:
        return []
    players = getattr(state, "players", {})
    result: list[Any] = []
    for player_id in getattr(team_state, "roster_player_ids", ()):
        player = players.get(_clean(player_id))
        if player is not None:
            result.append(player)
    return result


def role_opportunity_score(state: Any, player: Any, team: str) -> float:
    player_overall = _finite(getattr(player, "overall_rating", None)) or 70.0
    family = _position_family(getattr(player, "position", ""))
    roster = _team_roster_players(state, team)
    if not roster:
        return 95.0

    stronger_family = 0
    roster_ratings: list[float] = []
    for teammate in roster:
        rating = _finite(getattr(teammate, "overall_rating", None))
        if rating is not None:
            roster_ratings.append(rating)
        teammate_family = _position_family(getattr(teammate, "position", ""))
        if (
            rating is not None
            and rating > player_overall + 0.25
            and _family_compatible(family, teammate_family)
        ):
            stronger_family += 1

    depth_score = {
        0: 96.0,
        1: 84.0,
        2: 66.0,
        3: 46.0,
    }.get(stronger_family, 27.0)

    roster_ratings.sort(reverse=True)
    if len(roster_ratings) >= 8:
        rotation_cut = roster_ratings[7]
        if player_overall >= rotation_cut:
            depth_score += 6.0
        elif player_overall < rotation_cut - 4.0:
            depth_score -= 8.0
    elif len(roster_ratings) < 8:
        depth_score += 4.0

    return round(_clamp(depth_score), 3)


def _standings_source(state: Any) -> Mapping[str, Any]:
    history = list(getattr(state, "season_history", []) or [])
    if history:
        latest = history[-1]
        standings = getattr(latest, "standings", None)
        if isinstance(standings, Mapping) and standings:
            return standings
    standings = getattr(state, "standings", None)
    return standings if isinstance(standings, Mapping) else {}


def winning_environment_score(state: Any, team: str) -> float:
    standings = _standings_source(state)
    rows: list[tuple[str, float]] = []
    for code, standing in standings.items():
        wins = _finite(getattr(standing, "wins", None)) or 0.0
        losses = _finite(getattr(standing, "losses", None)) or 0.0
        games = wins + losses
        if games > 0:
            rows.append((_team(code), wins / games))
    if not rows:
        return 50.0
    rows.sort(key=lambda item: (item[1], item[0]))
    target = next((pct for code, pct in rows if code == _team(team)), None)
    if target is None:
        return 50.0
    lower = sum(1 for _, pct in rows if pct < target)
    equal = sum(1 for _, pct in rows if math.isclose(pct, target, abs_tol=1e-12))
    percentile = (lower + 0.5 * equal) / len(rows)
    return round(_clamp(20.0 + 80.0 * percentile), 3)


def security_score(player: Any, preview: Any) -> float:
    offer = _offer(preview)
    years = int(getattr(offer, "years", 0) or 0)
    guaranteed = bool(getattr(offer, "guaranteed", False))
    option = _clean(getattr(offer, "option_type", "")).lower()
    age = _finite(getattr(player, "age", None))
    age = age if age is not None else 27.0

    if age <= 24:
        term = {1: 58.0, 2: 76.0, 3: 94.0, 4: 98.0, 5: 95.0}.get(years, 40.0)
    elif age <= 29:
        term = {1: 60.0, 2: 80.0, 3: 96.0, 4: 100.0, 5: 96.0}.get(years, 40.0)
    elif age <= 33:
        term = {1: 70.0, 2: 96.0, 3: 100.0, 4: 90.0, 5: 80.0}.get(years, 40.0)
    else:
        term = {1: 88.0, 2: 100.0, 3: 92.0, 4: 76.0, 5: 62.0}.get(years, 40.0)

    score = 0.62 * term + 38.0 * (1.0 if guaranteed else 0.25)
    if option == "player_option":
        score += 7.0
    elif option == "team_option":
        score -= 8.0
    return round(_clamp(score), 3)


def _rating_market_salary_reference(player: Any, salary_cap: float) -> float:
    overall = _finite(getattr(player, "overall_rating", None)) or 72.0
    anchors = [
        (68.0, 0.008),
        (72.0, 0.012),
        (75.0, 0.022),
        (78.0, 0.040),
        (81.0, 0.070),
        (84.0, 0.115),
        (87.0, 0.175),
        (90.0, 0.245),
        (94.0, 0.305),
        (99.0, 0.350),
    ]
    if overall <= anchors[0][0]:
        pct = anchors[0][1]
    elif overall >= anchors[-1][0]:
        pct = anchors[-1][1]
    else:
        pct = anchors[0][1]
        for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
            if x0 <= overall <= x1:
                share = (overall - x0) / (x1 - x0)
                pct = y0 + share * (y1 - y0)
                break

    potential = _finite(getattr(player, "potential_rating", None))
    age = _finite(getattr(player, "age", None))
    if potential is not None and age is not None and age <= 25 and potential > overall:
        pct *= 1.0 + min(0.12, max(0.0, potential - overall) * 0.012)
    return salary_cap * pct


def market_salary_reference(player: Any, preview: Any) -> tuple[float, float | None, float | None]:
    payload = _financial_payload(preview)
    contract = _contract_legality_payload(preview)
    cap = _finite(payload.get("salary_cap")) or _finite(contract.get("anchor_salary_cap")) or 164_961_000.0
    minimum = _finite(contract.get("minimum_salary_floor"))
    maximum = _finite(contract.get("maximum_initial_salary"))
    prior = _finite(contract.get("prior_salary"))
    rating_reference = _rating_market_salary_reference(player, cap)
    if prior is not None and prior > 0:
        reference = 0.68 * rating_reference + 0.32 * prior
    else:
        reference = rating_reference
    if minimum is not None:
        reference = max(reference, minimum)
    if maximum is not None:
        reference = min(reference, maximum)
    return round(max(reference, 1.0), 2), minimum, maximum


def salary_value_score(annual_salary: float, market_reference: float, guaranteed: bool) -> float:
    effective_salary = float(annual_salary) * (1.0 if guaranteed else 0.82)
    ratio = max(effective_salary, 1.0) / max(float(market_reference), 1.0)
    score = 50.0 + 78.0 * math.log(ratio, 2.0)
    return round(_clamp(score), 3)


def career_fit_score(player: Any, role: float, winning: float) -> float:
    age = _finite(getattr(player, "age", None))
    age = age if age is not None else 27.0
    overall = _finite(getattr(player, "overall_rating", None)) or 72.0
    potential = _finite(getattr(player, "potential_rating", None))
    upside = max(0.0, (potential if potential is not None else overall) - overall)
    if age <= 24:
        score = 0.78 * role + 0.22 * winning + min(8.0, upside * 1.1)
    elif age <= 29:
        score = 0.54 * role + 0.46 * winning + min(4.0, upside * 0.6)
    else:
        score = 0.25 * role + 0.75 * winning
    return round(_clamp(score), 3)


def preference_profile(state: Any, player: Any) -> PlayerPreferenceProfile:
    player_id = _clean(getattr(player, "player_id", ""))
    season = _season_label(state)
    seed = f"{FREE_AGENCY_PLAYER_DECISION_VERSION}|{season}|{player_id}"
    units = [_stable_unit(seed, index) for index in range(7)]
    age = _finite(getattr(player, "age", None))
    age = age if age is not None else 27.0
    overall = _finite(getattr(player, "overall_rating", None)) or 72.0
    potential = _finite(getattr(player, "potential_rating", None))

    weights = {
        "money": 0.43 + (units[0] - 0.5) * 0.08,
        "role": 0.20 + (units[1] - 0.5) * 0.07,
        "winning": 0.15 + (units[2] - 0.5) * 0.07,
        "security": 0.14 + (units[3] - 0.5) * 0.06,
        "career": 0.08 + (units[4] - 0.5) * 0.04,
    }

    if age <= 24:
        weights["role"] += 0.055
        weights["career"] += 0.025
        weights["winning"] -= 0.040
        weights["security"] -= 0.015
        weights["money"] -= 0.025
    elif age >= 30:
        weights["winning"] += 0.060
        weights["security"] += 0.025
        weights["role"] -= 0.035
        weights["career"] -= 0.020
        weights["money"] -= 0.030

    weights = {key: max(0.035, value) for key, value in weights.items()}
    total = sum(weights.values())
    weights = {key: value / total for key, value in weights.items()}

    patience = units[5]
    threshold = 52.5 + patience * 9.5
    if overall >= 90.0:
        threshold += 3.0
    elif overall >= 85.0:
        threshold += 1.5
    if potential is not None and age <= 24 and potential >= 88.0:
        threshold += 1.5
    threshold = _clamp(threshold, 50.0, 68.0)

    highest = max(
        [
            (weights["money"], "Max-value focused"),
            (weights["role"], "Opportunity seeker"),
            (weights["winning"], "Winning focused"),
            (weights["security"], "Security focused"),
        ],
        key=lambda pair: pair[0],
    )[1]
    if max(weights.values()) < 0.40:
        highest = "Balanced"

    return PlayerPreferenceProfile(
        version=FREE_AGENCY_PLAYER_DECISION_VERSION,
        player_id=player_id,
        season_label=season,
        archetype=highest,
        money_weight=round(weights["money"], 6),
        role_weight=round(weights["role"], 6),
        winning_weight=round(weights["winning"], 6),
        security_weight=round(weights["security"], 6),
        career_fit_weight=round(weights["career"], 6),
        acceptance_threshold=round(threshold, 3),
        market_patience=round(patience, 6),
    )


def _utility(
    profile: PlayerPreferenceProfile,
    salary: float,
    role: float,
    winning: float,
    security: float,
    career: float,
) -> float:
    return round(
        profile.money_weight * salary
        + profile.role_weight * role
        + profile.winning_weight * winning
        + profile.security_weight * security
        + profile.career_fit_weight * career,
        3,
    )


def _decision_fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _counter_ceiling(preview: Any, maximum_legal: float | None) -> float | None:
    payload = _financial_payload(preview)
    cap_space = _finite(payload.get("cap_space_before"))
    candidates = [value for value in (maximum_legal, cap_space) if value is not None and value > 0]
    return min(candidates) if candidates else None


def _round_counter(value: float) -> float:
    increment = 250_000.0
    return math.ceil(value / increment) * increment


def _counter_salary(
    *,
    preview: Any,
    profile: PlayerPreferenceProfile,
    market_reference: float,
    role: float,
    winning: float,
    security: float,
    career: float,
    maximum_legal: float | None,
) -> float | None:
    offer = _offer(preview)
    current = _finite(getattr(offer, "annual_salary", None))
    if current is None or current <= 0:
        return None
    ceiling = _counter_ceiling(preview, maximum_legal)
    if ceiling is None or ceiling <= current + 1.0:
        return None

    guaranteed = bool(getattr(offer, "guaranteed", False))
    at_ceiling = _utility(
        profile,
        salary_value_score(ceiling, market_reference, guaranteed),
        role,
        winning,
        security,
        career,
    )
    if at_ceiling + 1e-9 < profile.acceptance_threshold:
        return None

    low, high = current, ceiling
    for _ in range(48):
        mid = (low + high) / 2.0
        score = _utility(
            profile,
            salary_value_score(mid, market_reference, guaranteed),
            role,
            winning,
            security,
            career,
        )
        if score >= profile.acceptance_threshold:
            high = mid
        else:
            low = mid
    counter = _round_counter(max(high, current + 250_000.0))
    if counter > ceiling + 0.01:
        return None
    return round(counter, 2)


def evaluate_free_agent_offer_decision(state: Any, preview: Any) -> FreeAgencyPlayerDecision:
    offer = _offer(preview)
    if offer is None:
        raise FreeAgencyPlayerDecisionError("The free-agency preview does not contain an offer.")

    player_id = _clean(getattr(offer, "player_id", ""))
    player = _player(state, player_id)
    if player is None:
        raise FreeAgencyPlayerDecisionError(f"Player {player_id} is not available in the decision state.")

    backend_status = _clean(getattr(preview, "status", "")).lower()
    backend_commit = bool(getattr(preview, "can_commit", False))
    team = _team(getattr(offer, "team_abbreviation", ""))
    annual_salary = _finite(getattr(offer, "annual_salary", None)) or 0.0
    years = int(getattr(offer, "years", 0) or 0)
    guaranteed = bool(getattr(offer, "guaranteed", False))
    option_type = _clean(getattr(offer, "option_type", "")).lower()
    source_fingerprint = _clean(getattr(preview, "source_fingerprint", ""))

    profile = preference_profile(state, player)
    reference, minimum, maximum = market_salary_reference(player, preview)
    role = role_opportunity_score(state, player, team)
    winning = winning_environment_score(state, team)
    security = security_score(player, preview)
    career = career_fit_score(player, role, winning)
    salary = salary_value_score(annual_salary, reference, guaranteed)
    utility = _utility(profile, salary, role, winning, security, career)
    affordable = _counter_ceiling(preview, maximum)

    if backend_status != "pass" or not backend_commit:
        status = "not_evaluated"
        counter = None
        rationale = (
            "Player decision is not evaluated until every structural and CBA/financial gate returns PASS.",
        )
    elif utility >= profile.acceptance_threshold:
        status = "accept"
        counter = None
        rationale_parts = [
            f"Offer utility {utility:.1f} clears the player threshold {profile.acceptance_threshold:.1f}.",
            f"Annual salary grades {salary:.1f}/100 against a ${reference:,.0f} market reference.",
        ]
        if role >= 75:
            rationale_parts.append("The destination projects a strong rotation/role opportunity.")
        if winning >= 70:
            rationale_parts.append("The destination grades as a strong recent winning environment.")
        if security >= 80:
            rationale_parts.append("Contract term and guarantee structure provide strong security.")
        rationale = tuple(rationale_parts)
    else:
        counter = _counter_salary(
            preview=preview,
            profile=profile,
            market_reference=reference,
            role=role,
            winning=winning,
            security=security,
            career=career,
            maximum_legal=maximum,
        )
        gap = profile.acceptance_threshold - utility
        if counter is not None and gap <= 18.0:
            status = "counter"
            rationale = (
                f"Offer utility {utility:.1f} is below the player threshold {profile.acceptance_threshold:.1f}.",
                f"The player would counter at approximately ${counter:,.0f} per year on the same term/guarantee structure.",
                "The counter is capped by both the V1.3 salary ceiling and the team's verified pure cap space.",
            )
        else:
            status = "decline"
            rationale_parts = [
                f"Offer utility {utility:.1f} is below the player threshold {profile.acceptance_threshold:.1f}.",
                f"Annual salary grades {salary:.1f}/100 against a ${reference:,.0f} market reference.",
            ]
            if role < 50:
                rationale_parts.append("The current roster projects a crowded role at the player's position family.")
            if winning < 45 and profile.winning_weight >= 0.16:
                rationale_parts.append("The destination's recent winning environment is a meaningful drawback for this player profile.")
            if affordable is not None and affordable <= annual_salary + 1.0:
                rationale_parts.append("No higher pure-cap-space counter is available inside the current verified signing route.")
            rationale = tuple(rationale_parts)

    fingerprint_payload = {
        "version": FREE_AGENCY_PLAYER_DECISION_VERSION,
        "preview_source_fingerprint": source_fingerprint,
        "offer": {
            "player_id": player_id,
            "team": team,
            "salary": round(annual_salary, 2),
            "years": years,
            "guaranteed": guaranteed,
            "option_type": option_type,
        },
        "player_profile": asdict(profile),
        "scores": {
            "salary": salary,
            "role": role,
            "winning": winning,
            "security": security,
            "career": career,
            "utility": utility,
        },
        "status": status,
        "counter_salary": counter,
    }
    fingerprint = _decision_fingerprint(fingerprint_payload)

    return FreeAgencyPlayerDecision(
        version=FREE_AGENCY_PLAYER_DECISION_VERSION,
        scope=FREE_AGENCY_PLAYER_DECISION_SCOPE,
        status=status,
        player_id=player_id,
        player_name=_clean(getattr(player, "player_name", "")) or player_id,
        team_abbreviation=team,
        offer_id=_clean(getattr(offer, "offer_id", "")),
        annual_salary=round(annual_salary, 2),
        years=years,
        guaranteed=guaranteed,
        option_type=option_type,
        utility_score=utility,
        acceptance_threshold=profile.acceptance_threshold,
        market_salary_reference=reference,
        minimum_salary_floor=minimum,
        maximum_legal_salary=maximum,
        maximum_affordable_salary=affordable,
        salary_score=salary,
        role_score=role,
        winning_score=winning,
        security_score=security,
        career_fit_score=career,
        counter_salary=counter,
        rationale=rationale,
        preference_profile=profile,
        preview_source_fingerprint=source_fingerprint,
        decision_fingerprint=fingerprint,
    )


def decision_matches_preview(state: Any, preview: Any, decision: Any) -> bool:
    if not isinstance(decision, FreeAgencyPlayerDecision):
        return False
    try:
        current = evaluate_free_agent_offer_decision(state, preview)
    except Exception:
        return False
    return current.decision_fingerprint == decision.decision_fingerprint


def commit_player_accepted_free_agency_preview_live(
    preview: Any,
    decision: FreeAgencyPlayerDecision,
    *,
    hypothetical: bool = False,
) -> PlayerAcceptedLiveSigningResult:
    """Re-evaluate the player decision on durable state before delegating to Live Signing V1."""
    if hypothetical:
        raise FreeAgencyPlayerDecisionError("A hypothetical player decision can never be committed.")
    if not isinstance(decision, FreeAgencyPlayerDecision) or not decision.accepted:
        raise FreeAgencyPlayerDecisionError("Only an ACCEPT player decision can be committed.")

    from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint

    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise FreeAgencyPlayerDecisionError("The durable franchise checkpoint is unavailable.")
    state = getattr(checkpoint, "simulation_state", None)
    current = evaluate_free_agent_offer_decision(state, preview)
    if current.status != "accept":
        raise FreeAgencyPlayerDecisionError(
            f"The durable player decision is now {current.status.upper()}, not ACCEPT. Preview and submit the offer again."
        )
    if current.decision_fingerprint != decision.decision_fingerprint:
        raise FreeAgencyPlayerDecisionError(
            "The player decision is stale relative to the durable franchise state. Preview and submit the offer again."
        )

    try:
        live = commit_contract_legal_free_agency_preview_live(
            preview,
            hypothetical=False,
        )
    except FreeAgencyLiveSigningError:
        raise
    except Exception as exc:
        raise FreeAgencyPlayerDecisionError(str(exc)) from exc

    return PlayerAcceptedLiveSigningResult(
        version=FREE_AGENCY_PLAYER_DECISION_VERSION,
        decision_fingerprint=decision.decision_fingerprint,
        player_decision_status=decision.status,
        live_signing_result=live,
    )
