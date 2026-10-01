from __future__ import annotations

import hashlib
import importlib
import json
import math
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from franchise_offseason_market_season_v1 import resolve_offseason_market_season
from franchise_free_agency_competing_market_v1 import (
    FREE_AGENCY_COMPETING_MARKET_VERSION,
    FreeAgencyCompetingMarketResult,
    evaluate_competing_offer_market,
)
from franchise_free_agency_contract_salary_legality_v1_3 import (
    FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION,
    maximum_initial_salary_for_offer,
    minimum_salary_floor_for_offer,
    maximum_initial_salary_for_state,
    minimum_salary_floor_for_state,
    resolve_years_of_service,
    resolve_years_of_service_for_state,
)
from franchise_free_agency_financial_bridge_v1_2 import (
    FREE_AGENCY_FINANCIAL_BRIDGE_VERSION,
    resolve_free_agency_financial_environment,
)
from franchise_free_agency_player_decision_v1 import (
    FREE_AGENCY_PLAYER_DECISION_VERSION,
    market_salary_reference,
)
from franchise_free_agency_transaction_v1 import (
    FreeAgencyOffer,
    free_agency_state_fingerprint,
)
from franchise_free_agency_transaction_v1_1 import team_guaranteed_payroll
from franchise_free_agency_cpu_minimum_exception_targeting_v1 import (
    CPU_FREE_AGENCY_MINIMUM_EXCEPTION_TARGETING_VERSION,
    CPUMinimumExceptionTargetingResult,
    evaluate_minimum_exception_targeting,
)
from franchise_free_agency_cpu_roster_construction_v1 import (
    CPU_FREE_AGENCY_ROSTER_CONSTRUCTION_VERSION,
    CPURosterConstructionOfferResult,
    CPURosterConstructionTargetResult,
    evaluate_roster_construction_offer,
    evaluate_roster_construction_target,
)
from franchise_free_agency_cpu_offer_economic_intelligence_v1 import (
    CPU_FREE_AGENCY_OFFER_ECONOMIC_INTELLIGENCE_VERSION,
    CPUOfferEconomicIntelligenceResult,
    evaluate_cpu_offer_economic_intelligence,
)
from franchise_free_agency_rights_exceptions_v1 import (
    FREE_AGENCY_RIGHTS_EXCEPTIONS_VERSION,
    ROUTE_BIRD,
    ROUTE_EARLY_BIRD,
    ROUTE_MINIMUM,
    ROUTE_NON_BIRD,
    ROUTE_PURE_CAP,
    build_rights_exception_free_agency_preview,
    resolve_free_agency_rights,
    resolve_prior_team_exception_route,
)

CPU_FREE_AGENCY_OFFER_GENERATION_VERSION = (
    "franchise-free-agency-cpu-offer-generation-v1-2026-08-14"
)
CPU_FREE_AGENCY_PREVIEW_REUSE_VERSION = (
    "franchise-free-agency-cpu-preview-reuse-v1-2026-09-11"
)
CPU_FREE_AGENCY_SPECULATIVE_SOURCE_VALIDATION_VERSION = (
    "franchise-free-agency-speculative-source-validation-v1-2026-09-25"
)
CPU_FREE_AGENCY_BOARD_CACHE_VERSION = (
    "franchise-free-agency-cpu-board-cache-v1-2026-09-24"
)
CPU_FREE_AGENCY_OFFER_GENERATION_SCOPE = (
    "read_only_cpu_bid_construction_from_existing_front_office_target_boards"
)
CPU_FRONT_OFFICE_MODULE = "franchise_cpu_front_office_v1"
CPU_FRONT_OFFICE_BUILDER = "build_league_front_office_plan"
CPU_FREE_AGENCY_DIRECTION_ADAPTER_VERSION = (
    "franchise-free-agency-cpu-direction-adapter-v1.0.1-2026-08-14"
)
CPU_FREE_AGENCY_TERM_FEASIBILITY_VERSION = (
    "franchise-free-agency-cpu-term-feasibility-v1.0.2-2026-08-14"
)
CPU_FREE_AGENCY_EXCEPTION_ROUTING_VERSION = (
    "franchise-free-agency-cpu-exception-routing-v1-2026-08-14"
)
CPU_FREE_AGENCY_MINIMUM_TARGETING_ADAPTER_VERSION = (
    "franchise-free-agency-cpu-minimum-targeting-adapter-v1-2026-08-14"
)
CPU_FREE_AGENCY_ROSTER_CONSTRUCTION_ADAPTER_VERSION = (
    "franchise-free-agency-cpu-roster-construction-adapter-v1-2026-08-14"
)
CPU_FREE_AGENCY_OFFER_ECONOMIC_ADAPTER_VERSION = (
    "franchise-free-agency-cpu-offer-economic-adapter-v1-2026-08-14"
)


class CPUFreeAgencyOfferGenerationError(RuntimeError):
    """Raised when CPU free-agency bid construction cannot proceed safely."""


@dataclass(frozen=True)
class CPUFreeAgencyGeneratedOffer:
    version: str
    season_label: str
    player_id: str
    player_name: str
    team_abbreviation: str
    team_direction: str
    salary_posture: str
    target_fit_score: float
    target_tier: str
    market_salary_reference: float
    annual_salary: float
    years: int
    guaranteed: bool
    option_type: str
    minimum_salary_floor: float
    maximum_initial_salary: float
    cap_space_before: float
    aggression_multiplier: float
    preview: Any
    offer_fingerprint: str
    strategic_requested_years: int = 0
    term_fallback_applied: bool = False
    financial_route: str = ROUTE_PURE_CAP
    rights_classification: str = "unknown"
    prior_team: str = ""
    minimum_targeting_status: str = "not_applicable"
    minimum_targeting_tier: str = ""
    minimum_targeting_score: float = 0.0
    minimum_targeting_reason_code: str = ""
    minimum_targeting_interest: float | None = None
    minimum_targeting_gap: float | None = None
    minimum_targeting_market_ratio: float | None = None
    minimum_targeting_fingerprint: str = ""
    roster_construction_score: float = 0.0
    roster_construction_tier: str = ""
    roster_construction_reason_code: str = ""
    roster_position_family: str = ""
    roster_projected_role: str = ""
    roster_positional_need_score: float = 0.0
    roster_role_upgrade_score: float = 0.0
    roster_timeline_fit_score: float = 0.0
    roster_upside_fit_score: float = 0.0
    roster_redundancy_risk: float = 0.0
    roster_prospect_blocking_risk: float = 0.0
    roster_marginal_overall_vs_best: float = 0.0
    roster_marginal_overall_vs_second: float = 0.0
    roster_spending_multiplier: float = 1.0
    roster_target_fingerprint: str = ""
    roster_offer_status: str = "not_evaluated"
    roster_offer_reason_code: str = ""
    roster_offer_economic_score: float = 0.0
    roster_offer_salary_to_market_ratio: float | None = None
    roster_offer_interest: float | None = None
    roster_offer_gap: float | None = None
    roster_offer_fingerprint: str = ""
    offer_economic_status: str = "not_evaluated"
    offer_economic_tier: str = ""
    offer_economic_reason_code: str = ""
    offer_economic_credibility_score: float = 0.0
    offer_economic_minimum_market_ratio: float = 0.0
    offer_economic_salary_to_market_ratio: float | None = None
    offer_economic_interest: float | None = None
    offer_economic_gap: float | None = None
    offer_economic_discount_support_score: float = 0.0
    offer_economic_fingerprint: str = ""


@dataclass(frozen=True)
class CPUFreeAgencySkippedBid:
    player_id: str
    player_name: str
    team_abbreviation: str
    reason: str
    roster_construction_score: float | None = None
    roster_construction_reason_code: str = ""
    roster_construction_fingerprint: str = ""
    offer_economic_score: float | None = None
    offer_economic_reason_code: str = ""
    offer_economic_fingerprint: str = ""


@dataclass(frozen=True)
class CPUFreeAgencyOfferBoard:
    version: str
    scope: str
    season_label: str
    cpu_team_count: int
    targeted_player_count: int
    generated_offer_count: int
    skipped_bid_count: int
    offers: tuple[CPUFreeAgencyGeneratedOffer, ...]
    skipped: tuple[CPUFreeAgencySkippedBid, ...]
    board_fingerprint: str


@dataclass(frozen=True)
class CPUFreeAgencyPlayerMarket:
    version: str
    player_id: str
    player_name: str
    cpu_offer_count: int
    market: FreeAgencyCompetingMarketResult


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


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _season(state: Any) -> str:
    return resolve_offseason_market_season(state)


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


def _sequence(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        return tuple(value.values())
    if isinstance(value, (str, bytes)):
        return ()
    try:
        return tuple(value)
    except TypeError:
        return ()


def _name_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", _clean(value))
    ascii_text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(ascii_text.casefold().split())


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _state_player_maps(state: Any) -> tuple[dict[str, Any], dict[str, str]]:
    players = dict(getattr(state, "players", {}) or {})
    free_ids = {_clean(value) for value in getattr(state, "free_agent_player_ids", ())}
    by_name: dict[str, str] = {}
    for player_id in free_ids:
        player = players.get(player_id)
        if player is None:
            continue
        name = _name_key(getattr(player, "player_name", ""))
        if name and name not in by_name:
            by_name[name] = player_id
    return players, by_name


def _extract_team_plans(front_office_plan: Any) -> tuple[tuple[str, Any], ...]:
    candidate = _value(
        front_office_plan,
        (
            "team_plans",
            "plans_by_team",
            "team_plans_by_team",
            "plans",
            "teams",
            "by_team",
        ),
        None,
    )
    if candidate is None:
        candidate = front_office_plan

    rows: list[tuple[str, Any]] = []
    if isinstance(candidate, Mapping):
        for key, plan in candidate.items():
            team = _team(
                _value(
                    plan,
                    ("team_abbreviation", "team", "team_code", "abbreviation"),
                    key,
                )
            )
            if team:
                rows.append((team, plan))
    else:
        for plan in _sequence(candidate):
            team = _team(
                _value(
                    plan,
                    ("team_abbreviation", "team", "team_code", "abbreviation"),
                    "",
                )
            )
            if team:
                rows.append((team, plan))

    unique: dict[str, Any] = {}
    for team, plan in rows:
        unique[team] = plan
    return tuple(sorted(unique.items()))


def _extract_targets(team_plan: Any) -> tuple[Any, ...]:
    return _sequence(
        _value(
            team_plan,
            (
                "free_agent_targets",
                "free_agent_target_board",
                "free_agent_board",
                "fa_targets",
                "target_free_agents",
                "free_agents",
            ),
            (),
        )
    )


def _target_player_id(target: Any, by_name: Mapping[str, str]) -> str:
    player_id = _clean(
        _value(
            target,
            (
                "player_id",
                "target_player_id",
                "free_agent_player_id",
                "id",
            ),
            "",
        )
    )
    if player_id:
        if player_id.endswith(".0") and player_id[:-2].isdigit():
            player_id = player_id[:-2]
        return player_id

    player_name = _value(
        target,
        (
            "player_name",
            "target_player_name",
            "free_agent_name",
            "name",
        ),
        "",
    )
    return _clean(by_name.get(_name_key(player_name), ""))


def _target_fit_score(target: Any) -> float:
    direct = _finite(
        _value(
            target,
            (
                "fit_score",
                "target_score",
                "free_agent_fit_score",
                "strategic_fit_score",
                "score",
                "priority_score",
            ),
            None,
        )
    )
    if direct is not None:
        return round(_clamp(direct, 0.0, 100.0), 3)

    tier = _clean(
        _value(
            target,
            ("target_tier", "tier", "interest_tier", "priority", "market_tier"),
            "",
        )
    ).casefold()
    if any(token in tier for token in ("primary", "priority", "aggressive", "top")):
        return 88.0
    if any(token in tier for token in ("secondary", "strong", "medium")):
        return 76.0
    if any(token in tier for token in ("value", "depth", "watch")):
        return 65.0
    return 72.0


def _target_tier(target: Any) -> str:
    return _clean(
        _value(
            target,
            ("target_tier", "tier", "interest_tier", "priority", "market_tier"),
            "",
        )
    ) or "Target board"


def _canonical_direction_label(value: Any) -> str:
    if hasattr(value, "value"):
        value = getattr(value, "value")
    raw = _clean(value)
    if not raw:
        return ""
    normalized = raw.casefold().replace("_", " ").replace("-", " ")
    normalized = " ".join(normalized.split())
    if "championship" in normalized or "title" in normalized or normalized in {"all in", "all in contender"}:
        return "Championship Push"
    if "contend" in normalized or "win now" in normalized:
        return "Contend"
    if "retool" in normalized:
        return "Retool"
    if "develop" in normalized:
        return "Develop"
    if "rebuild" in normalized or "asset accumulation" in normalized:
        return "Rebuild"
    if normalized == "balanced":
        return "Balanced"
    return raw


def resolve_cpu_team_direction(team_plan: Any) -> str:
    """Resolve the current CPU Front Office strategy without collapsing live timeline labels."""
    # Current CPU Front Office V1.6.x stores the canonical strategy in timeline_label.
    # Older planners used direction/team_direction, so those remain supported fallbacks.
    value = _value(
        team_plan,
        (
            "timeline_label",
            "direction",
            "team_direction",
            "competitive_direction",
            "franchise_direction",
            "strategy_direction",
            "timeline",
        ),
        "",
    )
    label = _canonical_direction_label(value)
    if label:
        return label

    # behavior_label is not the primary source, but it safely recovers the five
    # current strategy families when a serialized plan omits timeline_label.
    behavior = _value(team_plan, ("behavior_label", "behavior", "behavior_summary"), "")
    label = _canonical_direction_label(behavior)
    return label or "Balanced"


def _team_direction(team_plan: Any) -> str:
    return resolve_cpu_team_direction(team_plan)


def _salary_posture(team_plan: Any) -> str:
    value = _value(
        team_plan,
        (
            "salary_posture",
            "financial_posture",
            "spending_posture",
            "cap_posture",
            "financial_summary",
        ),
        "",
    )
    return _clean(value) or "Balanced flexibility"


def _direction_multiplier(direction: str) -> float:
    text = _clean(direction).casefold()
    if "championship" in text or "title" in text:
        return 1.06
    if "contend" in text or "win now" in text or "win-now" in text:
        return 1.035
    if "retool" in text:
        return 1.00
    if "develop" in text:
        return 0.965
    if "rebuild" in text:
        return 0.93
    return 1.00


def _posture_multiplier(posture: str) -> float:
    text = _clean(posture).casefold()
    if any(token in text for token in ("high salary pressure", "tax pressure", "constrained", "tight")):
        return 0.92
    if any(token in text for token in ("flexible spending", "cap space", "aggressive spending", "room")):
        return 1.025
    if "balanced" in text:
        return 0.99
    return 1.00


def _offer_term(player: Any, direction: str) -> int:
    age = _finite(getattr(player, "age", None))
    age = 27.0 if age is None else age
    overall = _finite(getattr(player, "overall_rating", None))
    overall = 72.0 if overall is None else overall
    potential = _finite(getattr(player, "potential_rating", None))
    potential = overall if potential is None else potential

    if age >= 35.0:
        years = 1
    elif age >= 32.0:
        years = 2 if overall >= 80.0 else 1
    elif overall >= 88.0:
        years = 4
    elif overall >= 82.0:
        years = 3
    elif age <= 25.0 and potential >= 84.0:
        years = 3
    else:
        years = 2

    direction_text = _clean(direction).casefold()
    if age <= 25.0 and ("develop" in direction_text or "rebuild" in direction_text):
        years += 1
    return max(1, min(4, years))


@dataclass(frozen=True)
class CPUFreeAgencyTermResolution:
    requested_years: int
    years: int
    minimum_salary_floor: float
    maximum_initial_salary: float
    fallback_applied: bool


def resolve_supported_cpu_offer_term(
    player: Any,
    direction: str,
    *,
    state: Any | None = None,
) -> CPUFreeAgencyTermResolution | None:
    """Return the longest strategically preferred term that the locked salary layer can certify.

    Direction is allowed to lengthen a preferred contract term, but CPU offer generation
    must never discard an otherwise viable target merely because the V1.3 minimum-salary
    table cannot certify that longer horizon. Fallback only shortens the term and never
    invents salary scales or exceptions.
    """
    requested_years = _offer_term(player, direction)
    service, _ = (
        resolve_years_of_service_for_state(
            state,
            getattr(player, "player_id", ""),
        )
        if state is not None
        else resolve_years_of_service(player)
    )
    contract = getattr(player, "contract", None)
    prior_salary = _finite(getattr(contract, "salary", None)) if contract is not None else None
    maximum = (
        maximum_initial_salary_for_state(
            state,
            years_of_service=service,
            prior_salary=prior_salary,
        )
        if state is not None
        else maximum_initial_salary_for_offer(
            years_of_service=service,
            prior_salary=prior_salary,
        )
    )
    if maximum is None:
        return None

    for years in range(int(requested_years), 0, -1):
        minimum = (
            minimum_salary_floor_for_state(
                state,
                years_of_service=service,
                contract_years=years,
            )
            if state is not None
            else minimum_salary_floor_for_offer(
                years_of_service=service,
                contract_years=years,
            )
        )
        if minimum is None:
            continue
        return CPUFreeAgencyTermResolution(
            requested_years=int(requested_years),
            years=int(years),
            minimum_salary_floor=float(minimum),
            maximum_initial_salary=float(maximum),
            fallback_applied=int(years) != int(requested_years),
        )
    return None


def _budget_share(player: Any, fit_score: float) -> float:
    overall = _finite(getattr(player, "overall_rating", None))
    overall = 72.0 if overall is None else overall
    if overall >= 90.0:
        base = 0.98
    elif overall >= 86.0:
        base = 0.90
    elif overall >= 82.0:
        base = 0.76
    elif overall >= 78.0:
        base = 0.61
    elif overall >= 74.0:
        base = 0.47
    else:
        base = 0.34
    base += (fit_score - 70.0) * 0.003
    return _clamp(base, 0.28, 0.99)


def _round_salary(value: float) -> float:
    return round(max(value, 0.0) / 50_000.0) * 50_000.0


def _front_office_plan_from_runtime(state: Any, controlled_teams: Iterable[str]) -> Any:
    module = importlib.import_module(CPU_FRONT_OFFICE_MODULE)
    builder = getattr(module, CPU_FRONT_OFFICE_BUILDER, None)
    if not callable(builder):
        raise CPUFreeAgencyOfferGenerationError(
            f"{CPU_FRONT_OFFICE_MODULE} does not expose {CPU_FRONT_OFFICE_BUILDER}()."
        )
    controlled = tuple(sorted({_team(value) for value in controlled_teams if _team(value)}))
    return builder(state, controlled_teams=controlled)


def _preview_financial_route(preview: Any) -> tuple[str, str, str]:
    gate = getattr(preview, "financial_gate", None)
    payload = dict(getattr(gate, "payload", {}) or {})
    route = _clean(payload.get("financial_route") or payload.get("route")) or ROUTE_PURE_CAP
    rights = _clean(payload.get("rights_classification")) or "unknown"
    prior = _team(payload.get("prior_team"))
    return route, rights, prior


def build_cpu_free_agency_offer_board(
    state: Any,
    *,
    controlled_teams: Iterable[str] = (),
    eligible_teams: Iterable[str] | None = None,
    front_office_plan: Any | None = None,
    preview_builder: Callable[..., Any] | None = None,
    financial_environment_resolver: Callable[[Any], Any] | None = None,
    payroll_resolver: Callable[[Any, str], tuple[float, dict[str, Any]]] | None = None,
    market_reference_resolver: Callable[[Any, Any], tuple[float, float | None, float | None]] | None = None,
    max_targets_per_team: int = 5,
) -> CPUFreeAgencyOfferBoard:
    """Construct backend-PASS CPU bids from current front-office target boards.

    The locked pure-cap route remains first choice. If ordinary cap space cannot
    support the strategic bid, V1 may use only explicitly proven prior-team
    Bird-family rights or an exact one-year Minimum Salary Exception. No MLE,
    BAE, RFA matching, or sign-and-trade authority is inferred here.
    """
    if max_targets_per_team < 1:
        raise CPUFreeAgencyOfferGenerationError("max_targets_per_team must be positive.")

    season_label = _season(state)
    controlled = {_team(value) for value in controlled_teams if _team(value)}
    eligible = (
        None
        if eligible_teams is None
        else {_team(value) for value in eligible_teams if _team(value)}
    )
    plan = front_office_plan if front_office_plan is not None else _front_office_plan_from_runtime(state, controlled)
    team_plans = _extract_team_plans(plan)
    if not team_plans:
        raise CPUFreeAgencyOfferGenerationError("CPU front-office plan contains no team plans.")

    players, free_agent_name_lookup = _state_player_maps(state)
    free_ids = {_clean(value) for value in getattr(state, "free_agent_player_ids", ())}
    if not free_ids:
        return CPUFreeAgencyOfferBoard(
            version=CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
            scope=CPU_FREE_AGENCY_OFFER_GENERATION_SCOPE,
            season_label=season_label,
            cpu_team_count=sum(
                team not in controlled
                and (eligible is None or team in eligible)
                for team, _ in team_plans
            ),
            targeted_player_count=0,
            generated_offer_count=0,
            skipped_bid_count=0,
            offers=(),
            skipped=(),
            board_fingerprint=_fingerprint({"season": season_label, "offers": []}),
        )

    environment_fn = financial_environment_resolver or resolve_free_agency_financial_environment
    payroll_fn = payroll_resolver or team_guaranteed_payroll
    market_reference_fn = market_reference_resolver or market_salary_reference
    environment = environment_fn(state)
    if environment.status != "pass" or environment.salary_cap is None:
        raise CPUFreeAgencyOfferGenerationError(
            "CPU Offer Generation V1 requires an approved free-agency financial environment."
        )

    builder = preview_builder or build_rights_exception_free_agency_preview
    if preview_builder is None:
        # The speculative preview path below clones only the target player,
        # destination team and free-agent tuple. Prove the immutable source
        # universe is valid once per complete board, then let each hypothetical
        # signing validate only the touched surfaces. Actual winners still go
        # through the existing full durable validation path before commit.
        from simulation_league_state_v1 import validate_simulation_league_state

        validate_simulation_league_state(state)

    # The state is immutable for the lifetime of one offer-board build. Cache
    # repeated pure reads without reusing a board across committed signings.
    payroll_cache: dict[str, tuple[float, dict[str, Any]]] = {}
    service_cache: dict[str, tuple[int | None, str]] = {}
    rights_cache: dict[str, Any] = {}
    route_cache: dict[tuple[str, str, int], Any] = {}
    term_cache: dict[tuple[str, str], CPUFreeAgencyTermResolution | None] = {}

    def cached_payroll(team: str) -> tuple[float, dict[str, Any]]:
        resolved = _team(team)
        if resolved not in payroll_cache:
            payroll_cache[resolved] = payroll_fn(state, resolved)
        return payroll_cache[resolved]

    def cached_service(player_id: str) -> tuple[int | None, str]:
        pid = _clean(player_id)
        if pid not in service_cache:
            service_cache[pid] = resolve_years_of_service_for_state(state, pid)
        return service_cache[pid]

    def cached_rights(player_id: str) -> Any:
        pid = _clean(player_id)
        if pid not in rights_cache:
            rights_cache[pid] = resolve_free_agency_rights(state, pid)
        return rights_cache[pid]

    def cached_route(offer: FreeAgencyOffer) -> Any:
        key = (
            _clean(offer.player_id),
            _team(offer.team_abbreviation),
            int(offer.years),
        )
        if key not in route_cache:
            route_cache[key] = resolve_prior_team_exception_route(state, offer)
        return route_cache[key]

    def cached_term(
        player_id: str,
        player: Any,
        direction: str,
    ) -> CPUFreeAgencyTermResolution | None:
        key = (_clean(player_id), _clean(direction))
        if key not in term_cache:
            term_cache[key] = resolve_supported_cpu_offer_term(
                player,
                direction,
                state=state,
            )
        return term_cache[key]

    shared_source_fingerprint = (
        free_agency_state_fingerprint(state)
        if preview_builder is None
        else None
    )
    # A target's legal seed and final offer are frequently identical.  Reusing
    # that immutable preview avoids validating and fingerprinting the same
    # candidate state twice while preserving the exact board and decisions.
    preview_cache: dict[tuple[Any, ...], Any] = {}

    def build_preview(offer: FreeAgencyOffer) -> Any:
        if shared_source_fingerprint is None:
            return builder(state, offer)
        key = (
            _clean(offer.player_id),
            _team(offer.team_abbreviation),
            round(float(offer.annual_salary), 2),
            int(offer.years),
            bool(offer.guaranteed),
            _clean(offer.option_type).lower(),
        )
        cached = preview_cache.get(key)
        if cached is not None:
            return cached
        try:
            preview = builder(
                state,
                offer,
                _source_fingerprint=shared_source_fingerprint,
                _defer_candidate_fingerprint=True,
            )
        except TypeError as exc:
            # Custom/fixture builders may predate the internal speculative
            # fingerprint optimization. Preserve their public contract.
            if "_defer_candidate_fingerprint" not in str(exc):
                raise
            preview = builder(
                state,
                offer,
                _source_fingerprint=shared_source_fingerprint,
            )
        preview_cache[key] = preview
        return preview

    generated: list[CPUFreeAgencyGeneratedOffer] = []
    skipped: list[CPUFreeAgencySkippedBid] = []
    seen_pairs: set[tuple[str, str]] = set()

    for team, team_plan in team_plans:
        if team in controlled:
            continue
        if eligible is not None and team not in eligible:
            continue
        direction = _team_direction(team_plan)
        posture = _salary_posture(team_plan)
        targets = _extract_targets(team_plan)
        generated_for_team = 0
        for target in targets:
            if generated_for_team >= max_targets_per_team:
                break
            player_id = _target_player_id(target, free_agent_name_lookup)
            if not player_id or player_id not in free_ids:
                skipped.append(CPUFreeAgencySkippedBid(player_id, _clean(_value(target, ("player_name", "target_player_name", "name"), "")), team, "target_not_in_live_free_agent_pool"))
                continue
            pair = (team, player_id)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            player = players.get(player_id)
            if player is None:
                skipped.append(CPUFreeAgencySkippedBid(player_id, player_id, team, "player_record_missing"))
                continue

            player_name = _clean(getattr(player, "player_name", "")) or player_id
            fit_score = _target_fit_score(target)
            target_tier = _target_tier(target)
            roster_target = evaluate_roster_construction_target(
                state,
                player,
                team_plan,
                target,
                team_abbreviation=team,
                team_direction=direction,
                target_fit_score=fit_score,
            )
            if not roster_target.allowed:
                skipped.append(
                    CPUFreeAgencySkippedBid(
                        player_id,
                        player_name,
                        team,
                        f"roster_construction:{roster_target.reason_code}",
                        roster_construction_score=roster_target.score,
                        roster_construction_reason_code=roster_target.reason_code,
                        roster_construction_fingerprint=roster_target.fingerprint,
                    )
                )
                continue
            term_resolution = cached_term(
                player_id,
                player,
                direction,
            )
            if term_resolution is None:
                skipped.append(CPUFreeAgencySkippedBid(player_id, player_name, team, "salary_legality_bounds_unavailable"))
                continue

            requested_years = int(term_resolution.requested_years)
            strategic_years = int(term_resolution.years)
            strategic_minimum = float(term_resolution.minimum_salary_floor)
            generic_maximum = float(term_resolution.maximum_initial_salary)
            payroll, _ = cached_payroll(team)
            cap_space = float(environment.salary_cap) - float(payroll)

            rights = cached_rights(player_id)
            provisional_offer = FreeAgencyOffer(
                player_id=player_id,
                team_abbreviation=team,
                annual_salary=strategic_minimum,
                years=strategic_years,
                guaranteed=True,
                option_type="",
            )
            rights_route = cached_route(provisional_offer)
            rights_available = (
                rights_route.status == "pass"
                and rights_route.safe_exception_ceiling is not None
                and rights_route.minimum_salary_floor is not None
                and rights_route.min_contract_years <= strategic_years <= rights_route.max_contract_years
                and strategic_minimum <= float(rights_route.safe_exception_ceiling) + 0.01
            )

            service, _ = cached_service(player_id)
            minimum_exception_salary = minimum_salary_floor_for_state(
                state,
                years_of_service=service,
                contract_years=1,
            ) if service is not None else None

            # Build a legal seed preview for the market-value resolver. Prefer the
            # strategic term through pure cap/rights. Otherwise use a one-year
            # exact-minimum exception when verified service makes it provable.
            if cap_space + 0.01 >= strategic_minimum or rights_available:
                seed_years = strategic_years
                seed_salary = strategic_minimum
            elif minimum_exception_salary is not None:
                seed_years = 1
                seed_salary = float(minimum_exception_salary)
            else:
                skipped.append(CPUFreeAgencySkippedBid(player_id, player_name, team, "insufficient_pure_cap_and_no_proven_exception"))
                continue

            seed_offer = FreeAgencyOffer(
                player_id=player_id,
                team_abbreviation=team,
                annual_salary=float(seed_salary),
                years=int(seed_years),
                guaranteed=True,
                option_type="",
            )
            try:
                seed_preview = build_preview(seed_offer)
            except Exception as exc:
                skipped.append(CPUFreeAgencySkippedBid(player_id, player_name, team, f"minimum_preview_error:{type(exc).__name__}"))
                continue
            if _clean(getattr(seed_preview, "status", "")).lower() != "pass" or not bool(getattr(seed_preview, "can_commit", False)):
                skipped.append(CPUFreeAgencySkippedBid(player_id, player_name, team, "minimum_offer_does_not_clear_locked_backend"))
                continue

            try:
                reference, _, _ = market_reference_fn(player, seed_preview)
            except Exception:
                reference = float(seed_salary)

            fit_multiplier = 0.90 + 0.0020 * fit_score
            aggression = (
                fit_multiplier
                * _direction_multiplier(direction)
                * _posture_multiplier(posture)
                * roster_target.spending_multiplier
            )
            desired = float(reference) * aggression
            pure_cap_legal_ceiling = min(generic_maximum, max(cap_space, 0.0))
            pure_cap_can_fund_desired = (
                cap_space + 0.01 >= strategic_minimum
                and desired <= pure_cap_legal_ceiling + 0.01
            )

            final_years = strategic_years
            final_minimum = strategic_minimum
            final_maximum = generic_maximum

            if pure_cap_can_fund_desired:
                budget_ceiling = cap_space * _budget_share(player, fit_score)
                salary = min(desired, budget_ceiling, pure_cap_legal_ceiling)
                salary = max(strategic_minimum, salary)
                salary = _round_salary(salary)
                salary = min(salary, pure_cap_legal_ceiling)
                salary = max(salary, strategic_minimum)
            elif rights_available:
                final_maximum = min(generic_maximum, float(rights_route.safe_exception_ceiling))
                salary = _round_salary(min(max(desired, strategic_minimum), final_maximum))
                salary = min(max(salary, strategic_minimum), final_maximum)
            elif cap_space + 0.01 >= strategic_minimum:
                budget_ceiling = cap_space * _budget_share(player, fit_score)
                salary = min(desired, budget_ceiling, pure_cap_legal_ceiling)
                salary = max(strategic_minimum, salary)
                salary = _round_salary(salary)
                salary = min(salary, pure_cap_legal_ceiling)
                salary = max(salary, strategic_minimum)
            elif minimum_exception_salary is not None:
                final_years = 1
                final_minimum = float(minimum_exception_salary)
                final_maximum = float(minimum_exception_salary)
                salary = float(minimum_exception_salary)
            else:
                skipped.append(CPUFreeAgencySkippedBid(player_id, player_name, team, "insufficient_pure_cap_and_no_proven_exception"))
                continue

            final_offer = FreeAgencyOffer(
                player_id=player_id,
                team_abbreviation=team,
                annual_salary=round(float(salary), 2),
                years=int(final_years),
                guaranteed=True,
                option_type="",
            )
            try:
                preview = build_preview(final_offer)
            except Exception as exc:
                skipped.append(CPUFreeAgencySkippedBid(player_id, player_name, team, f"final_preview_error:{type(exc).__name__}"))
                continue
            if _clean(getattr(preview, "status", "")).lower() != "pass" or not bool(getattr(preview, "can_commit", False)):
                skipped.append(CPUFreeAgencySkippedBid(player_id, player_name, team, "generated_bid_does_not_clear_locked_backend"))
                continue

            normalized_offer = getattr(preview, "offer", final_offer)
            route, rights_classification, prior_team = _preview_financial_route(preview)

            minimum_targeting: CPUMinimumExceptionTargetingResult | None = None
            if route == ROUTE_MINIMUM:
                try:
                    minimum_targeting = evaluate_minimum_exception_targeting(
                        state,
                        preview,
                        target_fit_score=fit_score,
                        team_direction=direction,
                        strategic_requested_years=requested_years,
                    )
                except Exception as exc:
                    skipped.append(
                        CPUFreeAgencySkippedBid(
                            player_id,
                            player_name,
                            team,
                            f"minimum_exception_targeting_error:{type(exc).__name__}",
                        )
                    )
                    continue
                if not minimum_targeting.allowed:
                    skipped.append(
                        CPUFreeAgencySkippedBid(
                            player_id,
                            player_name,
                            team,
                            f"minimum_exception_targeting:{minimum_targeting.reason_code}",
                        )
                    )
                    continue

            roster_offer = evaluate_roster_construction_offer(
                state,
                player,
                preview,
                roster_target,
                market_salary_reference=float(reference),
                financial_route=route,
            )
            if not roster_offer.allowed:
                skipped.append(
                    CPUFreeAgencySkippedBid(
                        player_id,
                        player_name,
                        team,
                        f"roster_construction:{roster_offer.reason_code}",
                        roster_construction_score=roster_target.score,
                        roster_construction_reason_code=roster_offer.reason_code,
                        roster_construction_fingerprint=roster_offer.fingerprint,
                    )
                )
                continue

            offer_economics: CPUOfferEconomicIntelligenceResult
            try:
                offer_economics = evaluate_cpu_offer_economic_intelligence(
                    state,
                    player,
                    preview,
                    market_salary_reference=float(reference),
                    financial_route=route,
                    roster_construction_score=roster_target.score,
                    roster_projected_role=roster_target.projected_role,
                )
            except Exception as exc:
                skipped.append(
                    CPUFreeAgencySkippedBid(
                        player_id,
                        player_name,
                        team,
                        f"offer_economics_error:{type(exc).__name__}",
                        roster_construction_score=roster_target.score,
                        roster_construction_reason_code=roster_target.reason_code,
                        roster_construction_fingerprint=roster_target.fingerprint,
                    )
                )
                continue
            if not offer_economics.allowed:
                skipped.append(
                    CPUFreeAgencySkippedBid(
                        player_id,
                        player_name,
                        team,
                        f"offer_economics:{offer_economics.reason_code}",
                        roster_construction_score=roster_target.score,
                        roster_construction_reason_code=roster_target.reason_code,
                        roster_construction_fingerprint=roster_target.fingerprint,
                        offer_economic_score=offer_economics.economic_credibility_score,
                        offer_economic_reason_code=offer_economics.reason_code,
                        offer_economic_fingerprint=offer_economics.fingerprint,
                    )
                )
                continue

            # The route itself is authoritative. Minimum exception is exact-minimum
            # and can exceed ordinary cap room. Bird-family routes are restricted
            # to the explicitly proven prior team by the financial gate.
            exported_maximum = final_maximum
            if route == ROUTE_MINIMUM:
                exported_maximum = final_minimum
            offer_payload = {
                "version": CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
                "exception_routing": CPU_FREE_AGENCY_EXCEPTION_ROUTING_VERSION,
                "season": season_label,
                "player_id": player_id,
                "team": team,
                "salary": round(float(getattr(normalized_offer, "annual_salary", salary)), 2),
                "years": int(getattr(normalized_offer, "years", final_years)),
                "fit": round(fit_score, 3),
                "direction": direction,
                "posture": posture,
                "financial_route": route,
                "rights_classification": rights_classification,
                "prior_team": prior_team,
                "minimum_targeting_version": CPU_FREE_AGENCY_MINIMUM_EXCEPTION_TARGETING_VERSION,
                "minimum_targeting_status": getattr(minimum_targeting, "status", "not_applicable"),
                "minimum_targeting_reason": getattr(minimum_targeting, "reason_code", ""),
                "minimum_targeting_fingerprint": getattr(minimum_targeting, "fingerprint", ""),
                "roster_construction_version": CPU_FREE_AGENCY_ROSTER_CONSTRUCTION_VERSION,
                "roster_construction_score": roster_target.score,
                "roster_construction_reason": roster_target.reason_code,
                "roster_target_fingerprint": roster_target.fingerprint,
                "roster_offer_reason": roster_offer.reason_code,
                "roster_offer_fingerprint": roster_offer.fingerprint,
                "offer_economic_version": CPU_FREE_AGENCY_OFFER_ECONOMIC_INTELLIGENCE_VERSION,
                "offer_economic_status": offer_economics.status,
                "offer_economic_reason": offer_economics.reason_code,
                "offer_economic_score": offer_economics.economic_credibility_score,
                "offer_economic_fingerprint": offer_economics.fingerprint,
                "source_fingerprint": _clean(getattr(preview, "source_fingerprint", "")),
            }
            generated.append(
                CPUFreeAgencyGeneratedOffer(
                    version=CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
                    season_label=season_label,
                    player_id=player_id,
                    player_name=player_name,
                    team_abbreviation=team,
                    team_direction=direction,
                    salary_posture=posture,
                    target_fit_score=fit_score,
                    target_tier=target_tier,
                    market_salary_reference=round(float(reference), 2),
                    annual_salary=round(float(getattr(normalized_offer, "annual_salary", salary)), 2),
                    years=int(getattr(normalized_offer, "years", final_years)),
                    guaranteed=bool(getattr(normalized_offer, "guaranteed", True)),
                    option_type=_clean(getattr(normalized_offer, "option_type", "")),
                    minimum_salary_floor=round(float(final_minimum), 2),
                    maximum_initial_salary=round(float(exported_maximum), 2),
                    cap_space_before=round(float(cap_space), 2),
                    aggression_multiplier=round(float(aggression), 6),
                    preview=preview,
                    offer_fingerprint=_fingerprint(offer_payload),
                    strategic_requested_years=requested_years,
                    term_fallback_applied=int(getattr(normalized_offer, "years", final_years)) != requested_years,
                    financial_route=route,
                    rights_classification=rights_classification,
                    prior_team=prior_team,
                    minimum_targeting_status=getattr(minimum_targeting, "status", "not_applicable"),
                    minimum_targeting_tier=(
                        "accepted_minimum" if getattr(minimum_targeting, "reason_code", "") == "player_accepts_exact_minimum"
                        else "credible_pitch" if minimum_targeting is not None
                        else ""
                    ),
                    minimum_targeting_score=round(float(getattr(minimum_targeting, "credibility_score", 0.0)), 3),
                    minimum_targeting_reason_code=_clean(getattr(minimum_targeting, "reason_code", "")),
                    minimum_targeting_interest=(
                        round(float(minimum_targeting.interest_score), 3) if minimum_targeting is not None else None
                    ),
                    minimum_targeting_gap=(
                        round(float(minimum_targeting.gap_to_acceptance), 3) if minimum_targeting is not None else None
                    ),
                    minimum_targeting_market_ratio=(
                        round(float(minimum_targeting.salary_to_market_ratio), 6) if minimum_targeting is not None else None
                    ),
                    minimum_targeting_fingerprint=_clean(getattr(minimum_targeting, "fingerprint", "")),
                    roster_construction_score=roster_target.score,
                    roster_construction_tier=roster_target.tier,
                    roster_construction_reason_code=roster_target.reason_code,
                    roster_position_family=roster_target.position_family,
                    roster_projected_role=roster_target.projected_role,
                    roster_positional_need_score=roster_target.positional_need_score,
                    roster_role_upgrade_score=roster_target.role_upgrade_score,
                    roster_timeline_fit_score=roster_target.timeline_fit_score,
                    roster_upside_fit_score=roster_target.upside_fit_score,
                    roster_redundancy_risk=roster_target.redundancy_risk,
                    roster_prospect_blocking_risk=roster_target.prospect_blocking_risk,
                    roster_marginal_overall_vs_best=roster_target.marginal_overall_vs_best,
                    roster_marginal_overall_vs_second=roster_target.marginal_overall_vs_second,
                    roster_spending_multiplier=roster_target.spending_multiplier,
                    roster_target_fingerprint=roster_target.fingerprint,
                    roster_offer_status=roster_offer.status,
                    roster_offer_reason_code=roster_offer.reason_code,
                    roster_offer_economic_score=roster_offer.economic_pursuit_score,
                    roster_offer_salary_to_market_ratio=roster_offer.salary_to_market_ratio,
                    roster_offer_interest=roster_offer.player_interest,
                    roster_offer_gap=roster_offer.gap_to_acceptance,
                    roster_offer_fingerprint=roster_offer.fingerprint,
                    offer_economic_status=offer_economics.status,
                    offer_economic_tier=offer_economics.tier,
                    offer_economic_reason_code=offer_economics.reason_code,
                    offer_economic_credibility_score=offer_economics.economic_credibility_score,
                    offer_economic_minimum_market_ratio=offer_economics.minimum_credible_market_ratio,
                    offer_economic_salary_to_market_ratio=offer_economics.salary_to_market_ratio,
                    offer_economic_interest=offer_economics.player_interest,
                    offer_economic_gap=offer_economics.gap_to_acceptance,
                    offer_economic_discount_support_score=offer_economics.discount_support_score,
                    offer_economic_fingerprint=offer_economics.fingerprint,
                )
            )
            generated_for_team += 1

    generated.sort(key=lambda row: (row.player_id, -row.target_fit_score, row.team_abbreviation))
    skipped.sort(key=lambda row: (row.player_id, row.team_abbreviation, row.reason))
    targeted_players = {row.player_id for row in generated}
    payload = {
        "version": CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
        "exception_routing": CPU_FREE_AGENCY_EXCEPTION_ROUTING_VERSION,
        "season": season_label,
        "controlled_teams": sorted(controlled),
        "eligible_teams": (sorted(eligible) if eligible is not None else None),
        "offers": [
            {
                "player_id": row.player_id,
                "team": row.team_abbreviation,
                "salary": row.annual_salary,
                "years": row.years,
                "fit": row.target_fit_score,
                "route": row.financial_route,
                "rights": row.rights_classification,
                "prior_team": row.prior_team,
                "minimum_targeting_status": row.minimum_targeting_status,
                "minimum_targeting_reason": row.minimum_targeting_reason_code,
                "minimum_targeting_score": row.minimum_targeting_score,
                "minimum_targeting_fingerprint": row.minimum_targeting_fingerprint,
                "roster_construction_score": row.roster_construction_score,
                "roster_construction_reason": row.roster_construction_reason_code,
                "roster_target_fingerprint": row.roster_target_fingerprint,
                "roster_offer_reason": row.roster_offer_reason_code,
                "roster_offer_fingerprint": row.roster_offer_fingerprint,
                "offer_economic_status": row.offer_economic_status,
                "offer_economic_reason": row.offer_economic_reason_code,
                "offer_economic_score": row.offer_economic_credibility_score,
                "offer_economic_fingerprint": row.offer_economic_fingerprint,
                "fingerprint": row.offer_fingerprint,
            }
            for row in generated
        ],
        "skipped": [
            {
                "player": row.player_id,
                "team": row.team_abbreviation,
                "reason": row.reason,
                "roster_score": row.roster_construction_score,
                "roster_reason": row.roster_construction_reason_code,
                "roster_fingerprint": row.roster_construction_fingerprint,
                "offer_economic_score": row.offer_economic_score,
                "offer_economic_reason": row.offer_economic_reason_code,
                "offer_economic_fingerprint": row.offer_economic_fingerprint,
            }
            for row in skipped
        ],
    }
    return CPUFreeAgencyOfferBoard(
        version=CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
        scope=CPU_FREE_AGENCY_OFFER_GENERATION_SCOPE,
        season_label=season_label,
        cpu_team_count=sum(
            team not in controlled
            and (eligible is None or team in eligible)
            for team, _ in team_plans
        ),
        targeted_player_count=len(targeted_players),
        generated_offer_count=len(generated),
        skipped_bid_count=len(skipped),
        offers=tuple(generated),
        skipped=tuple(skipped),
        board_fingerprint=_fingerprint(payload),
    )

def build_cpu_competing_markets(
    state: Any,
    board: CPUFreeAgencyOfferBoard,
) -> tuple[CPUFreeAgencyPlayerMarket, ...]:
    groups: dict[str, list[CPUFreeAgencyGeneratedOffer]] = {}
    for offer in board.offers:
        groups.setdefault(offer.player_id, []).append(offer)

    markets: list[CPUFreeAgencyPlayerMarket] = []
    for player_id, offers in sorted(groups.items()):
        previews = [row.preview for row in offers]
        if not previews:
            continue
        market = evaluate_competing_offer_market(state, previews)
        player_name = offers[0].player_name if offers else player_id
        markets.append(
            CPUFreeAgencyPlayerMarket(
                version=CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
                player_id=player_id,
                player_name=player_name,
                cpu_offer_count=len(offers),
                market=market,
            )
        )
    return tuple(markets)


def generation_contract_report() -> dict[str, Any]:
    return {
        "version": CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
        "scope": CPU_FREE_AGENCY_OFFER_GENERATION_SCOPE,
        "cpu_front_office_module": CPU_FRONT_OFFICE_MODULE,
        "cpu_front_office_builder": CPU_FRONT_OFFICE_BUILDER,
        "financial_bridge_version": FREE_AGENCY_FINANCIAL_BRIDGE_VERSION,
        "salary_legality_version": FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION,
        "player_decision_version": FREE_AGENCY_PLAYER_DECISION_VERSION,
        "competing_market_version": FREE_AGENCY_COMPETING_MARKET_VERSION,
        "direction_adapter_version": CPU_FREE_AGENCY_DIRECTION_ADAPTER_VERSION,
        "term_feasibility_version": CPU_FREE_AGENCY_TERM_FEASIBILITY_VERSION,
        "exception_routing_version": CPU_FREE_AGENCY_EXCEPTION_ROUTING_VERSION,
        "minimum_targeting_adapter_version": CPU_FREE_AGENCY_MINIMUM_TARGETING_ADAPTER_VERSION,
        "minimum_exception_targeting_version": CPU_FREE_AGENCY_MINIMUM_EXCEPTION_TARGETING_VERSION,
        "roster_construction_adapter_version": CPU_FREE_AGENCY_ROSTER_CONSTRUCTION_ADAPTER_VERSION,
        "roster_construction_version": CPU_FREE_AGENCY_ROSTER_CONSTRUCTION_VERSION,
        "offer_economic_adapter_version": CPU_FREE_AGENCY_OFFER_ECONOMIC_ADAPTER_VERSION,
        "offer_economic_intelligence_version": CPU_FREE_AGENCY_OFFER_ECONOMIC_INTELLIGENCE_VERSION,
        "speculative_candidate_fingerprint_deferred": True,
        "speculative_source_full_validation_once_per_board": True,
        "speculative_candidate_touched_surface_validation": True,
        "durable_winner_full_league_validation_preserved": True,
        "rights_exceptions_version": FREE_AGENCY_RIGHTS_EXCEPTIONS_VERSION,
        "preview_reuse_version": CPU_FREE_AGENCY_PREVIEW_REUSE_VERSION,
        "board_cache_version": CPU_FREE_AGENCY_BOARD_CACHE_VERSION,
        "board_local_payroll_cache": True,
        "board_local_service_cache": True,
        "board_local_rights_cache": True,
        "board_local_exception_route_cache": True,
        "board_local_term_resolution_cache": True,
        "board_cache_changes_offer_order_or_legality": False,
        "identical_seed_final_previews_reused": True,
        "autonomous_commit_enabled": False,
        "pure_cap_space_only": False,
        "pure_cap_space_remains_first_choice": True,
        "minimum_salary_exception_one_year_enabled": True,
        "minimum_exception_targeting_intelligence_enabled": True,
        "minimum_exception_targeting_filters_legally_valid_noncredible_bids": True,
        "target_scan_replaces_filtered_bids_with_lower_board_targets": True,
        "eligible_team_filter_supported": True,
        "offer_economic_intelligence_enabled": True,
        "offer_economic_filter_preserves_player_counters": True,
        "offer_economic_filter_uses_contextual_market_ratio_floor": True,
        "prior_team_rights_routes_enabled_with_explicit_evidence": True,
        "max_contract_term_years": 4,
        "guaranteed_contracts_only": True,
    }
