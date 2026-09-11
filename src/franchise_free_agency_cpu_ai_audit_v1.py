from __future__ import annotations

import copy
import csv
import hashlib
import importlib
import inspect
import json
import math
import shutil
import tempfile
import zipfile
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from franchise_free_agency_cpu_offer_generation_v1 import (
    CPU_FREE_AGENCY_DIRECTION_ADAPTER_VERSION,
    CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
    CPU_FREE_AGENCY_TERM_FEASIBILITY_VERSION,
    CPU_FREE_AGENCY_EXCEPTION_ROUTING_VERSION,
    CPU_FREE_AGENCY_MINIMUM_TARGETING_ADAPTER_VERSION,
    CPU_FREE_AGENCY_ROSTER_CONSTRUCTION_ADAPTER_VERSION,
    CPU_FREE_AGENCY_OFFER_ECONOMIC_ADAPTER_VERSION,
    build_cpu_competing_markets,
    build_cpu_free_agency_offer_board,
    resolve_cpu_team_direction,
)
from franchise_free_agency_live_signing_v1 import (
    FREE_AGENCY_LIVE_SIGNING_VERSION,
    controlled_teams_from_durable_checkpoint,
    trade_state_fingerprint,
)
from franchise_free_agency_negotiation_rounds_v1 import (
    FREE_AGENCY_NEGOTIATION_ROUNDS_VERSION,
    MAX_FREE_AGENCY_NEGOTIATION_ROUNDS,
)
from franchise_free_agency_persistent_calendar_v1 import (
    FREE_AGENCY_CALENDAR_ATTR,
    FREE_AGENCY_PERSISTENT_CALENDAR_VERSION,
    free_agency_calendar_snapshot,
    persistent_calendar_fingerprint,
)
from franchise_free_agency_interest_meter_v1 import (
    FREE_AGENCY_INTEREST_METER_VERSION,
    interest_band,
)
from franchise_free_agency_player_decision_v1 import (
    FREE_AGENCY_PLAYER_DECISION_VERSION,
    evaluate_free_agent_offer_decision,
)
from franchise_free_agency_contract_salary_legality_v1_3 import resolve_years_of_service
from franchise_free_agency_cpu_minimum_exception_targeting_v1 import CPU_FREE_AGENCY_MINIMUM_EXCEPTION_TARGETING_VERSION
from franchise_free_agency_cpu_roster_construction_v1 import CPU_FREE_AGENCY_ROSTER_CONSTRUCTION_VERSION
from franchise_free_agency_cpu_offer_economic_intelligence_v1 import CPU_FREE_AGENCY_OFFER_ECONOMIC_INTELLIGENCE_VERSION
from franchise_free_agency_transaction_v1 import free_agency_state_fingerprint
from franchise_free_agency_rights_exceptions_v1 import FREE_AGENCY_RIGHTS_EXCEPTIONS_VERSION

FREE_AGENCY_CPU_AI_AUDIT_VERSION = (
    "franchise-free-agency-cpu-ai-audit-extension-v1-2026-08-14"
)
FREE_AGENCY_CPU_AI_AUDIT_SCHEMA_VERSION = "free-agency-cpu-ai-audit-schema-v1"
FREE_AGENCY_CPU_AI_AUDIT_OFFER_QUALITY_VERSION = (
    "franchise-free-agency-cpu-ai-audit-offer-quality-v1.1-2026-08-14"
)
FREE_AGENCY_CPU_AI_AUDIT_OFFER_QUALITY_SCHEMA_VERSION = (
    "free-agency-cpu-ai-offer-quality-schema-v1.1"
)
FREE_AGENCY_CPU_AI_AUDIT_ROSTER_CONSTRUCTION_VERSION = (
    "franchise-free-agency-cpu-ai-audit-roster-construction-v1-2026-08-14"
)
FREE_AGENCY_CPU_AI_AUDIT_ROSTER_CONSTRUCTION_SCHEMA_VERSION = (
    "free-agency-cpu-ai-roster-construction-schema-v1"
)
FREE_AGENCY_CPU_AI_AUDIT_OFFER_ECONOMIC_VERSION = (
    "franchise-free-agency-cpu-ai-audit-offer-economics-v1-2026-08-14"
)
FREE_AGENCY_CPU_AI_AUDIT_OFFER_ECONOMIC_SCHEMA_VERSION = (
    "free-agency-cpu-ai-offer-economics-schema-v1"
)
FREE_AGENCY_CPU_AI_AUDIT_SCOPE = (
    "read_only_checkpoint_and_isolated_offseason_cpu_fa_behavior_export"
)

CPU_FRONT_OFFICE_MODULE = "franchise_cpu_front_office_v1"
CPU_FRONT_OFFICE_BUILDER = "build_league_front_office_plan"

REQUIRED_FILES = (
    "audit_manifest.csv",
    "behavioral_checks.csv",
    "watch_metrics.csv",
    "cpu_front_office_team_plans.csv",
    "cpu_free_agent_targets.csv",
    "cpu_free_agency_offers.csv",
    "cpu_free_agency_skipped_bids.csv",
    "cpu_free_agency_player_markets.csv",
    "cpu_free_agency_market_evaluations.csv",
    "cpu_free_agency_offer_quality.csv",
    "cpu_free_agency_player_profiles.csv",
    "cpu_free_agency_market_quality.csv",
    "cpu_free_agency_quality_flags.csv",
    "cpu_free_agency_roster_construction.csv",
    "cpu_free_agency_roster_construction_flags.csv",
    "cpu_free_agency_offer_economics.csv",
    "cpu_free_agency_offer_economic_flags.csv",
    "persistent_free_agency_markets.csv",
    "persistent_free_agency_round_history.csv",
    "persistent_free_agency_cpu_actions.csv",
    "persistent_free_agency_evaluations.csv",
    "persistent_free_agency_day_history.csv",
    "free_agency_transactions.csv",
    "trade_state_contract_overrides.csv",
    "audit_summary.json",
)


class FreeAgencyCPUAuditError(RuntimeError):
    """Raised when the read-only CPU/free-agency audit cannot be built safely."""


@dataclass(frozen=True)
class FreeAgencyCPUAuditBuildResult:
    version: str
    schema_version: str
    season_label: str
    live_phase: str
    analysis_phase: str
    output_zip: str
    zip_sha256: str
    checkpoint_sha256: str
    state_fingerprint: str
    trade_fingerprint: str
    calendar_fingerprint: str
    controlled_teams: tuple[str, ...]
    strict_pass: bool
    failed_checks: tuple[str, ...]
    row_counts: dict[str, int]


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _phase(state: Any) -> str:
    raw = getattr(state, "phase", "")
    return _clean(getattr(raw, "value", raw)).lower()


def _season(state: Any) -> str:
    return _clean(getattr(getattr(state, "settings", None), "season_label", ""))


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sha256(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "__dict__"):
        return {
            str(key): _json_safe(item)
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }
    return str(value)


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
    if value is None or isinstance(value, (str, bytes)):
        return ()
    if isinstance(value, Mapping):
        return tuple(value.values())
    try:
        return tuple(value)
    except TypeError:
        return ()


def _extract_team_plans(front_office_plan: Any) -> tuple[tuple[str, Any], ...]:
    candidate = _value(
        front_office_plan,
        ("team_plans", "plans_by_team", "team_plans_by_team", "plans", "teams", "by_team"),
        front_office_plan,
    )
    rows: list[tuple[str, Any]] = []
    if isinstance(candidate, Mapping):
        for key, plan in candidate.items():
            team = _team(_value(plan, ("team_abbreviation", "team", "team_code", "abbreviation"), key))
            if team:
                rows.append((team, plan))
    else:
        for plan in _sequence(candidate):
            team = _team(_value(plan, ("team_abbreviation", "team", "team_code", "abbreviation"), ""))
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


def _isolated_offseason_state(state: Any) -> Any:
    candidate = copy.deepcopy(state)
    if _phase(candidate) == "offseason":
        return candidate
    try:
        from franchise_free_agency_ui_v1 import isolated_offseason_preview_state
        return isolated_offseason_preview_state(candidate)
    except Exception:
        pass
    try:
        from simulation_league_state_v1 import LeaguePhase
        candidate.phase = LeaguePhase.OFFSEASON
    except Exception:
        candidate.phase = "offseason"
    return candidate


def _checkpoint_contract() -> tuple[Any, Path]:
    module = importlib.import_module("simulation_franchise_checkpoint_v1")
    load_fn = getattr(module, "load_franchise_checkpoint", None)
    path = Path(getattr(module, "DEFAULT_CHECKPOINT_PATH", "outputs/runtime/franchise_mode_checkpoint_v1.pkl.gz"))
    if not callable(load_fn):
        raise FreeAgencyCPUAuditError("load_franchise_checkpoint() is unavailable.")
    required = [
        parameter
        for parameter in inspect.signature(load_fn).parameters.values()
        if parameter.default is inspect._empty
        and parameter.kind not in {parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD}
    ]
    if required:
        raise FreeAgencyCPUAuditError(
            "The durable checkpoint loader unexpectedly requires arguments."
        )
    return load_fn, path


def _front_office_plan(state: Any, controlled_teams: Iterable[str]) -> Any:
    module = importlib.import_module(CPU_FRONT_OFFICE_MODULE)
    builder = getattr(module, CPU_FRONT_OFFICE_BUILDER, None)
    if not callable(builder):
        raise FreeAgencyCPUAuditError(
            f"{CPU_FRONT_OFFICE_MODULE}.{CPU_FRONT_OFFICE_BUILDER}() is unavailable."
        )
    controlled = tuple(sorted({_team(value) for value in controlled_teams if _team(value)}))
    return builder(state, controlled_teams=controlled)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    if not fieldnames:
        fieldnames = ["empty"]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        if rows:
            for row in rows:
                normalized = {}
                for key in fieldnames:
                    value = row.get(key)
                    if isinstance(value, (Mapping, list, tuple, set)):
                        normalized[key] = json.dumps(_json_safe(value), sort_keys=True, separators=(",", ":"))
                    else:
                        normalized[key] = value
                writer.writerow(normalized)


def _raw_calendar_payload(state: Any) -> dict[str, Any]:
    raw = getattr(state, FREE_AGENCY_CALENDAR_ATTR, None)
    return copy.deepcopy(dict(raw)) if isinstance(raw, Mapping) else {}


def _front_office_exports(front_office_plan: Any, controlled: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    team_rows: list[dict[str, Any]] = []
    target_rows: list[dict[str, Any]] = []
    for team, plan in _extract_team_plans(front_office_plan):
        targets = _extract_targets(plan)
        direction = resolve_cpu_team_direction(plan)
        posture = _clean(_value(plan, ("salary_posture", "financial_posture", "cap_posture", "spending_posture"), ""))
        team_rows.append({
            "team_abbreviation": team,
            "is_user_controlled": team in controlled,
            "team_direction": direction,
            "salary_posture": posture,
            "free_agent_target_count": len(targets),
            "plan_json": _json_safe(plan),
        })
        for rank, target in enumerate(targets, start=1):
            target_rows.append({
                "team_abbreviation": team,
                "is_user_controlled": team in controlled,
                "target_rank": rank,
                "player_id": _clean(_value(target, ("player_id", "target_player_id", "free_agent_player_id", "id"), "")),
                "player_name": _clean(_value(target, ("player_name", "target_player_name", "name"), "")),
                "fit_score": _finite(_value(target, ("fit_score", "target_fit_score", "score", "free_agent_fit_score"), None)),
                "target_tier": _clean(_value(target, ("target_tier", "tier", "priority_tier", "label"), "")),
                "team_direction": direction,
                "salary_posture": posture,
                "target_json": _json_safe(target),
            })
    return team_rows, target_rows


def _offer_exports(board: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    offers: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in getattr(board, "offers", ()):
        preview = getattr(row, "preview", None)
        offers.append({
            "player_id": _clean(getattr(row, "player_id", "")),
            "player_name": _clean(getattr(row, "player_name", "")),
            "team_abbreviation": _team(getattr(row, "team_abbreviation", "")),
            "team_direction": _clean(getattr(row, "team_direction", "")),
            "salary_posture": _clean(getattr(row, "salary_posture", "")),
            "target_fit_score": _finite(getattr(row, "target_fit_score", None)),
            "target_tier": _clean(getattr(row, "target_tier", "")),
            "market_salary_reference": _finite(getattr(row, "market_salary_reference", None)),
            "annual_salary": _finite(getattr(row, "annual_salary", None)),
            "years": getattr(row, "years", None),
            "strategic_requested_years": getattr(row, "strategic_requested_years", getattr(row, "years", None)),
            "term_fallback_applied": bool(getattr(row, "term_fallback_applied", False)),
            "financial_route": _clean(getattr(row, "financial_route", "pure_cap_space_only")),
            "rights_classification": _clean(getattr(row, "rights_classification", "unknown")),
            "prior_team": _team(getattr(row, "prior_team", "")),
            "minimum_targeting_status": _clean(getattr(row, "minimum_targeting_status", "not_applicable")),
            "minimum_targeting_tier": _clean(getattr(row, "minimum_targeting_tier", "")),
            "minimum_targeting_score": _finite(getattr(row, "minimum_targeting_score", None)),
            "minimum_targeting_reason_code": _clean(getattr(row, "minimum_targeting_reason_code", "")),
            "minimum_targeting_interest": _finite(getattr(row, "minimum_targeting_interest", None)),
            "minimum_targeting_gap": _finite(getattr(row, "minimum_targeting_gap", None)),
            "minimum_targeting_market_ratio": _finite(getattr(row, "minimum_targeting_market_ratio", None)),
            "minimum_targeting_fingerprint": _clean(getattr(row, "minimum_targeting_fingerprint", "")),
            "roster_construction_score": _finite(getattr(row, "roster_construction_score", None)),
            "roster_construction_tier": _clean(getattr(row, "roster_construction_tier", "")),
            "roster_construction_reason_code": _clean(getattr(row, "roster_construction_reason_code", "")),
            "roster_position_family": _clean(getattr(row, "roster_position_family", "")),
            "roster_projected_role": _clean(getattr(row, "roster_projected_role", "")),
            "roster_positional_need_score": _finite(getattr(row, "roster_positional_need_score", None)),
            "roster_role_upgrade_score": _finite(getattr(row, "roster_role_upgrade_score", None)),
            "roster_timeline_fit_score": _finite(getattr(row, "roster_timeline_fit_score", None)),
            "roster_upside_fit_score": _finite(getattr(row, "roster_upside_fit_score", None)),
            "roster_redundancy_risk": _finite(getattr(row, "roster_redundancy_risk", None)),
            "roster_prospect_blocking_risk": _finite(getattr(row, "roster_prospect_blocking_risk", None)),
            "roster_marginal_overall_vs_best": _finite(getattr(row, "roster_marginal_overall_vs_best", None)),
            "roster_marginal_overall_vs_second": _finite(getattr(row, "roster_marginal_overall_vs_second", None)),
            "roster_spending_multiplier": _finite(getattr(row, "roster_spending_multiplier", None)),
            "roster_target_fingerprint": _clean(getattr(row, "roster_target_fingerprint", "")),
            "roster_offer_status": _clean(getattr(row, "roster_offer_status", "")),
            "roster_offer_reason_code": _clean(getattr(row, "roster_offer_reason_code", "")),
            "roster_offer_economic_score": _finite(getattr(row, "roster_offer_economic_score", None)),
            "roster_offer_salary_to_market_ratio": _finite(getattr(row, "roster_offer_salary_to_market_ratio", None)),
            "roster_offer_interest": _finite(getattr(row, "roster_offer_interest", None)),
            "roster_offer_gap": _finite(getattr(row, "roster_offer_gap", None)),
            "roster_offer_fingerprint": _clean(getattr(row, "roster_offer_fingerprint", "")),
            "offer_economic_status": _clean(getattr(row, "offer_economic_status", "")),
            "offer_economic_tier": _clean(getattr(row, "offer_economic_tier", "")),
            "offer_economic_reason_code": _clean(getattr(row, "offer_economic_reason_code", "")),
            "offer_economic_credibility_score": _finite(getattr(row, "offer_economic_credibility_score", None)),
            "offer_economic_minimum_market_ratio": _finite(getattr(row, "offer_economic_minimum_market_ratio", None)),
            "offer_economic_salary_to_market_ratio": _finite(getattr(row, "offer_economic_salary_to_market_ratio", None)),
            "offer_economic_interest": _finite(getattr(row, "offer_economic_interest", None)),
            "offer_economic_gap": _finite(getattr(row, "offer_economic_gap", None)),
            "offer_economic_discount_support_score": _finite(getattr(row, "offer_economic_discount_support_score", None)),
            "offer_economic_fingerprint": _clean(getattr(row, "offer_economic_fingerprint", "")),
            "guaranteed": bool(getattr(row, "guaranteed", False)),
            "option_type": _clean(getattr(row, "option_type", "")),
            "minimum_salary_floor": _finite(getattr(row, "minimum_salary_floor", None)),
            "maximum_initial_salary": _finite(getattr(row, "maximum_initial_salary", None)),
            "cap_space_before": _finite(getattr(row, "cap_space_before", None)),
            "aggression_multiplier": _finite(getattr(row, "aggression_multiplier", None)),
            "offer_fingerprint": _clean(getattr(row, "offer_fingerprint", "")),
            "backend_status": _clean(getattr(preview, "status", "")),
            "backend_can_commit": bool(getattr(preview, "can_commit", False)),
            "preview_source_fingerprint": _clean(getattr(preview, "source_fingerprint", "")),
        })
    for row in getattr(board, "skipped", ()):
        skipped.append({
            "player_id": _clean(getattr(row, "player_id", "")),
            "player_name": _clean(getattr(row, "player_name", "")),
            "team_abbreviation": _team(getattr(row, "team_abbreviation", "")),
            "reason": _clean(getattr(row, "reason", "")),
            "roster_construction_score": _finite(getattr(row, "roster_construction_score", None)),
            "roster_construction_reason_code": _clean(getattr(row, "roster_construction_reason_code", "")),
            "roster_construction_fingerprint": _clean(getattr(row, "roster_construction_fingerprint", "")),
            "offer_economic_score": _finite(getattr(row, "offer_economic_score", None)),
            "offer_economic_reason_code": _clean(getattr(row, "offer_economic_reason_code", "")),
            "offer_economic_fingerprint": _clean(getattr(row, "offer_economic_fingerprint", "")),
        })
    return offers, skipped


def _market_exports(markets: Iterable[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    market_rows: list[dict[str, Any]] = []
    evaluation_rows: list[dict[str, Any]] = []
    for wrapper in markets:
        market = getattr(wrapper, "market", wrapper)
        player_id = _clean(getattr(wrapper, "player_id", getattr(market, "player_id", "")))
        player_name = _clean(getattr(wrapper, "player_name", getattr(market, "player_name", "")))
        market_rows.append({
            "player_id": player_id,
            "player_name": player_name,
            "cpu_offer_count": int(getattr(wrapper, "cpu_offer_count", getattr(market, "offer_count", 0)) or 0),
            "market_status": _clean(getattr(market, "status", "")),
            "accepted_offer_count": int(getattr(market, "accepted_offer_count", 0) or 0),
            "winner_team_abbreviation": _team(getattr(market, "winner_team_abbreviation", "")) or None,
            "winner_utility_score": _finite(getattr(market, "winner_utility_score", None)),
            "runner_up_team_abbreviation": _team(getattr(market, "runner_up_team_abbreviation", "")) or None,
            "runner_up_utility_score": _finite(getattr(market, "runner_up_utility_score", None)),
            "winning_margin": _finite(getattr(market, "winning_margin", None)),
            "best_counter_team_abbreviation": _team(getattr(market, "best_counter_team_abbreviation", "")) or None,
            "best_counter_salary": _finite(getattr(market, "best_counter_salary", None)),
            "market_fingerprint": _clean(getattr(market, "market_fingerprint", "")),
        })
        for evaluation in getattr(market, "evaluations", ()):
            evaluation_rows.append({
                "player_id": player_id,
                "player_name": player_name,
                "rank": int(getattr(evaluation, "rank", 0) or 0),
                "team_abbreviation": _team(getattr(evaluation, "team_abbreviation", "")),
                "offer_id": _clean(getattr(evaluation, "offer_id", "")),
                "annual_salary": _finite(getattr(evaluation, "annual_salary", None)),
                "years": getattr(evaluation, "years", None),
                "guaranteed": bool(getattr(evaluation, "guaranteed", False)),
                "option_type": _clean(getattr(evaluation, "option_type", "")),
                "utility_score": _finite(getattr(evaluation, "utility_score", None)),
                "acceptance_threshold": _finite(getattr(evaluation, "acceptance_threshold", None)),
                "player_decision_status": _clean(getattr(evaluation, "player_decision_status", "")),
                "accepted": bool(getattr(evaluation, "accepted", False)),
                "utility_gap_to_winner": _finite(getattr(evaluation, "utility_gap_to_winner", None)),
                "decision_fingerprint": _clean(getattr(evaluation, "decision_fingerprint", "")),
                "source_fingerprint": _clean(getattr(evaluation, "source_fingerprint", "")),
                "market_fingerprint": _clean(getattr(market, "market_fingerprint", "")),
            })
    return market_rows, evaluation_rows



def _quality_fingerprint(rows: Sequence[Mapping[str, Any]]) -> str:
    payload = [dict(row) for row in rows]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _percentile(values: Sequence[float], p: float) -> float | None:
    clean = sorted(float(v) for v in values if math.isfinite(float(v)))
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    pos = max(0.0, min(1.0, float(p))) * (len(clean) - 1)
    low = int(math.floor(pos))
    high = int(math.ceil(pos))
    if low == high:
        return clean[low]
    share = pos - low
    return clean[low] * (1.0 - share) + clean[high] * share


def _offer_quality_exports(state: Any, board: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    players = dict(getattr(state, "players", {}) or {})
    quality_rows: list[dict[str, Any]] = []
    profile_by_player: dict[str, dict[str, Any]] = {}
    for generated in getattr(board, "offers", ()):
        player_id = _clean(getattr(generated, "player_id", ""))
        player = players.get(player_id)
        preview = getattr(generated, "preview", None)
        route = _clean(getattr(generated, "financial_route", "pure_cap_space_only")) or "pure_cap_space_only"
        base = {
            "player_id": player_id,
            "player_name": _clean(getattr(generated, "player_name", getattr(player, "player_name", ""))),
            "team_abbreviation": _team(getattr(generated, "team_abbreviation", "")),
            "team_direction": _clean(getattr(generated, "team_direction", "")),
            "target_fit_score": _finite(getattr(generated, "target_fit_score", None)),
            "target_tier": _clean(getattr(generated, "target_tier", "")),
            "financial_route": route,
            "rights_classification": _clean(getattr(generated, "rights_classification", "unknown")),
            "prior_team": _team(getattr(generated, "prior_team", "")),
            "minimum_targeting_status": _clean(getattr(generated, "minimum_targeting_status", "not_applicable")),
            "minimum_targeting_tier": _clean(getattr(generated, "minimum_targeting_tier", "")),
            "minimum_targeting_score": _finite(getattr(generated, "minimum_targeting_score", None)),
            "minimum_targeting_reason_code": _clean(getattr(generated, "minimum_targeting_reason_code", "")),
            "minimum_targeting_interest": _finite(getattr(generated, "minimum_targeting_interest", None)),
            "minimum_targeting_gap": _finite(getattr(generated, "minimum_targeting_gap", None)),
            "minimum_targeting_market_ratio": _finite(getattr(generated, "minimum_targeting_market_ratio", None)),
            "roster_construction_score": _finite(getattr(generated, "roster_construction_score", None)),
            "roster_construction_tier": _clean(getattr(generated, "roster_construction_tier", "")),
            "roster_construction_reason_code": _clean(getattr(generated, "roster_construction_reason_code", "")),
            "offer_economic_status": _clean(getattr(generated, "offer_economic_status", "")),
            "offer_economic_tier": _clean(getattr(generated, "offer_economic_tier", "")),
            "offer_economic_reason_code": _clean(getattr(generated, "offer_economic_reason_code", "")),
            "offer_economic_credibility_score": _finite(getattr(generated, "offer_economic_credibility_score", None)),
            "offer_economic_minimum_market_ratio": _finite(getattr(generated, "offer_economic_minimum_market_ratio", None)),
            "offer_economic_discount_support_score": _finite(getattr(generated, "offer_economic_discount_support_score", None)),
            "offer_economic_fingerprint": _clean(getattr(generated, "offer_economic_fingerprint", "")),
            "roster_position_family": _clean(getattr(generated, "roster_position_family", "")),
            "roster_projected_role": _clean(getattr(generated, "roster_projected_role", "")),
            "roster_positional_need_score": _finite(getattr(generated, "roster_positional_need_score", None)),
            "roster_role_upgrade_score": _finite(getattr(generated, "roster_role_upgrade_score", None)),
            "roster_timeline_fit_score": _finite(getattr(generated, "roster_timeline_fit_score", None)),
            "roster_upside_fit_score": _finite(getattr(generated, "roster_upside_fit_score", None)),
            "roster_redundancy_risk": _finite(getattr(generated, "roster_redundancy_risk", None)),
            "roster_prospect_blocking_risk": _finite(getattr(generated, "roster_prospect_blocking_risk", None)),
            "roster_spending_multiplier": _finite(getattr(generated, "roster_spending_multiplier", None)),
            "roster_offer_status": _clean(getattr(generated, "roster_offer_status", "")),
            "roster_offer_reason_code": _clean(getattr(generated, "roster_offer_reason_code", "")),
            "roster_offer_economic_score": _finite(getattr(generated, "roster_offer_economic_score", None)),
            "roster_offer_fingerprint": _clean(getattr(generated, "roster_offer_fingerprint", "")),
            "annual_salary": _finite(getattr(generated, "annual_salary", None)),
            "years": int(getattr(generated, "years", 0) or 0),
            "strategic_requested_years": int(getattr(generated, "strategic_requested_years", getattr(generated, "years", 0)) or 0),
            "term_fallback_applied": bool(getattr(generated, "term_fallback_applied", False)),
            "market_salary_reference_from_generator": _finite(getattr(generated, "market_salary_reference", None)),
            "player_overall": _finite(getattr(player, "overall_rating", None)) if player is not None else None,
            "player_potential": _finite(getattr(player, "potential_rating", None)) if player is not None else None,
            "player_age": _finite(getattr(player, "age", None)) if player is not None else None,
            "player_position": _clean(getattr(player, "position", "")) if player is not None else "",
            "evaluation_error": "",
        }
        try:
            service, service_source = resolve_years_of_service(player) if player is not None else (None, "missing_player")
            decision = evaluate_free_agent_offer_decision(state, preview)
            profile = decision.preference_profile
            reference = float(decision.market_salary_reference or 0.0)
            annual = float(decision.annual_salary or 0.0)
            ratio = annual / reference if reference > 0 else None
            gap = float(decision.utility_score) - float(decision.acceptance_threshold)
            counter_raise_pct = None
            if decision.counter_salary is not None and annual > 0:
                counter_raise_pct = 100.0 * (float(decision.counter_salary) - annual) / annual
            status = _clean(decision.status).lower()
            band = interest_band(decision.utility_score, decision.acceptance_threshold, status)
            row = {
                **base,
                "years_of_service": service,
                "service_source": _clean(service_source),
                "interest_score": round(float(decision.utility_score), 3),
                "interest_band": band,
                "acceptance_threshold": round(float(decision.acceptance_threshold), 3),
                "gap_to_acceptance": round(gap, 3),
                "player_decision_status": status,
                "accepted": bool(decision.accepted),
                "counter_salary": _finite(decision.counter_salary),
                "counter_raise_pct": round(counter_raise_pct, 3) if counter_raise_pct is not None else None,
                "market_salary_reference": reference,
                "salary_to_market_ratio": round(ratio, 6) if ratio is not None else None,
                "salary_to_market_pct": round(100.0 * ratio, 2) if ratio is not None else None,
                "total_contract_value": round(annual * max(int(decision.years), 0), 2),
                "salary_score": round(float(decision.salary_score), 3),
                "role_score": round(float(decision.role_score), 3),
                "winning_score": round(float(decision.winning_score), 3),
                "security_score": round(float(decision.security_score), 3),
                "career_fit_score": round(float(decision.career_fit_score), 3),
                "preference_archetype": _clean(profile.archetype),
                "money_weight": float(profile.money_weight),
                "role_weight": float(profile.role_weight),
                "winning_weight": float(profile.winning_weight),
                "security_weight": float(profile.security_weight),
                "career_fit_weight": float(profile.career_fit_weight),
                "market_patience": float(profile.market_patience),
                "premium_player_watch": bool((base["player_overall"] or 0.0) >= 80.0),
                "competitive_offer": status in {"accept", "counter"},
                "hopeless_offer_watch": bool(status == "decline" and gap <= -20.0),
                "offer_fingerprint": _clean(getattr(generated, "offer_fingerprint", "")),
                "decision_fingerprint": _clean(decision.decision_fingerprint),
            }
            quality_rows.append(row)
            if player_id not in profile_by_player:
                profile_by_player[player_id] = {
                    "player_id": player_id,
                    "player_name": row["player_name"],
                    "player_overall": row["player_overall"],
                    "player_potential": row["player_potential"],
                    "player_age": row["player_age"],
                    "player_position": row["player_position"],
                    "years_of_service": service,
                    "service_source": _clean(service_source),
                    "preference_archetype": _clean(profile.archetype),
                    "money_weight": float(profile.money_weight),
                    "role_weight": float(profile.role_weight),
                    "winning_weight": float(profile.winning_weight),
                    "security_weight": float(profile.security_weight),
                    "career_fit_weight": float(profile.career_fit_weight),
                    "acceptance_threshold": float(profile.acceptance_threshold),
                    "market_patience": float(profile.market_patience),
                    "market_salary_reference": reference,
                }
        except Exception as exc:
            quality_rows.append({
                **base,
                "years_of_service": None,
                "service_source": "",
                "interest_score": None,
                "interest_band": "",
                "acceptance_threshold": None,
                "gap_to_acceptance": None,
                "player_decision_status": "evaluation_error",
                "accepted": False,
                "counter_salary": None,
                "counter_raise_pct": None,
                "market_salary_reference": None,
                "salary_to_market_ratio": None,
                "salary_to_market_pct": None,
                "total_contract_value": None,
                "salary_score": None,
                "role_score": None,
                "winning_score": None,
                "security_score": None,
                "career_fit_score": None,
                "preference_archetype": "",
                "money_weight": None,
                "role_weight": None,
                "winning_weight": None,
                "security_weight": None,
                "career_fit_weight": None,
                "market_patience": None,
                "premium_player_watch": bool((base["player_overall"] or 0.0) >= 80.0),
                "competitive_offer": False,
                "hopeless_offer_watch": False,
                "offer_fingerprint": _clean(getattr(generated, "offer_fingerprint", "")),
                "decision_fingerprint": "",
                "evaluation_error": f"{type(exc).__name__}: {exc}",
            })
    quality_rows.sort(key=lambda r: (_clean(r.get("player_id")), _team(r.get("team_abbreviation"))))
    profiles = sorted(profile_by_player.values(), key=lambda r: (_clean(r.get("player_name")), _clean(r.get("player_id"))))
    return quality_rows, profiles


def _market_quality_exports(
    quality_rows: list[dict[str, Any]],
    market_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    market_by_player = {_clean(row.get("player_id")): row for row in market_rows}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in quality_rows:
        grouped.setdefault(_clean(row.get("player_id")), []).append(row)
    out: list[dict[str, Any]] = []
    for player_id, rows in sorted(grouped.items()):
        valid = [r for r in rows if not _clean(r.get("evaluation_error"))]
        interests = [float(r["interest_score"]) for r in valid if _finite(r.get("interest_score")) is not None]
        salaries = [float(r["annual_salary"] or 0.0) for r in valid]
        ratios = [float(r["salary_to_market_ratio"]) for r in valid if _finite(r.get("salary_to_market_ratio")) is not None]
        statuses = [_clean(r.get("player_decision_status")).lower() for r in valid]
        route_counts: dict[str, int] = {}
        for row in valid:
            route = _clean(row.get("financial_route")) or "unknown"
            route_counts[route] = route_counts.get(route, 0) + 1
        market = market_by_player.get(player_id, {})
        winner_team = _team(market.get("winner_team_abbreviation"))
        winner_row = next((r for r in valid if _team(r.get("team_abbreviation")) == winner_team), None)
        highest_salary = max(salaries) if salaries else None
        winner_salary = _finite(winner_row.get("annual_salary")) if winner_row else None
        winner_interest = _finite(winner_row.get("interest_score")) if winner_row else None
        lower_salary_winner = bool(
            winner_salary is not None and highest_salary is not None and winner_salary < highest_salary - 0.01
        )
        out.append({
            "player_id": player_id,
            "player_name": _clean(rows[0].get("player_name")) if rows else "",
            "player_overall": _finite(rows[0].get("player_overall")) if rows else None,
            "player_age": _finite(rows[0].get("player_age")) if rows else None,
            "offer_count": len(valid),
            "accept_count": sum(s == "accept" for s in statuses),
            "counter_count": sum(s == "counter" for s in statuses),
            "decline_count": sum(s == "decline" for s in statuses),
            "competitive_offer_count": sum(s in {"accept", "counter"} for s in statuses),
            "hopeless_offer_count": sum(bool(r.get("hopeless_offer_watch")) for r in valid),
            "max_interest": round(max(interests), 3) if interests else None,
            "median_interest": round(float(_percentile(interests, 0.5)), 3) if interests else None,
            "min_interest": round(min(interests), 3) if interests else None,
            "interest_spread": round(max(interests) - min(interests), 3) if interests else None,
            "median_salary_to_market_pct": round(100.0 * float(_percentile(ratios, 0.5)), 2) if ratios else None,
            "highest_annual_salary": highest_salary,
            "winner_team_abbreviation": winner_team or None,
            "winner_interest": winner_interest,
            "winner_salary": winner_salary,
            "highest_salary_wins": bool(winner_salary is not None and highest_salary is not None and math.isclose(winner_salary, highest_salary, abs_tol=0.01)),
            "lower_salary_winner": lower_salary_winner,
            "winning_margin": _finite(market.get("winning_margin")),
            "financial_route_distribution": json.dumps(route_counts, sort_keys=True),
            "minimum_exception_offer_count": route_counts.get("minimum_salary_exception", 0),
            "premium_player_watch": bool((_finite(rows[0].get("player_overall")) or 0.0) >= 80.0) if rows else False,
            "no_accepted_destination_watch": sum(s == "accept" for s in statuses) == 0,
            "no_competitive_destination_watch": sum(s in {"accept", "counter"} for s in statuses) == 0,
            "market_fingerprint": _clean(market.get("market_fingerprint")),
        })
    return out


def _roster_construction_exports(
    offer_rows: list[dict[str, Any]],
    skipped_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    flags: list[dict[str, Any]] = []
    for offer in offer_rows:
        row = {
            "player_id": _clean(offer.get("player_id")),
            "player_name": _clean(offer.get("player_name")),
            "team_abbreviation": _team(offer.get("team_abbreviation")),
            "team_direction": _clean(offer.get("team_direction")),
            "financial_route": _clean(offer.get("financial_route")),
            "annual_salary": _finite(offer.get("annual_salary")),
            "market_salary_reference": _finite(offer.get("market_salary_reference")),
            "roster_construction_score": _finite(offer.get("roster_construction_score")),
            "roster_construction_tier": _clean(offer.get("roster_construction_tier")),
            "position_family": _clean(offer.get("roster_position_family")),
            "projected_role": _clean(offer.get("roster_projected_role")),
            "positional_need_score": _finite(offer.get("roster_positional_need_score")),
            "role_upgrade_score": _finite(offer.get("roster_role_upgrade_score")),
            "timeline_fit_score": _finite(offer.get("roster_timeline_fit_score")),
            "upside_fit_score": _finite(offer.get("roster_upside_fit_score")),
            "redundancy_risk": _finite(offer.get("roster_redundancy_risk")),
            "prospect_blocking_risk": _finite(offer.get("roster_prospect_blocking_risk")),
            "marginal_overall_vs_best": _finite(offer.get("roster_marginal_overall_vs_best")),
            "marginal_overall_vs_second": _finite(offer.get("roster_marginal_overall_vs_second")),
            "spending_multiplier": _finite(offer.get("roster_spending_multiplier")),
            "target_reason_code": _clean(offer.get("roster_construction_reason_code")),
            "offer_status": _clean(offer.get("roster_offer_status")),
            "offer_reason_code": _clean(offer.get("roster_offer_reason_code")),
            "economic_pursuit_score": _finite(offer.get("roster_offer_economic_score")),
            "salary_to_market_ratio": _finite(offer.get("roster_offer_salary_to_market_ratio")),
            "player_interest": _finite(offer.get("roster_offer_interest")),
            "gap_to_acceptance": _finite(offer.get("roster_offer_gap")),
            "target_fingerprint": _clean(offer.get("roster_target_fingerprint")),
            "offer_fingerprint": _clean(offer.get("roster_offer_fingerprint")),
        }
        rows.append(row)
        score = _finite(row.get("roster_construction_score"))
        redundancy = _finite(row.get("redundancy_risk"))
        blocking = _finite(row.get("prospect_blocking_risk"))
        if score is not None and score < 55.0:
            flags.append({"scope":"offer","flag_code":"LOW_ROSTER_CONSTRUCTION_SCORE","status":"WATCH","impact":"medium","player_id":row["player_id"],"player_name":row["player_name"],"team_abbreviation":row["team_abbreviation"],"detail":f"Roster-construction score is only {score:.1f}/100."})
        if redundancy is not None and redundancy >= 65.0:
            flags.append({"scope":"offer","flag_code":"POSITION_REDUNDANCY_RISK","status":"WATCH","impact":"medium","player_id":row["player_id"],"player_name":row["player_name"],"team_abbreviation":row["team_abbreviation"],"detail":f"Position-family redundancy risk is {redundancy:.1f}/100."})
        if blocking is not None and blocking >= 65.0:
            flags.append({"scope":"offer","flag_code":"PROSPECT_BLOCKING_RISK","status":"WATCH","impact":"medium","player_id":row["player_id"],"player_name":row["player_name"],"team_abbreviation":row["team_abbreviation"],"detail":f"Development-runway blocking risk is {blocking:.1f}/100."})
    for skipped in skipped_rows:
        reason = _clean(skipped.get("reason"))
        if not reason.startswith("roster_construction:"):
            continue
        flags.append({
            "scope":"filtered_target",
            "flag_code":"ROSTER_CONSTRUCTION_FILTERED_TARGET",
            "status":"WATCH",
            "impact":"info",
            "player_id":_clean(skipped.get("player_id")),
            "player_name":_clean(skipped.get("player_name")),
            "team_abbreviation":_team(skipped.get("team_abbreviation")),
            "detail":reason.split(":",1)[1] if ":" in reason else reason,
        })
    rows.sort(key=lambda r: (_clean(r.get("player_id")), _team(r.get("team_abbreviation"))))
    flags.sort(key=lambda r: (_clean(r.get("flag_code")), _clean(r.get("player_id")), _team(r.get("team_abbreviation"))))
    return rows, flags


def _roster_construction_behavioral_checks(
    offer_rows: list[dict[str, Any]],
    skipped_rows: list[dict[str, Any]],
    roster_rows: list[dict[str, Any]],
    roster_flags: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    def add(check_id: str, ok: bool, detail: str) -> None:
        checks.append({"check_id":check_id,"status":"PASS" if ok else "FAIL","severity":"strict","detail":detail})
    add("roster_construction_rows_match_generated_offers", len(roster_rows) == len(offer_rows), f"Roster rows: {len(roster_rows)}; offers: {len(offer_rows)}.")
    add("every_generated_offer_has_roster_construction_score", all(_finite(r.get("roster_construction_score")) is not None for r in offer_rows), "Every submitted CPU bid must carry a roster-construction score.")
    add("roster_construction_scores_are_bounded", all(0.0 <= float(r.get("roster_construction_score")) <= 100.0 for r in offer_rows if _finite(r.get("roster_construction_score")) is not None), "Roster scores must remain within 0-100.")
    risk_fields=("roster_redundancy_risk","roster_prospect_blocking_risk","roster_positional_need_score","roster_role_upgrade_score","roster_timeline_fit_score","roster_upside_fit_score")
    add("roster_construction_components_are_bounded", all(0.0 <= float(r.get(field)) <= 100.0 for r in offer_rows for field in risk_fields if _finite(r.get(field)) is not None), "All roster intelligence components must remain within 0-100.")
    add("roster_spending_multiplier_is_conservative", all(0.94 - 1e-9 <= float(r.get("roster_spending_multiplier")) <= 1.06 + 1e-9 for r in offer_rows if _finite(r.get("roster_spending_multiplier")) is not None), "Roster spending adjustment is bounded to +/-6%.")
    add("every_generated_offer_passed_roster_offer_gate", all(_clean(r.get("roster_offer_status")).lower() == "pass" for r in offer_rows), "Only roster-offer PASS rows may reach the generated board.")
    add("roster_construction_fingerprints_are_present", all(_clean(r.get("roster_target_fingerprint")) and _clean(r.get("roster_offer_fingerprint")) for r in offer_rows), "Every generated offer must preserve target and offer roster fingerprints.")
    roster_skips=[r for r in skipped_rows if _clean(r.get("reason")).startswith("roster_construction:")]
    add("roster_filtered_targets_have_explicit_reason", all(_clean(r.get("roster_construction_reason_code")) for r in roster_skips), f"Roster-filtered targets: {len(roster_skips)}.")
    add("roster_quality_flags_are_watch_only", all(_clean(r.get("status")) == "WATCH" for r in roster_flags), "Roster diagnostics may not become hidden legality failures.")
    return checks


def _roster_construction_watch_metrics(
    roster_rows: list[dict[str, Any]],
    skipped_rows: list[dict[str, Any]],
    roster_flags: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    def add(metric: str, value: Any, detail: str = "") -> None:
        out.append({"metric":metric,"value":value,"status":"WATCH","detail":detail})
    scores=[float(r["roster_construction_score"]) for r in roster_rows if _finite(r.get("roster_construction_score")) is not None]
    add("roster_construction_average_score", round(sum(scores)/len(scores),3) if scores else None)
    add("roster_construction_median_score", round(float(_percentile(scores,0.5)),3) if scores else None)
    add("roster_construction_low_score_offer_count", sum(v < 55.0 for v in scores))
    add("roster_construction_clear_starter_upgrade_count", sum(_clean(r.get("projected_role")) in {"clear_starter_upgrade","starter_upgrade"} for r in roster_rows))
    add("roster_construction_high_redundancy_offer_count", sum((_finite(r.get("redundancy_risk")) or 0.0) >= 65.0 for r in roster_rows))
    add("roster_construction_high_prospect_blocking_offer_count", sum((_finite(r.get("prospect_blocking_risk")) or 0.0) >= 65.0 for r in roster_rows))
    roster_skips=[r for r in skipped_rows if _clean(r.get("reason")).startswith("roster_construction:")]
    add("roster_construction_filtered_target_count", len(roster_skips))
    reason_counts: dict[str,int]={}
    for row in roster_skips:
        reason=_clean(row.get("reason")).split(":",1)[-1]
        reason_counts[reason]=reason_counts.get(reason,0)+1
    add("roster_construction_filter_reason_distribution", json.dumps(reason_counts,sort_keys=True))
    role_counts: dict[str,int]={}
    direction_scores: dict[str,list[float]]={}
    for row in roster_rows:
        role=_clean(row.get("projected_role")) or "unknown"
        role_counts[role]=role_counts.get(role,0)+1
        direction=_clean(row.get("team_direction")) or "unknown"
        score=_finite(row.get("roster_construction_score"))
        if score is not None:
            direction_scores.setdefault(direction,[]).append(score)
    add("roster_construction_projected_role_distribution", json.dumps(role_counts,sort_keys=True))
    add("roster_construction_average_score_by_direction", json.dumps({k:round(sum(v)/len(v),3) for k,v in sorted(direction_scores.items()) if v},sort_keys=True))
    flag_counts: dict[str,int]={}
    for row in roster_flags:
        code=_clean(row.get("flag_code"))
        flag_counts[code]=flag_counts.get(code,0)+1
    add("roster_construction_flag_distribution", json.dumps(flag_counts,sort_keys=True))
    return out



def _offer_economic_exports(
    offer_rows: list[dict[str, Any]],
    skipped_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    flags: list[dict[str, Any]] = []
    for offer in offer_rows:
        row = {
            "player_id": _clean(offer.get("player_id")),
            "player_name": _clean(offer.get("player_name")),
            "team_abbreviation": _team(offer.get("team_abbreviation")),
            "team_direction": _clean(offer.get("team_direction")),
            "financial_route": _clean(offer.get("financial_route")),
            "annual_salary": _finite(offer.get("annual_salary")),
            "market_salary_reference": _finite(offer.get("market_salary_reference")),
            "salary_to_market_ratio": _finite(offer.get("offer_economic_salary_to_market_ratio")),
            "minimum_credible_market_ratio": _finite(offer.get("offer_economic_minimum_market_ratio")),
            "economic_credibility_score": _finite(offer.get("offer_economic_credibility_score")),
            "economic_tier": _clean(offer.get("offer_economic_tier")),
            "economic_status": _clean(offer.get("offer_economic_status")),
            "economic_reason_code": _clean(offer.get("offer_economic_reason_code")),
            "player_interest": _finite(offer.get("offer_economic_interest")),
            "gap_to_acceptance": _finite(offer.get("offer_economic_gap")),
            "discount_support_score": _finite(offer.get("offer_economic_discount_support_score")),
            "roster_construction_score": _finite(offer.get("roster_construction_score")),
            "projected_role": _clean(offer.get("roster_projected_role")),
            "fingerprint": _clean(offer.get("offer_economic_fingerprint")),
        }
        rows.append(row)
        ratio = _finite(row.get("salary_to_market_ratio"))
        floor = _finite(row.get("minimum_credible_market_ratio"))
        score = _finite(row.get("economic_credibility_score"))
        route = _clean(row.get("financial_route"))
        if route != "minimum_salary_exception" and ratio is not None and ratio < 0.50:
            flags.append({"scope":"offer","flag_code":"SUBMITTED_DEEP_MARKET_DISCOUNT","status":"WATCH","impact":"medium","player_id":row["player_id"],"player_name":row["player_name"],"team_abbreviation":row["team_abbreviation"],"detail":f"Submitted non-MSE offer is only {ratio*100:.1f}% of market reference."})
        if route != "minimum_salary_exception" and floor is not None and ratio is not None and ratio + 1e-9 < floor:
            flags.append({"scope":"offer","flag_code":"SUBMITTED_BELOW_CONTEXTUAL_ECONOMIC_FLOOR","status":"WATCH","impact":"high","player_id":row["player_id"],"player_name":row["player_name"],"team_abbreviation":row["team_abbreviation"],"detail":f"Submitted ratio {ratio:.3f} is below contextual floor {floor:.3f}."})
        if score is not None and score < 52.0:
            flags.append({"scope":"offer","flag_code":"LOW_OFFER_ECONOMIC_CREDIBILITY","status":"WATCH","impact":"medium","player_id":row["player_id"],"player_name":row["player_name"],"team_abbreviation":row["team_abbreviation"],"detail":f"Offer Economic Intelligence score is {score:.1f}/100."})
        if ratio is not None and ratio >= 1.18 and (_finite(row.get("roster_construction_score")) or 0.0) < 65.0:
            flags.append({"scope":"offer","flag_code":"OVERPAY_WITH_LIMITED_ROSTER_VALUE","status":"WATCH","impact":"medium","player_id":row["player_id"],"player_name":row["player_name"],"team_abbreviation":row["team_abbreviation"],"detail":f"Offer is {ratio*100:.1f}% of market reference with roster score below 65."})
    for skipped in skipped_rows:
        reason = _clean(skipped.get("reason"))
        if not reason.startswith("offer_economics:"):
            continue
        flags.append({
            "scope":"filtered_target",
            "flag_code":"OFFER_ECONOMIC_FILTERED_TARGET",
            "status":"WATCH",
            "impact":"info",
            "player_id":_clean(skipped.get("player_id")),
            "player_name":_clean(skipped.get("player_name")),
            "team_abbreviation":_team(skipped.get("team_abbreviation")),
            "detail":reason.split(":",1)[1] if ":" in reason else reason,
        })
    rows.sort(key=lambda r: (_clean(r.get("player_id")), _team(r.get("team_abbreviation"))))
    flags.sort(key=lambda r: (_clean(r.get("flag_code")), _clean(r.get("player_id")), _team(r.get("team_abbreviation"))))
    return rows, flags


def _offer_economic_behavioral_checks(
    offer_rows: list[dict[str, Any]],
    skipped_rows: list[dict[str, Any]],
    economic_rows: list[dict[str, Any]],
    economic_flags: list[dict[str, Any]],
    quality_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    def add(check_id: str, ok: bool, detail: str) -> None:
        checks.append({"check_id":check_id,"status":"PASS" if ok else "FAIL","severity":"strict","detail":detail})
    add("offer_economic_rows_match_generated_offers", len(economic_rows) == len(offer_rows), f"Economic rows: {len(economic_rows)}; offers: {len(offer_rows)}.")
    add("every_generated_offer_passed_offer_economic_gate", all(_clean(r.get("offer_economic_status")).lower() == "pass" for r in offer_rows), "Every submitted offer must have passed Offer Economic Intelligence.")
    add("offer_economic_scores_are_bounded", all(0.0 <= float(r.get("economic_credibility_score")) <= 100.0 for r in economic_rows if _finite(r.get("economic_credibility_score")) is not None), "Economic credibility scores remain within 0-100.")
    add("offer_economic_market_ratios_are_nonnegative", all(float(r.get("salary_to_market_ratio")) >= 0.0 for r in economic_rows if _finite(r.get("salary_to_market_ratio")) is not None), "Salary-to-market ratios must be nonnegative.")
    add("offer_economic_contextual_floors_are_bounded", all(0.42 - 1e-9 <= float(r.get("minimum_credible_market_ratio")) <= 0.82 + 1e-9 for r in economic_rows if _finite(r.get("minimum_credible_market_ratio")) is not None), "Contextual economic floors remain in the conservative 42%-82% band.")
    add("offer_economic_fingerprints_are_present", all(_clean(r.get("fingerprint")) for r in economic_rows), "Every submitted offer must retain an economic-intelligence fingerprint.")
    add("minimum_exception_survivors_are_not_second_guessed", all(_clean(r.get("economic_reason_code")) == "minimum_exception_targeting_authoritative" for r in economic_rows if _clean(r.get("financial_route")) == "minimum_salary_exception"), "MSE credibility remains authoritative upstream.")
    economic_skips=[r for r in skipped_rows if _clean(r.get("reason")).startswith("offer_economics:")]
    add("offer_economic_filtered_targets_have_explicit_reason", all(_clean(r.get("offer_economic_reason_code")) and _clean(r.get("offer_economic_fingerprint")) for r in economic_skips), f"Economic-filtered targets: {len(economic_skips)}.")
    add("offer_economic_flags_are_watch_only", all(_clean(r.get("status")) == "WATCH" for r in economic_flags), "Economic diagnostics remain WATCH-only and cannot become hidden legality gates.")
    quality_by_key={(_clean(r.get("player_id")),_team(r.get("team_abbreviation"))):r for r in quality_rows}
    exact_interest=True; exact_gap=True
    for row in economic_rows:
        key=(_clean(row.get("player_id")),_team(row.get("team_abbreviation")))
        q=quality_by_key.get(key)
        if not q: continue
        ei=_finite(row.get("player_interest")); qi=_finite(q.get("interest_score"))
        eg=_finite(row.get("gap_to_acceptance")); qg=_finite(q.get("gap_to_acceptance"))
        if ei is not None and qi is not None and abs(ei-qi)>1e-6: exact_interest=False
        if eg is not None and qg is not None and abs(eg-qg)>1e-6: exact_gap=False
    add("offer_economic_interest_matches_player_decision", exact_interest, "Economic Intelligence must reuse the exact Player Decisions utility score.")
    add("offer_economic_gap_matches_player_decision", exact_gap, "Economic Intelligence must reuse the exact Player Decisions acceptance gap.")
    return checks


def _offer_economic_watch_metrics(
    economic_rows: list[dict[str, Any]],
    skipped_rows: list[dict[str, Any]],
    economic_flags: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]]=[]
    def add(metric: str, value: Any, detail: str = "") -> None:
        out.append({"metric":metric,"value":value,"status":"WATCH","detail":detail})
    scores=[float(r["economic_credibility_score"]) for r in economic_rows if _finite(r.get("economic_credibility_score")) is not None]
    ratios=[float(r["salary_to_market_ratio"]) for r in economic_rows if _finite(r.get("salary_to_market_ratio")) is not None and _clean(r.get("financial_route"))!="minimum_salary_exception"]
    add("offer_economic_average_credibility_score", round(sum(scores)/len(scores),3) if scores else None)
    add("offer_economic_median_credibility_score", round(float(_percentile(scores,0.5)),3) if scores else None)
    add("offer_economic_median_non_mse_market_ratio", round(float(_percentile(ratios,0.5)),6) if ratios else None)
    add("offer_economic_submitted_non_mse_below_50pct_market_count", sum(v<0.50 for v in ratios))
    economic_skips=[r for r in skipped_rows if _clean(r.get("reason")).startswith("offer_economics:")]
    add("offer_economic_filtered_target_count", len(economic_skips))
    reasons: dict[str,int]={}
    for row in economic_skips:
        reason=_clean(row.get("reason")).split(":",1)[-1]
        reasons[reason]=reasons.get(reason,0)+1
    add("offer_economic_filter_reason_distribution", json.dumps(reasons,sort_keys=True))
    tiers: dict[str,int]={}
    for row in economic_rows:
        tier=_clean(row.get("economic_tier")) or "unknown"
        tiers[tier]=tiers.get(tier,0)+1
    add("offer_economic_tier_distribution", json.dumps(tiers,sort_keys=True))
    flags: dict[str,int]={}
    for row in economic_flags:
        code=_clean(row.get("flag_code")); flags[code]=flags.get(code,0)+1
    add("offer_economic_flag_distribution", json.dumps(flags,sort_keys=True))
    return out

def _quality_flags(
    quality_rows: list[dict[str, Any]],
    market_quality_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    def add(scope: str, code: str, row: Mapping[str, Any], detail: str, impact: str = "medium") -> None:
        flags.append({
            "scope": scope,
            "flag_code": code,
            "status": "WATCH",
            "impact": impact,
            "player_id": _clean(row.get("player_id")),
            "player_name": _clean(row.get("player_name")),
            "team_abbreviation": _team(row.get("team_abbreviation")) or None,
            "detail": detail,
        })
    for row in quality_rows:
        if _clean(row.get("evaluation_error")):
            add("offer", "DECISION_EVALUATION_ERROR", row, _clean(row.get("evaluation_error")), "high")
            continue
        gap = _finite(row.get("gap_to_acceptance"))
        fit = _finite(row.get("target_fit_score"))
        ratio = _finite(row.get("salary_to_market_ratio"))
        overall = _finite(row.get("player_overall")) or 0.0
        route = _clean(row.get("financial_route"))
        status = _clean(row.get("player_decision_status")).lower()
        if status == "decline" and gap is not None and gap <= -20.0:
            add("offer", "NONCOMPETITIVE_OFFER_20_PLUS_BELOW_THRESHOLD", row, f"Interest is {abs(gap):.1f} points below the player's acceptance line.")
        if route == "minimum_salary_exception" and overall >= 80.0:
            add("offer", "PREMIUM_PLAYER_MINIMUM_EXCEPTION_OFFER", row, f"{overall:.1f} OVR player received a one-year minimum-exception bid.", "high")
        if fit is not None and fit >= 80.0 and status == "decline" and gap is not None and gap <= -20.0:
            add("offer", "HIGH_FIT_BUT_NONCOMPETITIVE_OFFER", row, f"Target fit is {fit:.1f}, but player interest is far below acceptance.")
        if ratio is not None and ratio < 0.40 and overall >= 78.0:
            add("offer", "SEVERE_MARKET_UNDERPAY_WATCH", row, f"Offer is only {100.0*ratio:.1f}% of this model's market salary reference.")
        if bool(row.get("term_fallback_applied")) and int(row.get("years") or 0) == 1 and int(row.get("strategic_requested_years") or 0) >= 3:
            add("offer", "LONG_TERM_STRATEGY_COLLAPSED_TO_ONE_YEAR", row, f"CPU requested {row.get('strategic_requested_years')} years but legality/route support reduced the bid to one year.")
        if fit is not None and fit < 45.0 and ratio is not None and ratio >= 0.90:
            add("offer", "LOW_FIT_NEAR_MARKET_RATE_OFFER", row, f"Target fit is only {fit:.1f} while salary is {100.0*ratio:.1f}% of market reference.")
    for row in market_quality_rows:
        if bool(row.get("premium_player_watch")) and bool(row.get("no_accepted_destination_watch")):
            add("market", "PREMIUM_PLAYER_WITHOUT_ACCEPTED_DESTINATION", row, "Premium player has no accepted CPU destination in the current isolated market.", "high")
        if bool(row.get("no_competitive_destination_watch")):
            add("market", "NO_COMPETITIVE_CPU_DESTINATION", row, "Every CPU offer is a decline under the current player decision model.")
        offer_count = int(row.get("offer_count") or 0)
        mse_count = int(row.get("minimum_exception_offer_count") or 0)
        if offer_count >= 4 and mse_count / max(offer_count, 1) >= 0.75:
            add("market", "MINIMUM_EXCEPTION_DOMINATED_MARKET", row, f"{mse_count}/{offer_count} offers use the one-year Minimum Salary Exception.")
        if offer_count == 1:
            add("market", "SINGLE_TEAM_CPU_MARKET", row, "Only one CPU team submitted a legal bid in this market.", "low")
    return flags


def _quality_watch_metrics(
    quality_rows: list[dict[str, Any]],
    profile_rows: list[dict[str, Any]],
    market_quality_rows: list[dict[str, Any]],
    quality_flags: list[dict[str, Any]],
    skipped_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    def add(name: str, value: Any, note: str) -> None:
        metrics.append({"metric": name, "value": value, "status": "WATCH", "note": note})
    valid = [r for r in quality_rows if not _clean(r.get("evaluation_error"))]
    n = len(valid)
    interests = [float(r["interest_score"]) for r in valid if _finite(r.get("interest_score")) is not None]
    ratios = [float(r["salary_to_market_ratio"]) for r in valid if _finite(r.get("salary_to_market_ratio")) is not None]
    statuses = [_clean(r.get("player_decision_status")).lower() for r in valid]
    add("offer_quality_evaluated_bid_count", n, "Every generated legal CPU bid should have a player-interest/offer-quality evaluation.")
    add("average_player_interest", round(sum(interests)/len(interests), 3) if interests else None, "Mean deterministic player utility across generated CPU bids, not a signing probability.")
    add("median_player_interest", round(float(_percentile(interests, 0.5)), 3) if interests else None, "Median deterministic player utility across generated CPU bids.")
    add("player_interest_p25", round(float(_percentile(interests, 0.25)), 3) if interests else None, "Lower quartile of player interest.")
    add("player_interest_p75", round(float(_percentile(interests, 0.75)), 3) if interests else None, "Upper quartile of player interest.")
    add("accept_offer_count", sum(s == "accept" for s in statuses), "Offers immediately accepted by the deterministic player-decision model.")
    add("counter_offer_count", sum(s == "counter" for s in statuses), "Offers close enough for a player counter.")
    add("decline_offer_count", sum(s == "decline" for s in statuses), "Offers declined outright.")
    if n:
        add("competitive_offer_share_pct", round(100.0*sum(s in {"accept","counter"} for s in statuses)/n, 2), "Share of CPU bids that produce ACCEPT or COUNTER rather than a hard decline.")
        hopeless = sum(bool(r.get("hopeless_offer_watch")) for r in valid)
        add("noncompetitive_20_plus_below_threshold_share_pct", round(100.0*hopeless/n, 2), "Share of bids at least 20 interest points below the player's acceptance line.")
        fallback = sum(bool(r.get("term_fallback_applied")) for r in valid)
        add("term_fallback_share_pct", round(100.0*fallback/n, 2), "Share of bids whose strategic term had to be shortened by legality/route support.")
    add("median_salary_to_market_pct", round(100.0*float(_percentile(ratios, 0.5)), 2) if ratios else None, "Median annual salary as a share of the player-decision model's market salary reference.")
    add("salary_to_market_p10_pct", round(100.0*float(_percentile(ratios, 0.10)), 2) if ratios else None, "10th percentile offer/reference ratio.")
    add("salary_to_market_p90_pct", round(100.0*float(_percentile(ratios, 0.90)), 2) if ratios else None, "90th percentile offer/reference ratio.")
    route_stats: dict[str, dict[str, float]] = {}
    direction_stats: dict[str, dict[str, float]] = {}
    for row in valid:
        interest = _finite(row.get("interest_score"))
        if interest is None:
            continue
        for key, bucket in (("financial_route", route_stats), ("team_direction", direction_stats)):
            label = _clean(row.get(key)) or "unknown"
            payload = bucket.setdefault(label, {"sum": 0.0, "n": 0.0, "competitive": 0.0})
            payload["sum"] += interest
            payload["n"] += 1
            payload["competitive"] += 1 if bool(row.get("competitive_offer")) else 0
    def summarize(raw: dict[str, dict[str, float]]) -> str:
        return json.dumps({k: {"avg_interest": round(v["sum"]/v["n"], 2), "competitive_share_pct": round(100*v["competitive"]/v["n"], 2), "offers": int(v["n"])} for k,v in sorted(raw.items()) if v["n"]}, sort_keys=True)
    add("interest_by_financial_route", summarize(route_stats), "Average interest and competitive-offer share by financial mechanism.")
    add("interest_by_team_direction", summarize(direction_stats), "Average interest and competitive-offer share by CPU strategic direction.")
    archetypes: dict[str, int] = {}
    for row in profile_rows:
        label = _clean(row.get("preference_archetype")) or "unknown"
        archetypes[label] = archetypes.get(label, 0) + 1
    add("player_preference_archetype_distribution", json.dumps(archetypes, sort_keys=True), "Distribution of deterministic player motivation archetypes in evaluated markets.")
    mse = [r for r in valid if _clean(r.get("financial_route")) == "minimum_salary_exception"]
    if mse:
        mse_comp = sum(_clean(r.get("player_decision_status")) in {"accept", "counter"} for r in mse)
        mse_accept = sum(_clean(r.get("player_decision_status")) == "accept" for r in mse)
        mse_hopeless = sum(bool(r.get("hopeless_offer_watch")) for r in mse)
        premium_mse = sum(bool(r.get("premium_player_watch")) for r in mse)
        add("minimum_exception_competitive_share_pct", round(100.0*mse_comp/len(mse), 2), "How often one-year minimum-exception bids generate ACCEPT or COUNTER.")
        add("minimum_exception_accept_share_pct", round(100.0*mse_accept/len(mse), 2), "Immediate acceptance rate for one-year minimum-exception bids.")
        add("minimum_exception_hopeless_offer_count", mse_hopeless, "Minimum-exception bids at least 20 points below acceptance.")
        add("minimum_exception_premium_player_offer_count", premium_mse, "WATCH only: minimum-exception bids to 80+ OVR players.")
    else:
        add("minimum_exception_competitive_share_pct", None, "No Minimum Salary Exception bids in this audit snapshot.")
        add("minimum_exception_accept_share_pct", None, "No Minimum Salary Exception bids in this audit snapshot.")
        add("minimum_exception_hopeless_offer_count", 0, "No Minimum Salary Exception bids in this audit snapshot.")
        add("minimum_exception_premium_player_offer_count", 0, "No Minimum Salary Exception bids in this audit snapshot.")
    targeting_skips = [r for r in (skipped_rows or []) if _clean(r.get("reason")).startswith("minimum_exception_targeting:")]
    targeting_reason_counts: dict[str, int] = {}
    for row in targeting_skips:
        raw_reason = _clean(row.get("reason"))
        reason = raw_reason.split(":", 1)[1] if ":" in raw_reason else "unknown"
        targeting_reason_counts[reason] = targeting_reason_counts.get(reason, 0) + 1
    targeted_mse = [r for r in mse if _clean(r.get("minimum_targeting_status")) == "allow"]
    add("minimum_exception_targeting_generated_count", len(targeted_mse), "MSE bids that survived the CPU credibility gate and were actually submitted.")
    add("minimum_exception_targeting_filtered_count", len(targeting_skips), "Legally valid MSE targets filtered before bid submission because the exact minimum was not strategically credible.")
    add("minimum_exception_targeting_filter_reason_distribution", json.dumps(targeting_reason_counts, sort_keys=True), "Why technically legal exact-minimum targets were filtered by CPU offer-selection intelligence.")
    if targeted_mse:
        add("minimum_exception_targeting_average_credibility", round(sum(float(r.get("minimum_targeting_score") or 0.0) for r in targeted_mse)/len(targeted_mse), 3), "Average credibility score for submitted one-year MSE bids.")
    else:
        add("minimum_exception_targeting_average_credibility", None, "No MSE bid survived the targeting gate in this snapshot.")
    premium_no_accept = sum(bool(r.get("premium_player_watch")) and bool(r.get("no_accepted_destination_watch")) for r in market_quality_rows)
    add("premium_player_markets_without_accepted_destination", premium_no_accept, "80+ OVR markets with no ACCEPT destination. Use as a realism diagnostic, not a hard failure.")
    lower_salary = sum(bool(r.get("lower_salary_winner")) for r in market_quality_rows)
    winner_markets = sum(bool(r.get("winner_team_abbreviation")) for r in market_quality_rows)
    add("lower_salary_winner_count", lower_salary, "Markets where player utility selected a lower annual salary over the highest offer.")
    if winner_markets:
        add("lower_salary_winner_share_pct", round(100.0*lower_salary/winner_markets, 2), "Share of winner markets where non-money preferences overcame a higher annual salary.")
    flag_counts: dict[str, int] = {}
    for row in quality_flags:
        code = _clean(row.get("flag_code")) or "unknown"
        flag_counts[code] = flag_counts.get(code, 0) + 1
    add("offer_quality_watch_flag_distribution", json.dumps(flag_counts, sort_keys=True), "Diagnostic WATCH flags. These do not fail legality or safety unless promoted by a later calibrated audit version.")
    return metrics


def _quality_behavioral_checks(
    *,
    offer_rows: list[dict[str, Any]],
    quality_rows: list[dict[str, Any]],
    profile_rows: list[dict[str, Any]],
    market_quality_rows: list[dict[str, Any]],
    quality_flags: list[dict[str, Any]],
    quality_fingerprint: str,
    repeat_quality_fingerprint: str,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    def add(check_id: str, passed: bool, detail: str) -> None:
        checks.append({"check_id": check_id, "status": "PASS" if passed else "FAIL", "severity": "strict", "detail": detail})
    add("every_generated_bid_has_offer_quality_evaluation", len(quality_rows) == len(offer_rows), f"Offers={len(offer_rows)} quality_rows={len(quality_rows)}")
    add("offer_quality_has_no_evaluation_errors", all(not _clean(r.get("evaluation_error")) for r in quality_rows), "Player decision evaluation must succeed for every backend-PASS CPU bid.")
    add("offer_quality_team_player_pairs_are_unique", len({(_clean(r.get('player_id')), _team(r.get('team_abbreviation'))) for r in quality_rows}) == len(quality_rows), "One quality row per CPU team/player bid.")
    add("offer_quality_interest_is_bounded", all((_finite(r.get("interest_score")) is not None and 0.0 <= float(r.get("interest_score")) <= 100.0) for r in quality_rows), "Interest is deterministic utility on a 0-100 display scale.")
    add("offer_quality_components_are_bounded", all(all(_finite(r.get(k)) is not None and 0.0 <= float(r.get(k)) <= 100.0 for k in ("salary_score","role_score","winning_score","security_score","career_fit_score")) for r in quality_rows), "All component scores must remain on the 0-100 player-decision scale.")
    add("offer_quality_gap_to_acceptance_is_exact", all(math.isclose(float(r.get("gap_to_acceptance")), float(r.get("interest_score"))-float(r.get("acceptance_threshold")), abs_tol=0.002) for r in quality_rows), "Interest minus acceptance threshold must equal exported gap.")
    add("offer_quality_decision_status_is_supported", all(_clean(r.get("player_decision_status")) in {"accept","counter","decline"} for r in quality_rows), "Only current Player Decisions V1 outcomes are allowed.")
    add("offer_quality_accept_flag_matches_status", all(bool(r.get("accepted")) == (_clean(r.get("player_decision_status")) == "accept") for r in quality_rows), "Accepted boolean must exactly match ACCEPT status.")
    add("offer_quality_market_reference_is_positive", all((_finite(r.get("market_salary_reference")) or 0.0) > 0.0 for r in quality_rows), "Every evaluated offer needs a positive market salary reference.")
    add("offer_quality_salary_ratio_is_finite_nonnegative", all((_finite(r.get("salary_to_market_ratio")) is not None and float(r.get("salary_to_market_ratio")) >= 0.0) for r in quality_rows), "Salary/reference ratio must be finite and nonnegative.")
    add("player_preference_weights_sum_to_one", all(math.isclose(sum(float(r.get(k) or 0.0) for k in ("money_weight","role_weight","winning_weight","security_weight","career_fit_weight")), 1.0, abs_tol=1e-5) for r in profile_rows), "Player motivation weights must remain normalized.")
    add("player_profiles_are_unique_by_player", len({_clean(r.get("player_id")) for r in profile_rows}) == len(profile_rows), "One deterministic motivation profile per evaluated free agent.")
    add("market_quality_offer_counts_reconcile", sum(int(r.get("offer_count") or 0) for r in market_quality_rows) == len(quality_rows), "Per-market offer counts must reconcile to offer-quality rows.")
    add("offer_quality_same_state_replay_is_exact", bool(quality_fingerprint) and quality_fingerprint == repeat_quality_fingerprint, "Same state and same CPU board inputs must reproduce the exact offer-quality fingerprint.")
    add("quality_flags_are_watch_only", all(_clean(r.get("status")) == "WATCH" for r in quality_flags), "Behavioral diagnostics are WATCH-only until calibrated thresholds are explicitly promoted.")
    add("offer_quality_is_not_labeled_as_probability", all("probability" not in _clean(k).lower() for r in quality_rows[:1] for k in r.keys()), "Interest utility must never be mislabeled as signing probability.")
    mse_rows = [r for r in quality_rows if _clean(r.get("financial_route")) == "minimum_salary_exception"]
    non_mse_rows = [r for r in quality_rows if _clean(r.get("financial_route")) != "minimum_salary_exception"]
    add("minimum_exception_targeting_metadata_is_complete", all(_clean(r.get("minimum_targeting_status")) == "allow" and _finite(r.get("minimum_targeting_score")) is not None and bool(_clean(r.get("minimum_targeting_reason_code"))) for r in mse_rows), "Every submitted MSE bid must carry an explicit allow decision, credibility score, and reason from the targeting gate.")
    add("minimum_exception_targeting_does_not_relabel_other_routes", all(_clean(r.get("minimum_targeting_status")) in {"", "not_applicable"} for r in non_mse_rows), "Pure-cap and Bird-family bids must remain outside the MSE targeting gate.")
    add("minimum_exception_targeting_interest_matches_player_decision", all((_finite(r.get("minimum_targeting_interest")) is not None and math.isclose(float(r.get("minimum_targeting_interest")), float(r.get("interest_score")), abs_tol=0.002)) for r in mse_rows), "The targeting gate must use the exact same deterministic player-interest evaluation exported by the audit.")
    add("minimum_exception_targeting_gap_matches_player_decision", all((_finite(r.get("minimum_targeting_gap")) is not None and math.isclose(float(r.get("minimum_targeting_gap")), float(r.get("gap_to_acceptance")), abs_tol=0.002)) for r in mse_rows), "The targeting gate acceptance gap must exactly match Player Decisions V1.")
    return checks


def _persistent_exports(state: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    payload = _raw_calendar_payload(state)
    active = dict(payload.get("active_markets", {}) or {}) if isinstance(payload.get("active_markets", {}), Mapping) else {}
    archived = list(payload.get("archived_markets", []) or []) if isinstance(payload.get("archived_markets", []), list) else []
    market_rows: list[dict[str, Any]] = []
    round_rows: list[dict[str, Any]] = []
    cpu_rows: list[dict[str, Any]] = []
    eval_rows: list[dict[str, Any]] = []
    day_rows: list[dict[str, Any]] = []

    combined: list[tuple[str, str, Mapping[str, Any]]] = []
    for market_id, record in active.items():
        if isinstance(record, Mapping):
            combined.append(("active", _clean(market_id), record))
    for index, record in enumerate(archived):
        if isinstance(record, Mapping):
            combined.append(("archived", _clean(record.get("market_id", "")) or f"ARCHIVED-{index+1}", record))

    for storage_status, market_id, record in combined:
        offer = dict(record.get("offer", {}) or {}) if isinstance(record.get("offer", {}), Mapping) else {}
        market_rows.append({
            "storage_status": storage_status,
            "market_id": market_id,
            "season_label": _clean(record.get("season_label", "")),
            "player_id": _clean(record.get("player_id", "")),
            "player_name": _clean(record.get("player_name", "")),
            "user_team_abbreviation": _team(record.get("user_team_abbreviation", "")),
            "annual_salary": _finite(offer.get("annual_salary")),
            "years": offer.get("years"),
            "guaranteed": bool(offer.get("guaranteed", False)),
            "option_type": _clean(offer.get("option_type", "")),
            "created_day": record.get("created_day"),
            "last_updated_day": record.get("last_updated_day"),
            "current_round": record.get("current_round"),
            "max_rounds": record.get("max_rounds"),
            "status": _clean(record.get("status", "")),
            "player_response": _clean(record.get("player_response", "")),
            "winner_team_abbreviation": _team(record.get("winner_team_abbreviation", "")) or None,
            "winner_utility_score": _finite(record.get("winner_utility_score")),
            "winning_margin": _finite(record.get("winning_margin")),
            "active_cpu_offer_count": record.get("active_cpu_offer_count"),
            "source_state_fingerprint": _clean(record.get("source_state_fingerprint", "")),
            "user_offer_fingerprint": _clean(record.get("user_offer_fingerprint", "")),
            "base_cpu_board_fingerprint": _clean(record.get("base_cpu_board_fingerprint", "")),
            "negotiation_fingerprint": _clean(record.get("negotiation_fingerprint", "")),
            "market_fingerprint": _clean(record.get("market_fingerprint", "")),
        })
        for row in list(record.get("round_history", []) or []):
            if not isinstance(row, Mapping):
                continue
            out = {"storage_status": storage_status, "market_id": market_id}
            out.update(_json_safe(row))
            round_rows.append(out)
        for row in list(record.get("current_cpu_offers", []) or []):
            if not isinstance(row, Mapping):
                continue
            out = {"storage_status": storage_status, "market_id": market_id, "player_id": _clean(record.get("player_id", ""))}
            out.update(_json_safe(row))
            cpu_rows.append(out)
        for row in list(record.get("current_evaluations", []) or []):
            if not isinstance(row, Mapping):
                continue
            out = {"storage_status": storage_status, "market_id": market_id, "player_id": _clean(record.get("player_id", ""))}
            out.update(_json_safe(row))
            eval_rows.append(out)

    for row in list(payload.get("day_history", []) or []):
        if isinstance(row, Mapping):
            day_rows.append(_json_safe(row))
    return market_rows, round_rows, cpu_rows, eval_rows, day_rows


def _transaction_exports(state: Any, trade_state: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    transactions: list[dict[str, Any]] = []
    history = getattr(state, "free_agency_transaction_history", None)
    if isinstance(history, list):
        for row in history:
            if not isinstance(row, Mapping):
                continue
            transactions.append({
                "transaction_id": _clean(row.get("transaction_id", "")),
                "offer_id": _clean(row.get("offer_id", "")),
                "player_id": _clean(row.get("player_id", "")),
                "player_name": _clean(row.get("player_name", "")),
                "team_abbreviation": _team(row.get("team_abbreviation", "")),
                "annual_salary": _finite(row.get("annual_salary")),
                "years": row.get("years"),
                "guaranteed": row.get("guaranteed"),
                "option_type": _clean(row.get("option_type", "")),
                "financial_gate_status": _clean(row.get("financial_gate_status", "")),
                "execution_actor": _clean(row.get("execution_actor", "")) or "user_or_legacy",
                "competing_market_fingerprint": _clean(row.get("competing_market_fingerprint", "")),
                "source_fingerprint": _clean(row.get("source_fingerprint", "")),
                "candidate_fingerprint": _clean(row.get("candidate_fingerprint", "")),
                "raw_json": _json_safe(row),
            })
    overrides_rows: list[dict[str, Any]] = []
    overrides = getattr(trade_state, "free_agency_contract_overrides", None)
    if isinstance(overrides, Mapping):
        for player_id, row in overrides.items():
            payload = row if isinstance(row, Mapping) else {"value": row}
            out = {"player_id": _clean(player_id)}
            out.update(_json_safe(payload))
            overrides_rows.append(out)
    return transactions, overrides_rows


def _watch_metrics(
    *,
    team_rows: list[dict[str, Any]],
    target_rows: list[dict[str, Any]],
    offer_rows: list[dict[str, Any]],
    skipped_rows: list[dict[str, Any]],
    market_rows: list[dict[str, Any]],
    evaluation_rows: list[dict[str, Any]],
    persistent_market_rows: list[dict[str, Any]],
    persistent_round_rows: list[dict[str, Any]],
    persistent_cpu_rows: list[dict[str, Any]],
    transaction_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    def add(name: str, value: Any, note: str) -> None:
        metrics.append({"metric": name, "value": value, "status": "WATCH", "note": note})

    cpu_teams = [row for row in team_rows if not bool(row.get("is_user_controlled"))]
    add("cpu_team_count", len(cpu_teams), "Expected to reflect all non-user-controlled teams in the current franchise.")
    plan_direction_counts: dict[str, int] = {}
    for row in cpu_teams:
        label = _clean(row.get("team_direction")) or "Unresolved"
        plan_direction_counts[label] = plan_direction_counts.get(label, 0) + 1
    offer_direction_counts: dict[str, int] = {}
    for row in offer_rows:
        label = _clean(row.get("team_direction")) or "Unresolved"
        offer_direction_counts[label] = offer_direction_counts.get(label, 0) + 1
    add("cpu_plan_direction_distribution", json.dumps(plan_direction_counts, sort_keys=True), "Distribution of resolved CPU Front Office strategy labels.")
    add("cpu_offer_direction_distribution", json.dumps(offer_direction_counts, sort_keys=True), "Distribution of strategy labels actually propagated into generated CPU bids.")
    add("cpu_free_agent_target_rows", len([r for r in target_rows if not bool(r.get("is_user_controlled"))]), "Raw CPU free-agent target-board depth.")
    add("generated_legal_cpu_bids", len(offer_rows), "Backend-PASS CPU bids across pure cap and explicitly supported exception routes.")
    route_counts: dict[str, int] = {}
    for row in offer_rows:
        route = _clean(row.get("financial_route")) or "unknown"
        route_counts[route] = route_counts.get(route, 0) + 1
    add("cpu_financial_route_distribution", json.dumps(route_counts, sort_keys=True), "Distribution of pure-cap and explicitly supported exception routes in generated CPU bids.")
    add(
        "cpu_term_fallback_count",
        sum(bool(row.get("term_fallback_applied")) for row in offer_rows),
        "Strategically preferred terms shortened only when the locked V1.3 salary floor could not certify the longer horizon.",
    )
    add("skipped_cpu_bid_attempts", len(skipped_rows), "Skipped targets are useful for diagnosing cap-space and data limitations.")
    add("cpu_player_markets", len(market_rows), "Distinct player markets formed from generated CPU bids.")
    accepted_markets = [row for row in market_rows if _clean(row.get("market_status")) == "winner_selected"]
    add("accepted_cpu_winner_markets", len(accepted_markets), "Markets with at least one accepted CPU destination.")
    if offer_rows:
        avg_fit = sum(float(row.get("target_fit_score") or 0.0) for row in offer_rows) / len(offer_rows)
        avg_salary = sum(float(row.get("annual_salary") or 0.0) for row in offer_rows) / len(offer_rows)
        add("average_generated_cpu_target_fit", round(avg_fit, 3), "Track across versions to ensure bid generation remains aligned with target quality.")
        add("average_generated_cpu_salary", round(avg_salary, 2), "Track across offseason soaks and salary-model changes.")
    else:
        add("average_generated_cpu_target_fit", None, "No generated CPU offers in this audit snapshot.")
        add("average_generated_cpu_salary", None, "No generated CPU offers in this audit snapshot.")

    accepted_evals = [row for row in evaluation_rows if bool(row.get("accepted"))]
    if accepted_evals:
        highest_salary_by_player: dict[str, float] = {}
        winner_salary_by_player: dict[str, float] = {}
        for row in evaluation_rows:
            pid = _clean(row.get("player_id"))
            salary = float(row.get("annual_salary") or 0.0)
            highest_salary_by_player[pid] = max(highest_salary_by_player.get(pid, 0.0), salary)
            if int(row.get("rank") or 0) == 1 and bool(row.get("accepted")):
                winner_salary_by_player[pid] = salary
        comparable = [pid for pid in winner_salary_by_player if pid in highest_salary_by_player]
        if comparable:
            same = sum(1 for pid in comparable if math.isclose(winner_salary_by_player[pid], highest_salary_by_player[pid], abs_tol=0.01))
            add("highest_salary_wins_share_pct", round(100.0 * same / len(comparable), 2), "Should not mechanically converge to 100% because player utility includes role, winning, security and career fit.")

    cpu_actions = [_clean(row.get("action")).lower() for row in persistent_cpu_rows]
    if cpu_actions:
        add("persistent_cpu_raise_count", sum(action == "increase" for action in cpu_actions), "Track how often CPU teams escalate during active negotiations.")
        add("persistent_cpu_withdraw_count", sum(action == "withdraw" for action in cpu_actions), "Track withdrawal frequency across full offseason soaks.")
        add("persistent_cpu_hold_count", sum(action in {"hold", "open"} for action in cpu_actions), "Track passive bid behavior across rounds.")
    else:
        add("persistent_cpu_raise_count", 0, "No persistent offseason markets are active in this snapshot.")
        add("persistent_cpu_withdraw_count", 0, "No persistent offseason markets are active in this snapshot.")
        add("persistent_cpu_hold_count", 0, "No persistent offseason markets are active in this snapshot.")

    add("persistent_active_or_archived_markets", len(persistent_market_rows), "Persistent market volume should be examined during real offseason calendar runs.")
    add("persistent_round_history_rows", len(persistent_round_rows), "Round-history growth is a key soak-test signal.")
    add("fatx_transaction_count", len(transaction_rows), "Use alongside offseason day and team payroll changes once real FA execution begins.")
    return metrics


def _behavioral_checks(
    *,
    controlled: set[str],
    team_rows: list[dict[str, Any]],
    offer_rows: list[dict[str, Any]],
    board_fingerprint: str,
    repeat_board_fingerprint: str,
    market_rows: list[dict[str, Any]],
    repeat_market_fingerprints: tuple[str, ...],
    persistent_market_rows: list[dict[str, Any]],
    persistent_cpu_rows: list[dict[str, Any]],
    transaction_rows: list[dict[str, Any]],
    live_state: Any,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    def add(check_id: str, passed: bool, detail: str, severity: str = "strict") -> None:
        checks.append({
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "severity": severity,
            "detail": detail,
        })

    add(
        "controlled_teams_never_receive_cpu_bids",
        all(_team(row.get("team_abbreviation")) not in controlled for row in offer_rows),
        f"Controlled teams: {', '.join(sorted(controlled)) or 'none'}.",
    )
    plan_direction_by_team = {
        _team(row.get("team_abbreviation")): _clean(row.get("team_direction"))
        for row in team_rows
        if _team(row.get("team_abbreviation"))
    }
    direction_rows_ok = all(
        _clean(row.get("team_direction"))
        and _clean(row.get("team_direction")) == plan_direction_by_team.get(_team(row.get("team_abbreviation")), "")
        for row in offer_rows
    )
    add(
        "cpu_offer_direction_matches_front_office_plan",
        direction_rows_ok,
        "Every generated bid must carry the same resolved strategy direction as its current CPU Front Office team plan.",
    )
    pairs = [(_team(row.get("team_abbreviation")), _clean(row.get("player_id"))) for row in offer_rows]
    add(
        "no_duplicate_cpu_team_player_bids",
        len(pairs) == len(set(pairs)),
        f"Generated CPU bid rows: {len(pairs)}.",
    )
    add(
        "all_generated_cpu_bids_are_backend_pass",
        all(_clean(row.get("backend_status")).lower() == "pass" and bool(row.get("backend_can_commit")) for row in offer_rows),
        "Every emitted CPU bid must already clear the locked free-agency preview stack.",
    )
    add(
        "generated_cpu_term_fallback_only_shortens_requested_term",
        all(
            int(row.get("years") or 0) >= 1
            and int(row.get("strategic_requested_years") or row.get("years") or 0) >= int(row.get("years") or 0)
            for row in offer_rows
        ),
        "A legality fallback may shorten a strategic term but can never lengthen it.",
    )
    salary_bounds_ok = True
    route_legality_ok = True
    minimum_exception_ok = True
    rights_destination_ok = True
    supported_routes = {
        "pure_cap_space_only",
        "minimum_salary_exception",
        "bird_exception",
        "early_bird_exception",
        "non_bird_exception",
    }
    for row in offer_rows:
        salary = _finite(row.get("annual_salary"))
        minimum = _finite(row.get("minimum_salary_floor"))
        maximum = _finite(row.get("maximum_initial_salary"))
        cap_space = _finite(row.get("cap_space_before"))
        years = int(row.get("years") or 0)
        route = _clean(row.get("financial_route")) or "pure_cap_space_only"
        if salary is None or minimum is None or maximum is None or salary + 0.01 < minimum or salary - 0.01 > maximum:
            salary_bounds_ok = False
        if route not in supported_routes:
            route_legality_ok = False
        if route == "pure_cap_space_only":
            if salary is None or cap_space is None or salary - 0.01 > cap_space:
                route_legality_ok = False
        elif route == "minimum_salary_exception":
            if salary is None or minimum is None or years != 1 or not math.isclose(salary, minimum, abs_tol=0.01):
                minimum_exception_ok = False
                route_legality_ok = False
        elif route in {"bird_exception", "early_bird_exception", "non_bird_exception"}:
            if _team(row.get("team_abbreviation")) != _team(row.get("prior_team")) or _clean(row.get("rights_classification")) in {"", "unknown"}:
                rights_destination_ok = False
                route_legality_ok = False
    add("generated_cpu_salaries_respect_exported_route_bounds", salary_bounds_ok, "All generated annual salaries must stay within the route-specific exported minimum/maximum bounds.")
    add("generated_cpu_financial_routes_are_explicit_and_legal", route_legality_ok, "Pure-cap bids must fit cap space, minimum-exception bids must be exact one-year minimums, and Bird-family bids must target the proven prior team.")
    add("minimum_exception_cpu_bids_are_exact_one_year_minimum", minimum_exception_ok, "V1 auto-releases only exact one-year minimum-salary exception bids because ContractState currently stores one flat annual salary.")
    add("prior_team_rights_bids_target_proven_prior_team", rights_destination_ok, "Bird-family CPU bids may only use the explicitly proven prior-team destination.")
    add("cpu_offer_board_is_deterministic", bool(board_fingerprint) and board_fingerprint == repeat_board_fingerprint, "The same state and target boards must reproduce the same CPU offer board fingerprint.")
    market_fps = tuple(_clean(row.get("market_fingerprint")) for row in market_rows)
    add("cpu_player_markets_are_deterministic", market_fps == repeat_market_fingerprints, "The same CPU board must reproduce identical player-market fingerprints.")

    persistent_ids = [_clean(row.get("market_id")) for row in persistent_market_rows if _clean(row.get("market_id"))]
    add("persistent_market_ids_are_unique", len(persistent_ids) == len(set(persistent_ids)), f"Persistent market records inspected: {len(persistent_ids)}.")
    rounds_ok = True
    for row in persistent_market_rows:
        current = int(row.get("current_round") or 0)
        maximum = int(row.get("max_rounds") or MAX_FREE_AGENCY_NEGOTIATION_ROUNDS)
        if current < 0 or current > maximum or maximum != MAX_FREE_AGENCY_NEGOTIATION_ROUNDS:
            rounds_ok = False
    add("persistent_negotiation_rounds_remain_bounded", rounds_ok, f"Maximum negotiation rounds expected: {MAX_FREE_AGENCY_NEGOTIATION_ROUNDS}.")
    add(
        "persistent_cpu_offers_exclude_controlled_teams",
        all(_team(row.get("team_abbreviation")) not in controlled for row in persistent_cpu_rows),
        "Current persisted CPU offers may never be owned by a user-controlled team.",
    )
    persistent_salary_ok = True
    increase_ok = True
    for row in persistent_cpu_rows:
        salary = _finite(row.get("annual_salary"))
        minimum = _finite(row.get("minimum_salary_floor"))
        maximum = _finite(row.get("maximum_initial_salary"))
        cap_space = _finite(row.get("cap_space_before"))
        if salary is None or minimum is None or maximum is None or cap_space is None:
            persistent_salary_ok = False
        elif salary + 0.01 < minimum or salary - 0.01 > maximum or salary - 0.01 > cap_space:
            persistent_salary_ok = False
        if _clean(row.get("action")).lower() == "increase":
            prior = _finite(row.get("prior_salary"))
            if prior is None or salary is None or salary + 0.01 < prior:
                increase_ok = False
    add("persistent_cpu_offers_remain_salary_and_cap_legal", persistent_salary_ok, "Persisted current CPU bids must remain inside their recorded legal and affordable bounds.")
    add("persistent_cpu_increases_never_reduce_salary", increase_ok, "An INCREASE action may never reduce annual salary.")

    fatx_ids = [_clean(row.get("transaction_id")) for row in transaction_rows if _clean(row.get("transaction_id"))]
    add("fatx_transaction_ids_are_unique", len(fatx_ids) == len(set(fatx_ids)), f"FATX rows inspected: {len(fatx_ids)}.")
    add(
        "cpu_fatx_never_targets_controlled_team",
        all(not (_clean(row.get("execution_actor")) == "cpu_front_office" and _team(row.get("team_abbreviation")) in controlled) for row in transaction_rows),
        "CPU execution metadata must never show a user-controlled destination.",
    )

    players = dict(getattr(live_state, "players", {}) or {})
    free_ids = {_clean(value) for value in getattr(live_state, "free_agent_player_ids", ())}
    pool_consistent = True
    for player_id in free_ids:
        player = players.get(player_id)
        if player is None:
            pool_consistent = False
            continue
        team = _team(getattr(player, "team_abbreviation", ""))
        roster_status = _clean(getattr(player, "roster_status", "")).lower()
        if team or (roster_status and roster_status != "free_agent"):
            pool_consistent = False
    add("free_agent_pool_has_no_currently_owned_players", pool_consistent, "Every current free-agent-pool entry should be unassigned and marked free_agent when status is available.")
    return checks


def build_free_agency_cpu_ai_audit(
    *,
    output_dir: str | Path | None = None,
    max_targets_per_team: int = 5,
    checkpoint: Any | None = None,
    checkpoint_path: str | Path | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> FreeAgencyCPUAuditBuildResult:
    def progress(message: str) -> None:
        if progress_callback is not None:
            progress_callback(message)

    progress("[1/8] Loading canonical checkpoint and protected-state fingerprints...")
    load_fn, default_checkpoint_path = _checkpoint_contract()
    path = Path(checkpoint_path) if checkpoint_path is not None else default_checkpoint_path
    durable = checkpoint if checkpoint is not None else load_fn()
    if durable is None:
        raise FreeAgencyCPUAuditError("The durable franchise checkpoint could not be loaded.")
    live_state = getattr(durable, "simulation_state", None)
    trade_state = getattr(durable, "trade_state", None)
    if live_state is None or trade_state is None:
        raise FreeAgencyCPUAuditError("Checkpoint is missing simulation_state or trade_state.")

    checkpoint_hash_before = _sha256(path)
    state_fp_before = free_agency_state_fingerprint(live_state)
    trade_fp_before = trade_state_fingerprint(trade_state)
    calendar_fp_before = persistent_calendar_fingerprint(live_state)
    controlled = tuple(sorted(controlled_teams_from_durable_checkpoint(durable)))
    controlled_set = set(controlled)

    progress("[2/8] Building isolated-offseason CPU front-office plans and legal offers...")
    analysis_state = _isolated_offseason_state(live_state)
    analysis_phase = _phase(analysis_state)
    front_plan = _front_office_plan(analysis_state, controlled)
    board = build_cpu_free_agency_offer_board(
        analysis_state,
        controlled_teams=controlled,
        front_office_plan=front_plan,
        max_targets_per_team=max_targets_per_team,
    )
    markets = build_cpu_competing_markets(analysis_state, board)
    progress(f"      Generated {len(getattr(board, 'offers', ()))} legal CPU bid(s) across {len(markets)} player market(s).")
    progress("[3/8] Evaluating player interest, market value, roster construction, and offer economic credibility...")
    quality_rows, profile_rows = _offer_quality_exports(analysis_state, board)

    # Determinism repeats use the same deep-copied analysis state and front-office plan.
    progress("[4/8] Replaying the same-state market for exact determinism...")
    repeat_board = build_cpu_free_agency_offer_board(
        analysis_state,
        controlled_teams=controlled,
        front_office_plan=front_plan,
        max_targets_per_team=max_targets_per_team,
    )
    repeat_markets = build_cpu_competing_markets(analysis_state, repeat_board)
    repeat_quality_rows, _ = _offer_quality_exports(analysis_state, repeat_board)
    quality_fp = _quality_fingerprint(quality_rows)
    repeat_quality_fp = _quality_fingerprint(repeat_quality_rows)

    progress("[5/8] Building market/roster realism summaries and diagnostic WATCH flags...")
    team_rows, target_rows = _front_office_exports(front_plan, controlled_set)
    offer_rows, skipped_rows = _offer_exports(board)
    roster_construction_rows, roster_construction_flag_rows = _roster_construction_exports(offer_rows, skipped_rows)
    offer_economic_rows, offer_economic_flag_rows = _offer_economic_exports(offer_rows, skipped_rows)
    market_rows, evaluation_rows = _market_exports(markets)
    market_quality_rows = _market_quality_exports(quality_rows, market_rows)
    quality_flag_rows = _quality_flags(quality_rows, market_quality_rows)
    persistent_market_rows, persistent_round_rows, persistent_cpu_rows, persistent_eval_rows, day_rows = _persistent_exports(live_state)
    transaction_rows, override_rows = _transaction_exports(live_state, trade_state)

    repeat_market_fps = tuple(
        _clean(getattr(getattr(row, "market", row), "market_fingerprint", ""))
        for row in repeat_markets
    )
    progress("[6/8] Running strict safety/determinism checks and realism diagnostics...")
    checks = _behavioral_checks(
        controlled=controlled_set,
        team_rows=team_rows,
        offer_rows=offer_rows,
        board_fingerprint=_clean(getattr(board, "board_fingerprint", "")),
        repeat_board_fingerprint=_clean(getattr(repeat_board, "board_fingerprint", "")),
        market_rows=market_rows,
        repeat_market_fingerprints=repeat_market_fps,
        persistent_market_rows=persistent_market_rows,
        persistent_cpu_rows=persistent_cpu_rows,
        transaction_rows=transaction_rows,
        live_state=live_state,
    )
    checks.extend(_quality_behavioral_checks(
        offer_rows=offer_rows,
        quality_rows=quality_rows,
        profile_rows=profile_rows,
        market_quality_rows=market_quality_rows,
        quality_flags=quality_flag_rows,
        quality_fingerprint=quality_fp,
        repeat_quality_fingerprint=repeat_quality_fp,
    ))
    checks.extend(_roster_construction_behavioral_checks(
        offer_rows=offer_rows,
        skipped_rows=skipped_rows,
        roster_rows=roster_construction_rows,
        roster_flags=roster_construction_flag_rows,
    ))
    checks.extend(_offer_economic_behavioral_checks(
        offer_rows=offer_rows,
        skipped_rows=skipped_rows,
        economic_rows=offer_economic_rows,
        economic_flags=offer_economic_flag_rows,
        quality_rows=quality_rows,
    ))
    watch_rows = _watch_metrics(
        team_rows=team_rows,
        target_rows=target_rows,
        offer_rows=offer_rows,
        skipped_rows=skipped_rows,
        market_rows=market_rows,
        evaluation_rows=evaluation_rows,
        persistent_market_rows=persistent_market_rows,
        persistent_round_rows=persistent_round_rows,
        persistent_cpu_rows=persistent_cpu_rows,
        transaction_rows=transaction_rows,
    )
    watch_rows.extend(_quality_watch_metrics(quality_rows, profile_rows, market_quality_rows, quality_flag_rows, skipped_rows))
    watch_rows.extend(_roster_construction_watch_metrics(roster_construction_rows, skipped_rows, roster_construction_flag_rows))
    watch_rows.extend(_offer_economic_watch_metrics(offer_economic_rows, skipped_rows, offer_economic_flag_rows))

    checkpoint_hash_after_analysis = _sha256(path)
    state_fp_after = free_agency_state_fingerprint(live_state)
    trade_fp_after = trade_state_fingerprint(trade_state)
    calendar_fp_after = persistent_calendar_fingerprint(live_state)
    read_only_ok = (
        checkpoint_hash_before == checkpoint_hash_after_analysis
        and state_fp_before == state_fp_after
        and trade_fp_before == trade_fp_after
        and calendar_fp_before == calendar_fp_after
    )
    checks.append({
        "check_id": "audit_generation_is_read_only",
        "status": "PASS" if read_only_ok else "FAIL",
        "severity": "strict",
        "detail": "Checkpoint hash plus simulation, Trade Machine and persistent-calendar fingerprints must remain unchanged during export generation.",
    })

    failed = tuple(row["check_id"] for row in checks if row["status"] == "FAIL" and row["severity"] == "strict")
    strict_pass = not failed

    out_root = Path(output_dir) if output_dir is not None else Path("outputs") / "audits"
    out_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    season_label = _season(live_state) or "unknown-season"
    export_id = f"franchise_free_agency_cpu_ai_audit_{season_label}_{stamp}"
    zip_path = out_root / f"{export_id}.zip"

    progress("[7/8] Packaging audit CSV/JSON exports...")
    with tempfile.TemporaryDirectory(prefix="fa_cpu_ai_audit_") as tmp:
        root = Path(tmp) / export_id
        root.mkdir(parents=True, exist_ok=True)

        exports = {
            "behavioral_checks.csv": checks,
            "watch_metrics.csv": watch_rows,
            "cpu_front_office_team_plans.csv": team_rows,
            "cpu_free_agent_targets.csv": target_rows,
            "cpu_free_agency_offers.csv": offer_rows,
            "cpu_free_agency_skipped_bids.csv": skipped_rows,
            "cpu_free_agency_player_markets.csv": market_rows,
            "cpu_free_agency_market_evaluations.csv": evaluation_rows,
            "cpu_free_agency_offer_quality.csv": quality_rows,
            "cpu_free_agency_player_profiles.csv": profile_rows,
            "cpu_free_agency_market_quality.csv": market_quality_rows,
            "cpu_free_agency_quality_flags.csv": quality_flag_rows,
            "cpu_free_agency_roster_construction.csv": roster_construction_rows,
            "cpu_free_agency_roster_construction_flags.csv": roster_construction_flag_rows,
            "cpu_free_agency_offer_economics.csv": offer_economic_rows,
            "cpu_free_agency_offer_economic_flags.csv": offer_economic_flag_rows,
            "persistent_free_agency_markets.csv": persistent_market_rows,
            "persistent_free_agency_round_history.csv": persistent_round_rows,
            "persistent_free_agency_cpu_actions.csv": persistent_cpu_rows,
            "persistent_free_agency_evaluations.csv": persistent_eval_rows,
            "persistent_free_agency_day_history.csv": day_rows,
            "free_agency_transactions.csv": transaction_rows,
            "trade_state_contract_overrides.csv": override_rows,
        }
        for filename, rows in exports.items():
            _write_csv(root / filename, rows)

        summary = {
            "audit_version": FREE_AGENCY_CPU_AI_AUDIT_VERSION,
            "offer_quality_version": FREE_AGENCY_CPU_AI_AUDIT_OFFER_QUALITY_VERSION,
            "offer_quality_schema_version": FREE_AGENCY_CPU_AI_AUDIT_OFFER_QUALITY_SCHEMA_VERSION,
            "interest_meter_version": FREE_AGENCY_INTEREST_METER_VERSION,
            "roster_construction_audit_version": FREE_AGENCY_CPU_AI_AUDIT_ROSTER_CONSTRUCTION_VERSION,
            "roster_construction_schema_version": FREE_AGENCY_CPU_AI_AUDIT_ROSTER_CONSTRUCTION_SCHEMA_VERSION,
            "cpu_roster_construction_adapter_version": CPU_FREE_AGENCY_ROSTER_CONSTRUCTION_ADAPTER_VERSION,
            "cpu_roster_construction_version": CPU_FREE_AGENCY_ROSTER_CONSTRUCTION_VERSION,
            "offer_economic_audit_version": FREE_AGENCY_CPU_AI_AUDIT_OFFER_ECONOMIC_VERSION,
            "offer_economic_schema_version": FREE_AGENCY_CPU_AI_AUDIT_OFFER_ECONOMIC_SCHEMA_VERSION,
            "cpu_offer_economic_adapter_version": CPU_FREE_AGENCY_OFFER_ECONOMIC_ADAPTER_VERSION,
            "cpu_offer_economic_intelligence_version": CPU_FREE_AGENCY_OFFER_ECONOMIC_INTELLIGENCE_VERSION,
            "offer_quality_fingerprint": quality_fp,
            "schema_version": FREE_AGENCY_CPU_AI_AUDIT_SCHEMA_VERSION,
            "scope": FREE_AGENCY_CPU_AI_AUDIT_SCOPE,
            "export_id": export_id,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "season_label": season_label,
            "live_phase": _phase(live_state),
            "analysis_phase": analysis_phase,
            "analysis_uses_isolated_offseason_copy": _phase(live_state) != "offseason",
            "controlled_teams": list(controlled),
            "checkpoint_path": str(path),
            "checkpoint_sha256": checkpoint_hash_before,
            "free_agency_state_fingerprint": state_fp_before,
            "trade_state_fingerprint": trade_fp_before,
            "persistent_calendar_fingerprint": calendar_fp_before,
            "calendar_snapshot": _json_safe(free_agency_calendar_snapshot(live_state)),
            "cpu_offer_board_fingerprint": _clean(getattr(board, "board_fingerprint", "")),
            "cpu_offer_generation_version": CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
            "cpu_direction_adapter_version": CPU_FREE_AGENCY_DIRECTION_ADAPTER_VERSION,
            "cpu_term_feasibility_version": CPU_FREE_AGENCY_TERM_FEASIBILITY_VERSION,
            "cpu_minimum_targeting_adapter_version": CPU_FREE_AGENCY_MINIMUM_TARGETING_ADAPTER_VERSION,
            "cpu_minimum_exception_targeting_version": CPU_FREE_AGENCY_MINIMUM_EXCEPTION_TARGETING_VERSION,
            "cpu_offer_economic_adapter_version_runtime": CPU_FREE_AGENCY_OFFER_ECONOMIC_ADAPTER_VERSION,
            "cpu_offer_economic_intelligence_version_runtime": CPU_FREE_AGENCY_OFFER_ECONOMIC_INTELLIGENCE_VERSION,
            "negotiation_rounds_version": FREE_AGENCY_NEGOTIATION_ROUNDS_VERSION,
            "persistent_calendar_version": FREE_AGENCY_PERSISTENT_CALENDAR_VERSION,
            "player_decision_version": FREE_AGENCY_PLAYER_DECISION_VERSION,
            "live_signing_version": FREE_AGENCY_LIVE_SIGNING_VERSION,
            "strict_pass": strict_pass,
            "failed_checks": list(failed),
            "row_counts": {name: len(rows) for name, rows in exports.items()},
        }
        (root / "audit_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )

        manifest_rows = [
            {"key": "audit_version", "value": FREE_AGENCY_CPU_AI_AUDIT_VERSION},
            {"key": "offer_quality_version", "value": FREE_AGENCY_CPU_AI_AUDIT_OFFER_QUALITY_VERSION},
            {"key": "offer_quality_schema_version", "value": FREE_AGENCY_CPU_AI_AUDIT_OFFER_QUALITY_SCHEMA_VERSION},
            {"key": "interest_meter_version", "value": FREE_AGENCY_INTEREST_METER_VERSION},
            {"key": "offer_quality_fingerprint", "value": quality_fp},
            {"key": "schema_version", "value": FREE_AGENCY_CPU_AI_AUDIT_SCHEMA_VERSION},
            {"key": "scope", "value": FREE_AGENCY_CPU_AI_AUDIT_SCOPE},
            {"key": "export_id", "value": export_id},
            {"key": "season_label", "value": season_label},
            {"key": "live_phase", "value": _phase(live_state)},
            {"key": "analysis_phase", "value": analysis_phase},
            {"key": "controlled_teams", "value": ",".join(controlled)},
            {"key": "checkpoint_path", "value": str(path)},
            {"key": "checkpoint_sha256", "value": checkpoint_hash_before},
            {"key": "free_agency_state_fingerprint", "value": state_fp_before},
            {"key": "trade_state_fingerprint", "value": trade_fp_before},
            {"key": "persistent_calendar_fingerprint", "value": calendar_fp_before},
            {"key": "cpu_offer_board_fingerprint", "value": _clean(getattr(board, "board_fingerprint", ""))},
            {"key": "cpu_direction_adapter_version", "value": CPU_FREE_AGENCY_DIRECTION_ADAPTER_VERSION},
            {"key": "cpu_term_feasibility_version", "value": CPU_FREE_AGENCY_TERM_FEASIBILITY_VERSION},
            {"key": "cpu_minimum_targeting_adapter_version", "value": CPU_FREE_AGENCY_MINIMUM_TARGETING_ADAPTER_VERSION},
            {"key": "cpu_minimum_exception_targeting_version", "value": CPU_FREE_AGENCY_MINIMUM_EXCEPTION_TARGETING_VERSION},
            {"key": "strict_pass", "value": strict_pass},
            {"key": "failed_checks", "value": ",".join(failed)},
        ]
        for name, rows in exports.items():
            manifest_rows.append({"key": f"rows:{name}", "value": len(rows)})
        _write_csv(root / "audit_manifest.csv", manifest_rows)

        for required in REQUIRED_FILES:
            if not (root / required).exists():
                raise FreeAgencyCPUAuditError(f"Required audit export is missing: {required}")

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for file_path in sorted(root.iterdir()):
                archive.write(file_path, arcname=f"{export_id}/{file_path.name}")

    progress("[8/8] Verifying canonical checkpoint/state remained untouched...")
    checkpoint_hash_final = _sha256(path)
    if checkpoint_hash_final != checkpoint_hash_before:
        try:
            zip_path.unlink(missing_ok=True)
        finally:
            raise FreeAgencyCPUAuditError("Checkpoint changed while building the audit ZIP.")

    row_counts = {name: len(rows) for name, rows in exports.items()}
    row_counts["audit_manifest.csv"] = len(manifest_rows)
    row_counts["audit_summary.json"] = 1
    return FreeAgencyCPUAuditBuildResult(
        version=FREE_AGENCY_CPU_AI_AUDIT_VERSION,
        schema_version=FREE_AGENCY_CPU_AI_AUDIT_SCHEMA_VERSION,
        season_label=season_label,
        live_phase=_phase(live_state),
        analysis_phase=analysis_phase,
        output_zip=str(zip_path),
        zip_sha256=_sha256(zip_path),
        checkpoint_sha256=checkpoint_hash_before,
        state_fingerprint=state_fp_before,
        trade_fingerprint=trade_fp_before,
        calendar_fingerprint=calendar_fp_before,
        controlled_teams=controlled,
        strict_pass=strict_pass,
        failed_checks=failed,
        row_counts=row_counts,
    )


def audit_contract_report() -> dict[str, Any]:
    return {
        "version": FREE_AGENCY_CPU_AI_AUDIT_VERSION,
        "schema_version": FREE_AGENCY_CPU_AI_AUDIT_SCHEMA_VERSION,
        "offer_quality_version": FREE_AGENCY_CPU_AI_AUDIT_OFFER_QUALITY_VERSION,
        "offer_quality_schema_version": FREE_AGENCY_CPU_AI_AUDIT_OFFER_QUALITY_SCHEMA_VERSION,
        "interest_meter_version": FREE_AGENCY_INTEREST_METER_VERSION,
        "cpu_minimum_targeting_adapter_version": CPU_FREE_AGENCY_MINIMUM_TARGETING_ADAPTER_VERSION,
        "cpu_minimum_exception_targeting_version": CPU_FREE_AGENCY_MINIMUM_EXCEPTION_TARGETING_VERSION,
        "scope": FREE_AGENCY_CPU_AI_AUDIT_SCOPE,
        "required_files": list(REQUIRED_FILES),
        "cpu_offer_generation_version": CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
        "negotiation_rounds_version": FREE_AGENCY_NEGOTIATION_ROUNDS_VERSION,
        "persistent_calendar_version": FREE_AGENCY_PERSISTENT_CALENDAR_VERSION,
        "player_decision_version": FREE_AGENCY_PLAYER_DECISION_VERSION,
        "live_signing_version": FREE_AGENCY_LIVE_SIGNING_VERSION,
        "read_only": True,
        "isolated_offseason_analysis_when_live_not_offseason": True,
    }
