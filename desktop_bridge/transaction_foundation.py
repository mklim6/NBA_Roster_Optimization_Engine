from __future__ import annotations

from dataclasses import asdict, is_dataclass
from functools import lru_cache
from typing import Any, Mapping

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
    FreeAgencyOffer,
)
from franchise_live_asset_ledger_v1 import (
    ASSET_LEDGER_VERSION,
    build_live_asset_ledger,
)
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
    "v3-transaction-foundation-batch-08-transactional-trade-execution-2026-10-02"
)


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


def build_free_agency_preview_payload(checkpoint: Any, active_team: str, request_payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(request_payload, Mapping):
        raise ValueError("Free-agency preview request body must be a JSON object.")

    state = checkpoint.simulation_state
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

    offer = FreeAgencyOffer(
        player_id=player_id,
        team_abbreviation=team,
        annual_salary=annual_salary,
        years=years,
        guaranteed=bool(request_payload.get("guaranteed", True)),
        option_type=str(request_payload.get("option_type", "") or "").strip(),
    )

    gate = evaluate_contract_legal_financial_gate(state, offer)
    preview = build_contract_legal_free_agency_preview(state, offer)
    return {
        "foundation_version": TRANSACTION_FOUNDATION_VERSION,
        "source": "v3_working_checkpoint",
        "read_only": True,
        "write_actions_enabled": False,
        "team": team,
        "player_id": player_id,
        "contract_cba_gate": _json_safe(gate),
        "transaction_preview": _json_safe(preview),
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
