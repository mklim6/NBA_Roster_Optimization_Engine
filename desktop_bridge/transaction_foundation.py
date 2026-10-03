from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from functools import lru_cache
from typing import Any, Mapping
import copy
import hashlib
import json
import time

from freeform_trade_machine_engine_v3 import (
    load_runtime_data,
    normalize_player_id,
    normalize_team,
)
from franchise_embedded_trade_center_v2 import (
    EMBEDDED_TRADE_CENTER_VERSION,
    build_franchise_trade_preview,
    preview_to_dict,
)
from franchise_free_agency_contract_salary_legality_v1_3 import (
    FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION,
    build_contract_legal_free_agency_preview,
    evaluate_contract_legal_financial_gate,
)
from franchise_free_agency_transaction_v1 import (
    FREE_AGENCY_TRANSACTION_VERSION,
    FreeAgencyCommitResult,
    FreeAgencyOffer,
    FreeAgencyTransactionError,
    FreeAgencyTransactionPreview,
    commit_free_agency_preview,
    free_agency_state_fingerprint,
)
from franchise_live_asset_ledger_v1 import (
    ASSET_LEDGER_VERSION,
    build_live_asset_ledger,
)

from franchise_draft_engine_v1 import (
    DRAFT_ENGINE_VERSION,
    current_pick as draft_current_pick,
    draft_state as production_draft_state,
    make_selection as make_draft_selection,
)
from franchise_scouting_discovery_v1 import (
    FRANCHISE_SCOUTING_DISCOVERY_VERSION,
    MAX_FOCUS_PROSPECTS,
    advance_scouting_week_v1,
    scouting_board_rows_v1,
    scouting_summary_v1,
    set_scouting_focus_v1,
)
from franchise_staff_system_v1 import lead_scout_member
from franchise_trade_finder_ai_v1 import (
    GOAL_BEST_AVAILABLE,
    TRADE_FINDER_AI_VERSION,
    TRADE_FINDER_VALUE_MODEL_VERSION,
    generate_trade_finder_proposals,
)
from franchise_trade_transaction_v1 import (
    FRANCHISE_TRADE_TRANSACTION_VERSION,
    FranchiseTradeCandidate,
    build_franchise_trade_candidate,
)


TRANSACTION_FOUNDATION_VERSION = (
    "v3-transaction-foundation-batch-08-transactional-trade-execution-"
    "batch-09-transactional-free-agency-execution-"
    "batch-10-scouting-draft-workflow-2026-10-02"
)


@dataclass(frozen=True)
class V3FreeAgencyExecutionCandidate:
    state: Any
    preview: FreeAgencyTransactionPreview
    commit_result: FreeAgencyCommitResult

@dataclass(frozen=True)
class V3ScoutingAdvanceCandidate:
    state: Any
    team: str
    draft_year: int
    phase: str
    focus_ids: tuple[str, ...]
    action_fingerprint: str
    weeks_before: int
    weeks_after: int
    summary_after: dict[str, Any]


@dataclass(frozen=True)
class V3DraftSelectionCandidate:
    state: Any
    team: str
    draft_year: int
    prospect_id: str
    prospect_name: str
    overall_pick: int
    round_number: int
    round_pick: int
    action_fingerprint: str
    next_pick_index: int
    draft_complete: bool



@lru_cache(maxsize=1)
def _runtime() -> Any:
    return load_runtime_data()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, (str, int, float, bool)):
        return enum_value
    return str(value)


def _phase(state: Any) -> str:
    raw = getattr(state, "phase", "")
    return str(getattr(raw, "value", raw) or "").strip().lower()


def _asset_maps(ledger: Any) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    players = {
        normalize_player_id(row.get("player_id")): dict(row)
        for row in ledger.player_rows
        if normalize_player_id(row.get("player_id"))
    }
    picks = {
        str(row.get("asset_id", "") or "").strip(): dict(row)
        for row in ledger.draft_rows
        if str(row.get("asset_id", "") or "").strip()
    }
    return players, picks


def _player_asset_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "player_id": str(row.get("player_id", "")),
        "name": str(row.get("player_name", row.get("player_id", ""))),
        "team": str(row.get("team", "")),
        "position": str(row.get("position", "")),
        "age": row.get("age"),
        "overall": row.get("overall"),
        "potential": row.get("potential"),
        "future_outlook": row.get("future_outlook"),
        "role": str(row.get("role", "")),
        "salary": row.get("salary"),
        "years_remaining": row.get("years_remaining"),
        "asset_score": row.get("asset_score"),
        "availability": str(row.get("availability", "")),
        "generated_player": bool(row.get("generated_player", False)),
    }


def _pick_asset_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "asset_id": str(row.get("asset_id", "")),
        "draft_year": row.get("draft_year"),
        "round": row.get("round"),
        "origin_team": str(row.get("origin_team", "")),
        "current_owner": str(row.get("current_owner", "")),
        "display_name": str(row.get("display_name", row.get("asset_id", ""))),
        "asset_type": str(row.get("asset_type", "")),
        "protection": str(row.get("protection", "")),
        "swap_status": str(row.get("swap_status", "")),
        "encumbrance": str(row.get("encumbrance", "")),
        "stepien_status": str(row.get("stepien_status", "")),
        "tradability_status": str(row.get("tradability_status", "")),
        "manual_review_required": bool(row.get("manual_review_required", False)),
        "manual_review_reason": str(row.get("manual_review_reason", "")),
        "engine_ready": bool(row.get("engine_ready", False)),
        "forfeiture_status": str(row.get("forfeiture_status", "")),
    }


def _team_assets(ledger: Any, active_team: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    team = normalize_team(active_team)
    players = [
        _player_asset_payload(dict(row))
        for row in ledger.player_rows
        if normalize_team(row.get("team")) == team
        and str(row.get("roster_status", "")).lower() == "rostered"
    ]
    players.sort(
        key=lambda row: (
            -float(row.get("asset_score") or 0.0),
            -float(row.get("overall") or 0.0),
            str(row.get("name", "")),
        )
    )

    picks = [
        _pick_asset_payload(dict(row))
        for row in ledger.draft_rows
        if normalize_team(row.get("current_owner")) == team
        and str(row.get("forfeiture_status", "")).lower() != "forfeited"
    ]
    picks.sort(
        key=lambda row: (
            int(row.get("draft_year") or 9999),
            int(row.get("round") or 9),
            str(row.get("origin_team", "")),
            str(row.get("asset_id", "")),
        )
    )
    return players, picks


def _asset_label(asset_id: str, player_map: dict[str, dict[str, Any]], pick_map: dict[str, dict[str, Any]]) -> str:
    pid = normalize_player_id(asset_id)
    if pid in player_map:
        return str(player_map[pid].get("player_name", pid))
    if asset_id in pick_map:
        return str(pick_map[asset_id].get("display_name", asset_id))
    return str(asset_id)


def _proposal_payload(proposal: Any, player_map: dict[str, dict[str, Any]], pick_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    outgoing_ids = [
        *[str(value) for value in proposal.side_a_player_ids],
        *[str(value) for value in proposal.side_a_pick_asset_ids],
    ]
    incoming_ids = [
        *[str(value) for value in proposal.side_b_player_ids],
        *[str(value) for value in proposal.side_b_pick_asset_ids],
    ]
    preview = dict(getattr(proposal, "preview_payload", {}) or {})
    return {
        "proposal_id": str(proposal.proposal_id),
        "active_team": str(proposal.active_team),
        "partner_team": str(proposal.partner_team),
        "goal": str(proposal.goal),
        "cpu_response": str(proposal.cpu_response),
        "response_label": str(proposal.response_label),
        "deal_type": str(proposal.deal_type),
        "target_player_id": str(proposal.target_player_id),
        "target_player_name": str(proposal.target_player_name),
        "side_a_player_ids": [str(value) for value in proposal.side_a_player_ids],
        "side_b_player_ids": [str(value) for value in proposal.side_b_player_ids],
        "side_a_pick_asset_ids": [str(value) for value in proposal.side_a_pick_asset_ids],
        "side_b_pick_asset_ids": [str(value) for value in proposal.side_b_pick_asset_ids],
        "outgoing": [_asset_label(asset_id, player_map, pick_map) for asset_id in outgoing_ids],
        "incoming": [_asset_label(asset_id, player_map, pick_map) for asset_id in incoming_ids],
        "user_value_sent": round(float(proposal.user_value_sent), 2),
        "user_value_received": round(float(proposal.user_value_received), 2),
        "user_value_delta": round(float(proposal.user_value_delta), 2),
        "fit_score": round(float(proposal.fit_score), 2),
        "ranking_score": round(float(proposal.ranking_score), 2),
        "rationale": str(proposal.rationale),
        "counter_sweetener": str(proposal.counter_sweetener),
        "legal_status": str(preview.get("status", "")),
        "can_commit_in_engine": bool(preview.get("can_commit", False)),
    }


def _trade_finder_payload(runtime: Any, state: Any, trade_state: Any, ledger: Any, active_team: str) -> dict[str, Any]:
    player_map, pick_map = _asset_maps(ledger)
    try:
        result = generate_trade_finder_proposals(
            runtime,
            state,
            trade_state,
            active_team=active_team,
            goal=GOAL_BEST_AVAILABLE,
            include_picks=True,
            max_results=5,
            max_partners=12,
            max_targets_per_partner=4,
            max_package_evaluations=9,
            max_financial_prechecks=160,
            ledger=ledger,
        )
    except Exception as exc:
        return {
            "status": "unavailable",
            "exception_type": type(exc).__name__,
            "detail": str(exc),
            "proposals": [],
        }

    route_stage_counts: dict[str, int] = {}
    for audit_row in result.package_audit_rows:
        stage = str(audit_row.get("route_stage", "") or "unknown")
        route_stage_counts[stage] = route_stage_counts.get(stage, 0) + 1

    return {
        "status": "ok",
        "goal": str(result.goal),
        "teams_scanned": int(result.teams_scanned),
        "packages_evaluated": int(result.packages_evaluated),
        "legal_packages": int(result.legal_packages),
        "cpu_accepts_found": int(result.cpu_accepts_found),
        "cpu_counters_found": int(result.cpu_counters_found),
        "fallback_used": bool(result.fallback_used),
        "targets_identified": int(result.targets_identified),
        "primary_need_targets_identified": int(result.primary_need_targets_identified),
        "candidate_packages_generated": int(result.candidate_packages_generated),
        "value_screen_passes": int(result.value_screen_passes),
        "guaranteed_exploration_packages": int(result.guaranteed_exploration_packages),
        "financial_prechecks": int(result.financial_prechecks),
        "financial_precheck_passes": int(result.financial_precheck_passes),
        "partners_with_targets": int(result.partners_with_targets),
        "partners_with_financial_pass": int(result.partners_with_financial_pass),
        "partners_with_legal_pass": int(result.partners_with_legal_pass),
        "cpu_rejected_legal": int(result.cpu_rejected_legal),
        "rejection_counts": _json_safe(result.rejection_counts),
        "rejection_examples": _json_safe(result.rejection_examples),
        "route_stage_counts": route_stage_counts,
        "near_miss_count": len(result.near_misses),
        "search_elapsed_seconds": round(float(result.search_elapsed_seconds), 3),
        "proposals": [_proposal_payload(proposal, player_map, pick_map) for proposal in result.proposals[:5]],
    }


def build_transaction_foundation_payload(checkpoint: Any, active_team: str, *, include_trade_finder: bool = True) -> dict[str, Any]:
    state = getattr(checkpoint, "simulation_state", None)
    trade_state = getattr(checkpoint, "trade_state", None)
    if state is None:
        raise RuntimeError("V3 working checkpoint has no simulation state.")
    if trade_state is None:
        raise RuntimeError("V3 working checkpoint has no durable trade state.")

    team = normalize_team(active_team)
    if team not in getattr(state, "teams", {}):
        raise ValueError(f"Unknown active franchise team: {team or '<blank>'}.")

    runtime = _runtime()
    ledger = build_live_asset_ledger(runtime, state, trade_state)
    players, picks = _team_assets(ledger, team)
    finder = (
        _trade_finder_payload(runtime, state, trade_state, ledger, team)
        if include_trade_finder
        else {"status": "not_requested", "proposals": []}
    )
    phase = _phase(state)

    return {
        "foundation_version": TRANSACTION_FOUNDATION_VERSION,
        "source": "v3_working_checkpoint",
        "read_only": True,
        "working_save_write_performed": False,
        "active_v2_read_only": True,
        "write_actions_enabled": False,
        "team": team,
        "teams": [
            value
            for value in sorted(getattr(state, "teams", {}))
            if normalize_team(value) != team
        ],
        "season": {
            "label": str(getattr(getattr(state, "settings", None), "season_label", "")),
            "phase": phase,
            "day_index": int(getattr(state, "current_day_index", 0) or 0),
        },
        "engine_versions": {
            "asset_ledger": ASSET_LEDGER_VERSION,
            "trade_finder": TRADE_FINDER_AI_VERSION,
            "trade_value_model": TRADE_FINDER_VALUE_MODEL_VERSION,
            "trade_preview": EMBEDDED_TRADE_CENTER_VERSION,
            "free_agency_transaction": FREE_AGENCY_TRANSACTION_VERSION,
            "free_agency_contract_salary": FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION,
        },
        "trade_assets": {"players": players, "player_count": len(players)},
        "draft_assets": {
            "owned": picks,
            "owned_count": len(picks),
            "engine_ready_count": sum(bool(row.get("engine_ready")) for row in picks),
            "manual_review_count": sum(bool(row.get("manual_review_required")) for row in picks),
        },
        "trade_finder": finder,
        "trade_preview": {
            "available": True,
            "endpoint": "/v3/trade/preview",
            "write_actions_enabled": False,
        },
        "trade_execution": {
            "available": True,
            "endpoint": "/v3/trade/execute",
            "transaction_engine_version": FRANCHISE_TRADE_TRANSACTION_VERSION,
            "requires_fresh_preview_fingerprint": True,
            "requires_working_save_sha256": True,
            "working_save_only": True,
            "active_v2_read_only": True,
        },
        "free_agency_preview": {
            "available": True,
            "endpoint": "/v3/free-agency/preview",
            "free_agent_count": int(getattr(ledger, "free_agent_count", 0)),
            "current_phase": phase,
            "durable_execution_phase_supported": phase == "offseason",
            "write_actions_enabled": False,
        },
        "incoming_offers": {
            "queue_exposed": False,
            "reason": (
                "The production incoming-offer tick can mutate franchise state, so Batch 06 "
                "does not call it from a read-only endpoint."
            ),
        },
    }


def _string_tuple(payload: Mapping[str, Any], key: str) -> tuple[str, ...]:
    raw = payload.get(key, [])
    if raw is None:
        raw = []
    if not isinstance(raw, (list, tuple)):
        raise ValueError(f"{key} must be an array.")
    values = tuple(str(value or "").strip() for value in raw if str(value or "").strip())
    if len(values) > 8:
        raise ValueError(f"{key} cannot contain more than 8 assets in the V3 preview API.")
    return values


def build_trade_preview_payload(checkpoint: Any, active_team: str, request_payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(request_payload, Mapping):
        raise ValueError("Trade preview request body must be a JSON object.")

    state = checkpoint.simulation_state
    trade_state = checkpoint.trade_state
    if trade_state is None:
        raise RuntimeError("V3 working checkpoint has no durable trade state.")

    team_a = normalize_team(active_team)
    team_b = normalize_team(request_payload.get("partner_team"))
    if not team_b:
        raise ValueError("partner_team is required.")
    if team_a == team_b:
        raise ValueError("Trade preview requires a different partner team.")

    runtime = _runtime()
    ledger = build_live_asset_ledger(runtime, state, trade_state)
    preview = build_franchise_trade_preview(
        runtime,
        state,
        trade_state,
        team_a=team_a,
        team_b=team_b,
        side_a_player_ids=_string_tuple(request_payload, "side_a_player_ids"),
        side_b_player_ids=_string_tuple(request_payload, "side_b_player_ids"),
        side_a_pick_asset_ids=_string_tuple(request_payload, "side_a_pick_asset_ids"),
        side_b_pick_asset_ids=_string_tuple(request_payload, "side_b_pick_asset_ids"),
        ledger=ledger,
    )
    return {
        "foundation_version": TRANSACTION_FOUNDATION_VERSION,
        "source": "v3_working_checkpoint",
        "read_only": True,
        "write_actions_enabled": False,
        "team": team_a,
        "partner_team": team_b,
        "execution": {
            "eligible": bool(preview.status == "pass" and preview.can_commit),
            "endpoint": "/v3/trade/execute",
            "transaction_engine_version": FRANCHISE_TRADE_TRANSACTION_VERSION,
            "requires_package_fingerprint": True,
            "requires_working_save_sha256": True,
        },
        "preview": _json_safe(preview_to_dict(preview)),
    }


def build_trade_execution_candidate(
    checkpoint: Any,
    active_team: str,
    request_payload: Mapping[str, Any],
) -> FranchiseTradeCandidate:
    """Re-preview and build an in-memory candidate for a V3 working-save trade.

    This function deliberately does not write a checkpoint. The bridge owns the
    isolated V3 durable write/rollback boundary, while the production V2
    transaction engine remains the single authority for mutation and legality.
    """
    if not isinstance(request_payload, Mapping):
        raise ValueError("Trade execution request body must be a JSON object.")

    state = checkpoint.simulation_state
    trade_state = checkpoint.trade_state
    if trade_state is None:
        raise RuntimeError("V3 working checkpoint has no durable trade state.")

    team_a = normalize_team(active_team)
    team_b = normalize_team(request_payload.get("partner_team"))
    if not team_b:
        raise ValueError("partner_team is required.")
    if team_a == team_b:
        raise ValueError("Trade execution requires a different partner team.")

    expected_fingerprint = str(
        request_payload.get("expected_package_fingerprint", "") or ""
    ).strip()
    if not expected_fingerprint:
        raise ValueError(
            "expected_package_fingerprint is required. Run a fresh legality preview first."
        )

    return build_franchise_trade_candidate(
        _runtime(),
        state,
        trade_state,
        team_a=team_a,
        team_b=team_b,
        side_a_player_ids=_string_tuple(request_payload, "side_a_player_ids"),
        side_b_player_ids=_string_tuple(request_payload, "side_b_player_ids"),
        side_a_pick_asset_ids=_string_tuple(request_payload, "side_a_pick_asset_ids"),
        side_b_pick_asset_ids=_string_tuple(request_payload, "side_b_pick_asset_ids"),
        expected_fingerprint=expected_fingerprint,
    )


def verify_trade_execution_persisted(
    checkpoint: Any,
    candidate: FranchiseTradeCandidate,
) -> dict[str, Any]:
    """Verify a committed V3 trade after checkpoint reload."""
    state = checkpoint.simulation_state
    trade_state = checkpoint.trade_state
    if trade_state is None:
        raise RuntimeError("Reloaded V3 working checkpoint has no durable trade state.")

    history = getattr(state, "franchise_transaction_history_v1", None)
    if not isinstance(history, list) or not history:
        raise RuntimeError("Reloaded V3 checkpoint has no franchise transaction history.")
    if str(history[-1].get("transaction_id", "")) != candidate.transaction_id:
        raise RuntimeError(
            "Reloaded V3 checkpoint did not preserve the committed trade transaction."
        )

    expected_revision = int(
        getattr(candidate.state, "franchise_trade_revision_v1", 0) or 0
    )
    observed_revision = int(
        getattr(state, "franchise_trade_revision_v1", 0) or 0
    )
    if observed_revision != expected_revision:
        raise RuntimeError(
            "Reloaded V3 checkpoint did not preserve the committed trade revision."
        )

    ledger = build_live_asset_ledger(_runtime(), state, trade_state)
    player_map, pick_map = _asset_maps(ledger)
    record = candidate.transaction_record
    team_a = normalize_team(record.get("team_a"))
    team_b = normalize_team(record.get("team_b"))

    for player_id in record.get("side_a_player_ids", []):
        pid = normalize_player_id(player_id)
        if pid not in player_map or normalize_team(player_map[pid].get("team")) != team_b:
            raise RuntimeError(
                f"Reloaded V3 checkpoint lost player transfer {pid} to {team_b}."
            )
    for player_id in record.get("side_b_player_ids", []):
        pid = normalize_player_id(player_id)
        if pid not in player_map or normalize_team(player_map[pid].get("team")) != team_a:
            raise RuntimeError(
                f"Reloaded V3 checkpoint lost player transfer {pid} to {team_a}."
            )
    for asset_id in record.get("side_a_pick_asset_ids", []):
        aid = str(asset_id)
        if aid not in pick_map or normalize_team(pick_map[aid].get("current_owner")) != team_b:
            raise RuntimeError(
                f"Reloaded V3 checkpoint lost draft-right transfer {aid} to {team_b}."
            )
    for asset_id in record.get("side_b_pick_asset_ids", []):
        aid = str(asset_id)
        if aid not in pick_map or normalize_team(pick_map[aid].get("current_owner")) != team_a:
            raise RuntimeError(
                f"Reloaded V3 checkpoint lost draft-right transfer {aid} to {team_a}."
            )

    return {
        "transaction_id": candidate.transaction_id,
        "trade_revision": observed_revision,
        "transaction_history_count": len(history),
        "package_fingerprint": str(record.get("package_fingerprint", "")),
        "team_a": team_a,
        "team_b": team_b,
        "side_a_player_ids": list(record.get("side_a_player_ids", [])),
        "side_b_player_ids": list(record.get("side_b_player_ids", [])),
        "side_a_pick_asset_ids": list(record.get("side_a_pick_asset_ids", [])),
        "side_b_pick_asset_ids": list(record.get("side_b_pick_asset_ids", [])),
    }


def _free_agency_offer_from_request(
    active_team: str,
    request_payload: Mapping[str, Any],
) -> FreeAgencyOffer:
    if not isinstance(request_payload, Mapping):
        raise ValueError("Free-agency request body must be a JSON object.")

    team = normalize_team(active_team)
    player_id = normalize_player_id(request_payload.get("player_id"))
    if not player_id:
        raise ValueError("player_id is required.")

    try:
        annual_salary = float(request_payload.get("annual_salary"))
    except (TypeError, ValueError) as exc:
        raise ValueError("annual_salary must be numeric.") from exc
    try:
        years = int(request_payload.get("years"))
    except (TypeError, ValueError) as exc:
        raise ValueError("years must be an integer.") from exc

    return FreeAgencyOffer(
        player_id=player_id,
        team_abbreviation=team,
        annual_salary=annual_salary,
        years=years,
        guaranteed=bool(request_payload.get("guaranteed", True)),
        option_type=str(request_payload.get("option_type", "") or "").strip(),
    )


def build_free_agency_preview_payload(checkpoint: Any, active_team: str, request_payload: Mapping[str, Any]) -> dict[str, Any]:
    state = checkpoint.simulation_state
    team = normalize_team(active_team)
    offer = _free_agency_offer_from_request(team, request_payload)

    gate = evaluate_contract_legal_financial_gate(state, offer)
    preview = build_contract_legal_free_agency_preview(state, offer)
    return {
        "foundation_version": TRANSACTION_FOUNDATION_VERSION,
        "source": "v3_working_checkpoint",
        "read_only": True,
        "write_actions_enabled": False,
        "team": team,
        "player_id": offer.player_id,
        "contract_cba_gate": _json_safe(gate),
        "transaction_preview": _json_safe(preview),
        "execution": {
            "eligible": bool(preview.status == "pass" and preview.can_commit),
            "endpoint": "/v3/free-agency/execute",
            "transaction_engine_version": FREE_AGENCY_TRANSACTION_VERSION,
            "requires_candidate_fingerprint": True,
            "requires_working_save_sha256": True,
            "phase_required": "offseason",
        },
    }


def build_free_agency_execution_candidate(
    checkpoint: Any,
    active_team: str,
    request_payload: Mapping[str, Any],
) -> V3FreeAgencyExecutionCandidate:
    """Re-preview and build a non-durable free-agency signing candidate.

    The production free-agency engine remains the single authority for roster,
    contract, financial/CBA, phase, and candidate-state validation. This bridge
    function does not write a checkpoint.
    """
    if not isinstance(request_payload, Mapping):
        raise ValueError("Free-agency execution request body must be a JSON object.")

    state = checkpoint.simulation_state
    offer = _free_agency_offer_from_request(active_team, request_payload)
    expected_fingerprint = str(
        request_payload.get("expected_candidate_fingerprint", "") or ""
    ).strip()
    if not expected_fingerprint:
        raise ValueError(
            "expected_candidate_fingerprint is required. Run a fresh offer preview first."
        )

    preview = build_contract_legal_free_agency_preview(state, offer)
    if preview.status != "pass" or not preview.can_commit:
        raise FreeAgencyTransactionError(
            preview.message or "The free-agency offer is no longer committable."
        )
    if preview.candidate_fingerprint != expected_fingerprint:
        raise FreeAgencyTransactionError(
            "The free-agency preview is stale because the candidate fingerprint changed."
        )

    candidate_state, result = commit_free_agency_preview(
        state,
        preview,
        financial_gate=evaluate_contract_legal_financial_gate,
    )
    if result.committed_fingerprint != expected_fingerprint:
        raise FreeAgencyTransactionError(
            "The committed free-agency candidate no longer matches the approved preview."
        )

    return V3FreeAgencyExecutionCandidate(
        state=candidate_state,
        preview=preview,
        commit_result=result,
    )


def verify_free_agency_execution_persisted(
    checkpoint: Any,
    candidate: V3FreeAgencyExecutionCandidate,
) -> dict[str, Any]:
    """Verify one committed free-agency signing after checkpoint reload."""
    state = checkpoint.simulation_state
    offer = candidate.preview.offer
    result = candidate.commit_result

    observed_fingerprint = free_agency_state_fingerprint(state)
    if observed_fingerprint != result.committed_fingerprint:
        raise RuntimeError(
            "Reloaded V3 checkpoint does not match the committed free-agency candidate."
        )

    free_agents = {
        normalize_player_id(player_id)
        for player_id in getattr(state, "free_agent_player_ids", ())
    }
    if offer.player_id in free_agents:
        raise RuntimeError(
            f"Reloaded V3 checkpoint still lists {offer.player_id} as a free agent."
        )

    team = getattr(state, "teams", {}).get(offer.team_abbreviation)
    if team is None:
        raise RuntimeError(
            f"Reloaded V3 checkpoint lost team {offer.team_abbreviation}."
        )
    roster_ids = {
        normalize_player_id(player_id)
        for player_id in getattr(team, "roster_player_ids", ())
    }
    if offer.player_id not in roster_ids:
        raise RuntimeError(
            f"Reloaded V3 checkpoint did not preserve {offer.player_id} on {offer.team_abbreviation}."
        )

    player = getattr(state, "players", {}).get(offer.player_id)
    if player is None:
        raise RuntimeError(
            f"Reloaded V3 checkpoint lost signed player {offer.player_id}."
        )
    if normalize_team(getattr(player, "team_abbreviation", "")) != offer.team_abbreviation:
        raise RuntimeError(
            f"Reloaded V3 checkpoint did not preserve player ownership for {offer.player_id}."
        )

    contract = getattr(player, "contract", None)
    if contract is None:
        raise RuntimeError("Reloaded signed player has no contract state.")
    if abs(float(getattr(contract, "salary", 0.0) or 0.0) - float(offer.annual_salary)) > 0.01:
        raise RuntimeError("Reloaded signed player salary does not match the approved offer.")
    if int(getattr(contract, "years_remaining", 0) or 0) != int(offer.years):
        raise RuntimeError("Reloaded signed player term does not match the approved offer.")
    if str(getattr(contract, "option_type", "") or "") != offer.option_type:
        raise RuntimeError("Reloaded signed player option does not match the approved offer.")
    if bool(getattr(contract, "guaranteed", False)) != bool(offer.guaranteed):
        raise RuntimeError("Reloaded signed player guarantee does not match the approved offer.")

    roster_count = len(getattr(team, "roster_player_ids", ()))
    if roster_count != int(result.roster_count_after):
        raise RuntimeError(
            "Reloaded team roster count does not match the committed signing result."
        )

    return {
        "offer_id": result.offer_id,
        "player_id": result.player_id,
        "player_name": result.player_name,
        "team": result.team_abbreviation,
        "candidate_fingerprint": result.committed_fingerprint,
        "roster_count_before": result.roster_count_before,
        "roster_count_after": result.roster_count_after,
        "annual_salary": offer.annual_salary,
        "years": offer.years,
        "option_type": offer.option_type,
        "guaranteed": offer.guaranteed,
    }


def _fingerprint_payload(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(_json_safe(dict(payload)), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalized_focus_ids(
    state: Any,
    raw_values: Any,
) -> tuple[str, ...]:
    if raw_values is None:
        raw_values = []
    if not isinstance(raw_values, (list, tuple)):
        raise ValueError("focus_ids must be an array.")
    current = production_draft_state(state)
    if current is None:
        raise ValueError("Draft state is not initialized.")
    valid_ids = {
        str(row.get("prospect_id", "") or "").strip()
        for row in current.get("prospects", [])
        if str(row.get("prospect_id", "") or "").strip()
    }
    selected: list[str] = []
    for raw in raw_values:
        prospect_id = str(raw or "").strip()
        if not prospect_id:
            continue
        if prospect_id not in valid_ids:
            raise ValueError(f"Unknown scouting prospect: {prospect_id}.")
        if prospect_id not in selected:
            selected.append(prospect_id)
    if len(selected) > MAX_FOCUS_PROSPECTS:
        raise ValueError(
            f"Scouting focus supports at most {MAX_FOCUS_PROSPECTS} prospects."
        )
    return tuple(selected)


def _scouting_action_fingerprint(
    state: Any,
    team: str,
    focus_ids: tuple[str, ...],
) -> str:
    current = production_draft_state(state) or {}
    summary = scouting_summary_v1(copy.deepcopy(state), team)
    return _fingerprint_payload(
        {
            "kind": "v3_scouting_advance_v1",
            "team": normalize_team(team),
            "draft_year": int(current.get("draft_year", 0) or 0),
            "phase": str(current.get("phase", "") or ""),
            "current_pick_index": int(current.get("current_pick_index", 0) or 0),
            "weeks_completed": int(summary.get("weeks_completed", 0) or 0),
            "focus_ids": list(focus_ids),
            "scouting_version": FRANCHISE_SCOUTING_DISCOVERY_VERSION,
        }
    )


def _draft_action_fingerprint(
    state: Any,
    team: str,
    prospect_id: str,
) -> str:
    current = production_draft_state(state) or {}
    pick = draft_current_pick(current) if current else None
    if pick is None:
        raise ValueError("No Draft pick is currently on the clock.")
    return _fingerprint_payload(
        {
            "kind": "v3_draft_selection_v1",
            "team": normalize_team(team),
            "draft_year": int(current.get("draft_year", 0) or 0),
            "phase": str(current.get("phase", "") or ""),
            "current_pick_index": int(current.get("current_pick_index", 0) or 0),
            "overall_pick": int(pick.get("overall_pick", 0) or 0),
            "owner_team": normalize_team(pick.get("owner_team")),
            "prospect_id": str(prospect_id or "").strip(),
            "draft_engine_version": DRAFT_ENGINE_VERSION,
        }
    )


def build_scouting_draft_payload(
    checkpoint: Any,
    active_team: str,
) -> dict[str, Any]:
    state = getattr(checkpoint, "simulation_state", None)
    if state is None:
        raise RuntimeError("V3 working checkpoint has no simulation state.")
    team = normalize_team(active_team)
    if team not in getattr(state, "teams", {}):
        raise ValueError(f"Unknown active franchise team: {team or '<blank>'}.")

    current = production_draft_state(state)
    if current is None:
        return {
            "foundation_version": TRANSACTION_FOUNDATION_VERSION,
            "source": "v3_working_checkpoint",
            "read_only": True,
            "team": team,
            "draft_initialized": False,
            "board": [],
            "summary": {},
            "draft": {},
            "lead_scout": {},
            "scouting_preview_endpoint": "/v3/scouting/preview",
            "scouting_execute_endpoint": "/v3/scouting/advance",
            "draft_preview_endpoint": "/v3/draft/selection/preview",
            "draft_execute_endpoint": "/v3/draft/selection/execute",
        }

    # Production scouting getters lazily materialize reports. Build the display
    # payload from a deep copy so GET remains byte-for-byte read only.
    view_state = copy.deepcopy(state)
    view_current = production_draft_state(view_state) or {}
    # Materialize the complete board before computing its aggregate summary.
    # Production scouting reports are lazy, so summarizing first can average only
    # a partially persisted report set and make confidence appear to fall after
    # a preview even though every weekly confidence gain is non-negative.
    board = scouting_board_rows_v1(view_state, team, available_only=False)
    summary = scouting_summary_v1(view_state, team)
    phase = str(view_current.get("phase", "") or "")
    pick = draft_current_pick(view_current) if phase == "draft_in_progress" else None
    owner = normalize_team(pick.get("owner_team")) if pick else ""
    scout = lead_scout_member(view_state, team, ensure=True)

    current_pick_payload: dict[str, Any] = {}
    if pick is not None:
        current_pick_payload = {
            "overall_pick": int(pick.get("overall_pick", 0) or 0),
            "round": int(pick.get("round", 0) or 0),
            "round_pick": int(pick.get("round_pick", 0) or 0),
            "owner_team": owner,
            "origin_team": normalize_team(pick.get("origin_team")),
            "asset_id": str(pick.get("asset_id", "") or ""),
            "team_on_clock": owner == team,
        }

    return {
        "foundation_version": TRANSACTION_FOUNDATION_VERSION,
        "source": "v3_working_checkpoint",
        "read_only": True,
        "working_save_write_performed": False,
        "active_v2_read_only": True,
        "team": team,
        "draft_initialized": True,
        "draft": {
            "draft_year": int(view_current.get("draft_year", 0) or 0),
            "source_season": str(view_current.get("source_season", "") or ""),
            "target_season": str(view_current.get("target_season", "") or ""),
            "phase": phase,
            "current_pick_index": int(view_current.get("current_pick_index", 0) or 0),
            "draft_order_count": len(view_current.get("draft_order", []) or []),
            "available_prospect_count": sum(
                1 for row in view_current.get("prospects", []) if not row.get("drafted")
            ),
            "current_pick": current_pick_payload,
            "selection_enabled": bool(
                phase == "draft_in_progress" and owner == team
            ),
            "engine_version": DRAFT_ENGINE_VERSION,
        },
        "summary": _json_safe(summary),
        "board": _json_safe(board),
        "lead_scout": (
            {
                "staff_id": str(getattr(scout, "staff_id", "")),
                "name": str(getattr(scout, "name", "")),
                "overall": float(getattr(scout, "overall_rating", 0.0) or 0.0),
                "current_rating": float(getattr(scout, "scouting_current_rating", 0.0) or 0.0),
                "potential_rating": float(getattr(scout, "scouting_potential_rating", 0.0) or 0.0),
                "traits": list(getattr(scout, "traits", ()) or ()),
            }
            if scout is not None
            else {}
        ),
        "scouting_preview_endpoint": "/v3/scouting/preview",
        "scouting_execute_endpoint": "/v3/scouting/advance",
        "draft_preview_endpoint": "/v3/draft/selection/preview",
        "draft_execute_endpoint": "/v3/draft/selection/execute",
        "scouting_execution_enabled": phase in {"season_scouting", "scouting"},
        "draft_execution_enabled": bool(
            phase == "draft_in_progress" and owner == team
        ),
    }


def build_scouting_advance_preview_payload(
    checkpoint: Any,
    active_team: str,
    request_payload: Mapping[str, Any],
) -> dict[str, Any]:
    state = getattr(checkpoint, "simulation_state", None)
    if state is None:
        raise RuntimeError("V3 working checkpoint has no simulation state.")
    team = normalize_team(active_team)
    current = production_draft_state(state)
    if current is None:
        raise ValueError("Draft state is not initialized.")
    phase = str(current.get("phase", "") or "")
    focus_ids = _normalized_focus_ids(state, request_payload.get("focus_ids", []))
    fingerprint = _scouting_action_fingerprint(state, team, focus_ids)

    # Compare like with like. Scouting reports are lazily materialized, so build
    # the full read-only board before taking the pre-week aggregate. Otherwise a
    # partially persisted report set can make the preview average appear to drop
    # when the candidate creates reports for the rest of the class.
    before_state = copy.deepcopy(state)
    scouting_board_rows_v1(before_state, team, available_only=False)
    before = scouting_summary_v1(before_state, team)

    if phase not in {"season_scouting", "scouting"}:
        return {
            "foundation_version": TRANSACTION_FOUNDATION_VERSION,
            "source": "v3_working_checkpoint",
            "read_only": True,
            "status": "blocked",
            "can_commit": False,
            "reason": f"Scouting-week advancement is unavailable during draft phase '{phase}'.",
            "phase": phase,
            "focus_ids": list(focus_ids),
            "action_fingerprint": fingerprint,
            "summary_before": _json_safe(before),
            "summary_after": _json_safe(before),
            "scouting_version": FRANCHISE_SCOUTING_DISCOVERY_VERSION,
        }

    candidate_state = copy.deepcopy(state)
    set_scouting_focus_v1(candidate_state, team, focus_ids)
    after = advance_scouting_week_v1(candidate_state, team)
    return {
        "foundation_version": TRANSACTION_FOUNDATION_VERSION,
        "source": "v3_working_checkpoint",
        "read_only": True,
        "status": "pass",
        "can_commit": True,
        "phase": phase,
        "team": team,
        "focus_ids": list(focus_ids),
        "action_fingerprint": fingerprint,
        "summary_before": _json_safe(before),
        "summary_after": _json_safe(after),
        "scouting_version": FRANCHISE_SCOUTING_DISCOVERY_VERSION,
    }


def build_scouting_advance_candidate(
    checkpoint: Any,
    active_team: str,
    request_payload: Mapping[str, Any],
) -> V3ScoutingAdvanceCandidate:
    state = getattr(checkpoint, "simulation_state", None)
    if state is None:
        raise RuntimeError("V3 working checkpoint has no simulation state.")
    team = normalize_team(active_team)
    current = production_draft_state(state)
    if current is None:
        raise ValueError("Draft state is not initialized.")
    phase = str(current.get("phase", "") or "")
    if phase not in {"season_scouting", "scouting"}:
        raise ValueError(
            f"Scouting-week advancement is unavailable during draft phase '{phase}'."
        )
    focus_ids = _normalized_focus_ids(state, request_payload.get("focus_ids", []))
    expected = str(request_payload.get("expected_action_fingerprint", "") or "").strip()
    if not expected:
        raise ValueError(
            "expected_action_fingerprint is required. Run a fresh scouting preview first."
        )
    observed = _scouting_action_fingerprint(state, team, focus_ids)
    if observed != expected:
        raise ValueError(
            "The scouting preview is stale or the focus package changed. Run PREVIEW WEEK again."
        )
    before = scouting_summary_v1(copy.deepcopy(state), team)
    candidate_state = copy.deepcopy(state)
    set_scouting_focus_v1(candidate_state, team, focus_ids)
    after = advance_scouting_week_v1(candidate_state, team)
    return V3ScoutingAdvanceCandidate(
        state=candidate_state,
        team=team,
        draft_year=int(current.get("draft_year", 0) or 0),
        phase=phase,
        focus_ids=focus_ids,
        action_fingerprint=observed,
        weeks_before=int(before.get("weeks_completed", 0) or 0),
        weeks_after=int(after.get("weeks_completed", 0) or 0),
        summary_after=dict(after),
    )


def verify_scouting_advance_persisted(
    checkpoint: Any,
    candidate: V3ScoutingAdvanceCandidate,
) -> dict[str, Any]:
    state = checkpoint.simulation_state
    summary = scouting_summary_v1(copy.deepcopy(state), candidate.team)
    if int(summary.get("weeks_completed", -1)) != candidate.weeks_after:
        raise RuntimeError("Reloaded V3 checkpoint lost the scouting-week advancement.")
    observed_focus = tuple(str(value) for value in summary.get("focus_ids", ()) or ())
    if observed_focus != candidate.focus_ids:
        raise RuntimeError("Reloaded V3 checkpoint lost the scouting focus assignments.")
    return {
        "team": candidate.team,
        "draft_year": candidate.draft_year,
        "phase": candidate.phase,
        "weeks_before": candidate.weeks_before,
        "weeks_after": candidate.weeks_after,
        "focus_ids": list(candidate.focus_ids),
        "average_confidence": summary.get("average_confidence"),
        "action_fingerprint": candidate.action_fingerprint,
    }


def build_draft_selection_preview_payload(
    checkpoint: Any,
    active_team: str,
    request_payload: Mapping[str, Any],
) -> dict[str, Any]:
    state = getattr(checkpoint, "simulation_state", None)
    if state is None:
        raise RuntimeError("V3 working checkpoint has no simulation state.")
    team = normalize_team(active_team)
    prospect_id = str(request_payload.get("prospect_id", "") or "").strip()
    if not prospect_id:
        raise ValueError("prospect_id is required.")
    current = production_draft_state(state)
    if current is None:
        raise ValueError("Draft state is not initialized.")
    phase = str(current.get("phase", "") or "")
    prospect = next(
        (
            row for row in current.get("prospects", [])
            if str(row.get("prospect_id", "")) == prospect_id and not row.get("drafted")
        ),
        None,
    )
    if prospect is None:
        raise ValueError("The selected prospect is not available.")
    if phase != "draft_in_progress":
        return {
            "foundation_version": TRANSACTION_FOUNDATION_VERSION,
            "source": "v3_working_checkpoint",
            "read_only": True,
            "status": "blocked",
            "can_commit": False,
            "reason": "Draft selection is phase-locked until Draft Night is in progress.",
            "phase": phase,
            "prospect_id": prospect_id,
            "prospect_name": str(prospect.get("player_name", prospect_id)),
            "draft_engine_version": DRAFT_ENGINE_VERSION,
        }
    pick = draft_current_pick(current)
    if pick is None:
        raise ValueError("No Draft pick is currently on the clock.")
    owner = normalize_team(pick.get("owner_team"))
    fingerprint = _draft_action_fingerprint(state, team, prospect_id)
    if owner != team:
        return {
            "foundation_version": TRANSACTION_FOUNDATION_VERSION,
            "source": "v3_working_checkpoint",
            "read_only": True,
            "status": "blocked",
            "can_commit": False,
            "reason": f"{owner or 'A CPU team'} is currently on the clock.",
            "phase": phase,
            "prospect_id": prospect_id,
            "prospect_name": str(prospect.get("player_name", prospect_id)),
            "current_pick": _json_safe(pick),
            "action_fingerprint": fingerprint,
            "draft_engine_version": DRAFT_ENGINE_VERSION,
        }
    return {
        "foundation_version": TRANSACTION_FOUNDATION_VERSION,
        "source": "v3_working_checkpoint",
        "read_only": True,
        "status": "pass",
        "can_commit": True,
        "phase": phase,
        "team": team,
        "prospect_id": prospect_id,
        "prospect_name": str(prospect.get("player_name", prospect_id)),
        "current_pick": {
            "overall_pick": int(pick.get("overall_pick", 0) or 0),
            "round": int(pick.get("round", 0) or 0),
            "round_pick": int(pick.get("round_pick", 0) or 0),
            "owner_team": owner,
            "origin_team": normalize_team(pick.get("origin_team")),
        },
        "action_fingerprint": fingerprint,
        "draft_engine_version": DRAFT_ENGINE_VERSION,
    }


def build_draft_selection_candidate(
    checkpoint: Any,
    active_team: str,
    request_payload: Mapping[str, Any],
) -> V3DraftSelectionCandidate:
    state = getattr(checkpoint, "simulation_state", None)
    if state is None:
        raise RuntimeError("V3 working checkpoint has no simulation state.")
    team = normalize_team(active_team)
    prospect_id = str(request_payload.get("prospect_id", "") or "").strip()
    if not prospect_id:
        raise ValueError("prospect_id is required.")
    current = production_draft_state(state)
    if current is None or str(current.get("phase", "")) != "draft_in_progress":
        raise ValueError("Draft selection is phase-locked until Draft Night is in progress.")
    pick = draft_current_pick(current)
    if pick is None:
        raise ValueError("No Draft pick is currently on the clock.")
    if normalize_team(pick.get("owner_team")) != team:
        raise ValueError("The active franchise is not currently on the clock.")
    prospect = next(
        (
            row for row in current.get("prospects", [])
            if str(row.get("prospect_id", "")) == prospect_id and not row.get("drafted")
        ),
        None,
    )
    if prospect is None:
        raise ValueError("The selected prospect is not available.")
    expected = str(request_payload.get("expected_action_fingerprint", "") or "").strip()
    if not expected:
        raise ValueError(
            "expected_action_fingerprint is required. Run a fresh Draft preview first."
        )
    observed = _draft_action_fingerprint(state, team, prospect_id)
    if observed != expected:
        raise ValueError(
            "The Draft preview is stale or the selected prospect changed. Run PREVIEW PICK again."
        )

    candidate_state = copy.deepcopy(state)
    candidate_current = production_draft_state(candidate_state) or {}
    selected_pick = make_draft_selection(
        candidate_state,
        prospect_id,
        selected_by_user=True,
        now_ts=time.time(),
        integrate=True,
    )
    return V3DraftSelectionCandidate(
        state=candidate_state,
        team=team,
        draft_year=int(current.get("draft_year", 0) or 0),
        prospect_id=prospect_id,
        prospect_name=str(prospect.get("player_name", prospect_id)),
        overall_pick=int(selected_pick.get("overall_pick", 0) or 0),
        round_number=int(selected_pick.get("round", 0) or 0),
        round_pick=int(selected_pick.get("round_pick", 0) or 0),
        action_fingerprint=observed,
        next_pick_index=int(candidate_current.get("current_pick_index", 0) or 0),
        draft_complete=str(candidate_current.get("phase", "")) == "draft_complete",
    )


def verify_draft_selection_persisted(
    checkpoint: Any,
    candidate: V3DraftSelectionCandidate,
) -> dict[str, Any]:
    state = checkpoint.simulation_state
    current = production_draft_state(state)
    if current is None:
        raise RuntimeError("Reloaded V3 checkpoint lost the Draft state.")
    prospect = next(
        (
            row for row in current.get("prospects", [])
            if str(row.get("prospect_id", "")) == candidate.prospect_id
        ),
        None,
    )
    if prospect is None or not prospect.get("drafted"):
        raise RuntimeError("Reloaded V3 checkpoint lost the drafted prospect selection.")
    if normalize_team(prospect.get("drafted_by")) != candidate.team:
        raise RuntimeError("Reloaded V3 checkpoint has the drafted prospect on the wrong team.")
    player = getattr(state, "players", {}).get(candidate.prospect_id)
    if player is None or normalize_team(getattr(player, "team_abbreviation", "")) != candidate.team:
        raise RuntimeError("Reloaded V3 checkpoint lost the integrated drafted player.")
    team_state = getattr(state, "teams", {}).get(candidate.team)
    if team_state is None or candidate.prospect_id not in getattr(team_state, "roster_player_ids", ()):
        raise RuntimeError("Reloaded V3 checkpoint lost the drafted player from the team roster.")
    if int(current.get("current_pick_index", -1)) != candidate.next_pick_index:
        raise RuntimeError("Reloaded V3 checkpoint lost the Draft pick-index advancement.")
    return {
        "team": candidate.team,
        "draft_year": candidate.draft_year,
        "prospect_id": candidate.prospect_id,
        "prospect_name": candidate.prospect_name,
        "overall_pick": candidate.overall_pick,
        "round": candidate.round_number,
        "round_pick": candidate.round_pick,
        "next_pick_index": candidate.next_pick_index,
        "draft_complete": candidate.draft_complete,
        "action_fingerprint": candidate.action_fingerprint,
    }

def build_trade_team_assets_payload(
    checkpoint: Any,
    active_team: str,
    requested_team: str,
) -> dict[str, Any]:
    state = getattr(checkpoint, "simulation_state", None)
    trade_state = getattr(checkpoint, "trade_state", None)
    if state is None:
        raise RuntimeError("V3 working checkpoint has no simulation state.")
    if trade_state is None:
        raise RuntimeError("V3 working checkpoint has no durable trade state.")

    active = normalize_team(active_team)
    requested = normalize_team(requested_team)
    if not requested:
        raise ValueError("team query parameter is required.")
    if requested not in getattr(state, "teams", {}):
        raise ValueError(f"Unknown franchise team: {requested}.")

    runtime = _runtime()
    ledger = build_live_asset_ledger(runtime, state, trade_state)
    players, picks = _team_assets(ledger, requested)

    return {
        "foundation_version": TRANSACTION_FOUNDATION_VERSION,
        "source": "v3_working_checkpoint",
        "read_only": True,
        "working_save_write_performed": False,
        "active_v2_read_only": True,
        "write_actions_enabled": False,
        "active_team": active,
        "team": requested,
        "is_active_team": requested == active,
        "players": players,
        "player_count": len(players),
        "picks": picks,
        "pick_count": len(picks),
        "engine_ready_pick_count": sum(
            bool(row.get("engine_ready")) for row in picks
        ),
    }


def build_free_agency_market_payload(
    checkpoint: Any,
    active_team: str,
) -> dict[str, Any]:
    state = getattr(checkpoint, "simulation_state", None)
    trade_state = getattr(checkpoint, "trade_state", None)
    if state is None:
        raise RuntimeError("V3 working checkpoint has no simulation state.")
    if trade_state is None:
        raise RuntimeError("V3 working checkpoint has no durable trade state.")

    team = normalize_team(active_team)
    if team not in getattr(state, "teams", {}):
        raise ValueError(f"Unknown active franchise team: {team or '<blank>'}.")

    runtime = _runtime()
    ledger = build_live_asset_ledger(runtime, state, trade_state)
    player_map, _ = _asset_maps(ledger)
    free_agent_ids = {
        normalize_player_id(value)
        for value in getattr(state, "free_agent_player_ids", ())
        if normalize_player_id(value)
    }

    players: list[dict[str, Any]] = []
    for player_id in free_agent_ids:
        row = player_map.get(player_id)
        if row is None:
            continue
        payload = _player_asset_payload(dict(row))
        payload["player_id"] = player_id
        payload["roster_status"] = str(row.get("roster_status", ""))
        payload["market_reference_salary"] = row.get("salary")
        players.append(payload)

    players.sort(
        key=lambda row: (
            -float(row.get("overall") or 0.0),
            -float(row.get("future_outlook") or 0.0),
            float(row.get("age") or 99.0),
            str(row.get("name", "")),
        )
    )

    team_state = getattr(state, "teams", {}).get(team)
    roster_count = len(
        getattr(team_state, "roster_player_ids", ())
    ) if team_state is not None else 0

    return {
        "foundation_version": TRANSACTION_FOUNDATION_VERSION,
        "source": "v3_working_checkpoint",
        "read_only": True,
        "working_save_write_performed": False,
        "active_v2_read_only": True,
        "write_actions_enabled": False,
        "team": team,
        "season": {
            "label": str(
                getattr(getattr(state, "settings", None), "season_label", "")
            ),
            "phase": _phase(state),
            "day_index": int(getattr(state, "current_day_index", 0) or 0),
        },
        "roster_count": roster_count,
        "total_available": len(players),
        "players": players,
        "preview_endpoint": "/v3/free-agency/preview",
        "execution_phase_supported": _phase(state) == "offseason",
    }
