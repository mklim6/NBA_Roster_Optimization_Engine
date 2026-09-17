from __future__ import annotations

import copy
import hashlib
import json
import math
import itertools
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable

from freeform_trade_machine_engine_v3 import (
    TradeRequest,
    TradeSideRequest,
    evaluate_trade,
    normalize_player_id,
    normalize_team,
)
from franchise_command_center_v1 import position_family, team_needs_rows
from franchise_asset_market_value_v1 import (
    ASSET_MARKET_CONTEXT_VERSION,
    ASSET_MARKET_MODEL_VERSION,
    AssetMarketContext,
    build_league_asset_market_contexts,
    build_trade_row_market_context,
    trade_market_value_from_row,
)
from franchise_draft_right_stepien_bridge_v1 import (
    build_franchise_draft_right_profiles,
    evaluate_franchise_draft_right_trade,
)
from franchise_embedded_trade_center_v2 import build_franchise_trade_preview, preview_to_dict
from franchise_financial_cba_bridge_v1 import (
    build_franchise_financial_snapshot,
    evaluate_franchise_financial_trade,
)
from franchise_live_asset_ledger_v1 import FranchiseAssetLedger, build_live_asset_ledger, team_draft_rows, team_player_rows
from franchise_player_contract_bridge_v1 import (
    build_franchise_player_contract_snapshot,
    evaluate_franchise_player_contract_trade,
)
from franchise_morale_trade_finder_terms_v1 import (
    build_morale_trade_finder_terms_v1,
    morale_trade_finder_search_bonus_v1,
    morale_trade_finder_target_available_v1,
)


TRADE_FINDER_AI_VERSION = "franchise-trade-finder-cpu-ai-v1.5.3-anchor-preview-resolution-2026-08-13"
TRADE_FINDER_VALUE_MODEL_VERSION = "shared-franchise-asset-market-context-v1.0.2-trade-finder-v1.5.3-2026-08-13"

GOAL_BEST_AVAILABLE = "best_available"
GOAL_BIGGEST_NEED = "fill_biggest_need"
GOAL_WIN_NOW = "win_now"
GOAL_FUTURE_UPSIDE = "future_upside"
VALID_GOALS = {
    GOAL_BEST_AVAILABLE,
    GOAL_BIGGEST_NEED,
    GOAL_WIN_NOW,
    GOAL_FUTURE_UPSIDE,
}


class FranchiseTradeFinderAIError(RuntimeError):
    """Raised when live franchise Trade Finder generation cannot be completed safely."""


@dataclass(frozen=True)
class TeamTradeAIProfile:
    team: str
    games_played: int
    win_pct: float
    average_age: float
    average_overall: float
    top_five_overall: float
    timeline: str
    biggest_need: str
    need_scores: dict[str, float]
    current_player_preference: float
    future_asset_preference: float


@dataclass(frozen=True)
class FranchiseTradeFinderProposal:
    proposal_id: str
    active_team: str
    partner_team: str
    goal: str
    cpu_response: str
    response_label: str
    side_a_player_ids: tuple[str, ...]
    side_b_player_ids: tuple[str, ...]
    side_a_pick_asset_ids: tuple[str, ...]
    side_b_pick_asset_ids: tuple[str, ...]
    user_value_sent: float
    user_value_received: float
    user_value_delta: float
    cpu_value_sent: float
    cpu_value_received: float
    cpu_value_delta: float
    fit_score: float
    ranking_score: float
    target_player_id: str
    target_player_name: str
    rationale: str
    preview_payload: dict[str, Any]
    deal_type: str = "Player-centered"
    counter_sweetener: str = ""


@dataclass(frozen=True)
class FranchiseTradeFinderResult:
    version: str
    value_model_version: str
    season_label: str
    franchise_trade_revision: int
    active_team: str
    goal: str
    partner_filter: str
    teams_scanned: int
    packages_evaluated: int
    legal_packages: int
    cpu_accepts_found: int
    cpu_counters_found: int
    fallback_used: bool
    targets_identified: int = 0
    primary_need_targets_identified: int = 0
    candidate_packages_generated: int = 0
    value_screen_passes: int = 0
    guaranteed_exploration_packages: int = 0
    financial_prechecks: int = 0
    financial_precheck_passes: int = 0
    partners_with_targets: int = 0
    partners_with_financial_pass: int = 0
    partners_with_legal_pass: int = 0
    cpu_rejected_legal: int = 0
    partner_funnel: dict[str, dict[str, int]] = field(default_factory=dict)
    rejection_counts: dict[str, int] = field(default_factory=dict)
    rejection_examples: dict[str, tuple[str, ...]] = field(default_factory=dict)
    proposals: tuple[FranchiseTradeFinderProposal, ...] = field(default_factory=tuple)
    near_misses: tuple[FranchiseTradeFinderProposal, ...] = field(default_factory=tuple)
    package_audit_rows: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    search_elapsed_seconds: float = 0.0


def trade_finder_result_to_dict(result: FranchiseTradeFinderResult) -> dict[str, Any]:
    return asdict(result)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return float(number) if math.isfinite(number) else float(default)



def _shared_asset_tier(row: dict[str, Any]) -> str:
    return _clean(row.get("_shared_asset_tier")) or "Filler"


def _shared_trade_value(row: dict[str, Any]) -> float:
    cached = row.get("_shared_trade_value_score")
    if cached not in (None, ""):
        return max(0.0, min(185.0, _finite(cached, 0.0)))
    return max(0.0, min(185.0, trade_market_value_from_row(row)))


def _apply_shared_context(
    row: dict[str, Any],
    context: AssetMarketContext | None,
) -> dict[str, Any]:
    if context is None:
        context = build_trade_row_market_context(row)
    row["_shared_asset_tier"] = context.asset_tier
    row["_shared_market_score"] = context.market_score
    row["_shared_organizational_score"] = context.organizational_score
    row["_shared_trade_value_score"] = context.trade_value_score
    row["_shared_market_percentile"] = context.market_percentile
    row["_shared_age_curve_score"] = context.age_curve_score
    row["_shared_contract_control_score"] = context.contract_control_score
    row["_shared_salary_efficiency_score"] = context.salary_efficiency_score
    row["_shared_availability_score"] = context.availability_score
    row["_shared_context_confidence"] = context.confidence_score
    return row


def _annotate_rows_with_shared_context(
    rows: Iterable[dict[str, Any]],
    contexts: dict[str, AssetMarketContext],
) -> None:
    for row in rows:
        player_id = normalize_player_id(row.get("player_id"))
        _apply_shared_context(row, contexts.get(player_id))


def _directional_salary_route_penalty(
    outgoing_salary: float,
    incoming_salary: float,
) -> float:
    outgoing_salary = max(0.0, float(outgoing_salary))
    incoming_salary = max(0.0, float(incoming_salary))
    if outgoing_salary >= incoming_salary:
        return abs(outgoing_salary - incoming_salary) / 1_000_000.0
    shortfall = incoming_salary - outgoing_salary
    return 7.0 + 1.35 * shortfall / 1_000_000.0

def _state_signature(state: Any) -> str:
    payload = {
        "season": _clean(getattr(getattr(state, "settings", None), "season_label", "")),
        "trade_revision": int(getattr(state, "franchise_trade_revision_v1", 0) or 0),
        "history": [
            _clean(row.get("transaction_id"))
            for row in getattr(state, "franchise_transaction_history_v1", []) or []
            if isinstance(row, dict)
        ],
        "draft_ownership": sorted(
            (str(k), normalize_team(v))
            for k, v in (getattr(state, "franchise_draft_right_ownership_v1", {}) or {}).items()
        ),
        "rosters": sorted(
            (
                normalize_team(team),
                tuple(getattr(team_state, "roster_player_ids", ())),
            )
            for team, team_state in getattr(state, "teams", {}).items()
        ),
        "player_teams": sorted(
            (
                normalize_player_id(pid),
                normalize_team(getattr(player, "team_abbreviation", "")),
            )
            for pid, player in getattr(state, "players", {}).items()
        ),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _trade_state_signature(trade_state: Any) -> str:
    payload = {
        "revision": int(getattr(trade_state, "state_revision", 0) or 0),
        "transactions": len(getattr(trade_state, "transaction_history", ()) or ()),
        "players": sorted((getattr(trade_state, "player_team_by_id", {}) or {}).items()),
        "picks": sorted((getattr(trade_state, "pick_team_by_id", {}) or {}).items()),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _need_map(state: Any, team: str) -> dict[str, float]:
    return {
        str(row.get("Position Group", "")): _finite(row.get("Need Score"), 0.0)
        for row in team_needs_rows(state, team)
    }


def _team_profile(state: Any, ledger: FranchiseAssetLedger, team: str) -> TeamTradeAIProfile:
    resolved = normalize_team(team)
    rows = [
        row
        for row in team_player_rows(ledger, resolved)
        if row.get("roster_status") == "rostered"
    ]
    ages = [_finite(row.get("age"), -1.0) for row in rows]
    ages = [age for age in ages if age >= 0]
    ovrs = sorted((_finite(row.get("overall"), 60.0) for row in rows), reverse=True)
    average_age = sum(ages) / len(ages) if ages else 27.0
    average_overall = sum(ovrs) / len(ovrs) if ovrs else 70.0
    top_five = sum(ovrs[:5]) / min(5, len(ovrs)) if ovrs else 70.0

    standing = getattr(state, "standings", {}).get(resolved)
    games = int(getattr(standing, "games_played", 0) or 0)
    wins = int(getattr(standing, "wins", 0) or 0)
    win_pct = wins / games if games > 0 else max(0.0, min(1.0, (top_five - 72.0) / 22.0))

    if win_pct >= 0.56 or top_five >= 86.0:
        timeline = "contender"
        current_pref = 1.10
        future_pref = 0.93
    elif win_pct <= 0.42 and (average_age <= 27.5 or top_five <= 82.0):
        timeline = "rebuild"
        current_pref = 0.94
        future_pref = 1.12
    else:
        timeline = "balanced"
        current_pref = 1.00
        future_pref = 1.00

    needs = _need_map(state, resolved)
    # "Other" is a catch-all bucket in the Command Center, not an actual NBA
    # roster position target. A normal roster often has zero "Other" players,
    # which would otherwise create an artificial maximum need score.
    needs["Other"] = 0.0
    biggest_need = max(
        ("Guard", "Wing/Forward", "Center"),
        key=lambda family: (needs.get(family, 0.0), family),
    )
    return TeamTradeAIProfile(
        team=resolved,
        games_played=games,
        win_pct=round(win_pct, 4),
        average_age=round(average_age, 2),
        average_overall=round(average_overall, 2),
        top_five_overall=round(top_five, 2),
        timeline=timeline,
        biggest_need=biggest_need,
        need_scores=dict(needs),
        current_player_preference=current_pref,
        future_asset_preference=future_pref,
    )


def build_team_trade_ai_profiles(
    state: Any,
    ledger: FranchiseAssetLedger,
) -> dict[str, TeamTradeAIProfile]:
    return {
        normalize_team(team): _team_profile(state, ledger, team)
        for team in sorted(getattr(state, "teams", {}))
        if normalize_team(team)
    }


def _goal_player_bonus(
    row: dict[str, Any],
    profile: TeamTradeAIProfile,
    goal: str,
) -> float:
    """Small fit adjustment layered on top of intrinsic trade value.

    V2 deliberately keeps team fit much smaller than intrinsic value so roster
    need cannot make a rotation player numerically resemble a franchise star.
    """
    overall = _finite(row.get("overall"), 60.0)
    potential = _finite(row.get("potential"), overall)
    age = _finite(row.get("age"), 27.0)
    family = position_family(str(row.get("position", "")))
    need = min(16.0, max(0.0, profile.need_scores.get(family, 0.0)))
    bonus = 0.16 * need

    if profile.timeline == "contender":
        bonus += max(-1.5, min(3.5, 0.16 * (overall - 80.0)))
    elif profile.timeline == "rebuild":
        bonus += max(-1.5, min(3.5, (27.0 - age) * 0.24 + max(0.0, potential - overall) * 0.10))

    if goal == GOAL_BIGGEST_NEED:
        bonus += 2.2 if family == profile.biggest_need else -0.4
    elif goal == GOAL_WIN_NOW:
        bonus += max(-1.5, min(3.5, 0.18 * (overall - 82.0)))
    elif goal == GOAL_FUTURE_UPSIDE:
        bonus += max(-1.5, min(3.5, (26.0 - age) * 0.22 + max(0.0, potential - overall) * 0.16))
    return bonus


def _intrinsic_player_value(row: dict[str, Any]) -> float:
    """Shared franchise market value used by Front Office and Trade Finder."""
    return round(_shared_trade_value(row), 2)


def player_value_for_team(
    row: dict[str, Any],
    profile: TeamTradeAIProfile,
    *,
    goal: str = GOAL_BEST_AVAILABLE,
) -> float:
    return round(
        max(0.0, min(185.0, _intrinsic_player_value(row) + _goal_player_bonus(row, profile, goal))),
        2,
    )


def pick_value_for_team(
    row: dict[str, Any],
    ledger: FranchiseAssetLedger,
    profile: TeamTradeAIProfile,
) -> float:
    """Expected-slot draft value instead of generic 'first round pick' value."""
    year = int(row.get("draft_year") or ledger.horizon_end_year)
    years_out = max(0, year - int(ledger.next_draft_year))
    round_number = int(row.get("round") or 2)
    origin_win_pct = max(0.05, min(0.75, _finite(row.get("_origin_win_pct"), 0.50)))

    # Current team strength implies an expected slot, then regresses toward the
    # middle of the round as the pick gets farther away and uncertainty grows.
    current_slot = max(1.0, min(30.0, 1.0 + 44.0 * origin_win_pct))
    uncertainty = min(0.50, years_out * 0.08)
    expected_slot = current_slot * (1.0 - uncertainty) + 16.0 * uncertainty

    if round_number == 1:
        base = 68.0 - 1.65 * (expected_slot - 1.0)
        base *= 0.95 ** years_out
        floor, ceiling = 17.0, 68.0
    else:
        base = 13.0 - 0.25 * max(0.0, expected_slot - 1.0)
        base *= 0.92 ** years_out
        floor, ceiling = 2.5, 13.0

    protection = _clean(row.get("protection")).lower()
    if protection not in {"", "none", "unprotected", "not_applicable"}:
        base *= 0.82

    base *= profile.future_asset_preference
    return round(max(floor, min(ceiling, base)), 2)


def _bundle_value(
    *,
    player_ids: Iterable[str],
    pick_ids: Iterable[str],
    player_map: dict[str, dict[str, Any]],
    pick_map: dict[str, dict[str, Any]],
    ledger: FranchiseAssetLedger,
    profile: TeamTradeAIProfile,
    goal: str,
) -> float:
    """Diminishing bundle value prevents 'four quarters for a dollar' trades."""
    values: list[float] = []
    for pid in player_ids:
        row = player_map.get(normalize_player_id(pid))
        if row is not None:
            values.append(player_value_for_team(row, profile, goal=goal))
    for aid in pick_ids:
        row = pick_map.get(str(aid))
        if row is not None:
            values.append(pick_value_for_team(row, ledger, profile))

    values.sort(reverse=True)
    total = 0.0
    for index, asset_value in enumerate(values):
        if index == 0:
            weight = 1.0
        elif index == 1:
            weight = 0.78 if asset_value >= 75.0 else 0.65 if asset_value >= 35.0 else 0.55
        elif index == 2:
            weight = 0.58 if asset_value >= 75.0 else 0.46 if asset_value >= 35.0 else 0.36
        elif index == 3:
            weight = 0.42 if asset_value >= 75.0 else 0.32 if asset_value >= 35.0 else 0.25
        else:
            weight = 0.18
        total += asset_value * weight
    return round(total, 2)


def _player_name(player_map: dict[str, dict[str, Any]], player_id: str) -> str:
    row = player_map.get(normalize_player_id(player_id), {})
    return _clean(row.get("player_name")) or normalize_player_id(player_id)


def _asset_label(
    player_map: dict[str, dict[str, Any]],
    pick_map: dict[str, dict[str, Any]],
    *,
    player_ids: Iterable[str],
    pick_ids: Iterable[str],
) -> str:
    labels: list[str] = []
    for pid in player_ids:
        labels.append(_player_name(player_map, pid))
    for aid in pick_ids:
        row = pick_map.get(str(aid), {})
        labels.append(_clean(row.get("display_name")) or str(aid))
    return ", ".join(labels) if labels else "nothing"


def _tradable_players_by_team(
    runtime: Any,
    state: Any,
    ledger: FranchiseAssetLedger,
    *,
    contract_snapshot: Any | None = None,
) -> dict[str, list[dict[str, Any]]]:
    snapshot = contract_snapshot or build_franchise_player_contract_snapshot(runtime, state)
    profile_map = {profile.player_id: profile for profile in snapshot.profiles}
    output: dict[str, list[dict[str, Any]]] = {}
    for row in ledger.player_rows:
        if row.get("roster_status") != "rostered":
            continue
        team = normalize_team(row.get("team"))
        profile = profile_map.get(normalize_player_id(row.get("player_id")))
        if profile is None or profile.status != "pass" or not profile.trade_eligible:
            continue
        if profile.two_way or profile.synthetic:
            continue
        if _clean(row.get("career_status")).lower() in {"retired", "farewell_season"}:
            continue
        # The final live preview requires a positive live trade salary. Do not
        # spend market-search time on generated/filler rows it will structurally
        # reject as side_*_live_salary_missing.
        if _salary(row) <= 0.0:
            continue
        output.setdefault(team, []).append(dict(row))
    for team in output:
        output[team].sort(
            key=lambda row: (-_finite(row.get("asset_score"), 50.0), row.get("player_name", ""))
        )
    return output


def _tradable_picks_by_team(
    ledger: FranchiseAssetLedger,
) -> dict[str, list[dict[str, Any]]]:
    profiles = {
        profile.asset_id: profile
        for profile in build_franchise_draft_right_profiles(ledger)
    }
    output: dict[str, list[dict[str, Any]]] = {}
    for row in ledger.draft_rows:
        owner = normalize_team(row.get("current_owner"))
        profile = profiles.get(str(row.get("asset_id")))
        if profile is None or not profile.bridge_ready or profile.status != "pass":
            continue
        output.setdefault(owner, []).append(dict(row))
    for team in output:
        output[team].sort(
            key=lambda row: (
                int(row.get("round") or 9),
                int(row.get("draft_year") or 9999),
                str(row.get("asset_id")),
            )
        )
    return output


def _untouchable(
    row: dict[str, Any],
    cpu_profile: TeamTradeAIProfile,
) -> bool:
    overall = _finite(row.get("overall"), 60.0)
    age = _finite(row.get("age"), 27.0)
    tier = _shared_asset_tier(row)
    intrinsic = _intrinsic_player_value(row)
    if tier == "Franchise" and age <= 31.0:
        return True
    if tier == "Star" and age <= 25.0 and intrinsic >= 138.0:
        return True
    if cpu_profile.timeline == "rebuild" and age <= 25.0 and intrinsic >= 128.0:
        return True
    role = _clean(row.get("role")).lower()
    if overall >= 96.0 and age <= 30.0:
        return True
    if role == "franchise" and overall >= 94.0 and age <= 27.0:
        return True
    return False


# FRANCHISE_MORALE_TRADE_FINDER_V5B
def _morale_trade_finder_target_available_v1(
    state: Any,
    team: str,
    row: dict[str, Any],
    cpu_profile: TeamTradeAIProfile,
) -> bool:
    return morale_trade_finder_target_available_v1(
        state,
        team,
        row,
        base_untouchable=_untouchable(
            row,
            cpu_profile,
        ),
    )


def _salary(row: dict[str, Any]) -> float:
    return max(0.0, _finite(row.get("salary"), 0.0))


def _bundle_salary(
    player_ids: Iterable[str],
    player_map: dict[str, dict[str, Any]],
) -> float:
    return round(
        sum(_salary(player_map.get(normalize_player_id(player_id), {})) for player_id in player_ids),
        2,
    )


def _salary_gap_ratio(
    side_a_player_ids: Iterable[str],
    side_b_player_ids: Iterable[str],
    player_map: dict[str, dict[str, Any]],
) -> float:
    salary_a = _bundle_salary(side_a_player_ids, player_map)
    salary_b = _bundle_salary(side_b_player_ids, player_map)
    scale = max(salary_a, salary_b, 1_000_000.0)
    return abs(salary_a - salary_b) / scale


def _financial_precheck_status(
    runtime: Any,
    state: Any,
    *,
    team_a: str,
    team_b: str,
    side_a_player_ids: tuple[str, ...],
    side_b_player_ids: tuple[str, ...],
    financial_snapshot: Any,
) -> tuple[str, tuple[str, ...]]:
    """Cheap Financial Bridge routing with a strict 2026-27 anchor exception.

    A true PASS stays PASS.

    A MANUAL_REVIEW may be routed forward only when:
    - live season equals the canonical runtime league year, and
    - every non-pass code is one of the exact two future-buffer uncertainty
      codes below.

    That route is not treated as legal. The canonical engine gets a read-only
    precheck and every surfaced offer still requires the full embedded preview.
    """
    if not side_a_player_ids and not side_b_player_ids:
        return "pass", ()

    evaluation = evaluate_franchise_financial_trade(
        runtime,
        state,
        team_a=normalize_team(team_a),
        team_b=normalize_team(team_b),
        side_a_player_ids=tuple(side_a_player_ids),
        side_b_player_ids=tuple(side_b_player_ids),
        snapshot=financial_snapshot,
        verify_nonmutation=False,
    )

    raw = str(getattr(evaluation, "status", "") or "").lower()
    if raw.endswith(".pass") or raw == "pass":
        status = "pass"
    elif raw.endswith(".blocked") or raw == "blocked":
        status = "blocked"
    else:
        status = "manual_review"

    reasons = tuple(
        str(getattr(check, "code", "") or "").strip()
        for check in getattr(evaluation, "checks", ()) or ()
        if str(getattr(check, "status", "") or "").lower()
        not in {"pass", "status.pass"}
        and str(getattr(check, "code", "") or "").strip()
    )

    if status == "manual_review":
        season = _clean(
            getattr(
                getattr(state, "settings", None),
                "season_label",
                "",
            )
        )
        engine_year = _clean(
            getattr(runtime, "rules", {}).get("league_year")
        )
        anchor_resolvable = {
            "future_standard_roster_minimum_review",
            "future_apron_nonplayer_charge_buffer",
        }
        if (
            season
            and season == engine_year
            and reasons
            and set(reasons).issubset(anchor_resolvable)
        ):
            return "anchor_review", reasons

    return status, reasons


def _preview_rejection_categories(preview: Any) -> tuple[str, ...]:
    categories: list[str] = []
    financial = str(getattr(preview, "financial_bridge_status", "") or "").lower()
    contract = str(getattr(preview, "player_contract_bridge_status", "") or "").lower()
    draft = str(getattr(preview, "draft_right_bridge_status", "") or "").lower()
    if financial and financial != "pass":
        categories.append("financial")
    if contract and contract != "pass":
        categories.append("player_contract")
    if draft and draft != "pass":
        categories.append("draft_right_stepien")
    for check in getattr(preview, "checks", ()) or ():
        status = str(getattr(check, "status", "") or "").lower()
        if status == "pass":
            continue
        code = str(getattr(check, "code", "") or "").lower()
        if "roster" in code:
            categories.append("roster")
        elif "ownership" in code:
            categories.append("ownership")
        elif "fingerprint" in code or "stale" in code:
            categories.append("stale_state")
        elif "canonical" in code:
            categories.append("canonical_guard")
        elif "salary" in code or "apron" in code or "financial" in code:
            categories.append("financial")
        elif "contract" in code or "player_" in code and "bridge" in code:
            categories.append("player_contract")
        elif "stepien" in code or "draft" in code or "pick" in code:
            categories.append("draft_right_stepien")
        else:
            categories.append("structural")
    if not categories:
        categories.append("other")
    return tuple(dict.fromkeys(categories))



def _canonical_pick_ids_for_market(
    ledger: FranchiseAssetLedger,
    asset_ids: tuple[str, ...],
) -> tuple[str, ...] | None:
    lookup = {
        str(row.get("asset_id")): row
        for row in ledger.draft_rows
    }
    result: list[str] = []
    for asset_id in asset_ids:
        row = lookup.get(str(asset_id))
        if not row or not bool(row.get("engine_ready")):
            return None
        canonical = _clean(row.get("canonical_pick_right_id"))
        if not canonical:
            return None
        result.append(canonical)
    return tuple(result)


def _canonical_anchor_precheck(
    runtime: Any,
    state: Any,
    ledger: FranchiseAssetLedger,
    *,
    team_a: str,
    team_b: str,
    spec: tuple[
        tuple[str, ...],
        tuple[str, ...],
        tuple[str, ...],
        tuple[str, ...],
    ],
) -> tuple[str, tuple[str, ...]]:
    season = _clean(
        getattr(
            getattr(state, "settings", None),
            "season_label",
            "",
        )
    )
    engine_year = _clean(
        getattr(runtime, "rules", {}).get("league_year")
    )
    if not season or season != engine_year:
        return "not_applicable", ()

    a_players, b_players, a_picks, b_picks = spec
    player_lookup = {
        normalize_player_id(row.get("player_id")): row
        for row in ledger.player_rows
    }

    for player_id in (*a_players, *b_players):
        normalized = normalize_player_id(player_id)
        row = player_lookup.get(normalized, {})
        if (
            not normalized
            or bool(row.get("generated_player"))
            or normalized not in getattr(runtime, "trade_by_id", {})
            or normalized not in getattr(runtime, "player_cba_by_id", {})
        ):
            return "not_applicable", ("canonical_player_coverage_incomplete",)

    canonical_a = _canonical_pick_ids_for_market(ledger, a_picks)
    canonical_b = _canonical_pick_ids_for_market(ledger, b_picks)
    if canonical_a is None or canonical_b is None:
        return "not_applicable", ("canonical_pick_mapping_incomplete",)

    request = TradeRequest(
        side_a=TradeSideRequest(
            team_abbreviation=normalize_team(team_a),
            player_ids=tuple(a_players),
            pick_right_ids=canonical_a,
        ),
        side_b=TradeSideRequest(
            team_abbreviation=normalize_team(team_b),
            player_ids=tuple(b_players),
            pick_right_ids=canonical_b,
        ),
    )
    evaluation = evaluate_trade(runtime, request)
    raw_status = getattr(
        getattr(evaluation, "status", None),
        "value",
        getattr(evaluation, "status", ""),
    )
    status = _clean(raw_status).lower()
    reasons = tuple(
        str(getattr(check, "code", "") or "").strip()
        for check in getattr(evaluation, "checks", ()) or ()
        if str(
            getattr(
                getattr(check, "status", None),
                "value",
                getattr(check, "status", ""),
            )
            or ""
        ).lower() != "pass"
        and str(getattr(check, "code", "") or "").strip()
    )
    if status == "pass":
        return "pass", reasons
    if status == "blocked":
        return "blocked", reasons
    return "manual_review", reasons


def _candidate_specs_for_target(
    *,
    active_team: str,
    partner_team: str,
    target: dict[str, Any],
    active_players: list[dict[str, Any]],
    active_picks: list[dict[str, Any]],
    partner_players: list[dict[str, Any]],
    partner_picks: list[dict[str, Any]],
    active_profile: TeamTradeAIProfile,
    partner_profile: TeamTradeAIProfile,
    ledger: FranchiseAssetLedger,
    include_picks: bool,
) -> list[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]]:
    """Build salary-aware NBA-like packages around one target.

    V1.1.1 ranks package shapes by both basketball value and live modeled salary
    balance before they ever consume a full legality evaluation. It considers
    one-, two-, and three-player outgoing constructions plus one partner filler,
    while keeping the search bounded.
    """
    target_id = normalize_player_id(target.get("player_id"))
    target_cpu_value = player_value_for_team(target, partner_profile)
    target_user_value = player_value_for_team(target, active_profile)
    target_asset = _finite(target.get("asset_score"), 50.0)
    target_tier = _shared_asset_tier(target)
    target_intrinsic = _intrinsic_player_value(target)
    premium_target = (
        target_tier in {"Franchise", "Star"}
        or target_intrinsic >= 125.0
    )

    outgoing_pool = [
        row for row in active_players
        if (not _untouchable(row, active_profile) or premium_target)
    ]
    # A blend of value fit and salary fit. Keep enough players around to permit
    # multi-player matching without brute-forcing the full roster.
    outgoing_pool = sorted(
        outgoing_pool,
        key=lambda row: (
            0.50 * abs(
                player_value_for_team(row, partner_profile) - target_cpu_value
            )
            + 0.50 * _directional_salary_route_penalty(
                _salary(row), _salary(target)
            ),
            _directional_salary_route_penalty(_salary(row), _salary(target)),
            -player_value_for_team(row, partner_profile),
            str(row.get("player_id")),
        ),
    )[:14]

    active_pick_rank = sorted(
        active_picks,
        key=lambda row: (
            -pick_value_for_team(row, ledger, partner_profile),
            int(row.get("draft_year") or 9999),
            str(row.get("asset_id")),
        ),
    )[:5]
    partner_pick_rank = sorted(
        partner_picks,
        key=lambda row: (
            pick_value_for_team(row, ledger, active_profile),
            int(row.get("draft_year") or 9999),
            str(row.get("asset_id")),
        ),
    )[:4]

    partner_fillers = sorted(
        [
            row for row in partner_players
            if normalize_player_id(row.get("player_id")) != target_id
            and not _untouchable(row, partner_profile)
            and player_value_for_team(row, active_profile) <= 75.0
        ],
        key=lambda row: (
            _salary(row),
            player_value_for_team(row, active_profile),
            str(row.get("player_id")),
        ),
    )[:5]

    active_row_map = {
        normalize_player_id(row.get("player_id")): row
        for row in outgoing_pool
    }
    partner_row_map = {
        normalize_player_id(row.get("player_id")): row
        for row in [target, *partner_fillers]
    }

    specs: list[
        tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]
    ] = []

    # Financial-routing priority: explicitly test the closest salary 1-for-1
    # structures before spending budget on aggregation or draft sweeteners.
    salary_close_one_for_one = sorted(
        outgoing_pool,
        key=lambda row: (
            _directional_salary_route_penalty(_salary(row), _salary(target)),
            abs(player_value_for_team(row, partner_profile) - target_cpu_value),
            str(row.get("player_id")),
        ),
    )[:8]
    for player in salary_close_one_for_one:
        pid = normalize_player_id(player.get("player_id"))
        specs.append(((pid,), (target_id,), (), ()))

    # 1-for-1 and player + draft capital.
    for player in outgoing_pool:
        pid = normalize_player_id(player.get("player_id"))
        specs.append(((pid,), (target_id,), (), ()))
        if include_picks:
            for pick in active_pick_rank[:3]:
                specs.append(((pid,), (target_id,), (str(pick["asset_id"]),), ()))
            # Premium targets often require more than one first-equivalent asset.
            if target_intrinsic >= 115.0 and len(active_pick_rank) >= 2:
                for pick_a, pick_b in itertools.combinations(active_pick_rank[:4], 2):
                    specs.append(
                        (
                            (pid,),
                            (target_id,),
                            (str(pick_a["asset_id"]), str(pick_b["asset_id"])),
                            (),
                        )
                    )
            if player_value_for_team(player, active_profile) > target_user_value + 5.0:
                for pick in partner_pick_rank[:2]:
                    specs.append(((pid,), (target_id,), (), (str(pick["asset_id"]),)))

    # 2-for-1 / 3-for-1 consolidation. Salary matching is part of the sort.
    combo_rows: list[tuple[dict[str, Any], ...]] = []
    for size in (2, 3):
        combo_rows.extend(itertools.combinations(outgoing_pool[:8], size))
    combo_rows.sort(
        key=lambda combo: (
            _directional_salary_route_penalty(
                sum(_salary(row) for row in combo),
                _salary(target),
            ),
            abs(
                sum(
                    player_value_for_team(row, partner_profile)
                    for row in combo
                )
                - target_cpu_value
            ),
            len(combo),
        )
    )
    for combo in combo_rows[:18]:
        ids = tuple(normalize_player_id(row.get("player_id")) for row in combo)
        specs.append((ids, (target_id,), (), ()))
        if include_picks:
            for pick in active_pick_rank[:2]:
                specs.append((ids, (target_id,), (str(pick["asset_id"]),), ()))
            if target_intrinsic >= 125.0 and len(active_pick_rank) >= 2:
                for pick_a, pick_b in itertools.combinations(active_pick_rank[:3], 2):
                    specs.append(
                        (
                            ids,
                            (target_id,),
                            (str(pick_a["asset_id"]), str(pick_b["asset_id"])),
                            (),
                        )
                    )

    # Salary/depth balancing on the receiving side. Target + one lower-value
    # filler frequently creates a much better legal salary path than target alone.
    for filler in partner_fillers:
        filler_id = normalize_player_id(filler.get("player_id"))
        receiving_ids = (target_id, filler_id)
        receiving_salary = _salary(target) + _salary(filler)
        receiving_value = (
            target_cpu_value
            + player_value_for_team(filler, partner_profile)
        )
        # 1-for-2
        ranked_one = sorted(
            outgoing_pool,
            key=lambda row: (
                _directional_salary_route_penalty(
                    _salary(row),
                    receiving_salary,
                ),
                abs(
                    player_value_for_team(row, partner_profile)
                    - receiving_value
                ),
            ),
        )[:3]
        for player in ranked_one:
            specs.append(
                (
                    (normalize_player_id(player.get("player_id")),),
                    receiving_ids,
                    (),
                    (),
                )
            )
        # 2-for-2
        pairs = list(itertools.combinations(outgoing_pool[:8], 2))
        pairs.sort(
            key=lambda combo: (
                _directional_salary_route_penalty(
                    sum(_salary(row) for row in combo),
                    receiving_salary,
                ),
                abs(
                    sum(
                        player_value_for_team(row, partner_profile)
                        for row in combo
                    )
                    - receiving_value
                ),
            )
        )
        for combo in pairs[:3]:
            specs.append(
                (
                    tuple(normalize_player_id(row.get("player_id")) for row in combo),
                    receiving_ids,
                    (),
                    (),
                )
            )

    # Picks can acquire lower-end players, but never emit asset-only swaps.
    if include_picks and target_cpu_value <= 60.0:
        for pick in active_pick_rank[:2]:
            specs.append(((), (target_id,), (str(pick["asset_id"]),), ()))

    # De-duplicate then salary-rank the final list. Equal-ish salary is not itself
    # a legality decision, but it is a powerful routing signal for apron teams.
    seen = set()
    output = []
    all_player_rows = {**active_row_map, **partner_row_map}
    for spec in specs:
        key = tuple(tuple(part) for part in spec)
        if key in seen:
            continue
        seen.add(key)
        if not spec[0] and not spec[1]:
            continue
        output.append(spec)

    local_pick_map = {
        str(row.get("asset_id")): row
        for row in [*active_pick_rank, *partner_pick_rank]
        if str(row.get("asset_id") or "")
    }

    def priority(spec):
        a_players, b_players, a_picks, b_picks = spec
        salary_gap = _salary_gap_ratio(a_players, b_players, all_player_rows)
        a_value = sum(
            player_value_for_team(all_player_rows.get(pid, {}), partner_profile)
            for pid in a_players
        )
        b_value = sum(
            player_value_for_team(all_player_rows.get(pid, {}), partner_profile)
            for pid in b_players
        )
        a_value += sum(
            pick_value_for_team(local_pick_map[aid], ledger, partner_profile)
            for aid in a_picks if aid in local_pick_map
        )
        b_value += sum(
            pick_value_for_team(local_pick_map[aid], ledger, partner_profile)
            for aid in b_picks if aid in local_pick_map
        )
        value_gap = abs(a_value - b_value) / max(a_value, b_value, 1.0)
        complexity = 0.025 * max(0, len(a_players) + len(b_players) - 2)
        return (
            0.68 * salary_gap + 0.32 * value_gap + complexity,
            salary_gap,
            value_gap,
            len(a_players) + len(b_players),
        )

    output.sort(key=priority)
    return output[:32]



def _proposal_id(
    active_team: str,
    partner_team: str,
    spec: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]],
    response: str,
) -> str:
    payload = {
        "a": active_team,
        "b": partner_team,
        "spec": spec,
        "response": response,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return f"TF-{digest[:12].upper()}"


def _evaluate_spec(
    runtime: Any,
    state: Any,
    trade_state: Any,
    ledger: FranchiseAssetLedger,
    *,
    active_team: str,
    partner_team: str,
    spec: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]],
    financial_snapshot: Any | None = None,
    contract_snapshot: Any | None = None,
) -> tuple[Any, dict[str, Any]] | None:
    a_players, b_players, a_picks, b_picks = spec
    preview = build_franchise_trade_preview(
        runtime,
        state,
        trade_state,
        team_a=active_team,
        team_b=partner_team,
        side_a_player_ids=a_players,
        side_b_player_ids=b_players,
        side_a_pick_asset_ids=a_picks,
        side_b_pick_asset_ids=b_picks,
        ledger=ledger,
        financial_snapshot=financial_snapshot,
        player_contract_snapshot=contract_snapshot,
        market_read_only_fast_path=bool(financial_snapshot is not None or contract_snapshot is not None),
    )
    if preview.status != "pass" or not preview.can_commit:
        return None
    return preview, preview_to_dict(preview)


def _values_for_spec(
    *,
    spec: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]],
    active_profile: TeamTradeAIProfile,
    partner_profile: TeamTradeAIProfile,
    player_map: dict[str, dict[str, Any]],
    pick_map: dict[str, dict[str, Any]],
    ledger: FranchiseAssetLedger,
    active_goal: str,
) -> tuple[float, float, float, float, float, float]:
    a_players, b_players, a_picks, b_picks = spec
    user_sent = _bundle_value(
        player_ids=a_players,
        pick_ids=a_picks,
        player_map=player_map,
        pick_map=pick_map,
        ledger=ledger,
        profile=active_profile,
        goal=active_goal,
    )
    user_received = _bundle_value(
        player_ids=b_players,
        pick_ids=b_picks,
        player_map=player_map,
        pick_map=pick_map,
        ledger=ledger,
        profile=active_profile,
        goal=active_goal,
    )
    cpu_sent = _bundle_value(
        player_ids=b_players,
        pick_ids=b_picks,
        player_map=player_map,
        pick_map=pick_map,
        ledger=ledger,
        profile=partner_profile,
        goal=GOAL_BEST_AVAILABLE,
    )
    cpu_received = _bundle_value(
        player_ids=a_players,
        pick_ids=a_picks,
        player_map=player_map,
        pick_map=pick_map,
        ledger=ledger,
        profile=partner_profile,
        goal=GOAL_BEST_AVAILABLE,
    )
    return (
        user_sent,
        user_received,
        round(user_received - user_sent, 2),
        cpu_sent,
        cpu_received,
        round(cpu_received - cpu_sent, 2),
    )


def _cpu_accept_floor(
    *,
    partner_profile: TeamTradeAIProfile,
    target: dict[str, Any] | None,
) -> float:
    floor = 0.0
    if partner_profile.timeline == "contender":
        floor = 0.75
    elif partner_profile.timeline == "rebuild":
        floor = -0.5

    if target is None:
        return floor

    overall = _finite(target.get("overall"), 60.0)
    age = _finite(target.get("age"), 27.0)
    tier = _shared_asset_tier(target)
    intrinsic = _intrinsic_player_value(target)

    if tier == "Franchise":
        floor = max(floor, 12.0)
        if intrinsic >= 160.0:
            floor = max(floor, 18.0)
        elif age <= 29.0 and intrinsic >= 150.0:
            floor = max(floor, 16.0)

    elif tier == "Star":
        floor = max(floor, 3.0)
        if age <= 25.0 and intrinsic >= 130.0:
            floor = max(floor, 14.0)
        elif intrinsic >= 135.0:
            floor = max(floor, 8.0)

    elif tier == "High-End Starter":
        floor = max(floor, 0.5)

    elif overall >= 90.0:
        floor = max(floor, 1.5)

    return floor


def _fit_score(
    target: dict[str, Any] | None,
    active_profile: TeamTradeAIProfile,
    goal: str,
) -> float:
    if target is None:
        return 0.0
    family = position_family(str(target.get("position", "")))
    need = min(16.0, max(0.0, active_profile.need_scores.get(family, 0.0)))
    score = 0.4 * need
    if family == active_profile.biggest_need:
        score += 2.0
    overall = _finite(target.get("overall"), 60.0)
    potential = _finite(target.get("potential"), overall)
    age = _finite(target.get("age"), 27.0)
    if goal == GOAL_WIN_NOW:
        score += max(0.0, overall - 80.0) * 0.25
    elif goal == GOAL_FUTURE_UPSIDE:
        score += max(0.0, potential - overall) * 0.35 + max(0.0, 25.0 - age) * 0.25
    return round(score, 2)


def _deal_type(
    spec: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]],
    target: dict[str, Any] | None,
    active_profile: TeamTradeAIProfile,
) -> str:
    a_players, b_players, a_picks, b_picks = spec
    if target is not None:
        family = position_family(str(target.get("position", "")))
        overall = _finite(target.get("overall"), 60.0)
        if overall >= 90.0:
            return "Star pursuit"
        if family == active_profile.biggest_need:
            return "Need upgrade"
    if len(a_players) >= 2 and len(b_players) == 1:
        return "Consolidation"
    if len(a_players) == 1 and len(b_players) >= 2:
        return "Depth rebalance"
    if a_picks or b_picks:
        return "Player + draft capital"
    return "Player swap"


def _make_proposal(
    *,
    spec: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]],
    active_team: str,
    partner_team: str,
    goal: str,
    response: str,
    preview_payload: dict[str, Any],
    active_profile: TeamTradeAIProfile,
    partner_profile: TeamTradeAIProfile,
    player_map: dict[str, dict[str, Any]],
    pick_map: dict[str, dict[str, Any]],
    ledger: FranchiseAssetLedger,
    target: dict[str, Any] | None,
    counter_sweetener: str = "",
) -> FranchiseTradeFinderProposal:
    values = _values_for_spec(
        spec=spec,
        active_profile=active_profile,
        partner_profile=partner_profile,
        player_map=player_map,
        pick_map=pick_map,
        ledger=ledger,
        active_goal=goal,
    )
    user_sent, user_received, user_delta, cpu_sent, cpu_received, cpu_delta = values
    fit = _fit_score(target, active_profile, goal)
    response_bonus = 3.0 if response == "accept" else 1.0 if response == "counter" else -0.5 if response == "overpay" else 0.0
    ranking = round(user_delta + 1.7 * fit + response_bonus + min(3.0, max(-3.0, cpu_delta * 0.25)), 2)
    a_players, b_players, a_picks, b_picks = spec
    target_id = normalize_player_id(target.get("player_id")) if target else ""
    target_name = _clean(target.get("player_name")) if target else ""
    received = _asset_label(
        player_map,
        pick_map,
        player_ids=b_players,
        pick_ids=b_picks,
    )
    sent = _asset_label(
        player_map,
        pick_map,
        player_ids=a_players,
        pick_ids=a_picks,
    )
    if response == "accept":
        rationale = (
            f"{partner_team} projects this as acceptable value while {active_team} addresses "
            f"{active_profile.biggest_need.lower()} / timeline fit. {active_team} receives {received} "
            f"and sends {sent}."
        )
        response_label = "CPU ACCEPT"
    elif response == "counter":
        rationale = (
            f"{partner_team} would not accept the original value balance, but this legal counter "
            f"closes the gap. {active_team} receives {received} and sends {sent}."
        )
        response_label = "CPU COUNTER"
    elif response == "overpay":
        rationale = (
            f"{partner_team} would accept the value, but the Trade Finder blocks this as an "
            f"overpay for {active_team}. It is shown for comparison, not as an executable recommendation."
        )
        response_label = "USER VALUE GUARD"
    else:
        rationale = (
            f"This package is legal and financially routable, but {partner_team} still sees a "
            f"value gap. It is shown as a negotiation lead, not an executable CPU-approved deal."
        )
        response_label = "CPU DECLINES"
    proposal_payload = copy.deepcopy(preview_payload)
    morale_terms_v5b = dict(
        (target or {}).get(
            "_morale_trade_finder_terms_v1",
            {},
        )
        or {}
    )
    if morale_terms_v5b:
        proposal_payload[
            "morale_trade_finder_terms_v1"
        ] = copy.deepcopy(morale_terms_v5b)
    return FranchiseTradeFinderProposal(
        proposal_id=_proposal_id(active_team, partner_team, spec, response),
        active_team=active_team,
        partner_team=partner_team,
        goal=goal,
        cpu_response=response,
        response_label=response_label,
        side_a_player_ids=tuple(a_players),
        side_b_player_ids=tuple(b_players),
        side_a_pick_asset_ids=tuple(a_picks),
        side_b_pick_asset_ids=tuple(b_picks),
        user_value_sent=user_sent,
        user_value_received=user_received,
        user_value_delta=user_delta,
        cpu_value_sent=cpu_sent,
        cpu_value_received=cpu_received,
        cpu_value_delta=cpu_delta,
        fit_score=fit,
        ranking_score=ranking,
        target_player_id=target_id,
        target_player_name=target_name,
        rationale=rationale,
        preview_payload=proposal_payload,
        deal_type=_deal_type(spec, target, active_profile),
        counter_sweetener=counter_sweetener,
    )



def _audit_player_columns(
    *,
    prefix: str,
    player_ids: Iterable[str],
    player_map: dict[str, dict[str, Any]],
    active_profile: TeamTradeAIProfile,
    partner_profile: TeamTradeAIProfile,
    goal: str,
    max_players: int = 5,
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    ids = [normalize_player_id(value) for value in player_ids if normalize_player_id(value)]
    for index in range(1, max_players + 1):
        base = f"{prefix}_player_{index}"
        if index > len(ids):
            for suffix in (
                "id", "name", "position", "age", "overall", "potential",
                "future_outlook", "salary", "years_remaining", "role",
                "career_status", "availability", "asset_score",
                "shared_asset_tier", "shared_market_score",
                "shared_organizational_score", "shared_trade_value",
                "shared_market_percentile", "shared_age_curve_score",
                "shared_contract_control_score", "shared_salary_efficiency_score",
                "shared_availability_score", "shared_context_confidence",
                "intrinsic_value", "fit_value_active", "fit_value_partner",
                "value_to_active", "value_to_partner",
            ):
                output[f"{base}_{suffix}"] = ""
            continue
        pid = ids[index - 1]
        row = player_map.get(pid, {})
        output[f"{base}_id"] = pid
        output[f"{base}_name"] = _clean(row.get("player_name")) or pid
        output[f"{base}_position"] = _clean(row.get("position")) or "UNK"
        output[f"{base}_age"] = _finite(row.get("age"), 0.0)
        output[f"{base}_overall"] = _finite(row.get("overall"), 0.0)
        output[f"{base}_potential"] = _finite(row.get("potential"), _finite(row.get("overall"), 0.0))
        output[f"{base}_future_outlook"] = _finite(row.get("future_outlook"), _finite(row.get("potential"), 0.0))
        output[f"{base}_salary"] = _finite(row.get("salary"), 0.0)
        output[f"{base}_years_remaining"] = int(row.get("years_remaining") or 0)
        output[f"{base}_role"] = _clean(row.get("role"))
        output[f"{base}_career_status"] = _clean(row.get("career_status"))
        output[f"{base}_availability"] = _clean(row.get("availability"))
        output[f"{base}_asset_score"] = _finite(row.get("asset_score"), 0.0)
        output[f"{base}_shared_asset_tier"] = _shared_asset_tier(row)
        output[f"{base}_shared_market_score"] = _finite(row.get("_shared_market_score"), 0.0)
        output[f"{base}_shared_organizational_score"] = _finite(row.get("_shared_organizational_score"), 0.0)
        output[f"{base}_shared_trade_value"] = _intrinsic_player_value(row)
        output[f"{base}_shared_market_percentile"] = _finite(row.get("_shared_market_percentile"), 0.0)
        output[f"{base}_shared_age_curve_score"] = _finite(row.get("_shared_age_curve_score"), 0.0)
        output[f"{base}_shared_contract_control_score"] = _finite(row.get("_shared_contract_control_score"), 0.0)
        output[f"{base}_shared_salary_efficiency_score"] = _finite(row.get("_shared_salary_efficiency_score"), 0.0)
        output[f"{base}_shared_availability_score"] = _finite(row.get("_shared_availability_score"), 0.0)
        output[f"{base}_shared_context_confidence"] = _finite(row.get("_shared_context_confidence"), 0.0)
        output[f"{base}_intrinsic_value"] = round(_intrinsic_player_value(row), 2)
        output[f"{base}_fit_value_active"] = round(_goal_player_bonus(row, active_profile, goal), 2)
        output[f"{base}_fit_value_partner"] = round(_goal_player_bonus(row, partner_profile, GOAL_BEST_AVAILABLE), 2)
        output[f"{base}_value_to_active"] = player_value_for_team(
            row, active_profile, goal=goal
        )
        output[f"{base}_value_to_partner"] = player_value_for_team(
            row, partner_profile, goal=GOAL_BEST_AVAILABLE
        )
    return output


def _audit_pick_columns(
    *,
    prefix: str,
    pick_ids: Iterable[str],
    pick_map: dict[str, dict[str, Any]],
    ledger: FranchiseAssetLedger,
    active_profile: TeamTradeAIProfile,
    partner_profile: TeamTradeAIProfile,
    max_picks: int = 4,
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    ids = [str(value) for value in pick_ids if str(value)]
    for index in range(1, max_picks + 1):
        base = f"{prefix}_pick_{index}"
        if index > len(ids):
            for suffix in (
                "asset_id", "name", "year", "round", "origin_team",
                "current_owner", "tradability_status",
                "value_to_active", "value_to_partner",
            ):
                output[f"{base}_{suffix}"] = ""
            continue
        aid = ids[index - 1]
        row = pick_map.get(aid, {})
        output[f"{base}_asset_id"] = aid
        output[f"{base}_name"] = _clean(row.get("display_name")) or aid
        output[f"{base}_year"] = int(row.get("draft_year") or 0)
        output[f"{base}_round"] = int(row.get("round") or 0)
        output[f"{base}_origin_team"] = _clean(row.get("origin_team"))
        output[f"{base}_current_owner"] = _clean(row.get("current_owner"))
        output[f"{base}_tradability_status"] = _clean(row.get("tradability_status"))
        output[f"{base}_value_to_active"] = pick_value_for_team(
            row, ledger, active_profile
        ) if row else 0.0
        output[f"{base}_value_to_partner"] = pick_value_for_team(
            row, ledger, partner_profile
        ) if row else 0.0
    return output


def _new_package_audit_row(
    *,
    audit_id: str,
    spec: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]],
    active_team: str,
    partner_team: str,
    goal: str,
    target: dict[str, Any] | None,
    active_profile: TeamTradeAIProfile,
    partner_profile: TeamTradeAIProfile,
    player_map: dict[str, dict[str, Any]],
    pick_map: dict[str, dict[str, Any]],
    ledger: FranchiseAssetLedger,
    values: tuple[float, float, float, float, float, float],
    accept_floor: float,
    guaranteed_exploration: bool,
) -> dict[str, Any]:
    a_players, b_players, a_picks, b_picks = spec
    user_sent, user_received, user_delta, cpu_sent, cpu_received, cpu_delta = values
    target_row = target or {}
    morale_terms_v5b = dict(
        target_row.get(
            "_morale_trade_finder_terms_v1",
            {},
        )
        or {}
    )
    output: dict[str, Any] = {
        "audit_id": audit_id,
        "trade_finder_version": TRADE_FINDER_AI_VERSION,
        "value_model_version": TRADE_FINDER_VALUE_MODEL_VERSION,
        "shared_asset_market_context_version": ASSET_MARKET_CONTEXT_VERSION,
        "shared_asset_market_model_version": ASSET_MARKET_MODEL_VERSION,
        "season_label": ledger.season_label,
        "active_team": active_team,
        "partner_team": partner_team,
        "search_goal": goal,
        "deal_type": _deal_type(spec, target, active_profile),
        "route_stage": "generated_not_routed",
        "final_cpu_response": "",
        "target_player_id": normalize_player_id(target_row.get("player_id")) if target else "",
        "target_player_name": _clean(target_row.get("player_name")) if target else "",
        "target_position": _clean(target_row.get("position")) if target else "",
        "target_age": _finite(target_row.get("age"), 0.0) if target else "",
        "target_overall": _finite(target_row.get("overall"), 0.0) if target else "",
        "target_potential": _finite(target_row.get("potential"), 0.0) if target else "",
        "target_salary": _finite(target_row.get("salary"), 0.0) if target else "",
        "target_shared_asset_tier": _shared_asset_tier(target_row) if target else "",
        "target_shared_market_score": _finite(target_row.get("_shared_market_score"), 0.0) if target else "",
        "target_shared_trade_value": _intrinsic_player_value(target_row) if target else "",
        "target_shared_market_percentile": _finite(target_row.get("_shared_market_percentile"), 0.0) if target else "",
        "target_value_to_active": player_value_for_team(target_row, active_profile, goal=goal) if target else "",
        "target_value_to_partner": player_value_for_team(target_row, partner_profile) if target else "",
        "active_team_timeline": active_profile.timeline,
        "partner_team_timeline": partner_profile.timeline,
        "active_team_biggest_need": active_profile.biggest_need,
        "partner_team_biggest_need": partner_profile.biggest_need,
        "side_a_player_count": len(a_players),
        "side_b_player_count": len(b_players),
        "side_a_pick_count": len(a_picks),
        "side_b_pick_count": len(b_picks),
        "side_a_player_names": _asset_label(
            player_map, {}, player_ids=a_players, pick_ids=()
        ),
        "side_b_player_names": _asset_label(
            player_map, {}, player_ids=b_players, pick_ids=()
        ),
        "side_a_pick_names": _asset_label(
            {}, pick_map, player_ids=(), pick_ids=a_picks
        ),
        "side_b_pick_names": _asset_label(
            {}, pick_map, player_ids=(), pick_ids=b_picks
        ),
        "side_a_salary": _bundle_salary(a_players, player_map),
        "side_b_salary": _bundle_salary(b_players, player_map),
        "user_value_sent": user_sent,
        "user_value_received": user_received,
        "user_value_delta": user_delta,
        "cpu_value_sent": cpu_sent,
        "cpu_value_received": cpu_received,
        "cpu_value_delta": cpu_delta,
        "cpu_accept_floor": accept_floor,
        "cpu_accept_floor_base": morale_terms_v5b.get("base_accept_floor", accept_floor),
        "morale_market_floor_adjustment": morale_terms_v5b.get("floor_adjustment", 0.0),
        "morale_market_posture": morale_terms_v5b.get("market_posture", ""),
        "morale_trade_risk": morale_terms_v5b.get("trade_risk", 0.0),
        "morale_trade_request": morale_terms_v5b.get("request_status", ""),
        "seller_ask_multiplier": morale_terms_v5b.get("seller_ask_multiplier", 1.0),
        "morale_market_search_bonus": morale_terms_v5b.get("search_priority_bonus", 0.0),
        "roster_fit": _fit_score(target, active_profile, goal),
        "guaranteed_exploration": bool(guaranteed_exploration),
        "value_screen_pass": False,
        "financial_status": "not_checked",
        "financial_reason_codes": "",
        "canonical_precheck_status": "not_checked",
        "canonical_precheck_reason_codes": "",
        "anchor_financial_resolution_applied": False,
        "full_legality_status": "not_checked",
        "can_commit": False,
        "legality_reason_codes": "",
        "counter_sweetener": "",
    }
    output.update(
        _audit_player_columns(
            prefix="side_a",
            player_ids=a_players,
            player_map=player_map,
            active_profile=active_profile,
            partner_profile=partner_profile,
            goal=goal,
        )
    )
    output.update(
        _audit_player_columns(
            prefix="side_b",
            player_ids=b_players,
            player_map=player_map,
            active_profile=active_profile,
            partner_profile=partner_profile,
            goal=goal,
        )
    )
    output.update(
        _audit_pick_columns(
            prefix="side_a",
            pick_ids=a_picks,
            pick_map=pick_map,
            ledger=ledger,
            active_profile=active_profile,
            partner_profile=partner_profile,
        )
    )
    output.update(
        _audit_pick_columns(
            prefix="side_b",
            pick_ids=b_picks,
            pick_map=pick_map,
            ledger=ledger,
            active_profile=active_profile,
            partner_profile=partner_profile,
        )
    )
    return output


def _audit_legality_codes(preview: Any) -> str:
    codes = []
    for check in getattr(preview, "checks", ()) or ():
        if str(getattr(check, "status", "") or "").lower() == "pass":
            continue
        code = str(getattr(check, "code", "") or "").strip()
        if code and code not in codes:
            codes.append(code)
    return "|".join(codes)


def _find_counter(
    runtime: Any,
    state: Any,
    trade_state: Any,
    ledger: FranchiseAssetLedger,
    *,
    active_team: str,
    partner_team: str,
    base_spec: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]],
    active_players: list[dict[str, Any]],
    active_picks: list[dict[str, Any]],
    active_profile: TeamTradeAIProfile,
    partner_profile: TeamTradeAIProfile,
    player_map: dict[str, dict[str, Any]],
    pick_map: dict[str, dict[str, Any]],
    goal: str,
    target: dict[str, Any] | None,
    include_picks: bool,
    accept_floor: float,
    financial_snapshot: Any | None = None,
    contract_snapshot: Any | None = None,
    max_attempts: int = 3,
) -> tuple[
    tuple[
        tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]],
        dict[str, Any],
        str,
    ] | None,
    int,
]:
    a_players, b_players, a_picks, b_picks = base_spec
    _, _, _, _, _, current_cpu_delta = _values_for_spec(
        spec=base_spec,
        active_profile=active_profile,
        partner_profile=partner_profile,
        player_map=player_map,
        pick_map=pick_map,
        ledger=ledger,
        active_goal=goal,
    )
    needed = max(0.0, accept_floor - current_cpu_delta)
    candidates = []

    if include_picks:
        pick_rows = [
            row
            for row in active_picks
            if str(row.get("asset_id")) not in a_picks
        ]
        pick_rows.sort(
            key=lambda row: (
                -pick_value_for_team(row, ledger, partner_profile),
                int(row.get("draft_year") or 9999),
                str(row.get("asset_id")),
            )
        )
        pick_rows = pick_rows[:5]

        for row in pick_rows:
            aid = str(row.get("asset_id"))
            value = pick_value_for_team(row, ledger, partner_profile)
            spec = (a_players, b_players, tuple((*a_picks, aid)), b_picks)
            label = _clean(pick_map.get(aid, {}).get("display_name")) or aid
            candidates.append((abs(value - needed), spec, label))

        # Two-pick rescue for premium targets / larger value gaps.
        if len(pick_rows) >= 2 and (
            needed >= 10.0
            or (
                target is not None
                and _shared_asset_tier(target) in {"Franchise", "Star"}
            )
        ):
            for left, right in itertools.combinations(pick_rows[:4], 2):
                left_id = str(left.get("asset_id"))
                right_id = str(right.get("asset_id"))
                combined = (
                    pick_value_for_team(left, ledger, partner_profile)
                    + pick_value_for_team(right, ledger, partner_profile)
                )
                spec = (
                    a_players,
                    b_players,
                    tuple((*a_picks, left_id, right_id)),
                    b_picks,
                )
                left_label = _clean(
                    pick_map.get(left_id, {}).get("display_name")
                ) or left_id
                right_label = _clean(
                    pick_map.get(right_id, {}).get("display_name")
                ) or right_id
                candidates.append(
                    (
                        abs(combined - needed),
                        spec,
                        f"{left_label} + {right_label}",
                    )
                )

    for row in active_players:
        player_id = normalize_player_id(row.get("player_id"))
        if player_id in a_players:
            continue
        value = player_value_for_team(row, partner_profile)
        if value <= 75.0:
            candidates.append(
                (
                    abs(value - needed),
                    (tuple((*a_players, player_id)), b_players, a_picks, b_picks),
                    _player_name(player_map, player_id),
                )
            )

    candidates.sort(
        key=lambda item: (
            item[0],
            len(item[1][0]) + len(item[1][2]),
            item[2],
        )
    )

    attempts = 0
    seen = set()
    for _, counter_spec, sweetener in candidates:
        key = tuple(tuple(part) for part in counter_spec)
        if key in seen:
            continue
        seen.add(key)

        values = _values_for_spec(
            spec=counter_spec,
            active_profile=active_profile,
            partner_profile=partner_profile,
            player_map=player_map,
            pick_map=pick_map,
            ledger=ledger,
            active_goal=goal,
        )
        _, _, user_delta, _, _, cpu_delta = values
        if cpu_delta < accept_floor or user_delta < -12.0:
            continue

        attempts += 1
        legal = _evaluate_spec(
            runtime,
            state,
            trade_state,
            ledger,
            active_team=active_team,
            partner_team=partner_team,
            spec=counter_spec,
            financial_snapshot=financial_snapshot,
            contract_snapshot=contract_snapshot,
        )
        if legal is not None:
            _, payload = legal
            return (counter_spec, payload, sweetener), attempts

        if attempts >= max(1, int(max_attempts)):
            break

    return None, attempts


def _fallback_second_round_swaps(
    runtime: Any,
    state: Any,
    trade_state: Any,
    ledger: FranchiseAssetLedger,
    *,
    active_team: str,
    partners: list[str],
    picks_by_team: dict[str, list[dict[str, Any]]],
    profiles: dict[str, TeamTradeAIProfile],
    player_map: dict[str, dict[str, Any]],
    pick_map: dict[str, dict[str, Any]],
    goal: str,
    max_results: int,
    max_evaluations: int = 8,
) -> tuple[list[FranchiseTradeFinderProposal], int, int]:
    proposals: list[FranchiseTradeFinderProposal] = []
    evaluated = 0
    legal_count = 0
    active_seconds = [
        row for row in picks_by_team.get(active_team, [])
        if int(row.get("round") or 0) == 2
    ]
    for partner in partners:
        partner_seconds = [
            row for row in picks_by_team.get(partner, [])
            if int(row.get("round") or 0) == 2
        ]
        pairs = sorted(
            (
                (a, b)
                for a in active_seconds
                for b in partner_seconds
            ),
            key=lambda pair: (
                abs(int(pair[0].get("draft_year") or 0) - int(pair[1].get("draft_year") or 0)),
                int(pair[0].get("draft_year") or 9999),
                int(pair[1].get("draft_year") or 9999),
            ),
        )[:3]
        for a_pick, b_pick in pairs:
            if evaluated >= max(1, int(max_evaluations)):
                return proposals, evaluated, legal_count
            spec = ((), (), (str(a_pick["asset_id"]),), (str(b_pick["asset_id"]),))
            evaluated += 1
            legal = _evaluate_spec(
                runtime,
                state,
                trade_state,
                ledger,
                active_team=active_team,
                partner_team=partner,
                spec=spec,
            )
            if legal is None:
                continue
            legal_count += 1
            _, payload = legal
            active_profile = profiles[active_team]
            partner_profile = profiles[partner]
            values = _values_for_spec(
                spec=spec,
                active_profile=active_profile,
                partner_profile=partner_profile,
                player_map=player_map,
                pick_map=pick_map,
                ledger=ledger,
                active_goal=goal,
            )
            user_sent, user_received, user_delta, cpu_sent, cpu_received, cpu_delta = values
            # Equal-round future-capital swaps are deliberately permissive fallback
            # offers. They are still subject to the live legality bridges.
            if cpu_delta < -3.0 or user_delta < -8.0:
                continue
            proposals.append(
                _make_proposal(
                    spec=spec,
                    active_team=active_team,
                    partner_team=partner,
                    goal=goal,
                    response="accept",
                    preview_payload=payload,
                    active_profile=active_profile,
                    partner_profile=partner_profile,
                    player_map=player_map,
                    pick_map=pick_map,
                    ledger=ledger,
                    target=None,
                )
            )
            if len(proposals) >= max_results:
                return proposals, evaluated, legal_count
    return proposals, evaluated, legal_count


# FRANCHISE_TRADE_MARKET_PERFORMANCE_V7_1
@dataclass(frozen=True)
class FranchiseTradeFinderSearchContext:
    """Reusable, read-only setup shared across repeated searches on one live state.

    Full package legality is still evaluated independently for every candidate.
    This cache only avoids reconstructing identical ledgers/snapshots/profiles and
    market pools when V6A/V6B query the same postgame state repeatedly.
    """

    ledger: FranchiseAssetLedger
    financial_snapshot: Any
    contract_snapshot: Any
    profiles: dict[str, TeamTradeAIProfile]
    shared_contexts: dict[str, AssetMarketContext]
    tradable_players: dict[str, tuple[dict[str, Any], ...]]
    tradable_picks: dict[str, tuple[dict[str, Any], ...]]
    player_map: dict[str, dict[str, Any]]
    pick_map: dict[str, dict[str, Any]]
    build_timing: dict[str, float] = field(default_factory=dict)


def build_trade_finder_search_context(
    runtime: Any,
    state: Any,
    trade_state: Any,
    *,
    ledger: FranchiseAssetLedger | None = None,
    trusted_read_only_state: bool = False,
) -> FranchiseTradeFinderSearchContext:
    # FRANCHISE_TRADE_MARKET_PERFORMANCE_V7_3
    # Diagnostic-only substage timings expose which immutable context component
    # dominates V6B setup. They do not change search inputs or legality.
    build_timing: dict[str, float] = {}

    _stage_started = time.perf_counter()
    live_ledger = ledger or build_live_asset_ledger(runtime, state, trade_state)
    build_timing["ledger"] = round(time.perf_counter() - _stage_started, 4)

    _stage_started = time.perf_counter()
    financial_snapshot = build_franchise_financial_snapshot(runtime, state)
    build_timing["financial"] = round(time.perf_counter() - _stage_started, 4)

    _stage_started = time.perf_counter()
    contract_snapshot = build_franchise_player_contract_snapshot(
        runtime,
        state,
        # FRANCHISE_TRADE_MARKET_PERFORMANCE_V7_4
        # The snapshot builder is read-only. Skip only its expensive defensive
        # clone/equality audit when the caller explicitly certifies that this
        # state is already an isolated transaction.
        verify_immutability=not trusted_read_only_state,
    )
    build_timing["contracts"] = round(time.perf_counter() - _stage_started, 4)

    _stage_started = time.perf_counter()
    profiles = build_team_trade_ai_profiles(state, live_ledger)
    build_timing["profiles"] = round(time.perf_counter() - _stage_started, 4)

    _stage_started = time.perf_counter()
    shared_contexts_raw = build_league_asset_market_contexts(
        state,
        team_timelines={team: profile.timeline for team, profile in profiles.items()},
    )
    build_timing["market_contexts"] = round(time.perf_counter() - _stage_started, 4)
    shared_contexts = {
        normalize_player_id(player_id): context
        for player_id, context in shared_contexts_raw.items()
        if normalize_player_id(player_id)
    }

    _stage_started = time.perf_counter()
    tradable_players_working = _tradable_players_by_team(
        runtime, state, live_ledger, contract_snapshot=contract_snapshot
    )
    for rows in tradable_players_working.values():
        _annotate_rows_with_shared_context(rows, shared_contexts)
    build_timing["player_pool"] = round(time.perf_counter() - _stage_started, 4)

    _stage_started = time.perf_counter()
    tradable_picks_working = _tradable_picks_by_team(live_ledger)
    for rows in tradable_picks_working.values():
        for row in rows:
            origin = normalize_team(row.get("origin_team"))
            origin_profile = profiles.get(origin)
            if origin_profile is not None:
                row["_origin_win_pct"] = origin_profile.win_pct
                row["_origin_timeline"] = origin_profile.timeline
    build_timing["pick_pool"] = round(time.perf_counter() - _stage_started, 4)

    _stage_started = time.perf_counter()
    player_map = {
        normalize_player_id(row.get("player_id")): dict(row)
        for row in live_ledger.player_rows
    }
    _annotate_rows_with_shared_context(player_map.values(), shared_contexts)
    pick_map = {
        str(row.get("asset_id")): dict(row)
        for row in live_ledger.draft_rows
    }
    for row in pick_map.values():
        origin = normalize_team(row.get("origin_team"))
        origin_profile = profiles.get(origin)
        if origin_profile is not None:
            row["_origin_win_pct"] = origin_profile.win_pct
            row["_origin_timeline"] = origin_profile.timeline
    build_timing["maps"] = round(time.perf_counter() - _stage_started, 4)

    _stage_started = time.perf_counter()
    result = FranchiseTradeFinderSearchContext(
        ledger=live_ledger,
        financial_snapshot=financial_snapshot,
        contract_snapshot=contract_snapshot,
        profiles=profiles,
        shared_contexts=shared_contexts,
        tradable_players={
            team: tuple(dict(row) for row in rows)
            for team, rows in tradable_players_working.items()
        },
        tradable_picks={
            team: tuple(dict(row) for row in rows)
            for team, rows in tradable_picks_working.items()
        },
        player_map={key: dict(row) for key, row in player_map.items()},
        pick_map={key: dict(row) for key, row in pick_map.items()},
        build_timing=build_timing,
    )
    build_timing["freeze"] = round(time.perf_counter() - _stage_started, 4)
    return result


def generate_trade_finder_proposals(
    runtime: Any,
    state: Any,
    trade_state: Any,
    *,
    active_team: str,
    goal: str = GOAL_BEST_AVAILABLE,
    partner_team: str = "",
    include_picks: bool = True,
    max_results: int = 8,
    max_partners: int = 29,
    max_targets_per_partner: int = 4,
    max_package_evaluations: int = 72,
    max_financial_prechecks: int = 480,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ledger: FranchiseAssetLedger | None = None,
    search_context: FranchiseTradeFinderSearchContext | None = None,
) -> FranchiseTradeFinderResult:
    resolved_active = normalize_team(active_team)
    if goal not in VALID_GOALS:
        raise FranchiseTradeFinderAIError(f"Unsupported Trade Finder goal: {goal}.")
    if resolved_active not in getattr(state, "teams", {}):
        raise FranchiseTradeFinderAIError(f"Unknown active franchise team: {resolved_active}.")
    max_results = max(1, min(int(max_results), 12))
    max_partners = max(1, min(int(max_partners), 29))
    max_targets_per_partner = max(1, min(int(max_targets_per_partner), 4))
    # Full live previews are the expensive step. V2 hard-caps them relative to
    # requested result count; cheap cached routing can still inspect hundreds of
    # packages first.
    deep_preview_cap = min(14, max(8, max_results + 4))
    max_package_evaluations = max(4, min(int(max_package_evaluations), deep_preview_cap))
    max_financial_prechecks = max(12, min(int(max_financial_prechecks), 600))
    search_started = time.perf_counter()

    def emit_progress(
        stage: str,
        *,
        partner: str = "",
        partner_index: int = 0,
        partner_total: int = 0,
        packages_evaluated: int = 0,
        financial_prechecks_done: int = 0,
        targets_found: int = 0,
        packages_generated: int = 0,
        financial_passes: int = 0,
        legal_passes: int = 0,
        proposals_found: int = 0,
    ) -> None:
        if progress_callback is None:
            return
        progress_callback(
            {
                "stage": stage,
                "partner": partner,
                "partner_index": int(partner_index),
                "partner_total": int(partner_total),
                "packages_evaluated": int(packages_evaluated),
                "max_package_evaluations": int(max_package_evaluations),
                "financial_prechecks": int(financial_prechecks_done),
                "max_financial_prechecks": int(max_financial_prechecks),
                "targets_found": int(targets_found),
                "packages_generated": int(packages_generated),
                "financial_passes": int(financial_passes),
                "legal_passes": int(legal_passes),
                "proposals_found": int(proposals_found),
            }
        )

    before_state = _state_signature(state)
    before_trade = _trade_state_signature(trade_state)
    context = search_context or build_trade_finder_search_context(
        runtime, state, trade_state, ledger=ledger
    )
    live_ledger = context.ledger
    financial_snapshot = context.financial_snapshot
    contract_snapshot = context.contract_snapshot
    profiles = context.profiles
    shared_contexts = context.shared_contexts
    active_profile = profiles[resolved_active]

    # Per-search copies preserve the old mutation isolation while the expensive
    # league-wide setup above is reused across repeated V6A/V6B searches.
    tradable_players = {
        team: [dict(row) for row in rows]
        for team, rows in context.tradable_players.items()
    }
    tradable_picks = {
        team: [dict(row) for row in rows]
        for team, rows in context.tradable_picks.items()
    }
    player_map = {key: dict(row) for key, row in context.player_map.items()}
    pick_map = {key: dict(row) for key, row in context.pick_map.items()}

    all_partners = [
        team for team in sorted(getattr(state, "teams", {}))
        if normalize_team(team) != resolved_active
    ]
    requested_partner = normalize_team(partner_team)
    if requested_partner:
        if requested_partner == resolved_active or requested_partner not in profiles:
            raise FranchiseTradeFinderAIError(
                f"Invalid Trade Finder partner filter: {requested_partner}."
            )
        partners = [requested_partner]
    else:
        partner_scores = []
        active_market_players = [
            row
            for row in tradable_players.get(resolved_active, [])
            if not _untouchable(row, active_profile)
        ]
        for partner in all_partners:
            cpu_profile = profiles[partner]
            targets = [
                row
                for row in tradable_players.get(partner, [])
                if _morale_trade_finder_target_available_v1(
                    state,
                    partner,
                    row,
                    cpu_profile,
                )
            ]
            if not targets:
                continue

            scores = []
            for row in targets[:16]:
                premium_target = (
                    _shared_asset_tier(row) in {"Franchise", "Star"}
                    or _intrinsic_player_value(row) >= 125.0
                )
                outgoing_choices = (
                    tradable_players.get(resolved_active, [])
                    if premium_target
                    else active_market_players
                )
                route_penalty = min(
                    (
                        _directional_salary_route_penalty(
                            _salary(active_row),
                            _salary(row),
                        )
                        for active_row in outgoing_choices
                    ),
                    default=25.0,
                )
                scores.append(
                    player_value_for_team(row, active_profile, goal=goal)
                    - 0.35 * player_value_for_team(row, cpu_profile)
                    - 1.40 * min(route_penalty, 20.0)
                )

            partner_scores.append((max(scores), partner))
        partner_scores.sort(key=lambda item: (-item[0], item[1]))
        partners = [partner for _, partner in partner_scores[:max_partners]]
        # Keep a broad legal fallback if contract restrictions reduce the player pool.
        for team in all_partners:
            if team not in partners and len(partners) < max_partners:
                partners.append(team)

    active_players = tradable_players.get(resolved_active, [])
    active_picks = tradable_picks.get(resolved_active, []) if include_picks else []
    proposals: list[FranchiseTradeFinderProposal] = []
    near_miss_buffer: list[FranchiseTradeFinderProposal] = []
    package_audit_rows: list[dict[str, Any]] = []
    packages_evaluated = 0
    legal_packages = 0
    targets_identified = 0
    primary_need_targets_identified = 0
    candidate_packages_generated = 0
    value_screen_passes = 0
    guaranteed_exploration_packages = 0
    financial_prechecks = 0
    financial_precheck_passes = 0
    cpu_rejected_legal = 0
    partners_scanned_count = 0
    partners_with_targets_set: set[str] = set()
    partners_with_financial_pass_set: set[str] = set()
    partners_with_legal_pass_set: set[str] = set()
    partner_funnel: dict[str, dict[str, int]] = {}
    rejection_counts: dict[str, int] = {}
    rejection_examples: dict[str, list[str]] = {}
    budget_exhausted = False

    def record_rejection(category: str, reasons: Iterable[str] = ()) -> None:
        key = str(category or "other")
        rejection_counts[key] = rejection_counts.get(key, 0) + 1
        bucket = rejection_examples.setdefault(key, [])
        for reason in reasons:
            text = str(reason or "").strip()
            if text and text not in bucket and len(bucket) < 4:
                bucket.append(text)

    emit_progress(
        "prepared",
        partner_total=len(partners),
        packages_evaluated=0,
        financial_prechecks_done=0,
        targets_found=0,
        packages_generated=0,
        financial_passes=0,
        legal_passes=0,
        proposals_found=0,
    )

    per_partner_financial_budget = max(
        16,
        int(max_financial_prechecks / max(1, len(partners))),
    )

    for partner_index, partner in enumerate(partners, start=1):
        partners_scanned_count += 1
        partner_financial_start = financial_prechecks
        partner_budget_exhausted = False
        partner_funnel.setdefault(
            partner,
            {
                "targets": 0,
                "primary_need_targets": 0,
                "packages": 0,
                "value_routes": 0,
                "financial_prechecks": 0,
                "financial_pass": 0,
                "full_legality": 0,
                "legal_pass": 0,
                "cpu_offers": 0,
            },
        )
        emit_progress(
            "partner",
            partner=partner,
            partner_index=partner_index,
            partner_total=len(partners),
            packages_evaluated=packages_evaluated,
            financial_prechecks_done=financial_prechecks,
            targets_found=targets_identified,
            packages_generated=candidate_packages_generated,
            financial_passes=financial_precheck_passes,
            legal_passes=legal_packages,
            proposals_found=len(proposals),
        )
        partner_profile = profiles[partner]
        targets = [
            row for row in tradable_players.get(partner, [])
            if _morale_trade_finder_target_available_v1(
                state,
                partner,
                row,
                partner_profile,
            )
        ]
        if not targets:
            record_rejection("target_pool_empty", (f"{partner}: no contract-eligible tradable player targets",))
            continue

        def target_rank(row: dict[str, Any]) -> tuple[Any, ...]:
            family = position_family(str(row.get("position", "")))
            need_score = active_profile.need_scores.get(family, 0.0)
            primary_bonus = 8.0 if family == active_profile.biggest_need else 0.0
            morale_market_bonus = morale_trade_finder_search_bonus_v1(
                state,
                partner,
                row,
            )
            score = (
                player_value_for_team(row, active_profile, goal=goal)
                + _fit_score(row, active_profile, goal)
                + primary_bonus
                + morale_market_bonus
                + 0.20 * min(16.0, max(0.0, need_score))
                - 0.20 * player_value_for_team(row, partner_profile)
            )
            return (-score, -_finite(row.get("overall"), 60.0), str(row.get("player_name", "")))

        targets.sort(key=target_rank)
        if goal == GOAL_BIGGEST_NEED:
            primary_targets = [
                row for row in targets
                if position_family(str(row.get("position", ""))) == active_profile.biggest_need
            ]
            secondary_targets = [row for row in targets if row not in primary_targets]
            primary_quota = max(1, min(len(primary_targets), (max_targets_per_partner + 1) // 2))
            selected_targets = primary_targets[:primary_quota]
            selected_targets.extend(
                secondary_targets[: max(0, max_targets_per_partner - len(selected_targets))]
            )
            if len(selected_targets) < max_targets_per_partner:
                selected_targets.extend(
                    primary_targets[primary_quota : primary_quota + (max_targets_per_partner - len(selected_targets))]
                )
        elif goal == GOAL_BEST_AVAILABLE and len(targets) > max_targets_per_partner:
            # Keep elite targets but reserve market slots for financially accessible
            # players. Best Available should not mean "four max-salary stars only."
            selected_targets = targets[: min(2, max_targets_per_partner)]
            remaining = [row for row in targets if row not in selected_targets]
            def accessibility(row: dict[str, Any]) -> tuple[Any, ...]:
                target_salary = _salary(row)
                premium_target = (
                    _shared_asset_tier(row) in {"Franchise", "Star"}
                    or _intrinsic_player_value(row) >= 125.0
                )
                eligible_outgoing = [
                    active_row
                    for active_row in active_players
                    if (
                        not _untouchable(active_row, active_profile)
                        or premium_target
                    )
                ]
                route_penalty = min(
                    (
                        _directional_salary_route_penalty(
                            _salary(active_row),
                            target_salary,
                        )
                        for active_row in eligible_outgoing
                    ),
                    default=10**12,
                )
                return (
                    route_penalty,
                    -player_value_for_team(row, active_profile, goal=goal),
                    str(row.get("player_name", "")),
                )
            for row in sorted(remaining, key=accessibility):
                if len(selected_targets) >= max_targets_per_partner:
                    break
                selected_targets.append(row)
        else:
            selected_targets = targets[:max_targets_per_partner]

        partners_with_targets_set.add(partner)
        targets_identified += len(selected_targets)
        primary_count = sum(
            position_family(str(row.get("position", ""))) == active_profile.biggest_need
            for row in selected_targets
        )
        primary_need_targets_identified += primary_count
        partner_funnel[partner]["targets"] += len(selected_targets)
        partner_funnel[partner]["primary_need_targets"] += int(primary_count)
        partner_picks = tradable_picks.get(partner, []) if include_picks else []
        accepted_for_partner = 0
        per_target_financial_budget = max(
            6,
            int(
                per_partner_financial_budget
                / max(1, len(selected_targets))
            ),
        )
        for target in selected_targets:
            target_financial_start = financial_prechecks
            target_id = normalize_player_id(target.get("player_id"))
            if not target_id:
                continue
            base_accept_floor_v5b = _cpu_accept_floor(
                partner_profile=partner_profile,
                target=target,
            )
            market_terms_v5b = build_morale_trade_finder_terms_v1(
                state,
                partner,
                target,
                base_accept_floor=base_accept_floor_v5b,
            )
            target["_morale_trade_finder_terms_v1"] = (
                market_terms_v5b.to_payload()
            )
            specs = _candidate_specs_for_target(
                active_team=resolved_active,
                partner_team=partner,
                target=target,
                active_players=active_players,
                active_picks=active_picks,
                partner_players=tradable_players.get(partner, []),
                partner_picks=partner_picks,
                active_profile=active_profile,
                partner_profile=partner_profile,
                ledger=live_ledger,
                include_picks=include_picks,
            )
            candidate_packages_generated += len(specs)
            partner_funnel[partner]["packages"] += len(specs)
            if not specs:
                record_rejection(
                    "package_generation",
                    (f"{partner}/{target.get('player_name', target_id)}: no package archetype generated",),
                )
                continue
            guaranteed_routes = min(4, len(specs))

            # Create an audit row for every constructed package BEFORE routing.
            # This makes the CSV reconcile to candidate_packages_generated even when
            # later search budgets or CPU-offer caps stop evaluation early.
            routed_specs: list[
                tuple[
                    int,
                    tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]],
                    tuple[float, float, float, float, float, float],
                    float,
                    bool,
                ]
            ] = []
            for spec_index, spec in enumerate(specs):
                values = _values_for_spec(
                    spec=spec,
                    active_profile=active_profile,
                    partner_profile=partner_profile,
                    player_map=player_map,
                    pick_map=pick_map,
                    ledger=live_ledger,
                    active_goal=goal,
                )
                accept_floor = (
                    market_terms_v5b.adjusted_accept_floor
                )
                guaranteed = spec_index < guaranteed_routes
                audit_id = hashlib.sha1(
                    json.dumps(
                        {
                            "team_a": resolved_active,
                            "team_b": partner,
                            "target": target_id,
                            "spec": spec,
                            "index": spec_index,
                        },
                        sort_keys=True,
                        default=str,
                    ).encode("utf-8")
                ).hexdigest()[:16]
                audit_index = len(package_audit_rows)
                package_audit_rows.append(
                    _new_package_audit_row(
                        audit_id=audit_id,
                        spec=spec,
                        active_team=resolved_active,
                        partner_team=partner,
                        goal=goal,
                        target=target,
                        active_profile=active_profile,
                        partner_profile=partner_profile,
                        player_map=player_map,
                        pick_map=pick_map,
                        ledger=live_ledger,
                        values=values,
                        accept_floor=accept_floor,
                        guaranteed_exploration=guaranteed,
                    )
                )
                routed_specs.append(
                    (audit_index, spec, values, accept_floor, guaranteed)
                )

            for spec_index, (audit_index, spec, values, accept_floor, guaranteed) in enumerate(routed_specs):
                audit_row = package_audit_rows[audit_index]
                user_sent, user_received, user_delta, cpu_sent, cpu_received, cpu_delta = values

                value_screen_pass = not (
                    user_delta < -28.0 or cpu_delta < accept_floor - 22.0
                )
                audit_row["value_screen_pass"] = bool(value_screen_pass)
                if value_screen_pass:
                    value_screen_passes += 1
                    partner_funnel[partner]["value_routes"] += 1
                    audit_row["route_stage"] = "value_screen_pass"
                elif guaranteed:
                    guaranteed_exploration_packages += 1
                    audit_row["route_stage"] = "guaranteed_exploration"
                else:
                    audit_row["route_stage"] = "value_screen_rejected"
                    audit_row["financial_reason_codes"] = "package_value_gap_outside_exploration_window"
                    record_rejection("value_screen", ("package_value_gap_outside_exploration_window",))
                    continue

                a_player_ids, b_player_ids, _, _ = spec
                if financial_prechecks >= max_financial_prechecks:
                    audit_row["route_stage"] = "financial_budget_not_routed"
                    budget_exhausted = True
                    break

                if (
                    financial_prechecks - partner_financial_start
                    >= per_partner_financial_budget
                ):
                    audit_row["route_stage"] = "partner_financial_budget_not_routed"
                    partner_budget_exhausted = True
                    break

                if (
                    financial_prechecks - target_financial_start
                    >= per_target_financial_budget
                ):
                    audit_row["route_stage"] = "target_financial_budget_not_routed"
                    break

                financial_prechecks += 1
                partner_funnel[partner]["financial_prechecks"] += 1
                emit_progress(
                    "financial",
                    partner=partner,
                    partner_index=partner_index,
                    partner_total=len(partners),
                    packages_evaluated=packages_evaluated,
                    financial_prechecks_done=financial_prechecks,
                    targets_found=targets_identified,
                    packages_generated=candidate_packages_generated,
                    financial_passes=financial_precheck_passes,
                    legal_passes=legal_packages,
                    proposals_found=len(proposals),
                )
                financial_status, financial_reasons = _financial_precheck_status(
                    runtime,
                    state,
                    team_a=resolved_active,
                    team_b=partner,
                    side_a_player_ids=a_player_ids,
                    side_b_player_ids=b_player_ids,
                    financial_snapshot=financial_snapshot,
                )
                audit_row["financial_status"] = financial_status
                audit_row["financial_reason_codes"] = "|".join(
                    str(value) for value in financial_reasons if str(value)
                )
                if financial_status not in {"pass", "anchor_review"}:
                    audit_row["route_stage"] = "financial_rejected"
                    record_rejection("financial_precheck", financial_reasons)
                    continue

                if financial_status == "pass":
                    audit_row["route_stage"] = "financial_pass"
                    financial_precheck_passes += 1
                    partners_with_financial_pass_set.add(partner)
                    partner_funnel[partner]["financial_pass"] += 1
                else:
                    audit_row["route_stage"] = "financial_anchor_review_routed"

                # Cheap cached contract/aggregation precheck before any deep preview.
                contract_eval = evaluate_franchise_player_contract_trade(
                    runtime,
                    state,
                    team_a=resolved_active,
                    team_b=partner,
                    side_a_player_ids=spec[0],
                    side_b_player_ids=spec[1],
                    snapshot=contract_snapshot,
                    verify_nonmutation=False,
                )
                if str(contract_eval.status).lower() != "pass":
                    audit_row["route_stage"] = "contract_precheck_rejected"
                    audit_row["legality_reason_codes"] = "|".join(
                        check.code for check in contract_eval.checks
                        if str(check.status).lower() != "pass"
                    )
                    record_rejection("player_contract_precheck", (audit_row["legality_reason_codes"],))
                    continue

                if spec[2] or spec[3]:
                    draft_eval = evaluate_franchise_draft_right_trade(
                        runtime,
                        state,
                        trade_state,
                        team_a=resolved_active,
                        team_b=partner,
                        side_a_asset_ids=spec[2],
                        side_b_asset_ids=spec[3],
                        ledger=live_ledger,
                    )
                    if str(draft_eval.status).lower() != "pass":
                        audit_row["route_stage"] = "draft_precheck_rejected"
                        audit_row["legality_reason_codes"] = "|".join(
                            check.code for check in draft_eval.checks
                            if str(check.status).lower() != "pass"
                        )
                        record_rejection("draft_right_stepien_precheck", (audit_row["legality_reason_codes"],))
                        continue

                # Value Intelligence V2 decides whether a package is worth paying
                # for a deep transactional preview. This is a routing decision, not
                # a legality shortcut: every surfaced offer still receives the full
                # preview below.
                user_guard_floor = -8.0
                cpu_close_enough = cpu_delta >= accept_floor - 8.0
                user_close_enough = user_delta >= -16.0

                if (
                    not cpu_close_enough
                    and user_close_enough
                    and packages_evaluated < max_package_evaluations
                ):
                    rescue, rescue_attempts = _find_counter(
                        runtime,
                        state,
                        trade_state,
                        live_ledger,
                        active_team=resolved_active,
                        partner_team=partner,
                        base_spec=spec,
                        active_players=active_players,
                        active_picks=active_picks,
                        active_profile=active_profile,
                        partner_profile=partner_profile,
                        player_map=player_map,
                        pick_map=pick_map,
                        goal=goal,
                        target=target,
                        include_picks=include_picks,
                        accept_floor=accept_floor,
                        financial_snapshot=financial_snapshot,
                        contract_snapshot=contract_snapshot,
                        max_attempts=max(
                            1,
                            min(
                                3,
                                max_package_evaluations - packages_evaluated,
                            ),
                        ),
                    )
                    packages_evaluated += int(rescue_attempts)
                    partner_funnel[partner]["full_legality"] += int(rescue_attempts)

                    if rescue is not None:
                        rescue_spec, rescue_payload, rescue_sweetener = rescue
                        rescue_values = _values_for_spec(
                            spec=rescue_spec,
                            active_profile=active_profile,
                            partner_profile=partner_profile,
                            player_map=player_map,
                            pick_map=pick_map,
                            ledger=live_ledger,
                            active_goal=goal,
                        )
                        rescue_audit = _new_package_audit_row(
                            audit_id=f"{audit_row['audit_id']}-financial-rescue",
                            spec=rescue_spec,
                            active_team=resolved_active,
                            partner_team=partner,
                            goal=goal,
                            target=target,
                            active_profile=active_profile,
                            partner_profile=partner_profile,
                            player_map=player_map,
                            pick_map=pick_map,
                            ledger=live_ledger,
                            values=rescue_values,
                            accept_floor=accept_floor,
                            guaranteed_exploration=False,
                        )
                        rescue_audit.update(
                            {
                                "route_stage": "financial_pass_value_rescue",
                                "final_cpu_response": "counter",
                                "value_screen_pass": True,
                                "financial_status": "pass",
                                "full_legality_status": str(
                                    rescue_payload.get("status", "pass")
                                ),
                                "can_commit": bool(
                                    rescue_payload.get("can_commit", True)
                                ),
                                "counter_sweetener": rescue_sweetener,
                            }
                        )
                        package_audit_rows.append(rescue_audit)
                        proposals.append(
                            _make_proposal(
                                spec=rescue_spec,
                                active_team=resolved_active,
                                partner_team=partner,
                                goal=goal,
                                response="counter",
                                preview_payload=rescue_payload,
                                active_profile=active_profile,
                                partner_profile=partner_profile,
                                player_map=player_map,
                                pick_map=pick_map,
                                ledger=live_ledger,
                                target=target,
                                counter_sweetener=rescue_sweetener,
                            )
                        )
                        legal_packages += 1
                        partners_with_legal_pass_set.add(partner)
                        partner_funnel[partner]["legal_pass"] += 1
                        accepted_for_partner += 1
                        partner_funnel[partner]["cpu_offers"] += 1
                        audit_row["route_stage"] = "financial_pass_rescued_by_counter"
                        audit_row["counter_sweetener"] = rescue_sweetener
                        continue

                if not cpu_close_enough or not user_close_enough:
                    audit_row["route_stage"] = (
                        "cpu_value_precheck_rejected"
                        if not cpu_close_enough
                        else "user_value_precheck_rejected"
                    )
                    record_rejection(audit_row["route_stage"], ())
                    continue

                canonical_status, canonical_reasons = _canonical_anchor_precheck(
                    runtime,
                    state,
                    live_ledger,
                    team_a=resolved_active,
                    team_b=partner,
                    spec=spec,
                )
                audit_row["canonical_precheck_status"] = canonical_status
                audit_row["canonical_precheck_reason_codes"] = "|".join(
                    canonical_reasons
                )

                if canonical_status == "blocked":
                    audit_row["route_stage"] = "canonical_precheck_rejected"
                    record_rejection(
                        "canonical_precheck",
                        canonical_reasons,
                    )
                    continue

                if (
                    financial_status == "anchor_review"
                    and canonical_status != "pass"
                ):
                    audit_row["route_stage"] = (
                        "anchor_review_canonical_unresolved"
                    )
                    record_rejection(
                        "anchor_review_canonical_unresolved",
                        canonical_reasons,
                    )
                    continue

                # Keep any single partner from consuming the entire expensive
                # preview budget before the broader market gets a chance.
                if partner_funnel[partner]["full_legality"] >= 2:
                    audit_row["route_stage"] = "deep_preview_partner_cap"
                    continue

                if packages_evaluated >= max_package_evaluations:
                    audit_row["route_stage"] = "legality_budget_not_routed"
                    budget_exhausted = True
                    break

                packages_evaluated += 1
                partner_funnel[partner]["full_legality"] += 1
                emit_progress(
                    "legality",
                    partner=partner,
                    partner_index=partner_index,
                    partner_total=len(partners),
                    packages_evaluated=packages_evaluated,
                    financial_prechecks_done=financial_prechecks,
                    targets_found=targets_identified,
                    packages_generated=candidate_packages_generated,
                    financial_passes=financial_precheck_passes,
                    legal_passes=legal_packages,
                    proposals_found=len(proposals),
                )
                preview = build_franchise_trade_preview(
                    runtime,
                    state,
                    trade_state,
                    team_a=resolved_active,
                    team_b=partner,
                    side_a_player_ids=spec[0],
                    side_b_player_ids=spec[1],
                    side_a_pick_asset_ids=spec[2],
                    side_b_pick_asset_ids=spec[3],
                    ledger=live_ledger,
                    financial_snapshot=financial_snapshot,
                    player_contract_snapshot=contract_snapshot,
                    market_read_only_fast_path=True,
                )
                audit_row["full_legality_status"] = str(preview.status or "")
                audit_row["can_commit"] = bool(preview.can_commit)
                audit_row["anchor_financial_resolution_applied"] = bool(
                    getattr(
                        preview,
                        "anchor_financial_resolution_applied",
                        False,
                    )
                )
                audit_row["legality_reason_codes"] = _audit_legality_codes(preview)
                if preview.status != "pass" or not preview.can_commit:
                    audit_row["route_stage"] = "legality_rejected"
                    for category in _preview_rejection_categories(preview):
                        reason_codes = tuple(
                            str(getattr(check, "code", "") or "")
                            for check in getattr(preview, "checks", ()) or ()
                            if str(getattr(check, "status", "") or "").lower() != "pass"
                        )
                        record_rejection(category, reason_codes)
                    continue
                audit_row["route_stage"] = "legal_pass"
                legal_packages += 1
                partners_with_legal_pass_set.add(partner)
                partner_funnel[partner]["legal_pass"] += 1
                payload = preview_to_dict(preview)

                if cpu_delta >= accept_floor and user_delta >= user_guard_floor:
                    audit_row["route_stage"] = "cpu_accept"
                    audit_row["final_cpu_response"] = "accept"
                    proposals.append(
                        _make_proposal(
                            spec=spec,
                            active_team=resolved_active,
                            partner_team=partner,
                            goal=goal,
                            response="accept",
                            preview_payload=payload,
                            active_profile=active_profile,
                            partner_profile=partner_profile,
                            player_map=player_map,
                            pick_map=pick_map,
                            ledger=live_ledger,
                            target=target,
                        )
                    )
                    accepted_for_partner += 1
                    partner_funnel[partner]["cpu_offers"] += 1
                elif cpu_delta >= accept_floor and user_delta < user_guard_floor:
                    audit_row["route_stage"] = "user_overpay_guard"
                    audit_row["final_cpu_response"] = "overpay"
                    near_miss_buffer.append(
                        _make_proposal(
                            spec=spec,
                            active_team=resolved_active,
                            partner_team=partner,
                            goal=goal,
                            response="overpay",
                            preview_payload=payload,
                            active_profile=active_profile,
                            partner_profile=partner_profile,
                            player_map=player_map,
                            pick_map=pick_map,
                            ledger=live_ledger,
                            target=target,
                        )
                    )
                    record_rejection("user_value_guard", ("legal_cpu_accept_but_user_overpay",))
                elif cpu_delta >= accept_floor - 6.0 and user_delta >= -10.0:
                    if packages_evaluated >= max_package_evaluations:
                        counter = None
                        counter_preview_attempts = 0
                    else:
                        counter, counter_preview_attempts = _find_counter(
                            runtime,
                            state,
                            trade_state,
                            live_ledger,
                            active_team=resolved_active,
                            partner_team=partner,
                            base_spec=spec,
                            active_players=active_players,
                            active_picks=active_picks,
                            active_profile=active_profile,
                            partner_profile=partner_profile,
                            player_map=player_map,
                            pick_map=pick_map,
                            goal=goal,
                            target=target,
                            include_picks=include_picks,
                            accept_floor=accept_floor,
                            financial_snapshot=financial_snapshot,
                            contract_snapshot=contract_snapshot,
                            max_attempts=max(
                                1,
                                max_package_evaluations - packages_evaluated,
                            ),
                        )
                    packages_evaluated += int(counter_preview_attempts)
                    partner_funnel[partner]["full_legality"] += int(counter_preview_attempts)
                    if counter is not None:
                        counter_spec, counter_payload, sweetener = counter
                        audit_row["route_stage"] = "cpu_counter_trigger"
                        audit_row["final_cpu_response"] = "counter"
                        audit_row["counter_sweetener"] = sweetener

                        counter_values = _values_for_spec(
                            spec=counter_spec,
                            active_profile=active_profile,
                            partner_profile=partner_profile,
                            player_map=player_map,
                            pick_map=pick_map,
                            ledger=live_ledger,
                            active_goal=goal,
                        )
                        counter_audit = _new_package_audit_row(
                            audit_id=f"{audit_row['audit_id']}-counter",
                            spec=counter_spec,
                            active_team=resolved_active,
                            partner_team=partner,
                            goal=goal,
                            target=target,
                            active_profile=active_profile,
                            partner_profile=partner_profile,
                            player_map=player_map,
                            pick_map=pick_map,
                            ledger=live_ledger,
                            values=counter_values,
                            accept_floor=accept_floor,
                            guaranteed_exploration=False,
                        )
                        counter_audit.update(
                            {
                                "route_stage": "cpu_counter",
                                "final_cpu_response": "counter",
                                "value_screen_pass": True,
                                "financial_status": "pass",
                                "full_legality_status": str(counter_payload.get("status", "pass")),
                                "can_commit": bool(counter_payload.get("can_commit", True)),
                                "counter_sweetener": sweetener,
                            }
                        )
                        package_audit_rows.append(counter_audit)

                        proposals.append(
                            _make_proposal(
                                spec=counter_spec,
                                active_team=resolved_active,
                                partner_team=partner,
                                goal=goal,
                                response="counter",
                                preview_payload=counter_payload,
                                active_profile=active_profile,
                                partner_profile=partner_profile,
                                player_map=player_map,
                                pick_map=pick_map,
                                ledger=live_ledger,
                                target=target,
                                counter_sweetener=sweetener,
                            )
                        )
                        accepted_for_partner += 1
                        partner_funnel[partner]["cpu_offers"] += 1
                    else:
                        audit_row["route_stage"] = "cpu_decline"
                        audit_row["final_cpu_response"] = "decline"
                        cpu_rejected_legal += 1
                        near_miss_buffer.append(
                            _make_proposal(
                                spec=spec,
                                active_team=resolved_active,
                                partner_team=partner,
                                goal=goal,
                                response="reject",
                                preview_payload=payload,
                                active_profile=active_profile,
                                partner_profile=partner_profile,
                                player_map=player_map,
                                pick_map=pick_map,
                                ledger=live_ledger,
                                target=target,
                            )
                        )
                        record_rejection("cpu_value", ("legal_package_counter_not_acceptable",))
                else:
                    audit_row["route_stage"] = "cpu_decline"
                    audit_row["final_cpu_response"] = "decline"
                    cpu_rejected_legal += 1
                    near_miss_buffer.append(
                        _make_proposal(
                            spec=spec,
                            active_team=resolved_active,
                            partner_team=partner,
                            goal=goal,
                            response="reject",
                            preview_payload=payload,
                            active_profile=active_profile,
                            partner_profile=partner_profile,
                            player_map=player_map,
                            pick_map=pick_map,
                            ledger=live_ledger,
                            target=target,
                        )
                    )
                    record_rejection("cpu_value", ("legal_package_rejected_by_cpu_value",))

                # Bound each partner so one roster cannot dominate the result set.
                if accepted_for_partner >= 2:
                    break
            if (
                budget_exhausted
                or partner_budget_exhausted
                or accepted_for_partner >= 2
            ):
                break

        if budget_exhausted or len(proposals) >= max_results * 2:
            break

    # V1.1 deliberately does not fill an empty basketball search with neutral
    # same-round pick swaps. "No realistic player-centered deal found" is more
    # useful than a technically legal but meaningless result.
    fallback_used = False

    # Dedupe exact packages, keeping the best-ranked version.
    best_by_package: dict[tuple[Any, ...], FranchiseTradeFinderProposal] = {}
    for proposal in proposals:
        key = (
            proposal.partner_team,
            proposal.side_a_player_ids,
            proposal.side_b_player_ids,
            proposal.side_a_pick_asset_ids,
            proposal.side_b_pick_asset_ids,
        )
        incumbent = best_by_package.get(key)
        if incumbent is None or proposal.ranking_score > incumbent.ranking_score:
            best_by_package[key] = proposal
    family_best: dict[tuple[Any, ...], FranchiseTradeFinderProposal] = {}
    for proposal in best_by_package.values():
        family_key = (
            proposal.partner_team,
            proposal.target_player_id or proposal.side_b_player_ids[:1],
        )
        incumbent = family_best.get(family_key)
        if incumbent is None or (
            (proposal.cpu_response == "accept", proposal.ranking_score, proposal.user_value_delta)
            > (incumbent.cpu_response == "accept", incumbent.ranking_score, incumbent.user_value_delta)
        ):
            family_best[family_key] = proposal
    ordered = sorted(
        family_best.values(),
        key=lambda item: (
            0 if item.cpu_response == "accept" else 1,
            -item.ranking_score,
            -item.user_value_delta,
            item.partner_team,
            item.proposal_id,
        ),
    )[:max_results]

    near_best: dict[tuple[Any, ...], FranchiseTradeFinderProposal] = {}
    for proposal in near_miss_buffer:
        key = (
            proposal.partner_team,
            proposal.side_a_player_ids,
            proposal.side_b_player_ids,
            proposal.side_a_pick_asset_ids,
            proposal.side_b_pick_asset_ids,
        )
        incumbent = near_best.get(key)
        if incumbent is None or proposal.cpu_value_delta > incumbent.cpu_value_delta:
            near_best[key] = proposal
    near_family: dict[tuple[Any, ...], FranchiseTradeFinderProposal] = {}
    for proposal in near_best.values():
        key = (proposal.partner_team, proposal.target_player_id or proposal.side_b_player_ids[:1])
        incumbent = near_family.get(key)
        if incumbent is None or abs(proposal.cpu_value_delta) < abs(incumbent.cpu_value_delta):
            near_family[key] = proposal
    near_misses = sorted(
        near_family.values(),
        key=lambda item: (
            0 if item.cpu_response == "overpay" else 1,
            abs(item.cpu_value_delta),
            -item.fit_score,
            -item.user_value_delta,
            item.partner_team,
        ),
    )[:3]

    if _state_signature(state) != before_state:
        raise FranchiseTradeFinderAIError(
            "Trade Finder generation mutated the live SimulationLeagueState."
        )
    if _trade_state_signature(trade_state) != before_trade:
        raise FranchiseTradeFinderAIError(
            "Trade Finder generation mutated the separate Trade Machine state."
        )

    emit_progress(
        "complete",
        partner_total=len(partners),
        packages_evaluated=packages_evaluated,
        financial_prechecks_done=financial_prechecks,
        targets_found=targets_identified,
        packages_generated=candidate_packages_generated,
        financial_passes=financial_precheck_passes,
        legal_passes=legal_packages,
        proposals_found=len(ordered),
    )

    return FranchiseTradeFinderResult(
        version=TRADE_FINDER_AI_VERSION,
        value_model_version=TRADE_FINDER_VALUE_MODEL_VERSION,
        season_label=_clean(getattr(getattr(state, "settings", None), "season_label", "")),
        franchise_trade_revision=int(
            getattr(state, "franchise_trade_revision_v1", 0) or 0
        ),
        active_team=resolved_active,
        goal=goal,
        partner_filter=requested_partner,
        teams_scanned=partners_scanned_count,
        packages_evaluated=packages_evaluated,
        legal_packages=legal_packages,
        cpu_accepts_found=sum(p.cpu_response == "accept" for p in ordered),
        cpu_counters_found=sum(p.cpu_response == "counter" for p in ordered),
        fallback_used=fallback_used,
        targets_identified=targets_identified,
        primary_need_targets_identified=primary_need_targets_identified,
        candidate_packages_generated=candidate_packages_generated,
        value_screen_passes=value_screen_passes,
        guaranteed_exploration_packages=guaranteed_exploration_packages,
        financial_prechecks=financial_prechecks,
        financial_precheck_passes=financial_precheck_passes,
        partners_with_targets=len(partners_with_targets_set),
        partners_with_financial_pass=len(partners_with_financial_pass_set),
        partners_with_legal_pass=len(partners_with_legal_pass_set),
        cpu_rejected_legal=cpu_rejected_legal,
        partner_funnel={
            key: dict(value)
            for key, value in sorted(partner_funnel.items())
        },
        rejection_counts=dict(sorted(rejection_counts.items())),
        rejection_examples={
            key: tuple(values)
            for key, values in sorted(rejection_examples.items())
        },
        proposals=tuple(ordered),
        near_misses=tuple(near_misses),
        package_audit_rows=tuple(copy.deepcopy(package_audit_rows)),
        search_elapsed_seconds=round(time.perf_counter() - search_started, 3),
    )
