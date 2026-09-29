
from __future__ import annotations

import copy
import hashlib
import json
import math
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from franchise_free_agency_transaction_v1 import (
    FreeAgencyFinancialGateResult,
    FreeAgencyOffer,
    FreeAgencyTransactionPreview,
    build_free_agency_preview,
    free_agency_state_fingerprint,
)
from franchise_free_agency_transaction_v1_1 import (
    build_free_agency_durable_candidate,
)
from franchise_free_agency_contract_salary_legality_v1_3 import (
    build_contract_legal_free_agency_preview,
    evaluate_contract_legal_financial_gate,
)
from franchise_free_agency_live_signing_v1 import (
    _align_simulation_source_to_trade_state,
    build_trade_state_free_agency_candidate,
    controlled_teams_from_durable_checkpoint,
    free_agency_durable_state_fingerprint,
    trade_state_fingerprint,
)
from franchise_free_agency_negotiation_rounds_v1 import (
    MAX_FREE_AGENCY_NEGOTIATION_ROUNDS,
    build_free_agency_negotiation_round,
)
from franchise_free_agency_persistent_calendar_v1 import (
    free_agency_calendar_snapshot,
)
from franchise_free_agency_rfa_qo_lifecycle_v1 import (
    RFA_LEDGER_ATTR,
    _decision_fingerprint,
    _projected_action_candidates,
)

RFA_OFFER_SHEET_VERSION = (
    "franchise-free-agency-rfa-offer-sheet-v1-2026-08-16"
)
RFA_OFFER_SHEET_SCOPE = (
    "external-rfa-offer-sheet-right-of-first-refusal-match-decline"
)

ACTIVE_ATTR = "offseason_rfa_offer_sheets_v1"
HISTORY_ATTR = "offseason_rfa_offer_sheet_history_v1"

MIN_OFFER_SHEET_YEARS = 2
MATCH_WINDOW_DAYS = 2

STATUS_PENDING = "pending_right_of_first_refusal"
STATUS_MATCHED = "matched"
STATUS_DECLINED = "declined"

DECISION_MATCH = "match"
DECISION_DECLINE = "decline"


class RFAOfferSheetError(RuntimeError):
    pass


@dataclass(frozen=True)
class RFAOfferSheetPreview:
    version: str
    player_id: str
    player_name: str
    prior_team: str
    offering_team: str
    annual_salary: float
    years: int
    guaranteed: bool
    option_type: str
    offer_id: str
    qo_amount: float | None
    rights_charge: float
    created_day: int
    match_deadline_day: int
    accepted_round: int
    source_simulation_fingerprint: str
    source_trade_fingerprint: str
    confirmation_token: str


@dataclass(frozen=True)
class RFAOfferSheetWriteResult:
    version: str
    offer_sheet_id: str
    player_id: str
    player_name: str
    prior_team: str
    offering_team: str
    annual_salary: float
    years: int
    created_day: int
    match_deadline_day: int
    status: str
    trade_revision_before: int
    trade_revision_after: int
    checkpoint_hash_before: str
    checkpoint_hash_after: str
    recovery_primary_path: str
    recovery_backup_path: str | None


@dataclass(frozen=True)
class RFAOfferSheetResolutionResult:
    version: str
    offer_sheet_id: str
    decision: str
    destination_team: str
    player_id: str
    player_name: str
    annual_salary: float
    years: int
    rights_charge_released: float
    fatx_transaction_id: str
    trade_revision_before: int
    trade_revision_after: int
    checkpoint_hash_before: str
    checkpoint_hash_after: str
    recovery_primary_path: str
    recovery_backup_path: str | None


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _pid(value: Any) -> str:
    text = _clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _amount(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _sha256(path: Path) -> str:
    d = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            d.update(block)
    return d.hexdigest()


def _phase(state: Any) -> str:
    phase = getattr(state, "phase", None)
    return _clean(getattr(phase, "value", phase)).lower()


def _rfa_rows(state: Any) -> list[dict[str, Any]]:
    rows = [
        dict(row)
        for row in list(getattr(state, RFA_LEDGER_ATTR, ()) or ())
        if isinstance(row, Mapping)
    ]
    if len(rows) != 64:
        raise RFAOfferSheetError(
            f"Expected the verified 64-player RFA ledger, found {len(rows)}."
        )
    return rows


def _rfa_row(state: Any, player_id: str) -> dict[str, Any]:
    target = _pid(player_id)
    rows = [
        row
        for row in _rfa_rows(state)
        if _pid(row.get("player_id")) == target
    ]
    if len(rows) != 1:
        raise RFAOfferSheetError(
            f"Expected exactly one RFA row for {target!r}, found {len(rows)}."
        )
    return dict(rows[0])


def _active_map(state: Any) -> dict[str, dict[str, Any]]:
    raw = getattr(state, ACTIVE_ATTR, {})
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise RFAOfferSheetError(
            f"{ACTIVE_ATTR} must be a mapping when present."
        )
    return {
        _clean(key): copy.deepcopy(dict(value))
        for key, value in raw.items()
        if isinstance(value, Mapping)
    }


def _history(state: Any) -> list[dict[str, Any]]:
    raw = getattr(state, HISTORY_ATTR, [])
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise RFAOfferSheetError(
            f"{HISTORY_ATTR} must be a list when present."
        )
    return copy.deepcopy(raw)


def _set_offer_sheet_state(
    state: Any,
    *,
    active: Mapping[str, Mapping[str, Any]],
    history: list[dict[str, Any]],
) -> None:
    setattr(
        state,
        ACTIVE_ATTR,
        {
            str(key): copy.deepcopy(dict(value))
            for key, value in active.items()
        },
    )
    setattr(
        state,
        HISTORY_ATTR,
        copy.deepcopy(history),
    )


def pending_offer_sheets(state: Any) -> tuple[dict[str, Any], ...]:
    return tuple(
        copy.deepcopy(record)
        for _, record in sorted(_active_map(state).items())
        if _clean(record.get("status")) == STATUS_PENDING
    )


def pending_offer_sheet_for_team(
    state: Any,
    team_abbreviation: str,
) -> dict[str, Any] | None:
    team = _team(team_abbreviation)
    for record in pending_offer_sheets(state):
        if team in {
            _team(record.get("offering_team")),
            _team(record.get("prior_team")),
        }:
            return copy.deepcopy(record)
    return None


def pending_offer_sheet_for_player(
    state: Any,
    player_id: str,
) -> dict[str, Any] | None:
    pid = _pid(player_id)
    for record in pending_offer_sheets(state):
        if _pid(record.get("player_id")) == pid:
            return copy.deepcopy(record)
    return None


def _offer_sheet_fingerprint(
    simulation_state: Any,
    trade_state: Any,
) -> str:
    payload = {
        "simulation_base": free_agency_state_fingerprint(simulation_state),
        "trade_base": trade_state_fingerprint(trade_state),
        "rfa_decision_financial_state": _decision_fingerprint(
            simulation_state,
            trade_state,
        ),
        "simulation_active": _active_map(simulation_state),
        "simulation_history": _history(simulation_state),
        "trade_active": _active_map(trade_state),
        "trade_history": _history(trade_state),
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _confirmation_token(
    *,
    player_id: str,
    offering_team: str,
    annual_salary: float,
    years: int,
) -> str:
    salary = int(round(float(annual_salary)))
    return (
        f"CONFIRM_RFA_OFFER_SHEET::{_pid(player_id)}::"
        f"{_team(offering_team)}::{salary}::{int(years)}"
    )


def _normalized_offer(
    offer: FreeAgencyOffer,
) -> FreeAgencyOffer:
    return FreeAgencyOffer(
        player_id=_pid(offer.player_id),
        team_abbreviation=_team(offer.team_abbreviation),
        annual_salary=float(offer.annual_salary),
        years=int(offer.years),
        guaranteed=bool(offer.guaranteed),
        option_type=_clean(offer.option_type),
        offer_id=_clean(offer.offer_id),
    )


def _accepted_round(
    state: Any,
    preview: FreeAgencyTransactionPreview,
    *,
    controlled_team: str,
) -> int:
    for round_number in range(
        1,
        int(MAX_FREE_AGENCY_NEGOTIATION_ROUNDS) + 1,
    ):
        result = build_free_agency_negotiation_round(
            state,
            preview,
            controlled_teams=(controlled_team,),
            round_number=round_number,
        )
        if bool(getattr(result, "user_can_commit", False)):
            return round_number
    raise RFAOfferSheetError(
        "The player did not accept the external offer within the supported negotiation rounds."
    )


def build_external_offer_sheet_preview(
    checkpoint: Any,
    offer: FreeAgencyOffer,
) -> RFAOfferSheetPreview:
    state = getattr(checkpoint, "simulation_state", None)
    trade_state = getattr(checkpoint, "trade_state", None)
    if state is None or trade_state is None:
        raise RFAOfferSheetError(
            "The durable checkpoint requires simulation and trade state."
        )
    if _phase(state) != "offseason":
        raise RFAOfferSheetError(
            "Offer sheets are available only during the actual offseason."
        )

    calendar = free_agency_calendar_snapshot(state)
    if not calendar.initialized:
        raise RFAOfferSheetError(
            "The Free Agency calendar must be initialized before an offer sheet can start its match window."
        )

    resolved = _normalized_offer(offer)
    if resolved.years < MIN_OFFER_SHEET_YEARS:
        raise RFAOfferSheetError(
            "An NBA restricted-free-agent offer sheet must be for at least two seasons."
        )

    free_agents = {
        _pid(value)
        for value in getattr(state, "free_agent_player_ids", ()) or ()
    }
    if resolved.player_id not in free_agents:
        raise RFAOfferSheetError(
            "The player is no longer in the live free-agent market."
        )

    row = _rfa_row(state, resolved.player_id)
    prior_team = _team(row.get("prior_team"))
    if not prior_team:
        raise RFAOfferSheetError(
            "The RFA prior team is unavailable."
        )
    if _clean(row.get("rights_decision")) != "retain_rights":
        raise RFAOfferSheetError(
            "An offer sheet requires the original team to retain the player's rights."
        )
    if _clean(row.get("qo_decision")) != "issue_qo":
        raise RFAOfferSheetError(
            "An offer sheet requires an active qualifying offer."
        )
    if resolved.team_abbreviation == prior_team:
        raise RFAOfferSheetError(
            "A contract with the player's prior team is not an external offer sheet."
        )

    controlled = tuple(
        sorted(
            {
                _team(value)
                for value in controlled_teams_from_durable_checkpoint(checkpoint)
                if _team(value)
            }
        )
    )
    if resolved.team_abbreviation not in controlled:
        raise RFAOfferSheetError(
            "The offering team is not user-controlled in the durable checkpoint."
        )

    if pending_offer_sheet_for_player(state, resolved.player_id) is not None:
        raise RFAOfferSheetError(
            "This player already has a pending offer sheet."
        )
    if pending_offer_sheet_for_team(state, resolved.team_abbreviation) is not None:
        raise RFAOfferSheetError(
            "This controlled team already has a pending RFA offer-sheet obligation. "
            "V1 conservatively locks one pending sheet per team to preserve cap-room safety."
        )

    preview = build_contract_legal_free_agency_preview(
        state,
        resolved,
    )
    if (
        _clean(getattr(preview, "status", "")).lower() != "pass"
        or not bool(getattr(preview, "can_commit", False))
    ):
        raise RFAOfferSheetError(
            "The external offer is not a fully PASS contract/legal/cap preview."
        )

    accepted_round = _accepted_round(
        state,
        preview,
        controlled_team=resolved.team_abbreviation,
    )

    qo_amount = _amount(row.get("qo_amount_2026_27"))
    rights_charge = float(
        _amount(row.get("effective_charge_2026_27")) or 0.0
    )
    created_day = int(calendar.offseason_day)
    deadline = created_day + MATCH_WINDOW_DAYS

    return RFAOfferSheetPreview(
        version=RFA_OFFER_SHEET_VERSION,
        player_id=resolved.player_id,
        player_name=_clean(row.get("player_name"))
            or _clean(getattr(preview, "player_name", "")),
        prior_team=prior_team,
        offering_team=resolved.team_abbreviation,
        annual_salary=float(resolved.annual_salary),
        years=int(resolved.years),
        guaranteed=bool(resolved.guaranteed),
        option_type=_clean(resolved.option_type),
        offer_id=_clean(preview.offer.offer_id),
        qo_amount=qo_amount,
        rights_charge=rights_charge,
        created_day=created_day,
        match_deadline_day=deadline,
        accepted_round=accepted_round,
        source_simulation_fingerprint=free_agency_state_fingerprint(state),
        source_trade_fingerprint=trade_state_fingerprint(trade_state),
        confirmation_token=_confirmation_token(
            player_id=resolved.player_id,
            offering_team=resolved.team_abbreviation,
            annual_salary=resolved.annual_salary,
            years=resolved.years,
        ),
    )


def _checkpoint_backup_path(
    checkpoint_module: Any,
    checkpoint_path: Path,
) -> Path | None:
    helper = getattr(
        checkpoint_module,
        "checkpoint_backup_path",
        None,
    )
    if not callable(helper):
        return None
    try:
        return Path(helper(checkpoint_path))
    except TypeError:
        return Path(helper())


def _preferences(checkpoint: Any) -> dict[str, Any]:
    return copy.deepcopy(
        dict(getattr(checkpoint, "preferences", {}) or {})
    )


def _atomic_save(
    *,
    checkpoint_module: Any,
    checkpoint: Any,
    simulation_candidate: Any,
    trade_candidate: Any,
    reason: str,
    recovery_directory: str | Path | None,
    expected_fingerprint: str,
) -> tuple[str, str, str, str | None]:
    checkpoint_path = Path(
        checkpoint_module.DEFAULT_CHECKPOINT_PATH
    )
    backup_path = _checkpoint_backup_path(
        checkpoint_module,
        checkpoint_path,
    )
    checkpoint_hash_before = _sha256(checkpoint_path)
    backup_hash_before = (
        _sha256(backup_path)
        if backup_path is not None and backup_path.exists()
        else None
    )

    root = (
        Path(recovery_directory)
        if recovery_directory is not None
        else checkpoint_path.parent / "rfa_offer_sheet_recovery"
    )
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    safe_reason = "".join(
        ch if ch.isalnum() or ch in "-_" else "_"
        for ch in reason
    )[:80]
    recovery_primary = (
        root / f"pre_{safe_reason}_{stamp}_{checkpoint_path.name}"
    )
    shutil.copy2(checkpoint_path, recovery_primary)

    recovery_backup: Path | None = None
    if backup_path is not None and backup_path.exists():
        recovery_backup = (
            root / f"pre_{safe_reason}_{stamp}_{backup_path.name}"
        )
        shutil.copy2(backup_path, recovery_backup)

    source_fingerprint = _offer_sheet_fingerprint(
        checkpoint.simulation_state,
        checkpoint.trade_state,
    )

    try:
        reloaded = checkpoint_module.save_franchise_checkpoint(
            simulation_candidate,
            trade_candidate,
            preferences=_preferences(checkpoint),
            reason=reason,
            copy_payload=False,
            _return_verified=True,
            _existing_checkpoint=checkpoint,
            _expected_existing_sha256=checkpoint_hash_before,
        )
        observed = _offer_sheet_fingerprint(
            reloaded.simulation_state,
            reloaded.trade_state,
        )
        if observed != expected_fingerprint:
            raise RFAOfferSheetError(
                "Reloaded RFA offer-sheet state does not exactly match the approved candidate."
            )
    except Exception as exc:
        shutil.copy2(
            recovery_primary,
            checkpoint_path,
        )
        if (
            backup_path is not None
            and recovery_backup is not None
            and recovery_backup.exists()
        ):
            shutil.copy2(
                recovery_backup,
                backup_path,
            )

        restored = checkpoint_module.load_franchise_checkpoint()
        if restored is None:
            raise RFAOfferSheetError(
                "Offer-sheet write failed and the restored checkpoint could not be loaded."
            ) from exc
        if _offer_sheet_fingerprint(
            restored.simulation_state,
            restored.trade_state,
        ) != source_fingerprint:
            raise RFAOfferSheetError(
                "Offer-sheet write failed and exact automatic recovery could not be verified."
            ) from exc
        if _sha256(checkpoint_path) != checkpoint_hash_before:
            raise RFAOfferSheetError(
                "Offer-sheet recovery did not restore the exact primary checkpoint bytes."
            ) from exc
        if (
            backup_hash_before is not None
            and backup_path is not None
            and _sha256(backup_path) != backup_hash_before
        ):
            raise RFAOfferSheetError(
                "Offer-sheet recovery did not restore the exact automatic-backup bytes."
            ) from exc
        raise RFAOfferSheetError(
            f"RFA offer-sheet write failed. Exact pre-write state was restored: {exc}"
        ) from exc

    return (
        checkpoint_hash_before,
        _sha256(checkpoint_path),
        str(recovery_primary),
        (
            str(recovery_backup)
            if recovery_backup is not None
            else None
        ),
    )


def commit_external_offer_sheet_live(
    preview: RFAOfferSheetPreview,
    *,
    confirmation_token: str,
    recovery_directory: str | Path | None = None,
) -> RFAOfferSheetWriteResult:
    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(
        checkpoint_module.DEFAULT_CHECKPOINT_PATH
    )
    if not checkpoint_path.exists():
        raise RFAOfferSheetError(
            "The durable franchise checkpoint does not exist."
        )
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    if checkpoint is None:
        raise RFAOfferSheetError(
            "The durable franchise checkpoint could not be loaded."
        )

    state = checkpoint.simulation_state
    trade = checkpoint.trade_state
    if _phase(state) != "offseason":
        raise RFAOfferSheetError(
            "Offer sheets are available only during the offseason."
        )
    if _clean(confirmation_token) != preview.confirmation_token:
        raise RFAOfferSheetError(
            "The explicit offer-sheet confirmation token does not match the approved terms."
        )
    if free_agency_state_fingerprint(state) != preview.source_simulation_fingerprint:
        raise RFAOfferSheetError(
            "The approved offer-sheet preview is stale relative to the durable simulation state."
        )
    if trade_state_fingerprint(trade) != preview.source_trade_fingerprint:
        raise RFAOfferSheetError(
            "The approved offer-sheet preview is stale relative to the durable trade state."
        )

    rebuilt = build_external_offer_sheet_preview(
        checkpoint,
        FreeAgencyOffer(
            player_id=preview.player_id,
            team_abbreviation=preview.offering_team,
            annual_salary=preview.annual_salary,
            years=preview.years,
            guaranteed=preview.guaranteed,
            option_type=preview.option_type,
            offer_id=preview.offer_id,
        ),
    )
    if rebuilt.confirmation_token != preview.confirmation_token:
        raise RFAOfferSheetError(
            "The rebuilt offer sheet does not match the approved terms."
        )

    sim_candidate = copy.deepcopy(state)
    trade_candidate = copy.deepcopy(trade)

    active = _active_map(sim_candidate)
    history = _history(sim_candidate)
    offer_sheet_id = f"RFAOS-{len(history) + 1:04d}"

    record = {
        "offer_sheet_id": offer_sheet_id,
        "version": RFA_OFFER_SHEET_VERSION,
        "status": STATUS_PENDING,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "player_id": preview.player_id,
        "player_name": preview.player_name,
        "prior_team": preview.prior_team,
        "offering_team": preview.offering_team,
        "annual_salary": float(preview.annual_salary),
        "years": int(preview.years),
        "guaranteed": bool(preview.guaranteed),
        "option_type": preview.option_type,
        "offer_id": preview.offer_id,
        "qo_amount": preview.qo_amount,
        "rights_charge": float(preview.rights_charge),
        "created_day": int(preview.created_day),
        "match_deadline_day": int(preview.match_deadline_day),
        "accepted_round": int(preview.accepted_round),
        "reserved_initial_salary": float(preview.annual_salary),
        "cap_room_lock_mode": "conservative_one_pending_sheet_per_team",
    }
    active[offer_sheet_id] = copy.deepcopy(record)
    history.append(
        {
            **copy.deepcopy(record),
            "event": "offer_sheet_created",
        }
    )

    _set_offer_sheet_state(
        sim_candidate,
        active=active,
        history=history,
    )
    _set_offer_sheet_state(
        trade_candidate,
        active=active,
        history=history,
    )

    revision_before = int(
        getattr(trade_candidate, "state_revision", 0) or 0
    )
    setattr(
        trade_candidate,
        "state_revision",
        revision_before + 1,
    )
    _align_simulation_source_to_trade_state(
        sim_candidate,
        trade_candidate,
    )

    expected = _offer_sheet_fingerprint(
        sim_candidate,
        trade_candidate,
    )
    before_hash, after_hash, recovery_primary, recovery_backup = (
        _atomic_save(
            checkpoint_module=checkpoint_module,
            checkpoint=checkpoint,
            simulation_candidate=sim_candidate,
            trade_candidate=trade_candidate,
            reason=f"rfa-offer-sheet-create-{offer_sheet_id}",
            recovery_directory=recovery_directory,
            expected_fingerprint=expected,
        )
    )

    return RFAOfferSheetWriteResult(
        version=RFA_OFFER_SHEET_VERSION,
        offer_sheet_id=offer_sheet_id,
        player_id=preview.player_id,
        player_name=preview.player_name,
        prior_team=preview.prior_team,
        offering_team=preview.offering_team,
        annual_salary=float(preview.annual_salary),
        years=int(preview.years),
        created_day=int(preview.created_day),
        match_deadline_day=int(preview.match_deadline_day),
        status=STATUS_PENDING,
        trade_revision_before=revision_before,
        trade_revision_after=revision_before + 1,
        checkpoint_hash_before=before_hash,
        checkpoint_hash_after=after_hash,
        recovery_primary_path=recovery_primary,
        recovery_backup_path=recovery_backup,
    )


def _matched_financial_gate(
    state: Any,
    offer: FreeAgencyOffer,
) -> FreeAgencyFinancialGateResult:
    return FreeAgencyFinancialGateResult(
        status="pass",
        reason=(
            "Right-of-first-refusal match uses the exact principal terms of "
            "a previously legal and player-accepted external offer sheet."
        ),
        payload={
            "route": "rfa_right_of_first_refusal_match",
            "offer_sheet_terms_already_validated": True,
        },
    )


def _set_resolved_rfa_ledger(
    state: Any,
    *,
    player_id: str,
    decision: str,
    offer_sheet_id: str,
    destination_team: str,
) -> None:
    rows = _rfa_rows(state)
    target = _pid(player_id)
    found = False
    for row in rows:
        if _pid(row.get("player_id")) != target:
            continue
        found = True
        row["rights_decision"] = "consumed_by_contract"
        row["qo_decision"] = "terminated_by_contract"
        row["effective_charge_2026_27"] = 0.0
        row["offer_sheet_id"] = offer_sheet_id
        row["offer_sheet_resolution"] = decision
        row["offer_sheet_destination_team"] = _team(destination_team)
    if not found:
        raise RFAOfferSheetError(
            "The resolved player disappeared from the RFA ledger."
        )
    setattr(
        state,
        RFA_LEDGER_ATTR,
        copy.deepcopy(rows),
    )


def _resolved_offer(
    record: Mapping[str, Any],
    destination_team: str,
) -> FreeAgencyOffer:
    return FreeAgencyOffer(
        player_id=_pid(record.get("player_id")),
        team_abbreviation=_team(destination_team),
        annual_salary=float(record["annual_salary"]),
        years=int(record["years"]),
        guaranteed=bool(record.get("guaranteed", True)),
        option_type=_clean(record.get("option_type")),
        offer_id=_clean(record.get("offer_id")),
    )


def build_offer_sheet_resolution_candidate(
    checkpoint: Any,
    *,
    offer_sheet_id: str,
    decision: str,
) -> tuple[Any, Any, dict[str, Any]]:
    from simulation_league_state_v1 import (
        validate_simulation_league_state,
    )

    state = checkpoint.simulation_state
    trade = checkpoint.trade_state
    if _phase(state) != "offseason":
        raise RFAOfferSheetError(
            "Offer-sheet resolution is available only during the offseason."
        )

    active = _active_map(state)
    record = active.get(_clean(offer_sheet_id))
    if record is None:
        raise RFAOfferSheetError(
            "The requested offer sheet is not pending."
        )
    if _clean(record.get("status")) != STATUS_PENDING:
        raise RFAOfferSheetError(
            "The requested offer sheet is not in the pending match window."
        )

    decision = _clean(decision).lower()
    if decision not in {DECISION_MATCH, DECISION_DECLINE}:
        raise RFAOfferSheetError(
            f"Unsupported offer-sheet decision {decision!r}."
        )

    calendar = free_agency_calendar_snapshot(state)
    if not calendar.initialized:
        raise RFAOfferSheetError(
            "The Free Agency calendar is not initialized."
        )
    deadline = int(record["match_deadline_day"])
    if decision == DECISION_MATCH and int(calendar.offseason_day) > deadline:
        raise RFAOfferSheetError(
            "The original team's two-day right-of-first-refusal window has expired."
        )

    player_id = _pid(record["player_id"])
    prior_team = _team(record["prior_team"])
    offering_team = _team(record["offering_team"])
    destination = (
        prior_team
        if decision == DECISION_MATCH
        else offering_team
    )

    released_sim, released_trade, release_meta = (
        _projected_action_candidates(
            state,
            trade,
            player_id=player_id,
            action="renounce_rights",
        )
    )

    offer = _resolved_offer(
        record,
        destination,
    )

    if decision == DECISION_MATCH:
        preview = build_free_agency_preview(
            released_sim,
            offer,
            financial_gate=_matched_financial_gate,
            state_validator=validate_simulation_league_state,
        )
        financial_gate = _matched_financial_gate
    else:
        preview = build_contract_legal_free_agency_preview(
            released_sim,
            offer,
        )
        financial_gate = evaluate_contract_legal_financial_gate

    if (
        _clean(getattr(preview, "status", "")).lower() != "pass"
        or not bool(getattr(preview, "can_commit", False))
    ):
        raise RFAOfferSheetError(
            "The offer sheet cannot be finalized from the current durable financial state."
        )

    sim_candidate, commit, revision, fatx_id = (
        build_free_agency_durable_candidate(
            released_sim,
            preview,
            financial_gate=financial_gate,
            state_validator=validate_simulation_league_state,
            max_roster_size=18,
        )
    )
    trade_candidate, trade_sync = (
        build_trade_state_free_agency_candidate(
            released_trade,
            preview.offer,
            transaction_id=fatx_id,
            validate=True,
        )
    )
    _align_simulation_source_to_trade_state(
        sim_candidate,
        trade_candidate,
    )
    validate_simulation_league_state(
        sim_candidate
    )

    _set_resolved_rfa_ledger(
        sim_candidate,
        player_id=player_id,
        decision=decision,
        offer_sheet_id=_clean(offer_sheet_id),
        destination_team=destination,
    )
    _set_resolved_rfa_ledger(
        trade_candidate,
        player_id=player_id,
        decision=decision,
        offer_sheet_id=_clean(offer_sheet_id),
        destination_team=destination,
    )

    active_after = _active_map(sim_candidate)
    active_after.pop(_clean(offer_sheet_id), None)
    history_after = _history(sim_candidate)
    history_after.append(
        {
            **copy.deepcopy(record),
            "event": "offer_sheet_resolved",
            "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
            "decision": decision,
            "destination_team": destination,
            "fatx_transaction_id": fatx_id,
            "status": (
                STATUS_MATCHED
                if decision == DECISION_MATCH
                else STATUS_DECLINED
            ),
        }
    )
    _set_offer_sheet_state(
        sim_candidate,
        active=active_after,
        history=history_after,
    )
    _set_offer_sheet_state(
        trade_candidate,
        active=active_after,
        history=history_after,
    )

    fa_history = getattr(
        sim_candidate,
        "free_agency_transaction_history",
        None,
    )
    if isinstance(fa_history, list) and fa_history:
        fa_history[-1]["candidate_fingerprint"] = (
            free_agency_state_fingerprint(sim_candidate)
        )

    metadata = {
        "record": copy.deepcopy(record),
        "decision": decision,
        "destination_team": destination,
        "rights_release_meta": release_meta,
        "fatx_transaction_id": fatx_id,
        "free_agency_revision": revision,
        "trade_revision_before": trade_sync.state_revision_before,
        "trade_revision_after": trade_sync.state_revision_after,
        "expected_simulation_fingerprint":
            free_agency_durable_state_fingerprint(sim_candidate),
        "expected_trade_fingerprint":
            trade_state_fingerprint(trade_candidate),
    }
    return sim_candidate, trade_candidate, metadata


def resolve_offer_sheet_live(
    *,
    offer_sheet_id: str,
    decision: str,
    authority: str,
    recovery_directory: str | Path | None = None,
) -> RFAOfferSheetResolutionResult:
    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(
        checkpoint_module.DEFAULT_CHECKPOINT_PATH
    )
    if not checkpoint_path.exists():
        raise RFAOfferSheetError(
            "The durable franchise checkpoint does not exist."
        )
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    if checkpoint is None:
        raise RFAOfferSheetError(
            "The durable franchise checkpoint could not be loaded."
        )

    active = _active_map(checkpoint.simulation_state)
    record = active.get(_clean(offer_sheet_id))
    if record is None:
        raise RFAOfferSheetError(
            "The requested offer sheet is not pending."
        )

    prior_team = _team(record["prior_team"])
    controlled = {
        _team(value)
        for value in controlled_teams_from_durable_checkpoint(checkpoint)
        if _team(value)
    }
    authority = _clean(authority).lower()
    if authority == "user":
        if prior_team not in controlled:
            raise RFAOfferSheetError(
                "Only a user-controlled original team may use user match/decline authority."
            )
    elif authority == "cpu":
        if prior_team in controlled:
            raise RFAOfferSheetError(
                "CPU authority cannot decide a user-controlled original team's offer sheet."
            )
    else:
        raise RFAOfferSheetError(
            "Offer-sheet resolution authority must be 'user' or 'cpu'."
        )

    sim_candidate, trade_candidate, meta = (
        build_offer_sheet_resolution_candidate(
            checkpoint,
            offer_sheet_id=offer_sheet_id,
            decision=decision,
        )
    )

    expected = _offer_sheet_fingerprint(
        sim_candidate,
        trade_candidate,
    )
    before_hash, after_hash, recovery_primary, recovery_backup = (
        _atomic_save(
            checkpoint_module=checkpoint_module,
            checkpoint=checkpoint,
            simulation_candidate=sim_candidate,
            trade_candidate=trade_candidate,
            reason=(
                f"rfa-offer-sheet-{_clean(decision).lower()}-"
                f"{_clean(offer_sheet_id)}"
            ),
            recovery_directory=recovery_directory,
            expected_fingerprint=expected,
        )
    )

    record = meta["record"]
    destination = meta["destination_team"]
    return RFAOfferSheetResolutionResult(
        version=RFA_OFFER_SHEET_VERSION,
        offer_sheet_id=_clean(offer_sheet_id),
        decision=_clean(decision).lower(),
        destination_team=destination,
        player_id=_pid(record["player_id"]),
        player_name=_clean(record.get("player_name")),
        annual_salary=float(record["annual_salary"]),
        years=int(record["years"]),
        rights_charge_released=float(
            _amount(record.get("rights_charge")) or 0.0
        ),
        fatx_transaction_id=_clean(meta["fatx_transaction_id"]),
        trade_revision_before=int(
            meta["trade_revision_before"]
        ),
        trade_revision_after=int(
            meta["trade_revision_after"]
        ),
        checkpoint_hash_before=before_hash,
        checkpoint_hash_after=after_hash,
        recovery_primary_path=recovery_primary,
        recovery_backup_path=recovery_backup,
    )


def offer_sheet_contract_report() -> dict[str, Any]:
    return {
        "version": RFA_OFFER_SHEET_VERSION,
        "scope": RFA_OFFER_SHEET_SCOPE,
        "minimum_offer_sheet_years": MIN_OFFER_SHEET_YEARS,
        "match_window_days": MATCH_WINDOW_DAYS,
        "player_acceptance_required": True,
        "active_qualifying_offer_required": True,
        "retained_rights_required": True,
        "external_team_required": True,
        "offering_team_cap_legality_revalidated_at_resolution": True,
        "right_of_first_refusal_match_uses_exact_principal_terms": True,
        "prior_team_rights_charge_released_before_contract_accounting": True,
        "atomic_primary_and_backup_recovery": True,
        "conservative_pending_team_lock": True,
    }
