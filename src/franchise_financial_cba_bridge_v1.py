from __future__ import annotations

import copy
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from freeform_trade_machine_engine_v3 import (
    RuntimeData,
    normalize_player_id,
    normalize_team,
    salary_route,
    to_float,
)


FINANCIAL_BRIDGE_VERSION = (
    "franchise-financial-cba-bridge-v2-simulation-native-future-economy-2026-08-12"
)
BASE_LEAGUE_YEAR = "2026-27"
DEFAULT_ANNUAL_CAP_GROWTH = 0.08
MAX_ANNUAL_CAP_GROWTH = 0.10
APRON_UNMODELED_BUFFER_PCT_CAP = 0.04
REGULAR_SEASON_STANDARD_MIN = 14
REGULAR_SEASON_STANDARD_MAX = 15
TWO_WAY_MAX = 3
OFFSEASON_TOTAL_MAX = 21


class FranchiseFinancialBridgeError(RuntimeError):
    """Raised when future-season franchise financials cannot be modeled safely."""


@dataclass(frozen=True)
class FranchiseLeagueThresholds:
    season_label: str
    years_after_anchor: int
    salary_cap: float
    minimum_team_salary: float
    tax_level: float
    first_apron: float
    second_apron: float
    salary_cap_2023_24: float
    tpe_allowance: float
    annual_cap_growth: float
    source: str


@dataclass(frozen=True)
class FranchisePlayerFinancial:
    player_id: str
    player_name: str
    team: str
    roster_status: str
    two_way: bool
    generated_player: bool
    live_contract_salary: float | None
    modeled_trade_salary: float
    salary_source: str
    salary_confidence: str
    years_remaining: int | None
    draft_year: int | None
    overall: float
    age: float | None


@dataclass(frozen=True)
class FranchiseTeamFinancial:
    team: str
    modeled_team_salary: float
    modeled_apron_salary: float
    standard_contract_count: int
    two_way_contract_count: int
    total_roster_count: int
    cap_room: float
    tax_distance: float
    first_apron_distance: float
    second_apron_distance: float
    aggregation_blocked: bool
    existing_hard_cap_active: bool
    existing_hard_cap_level: str
    apron_ledger_complete: bool
    salary_source_summary: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class FranchiseFinancialSnapshot:
    version: str
    season_label: str
    phase: str
    thresholds: FranchiseLeagueThresholds
    player_financials: tuple[FranchisePlayerFinancial, ...]
    team_financials: tuple[FranchiseTeamFinancial, ...]


@dataclass(frozen=True)
class FranchiseFinancialTradeCheck:
    status: str
    code: str
    message: str
    team: str = ""


@dataclass(frozen=True)
class FranchiseFinancialSideEvaluation:
    team: str
    pretrade_team_salary: float
    pretrade_apron_salary: float
    outgoing_salary: float
    incoming_salary: float
    posttrade_team_salary: float
    posttrade_apron_salary: float
    salary_route: str
    max_incoming_salary: float
    roster_before: int
    roster_after: int
    standard_before: int
    standard_after: int
    two_way_before: int
    two_way_after: int
    hard_cap_after_trade: str
    status: str


@dataclass(frozen=True)
class FranchiseFinancialTradeEvaluation:
    version: str
    season_label: str
    status: str
    side_a: FranchiseFinancialSideEvaluation
    side_b: FranchiseFinancialSideEvaluation
    checks: tuple[FranchiseFinancialTradeCheck, ...]
    snapshot_source: str


_STATUS_PRIORITY = {"pass": 0, "manual_review": 1, "blocked": 2}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _finite(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _season_start(season_label: str) -> int:
    match = re.fullmatch(r"(\d{4})-(\d{2}|\d{4})", _clean(season_label))
    if not match:
        raise FranchiseFinancialBridgeError(
            f"Unsupported franchise season label: {season_label!r}."
        )
    start = int(match.group(1))
    suffix = match.group(2)
    end = int(suffix) if len(suffix) == 4 else (start // 100) * 100 + int(suffix)
    if end < start:
        end += 100
    if end != start + 1:
        raise FranchiseFinancialBridgeError(
            f"Season label is not a one-year NBA season: {season_label!r}."
        )
    return start


def _runtime_number(runtime: RuntimeData, key: str) -> float:
    value = to_float(runtime.rules.get("thresholds", {}).get(key))
    if value is None:
        raise FranchiseFinancialBridgeError(
            f"The canonical 2026-27 rules are missing threshold {key!r}."
        )
    return float(value)


def build_future_thresholds(
    runtime: RuntimeData,
    season_label: str,
    *,
    annual_cap_growth: float = DEFAULT_ANNUAL_CAP_GROWTH,
) -> FranchiseLeagueThresholds:
    growth = float(annual_cap_growth)
    if not 0.0 <= growth <= MAX_ANNUAL_CAP_GROWTH:
        raise FranchiseFinancialBridgeError(
            "Modeled annual cap growth must be between 0% and 10%."
        )

    anchor_start = _season_start(BASE_LEAGUE_YEAR)
    target_start = _season_start(season_label)
    years = target_start - anchor_start
    if years < 0:
        raise FranchiseFinancialBridgeError(
            f"Financial Bridge V1 cannot backcast before {BASE_LEAGUE_YEAR}."
        )

    anchor_cap = _runtime_number(runtime, "salary_cap")
    cap = anchor_cap * ((1.0 + growth) ** years)

    def scaled_ratio(key: str) -> float:
        anchor = _runtime_number(runtime, key)
        return cap * (anchor / anchor_cap)

    # The +$250K TPE allowance is kept fixed because the canonical engine models
    # it as a fixed CBA amount, while the expanded-TPE addend scales from the
    # 2023-24 cap internally through salary_route().
    return FranchiseLeagueThresholds(
        season_label=season_label,
        years_after_anchor=years,
        salary_cap=round(cap, 2),
        minimum_team_salary=round(scaled_ratio("minimum_team_salary"), 2),
        tax_level=round(scaled_ratio("tax_level"), 2),
        first_apron=round(scaled_ratio("first_apron"), 2),
        second_apron=round(scaled_ratio("second_apron"), 2),
        salary_cap_2023_24=_runtime_number(runtime, "salary_cap_2023_24"),
        tpe_allowance=_runtime_number(runtime, "tpe_allowance"),
        annual_cap_growth=growth,
        source=(
            "simulated_future_thresholds_scaled_from_verified_2026_27_anchor"
            if years
            else "verified_2026_27_anchor"
        ),
    )


def _roster_status(state: Any, player_id: str, team: str) -> str:
    free_agents = {
        normalize_player_id(x)
        for x in getattr(state, "free_agent_player_ids", ())
        if normalize_player_id(x)
    }
    return "free_agent" if player_id in free_agents or not team else "rostered"


def _player_salary_pct(overall: float, age: float | None) -> float:
    if overall >= 92:
        pct = 0.34
    elif overall >= 88:
        pct = 0.285
    elif overall >= 84:
        pct = 0.225
    elif overall >= 80:
        pct = 0.165
    elif overall >= 76:
        pct = 0.105
    elif overall >= 72:
        pct = 0.065
    elif overall >= 68:
        pct = 0.04
    else:
        pct = 0.025

    if age is not None and age >= 34:
        pct *= 0.86
    if age is not None and age >= 38:
        pct *= 0.74
    return pct


def _rookie_proxy_pct(overall: float, years_since_draft: int) -> float:
    # Without a persistent draft-slot salary table, V1 deliberately uses a
    # bounded rookie-scale proxy. This preserves rookie discounts and prevents
    # high-OVR generated players from being treated like max veterans during
    # their first four seasons.
    if overall >= 84:
        base = 0.105
    elif overall >= 80:
        base = 0.085
    elif overall >= 76:
        base = 0.065
    elif overall >= 72:
        base = 0.045
    else:
        base = 0.03
    escalator = 1.0 + max(0, min(years_since_draft, 3)) * 0.10
    return min(base * escalator, 0.13)


def _model_player_financial(
    runtime: RuntimeData,
    state: Any,
    player_id: str,
    player: Any,
    thresholds: FranchiseLeagueThresholds,
) -> FranchisePlayerFinancial:
    normalized = normalize_player_id(player_id)
    team = normalize_team(getattr(player, "team_abbreviation", ""))
    contract = getattr(player, "contract", None)
    live_salary = _finite(getattr(contract, "salary", None)) if contract is not None else None
    years_remaining = _int_or_none(getattr(contract, "years_remaining", None)) if contract is not None else None
    overall = _finite(getattr(player, "overall_rating", None), 60.0) or 60.0
    age = _finite(getattr(player, "age", None))
    draft_year = _int_or_none(getattr(player, "draft_year", None))
    generated = normalized not in runtime.trade_by_id or bool(_clean(getattr(player, "draft_class_id", "")))
    two_way = bool(getattr(player, "two_way", False))
    status = _roster_status(state, normalized, team)

    target_start = _season_start(thresholds.season_label)
    years_since_draft = max(0, target_start - draft_year) if draft_year is not None else None

    if two_way:
        modeled = 0.0
        source = "two_way_salary_excluded_from_trade_matching_v2"
        confidence = "modeled_rule"
    elif live_salary is not None and live_salary > 0 and (years_remaining is None or years_remaining > 0):
        modeled = live_salary
        source = "live_franchise_contract_salary"
        confidence = "live_state"
    elif generated and years_since_draft is not None and years_since_draft <= 3:
        modeled = thresholds.salary_cap * _rookie_proxy_pct(overall, years_since_draft)
        source = "modeled_rookie_scale_proxy"
        confidence = "modeled"
    elif generated:
        modeled = thresholds.salary_cap * _player_salary_pct(overall, age)
        source = "modeled_generated_market_salary_proxy"
        confidence = "modeled"
    elif thresholds.years_after_anchor == 0 and live_salary is not None:
        modeled = live_salary
        source = "verified_anchor_live_salary"
        confidence = "verified_anchor"
    else:
        modeled = thresholds.salary_cap * _player_salary_pct(overall, age)
        source = "modeled_future_market_salary_proxy"
        confidence = "modeled"

    if not two_way:
        modeled = max(0.0125 * thresholds.salary_cap, modeled)
        modeled = min(0.35 * thresholds.salary_cap, modeled)

    return FranchisePlayerFinancial(
        player_id=normalized,
        player_name=_clean(getattr(player, "player_name", "")) or normalized,
        team=team,
        roster_status=status,
        two_way=two_way,
        generated_player=generated,
        live_contract_salary=live_salary,
        modeled_trade_salary=round(float(modeled), 2),
        salary_source=source,
        salary_confidence=confidence,
        years_remaining=years_remaining,
        draft_year=draft_year,
        overall=round(overall, 1),
        age=age,
    )


def _salary_uncertainty_pct(row: FranchisePlayerFinancial) -> float:
    confidence = _clean(row.salary_confidence).lower()
    if confidence in {"live_state", "verified_anchor"}:
        return 0.035
    if confidence == "modeled_rule":
        return 0.0
    if confidence == "modeled":
        return 0.18
    return 0.22


def _team_modeled_salary_share(team_fin: FranchiseTeamFinancial) -> float:
    total = sum(int(value) for value in team_fin.salary_source_summary.values())
    if total <= 0:
        return 1.0
    modeled = sum(
        int(value)
        for key, value in team_fin.salary_source_summary.items()
        if "modeled" in str(key).lower() or "proxy" in str(key).lower()
    )
    return modeled / total

def build_franchise_financial_snapshot(
    runtime: RuntimeData,
    state: Any,
    *,
    annual_cap_growth: float = DEFAULT_ANNUAL_CAP_GROWTH,
) -> FranchiseFinancialSnapshot:
    season_label = _clean(getattr(getattr(state, "settings", None), "season_label", ""))
    thresholds = build_future_thresholds(
        runtime,
        season_label,
        annual_cap_growth=annual_cap_growth,
    )

    players_obj = getattr(state, "players", {})
    teams_obj = getattr(state, "teams", {})
    if not isinstance(players_obj, dict) or not isinstance(teams_obj, dict):
        raise FranchiseFinancialBridgeError(
            "Live franchise state does not expose player/team dictionaries."
        )

    player_rows = tuple(
        _model_player_financial(runtime, state, str(player_id), player, thresholds)
        for player_id, player in players_obj.items()
        if normalize_player_id(player_id)
    )
    player_by_id = {row.player_id: row for row in player_rows}

    # FA_POST_DRAFT_PICK_HOLD_BRIDGE_V1: financial-snapshot hook
    from franchise_post_draft_first_round_pick_hold_bridge_v1 import (
        active_post_draft_first_round_pick_hold_rows,
    )
    post_draft_hold_rows = active_post_draft_first_round_pick_hold_rows(state)
    pending_hold_player_ids = {
        str(row["player_id"]) for row in post_draft_hold_rows
    }
    post_draft_hold_totals: dict[str, float] = {}
    post_draft_hold_counts: dict[str, int] = {}
    for hold_row in post_draft_hold_rows:
        hold_team = normalize_team(hold_row["rights_holder_team"])
        post_draft_hold_totals[hold_team] = (
            post_draft_hold_totals.get(hold_team, 0.0)
            + float(hold_row["rookie_scale_cap_hold_amount"])
        )
        post_draft_hold_counts[hold_team] = post_draft_hold_counts.get(hold_team, 0) + 1

    team_rows: list[FranchiseTeamFinancial] = []
    for raw_team, team_state in sorted(teams_obj.items()):
        team = normalize_team(raw_team)
        roster_ids = tuple(
            normalize_player_id(x)
            for x in getattr(team_state, "roster_player_ids", ())
            if normalize_player_id(x)
        )
        financials = [player_by_id[x] for x in roster_ids if x in player_by_id]
        standard = sum(
            not row.two_way and row.player_id not in pending_hold_player_ids
            for row in financials
        )
        two_way = sum(row.two_way for row in financials)
        # Pending first-round players have no signed contract salary. Exclude
        # the legacy generated-player proxy, then add the exact rights-holder
        # cap hold once through the dynamic bridge.
        payroll = sum(
            row.modeled_trade_salary
            for row in financials
            if row.player_id not in pending_hold_player_ids
        ) + post_draft_hold_totals.get(team, 0.0)

        sources: dict[str, int] = {}
        for row in financials:
            if row.player_id in pending_hold_player_ids:
                continue
            sources[row.salary_source] = sources.get(row.salary_source, 0) + 1
        if post_draft_hold_counts.get(team, 0):
            sources["post_draft_first_round_pick_hold_bridge_v1"] = (
                post_draft_hold_counts[team]
            )

        # The dynamic first-round hold is part of Team Salary and apron salary.
        # Other non-player components remain governed by their frozen ledgers.
        apron_salary = payroll
        team_rows.append(
            FranchiseTeamFinancial(
                team=team,
                modeled_team_salary=round(payroll, 2),
                modeled_apron_salary=round(apron_salary, 2),
                standard_contract_count=standard,
                two_way_contract_count=two_way,
                total_roster_count=len(roster_ids),
                cap_room=round(thresholds.salary_cap - payroll, 2),
                tax_distance=round(thresholds.tax_level - apron_salary, 2),
                first_apron_distance=round(thresholds.first_apron - apron_salary, 2),
                second_apron_distance=round(thresholds.second_apron - apron_salary, 2),
                aggregation_blocked=apron_salary > thresholds.second_apron,
                existing_hard_cap_active=False,
                existing_hard_cap_level="none",
                apron_ledger_complete=False,
                salary_source_summary=sources,
            )
        )

    phase_value = getattr(getattr(state, "phase", ""), "value", getattr(state, "phase", ""))
    return FranchiseFinancialSnapshot(
        version=FINANCIAL_BRIDGE_VERSION,
        season_label=season_label,
        phase=_clean(phase_value).lower(),
        thresholds=thresholds,
        player_financials=player_rows,
        team_financials=tuple(team_rows),
    )


def _combine(checks: list[FranchiseFinancialTradeCheck]) -> str:
    if not checks:
        return "pass"
    return max(
        (_clean(check.status).lower() for check in checks),
        key=lambda value: _STATUS_PRIORITY.get(value, 1),
    )


def _side_eval(
    *,
    snapshot: FranchiseFinancialSnapshot,
    team: str,
    outgoing_ids: tuple[str, ...],
    incoming_ids: tuple[str, ...],
) -> tuple[FranchiseFinancialSideEvaluation, list[FranchiseFinancialTradeCheck]]:
    resolved = normalize_team(team)
    pmap = {row.player_id: row for row in snapshot.player_financials}
    tmap = {row.team: row for row in snapshot.team_financials}
    team_fin = tmap.get(resolved)
    if team_fin is None:
        raise FranchiseFinancialBridgeError(f"No financial snapshot exists for team {resolved}.")

    outgoing_rows = [pmap[x] for x in outgoing_ids if x in pmap]
    incoming_rows = [pmap[x] for x in incoming_ids if x in pmap]
    outgoing_salary = sum(row.modeled_trade_salary for row in outgoing_rows if not row.two_way)
    incoming_salary = sum(row.modeled_trade_salary for row in incoming_rows if not row.two_way)
    outgoing_two_way = sum(row.two_way for row in outgoing_rows)
    incoming_two_way = sum(row.two_way for row in incoming_rows)
    outgoing_standard = len(outgoing_rows) - outgoing_two_way
    incoming_standard = len(incoming_rows) - incoming_two_way

    future_mode = snapshot.thresholds.years_after_anchor > 0
    modeled_share = _team_modeled_salary_share(team_fin)
    apron_uncertain = future_mode and (not team_fin.apron_ledger_complete) and modeled_share >= 0.20
    effective_aggregation_blocked = bool(team_fin.aggregation_blocked and not apron_uncertain)

    route, max_incoming = salary_route(
        pre_team_salary=team_fin.modeled_team_salary,
        pre_apron_salary=team_fin.modeled_apron_salary,
        outgoing=outgoing_salary,
        incoming_matching=incoming_salary,
        incoming_actual=incoming_salary,
        outgoing_count=outgoing_standard,
        aggregation_policy_blocked=effective_aggregation_blocked,
        salary_cap=snapshot.thresholds.salary_cap,
        first_apron=snapshot.thresholds.first_apron,
        second_apron=snapshot.thresholds.second_apron,
        salary_cap_2023_24=snapshot.thresholds.salary_cap_2023_24,
        tpe_allowance=snapshot.thresholds.tpe_allowance,
    )

    checks: list[FranchiseFinancialTradeCheck] = []
    if route == "none" and future_mode:
        outgoing_high = sum(
            row.modeled_trade_salary * (1.0 + _salary_uncertainty_pct(row))
            for row in outgoing_rows if not row.two_way
        )
        incoming_low = sum(
            row.modeled_trade_salary * (1.0 - _salary_uncertainty_pct(row))
            for row in incoming_rows if not row.two_way
        )
        proxy_route, proxy_max = salary_route(
            pre_team_salary=team_fin.modeled_team_salary,
            pre_apron_salary=team_fin.modeled_apron_salary,
            outgoing=outgoing_high,
            incoming_matching=incoming_low,
            incoming_actual=incoming_low,
            outgoing_count=outgoing_standard,
            aggregation_policy_blocked=effective_aggregation_blocked,
            salary_cap=snapshot.thresholds.salary_cap,
            first_apron=snapshot.thresholds.first_apron,
            second_apron=snapshot.thresholds.second_apron,
            salary_cap_2023_24=snapshot.thresholds.salary_cap_2023_24,
            tpe_allowance=snapshot.thresholds.tpe_allowance,
        )
        if proxy_route != "none":
            route = f"future_proxy_uncertainty_{proxy_route}"
            max_incoming = proxy_max
            checks.append(FranchiseFinancialTradeCheck(
                "pass", "future_salary_proxy_uncertainty_release",
                f"{resolved} clears salary routing after applying the explicit future-contract uncertainty band to simulated salaries.", resolved,
            ))
        elif outgoing_salary > 0 and incoming_salary > 0:
            uncertainty_band = (
                sum(row.modeled_trade_salary * _salary_uncertainty_pct(row) for row in outgoing_rows if not row.two_way)
                + sum(row.modeled_trade_salary * _salary_uncertainty_pct(row) for row in incoming_rows if not row.two_way)
                + 0.025 * snapshot.thresholds.salary_cap
            )
            salary_gap = abs(incoming_salary - outgoing_salary)
            if salary_gap <= uncertainty_band:
                route = "future_simulation_uncertainty_band"
                max_incoming = max(outgoing_salary, incoming_salary)
                checks.append(FranchiseFinancialTradeCheck(
                    "pass", "future_salary_simulation_band_release",
                    f"{resolved} modeled salary gap (${salary_gap:,.0f}) fits inside the future-contract uncertainty band (${uncertainty_band:,.0f}).", resolved,
                ))

    if route == "none":
        checks.append(FranchiseFinancialTradeCheck(
            "blocked", "future_salary_matching_failed",
            f"{resolved} cannot receive ${incoming_salary:,.0f} against ${outgoing_salary:,.0f} of modeled outgoing salary under the simulated {snapshot.season_label} economy.", resolved,
        ))
    elif not any(check.code.startswith("future_salary_") for check in checks):
        checks.append(FranchiseFinancialTradeCheck(
            "pass", "future_salary_matching_passed",
            f"{resolved} salary route: {route}; modeled max incoming ${max_incoming:,.0f} versus ${incoming_salary:,.0f} received.", resolved,
        ))

    post_team = team_fin.modeled_team_salary - outgoing_salary + incoming_salary
    post_apron = team_fin.modeled_apron_salary - outgoing_salary + incoming_salary
    standard_after = team_fin.standard_contract_count - outgoing_standard + incoming_standard
    two_way_after = team_fin.two_way_contract_count - outgoing_two_way + incoming_two_way
    roster_after = standard_after + two_way_after

    if two_way_after > TWO_WAY_MAX:
        checks.append(FranchiseFinancialTradeCheck("blocked", "future_two_way_roster_limit_failed", f"{resolved} would have {two_way_after} two-way contracts; maximum is {TWO_WAY_MAX}.", resolved))
    else:
        checks.append(FranchiseFinancialTradeCheck("pass", "future_two_way_roster_limit_passed", f"{resolved} two-way count remains {two_way_after}/{TWO_WAY_MAX}.", resolved))

    if snapshot.phase == "offseason":
        if roster_after > OFFSEASON_TOTAL_MAX:
            checks.append(FranchiseFinancialTradeCheck("blocked", "future_offseason_roster_limit_failed", f"{resolved} would have {roster_after} total players; offseason maximum is {OFFSEASON_TOTAL_MAX} including two-way contracts.", resolved))
        else:
            checks.append(FranchiseFinancialTradeCheck("pass", "future_offseason_roster_limit_passed", f"{resolved} offseason roster remains {roster_after}/{OFFSEASON_TOTAL_MAX}.", resolved))
    else:
        max_standard = REGULAR_SEASON_STANDARD_MAX
        standard_before = team_fin.standard_contract_count
        if standard_before > max_standard:
            if standard_after <= standard_before:
                checks.append(FranchiseFinancialTradeCheck("pass", "future_existing_standard_roster_overflow_not_worsened", f"{resolved} enters with {standard_before} modeled standard contracts; the trade does not worsen the inherited simulator overflow ({standard_before} -> {standard_after}).", resolved))
            else:
                checks.append(FranchiseFinancialTradeCheck("blocked", "future_existing_standard_roster_overflow_worsened", f"{resolved} would worsen an inherited standard-roster overflow ({standard_before} -> {standard_after}).", resolved))
        elif standard_before < REGULAR_SEASON_STANDARD_MIN:
            # Mature franchise saves can legitimately inherit a simulator roster
            # below the NBA regular-season standard-contract minimum. Treat that
            # pre-existing condition symmetrically with inherited overflow:
            # a trade may preserve or improve the count, but may not worsen it.
            #
            # This does not declare the inherited roster CBA-compliant. It only
            # prevents an unrelated pre-existing roster-size condition from
            # vetoing every otherwise valid trade in future simulated seasons.
            if standard_after >= standard_before:
                checks.append(FranchiseFinancialTradeCheck(
                    "pass",
                    "future_existing_standard_roster_underflow_not_worsened",
                    f"{resolved} enters with {standard_before} modeled standard contracts; the trade preserves or improves the inherited simulator underflow ({standard_before} -> {standard_after}).",
                    resolved,
                ))
            else:
                checks.append(FranchiseFinancialTradeCheck(
                    "blocked",
                    "future_existing_standard_roster_underflow_worsened",
                    f"{resolved} would worsen an inherited standard-roster underflow ({standard_before} -> {standard_after}).",
                    resolved,
                ))
        elif standard_after > max_standard:
            checks.append(FranchiseFinancialTradeCheck("blocked", "future_standard_roster_limit_failed", f"{resolved} would have {standard_after} standard contracts; maximum is {max_standard}.", resolved))
        elif standard_after < REGULAR_SEASON_STANDARD_MIN:
            checks.append(FranchiseFinancialTradeCheck("manual_review", "future_standard_roster_minimum_review", f"{resolved} would have {standard_after} standard contracts, below the modeled {REGULAR_SEASON_STANDARD_MIN}-player minimum.", resolved))
        else:
            checks.append(FranchiseFinancialTradeCheck("pass", "future_standard_roster_limit_passed", f"{resolved} standard roster remains {standard_after}/{max_standard}.", resolved))

    if apron_uncertain:
        checks.append(FranchiseFinancialTradeCheck(
            "pass", "future_apron_status_simulation_advisory",
            f"{resolved} apron restrictions are advisory in {snapshot.season_label}: {modeled_share:.0%} of roster salary is modeled and the persistent apron-charge ledger is incomplete.", resolved,
        ))
    else:
        buffer_amount = snapshot.thresholds.salary_cap * APRON_UNMODELED_BUFFER_PCT_CAP
        nearest_apron = min(abs(snapshot.thresholds.first_apron - post_apron), abs(snapshot.thresholds.second_apron - post_apron))
        if nearest_apron <= buffer_amount:
            checks.append(FranchiseFinancialTradeCheck("manual_review", "future_apron_nonplayer_charge_buffer", f"{resolved} finishes within ${buffer_amount:,.0f} of an apron and the non-player ledger is incomplete.", resolved))
        else:
            checks.append(FranchiseFinancialTradeCheck("pass", "future_apron_boundary_buffer_clear", f"{resolved} remains outside the apron uncertainty buffer.", resolved))

    if post_apron > snapshot.thresholds.second_apron and outgoing_standard > 1:
        if apron_uncertain:
            checks.append(FranchiseFinancialTradeCheck("pass", "future_second_apron_aggregation_simulation_advisory", f"{resolved} aggregation is advisory because future apron status is not deterministic without a complete simulated apron ledger.", resolved))
        else:
            checks.append(FranchiseFinancialTradeCheck("blocked", "future_second_apron_aggregation_failed", f"{resolved} would be above the simulated second apron while aggregating multiple outgoing standard contracts.", resolved))

    hard_cap_after = "none"
    if str(route).endswith("expanded_tpe"):
        hard_cap_after = "first_apron"
    elif str(route).endswith("aggregated_standard_tpe"):
        hard_cap_after = "second_apron"

    if hard_cap_after == "first_apron" and post_apron > snapshot.thresholds.first_apron:
        checks.append(FranchiseFinancialTradeCheck("pass" if apron_uncertain else "blocked", "future_first_apron_hard_cap_simulation_advisory" if apron_uncertain else "future_first_apron_transaction_hard_cap_failed", f"{resolved} modeled post-trade salary crosses the first-apron line; {'future status is advisory' if apron_uncertain else 'transaction is blocked'}.", resolved))
    if hard_cap_after == "second_apron" and post_apron > snapshot.thresholds.second_apron:
        checks.append(FranchiseFinancialTradeCheck("pass" if apron_uncertain else "blocked", "future_second_apron_hard_cap_simulation_advisory" if apron_uncertain else "future_second_apron_transaction_hard_cap_failed", f"{resolved} modeled post-trade salary crosses the second-apron line; {'future status is advisory' if apron_uncertain else 'transaction is blocked'}.", resolved))

    status = _combine(checks)
    side = FranchiseFinancialSideEvaluation(
        team=resolved,
        pretrade_team_salary=round(team_fin.modeled_team_salary, 2),
        pretrade_apron_salary=round(team_fin.modeled_apron_salary, 2),
        outgoing_salary=round(outgoing_salary, 2),
        incoming_salary=round(incoming_salary, 2),
        posttrade_team_salary=round(post_team, 2),
        posttrade_apron_salary=round(post_apron, 2),
        salary_route=route,
        max_incoming_salary=round(max_incoming, 2),
        roster_before=team_fin.total_roster_count,
        roster_after=roster_after,
        standard_before=team_fin.standard_contract_count,
        standard_after=standard_after,
        two_way_before=team_fin.two_way_contract_count,
        two_way_after=two_way_after,
        hard_cap_after_trade=hard_cap_after,
        status=status,
    )
    return side, checks

def evaluate_franchise_financial_trade(
    runtime: RuntimeData,
    state: Any,
    *,
    team_a: str,
    team_b: str,
    side_a_player_ids: tuple[str, ...],
    side_b_player_ids: tuple[str, ...],
    annual_cap_growth: float = DEFAULT_ANNUAL_CAP_GROWTH,
    snapshot: FranchiseFinancialSnapshot | None = None,
    verify_nonmutation: bool = True,
) -> FranchiseFinancialTradeEvaluation:
    # Normal Trade Builder / commit calls keep the defensive deep-copy path.
    # Bulk read-only routing can pass one immutable snapshot and rely on an
    # outer state-signature check instead of copying the league per candidate.
    before = copy.deepcopy(state) if verify_nonmutation else None
    if snapshot is None:
        snapshot = build_franchise_financial_snapshot(
            runtime,
            state,
            annual_cap_growth=annual_cap_growth,
        )

    side_a, checks_a = _side_eval(
        snapshot=snapshot,
        team=team_a,
        outgoing_ids=side_a_player_ids,
        incoming_ids=side_b_player_ids,
    )
    side_b, checks_b = _side_eval(
        snapshot=snapshot,
        team=team_b,
        outgoing_ids=side_b_player_ids,
        incoming_ids=side_a_player_ids,
    )
    checks = checks_a + checks_b

    # Defensive source-mutation verification remains the default for normal
    # Trade Builder / commit evaluations. Bulk Trade Finder routing performs
    # one outer live-state signature check instead.
    if verify_nonmutation:
        try:
            unchanged = state == before
        except Exception:
            unchanged = repr(state) == repr(before)
        if not unchanged:
            raise FranchiseFinancialBridgeError(
                "Financial trade evaluation mutated the live franchise state."
            )

    return FranchiseFinancialTradeEvaluation(
        version=FINANCIAL_BRIDGE_VERSION,
        season_label=snapshot.season_label,
        status=_combine(checks),
        side_a=side_a,
        side_b=side_b,
        checks=tuple(checks),
        snapshot_source=snapshot.thresholds.source,
    )


def snapshot_to_dict(snapshot: FranchiseFinancialSnapshot) -> dict[str, Any]:
    return asdict(snapshot)


def financial_trade_to_dict(evaluation: FranchiseFinancialTradeEvaluation) -> dict[str, Any]:
    return asdict(evaluation)
