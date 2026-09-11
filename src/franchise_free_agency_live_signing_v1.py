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

from franchise_free_agency_contract_salary_legality_v1_3 import (
    FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION,
    evaluate_contract_legal_financial_gate,
)
from franchise_free_agency_financial_bridge_v1_2 import (
    FREE_AGENCY_FINANCIAL_BRIDGE_VERSION,
)
from franchise_free_agency_transaction_v1 import (
    FREE_AGENCY_TRANSACTION_VERSION,
    FreeAgencyOffer,
    FreeAgencyTransactionPreview,
    free_agency_state_fingerprint,
)
from franchise_free_agency_transaction_v1_1 import (
    FREE_AGENCY_DURABLE_COMMIT_VERSION,
    FREE_AGENCY_TRANSACTION_V1_1_VERSION,
    build_free_agency_durable_candidate,
    free_agency_durable_state_fingerprint,
)

FREE_AGENCY_LIVE_SIGNING_VERSION = (
    "franchise-free-agency-live-signing-v1-2026-08-14"
)
FREE_AGENCY_TRADE_STATE_SYNC_VERSION = (
    "franchise-free-agency-trade-state-sync-v1-2026-08-14"
)
FREE_AGENCY_LIVE_UI_VERSION = (
    "franchise-free-agency-live-ui-v1-2026-08-14"
)
TRADE_CONTRACT_OVERRIDES_ATTR = "free_agency_contract_overrides"
TRADE_FREE_AGENCY_HISTORY_ATTR = "free_agency_transaction_history"
CONTROLLED_TEAMS_PREFERENCE_KEY = "franchise_pref_controlled_teams"


class FreeAgencyLiveSigningError(RuntimeError):
    """Raised when a live free-agent signing cannot be committed safely."""


@dataclass(frozen=True)
class TradeStateSigningSyncResult:
    version: str
    player_id: str
    team_abbreviation: str
    state_revision_before: int
    state_revision_after: int
    team_salary_before: float
    team_salary_after: float
    apron_salary_before: float
    apron_salary_after: float
    standard_contract_count_before: int
    standard_contract_count_after: int
    undo_snapshots_rebased: int
    initial_snapshot_rebased: bool


@dataclass(frozen=True)
class FreeAgencyLiveSigningResult:
    version: str
    transaction_id: str
    offer_id: str
    player_id: str
    player_name: str
    team_abbreviation: str
    annual_salary: float
    years: int
    free_agency_revision: int
    source_simulation_fingerprint: str
    committed_simulation_fingerprint: str
    source_trade_fingerprint: str
    committed_trade_fingerprint: str
    trade_state_revision_before: int
    trade_state_revision_after: int
    checkpoint_hash_before: str
    checkpoint_hash_after: str
    checkpoint_saved_at_utc: str
    checkpoint_reason: str
    recovery_path: str


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _player_id(value: Any) -> str:
    return _clean(value)


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _phase(state: Any) -> str:
    value = getattr(state, "phase", "")
    return _clean(getattr(value, "value", value)).lower()


def _preference_dict(checkpoint: Any) -> dict[str, Any]:
    raw = getattr(checkpoint, "preferences", None)
    return copy.deepcopy(dict(raw)) if isinstance(raw, Mapping) else {}


def controlled_teams_from_durable_checkpoint(checkpoint: Any) -> tuple[str, ...]:
    """Resolve only teams explicitly persisted as user-controlled."""
    state = getattr(checkpoint, "simulation_state", None)
    teams = {_team(key) for key in getattr(state, "teams", {})}
    raw = _preference_dict(checkpoint).get(
        CONTROLLED_TEAMS_PREFERENCE_KEY,
        (),
    )
    if isinstance(raw, str):
        values = [raw]
    else:
        try:
            values = list(raw)
        except TypeError:
            values = []
    result: list[str] = []
    for value in values:
        team = _team(value)
        if team and team in teams and team not in result:
            result.append(team)
    return tuple(result)


def _financial_payload(value: Any) -> dict[str, Any]:
    return {
        "team_abbreviation": _team(getattr(value, "team_abbreviation", "")),
        "team_salary": _finite(getattr(value, "team_salary", None)),
        "apron_salary": _finite(getattr(value, "apron_salary", None)),
        "standard_contract_count": getattr(value, "standard_contract_count", None),
        "two_way_contract_count": getattr(value, "two_way_contract_count", None),
        "hard_cap_active": getattr(value, "hard_cap_active", None),
        "hard_cap_level": _clean(getattr(value, "hard_cap_level", "")),
    }


def _snapshot_payload(snapshot: Any) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    return {
        "player_team_by_id": sorted(
            (_player_id(k), _team(v))
            for k, v in dict(getattr(snapshot, "player_team_by_id", {}) or {}).items()
        ),
        "pick_team_by_id": sorted(
            (_clean(k), _team(v))
            for k, v in dict(getattr(snapshot, "pick_team_by_id", {}) or {}).items()
        ),
        "team_financials": [
            (team, _financial_payload(value))
            for team, value in sorted(
                dict(getattr(snapshot, "team_financials", {}) or {}).items()
            )
        ],
        "acquired_player_ids": sorted(
            _player_id(value)
            for value in set(getattr(snapshot, "acquired_player_ids", set()) or set())
        ),
    }


def trade_state_payload(state: Any) -> dict[str, Any]:
    history = list(getattr(state, "transaction_history", []) or [])
    trade_history = [
        {
            "transaction_id": _clean(getattr(record, "transaction_id", "")),
            "state_revision": int(getattr(record, "state_revision", 0) or 0),
            "evaluation_status": _clean(getattr(record, "evaluation_status", "")),
        }
        for record in history
    ]
    overrides = getattr(state, TRADE_CONTRACT_OVERRIDES_ATTR, {})
    if not isinstance(overrides, Mapping):
        overrides = {}
    fa_history = getattr(state, TRADE_FREE_AGENCY_HISTORY_ATTR, [])
    if not isinstance(fa_history, list):
        fa_history = []
    return {
        "state_version": _clean(getattr(state, "state_version", "")),
        "engine_validation_revision": _clean(
            getattr(state, "engine_validation_revision", "")
        ),
        "state_revision": int(getattr(state, "state_revision", 0) or 0),
        "player_team_by_id": sorted(
            (_player_id(k), _team(v))
            for k, v in dict(getattr(state, "player_team_by_id", {}) or {}).items()
        ),
        "pick_team_by_id": sorted(
            (_clean(k), _team(v))
            for k, v in dict(getattr(state, "pick_team_by_id", {}) or {}).items()
        ),
        "team_financials": [
            (team, _financial_payload(value))
            for team, value in sorted(
                dict(getattr(state, "team_financials", {}) or {}).items()
            )
        ],
        "acquired_player_ids": sorted(
            _player_id(value)
            for value in set(getattr(state, "acquired_player_ids", set()) or set())
        ),
        "trade_transaction_history": trade_history,
        "undo_stack": [
            _snapshot_payload(snapshot)
            for snapshot in list(getattr(state, "undo_stack", []) or [])
        ],
        "initial_snapshot": _snapshot_payload(
            getattr(state, "initial_snapshot", None)
        ),
        "free_agency_contract_overrides": copy.deepcopy(dict(overrides)),
        "free_agency_transaction_history": copy.deepcopy(fa_history),
    }


def trade_state_fingerprint(state: Any) -> str:
    encoded = json.dumps(
        trade_state_payload(state),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _apply_financial_delta(
    financial: Any,
    salary: float,
) -> tuple[float, float, int]:
    team_salary = _finite(getattr(financial, "team_salary", None))
    apron_salary = _finite(getattr(financial, "apron_salary", None))
    count = getattr(financial, "standard_contract_count", None)
    if team_salary is None or apron_salary is None:
        raise FreeAgencyLiveSigningError(
            "Trade-state team salary/apron salary is not deterministic enough "
            "to synchronize this signing."
        )
    if not isinstance(count, int):
        raise FreeAgencyLiveSigningError(
            "Trade-state standard-contract count is unavailable."
        )
    financial.team_salary = round(team_salary + salary, 2)
    financial.apron_salary = round(apron_salary + salary, 2)
    financial.standard_contract_count = count + 1
    return team_salary, apron_salary, count


def _rebase_snapshot_for_signing(
    snapshot: Any,
    *,
    player_id: str,
    team: str,
    salary: float,
) -> None:
    if snapshot is None:
        return
    ownership = getattr(snapshot, "player_team_by_id", None)
    financials = getattr(snapshot, "team_financials", None)
    acquired = getattr(snapshot, "acquired_player_ids", None)
    if not isinstance(ownership, dict) or not isinstance(financials, dict):
        raise FreeAgencyLiveSigningError(
            "A Trade Machine undo/reset snapshot does not expose the expected state contract."
        )
    if player_id not in ownership:
        raise FreeAgencyLiveSigningError(
            "The free agent is missing from a Trade Machine undo/reset snapshot."
        )
    observed = _team(ownership[player_id])
    if observed not in {"", team}:
        raise FreeAgencyLiveSigningError(
            "A historical Trade Machine snapshot assigns the free agent to an incompatible team."
        )
    if team not in financials:
        raise FreeAgencyLiveSigningError(
            "The signing team is missing from a Trade Machine undo/reset snapshot."
        )
    ownership[player_id] = team
    if observed == "":
        _apply_financial_delta(financials[team], salary)
    if isinstance(acquired, set):
        acquired.add(player_id)


def _record_trade_state_free_agency_metadata(
    state: Any,
    *,
    offer: FreeAgencyOffer,
    transaction_id: str,
) -> None:
    overrides = getattr(state, TRADE_CONTRACT_OVERRIDES_ATTR, None)
    if overrides is None:
        overrides = {}
    if not isinstance(overrides, dict):
        raise FreeAgencyLiveSigningError(
            f"{TRADE_CONTRACT_OVERRIDES_ATTR} must be a dict when present."
        )
    overrides = copy.deepcopy(overrides)
    overrides[offer.player_id] = {
        "version": FREE_AGENCY_TRADE_STATE_SYNC_VERSION,
        "transaction_id": transaction_id,
        "player_id": offer.player_id,
        "team_abbreviation": offer.team_abbreviation,
        "annual_salary": float(offer.annual_salary),
        "years": int(offer.years),
        "guaranteed": bool(offer.guaranteed),
        "option_type": offer.option_type,
    }
    setattr(state, TRADE_CONTRACT_OVERRIDES_ATTR, overrides)

    history = getattr(state, TRADE_FREE_AGENCY_HISTORY_ATTR, None)
    if history is None:
        history = []
    if not isinstance(history, list):
        raise FreeAgencyLiveSigningError(
            f"{TRADE_FREE_AGENCY_HISTORY_ATTR} must be a list when present."
        )
    history = copy.deepcopy(history)
    history.append(copy.deepcopy(overrides[offer.player_id]))
    setattr(state, TRADE_FREE_AGENCY_HISTORY_ATTR, history)



# NON_RFA_SAME_TEAM_RESIGN_CONSUMPTION_V1_TRADE
_NON_RFA_RESIGN_LEDGER_ATTR = "offseason_non_rfa_rights_decisions_v1"
_NON_RFA_RESIGN_MARKET_ATTR = "offseason_free_agent_amount_candidates_v1"
_NON_RFA_RESIGN_RFA_LEDGER_ATTR = "offseason_rfa_rights_qo_decisions_v1"
_NON_RFA_RESIGN_HISTORY_ATTR = "offseason_non_rfa_rights_lifecycle_history_v1"
_NON_RFA_RESIGN_RETAINED = {"retain_rights_by_default", "retain_rights"}


def _same_team_trade_non_rfa_rights_charge(
    state: Any,
    *,
    player_id: str,
    team: str,
) -> float:
    for row in list(getattr(state, _NON_RFA_RESIGN_RFA_LEDGER_ATTR, ()) or ()):
        if (
            isinstance(row, Mapping)
            and _player_id(row.get("player_id")) == player_id
        ):
            return 0.0

    matches = [
        dict(row)
        for row in list(getattr(state, _NON_RFA_RESIGN_LEDGER_ATTR, ()) or ())
        if isinstance(row, Mapping)
        and _player_id(row.get("player_id")) == player_id
    ]
    if not matches:
        return 0.0
    if len(matches) != 1:
        raise FreeAgencyLiveSigningError(
            f"Expected one non-RFA rights row for {player_id!r}, found {len(matches)}."
        )

    row = matches[0]
    if _team(row.get("prior_team")) != team:
        return 0.0
    if _clean(row.get("rights_decision")) not in _NON_RFA_RESIGN_RETAINED:
        return 0.0

    charge = _finite(row.get("effective_charge_2026_27"))
    if charge is None:
        raise FreeAgencyLiveSigningError(
            "The retained non-RFA rights charge is not deterministic."
        )
    return float(charge) if charge > 0 else 0.0


def _consume_trade_non_rfa_rights_rows(
    state: Any,
    *,
    player_id: str,
    team: str,
    transaction_id: str,
    charge: float,
    contract_salary: float,
    require_rows: bool = True,
) -> None:
    if charge <= 0:
        return

    updates = {
        "rights_decision": "consumed_by_contract",
        "effective_charge_2026_27": 0.0,
        "cap_hold_applied": False,
        "cap_hold_applied_to_clone": False,
        "rights_decision_applied": True,
        "rights_decision_applied_to_clone": True,
        "decision_source": "same_team_non_rfa_contract_consumption_v1",
        "contract_consumption_applied": True,
        "contract_consumption_transaction_id": transaction_id,
    }

    for attr in (_NON_RFA_RESIGN_LEDGER_ATTR, _NON_RFA_RESIGN_MARKET_ATTR):
        raw = getattr(state, attr, None)
        if raw is None:
            if require_rows:
                raise FreeAgencyLiveSigningError(
                    f"{attr} is unavailable while consuming retained non-RFA rights."
                )
            continue
        rows = list(raw or ())
        if not rows:
            if require_rows:
                raise FreeAgencyLiveSigningError(
                    f"{attr} is empty while consuming retained non-RFA rights."
                )
            continue

        replaced = []
        found = 0
        for source_row in rows:
            if not isinstance(source_row, Mapping):
                replaced.append(copy.deepcopy(source_row))
                continue
            row = copy.deepcopy(dict(source_row))
            if _player_id(row.get("player_id")) == player_id:
                row.update(copy.deepcopy(updates))
                found += 1
            replaced.append(row)

        if found != 1:
            if require_rows:
                raise FreeAgencyLiveSigningError(
                    f"Expected one {attr} row for {player_id!r}, replaced {found}."
                )
            continue
        setattr(state, attr, replaced)

    if not require_rows:
        return

    history = getattr(state, _NON_RFA_RESIGN_HISTORY_ATTR, None)
    if history is None:
        history = []
    if not isinstance(history, list):
        raise FreeAgencyLiveSigningError(
            f"{_NON_RFA_RESIGN_HISTORY_ATTR} must be a list when present."
        )
    history = copy.deepcopy(history)
    history.append(
        {
            "transaction_id": transaction_id,
            "event": "non_rfa_rights_consumed_by_same_team_contract",
            "player_id": player_id,
            "prior_team": team,
            "released_charge": float(charge),
            "contract_salary": float(contract_salary),
            "rights_decision": "consumed_by_contract",
        }
    )
    setattr(state, _NON_RFA_RESIGN_HISTORY_ATTR, history)


def _annotate_trade_fatx_rights_consumption(
    state: Any,
    *,
    player_id: str,
    charge: float,
) -> None:
    if charge <= 0:
        return

    overrides = getattr(state, TRADE_CONTRACT_OVERRIDES_ATTR, None)
    if isinstance(overrides, dict) and player_id in overrides:
        overrides = copy.deepcopy(overrides)
        overrides[player_id]["non_rfa_rights_consumed"] = True
        overrides[player_id]["non_rfa_rights_charge_released"] = float(charge)
        setattr(state, TRADE_CONTRACT_OVERRIDES_ATTR, overrides)

    history = getattr(state, TRADE_FREE_AGENCY_HISTORY_ATTR, None)
    if isinstance(history, list) and history:
        history = copy.deepcopy(history)
        if _player_id(history[-1].get("player_id")) == player_id:
            history[-1]["non_rfa_rights_consumed"] = True
            history[-1]["non_rfa_rights_charge_released"] = float(charge)
            setattr(state, TRADE_FREE_AGENCY_HISTORY_ATTR, history)



def build_trade_state_free_agency_candidate(
    trade_state: Any,
    offer: FreeAgencyOffer,
    *,
    transaction_id: str,
    validate: bool = True,
) -> tuple[Any, TradeStateSigningSyncResult]:
    """Synchronize ownership/aggregate finance without inventing a trade record.

    Existing trade undo/reset snapshots are rebased so later Trade Machine undo
    actions preserve the signing instead of restoring a pre-free-agency roster.
    """
    if trade_state is None:
        raise FreeAgencyLiveSigningError(
            "Durable Trade Machine state is unavailable."
        )
    player_id = _player_id(offer.player_id)
    team = _team(offer.team_abbreviation)
    salary = _finite(offer.annual_salary)
    if not player_id or not team or salary is None or salary <= 0:
        raise FreeAgencyLiveSigningError(
            "Trade-state synchronization received an invalid offer."
        )

    candidate = copy.deepcopy(trade_state)
    ownership = getattr(candidate, "player_team_by_id", None)
    financials = getattr(candidate, "team_financials", None)
    if not isinstance(ownership, dict) or not isinstance(financials, dict):
        raise FreeAgencyLiveSigningError(
            "Trade Machine state does not expose mutable ownership/financial maps."
        )
    if player_id not in ownership:
        raise FreeAgencyLiveSigningError(
            "Free agent is missing from the durable Trade Machine player map."
        )
    if _team(ownership[player_id]):
        raise FreeAgencyLiveSigningError(
            "Trade Machine state no longer considers this player a free agent."
        )
    if team not in financials:
        raise FreeAgencyLiveSigningError(
            "Signing team is missing from the durable Trade Machine financial map."
        )

    before_financial = financials[team]
    before_team_salary = _finite(getattr(before_financial, "team_salary", None))
    before_apron_salary = _finite(getattr(before_financial, "apron_salary", None))
    before_count = getattr(before_financial, "standard_contract_count", None)
    if before_team_salary is None or before_apron_salary is None or not isinstance(before_count, int):
        raise FreeAgencyLiveSigningError(
            "Signing team lacks deterministic Trade Machine salary/count data."
        )
    revision_before = int(getattr(candidate, "state_revision", 0) or 0)

    _non_rfa_rights_charge = _same_team_trade_non_rfa_rights_charge(
        candidate,
        player_id=player_id,
        team=team,
    )
    _financial_delta = salary - _non_rfa_rights_charge

    ownership[player_id] = team
    _apply_financial_delta(financials[team], _financial_delta)
    if _non_rfa_rights_charge > 0:
        _consume_trade_non_rfa_rights_rows(
            candidate,
            player_id=player_id,
            team=team,
            transaction_id=transaction_id,
            charge=_non_rfa_rights_charge,
            contract_salary=salary,
            require_rows=True,
        )

    acquired = getattr(candidate, "acquired_player_ids", None)
    if isinstance(acquired, set):
        acquired.add(player_id)

    undo_stack = list(getattr(candidate, "undo_stack", []) or [])
    for snapshot in undo_stack:
        _rebase_snapshot_for_signing(
            snapshot,
            player_id=player_id,
            team=team,
            salary=salary,
        )
        if _non_rfa_rights_charge > 0:
            _consume_trade_non_rfa_rights_rows(
                snapshot,
                player_id=player_id,
                team=team,
                transaction_id=transaction_id,
                charge=_non_rfa_rights_charge,
                contract_salary=salary,
                require_rows=False,
            )
            if hasattr(snapshot, "team_financials"):
                snapshot.team_financials = copy.deepcopy(candidate.team_financials)

    initial_snapshot = getattr(candidate, "initial_snapshot", None)
    if initial_snapshot is not None:
        _rebase_snapshot_for_signing(
            initial_snapshot,
            player_id=player_id,
            team=team,
            salary=salary,
        )
        if _non_rfa_rights_charge > 0:
            _consume_trade_non_rfa_rights_rows(
                initial_snapshot,
                player_id=player_id,
                team=team,
                transaction_id=transaction_id,
                charge=_non_rfa_rights_charge,
                contract_salary=salary,
                require_rows=False,
            )
            if hasattr(initial_snapshot, "team_financials"):
                initial_snapshot.team_financials = copy.deepcopy(
                    candidate.team_financials
                )

    setattr(candidate, "state_revision", revision_before + 1)
    _record_trade_state_free_agency_metadata(
        candidate,
        offer=offer,
        transaction_id=transaction_id,
    )
    _annotate_trade_fatx_rights_consumption(
        candidate,
        player_id=player_id,
        charge=_non_rfa_rights_charge,
    )

    if validate:
        try:
            from freeform_trade_machine_engine_v3 import load_runtime_data
            from mutable_league_state_v1 import validate_state
            runtime = load_runtime_data()
            validate_state(candidate, runtime)
        except FreeAgencyLiveSigningError:
            raise
        except Exception as exc:
            raise FreeAgencyLiveSigningError(
                f"Synchronized Trade Machine candidate is invalid: {exc}"
            ) from exc

    after = financials[team]
    result = TradeStateSigningSyncResult(
        version=FREE_AGENCY_TRADE_STATE_SYNC_VERSION,
        player_id=player_id,
        team_abbreviation=team,
        state_revision_before=revision_before,
        state_revision_after=int(getattr(candidate, "state_revision", 0) or 0),
        team_salary_before=float(before_team_salary),
        team_salary_after=float(getattr(after, "team_salary")),
        apron_salary_before=float(before_apron_salary),
        apron_salary_after=float(getattr(after, "apron_salary")),
        standard_contract_count_before=int(before_count),
        standard_contract_count_after=int(getattr(after, "standard_contract_count")),
        undo_snapshots_rebased=len(undo_stack),
        initial_snapshot_rebased=initial_snapshot is not None,
    )
    return candidate, result


def _align_simulation_source_to_trade_state(
    simulation_candidate: Any,
    trade_candidate: Any,
) -> None:
    if hasattr(simulation_candidate, "source_league_state_revision"):
        simulation_candidate.source_league_state_revision = int(
            getattr(trade_candidate, "state_revision", 0) or 0
        )
    if hasattr(simulation_candidate, "source_transaction_count"):
        simulation_candidate.source_transaction_count = len(
            list(getattr(trade_candidate, "transaction_history", []) or [])
        )
    history = getattr(simulation_candidate, "free_agency_transaction_history", None)
    if isinstance(history, list) and history:
        history[-1]["candidate_fingerprint"] = free_agency_state_fingerprint(
            simulation_candidate
        )


def assert_live_commit_preconditions(
    checkpoint: Any,
    preview: FreeAgencyTransactionPreview,
    *,
    hypothetical: bool = False,
) -> None:
    state = getattr(checkpoint, "simulation_state", None)
    if state is None:
        raise FreeAgencyLiveSigningError(
            "Durable checkpoint has no simulation state."
        )
    if hypothetical:
        raise FreeAgencyLiveSigningError(
            "A hypothetical offseason preview can never be committed."
        )
    if _phase(state) != "offseason":
        raise FreeAgencyLiveSigningError(
            "Live free-agent signings are available only during the actual offseason."
        )
    if not bool(getattr(preview, "can_commit", False)) or _clean(
        getattr(preview, "status", "")
    ).lower() != "pass":
        raise FreeAgencyLiveSigningError(
            "Only a fully PASS V1.2 + V1.3 free-agency preview can be committed."
        )
    controlled = controlled_teams_from_durable_checkpoint(checkpoint)
    team = _team(preview.offer.team_abbreviation)
    if team not in controlled:
        raise FreeAgencyLiveSigningError(
            "The signing team is not explicitly user-controlled in the durable checkpoint."
        )

    # RFA_OFFER_SHEET_PENDING_TEAM_LOCK_V1
    # Conservatively preserve the offering team's required cap room while a
    # restricted-free-agent offer sheet is awaiting right-of-first-refusal.
    from franchise_free_agency_rfa_offer_sheet_v1 import (
        pending_offer_sheet_for_team,
    )
    pending_offer_sheet = pending_offer_sheet_for_team(state, team)
    if pending_offer_sheet is not None:
        raise FreeAgencyLiveSigningError(
            "This controlled team has a pending RFA offer sheet. Resolve the "
            "right-of-first-refusal window before committing another live "
            "free-agent signing."
        )

    if free_agency_state_fingerprint(state) != preview.source_fingerprint:
        raise FreeAgencyLiveSigningError(
            "Approved free-agency preview is stale relative to the durable checkpoint."
        )


def commit_contract_legal_free_agency_preview_live(
    preview: FreeAgencyTransactionPreview,
    *,
    hypothetical: bool = False,
    max_roster_size: int = 18,
    recovery_directory: str | Path | None = None,
) -> FreeAgencyLiveSigningResult:
    """Commit a user-controlled free-agent signing to both durable states."""
    from simulation_franchise_checkpoint_v1 import (
        DEFAULT_CHECKPOINT_PATH,
        checkpoint_backup_path,
        load_franchise_checkpoint,
        save_franchise_checkpoint,
    )
    from simulation_league_state_v1 import validate_simulation_league_state

    checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    try:
        automatic_backup_path = Path(checkpoint_backup_path(checkpoint_path))
    except TypeError:
        automatic_backup_path = Path(checkpoint_backup_path())
    if not checkpoint_path.exists():
        raise FreeAgencyLiveSigningError(
            "Durable franchise checkpoint does not exist."
        )
    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise FreeAgencyLiveSigningError(
            "Durable franchise checkpoint could not be loaded."
        )
    assert_live_commit_preconditions(
        checkpoint,
        preview,
        hypothetical=hypothetical,
    )

    source_sim = checkpoint.simulation_state
    source_trade = checkpoint.trade_state
    if source_trade is None:
        raise FreeAgencyLiveSigningError(
            "Durable checkpoint has no Trade Machine state."
        )
    validate_simulation_league_state(source_sim)
    source_sim_fp = free_agency_state_fingerprint(source_sim)
    source_trade_fp = trade_state_fingerprint(source_trade)

    simulation_candidate, commit, revision, transaction_id = (
        build_free_agency_durable_candidate(
            source_sim,
            preview,
            financial_gate=evaluate_contract_legal_financial_gate,
            state_validator=validate_simulation_league_state,
            max_roster_size=max_roster_size,
        )
    )
    trade_candidate, trade_sync = build_trade_state_free_agency_candidate(
        source_trade,
        preview.offer,
        transaction_id=transaction_id,
        validate=True,
    )
    _align_simulation_source_to_trade_state(
        simulation_candidate,
        trade_candidate,
    )
    validate_simulation_league_state(simulation_candidate)

    # Refresh the final history fingerprint after source-revision alignment.
    history = getattr(simulation_candidate, "free_agency_transaction_history", None)
    if isinstance(history, list) and history:
        history[-1]["candidate_fingerprint"] = free_agency_state_fingerprint(
            simulation_candidate
        )
    expected_sim_fp = free_agency_durable_state_fingerprint(
        simulation_candidate
    )
    expected_trade_fp = trade_state_fingerprint(trade_candidate)

    checkpoint_hash_before = _sha256(checkpoint_path)
    recovery_root = (
        Path(recovery_directory)
        if recovery_directory is not None
        else checkpoint_path.parent / "free_agency_recovery"
    )
    recovery_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    recovery_path = recovery_root / (
        f"pre_{transaction_id}_{stamp}_{checkpoint_path.name}"
    )
    shutil.copy2(checkpoint_path, recovery_path)
    automatic_backup_existed_before = automatic_backup_path.exists()
    recovery_backup_path = recovery_root / (
        f"pre_{transaction_id}_{stamp}_{automatic_backup_path.name}"
    )
    if automatic_backup_existed_before:
        shutil.copy2(automatic_backup_path, recovery_backup_path)
    reason = f"free-agency-live-signing-{transaction_id}"

    try:
        saved = save_franchise_checkpoint(
            simulation_candidate,
            trade_candidate,
            preferences=_preference_dict(checkpoint),
            reason=reason,
            copy_payload=True,
        )
        reloaded = load_franchise_checkpoint()
        if reloaded is None:
            raise FreeAgencyLiveSigningError(
                "Checkpoint reload returned no state after live signing."
            )
        observed_sim_fp = free_agency_durable_state_fingerprint(
            reloaded.simulation_state
        )
        observed_trade_fp = trade_state_fingerprint(reloaded.trade_state)
        if observed_sim_fp != expected_sim_fp:
            raise FreeAgencyLiveSigningError(
                "Reloaded simulation state does not exactly match the approved signing."
            )
        if observed_trade_fp != expected_trade_fp:
            raise FreeAgencyLiveSigningError(
                "Reloaded Trade Machine state does not exactly match the synchronized signing."
            )
        observed_history = getattr(
            reloaded.simulation_state,
            "free_agency_transaction_history",
            [],
        )
        if not observed_history or observed_history[-1].get("transaction_id") != transaction_id:
            raise FreeAgencyLiveSigningError(
                "FATX history did not survive checkpoint reload."
            )
        if _team(reloaded.trade_state.player_team_by_id.get(preview.offer.player_id, "")) != _team(preview.offer.team_abbreviation):
            raise FreeAgencyLiveSigningError(
                "Trade Machine player ownership did not survive checkpoint reload."
            )
    except Exception as exc:
        shutil.copy2(recovery_path, checkpoint_path)
        if automatic_backup_existed_before:
            if not recovery_backup_path.exists():
                raise FreeAgencyLiveSigningError(
                    "Live signing failed and the pre-signing automatic-backup "
                    "recovery copy is missing."
                ) from exc
            shutil.copy2(recovery_backup_path, automatic_backup_path)
        elif automatic_backup_path.exists():
            automatic_backup_path.unlink()
        restored = load_franchise_checkpoint()
        if restored is None:
            raise FreeAgencyLiveSigningError(
                "Live signing failed and checkpoint recovery could not be loaded."
            ) from exc
        restored_sim_fp = free_agency_state_fingerprint(restored.simulation_state)
        restored_trade_fp = trade_state_fingerprint(restored.trade_state)
        if restored_sim_fp != source_sim_fp or restored_trade_fp != source_trade_fp:
            raise FreeAgencyLiveSigningError(
                "Live signing failed and automatic recovery could not be verified."
            ) from exc
        raise FreeAgencyLiveSigningError(
            f"Live signing failed. The pre-signing checkpoint was restored: {exc}"
        ) from exc

    return FreeAgencyLiveSigningResult(
        version=FREE_AGENCY_LIVE_SIGNING_VERSION,
        transaction_id=transaction_id,
        offer_id=commit.offer_id,
        player_id=commit.player_id,
        player_name=commit.player_name,
        team_abbreviation=commit.team_abbreviation,
        annual_salary=float(preview.offer.annual_salary),
        years=int(preview.offer.years),
        free_agency_revision=revision,
        source_simulation_fingerprint=source_sim_fp,
        committed_simulation_fingerprint=expected_sim_fp,
        source_trade_fingerprint=source_trade_fp,
        committed_trade_fingerprint=expected_trade_fp,
        trade_state_revision_before=trade_sync.state_revision_before,
        trade_state_revision_after=trade_sync.state_revision_after,
        checkpoint_hash_before=checkpoint_hash_before,
        checkpoint_hash_after=_sha256(checkpoint_path),
        checkpoint_saved_at_utc=_clean(getattr(saved, "saved_at_utc", "")),
        checkpoint_reason=reason,
        recovery_path=str(recovery_path),
    )
