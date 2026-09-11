from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from statistics import median
from typing import Any, Iterable, Mapping
from franchise_asset_market_value_v1 import (
    ASSET_MARKET_CONTEXT_VERSION,
    ASSET_MARKET_MODEL_VERSION,
    AssetMarketContext,
    build_asset_market_context,
    build_league_asset_market_contexts,
)



CPU_FRONT_OFFICE_VERSION = "franchise-cpu-front-office-v1.6.2-2026-08-13"
CPU_FRONT_OFFICE_MODEL_VERSION = "shared-market-context-asset-tier-calibration-v1.6.2-2026-08-13"

TIMELINE_CHAMPIONSHIP_PUSH = "championship_push"
TIMELINE_CONTENDER = "contender"
TIMELINE_RETOOL = "retool"
TIMELINE_DEVELOP = "develop"
TIMELINE_REBUILD = "rebuild"

TIMELINE_LABELS = {
    TIMELINE_CHAMPIONSHIP_PUSH: "Championship Push",
    TIMELINE_CONTENDER: "Contend",
    TIMELINE_RETOOL: "Retool",
    TIMELINE_DEVELOP: "Develop",
    TIMELINE_REBUILD: "Rebuild",
}


@dataclass(frozen=True)
class FrontOfficeBehaviorProfile:
    timeline: str
    label: str
    win_now_bias: float
    youth_bias: float
    future_asset_bias: float
    consolidation_bias: float
    salary_discipline: float
    continuity_bias: float
    veteran_liquidity: float
    preferred_fa_age_ceiling: float
    summary: str


BEHAVIOR_PROFILES = {
    TIMELINE_CHAMPIONSHIP_PUSH: FrontOfficeBehaviorProfile(
        timeline=TIMELINE_CHAMPIONSHIP_PUSH,
        label="All-in contender",
        win_now_bias=95.0,
        youth_bias=38.0,
        future_asset_bias=20.0,
        consolidation_bias=92.0,
        salary_discipline=48.0,
        continuity_bias=90.0,
        veteran_liquidity=25.0,
        preferred_fa_age_ceiling=34.0,
        summary=(
            "Protect the championship core, keep proven playoff impact, "
            "and consolidate secondary assets only for clear upgrades."
        ),
    ),
    TIMELINE_CONTENDER: FrontOfficeBehaviorProfile(
        timeline=TIMELINE_CONTENDER,
        label="Balanced contender",
        win_now_bias=82.0,
        youth_bias=50.0,
        future_asset_bias=35.0,
        consolidation_bias=72.0,
        salary_discipline=62.0,
        continuity_bias=82.0,
        veteran_liquidity=38.0,
        preferred_fa_age_ceiling=32.0,
        summary=(
            "Protect top-end continuity while pursuing targeted upgrades "
            "without emptying the future asset base."
        ),
    ),
    TIMELINE_RETOOL: FrontOfficeBehaviorProfile(
        timeline=TIMELINE_RETOOL,
        label="Flexible retool",
        win_now_bias=56.0,
        youth_bias=68.0,
        future_asset_bias=60.0,
        consolidation_bias=58.0,
        salary_discipline=76.0,
        continuity_bias=66.0,
        veteran_liquidity=65.0,
        preferred_fa_age_ceiling=30.0,
        summary=(
            "Preserve the best long-term pieces, listen on older secondary "
            "veterans, and reshape the roster toward younger two-way fits."
        ),
    ),
    TIMELINE_DEVELOP: FrontOfficeBehaviorProfile(
        timeline=TIMELINE_DEVELOP,
        label="Development first",
        win_now_bias=28.0,
        youth_bias=94.0,
        future_asset_bias=86.0,
        consolidation_bias=24.0,
        salary_discipline=84.0,
        continuity_bias=72.0,
        veteran_liquidity=82.0,
        preferred_fa_age_ceiling=27.0,
        summary=(
            "Protect young rotation players, preserve minutes and picks, "
            "and move veterans only when the return improves the development runway."
        ),
    ),
    TIMELINE_REBUILD: FrontOfficeBehaviorProfile(
        timeline=TIMELINE_REBUILD,
        label="Asset accumulation",
        win_now_bias=12.0,
        youth_bias=90.0,
        future_asset_bias=100.0,
        consolidation_bias=16.0,
        salary_discipline=94.0,
        continuity_bias=48.0,
        veteran_liquidity=100.0,
        preferred_fa_age_ceiling=26.0,
        summary=(
            "Protect true young cornerstones, aggressively monetize veteran value, "
            "avoid long commitments, and accumulate picks, youth and flexibility."
        ),
    ),
}


def behavior_profile(timeline: str) -> FrontOfficeBehaviorProfile:
    return BEHAVIOR_PROFILES.get(
        timeline,
        BEHAVIOR_PROFILES[TIMELINE_RETOOL],
    )


@dataclass(frozen=True)
class FrontOfficePlayerDecision:
    player_id: str
    player_name: str
    position: str
    age: float
    overall: float
    potential: float
    salary: float
    years_remaining: int | None
    role: str
    strategic_value: float
    retention_score: float
    contract_plan: str
    market_stance: str
    asset_policy: str
    decision_priority: float
    position_family: str
    family_depth_rank: int
    roster_fit: str
    asset_tier: str
    premium_market: bool
    minimum_return_label: str
    market_value_score: float
    organizational_value_score: float
    trade_value_score: float
    market_percentile: float
    age_curve_score: float
    contract_control_score: float
    salary_efficiency_score: float
    availability_score: float
    market_context_confidence: float
    rationale: tuple[str, ...]


@dataclass(frozen=True)
class FrontOfficeFreeAgentTarget:
    player_id: str
    player_name: str
    position: str
    age: float
    overall: float
    potential: float
    salary_reference: float
    fit_score: float
    target_tier: str
    target_lane: str
    position_family: str
    rationale: tuple[str, ...]


@dataclass(frozen=True)
class FrontOfficeTradePackageIntent:
    intent_id: str
    intent_type: str
    priority: float
    outgoing_player_ids: tuple[str, ...]
    outgoing_player_names: tuple[str, ...]
    outgoing_positions: tuple[str, ...]
    outgoing_value: float
    outgoing_salary: float
    target_family: str
    return_profile: str
    draft_first_budget: int
    draft_second_budget: int
    allow_pick_swap: bool
    outgoing_peak_asset_tier: str
    required_first_equivalent_return: int
    requires_blue_chip_return: bool
    minimum_return_label: str
    execution_ready: bool
    rationale: tuple[str, ...]


@dataclass(frozen=True)
class TeamFrontOfficePlan:
    version: str
    model_version: str
    season_label: str
    team: str
    cpu_managed: bool
    timeline: str
    timeline_label: str
    league_rank: int
    league_percentile: float
    competitive_score: float
    direction_rationale: tuple[str, ...]
    win_pct: float
    strength_score: float
    average_age: float
    top_five_overall: float
    top_three_overall: float
    rotation_quality: float
    young_core_score: float
    roster_count: int
    known_payroll: float
    salary_coverage: float
    financial_posture: str
    behavior_label: str
    behavior_summary: str
    win_now_bias: float
    youth_bias: float
    future_asset_bias: float
    consolidation_bias: float
    salary_discipline: float
    veteran_liquidity: float
    free_agent_strategy: str
    biggest_need: str
    secondary_need: str
    surplus_family: str
    primary_upgrade_need: str
    secondary_upgrade_need: str
    depth_surplus_family: str
    roster_balance_score: float
    need_scores: dict[str, float]
    surplus_scores: dict[str, float]
    position_profiles: dict[str, dict[str, float | int]]
    draft_posture: str
    trade_goal: str
    objectives: tuple[str, ...]
    protected_player_ids: tuple[str, ...]
    shop_player_ids: tuple[str, ...]
    retention_priority_ids: tuple[str, ...]
    development_player_ids: tuple[str, ...]
    cut_candidate_ids: tuple[str, ...]
    tradeable_player_pool_ids: tuple[str, ...]
    consolidation_candidate_ids: tuple[str, ...]
    draft_first_budget: int
    draft_second_budget: int
    allow_pick_swap: bool
    desired_return_profile: str
    trade_package_intents: tuple[FrontOfficeTradePackageIntent, ...]
    player_decisions: tuple[FrontOfficePlayerDecision, ...]
    free_agent_targets: tuple[FrontOfficeFreeAgentTarget, ...]
    risk_flags: tuple[str, ...]


@dataclass(frozen=True)
class LeagueFrontOfficePlan:
    version: str
    model_version: str
    season_label: str
    state_fingerprint: str
    teams: dict[str, TeamFrontOfficePlan]
    timeline_counts: dict[str, int]
    cpu_team_count: int
    user_team_count: int
    roster_pressure_teams: tuple[str, ...]
    contract_decision_count: int
    shop_candidate_count: int
    trade_intent_count: int
    teams_with_trade_intents: tuple[str, ...]


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _age(player: Any) -> float:
    value = getattr(player, "age", None)
    return _finite(value, 27.0) if value is not None else 27.0


def _overall(player: Any) -> float:
    return _finite(getattr(player, "overall_rating", 60.0), 60.0)


def _potential(player: Any) -> float:
    overall = _overall(player)
    value = getattr(player, "potential_rating", None)
    return _finite(value, overall) if value is not None else overall


def _future(player: Any) -> float:
    potential = _potential(player)
    value = getattr(player, "future_outlook_rating", None)
    return _finite(value, potential) if value is not None else potential


def _salary(player: Any) -> float:
    contract = getattr(player, "contract", None)
    return max(0.0, _finite(getattr(contract, "salary", 0.0), 0.0))


def _years(player: Any) -> int | None:
    contract = getattr(player, "contract", None)
    value = getattr(contract, "years_remaining", None)
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _contract_status(player: Any) -> str:
    contract = getattr(player, "contract", None)
    return _clean(getattr(contract, "status", "")).lower()


def _career_status(player: Any) -> str:
    for name in (
        "career_status",
        "career_intent",
        "retirement_status",
    ):
        value = _clean(getattr(player, name, "")).lower()
        if value:
            return value
    return "active"


def position_family(position: str) -> str:
    tokens = {
        token.strip().upper()
        for token in str(position or "").replace("-", "/").split("/")
        if token.strip()
    }
    if tokens.intersection({"PG", "SG", "G"}):
        return "Guard"
    if "C" in tokens:
        return "Center"
    return "Wing/Forward"


def _player_role(player: Any) -> str:
    overall = _overall(player)
    potential = _potential(player)
    age = _age(player)
    if overall >= 90.0 and age <= 31.0:
        return "Cornerstone"
    if overall >= 84.0:
        return "Core"
    if overall >= 79.0:
        return "Starter"
    if age <= 24.5 and potential >= max(80.0, overall + 4.0):
        return "Development"
    if overall >= 73.5:
        return "Rotation"
    if age <= 23.5 and potential >= overall + 5.0:
        return "Development"
    return "Fringe"


def intrinsic_player_value(player: Any) -> float:
    overall = _overall(player)
    potential = _potential(player)
    future = _future(player)
    age = _age(player)
    salary = _salary(player)
    years = _years(player) or 0
    role = _player_role(player)

    above_replacement = max(0.0, overall - 68.0)
    value = 1.35 * (above_replacement ** 1.34)

    upside = max(0.0, potential - overall)
    if age <= 26.0:
        value += (27.0 - age) * 1.55 + upside * 0.85
    elif age <= 29.0:
        value += upside * 0.45
    elif age > 30.0:
        value -= (age - 30.0) * 1.85

    value += {
        "Cornerstone": 16.0,
        "Core": 6.0,
        "Starter": 2.0,
        "Rotation": 0.0,
        "Development": 2.5,
        "Fringe": -1.5,
    }.get(role, 0.0)

    if salary > 0.0:
        if overall >= 88.0:
            expected = 42_000_000.0 if overall >= 92.0 else 34_000_000.0
            value += max(-4.0, min(5.0, (expected - salary) / 7_000_000.0))
        elif overall >= 80.0:
            value += max(-3.0, min(3.0, (19_000_000.0 - salary) / 8_000_000.0))
        else:
            value += max(-4.0, min(1.5, (8_000_000.0 - salary) / 8_000_000.0))

    if years > 0:
        value += min(years, 4) * (1.25 if age <= 28.0 and overall >= 82.0 else 0.35)

    value += max(-3.0, min(4.0, (future - overall) * 0.28))

    career = _career_status(player)
    if "farewell" in career:
        value *= 0.20
    elif "retir" in career or "consider" in career:
        value *= 0.55

    return round(max(0.0, min(175.0, value)), 2)


def _team_roster_players(state: Any, team: str) -> list[Any]:
    resolved = _team(team)
    team_state = getattr(state, "teams", {}).get(resolved)
    if team_state is None:
        return []
    players = getattr(state, "players", {})
    return [
        players[player_id]
        for player_id in tuple(getattr(team_state, "roster_player_ids", ()) or ())
        if player_id in players
    ]


def team_roster_construction(
    state: Any,
    team: str,
) -> dict[str, Any]:
    families = ("Guard", "Wing/Forward", "Center")
    target_counts = {
        "Guard": 4,
        "Wing/Forward": 5,
        "Center": 2,
    }
    groups: dict[str, list[Any]] = {
        family: []
        for family in families
    }

    for player in _team_roster_players(state, team):
        groups[
            position_family(getattr(player, "position", ""))
        ].append(player)

    profiles: dict[str, dict[str, float | int]] = {}
    need_scores: dict[str, float] = {}
    starter_need_scores: dict[str, float] = {}
    depth_need_scores: dict[str, float] = {}
    surplus_scores: dict[str, float] = {}

    for family in families:
        players = sorted(
            groups[family],
            key=_overall,
            reverse=True,
        )
        ratings = [_overall(player) for player in players]
        count = len(players)
        top = ratings[0] if ratings else 0.0
        second = ratings[1] if len(ratings) > 1 else 0.0
        third = ratings[2] if len(ratings) > 2 else 0.0
        top_two_average = (
            sum(ratings[:2]) / len(ratings[:2])
            if ratings[:2]
            else 0.0
        )
        rotation_count = sum(rating >= 76.0 for rating in ratings)
        starter_count = sum(rating >= 79.0 for rating in ratings)
        young_upside_count = sum(
            _age(player) <= 25.5
            and _potential(player) >= max(
                80.0,
                _overall(player) + 4.0,
            )
            for player in players
        )

        quantity_gap = max(0, target_counts[family] - count)
        rotation_gap = max(
            0,
            min(target_counts[family], 2) - rotation_count,
        )

        # Starter-quality need is intentionally independent of raw player count.
        # A team can carry several centers and still need a better starting center.
        starter_quality_gap = max(0.0, 84.0 - top)
        second_quality_gap = max(0.0, 79.0 - second)
        starter_need = (
            starter_quality_gap * 1.05
            + second_quality_gap * 0.30
        )
        if top == 0.0:
            starter_need += 10.0

        depth_need = (
            quantity_gap * 4.0
            + rotation_gap * 4.5
            + max(0.0, 76.0 - second) * 0.30
        )
        if count == 0:
            depth_need += 8.0

        need = starter_need + depth_need * 0.70

        excess_count = max(
            0,
            count - target_counts[family],
        )
        depth_surplus = (
            excess_count * 4.0
            + max(0.0, second - 80.0) * 0.45
            + max(0.0, third - 77.0) * 0.35
        )
        if count <= target_counts[family]:
            depth_surplus *= 0.35

        profiles[family] = {
            "count": count,
            "target_count": target_counts[family],
            "top_overall": round(top, 2),
            "second_overall": round(second, 2),
            "top_two_average": round(top_two_average, 2),
            "rotation_count": rotation_count,
            "starter_count": starter_count,
            "young_upside_count": young_upside_count,
            "starter_need_score": round(starter_need, 2),
            "depth_need_score": round(depth_need, 2),
            "need_score": round(need, 2),
            "surplus_score": round(depth_surplus, 2),
        }
        starter_need_scores[family] = round(starter_need, 2)
        depth_need_scores[family] = round(depth_need, 2)
        need_scores[family] = round(need, 2)
        surplus_scores[family] = round(depth_surplus, 2)

    upgrade_order = tuple(
        sorted(
            families,
            key=lambda family: (
                -starter_need_scores[family],
                -need_scores[family],
                family,
            ),
        )
    )
    need_order = tuple(
        sorted(
            families,
            key=lambda family: (
                -need_scores[family],
                surplus_scores[family],
                family,
            ),
        )
    )
    surplus_order = tuple(
        sorted(
            families,
            key=lambda family: (
                -surplus_scores[family],
                need_scores[family],
                family,
            ),
        )
    )

    total_need = sum(need_scores.values())
    total_surplus = sum(surplus_scores.values())
    balance = max(
        0.0,
        min(
            100.0,
            100.0 - total_need * 1.05 - total_surplus * 0.40,
        ),
    )

    return {
        "profiles": profiles,
        "need_scores": need_scores,
        "starter_need_scores": starter_need_scores,
        "depth_need_scores": depth_need_scores,
        "surplus_scores": surplus_scores,
        "need_order": need_order,
        "upgrade_order": upgrade_order,
        "surplus_order": surplus_order,
        "biggest_need": need_order[0],
        "secondary_need": need_order[1],
        "primary_upgrade_need": upgrade_order[0],
        "secondary_upgrade_need": upgrade_order[1],
        "surplus_family": surplus_order[0],
        "depth_surplus_family": surplus_order[0],
        "roster_balance_score": round(balance, 1),
    }


def team_need_scores(state: Any, team: str) -> dict[str, float]:
    return dict(
        team_roster_construction(
            state,
            team,
        )["need_scores"]
    )


def _standing_win_pct(
    state: Any,
    team: str,
    top_five: float,
) -> tuple[float, int, float]:
    standing = getattr(state, "standings", {}).get(_team(team))
    games = int(getattr(standing, "games_played", 0) or 0)
    wins = int(getattr(standing, "wins", 0) or 0)
    points_for = _finite(getattr(standing, "points_for", 0.0), 0.0)
    points_against = _finite(
        getattr(standing, "points_against", 0.0),
        0.0,
    )
    if games > 0:
        win_pct = max(0.0, min(1.0, wins / games))
        point_diff_per_game = (
            points_for - points_against
        ) / max(games, 1)
        return win_pct, games, point_diff_per_game

    # At season open, standings contain no information. Keep this only as a
    # mild absolute roster prior; the league-relative rank below does the real
    # classification work.
    projected = max(
        0.30,
        min(0.70, 0.50 + (top_five - 82.0) / 42.0),
    )
    return projected, 0, 0.0


def _team_base_metrics(state: Any, team: str) -> dict[str, Any]:
    players = _team_roster_players(state, team)
    ratings = sorted(
        (_overall(player) for player in players),
        reverse=True,
    )
    top_five = (
        sum(ratings[:5]) / max(1, min(5, len(ratings)))
        if ratings
        else 65.0
    )
    top_three = (
        sum(ratings[:3]) / max(1, min(3, len(ratings)))
        if ratings
        else 65.0
    )
    rotation = (
        sum(ratings[:9]) / max(1, min(9, len(ratings)))
        if ratings
        else 65.0
    )
    best_overall = ratings[0] if ratings else 65.0

    top_eight = sorted(
        players,
        key=_overall,
        reverse=True,
    )[:8]
    ages = [_age(player) for player in top_eight]
    average_age = (
        sum(ages) / len(ages)
        if ages
        else 27.0
    )

    young_core_score = sum(
        max(0.0, _overall(player) - 72.0)
        + max(
            0.0,
            _potential(player) - _overall(player),
        )
        * 0.65
        for player in players
        if _age(player) <= 25.5
    )

    win_pct, games_played, point_diff_per_game = (
        _standing_win_pct(
            state,
            team,
            top_five,
        )
    )

    # Retain the old absolute score for continuity/debugging. V1.1 direction
    # classification no longer thresholds directly on this number.
    strength_score = (
        win_pct * 45.0
        + max(0.0, top_three - 75.0) * 1.45
        + max(0.0, top_five - 75.0) * 0.80
        + max(0.0, rotation - 72.0) * 0.40
    )

    salaries = [_salary(player) for player in players]
    known = [
        salary
        for salary in salaries
        if salary > 0.0
    ]
    known_payroll = sum(known)
    salary_coverage = (
        len(known) / len(players)
        if players
        else 0.0
    )

    return {
        "players": players,
        "ratings": ratings,
        "best_overall": best_overall,
        "top_five": top_five,
        "top_three": top_three,
        "rotation": rotation,
        "average_age": average_age,
        "young_core_score": young_core_score,
        "win_pct": win_pct,
        "games_played": games_played,
        "point_diff_per_game": point_diff_per_game,
        "strength_score": strength_score,
        "known_payroll": known_payroll,
        "salary_coverage": salary_coverage,
    }


def _percentile_map(
    metrics_by_team: Mapping[str, Mapping[str, Any]],
    key: str,
) -> dict[str, float]:
    ordered = sorted(
        (
            (_finite(metrics.get(key), 0.0), team)
            for team, metrics in metrics_by_team.items()
        ),
        key=lambda row: (row[0], row[1]),
    )
    count = len(ordered)
    if count <= 1:
        return {
            team: 0.50
            for _, team in ordered
        }

    # Average percentile across ties so a single tiny rating difference does
    # not produce a large organizational-direction jump.
    result: dict[str, float] = {}
    index = 0
    while index < count:
        value = ordered[index][0]
        end = index + 1
        while (
            end < count
            and abs(ordered[end][0] - value) < 1e-9
        ):
            end += 1
        average_rank = (
            (index + (end - 1)) / 2.0
        )
        percentile = average_rank / (count - 1)
        for tie_index in range(index, end):
            result[ordered[tie_index][1]] = percentile
        index = end
    return result


def _ordinal_suffix(value: int) -> str:
    if 10 <= value % 100 <= 20:
        return "th"
    return {
        1: "st",
        2: "nd",
        3: "rd",
    }.get(value % 10, "th")


def _rank_label(value: int) -> str:
    return f"{value}{_ordinal_suffix(value)}"


def _league_relative_classifications(
    metrics_by_team: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    teams = sorted(metrics_by_team)
    if not teams:
        return {}

    top_three_pct = _percentile_map(
        metrics_by_team,
        "top_three",
    )
    top_five_pct = _percentile_map(
        metrics_by_team,
        "top_five",
    )
    rotation_pct = _percentile_map(
        metrics_by_team,
        "rotation",
    )
    win_pct_rank = _percentile_map(
        metrics_by_team,
        "win_pct",
    )
    point_diff_pct = _percentile_map(
        metrics_by_team,
        "point_diff_per_game",
    )
    young_core_pct = _percentile_map(
        metrics_by_team,
        "young_core_score",
    )

    competitive_scores: dict[str, float] = {}
    performance_weights: dict[str, float] = {}

    for team in teams:
        metrics = metrics_by_team[team]
        talent = 100.0 * (
            0.40 * top_three_pct[team]
            + 0.35 * top_five_pct[team]
            + 0.25 * rotation_pct[team]
        )

        games = int(
            _finite(metrics.get("games_played"), 0.0)
        )
        # Standings earn authority gradually. At roughly 30 games they have
        # enough signal to carry most of the classification, but roster quality
        # never becomes irrelevant.
        performance_weight = min(
            0.58,
            games / 30.0 * 0.58,
        )
        performance_weights[team] = performance_weight

        performance = 100.0 * (
            0.70 * win_pct_rank[team]
            + 0.30 * point_diff_pct[team]
        )

        # A genuine superstar ceiling matters at the very top, but only as a
        # small modifier after league-relative talent.
        best = _finite(
            metrics.get("best_overall"),
            65.0,
        )
        star_bonus = max(
            0.0,
            min(4.0, (best - 90.0) * 0.70),
        )

        competitive_scores[team] = round(
            (
                talent * (1.0 - performance_weight)
                + performance * performance_weight
                + star_bonus
            ),
            3,
        )

    ranked = sorted(
        teams,
        key=lambda team: (
            -competitive_scores[team],
            -_finite(metrics_by_team[team].get("top_three"), 0.0),
            -_finite(metrics_by_team[team].get("top_five"), 0.0),
            team,
        ),
    )
    ranks = {
        team: index + 1
        for index, team in enumerate(ranked)
    }

    team_count = len(teams)
    push_band = max(
        4,
        min(6, round(team_count * 0.17)),
    )
    contender_band = max(
        push_band + 5,
        min(13, round(team_count * 0.40)),
    )
    bottom_band_start = max(
        contender_band + 5,
        round(team_count * 0.73),
    )

    results: dict[str, dict[str, Any]] = {}

    for team in teams:
        metrics = metrics_by_team[team]
        rank = ranks[team]
        percentile = (
            1.0
            if team_count <= 1
            else 1.0 - ((rank - 1) / (team_count - 1))
        )
        top_three = _finite(metrics.get("top_three"), 75.0)
        top_five = _finite(metrics.get("top_five"), 75.0)
        rotation = _finite(metrics.get("rotation"), 72.0)
        average_age = _finite(metrics.get("average_age"), 27.0)
        young_core = _finite(metrics.get("young_core_score"), 0.0)
        games = int(_finite(metrics.get("games_played"), 0.0))
        win_pct = _finite(metrics.get("win_pct"), 0.5)

        young_profile = (
            average_age <= 26.7
            and (
                young_core_pct[team] >= 0.55
                or young_core >= 42.0
            )
        )

        # Bottom-tier direction is based on *why* the team is weak. A bad
        # young roster with a credible core should Develop, not be forced into
        # a teardown simply because it ranks 29th or 30th. Rebuild is reserved
        # for weak teams without a strong long-term young-core case.
        if rank >= bottom_band_start:
            if young_profile:
                timeline = TIMELINE_DEVELOP
            else:
                timeline = TIMELINE_REBUILD
        elif (
            rank >= max(contender_band + 3, 19)
            and young_profile
            and top_five < 84.5
        ):
            timeline = TIMELINE_DEVELOP
        elif (
            rank <= push_band
            and top_three >= 84.5
            and top_five >= 81.5
            and rotation >= 76.5
            and (
                games == 0
                or win_pct >= 0.50
                or rank <= 3
            )
        ):
            timeline = TIMELINE_CHAMPIONSHIP_PUSH
        elif (
            rank <= contender_band
            and top_five >= 79.5
            and rotation >= 74.5
        ):
            timeline = TIMELINE_CONTENDER
        else:
            timeline = TIMELINE_RETOOL

        rationale: list[str] = [
            (
                f"Competitive profile ranks "
                f"{_rank_label(rank)} of {team_count}."
            ),
            (
                "Top-three talent sits in the "
                f"{top_three_pct[team] * 100:.0f}th league percentile; "
                "rotation quality sits in the "
                f"{rotation_pct[team] * 100:.0f}th percentile."
            ),
        ]
        if games > 0:
            rationale.append(
                (
                    f"{games} game(s) are complete, so current results carry "
                    f"{performance_weights[team] * 100:.0f}% of the competitive score."
                )
            )
        else:
            rationale.append(
                "No current-season games are complete, so direction is driven by relative roster strength."
            )
        if timeline == TIMELINE_DEVELOP:
            rationale.append(
                "The roster is below the competitive middle but has a credible young-core development case."
            )
        elif timeline == TIMELINE_REBUILD:
            rationale.append(
                "The club sits in the league's bottom competitive band without enough young-core strength to justify a pure development path, so long-term asset accumulation should lead."
            )
        elif timeline == TIMELINE_CHAMPIONSHIP_PUSH:
            rationale.append(
                "Elite league rank plus sufficient top-end and rotation quality supports a true title-window posture."
            )
        elif timeline == TIMELINE_CONTENDER:
            rationale.append(
                "The club is in the upper competitive tier but falls short of the stricter title-push bar."
            )
        else:
            rationale.append(
                "The roster belongs in the league's middle class, where reshaping is more appropriate than all-in or teardown behavior."
            )

        results[team] = {
            "timeline": timeline,
            "league_rank": rank,
            "league_percentile": round(percentile, 4),
            "competitive_score": competitive_scores[team],
            "direction_rationale": tuple(rationale[:4]),
        }

    return results


def classify_timeline(metrics: Mapping[str, Any]) -> str:
    # Backward-compatible single-team fallback. League planning uses the
    # relative model above because organizational direction is inherently a
    # comparison against the other 29 teams.
    win_pct = _finite(metrics.get("win_pct"), 0.5)
    top_five = _finite(metrics.get("top_five"), 75.0)
    average_age = _finite(metrics.get("average_age"), 27.0)
    young_core = _finite(metrics.get("young_core_score"), 0.0)

    if win_pct >= 0.61 and top_five >= 84.5:
        return TIMELINE_CHAMPIONSHIP_PUSH
    if win_pct >= 0.53 and top_five >= 80.5:
        return TIMELINE_CONTENDER
    if win_pct <= 0.40 and top_five < 80.0:
        return (
            TIMELINE_DEVELOP
            if average_age <= 26.5 and young_core >= 42.0
            else TIMELINE_REBUILD
        )
    return TIMELINE_RETOOL


def _financial_posture(metrics: Mapping[str, Any], median_payroll: float) -> str:
    coverage = _finite(metrics.get("salary_coverage"), 0.0)
    payroll = _finite(metrics.get("known_payroll"), 0.0)
    if coverage < 0.60:
        return "Future salary picture incomplete"
    if median_payroll <= 0.0:
        return "Balanced flexibility"
    if payroll >= median_payroll * 1.16:
        return "High salary pressure"
    if payroll <= median_payroll * 0.82:
        return "Flexible spending posture"
    return "Balanced flexibility"


def _draft_posture(timeline: str) -> str:
    return {
        TIMELINE_CHAMPIONSHIP_PUSH: (
            "Spend selectively: firsts move only for a championship-level upgrade"
        ),
        TIMELINE_CONTENDER: (
            "Stay flexible: value firsts, spend only for a clear playoff upgrade"
        ),
        TIMELINE_RETOOL: (
            "Protect premium firsts and use secondary capital to reshape the rotation"
        ),
        TIMELINE_DEVELOP: (
            "Preserve firsts, add extra chances, and prioritize upside"
        ),
        TIMELINE_REBUILD: (
            "Accumulate firsts and swaps; avoid spending future capital for short-term wins"
        ),
    }[timeline]


def _trade_goal(timeline: str, biggest_need: str) -> str:
    # Keep the existing stable goal vocabulary because Trade Finder and future
    # execution layers can consume these values without learning a second API.
    if timeline == TIMELINE_CHAMPIONSHIP_PUSH:
        return "win_now"
    if timeline == TIMELINE_CONTENDER:
        return "fill_biggest_need"
    if timeline in {TIMELINE_DEVELOP, TIMELINE_REBUILD}:
        return "future_upside"
    return "best_available"



def _free_agent_strategy(timeline: str) -> str:
    return {
        TIMELINE_CHAMPIONSHIP_PUSH: (
            "Immediate playoff impact; veterans are acceptable when role and price fit"
        ),
        TIMELINE_CONTENDER: (
            "Targeted two-way upgrade; balance current impact with age and value"
        ),
        TIMELINE_RETOOL: (
            "Younger two-way fits and value contracts; avoid paying for reputation"
        ),
        TIMELINE_DEVELOP: (
            "Young upside and development-compatible value; avoid blocking prospects"
        ),
        TIMELINE_REBUILD: (
            "Young upside, distressed value and flexibility; avoid long veteran commitments"
        ),
    }[timeline]


PROTECTED_MARKET_STANCES = {
    "Untouchable",
    "Premium offers only",
    "Protect development asset",
}
MARKET_ACTION_STANCES = {
    "Shop / salary relief",
    "Listen for future assets",
    "Shop for future assets",
    "Premium future assets only",
    "Listen for younger fit",
    "Available for future assets",
    "Available in reshape package",
}
CONSOLIDATION_STANCES = {
    "Available in championship upgrade",
    "Available in targeted upgrade",
}


def _asset_policy(market_stance: str) -> str:
    if market_stance in {"Untouchable", "Premium offers only"}:
        return "Protect"
    if market_stance == "Protect development asset":
        return "Develop"
    if market_stance == "Waive/cut candidate":
        return "Exit"
    if market_stance in CONSOLIDATION_STANCES:
        return "Consolidate"
    if market_stance in MARKET_ACTION_STANCES:
        return "Market"
    return "Retain"


def _contract_is_retention_priority(contract_plan: str) -> bool:
    return contract_plan in {
        "Re-sign priority",
        "Re-sign young core",
        "Extension priority",
        "Retain if price fits",
        "Retain for playoff role if price fits",
        "Retain young fit if price fits",
    }


def _decision_priority(
    player: Any,
    *,
    role: str,
    market_stance: str,
    contract_plan: str,
    timeline: str,
    biggest_need: str,
    roster_count: int,
) -> float:
    profile = behavior_profile(timeline)
    years = _years(player)
    family = position_family(getattr(player, "position", ""))
    policy = _asset_policy(market_stance)

    score = 24.0
    if years in {0, 1}:
        score += 26.0
    if role == "Cornerstone":
        score += 24.0
    elif role == "Core":
        score += 15.0
    if family == biggest_need:
        score += 6.0

    if policy == "Market":
        score += 10.0 + profile.veteran_liquidity * 0.20
    elif policy == "Consolidate":
        score += 8.0 + profile.consolidation_bias * 0.18
    elif policy == "Develop":
        score += 8.0 + profile.youth_bias * 0.15
    elif policy == "Protect":
        score += profile.continuity_bias * 0.12
    elif policy == "Exit":
        score += 28.0 if roster_count > 15 else 12.0

    if "priority" in contract_plan.lower():
        score += 12.0
    return round(max(0.0, min(100.0, score)), 1)




ASSET_TIER_ORDER = {
    "Filler": 0,
    "Rotation": 1,
    "Development": 2,
    "Starter": 3,
    "High-End Starter": 4,
    "Star": 5,
    "Franchise": 6,
}


def _asset_tier(
    player: Any,
    *,
    role: str,
    strategic_value: float,
    market_context: AssetMarketContext | None = None,
    timeline: str = "",
) -> str:
    if market_context is not None:
        return market_context.asset_tier

    # Single-team fallback when a league-relative context map is unavailable.
    context = build_asset_market_context(
        player,
        timeline=timeline,
    )
    return context.asset_tier


def _minimum_return_for_asset_tier(
    asset_tier: str,
    *,
    age: float,
    timeline: str,
    market_context: AssetMarketContext | None = None,
    trade_value_score: float | None = None,
    contract_control_score: float | None = None,
) -> tuple[str, int, bool]:
    trade_value = (
        float(trade_value_score)
        if trade_value_score is not None
        else (
            market_context.trade_value_score
            if market_context is not None
            else 0.0
        )
    )
    control = (
        float(contract_control_score)
        if contract_control_score is not None
        else (
            market_context.contract_control_score
            if market_context is not None
            else 50.0
        )
    )

    if asset_tier == "Franchise":
        firsts = (
            3
            if (
                age <= 29.0
                and trade_value >= 155.0
                and control >= 50.0
            )
            else 2
        )
        blue_chip = (
            age <= 31.0
            and trade_value >= 138.0
        )
        if blue_chip:
            label = (
                "Blue-chip young star plus multiple premium first-round equivalents"
            )
        else:
            label = (
                "Multiple premium first-round-equivalent assets plus a high-end young starter"
            )
        return label, firsts, blue_chip

    if asset_tier == "Star":
        firsts = (
            2
            if (
                age <= 30.0
                and trade_value >= 125.0
            )
            else 1
        )
        blue_chip = (
            age <= 29.0
            and trade_value >= 135.0
        )
        label = (
            "Premium young starter plus premium first-round-equivalent value"
            if blue_chip
            else "Premium starter or young asset plus first-round-equivalent value"
        )
        return label, firsts, blue_chip

    if asset_tier == "High-End Starter":
        requires_first = (
            trade_value >= 95.0
            or timeline in {
                TIMELINE_DEVELOP,
                TIMELINE_REBUILD,
            }
        )
        return (
            (
                "First-round-equivalent value or a younger high-level starter"
                if requires_first
                else "Clear high-end rotation upgrade or strong young value"
            ),
            1 if requires_first else 0,
            False,
        )

    if asset_tier == "Starter":
        return (
            "Comparable starter value or meaningful draft compensation",
            0,
            False,
        )

    if asset_tier == "Development":
        return (
            "Young asset with equal-or-better upside",
            0,
            False,
        )

    if asset_tier == "Rotation":
        return (
            "Useful rotation value, draft value, or roster-fit improvement",
            0,
            False,
        )

    return (
        "Roster flexibility or minor asset value",
        0,
        False,
    )


def _premium_market_flag(
    asset_tier: str,
    *,
    age: float,
    timeline: str,
    trade_value_score: float = 0.0,
) -> bool:
    if asset_tier == "Franchise":
        return True
    if asset_tier == "Star":
        return trade_value_score >= 88.0
    if (
        asset_tier == "High-End Starter"
        and timeline in {
            TIMELINE_RETOOL,
            TIMELINE_DEVELOP,
            TIMELINE_REBUILD,
        }
        and age <= 30.5
        and trade_value_score >= 88.0
    ):
        return True
    return False


def _family_depth_rank(
    player: Any,
    roster_players: Iterable[Any],
) -> int:
    family = position_family(
        getattr(player, "position", "")
    )
    family_players = [
        row
        for row in roster_players
        if position_family(
            getattr(row, "position", "")
        ) == family
    ]
    family_players.sort(
        key=lambda row: (
            -_overall(row),
            -_potential(row),
            _age(row),
            _clean(
                getattr(row, "player_name", "")
            ),
        )
    )
    player_id = str(
        getattr(player, "player_id", "")
    )
    for index, row in enumerate(
        family_players,
        start=1,
    ):
        if str(getattr(row, "player_id", "")) == player_id:
            return index
    return max(1, len(family_players))


def _roster_fit_label(
    *,
    family: str,
    depth_rank: int,
    biggest_need: str,
    secondary_need: str,
    family_need: float,
    family_surplus: float,
    role: str,
    overall: float,
    age: float,
    timeline: str,
) -> str:
    if role in {"Cornerstone", "Core"}:
        return "Core fit"

    # "Need protection" is an actual front-office constraint, not merely a
    # description that the team is thin at the player's position. The player
    # must be useful enough to protect and must fit the team's timeline.
    timeline_eligible = not (
        (
            timeline == TIMELINE_REBUILD
            and age >= 28.5
        )
        or (
            timeline == TIMELINE_DEVELOP
            and age >= 30.0
        )
    )

    primary_protection = (
        family == biggest_need
        and family_need >= 8.0
        and depth_rank <= 3
        and overall >= 74.0
        and timeline_eligible
    )
    secondary_protection = (
        family == secondary_need
        and family_need >= 8.0
        and depth_rank <= 2
        and overall >= 75.0
        and timeline_eligible
    )

    if primary_protection or secondary_protection:
        return "Need protection"

    if (
        family_surplus >= 5.0
        and depth_rank >= 3
    ):
        return "Surplus"

    return "Neutral"


def _retention_score(
    player: Any,
    *,
    role: str,
    timeline: str,
    biggest_need: str,
    need_scores: Mapping[str, float],
    financial_posture: str,
) -> float:
    profile = behavior_profile(timeline)
    value = intrinsic_player_value(player)
    overall = _overall(player)
    potential = _potential(player)
    age = _age(player)
    family = position_family(getattr(player, "position", ""))
    need = max(0.0, _finite(need_scores.get(family), 0.0))
    salary = _salary(player)

    score = 22.0 + value * 0.45 + min(10.0, need * 0.32)
    if family == biggest_need:
        score += 4.0

    immediate_signal = max(-10.0, min(18.0, (overall - 77.0) * 1.05))
    youth_signal = max(
        -10.0,
        min(
            18.0,
            (27.0 - age) * 1.25
            + max(0.0, potential - overall) * 0.70,
        ),
    )
    score += immediate_signal * (profile.win_now_bias / 100.0)
    score += youth_signal * (profile.youth_bias / 100.0)

    if role == "Cornerstone":
        score += 10.0 + profile.continuity_bias * 0.10
    elif role == "Core":
        score += 5.0 + profile.continuity_bias * 0.065
    elif role == "Development":
        score += profile.youth_bias * 0.055

    # Rebuilders and development teams should not confuse useful veterans with
    # long-term core pieces. The stronger the veteran-liquidity preference, the
    # more replaceable non-core veterans become.
    if age >= 29.5 and role not in {"Cornerstone"}:
        veteran_penalty = min(
            16.0,
            max(0.0, age - 29.0) * 2.0
            + max(0.0, 82.0 - overall) * 0.55,
        )
        score -= veteran_penalty * (profile.veteran_liquidity / 100.0)

    if (
        timeline == TIMELINE_REBUILD
        and age >= 29.0
        and role == "Core"
        and overall < 90.0
    ):
        score -= 6.0

    if (
        financial_posture == "High salary pressure"
        and salary >= 18_000_000.0
        and overall < 85.0
    ):
        salary_penalty = min(
            14.0,
            (salary - 16_000_000.0) / 2_250_000.0,
        )
        score -= salary_penalty * (profile.salary_discipline / 100.0)

    career = _career_status(player)
    if "farewell" in career:
        score = min(score, 36.0)
    elif "retir" in career or "consider" in career:
        score -= 12.0

    return round(max(0.0, min(100.0, score)), 1)


def _contract_plan(
    player: Any,
    retention_score: float,
    role: str,
    timeline: str,
) -> str:
    years = _years(player)
    status = _contract_status(player)
    age = _age(player)
    is_free_agent = "free" in status or "ufa" in status or "rfa" in status

    if is_free_agent or years == 0:
        if role in {"Cornerstone", "Core"} and retention_score >= 80.0:
            return "Re-sign priority"

        if timeline == TIMELINE_CHAMPIONSHIP_PUSH:
            if retention_score >= 70.0:
                return "Retain for playoff role if price fits"
            if retention_score >= 54.0:
                return "Replace only for clear upgrade"
            return "Let walk / upgrade role"

        if timeline == TIMELINE_CONTENDER:
            if retention_score >= 72.0:
                return "Retain if price fits"
            if retention_score >= 56.0:
                return "Explore alternatives"
            return "Let walk / replace"

        if timeline == TIMELINE_RETOOL:
            if age <= 28.5 and retention_score >= 70.0:
                return "Retain young fit if price fits"
            if age >= 30.0:
                return "Short-term/value only"
            if retention_score >= 56.0:
                return "Explore younger alternatives"
            return "Let walk / reshape role"

        if timeline == TIMELINE_DEVELOP:
            if age <= 26.0 and retention_score >= 66.0:
                return "Re-sign young core"
            if age >= 29.0:
                return "Avoid long-term veteran commitment"
            if retention_score >= 56.0:
                return "Retain only if development fit"
            return "Let walk for development slot"

        if age <= 26.0 and retention_score >= 66.0:
            return "Re-sign young core"
        if age >= 28.0:
            return "Preserve flexibility / let market develop"
        if retention_score >= 56.0:
            return "Retain only at value"
        return "Let walk / preserve flexibility"

    if years is None:
        if retention_score >= 84.0 and role in {"Cornerstone", "Core"}:
            return "Control data incomplete: preserve core"
        if retention_score <= 50.0:
            return "Control data incomplete: evaluate exit"
        return "Control data incomplete: monitor"

    if years == 1:
        if role in {"Cornerstone", "Core"} and retention_score >= 84.0:
            if timeline == TIMELINE_REBUILD and age >= 29.0:
                return "Explore premium market before extension"
            return "Extension priority"
        if (
            timeline in {TIMELINE_DEVELOP, TIMELINE_REBUILD}
            and age <= 26.0
            and retention_score >= 68.0
        ):
            return "Extension priority"
        if retention_score >= 70.0:
            return "Extension watch"
        if timeline == TIMELINE_REBUILD and age >= 28.0:
            return "Explore trade before extension"
        return "Evaluate before contract decision"

    if retention_score <= 42.0:
        return "Under contract: seek roster upgrade"
    return "Keep under contract"


def _market_stance(
    player: Any,
    *,
    role: str,
    retention_score: float,
    timeline: str,
    roster_count: int,
    family_need: float = 0.0,
    family_surplus: float = 0.0,
    depth_rank: int = 1,
    is_biggest_need: bool = False,
    need_protection: bool = False,
    asset_tier: str = "Rotation",
) -> str:
    overall = _overall(player)
    potential = _potential(player)
    age = _age(player)
    salary = _salary(player)

    # V1.5 gives high-value assets a separate market regime. A team may still
    # listen on a star, but never treats that player like an ordinary veteran.
    if asset_tier == "Franchise":
        if (
            timeline == TIMELINE_REBUILD
            and age >= 30.5
        ):
            return "Premium future assets only"
        return "Untouchable"

    if asset_tier == "Star":
        if timeline in {
            TIMELINE_CHAMPIONSHIP_PUSH,
            TIMELINE_CONTENDER,
        }:
            return "Premium offers only"
        if timeline == TIMELINE_RETOOL:
            return (
                "Premium future assets only"
                if age >= 31.0
                else "Premium offers only"
            )
        if age <= 28.5:
            return "Protect development asset"
        return "Premium future assets only"

    if asset_tier == "High-End Starter":
        if timeline in {
            TIMELINE_CHAMPIONSHIP_PUSH,
            TIMELINE_CONTENDER,
        }:
            return "Hold for playoff role"
        if timeline == TIMELINE_RETOOL:
            if age >= 31.0 and not need_protection:
                return "Listen for younger fit"
            return "Hold"
        if timeline in {
            TIMELINE_DEVELOP,
            TIMELINE_REBUILD,
        }:
            if age <= 27.0:
                return "Protect development asset"
            if age >= 29.5:
                return "Premium future assets only"
            return "Hold"

    if role == "Core":
        if timeline in {
            TIMELINE_CHAMPIONSHIP_PUSH,
            TIMELINE_CONTENDER,
        }:
            return "Premium offers only"
        if timeline == TIMELINE_RETOOL:
            return (
                "Listen for younger fit"
                if age >= 30.0
                and overall < 89.0
                and not is_biggest_need
                else "Premium offers only"
            )
        if (
            age <= 26.5
            or potential >= overall + 4.0
        ):
            return "Protect development asset"
        return "Premium future assets only"

    if (
        role == "Development"
        and age <= 24.5
        and potential >= overall + 4.0
    ):
        if timeline in {
            TIMELINE_RETOOL,
            TIMELINE_DEVELOP,
            TIMELINE_REBUILD,
        }:
            return "Protect development asset"
        if retention_score >= 74.0:
            return "Protect development asset"

    if need_protection:
        if timeline in {
            TIMELINE_CHAMPIONSHIP_PUSH,
            TIMELINE_CONTENDER,
        }:
            return "Hold for playoff role"
        return "Hold"

    if (
        retention_score <= 34.0
        and roster_count > 15
        and overall < 74.5
    ):
        return "Waive/cut candidate"

    surplus_asset = (
        family_surplus >= 5.0
        and depth_rank >= 3
    )
    bad_salary = (
        salary >= 18_000_000.0
        and overall < 82.0
        and retention_score <= 42.0
    )

    if (
        bad_salary
        or (
            retention_score <= 35.0
            and age >= 30.0
        )
    ):
        return "Shop / salary relief"

    if timeline == TIMELINE_CHAMPIONSHIP_PUSH:
        if overall >= 80.0:
            return "Hold for playoff role"
        if (
            surplus_asset
            or (
                overall >= 74.5
                and depth_rank >= 3
            )
        ):
            return "Available in championship upgrade"
        return "Hold"

    if timeline == TIMELINE_CONTENDER:
        if overall >= 80.0:
            return "Hold for playoff role"
        if (
            surplus_asset
            or (
                overall >= 74.5
                and depth_rank >= 3
            )
        ):
            return "Available in targeted upgrade"
        return "Hold"

    if timeline == TIMELINE_RETOOL:
        if (
            age >= 30.0
            and overall >= 76.0
            and depth_rank >= 2
        ):
            return "Listen for younger fit"
        if surplus_asset:
            return "Available in reshape package"
        if (
            age <= 28.5
            and retention_score >= 56.0
        ):
            return "Hold"
        if (
            depth_rank >= 4
            and retention_score < 50.0
        ):
            return "Available in reshape package"
        return "Hold"

    if timeline == TIMELINE_DEVELOP:
        if (
            age <= 25.5
            and (
                role == "Development"
                or potential >= max(
                    80.0,
                    overall + 4.0,
                )
            )
        ):
            return "Protect development asset"
        if (
            age >= 29.0
            and overall >= 76.0
        ):
            return "Listen for future assets"
        if (
            surplus_asset
            and age >= 26.0
        ):
            return "Available for future assets"
        if (
            age >= 27.0
            and retention_score <= 50.0
            and depth_rank >= 3
        ):
            return "Available for future assets"
        return "Hold"

    if (
        age <= 25.5
        and (
            role == "Development"
            or potential >= max(
                80.0,
                overall + 4.0,
            )
        )
    ):
        return "Protect development asset"
    if age >= 28.0 and overall >= 76.0:
        return "Shop for future assets"
    if age >= 30.0:
        return "Shop / salary relief"
    if surplus_asset and depth_rank >= 3:
        return "Available for future assets"
    if (
        retention_score <= 56.0
        and depth_rank >= 3
    ):
        return "Available for future assets"
    return "Hold"


def _player_rationale(
    player: Any,
    *,
    role: str,
    retention_score: float,
    biggest_need: str,
    timeline: str,
    financial_posture: str,
    market_stance: str,
) -> tuple[str, ...]:
    reasons: list[str] = []
    profile = behavior_profile(timeline)
    family = position_family(getattr(player, "position", ""))
    age = _age(player)
    overall = _overall(player)
    potential = _potential(player)
    salary = _salary(player)
    years = _years(player)

    if role in {"Cornerstone", "Core"}:
        reasons.append(f"{role.lower()}-level talent")
    elif role == "Development":
        reasons.append("meaningful youth/upside runway")

    if family == biggest_need:
        reasons.append(f"fills the roster's biggest {family.lower()} need")

    if (
        profile.youth_bias >= 68.0
        and age <= 25.5
    ):
        reasons.append("age fits the organizational timeline")
    if (
        profile.win_now_bias >= 80.0
        and overall >= 80.0
    ):
        reasons.append("current impact matches the competitive window")
    if (
        profile.veteran_liquidity >= 65.0
        and age >= 30.0
        and role not in {"Cornerstone"}
    ):
        reasons.append("veteran value can be recycled into younger/future assets")
    if potential >= overall + 5.0:
        reasons.append("potential materially exceeds current rating")
    if (
        financial_posture == "High salary pressure"
        and salary >= 20_000_000.0
        and overall < 84.0
    ):
        reasons.append("salary burden is significant relative to impact")
    if market_stance in CONSOLIDATION_STANCES:
        reasons.append("secondary asset can be consolidated for a larger upgrade")
    if years in {0, 1}:
        reasons.append("near-term contract decision")
    elif years is None:
        reasons.append("future contract control is incomplete")

    if not reasons:
        reasons.append("neutral roster-value profile")
    return tuple(reasons[:4])


def _free_agent_target_score(
    player: Any,
    *,
    timeline: str,
    biggest_need: str,
    secondary_need: str,
    need_scores: Mapping[str, float],
    surplus_scores: Mapping[str, float],
    financial_posture: str,
) -> tuple[float, tuple[str, ...]]:
    profile = behavior_profile(timeline)
    overall = _overall(player)
    potential = _potential(player)
    age = _age(player)
    salary = _salary(player)
    family = position_family(
        getattr(player, "position", "")
    )
    need = max(
        0.0,
        _finite(
            need_scores.get(family),
            0.0,
        ),
    )
    surplus = max(
        0.0,
        _finite(
            surplus_scores.get(family),
            0.0,
        ),
    )
    upside = max(
        0.0,
        potential - overall,
    )

    # V1.3 intentionally reduces raw intrinsic-value dominance. Team need and
    # timeline fit now have enough weight to change who actually leads a board.
    score = intrinsic_player_value(player) * 0.34
    score += min(30.0, need * 1.18)
    score -= min(16.0, surplus * 0.85)

    immediate_signal = max(
        -8.0,
        min(
            16.0,
            (overall - 75.0) * 1.05,
        ),
    )
    youth_signal = max(
        -8.0,
        min(
            18.0,
            (27.0 - age) * 1.20
            + upside * 0.75,
        ),
    )
    score += immediate_signal * (
        profile.win_now_bias / 100.0
    )
    score += youth_signal * (
        profile.youth_bias / 100.0
    )

    reasons: list[str] = []
    if family == biggest_need:
        score += 14.0
        reasons.append(
            f"primary {biggest_need.lower()} need"
        )
    elif family == secondary_need:
        score += 6.0
        reasons.append(
            f"secondary {secondary_need.lower()} need"
        )

    if (
        profile.win_now_bias >= 80.0
        and overall >= 79.0
    ):
        score += 5.0
        reasons.append(
            "ready for a competitive rotation"
        )
    if (
        profile.youth_bias >= 68.0
        and age <= 26.0
    ):
        score += 5.0
        reasons.append(
            "age fits the organizational timeline"
        )
    if (
        profile.youth_bias >= 68.0
        and upside >= 4.0
    ):
        score += 4.0
        reasons.append("upside remains")

    if surplus >= 6.0:
        reasons.append(
            "position already carries meaningful depth"
        )

    if age > profile.preferred_fa_age_ceiling:
        score -= (
            age - profile.preferred_fa_age_ceiling
        ) * (
            1.4
            + profile.future_asset_bias / 100.0
        )

    if (
        timeline == TIMELINE_REBUILD
        and age >= 29.0
        and overall < 88.0
    ):
        score -= 18.0
        reasons.append(
            "veteran timeline conflicts with asset-building phase"
        )
    elif (
        timeline == TIMELINE_DEVELOP
        and age >= 30.0
        and overall < 86.0
    ):
        score -= 12.0
        reasons.append(
            "veteran timeline could block development minutes"
        )

    if salary > 0.0:
        if (
            financial_posture == "High salary pressure"
            and salary > 16_000_000.0
        ):
            salary_penalty = min(
                14.0,
                (
                    salary - 16_000_000.0
                ) / 1_800_000.0,
            )
            score -= salary_penalty * (
                profile.salary_discipline / 100.0
            )
            reasons.append(
                "price could conflict with salary flexibility"
            )
        elif (
            salary <= 10_000_000.0
            and overall >= 75.0
        ):
            score += 4.0 * (
                profile.salary_discipline / 100.0
            )
            reasons.append(
                "salary reference suggests value potential"
            )

    career = _career_status(player)
    if (
        "farewell" in career
        or "retired" in career
    ):
        score -= 50.0
    elif "consider" in career:
        score -= 18.0

    if not reasons:
        reasons.append(
            "best available fit on the current market"
        )
    return round(score, 2), tuple(reasons[:3])


def _free_agent_targets(
    state: Any,
    *,
    timeline: str,
    biggest_need: str,
    secondary_need: str,
    need_scores: Mapping[str, float],
    surplus_scores: Mapping[str, float],
    financial_posture: str,
    limit: int = 6,
) -> tuple[FrontOfficeFreeAgentTarget, ...]:
    players = getattr(state, "players", {})
    free_agent_ids = tuple(
        getattr(
            state,
            "free_agent_player_ids",
            (),
        )
        or ()
    )
    candidates: list[
        FrontOfficeFreeAgentTarget
    ] = []

    for player_id in free_agent_ids:
        player = players.get(player_id)
        if player is None:
            continue

        overall = _overall(player)
        potential = _potential(player)
        age = _age(player)
        family = position_family(
            getattr(player, "position", "")
        )

        if (
            overall < 68.0
            and potential < 76.0
        ):
            continue
        if (
            timeline == TIMELINE_REBUILD
            and age > 31.0
            and overall < 88.0
        ):
            continue
        if (
            timeline == TIMELINE_DEVELOP
            and age > 32.0
            and overall < 86.0
        ):
            continue

        fit_score, reasons = (
            _free_agent_target_score(
                player,
                timeline=timeline,
                biggest_need=biggest_need,
                secondary_need=secondary_need,
                need_scores=need_scores,
                surplus_scores=surplus_scores,
                financial_posture=financial_posture,
            )
        )
        if fit_score < 20.0:
            continue

        if timeline == TIMELINE_CHAMPIONSHIP_PUSH:
            tier = (
                "Win-now priority"
                if fit_score >= 75.0
                else "Playoff rotation fit"
                if fit_score >= 55.0
                else "Depth/value target"
            )
        elif timeline == TIMELINE_CONTENDER:
            tier = (
                "Priority upgrade"
                if fit_score >= 75.0
                else "Strong two-way fit"
                if fit_score >= 55.0
                else "Depth/value target"
            )
        elif timeline == TIMELINE_RETOOL:
            tier = (
                "Core-age fit"
                if fit_score >= 72.0
                else "Younger value fit"
                if fit_score >= 52.0
                else "Flexible depth target"
            )
        else:
            tier = (
                "Young-core target"
                if fit_score >= 70.0
                else "Upside/value target"
                if fit_score >= 50.0
                else "Development flyer"
            )

        candidates.append(
            FrontOfficeFreeAgentTarget(
                player_id=str(player_id),
                player_name=_clean(
                    getattr(
                        player,
                        "player_name",
                        player_id,
                    )
                ),
                position=_clean(
                    getattr(
                        player,
                        "position",
                        "UNK",
                    )
                )
                or "UNK",
                age=round(age, 1),
                overall=round(overall, 1),
                potential=round(potential, 1),
                salary_reference=round(
                    _salary(player),
                    2,
                ),
                fit_score=fit_score,
                target_tier=tier,
                target_lane="Best value",
                position_family=family,
                rationale=reasons,
            )
        )

    candidates.sort(
        key=lambda row: (
            -row.fit_score,
            -row.overall,
            row.age,
            row.player_name,
        )
    )

    # V1.3 builds a board rather than cloning one global FA ranking. The best
    # primary-need and secondary-need candidates are guaranteed lanes when
    # they clear the minimum fit threshold, then the rest is filled by value
    # with a family cap to prevent six centers/guards/wings from dominating.
    selected: list[
        FrontOfficeFreeAgentTarget
    ] = []
    selected_ids: set[str] = set()
    family_counts = {
        "Guard": 0,
        "Wing/Forward": 0,
        "Center": 0,
    }

    def add_best_family(
        family: str,
        lane: str,
    ) -> None:
        for candidate in candidates:
            if candidate.player_id in selected_ids:
                continue
            if candidate.position_family != family:
                continue
            selected.append(
                FrontOfficeFreeAgentTarget(
                    player_id=candidate.player_id,
                    player_name=candidate.player_name,
                    position=candidate.position,
                    age=candidate.age,
                    overall=candidate.overall,
                    potential=candidate.potential,
                    salary_reference=candidate.salary_reference,
                    fit_score=candidate.fit_score,
                    target_tier=candidate.target_tier,
                    target_lane=lane,
                    position_family=candidate.position_family,
                    rationale=candidate.rationale,
                )
            )
            selected_ids.add(candidate.player_id)
            family_counts[family] += 1
            return

    add_best_family(
        biggest_need,
        "Primary need",
    )
    if secondary_need != biggest_need:
        add_best_family(
            secondary_need,
            "Secondary need",
        )

    for candidate in candidates:
        if len(selected) >= limit:
            break
        if candidate.player_id in selected_ids:
            continue
        if (
            family_counts[
                candidate.position_family
            ] >= 3
        ):
            continue
        lane = (
            "Upside/value"
            if candidate.age <= 25.5
            and candidate.potential
            >= candidate.overall + 4.0
            else "Best value"
        )
        selected.append(
            FrontOfficeFreeAgentTarget(
                player_id=candidate.player_id,
                player_name=candidate.player_name,
                position=candidate.position,
                age=candidate.age,
                overall=candidate.overall,
                potential=candidate.potential,
                salary_reference=candidate.salary_reference,
                fit_score=candidate.fit_score,
                target_tier=candidate.target_tier,
                target_lane=lane,
                position_family=candidate.position_family,
                rationale=candidate.rationale,
            )
        )
        selected_ids.add(candidate.player_id)
        family_counts[
            candidate.position_family
        ] += 1

    return tuple(selected[:limit])


def _risk_flags(
    players: list[Any],
    *,
    need_scores: Mapping[str, float],
    average_age: float,
    salary_coverage: float,
    financial_posture: str,
) -> tuple[str, ...]:
    flags: list[str] = []
    if len(players) > 15:
        flags.append(f"Roster pressure: {len(players)} standard roster players")
    if average_age >= 30.0:
        flags.append("Older core: age-curve risk is elevated")
    for family in ("Guard", "Wing/Forward", "Center"):
        if _finite(need_scores.get(family), 0.0) >= 18.0:
            flags.append(f"Major {family.lower()} weakness")
    if salary_coverage < 0.60:
        flags.append("Future salary/control data is incomplete")
    elif financial_posture == "High salary pressure":
        flags.append("Limited internal salary flexibility")
    return tuple(flags[:5])


def _objectives(
    *,
    timeline: str,
    biggest_need: str,
    financial_posture: str,
    decisions: Iterable[FrontOfficePlayerDecision],
    fa_targets: tuple[FrontOfficeFreeAgentTarget, ...],
) -> tuple[str, ...]:
    rows = list(decisions)
    retain = [
        row
        for row in rows
        if _contract_is_retention_priority(row.contract_plan)
    ]
    market = [
        row
        for row in rows
        if row.asset_policy == "Market"
    ]
    consolidate = [
        row
        for row in rows
        if row.asset_policy == "Consolidate"
    ]
    develop = [
        row
        for row in rows
        if row.asset_policy == "Develop"
    ]

    objectives: list[str] = []
    if timeline == TIMELINE_CHAMPIONSHIP_PUSH:
        objectives.append(
            "Maximize the current title window and keep the championship core intact."
        )
        if consolidate:
            objectives.append(
                f"Use {consolidate[0].player_name} only as part of a clear championship-level upgrade."
            )
    elif timeline == TIMELINE_CONTENDER:
        objectives.append(
            "Add a meaningful playoff upgrade while preserving top-end continuity and future optionality."
        )
    elif timeline == TIMELINE_RETOOL:
        objectives.append(
            "Reshape the supporting cast toward younger two-way fits without tearing down the core."
        )
        if market:
            objectives.append(
                f"Listen on {market[0].player_name} for younger value or a cleaner roster fit."
            )
    elif timeline == TIMELINE_DEVELOP:
        objectives.append(
            "Protect young-player minutes, patience and asset control around the development core."
        )
        if develop:
            objectives.append(
                f"Preserve a real development runway for {develop[0].player_name}."
            )
    else:
        objectives.append(
            "Accumulate picks, youth and flexibility; do not spend future value for short-term wins."
        )
        if market:
            objectives.append(
                f"Actively test the future-asset market for {market[0].player_name}."
            )

    objectives.append(
        f"Address {biggest_need.lower()} depth/quality as the primary roster need."
    )

    if retain:
        names = ", ".join(row.player_name for row in retain[:2])
        objectives.append(
            f"Resolve high-priority retention decisions: {names}."
        )
    elif develop and timeline in {
        TIMELINE_DEVELOP,
        TIMELINE_REBUILD,
    }:
        names = ", ".join(row.player_name for row in develop[:2])
        objectives.append(
            f"Protect development runway for {names}."
        )
    else:
        objectives.append(
            "Keep contract decisions disciplined around role and timeline fit."
        )

    if financial_posture == "High salary pressure":
        objectives.append(
            "Create flexibility before adding expensive non-core salary."
        )
    elif financial_posture == "Flexible spending posture":
        objectives.append(
            "Use available flexibility selectively instead of spending simply because space exists."
        )
    else:
        objectives.append(
            "Preserve enough flexibility to react to genuine value opportunities."
        )

    if fa_targets and len(objectives) < 5:
        objectives.append(
            f"Track {fa_targets[0].player_name} as the leading free-agent fit."
        )
    return tuple(objectives[:5])


def front_office_state_fingerprint(state: Any) -> str:
    players = getattr(state, "players", {})
    payload = {
        "season": _clean(getattr(getattr(state, "settings", None), "season_label", "")),
        "phase": _clean(getattr(getattr(state, "phase", None), "value", getattr(state, "phase", ""))),
        "teams": {
            team: list(tuple(getattr(team_state, "roster_player_ids", ()) or ()))
            for team, team_state in sorted(getattr(state, "teams", {}).items())
        },
        "players": {
            str(player_id): {
                "team": _team(getattr(player, "team_abbreviation", "")),
                "roster_status": _clean(getattr(player, "roster_status", "")),
                "overall": round(_overall(player), 4),
                "potential": round(_potential(player), 4),
                "future": round(_future(player), 4),
                "age": round(_age(player), 4),
                "salary": round(_salary(player), 2),
                "years": _years(player),
                "position": _clean(getattr(player, "position", "")),
            }
            for player_id, player in sorted(players.items(), key=lambda item: str(item[0]))
        },
        "free_agents": sorted(str(value) for value in tuple(getattr(state, "free_agent_player_ids", ()) or ())),
        "standings": {
            team: [
                int(getattr(standing, "games_played", 0) or 0),
                int(getattr(standing, "wins", 0) or 0),
                int(getattr(standing, "losses", 0) or 0),
            ]
            for team, standing in sorted(getattr(state, "standings", {}).items())
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()



def _draft_spend_budget(
    timeline: str,
    *,
    league_rank: int,
    biggest_need_score: float,
) -> tuple[int, int, bool]:
    if timeline == TIMELINE_CHAMPIONSHIP_PUSH:
        firsts = 2 if league_rank <= 3 and biggest_need_score >= 8.0 else 1
        return firsts, 2, True
    if timeline == TIMELINE_CONTENDER:
        firsts = 1 if biggest_need_score >= 8.0 else 0
        return firsts, 2, True
    if timeline == TIMELINE_RETOOL:
        return 0, 2, True
    if timeline == TIMELINE_DEVELOP:
        return 0, 1, False
    return 0, 0, False


def _desired_return_profile(
    timeline: str,
    *,
    biggest_need: str,
) -> str:
    if timeline == TIMELINE_CHAMPIONSHIP_PUSH:
        return f"Immediate-impact {biggest_need.lower()} starter or playoff closer"
    if timeline == TIMELINE_CONTENDER:
        return f"Playoff-caliber {biggest_need.lower()} upgrade"
    if timeline == TIMELINE_RETOOL:
        return f"Younger {biggest_need.lower()} fit or flexible future value"
    if timeline == TIMELINE_DEVELOP:
        return "Young player, draft value, or development-compatible contract"
    return "Future first-equivalent value, young asset, or clean flexibility"


def _eligible_trade_rows(
    decisions: Iterable[FrontOfficePlayerDecision],
) -> list[FrontOfficePlayerDecision]:
    rows = [
        row
        for row in decisions
        if row.asset_policy in {"Consolidate", "Market", "Exit"}
        and row.roster_fit != "Need protection"
        and row.role != "Cornerstone"
    ]
    rows.sort(
        key=lambda row: (
            -row.decision_priority,
            row.strategic_value,
            -row.salary,
            row.player_name,
        )
    )
    return rows


def _package_rationale(
    *,
    timeline: str,
    outgoing: tuple[FrontOfficePlayerDecision, ...],
    biggest_need: str,
    surplus_family: str,
    intent_type: str,
) -> tuple[str, ...]:
    reasons: list[str] = []
    peak_tier = max(
        (row.asset_tier for row in outgoing),
        key=lambda tier: ASSET_TIER_ORDER.get(tier, -1),
    )

    if any(row.roster_fit == "Surplus" for row in outgoing):
        reasons.append(
            f"uses genuine {surplus_family.lower()} depth surplus rather than protected depth"
        )

    if peak_tier in {"Franchise", "Star"}:
        reasons.append(
            f"{peak_tier.lower()} asset requires a premium return and cannot be treated as routine roster churn"
        )
    elif peak_tier == "High-End Starter":
        reasons.append(
            "high-end starter value requires a materially positive return"
        )

    if any(row.asset_policy == "Consolidate" for row in outgoing):
        reasons.append(
            "secondary pieces are explicitly available for consolidation"
        )
    if any(row.asset_policy == "Market" for row in outgoing):
        reasons.append(
            "front office already has these players in a shop/listen posture"
        )

    if timeline in {
        TIMELINE_CHAMPIONSHIP_PUSH,
        TIMELINE_CONTENDER,
    }:
        reasons.append(
            f"return should materially improve the {biggest_need.lower()} rotation"
        )
    elif timeline == TIMELINE_RETOOL:
        reasons.append(
            "return should improve age curve, fit, or future flexibility"
        )
    elif timeline == TIMELINE_DEVELOP:
        reasons.append(
            "return must preserve development minutes and future optionality"
        )
    else:
        reasons.append(
            "return should maximize future asset value rather than current wins"
        )

    return tuple(reasons[:4])


def build_trade_package_intents(
    *,
    team: str,
    timeline: str,
    league_rank: int,
    decisions: Iterable[FrontOfficePlayerDecision],
    biggest_need: str,
    secondary_need: str,
    surplus_family: str,
    biggest_need_score: float,
    financial_posture: str,
    limit: int = 4,
) -> tuple[
    tuple[FrontOfficeTradePackageIntent, ...],
    tuple[str, ...],
    tuple[str, ...],
    int,
    int,
    bool,
    str,
]:
    rows = list(decisions)
    eligible = _eligible_trade_rows(rows)

    tradeable_pool_ids = tuple(row.player_id for row in eligible)
    consolidation_ids = tuple(
        row.player_id
        for row in eligible
        if row.asset_policy == "Consolidate"
    )

    first_budget, second_budget, allow_swap = _draft_spend_budget(
        timeline,
        league_rank=league_rank,
        biggest_need_score=biggest_need_score,
    )
    desired_return = _desired_return_profile(
        timeline,
        biggest_need=biggest_need,
    )

    intents: list[FrontOfficeTradePackageIntent] = []
    seen_packages: set[tuple[str, ...]] = set()

    def add_intent(
        intent_type: str,
        outgoing_rows: Iterable[FrontOfficePlayerDecision],
        *,
        target_family: str,
        return_profile: str,
        firsts: int,
        seconds: int,
        swap: bool,
        priority_bonus: float = 0.0,
    ) -> None:
        outgoing = tuple(outgoing_rows)
        if not outgoing:
            return
        if len(outgoing) > 2:
            return

        ids = tuple(sorted(row.player_id for row in outgoing))
        if ids in seen_packages:
            return

        if any(
            row.asset_policy in {"Protect", "Develop"}
            or row.roster_fit == "Need protection"
            or row.role == "Cornerstone"
            for row in outgoing
        ):
            return

        peak_tier = max(
            (row.asset_tier for row in outgoing),
            key=lambda tier: ASSET_TIER_ORDER.get(tier, -1),
        )

        # Premium assets are never bundled with filler merely to make a package.
        if (
            peak_tier in {"Franchise", "Star"}
            and len(outgoing) > 1
        ):
            return

        required_firsts = 0
        requires_blue_chip = False
        minimum_labels = []

        for row in outgoing:
            label, row_firsts, row_blue_chip = _minimum_return_for_asset_tier(
                row.asset_tier,
                age=row.age,
                timeline=timeline,
                trade_value_score=row.trade_value_score,
                contract_control_score=row.contract_control_score,
            )
            minimum_labels.append(label)
            required_firsts = max(required_firsts, row_firsts)
            requires_blue_chip = requires_blue_chip or row_blue_chip

        minimum_return_label = max(
            minimum_labels,
            key=lambda label: len(label),
        )

        premium_asset = peak_tier in {
            "Franchise",
            "Star",
        }
        if premium_asset:
            if timeline in {
                TIMELINE_DEVELOP,
                TIMELINE_REBUILD,
            }:
                intent_type = "Premium star market"
            elif timeline == TIMELINE_RETOOL:
                intent_type = "Premium asset reshape"
            return_profile = minimum_return_label

        seen_packages.add(ids)

        outgoing_value = round(
            sum(row.strategic_value for row in outgoing),
            2,
        )
        outgoing_salary = round(
            sum(row.salary for row in outgoing),
            2,
        )
        avg_priority = (
            sum(row.decision_priority for row in outgoing)
            / len(outgoing)
        )
        priority = round(
            max(
                0.0,
                min(
                    100.0,
                    avg_priority
                    + priority_bonus
                    + (
                        8.0
                        if premium_asset
                        else 0.0
                    ),
                ),
            ),
            1,
        )

        intents.append(
            FrontOfficeTradePackageIntent(
                intent_id=f"{team}-TPI-{len(intents) + 1:02d}",
                intent_type=intent_type,
                priority=priority,
                outgoing_player_ids=tuple(
                    row.player_id for row in outgoing
                ),
                outgoing_player_names=tuple(
                    row.player_name for row in outgoing
                ),
                outgoing_positions=tuple(
                    row.position for row in outgoing
                ),
                outgoing_value=outgoing_value,
                outgoing_salary=outgoing_salary,
                target_family=target_family,
                return_profile=return_profile,
                draft_first_budget=max(0, int(firsts)),
                draft_second_budget=max(0, int(seconds)),
                allow_pick_swap=bool(swap),
                outgoing_peak_asset_tier=peak_tier,
                required_first_equivalent_return=required_firsts,
                requires_blue_chip_return=requires_blue_chip,
                minimum_return_label=minimum_return_label,
                execution_ready=False,
                rationale=_package_rationale(
                    timeline=timeline,
                    outgoing=outgoing,
                    biggest_need=biggest_need,
                    surplus_family=surplus_family,
                    intent_type=intent_type,
                ),
            )
        )

    consolidate = [
        row
        for row in eligible
        if row.asset_policy == "Consolidate"
    ]
    ordinary_market = [
        row
        for row in eligible
        if row.asset_policy == "Market"
        and row.asset_tier not in {"Franchise", "Star"}
    ]
    premium_market = [
        row
        for row in eligible
        if row.asset_policy == "Market"
        and row.asset_tier in {"Franchise", "Star"}
    ]
    exit_rows = [
        row
        for row in eligible
        if row.asset_policy == "Exit"
    ]

    # Premium assets always receive their own single-player intent first.
    for row in premium_market[:2]:
        add_intent(
            "Premium star market",
            (row,),
            target_family=biggest_need,
            return_profile=row.minimum_return_label,
            firsts=0,
            seconds=0,
            swap=False,
            priority_bonus=10.0,
        )

    if timeline == TIMELINE_CHAMPIONSHIP_PUSH:
        if consolidate:
            add_intent(
                "Championship upgrade",
                consolidate[:2],
                target_family=biggest_need,
                return_profile=desired_return,
                firsts=first_budget,
                seconds=second_budget,
                swap=allow_swap,
                priority_bonus=8.0,
            )
        for row in ordinary_market[:2]:
            add_intent(
                "Secondary asset upgrade",
                (row,),
                target_family=biggest_need,
                return_profile=desired_return,
                firsts=min(1, first_budget),
                seconds=min(1, second_budget),
                swap=allow_swap,
                priority_bonus=2.0,
            )

    elif timeline == TIMELINE_CONTENDER:
        if consolidate:
            add_intent(
                "Targeted playoff upgrade",
                consolidate[:2],
                target_family=biggest_need,
                return_profile=desired_return,
                firsts=first_budget,
                seconds=second_budget,
                swap=allow_swap,
                priority_bonus=6.0,
            )
        for row in ordinary_market[:2]:
            add_intent(
                "Rotation reshape",
                (row,),
                target_family=biggest_need,
                return_profile=desired_return,
                firsts=0,
                seconds=min(1, second_budget),
                swap=False,
                priority_bonus=1.0,
            )

    elif timeline == TIMELINE_RETOOL:
        for row in ordinary_market[:3]:
            add_intent(
                "Younger-fit reshape",
                (row,),
                target_family=biggest_need,
                return_profile=desired_return,
                firsts=0,
                seconds=min(1, second_budget),
                swap=allow_swap,
                priority_bonus=4.0 if row.age >= 29.0 else 0.0,
            )
        if len(ordinary_market) >= 2:
            pair = tuple(
                sorted(
                    ordinary_market[:4],
                    key=lambda row: (
                        row.roster_fit != "Surplus",
                        row.strategic_value,
                        -row.decision_priority,
                    ),
                )[:2]
            )
            add_intent(
                "Two-for-one roster reshape",
                pair,
                target_family=biggest_need,
                return_profile=(
                    f"Clear {biggest_need.lower()} upgrade with a younger age curve"
                ),
                firsts=0,
                seconds=second_budget,
                swap=allow_swap,
                priority_bonus=3.0,
            )

    elif timeline == TIMELINE_DEVELOP:
        veteran_market = [
            row
            for row in ordinary_market
            if row.age >= 27.0
        ]
        for row in veteran_market[:3]:
            add_intent(
                "Veteran-to-future value",
                (row,),
                target_family=secondary_need,
                return_profile=desired_return,
                firsts=0,
                seconds=0,
                swap=False,
                priority_bonus=6.0,
            )
        for row in exit_rows[:1]:
            add_intent(
                "Roster-slot cleanup",
                (row,),
                target_family=secondary_need,
                return_profile="Minimal-return salary/roster-slot flexibility",
                firsts=0,
                seconds=0,
                swap=False,
                priority_bonus=3.0,
            )

    else:
        rebuild_market = [
            row
            for row in ordinary_market
            if row.age >= 26.0
            or row.asset_policy == "Market"
        ]
        for row in rebuild_market[:4]:
            add_intent(
                "Veteran asset liquidation",
                (row,),
                target_family=secondary_need,
                return_profile=desired_return,
                firsts=0,
                seconds=0,
                swap=False,
                priority_bonus=10.0 if row.age >= 29.0 else 5.0,
            )
        if (
            financial_posture == "High salary pressure"
            and exit_rows
        ):
            add_intent(
                "Salary cleanup",
                exit_rows[:1],
                target_family=secondary_need,
                return_profile="Flexibility without attaching premium draft capital",
                firsts=0,
                seconds=0,
                swap=False,
                priority_bonus=7.0,
            )

    intents.sort(
        key=lambda intent: (
            -intent.priority,
            -ASSET_TIER_ORDER.get(
                intent.outgoing_peak_asset_tier,
                -1,
            ),
            intent.intent_type,
            intent.intent_id,
        )
    )

    return (
        tuple(intents[:limit]),
        tradeable_pool_ids,
        consolidation_ids,
        first_budget,
        second_budget,
        allow_swap,
        desired_return,
    )


def build_team_front_office_plan(
    state: Any,
    team: str,
    *,
    controlled_teams: Iterable[str] = (),
    league_median_payroll: float | None = None,
    classification: Mapping[str, Any] | None = None,
    asset_contexts: Mapping[str, AssetMarketContext] | None = None,
) -> TeamFrontOfficePlan:
    resolved = _team(team)
    metrics = _team_base_metrics(state, resolved)
    players = list(metrics["players"])
    resolved_classification = dict(classification or {})
    timeline = _clean(
        resolved_classification.get("timeline")
    ) or classify_timeline(metrics)
    league_rank = int(
        _finite(
            resolved_classification.get("league_rank"),
            0.0,
        )
    )
    league_percentile = _finite(
        resolved_classification.get("league_percentile"),
        0.50,
    )
    competitive_score = _finite(
        resolved_classification.get("competitive_score"),
        metrics.get("strength_score", 0.0),
    )
    direction_rationale = tuple(
        resolved_classification.get(
            "direction_rationale",
            (
                "Single-team fallback classification; league-relative context was not supplied.",
            ),
        )
    )
    roster_construction = team_roster_construction(
        state,
        resolved,
    )
    needs = dict(
        roster_construction["need_scores"]
    )
    surplus_scores = dict(
        roster_construction["surplus_scores"]
    )
    biggest_need = str(
        roster_construction["biggest_need"]
    )
    secondary_need = str(
        roster_construction["secondary_need"]
    )
    surplus_family = str(
        roster_construction["surplus_family"]
    )
    primary_upgrade_need = str(
        roster_construction["primary_upgrade_need"]
    )
    secondary_upgrade_need = str(
        roster_construction["secondary_upgrade_need"]
    )
    depth_surplus_family = str(
        roster_construction["depth_surplus_family"]
    )

    if league_median_payroll is None:
        payrolls = [
            _team_base_metrics(state, other)["known_payroll"]
            for other in sorted(getattr(state, "teams", {}))
            if _team_base_metrics(state, other)["salary_coverage"] >= 0.60
        ]
        league_median_payroll = median(payrolls) if payrolls else 0.0
    financial_posture = _financial_posture(metrics, league_median_payroll)

    decisions: list[FrontOfficePlayerDecision] = []
    for player in players:
        role = _player_role(player)
        retention = _retention_score(
            player,
            role=role,
            timeline=timeline,
            biggest_need=biggest_need,
            need_scores=needs,
            financial_posture=financial_posture,
        )
        value = intrinsic_player_value(player)
        player_id_key = str(
            getattr(player, "player_id", "")
        )
        market_context = (
            dict(asset_contexts or {}).get(player_id_key)
            if asset_contexts is not None
            else None
        )
        if market_context is None:
            market_context = build_asset_market_context(
                player,
                timeline=timeline,
                team=resolved,
            )

        family = position_family(
            getattr(player, "position", "")
        )
        depth_rank = _family_depth_rank(
            player,
            players,
        )
        asset_tier = _asset_tier(
            player,
            role=role,
            strategic_value=value,
            market_context=market_context,
            timeline=timeline,
        )
        premium_market = _premium_market_flag(
            asset_tier,
            age=_age(player),
            timeline=timeline,
            trade_value_score=market_context.trade_value_score,
        )
        minimum_return_label, _, _ = _minimum_return_for_asset_tier(
            asset_tier,
            age=_age(player),
            timeline=timeline,
            market_context=market_context,
        )
        roster_fit = _roster_fit_label(
            family=family,
            depth_rank=depth_rank,
            biggest_need=biggest_need,
            secondary_need=secondary_need,
            family_need=needs.get(family, 0.0),
            family_surplus=surplus_scores.get(family, 0.0),
            role=role,
            overall=_overall(player),
            age=_age(player),
            timeline=timeline,
        )
        market = _market_stance(
            player,
            role=role,
            retention_score=retention,
            timeline=timeline,
            roster_count=len(players),
            family_need=needs.get(family, 0.0),
            family_surplus=surplus_scores.get(family, 0.0),
            depth_rank=depth_rank,
            is_biggest_need=(family == biggest_need),
            need_protection=(roster_fit == "Need protection"),
            asset_tier=asset_tier,
        )
        contract_plan = _contract_plan(
            player,
            retention,
            role,
            timeline,
        )
        asset_policy = _asset_policy(market)
        decision_priority = _decision_priority(
            player,
            role=role,
            market_stance=market,
            contract_plan=contract_plan,
            timeline=timeline,
            biggest_need=biggest_need,
            roster_count=len(players),
        )
        decisions.append(
            FrontOfficePlayerDecision(
                player_id=str(getattr(player, "player_id", "")),
                player_name=_clean(getattr(player, "player_name", getattr(player, "player_id", ""))),
                position=_clean(getattr(player, "position", "UNK")) or "UNK",
                age=round(_age(player), 1),
                overall=round(_overall(player), 1),
                potential=round(_potential(player), 1),
                salary=round(_salary(player), 2),
                years_remaining=_years(player),
                role=role,
                strategic_value=value,
                retention_score=retention,
                contract_plan=contract_plan,
                market_stance=market,
                asset_policy=asset_policy,
                decision_priority=decision_priority,
                position_family=family,
                family_depth_rank=depth_rank,
                roster_fit=roster_fit,
                asset_tier=asset_tier,
                premium_market=premium_market,
                minimum_return_label=minimum_return_label,
                market_value_score=market_context.market_score,
                organizational_value_score=market_context.organizational_score,
                trade_value_score=market_context.trade_value_score,
                market_percentile=market_context.market_percentile,
                age_curve_score=market_context.age_curve_score,
                contract_control_score=market_context.contract_control_score,
                salary_efficiency_score=market_context.salary_efficiency_score,
                availability_score=market_context.availability_score,
                market_context_confidence=market_context.confidence_score,
                rationale=_player_rationale(
                    player,
                    role=role,
                    retention_score=retention,
                    biggest_need=biggest_need,
                    timeline=timeline,
                    financial_posture=financial_posture,
                    market_stance=market,
                ),
            )
        )

    decisions.sort(key=lambda row: (-row.strategic_value, -row.retention_score, row.player_name))
    fa_targets = _free_agent_targets(
        state,
        timeline=timeline,
        biggest_need=biggest_need,
        secondary_need=secondary_need,
        need_scores=needs,
        surplus_scores=surplus_scores,
        financial_posture=financial_posture,
    )

    protected = tuple(
        row.player_id
        for row in decisions
        if row.asset_policy in {"Protect", "Develop"}
    )
    shop = tuple(
        row.player_id
        for row in decisions
        if row.asset_policy == "Market"
    )
    retention = tuple(
        row.player_id
        for row in decisions
        if _contract_is_retention_priority(row.contract_plan)
    )
    development = tuple(
        row.player_id
        for row in decisions
        if row.asset_policy == "Develop"
        or row.role == "Development"
    )
    cut = tuple(
        row.player_id
        for row in decisions
        if row.asset_policy == "Exit"
    )

    (
        trade_package_intents,
        tradeable_player_pool_ids,
        consolidation_candidate_ids,
        draft_first_budget,
        draft_second_budget,
        allow_pick_swap,
        desired_return_profile,
    ) = build_trade_package_intents(
        team=resolved,
        timeline=timeline,
        league_rank=league_rank,
        decisions=decisions,
        biggest_need=biggest_need,
        secondary_need=secondary_need,
        surplus_family=surplus_family,
        biggest_need_score=needs.get(biggest_need, 0.0),
        financial_posture=financial_posture,
    )

    controlled = {_team(value) for value in controlled_teams}
    behavior = behavior_profile(timeline)
    return TeamFrontOfficePlan(
        version=CPU_FRONT_OFFICE_VERSION,
        model_version=CPU_FRONT_OFFICE_MODEL_VERSION,
        season_label=_clean(getattr(getattr(state, "settings", None), "season_label", "")),
        team=resolved,
        cpu_managed=resolved not in controlled,
        timeline=timeline,
        timeline_label=TIMELINE_LABELS[timeline],
        league_rank=league_rank,
        league_percentile=round(league_percentile, 4),
        competitive_score=round(competitive_score, 2),
        direction_rationale=direction_rationale,
        win_pct=round(_finite(metrics["win_pct"]), 4),
        strength_score=round(_finite(metrics["strength_score"]), 2),
        average_age=round(_finite(metrics["average_age"]), 2),
        top_five_overall=round(_finite(metrics["top_five"]), 2),
        top_three_overall=round(_finite(metrics["top_three"]), 2),
        rotation_quality=round(_finite(metrics["rotation"]), 2),
        young_core_score=round(_finite(metrics["young_core_score"]), 2),
        roster_count=len(players),
        known_payroll=round(_finite(metrics["known_payroll"]), 2),
        salary_coverage=round(_finite(metrics["salary_coverage"]), 4),
        financial_posture=financial_posture,
        behavior_label=behavior.label,
        behavior_summary=behavior.summary,
        win_now_bias=behavior.win_now_bias,
        youth_bias=behavior.youth_bias,
        future_asset_bias=behavior.future_asset_bias,
        consolidation_bias=behavior.consolidation_bias,
        salary_discipline=behavior.salary_discipline,
        veteran_liquidity=behavior.veteran_liquidity,
        free_agent_strategy=_free_agent_strategy(timeline),
        biggest_need=biggest_need,
        secondary_need=secondary_need,
        surplus_family=surplus_family,
        primary_upgrade_need=primary_upgrade_need,
        secondary_upgrade_need=secondary_upgrade_need,
        depth_surplus_family=depth_surplus_family,
        roster_balance_score=float(
            roster_construction[
                "roster_balance_score"
            ]
        ),
        need_scores=dict(needs),
        surplus_scores=dict(surplus_scores),
        position_profiles={
            family: dict(values)
            for family, values in roster_construction[
                "profiles"
            ].items()
        },
        draft_posture=_draft_posture(timeline),
        trade_goal=_trade_goal(timeline, biggest_need),
        objectives=_objectives(
            timeline=timeline,
            biggest_need=biggest_need,
            financial_posture=financial_posture,
            decisions=decisions,
            fa_targets=fa_targets,
        ),
        protected_player_ids=protected,
        shop_player_ids=shop,
        retention_priority_ids=retention,
        development_player_ids=development,
        cut_candidate_ids=cut,
        tradeable_player_pool_ids=tradeable_player_pool_ids,
        consolidation_candidate_ids=consolidation_candidate_ids,
        draft_first_budget=draft_first_budget,
        draft_second_budget=draft_second_budget,
        allow_pick_swap=allow_pick_swap,
        desired_return_profile=desired_return_profile,
        trade_package_intents=trade_package_intents,
        player_decisions=tuple(decisions),
        free_agent_targets=fa_targets,
        risk_flags=_risk_flags(
            players,
            need_scores=needs,
            average_age=_finite(metrics["average_age"]),
            salary_coverage=_finite(metrics["salary_coverage"]),
            financial_posture=financial_posture,
        ),
    )


def build_league_front_office_plan(
    state: Any,
    *,
    controlled_teams: Iterable[str] = (),
) -> LeagueFrontOfficePlan:
    before = front_office_state_fingerprint(state)
    teams = sorted(_team(team) for team in getattr(state, "teams", {}) if _team(team))
    metrics_by_team = {
        team: _team_base_metrics(state, team)
        for team in teams
    }
    classifications = _league_relative_classifications(
        metrics_by_team
    )
    team_timelines = {
        team: str(
            classifications.get(team, {}).get(
                "timeline",
                TIMELINE_RETOOL,
            )
        )
        for team in teams
    }
    asset_contexts = build_league_asset_market_contexts(
        state,
        team_timelines=team_timelines,
    )

    payrolls = [
        _finite(metrics["known_payroll"])
        for metrics in metrics_by_team.values()
        if _finite(metrics["salary_coverage"]) >= 0.60 and _finite(metrics["known_payroll"]) > 0.0
    ]
    median_payroll = median(payrolls) if payrolls else 0.0

    plans = {
        team: build_team_front_office_plan(
            state,
            team,
            controlled_teams=controlled_teams,
            league_median_payroll=median_payroll,
            classification=classifications.get(team),
            asset_contexts=asset_contexts,
        )
        for team in teams
    }
    after = front_office_state_fingerprint(state)
    if before != after:
        raise RuntimeError("CPU Front Office planning unexpectedly mutated the live franchise state.")

    timeline_counts = {timeline: 0 for timeline in TIMELINE_LABELS}
    for plan in plans.values():
        timeline_counts[plan.timeline] = timeline_counts.get(plan.timeline, 0) + 1

    roster_pressure = tuple(sorted(team for team, plan in plans.items() if plan.roster_count > 15))
    contract_decisions = sum(
        1
        for plan in plans.values()
        for row in plan.player_decisions
        if row.contract_plan not in {"Keep under contract"}
    )
    shop_candidates = sum(len(plan.shop_player_ids) for plan in plans.values())
    trade_intent_count = sum(
        len(plan.trade_package_intents)
        for plan in plans.values()
    )
    teams_with_trade_intents = tuple(
        sorted(
            team
            for team, plan in plans.items()
            if plan.trade_package_intents
        )
    )

    controlled = {_team(value) for value in controlled_teams}
    return LeagueFrontOfficePlan(
        version=CPU_FRONT_OFFICE_VERSION,
        model_version=CPU_FRONT_OFFICE_MODEL_VERSION,
        season_label=_clean(getattr(getattr(state, "settings", None), "season_label", "")),
        state_fingerprint=before,
        teams=plans,
        timeline_counts=timeline_counts,
        cpu_team_count=sum(1 for team in teams if team not in controlled),
        user_team_count=sum(1 for team in teams if team in controlled),
        roster_pressure_teams=roster_pressure,
        contract_decision_count=contract_decisions,
        shop_candidate_count=shop_candidates,
        trade_intent_count=trade_intent_count,
        teams_with_trade_intents=teams_with_trade_intents,
    )


def plan_to_dict(plan: TeamFrontOfficePlan) -> dict[str, Any]:
    return asdict(plan)


def league_plan_to_dict(plan: LeagueFrontOfficePlan) -> dict[str, Any]:
    return asdict(plan)


def team_plan_rows(league_plan: LeagueFrontOfficePlan) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for team, plan in sorted(league_plan.teams.items()):
        rows.append({
            "Team": team,
            "Control": "CPU" if plan.cpu_managed else "User",
            "Direction": plan.timeline_label,
            "League Rank": plan.league_rank,
            "Competitive Score": round(plan.competitive_score, 1),
            "Win %": round(plan.win_pct, 3),
            "Top-5 OVR": round(plan.top_five_overall, 1),
            "Core Age": round(plan.average_age, 1),
            "Biggest Need": plan.biggest_need,
            "Financial Posture": plan.financial_posture,
            "Roster": plan.roster_count,
            "Retain": len(plan.retention_priority_ids),
            "Shop": len(plan.shop_player_ids),
            "Develop": len(plan.development_player_ids),
            "Cuts": len(plan.cut_candidate_ids),
            "Trade Intents": len(plan.trade_package_intents),
            "First Budget": plan.draft_first_budget,
            "Second Budget": plan.draft_second_budget,
            "Trade Goal": plan.trade_goal,
        })
    return rows
