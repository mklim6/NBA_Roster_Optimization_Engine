from __future__ import annotations

import copy
import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import streamlit as st

from franchise_financial_cba_bridge_v1 import (
    OFFSEASON_TOTAL_MAX,
    REGULAR_SEASON_STANDARD_MAX,
    TWO_WAY_MAX,
)
from freeform_trade_machine_engine_v3 import load_runtime_data
from mutable_league_state_v1 import validate_state as validate_trade_state
from simulation_franchise_checkpoint_v1 import (
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
    save_franchise_checkpoint,
)
from simulation_league_state_v1 import validate_simulation_league_state


USER_TWO_WAY_MANAGEMENT_VERSION = (
    "franchise-user-two-way-management-v1-2026-09-30"
)
USER_TWO_WAY_HISTORY_ATTR = "franchise_user_two_way_transaction_history_v1"

ALLOWED_TWO_WAY_PHASES = frozenset(
    {"preseason", "regular_season", "offseason"}
)


class UserTwoWayManagementError(RuntimeError):
    pass


@dataclass(frozen=True)
class TwoWayEligibility:
    eligible: bool
    blockers: tuple[str, ...]
    age: float | None
    overall_rating: float
    potential_rating: float


@dataclass(frozen=True)
class UserTwoWayTransactionResult:
    version: str
    transaction_id: str
    action: str
    team: str
    player_id: str
    player_name: str
    season_label: str
    phase: str
    standard_contract_count_before: int
    standard_contract_count_after: int
    two_way_contract_count_before: int
    two_way_contract_count_after: int
    trade_revision_before: int
    trade_revision_after: int


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _finite(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed if math.isfinite(parsed) else float(default)


def _player_age(player: Any) -> float | None:
    try:
        value = float(getattr(player, "age", None))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _phase(state: Any) -> str:
    raw = getattr(state, "phase", "")
    return _clean(getattr(raw, "value", raw)).lower()


def _season(state: Any) -> str:
    return _clean(getattr(getattr(state, "settings", None), "season_label", ""))


def _player_is_two_way(player: Any) -> bool:
    return bool(getattr(player, "two_way", False)) or (
        _clean(getattr(player, "roster_status", "")).lower() == "two_way"
    )


def _roster_ids(state: Any, team_code: str) -> tuple[str, ...]:
    team_state = getattr(state, "teams", {}).get(team_code)
    if team_state is None:
        return ()
    return tuple(
        _clean(value)
        for value in tuple(getattr(team_state, "roster_player_ids", ()) or ())
        if _clean(value)
    )


def two_way_count_v1(state: Any, team_code: str) -> int:
    code = _team(team_code)
    players = getattr(state, "players", {}) or {}
    return sum(
        1
        for player_id in _roster_ids(state, code)
        if player_id in players and _player_is_two_way(players[player_id])
    )


def standard_contract_count_v1(state: Any, team_code: str) -> int:
    code = _team(team_code)
    players = getattr(state, "players", {}) or {}
    return sum(
        1
        for player_id in _roster_ids(state, code)
        if player_id in players and not _player_is_two_way(players[player_id])
    )


def _controlled_set(values: Iterable[str]) -> set[str]:
    return {
        _team(value)
        for value in values
        if _team(value)
    }


def _controlled_from_preferences(preferences: Mapping[str, Any] | None) -> tuple[str, ...]:
    payload = dict(preferences or {})
    raw = payload.get("franchise_pref_controlled_teams", ()) or ()
    if isinstance(raw, str):
        raw = [raw]
    return tuple(sorted(_controlled_set(raw)))


def two_way_eligibility_v1(player: Any) -> TwoWayEligibility:
    blockers: list[str] = []

    if player is None:
        return TwoWayEligibility(
            eligible=False,
            blockers=("Player record is unavailable.",),
            age=None,
            overall_rating=0.0,
            potential_rating=0.0,
        )

    overall = _finite(getattr(player, "overall_rating", None), -1.0)
    potential = _finite(getattr(player, "potential_rating", None), overall)
    age = _player_age(player)

    if bool(getattr(player, "synthetic", False)):
        blockers.append("Synthetic replacement players cannot receive two-way contracts.")

    if _player_is_two_way(player):
        blockers.append("Player is already on a two-way contract.")

    if _team(getattr(player, "team_abbreviation", "")):
        blockers.append("Player is already assigned to an NBA team.")

    roster_status = _clean(getattr(player, "roster_status", "")).lower()
    if roster_status not in {"free_agent", "free_agent_pool"}:
        blockers.append("Player is not in the free-agent pool.")

    contract = getattr(player, "contract", None)
    contract_status = _clean(getattr(contract, "status", "")).lower()
    if contract_status not in {"", "free_agent", "free_agent_pool"}:
        blockers.append("Player still has a non-free-agent contract status.")

    # These guardrails intentionally mirror the CPU two-way completion model.
    # Service-year data is not yet dependable for every generated player, so
    # V2 uses conservative age/quality/development proxies.
    if overall < 55.0:
        blockers.append("Overall rating is below the V2 developmental floor (55).")
    if overall > 80.0:
        blockers.append("Overall rating exceeds the V2 two-way ceiling (80).")
    if age is not None and age < 18.0:
        blockers.append("Player is younger than the V2 developmental eligibility floor.")
    if age is not None and age > 27.0:
        blockers.append("Player is older than the current V2 two-way proxy allows (27).")
    if age is None and overall > 74.0:
        blockers.append(
            "Unknown-age players above 74 OVR are blocked from the conservative two-way proxy."
        )
    if potential < 62.0:
        blockers.append("Potential rating is below the V2 developmental floor (62).")

    return TwoWayEligibility(
        eligible=not blockers,
        blockers=tuple(blockers),
        age=age,
        overall_rating=overall,
        potential_rating=potential,
    )


def _position_bucket(value: Any) -> str:
    text = _clean(value).upper().replace("-", "/")
    for token in ("PG", "SG", "SF", "PF", "C"):
        if token in text:
            return token
    return "UNK"


def _team_position_counts(state: Any, team_code: str) -> dict[str, int]:
    counts = {key: 0 for key in ("PG", "SG", "SF", "PF", "C", "UNK")}
    players = getattr(state, "players", {}) or {}
    for player_id in _roster_ids(state, team_code):
        player = players.get(player_id)
        if player is None or _player_is_two_way(player):
            continue
        bucket = _position_bucket(getattr(player, "position", ""))
        counts[bucket] = counts.get(bucket, 0) + 1
    return counts


def _stable_tiebreak(team_code: str, player_id: str) -> float:
    digest = hashlib.sha256(
        f"{team_code}|{player_id}".encode("utf-8")
    ).digest()
    raw = int.from_bytes(digest[:8], "big")
    return raw / float(2**64 - 1)


def development_score_v1(state: Any, team_code: str, player: Any) -> float:
    overall = _finite(getattr(player, "overall_rating", None), 55.0)
    potential = _finite(getattr(player, "potential_rating", None), overall)
    future = _finite(getattr(player, "future_outlook_rating", None), potential)
    reliability = max(
        0.0,
        min(1.0, _finite(getattr(player, "profile_reliability", None), 0.5)),
    )
    age = _player_age(player)
    age_bonus = 0.0 if age is None else max(0.0, 27.0 - age) * 1.25
    upside = max(0.0, potential - overall)
    future_upside = max(0.0, future - overall)
    bucket = _position_bucket(getattr(player, "position", ""))
    position_counts = _team_position_counts(state, team_code)
    position_need_bonus = (
        max(0.0, 3.0 - float(position_counts.get(bucket, 0))) * 1.5
    )

    return (
        overall * 0.45
        + potential * 0.35
        + future * 0.20
        + upside * 1.20
        + future_upside * 0.60
        + age_bonus
        + reliability * 1.5
        + position_need_bonus
        + _stable_tiebreak(
            _team(team_code),
            _clean(getattr(player, "player_id", "")),
        ) * 0.01
    )


def eligible_two_way_free_agents_v1(
    state: Any,
    team_code: str,
) -> list[dict[str, Any]]:
    code = _team(team_code)
    players = getattr(state, "players", {}) or {}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw_id in tuple(getattr(state, "free_agent_player_ids", ()) or ()):
        player_id = _clean(raw_id)
        if not player_id or player_id in seen:
            continue
        seen.add(player_id)
        player = players.get(player_id)
        eligibility = two_way_eligibility_v1(player)
        if not eligibility.eligible:
            continue
        rows.append(
            {
                "player_id": player_id,
                "player_name": _clean(getattr(player, "player_name", "")) or player_id,
                "position": _clean(getattr(player, "position", "")) or "UNK",
                "age": eligibility.age,
                "overall": eligibility.overall_rating,
                "potential": eligibility.potential_rating,
                "future": _finite(
                    getattr(player, "future_outlook_rating", None),
                    eligibility.potential_rating,
                ),
                "development_score": development_score_v1(state, code, player),
            }
        )

    rows.sort(
        key=lambda row: (
            -float(row["development_score"]),
            -float(row["potential"]),
            -float(row["overall"]),
            str(row["player_name"]),
            str(row["player_id"]),
        )
    )
    return rows


def current_two_way_players_v1(
    state: Any,
    team_code: str,
) -> list[dict[str, Any]]:
    code = _team(team_code)
    players = getattr(state, "players", {}) or {}
    rows: list[dict[str, Any]] = []
    for player_id in _roster_ids(state, code):
        player = players.get(player_id)
        if player is None or not _player_is_two_way(player):
            continue
        contract = getattr(player, "contract", None)
        rows.append(
            {
                "player_id": player_id,
                "player_name": _clean(getattr(player, "player_name", "")) or player_id,
                "position": _clean(getattr(player, "position", "")) or "UNK",
                "age": _player_age(player),
                "overall": _finite(getattr(player, "overall_rating", None), 0.0),
                "potential": _finite(
                    getattr(player, "potential_rating", None),
                    _finite(getattr(player, "overall_rating", None), 0.0),
                ),
                "years": getattr(contract, "years_remaining", None),
            }
        )
    rows.sort(key=lambda row: (-float(row["overall"]), str(row["player_name"])))
    return rows


def _capacity_blockers(state: Any, team_code: str) -> tuple[str, ...]:
    code = _team(team_code)
    blockers: list[str] = []
    phase = _phase(state)
    standard = standard_contract_count_v1(state, code)
    two_way = two_way_count_v1(state, code)
    total = len(_roster_ids(state, code))

    if phase not in ALLOWED_TWO_WAY_PHASES:
        blockers.append(
            "Two-way roster moves are locked during the Play-In and playoffs."
        )

    if two_way >= int(TWO_WAY_MAX):
        blockers.append(
            f"{code} already uses all {int(TWO_WAY_MAX)} two-way slots."
        )

    if phase in {"preseason", "regular_season"}:
        if standard > int(REGULAR_SEASON_STANDARD_MAX):
            blockers.append(
                f"{code} has {standard} standard contracts; regular-season maximum is "
                f"{int(REGULAR_SEASON_STANDARD_MAX)}."
            )
        if total + 1 > int(REGULAR_SEASON_STANDARD_MAX) + int(TWO_WAY_MAX):
            blockers.append(
                "Signing would exceed the regular-season standard + two-way roster limit."
            )
    elif phase == "offseason" and total + 1 > int(OFFSEASON_TOTAL_MAX):
        blockers.append(
            f"Signing would exceed the offseason total roster maximum "
            f"({int(OFFSEASON_TOTAL_MAX)}, including two-way contracts)."
        )

    return tuple(blockers)


def _remove_from_rotation(team_state: Any, player_id: str) -> None:
    rotation = getattr(team_state, "rotation", None)
    if rotation is None:
        return

    for attr in ("starter_ids", "rotation_player_ids"):
        if hasattr(rotation, attr):
            values = tuple(
                _clean(value)
                for value in tuple(getattr(rotation, attr, ()) or ())
                if _clean(value) and _clean(value) != player_id
            )
            setattr(rotation, attr, values)

    if hasattr(rotation, "minutes_targets"):
        values = dict(getattr(rotation, "minutes_targets", {}) or {})
        values.pop(player_id, None)
        rotation.minutes_targets = values

    if hasattr(rotation, "minutes_by_player_id"):
        values = dict(getattr(rotation, "minutes_by_player_id", {}) or {})
        values.pop(player_id, None)
        rotation.minutes_by_player_id = values


def _append_history(
    state: Any,
    *,
    transaction_id: str,
    action: str,
    team_code: str,
    player: Any,
) -> None:
    history = list(getattr(state, USER_TWO_WAY_HISTORY_ATTR, []) or [])
    history.append(
        {
            "version": USER_TWO_WAY_MANAGEMENT_VERSION,
            "transaction_id": transaction_id,
            "action": action,
            "season_label": _season(state),
            "phase": _phase(state),
            "team": team_code,
            "player_id": _clean(getattr(player, "player_id", "")),
            "player_name": _clean(getattr(player, "player_name", "")),
            "canonical_mutation": True,
        }
    )
    setattr(state, USER_TWO_WAY_HISTORY_ATTR, history)


def _next_transaction_id(state: Any) -> str:
    history = list(getattr(state, USER_TWO_WAY_HISTORY_ATTR, []) or [])
    return f"TW-{len(history) + 1:04d}"


def _sync_trade_snapshot(
    snapshot: Any,
    *,
    player_id: str,
    owner_code: str,
    financial_team_code: str,
    two_way_count: int,
    acquired: bool,
) -> None:
    if snapshot is None:
        return

    ownership = getattr(snapshot, "player_team_by_id", None)
    financials = getattr(snapshot, "team_financials", None)
    if not isinstance(ownership, dict) or not isinstance(financials, dict):
        raise UserTwoWayManagementError(
            "TradeState reset/undo snapshot does not expose the expected ownership/financial maps."
        )
    if player_id not in ownership:
        raise UserTwoWayManagementError(
            "Two-way player is missing from a TradeState reset/undo snapshot."
        )
    if financial_team_code not in financials:
        raise UserTwoWayManagementError(
            f"{financial_team_code} is missing from a TradeState reset/undo snapshot."
        )

    ownership[player_id] = owner_code
    financials[financial_team_code].two_way_contract_count = int(two_way_count)

    acquired_ids = getattr(snapshot, "acquired_player_ids", None)
    if isinstance(acquired_ids, set):
        if acquired:
            acquired_ids.add(player_id)
        else:
            acquired_ids.discard(player_id)


def _sync_trade_candidate(
    trade_state: Any,
    *,
    player_id: str,
    team_code: str,
    two_way_count_after: int,
    signing: bool,
) -> tuple[Any, int, int]:
    candidate = copy.deepcopy(trade_state)
    ownership = getattr(candidate, "player_team_by_id", None)
    financials = getattr(candidate, "team_financials", None)
    if not isinstance(ownership, dict) or not isinstance(financials, dict):
        raise UserTwoWayManagementError(
            "TradeState does not expose mutable ownership/financial maps."
        )
    if player_id not in ownership:
        raise UserTwoWayManagementError(
            "Player is missing from the durable TradeState registry."
        )
    if team_code not in financials:
        raise UserTwoWayManagementError(
            f"{team_code} is missing from the TradeState financial ledger."
        )

    observed_owner = _team(ownership.get(player_id, ""))
    if signing and observed_owner:
        raise UserTwoWayManagementError(
            f"TradeState still assigns this free agent to {observed_owner}."
        )
    if not signing and observed_owner != team_code:
        raise UserTwoWayManagementError(
            f"TradeState assigns this two-way player to {observed_owner or '<unassigned>'}, "
            f"not {team_code}."
        )

    financial = financials[team_code]
    salary_before = getattr(financial, "team_salary", None)
    apron_before = getattr(financial, "apron_salary", None)

    revision_before = int(getattr(candidate, "state_revision", 0) or 0)
    ownership[player_id] = team_code if signing else ""
    financial.two_way_contract_count = int(two_way_count_after)

    acquired_ids = getattr(candidate, "acquired_player_ids", None)
    if isinstance(acquired_ids, set):
        if signing:
            acquired_ids.add(player_id)
        else:
            acquired_ids.discard(player_id)

    for snapshot in list(getattr(candidate, "undo_stack", []) or []):
        _sync_trade_snapshot(
            snapshot,
            player_id=player_id,
            owner_code=team_code if signing else "",
            financial_team_code=team_code,
            two_way_count=two_way_count_after,
            acquired=signing,
        )

    initial_snapshot = getattr(candidate, "initial_snapshot", None)
    if initial_snapshot is not None:
        _sync_trade_snapshot(
            initial_snapshot,
            player_id=player_id,
            owner_code=team_code if signing else "",
            financial_team_code=team_code,
            two_way_count=two_way_count_after,
            acquired=signing,
        )

    # Two-way contracts carry zero cap salary in this V2 model.
    if getattr(financial, "team_salary", None) != salary_before:
        raise UserTwoWayManagementError("Two-way transaction changed team salary.")
    if getattr(financial, "apron_salary", None) != apron_before:
        raise UserTwoWayManagementError("Two-way transaction changed apron salary.")

    candidate.state_revision = revision_before + 1

    try:
        validate_trade_state(candidate, load_runtime_data())
    except Exception as exc:
        raise UserTwoWayManagementError(
            f"Two-way TradeState candidate is invalid: {exc}"
        ) from exc

    return candidate, revision_before, int(candidate.state_revision)


def _align_simulation_source(state: Any, trade_state: Any) -> None:
    if hasattr(state, "source_league_state_revision"):
        state.source_league_state_revision = int(
            getattr(trade_state, "state_revision", 0) or 0
        )
    if hasattr(state, "source_transaction_count"):
        state.source_transaction_count = len(
            list(getattr(trade_state, "transaction_history", []) or [])
        )


def authority_fingerprint_v1(
    state: Any,
    trade_state: Any,
    team_code: str,
) -> str:
    code = _team(team_code)
    financial = (getattr(trade_state, "team_financials", {}) or {}).get(code)
    payload = (
        _season(state),
        _phase(state),
        int(getattr(state, "source_league_state_revision", 0) or 0),
        int(getattr(state, "source_transaction_count", 0) or 0),
        tuple(_roster_ids(state, code)),
        tuple(sorted(_clean(value) for value in getattr(state, "free_agent_player_ids", ()) or ())),
        int(getattr(trade_state, "state_revision", 0) or 0),
        getattr(financial, "standard_contract_count", None),
        getattr(financial, "two_way_contract_count", None),
    )
    return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()


def build_user_two_way_signing_candidate_v1(
    state: Any,
    trade_state: Any,
    *,
    team_code: str,
    player_id: str,
    controlled_teams: Iterable[str],
) -> tuple[Any, Any, UserTwoWayTransactionResult]:
    code = _team(team_code)
    pid = _clean(player_id)
    controlled = _controlled_set(controlled_teams)

    if code not in controlled:
        raise UserTwoWayManagementError(
            f"{code} is not a user-controlled franchise."
        )
    if code not in getattr(state, "teams", {}):
        raise UserTwoWayManagementError(f"Unknown NBA team: {code}.")
    if pid not in getattr(state, "players", {}):
        raise UserTwoWayManagementError(f"Unknown player: {pid}.")

    eligibility = two_way_eligibility_v1(state.players[pid])
    blockers = list(eligibility.blockers)
    blockers.extend(_capacity_blockers(state, code))
    if blockers:
        raise UserTwoWayManagementError(" ".join(blockers))

    before_standard = standard_contract_count_v1(state, code)
    before_two_way = two_way_count_v1(state, code)

    candidate = copy.deepcopy(state)
    team_state = candidate.teams[code]
    player = candidate.players[pid]

    roster = list(_roster_ids(candidate, code))
    if pid in roster:
        raise UserTwoWayManagementError("Two-way signing would duplicate a rostered player.")
    roster.append(pid)
    team_state.roster_player_ids = tuple(roster)

    inactive = list(
        _clean(value)
        for value in tuple(getattr(team_state, "inactive_player_ids", ()) or ())
        if _clean(value)
    )
    if pid not in inactive:
        inactive.append(pid)
    team_state.inactive_player_ids = tuple(inactive)

    # Two-way signings are not automatically inserted into an NBA rotation.
    active = tuple(
        value
        for value in tuple(getattr(team_state, "active_player_ids", ()) or ())
        if _clean(value) != pid
    )
    team_state.active_player_ids = active
    _remove_from_rotation(team_state, pid)

    player.team_abbreviation = code
    player.roster_status = "two_way"
    player.two_way = True

    contract = getattr(player, "contract", None)
    if contract is None:
        raise UserTwoWayManagementError("Two-way target has no contract state.")
    contract.status = "two_way"
    contract.salary = 0.0
    contract.years_remaining = 1
    contract.option_type = ""
    contract.guaranteed = False

    setattr(player, "live_contract_cap_hit", 0.0)
    setattr(player, "live_contract_guaranteed_amount", 0.0)
    setattr(player, "live_contract_total_value", None)
    setattr(player, "live_contract_guarantee_status", "two_way")
    setattr(player, "live_contract_signing_method", "franchise_user_two_way")
    setattr(player, "live_contract_evidence_status", "franchise_user_two_way")

    candidate.free_agent_player_ids = tuple(
        value
        for value in tuple(getattr(candidate, "free_agent_player_ids", ()) or ())
        if _clean(value) != pid
    )

    transaction_id = _next_transaction_id(candidate)
    _append_history(
        candidate,
        transaction_id=transaction_id,
        action="sign_two_way",
        team_code=code,
        player=player,
    )

    after_standard = standard_contract_count_v1(candidate, code)
    after_two_way = two_way_count_v1(candidate, code)

    if after_standard != before_standard:
        raise UserTwoWayManagementError(
            "Two-way signing changed the standard-contract count."
        )
    if after_two_way != before_two_way + 1 or after_two_way > int(TWO_WAY_MAX):
        raise UserTwoWayManagementError(
            "Two-way signing produced an invalid two-way roster count."
        )

    trade_candidate, revision_before, revision_after = _sync_trade_candidate(
        trade_state,
        player_id=pid,
        team_code=code,
        two_way_count_after=after_two_way,
        signing=True,
    )
    _align_simulation_source(candidate, trade_candidate)
    validate_simulation_league_state(candidate)

    return candidate, trade_candidate, UserTwoWayTransactionResult(
        version=USER_TWO_WAY_MANAGEMENT_VERSION,
        transaction_id=transaction_id,
        action="sign_two_way",
        team=code,
        player_id=pid,
        player_name=_clean(getattr(player, "player_name", "")) or pid,
        season_label=_season(candidate),
        phase=_phase(candidate),
        standard_contract_count_before=before_standard,
        standard_contract_count_after=after_standard,
        two_way_contract_count_before=before_two_way,
        two_way_contract_count_after=after_two_way,
        trade_revision_before=revision_before,
        trade_revision_after=revision_after,
    )


def build_user_two_way_release_candidate_v1(
    state: Any,
    trade_state: Any,
    *,
    team_code: str,
    player_id: str,
    controlled_teams: Iterable[str],
) -> tuple[Any, Any, UserTwoWayTransactionResult]:
    code = _team(team_code)
    pid = _clean(player_id)
    controlled = _controlled_set(controlled_teams)

    if code not in controlled:
        raise UserTwoWayManagementError(
            f"{code} is not a user-controlled franchise."
        )
    if _phase(state) not in ALLOWED_TWO_WAY_PHASES:
        raise UserTwoWayManagementError(
            "Two-way roster moves are locked during the Play-In and playoffs."
        )
    if code not in getattr(state, "teams", {}):
        raise UserTwoWayManagementError(f"Unknown NBA team: {code}.")
    if pid not in getattr(state, "players", {}):
        raise UserTwoWayManagementError(f"Unknown player: {pid}.")

    player = state.players[pid]
    if _team(getattr(player, "team_abbreviation", "")) != code:
        raise UserTwoWayManagementError(
            "Player does not belong to the selected controlled team."
        )
    if not _player_is_two_way(player):
        raise UserTwoWayManagementError(
            "Only current two-way players can be released from this panel."
        )

    before_standard = standard_contract_count_v1(state, code)
    before_two_way = two_way_count_v1(state, code)

    candidate = copy.deepcopy(state)
    team_state = candidate.teams[code]
    player = candidate.players[pid]

    for attr in ("roster_player_ids", "active_player_ids", "inactive_player_ids"):
        if hasattr(team_state, attr):
            setattr(
                team_state,
                attr,
                tuple(
                    value
                    for value in tuple(getattr(team_state, attr, ()) or ())
                    if _clean(value) != pid
                ),
            )
    _remove_from_rotation(team_state, pid)

    player.team_abbreviation = ""
    player.roster_status = "free_agent"
    player.two_way = False

    contract = getattr(player, "contract", None)
    if contract is None:
        raise UserTwoWayManagementError("Two-way release target has no contract state.")
    contract.status = "free_agent_pool"
    contract.salary = None
    contract.years_remaining = 0
    contract.option_type = ""
    contract.guaranteed = None

    setattr(player, "live_contract_cap_hit", 0.0)
    setattr(player, "live_contract_guaranteed_amount", 0.0)
    setattr(player, "live_contract_total_value", None)
    setattr(player, "live_contract_guarantee_status", "not_under_contract")
    setattr(player, "live_contract_signing_method", "")
    setattr(player, "live_contract_evidence_status", "released_two_way_contract")

    free_agents = [
        _clean(value)
        for value in tuple(getattr(candidate, "free_agent_player_ids", ()) or ())
        if _clean(value)
    ]
    if pid not in free_agents:
        free_agents.append(pid)
    candidate.free_agent_player_ids = tuple(dict.fromkeys(free_agents))

    transaction_id = _next_transaction_id(candidate)
    _append_history(
        candidate,
        transaction_id=transaction_id,
        action="release_two_way",
        team_code=code,
        player=player,
    )

    after_standard = standard_contract_count_v1(candidate, code)
    after_two_way = two_way_count_v1(candidate, code)

    if after_standard != before_standard:
        raise UserTwoWayManagementError(
            "Two-way release changed the standard-contract count."
        )
    if after_two_way != before_two_way - 1:
        raise UserTwoWayManagementError(
            "Two-way release produced an invalid two-way roster count."
        )

    trade_candidate, revision_before, revision_after = _sync_trade_candidate(
        trade_state,
        player_id=pid,
        team_code=code,
        two_way_count_after=after_two_way,
        signing=False,
    )
    _align_simulation_source(candidate, trade_candidate)
    validate_simulation_league_state(candidate)

    return candidate, trade_candidate, UserTwoWayTransactionResult(
        version=USER_TWO_WAY_MANAGEMENT_VERSION,
        transaction_id=transaction_id,
        action="release_two_way",
        team=code,
        player_id=pid,
        player_name=_clean(getattr(player, "player_name", "")) or pid,
        season_label=_season(candidate),
        phase=_phase(candidate),
        standard_contract_count_before=before_standard,
        standard_contract_count_after=after_standard,
        two_way_contract_count_before=before_two_way,
        two_way_contract_count_after=after_two_way,
        trade_revision_before=revision_before,
        trade_revision_after=revision_after,
    )


def _checkpoint_sha256(path: Path = DEFAULT_CHECKPOINT_PATH) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _commit_candidate_durably(
    *,
    candidate_state: Any,
    candidate_trade: Any,
    source_checkpoint: Any,
    source_sha256: str,
    preferences: Mapping[str, Any],
    reason: str,
) -> Any:
    verified = save_franchise_checkpoint(
        candidate_state,
        candidate_trade,
        preferences=dict(preferences),
        reason=reason,
        copy_payload=False,
        _return_verified=True,
        _existing_checkpoint=source_checkpoint,
        _expected_existing_sha256=source_sha256,
    )
    if _clean(getattr(verified, "reason", "")) != reason:
        raise UserTwoWayManagementError(
            "A newer franchise checkpoint won the save race. Reload Team Management "
            "before retrying the two-way transaction."
        )
    return verified


def commit_user_two_way_signing_durably_v1(
    *,
    team_code: str,
    player_id: str,
    expected_authority_fingerprint: str,
    preferences_override: Mapping[str, Any] | None = None,
) -> tuple[Any, UserTwoWayTransactionResult]:
    checkpoint = load_franchise_checkpoint(allow_backup=False)
    if checkpoint is None:
        raise UserTwoWayManagementError(
            "The durable franchise checkpoint is unavailable."
        )
    source_sha = _checkpoint_sha256()
    preferences = dict(getattr(checkpoint, "preferences", {}) or {})
    if preferences_override is not None:
        preferences.update(dict(preferences_override))
    controlled = _controlled_from_preferences(preferences)
    code = _team(team_code)

    observed = authority_fingerprint_v1(
        checkpoint.simulation_state,
        checkpoint.trade_state,
        code,
    )
    if observed != _clean(expected_authority_fingerprint):
        raise UserTwoWayManagementError(
            "The durable franchise changed after this Team Management view loaded. "
            "Reload before signing the player."
        )

    candidate_state, candidate_trade, result = (
        build_user_two_way_signing_candidate_v1(
            checkpoint.simulation_state,
            checkpoint.trade_state,
            team_code=code,
            player_id=player_id,
            controlled_teams=controlled,
        )
    )
    verified = _commit_candidate_durably(
        candidate_state=candidate_state,
        candidate_trade=candidate_trade,
        source_checkpoint=checkpoint,
        source_sha256=source_sha,
        preferences=preferences,
        reason=f"user-two-way-signing:{result.transaction_id}",
    )
    return verified, result


def commit_user_two_way_release_durably_v1(
    *,
    team_code: str,
    player_id: str,
    expected_authority_fingerprint: str,
    preferences_override: Mapping[str, Any] | None = None,
) -> tuple[Any, UserTwoWayTransactionResult]:
    checkpoint = load_franchise_checkpoint(allow_backup=False)
    if checkpoint is None:
        raise UserTwoWayManagementError(
            "The durable franchise checkpoint is unavailable."
        )
    source_sha = _checkpoint_sha256()
    preferences = dict(getattr(checkpoint, "preferences", {}) or {})
    if preferences_override is not None:
        preferences.update(dict(preferences_override))
    controlled = _controlled_from_preferences(preferences)
    code = _team(team_code)

    observed = authority_fingerprint_v1(
        checkpoint.simulation_state,
        checkpoint.trade_state,
        code,
    )
    if observed != _clean(expected_authority_fingerprint):
        raise UserTwoWayManagementError(
            "The durable franchise changed after this Team Management view loaded. "
            "Reload before releasing the player."
        )

    candidate_state, candidate_trade, result = (
        build_user_two_way_release_candidate_v1(
            checkpoint.simulation_state,
            checkpoint.trade_state,
            team_code=code,
            player_id=player_id,
            controlled_teams=controlled,
        )
    )
    verified = _commit_candidate_durably(
        candidate_state=candidate_state,
        candidate_trade=candidate_trade,
        source_checkpoint=checkpoint,
        source_sha256=source_sha,
        preferences=preferences,
        reason=f"user-two-way-release:{result.transaction_id}",
    )
    return verified, result


def _age_text(value: float | None) -> str:
    return "—" if value is None else str(int(round(value)))


def render_user_two_way_management_v1(
    *,
    state: Any,
    trade_state: Any,
    team_code: str,
    controlled_teams: Iterable[str],
    preferences: Mapping[str, Any],
    disabled: bool = False,
) -> None:
    code = _team(team_code)
    controlled = _controlled_set(controlled_teams)
    standard = standard_contract_count_v1(state, code)
    two_way = two_way_count_v1(state, code)
    open_slots = max(0, int(TWO_WAY_MAX) - two_way)
    phase = _phase(state)

    st.markdown("### Two-Way Contracts")
    st.caption(
        "Manage the separate developmental roster. Two-way contracts do not count "
        "against the 15-player standard roster in this V2 model."
    )

    metrics = st.columns(4)
    metrics[0].metric("Standard roster", f"{standard}/{int(REGULAR_SEASON_STANDARD_MAX)}")
    metrics[1].metric("Two-way roster", f"{two_way}/{int(TWO_WAY_MAX)}")
    metrics[2].metric("Open two-way slots", open_slots)
    metrics[3].metric("Eligible free agents", len(eligible_two_way_free_agents_v1(state, code)))

    if code not in controlled:
        st.info("Two-way transactions are available only for user-controlled teams.")
        return

    if phase not in ALLOWED_TWO_WAY_PHASES:
        st.warning(
            "Two-way roster moves are locked during the Play-In and playoffs. "
            "Existing two-way players remain visible."
        )

    current = current_two_way_players_v1(state, code)
    if current:
        st.markdown("#### Current two-way players")
        st.dataframe(
            [
                {
                    "Player": row["player_name"],
                    "Pos": row["position"],
                    "Age": _age_text(row["age"]),
                    "OVR": round(float(row["overall"])),
                    "POT": round(float(row["potential"])),
                    "Term": (
                        f"{int(row['years'])} year"
                        if row["years"] is not None
                        else "Two-way"
                    ),
                }
                for row in current
            ],
            hide_index=True,
            width="stretch",
        )

        release_labels = {
            (
                f"{row['player_name']} · {row['position']} · "
                f"{row['overall']:.0f} OVR"
            ): row["player_id"]
            for row in current
        }
        selected_release_label = st.selectbox(
            "Two-way player to release",
            list(release_labels),
            key=f"franchise_two_way_release_select_{code}",
        )
        selected_release_id = release_labels[selected_release_label]

        if st.button(
            "Release two-way player",
            key=f"franchise_two_way_release_{code}",
            disabled=bool(disabled) or phase not in ALLOWED_TWO_WAY_PHASES,
            width="stretch",
        ):
            try:
                fingerprint = authority_fingerprint_v1(state, trade_state, code)
                verified, result = commit_user_two_way_release_durably_v1(
                    team_code=code,
                    player_id=selected_release_id,
                    expected_authority_fingerprint=fingerprint,
                    preferences_override=preferences,
                )
                st.session_state["franchise_simulation_league_state"] = (
                    verified.simulation_state
                )
                st.session_state["franchise_trade_league_state"] = verified.trade_state
                st.session_state["franchise_notice"] = (
                    f"{result.transaction_id}: released {result.player_name} from "
                    f"{code}'s two-way roster. {result.two_way_contract_count_after}/"
                    f"{int(TWO_WAY_MAX)} slots are now filled."
                )
            except Exception as exc:
                st.error(f"Two-way release was not committed. Detail: {exc}")
            else:
                st.rerun()
    else:
        st.info("No two-way players are currently assigned to this team.")

    st.markdown("#### Sign an eligible free agent")
    capacity_blockers = _capacity_blockers(state, code)
    eligible = eligible_two_way_free_agents_v1(state, code)

    if capacity_blockers:
        for blocker in capacity_blockers:
            st.warning(blocker)

    if not eligible:
        st.info(
            "No current free agents satisfy the V2 developmental two-way guardrails."
        )
        return

    display_rows = eligible[:40]
    st.dataframe(
        [
            {
                "Player": row["player_name"],
                "Pos": row["position"],
                "Age": _age_text(row["age"]),
                "OVR": round(float(row["overall"])),
                "POT": round(float(row["potential"])),
                "Future": round(float(row["future"])),
                "Fit score": round(float(row["development_score"]), 1),
            }
            for row in display_rows
        ],
        hide_index=True,
        width="stretch",
    )

    labels = {
        (
            f"{row['player_name']} · {row['position']} · "
            f"{row['overall']:.0f} OVR · {row['potential']:.0f} POT"
        ): row["player_id"]
        for row in eligible
    }
    selected_label = st.selectbox(
        "Eligible free agent",
        list(labels),
        key=f"franchise_two_way_sign_select_{code}",
    )
    selected_id = labels[selected_label]

    st.caption(
        "Current V2 eligibility uses the same conservative developmental proxy as "
        "CPU teams: free agent, non-synthetic, 55–80 OVR, age 18–27 when known "
        "(stricter when age is unknown), and at least 62 potential. Exact NBA "
        "years-of-service eligibility is a future realism upgrade."
    )

    if st.button(
        "Sign to two-way contract",
        type="primary",
        key=f"franchise_two_way_sign_{code}",
        disabled=(
            bool(disabled)
            or bool(capacity_blockers)
            or phase not in ALLOWED_TWO_WAY_PHASES
        ),
        width="stretch",
    ):
        try:
            fingerprint = authority_fingerprint_v1(state, trade_state, code)
            verified, result = commit_user_two_way_signing_durably_v1(
                team_code=code,
                player_id=selected_id,
                expected_authority_fingerprint=fingerprint,
                preferences_override=preferences,
            )
            st.session_state["franchise_simulation_league_state"] = (
                verified.simulation_state
            )
            st.session_state["franchise_trade_league_state"] = verified.trade_state
            st.session_state["franchise_notice"] = (
                f"{result.transaction_id}: signed {result.player_name} to "
                f"{code}'s two-way roster. {result.two_way_contract_count_after}/"
                f"{int(TWO_WAY_MAX)} slots are filled."
            )
        except Exception as exc:
            st.error(f"Two-way signing was not committed. Detail: {exc}")
        else:
            st.rerun()
