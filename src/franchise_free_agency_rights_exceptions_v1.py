from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping

from franchise_free_agency_contract_salary_legality_v1_3 import (
    ANCHOR_SEASON,
    FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION,
    evaluate_contract_salary_legality,
    maximum_initial_salary_for_offer,
    minimum_salary_floor_for_offer,
    maximum_initial_salary_for_state,
    minimum_salary_floor_for_state,
    resolve_years_of_service,
)
from franchise_free_agency_financial_bridge_v1_2 import (
    FREE_AGENCY_FINANCIAL_BRIDGE_VERSION,
    evaluate_live_free_agency_financial_gate,
)
from franchise_free_agency_transaction_v1 import (
    FreeAgencyFinancialGateResult,
    FreeAgencyOffer,
    FreeAgencyTransactionPreview,
    build_free_agency_preview,
)
from franchise_offseason_market_season_v1 import (
    modeled_future_market_enabled,
    resolve_offseason_market_season,
)
from franchise_free_agency_cba_financial_constants_v1 import (
    CBA_AVERAGE_PLAYER_SALARY_DENOMINATOR,
    CBA_FINANCIAL_CONSTANTS_VERSION,
    resolve_prior_average_player_salary,
)

FREE_AGENCY_RIGHTS_EXCEPTIONS_VERSION = (
    "franchise-free-agency-rights-exceptions-v1.1-modeled-future-minimum-2026-08-18"
)
FREE_AGENCY_RIGHTS_EXCEPTIONS_SCOPE = (
    "evidence_only_prior_team_rights_plus_one_year_minimum_salary_exception"
)
FREE_AGENCY_RIGHTS_REGISTRY_ATTRIBUTE = "free_agency_rights_registry_v1"
FREE_AGENCY_RIGHTS_EVIDENCE_VERSION = "free-agency-rights-evidence-v1"
FREE_AGENCY_RIGHTS_SOURCE = "2023_nba_nbpa_cba_article_vii"

ROUTE_PURE_CAP = "pure_cap_space_only"
ROUTE_BIRD = "bird_exception"
ROUTE_EARLY_BIRD = "early_bird_exception"
ROUTE_NON_BIRD = "non_bird_exception"
ROUTE_MINIMUM = "minimum_salary_exception"
ROUTE_UNRESOLVED = "manual_review_no_proven_route"

RIGHTS_BIRD = "bird"
RIGHTS_EARLY_BIRD = "early_bird"
RIGHTS_NON_BIRD = "non_bird"
RIGHTS_UNKNOWN = "unknown"


@dataclass(frozen=True)
class FreeAgencyRightsEvidence:
    player_id: str
    prior_team: str
    continuous_prior_seasons: int
    continuity_verified: bool
    prior_regular_salary: float | None = None
    prior_average_player_salary: float | None = None
    restricted_free_agent: bool = False
    qualifying_offer_amount: float | None = None
    source: str = "explicit_verified_input"
    evidence_version: str = FREE_AGENCY_RIGHTS_EVIDENCE_VERSION


@dataclass(frozen=True)
class FreeAgencyRightsResolution:
    version: str
    player_id: str
    status: str
    classification: str
    prior_team: str
    continuous_prior_seasons: int | None
    continuity_verified: bool
    reason: str
    prior_regular_salary: float | None
    prior_average_player_salary: float | None
    restricted_free_agent: bool
    qualifying_offer_amount: float | None
    evidence_source: str


@dataclass(frozen=True)
class FreeAgencyExceptionRouteResolution:
    version: str
    status: str
    financial_route: str
    rights_classification: str
    prior_team: str
    minimum_salary_floor: float | None
    maximum_initial_salary: float | None
    safe_exception_ceiling: float | None
    exact_exception_ceiling: bool
    min_contract_years: int
    max_contract_years: int
    reason: str


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _finite_positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _player_id(value: Any) -> str:
    text = _clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def rights_registry_from_state(state: Any) -> dict[str, dict[str, Any]]:
    """Return verified rights evidence from the state plus the season-scoped population overlay.

    Explicit state-owned evidence remains authoritative. The external overlay is read-only,
    season-scoped, and only exposes rows for players who are still in the current free-agent
    pool. Missing, stale, malformed, or unverified overlay rows are ignored rather than inferred.
    """
    registry: dict[str, dict[str, Any]] = {}
    try:
        from franchise_free_agency_rights_population_v1 import load_overlay_for_state
        overlay = load_overlay_for_state(state)
        if isinstance(overlay, Mapping):
            for raw_id, row in overlay.items():
                pid = _player_id(raw_id)
                if not pid or not isinstance(row, Mapping):
                    continue
                registry[pid] = copy.deepcopy(dict(row))
    except Exception:
        # Population is an additive evidence layer. Its absence can never make the
        # locked rights engine less conservative or prevent normal startup.
        pass

    raw = getattr(state, FREE_AGENCY_RIGHTS_REGISTRY_ATTRIBUTE, None)
    if raw is None:
        return registry
    if not isinstance(raw, Mapping):
        return registry
    for raw_id, row in raw.items():
        pid = _player_id(raw_id)
        if not pid or not isinstance(row, Mapping):
            continue
        # Explicit checkpoint/state evidence wins over the derived overlay.
        registry[pid] = copy.deepcopy(dict(row))
    return registry


def rights_registry_fingerprint(state: Any) -> str:
    encoded = json.dumps(
        rights_registry_from_state(state),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_rights_registry_candidate(
    state: Any,
    evidence: FreeAgencyRightsEvidence,
) -> Any:
    """Return a copy with explicit rights evidence persisted on simulation state.

    This helper never infers prior team, service continuity, salary, RFA status, or
    qualifying-offer values. The caller must provide verified evidence.
    """
    pid = _player_id(evidence.player_id)
    team = _team(evidence.prior_team)
    if not pid or not team:
        raise ValueError("Rights evidence requires player_id and prior_team.")
    if int(evidence.continuous_prior_seasons) < 0:
        raise ValueError("continuous_prior_seasons cannot be negative.")
    candidate = copy.deepcopy(state)
    registry = rights_registry_from_state(candidate)
    row = asdict(evidence)
    row["player_id"] = pid
    row["prior_team"] = team
    row["continuous_prior_seasons"] = int(evidence.continuous_prior_seasons)
    row["continuity_verified"] = bool(evidence.continuity_verified)
    row["prior_regular_salary"] = _finite_positive(evidence.prior_regular_salary)
    row["prior_average_player_salary"] = _finite_positive(
        evidence.prior_average_player_salary
    )
    row["qualifying_offer_amount"] = _finite_positive(evidence.qualifying_offer_amount)
    row["restricted_free_agent"] = bool(evidence.restricted_free_agent)
    registry[pid] = row
    setattr(candidate, FREE_AGENCY_RIGHTS_REGISTRY_ATTRIBUTE, registry)
    return candidate


def resolve_free_agency_rights(state: Any, player_id: str) -> FreeAgencyRightsResolution:
    pid = _player_id(player_id)
    row = rights_registry_from_state(state).get(pid)
    if row is None:
        return FreeAgencyRightsResolution(
            version=FREE_AGENCY_RIGHTS_EXCEPTIONS_VERSION,
            player_id=pid,
            status="manual_review",
            classification=RIGHTS_UNKNOWN,
            prior_team="",
            continuous_prior_seasons=None,
            continuity_verified=False,
            reason=(
                "No explicit prior-team continuity evidence is stored. V1 will not "
                "infer Bird rights from age, current free-agent status, target fit, or roster need."
            ),
            prior_regular_salary=None,
            prior_average_player_salary=None,
            restricted_free_agent=False,
            qualifying_offer_amount=None,
            evidence_source="",
        )

    prior_team = _team(row.get("prior_team"))
    continuity_verified = bool(row.get("continuity_verified", False))
    raw_seasons = row.get("continuous_prior_seasons")
    try:
        seasons = int(raw_seasons)
    except (TypeError, ValueError):
        seasons = -1
    if seasons < 0 or not prior_team or not continuity_verified:
        return FreeAgencyRightsResolution(
            version=FREE_AGENCY_RIGHTS_EXCEPTIONS_VERSION,
            player_id=pid,
            status="manual_review",
            classification=RIGHTS_UNKNOWN,
            prior_team=prior_team,
            continuous_prior_seasons=seasons if seasons >= 0 else None,
            continuity_verified=continuity_verified,
            reason="Stored rights evidence is incomplete or not explicitly verified.",
            prior_regular_salary=_finite_positive(row.get("prior_regular_salary")),
            prior_average_player_salary=_finite_positive(row.get("prior_average_player_salary")),
            restricted_free_agent=bool(row.get("restricted_free_agent", False)),
            qualifying_offer_amount=_finite_positive(row.get("qualifying_offer_amount")),
            evidence_source=_clean(row.get("source")),
        )

    if seasons >= 3:
        classification = RIGHTS_BIRD
    elif seasons >= 2:
        classification = RIGHTS_EARLY_BIRD
    else:
        classification = RIGHTS_NON_BIRD

    return FreeAgencyRightsResolution(
        version=FREE_AGENCY_RIGHTS_EXCEPTIONS_VERSION,
        player_id=pid,
        status="pass",
        classification=classification,
        prior_team=prior_team,
        continuous_prior_seasons=seasons,
        continuity_verified=True,
        reason=f"Verified prior-team continuity resolves {classification} rights.",
        prior_regular_salary=_finite_positive(row.get("prior_regular_salary")),
        prior_average_player_salary=_finite_positive(row.get("prior_average_player_salary")),
        restricted_free_agent=bool(row.get("restricted_free_agent", False)),
        qualifying_offer_amount=_finite_positive(row.get("qualifying_offer_amount")),
        evidence_source=_clean(row.get("source")),
    )


def _rights_exception_ceiling(
    state: Any,
    offer: FreeAgencyOffer,
    rights: FreeAgencyRightsResolution,
) -> FreeAgencyExceptionRouteResolution:
    player = getattr(state, "players", {}).get(_player_id(offer.player_id))
    service, _ = resolve_years_of_service(player)
    minimum = minimum_salary_floor_for_state(
        state,
        years_of_service=service,
        contract_years=int(offer.years),
    )
    max_player = maximum_initial_salary_for_state(
        state,
        years_of_service=service,
        prior_salary=rights.prior_regular_salary,
    )
    classification = rights.classification
    market_season = resolve_offseason_market_season(state)

    if rights.status != "pass" or _team(offer.team_abbreviation) != rights.prior_team:
        return FreeAgencyExceptionRouteResolution(
            version=FREE_AGENCY_RIGHTS_EXCEPTIONS_VERSION,
            status="manual_review",
            financial_route=ROUTE_UNRESOLVED,
            rights_classification=classification,
            prior_team=rights.prior_team,
            minimum_salary_floor=minimum,
            maximum_initial_salary=max_player,
            safe_exception_ceiling=None,
            exact_exception_ceiling=False,
            min_contract_years=1,
            max_contract_years=4,
            reason="No verified prior-team exception applies to this destination.",
        )

    if market_season != ANCHOR_SEASON and modeled_future_market_enabled(state):
        return FreeAgencyExceptionRouteResolution(
            version=FREE_AGENCY_RIGHTS_EXCEPTIONS_VERSION,
            status="manual_review",
            financial_route=ROUTE_UNRESOLVED,
            rights_classification=classification,
            prior_team=rights.prior_team,
            minimum_salary_floor=minimum,
            maximum_initial_salary=max_player,
            safe_exception_ceiling=None,
            exact_exception_ceiling=False,
            min_contract_years=1,
            max_contract_years=4,
            reason=(
                "Future Bird-family exception ceilings remain manual review until "
                "a season-specific rights rollover authority installs current evidence."
            ),
        )

    if classification == RIGHTS_BIRD:
        ceiling = max_player
        min_years, max_years = 1, 5
        exact = service is not None
        route = ROUTE_BIRD
    elif classification == RIGHTS_EARLY_BIRD:
        if rights.prior_regular_salary is None:
            ceiling = None
            exact = False
        else:
            average_resolution = resolve_prior_average_player_salary(ANCHOR_SEASON)
            effective_prior_average = (
                rights.prior_average_player_salary
                if rights.prior_average_player_salary is not None
                else (
                    average_resolution.average_player_salary
                    if average_resolution.status == "pass"
                    else None
                )
            )
            candidates = [1.75 * rights.prior_regular_salary]
            exact = effective_prior_average is not None
            if effective_prior_average is not None:
                candidates.append(1.05 * effective_prior_average)
            ceiling = min(max(candidates), max_player)
        min_years, max_years = 2, 4
        route = ROUTE_EARLY_BIRD
    elif classification == RIGHTS_NON_BIRD:
        one_year_minimum = minimum_salary_floor_for_state(
            state,
            years_of_service=service,
            contract_years=1,
        )
        candidates: list[float] = []
        if rights.prior_regular_salary is not None:
            candidates.append(1.20 * rights.prior_regular_salary)
        if one_year_minimum is not None:
            candidates.append(1.20 * one_year_minimum)
        exact = not rights.restricted_free_agent or rights.qualifying_offer_amount is not None
        if rights.restricted_free_agent and rights.qualifying_offer_amount is not None:
            candidates.append(rights.qualifying_offer_amount)
        ceiling = min(max(candidates), max_player) if candidates else None
        min_years, max_years = 1, 4
        route = ROUTE_NON_BIRD
    else:
        ceiling = None
        exact = False
        min_years, max_years = 1, 4
        route = ROUTE_UNRESOLVED

    status = "pass" if ceiling is not None and minimum is not None else "manual_review"
    reason = (
        f"Verified {classification} prior-team rights provide a conservative safe first-year ceiling."
        if status == "pass"
        else f"Verified {classification} rights exist, but salary evidence is incomplete."
    )
    return FreeAgencyExceptionRouteResolution(
        version=FREE_AGENCY_RIGHTS_EXCEPTIONS_VERSION,
        status=status,
        financial_route=route,
        rights_classification=classification,
        prior_team=rights.prior_team,
        minimum_salary_floor=minimum,
        maximum_initial_salary=max_player,
        safe_exception_ceiling=ceiling,
        exact_exception_ceiling=bool(exact),
        min_contract_years=min_years,
        max_contract_years=max_years,
        reason=reason,
    )


def resolve_prior_team_exception_route(
    state: Any,
    offer: FreeAgencyOffer,
) -> FreeAgencyExceptionRouteResolution:
    rights = resolve_free_agency_rights(state, offer.player_id)
    return _rights_exception_ceiling(state, offer, rights)


def _minimum_exception_gate(state: Any, offer: FreeAgencyOffer) -> FreeAgencyFinancialGateResult:
    season = resolve_offseason_market_season(state)
    player = getattr(state, "players", {}).get(_player_id(offer.player_id))
    service, service_source = resolve_years_of_service(player)
    minimum = minimum_salary_floor_for_state(
        state,
        years_of_service=service,
        contract_years=1,
    )
    salary = _finite_positive(offer.annual_salary)
    payload = {
        "rights_exceptions_version": FREE_AGENCY_RIGHTS_EXCEPTIONS_VERSION,
        "financial_route": ROUTE_MINIMUM,
        "season_label": season,
        "years_of_service": service,
        "service_source": service_source,
        "minimum_salary_floor": minimum,
        "contract_years": int(offer.years),
        "flat_salary_model": True,
        "two_year_minimum_exception_auto_release_supported": False,
    }
    if season != ANCHOR_SEASON and not modeled_future_market_enabled(state):
        return FreeAgencyFinancialGateResult(
            status="manual_review",
            reason=(
                "Future Minimum Salary Exception requires a durable completed-season "
                "market marker and modeled future salary scale."
            ),
            payload=payload,
        )
    if service is None:
        return FreeAgencyFinancialGateResult(
            status="manual_review",
            reason=(
                "Minimum Salary Exception requires the player's applicable minimum. "
                "V1 will not infer years of service from age."
            ),
            payload=payload,
        )
    if int(offer.years) != 1:
        return FreeAgencyFinancialGateResult(
            status="manual_review",
            reason=(
                "The CBA allows one- or two-year minimum-exception contracts, but the "
                "current ContractState stores one flat annual salary. V1 auto-releases "
                "one-year minimum contracts only until annual salary schedules exist."
            ),
            payload=payload,
        )
    if _clean(getattr(offer, "option_type", "")):
        return FreeAgencyFinancialGateResult(
            status="blocked",
            reason="V1 minimum-exception release does not attach an option to a one-year contract.",
            payload=payload,
        )
    if minimum is None or salary is None or not math.isclose(salary, minimum, abs_tol=0.01):
        return FreeAgencyFinancialGateResult(
            status="blocked",
            reason="Minimum Salary Exception V1 requires the exact applicable one-year minimum salary.",
            payload=payload,
        )
    return FreeAgencyFinancialGateResult(
        status="pass",
        reason="Offer is an exact one-year applicable-minimum contract using the Minimum Salary Exception.",
        payload=payload,
    )


def evaluate_rights_exception_financial_gate(
    state: Any,
    offer: FreeAgencyOffer,
) -> FreeAgencyFinancialGateResult:
    """Resolve pure cap first, then proven prior-team rights, then minimum exception.

    No exception is inferred. Bird-family routes require explicit state-owned evidence.
    The Minimum Salary Exception is auto-released only for one-year exact-minimum
    offers because the current contract model does not yet store per-season salaries.
    """
    pure_cap = evaluate_live_free_agency_financial_gate(state, offer)
    generic_contract = evaluate_contract_salary_legality(state, offer)
    base_payload = dict(pure_cap.payload or {})
    base_payload.update({
        "rights_exceptions_version": FREE_AGENCY_RIGHTS_EXCEPTIONS_VERSION,
        "financial_bridge_version": FREE_AGENCY_FINANCIAL_BRIDGE_VERSION,
        "contract_salary_legality_version": FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION,
        "generic_contract_status": generic_contract.status,
        "generic_contract_reason": generic_contract.reason,
    })

    if pure_cap.status == "pass" and generic_contract.status == "pass":
        base_payload["financial_route"] = ROUTE_PURE_CAP
        base_payload["rights_classification"] = RIGHTS_UNKNOWN
        return FreeAgencyFinancialGateResult(
            status="pass",
            reason=f"{pure_cap.reason} Contract salary legality also passes V1.3.",
            payload=base_payload,
        )

    prior_route = resolve_prior_team_exception_route(state, offer)
    rights_payload = asdict(prior_route)
    if prior_route.status == "pass":
        salary = _finite_positive(offer.annual_salary)
        years = int(offer.years)
        option_type = _clean(getattr(offer, "option_type", ""))
        minimum = prior_route.minimum_salary_floor
        ceiling = prior_route.safe_exception_ceiling
        term_ok = prior_route.min_contract_years <= years <= prior_route.max_contract_years
        option_ok = not option_type or years >= 2
        salary_ok = (
            salary is not None
            and minimum is not None
            and ceiling is not None
            and salary + 0.01 >= minimum
            and salary - 0.01 <= ceiling
        )
        if term_ok and option_ok and salary_ok:
            return FreeAgencyFinancialGateResult(
                status="pass",
                reason=(
                    f"Offer clears the verified {prior_route.rights_classification} "
                    "prior-team exception route and conservative salary/term bounds."
                ),
                payload={
                    **base_payload,
                    **rights_payload,
                    "financial_route": prior_route.financial_route,
                },
            )

    minimum_result = _minimum_exception_gate(state, offer)
    if minimum_result.status == "pass":
        payload = dict(base_payload)
        payload.update(minimum_result.payload or {})
        rights = resolve_free_agency_rights(state, offer.player_id)
        payload.update({
            "rights_classification": rights.classification,
            "prior_team": rights.prior_team,
        })
        return FreeAgencyFinancialGateResult(
            status="pass",
            reason=minimum_result.reason,
            payload=payload,
        )

    status = "blocked" if minimum_result.status == "blocked" and pure_cap.status == "blocked" else "manual_review"
    return FreeAgencyFinancialGateResult(
        status=status,
        reason=(
            "Offer does not fit verified pure cap space, no proven prior-team rights "
            "route clears the offer, and the one-year Minimum Salary Exception does not apply."
        ),
        payload={
            **base_payload,
            "financial_route": ROUTE_UNRESOLVED,
            "prior_team_route": rights_payload,
            "minimum_exception_status": minimum_result.status,
            "minimum_exception_reason": minimum_result.reason,
            "minimum_exception_payload": minimum_result.payload or {},
        },
    )


def build_rights_exception_free_agency_preview(
    state: Any,
    offer: FreeAgencyOffer,
    *,
    state_validator: Callable[[Any], Any] | None = None,
    max_roster_size: int = 18,
    _source_fingerprint: str | None = None,
    _defer_candidate_fingerprint: bool = False,
) -> FreeAgencyTransactionPreview:
    return build_free_agency_preview(
        state,
        offer,
        financial_gate=evaluate_rights_exception_financial_gate,
        state_validator=state_validator,
        max_roster_size=max_roster_size,
        _source_fingerprint=_source_fingerprint,
        _defer_candidate_fingerprint=_defer_candidate_fingerprint,
    )


def rights_exceptions_contract_report() -> dict[str, Any]:
    return {
        "version": FREE_AGENCY_RIGHTS_EXCEPTIONS_VERSION,
        "scope": FREE_AGENCY_RIGHTS_EXCEPTIONS_SCOPE,
        "rights_registry_attribute": FREE_AGENCY_RIGHTS_REGISTRY_ATTRIBUTE,
        "rights_are_evidence_only": True,
        "age_inference_enabled": False,
        "target_fit_inference_enabled": False,
        "bird_continuity_seasons": 3,
        "early_bird_continuity_seasons": 2,
        "early_bird_min_contract_years": 2,
        "non_bird_prior_salary_multiplier": 1.20,
        "early_bird_prior_salary_multiplier": 1.75,
        "early_bird_average_salary_multiplier": 1.05,
        "early_bird_average_salary_resolution": "season_scoped_cba_financial_constants_v1",
        "cba_financial_constants_version": CBA_FINANCIAL_CONSTANTS_VERSION,
        "average_player_salary_denominator": CBA_AVERAGE_PLAYER_SALARY_DENOMINATOR,
        "minimum_salary_exception_one_year_auto_release": True,
        "minimum_salary_exception_two_year_auto_release": False,
        "minimum_salary_exception_two_year_reason": "flat_contract_salary_model_needs_annual_schedule",
        "mid_level_exceptions_supported": False,
        "bi_annual_exception_supported": False,
        "restricted_free_agency_matching_supported": False,
        "sign_and_trade_supported": False,
    }


# Verified Bird-Rights Population V1 compatibility marker.
FREE_AGENCY_RIGHTS_POPULATION_OVERLAY_SUPPORTED = True
