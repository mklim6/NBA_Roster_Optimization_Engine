from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from freeform_trade_machine_engine_v3 import (
    RuntimeData,
    Status,
    TradeRequest,
    TradeSideRequest,
    evaluate_trade,
    normalize_player_id,
    normalize_team,
)
from franchise_live_asset_ledger_v1 import (
    FranchiseAssetLedger,
    build_live_asset_ledger,
)
from franchise_financial_cba_bridge_v1 import (
    FINANCIAL_BRIDGE_VERSION,
    evaluate_franchise_financial_trade,
    financial_trade_to_dict,
)
from franchise_player_contract_bridge_v1 import (
    PLAYER_CONTRACT_BRIDGE_VERSION,
    evaluate_franchise_player_contract_trade,
    player_contract_trade_to_dict,
)
from franchise_draft_right_stepien_bridge_v1 import (
    DRAFT_RIGHT_BRIDGE_VERSION,
    evaluate_franchise_draft_right_trade,
    draft_right_trade_to_dict,
)


EMBEDDED_TRADE_CENTER_VERSION = (
    "franchise-embedded-trade-center-v2.1-anchor-financial-resolution-2026-08-13"
)


class FranchiseTradeCenterError(RuntimeError):
    """Raised when a live franchise trade package cannot be previewed safely."""


@dataclass(frozen=True)
class FranchiseTradeCheck:
    status: str
    code: str
    message: str
    team: str = ""
    asset_id: str = ""


@dataclass(frozen=True)
class FranchiseTradeSidePreview:
    team: str
    player_ids: tuple[str, ...]
    pick_asset_ids: tuple[str, ...]
    outgoing_salary: float
    incoming_salary: float
    roster_players_before: int
    roster_players_after: int
    generated_player_count: int
    engine_covered_player_count: int
    engine_ready_pick_count: int


@dataclass(frozen=True)
class FranchiseTradePreview:
    version: str
    season_label: str
    status: str
    can_commit: bool
    side_a: FranchiseTradeSidePreview
    side_b: FranchiseTradeSidePreview
    checks: tuple[FranchiseTradeCheck, ...] = field(default_factory=tuple)
    canonical_engine_invoked: bool = False
    canonical_engine_status: str = "not_run"
    canonical_engine_payload: dict[str, Any] | None = None
    financial_bridge_invoked: bool = False
    financial_bridge_status: str = "not_run"
    financial_bridge_payload: dict[str, Any] | None = None
    financial_bridge_version: str = FINANCIAL_BRIDGE_VERSION
    anchor_financial_resolution_applied: bool = False
    player_contract_bridge_invoked: bool = False
    player_contract_bridge_status: str = "not_run"
    player_contract_bridge_payload: dict[str, Any] | None = None
    player_contract_bridge_version: str = PLAYER_CONTRACT_BRIDGE_VERSION
    draft_right_bridge_invoked: bool = False
    draft_right_bridge_status: str = "not_run"
    draft_right_bridge_payload: dict[str, Any] | None = None
    draft_right_bridge_version: str = DRAFT_RIGHT_BRIDGE_VERSION
    package_fingerprint: str = ""


_STATUS_PRIORITY = {
    "pass": 0,
    "manual_review": 1,
    "blocked": 2,
}


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _status(value: Any) -> str:
    resolved = getattr(value, "value", value)
    text = _clean_text(resolved).lower()
    if text in _STATUS_PRIORITY:
        return text
    return "manual_review"


def _combine(checks: list[FranchiseTradeCheck]) -> str:
    if not checks:
        return "pass"
    return max(
        (_status(check.status) for check in checks),
        key=lambda item: _STATUS_PRIORITY[item],
    )


def _season_label(state: Any) -> str:
    return _clean_text(getattr(getattr(state, "settings", None), "season_label", ""))


def _runtime_league_year(runtime: RuntimeData) -> str:
    return _clean_text(runtime.rules.get("league_year"))


def _live_player_lookup(ledger: FranchiseAssetLedger) -> dict[str, dict[str, Any]]:
    return {str(row["player_id"]): dict(row) for row in ledger.player_rows}


def _live_pick_lookup(ledger: FranchiseAssetLedger) -> dict[str, dict[str, Any]]:
    return {str(row["asset_id"]): dict(row) for row in ledger.draft_rows}


def _team_roster_ids(state: Any, team: str) -> tuple[str, ...]:
    resolved = normalize_team(team)
    teams = getattr(state, "teams", {})
    record = teams.get(resolved)
    if record is None:
        return ()
    return tuple(
        normalize_player_id(player_id)
        for player_id in getattr(record, "roster_player_ids", ())
        if normalize_player_id(player_id)
    )


def _live_salary(player_row: dict[str, Any]) -> float | None:
    try:
        value = float(player_row.get("salary"))
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _selected_salary(
    player_ids: tuple[str, ...],
    player_lookup: dict[str, dict[str, Any]],
) -> tuple[float, bool]:
    total = 0.0
    complete = True
    for player_id in player_ids:
        row = player_lookup.get(player_id, {})
        salary = _live_salary(row)
        if salary is None:
            complete = False
        else:
            total += salary
    return round(total, 2), complete


def _future_player_bridge_required(runtime: RuntimeData, row: dict[str, Any]) -> bool:
    player_id = normalize_player_id(row.get("player_id"))
    if not player_id:
        return True
    if bool(row.get("generated_player")):
        return True
    if player_id not in runtime.trade_by_id:
        return True
    if player_id not in runtime.player_cba_by_id:
        return True
    return False


def _player_engine_covered(runtime: RuntimeData, row: dict[str, Any]) -> bool:
    return not _future_player_bridge_required(runtime, row)


def _ownership_checks(
    *,
    state: Any,
    ledger: FranchiseAssetLedger,
    team: str,
    player_ids: tuple[str, ...],
    pick_asset_ids: tuple[str, ...],
) -> list[FranchiseTradeCheck]:
    checks: list[FranchiseTradeCheck] = []
    resolved = normalize_team(team)
    player_lookup = _live_player_lookup(ledger)
    pick_lookup = _live_pick_lookup(ledger)
    roster_ids = set(_team_roster_ids(state, resolved))

    for player_id in player_ids:
        row = player_lookup.get(player_id)
        if row is None:
            checks.append(
                FranchiseTradeCheck(
                    "blocked",
                    "player_not_in_live_ledger",
                    f"{player_id} is not present in the live franchise player ledger.",
                    resolved,
                    player_id,
                )
            )
            continue
        if row.get("roster_status") != "rostered" or player_id not in roster_ids:
            checks.append(
                FranchiseTradeCheck(
                    "blocked",
                    "player_not_rostered_by_team",
                    f"{row.get('player_name', player_id)} is not a rostered {resolved} player in the live state.",
                    resolved,
                    player_id,
                )
            )
        elif normalize_team(row.get("team")) != resolved:
            checks.append(
                FranchiseTradeCheck(
                    "blocked",
                    "player_live_owner_mismatch",
                    f"{row.get('player_name', player_id)} is assigned to {row.get('team')}, not {resolved}, in the live ledger.",
                    resolved,
                    player_id,
                )
            )
        else:
            checks.append(
                FranchiseTradeCheck(
                    "pass",
                    "player_live_ownership_verified",
                    f"Live ownership verified for {row.get('player_name', player_id)}.",
                    resolved,
                    player_id,
                )
            )

    for asset_id in pick_asset_ids:
        row = pick_lookup.get(asset_id)
        if row is None:
            checks.append(
                FranchiseTradeCheck(
                    "blocked",
                    "pick_not_in_live_ledger",
                    f"{asset_id} is not present in the live Draft Capital ledger.",
                    resolved,
                    asset_id,
                )
            )
            continue
        if normalize_team(row.get("current_owner")) != resolved:
            checks.append(
                FranchiseTradeCheck(
                    "blocked",
                    "pick_live_owner_mismatch",
                    f"{row.get('display_name', asset_id)} is owned by {row.get('current_owner')}, not {resolved}.",
                    resolved,
                    asset_id,
                )
            )
        else:
            checks.append(
                FranchiseTradeCheck(
                    "pass",
                    "pick_live_ownership_verified",
                    f"Live draft-right ownership verified for {row.get('display_name', asset_id)}. Franchise Draft Right / Stepien Bridge V1 will determine package legality.",
                    resolved,
                    asset_id,
                )
            )
    return checks


def _player_coverage_checks(
    *,
    runtime: RuntimeData,
    ledger: FranchiseAssetLedger,
    team: str,
    player_ids: tuple[str, ...],
) -> list[FranchiseTradeCheck]:
    checks: list[FranchiseTradeCheck] = []
    lookup = _live_player_lookup(ledger)
    resolved = normalize_team(team)
    for player_id in player_ids:
        row = lookup.get(player_id, {})
        name = row.get("player_name", player_id)
        if _future_player_bridge_required(runtime, row):
            reason = (
                "generated/drafted franchise player"
                if bool(row.get("generated_player"))
                else "player is not fully covered by the 2026-27 trade and player-CBA releases"
            )
            checks.append(
                FranchiseTradeCheck(
                    "manual_review",
                    "future_player_cba_bridge_required",
                    f"{name} is a {reason}. Live salary and ownership are available, but future fictional contract mechanics must be modeled before deterministic CBA release.",
                    resolved,
                    player_id,
                )
            )
        else:
            checks.append(
                FranchiseTradeCheck(
                    "pass",
                    "baseline_player_engine_evidence_available",
                    f"{name} is covered by the baseline Trade Machine and player-CBA evidence releases.",
                    resolved,
                    player_id,
                )
            )
    return checks


def _salary_checks(
    *,
    player_lookup: dict[str, dict[str, Any]],
    team_a: str,
    team_b: str,
    side_a_players: tuple[str, ...],
    side_b_players: tuple[str, ...],
) -> tuple[list[FranchiseTradeCheck], float, float]:
    checks: list[FranchiseTradeCheck] = []
    salary_a, complete_a = _selected_salary(side_a_players, player_lookup)
    salary_b, complete_b = _selected_salary(side_b_players, player_lookup)
    if complete_a:
        checks.append(
            FranchiseTradeCheck(
                "pass",
                "side_a_live_salaries_available",
                f"{team_a} live outgoing salary is ${salary_a:,.0f}.",
                team_a,
            )
        )
    else:
        checks.append(
            FranchiseTradeCheck(
                "manual_review",
                "side_a_live_salary_missing",
                f"At least one {team_a} outgoing player is missing a live contract salary.",
                team_a,
            )
        )
    if complete_b:
        checks.append(
            FranchiseTradeCheck(
                "pass",
                "side_b_live_salaries_available",
                f"{team_b} live outgoing salary is ${salary_b:,.0f}.",
                team_b,
            )
        )
    else:
        checks.append(
            FranchiseTradeCheck(
                "manual_review",
                "side_b_live_salary_missing",
                f"At least one {team_b} outgoing player is missing a live contract salary.",
                team_b,
            )
        )
    return checks, salary_a, salary_b


def _canonical_pick_ids(
    ledger: FranchiseAssetLedger,
    asset_ids: tuple[str, ...],
) -> tuple[str, ...] | None:
    lookup = _live_pick_lookup(ledger)
    result: list[str] = []
    for asset_id in asset_ids:
        row = lookup.get(asset_id)
        if not row or not bool(row.get("engine_ready")):
            return None
        canonical = _clean_text(row.get("canonical_pick_right_id"))
        if not canonical:
            return None
        result.append(canonical)
    return tuple(result)


def _canonical_engine_eligible(
    runtime: RuntimeData,
    ledger: FranchiseAssetLedger,
    season_label: str,
    side_a_players: tuple[str, ...],
    side_b_players: tuple[str, ...],
    side_a_picks: tuple[str, ...],
    side_b_picks: tuple[str, ...],
) -> tuple[bool, str]:
    engine_year = _runtime_league_year(runtime)
    if not engine_year or season_label != engine_year:
        return False, (
            f"The verified full-CBA runtime is for {engine_year or 'an unknown league year'}, "
            f"while the live franchise is in {season_label}. Franchise-native financial and "
            "player-contract bridges can evaluate their portions, but the historical canonical "
            "runtime itself is not a season-current final release."
        )
    player_lookup = _live_player_lookup(ledger)
    if any(
        not _player_engine_covered(runtime, player_lookup.get(player_id, {}))
        for player_id in (*side_a_players, *side_b_players)
    ):
        return False, "At least one selected player is not fully covered by the canonical player-CBA runtime."
    if _canonical_pick_ids(ledger, side_a_picks) is None or _canonical_pick_ids(ledger, side_b_picks) is None:
        return False, "At least one selected draft asset is not mapped to a canonical engine-ready right."
    return True, "Canonical runtime coverage is complete for the selected assets and league year."


def _canonical_preview(
    runtime: RuntimeData,
    ledger: FranchiseAssetLedger,
    team_a: str,
    team_b: str,
    side_a_players: tuple[str, ...],
    side_b_players: tuple[str, ...],
    side_a_picks: tuple[str, ...],
    side_b_picks: tuple[str, ...],
) -> tuple[str, dict[str, Any]]:
    from freeform_trade_machine_engine_v3 import result_to_dict

    pick_a = _canonical_pick_ids(ledger, side_a_picks)
    pick_b = _canonical_pick_ids(ledger, side_b_picks)
    if pick_a is None or pick_b is None:
        raise FranchiseTradeCenterError("Canonical preview was called with an unmapped draft asset.")
    request = TradeRequest(
        side_a=TradeSideRequest(
            team_abbreviation=team_a,
            player_ids=side_a_players,
            pick_right_ids=pick_a,
        ),
        side_b=TradeSideRequest(
            team_abbreviation=team_b,
            player_ids=side_b_players,
            pick_right_ids=pick_b,
        ),
    )
    evaluation = evaluate_trade(runtime, request)
    return _status(evaluation.status), result_to_dict(evaluation)


def _side_preview(
    *,
    runtime: RuntimeData,
    state: Any,
    ledger: FranchiseAssetLedger,
    team: str,
    player_ids: tuple[str, ...],
    pick_asset_ids: tuple[str, ...],
    incoming_salary: float,
) -> FranchiseTradeSidePreview:
    player_lookup = _live_player_lookup(ledger)
    pick_lookup = _live_pick_lookup(ledger)
    outgoing_salary, _ = _selected_salary(player_ids, player_lookup)
    roster_before = len(_team_roster_ids(state, team))
    incoming_count = 0
    # The caller replaces this with its actual incoming player count by creating
    # the dataclass after both sides are known. This helper exists for symmetry.
    generated = sum(bool(player_lookup.get(pid, {}).get("generated_player")) for pid in player_ids)
    covered = sum(_player_engine_covered(runtime, player_lookup.get(pid, {})) for pid in player_ids)
    ready_picks = sum(bool(pick_lookup.get(aid, {}).get("engine_ready")) for aid in pick_asset_ids)
    return FranchiseTradeSidePreview(
        team=normalize_team(team),
        player_ids=player_ids,
        pick_asset_ids=pick_asset_ids,
        outgoing_salary=outgoing_salary,
        incoming_salary=round(incoming_salary, 2),
        roster_players_before=roster_before,
        roster_players_after=roster_before - len(player_ids) + incoming_count,
        generated_player_count=generated,
        engine_covered_player_count=covered,
        engine_ready_pick_count=ready_picks,
    )


def _fingerprint(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_franchise_trade_preview(
    runtime: RuntimeData,
    state: Any,
    trade_state: Any,
    *,
    team_a: str,
    team_b: str,
    side_a_player_ids: tuple[str, ...] = (),
    side_b_player_ids: tuple[str, ...] = (),
    side_a_pick_asset_ids: tuple[str, ...] = (),
    side_b_pick_asset_ids: tuple[str, ...] = (),
    ledger: FranchiseAssetLedger | None = None,
    financial_snapshot: Any | None = None,
    player_contract_snapshot: Any | None = None,
    market_read_only_fast_path: bool = False,
) -> FranchiseTradePreview:
    resolved_a = normalize_team(team_a)
    resolved_b = normalize_team(team_b)
    players_a = tuple(normalize_player_id(x) for x in side_a_player_ids if normalize_player_id(x))
    players_b = tuple(normalize_player_id(x) for x in side_b_player_ids if normalize_player_id(x))
    picks_a = tuple(_clean_text(x) for x in side_a_pick_asset_ids if _clean_text(x))
    picks_b = tuple(_clean_text(x) for x in side_b_pick_asset_ids if _clean_text(x))
    live_ledger = ledger or build_live_asset_ledger(runtime, state, trade_state)
    checks: list[FranchiseTradeCheck] = []

    teams = {normalize_team(team) for team in getattr(state, "teams", {})}
    if not resolved_a or resolved_a not in teams:
        checks.append(FranchiseTradeCheck("blocked", "side_a_team_invalid", f"{resolved_a or '<blank>'} is not a live franchise team.", resolved_a))
    if not resolved_b or resolved_b not in teams:
        checks.append(FranchiseTradeCheck("blocked", "side_b_team_invalid", f"{resolved_b or '<blank>'} is not a live franchise team.", resolved_b))
    if resolved_a and resolved_a == resolved_b:
        checks.append(FranchiseTradeCheck("blocked", "same_team_on_both_sides", "A two-team trade requires two different teams."))
    if not (players_a or picks_a):
        checks.append(FranchiseTradeCheck("blocked", "side_a_empty", f"{resolved_a or 'Side A'} must send at least one asset.", resolved_a))
    if not (players_b or picks_b):
        checks.append(FranchiseTradeCheck("blocked", "side_b_empty", f"{resolved_b or 'Side B'} must send at least one asset.", resolved_b))
    if len(players_a) != len(set(players_a)) or len(players_b) != len(set(players_b)):
        checks.append(FranchiseTradeCheck("blocked", "duplicate_player_asset", "A player cannot appear twice on the same side."))
    if len(picks_a) != len(set(picks_a)) or len(picks_b) != len(set(picks_b)):
        checks.append(FranchiseTradeCheck("blocked", "duplicate_pick_asset", "A draft asset cannot appear twice on the same side."))
    if set(players_a) & set(players_b) or set(picks_a) & set(picks_b):
        checks.append(FranchiseTradeCheck("blocked", "asset_on_both_sides", "The same asset cannot appear on both sides of a trade."))

    if resolved_a in teams:
        checks.extend(_ownership_checks(state=state, ledger=live_ledger, team=resolved_a, player_ids=players_a, pick_asset_ids=picks_a))
    if resolved_b in teams:
        checks.extend(_ownership_checks(state=state, ledger=live_ledger, team=resolved_b, player_ids=players_b, pick_asset_ids=picks_b))

    draft_right_bridge_invoked = False
    draft_right_bridge_status = "not_run"
    draft_right_bridge_payload: dict[str, Any] | None = None
    if (
        resolved_a in teams
        and resolved_b in teams
        and not any(check.status == "blocked" for check in checks)
    ):
        draft_right_bridge_invoked = True
        draft_evaluation = evaluate_franchise_draft_right_trade(
            runtime,
            state,
            trade_state,
            team_a=resolved_a,
            team_b=resolved_b,
            side_a_asset_ids=picks_a,
            side_b_asset_ids=picks_b,
            ledger=live_ledger,
        )
        draft_right_bridge_status = _status(draft_evaluation.status)
        draft_right_bridge_payload = draft_right_trade_to_dict(draft_evaluation)
        for draft_check in draft_evaluation.checks:
            checks.append(
                FranchiseTradeCheck(
                    status=_status(draft_check.status),
                    code=draft_check.code,
                    message=draft_check.message,
                    team=draft_check.team,
                    asset_id=draft_check.asset_id,
                )
            )
        checks.append(
            FranchiseTradeCheck(
                draft_right_bridge_status,
                "franchise_draft_right_stepien_bridge_result",
                (
                    f"Franchise Draft Right / Stepien Bridge V1 returned "
                    f"{draft_right_bridge_status.replace('_', ' ').upper()} "
                    f"for the selected live draft assets in {_season_label(state)}."
                ),
            )
        )

    player_contract_bridge_invoked = False
    player_contract_bridge_status = "not_run"
    player_contract_bridge_payload: dict[str, Any] | None = None
    if not players_a and not players_b:
        player_contract_bridge_status = "pass"
        checks.append(
            FranchiseTradeCheck(
                "pass",
                "player_contract_bridge_not_applicable_no_players",
                "No players are included, so player-specific contract trade restrictions are not applicable.",
            )
        )
    elif (resolved_a in teams and resolved_b in teams and not any(
        check.status == "blocked" for check in checks
    )):
        player_contract_bridge_invoked = True
        contract_evaluation = evaluate_franchise_player_contract_trade(
            runtime,
            state,
            team_a=resolved_a,
            team_b=resolved_b,
            side_a_player_ids=players_a,
            side_b_player_ids=players_b,
            snapshot=player_contract_snapshot,
            verify_nonmutation=not market_read_only_fast_path,
        )
        player_contract_bridge_status = _status(contract_evaluation.status)
        player_contract_bridge_payload = player_contract_trade_to_dict(contract_evaluation)
        for contract_check in contract_evaluation.checks:
            checks.append(
                FranchiseTradeCheck(
                    status=_status(contract_check.status),
                    code=contract_check.code,
                    message=contract_check.message,
                    team=contract_check.team,
                    asset_id=contract_check.player_id,
                )
            )
        checks.append(
            FranchiseTradeCheck(
                player_contract_bridge_status,
                "franchise_player_contract_bridge_result",
                (
                    f"Franchise Player Contract Eligibility Bridge V1 returned "
                    f"{player_contract_bridge_status.replace('_', ' ').upper()} "
                    f"for the selected live-player contract restrictions in "
                    f"{_season_label(state)}."
                ),
            )
        )

    player_lookup = _live_player_lookup(live_ledger)
    salary_checks, salary_a, salary_b = _salary_checks(
        player_lookup=player_lookup,
        team_a=resolved_a,
        team_b=resolved_b,
        side_a_players=players_a,
        side_b_players=players_b,
    )
    checks.extend(salary_checks)

    financial_bridge_invoked = False
    financial_bridge_status = "not_run"
    financial_bridge_payload: dict[str, Any] | None = None
    financial_bridge_nonpass_codes: tuple[str, ...] = ()
    if not players_a and not players_b:
        financial_bridge_status = "pass"
        checks.append(
            FranchiseTradeCheck(
                "pass",
                "financial_bridge_not_applicable_no_players",
                "No player salary changes occur in this draft-right-only package, so salary matching and apron movement are not applicable.",
            )
        )
    elif (resolved_a in teams and resolved_b in teams and not any(
        check.status == "blocked" for check in checks
    )):
        financial_bridge_invoked = True
        financial_evaluation = evaluate_franchise_financial_trade(
            runtime,
            state,
            team_a=resolved_a,
            team_b=resolved_b,
            side_a_player_ids=players_a,
            side_b_player_ids=players_b,
            snapshot=financial_snapshot,
            verify_nonmutation=not market_read_only_fast_path,
        )
        financial_bridge_status = _status(financial_evaluation.status)
        financial_bridge_payload = financial_trade_to_dict(financial_evaluation)
        financial_bridge_nonpass_codes = tuple(
            str(getattr(financial_check, "code", "") or "").strip()
            for financial_check in financial_evaluation.checks
            if _status(getattr(financial_check, "status", "")) != "pass"
            and str(getattr(financial_check, "code", "") or "").strip()
        )
        for financial_check in financial_evaluation.checks:
            checks.append(
                FranchiseTradeCheck(
                    status=_status(financial_check.status),
                    code=financial_check.code,
                    message=financial_check.message,
                    team=financial_check.team,
                )
            )
        checks.append(
            FranchiseTradeCheck(
                financial_bridge_status,
                "franchise_future_financial_bridge_result",
                (
                    f"Franchise Financial / CBA Bridge V1 returned "
                    f"{financial_bridge_status.replace('_', ' ').upper()} "
                    f"for the player salary, roster-count, and apron portion "
                    f"of this { _season_label(state) } package."
                ),
            )
        )

    season = _season_label(state)
    eligible, eligibility_reason = _canonical_engine_eligible(
        runtime,
        live_ledger,
        season,
        players_a,
        players_b,
        picks_a,
        picks_b,
    )
    canonical_invoked = False
    canonical_status = "not_run"
    canonical_payload: dict[str, Any] | None = None

    if eligible and not any(check.status == "blocked" for check in checks):
        canonical_invoked = True
        canonical_status, canonical_payload = _canonical_preview(
            runtime,
            live_ledger,
            resolved_a,
            resolved_b,
            players_a,
            players_b,
            picks_a,
            picks_b,
        )
        checks.append(
            FranchiseTradeCheck(
                canonical_status,
                "canonical_trade_engine_result",
                f"Canonical Trade Machine evaluation returned {canonical_status.replace('_', ' ').upper()} for this fully covered package.",
            )
        )
    else:
        engine_year = _runtime_league_year(runtime)
        native_future_release = bool(
            season
            and engine_year
            and season != engine_year
            and draft_right_bridge_status == "pass"
            and player_contract_bridge_status == "pass"
            and financial_bridge_status == "pass"
            and not any(check.status == "blocked" for check in checks)
        )
        if native_future_release:
            checks.append(
                FranchiseTradeCheck(
                    "pass",
                    "franchise_native_future_legality_released",
                    (
                        f"The historical canonical runtime is anchored to {engine_year}, "
                        f"so it is not applied as a {season} final gate. All current "
                        "franchise-native financial, player-contract, and draft-right / "
                        "Stepien bridges passed, releasing this future-season package."
                    ),
                )
            )
        else:
            checks.append(
                FranchiseTradeCheck(
                    "manual_review" if not any(check.status == "blocked" for check in checks) else "blocked",
                    "canonical_engine_not_released_for_live_package",
                    eligibility_reason,
                )
            )

    # V2.1 canonical-anchor financial resolution.
    #
    # The future Financial Bridge intentionally leaves two historical anchor
    # quantities as MANUAL_REVIEW because it does not own the canonical 2026
    # historical CBA state. In the canonical anchor season, a verified PASS
    # from the historical canonical engine may resolve ONLY those two exact
    # uncertainty codes.
    #
    # This is not a bypass:
    # - live season must equal the canonical runtime year,
    # - canonical engine must have run and PASS,
    # - Contract Bridge must PASS,
    # - Draft Right / Stepien Bridge must PASS,
    # - Financial Bridge must be MANUAL_REVIEW, never BLOCKED,
    # - every financial non-pass code must be one of the two whitelisted
    #   anchor-only future-buffer uncertainty codes.
    anchor_financial_resolution_applied = False
    anchor_financial_review_codes = {
        "future_standard_roster_minimum_review",
        "future_apron_nonplayer_charge_buffer",
    }
    engine_year = _runtime_league_year(runtime)
    if (
        season
        and engine_year
        and season == engine_year
        and canonical_invoked
        and canonical_status == "pass"
        and player_contract_bridge_status == "pass"
        and draft_right_bridge_status == "pass"
        and financial_bridge_status == "manual_review"
        and financial_bridge_nonpass_codes
        and set(financial_bridge_nonpass_codes).issubset(
            anchor_financial_review_codes
        )
    ):
        rewritten_checks: list[FranchiseTradeCheck] = []
        for check in checks:
            if (
                check.status == "manual_review"
                and (
                    check.code in anchor_financial_review_codes
                    or check.code == "franchise_future_financial_bridge_result"
                )
            ):
                rewritten_checks.append(
                    FranchiseTradeCheck(
                        "pass",
                        check.code,
                        (
                            f"{check.message} "
                            "Resolved for the canonical anchor season by the "
                            "verified canonical trade engine PASS."
                        ),
                        check.team,
                        check.asset_id,
                    )
                )
            else:
                rewritten_checks.append(check)

        checks = rewritten_checks
        financial_bridge_status = "pass"
        anchor_financial_resolution_applied = True
        checks.append(
            FranchiseTradeCheck(
                "pass",
                "canonical_anchor_financial_review_resolved",
                (
                    f"The {season} canonical trade engine returned PASS, "
                    "the Contract and Draft Right / Stepien bridges passed, "
                    "and the Financial Bridge contained only the two "
                    "whitelisted anchor-season future-buffer uncertainties. "
                    "Those manual-review items are resolved for this "
                    "canonical-season package."
                ),
            )
        )

    # Live roster math is informational in V2. Full roster-limit and apron history
    # move into the future-season financial bridge before any commit path is enabled.
    before_a = len(_team_roster_ids(state, resolved_a)) if resolved_a in teams else 0
    before_b = len(_team_roster_ids(state, resolved_b)) if resolved_b in teams else 0
    after_a = before_a - len(players_a) + len(players_b)
    after_b = before_b - len(players_b) + len(players_a)
    if after_a < 5 or after_b < 5:
        checks.append(
            FranchiseTradeCheck(
                "blocked",
                "minimum_simulation_roster_failed",
                f"The package would leave a team below the simulator's five-player absolute roster floor ({resolved_a}: {after_a}, {resolved_b}: {after_b}).",
            )
        )
    else:
        checks.append(
            FranchiseTradeCheck(
                "pass",
                "live_roster_floor_preserved",
                f"Live roster floor is preserved ({resolved_a}: {before_a}->{after_a}, {resolved_b}: {before_b}->{after_b}).",
            )
        )

    side_a_base = _side_preview(
        runtime=runtime,
        state=state,
        ledger=live_ledger,
        team=resolved_a,
        player_ids=players_a,
        pick_asset_ids=picks_a,
        incoming_salary=salary_b,
    )
    side_b_base = _side_preview(
        runtime=runtime,
        state=state,
        ledger=live_ledger,
        team=resolved_b,
        player_ids=players_b,
        pick_asset_ids=picks_b,
        incoming_salary=salary_a,
    )
    side_a_payload = {**asdict(side_a_base), "roster_players_after": after_a}
    side_b_payload = {**asdict(side_b_base), "roster_players_after": after_b}
    if financial_bridge_payload:
        fin_a = financial_bridge_payload.get("side_a", {})
        fin_b = financial_bridge_payload.get("side_b", {})
        side_a_payload["outgoing_salary"] = float(fin_a.get("outgoing_salary", side_a_payload["outgoing_salary"]))
        side_a_payload["incoming_salary"] = float(fin_a.get("incoming_salary", side_a_payload["incoming_salary"]))
        side_b_payload["outgoing_salary"] = float(fin_b.get("outgoing_salary", side_b_payload["outgoing_salary"]))
        side_b_payload["incoming_salary"] = float(fin_b.get("incoming_salary", side_b_payload["incoming_salary"]))
    side_a = FranchiseTradeSidePreview(**side_a_payload)
    side_b = FranchiseTradeSidePreview(**side_b_payload)

    final_status = _combine(checks)
    engine_year = _runtime_league_year(runtime)
    anchor_engine_ok = bool(
        season != engine_year
        or (canonical_invoked and canonical_status == "pass")
    )
    native_bridges_ok = bool(
        draft_right_bridge_status == "pass"
        and player_contract_bridge_status == "pass"
        and financial_bridge_status == "pass"
    )
    can_commit = bool(
        final_status == "pass"
        and native_bridges_ok
        and anchor_engine_ok
    )
    draft_ownership = getattr(
        state, "franchise_draft_right_ownership_v1", {}
    ) or {}
    fingerprint_payload = {
        "season": season,
        "a": resolved_a,
        "b": resolved_b,
        "ap": players_a,
        "bp": players_b,
        "ak": picks_a,
        "bk": picks_b,
        "state_player_count": len(getattr(state, "players", {})),
        "trade_revision": getattr(trade_state, "state_revision", None),
        "franchise_trade_revision": int(
            getattr(state, "franchise_trade_revision_v1", 0) or 0
        ),
        "franchise_draft_ownership": sorted(
            (str(key), normalize_team(value))
            for key, value in draft_ownership.items()
        ),
    }
    return FranchiseTradePreview(
        version=EMBEDDED_TRADE_CENTER_VERSION,
        season_label=season,
        status=final_status,
        can_commit=can_commit,
        side_a=side_a,
        side_b=side_b,
        checks=tuple(checks),
        canonical_engine_invoked=canonical_invoked,
        canonical_engine_status=canonical_status,
        canonical_engine_payload=copy.deepcopy(canonical_payload),
        financial_bridge_invoked=financial_bridge_invoked,
        financial_bridge_status=financial_bridge_status,
        financial_bridge_payload=copy.deepcopy(financial_bridge_payload),
        anchor_financial_resolution_applied=anchor_financial_resolution_applied,
        player_contract_bridge_invoked=player_contract_bridge_invoked,
        player_contract_bridge_status=player_contract_bridge_status,
        player_contract_bridge_payload=copy.deepcopy(player_contract_bridge_payload),
        draft_right_bridge_invoked=draft_right_bridge_invoked,
        draft_right_bridge_status=draft_right_bridge_status,
        draft_right_bridge_payload=copy.deepcopy(draft_right_bridge_payload),
        package_fingerprint=_fingerprint(fingerprint_payload),
    )


def preview_to_dict(preview: FranchiseTradePreview) -> dict[str, Any]:
    return asdict(preview)
