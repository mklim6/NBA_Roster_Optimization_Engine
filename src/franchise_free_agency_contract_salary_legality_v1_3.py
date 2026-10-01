from __future__ import annotations

import math
import json
import re
from functools import lru_cache
from pathlib import Path
from dataclasses import asdict, dataclass
from typing import Any, Callable

from franchise_free_agency_transaction_v1 import (
    FreeAgencyFinancialGateResult,
    FreeAgencyOffer,
    FreeAgencyTransactionPreview,
    build_free_agency_preview,
)
from franchise_free_agency_financial_bridge_v1_2 import (
    FREE_AGENCY_CANONICAL_ANCHOR_SEASON,
    FREE_AGENCY_FINANCIAL_BRIDGE_VERSION,
    evaluate_live_free_agency_financial_gate,
    resolve_free_agency_financial_environment,
)
from franchise_free_agency_prior_salary_v1 import (
    resolve_prior_salary,
)
from franchise_offseason_market_season_v1 import (
    modeled_future_market_enabled,
    resolve_offseason_market_season,
)


FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION = (
    "franchise-free-agency-contract-salary-legality-v1.5-service-evidence-2026-09-24"
)
FREE_AGENCY_CONTRACT_SALARY_SOURCE = (
    "2023_nba_nbpa_cba_article_ii_sections_6_7_exhibit_c_article_ix_section_1"
)
ANCHOR_SEASON = "2026-27"
ANCHOR_SALARY_CAP = 164_961_000.0

# Exact 2026-27 Minimum Annual Salary Scale. Rows are years of service at
# contract signing (10 means 10+). Columns are contract years 1 through 5.
# V1.3 uses at most the first four columns for auto-release because a generic
# free-agent contract cannot be auto-proven for five seasons without prior-team
# qualifying-veteran/Bird-right evidence.
MINIMUM_SALARY_SCALE_2026_27: dict[int, tuple[float, ...]] = {
    0: (1_357_763, 0, 0, 0, 0),
    1: (2_185_116, 2_294_370, 0, 0, 0),
    2: (2_449_421, 2_571_895, 2_694_363, 0, 0),
    3: (2_537_526, 2_664_401, 2_791_275, 2_918_152, 0),
    4: (2_625_627, 2_756_912, 2_888_193, 3_019_474, 3_150_758),
    5: (2_845_883, 2_988_178, 3_130_471, 3_272_766, 3_415_061),
    6: (3_066_143, 3_219_451, 3_372_754, 3_526_061, 3_679_369),
    7: (3_286_399, 3_450_720, 3_615_040, 3_779_359, 3_943_681),
    8: (3_506_659, 3_681_991, 3_857_326, 4_032_662, 4_207_996),
    9: (3_524_115, 3_700_320, 3_876_527, 4_052_733, 4_228_939),
    10: (3_876_529, 4_070_355, 4_264_183, 4_458_009, 4_651_836),
}

MAX_SALARY_PCT_BY_SERVICE_BUCKET = {
    "0_6": 0.25,
    "7_9": 0.30,
    "10_plus": 0.35,
}
SERVICE_ATTRIBUTE_CANDIDATES = (
    "years_of_service",
    "service_years",
    "nba_years_of_service",
    "season_exp",
    "years_service",
)


@dataclass(frozen=True)
class FreeAgencyContractSalaryLegalityResult:
    version: str
    status: str
    reason: str
    season_label: str
    player_id: str
    years_of_service: int | None
    service_source: str
    annual_salary: float
    contract_years: int
    minimum_salary_floor: float | None
    maximum_initial_salary: float | None
    prior_salary: float | None
    service_bucket: str
    term_status: str
    option_status: str
    exact_service_evidence: bool
    higher_max_exception_inferred: bool = False
    prior_team_rights_inferred: bool = False


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _finite_nonnegative(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _finite_positive(value: Any) -> float | None:
    number = _finite_nonnegative(value)
    return number if number is not None and number > 0 else None


def _state_season(state: Any) -> str:
    return _clean(getattr(getattr(state, "settings", None), "season_label", ""))


def _player(state: Any, player_id: str) -> Any | None:
    return getattr(state, "players", {}).get(_clean(player_id))


def resolve_years_of_service(player: Any) -> tuple[int | None, str]:
    """Resolve explicit service evidence only. Never infer service from age."""
    if player is None:
        return None, "player_unavailable"
    for attribute in SERVICE_ATTRIBUTE_CANDIDATES:
        raw = getattr(player, attribute, None)
        if raw is None or isinstance(raw, bool):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or value < 0 or not value.is_integer():
            continue
        return int(value), attribute
    return None, "not_available_no_age_inference"



V2_SERVICE_EVIDENCE_VERSION = (
    "franchise-v2-free-agency-service-evidence-v1-2026-09-24"
)
V2_SERVICE_EVIDENCE_SOURCE = (
    "player_ratings_2026_27_v2.career_seasons_plus_market_season_offset"
)
V2_SERVICE_EVIDENCE_ANCHOR_START_YEAR = 2026
V2_SERVICE_EVIDENCE_RATINGS_PATH = (
    Path(__file__).resolve().parents[1]
    / "app_data"
    / "player_ratings_2026_27_v2.json"
)


def _v2_market_start_year(state: Any) -> int | None:
    season = str(resolve_offseason_market_season(state) or "").strip()
    if len(season) < 4 or not season[:4].isdigit():
        return None
    return int(season[:4])


@lru_cache(maxsize=1)
def _v2_baseline_career_seasons_by_player() -> dict[str, int]:
    path = V2_SERVICE_EVIDENCE_RATINGS_PATH
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    rows = payload.get("players_by_id", {})
    if not isinstance(rows, dict):
        return {}

    result: dict[str, int] = {}
    for raw_player_id, row in rows.items():
        if not isinstance(row, dict):
            continue
        raw = row.get("career_seasons")
        if raw is None or isinstance(raw, bool):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or value < 0 or not value.is_integer():
            continue
        player_id = str(raw_player_id or "").strip()
        if player_id:
            result[player_id] = int(value)
    return result


def resolve_years_of_service_for_state(
    state: Any,
    player_id: Any,
) -> tuple[int | None, str]:
    # Resolve explicit service evidence without age inference.
    pid = str(player_id or "").strip()
    player = getattr(state, "players", {}).get(pid)
    direct, direct_source = resolve_years_of_service(player)
    if direct is not None:
        return direct, direct_source

    market_start = _v2_market_start_year(state)
    if market_start is None:
        return None, "market_season_unavailable"

    generated = re.fullmatch(r"GEN-(\d{4})-\d+", pid, flags=re.IGNORECASE)
    if generated:
        draft_year = int(generated.group(1))
        if market_start < draft_year:
            return None, "generated_player_before_draft_year"
        return (
            max(0, market_start - draft_year),
            "generated_player_id_draft_year_progression",
        )

    baseline = _v2_baseline_career_seasons_by_player().get(pid)
    if baseline is None:
        return None, "no_explicit_service_evidence"

    offset = market_start - V2_SERVICE_EVIDENCE_ANCHOR_START_YEAR
    if offset < 0:
        return None, "market_precedes_service_evidence_anchor"
    return (
        baseline + offset,
        V2_SERVICE_EVIDENCE_SOURCE,
    )

def _service_row_key(years_of_service: int) -> int:
    return min(max(int(years_of_service), 0), 10)


def minimum_salary_floor_for_offer(
    *,
    years_of_service: int | None,
    contract_years: int,
) -> float | None:
    if contract_years < 1 or contract_years > 5:
        return None
    # Unknown service uses the 10+ row, which is the highest floor in every
    # contract-year column and is therefore safe for every service bucket.
    row = MINIMUM_SALARY_SCALE_2026_27[
        10 if years_of_service is None else _service_row_key(years_of_service)
    ]
    values = [float(row[index]) for index in range(contract_years)]
    if any(value <= 0 for value in values):
        return None
    # ContractState stores a flat annual salary, so that flat number must clear
    # every applicable annual minimum in the term.
    return max(values)


def minimum_salary_floor_for_state(
    state: Any,
    *,
    years_of_service: int | None,
    contract_years: int,
) -> float | None:
    anchor = minimum_salary_floor_for_offer(
        years_of_service=years_of_service,
        contract_years=contract_years,
    )
    if anchor is None:
        return None
    market = resolve_offseason_market_season(state)
    if market == ANCHOR_SEASON:
        return float(anchor)
    if not modeled_future_market_enabled(state):
        return None
    environment = resolve_free_agency_financial_environment(state)
    if environment.status != "pass" or environment.salary_cap is None:
        return None
    ratio = float(environment.salary_cap) / float(ANCHOR_SALARY_CAP)
    return round(float(anchor) * ratio, 2)


def maximum_initial_salary_for_state(
    state: Any,
    *,
    years_of_service: int | None,
    prior_salary: float | None,
) -> float | None:
    market = resolve_offseason_market_season(state)
    if market == ANCHOR_SEASON:
        cap = ANCHOR_SALARY_CAP
    else:
        if not modeled_future_market_enabled(state):
            return None
        environment = resolve_free_agency_financial_environment(state)
        if environment.status != "pass" or environment.salary_cap is None:
            return None
        cap = float(environment.salary_cap)
    return maximum_initial_salary_for_offer(
        years_of_service=years_of_service,
        prior_salary=prior_salary,
        salary_cap=cap,
    )


def service_bucket(years_of_service: int | None) -> str:
    if years_of_service is None:
        return "unknown_conservative_0_6_max"
    if years_of_service >= 10:
        return "10_plus"
    if years_of_service >= 7:
        return "7_9"
    return "0_6"


def maximum_initial_salary_for_offer(
    *,
    years_of_service: int | None,
    prior_salary: float | None,
    salary_cap: float = ANCHOR_SALARY_CAP,
) -> float:
    bucket = service_bucket(years_of_service)
    if years_of_service is None:
        pct = MAX_SALARY_PCT_BY_SERVICE_BUCKET["0_6"]
        # Unknown service cannot use 105% prior salary to expand the universally
        # safe ceiling because the applicable max bucket itself is unresolved.
        return float(salary_cap) * pct
    pct = MAX_SALARY_PCT_BY_SERVICE_BUCKET[bucket]
    cap_max = float(salary_cap) * pct
    prior = _finite_positive(prior_salary)
    return max(cap_max, prior * 1.05 if prior is not None else 0.0)


def _result_payload(result: FreeAgencyContractSalaryLegalityResult) -> dict[str, Any]:
    payload = asdict(result)
    payload["minimum_scale_source"] = FREE_AGENCY_CONTRACT_SALARY_SOURCE
    payload["anchor_salary_cap"] = ANCHOR_SALARY_CAP
    payload["generic_auto_release_max_term_years"] = 4
    payload["five_year_prior_team_rights_inferred"] = False
    payload["age_used_to_infer_service"] = False
    return payload


def evaluate_contract_salary_legality(
    state: Any,
    offer: FreeAgencyOffer,
) -> FreeAgencyContractSalaryLegalityResult:
    live_season = _state_season(state)
    season = resolve_offseason_market_season(state)
    environment = resolve_free_agency_financial_environment(state)
    salary = _finite_positive(getattr(offer, "annual_salary", None))
    years = int(getattr(offer, "years", 0) or 0)
    option_type = _clean(getattr(offer, "option_type", "")).lower()
    player = _player(state, getattr(offer, "player_id", ""))
    service, service_source = resolve_years_of_service_for_state(
        state,
        getattr(offer, "player_id", ""),
    )
    contract = getattr(player, "contract", None) if player is not None else None
    prior_salary = _finite_positive(getattr(contract, "salary", None))
    if prior_salary is None:
        prior_salary = _finite_positive(
            resolve_prior_salary(
                state,
                getattr(offer, "player_id", ""),
            )
        )

    minimum = minimum_salary_floor_for_state(
        state,
        years_of_service=service,
        contract_years=years,
    )
    maximum = maximum_initial_salary_for_state(
        state,
        years_of_service=service,
        prior_salary=prior_salary,
    ) if 1 <= years <= 5 else None

    base = dict(
        version=FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION,
        season_label=season,
        player_id=_clean(getattr(offer, "player_id", "")),
        years_of_service=service,
        service_source=service_source,
        annual_salary=float(salary or 0.0),
        contract_years=years,
        minimum_salary_floor=minimum,
        maximum_initial_salary=maximum,
        prior_salary=prior_salary,
        service_bucket=service_bucket(service),
        term_status="supported" if 1 <= years <= 4 else "manual_review",
        option_status=(
            "supported"
            if not option_type or years >= 2
            else "manual_review"
        ),
        exact_service_evidence=service is not None,
    )

    if season != ANCHOR_SEASON and not modeled_future_market_enabled(state):
        return FreeAgencyContractSalaryLegalityResult(
            status="manual_review",
            reason=(
                "Future-season salary legality requires the durable completed-season "
                "market marker. No modeled future market is active on this state."
            ),
            **base,
        )
    if season != ANCHOR_SEASON and (
        environment.status != "pass"
        or environment.salary_cap is None
        or minimum is None
        or maximum is None
    ):
        return FreeAgencyContractSalaryLegalityResult(
            status="manual_review",
            reason=(
                "Modeled future salary-scale evidence could not be resolved safely."
            ),
            **base,
        )
    if salary is None:
        return FreeAgencyContractSalaryLegalityResult(
            status="blocked",
            reason="Offer annual salary must be positive and finite.",
            **base,
        )
    if years < 1 or years > 5:
        return FreeAgencyContractSalaryLegalityResult(
            status="blocked",
            reason="Offer term is outside the supported 1-5 year structural range.",
            **base,
        )
    if years == 5:
        return FreeAgencyContractSalaryLegalityResult(
            status="manual_review",
            reason=(
                "A generic free-agent contract is auto-released for at most four "
                "seasons. Five seasons requires proven Prior Team qualifying-veteran "
                "rights, which V1.3 does not infer."
            ),
            **base,
        )
    if option_type and years < 2:
        return FreeAgencyContractSalaryLegalityResult(
            status="manual_review",
            reason=(
                "A one-season offer carrying a team/player option is not auto-released "
                "by V1.3 because the option-year structure is not represented safely."
            ),
            **base,
        )
    if minimum is None or maximum is None:
        return FreeAgencyContractSalaryLegalityResult(
            status="manual_review",
            reason="Minimum/maximum salary evidence could not be resolved.",
            **base,
        )

    if salary < minimum - 0.01:
        if service is None:
            return FreeAgencyContractSalaryLegalityResult(
                status="manual_review",
                reason=(
                    f"Offer is below the universal-safe ${minimum:,.0f} minimum for "
                    "unknown service time. It may be legal for a lower-service player, "
                    "but V1.3 will not infer years of service from age."
                ),
                **base,
            )
        return FreeAgencyContractSalaryLegalityResult(
            status="blocked",
            reason=(
                f"Offer is below the applicable ${minimum:,.0f} minimum salary floor "
                f"for the verified service record ({service} year(s))."
            ),
            **base,
        )

    if salary > maximum + 0.01:
        return FreeAgencyContractSalaryLegalityResult(
            status="manual_review",
            reason=(
                f"Offer exceeds the auto-releasable ${maximum:,.0f} initial maximum. "
                "V1.3 does not infer designated/higher-max or other special eligibility."
            ),
            **base,
        )

    return FreeAgencyContractSalaryLegalityResult(
        status="pass",
        reason=(
            f"Offer clears the V1.3 2026-27 salary floor/ceiling and term gate "
            f"(${minimum:,.0f} minimum, ${maximum:,.0f} auto-releasable maximum)."
        ),
        **base,
    )


def evaluate_contract_legal_financial_gate(
    state: Any,
    offer: FreeAgencyOffer,
) -> FreeAgencyFinancialGateResult:
    """Compose V1.2 cap-space legality with V1.3 contract salary legality."""
    v12 = evaluate_live_free_agency_financial_gate(state, offer)
    contract = evaluate_contract_salary_legality(state, offer)
    payload = dict(v12.payload or {})
    payload.update({
        "financial_bridge_version": FREE_AGENCY_FINANCIAL_BRIDGE_VERSION,
        "contract_salary_legality_version": FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION,
        "contract_salary_legality": _result_payload(contract),
    })

    # V1.2 always retains veto priority. V1.3 may only narrow a PASS route.
    if v12.status != "pass":
        return FreeAgencyFinancialGateResult(
            status=v12.status,
            reason=v12.reason,
            payload=payload,
        )
    if contract.status != "pass":
        return FreeAgencyFinancialGateResult(
            status=contract.status,
            reason=contract.reason,
            payload=payload,
        )
    return FreeAgencyFinancialGateResult(
        status="pass",
        reason=(
            f"{v12.reason} Contract salary legality also passes V1.3."
        ),
        payload=payload,
    )


def contract_legal_free_agency_gate() -> Callable[[Any, FreeAgencyOffer], FreeAgencyFinancialGateResult]:
    return evaluate_contract_legal_financial_gate


def build_contract_legal_free_agency_preview(
    state: Any,
    offer: FreeAgencyOffer,
    *,
    state_validator: Callable[[Any], Any] | None = None,
    max_roster_size: int = 18,
) -> FreeAgencyTransactionPreview:
    return build_free_agency_preview(
        state,
        offer,
        financial_gate=evaluate_contract_legal_financial_gate,
        state_validator=state_validator,
        max_roster_size=max_roster_size,
    )
