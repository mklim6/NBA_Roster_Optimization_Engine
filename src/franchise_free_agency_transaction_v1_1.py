from __future__ import annotations

import copy
import hashlib
import inspect
import json
import math
import shutil
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from franchise_free_agency_transaction_v1 import (
    FREE_AGENCY_TRANSACTION_VERSION,
    FreeAgencyCommitResult,
    FreeAgencyFinancialGateResult,
    FreeAgencyOffer,
    FreeAgencyTransactionError,
    FreeAgencyTransactionPreview,
    build_free_agency_preview,
    commit_free_agency_preview,
    free_agency_state_fingerprint,
)


FREE_AGENCY_TRANSACTION_V1_1_VERSION = (
    "franchise-free-agency-transaction-v1.1-2026-08-14"
)
FREE_AGENCY_CAP_SPACE_GATE_VERSION = (
    "franchise-free-agency-cap-space-gate-v1-2026-08-14"
)
FREE_AGENCY_DURABLE_COMMIT_VERSION = (
    "franchise-free-agency-durable-commit-v1-2026-08-14"
)
FREE_AGENCY_HISTORY_ATTR = "free_agency_transaction_history"
FREE_AGENCY_REVISION_ATTR = "free_agency_transaction_revision"


class FreeAgencyDurableCommitError(FreeAgencyTransactionError):
    """Raised when a durable free-agency commit cannot be proven safe."""


@dataclass(frozen=True)
class FreeAgencyCapSpaceGateConfig:
    salary_cap: float
    season_label: str
    source: str
    allow_zero_salary_rows: bool = False


@dataclass(frozen=True)
class FreeAgencyDurableCommitResult:
    version: str
    transaction_id: str
    offer_id: str
    player_id: str
    player_name: str
    team_abbreviation: str
    free_agency_revision: int
    source_fingerprint: str
    committed_fingerprint: str
    checkpoint_hash_before: str
    checkpoint_hash_after: str
    checkpoint_saved_at_utc: str
    checkpoint_reason: str
    recovery_path: str


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_team(value: Any) -> str:
    return _clean_text(value).upper()


def _finite_nonnegative(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(k): _json_safe(v)
            for k, v in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_safe(item) for item in value]
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, (str, int, float, bool)):
        return enum_value
    return str(value)


def _team_roster_ids(state: Any, team_abbreviation: str) -> tuple[str, ...]:
    team = getattr(state, "teams", {}).get(_normalize_team(team_abbreviation))
    if team is None:
        return ()
    return tuple(str(x).strip() for x in getattr(team, "roster_player_ids", ()))


def team_guaranteed_payroll(state: Any, team_abbreviation: str) -> tuple[float, dict[str, Any]]:
    """Return conservative payroll using live permanent contract salary rows.

    This function intentionally does not invent exceptions, cap holds, or future
    salary estimates. Unknown salary rows make the gate manual-review only.
    """
    players = getattr(state, "players", {})
    roster_ids = _team_roster_ids(state, team_abbreviation)
    payroll = 0.0
    known_rows = 0
    missing_rows: list[str] = []
    zero_rows: list[str] = []

    for player_id in roster_ids:
        player = players.get(player_id)
        contract = getattr(player, "contract", None) if player is not None else None
        salary = _finite_nonnegative(getattr(contract, "salary", None))
        if salary is None:
            missing_rows.append(player_id)
            continue
        known_rows += 1
        payroll += salary
        if salary == 0:
            zero_rows.append(player_id)

    return payroll, {
        "team": _normalize_team(team_abbreviation),
        "roster_count": len(roster_ids),
        "known_salary_rows": known_rows,
        "missing_salary_player_ids": missing_rows,
        "zero_salary_player_ids": zero_rows,
    }


def evaluate_cap_space_gate(
    state: Any,
    offer: FreeAgencyOffer,
    *,
    config: FreeAgencyCapSpaceGateConfig,
) -> FreeAgencyFinancialGateResult:
    cap = _finite_nonnegative(config.salary_cap)
    salary = _finite_nonnegative(offer.annual_salary)
    settings = getattr(state, "settings", None)
    live_season = _clean_text(getattr(settings, "season_label", ""))
    configured_season = _clean_text(config.season_label)

    if cap is None or cap <= 0:
        return FreeAgencyFinancialGateResult(
            status="manual_review",
            reason="Salary-cap threshold is missing or invalid.",
            payload={"gate_version": FREE_AGENCY_CAP_SPACE_GATE_VERSION},
        )
    if salary is None or salary <= 0:
        return FreeAgencyFinancialGateResult(
            status="blocked",
            reason="Offer salary is invalid.",
            payload={"gate_version": FREE_AGENCY_CAP_SPACE_GATE_VERSION},
        )
    if not configured_season or live_season != configured_season:
        return FreeAgencyFinancialGateResult(
            status="manual_review",
            reason=(
                "Cap-space threshold season does not match the live franchise season."
            ),
            payload={
                "gate_version": FREE_AGENCY_CAP_SPACE_GATE_VERSION,
                "live_season": live_season,
                "configured_season": configured_season,
            },
        )

    payroll, detail = team_guaranteed_payroll(state, offer.team_abbreviation)
    missing = detail["missing_salary_player_ids"]
    zero_rows = detail["zero_salary_player_ids"]
    if missing or (zero_rows and not config.allow_zero_salary_rows):
        return FreeAgencyFinancialGateResult(
            status="manual_review",
            reason=(
                "Live roster salary coverage is incomplete. V1.1 will not infer "
                "cap space from unknown or zero salary rows."
            ),
            payload={
                "gate_version": FREE_AGENCY_CAP_SPACE_GATE_VERSION,
                "source": config.source,
                "salary_cap": cap,
                "payroll_before": payroll,
                **detail,
            },
        )

    payroll_after = payroll + salary
    cap_space_before = cap - payroll
    cap_space_after = cap - payroll_after
    payload = {
        "gate_version": FREE_AGENCY_CAP_SPACE_GATE_VERSION,
        "route": "pure_cap_space_only",
        "source": config.source,
        "season_label": live_season,
        "salary_cap": cap,
        "payroll_before": payroll,
        "offer_annual_salary": salary,
        "payroll_after": payroll_after,
        "cap_space_before": cap_space_before,
        "cap_space_after": cap_space_after,
        **detail,
    }

    if payroll_after <= cap + 0.01:
        return FreeAgencyFinancialGateResult(
            status="pass",
            reason="Signing fits entirely inside verified cap space.",
            payload=payload,
        )

    return FreeAgencyFinancialGateResult(
        status="manual_review",
        reason=(
            "Team is over the pure cap-space route. V1.1 does not invent Bird, "
            "mid-level, minimum, bi-annual, sign-and-trade, or other exception rights."
        ),
        payload=payload,
    )


def cap_space_gate(config: FreeAgencyCapSpaceGateConfig) -> Callable[[Any, FreeAgencyOffer], FreeAgencyFinancialGateResult]:
    def _gate(state: Any, offer: FreeAgencyOffer) -> FreeAgencyFinancialGateResult:
        return evaluate_cap_space_gate(state, offer, config=config)
    return _gate


def _history(state: Any) -> list[dict[str, Any]]:
    raw = getattr(state, FREE_AGENCY_HISTORY_ATTR, None)
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise FreeAgencyDurableCommitError(
            f"{FREE_AGENCY_HISTORY_ATTR} must be a list when present."
        )
    return copy.deepcopy(raw)


def free_agency_durable_state_payload(state: Any) -> dict[str, Any]:
    return {
        "v1_state_fingerprint": free_agency_state_fingerprint(state),
        "free_agency_revision": int(getattr(state, FREE_AGENCY_REVISION_ATTR, 0) or 0),
        "free_agency_history": _json_safe(_history(state)),
    }


def free_agency_durable_state_fingerprint(state: Any) -> str:
    encoded = json.dumps(
        free_agency_durable_state_payload(state),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _append_history(
    state: Any,
    *,
    commit: FreeAgencyCommitResult,
    preview: FreeAgencyTransactionPreview,
) -> tuple[int, str]:
    history = _history(state)
    revision = int(getattr(state, FREE_AGENCY_REVISION_ATTR, 0) or 0) + 1
    transaction_id = f"FATX-{revision:04d}"
    history.append({
        "transaction_id": transaction_id,
        "transaction_version": FREE_AGENCY_TRANSACTION_V1_1_VERSION,
        "base_transaction_version": FREE_AGENCY_TRANSACTION_VERSION,
        "offer_id": commit.offer_id,
        "player_id": commit.player_id,
        "player_name": commit.player_name,
        "team_abbreviation": commit.team_abbreviation,
        "annual_salary": float(preview.offer.annual_salary),
        "years": int(preview.offer.years),
        "guaranteed": bool(preview.offer.guaranteed),
        "option_type": preview.offer.option_type,
        "financial_gate_status": preview.financial_gate.status,
        "financial_gate_reason": preview.financial_gate.reason,
        "financial_gate_payload": _json_safe(preview.financial_gate.payload or {}),
        "source_fingerprint": commit.source_fingerprint,
        "candidate_fingerprint": commit.committed_fingerprint,
    })
    setattr(state, FREE_AGENCY_HISTORY_ATTR, history)
    setattr(state, FREE_AGENCY_REVISION_ATTR, revision)
    return revision, transaction_id



# NON_RFA_SAME_TEAM_RESIGN_CONSUMPTION_V1_SIM
_NON_RFA_RESIGN_LEDGER_ATTR = "offseason_non_rfa_rights_decisions_v1"
_NON_RFA_RESIGN_MARKET_ATTR = "offseason_free_agent_amount_candidates_v1"
_NON_RFA_RESIGN_RFA_LEDGER_ATTR = "offseason_rfa_rights_qo_decisions_v1"
_NON_RFA_RESIGN_HISTORY_ATTR = "offseason_non_rfa_rights_lifecycle_history_v1"
_NON_RFA_RESIGN_RETAINED = {"retain_rights_by_default", "retain_rights"}


def _non_rfa_resign_pid(value: Any) -> str:
    text = str(value or "").strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _non_rfa_resign_team(value: Any) -> str:
    return str(value or "").strip().upper()


def _same_team_active_non_rfa_rights_charge(
    state: Any,
    offer: FreeAgencyOffer,
) -> float:
    player_id = _non_rfa_resign_pid(offer.player_id)
    signing_team = _non_rfa_resign_team(offer.team_abbreviation)

    for row in list(getattr(state, _NON_RFA_RESIGN_RFA_LEDGER_ATTR, ()) or ()):
        if (
            isinstance(row, Mapping)
            and _non_rfa_resign_pid(row.get("player_id")) == player_id
        ):
            return 0.0

    matches = [
        dict(row)
        for row in list(getattr(state, _NON_RFA_RESIGN_LEDGER_ATTR, ()) or ())
        if isinstance(row, Mapping)
        and _non_rfa_resign_pid(row.get("player_id")) == player_id
    ]
    if not matches:
        return 0.0
    if len(matches) != 1:
        raise FreeAgencyDurableCommitError(
            f"Expected one non-RFA rights row for {player_id!r}, found {len(matches)}."
        )

    row = matches[0]
    if _non_rfa_resign_team(row.get("prior_team")) != signing_team:
        return 0.0
    if str(row.get("rights_decision") or "").strip() not in _NON_RFA_RESIGN_RETAINED:
        return 0.0

    try:
        charge = float(row.get("effective_charge_2026_27") or 0.0)
    except (TypeError, ValueError):
        raise FreeAgencyDurableCommitError(
            "The retained non-RFA rights charge is not numeric."
        )
    if charge <= 0:
        return 0.0
    return charge


def _consume_same_team_non_rfa_rights(
    state: Any,
    offer: FreeAgencyOffer,
    *,
    transaction_id: str,
) -> float:
    charge = _same_team_active_non_rfa_rights_charge(state, offer)
    if charge <= 0:
        return 0.0

    player_id = _non_rfa_resign_pid(offer.player_id)
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
        raw = list(getattr(state, attr, ()) or ())
        if not raw:
            raise FreeAgencyDurableCommitError(
                f"{attr} is unavailable while consuming retained non-RFA rights."
            )
        replaced = []
        found = 0
        for source_row in raw:
            if not isinstance(source_row, Mapping):
                replaced.append(copy.deepcopy(source_row))
                continue
            row = copy.deepcopy(dict(source_row))
            if _non_rfa_resign_pid(row.get("player_id")) == player_id:
                row.update(copy.deepcopy(updates))
                found += 1
            replaced.append(row)
        if found != 1:
            raise FreeAgencyDurableCommitError(
                f"Expected one {attr} row for {player_id!r}, replaced {found}."
            )
        setattr(state, attr, replaced)

    history = getattr(state, _NON_RFA_RESIGN_HISTORY_ATTR, None)
    if history is None:
        history = []
    if not isinstance(history, list):
        raise FreeAgencyDurableCommitError(
            f"{_NON_RFA_RESIGN_HISTORY_ATTR} must be a list when present."
        )
    history = copy.deepcopy(history)
    history.append(
        {
            "transaction_id": transaction_id,
            "event": "non_rfa_rights_consumed_by_same_team_contract",
            "player_id": player_id,
            "prior_team": _non_rfa_resign_team(offer.team_abbreviation),
            "released_charge": float(charge),
            "contract_salary": float(offer.annual_salary),
            "rights_decision": "consumed_by_contract",
        }
    )
    setattr(state, _NON_RFA_RESIGN_HISTORY_ATTR, history)
    return float(charge)



def build_free_agency_durable_candidate(
    state: Any,
    preview: FreeAgencyTransactionPreview,
    *,
    financial_gate: Callable[[Any, FreeAgencyOffer], Any],
    state_validator: Callable[[Any], Any] | None = None,
    max_roster_size: int = 18,
    _candidate_copy_on_write: bool = False,
) -> tuple[Any, FreeAgencyCommitResult, int, str]:
    candidate, commit = commit_free_agency_preview(
        state,
        preview,
        financial_gate=financial_gate,
        state_validator=state_validator,
        max_roster_size=max_roster_size,
        _candidate_copy_on_write=_candidate_copy_on_write,
    )
    revision, transaction_id = _append_history(
        candidate,
        commit=commit,
        preview=preview,
    )

    _consumed_non_rfa_charge = _consume_same_team_non_rfa_rights(
        candidate,
        preview.offer,
        transaction_id=transaction_id,
    )
    if _consumed_non_rfa_charge > 0:
        from dataclasses import replace as _dataclass_replace

        _final_commit_fingerprint = free_agency_state_fingerprint(candidate)
        commit = _dataclass_replace(
            commit,
            committed_fingerprint=_final_commit_fingerprint,
        )
        _updated_history = _history(candidate)
        if not _updated_history:
            raise FreeAgencyDurableCommitError(
                "FATX history disappeared while consuming non-RFA rights."
            )
        _updated_history[-1]["candidate_fingerprint"] = _final_commit_fingerprint
        _updated_history[-1]["non_rfa_rights_consumed"] = True
        _updated_history[-1]["non_rfa_rights_charge_released"] = float(
            _consumed_non_rfa_charge
        )
        setattr(candidate, FREE_AGENCY_HISTORY_ATTR, _updated_history)

    if state_validator is not None:
        state_validator(candidate)
    else:
        from simulation_league_state_v1 import validate_simulation_league_state
        validate_simulation_league_state(candidate)
    return candidate, commit, revision, transaction_id


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def checkpoint_contract_report() -> dict[str, Any]:
    from simulation_franchise_checkpoint_v1 import (
        DEFAULT_CHECKPOINT_PATH,
        load_franchise_checkpoint,
        save_franchise_checkpoint,
    )
    load_sig = inspect.signature(load_franchise_checkpoint)
    save_sig = inspect.signature(save_franchise_checkpoint)

    # The durable checkpoint contract is that callers may invoke the loader
    # with zero arguments. The implementation is allowed to expose optional
    # keyword-only parameters (for example an alternate path for tests).
    # Treat only *required* parameters as incompatible with the canonical
    # zero-argument API.
    load_required_parameters = [
        parameter
        for parameter in load_sig.parameters.values()
        if parameter.kind
        not in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }
        and parameter.default is inspect.Parameter.empty
    ]

    return {
        "checkpoint_path": str(DEFAULT_CHECKPOINT_PATH),
        "checkpoint_exists": Path(DEFAULT_CHECKPOINT_PATH).exists(),
        "load_is_zero_argument": not load_required_parameters,
        "load_parameters": list(load_sig.parameters),
        "load_required_parameters": [
            parameter.name for parameter in load_required_parameters
        ],
        "save_parameters": list(save_sig.parameters),
        "save_accepts_simulation_state": "simulation_state" in save_sig.parameters,
        "save_accepts_trade_state": "trade_state" in save_sig.parameters,
        "save_accepts_reason": "reason" in save_sig.parameters,
    }


def commit_free_agency_preview_durably(
    preview: FreeAgencyTransactionPreview,
    *,
    financial_gate: Callable[[Any, FreeAgencyOffer], Any],
    preferences: Mapping[str, Any] | None = None,
    state_validator: Callable[[Any], Any] | None = None,
    max_roster_size: int = 18,
    recovery_directory: str | Path | None = None,
) -> FreeAgencyDurableCommitResult:
    """Persist an already-approved signing with checkpoint recovery.

    The durable checkpoint is the source of truth. The caller cannot pass an
    alternate live state, preventing a stale Streamlit object from overwriting
    newer durable data.
    """
    from simulation_franchise_checkpoint_v1 import (
        DEFAULT_CHECKPOINT_PATH,
        load_franchise_checkpoint,
        save_franchise_checkpoint,
    )

    checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    if not checkpoint_path.exists():
        raise FreeAgencyDurableCommitError("Durable franchise checkpoint does not exist.")

    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise FreeAgencyDurableCommitError("Durable franchise checkpoint could not be loaded.")

    durable_state = checkpoint.simulation_state
    durable_fingerprint = free_agency_state_fingerprint(durable_state)
    if durable_fingerprint != preview.source_fingerprint:
        raise FreeAgencyDurableCommitError(
            "Approved free-agency preview is stale relative to the durable checkpoint."
        )

    candidate, commit, revision, transaction_id = build_free_agency_durable_candidate(
        durable_state,
        preview,
        financial_gate=financial_gate,
        state_validator=state_validator,
        max_roster_size=max_roster_size,
    )
    expected_fingerprint = free_agency_durable_state_fingerprint(candidate)

    checkpoint_hash_before = _sha256(checkpoint_path)
    recovery_root = Path(recovery_directory) if recovery_directory is not None else checkpoint_path.parent / "free_agency_recovery"
    recovery_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    recovery_path = recovery_root / f"pre_{transaction_id}_{stamp}_{checkpoint_path.name}"
    shutil.copy2(checkpoint_path, recovery_path)

    reason = f"free-agency-commit-{transaction_id}"
    try:
        saved = save_franchise_checkpoint(
            candidate,
            checkpoint.trade_state,
            preferences=copy.deepcopy(dict(preferences or checkpoint.preferences or {})),
            reason=reason,
            copy_payload=True,
        )
        reloaded = load_franchise_checkpoint()
        if reloaded is None:
            raise FreeAgencyDurableCommitError("Checkpoint reload returned no state after save.")
        observed_fingerprint = free_agency_durable_state_fingerprint(reloaded.simulation_state)
        if observed_fingerprint != expected_fingerprint:
            raise FreeAgencyDurableCommitError(
                "Reloaded checkpoint does not exactly match the approved signing candidate."
            )
        history = _history(reloaded.simulation_state)
        if not history or history[-1].get("transaction_id") != transaction_id:
            raise FreeAgencyDurableCommitError("Free-agency transaction history did not survive checkpoint reload.")
    except Exception:
        shutil.copy2(recovery_path, checkpoint_path)
        restored = load_franchise_checkpoint()
        if restored is None or free_agency_state_fingerprint(restored.simulation_state) != durable_fingerprint:
            raise FreeAgencyDurableCommitError(
                "Free-agency commit failed and automatic checkpoint recovery could not be verified."
            )
        raise

    checkpoint_hash_after = _sha256(checkpoint_path)
    return FreeAgencyDurableCommitResult(
        version=FREE_AGENCY_DURABLE_COMMIT_VERSION,
        transaction_id=transaction_id,
        offer_id=commit.offer_id,
        player_id=commit.player_id,
        player_name=commit.player_name,
        team_abbreviation=commit.team_abbreviation,
        free_agency_revision=revision,
        source_fingerprint=preview.source_fingerprint,
        committed_fingerprint=expected_fingerprint,
        checkpoint_hash_before=checkpoint_hash_before,
        checkpoint_hash_after=checkpoint_hash_after,
        checkpoint_saved_at_utc=_clean_text(getattr(saved, "saved_at_utc", "")),
        checkpoint_reason=reason,
        recovery_path=str(recovery_path),
    )


def build_cap_space_preview(
    state: Any,
    offer: FreeAgencyOffer,
    *,
    config: FreeAgencyCapSpaceGateConfig,
    state_validator: Callable[[Any], Any] | None = None,
    max_roster_size: int = 18,
) -> FreeAgencyTransactionPreview:
    return build_free_agency_preview(
        state,
        offer,
        financial_gate=cap_space_gate(config),
        state_validator=state_validator,
        max_roster_size=max_roster_size,
    )
