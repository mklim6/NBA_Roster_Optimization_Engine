from __future__ import annotations

import copy
import math
import re
from dataclasses import asdict, dataclass
from typing import Any

from freeform_trade_machine_engine_v3 import (
    RuntimeData,
    normalize_player_id,
    normalize_team,
    to_bool,
    to_float,
)


PLAYER_CONTRACT_BRIDGE_VERSION = (
    "franchise-player-contract-bridge-v1.1-cached-market-2026-08-12"
)
BASE_LEAGUE_YEAR = "2026-27"
MODELED_ACQUISITION_AGGREGATION_DAYS = 60
MODELED_NEW_SIGNING_RESTRICTION_DAYS = 90
MODELED_EXTENSION_RESTRICTION_DAYS = 180


class FranchisePlayerContractBridgeError(RuntimeError):
    """Raised when live franchise player-contract eligibility cannot be modeled safely."""


@dataclass(frozen=True)
class FranchisePlayerContractProfile:
    player_id: str
    player_name: str
    team: str
    roster_status: str
    contract_status: str
    generated_player: bool
    synthetic: bool
    two_way: bool
    salary: float | None
    years_remaining: int | None
    option_type: str
    guaranteed: bool | None
    draft_year: int | None
    contract_model: str
    trade_eligible: bool
    aggregation_restricted: bool
    consent_required: bool
    trade_bonus_active: bool
    poison_pill_active: bool
    base_year_compensation_active: bool
    sign_and_trade_active: bool
    extend_and_trade_restricted: bool
    restriction_reason: str
    status: str
    confidence: str
    source: str


@dataclass(frozen=True)
class FranchisePlayerContractSnapshot:
    version: str
    season_label: str
    phase: str
    current_day_index: int
    profiles: tuple[FranchisePlayerContractProfile, ...]


@dataclass(frozen=True)
class FranchisePlayerContractCheck:
    status: str
    code: str
    message: str
    team: str = ""
    player_id: str = ""


@dataclass(frozen=True)
class FranchisePlayerContractTradeEvaluation:
    version: str
    season_label: str
    status: str
    checks: tuple[FranchisePlayerContractCheck, ...]
    selected_profiles: tuple[FranchisePlayerContractProfile, ...]
    source: str


_STATUS_PRIORITY = {"pass": 0, "manual_review": 1, "blocked": 2}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bool_attr(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    parsed = to_bool(value)
    return parsed if isinstance(parsed, bool) else None


def _season_start(season_label: str) -> int:
    match = re.fullmatch(r"(\d{4})-(\d{2}|\d{4})", _clean(season_label))
    if not match:
        raise FranchisePlayerContractBridgeError(
            f"Unsupported franchise season label: {season_label!r}."
        )
    start = int(match.group(1))
    suffix = match.group(2)
    end = int(suffix) if len(suffix) == 4 else (start // 100) * 100 + int(suffix)
    if end < start:
        end += 100
    if end != start + 1:
        raise FranchisePlayerContractBridgeError(
            f"Season label is not a one-year NBA season: {season_label!r}."
        )
    return start


def _phase(state: Any) -> str:
    value = getattr(getattr(state, "phase", ""), "value", getattr(state, "phase", ""))
    return _clean(value).lower()


def _current_day(state: Any) -> int:
    value = _int_or_none(getattr(state, "current_day_index", 0))
    return max(0, value or 0)


def _free_agent_ids(state: Any) -> set[str]:
    return {
        normalize_player_id(player_id)
        for player_id in getattr(state, "free_agent_player_ids", ())
        if normalize_player_id(player_id)
    }


def _runtime_league_year(runtime: RuntimeData) -> str:
    return _clean(getattr(runtime, "rules", {}).get("league_year"))


def _normalized_status(value: Any) -> str:
    return _clean(value).lower().replace("-", "_").replace(" ", "_")


def _event_day(record: Any) -> int | None:
    if isinstance(record, dict):
        for key in ("day_index", "transaction_day_index", "signed_day_index", "event_day_index"):
            if key in record:
                value = _int_or_none(record.get(key))
                if value is not None:
                    return value
    else:
        for key in ("day_index", "transaction_day_index", "signed_day_index", "event_day_index"):
            value = _int_or_none(getattr(record, key, None))
            if value is not None:
                return value
    return None


def _event_value(record: Any, key: str, default: Any = None) -> Any:
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _history_records(state: Any, *names: str) -> list[Any]:
    rows: list[Any] = []
    for name in names:
        value = getattr(state, name, None)
        if isinstance(value, (list, tuple)):
            rows.extend(value)
    return rows


def _transaction_acquisition_day(
    state: Any,
    player_id: str,
    current_team: str,
    season_label: str,
) -> int | None:
    latest: int | None = None
    histories = _history_records(
        state,
        "franchise_transaction_history_v1",
        "franchise_transaction_history",
    )
    for record in histories:
        record_season = _clean(
            _event_value(record, "season_label", _event_value(record, "season", ""))
        )
        if record_season and record_season != season_label:
            continue
        day = _event_day(record)
        if day is None:
            continue
        team_a = normalize_team(_event_value(record, "team_a", ""))
        team_b = normalize_team(_event_value(record, "team_b", ""))
        side_a = {
            normalize_player_id(x)
            for x in (_event_value(record, "side_a_player_ids", ()) or ())
            if normalize_player_id(x)
        }
        side_b = {
            normalize_player_id(x)
            for x in (_event_value(record, "side_b_player_ids", ()) or ())
            if normalize_player_id(x)
        }
        acquired = (
            player_id in side_a and current_team == team_b
        ) or (
            player_id in side_b and current_team == team_a
        )
        if acquired:
            latest = day if latest is None else max(latest, day)
    return latest


def _contract_event_context(
    state: Any,
    player_id: str,
    season_label: str,
) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    latest_day = -1
    histories = _history_records(
        state,
        "franchise_contract_transaction_history_v1",
        "franchise_contract_history_v1",
        "franchise_contract_history",
    )
    for record in histories:
        rid = normalize_player_id(_event_value(record, "player_id", ""))
        if rid != player_id:
            continue
        record_season = _clean(
            _event_value(record, "season_label", _event_value(record, "season", ""))
        )
        if record_season and record_season != season_label:
            continue
        day = _event_day(record)
        if day is None:
            continue
        if day >= latest_day:
            latest_day = day
            latest = {
                "day_index": day,
                "event_type": _normalized_status(_event_value(record, "event_type", "")),
                "extend_and_trade_restricted": bool(
                    _bool_attr(_event_value(record, "extend_and_trade_restricted", False))
                ),
            }
    return latest


def _explicit_flag(player: Any, contract: Any, names: tuple[str, ...]) -> bool | None:
    for owner in (player, contract):
        if owner is None:
            continue
        for name in names:
            if hasattr(owner, name):
                parsed = _bool_attr(getattr(owner, name))
                if parsed is not None:
                    return parsed
    return None


def _explicit_number(player: Any, contract: Any, names: tuple[str, ...]) -> float | None:
    for owner in (player, contract):
        if owner is None:
            continue
        for name in names:
            if hasattr(owner, name):
                value = _finite(getattr(owner, name))
                if value is not None:
                    return value
    return None


def _combine_status(statuses: list[str]) -> str:
    if not statuses:
        return "pass"
    return max(
        (_normalized_status(status) for status in statuses),
        key=lambda value: _STATUS_PRIORITY.get(value, 1),
    )


def _anchor_profile(
    runtime: RuntimeData,
    state: Any,
    player_id: str,
    player: Any,
    *,
    team: str,
    roster_status: str,
    generated: bool,
    contract: Any,
) -> FranchisePlayerContractProfile | None:
    if generated or _runtime_league_year(runtime) != BASE_LEAGUE_YEAR:
        return None
    decision = getattr(runtime, "player_cba_by_id", {}).get(player_id)
    if not isinstance(decision, dict):
        return None

    trade_eligible = to_bool(decision.get("trade_eligible_on_trade_date")) is not False
    aggregation = to_bool(decision.get("aggregation_restricted_on_trade_date")) is True
    consent = (
        to_bool(decision.get("trade_consent_required")) is True
        or to_bool(decision.get("no_trade_clause_active")) is True
    )
    trade_bonus = (
        (to_float(decision.get("trade_bonus_percent")) or 0.0) > 0
        and (to_float(decision.get("remaining_trade_bonus_amount")) or 0.0) > 0
    )
    poison = to_bool(decision.get("poison_pill_active")) is True
    byc = to_bool(decision.get("base_year_compensation_active")) is True
    sign_and_trade = to_bool(decision.get("sign_and_trade_player")) is True
    extend_restricted = to_bool(decision.get("extend_and_trade_restriction_active")) is True
    two_way = bool(getattr(player, "two_way", False)) or to_bool(decision.get("two_way_contract_active")) is True
    manual = (
        to_bool(decision.get("manual_review_required")) is True
        or _normalized_status(decision.get("player_cba_evidence_determination")) == "manual_review_required"
        or consent
        or trade_bonus
        or byc
        or sign_and_trade
        or two_way
    )

    if not trade_eligible or extend_restricted:
        status = "blocked"
    elif manual:
        status = "manual_review"
    else:
        status = "pass"

    return FranchisePlayerContractProfile(
        player_id=player_id,
        player_name=_clean(getattr(player, "player_name", "")) or player_id,
        team=team,
        roster_status=roster_status,
        contract_status=_clean(getattr(contract, "status", "")) if contract is not None else "",
        generated_player=generated,
        synthetic=bool(getattr(player, "synthetic", False)),
        two_way=two_way,
        salary=_finite(getattr(contract, "salary", None)) if contract is not None else None,
        years_remaining=_int_or_none(getattr(contract, "years_remaining", None)) if contract is not None else None,
        option_type=_clean(getattr(contract, "option_type", "")) if contract is not None else "",
        guaranteed=getattr(contract, "guaranteed", None) if contract is not None else None,
        draft_year=_int_or_none(getattr(player, "draft_year", None)),
        contract_model=_clean(decision.get("contract_type")) or "verified_2026_27_contract",
        trade_eligible=trade_eligible,
        aggregation_restricted=aggregation,
        consent_required=consent,
        trade_bonus_active=trade_bonus,
        poison_pill_active=poison,
        base_year_compensation_active=byc,
        sign_and_trade_active=sign_and_trade,
        extend_and_trade_restricted=extend_restricted,
        restriction_reason=_clean(decision.get("evidence_summary")),
        status=status,
        confidence="verified_anchor",
        source="verified_2026_27_player_cba_release",
    )


def _future_profile(
    runtime: RuntimeData,
    state: Any,
    player_id: str,
    player: Any,
    *,
    season_label: str,
    free_agents: set[str],
) -> FranchisePlayerContractProfile:
    team = normalize_team(getattr(player, "team_abbreviation", ""))
    roster_status = "free_agent" if player_id in free_agents or not team else "rostered"
    contract = getattr(player, "contract", None)
    contract_status = _normalized_status(getattr(contract, "status", "")) if contract is not None else ""
    salary = _finite(getattr(contract, "salary", None)) if contract is not None else None
    years = _int_or_none(getattr(contract, "years_remaining", None)) if contract is not None else None
    option = _clean(getattr(contract, "option_type", "")) if contract is not None else ""
    guaranteed = getattr(contract, "guaranteed", None) if contract is not None else None
    generated = player_id not in getattr(runtime, "trade_by_id", {}) or bool(
        _clean(getattr(player, "draft_class_id", ""))
    )
    synthetic = bool(getattr(player, "synthetic", False))
    two_way = bool(getattr(player, "two_way", False))
    draft_year = _int_or_none(getattr(player, "draft_year", None))
    current_day = _current_day(state)
    season_start = _season_start(season_label)

    explicit_trade_eligible = _explicit_flag(
        player,
        contract,
        ("trade_eligible", "trade_eligible_on_trade_date", "franchise_trade_eligible"),
    )
    explicit_aggregation = _explicit_flag(
        player,
        contract,
        ("aggregation_restricted", "aggregation_restricted_on_trade_date"),
    )
    consent = bool(
        _explicit_flag(player, contract, ("trade_consent_required", "no_trade_clause_active"))
    )
    trade_bonus_pct = _explicit_number(player, contract, ("trade_bonus_percent",)) or 0.0
    remaining_bonus = _explicit_number(player, contract, ("remaining_trade_bonus_amount",))
    trade_bonus = trade_bonus_pct > 0 and (remaining_bonus is None or remaining_bonus > 0)
    poison = bool(_explicit_flag(player, contract, ("poison_pill_active",)))
    byc = bool(_explicit_flag(player, contract, ("base_year_compensation_active",)))
    sign_and_trade = bool(_explicit_flag(player, contract, ("sign_and_trade_player",)))
    extend_restricted = bool(
        _explicit_flag(player, contract, ("extend_and_trade_restriction_active",))
    )

    acquired_day = _transaction_acquisition_day(state, player_id, team, season_label)
    history_aggregation = (
        acquired_day is not None
        and 0 <= current_day - acquired_day < MODELED_ACQUISITION_AGGREGATION_DAYS
    )
    aggregation = bool(explicit_aggregation) or history_aggregation

    contract_event = _contract_event_context(state, player_id, season_label)
    event_day = _int_or_none(contract_event.get("day_index")) if contract_event else None
    event_type = _normalized_status(contract_event.get("event_type")) if contract_event else ""
    signing_restricted = (
        event_day is not None
        and event_type in {"signing", "free_agent_signing", "re_signing", "resigning"}
        and 0 <= current_day - event_day < MODELED_NEW_SIGNING_RESTRICTION_DAYS
    )
    extension_history_restricted = (
        event_day is not None
        and bool(contract_event.get("extend_and_trade_restricted"))
        and 0 <= current_day - event_day < MODELED_EXTENSION_RESTRICTION_DAYS
    )
    extend_restricted = extend_restricted or extension_history_restricted

    reasons: list[str] = []
    statuses: list[str] = []

    invalid_contract_statuses = {
        "free_agent_pool",
        "free_agent",
        "expired",
        "retired",
        "waived",
        "simulation_replacement",
    }
    if roster_status != "rostered":
        statuses.append("blocked")
        reasons.append("player is not on a live team roster")
    if synthetic:
        statuses.append("blocked")
        reasons.append("synthetic simulation replacement players are not tradable assets")
    if contract is None:
        statuses.append("manual_review")
        reasons.append("live player has no contract object")
    elif contract_status in invalid_contract_statuses:
        statuses.append("blocked")
        reasons.append(f"contract status is {contract_status or 'invalid'}")
    elif not contract_status:
        statuses.append("manual_review")
        reasons.append("live contract status is missing")

    if explicit_trade_eligible is False:
        statuses.append("blocked")
        reasons.append("live contract explicitly marks the player not trade-eligible")
    if signing_restricted:
        statuses.append("blocked")
        reasons.append(
            f"modeled new-signing restriction remains active for {MODELED_NEW_SIGNING_RESTRICTION_DAYS} franchise days"
        )
    if extend_restricted:
        statuses.append("blocked")
        reasons.append("extend-and-trade restriction is active")
    if consent:
        statuses.append("manual_review")
        reasons.append("player consent or a no-trade clause must be resolved")
    if trade_bonus:
        statuses.append("manual_review")
        reasons.append("active trade-bonus waiver/allocation mechanics require review")
    if byc:
        statuses.append("manual_review")
        reasons.append("base-year compensation treatment is active")
    if sign_and_trade:
        statuses.append("manual_review")
        reasons.append("sign-and-trade treatment is active")
    if two_way:
        statuses.append("manual_review")
        reasons.append("two-way contract requires dedicated trade treatment")
    if poison:
        statuses.append("manual_review")
        reasons.append("poison-pill asymmetric salary treatment requires dedicated future modeling")

    if draft_year is not None and draft_year > season_start and roster_status == "rostered":
        statuses.append("blocked")
        reasons.append("player is rostered before their recorded draft year")

    # A drafted rookie activated into an opened NBA season has already passed the
    # 30-day post-signing rookie wait in the franchise calendar. Drafted players
    # remain non-rostered prospects until the next season opens, so V1 does not
    # invent a second in-season rookie waiting period.
    if generated and draft_year is not None and draft_year == season_start:
        draft_round = _int_or_none(getattr(player, "draft_round", None))
        if (
            draft_round == 2
            or option == "second_round_exception_team_option"
        ):
            contract_model = "live_generated_second_round_exception_contract"
            source = "live_generated_second_round_exception_contract_state"
        else:
            contract_model = "live_generated_rookie_scale_contract"
            source = "live_generated_rookie_contract_state"
    elif generated:
        contract_model = "simulated_generated_player_contract"
        source = "simulated_future_generated_contract_state"
    else:
        contract_model = "simulated_future_veteran_contract"
        source = "simulated_future_baseline_contract_state"

    if acquired_day is not None:
        source += "+franchise_transaction_history"
    if contract_event:
        source += "+franchise_contract_history"

    status = _combine_status(statuses)
    if not statuses:
        status = "pass"
        reasons.append(
            "live future-season contract has no active modeled player-level trade restriction"
        )
    elif status == "pass":
        reasons.append("no active modeled player-level trade restriction")

    return FranchisePlayerContractProfile(
        player_id=player_id,
        player_name=_clean(getattr(player, "player_name", "")) or player_id,
        team=team,
        roster_status=roster_status,
        contract_status=_clean(getattr(contract, "status", "")) if contract is not None else "",
        generated_player=generated,
        synthetic=synthetic,
        two_way=two_way,
        salary=salary,
        years_remaining=years,
        option_type=option,
        guaranteed=guaranteed,
        draft_year=draft_year,
        contract_model=contract_model,
        trade_eligible=(status != "blocked"),
        aggregation_restricted=aggregation,
        consent_required=consent,
        trade_bonus_active=trade_bonus,
        poison_pill_active=poison,
        base_year_compensation_active=byc,
        sign_and_trade_active=sign_and_trade,
        extend_and_trade_restricted=extend_restricted,
        restriction_reason="; ".join(dict.fromkeys(reasons)),
        status=status,
        confidence=(
            "live_state_plus_history"
            if acquired_day is not None or contract_event
            else "simulated_from_live_contract_state"
        ),
        source=source,
    )


def build_franchise_player_contract_snapshot(
    runtime: RuntimeData,
    state: Any,
) -> FranchisePlayerContractSnapshot:
    before = copy.deepcopy(state)
    players = getattr(state, "players", {})
    if not isinstance(players, dict):
        raise FranchisePlayerContractBridgeError(
            "Live franchise state does not expose a player dictionary."
        )

    season_label = _clean(getattr(getattr(state, "settings", None), "season_label", ""))
    _season_start(season_label)
    free_agents = _free_agent_ids(state)
    profiles: list[FranchisePlayerContractProfile] = []

    for raw_id, player in players.items():
        player_id = normalize_player_id(raw_id)
        if not player_id:
            continue
        team = normalize_team(getattr(player, "team_abbreviation", ""))
        roster_status = "free_agent" if player_id in free_agents or not team else "rostered"
        contract = getattr(player, "contract", None)
        generated = player_id not in getattr(runtime, "trade_by_id", {}) or bool(
            _clean(getattr(player, "draft_class_id", ""))
        )

        anchor = None
        if season_label == BASE_LEAGUE_YEAR:
            anchor = _anchor_profile(
                runtime,
                state,
                player_id,
                player,
                team=team,
                roster_status=roster_status,
                generated=generated,
                contract=contract,
            )
        profiles.append(
            anchor
            if anchor is not None
            else _future_profile(
                runtime,
                state,
                player_id,
                player,
                season_label=season_label,
                free_agents=free_agents,
            )
        )

    try:
        unchanged = state == before
    except Exception:
        unchanged = repr(state) == repr(before)
    if not unchanged:
        raise FranchisePlayerContractBridgeError(
            "Player-contract snapshot construction mutated the live franchise state."
        )

    return FranchisePlayerContractSnapshot(
        version=PLAYER_CONTRACT_BRIDGE_VERSION,
        season_label=season_label,
        phase=_phase(state),
        current_day_index=_current_day(state),
        profiles=tuple(profiles),
    )


def _selected_checks(
    snapshot: FranchisePlayerContractSnapshot,
    *,
    team: str,
    player_ids: tuple[str, ...],
) -> tuple[list[FranchisePlayerContractCheck], list[FranchisePlayerContractProfile]]:
    resolved = normalize_team(team)
    pmap = {profile.player_id: profile for profile in snapshot.profiles}
    checks: list[FranchisePlayerContractCheck] = []
    selected: list[FranchisePlayerContractProfile] = []

    for player_id in player_ids:
        normalized = normalize_player_id(player_id)
        profile = pmap.get(normalized)
        if profile is None:
            checks.append(
                FranchisePlayerContractCheck(
                    "blocked",
                    "future_player_contract_profile_missing",
                    f"{normalized or player_id} is missing from the future player-contract snapshot.",
                    resolved,
                    normalized,
                )
            )
            continue
        selected.append(profile)
        if profile.team != resolved or profile.roster_status != "rostered":
            checks.append(
                FranchisePlayerContractCheck(
                    "blocked",
                    "future_player_contract_owner_mismatch",
                    f"{profile.player_name} is not a rostered {resolved} player in the contract bridge.",
                    resolved,
                    normalized,
                )
            )
            continue

        if profile.status == "blocked":
            checks.append(
                FranchisePlayerContractCheck(
                    "blocked",
                    "future_player_contract_not_trade_eligible",
                    f"{profile.player_name} is blocked by the player-contract bridge: {profile.restriction_reason}.",
                    resolved,
                    normalized,
                )
            )
        elif profile.aggregation_restricted and len(player_ids) > 1:
            checks.append(
                FranchisePlayerContractCheck(
                    "blocked",
                    "future_player_aggregation_restricted",
                    f"{profile.player_name} may be retraded alone but cannot be aggregated with another outgoing player under the live franchise restriction history.",
                    resolved,
                    normalized,
                )
            )
        elif profile.status == "manual_review":
            checks.append(
                FranchisePlayerContractCheck(
                    "manual_review",
                    "future_player_contract_manual_review",
                    f"{profile.player_name} requires player-contract review: {profile.restriction_reason}.",
                    resolved,
                    normalized,
                )
            )
        elif profile.aggregation_restricted:
            checks.append(
                FranchisePlayerContractCheck(
                    "pass",
                    "future_player_contract_conditional_pass",
                    f"{profile.player_name} is trade-eligible as the sole outgoing player; an active aggregation restriction is preserved.",
                    resolved,
                    normalized,
                )
            )
        else:
            checks.append(
                FranchisePlayerContractCheck(
                    "pass",
                    "future_player_contract_pass",
                    f"{profile.player_name} has no active player-level trade restriction in the {snapshot.season_label} franchise contract model.",
                    resolved,
                    normalized,
                )
            )

    return checks, selected


def evaluate_franchise_player_contract_trade(
    runtime: RuntimeData,
    state: Any,
    *,
    team_a: str,
    team_b: str,
    side_a_player_ids: tuple[str, ...],
    side_b_player_ids: tuple[str, ...],
    snapshot: FranchisePlayerContractSnapshot | None = None,
    verify_nonmutation: bool = True,
) -> FranchisePlayerContractTradeEvaluation:
    # Normal Trade Builder/commit callers keep the defensive deep-copy path.
    # Bulk Trade Finder routing may reuse one immutable contract snapshot and
    # rely on the outer Trade Finder state fingerprint instead.
    before = copy.deepcopy(state) if verify_nonmutation else None
    if snapshot is None:
        snapshot = build_franchise_player_contract_snapshot(runtime, state)
    checks_a, selected_a = _selected_checks(
        snapshot,
        team=team_a,
        player_ids=tuple(normalize_player_id(x) for x in side_a_player_ids if normalize_player_id(x)),
    )
    checks_b, selected_b = _selected_checks(
        snapshot,
        team=team_b,
        player_ids=tuple(normalize_player_id(x) for x in side_b_player_ids if normalize_player_id(x)),
    )
    checks = checks_a + checks_b

    if verify_nonmutation:
        try:
            unchanged = state == before
        except Exception:
            unchanged = repr(state) == repr(before)
        if not unchanged:
            raise FranchisePlayerContractBridgeError(
                "Player-contract trade evaluation mutated the live franchise state."
            )

    return FranchisePlayerContractTradeEvaluation(
        version=PLAYER_CONTRACT_BRIDGE_VERSION,
        season_label=snapshot.season_label,
        status=_combine_status([check.status for check in checks]),
        checks=tuple(checks),
        selected_profiles=tuple(selected_a + selected_b),
        source=(
            "verified_2026_27_player_cba_plus_live_state"
            if snapshot.season_label == BASE_LEAGUE_YEAR
            else "simulated_future_player_contract_state_plus_live_franchise_history"
        ),
    )


def snapshot_to_dict(snapshot: FranchisePlayerContractSnapshot) -> dict[str, Any]:
    return asdict(snapshot)


def player_contract_trade_to_dict(
    evaluation: FranchisePlayerContractTradeEvaluation,
) -> dict[str, Any]:
    return asdict(evaluation)
