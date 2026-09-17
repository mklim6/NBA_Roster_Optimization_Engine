from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

RFA_QO_LIFECYCLE_VERSION = (
    "franchise-free-agency-rfa-qo-live-decision-v1-2026-08-16"
)
RFA_QO_LIFECYCLE_SCOPE = (
    "controlled-team-rfa-rights-and-qualifying-offer-decisions"
)

RFA_LEDGER_ATTR = "offseason_rfa_rights_qo_decisions_v1"
LIFECYCLE_HISTORY_ATTR = "offseason_rfa_qo_lifecycle_history_v1"

ACTION_ISSUE_QO = "issue_qo"
ACTION_WITHDRAW_QO = "withdraw_qo"
ACTION_RENOUNCE_RIGHTS = "renounce_rights"

VALID_ACTIONS = {
    ACTION_ISSUE_QO,
    ACTION_WITHDRAW_QO,
    ACTION_RENOUNCE_RIGHTS,
}

BAD_AUTHORITY_CALL = (
    "controlled_teams_from_durable_checkpoint(checkpoint, state)"
)

FINANCIAL_ATTR_PATTERN = re.compile(
    r"salary|financial|apron|tax|cap",
    re.IGNORECASE,
)


class RFAQOLifecycleError(RuntimeError):
    pass


@dataclass(frozen=True)
class RFAQODecisionPreview:
    version: str
    player_id: str
    player_name: str
    prior_team: str
    action: str
    rights_classification: str
    rights_decision_before: str
    rights_decision_after: str
    qo_decision_before: str
    qo_decision_after: str
    qo_amount: float | None
    free_agent_amount: float | None
    effective_charge_before: float
    effective_charge_after: float
    charge_delta: float
    controlled_teams: tuple[str, ...]
    confirmation_token: str
    projected_trade_revision_before: int
    projected_trade_revision_after: int


@dataclass(frozen=True)
class RFAQODecisionCommitResult:
    version: str
    transaction_id: str
    player_id: str
    player_name: str
    prior_team: str
    action: str
    rights_decision_before: str
    rights_decision_after: str
    qo_decision_before: str
    qo_decision_after: str
    effective_charge_before: float
    effective_charge_after: float
    charge_delta: float
    trade_revision_before: int
    trade_revision_after: int
    checkpoint_sha256_before: str
    checkpoint_sha256_after: str
    backup_sha256_before: str | None
    backup_sha256_after: str | None
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
    return _clean(getattr(phase, "value", phase))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ledger(state: Any) -> list[dict[str, Any]]:
    rows = list(getattr(state, RFA_LEDGER_ATTR, ()) or ())
    normalized = [
        dict(row)
        for row in rows
        if isinstance(row, Mapping)
    ]
    if len(normalized) != 64:
        raise RFAQOLifecycleError(
            f"Expected the verified 64-player RFA ledger, found {len(normalized)} rows."
        )
    ids = [_pid(row.get("player_id")) for row in normalized]
    if len(set(ids)) != 64 or any(not value for value in ids):
        raise RFAQOLifecycleError(
            "The RFA ledger does not contain 64 unique player IDs."
        )
    return normalized


def _row_for_player(state: Any, player_id: str) -> dict[str, Any]:
    target = _pid(player_id)
    matches = [
        row
        for row in _ledger(state)
        if _pid(row.get("player_id")) == target
    ]
    if len(matches) != 1:
        raise RFAQOLifecycleError(
            f"Expected exactly one RFA ledger row for {target!r}, found {len(matches)}."
        )
    return dict(matches[0])


def _free_agent_ids(state: Any) -> set[str]:
    return {
        _pid(value)
        for value in getattr(state, "free_agent_player_ids", ()) or ()
    }


def _controlled_teams(checkpoint: Any) -> tuple[str, ...]:
    from franchise_free_agency_live_signing_v1 import (
        controlled_teams_from_durable_checkpoint,
    )

    values = tuple(
        sorted(
            {
                _team(value)
                for value in controlled_teams_from_durable_checkpoint(checkpoint)
                if _team(value)
            }
        )
    )
    if not values:
        raise RFAQOLifecycleError(
            "The durable checkpoint exposes no user-controlled team."
        )
    return values


def _confirmation_token(
    *,
    player_id: str,
    action: str,
    team: str,
) -> str:
    return f"CONFIRM_RFAQO::{_pid(player_id)}::{action}::{_team(team)}"


def _effective_charge(
    row: Mapping[str, Any],
    *,
    rights_decision: str,
    qo_decision: str,
) -> float:
    if rights_decision == "renounce_rights":
        if qo_decision != "not_applicable_after_rights_renouncement":
            raise RFAQOLifecycleError(
                "A rights renouncement must make the Qualifying Offer inapplicable."
            )
        return 0.0

    if rights_decision != "retain_rights":
        raise RFAQOLifecycleError(
            f"Unsupported RFA rights decision: {rights_decision!r}"
        )

    free_agent_amount = _amount(row.get("free_agent_amount_2026_27"))
    if free_agent_amount is None or free_agent_amount <= 0:
        raise RFAQOLifecycleError(
            "A retained-rights RFA requires a positive verified Free Agent Amount."
        )

    if qo_decision == "do_not_issue_qo":
        return float(free_agent_amount)

    if qo_decision == "issue_qo":
        qo_amount = _amount(row.get("qo_amount_2026_27"))
        if qo_amount is None or qo_amount <= 0:
            raise RFAQOLifecycleError(
                "Issuing a Qualifying Offer requires a positive verified QO amount."
            )
        return float(max(free_agent_amount, qo_amount))

    raise RFAQOLifecycleError(
        f"Unsupported retained-rights QO decision: {qo_decision!r}"
    )


def _transition(
    row: Mapping[str, Any],
    action: str,
) -> tuple[str, str, float]:
    action = _clean(action).lower()
    if action not in VALID_ACTIONS:
        raise RFAQOLifecycleError(
            f"Unsupported RFA/QO action {action!r}."
        )

    rights_before = _clean(row.get("rights_decision"))
    qo_before = _clean(row.get("qo_decision"))

    if action == ACTION_WITHDRAW_QO:
        if rights_before != "retain_rights" or qo_before != "issue_qo":
            raise RFAQOLifecycleError(
                "A QO may be withdrawn only while rights are retained and the QO is currently issued."
            )
        rights_after = "retain_rights"
        qo_after = "do_not_issue_qo"

    elif action == ACTION_ISSUE_QO:
        if rights_before != "retain_rights":
            raise RFAQOLifecycleError(
                "A QO cannot be issued after the player's rights have been renounced."
            )
        if qo_before != "do_not_issue_qo":
            raise RFAQOLifecycleError(
                "The QO may be issued only from the retained-rights / no-QO state."
            )
        rights_after = "retain_rights"
        qo_after = "issue_qo"

    else:
        if rights_before != "retain_rights":
            raise RFAQOLifecycleError(
                "The player's rights are not currently retained."
            )
        rights_after = "renounce_rights"
        qo_after = "not_applicable_after_rights_renouncement"

    charge_after = _effective_charge(
        row,
        rights_decision=rights_after,
        qo_decision=qo_after,
    )
    return rights_after, qo_after, charge_after


def build_rfa_decision_board(
    state: Any,
    *,
    player_id: str | None = None,
    action: str | None = None,
) -> list[dict[str, Any]]:
    rows = _ledger(state)
    target = _pid(player_id) if player_id is not None else ""
    found = not target

    board: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        pid = _pid(row.get("player_id"))
        rights = _clean(row.get("rights_decision"))
        qo = _clean(row.get("qo_decision"))
        charge = float(_amount(row.get("effective_charge_2026_27")) or 0.0)

        if target and pid == target:
            found = True
            rights, qo, charge = _transition(row, _clean(action))

        board.append(
            {
                **row,
                "player_id": pid,
                "prior_team": _team(row.get("prior_team")),
                "executable_rights_decision": rights,
                "executable_qo_decision": qo,
                "effective_charge_if_recommended_branch": charge,
                "controlled_team_decision": bool(
                    row.get("controlled_team_decision")
                ),
            }
        )

    if not found:
        raise RFAQOLifecycleError(
            f"RFA player {target!r} is not present in the verified ledger."
        )
    return board


def _extract_projected_candidates(
    result: Any,
    source_simulation: Any,
    source_trade: Any,
) -> tuple[Any, Any]:
    candidates: list[Any] = []

    if isinstance(result, Mapping):
        candidates.extend(result.values())
    elif isinstance(result, (tuple, list)):
        candidates.extend(result)
    else:
        candidates.append(result)

    simulation_matches = [
        value
        for value in candidates
        if isinstance(value, type(source_simulation))
    ]
    trade_matches = [
        value
        for value in candidates
        if isinstance(value, type(source_trade))
    ]

    if len(simulation_matches) == 1 and len(trade_matches) == 1:
        return simulation_matches[0], trade_matches[0]

    if isinstance(result, Mapping):
        sim = (
            result.get("simulation_candidate")
            or result.get("simulation_state")
            or result.get("simulation")
        )
        trade = (
            result.get("trade_candidate")
            or result.get("trade_state")
            or result.get("trade")
        )
        if sim is not None and trade is not None:
            return sim, trade

    raise RFAQOLifecycleError(
        "Could not extract projected simulation/trade candidates from the "
        "verified historical RFA application engine."
    )


def _project_board(
    state: Any,
    trade_state: Any,
    board: list[dict[str, Any]],
) -> tuple[Any, Any]:
    from fa_rfa_rights_qo_recommended_branch_clone_apply_v1 import (
        apply_rfa_board,
    )

    result = apply_rfa_board(
        state,
        trade_state,
        board,
    )
    return _extract_projected_candidates(
        result,
        state,
        trade_state,
    )


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _apply_numeric_delta(
    target: Any,
    projected_before: Any,
    projected_after: Any,
) -> Any:
    if (
        _is_number(target)
        and _is_number(projected_before)
        and _is_number(projected_after)
    ):
        return type(target)(
            target
            + (projected_after - projected_before)
        )

    if (
        isinstance(target, dict)
        and isinstance(projected_before, Mapping)
        and isinstance(projected_after, Mapping)
    ):
        output = copy.deepcopy(target)
        for key in set(projected_before).intersection(projected_after):
            if key not in output:
                continue
            output[key] = _apply_numeric_delta(
                output[key],
                projected_before[key],
                projected_after[key],
            )
        return output

    if (
        hasattr(target, "__dict__")
        and hasattr(projected_before, "__dict__")
        and hasattr(projected_after, "__dict__")
    ):
        output = copy.deepcopy(target)
        for name, value in vars(output).items():
            if (
                hasattr(projected_before, name)
                and hasattr(projected_after, name)
            ):
                setattr(
                    output,
                    name,
                    _apply_numeric_delta(
                        value,
                        getattr(projected_before, name),
                        getattr(projected_after, name),
                    ),
                )
        return output

    return copy.deepcopy(target)


def _changed_numeric_paths(
    before: Any,
    after: Any,
    *,
    prefix: str = "",
    depth: int = 0,
) -> list[tuple[str, float, float]]:
    if depth > 5:
        return []

    if _is_number(before) and _is_number(after):
        if float(before) != float(after):
            return [
                (
                    prefix,
                    float(before),
                    float(after),
                )
            ]
        return []

    if isinstance(before, Mapping) and isinstance(after, Mapping):
        rows: list[tuple[str, float, float]] = []
        for key in set(before).intersection(after):
            rows.extend(
                _changed_numeric_paths(
                    before[key],
                    after[key],
                    prefix=(
                        f"{prefix}.{key}"
                        if prefix
                        else str(key)
                    ),
                    depth=depth + 1,
                )
            )
        return rows

    if hasattr(before, "__dict__") and hasattr(after, "__dict__"):
        rows = []
        for name in set(vars(before)).intersection(vars(after)):
            rows.extend(
                _changed_numeric_paths(
                    getattr(before, name),
                    getattr(after, name),
                    prefix=(
                        f"{prefix}.{name}"
                        if prefix
                        else name
                    ),
                    depth=depth + 1,
                )
            )
        return rows

    return []


def _financial_surface_names(
    source: Any,
    projected_before: Any,
    projected_after: Any,
) -> tuple[str, ...]:
    names = []
    for name in set(vars(projected_before)).intersection(vars(projected_after)):
        if not hasattr(source, name):
            continue
        if name in {
            RFA_LEDGER_ATTR,
            LIFECYCLE_HISTORY_ATTR,
            "transaction_history",
        }:
            continue
        if FINANCIAL_ATTR_PATTERN.search(name):
            if _changed_numeric_paths(
                getattr(projected_before, name),
                getattr(projected_after, name),
                prefix=name,
            ):
                names.append(name)
    return tuple(sorted(names))


def _market_attr_name(projected: Any) -> str | None:
    from fa_rfa_rights_qo_recommended_branch_clone_apply_v1 import (
        MARKET_AMOUNT_ATTR,
    )

    name = _clean(MARKET_AMOUNT_ATTR)
    if name and hasattr(projected, name):
        return name
    return None


def _projected_action_candidates(
    state: Any,
    trade_state: Any,
    *,
    player_id: str,
    action: str,
) -> tuple[Any, Any, dict[str, Any]]:
    base_board = build_rfa_decision_board(state)
    action_board = build_rfa_decision_board(
        state,
        player_id=player_id,
        action=action,
    )

    base_sim, base_trade = _project_board(
        state,
        trade_state,
        base_board,
    )
    action_sim, action_trade = _project_board(
        state,
        trade_state,
        action_board,
    )

    simulation_candidate = copy.deepcopy(state)
    trade_candidate = copy.deepcopy(trade_state)

    # The historical application engine is authoritative for how a decision
    # changes cap/accounting surfaces. We use only the DIFFERENCE between its
    # unchanged-board and action-board projections, so its old clone event or
    # baseline assumptions can never be re-applied to the live source state.
    sim_financial_names = _financial_surface_names(
        state,
        base_sim,
        action_sim,
    )
    trade_financial_names = _financial_surface_names(
        trade_state,
        base_trade,
        action_trade,
    )

    for name in sim_financial_names:
        setattr(
            simulation_candidate,
            name,
            _apply_numeric_delta(
                getattr(simulation_candidate, name),
                getattr(base_sim, name),
                getattr(action_sim, name),
            ),
        )

    for name in trade_financial_names:
        setattr(
            trade_candidate,
            name,
            _apply_numeric_delta(
                getattr(trade_candidate, name),
                getattr(base_trade, name),
                getattr(action_trade, name),
            ),
        )

    # These two decision surfaces are safe to replace from the action
    # projection because they are complete deterministic ledgers, not history.
    setattr(
        simulation_candidate,
        RFA_LEDGER_ATTR,
        copy.deepcopy(
            getattr(action_sim, RFA_LEDGER_ATTR)
        ),
    )
    setattr(
        trade_candidate,
        RFA_LEDGER_ATTR,
        copy.deepcopy(
            getattr(action_trade, RFA_LEDGER_ATTR)
        ),
    )

    market_attr = _market_attr_name(action_sim)
    if market_attr:
        setattr(
            simulation_candidate,
            market_attr,
            copy.deepcopy(
                getattr(action_sim, market_attr)
            ),
        )
        if hasattr(action_trade, market_attr):
            setattr(
                trade_candidate,
                market_attr,
                copy.deepcopy(
                    getattr(action_trade, market_attr)
                ),
            )

    metadata = {
        "simulation_financial_surfaces": sim_financial_names,
        "trade_financial_surfaces": trade_financial_names,
        "market_attr": market_attr,
    }
    return simulation_candidate, trade_candidate, metadata


def _team_salary(trade_state: Any, team: str) -> float:
    financials = getattr(trade_state, "team_financials", None)
    if not isinstance(financials, Mapping):
        raise RFAQOLifecycleError(
            "TradeState does not expose the required team_financials mapping."
        )
    financial = financials.get(_team(team))
    if financial is None:
        raise RFAQOLifecycleError(
            f"TradeState has no financial state for {_team(team)}."
        )
    salary = _amount(getattr(financial, "team_salary", None))
    if salary is None:
        raise RFAQOLifecycleError(
            f"TradeState team_salary is unavailable for {_team(team)}."
        )
    return float(salary)


def _decision_fingerprint(
    state: Any,
    trade_state: Any,
) -> str:
    financial_payload = {}
    financials = getattr(trade_state, "team_financials", {})
    if isinstance(financials, Mapping):
        for team in sorted(financials):
            value = financials[team]
            if hasattr(value, "__dict__"):
                financial_payload[_team(team)] = {
                    key: val
                    for key, val in sorted(vars(value).items())
                    if _is_number(val) or isinstance(val, (str, bool, type(None)))
                }
            else:
                financial_payload[_team(team)] = repr(value)

    payload = {
        "rfa_ledger": _ledger(state),
        "simulation_history": list(
            getattr(state, LIFECYCLE_HISTORY_ATTR, ()) or ()
        ),
        "trade_history": list(
            getattr(trade_state, LIFECYCLE_HISTORY_ATTR, ()) or ()
        ),
        "trade_revision": int(
            getattr(trade_state, "state_revision", -1)
        ),
        "source_trade_revision": int(
            getattr(state, "source_league_state_revision", -1)
        ),
        "source_transaction_count": int(
            getattr(state, "source_transaction_count", -1)
        ),
        "financials": financial_payload,
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def preview_controlled_rfa_action(
    checkpoint: Any,
    *,
    player_id: str,
    action: str,
) -> RFAQODecisionPreview:
    state = checkpoint.simulation_state
    trade_state = checkpoint.trade_state
    if state is None or trade_state is None:
        raise RFAQOLifecycleError(
            "The durable checkpoint requires both simulation and trade state."
        )
    if _phase(state) != "offseason":
        raise RFAQOLifecycleError(
            "RFA/QO decisions are available only during the offseason."
        )

    pid = _pid(player_id)
    if pid not in _free_agent_ids(state):
        raise RFAQOLifecycleError(
            "The RFA player is no longer in the current free-agent market."
        )

    row = _row_for_player(state, pid)
    team = _team(row.get("prior_team"))
    controlled = _controlled_teams(checkpoint)
    if team not in set(controlled):
        raise RFAQOLifecycleError(
            "Only a user-controlled prior team may make this rights/QO decision."
        )

    rights_before = _clean(row.get("rights_decision"))
    qo_before = _clean(row.get("qo_decision"))
    charge_before = float(
        _amount(row.get("effective_charge_2026_27")) or 0.0
    )
    rights_after, qo_after, charge_after = _transition(
        row,
        _clean(action),
    )

    revision_before = int(
        getattr(trade_state, "state_revision", -1)
    )
    if revision_before < 0:
        raise RFAQOLifecycleError(
            "TradeState revision is unavailable."
        )

    return RFAQODecisionPreview(
        version=RFA_QO_LIFECYCLE_VERSION,
        player_id=pid,
        player_name=_clean(row.get("player_name")),
        prior_team=team,
        action=_clean(action).lower(),
        rights_classification=_clean(row.get("rights_classification")),
        rights_decision_before=rights_before,
        rights_decision_after=rights_after,
        qo_decision_before=qo_before,
        qo_decision_after=qo_after,
        qo_amount=_amount(row.get("qo_amount_2026_27")),
        free_agent_amount=_amount(row.get("free_agent_amount_2026_27")),
        effective_charge_before=charge_before,
        effective_charge_after=float(charge_after),
        charge_delta=float(charge_after - charge_before),
        controlled_teams=controlled,
        confirmation_token=_confirmation_token(
            player_id=pid,
            action=_clean(action).lower(),
            team=team,
        ),
        projected_trade_revision_before=revision_before,
        projected_trade_revision_after=revision_before + 1,
    )


def build_controlled_rfa_action_candidate(
    checkpoint: Any,
    *,
    player_id: str,
    action: str,
) -> tuple[Any, Any, RFAQODecisionPreview, dict[str, Any]]:
    preview = preview_controlled_rfa_action(
        checkpoint,
        player_id=player_id,
        action=action,
    )
    source_sim = checkpoint.simulation_state
    source_trade = checkpoint.trade_state

    sim_candidate, trade_candidate, projection_meta = (
        _projected_action_candidates(
            source_sim,
            source_trade,
            player_id=preview.player_id,
            action=preview.action,
        )
    )

    row_after = _row_for_player(
        sim_candidate,
        preview.player_id,
    )
    if _clean(row_after.get("rights_decision")) != preview.rights_decision_after:
        raise RFAQOLifecycleError(
            "Projected RFA rights decision does not match the approved transition."
        )
    if _clean(row_after.get("qo_decision")) != preview.qo_decision_after:
        raise RFAQOLifecycleError(
            "Projected QO decision does not match the approved transition."
        )
    observed_charge = float(
        _amount(row_after.get("effective_charge_2026_27")) or 0.0
    )
    if abs(observed_charge - preview.effective_charge_after) > 0.01:
        raise RFAQOLifecycleError(
            "Projected effective charge does not match the approved transition."
        )

    before_salary = _team_salary(
        source_trade,
        preview.prior_team,
    )
    after_salary = _team_salary(
        trade_candidate,
        preview.prior_team,
    )
    observed_salary_delta = after_salary - before_salary
    if abs(observed_salary_delta - preview.charge_delta) > 0.01:
        raise RFAQOLifecycleError(
            "Historical RFA financial projection does not reproduce the exact "
            f"expected team-salary delta. Expected {preview.charge_delta}, "
            f"observed {observed_salary_delta}."
        )

    history = list(
        getattr(sim_candidate, LIFECYCLE_HISTORY_ATTR, ()) or ()
    )
    transaction_id = f"RFAQO-{len(history) + 1:04d}"
    event = {
        "transaction_id": transaction_id,
        "version": RFA_QO_LIFECYCLE_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "player_id": preview.player_id,
        "player_name": preview.player_name,
        "prior_team": preview.prior_team,
        "action": preview.action,
        "rights_decision_before": preview.rights_decision_before,
        "rights_decision_after": preview.rights_decision_after,
        "qo_decision_before": preview.qo_decision_before,
        "qo_decision_after": preview.qo_decision_after,
        "effective_charge_before": preview.effective_charge_before,
        "effective_charge_after": preview.effective_charge_after,
        "charge_delta": preview.charge_delta,
    }
    history.append(event)
    setattr(
        sim_candidate,
        LIFECYCLE_HISTORY_ATTR,
        copy.deepcopy(history),
    )
    setattr(
        trade_candidate,
        LIFECYCLE_HISTORY_ATTR,
        copy.deepcopy(history),
    )

    revision_before = int(
        getattr(source_trade, "state_revision", -1)
    )
    revision_after = revision_before + 1
    setattr(
        trade_candidate,
        "state_revision",
        revision_after,
    )
    if hasattr(sim_candidate, "source_league_state_revision"):
        setattr(
            sim_candidate,
            "source_league_state_revision",
            revision_after,
        )
    if hasattr(sim_candidate, "source_transaction_count"):
        # Rights/QO decisions are financial/free-agency lifecycle events, not
        # Trade Machine transactions.
        setattr(
            sim_candidate,
            "source_transaction_count",
            int(
                getattr(source_sim, "source_transaction_count", 0)
            ),
        )

    projection_meta = {
        **projection_meta,
        "transaction_id": transaction_id,
        "team_salary_before": before_salary,
        "team_salary_after": after_salary,
        "team_salary_delta": observed_salary_delta,
    }

    return sim_candidate, trade_candidate, preview, projection_meta


def _checkpoint_backup_path(
    checkpoint_module: Any,
    checkpoint_path: Path,
) -> Path | None:
    helper = getattr(
        checkpoint_module,
        "checkpoint_backup_path",
        None,
    )
    if callable(helper):
        try:
            return Path(helper(checkpoint_path))
        except TypeError:
            return Path(helper())
    return None


def commit_controlled_rfa_action_live(
    *,
    player_id: str,
    action: str,
    confirmation_token: str,
    recovery_directory: str | Path | None = None,
) -> RFAQODecisionCommitResult:
    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(
        checkpoint_module.DEFAULT_CHECKPOINT_PATH
    )
    if not checkpoint_path.exists():
        raise RFAQOLifecycleError(
            "The durable franchise checkpoint does not exist."
        )

    checkpoint = checkpoint_module.load_franchise_checkpoint()
    if checkpoint is None:
        raise RFAQOLifecycleError(
            "The durable franchise checkpoint could not be loaded."
        )

    sim_candidate, trade_candidate, preview, meta = (
        build_controlled_rfa_action_candidate(
            checkpoint,
            player_id=player_id,
            action=action,
        )
    )

    if _clean(confirmation_token) != preview.confirmation_token:
        raise RFAQOLifecycleError(
            "The explicit RFA/QO confirmation token does not match the "
            "current player, action, and controlled team."
        )

    source_fingerprint = _decision_fingerprint(
        checkpoint.simulation_state,
        checkpoint.trade_state,
    )
    candidate_fingerprint = _decision_fingerprint(
        sim_candidate,
        trade_candidate,
    )

    checkpoint_hash_before = _sha256(checkpoint_path)
    backup_path = _checkpoint_backup_path(
        checkpoint_module,
        checkpoint_path,
    )
    backup_hash_before = (
        _sha256(backup_path)
        if backup_path is not None and backup_path.exists()
        else None
    )

    root = (
        Path(recovery_directory)
        if recovery_directory is not None
        else checkpoint_path.parent / "rfa_qo_recovery"
    )
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    transaction_id = str(meta["transaction_id"])
    recovery_primary = (
        root
        / f"pre_{transaction_id}_{stamp}_{checkpoint_path.name}"
    )
    shutil.copy2(
        checkpoint_path,
        recovery_primary,
    )

    recovery_backup: Path | None = None
    if backup_path is not None and backup_path.exists():
        recovery_backup = (
            root
            / f"pre_{transaction_id}_{stamp}_{backup_path.name}"
        )
        shutil.copy2(
            backup_path,
            recovery_backup,
        )

    try:
        checkpoint_module.save_franchise_checkpoint(
            sim_candidate,
            trade_candidate,
            preferences=copy.deepcopy(
                dict(getattr(checkpoint, "preferences", {}) or {})
            ),
            reason=f"rfa-qo-live-{transaction_id}",
            copy_payload=True,
        )
        reloaded = checkpoint_module.load_franchise_checkpoint()
        if reloaded is None:
            raise RFAQOLifecycleError(
                "Checkpoint reload returned no state after the RFA/QO decision."
            )

        observed_fingerprint = _decision_fingerprint(
            reloaded.simulation_state,
            reloaded.trade_state,
        )
        if observed_fingerprint != candidate_fingerprint:
            raise RFAQOLifecycleError(
                "Reloaded RFA/QO state does not exactly match the approved candidate."
            )

        observed_row = _row_for_player(
            reloaded.simulation_state,
            preview.player_id,
        )
        if (
            _clean(observed_row.get("rights_decision"))
            != preview.rights_decision_after
            or _clean(observed_row.get("qo_decision"))
            != preview.qo_decision_after
        ):
            raise RFAQOLifecycleError(
                "Reloaded rights/QO decision did not survive the durable write."
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
            raise RFAQOLifecycleError(
                "RFA/QO commit failed and the restored checkpoint could not be loaded."
            ) from exc
        restored_fingerprint = _decision_fingerprint(
            restored.simulation_state,
            restored.trade_state,
        )
        if restored_fingerprint != source_fingerprint:
            raise RFAQOLifecycleError(
                "RFA/QO commit failed and exact automatic recovery could not be verified."
            ) from exc
        if _sha256(checkpoint_path) != checkpoint_hash_before:
            raise RFAQOLifecycleError(
                "RFA/QO commit failed and the primary checkpoint bytes were not restored exactly."
            ) from exc
        if (
            backup_hash_before is not None
            and backup_path is not None
            and _sha256(backup_path) != backup_hash_before
        ):
            raise RFAQOLifecycleError(
                "RFA/QO commit failed and the automatic-backup bytes were not restored exactly."
            ) from exc
        raise RFAQOLifecycleError(
            f"RFA/QO decision failed. Exact pre-decision state was restored: {exc}"
        ) from exc

    checkpoint_hash_after = _sha256(checkpoint_path)
    backup_hash_after = (
        _sha256(backup_path)
        if backup_path is not None and backup_path.exists()
        else None
    )

    return RFAQODecisionCommitResult(
        version=RFA_QO_LIFECYCLE_VERSION,
        transaction_id=transaction_id,
        player_id=preview.player_id,
        player_name=preview.player_name,
        prior_team=preview.prior_team,
        action=preview.action,
        rights_decision_before=preview.rights_decision_before,
        rights_decision_after=preview.rights_decision_after,
        qo_decision_before=preview.qo_decision_before,
        qo_decision_after=preview.qo_decision_after,
        effective_charge_before=preview.effective_charge_before,
        effective_charge_after=preview.effective_charge_after,
        charge_delta=preview.charge_delta,
        trade_revision_before=preview.projected_trade_revision_before,
        trade_revision_after=preview.projected_trade_revision_after,
        checkpoint_sha256_before=checkpoint_hash_before,
        checkpoint_sha256_after=checkpoint_hash_after,
        backup_sha256_before=backup_hash_before,
        backup_sha256_after=backup_hash_after,
        recovery_primary_path=str(recovery_primary),
        recovery_backup_path=(
            str(recovery_backup)
            if recovery_backup is not None
            else None
        ),
    )


def rfa_market_metadata(
    state: Any,
) -> dict[str, dict[str, Any]]:
    """Return the verified anchor-market RFA overlay when applicable.

    The 64-row rights/QO board is a certified 2026-27 historical surface.
    Modeled future offseason markets must not reuse that stale board.
    """
    raw_rows = list(getattr(state, RFA_LEDGER_ATTR, ()) or ())
    if not raw_rows:
        # Regular-season checkpoints intentionally clear the offseason rights
        # boards when the new season opens.  The standalone Free Agency page is
        # still available as a market/roster reference during that phase, so an
        # absent board means "no active RFA overlay" rather than corrupt state.
        # Keep the strict 64-row assertion for the anchor offseason, where the
        # certified historical board is required for rights/QO actions.
        if _phase(state).lower() != "offseason":
            return {}

        from franchise_offseason_market_season_v1 import (
            modeled_future_market_enabled,
        )

        if modeled_future_market_enabled(state):
            return {}

    result = {}
    for row in _ledger(state):
        pid = _pid(row.get("player_id"))
        result[pid] = {
            "restricted_free_agent": True,
            "prior_team": _team(row.get("prior_team")),
            "rights_classification": _clean(row.get("rights_classification")),
            "rights_decision": _clean(row.get("rights_decision")),
            "qo_decision": _clean(row.get("qo_decision")),
            "qo_amount_2026_27": _amount(row.get("qo_amount_2026_27")),
            "free_agent_amount_2026_27": _amount(
                row.get("free_agent_amount_2026_27")
            ),
            "effective_charge_2026_27": float(
                _amount(row.get("effective_charge_2026_27")) or 0.0
            ),
            "controlled_team_decision": bool(
                row.get("controlled_team_decision")
            ),
        }
    return result


def rfa_qo_lifecycle_contract_report() -> dict[str, Any]:
    return {
        "version": RFA_QO_LIFECYCLE_VERSION,
        "scope": RFA_QO_LIFECYCLE_SCOPE,
        "actions": tuple(sorted(VALID_ACTIONS)),
        "ledger_attribute": RFA_LEDGER_ATTR,
        "history_attribute": LIFECYCLE_HISTORY_ATTR,
        "uses_verified_historical_financial_projection_differential": True,
        "requires_explicit_confirmation_token": True,
        "atomic_primary_and_backup_recovery": True,
        "offer_sheet_lifecycle_in_scope": False,
        "next_layer": "offer-sheet-match-decline-state-machine",
    }
