
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

from franchise_free_agency_live_signing_v1 import (
    _align_simulation_source_to_trade_state,
    controlled_teams_from_durable_checkpoint,
    trade_state_fingerprint,
)
from franchise_free_agency_transaction_v1 import (
    free_agency_state_fingerprint,
)

NON_RFA_RIGHTS_LIVE_VERSION = (
    "franchise-free-agency-non-rfa-rights-live-renouncement-v1-2026-08-17"
)
NON_RFA_LEDGER_ATTR = "offseason_non_rfa_rights_decisions_v1"
MARKET_AMOUNT_ATTR = "offseason_free_agent_amount_candidates_v1"
HISTORY_ATTR = "offseason_non_rfa_rights_lifecycle_history_v1"

ACTION_RENOUNCE_RIGHTS = "renounce_rights"
RETAIN_DECISIONS = {
    "retain_rights_by_default",
    "retain_rights",
}


class NonRFARightsLifecycleError(RuntimeError):
    pass


@dataclass(frozen=True)
class NonRFARightsRenouncementPreview:
    version: str
    player_id: str
    player_name: str
    prior_team: str
    rights_classification: str
    current_rights_decision: str
    current_charge: float
    expected_team_salary_delta: float
    expected_apron_salary_delta: float
    source_simulation_fingerprint: str
    source_trade_fingerprint: str
    source_lifecycle_fingerprint: str
    confirmation_token: str


@dataclass(frozen=True)
class NonRFARightsRenouncementResult:
    version: str
    transaction_id: str
    player_id: str
    player_name: str
    prior_team: str
    released_charge: float
    team_salary_before: float
    team_salary_after: float
    apron_salary_before: float
    apron_salary_after: float
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
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _phase(state: Any) -> str:
    phase = getattr(state, "phase", None)
    return _clean(getattr(phase, "value", phase)).lower()


def _sha256(path: Path) -> str:
    d = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            d.update(block)
    return d.hexdigest()


def _dict_rows(value: Any) -> list[dict[str, Any]]:
    rows = []
    for item in list(value or ()):
        if isinstance(item, Mapping):
            rows.append(copy.deepcopy(dict(item)))
        elif hasattr(item, "__dict__"):
            rows.append(copy.deepcopy(vars(item)))
    return rows


def _ledger_rows(state: Any) -> list[dict[str, Any]]:
    rows = _dict_rows(
        getattr(state, NON_RFA_LEDGER_ATTR, ())
    )
    if len(rows) != 162:
        raise NonRFARightsLifecycleError(
            f"Expected the verified 162-player non-RFA rights ledger, found {len(rows)}."
        )
    return rows


def _market_rows(state: Any) -> list[dict[str, Any]]:
    rows = _dict_rows(
        getattr(state, MARKET_AMOUNT_ATTR, ())
    )
    if len(rows) != 226:
        raise NonRFARightsLifecycleError(
            f"Expected the verified 226-player Free Agent Amount market, found {len(rows)}."
        )
    return rows


def _history(state: Any) -> list[dict[str, Any]]:
    raw = getattr(state, HISTORY_ATTR, [])
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise NonRFARightsLifecycleError(
            f"{HISTORY_ATTR} must be a list when present."
        )
    return copy.deepcopy(raw)


def _row_for_player(
    state: Any,
    player_id: str,
) -> dict[str, Any]:
    target = _pid(player_id)
    matches = [
        row
        for row in _ledger_rows(state)
        if _pid(row.get("player_id")) == target
    ]
    if len(matches) != 1:
        raise NonRFARightsLifecycleError(
            f"Expected exactly one non-RFA rights row for {target!r}, found {len(matches)}."
        )
    return copy.deepcopy(matches[0])


def non_rfa_rights_metadata(
    state: Any,
) -> dict[str, dict[str, Any]]:
    return {
        _pid(row.get("player_id")): copy.deepcopy(row)
        for row in _ledger_rows(state)
        if _pid(row.get("player_id"))
    }


def _lifecycle_fingerprint(
    simulation_state: Any,
    trade_state: Any,
) -> str:
    payload = {
        "simulation_base":
            free_agency_state_fingerprint(
                simulation_state
            ),
        "trade_base":
            trade_state_fingerprint(
                trade_state
            ),
        "simulation_ledger":
            _ledger_rows(
                simulation_state
            ),
        "trade_ledger":
            _ledger_rows(
                trade_state
            ),
        "simulation_market":
            _market_rows(
                simulation_state
            ),
        "trade_market":
            _market_rows(
                trade_state
            ),
        "simulation_history":
            _history(
                simulation_state
            ),
        "trade_history":
            _history(
                trade_state
            ),
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
    team: str,
) -> str:
    return (
        f"CONFIRM_NONRFA_RIGHTS_RENOUNCE::"
        f"{_pid(player_id)}::{_team(team)}"
    )


def _controlled_teams(
    checkpoint: Any,
) -> set[str]:
    return {
        _team(value)
        for value in controlled_teams_from_durable_checkpoint(
            checkpoint
        )
        if _team(value)
    }


def preview_controlled_non_rfa_renouncement(
    checkpoint: Any,
    *,
    player_id: str,
) -> NonRFARightsRenouncementPreview:
    state = getattr(
        checkpoint,
        "simulation_state",
        None,
    )
    trade = getattr(
        checkpoint,
        "trade_state",
        None,
    )
    if state is None or trade is None:
        raise NonRFARightsLifecycleError(
            "The durable checkpoint requires both simulation and trade state."
        )
    if _phase(state) != "offseason":
        raise NonRFARightsLifecycleError(
            "Non-RFA rights renouncement is available only during the actual offseason."
        )

    pid = _pid(player_id)
    free_agents = {
        _pid(value)
        for value in getattr(
            state,
            "free_agent_player_ids",
            (),
        )
        or ()
    }
    if pid not in free_agents:
        raise NonRFARightsLifecycleError(
            "The player is no longer in the live free-agent market."
        )

    row = _row_for_player(
        state,
        pid,
    )
    decision = _clean(
        row.get("rights_decision")
    ).lower()
    if decision == ACTION_RENOUNCE_RIGHTS:
        raise NonRFARightsLifecycleError(
            "These rights have already been renounced. Renouncement is irreversible in the current offseason."
        )
    if decision not in RETAIN_DECISIONS:
        raise NonRFARightsLifecycleError(
            f"The player does not currently have retainable non-RFA rights: {decision!r}."
        )

    prior_team = _team(
        row.get("prior_team")
    )
    if not prior_team:
        raise NonRFARightsLifecycleError(
            "The non-RFA prior team is unavailable."
        )
    if prior_team not in _controlled_teams(
        checkpoint
    ):
        raise NonRFARightsLifecycleError(
            "Only the user-controlled prior team may renounce these rights."
        )

    charge = _amount(
        row.get(
            "effective_charge_2026_27"
        )
    )
    if charge is None or charge <= 0:
        raise NonRFARightsLifecycleError(
            "The retained non-RFA rights row does not carry a positive verified charge."
        )

    free_agent_amount = _amount(
        row.get(
            "free_agent_amount_2026_27"
        )
    )
    if (
        free_agent_amount is None
        or abs(
            free_agent_amount
            - charge
        )
        > 0.01
    ):
        raise NonRFARightsLifecycleError(
            "The verified non-RFA Free Agent Amount and current rights charge do not reconcile."
        )

    financial = getattr(
        trade,
        "team_financials",
        {},
    ).get(
        prior_team
    )
    if financial is None:
        raise NonRFARightsLifecycleError(
            f"TradeState financials are unavailable for {prior_team}."
        )

    player_name = _clean(
        row.get("player_name")
    ) or pid
    classification = _clean(
        row.get(
            "rights_classification"
        )
    )

    return NonRFARightsRenouncementPreview(
        version=
            NON_RFA_RIGHTS_LIVE_VERSION,
        player_id=pid,
        player_name=player_name,
        prior_team=prior_team,
        rights_classification=
            classification,
        current_rights_decision=
            decision,
        current_charge=
            float(charge),
        expected_team_salary_delta=
            -float(charge),
        expected_apron_salary_delta=
            -float(charge),
        source_simulation_fingerprint=
            free_agency_state_fingerprint(
                state
            ),
        source_trade_fingerprint=
            trade_state_fingerprint(
                trade
            ),
        source_lifecycle_fingerprint=
            _lifecycle_fingerprint(
                state,
                trade,
            ),
        confirmation_token=
            _confirmation_token(
                player_id=pid,
                team=prior_team,
            ),
    )


def _next_transaction_id(
    state: Any,
) -> str:
    history = _history(
        state
    )
    existing = {
        _clean(
            row.get(
                "transaction_id"
            )
        )
        for row in history
        if isinstance(
            row,
            Mapping,
        )
    }
    number = 1
    while (
        f"NRFAR-{number:04d}"
        in existing
    ):
        number += 1
    return f"NRFAR-{number:04d}"


def _replace_player_row(
    rows: list[dict[str, Any]],
    *,
    player_id: str,
    updates: Mapping[str, Any],
) -> list[dict[str, Any]]:
    target = _pid(
        player_id
    )
    output = []
    found = 0
    for source in rows:
        row = copy.deepcopy(
            source
        )
        if _pid(
            row.get(
                "player_id"
            )
        ) == target:
            row.update(
                copy.deepcopy(
                    dict(
                        updates
                    )
                )
            )
            found += 1
        output.append(
            row
        )
    if found != 1:
        raise NonRFARightsLifecycleError(
            f"Expected exactly one target row for {target!r}, replaced {found}."
        )
    return output


def build_non_rfa_renouncement_candidate(
    checkpoint: Any,
    preview: NonRFARightsRenouncementPreview,
) -> tuple[Any, Any, dict[str, Any]]:
    state = checkpoint.simulation_state
    trade = checkpoint.trade_state

    if (
        free_agency_state_fingerprint(
            state
        )
        != preview.source_simulation_fingerprint
        or trade_state_fingerprint(
            trade
        )
        != preview.source_trade_fingerprint
        or _lifecycle_fingerprint(
            state,
            trade,
        )
        != preview.source_lifecycle_fingerprint
    ):
        raise NonRFARightsLifecycleError(
            "The approved non-RFA rights preview is stale relative to the durable checkpoint."
        )

    current = preview_controlled_non_rfa_renouncement(
        checkpoint,
        player_id=
            preview.player_id,
    )
    if (
        current.confirmation_token
        != preview.confirmation_token
        or abs(
            current.current_charge
            - preview.current_charge
        )
        > 0.01
    ):
        raise NonRFARightsLifecycleError(
            "The rebuilt non-RFA rights preview no longer matches the approved action."
        )

    sim_candidate = copy.deepcopy(
        state
    )
    trade_candidate = copy.deepcopy(
        trade
    )
    transaction_id = (
        _next_transaction_id(
            state
        )
    )

    updates = {
        "rights_decision":
            ACTION_RENOUNCE_RIGHTS,
        "qo_decision":
            "not_applicable_non_rfa",
        "effective_charge_2026_27":
            0.0,
        "cap_hold_applied":
            False,
        "cap_hold_applied_to_clone":
            False,
        "rights_decision_applied":
            True,
        "decision_source":
            "explicit_live_non_rfa_rights_renouncement",
        "live_renouncement_applied":
            True,
        "live_renouncement_transaction_id":
            transaction_id,
        "live_renouncement_irreversible":
            True,
    }

    sim_ledger = (
        _replace_player_row(
            _ledger_rows(
                sim_candidate
            ),
            player_id=
                preview.player_id,
            updates=updates,
        )
    )
    trade_ledger = (
        _replace_player_row(
            _ledger_rows(
                trade_candidate
            ),
            player_id=
                preview.player_id,
            updates=updates,
        )
    )
    sim_market = (
        _replace_player_row(
            _market_rows(
                sim_candidate
            ),
            player_id=
                preview.player_id,
            updates=updates,
        )
    )
    trade_market = (
        _replace_player_row(
            _market_rows(
                trade_candidate
            ),
            player_id=
                preview.player_id,
            updates=updates,
        )
    )

    setattr(
        sim_candidate,
        NON_RFA_LEDGER_ATTR,
        sim_ledger,
    )
    setattr(
        trade_candidate,
        NON_RFA_LEDGER_ATTR,
        trade_ledger,
    )
    setattr(
        sim_candidate,
        MARKET_AMOUNT_ATTR,
        sim_market,
    )
    setattr(
        trade_candidate,
        MARKET_AMOUNT_ATTR,
        trade_market,
    )

    financial = (
        trade_candidate.team_financials[
            preview.prior_team
        ]
    )
    team_salary_before = float(
        financial.team_salary
    )
    apron_salary_before = float(
        financial.apron_salary
    )
    financial.team_salary = round(
        team_salary_before
        - preview.current_charge,
        2,
    )
    financial.apron_salary = round(
        apron_salary_before
        - preview.current_charge,
        2,
    )
    if (
        financial.team_salary
        < -0.01
        or financial.apron_salary
        < -0.01
    ):
        raise NonRFARightsLifecycleError(
            "The non-RFA rights release produced an invalid negative team financial value."
        )

    snapshots = list(
        getattr(
            trade_candidate,
            "undo_stack",
            (),
        )
        or ()
    )
    initial_snapshot = getattr(
        trade_candidate,
        "initial_snapshot",
        None,
    )
    if initial_snapshot is not None:
        snapshots.append(
            initial_snapshot
        )
    for snapshot in snapshots:
        if hasattr(
            snapshot,
            "team_financials",
        ):
            snapshot.team_financials = (
                copy.deepcopy(
                    trade_candidate.team_financials
                )
            )

    event = {
        "transaction_id":
            transaction_id,
        "version":
            NON_RFA_RIGHTS_LIVE_VERSION,
        "event":
            "non_rfa_rights_renounced",
        "created_at_utc":
            datetime.now(
                timezone.utc
            ).isoformat(),
        "player_id":
            preview.player_id,
        "player_name":
            preview.player_name,
        "prior_team":
            preview.prior_team,
        "rights_classification":
            preview.rights_classification,
        "previous_rights_decision":
            preview.current_rights_decision,
        "rights_decision":
            ACTION_RENOUNCE_RIGHTS,
        "released_charge":
            float(
                preview.current_charge
            ),
        "team_salary_delta":
            -float(
                preview.current_charge
            ),
        "apron_salary_delta":
            -float(
                preview.current_charge
            ),
        "irreversible":
            True,
    }
    sim_history = _history(
        sim_candidate
    )
    trade_history = _history(
        trade_candidate
    )
    sim_history.append(
        copy.deepcopy(
            event
        )
    )
    trade_history.append(
        copy.deepcopy(
            event
        )
    )
    setattr(
        sim_candidate,
        HISTORY_ATTR,
        sim_history,
    )
    setattr(
        trade_candidate,
        HISTORY_ATTR,
        trade_history,
    )

    revision_before = int(
        getattr(
            trade_candidate,
            "state_revision",
            0,
        )
        or 0
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

    meta = {
        "transaction_id":
            transaction_id,
        "team_salary_before":
            team_salary_before,
        "team_salary_after":
            float(
                financial.team_salary
            ),
        "apron_salary_before":
            apron_salary_before,
        "apron_salary_after":
            float(
                financial.apron_salary
            ),
        "trade_revision_before":
            revision_before,
        "trade_revision_after":
            revision_before + 1,
        "expected_fingerprint":
            _lifecycle_fingerprint(
                sim_candidate,
                trade_candidate,
            ),
    }
    return (
        sim_candidate,
        trade_candidate,
        meta,
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
    if not callable(
        helper
    ):
        return None
    try:
        return Path(
            helper(
                checkpoint_path
            )
        )
    except TypeError:
        return Path(
            helper()
        )


def _atomic_save(
    *,
    checkpoint_module: Any,
    checkpoint: Any,
    simulation_candidate: Any,
    trade_candidate: Any,
    transaction_id: str,
    expected_fingerprint: str,
    recovery_directory: str | Path | None,
) -> tuple[str, str, str, str | None]:
    checkpoint_path = Path(
        checkpoint_module.DEFAULT_CHECKPOINT_PATH
    )
    if not checkpoint_path.exists():
        raise NonRFARightsLifecycleError(
            "The durable franchise checkpoint does not exist."
        )

    backup_path = _checkpoint_backup_path(
        checkpoint_module,
        checkpoint_path,
    )
    checkpoint_hash_before = _sha256(
        checkpoint_path
    )
    backup_hash_before = (
        _sha256(
            backup_path
        )
        if backup_path is not None
        and backup_path.exists()
        else None
    )

    source_fingerprint = (
        _lifecycle_fingerprint(
            checkpoint.simulation_state,
            checkpoint.trade_state,
        )
    )

    root = (
        Path(
            recovery_directory
        )
        if recovery_directory
        is not None
        else checkpoint_path.parent
        / "non_rfa_rights_recovery"
    )
    root.mkdir(
        parents=True,
        exist_ok=True,
    )
    stamp = datetime.now(
        timezone.utc
    ).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )
    recovery_primary = (
        root
        / f"pre_{transaction_id}_{stamp}_{checkpoint_path.name}"
    )
    shutil.copy2(
        checkpoint_path,
        recovery_primary,
    )

    recovery_backup: Path | None = None
    if (
        backup_path is not None
        and backup_path.exists()
    ):
        recovery_backup = (
            root
            / f"pre_{transaction_id}_{stamp}_{backup_path.name}"
        )
        shutil.copy2(
            backup_path,
            recovery_backup,
        )

    try:
        reloaded = checkpoint_module.save_franchise_checkpoint(
            simulation_candidate,
            trade_candidate,
            preferences=copy.deepcopy(
                dict(
                    getattr(
                        checkpoint,
                        "preferences",
                        {},
                    )
                    or {}
                )
            ),
            reason=
                f"non-rfa-rights-renouncement-{transaction_id}",
            copy_payload=False,
            _return_verified=True,
            _existing_checkpoint=checkpoint,
            _expected_existing_sha256=checkpoint_hash_before,
        )
        observed = (
            _lifecycle_fingerprint(
                reloaded.simulation_state,
                reloaded.trade_state,
            )
        )
        if (
            observed
            != expected_fingerprint
        ):
            raise NonRFARightsLifecycleError(
                "Reloaded non-RFA rights state does not exactly match the approved candidate."
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

        restored = (
            checkpoint_module.load_franchise_checkpoint()
        )
        if restored is None:
            raise NonRFARightsLifecycleError(
                "Non-RFA rights write failed and the restored checkpoint could not be loaded."
            ) from exc
        if (
            _lifecycle_fingerprint(
                restored.simulation_state,
                restored.trade_state,
            )
            != source_fingerprint
        ):
            raise NonRFARightsLifecycleError(
                "Non-RFA rights write failed and exact automatic recovery could not be verified."
            ) from exc
        if (
            _sha256(
                checkpoint_path
            )
            != checkpoint_hash_before
        ):
            raise NonRFARightsLifecycleError(
                "Non-RFA rights recovery did not restore exact primary checkpoint bytes."
            ) from exc
        if (
            backup_hash_before
            is not None
            and backup_path
            is not None
            and _sha256(
                backup_path
            )
            != backup_hash_before
        ):
            raise NonRFARightsLifecycleError(
                "Non-RFA rights recovery did not restore exact automatic-backup bytes."
            ) from exc

        raise NonRFARightsLifecycleError(
            "Non-RFA rights renouncement failed. "
            f"Exact pre-action state was restored: {exc}"
        ) from exc

    return (
        checkpoint_hash_before,
        _sha256(
            checkpoint_path
        ),
        str(
            recovery_primary
        ),
        (
            str(
                recovery_backup
            )
            if recovery_backup
            is not None
            else None
        ),
    )


def commit_controlled_non_rfa_renouncement_live(
    preview: NonRFARightsRenouncementPreview,
    *,
    confirmation_token: str,
    recovery_directory: str | Path | None = None,
) -> NonRFARightsRenouncementResult:
    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint = (
        checkpoint_module.load_franchise_checkpoint()
    )
    if checkpoint is None:
        raise NonRFARightsLifecycleError(
            "The durable franchise checkpoint is unavailable."
        )

    if (
        _clean(
            confirmation_token
        )
        != preview.confirmation_token
    ):
        raise NonRFARightsLifecycleError(
            "The explicit non-RFA rights confirmation token does not match the approved action."
        )

    rebuilt = preview_controlled_non_rfa_renouncement(
        checkpoint,
        player_id=
            preview.player_id,
    )
    if (
        rebuilt.confirmation_token
        != preview.confirmation_token
        or rebuilt.source_lifecycle_fingerprint
        != preview.source_lifecycle_fingerprint
    ):
        raise NonRFARightsLifecycleError(
            "The approved non-RFA rights preview is stale."
        )

    (
        sim_candidate,
        trade_candidate,
        meta,
    ) = build_non_rfa_renouncement_candidate(
        checkpoint,
        preview,
    )

    (
        checkpoint_before,
        checkpoint_after,
        recovery_primary,
        recovery_backup,
    ) = _atomic_save(
        checkpoint_module=
            checkpoint_module,
        checkpoint=checkpoint,
        simulation_candidate=
            sim_candidate,
        trade_candidate=
            trade_candidate,
        transaction_id=
            meta[
                "transaction_id"
            ],
        expected_fingerprint=
            meta[
                "expected_fingerprint"
            ],
        recovery_directory=
            recovery_directory,
    )

    return NonRFARightsRenouncementResult(
        version=
            NON_RFA_RIGHTS_LIVE_VERSION,
        transaction_id=
            meta[
                "transaction_id"
            ],
        player_id=
            preview.player_id,
        player_name=
            preview.player_name,
        prior_team=
            preview.prior_team,
        released_charge=
            float(
                preview.current_charge
            ),
        team_salary_before=
            float(
                meta[
                    "team_salary_before"
                ]
            ),
        team_salary_after=
            float(
                meta[
                    "team_salary_after"
                ]
            ),
        apron_salary_before=
            float(
                meta[
                    "apron_salary_before"
                ]
            ),
        apron_salary_after=
            float(
                meta[
                    "apron_salary_after"
                ]
            ),
        trade_revision_before=
            int(
                meta[
                    "trade_revision_before"
                ]
            ),
        trade_revision_after=
            int(
                meta[
                    "trade_revision_after"
                ]
            ),
        checkpoint_hash_before=
            checkpoint_before,
        checkpoint_hash_after=
            checkpoint_after,
        recovery_primary_path=
            recovery_primary,
        recovery_backup_path=
            recovery_backup,
    )


def non_rfa_rights_lifecycle_contract_report() -> dict[str, Any]:
    return {
        "version":
            NON_RFA_RIGHTS_LIVE_VERSION,
        "action":
            ACTION_RENOUNCE_RIGHTS,
        "actual_offseason_required":
            True,
        "current_free_agent_required":
            True,
        "controlled_prior_team_required":
            True,
        "retained_rights_required":
            True,
        "positive_verified_charge_required":
            True,
        "explicit_confirmation_required":
            True,
        "renouncement_irreversible":
            True,
        "team_salary_released_exactly":
            True,
        "apron_salary_released_exactly":
            True,
        "market_and_ledger_mirrored":
            True,
        "history_mirrored":
            True,
        "trade_revision_advances_once":
            True,
        "primary_and_backup_rollback":
            True,
    }
