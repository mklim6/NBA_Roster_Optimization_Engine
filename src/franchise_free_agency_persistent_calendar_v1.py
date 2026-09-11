from __future__ import annotations

import copy
import hashlib
import inspect
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from franchise_free_agency_contract_salary_legality_v1_3 import (
    FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION,
    build_contract_legal_free_agency_preview,
)
from franchise_free_agency_live_signing_v1 import (
    FREE_AGENCY_LIVE_SIGNING_VERSION,
    controlled_teams_from_durable_checkpoint,
    trade_state_fingerprint,
)
from franchise_free_agency_negotiation_rounds_v1 import (
    FREE_AGENCY_NEGOTIATION_ROUNDS_VERSION,
    MAX_FREE_AGENCY_NEGOTIATION_ROUNDS,
    FreeAgencyNegotiationRoundResult,
    build_free_agency_negotiation_round,
    commit_negotiated_user_winner_live,
)
from franchise_free_agency_transaction_v1 import (
    FreeAgencyOffer,
    free_agency_state_fingerprint,
)

FREE_AGENCY_PERSISTENT_CALENDAR_VERSION = (
    "franchise-free-agency-persistent-offseason-market-calendar-v1-2026-08-14"
)
FREE_AGENCY_PERSISTENT_CALENDAR_UI_VERSION = (
    "franchise-free-agency-persistent-offseason-market-calendar-ui-v1-2026-08-14"
)
FREE_AGENCY_PERSISTENT_CALENDAR_SCOPE = (
    "checkpoint_owned_offseason_day_and_multi_player_negotiations_explicit_day_advance_no_background_signing"
)
FREE_AGENCY_CALENDAR_ATTR = "free_agency_market_calendar_v1"
MAX_FREE_AGENCY_CALENDAR_DAYS = 30


class FreeAgencyPersistentCalendarError(RuntimeError):
    """Raised when durable free-agency calendar state cannot be changed safely."""


@dataclass(frozen=True)
class PersistentFreeAgencyMarketRecord:
    market_id: str
    season_label: str
    player_id: str
    player_name: str
    user_team_abbreviation: str
    annual_salary: float
    years: int
    guaranteed: bool
    option_type: str
    created_day: int
    last_updated_day: int
    current_round: int
    max_rounds: int
    status: str
    player_response: str
    winner_team_abbreviation: str | None
    winning_margin: float | None
    source_state_fingerprint: str
    user_offer_fingerprint: str
    negotiation_fingerprint: str
    market_fingerprint: str
    active_cpu_offer_count: int
    round_history: tuple[dict[str, Any], ...]
    current_cpu_offers: tuple[dict[str, Any], ...]
    current_evaluations: tuple[dict[str, Any], ...]

    @property
    def is_open(self) -> bool:
        return self.status in {
            "open",
            "hold",
            "counter_market",
            "exploring_market",
            "ready_to_sign_user",
            "ready_to_sign_cpu",
        }


@dataclass(frozen=True)
class FreeAgencyCalendarSnapshot:
    version: str
    initialized: bool
    season_label: str
    offseason_day: int
    revision: int
    active_market_count: int
    archived_market_count: int
    active_markets: tuple[PersistentFreeAgencyMarketRecord, ...]
    day_history: tuple[dict[str, Any], ...]
    calendar_fingerprint: str


@dataclass(frozen=True)
class FreeAgencyCalendarWriteResult:
    version: str
    action: str
    season_label: str
    offseason_day: int
    revision: int
    calendar_fingerprint: str
    checkpoint_hash_before: str
    checkpoint_hash_after: str
    recovery_path: str
    checkpoint_reason: str


@dataclass(frozen=True)
class FreeAgencyDayAdvanceResult:
    version: str
    prior_day: int
    current_day: int
    markets_advanced: int
    markets_held: int
    markets_ready_user: int
    markets_ready_cpu: int
    markets_closed: int
    write_result: FreeAgencyCalendarWriteResult


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _season(state: Any) -> str:
    return _clean(getattr(getattr(state, "settings", None), "season_label", ""))


def _phase(state: Any) -> str:
    phase = getattr(state, "phase", "")
    return _clean(getattr(phase, "value", phase)).lower()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
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


def _offer_payload(offer: Any) -> dict[str, Any]:
    return {
        "player_id": _clean(getattr(offer, "player_id", "")),
        "team_abbreviation": _team(getattr(offer, "team_abbreviation", "")),
        "annual_salary": round(float(getattr(offer, "annual_salary", 0.0) or 0.0), 2),
        "years": int(getattr(offer, "years", 0) or 0),
        "guaranteed": bool(getattr(offer, "guaranteed", False)),
        "option_type": _clean(getattr(offer, "option_type", "")).lower(),
        "offer_id": _clean(getattr(offer, "offer_id", "")),
    }


def _offer_from_payload(payload: Mapping[str, Any]) -> FreeAgencyOffer:
    return FreeAgencyOffer(
        player_id=_clean(payload.get("player_id", "")),
        team_abbreviation=_team(payload.get("team_abbreviation", "")),
        annual_salary=float(payload.get("annual_salary", 0.0) or 0.0),
        years=int(payload.get("years", 0) or 0),
        guaranteed=bool(payload.get("guaranteed", False)),
        option_type=_clean(payload.get("option_type", "")).lower(),
        offer_id=_clean(payload.get("offer_id", "")) or None,
    )


def _market_id(season_label: str, offer: Any) -> str:
    payload = {
        "version": FREE_AGENCY_PERSISTENT_CALENDAR_VERSION,
        "season": _clean(season_label),
        "player": _clean(getattr(offer, "player_id", "")),
        "user_team": _team(getattr(offer, "team_abbreviation", "")),
    }
    return "FAMKT-" + _fingerprint(payload)[:14].upper()


def _default_calendar(state: Any) -> dict[str, Any]:
    return {
        "version": FREE_AGENCY_PERSISTENT_CALENDAR_VERSION,
        "season_label": _season(state),
        "initialized": False,
        "offseason_day": 0,
        "revision": 0,
        "active_markets": {},
        "archived_markets": [],
        "day_history": [],
    }


def _normalized_calendar_payload(state: Any) -> dict[str, Any]:
    raw = getattr(state, FREE_AGENCY_CALENDAR_ATTR, None)
    if raw is None:
        return _default_calendar(state)
    if not isinstance(raw, Mapping):
        raise FreeAgencyPersistentCalendarError(
            f"{FREE_AGENCY_CALENDAR_ATTR} must be a mapping when present."
        )
    payload = copy.deepcopy(dict(raw))
    payload.setdefault("version", FREE_AGENCY_PERSISTENT_CALENDAR_VERSION)
    payload.setdefault("season_label", _season(state))
    payload.setdefault("initialized", False)
    payload.setdefault("offseason_day", 0)
    payload.setdefault("revision", 0)
    payload.setdefault("active_markets", {})
    payload.setdefault("archived_markets", [])
    payload.setdefault("day_history", [])
    if not isinstance(payload["active_markets"], Mapping):
        raise FreeAgencyPersistentCalendarError("active_markets must be a mapping.")
    if not isinstance(payload["archived_markets"], list):
        raise FreeAgencyPersistentCalendarError("archived_markets must be a list.")
    if not isinstance(payload["day_history"], list):
        raise FreeAgencyPersistentCalendarError("day_history must be a list.")
    return payload


def _calendar_fingerprint(payload: Mapping[str, Any]) -> str:
    safe = {
        "version": _clean(payload.get("version", "")),
        "season_label": _clean(payload.get("season_label", "")),
        "initialized": bool(payload.get("initialized", False)),
        "offseason_day": int(payload.get("offseason_day", 0) or 0),
        "revision": int(payload.get("revision", 0) or 0),
        "active_markets": _json_safe(payload.get("active_markets", {})),
        "archived_markets": _json_safe(payload.get("archived_markets", [])),
        "day_history": _json_safe(payload.get("day_history", [])),
    }
    return _fingerprint(safe)


def persistent_calendar_fingerprint(state: Any) -> str:
    return _calendar_fingerprint(_normalized_calendar_payload(state))


def _record_status(result: FreeAgencyNegotiationRoundResult) -> str:
    if result.ready_to_sign:
        return "ready_to_sign_user" if result.user_is_winner else "ready_to_sign_cpu"
    response = _clean(result.player_response).lower()
    if response in {"hold", "counter_market", "exploring_market"}:
        return response
    if response == "no_acceptable_offer":
        return "closed_no_acceptable_offer"
    return "open"


def _serialize_round_history(result: FreeAgencyNegotiationRoundResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in result.history:
        rows.append({
            "round_number": int(row.round_number),
            "round_label": _clean(row.round_label),
            "player_response": _clean(row.player_response),
            "winner_team_abbreviation": _team(row.winner_team_abbreviation) or None,
            "winner_utility_score": (
                float(row.winner_utility_score)
                if row.winner_utility_score is not None
                else None
            ),
            "winning_margin": (
                float(row.winning_margin)
                if row.winning_margin is not None
                else None
            ),
            "active_cpu_offer_count": int(row.active_cpu_offer_count),
            "increased_cpu_offer_count": int(row.increased_cpu_offer_count),
            "withdrawn_cpu_offer_count": int(row.withdrawn_cpu_offer_count),
            "market_fingerprint": _clean(row.market_fingerprint),
        })
    return rows


def _serialize_cpu_offers(result: FreeAgencyNegotiationRoundResult) -> list[dict[str, Any]]:
    return [
        {
            "team_abbreviation": _team(row.team_abbreviation),
            "action": _clean(row.action),
            "action_reason": _clean(row.action_reason),
            "prior_salary": float(row.prior_salary),
            "annual_salary": float(row.annual_salary),
            "years": int(row.years),
            "target_fit_score": float(row.target_fit_score),
            "team_direction": _clean(row.team_direction),
            "salary_posture": _clean(row.salary_posture),
            "minimum_salary_floor": float(row.minimum_salary_floor),
            "maximum_initial_salary": float(row.maximum_initial_salary),
            "cap_space_before": float(row.cap_space_before),
            "offer_fingerprint": _clean(row.offer_fingerprint),
        }
        for row in result.cpu_offers
    ]


def _serialize_evaluations(result: FreeAgencyNegotiationRoundResult) -> list[dict[str, Any]]:
    return [
        {
            "rank": int(row.rank),
            "team_abbreviation": _team(row.team_abbreviation),
            "offer_id": _clean(row.offer_id),
            "annual_salary": float(row.annual_salary),
            "years": int(row.years),
            "guaranteed": bool(row.guaranteed),
            "option_type": _clean(row.option_type),
            "utility_score": float(row.utility_score),
            "acceptance_threshold": float(row.acceptance_threshold),
            "player_decision_status": _clean(row.player_decision_status),
            "decision_fingerprint": _clean(row.decision_fingerprint),
            "source_fingerprint": _clean(row.source_fingerprint),
            "accepted": bool(row.accepted),
            "utility_gap_to_winner": (
                float(row.utility_gap_to_winner)
                if row.utility_gap_to_winner is not None
                else None
            ),
        }
        for row in result.market.evaluations
    ]


def _record_from_result(
    result: FreeAgencyNegotiationRoundResult,
    offer: Any,
    *,
    market_id: str,
    created_day: int,
    last_updated_day: int,
    prior_round_history: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    full_history = _serialize_round_history(result)
    if prior_round_history is not None:
        old = [copy.deepcopy(dict(row)) for row in prior_round_history]
        latest = full_history[-1:] if full_history else []
        history = old
        seen_rounds = {int(row.get("round_number", 0) or 0) for row in history}
        for row in latest:
            if int(row.get("round_number", 0) or 0) not in seen_rounds:
                history.append(row)
    else:
        history = full_history

    return {
        "market_id": market_id,
        "season_label": result.season_label,
        "player_id": result.player_id,
        "player_name": result.player_name,
        "user_team_abbreviation": result.user_team_abbreviation,
        "offer": _offer_payload(offer),
        "created_day": int(created_day),
        "last_updated_day": int(last_updated_day),
        "current_round": int(result.round_number),
        "max_rounds": int(result.max_rounds),
        "status": _record_status(result),
        "player_response": result.player_response,
        "player_response_reason": result.player_response_reason,
        "winner_team_abbreviation": (
            _team(result.market.winner_team_abbreviation)
            if result.market.winner_team_abbreviation
            else None
        ),
        "winner_utility_score": (
            float(result.market.winner_utility_score)
            if result.market.winner_utility_score is not None
            else None
        ),
        "winning_margin": (
            float(result.market.winning_margin)
            if result.market.winning_margin is not None
            else None
        ),
        "source_state_fingerprint": result.source_state_fingerprint,
        "user_preview_source_fingerprint": result.user_preview_source_fingerprint,
        "user_offer_fingerprint": result.user_offer_fingerprint,
        "base_cpu_board_fingerprint": result.base_cpu_board_fingerprint,
        "negotiation_fingerprint": result.negotiation_fingerprint,
        "market_fingerprint": result.market.market_fingerprint,
        "active_cpu_offer_count": len(result.cpu_offers),
        "current_cpu_offers": _serialize_cpu_offers(result),
        "current_evaluations": _serialize_evaluations(result),
        "round_history": history,
    }


def _record_dataclass(record: Mapping[str, Any]) -> PersistentFreeAgencyMarketRecord:
    offer = dict(record.get("offer", {}) or {})
    return PersistentFreeAgencyMarketRecord(
        market_id=_clean(record.get("market_id", "")),
        season_label=_clean(record.get("season_label", "")),
        player_id=_clean(record.get("player_id", "")),
        player_name=_clean(record.get("player_name", "")),
        user_team_abbreviation=_team(record.get("user_team_abbreviation", "")),
        annual_salary=float(offer.get("annual_salary", 0.0) or 0.0),
        years=int(offer.get("years", 0) or 0),
        guaranteed=bool(offer.get("guaranteed", False)),
        option_type=_clean(offer.get("option_type", "")),
        created_day=int(record.get("created_day", 0) or 0),
        last_updated_day=int(record.get("last_updated_day", 0) or 0),
        current_round=int(record.get("current_round", 0) or 0),
        max_rounds=int(record.get("max_rounds", MAX_FREE_AGENCY_NEGOTIATION_ROUNDS) or MAX_FREE_AGENCY_NEGOTIATION_ROUNDS),
        status=_clean(record.get("status", "")),
        player_response=_clean(record.get("player_response", "")),
        winner_team_abbreviation=(
            _team(record.get("winner_team_abbreviation", "")) or None
        ),
        winning_margin=(
            float(record.get("winning_margin"))
            if record.get("winning_margin") is not None
            else None
        ),
        source_state_fingerprint=_clean(record.get("source_state_fingerprint", "")),
        user_offer_fingerprint=_clean(record.get("user_offer_fingerprint", "")),
        negotiation_fingerprint=_clean(record.get("negotiation_fingerprint", "")),
        market_fingerprint=_clean(record.get("market_fingerprint", "")),
        active_cpu_offer_count=int(record.get("active_cpu_offer_count", 0) or 0),
        round_history=tuple(copy.deepcopy(list(record.get("round_history", []) or []))),
        current_cpu_offers=tuple(copy.deepcopy(list(record.get("current_cpu_offers", []) or []))),
        current_evaluations=tuple(copy.deepcopy(list(record.get("current_evaluations", []) or []))),
    )


def _player_is_live_free_agent(state: Any, player_id: str) -> bool:
    return _clean(player_id) in {
        _clean(value) for value in getattr(state, "free_agent_player_ids", ())
    }


def free_agency_calendar_snapshot(state: Any) -> FreeAgencyCalendarSnapshot:
    payload = _normalized_calendar_payload(state)
    active: list[PersistentFreeAgencyMarketRecord] = []
    for key, raw in sorted(dict(payload["active_markets"]).items()):
        record = copy.deepcopy(dict(raw))
        record.setdefault("market_id", key)
        parsed = _record_dataclass(record)
        # Effective active view fails closed after another signing. The stale row
        # remains in the durable payload until the next explicit calendar write.
        if parsed.is_open and _player_is_live_free_agent(state, parsed.player_id):
            active.append(parsed)
    return FreeAgencyCalendarSnapshot(
        version=_clean(payload.get("version", "")),
        initialized=bool(payload.get("initialized", False)),
        season_label=_clean(payload.get("season_label", "")),
        offseason_day=int(payload.get("offseason_day", 0) or 0),
        revision=int(payload.get("revision", 0) or 0),
        active_market_count=len(active),
        archived_market_count=len(list(payload.get("archived_markets", []) or [])),
        active_markets=tuple(active),
        day_history=tuple(copy.deepcopy(list(payload.get("day_history", []) or []))),
        calendar_fingerprint=_calendar_fingerprint(payload),
    )


def persistent_market_for_player_team(
    state: Any,
    player_id: str,
    team_abbreviation: str,
) -> PersistentFreeAgencyMarketRecord | None:
    player_id = _clean(player_id)
    team = _team(team_abbreviation)
    for record in free_agency_calendar_snapshot(state).active_markets:
        if record.player_id == player_id and record.user_team_abbreviation == team:
            return record
    return None


def _ensure_offseason(state: Any) -> None:
    if _phase(state) != "offseason":
        raise FreeAgencyPersistentCalendarError(
            "Persistent free-agency calendar writes are available only during the actual offseason."
        )


def initialize_free_agency_calendar_candidate(state: Any) -> Any:
    _ensure_offseason(state)
    candidate = copy.deepcopy(state)
    payload = _normalized_calendar_payload(candidate)
    if payload["initialized"]:
        return candidate
    payload["initialized"] = True
    payload["season_label"] = _season(candidate)
    payload["offseason_day"] = 1
    payload["revision"] = int(payload.get("revision", 0) or 0) + 1
    payload["day_history"].append({
        "day": 1,
        "action": "calendar_initialized",
        "markets_advanced": 0,
        "active_market_count": 0,
    })
    setattr(candidate, FREE_AGENCY_CALENDAR_ATTR, payload)
    return candidate


def _preview_for_record(
    state: Any,
    record: Mapping[str, Any],
    *,
    preview_builder: Any | None = None,
) -> Any:
    offer = _offer_from_payload(dict(record.get("offer", {}) or {}))
    builder = preview_builder or build_contract_legal_free_agency_preview
    preview = builder(state, offer)
    if (
        _clean(getattr(preview, "status", "")).lower() != "pass"
        or not bool(getattr(preview, "can_commit", False))
    ):
        raise FreeAgencyPersistentCalendarError(
            "The persisted user offer no longer clears the locked free-agency backend."
        )
    return preview


def build_persistent_negotiation_result(
    state: Any,
    record: PersistentFreeAgencyMarketRecord | Mapping[str, Any],
    *,
    controlled_teams: Iterable[str],
    front_office_plan: Any | None = None,
    cpu_offer_board: Any | None = None,
    preview_builder: Any | None = None,
) -> FreeAgencyNegotiationRoundResult:
    if isinstance(record, PersistentFreeAgencyMarketRecord):
        raw = {
            "offer": {
                "player_id": record.player_id,
                "team_abbreviation": record.user_team_abbreviation,
                "annual_salary": record.annual_salary,
                "years": record.years,
                "guaranteed": record.guaranteed,
                "option_type": record.option_type,
            },
            "current_round": record.current_round,
        }
    else:
        raw = dict(record)
    preview = _preview_for_record(state, raw, preview_builder=preview_builder)
    return build_free_agency_negotiation_round(
        state,
        preview,
        controlled_teams=controlled_teams,
        round_number=int(raw.get("current_round", 1) or 1),
        front_office_plan=front_office_plan,
        cpu_offer_board=cpu_offer_board,
        preview_builder=preview_builder,
    )


def persist_negotiation_candidate(
    state: Any,
    user_preview: Any,
    *,
    controlled_teams: Iterable[str],
    front_office_plan: Any | None = None,
    cpu_offer_board: Any | None = None,
    preview_builder: Any | None = None,
) -> tuple[Any, PersistentFreeAgencyMarketRecord, FreeAgencyNegotiationRoundResult]:
    """Create/replace one durable market in an isolated candidate state."""
    _ensure_offseason(state)
    if (
        _clean(getattr(user_preview, "status", "")).lower() != "pass"
        or not bool(getattr(user_preview, "can_commit", False))
    ):
        raise FreeAgencyPersistentCalendarError(
            "Only a backend-PASS user offer can be persisted into the offseason calendar."
        )
    if preview_builder is None:
        if _clean(getattr(user_preview, "source_fingerprint", "")) != free_agency_state_fingerprint(state):
            raise FreeAgencyPersistentCalendarError(
                "The user offer preview is stale relative to the durable franchise state."
            )
    else:
        source_offer = getattr(user_preview, "offer", None)
        rebuilt_preview = preview_builder(state, source_offer) if source_offer is not None else None
        if (
            rebuilt_preview is None
            or _clean(getattr(rebuilt_preview, "source_fingerprint", ""))
            != _clean(getattr(user_preview, "source_fingerprint", ""))
        ):
            raise FreeAgencyPersistentCalendarError(
                "The supplied test preview is stale relative to its preview builder."
            )

    candidate = copy.deepcopy(state)
    payload = _normalized_calendar_payload(candidate)
    if not payload["initialized"]:
        candidate = initialize_free_agency_calendar_candidate(candidate)
        payload = _normalized_calendar_payload(candidate)

    result = build_free_agency_negotiation_round(
        candidate,
        user_preview,
        controlled_teams=controlled_teams,
        round_number=1,
        front_office_plan=front_office_plan,
        cpu_offer_board=cpu_offer_board,
        preview_builder=preview_builder,
    )
    offer = getattr(user_preview, "offer", None)
    if offer is None:
        raise FreeAgencyPersistentCalendarError("The user preview contains no offer.")
    market_id = _market_id(_season(candidate), offer)
    day = int(payload["offseason_day"] or 1)

    existing = dict(payload["active_markets"]).get(market_id)
    if existing is not None:
        archived = copy.deepcopy(dict(existing))
        archived["status"] = "superseded_user_offer"
        archived["archived_day"] = day
        payload["archived_markets"].append(archived)

    record = _record_from_result(
        result,
        offer,
        market_id=market_id,
        created_day=day,
        last_updated_day=day,
    )
    payload["active_markets"][market_id] = record
    payload["revision"] = int(payload.get("revision", 0) or 0) + 1
    setattr(candidate, FREE_AGENCY_CALENDAR_ATTR, payload)
    return candidate, _record_dataclass(record), result


def _reconcile_unavailable_markets(state: Any, payload: dict[str, Any], *, day: int) -> int:
    closed = 0
    for market_id, raw in list(dict(payload["active_markets"]).items()):
        record = copy.deepcopy(dict(raw))
        if _player_is_live_free_agent(state, _clean(record.get("player_id", ""))):
            continue
        record["status"] = "closed_player_unavailable"
        record["archived_day"] = int(day)
        payload["archived_markets"].append(record)
        payload["active_markets"].pop(market_id, None)
        closed += 1
    return closed


def advance_free_agency_day_candidate(
    state: Any,
    *,
    controlled_teams: Iterable[str],
    front_office_plan: Any | None = None,
    cpu_offer_board: Any | None = None,
    preview_builder: Any | None = None,
) -> tuple[Any, dict[str, int]]:
    """Advance the durable free-agency calendar exactly one day in memory.

    Every open persisted user market advances at most one negotiation round. No
    user or CPU signing is committed by this function.
    """
    _ensure_offseason(state)
    candidate = copy.deepcopy(state)
    payload = _normalized_calendar_payload(candidate)
    if not payload["initialized"]:
        candidate = initialize_free_agency_calendar_candidate(candidate)
        payload = _normalized_calendar_payload(candidate)

    prior_day = int(payload["offseason_day"] or 1)
    if prior_day >= MAX_FREE_AGENCY_CALENDAR_DAYS:
        raise FreeAgencyPersistentCalendarError(
            f"The V1 free-agency calendar is capped at {MAX_FREE_AGENCY_CALENDAR_DAYS} explicit days."
        )
    next_day = prior_day + 1
    closed = _reconcile_unavailable_markets(candidate, payload, day=next_day)
    advanced = 0
    held = 0
    ready_user = 0
    ready_cpu = 0

    for market_id in sorted(list(dict(payload["active_markets"]))):
        raw = copy.deepcopy(dict(payload["active_markets"][market_id]))
        status = _clean(raw.get("status", ""))
        current_round = int(raw.get("current_round", 1) or 1)
        if status in {"ready_to_sign_user", "ready_to_sign_cpu"}:
            if status == "ready_to_sign_user":
                ready_user += 1
            else:
                ready_cpu += 1
            continue
        if current_round >= MAX_FREE_AGENCY_NEGOTIATION_ROUNDS:
            raw["status"] = "closed_no_acceptable_offer"
            raw["last_updated_day"] = next_day
            payload["archived_markets"].append(raw)
            payload["active_markets"].pop(market_id, None)
            closed += 1
            continue
        try:
            preview = _preview_for_record(candidate, raw, preview_builder=preview_builder)
            result = build_free_agency_negotiation_round(
                candidate,
                preview,
                controlled_teams=controlled_teams,
                round_number=current_round + 1,
                front_office_plan=front_office_plan,
                cpu_offer_board=cpu_offer_board,
                preview_builder=preview_builder,
            )
        except Exception as exc:
            raw["status"] = "stale_or_illegal"
            raw["archived_day"] = next_day
            raw["archive_reason"] = f"{type(exc).__name__}: {exc}"
            payload["archived_markets"].append(raw)
            payload["active_markets"].pop(market_id, None)
            closed += 1
            continue

        offer = getattr(preview, "offer", None)
        replacement = _record_from_result(
            result,
            offer,
            market_id=market_id,
            created_day=int(raw.get("created_day", prior_day) or prior_day),
            last_updated_day=next_day,
            prior_round_history=list(raw.get("round_history", []) or []),
        )
        payload["active_markets"][market_id] = replacement
        advanced += 1
        if replacement["status"] == "ready_to_sign_user":
            ready_user += 1
        elif replacement["status"] == "ready_to_sign_cpu":
            ready_cpu += 1
        elif replacement["status"] == "hold":
            held += 1
        elif replacement["status"] == "closed_no_acceptable_offer":
            archived = copy.deepcopy(replacement)
            archived["archived_day"] = next_day
            payload["archived_markets"].append(archived)
            payload["active_markets"].pop(market_id, None)
            closed += 1

    payload["offseason_day"] = next_day
    payload["revision"] = int(payload.get("revision", 0) or 0) + 1
    payload["day_history"].append({
        "day": next_day,
        "action": "advance_free_agency_day",
        "markets_advanced": advanced,
        "markets_held": held,
        "markets_ready_user": ready_user,
        "markets_ready_cpu": ready_cpu,
        "markets_closed": closed,
        "active_market_count": len(payload["active_markets"]),
    })
    setattr(candidate, FREE_AGENCY_CALENDAR_ATTR, payload)
    return candidate, {
        "prior_day": prior_day,
        "current_day": next_day,
        "markets_advanced": advanced,
        "markets_held": held,
        "markets_ready_user": ready_user,
        "markets_ready_cpu": ready_cpu,
        "markets_closed": closed,
    }


def _checkpoint_functions():
    from simulation_franchise_checkpoint_v1 import (
        DEFAULT_CHECKPOINT_PATH,
        load_franchise_checkpoint,
        save_franchise_checkpoint,
    )
    return Path(DEFAULT_CHECKPOINT_PATH), load_franchise_checkpoint, save_franchise_checkpoint


def _load_checkpoint(load_fn: Any, checkpoint_path: Path | None = None) -> Any:
    sig = inspect.signature(load_fn)
    if checkpoint_path is not None:
        if "checkpoint_path" not in sig.parameters:
            raise FreeAgencyPersistentCalendarError(
                "This checkpoint loader does not expose a checkpoint_path test hook."
            )
        return load_fn(checkpoint_path=checkpoint_path)
    return load_fn()


def _save_checkpoint(
    save_fn: Any,
    state: Any,
    trade_state: Any,
    preferences: Mapping[str, Any],
    *,
    reason: str,
    checkpoint_path: Path | None = None,
) -> Any:
    sig = inspect.signature(save_fn)
    kwargs: dict[str, Any] = {}
    if "preferences" in sig.parameters:
        kwargs["preferences"] = copy.deepcopy(dict(preferences or {}))
    if "reason" in sig.parameters:
        kwargs["reason"] = reason
    if "copy_payload" in sig.parameters:
        kwargs["copy_payload"] = True
    if checkpoint_path is not None:
        if "checkpoint_path" not in sig.parameters:
            raise FreeAgencyPersistentCalendarError(
                "This checkpoint saver does not expose a checkpoint_path test hook."
            )
        kwargs["checkpoint_path"] = checkpoint_path
    return save_fn(state, trade_state, **kwargs)


def _durable_write_candidate(
    candidate_state: Any,
    *,
    action: str,
    expected_calendar_fingerprint: str,
    recovery_directory: str | Path | None = None,
    checkpoint_path_override: str | Path | None = None,
) -> FreeAgencyCalendarWriteResult:
    default_path, load_fn, save_fn = _checkpoint_functions()
    checkpoint_path = Path(checkpoint_path_override) if checkpoint_path_override is not None else default_path
    if not checkpoint_path.exists():
        raise FreeAgencyPersistentCalendarError("Durable franchise checkpoint does not exist.")
    checkpoint = _load_checkpoint(load_fn, checkpoint_path if checkpoint_path_override is not None else None)
    if checkpoint is None:
        raise FreeAgencyPersistentCalendarError("Durable franchise checkpoint could not be loaded.")

    source_state = checkpoint.simulation_state
    source_trade = checkpoint.trade_state
    source_state_fp = free_agency_state_fingerprint(source_state)
    source_trade_fp = trade_state_fingerprint(source_trade)
    if free_agency_state_fingerprint(candidate_state) != source_state_fp:
        raise FreeAgencyPersistentCalendarError(
            "Calendar-only write attempted to change roster/contract/free-agent franchise state."
        )

    hash_before = _sha256(checkpoint_path)
    recovery_root = (
        Path(recovery_directory)
        if recovery_directory is not None
        else checkpoint_path.parent / "free_agency_calendar_recovery"
    )
    recovery_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    revision = int(_normalized_calendar_payload(candidate_state).get("revision", 0) or 0)
    recovery_path = recovery_root / f"pre_FACAL_{revision:04d}_{stamp}_{checkpoint_path.name}"
    shutil.copy2(checkpoint_path, recovery_path)
    reason = f"free-agency-calendar-{action}-r{revision}"

    try:
        _save_checkpoint(
            save_fn,
            candidate_state,
            source_trade,
            getattr(checkpoint, "preferences", {}) or {},
            reason=reason,
            checkpoint_path=(checkpoint_path if checkpoint_path_override is not None else None),
        )
        reloaded = _load_checkpoint(load_fn, checkpoint_path if checkpoint_path_override is not None else None)
        if reloaded is None:
            raise FreeAgencyPersistentCalendarError("Checkpoint reload returned no state.")
        observed_calendar = persistent_calendar_fingerprint(reloaded.simulation_state)
        if observed_calendar != expected_calendar_fingerprint:
            raise FreeAgencyPersistentCalendarError(
                "Reloaded free-agency calendar does not match the approved candidate."
            )
        if free_agency_state_fingerprint(reloaded.simulation_state) != source_state_fp:
            raise FreeAgencyPersistentCalendarError(
                "Calendar write changed roster/contract/free-agent franchise state."
            )
        if trade_state_fingerprint(reloaded.trade_state) != source_trade_fp:
            raise FreeAgencyPersistentCalendarError(
                "Calendar write changed Trade Machine state."
            )
    except Exception as exc:
        shutil.copy2(recovery_path, checkpoint_path)
        restored = _load_checkpoint(load_fn, checkpoint_path if checkpoint_path_override is not None else None)
        if restored is None:
            raise FreeAgencyPersistentCalendarError(
                "Calendar write failed and recovery checkpoint could not be loaded."
            ) from exc
        if (
            free_agency_state_fingerprint(restored.simulation_state) != source_state_fp
            or trade_state_fingerprint(restored.trade_state) != source_trade_fp
        ):
            raise FreeAgencyPersistentCalendarError(
                "Calendar write failed and automatic recovery could not be verified."
            ) from exc
        raise FreeAgencyPersistentCalendarError(
            f"Calendar write failed. The prior checkpoint was restored: {exc}"
        ) from exc

    snapshot = free_agency_calendar_snapshot(candidate_state)
    return FreeAgencyCalendarWriteResult(
        version=FREE_AGENCY_PERSISTENT_CALENDAR_VERSION,
        action=action,
        season_label=snapshot.season_label,
        offseason_day=snapshot.offseason_day,
        revision=snapshot.revision,
        calendar_fingerprint=expected_calendar_fingerprint,
        checkpoint_hash_before=hash_before,
        checkpoint_hash_after=_sha256(checkpoint_path),
        recovery_path=str(recovery_path),
        checkpoint_reason=reason,
    )


def initialize_free_agency_calendar_durably(
    *,
    recovery_directory: str | Path | None = None,
) -> FreeAgencyCalendarWriteResult:
    _, load_fn, _ = _checkpoint_functions()
    checkpoint = _load_checkpoint(load_fn)
    if checkpoint is None:
        raise FreeAgencyPersistentCalendarError("Durable franchise checkpoint is unavailable.")
    state = checkpoint.simulation_state
    _ensure_offseason(state)
    candidate = initialize_free_agency_calendar_candidate(state)
    expected = persistent_calendar_fingerprint(candidate)
    return _durable_write_candidate(
        candidate,
        action="initialize",
        expected_calendar_fingerprint=expected,
        recovery_directory=recovery_directory,
    )


def persist_user_negotiation_durably(
    user_preview: Any,
    *,
    recovery_directory: str | Path | None = None,
) -> tuple[FreeAgencyCalendarWriteResult, PersistentFreeAgencyMarketRecord]:
    _, load_fn, _ = _checkpoint_functions()
    checkpoint = _load_checkpoint(load_fn)
    if checkpoint is None:
        raise FreeAgencyPersistentCalendarError("Durable franchise checkpoint is unavailable.")
    state = checkpoint.simulation_state
    _ensure_offseason(state)
    if _clean(getattr(user_preview, "source_fingerprint", "")) != free_agency_state_fingerprint(state):
        raise FreeAgencyPersistentCalendarError(
            "The user preview is stale relative to the durable checkpoint."
        )
    controlled = controlled_teams_from_durable_checkpoint(checkpoint)
    candidate, record, _ = persist_negotiation_candidate(
        state,
        user_preview,
        controlled_teams=controlled,
    )
    expected = persistent_calendar_fingerprint(candidate)
    write = _durable_write_candidate(
        candidate,
        action=f"persist-{record.market_id}",
        expected_calendar_fingerprint=expected,
        recovery_directory=recovery_directory,
    )
    return write, record


def advance_free_agency_day_durably(
    *,
    recovery_directory: str | Path | None = None,
) -> FreeAgencyDayAdvanceResult:
    _, load_fn, _ = _checkpoint_functions()
    checkpoint = _load_checkpoint(load_fn)
    if checkpoint is None:
        raise FreeAgencyPersistentCalendarError("Durable franchise checkpoint is unavailable.")
    state = checkpoint.simulation_state
    _ensure_offseason(state)
    controlled = controlled_teams_from_durable_checkpoint(checkpoint)
    candidate, detail = advance_free_agency_day_candidate(
        state,
        controlled_teams=controlled,
    )
    expected = persistent_calendar_fingerprint(candidate)
    write = _durable_write_candidate(
        candidate,
        action=f"advance-day-{detail['current_day']}",
        expected_calendar_fingerprint=expected,
        recovery_directory=recovery_directory,
    )
    return FreeAgencyDayAdvanceResult(
        version=FREE_AGENCY_PERSISTENT_CALENDAR_VERSION,
        prior_day=int(detail["prior_day"]),
        current_day=int(detail["current_day"]),
        markets_advanced=int(detail["markets_advanced"]),
        markets_held=int(detail["markets_held"]),
        markets_ready_user=int(detail["markets_ready_user"]),
        markets_ready_cpu=int(detail["markets_ready_cpu"]),
        markets_closed=int(detail["markets_closed"]),
        write_result=write,
    )


def commit_persistent_user_winner_live(
    market_id: str,
    *,
    hypothetical: bool = False,
) -> Any:
    """Rebuild and commit the exact persisted user market through the locked stack."""
    if hypothetical:
        raise FreeAgencyPersistentCalendarError(
            "A hypothetical persistent free-agency market can never be committed."
        )
    _, load_fn, _ = _checkpoint_functions()
    checkpoint = _load_checkpoint(load_fn)
    if checkpoint is None:
        raise FreeAgencyPersistentCalendarError("Durable franchise checkpoint is unavailable.")
    state = checkpoint.simulation_state
    _ensure_offseason(state)
    payload = _normalized_calendar_payload(state)
    raw = dict(payload["active_markets"]).get(_clean(market_id))
    if raw is None:
        raise FreeAgencyPersistentCalendarError("The persistent free-agency market is no longer active.")
    record = _record_dataclass(raw)
    controlled = controlled_teams_from_durable_checkpoint(checkpoint)
    preview = _preview_for_record(state, raw)
    result = build_free_agency_negotiation_round(
        state,
        preview,
        controlled_teams=controlled,
        round_number=record.current_round,
    )
    if result.negotiation_fingerprint != record.negotiation_fingerprint:
        raise FreeAgencyPersistentCalendarError(
            "The persisted negotiation is stale relative to the durable franchise state or CPU market."
        )
    if not result.user_can_commit:
        raise FreeAgencyPersistentCalendarError(
            "The persistent market is not a READY TO SIGN user-market victory."
        )
    # The locked negotiation wrapper reloads durable state again and performs the
    # existing synchronized FATX + Trade Machine + checkpoint recovery workflow.
    return commit_negotiated_user_winner_live(
        preview,
        result,
        hypothetical=False,
    )


def persistent_calendar_contract_report() -> dict[str, Any]:
    return {
        "version": FREE_AGENCY_PERSISTENT_CALENDAR_VERSION,
        "scope": FREE_AGENCY_PERSISTENT_CALENDAR_SCOPE,
        "negotiation_rounds_version": FREE_AGENCY_NEGOTIATION_ROUNDS_VERSION,
        "salary_legality_version": FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION,
        "live_signing_version": FREE_AGENCY_LIVE_SIGNING_VERSION,
        "calendar_attr": FREE_AGENCY_CALENDAR_ATTR,
        "max_calendar_days": MAX_FREE_AGENCY_CALENDAR_DAYS,
        "max_negotiation_rounds": MAX_FREE_AGENCY_NEGOTIATION_ROUNDS,
        "checkpoint_owned": True,
        "supports_multiple_user_markets": True,
        "explicit_day_advance_required": True,
        "background_advancement_enabled": False,
        "background_cpu_signing_enabled": False,
        "writes_trade_state": False,
        "writes_roster_or_contract_state": False,
    }
