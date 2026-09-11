from __future__ import annotations

import importlib
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable

from franchise_free_agency_transaction_v1 import (
    FreeAgencyFinancialGateResult,
    FreeAgencyOffer,
    FreeAgencyTransactionPreview,
    build_free_agency_preview,
)
from franchise_free_agency_transaction_v1_1 import (
    FREE_AGENCY_CAP_SPACE_GATE_VERSION,
    FreeAgencyCapSpaceGateConfig,
    commit_free_agency_preview_durably,
    evaluate_cap_space_gate,
)
from franchise_financial_cba_bridge_v1 import build_future_thresholds
from franchise_offseason_market_season_v1 import (
    modeled_future_market_enabled,
    resolve_offseason_market_season,
)


FREE_AGENCY_FINANCIAL_BRIDGE_VERSION = (
    "franchise-free-agency-financial-bridge-v1.3-modeled-future-market-2026-08-18"
)
FREE_AGENCY_CANONICAL_ANCHOR_SEASON = "2026-27"
FREE_AGENCY_CANONICAL_RUNTIME_MODULE = "freeform_trade_machine_engine_v3"
FREE_AGENCY_CANONICAL_SOURCE = (
    "canonical_2026_27_trade_machine_cba_rules"
)
UNSUPPORTED_EXCEPTION_MECHANISMS = (
    "bird_rights",
    "early_bird_rights",
    "non_bird_rights",
    "mid_level_exception",
    "taxpayer_mid_level_exception",
    "room_mid_level_exception",
    "bi_annual_exception",
    "minimum_salary_exception",
    "restricted_free_agency",
    "qualifying_offer",
    "sign_and_trade",
)


@dataclass(frozen=True)
class FreeAgencyFinancialEnvironment:
    version: str
    status: str
    season_label: str
    source: str
    source_module: str
    source_trade_date: str
    salary_cap: float | None
    first_apron: float | None
    second_apron: float | None
    reason: str
    exact_anchor_season: bool
    pure_cap_space_release_supported: bool
    exceptions_inferred: bool = False


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _finite_positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _state_season(state: Any) -> str:
    settings = getattr(state, "settings", None)
    return _clean_text(getattr(settings, "season_label", ""))


@lru_cache(maxsize=1)
def _canonical_anchor_payload() -> dict[str, Any]:
    """Load the canonical 2026-27 Trade Machine rule environment lazily.

    V1.2 intentionally uses only public runtime functions and exact rules that
    already power the canonical Trade Machine. It does not reinterpret trade
    salary-matching rules as free-agency exception rights.
    """
    module = importlib.import_module(FREE_AGENCY_CANONICAL_RUNTIME_MODULE)
    load_runtime_data = getattr(module, "load_runtime_data", None)
    rule_number = getattr(module, "rule_number", None)
    if not callable(load_runtime_data) or not callable(rule_number):
        raise RuntimeError(
            "Canonical Trade Machine runtime does not expose load_runtime_data "
            "and rule_number."
        )

    runtime = load_runtime_data()
    salary_cap = _finite_positive(rule_number(runtime, "salary_cap"))
    if salary_cap is None:
        raise RuntimeError("Canonical 2026-27 salary cap is unavailable.")

    optional: dict[str, float | None] = {}
    for key in ("first_apron", "second_apron"):
        try:
            optional[key] = _finite_positive(rule_number(runtime, key))
        except Exception:
            optional[key] = None

    return {
        "salary_cap": salary_cap,
        "first_apron": optional["first_apron"],
        "second_apron": optional["second_apron"],
        "trade_date": _clean_text(getattr(module, "TRADE_DATE", "")),
        "module": FREE_AGENCY_CANONICAL_RUNTIME_MODULE,
    }


@lru_cache(maxsize=32)
def _modeled_future_threshold_payload(season_label: str) -> dict[str, Any]:
    module = importlib.import_module(FREE_AGENCY_CANONICAL_RUNTIME_MODULE)
    load_runtime_data = getattr(module, "load_runtime_data", None)
    if not callable(load_runtime_data):
        raise RuntimeError("Canonical Trade Machine runtime does not expose load_runtime_data.")
    runtime = load_runtime_data()
    thresholds = build_future_thresholds(runtime, season_label)
    return {
        "salary_cap": float(thresholds.salary_cap),
        "first_apron": float(thresholds.first_apron),
        "second_apron": float(thresholds.second_apron),
        "source": str(thresholds.source),
        "annual_cap_growth": float(thresholds.annual_cap_growth),
        "years_after_anchor": int(thresholds.years_after_anchor),
    }


def clear_financial_environment_cache() -> None:
    _canonical_anchor_payload.cache_clear()
    _modeled_future_threshold_payload.cache_clear()


def resolve_free_agency_financial_environment(
    state: Any,
) -> FreeAgencyFinancialEnvironment:
    """Resolve the economic environment for the active Franchise FA market.

    The opening 2026-27 offseason remains exact/canonical. Once a completed
    postseason contract closeout is durably applied, the offseason market belongs
    to the following season even though the live season label intentionally stays
    on the completed source season until Draft/Open Next Season archives it. Future
    thresholds are therefore modeled from the existing verified 2026-27 financial
    bridge and carry explicit modeled provenance. No exception rights are inferred.
    """
    live_season = _state_season(state)
    season = resolve_offseason_market_season(state)
    if not season:
        return FreeAgencyFinancialEnvironment(
            version=FREE_AGENCY_FINANCIAL_BRIDGE_VERSION,
            status="manual_review",
            season_label="",
            source="missing_franchise_season",
            source_module="",
            source_trade_date="",
            salary_cap=None,
            first_apron=None,
            second_apron=None,
            reason="Franchise season label is unavailable.",
            exact_anchor_season=False,
            pure_cap_space_release_supported=False,
        )

    if season != FREE_AGENCY_CANONICAL_ANCHOR_SEASON:
        if not modeled_future_market_enabled(state):
            return FreeAgencyFinancialEnvironment(
                version=FREE_AGENCY_FINANCIAL_BRIDGE_VERSION,
                status="manual_review",
                season_label=season,
                source="future_market_not_bound_to_completed_season_closeout",
                source_module="franchise_financial_cba_bridge_v1",
                source_trade_date="",
                salary_cap=None,
                first_apron=None,
                second_apron=None,
                reason=(
                    "Future-season modeled Free Agency is released only from a durable "
                    "completed-season closeout. The live state has no matching market marker."
                ),
                exact_anchor_season=False,
                pure_cap_space_release_supported=False,
            )
        try:
            payload = _modeled_future_threshold_payload(season)
        except Exception as exc:
            return FreeAgencyFinancialEnvironment(
                version=FREE_AGENCY_FINANCIAL_BRIDGE_VERSION,
                status="manual_review",
                season_label=season,
                source="modeled_future_threshold_runtime_unavailable",
                source_module="franchise_financial_cba_bridge_v1",
                source_trade_date="",
                salary_cap=None,
                first_apron=None,
                second_apron=None,
                reason=f"Modeled future financial thresholds could not load: {exc}",
                exact_anchor_season=False,
                pure_cap_space_release_supported=False,
            )
        return FreeAgencyFinancialEnvironment(
            version=FREE_AGENCY_FINANCIAL_BRIDGE_VERSION,
            status="pass",
            season_label=season,
            source=(
                "modeled_future_fa_thresholds_from_verified_2026_27_anchor;"
                + payload["source"]
            ),
            source_module="franchise_financial_cba_bridge_v1",
            source_trade_date="",
            salary_cap=payload["salary_cap"],
            first_apron=payload["first_apron"],
            second_apron=payload["second_apron"],
            reason=(
                f"{season} Free Agency uses modeled thresholds scaled from the verified "
                "2026-27 anchor. This is simulation-native future economics, not a claim "
                "of an already-published future NBA cap."
            ),
            exact_anchor_season=False,
            pure_cap_space_release_supported=True,
        )

    try:
        payload = _canonical_anchor_payload()
    except Exception as exc:
        return FreeAgencyFinancialEnvironment(
            version=FREE_AGENCY_FINANCIAL_BRIDGE_VERSION,
            status="manual_review",
            season_label=season,
            source="canonical_anchor_runtime_unavailable",
            source_module=FREE_AGENCY_CANONICAL_RUNTIME_MODULE,
            source_trade_date="",
            salary_cap=None,
            first_apron=None,
            second_apron=None,
            reason=f"Canonical 2026-27 financial runtime could not load: {exc}",
            exact_anchor_season=True,
            pure_cap_space_release_supported=False,
        )

    return FreeAgencyFinancialEnvironment(
        version=FREE_AGENCY_FINANCIAL_BRIDGE_VERSION,
        status="pass",
        season_label=season,
        source=FREE_AGENCY_CANONICAL_SOURCE,
        source_module=payload["module"],
        source_trade_date=payload["trade_date"],
        salary_cap=payload["salary_cap"],
        first_apron=payload["first_apron"],
        second_apron=payload["second_apron"],
        reason=(
            "Exact anchor-season salary-cap threshold loaded from the canonical "
            "2026-27 Trade Machine CBA rules."
        ),
        exact_anchor_season=True,
        pure_cap_space_release_supported=True,
    )


def evaluate_live_free_agency_financial_gate(
    state: Any,
    offer: FreeAgencyOffer,
) -> FreeAgencyFinancialGateResult:
    environment = resolve_free_agency_financial_environment(state)
    base_payload = {
        "bridge_version": FREE_AGENCY_FINANCIAL_BRIDGE_VERSION,
        "environment_status": environment.status,
        "environment_source": environment.source,
        "environment_source_module": environment.source_module,
        "environment_trade_date": environment.source_trade_date,
        "season_label": environment.season_label,
        "live_state_season_label": _state_season(state),
        "economic_market_season_label": environment.season_label,
        "exact_anchor_season": environment.exact_anchor_season,
        "pure_cap_space_release_supported": (
            environment.pure_cap_space_release_supported
        ),
        "exceptions_inferred": False,
        "unsupported_exception_mechanisms": list(
            UNSUPPORTED_EXCEPTION_MECHANISMS
        ),
    }

    if (
        environment.status != "pass"
        or not environment.pure_cap_space_release_supported
        or environment.salary_cap is None
    ):
        return FreeAgencyFinancialGateResult(
            status="manual_review",
            reason=environment.reason,
            payload={
                **base_payload,
                "salary_cap": environment.salary_cap,
                "first_apron": environment.first_apron,
                "second_apron": environment.second_apron,
            },
        )

    result = evaluate_cap_space_gate(
        state,
        offer,
        config=FreeAgencyCapSpaceGateConfig(
            salary_cap=environment.salary_cap,
            # Keep the lower-level stale-state identity guard exact. The wrapper
            # separately carries the economic market season and modeled provenance.
            season_label=_state_season(state),
            source=environment.source,
            allow_zero_salary_rows=False,
        ),
    )
    payload = dict(result.payload or {})
    payload.update(base_payload)
    payload["first_apron"] = environment.first_apron
    payload["second_apron"] = environment.second_apron
    payload["cap_space_gate_version"] = FREE_AGENCY_CAP_SPACE_GATE_VERSION
    return FreeAgencyFinancialGateResult(
        status=result.status,
        reason=result.reason,
        payload=payload,
    )


def live_free_agency_financial_gate() -> Callable[
    [Any, FreeAgencyOffer], FreeAgencyFinancialGateResult
]:
    return evaluate_live_free_agency_financial_gate


def build_live_financial_free_agency_preview(
    state: Any,
    offer: FreeAgencyOffer,
    *,
    state_validator: Callable[[Any], Any] | None = None,
    max_roster_size: int = 18,
) -> FreeAgencyTransactionPreview:
    return build_free_agency_preview(
        state,
        offer,
        financial_gate=evaluate_live_free_agency_financial_gate,
        state_validator=state_validator,
        max_roster_size=max_roster_size,
    )


def commit_live_financial_free_agency_preview_durably(
    preview: FreeAgencyTransactionPreview,
    *,
    preferences: dict[str, Any] | None = None,
    state_validator: Callable[[Any], Any] | None = None,
    max_roster_size: int = 18,
    recovery_directory: str | Any | None = None,
):
    """Use the V1.1 durable transaction engine with the live V1.2 gate."""
    return commit_free_agency_preview_durably(
        preview,
        financial_gate=evaluate_live_free_agency_financial_gate,
        preferences=preferences,
        state_validator=state_validator,
        max_roster_size=max_roster_size,
        recovery_directory=recovery_directory,
    )
