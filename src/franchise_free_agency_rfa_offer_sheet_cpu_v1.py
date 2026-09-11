from __future__ import annotations

import copy
import hashlib
import json
import math
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Mapping

from franchise_cpu_front_office_v1 import build_league_front_office_plan
from franchise_free_agency_cpu_offer_generation_v1 import build_cpu_free_agency_offer_board
from franchise_free_agency_live_signing_v1 import controlled_teams_from_durable_checkpoint
from franchise_free_agency_persistent_calendar_v1 import (
    FREE_AGENCY_CALENDAR_ATTR,
    FREE_AGENCY_PERSISTENT_CALENDAR_VERSION,
    FreeAgencyCalendarWriteResult,
    advance_free_agency_day_candidate,
    free_agency_calendar_snapshot,
    persistent_calendar_fingerprint,
)
from franchise_free_agency_rfa_offer_sheet_v1 import (
    DECISION_DECLINE,
    DECISION_MATCH,
    _offer_sheet_fingerprint,
    build_offer_sheet_resolution_candidate,
    pending_offer_sheets,
)

CPU_RFA_MATCH_VERSION = "franchise-free-agency-rfa-offer-sheet-cpu-match-v1-2026-08-17"
CPU_RFA_MATCH_SCOPE = "cpu-original-team-match-intelligence-and-atomic-deadline-resolution"
CPU_DECISION_MATCH = "match"
CPU_DECISION_WAIT = "wait"
CPU_DECISION_DELAY_DAYS = 1


class RFAOfferSheetCPUError(RuntimeError):
    pass


@dataclass(frozen=True)
class CPUOfferSheetMatchDecision:
    version: str
    offer_sheet_id: str
    player_id: str
    player_name: str
    prior_team: str
    offering_team: str
    decision: str
    evaluated_day: int
    created_day: int
    deadline_day: int
    offer_salary: float
    generated_offer_found: bool
    generated_offer_salary: float | None
    generated_offer_maximum: float | None
    target_fit_score: float | None
    team_direction: str
    salary_posture: str
    match_budget: float | None
    reason: str
    fingerprint: str


@dataclass(frozen=True)
class RFAOfferSheetDayAdvanceResult:
    version: str
    prior_day: int
    current_day: int
    markets_advanced: int
    markets_held: int
    markets_ready_user: int
    markets_ready_cpu: int
    markets_closed: int
    write_result: FreeAgencyCalendarWriteResult
    cpu_offer_sheets_evaluated: int
    cpu_offer_sheets_matched: int
    expired_offer_sheets_declined: int
    offer_sheets_resolved: int
    resolved_offer_sheet_ids: tuple[str, ...]
    resolution_summaries: tuple[str, ...]

    @property
    def resolution_notice(self) -> str:
        return " · ".join(self.resolution_summaries)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _pid(value: Any) -> str:
    text = _clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _sha256(path: Path) -> str:
    d = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            d.update(block)
    return d.hexdigest()


def _fp(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _direction_premium(direction: str) -> float:
    text = _clean(direction).casefold()
    if "championship" in text or "title" in text:
        return 0.14
    if "contend" in text or "win now" in text or "win-now" in text:
        return 0.11
    if "retool" in text:
        return 0.08
    if "develop" in text:
        return 0.05
    if "rebuild" in text:
        return 0.02
    return 0.07


def _posture_adjustment(posture: str) -> float:
    text = _clean(posture).casefold()
    if "high salary pressure" in text:
        return -0.05
    if "pressure" in text or "limited" in text:
        return -0.03
    if "flexible" in text:
        return 0.02
    return 0.0


def _offer_row(board: Any, team: str, player_id: str) -> Any | None:
    rows = [
        row for row in getattr(board, "offers", ()) or ()
        if _team(getattr(row, "team_abbreviation", "")) == _team(team)
        and _pid(getattr(row, "player_id", "")) == _pid(player_id)
    ]
    if not rows:
        return None
    rows.sort(key=lambda row: (-_finite(getattr(row, "target_fit_score", 0.0)), -_finite(getattr(row, "annual_salary", 0.0)), _clean(getattr(row, "offer_fingerprint", ""))))
    return rows[0]


def evaluate_cpu_offer_sheet_match(
    state: Any,
    trade_state: Any,
    record: Mapping[str, Any],
    *,
    controlled_teams: Iterable[str] = (),
    front_office_plan: Any | None = None,
    cpu_offer_board: Any | None = None,
) -> CPUOfferSheetMatchDecision:
    prior = _team(record.get("prior_team"))
    offering = _team(record.get("offering_team"))
    player_id = _pid(record.get("player_id"))
    sheet_id = _clean(record.get("offer_sheet_id"))
    player_name = _clean(record.get("player_name")) or player_id
    controlled = {_team(v) for v in controlled_teams if _team(v)}
    if prior in controlled:
        raise RFAOfferSheetCPUError("CPU authority cannot decide a user-controlled original team's RFA response.")

    snap = free_agency_calendar_snapshot(state)
    if not snap.initialized:
        raise RFAOfferSheetCPUError("CPU RFA match intelligence requires the Free Agency calendar.")
    current_day = int(snap.offseason_day)
    created_day = int(record.get("created_day") or 0)
    deadline_day = int(record.get("match_deadline_day") or 0)
    salary = _finite(record.get("annual_salary"), 0.0)

    if current_day <= created_day:
        reason = "The CPU original team receives at least one explicit Free Agency day before evaluating the sheet."
        return CPUOfferSheetMatchDecision(
            CPU_RFA_MATCH_VERSION, sheet_id, player_id, player_name, prior, offering,
            CPU_DECISION_WAIT, current_day, created_day, deadline_day, salary,
            False, None, None, None, "", "", None, reason,
            _fp({"sheet": sheet_id, "day": current_day, "decision": "wait", "reason": reason}),
        )

    plan = front_office_plan or build_league_front_office_plan(state, controlled_teams=tuple(sorted(controlled)))
    board = cpu_offer_board or build_cpu_free_agency_offer_board(
        state,
        controlled_teams=tuple(sorted(controlled)),
        front_office_plan=plan,
        max_targets_per_team=6,
    )
    row = _offer_row(board, prior, player_id)
    if row is None:
        reason = "The original team does not target this player through the existing CPU free-agent board, so it waits rather than inventing a match valuation."
        return CPUOfferSheetMatchDecision(
            CPU_RFA_MATCH_VERSION, sheet_id, player_id, player_name, prior, offering,
            CPU_DECISION_WAIT, current_day, created_day, deadline_day, salary,
            False, None, None, None, "", "", None, reason,
            _fp({"sheet": sheet_id, "team": prior, "player": player_id, "day": current_day, "decision": "wait", "generated": None}),
        )

    generated = _finite(getattr(row, "annual_salary", 0.0), 0.0)
    maximum = _finite(getattr(row, "maximum_initial_salary", generated), generated)
    fit = _finite(getattr(row, "target_fit_score", 0.0), 0.0)
    direction = _clean(getattr(row, "team_direction", ""))
    posture = _clean(getattr(row, "salary_posture", ""))
    fit_premium = min(0.10, max(0.0, fit - 60.0) * 0.0025)
    multiplier = max(1.0, 1.0 + _direction_premium(direction) + fit_premium + _posture_adjustment(posture))
    minimum_dollars = 500_000.0 if generated < 10_000_000.0 else 1_000_000.0
    budget = min(maximum, max(generated * multiplier, generated + minimum_dollars))
    match = maximum + 0.01 >= salary and fit >= 45.0 and salary <= budget + 0.01
    decision = CPU_DECISION_MATCH if match else CPU_DECISION_WAIT
    if match:
        reason = f"{prior}'s existing CPU plan values the player at fit {fit:.1f} and supports a ${budget:,.0f} match budget, covering the ${salary:,.0f} sheet."
    elif fit < 45.0:
        reason = f"The CPU target fit ({fit:.1f}) is below the match threshold, so {prior} preserves flexibility."
    elif maximum + 0.01 < salary:
        reason = "The verified CPU financial/rights route does not support the sheet salary inside its current maximum initial-salary boundary."
    else:
        reason = f"The ${salary:,.0f} sheet exceeds {prior}'s existing strategic match budget of ${budget:,.0f}; the CPU waits rather than inventing a higher valuation."
    payload = {
        "version": CPU_RFA_MATCH_VERSION,
        "sheet": sheet_id,
        "team": prior,
        "player": player_id,
        "day": current_day,
        "decision": decision,
        "sheet_salary": round(salary, 2),
        "generated_salary": round(generated, 2),
        "maximum": round(maximum, 2),
        "fit": round(fit, 4),
        "direction": direction,
        "posture": posture,
        "budget": round(budget, 2),
    }
    return CPUOfferSheetMatchDecision(
        CPU_RFA_MATCH_VERSION, sheet_id, player_id, player_name, prior, offering,
        decision, current_day, created_day, deadline_day, salary,
        True, generated, maximum, fit, direction, posture, budget, reason, _fp(payload),
    )


def _combined_fingerprint(simulation_state: Any, trade_state: Any) -> str:
    return _fp({
        "calendar": persistent_calendar_fingerprint(simulation_state),
        "offer_sheet": _offer_sheet_fingerprint(simulation_state, trade_state),
    })


def _backup_path(cp: Any, checkpoint_path: Path) -> Path | None:
    helper = getattr(cp, "checkpoint_backup_path", None)
    if not callable(helper):
        return None
    try:
        return Path(helper(checkpoint_path))
    except TypeError:
        return Path(helper())


def _annotate_day_history(state: Any, *, evaluated: int, matched: int, expired: int, resolved: int) -> None:
    payload = copy.deepcopy(dict(getattr(state, FREE_AGENCY_CALENDAR_ATTR, {}) or {}))
    history = list(payload.get("day_history", []) or [])
    if history:
        row = copy.deepcopy(dict(history[-1]))
        row.update({
            "rfa_offer_sheets_cpu_evaluated": int(evaluated),
            "rfa_offer_sheets_cpu_matched": int(matched),
            "rfa_offer_sheets_expired_declined": int(expired),
            "rfa_offer_sheets_resolved": int(resolved),
        })
        history[-1] = row
        payload["day_history"] = history
        setattr(state, FREE_AGENCY_CALENDAR_ATTR, payload)


def _atomic_save(cp: Any, checkpoint: Any, sim_candidate: Any, trade_candidate: Any, *, current_day: int, recovery_directory: str | Path | None) -> FreeAgencyCalendarWriteResult:
    checkpoint_path = Path(cp.DEFAULT_CHECKPOINT_PATH)
    backup_path = _backup_path(cp, checkpoint_path)
    primary_hash = _sha256(checkpoint_path)
    backup_hash = _sha256(backup_path) if backup_path is not None and backup_path.exists() else None
    source_fp = _combined_fingerprint(checkpoint.simulation_state, checkpoint.trade_state)
    expected_fp = _combined_fingerprint(sim_candidate, trade_candidate)
    root = Path(recovery_directory) if recovery_directory is not None else checkpoint_path.parent / "rfa_offer_sheet_day_recovery"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    rec_primary = root / f"pre_RFAOSDAY_{current_day:02d}_{stamp}_{checkpoint_path.name}"
    shutil.copy2(checkpoint_path, rec_primary)
    rec_backup = None
    if backup_path is not None and backup_path.exists():
        rec_backup = root / f"pre_RFAOSDAY_{current_day:02d}_{stamp}_{backup_path.name}"
        shutil.copy2(backup_path, rec_backup)
    reason = f"free-agency-day-{current_day}-with-rfa-offer-sheet-resolution"
    try:
        cp.save_franchise_checkpoint(
            sim_candidate,
            trade_candidate,
            preferences=copy.deepcopy(dict(getattr(checkpoint, "preferences", {}) or {})),
            reason=reason,
            copy_payload=True,
        )
        reloaded = cp.load_franchise_checkpoint()
        if reloaded is None:
            raise RFAOfferSheetCPUError("Checkpoint reload returned no state after the combined Free Agency day advance.")
        if _combined_fingerprint(reloaded.simulation_state, reloaded.trade_state) != expected_fp:
            raise RFAOfferSheetCPUError("Reloaded calendar/offer-sheet state does not match the approved combined candidate.")
    except Exception as exc:
        shutil.copy2(rec_primary, checkpoint_path)
        if backup_path is not None and rec_backup is not None and rec_backup.exists():
            shutil.copy2(rec_backup, backup_path)
        restored = cp.load_franchise_checkpoint()
        if restored is None or _combined_fingerprint(restored.simulation_state, restored.trade_state) != source_fp:
            raise RFAOfferSheetCPUError("Combined day advance failed and exact automatic recovery could not be verified.") from exc
        if _sha256(checkpoint_path) != primary_hash:
            raise RFAOfferSheetCPUError("Combined day advance recovery did not restore exact primary checkpoint bytes.") from exc
        if backup_hash is not None and backup_path is not None and _sha256(backup_path) != backup_hash:
            raise RFAOfferSheetCPUError("Combined day advance recovery did not restore exact automatic-backup bytes.") from exc
        raise RFAOfferSheetCPUError(f"Combined Free Agency day advance failed. Exact pre-advance state was restored: {exc}") from exc

    snap = free_agency_calendar_snapshot(sim_candidate)
    return FreeAgencyCalendarWriteResult(
        version=FREE_AGENCY_PERSISTENT_CALENDAR_VERSION,
        action=f"advance-day-{current_day}-rfa-auto",
        season_label=snap.season_label,
        offseason_day=snap.offseason_day,
        revision=snap.revision,
        calendar_fingerprint=persistent_calendar_fingerprint(sim_candidate),
        checkpoint_hash_before=primary_hash,
        checkpoint_hash_after=_sha256(checkpoint_path),
        recovery_path=str(rec_primary),
        checkpoint_reason=reason,
    )


def advance_free_agency_day_with_rfa_offer_sheets_durably(
    *,
    recovery_directory: str | Path | None = None,
    cpu_decision_override: str | None = None,
) -> RFAOfferSheetDayAdvanceResult:
    """Advance one FA day and resolve due RFA sheets in one atomic checkpoint write.

    cpu_decision_override is a clone-test hook; production callers omit it.
    """
    import simulation_franchise_checkpoint_v1 as cp

    if cpu_decision_override not in {None, CPU_DECISION_MATCH, CPU_DECISION_WAIT}:
        raise RFAOfferSheetCPUError("cpu_decision_override must be None, 'match', or 'wait'.")
    checkpoint = cp.load_franchise_checkpoint()
    if checkpoint is None:
        raise RFAOfferSheetCPUError("The durable franchise checkpoint is unavailable.")
    controlled = tuple(sorted({_team(v) for v in controlled_teams_from_durable_checkpoint(checkpoint) if _team(v)}))
    sim_candidate, detail = advance_free_agency_day_candidate(checkpoint.simulation_state, controlled_teams=controlled)
    trade_candidate = copy.deepcopy(checkpoint.trade_state)
    current_day = int(detail["current_day"])
    pending = list(pending_offer_sheets(sim_candidate))

    cpu_candidates = [
        row for row in pending
        if _team(row.get("prior_team")) not in set(controlled)
        and current_day >= int(row.get("created_day") or 0) + CPU_DECISION_DELAY_DAYS
        and current_day <= int(row.get("match_deadline_day") or 0)
    ]
    plan = board = None
    if cpu_candidates and cpu_decision_override is None:
        try:
            plan = build_league_front_office_plan(sim_candidate, controlled_teams=controlled)
            board = build_cpu_free_agency_offer_board(sim_candidate, controlled_teams=controlled, front_office_plan=plan, max_targets_per_team=6)
        except Exception:
            plan = board = None

    evaluated = matched = expired = resolved = 0
    ids: list[str] = []
    summaries: list[str] = []
    for record in sorted(pending, key=lambda row: _clean(row.get("offer_sheet_id"))):
        sheet_id = _clean(record.get("offer_sheet_id"))
        live_map = {_clean(row.get("offer_sheet_id")): row for row in pending_offer_sheets(sim_candidate)}
        live_record = live_map.get(sheet_id)
        if live_record is None:
            continue
        prior = _team(live_record.get("prior_team"))
        created = int(live_record.get("created_day") or 0)
        deadline = int(live_record.get("match_deadline_day") or 0)
        decision = None
        kind = ""

        if current_day > deadline:
            decision = DECISION_DECLINE
            kind = "expired"
            expired += 1
        elif prior not in set(controlled) and current_day >= created + CPU_DECISION_DELAY_DAYS:
            evaluated += 1
            if cpu_decision_override is not None:
                cpu_decision = cpu_decision_override
            elif plan is None or board is None:
                cpu_decision = CPU_DECISION_WAIT
            else:
                cpu_decision = evaluate_cpu_offer_sheet_match(
                    sim_candidate,
                    trade_candidate,
                    live_record,
                    controlled_teams=controlled,
                    front_office_plan=plan,
                    cpu_offer_board=board,
                ).decision
            if cpu_decision == CPU_DECISION_MATCH:
                decision = DECISION_MATCH
                kind = "cpu_match"
                matched += 1

        if decision is None:
            continue
        temp = SimpleNamespace(simulation_state=sim_candidate, trade_state=trade_candidate)
        sim_candidate, trade_candidate, meta = build_offer_sheet_resolution_candidate(
            temp,
            offer_sheet_id=sheet_id,
            decision=decision,
        )
        resolved += 1
        ids.append(sheet_id)
        source = meta["record"]
        player_name = _clean(source.get("player_name")) or _pid(source.get("player_id"))
        destination = _team(meta["destination_team"])
        if kind == "cpu_match":
            summaries.append(f"{sheet_id}: {prior} matched {player_name}")
        else:
            summaries.append(f"{sheet_id}: response window expired; {player_name} joins {destination}")

    _annotate_day_history(sim_candidate, evaluated=evaluated, matched=matched, expired=expired, resolved=resolved)
    write = _atomic_save(
        cp,
        checkpoint,
        sim_candidate,
        trade_candidate,
        current_day=current_day,
        recovery_directory=recovery_directory,
    )
    return RFAOfferSheetDayAdvanceResult(
        version=CPU_RFA_MATCH_VERSION,
        prior_day=int(detail["prior_day"]),
        current_day=current_day,
        markets_advanced=int(detail["markets_advanced"]),
        markets_held=int(detail["markets_held"]),
        markets_ready_user=int(detail["markets_ready_user"]),
        markets_ready_cpu=int(detail["markets_ready_cpu"]),
        markets_closed=int(detail["markets_closed"]),
        write_result=write,
        cpu_offer_sheets_evaluated=evaluated,
        cpu_offer_sheets_matched=matched,
        expired_offer_sheets_declined=expired,
        offer_sheets_resolved=resolved,
        resolved_offer_sheet_ids=tuple(ids),
        resolution_summaries=tuple(summaries),
    )


def cpu_offer_sheet_match_contract_report() -> dict[str, Any]:
    return {
        "version": CPU_RFA_MATCH_VERSION,
        "scope": CPU_RFA_MATCH_SCOPE,
        "uses_existing_cpu_front_office_plan": True,
        "uses_existing_cpu_offer_board": True,
        "cpu_response_delay_days": CPU_DECISION_DELAY_DAYS,
        "cpu_match_budget_capped_by_verified_maximum": True,
        "unmatched_sheet_waits_until_deadline": True,
        "expired_sheet_auto_declines": True,
        "user_original_team_never_auto_matches": True,
        "calendar_and_resolution_saved_atomically": True,
        "primary_and_backup_rollback": True,
    }
