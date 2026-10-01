from __future__ import annotations

import copy
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
from typing import Any, Mapping, Sequence

CPU_POST_DRAFT_RELEASE_VERSION = (
    "franchise-cpu-post-draft-roster-trim-durable-release-v2-2026-09-25"
)
CPU_POST_DRAFT_RELEASE_HISTORY_ATTR = "cpu_post_draft_roster_trim_release_history_v1"
CPU_POST_DRAFT_RELEASE_CANONICAL_COMMIT_ENABLED = False


class CPUPostDraftReleaseError(RuntimeError):
    pass


@dataclass(frozen=True)
class CPUPostDraftReleasePreview:
    version: str
    status: str
    can_commit_to_clone: bool
    team: str
    player_id: str
    player_name: str
    source_simulation_fingerprint: str
    source_trade_fingerprint: str
    controlled_teams: tuple[str, ...]
    require_non_rotation: bool
    roster_count_before: int
    roster_count_after: int
    salary: float | None
    guaranteed: bool | None
    years_remaining: int | None
    dead_money_current_season: float | None
    future_guarantee_exposure: float | None
    financial_treatment: str
    checks: Mapping[str, bool]
    blockers: tuple[str, ...]
    rationale: tuple[str, ...]


@dataclass(frozen=True)
class CPUPostDraftReleaseCandidateResult:
    version: str
    transaction_id: str
    preview: CPUPostDraftReleasePreview
    simulation_candidate: Any
    trade_candidate: Any
    simulation_fingerprint: str
    trade_fingerprint: str
    released_player_ids: tuple[str, ...]
    trade_revision_before: int
    trade_revision_after: int
    trade_transaction_count_before: int
    trade_transaction_count_after: int
    financial_before: Mapping[str, Any]
    financial_after: Mapping[str, Any]


@dataclass(frozen=True)
class CPUPostDraftReleaseDurableResult:
    version: str
    transaction_id: str
    checkpoint_path: str
    source_checkpoint_sha256: str
    committed_checkpoint_sha256: str
    recovery_path: str
    automatic_backup_path: str
    source_simulation_fingerprint: str
    committed_simulation_fingerprint: str
    source_trade_fingerprint: str
    committed_trade_fingerprint: str
    rollback_performed: bool
    checkpoint_reason: str


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _player_id(value: Any) -> str:
    return _clean(value)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _history_payload(obj: Any) -> list[dict[str, Any]]:
    rows = getattr(obj, CPU_POST_DRAFT_RELEASE_HISTORY_ATTR, [])
    if not isinstance(rows, list):
        return []
    return copy.deepcopy(rows)


def _fingerprint_release_history_payload(obj: Any) -> list[dict[str, Any]]:
    """Return deterministic release-history content for durable fingerprints.

    Persisted audit timestamps remain in the checkpoint for human/audit use, but
    generated_at_utc is intentionally excluded from the canonical transaction
    fingerprint because rebuilding an identical approved release at a later
    instant must reproduce the same candidate fingerprint.
    """
    canonical: list[dict[str, Any]] = []
    for row in _history_payload(obj):
        if not isinstance(row, dict):
            canonical.append({"value": copy.deepcopy(row)})
            continue
        cooked = copy.deepcopy(row)
        cooked.pop("generated_at_utc", None)
        canonical.append(cooked)
    return canonical


def _append_release_history(
    simulation_state: Any,
    trade_state: Any,
    *,
    transaction_id: str,
    preview: CPUPostDraftReleasePreview,
) -> None:
    row = {
        "version": CPU_POST_DRAFT_RELEASE_VERSION,
        "transaction_id": transaction_id,
        "event": "cpu_post_draft_roster_trim_release",
        "player_id": preview.player_id,
        "player_name": preview.player_name,
        "team": preview.team,
        "dead_money_current_season": preview.dead_money_current_season,
        "future_guarantee_exposure": preview.future_guarantee_exposure,
        "financial_treatment": preview.financial_treatment,
        "rationale": list(preview.rationale),
        "trade_transaction_history_written": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    for obj in (simulation_state, trade_state):
        history = _history_payload(obj)
        history.append(copy.deepcopy(row))
        setattr(obj, CPU_POST_DRAFT_RELEASE_HISTORY_ATTR, history)


def _controlled_teams_from_checkpoint(checkpoint: Any) -> tuple[str, ...]:
    # Reuse the project's canonical control-resolution authority. This is a
    # safety boundary: do not independently infer CPU/user control from UI state.
    from franchise_free_agency_live_signing_v1 import (
        controlled_teams_from_durable_checkpoint,
    )

    return tuple(
        dict.fromkeys(
            _team(value)
            for value in controlled_teams_from_durable_checkpoint(checkpoint)
            if _team(value)
        )
    )


def _simulation_fingerprint(state: Any) -> str:
    from franchise_free_agency_transaction_v1_1 import (
        free_agency_durable_state_fingerprint,
    )

    base = free_agency_durable_state_fingerprint(state)
    release_history = _fingerprint_release_history_payload(state)
    encoded = json.dumps(
        {"base": base, "cpu_release_history": release_history},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _trade_fingerprint(state: Any) -> str:
    from franchise_free_agency_live_signing_v1 import trade_state_fingerprint

    base = trade_state_fingerprint(state)
    release_history = _fingerprint_release_history_payload(state)
    encoded = json.dumps(
        {"base": base, "cpu_release_history": release_history},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _contract_fields(player: Any) -> dict[str, Any]:
    contract = getattr(player, "contract", None)
    if contract is None:
        return {
            "contract": None,
            "salary": None,
            "guaranteed": None,
            "years_remaining": None,
            "guaranteed_remaining": None,
            "dead_money": None,
        }
    years_raw = getattr(contract, "years_remaining", None)
    try:
        years = int(years_raw) if years_raw is not None else None
    except (TypeError, ValueError):
        years = None

    guaranteed_remaining = None
    for attr in (
        "guaranteed_remaining",
        "remaining_guaranteed_salary",
        "guaranteed_salary_remaining",
    ):
        value = _finite(getattr(contract, attr, None))
        if value is not None:
            guaranteed_remaining = value
            break

    dead_money = None
    for attr in ("dead_money", "dead_cap", "waiver_dead_money"):
        value = _finite(getattr(contract, attr, None))
        if value is not None:
            dead_money = value
            break

    return {
        "contract": contract,
        "salary": _finite(getattr(contract, "salary", None)),
        "guaranteed": getattr(contract, "guaranteed", None),
        "years_remaining": years,
        "guaranteed_remaining": guaranteed_remaining,
        "dead_money": dead_money,
    }


def _generated_or_synthetic(player: Any) -> tuple[bool, bool]:
    synthetic = bool(getattr(player, "synthetic", False))
    generated = False
    for attr in (
        "generated_player",
        "is_generated_player",
        "generated_rookie",
        "is_generated_rookie",
    ):
        if bool(getattr(player, attr, False)):
            generated = True
            break
    source = _clean(getattr(player, "rating_source", "")).lower()
    if "generated" in source or "synthetic rookie" in source:
        generated = True
    return generated, synthetic


def _player_draft_year(player: Any) -> int | None:
    for attr in ("draft_year", "generated_draft_year", "rookie_draft_year"):
        value = getattr(player, attr, None)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _latest_generated_draft_year(simulation_state: Any) -> int | None:
    players = getattr(simulation_state, "players", {}) or {}
    years: list[int] = []
    for team_state in (getattr(simulation_state, "teams", {}) or {}).values():
        for value in tuple(getattr(team_state, "roster_player_ids", ()) or ()):
            player = players.get(_player_id(value))
            if player is None:
                continue
            generated, synthetic = _generated_or_synthetic(player)
            if not (generated or synthetic):
                continue
            draft_year = _player_draft_year(player)
            if draft_year is not None:
                years.append(draft_year)
    return max(years) if years else None


def _current_or_unresolved_generated_rookie(
    simulation_state: Any,
    player: Any,
) -> bool:
    generated, synthetic = _generated_or_synthetic(player)
    if not (generated or synthetic):
        return False
    draft_year = _player_draft_year(player)
    latest_year = _latest_generated_draft_year(simulation_state)
    return draft_year is None or latest_year is None or draft_year == latest_year


def _rotation_contains(team_state: Any, player_id: str) -> bool:
    rotation = getattr(team_state, "rotation", None)
    if rotation is None:
        return False
    for attr in ("starter_ids", "rotation_player_ids"):
        values = tuple(_player_id(value) for value in getattr(rotation, attr, ()) or ())
        if player_id in values:
            return True
    return False


def _financial_treatment(player: Any) -> tuple[
    str, float | None, float | None, tuple[str, ...]
]:
    fields = _contract_fields(player)
    salary = fields["salary"]
    guaranteed = fields["guaranteed"]
    years = fields["years_remaining"]
    guaranteed_remaining = fields["guaranteed_remaining"]
    dead_money = fields["dead_money"]
    generated, _synthetic = _generated_or_synthetic(player)
    option_type = _clean(getattr(fields["contract"], "option_type", "")).lower()

    blockers: list[str] = []
    if salary is None or salary < 0:
        blockers.append("Current contract salary is unresolved.")
        return "blocked_salary_unknown", None, None, tuple(blockers)

    if guaranteed is False:
        return "exact_non_guaranteed_release", 0.0, 0.0, ()

    if guaranteed is None and years == 1:
        # Legacy live-start rows can prove a one-year term and salary without
        # carrying a guarantee flag. Booking the full current salary as dead
        # money is conservative: it creates no cap room and has no unresolved
        # future-season allocation.
        return (
            "conservative_full_current_salary_one_year_unknown_guarantee",
            salary,
            0.0,
            (),
        )

    if guaranteed is None:
        blockers.append(
            "Multi-year guarantee status is unresolved; release cannot infer "
            "current or future dead money."
        )
        return "blocked_guarantee_status_unknown", None, None, tuple(blockers)

    if (
        guaranteed is True
        and generated
        and years is not None
        and years > 1
        and option_type in {
            "rookie_scale",
            "second_round_exception_team_option",
        }
    ):
        # Generated rookie contracts identify their future seasons as team
        # options but do not carry a per-year guarantee ledger. Preserve the
        # upcoming/current salary as conservative dead money and decline the
        # unexercised option seasons. Current draft-class rookies remain
        # protected by the preview gate and cannot reach this route.
        return (
            "conservative_generated_rookie_option_current_salary",
            salary,
            0.0,
            (),
        )

    if dead_money is not None:
        future = (
            max(0.0, guaranteed_remaining - dead_money)
            if guaranteed_remaining is not None
            else 0.0 if years == 1 else None
        )
        if future is None:
            blockers.append(
                "Explicit current dead money exists but future guarantee exposure is unresolved."
            )
            return "blocked_future_guarantee_unknown", dead_money, None, tuple(blockers)
        return "exact_explicit_dead_money", dead_money, future, ()

    if years == 1:
        return (
            "exact_full_current_salary_one_year_guarantee",
            salary,
            0.0,
            (),
        )

    if guaranteed_remaining is not None and years is not None and years > 0:
        current_dead = min(salary, guaranteed_remaining)
        future = max(0.0, guaranteed_remaining - current_dead)
        return "exact_from_guaranteed_remaining", current_dead, future, ()

    blockers.append(
        "Multi-year/unknown guaranteed allocation is unresolved; exact waiver accounting is required."
    )
    return (
        "blocked_multi_year_guarantee_allocation_unknown",
        None,
        None,
        tuple(blockers),
    )


def build_cpu_post_draft_release_preview(
    checkpoint: Any,
    *,
    team: str,
    player_id: str,
    rationale: Sequence[str] = (),
    require_non_rotation: bool = True,
    _precomputed_source_fingerprints: tuple[str, str] | None = None,
) -> CPUPostDraftReleasePreview:
    simulation_state = getattr(checkpoint, "simulation_state", None)
    trade_state = getattr(checkpoint, "trade_state", None)
    team = _team(team)
    player_id = _player_id(player_id)

    blockers: list[str] = []
    checks: dict[str, bool] = {}

    checks["checkpoint_has_simulation_state"] = simulation_state is not None
    checks["checkpoint_has_trade_state"] = trade_state is not None
    if simulation_state is None or trade_state is None:
        blockers.append("Durable checkpoint must contain SimulationState and TradeState.")
        return CPUPostDraftReleasePreview(
            version=CPU_POST_DRAFT_RELEASE_VERSION,
            status="blocked",
            can_commit_to_clone=False,
            team=team,
            player_id=player_id,
            player_name="",
            source_simulation_fingerprint="",
            source_trade_fingerprint="",
            controlled_teams=(),
            require_non_rotation=bool(require_non_rotation),
            roster_count_before=0,
            roster_count_after=0,
            salary=None,
            guaranteed=None,
            years_remaining=None,
            dead_money_current_season=None,
            future_guarantee_exposure=None,
            financial_treatment="blocked_missing_state",
            checks=checks,
            blockers=tuple(blockers),
            rationale=tuple(_clean(x) for x in rationale if _clean(x)),
        )

    phase = _clean(getattr(getattr(simulation_state, "settings", None), "phase", "")).lower()
    if not phase:
        phase = _clean(getattr(simulation_state, "phase", "")).lower()
    checks["actual_offseason"] = "offseason" in phase
    if not checks["actual_offseason"]:
        blockers.append("CPU post-Draft release preview is available only during the offseason.")

    controlled = _controlled_teams_from_checkpoint(checkpoint)
    checks["team_is_not_user_controlled"] = team not in controlled
    if not checks["team_is_not_user_controlled"]:
        blockers.append(f"{team} is user-controlled and cannot be auto-released by the CPU.")

    teams = getattr(simulation_state, "teams", {}) or {}
    players = getattr(simulation_state, "players", {}) or {}
    team_state = teams.get(team)
    player = players.get(player_id)
    checks["team_exists"] = team_state is not None
    checks["player_exists"] = player is not None
    if team_state is None:
        blockers.append(f"SimulationState has no team {team}.")
    if player is None:
        blockers.append(f"SimulationState has no player {player_id}.")

    roster_ids: tuple[str, ...] = ()
    player_name = ""
    generated = False
    synthetic = False
    in_rotation = False
    fields = {
        "salary": None,
        "guaranteed": None,
        "years_remaining": None,
    }
    treatment = "blocked_missing_player"
    dead_money = None
    future = None

    if team_state is not None:
        roster_ids = tuple(
            _player_id(value)
            for value in getattr(team_state, "roster_player_ids", ()) or ()
        )
    checks["player_rostered_by_team"] = player_id in roster_ids
    if not checks["player_rostered_by_team"]:
        blockers.append(f"{player_id} is not rostered by {team}.")

    if player is not None:
        player_name = _clean(getattr(player, "player_name", "")) or player_id
        generated, synthetic = _generated_or_synthetic(player)
        protected_generated_rookie = _current_or_unresolved_generated_rookie(
            simulation_state,
            player,
        )
        checks["player_not_current_or_unresolved_generated_rookie"] = (
            not protected_generated_rookie
        )
        if protected_generated_rookie:
            blockers.append(
                "Current or unresolved generated rookies are protected from CPU release; "
                "older generated players may be evaluated normally."
            )

        if team_state is not None:
            in_rotation = _rotation_contains(team_state, player_id)
        checks["player_not_in_rotation"] = (
            not in_rotation or not require_non_rotation
        )
        if require_non_rotation and in_rotation:
            blockers.append(
                "Player is in the current rotation; this foundation requires a non-rotation release target."
            )

        fields = _contract_fields(player)
        treatment, dead_money, future, financial_blockers = _financial_treatment(player)
        blockers.extend(financial_blockers)
        checks["financial_treatment_exact"] = not treatment.startswith("blocked_")
    else:
        checks["player_not_current_or_unresolved_generated_rookie"] = False
        checks["player_not_in_rotation"] = False
        checks["financial_treatment_exact"] = False

    ownership = getattr(trade_state, "player_team_by_id", None)
    owner = _team(ownership.get(player_id)) if isinstance(ownership, dict) else ""
    checks["trade_state_ownership_map_available"] = isinstance(ownership, dict)
    checks["trade_state_owner_matches_team"] = owner == team
    if not checks["trade_state_ownership_map_available"]:
        blockers.append("TradeState ownership map is unavailable.")
    elif not checks["trade_state_owner_matches_team"]:
        blockers.append(
            f"TradeState owner for {player_id} is {owner or 'free agent'}, not {team}."
        )

    financials = getattr(trade_state, "team_financials", None)
    checks["trade_state_financial_map_available"] = isinstance(financials, dict)
    checks["trade_state_team_financial_row_available"] = (
        isinstance(financials, dict) and team in financials
    )
    if not checks["trade_state_team_financial_row_available"]:
        blockers.append(f"TradeState financial row for {team} is unavailable.")

    if _precomputed_source_fingerprints is None:
        source_sim_fp = _simulation_fingerprint(simulation_state)
        source_trade_fp = _trade_fingerprint(trade_state)
    else:
        source_sim_fp, source_trade_fp = (
            _clean(value)
            for value in _precomputed_source_fingerprints
        )
        if not source_sim_fp or not source_trade_fp:
            raise CPUPostDraftReleaseError(
                "Precomputed release fingerprints must contain both state branches."
            )
    status = "pass" if not blockers and all(checks.values()) else "blocked"

    return CPUPostDraftReleasePreview(
        version=CPU_POST_DRAFT_RELEASE_VERSION,
        status=status,
        can_commit_to_clone=status == "pass",
        team=team,
        player_id=player_id,
        player_name=player_name,
        source_simulation_fingerprint=source_sim_fp,
        source_trade_fingerprint=source_trade_fp,
        controlled_teams=controlled,
        require_non_rotation=bool(require_non_rotation),
        roster_count_before=len(roster_ids),
        roster_count_after=(len(roster_ids) - 1 if status == "pass" else len(roster_ids)),
        salary=fields["salary"],
        guaranteed=fields["guaranteed"],
        years_remaining=fields["years_remaining"],
        dead_money_current_season=dead_money,
        future_guarantee_exposure=future,
        financial_treatment=treatment,
        checks=checks,
        blockers=tuple(blockers),
        rationale=tuple(_clean(x) for x in rationale if _clean(x)),
    )


def _mutate_attr(obj: Any, name: str, value: Any) -> Any:
    try:
        setattr(obj, name, value)
        return obj
    except Exception:
        if hasattr(obj, "__dataclass_fields__"):
            import dataclasses
            return dataclasses.replace(obj, **{name: value})
        raise


def _remove_from_rotation(team_state: Any, player_id: str) -> None:
    rotation = getattr(team_state, "rotation", None)
    if rotation is None:
        return
    for attr in ("starter_ids", "rotation_player_ids"):
        if hasattr(rotation, attr):
            values = tuple(_player_id(x) for x in getattr(rotation, attr, ()) or ())
            rotation = _mutate_attr(
                rotation,
                attr,
                tuple(x for x in values if x != player_id),
            )
    if hasattr(rotation, "minutes_by_player_id"):
        raw = getattr(rotation, "minutes_by_player_id", None)
        if isinstance(raw, dict):
            cooked = dict(raw)
            cooked.pop(player_id, None)
            rotation = _mutate_attr(rotation, "minutes_by_player_id", cooked)
    _mutate_attr(team_state, "rotation", rotation)


def _prepare_simulation_release(
    simulation_state: Any,
    *,
    preview: CPUPostDraftReleasePreview,
    copy_payload: bool = True,
) -> Any:
    candidate = copy.deepcopy(simulation_state) if copy_payload else simulation_state
    teams = getattr(candidate, "teams", None)
    players = getattr(candidate, "players", None)
    if not isinstance(teams, dict) or not isinstance(players, dict):
        raise CPUPostDraftReleaseError(
            "SimulationState lacks mutable team/player maps."
        )

    team_state = teams[preview.team]
    player = players[preview.player_id]

    for attr in ("roster_player_ids", "active_player_ids", "inactive_player_ids"):
        if hasattr(team_state, attr):
            values = tuple(
                _player_id(x) for x in getattr(team_state, attr, ()) or ()
            )
            _mutate_attr(
                team_state,
                attr,
                tuple(x for x in values if x != preview.player_id),
            )

    _remove_from_rotation(team_state, preview.player_id)

    if hasattr(player, "team_abbreviation"):
        player = _mutate_attr(player, "team_abbreviation", "")
    if hasattr(player, "roster_status"):
        player = _mutate_attr(player, "roster_status", "free_agent")

    contract = getattr(player, "contract", None)
    if contract is None:
        raise CPUPostDraftReleaseError("Release target has no contract object.")
    if hasattr(contract, "years_remaining"):
        contract = _mutate_attr(contract, "years_remaining", 0)
    if hasattr(contract, "status"):
        status = (
            "waived_non_guaranteed"
            if preview.financial_treatment == "exact_non_guaranteed_release"
            else "waived_guaranteed_dead_money"
        )
        contract = _mutate_attr(contract, "status", status)
    player = _mutate_attr(player, "contract", contract)
    players[preview.player_id] = player

    free_agents = tuple(
        _player_id(x)
        for x in getattr(candidate, "free_agent_player_ids", ()) or ()
    )
    if hasattr(candidate, "free_agent_player_ids"):
        _mutate_attr(
            candidate,
            "free_agent_player_ids",
            tuple(dict.fromkeys((*free_agents, preview.player_id))),
        )

    # Use the project-specific offseason repair. Fall back only if unavailable.
    try:
        from franchise_offseason_transaction_application_v1 import (
            repair_offseason_rotation,
        )
        repair_offseason_rotation(candidate, preview.team, ())
    except Exception:
        from simulation_season_transition_v1 import refresh_team_rotations
        refresh_team_rotations(candidate)

    return candidate


def _financial_payload(trade_state: Any, team: str) -> dict[str, Any]:
    financials = getattr(trade_state, "team_financials", None)
    if not isinstance(financials, dict) or team not in financials:
        raise CPUPostDraftReleaseError(
            f"TradeState financial row for {team} is unavailable."
        )
    row = financials[team]
    return {
        "team_salary": _finite(getattr(row, "team_salary", None)),
        "apron_salary": _finite(getattr(row, "apron_salary", None)),
        "standard_contract_count": getattr(row, "standard_contract_count", None),
        "two_way_contract_count": getattr(row, "two_way_contract_count", None),
    }


def _apply_numeric_delta(obj: Any, attr: str, delta: float) -> None:
    before = _finite(getattr(obj, attr, None))
    if before is None:
        raise CPUPostDraftReleaseError(
            f"TradeState financial value {attr} is unresolved."
        )
    _mutate_attr(obj, attr, before + delta)


def _decrement_standard_contract_count(row: Any) -> None:
    count = getattr(row, "standard_contract_count", None)
    if not isinstance(count, int) or count <= 0:
        raise CPUPostDraftReleaseError(
            "TradeState standard_contract_count is not decrementable."
        )
    _mutate_attr(row, "standard_contract_count", count - 1)


def _rebase_snapshot(
    snapshot: Any,
    *,
    preview: CPUPostDraftReleasePreview,
) -> None:
    if snapshot is None:
        return
    ownership = getattr(snapshot, "player_team_by_id", None)
    financials = getattr(snapshot, "team_financials", None)
    if isinstance(ownership, dict):
        ownership[preview.player_id] = None

    if isinstance(financials, dict) and preview.team in financials:
        row = financials[preview.team]
        _decrement_standard_contract_count(row)
        if preview.financial_treatment == "exact_non_guaranteed_release":
            salary = float(preview.salary or 0.0)
            _apply_numeric_delta(row, "team_salary", -salary)
            _apply_numeric_delta(row, "apron_salary", -salary)

    acquired = getattr(snapshot, "acquired_player_ids", None)
    if isinstance(acquired, set):
        acquired.discard(preview.player_id)


def _apply_release_financials(
    trade_state: Any,
    *,
    preview: CPUPostDraftReleasePreview,
    copy_payload: bool = True,
) -> Any:
    candidate = copy.deepcopy(trade_state) if copy_payload else trade_state
    ownership = getattr(candidate, "player_team_by_id", None)
    financials = getattr(candidate, "team_financials", None)
    if not isinstance(ownership, dict) or not isinstance(financials, dict):
        raise CPUPostDraftReleaseError(
            "TradeState lacks mutable ownership/financial maps."
        )
    if _team(ownership.get(preview.player_id)):
        raise CPUPostDraftReleaseError(
            "Ownership reconciliation did not release the player before financial rebasing."
        )

    row = financials[preview.team]
    _decrement_standard_contract_count(row)

    if preview.financial_treatment == "exact_non_guaranteed_release":
        salary = float(preview.salary or 0.0)
        _apply_numeric_delta(row, "team_salary", -salary)
        _apply_numeric_delta(row, "apron_salary", -salary)
    elif preview.financial_treatment in {
        "conservative_full_current_salary_one_year_unknown_guarantee",
        "conservative_generated_rookie_option_current_salary",
        "exact_full_current_salary_one_year_guarantee",
        "exact_explicit_dead_money",
        "exact_from_guaranteed_remaining",
    }:
        # Conservative current-season treatment: guaranteed current money
        # remains on team/apron salary as dead-money evidence.
        pass
    else:
        raise CPUPostDraftReleaseError(
            "Release financial treatment is not exact enough to commit."
        )

    acquired = getattr(candidate, "acquired_player_ids", None)
    if isinstance(acquired, set):
        acquired.discard(preview.player_id)

    for snapshot in list(getattr(candidate, "undo_stack", []) or []):
        _rebase_snapshot(snapshot, preview=preview)
    _rebase_snapshot(getattr(candidate, "initial_snapshot", None), preview=preview)
    return candidate


def build_cpu_post_draft_release_candidate(
    checkpoint: Any,
    preview: CPUPostDraftReleasePreview,
    *,
    copy_payload: bool = True,
    _defer_candidate_fingerprints: bool = False,
    _precomputed_source_fingerprints: tuple[str, str] | None = None,
) -> CPUPostDraftReleaseCandidateResult:
    if preview.version != CPU_POST_DRAFT_RELEASE_VERSION:
        raise CPUPostDraftReleaseError("Release preview version is stale.")
    if preview.status != "pass" or not preview.can_commit_to_clone:
        raise CPUPostDraftReleaseError(
            "Only a fully PASS release preview can build a candidate."
        )

    source_sim = getattr(checkpoint, "simulation_state", None)
    source_trade = getattr(checkpoint, "trade_state", None)
    if source_sim is None or source_trade is None:
        raise CPUPostDraftReleaseError(
            "Checkpoint no longer exposes both durable state branches."
        )

    if _precomputed_source_fingerprints is None:
        current_simulation_fingerprint = _simulation_fingerprint(source_sim)
        current_trade_fingerprint = _trade_fingerprint(source_trade)
    else:
        current_simulation_fingerprint, current_trade_fingerprint = (
            _clean(value)
            for value in _precomputed_source_fingerprints
        )
        if not current_simulation_fingerprint or not current_trade_fingerprint:
            raise CPUPostDraftReleaseError(
                "Precomputed candidate fingerprints must contain both state branches."
            )

    if current_simulation_fingerprint != preview.source_simulation_fingerprint:
        raise CPUPostDraftReleaseError(
            "Release preview is stale relative to SimulationState."
        )
    if current_trade_fingerprint != preview.source_trade_fingerprint:
        raise CPUPostDraftReleaseError(
            "Release preview is stale relative to TradeState."
        )

    rebuilt = build_cpu_post_draft_release_preview(
        checkpoint,
        team=preview.team,
        player_id=preview.player_id,
        rationale=preview.rationale,
        require_non_rotation=preview.require_non_rotation,
        _precomputed_source_fingerprints=(
            current_simulation_fingerprint,
            current_trade_fingerprint,
        ),
    )
    if rebuilt.status != "pass" or asdict(rebuilt) != asdict(preview):
        raise CPUPostDraftReleaseError(
            "Release preview no longer reproduces exactly at candidate-build time."
        )

    # Capture the immutable comparison baseline before the optional in-place
    # atomic-batch path mutates its already-disposable working clone.
    trade_before = _financial_payload(source_trade, preview.team)
    trade_transaction_count_before = len(
        getattr(source_trade, "transaction_history", []) or []
    )
    revision_before = int(getattr(source_trade, "state_revision", 0) or 0)

    simulation_pre = _prepare_simulation_release(
        source_sim,
        preview=preview,
        copy_payload=copy_payload,
    )

    from simulation_season_boundary_trade_reconciliation_v1 import (
        reconcile_trade_state_after_season_boundary,
    )

    simulation_candidate, trade_reconciled, reconciliation = (
        reconcile_trade_state_after_season_boundary(
            simulation_pre,
            copy.deepcopy(source_trade) if copy_payload else source_trade,
            copy_payload=copy_payload,
        )
    )
    released = tuple(
        sorted(
            _player_id(value)
            for value in getattr(reconciliation, "released_player_ids", ()) or ()
        )
    )
    if released != (preview.player_id,):
        raise CPUPostDraftReleaseError(
            "Ownership reconciliation did not release exactly the approved player."
        )

    trade_candidate = _apply_release_financials(
        trade_reconciled,
        preview=preview,
        copy_payload=copy_payload,
    )

    revision_after = int(getattr(trade_candidate, "state_revision", 0) or 0)
    trade_transaction_count_after = len(
        getattr(trade_candidate, "transaction_history", []) or []
    )
    if revision_after != revision_before + 1:
        raise CPUPostDraftReleaseError(
            "TradeState revision must increment exactly once for a release."
        )
    if trade_transaction_count_after != trade_transaction_count_before:
        raise CPUPostDraftReleaseError(
            "Waiver/release must not create a fake trade transaction."
        )

    transaction_id = (
        "CPUTRIM-"
        + hashlib.sha256(
            (
                preview.team
                + "|"
                + preview.player_id
                + "|"
                + preview.source_simulation_fingerprint
                + "|"
                + CPU_POST_DRAFT_RELEASE_VERSION
            ).encode("utf-8")
        ).hexdigest()[:18].upper()
    )
    _append_release_history(
        simulation_candidate,
        trade_candidate,
        transaction_id=transaction_id,
        preview=preview,
    )

    trade_after = _financial_payload(trade_candidate, preview.team)
    return CPUPostDraftReleaseCandidateResult(
        version=CPU_POST_DRAFT_RELEASE_VERSION,
        transaction_id=transaction_id,
        preview=preview,
        simulation_candidate=simulation_candidate,
        trade_candidate=trade_candidate,
        simulation_fingerprint=(
            ""
            if _defer_candidate_fingerprints
            else _simulation_fingerprint(simulation_candidate)
        ),
        trade_fingerprint=(
            ""
            if _defer_candidate_fingerprints
            else _trade_fingerprint(trade_candidate)
        ),
        released_player_ids=released,
        trade_revision_before=revision_before,
        trade_revision_after=revision_after,
        trade_transaction_count_before=trade_transaction_count_before,
        trade_transaction_count_after=trade_transaction_count_after,
        financial_before=trade_before,
        financial_after=trade_after,
    )


def _checkpoint_backup_path(module: Any, checkpoint_path: Path) -> Path:
    try:
        return Path(module.checkpoint_backup_path(checkpoint_path))
    except TypeError:
        return Path(str(checkpoint_path) + ".backup.pkl.gz")


def commit_cpu_post_draft_release_clone_durably(
    preview: CPUPostDraftReleasePreview,
    *,
    checkpoint_path: str | Path,
    inject_failure_after_verified_save: bool = False,
) -> CPUPostDraftReleaseDurableResult:
    """
    Persist a release ONLY to a non-canonical checkpoint clone.

    The canonical checkpoint path is hard-blocked in this foundation version.
    This is deliberate: automatic/live CPU waivers are enabled only after the
    installed-module clone regression proves this API.
    """
    import simulation_franchise_checkpoint_v1 as cp

    path = Path(checkpoint_path).resolve()
    canonical = Path(cp.DEFAULT_CHECKPOINT_PATH).resolve()
    if path == canonical:
        raise CPUPostDraftReleaseError(
            "Canonical CPU release commits are disabled in transaction foundation V1."
        )
    if not path.exists():
        raise CPUPostDraftReleaseError(
            "Clone checkpoint path does not exist."
        )

    source_checkpoint_hash = _sha256(path)
    checkpoint = cp.load_franchise_checkpoint(path=path, allow_backup=False)
    if checkpoint is None:
        raise CPUPostDraftReleaseError(
            "Clone checkpoint could not be loaded without backup fallback."
        )

    source_sim_fp = _simulation_fingerprint(checkpoint.simulation_state)
    source_trade_fp = _trade_fingerprint(checkpoint.trade_state)
    if source_sim_fp != preview.source_simulation_fingerprint:
        raise CPUPostDraftReleaseError(
            "Approved preview is stale relative to clone SimulationState."
        )
    if source_trade_fp != preview.source_trade_fingerprint:
        raise CPUPostDraftReleaseError(
            "Approved preview is stale relative to clone TradeState."
        )

    rebuilt = build_cpu_post_draft_release_preview(
        checkpoint,
        team=preview.team,
        player_id=preview.player_id,
        rationale=preview.rationale,
        require_non_rotation=preview.require_non_rotation,
    )
    if asdict(rebuilt) != asdict(preview):
        raise CPUPostDraftReleaseError(
            "Clone durable commit could not reproduce the approved release preview."
        )

    candidate = build_cpu_post_draft_release_candidate(checkpoint, rebuilt)

    recovery_root = path.parent / "cpu_post_draft_release_recovery"
    recovery_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    recovery_path = recovery_root / (
        f"pre_{candidate.transaction_id}_{stamp}_{path.name}"
    )
    shutil.copy2(path, recovery_path)

    automatic_backup = _checkpoint_backup_path(cp, path)
    backup_existed = automatic_backup.exists()
    recovery_backup = recovery_root / (
        f"pre_{candidate.transaction_id}_{stamp}_{automatic_backup.name}"
    )
    if backup_existed:
        shutil.copy2(automatic_backup, recovery_backup)

    reason = f"cpu-post-draft-roster-trim-release-{candidate.transaction_id}"
    preferences = copy.deepcopy(
        dict(getattr(checkpoint, "preferences", {}) or {})
    )

    rollback_performed = False
    try:
        cp.save_franchise_checkpoint(
            candidate.simulation_candidate,
            candidate.trade_candidate,
            preferences=preferences,
            reason=reason,
            path=path,
            copy_payload=True,
        )
        reloaded = cp.load_franchise_checkpoint(path=path, allow_backup=False)
        if reloaded is None:
            raise CPUPostDraftReleaseError(
                "Clone checkpoint reload returned no state after release save."
            )
        if (
            _simulation_fingerprint(reloaded.simulation_state)
            != candidate.simulation_fingerprint
        ):
            raise CPUPostDraftReleaseError(
                "Reloaded SimulationState does not match approved release candidate."
            )
        if _trade_fingerprint(reloaded.trade_state) != candidate.trade_fingerprint:
            raise CPUPostDraftReleaseError(
                "Reloaded TradeState does not match approved release candidate."
            )
        if inject_failure_after_verified_save:
            raise CPUPostDraftReleaseError(
                "Regression-only injected failure after verified clone save."
            )
    except Exception:
        rollback_performed = True
        shutil.copy2(recovery_path, path)
        if backup_existed:
            shutil.copy2(recovery_backup, automatic_backup)
        elif automatic_backup.exists():
            automatic_backup.unlink()

        restored = cp.load_franchise_checkpoint(path=path, allow_backup=False)
        if restored is None:
            raise CPUPostDraftReleaseError(
                "Release failed and clone rollback could not reload source state."
            )
        if _simulation_fingerprint(restored.simulation_state) != source_sim_fp:
            raise CPUPostDraftReleaseError(
                "Release failed and clone SimulationState rollback was not exact."
            )
        if _trade_fingerprint(restored.trade_state) != source_trade_fp:
            raise CPUPostDraftReleaseError(
                "Release failed and clone TradeState rollback was not exact."
            )
        raise

    return CPUPostDraftReleaseDurableResult(
        version=CPU_POST_DRAFT_RELEASE_VERSION,
        transaction_id=candidate.transaction_id,
        checkpoint_path=str(path),
        source_checkpoint_sha256=source_checkpoint_hash,
        committed_checkpoint_sha256=_sha256(path),
        recovery_path=str(recovery_path),
        automatic_backup_path=str(automatic_backup),
        source_simulation_fingerprint=source_sim_fp,
        committed_simulation_fingerprint=candidate.simulation_fingerprint,
        source_trade_fingerprint=source_trade_fp,
        committed_trade_fingerprint=candidate.trade_fingerprint,
        rollback_performed=rollback_performed,
        checkpoint_reason=reason,
    )


def cpu_post_draft_release_contract_report() -> dict[str, Any]:
    return {
        "version": CPU_POST_DRAFT_RELEASE_VERSION,
        "canonical_commit_enabled": CPU_POST_DRAFT_RELEASE_CANONICAL_COMMIT_ENABLED,
        "canonical_control_resolver": (
            "franchise_free_agency_live_signing_v1."
            "controlled_teams_from_durable_checkpoint"
        ),
        "ownership_reconciliation_authority": (
            "simulation_season_boundary_trade_reconciliation_v1."
            "reconcile_trade_state_after_season_boundary"
        ),
        "public_functions": [
            "build_cpu_post_draft_release_preview",
            "build_cpu_post_draft_release_candidate",
            "commit_cpu_post_draft_release_clone_durably",
            "cpu_post_draft_release_contract_report",
        ],
        "canonical_checkpoint_hard_blocked_in_clone_commit": True,
        "release_history_timestamp_excluded_from_fingerprint": True,
        "preview_accepts_internal_precomputed_source_fingerprints": True,
        "candidate_rechecks_source_before_internal_fingerprint_reuse": True,
        "atomic_batch_can_defer_unused_candidate_fingerprints": True,
        "fingerprinted_release_history_fields": [
            "version",
            "transaction_id",
            "event",
            "player_id",
            "player_name",
            "team",
            "dead_money_current_season",
            "future_guarantee_exposure",
            "financial_treatment",
            "rationale",
            "trade_transaction_history_written",
        ],
        "fake_trade_history_allowed": False,
        "unknown_guarantee_release_allowed": False,
        "one_year_unknown_guarantee_conservative_full_salary_allowed": True,
        "multi_year_unknown_guarantee_release_allowed": False,
        "current_or_unresolved_generated_rookie_release_allowed": False,
        "older_generated_or_synthetic_release_allowed": True,
    }
