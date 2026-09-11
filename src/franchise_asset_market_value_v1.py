from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

ASSET_MARKET_CONTEXT_VERSION = "franchise-asset-market-context-v1.0.2-2026-08-13"
ASSET_MARKET_MODEL_VERSION = "age-upside-control-salary-availability-v1.0.2-2026-08-13"

ASSET_TIER_ORDER = {
    "Filler": 0,
    "Rotation": 1,
    "Development": 2,
    "Starter": 3,
    "High-End Starter": 4,
    "Star": 5,
    "Franchise": 6,
}


@dataclass(frozen=True)
class AssetMarketContext:
    player_id: str
    player_name: str
    team: str
    age: float
    overall: float
    potential: float
    future_outlook: float
    salary: float
    years_remaining: int | None
    current_impact_score: float
    upside_score: float
    age_curve_score: float
    contract_control_score: float
    salary_efficiency_score: float
    availability_score: float
    confidence_score: float
    market_score: float
    organizational_score: float
    tier_score: float
    trade_value_score: float
    asset_tier: str
    market_percentile: float


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    if number != number or number in (float("inf"), float("-inf")):
        return float(default)
    return number


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _contract(source: Any) -> Any:
    if isinstance(source, Mapping):
        return source.get("contract")
    return getattr(source, "contract", None)


def _get(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        if name in source:
            return source.get(name)
        contract = source.get("contract")
        if isinstance(contract, Mapping) and name in contract:
            return contract.get(name)
        return default
    if hasattr(source, name):
        return getattr(source, name)
    contract = getattr(source, "contract", None)
    if contract is not None and hasattr(contract, name):
        return getattr(contract, name)
    return default


def _player_id(source: Any) -> str:
    return _clean(
        _get(source, "player_id", "")
        or _get(source, "id", "")
    )


def _player_name(source: Any) -> str:
    return _clean(
        _get(source, "player_name", "")
        or _get(source, "name", "")
        or _player_id(source)
    )


def _overall(source: Any) -> float:
    return _finite(
        _get(
            source,
            "overall_rating",
            _get(source, "overall", 60.0),
        ),
        60.0,
    )


def _potential(source: Any) -> float:
    overall = _overall(source)
    return _finite(
        _get(
            source,
            "potential_rating",
            _get(source, "potential", overall),
        ),
        overall,
    )


def _future(source: Any) -> float:
    potential = _potential(source)
    return _finite(
        _get(
            source,
            "future_outlook_rating",
            _get(source, "future_outlook", potential),
        ),
        potential,
    )


def _age(source: Any) -> float:
    return _finite(_get(source, "age", 27.0), 27.0)


def _salary(source: Any) -> float:
    return max(
        0.0,
        _finite(_get(source, "salary", 0.0), 0.0),
    )


def _years(source: Any) -> int | None:
    value = _get(source, "years_remaining", None)
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _contract_status(source: Any) -> str:
    return _clean(_get(source, "status", "")).lower()


def _career_status(source: Any) -> str:
    for name in (
        "career_status",
        "career_intent",
        "retirement_status",
    ):
        value = _clean(_get(source, name, "")).lower()
        if value:
            return value
    return "active"


def _availability_label(source: Any) -> str:
    for name in (
        "availability",
        "availability_status",
        "injury_status",
        "medical_status",
        "health_status",
    ):
        value = _clean(_get(source, name, "")).lower()
        if value:
            return value
    return ""


def _age_curve(age: float) -> float:
    points = (
        (19.0, 100.0),
        (21.0, 100.0),
        (23.0, 98.0),
        (24.0, 95.0),
        (25.0, 91.0),
        (26.0, 86.0),
        (27.0, 80.0),
        (28.0, 73.0),
        (29.0, 66.0),
        (30.0, 58.0),
        (31.0, 49.0),
        (32.0, 41.0),
        (33.0, 33.0),
        (34.0, 26.0),
        (35.0, 20.0),
        (36.0, 14.0),
        (38.0, 8.0),
        (40.0, 4.0),
    )
    if age <= points[0][0]:
        return points[0][1]
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        if age <= x2:
            t = (age - x1) / max(0.01, x2 - x1)
            return y1 + t * (y2 - y1)
    return 3.0


def _control_score(source: Any) -> tuple[float, int | None, float]:
    years = _years(source)
    status = _contract_status(source)
    confidence = 100.0

    if years is None:
        score = 50.0
        confidence = 58.0
    elif years <= 0:
        score = 12.0
    elif years == 1:
        score = 34.0
    elif years == 2:
        score = 58.0
    elif years == 3:
        score = 78.0
    else:
        score = 92.0

    if "rfa" in status:
        score = min(100.0, score + 8.0)
    elif "ufa" in status or "free" in status:
        score = min(score, 12.0)

    return _clamp(score), years, confidence


def _salary_efficiency(
    overall: float,
    salary: float,
) -> tuple[float, float]:
    if salary <= 0.0:
        return 55.0, 55.0

    expected_millions = _clamp(
        4.0 + max(0.0, overall - 72.0) * 2.5,
        3.0,
        60.0,
    )
    actual_millions = salary / 1_000_000.0
    score = 55.0 + (expected_millions - actual_millions) * 1.40
    return _clamp(score), 100.0


def _availability_score(source: Any) -> tuple[float, float]:
    label = _availability_label(source)
    score = 100.0
    confidence = 45.0 if not label else 78.0

    if label:
        if any(token in label for token in ("retired", "inactive")):
            score = 15.0
        elif any(
            token in label
            for token in (
                "out",
                "injured",
                "injury reserve",
                "ir",
            )
        ):
            score = 64.0
        elif any(
            token in label
            for token in (
                "day_to_day",
                "day-to-day",
                "questionable",
                "doubtful",
                "limited",
            )
        ):
            score = 88.0
        elif any(
            token in label
            for token in ("healthy", "available", "active")
        ):
            score = 100.0

    games_remaining = _get(
        source,
        "injury_games_remaining",
        _get(source, "games_remaining_injury", None),
    )
    if games_remaining is not None:
        confidence = max(confidence, 85.0)
        games = max(0.0, _finite(games_remaining, 0.0))
        score -= min(28.0, games * 2.0)

    durability = _get(
        source,
        "durability_rating",
        _get(source, "durability", None),
    )
    if durability is not None:
        confidence = max(confidence, 80.0)
        d = _finite(durability, 75.0)
        if 0.0 <= d <= 1.0:
            d *= 100.0
        score = score * 0.80 + _clamp(d) * 0.20

    return _clamp(score), _clamp(confidence)


def _timeline_adjustment(
    timeline: str,
    *,
    age: float,
    overall: float,
    potential: float,
) -> float:
    timeline = _clean(timeline).lower()
    gap = max(0.0, potential - overall)

    if timeline in {
        "championship_push",
        "championship push",
        "contender",
        "contend",
    }:
        adjustment = min(
            4.0,
            max(0.0, overall - 83.0) * 0.50,
        )
        if age >= 34.0:
            adjustment -= 2.0
        return adjustment

    if timeline == "retool":
        adjustment = 0.0
        if age <= 27.0:
            adjustment += 2.0 + min(1.5, gap * 0.15)
        if age >= 32.0:
            adjustment -= 3.0
        return adjustment

    if timeline in {"develop", "rebuild"}:
        adjustment = 0.0
        if age <= 25.0:
            adjustment += 5.0 + min(2.0, gap * 0.20)
        elif age <= 28.0:
            adjustment += 2.0
        if age >= 30.0:
            adjustment -= min(
                7.0,
                (age - 29.0) * 1.5,
            )
        return adjustment

    return 0.0


def _trade_value_from_market_score(market_score: float) -> float:
    score = _clamp(market_score)
    value = (
        0.014 * score * score
        + 0.55 * score
        - 10.0
    )
    return max(0.0, min(185.0, value))


def build_asset_market_context(
    source: Any,
    *,
    timeline: str = "",
    team: str = "",
) -> AssetMarketContext:
    overall = _overall(source)
    potential = _potential(source)
    future = _future(source)
    age = _age(source)
    salary = _salary(source)

    impact = _clamp(
        (overall - 68.0) / 26.0 * 100.0
    )

    potential_base = _clamp(
        (potential - 72.0) / 22.0 * 100.0
    )
    gap_signal = _clamp(
        max(0.0, potential - overall) * 8.0,
        0.0,
        40.0,
    )
    future_signal = _clamp(
        (future - 74.0) / 20.0 * 100.0
    )
    upside = _clamp(
        0.55 * potential_base
        + 0.25 * gap_signal
        + 0.20 * future_signal
    )

    age_score = _clamp(_age_curve(age))
    control_score, years, control_conf = _control_score(source)
    salary_efficiency, salary_conf = _salary_efficiency(
        overall,
        salary,
    )
    availability, availability_conf = _availability_score(source)

    market = (
        0.42 * impact
        + 0.22 * upside
        + 0.15 * age_score
        + 0.10 * control_score
        + 0.06 * salary_efficiency
        + 0.05 * availability
    )

    # Scarce elite-young value is intentionally nonlinear.
    if (
        age <= 24.5
        and overall >= 82.0
        and potential >= 90.0
    ):
        market += 8.0
    if age <= 22.5 and potential >= 92.0:
        market += 4.0

    # True prime superstars still separate at the top.
    if overall >= 92.0 and age <= 30.0:
        market += 6.0
    if overall >= 94.0 and age <= 31.0:
        market += 3.0

    # Aging/short-control stars remain good players but lose market value.
    if age >= 33.0:
        market -= min(10.0, (age - 32.0) * 2.0)
    if (
        age >= 31.0
        and years is not None
        and years <= 1
    ):
        market -= 5.0

    career = _career_status(source)
    if "farewell" in career:
        market *= 0.42
    elif "retir" in career or "consider" in career:
        market *= 0.70
    elif "retired" in career:
        market = 0.0

    market = _clamp(market)
    organizational = _clamp(
        market
        + _timeline_adjustment(
            timeline,
            age=age,
            overall=overall,
            potential=potential,
        )
    )
    tier_score = _clamp(
        market
        + 0.35 * (
            organizational - market
        )
    )

    confidence = _clamp(
        0.40 * 100.0
        + 0.22 * control_conf
        + 0.18 * salary_conf
        + 0.20 * availability_conf
    )

    return AssetMarketContext(
        player_id=_player_id(source),
        player_name=_player_name(source),
        team=_clean(team),
        age=round(age, 2),
        overall=round(overall, 2),
        potential=round(potential, 2),
        future_outlook=round(future, 2),
        salary=round(salary, 2),
        years_remaining=years,
        current_impact_score=round(impact, 2),
        upside_score=round(upside, 2),
        age_curve_score=round(age_score, 2),
        contract_control_score=round(control_score, 2),
        salary_efficiency_score=round(salary_efficiency, 2),
        availability_score=round(availability, 2),
        confidence_score=round(confidence, 2),
        market_score=round(market, 2),
        organizational_score=round(organizational, 2),
        tier_score=round(tier_score, 2),
        trade_value_score=round(
            _trade_value_from_market_score(market),
            2,
        ),
        asset_tier="Filler",
        market_percentile=0.0,
    )


def _franchise_gate(context: AssetMarketContext) -> bool:
    elite_young = (
        context.age <= 24.5
        and context.overall >= 82.0
        and context.potential >= 91.0
        and context.market_score >= 86.0
    )
    prime_superstar = (
        context.age <= 31.0
        and context.overall >= 89.0
        and context.market_score >= 82.0
    )
    generational = (
        context.overall >= 93.0
        and context.market_score >= 84.0
    )
    return elite_young or prime_superstar or generational


def _star_gate(context: AssetMarketContext) -> bool:
    elite_young = (
        context.age <= 25.0
        and context.overall >= 80.0
        and context.potential >= 89.0
        and context.market_score >= 69.0
    )
    prime_star = (
        context.overall >= 85.0
        and context.market_score >= 68.0
    )
    legacy_superstar = (
        context.overall >= 91.5
        and context.market_score >= 55.0
    )
    return elite_young or prime_star or legacy_superstar


def _mandatory_star_floor(
    context: AssetMarketContext,
) -> bool:
    # This intentionally matches the validator's basketball definition exactly.
    # If a player is 25 or younger, already 82+ OVR, and carries 90+ POT,
    # he is a premium young asset even if salary/control context trims the raw
    # market score. Those context factors still affect trade value and return
    # floors, but they cannot demote the asset below Star.
    elite_young = (
        context.age <= 25.0
        and context.overall >= 82.0
        and context.potential >= 90.0
    )

    # Age should reduce trade value, not erase the basketball stature of a
    # still-elite current superstar. 91.5 captures Curry's live 91.8 OVR while
    # remaining much stricter than a generic veteran-star threshold.
    legacy_superstar = (
        context.overall >= 91.5
        and context.market_score >= 55.0
    )

    return elite_young or legacy_superstar


def _high_end_gate(context: AssetMarketContext) -> bool:
    return (
        (
            context.overall >= 83.0
            and context.market_score >= 51.0
        )
        or (
            context.age <= 24.5
            and context.potential >= 88.0
            and context.market_score >= 58.0
        )
    )


def _fallback_tier(context: AssetMarketContext) -> str:
    if _franchise_gate(context) and context.market_score >= 88.0:
        return "Franchise"
    if _star_gate(context) and context.market_score >= 74.0:
        return "Star"
    if _high_end_gate(context):
        return "High-End Starter"
    if (
        context.overall >= 79.0
        or context.market_score >= 52.0
    ):
        return "Starter"
    if (
        context.age <= 24.5
        and context.potential >= max(
            82.0,
            context.overall + 4.0,
        )
    ):
        return "Development"
    if context.overall >= 74.0:
        return "Rotation"
    return "Filler"


def calibrate_league_asset_tiers(
    contexts: Mapping[str, AssetMarketContext],
) -> dict[str, AssetMarketContext]:
    if not contexts:
        return {}

    ordered = sorted(
        contexts.items(),
        key=lambda item: (
            -item[1].tier_score,
            -item[1].market_score,
            -item[1].overall,
            item[1].age,
            item[1].player_name,
        ),
    )
    n = len(ordered)
    franchise_cap = max(
        6,
        min(
            12,
            round(n * 0.030),
        ),
    )
    star_total_cap = max(
        franchise_cap + 12,
        min(
            franchise_cap + 30,
            round(n * 0.105),
        ),
    )

    result: dict[str, AssetMarketContext] = {}

    franchise_used = 0
    star_used = 0

    for index, (player_id, context) in enumerate(
        ordered,
        start=1,
    ):
        percentile = (
            1.0
            if n <= 1
            else 1.0 - (index - 1) / (n - 1)
        )

        tier = _fallback_tier(context)

        if (
            franchise_used < franchise_cap
            and _franchise_gate(context)
            and context.age < 33.0
            and (
                index <= franchise_cap
                or context.market_score >= 90.0
            )
        ):
            tier = "Franchise"
            franchise_used += 1
        elif _mandatory_star_floor(context):
            tier = "Star"
            star_used += 1
        elif (
            franchise_used + star_used < star_total_cap
            and _star_gate(context)
            and (
                index <= star_total_cap
                or context.market_score >= 80.0
            )
        ):
            tier = "Star"
            star_used += 1
        elif _high_end_gate(context):
            tier = "High-End Starter"
        elif (
            context.overall >= 79.0
            or context.market_score >= 52.0
        ):
            tier = "Starter"
        elif (
            context.age <= 24.5
            and context.potential >= max(
                82.0,
                context.overall + 4.0,
            )
        ):
            tier = "Development"
        elif context.overall >= 74.0:
            tier = "Rotation"
        else:
            tier = "Filler"

        result[player_id] = replace(
            context,
            asset_tier=tier,
            market_percentile=round(
                _clamp(percentile * 100.0),
                2,
            ),
        )

    return result


def build_league_asset_market_contexts(
    state: Any,
    *,
    team_timelines: Mapping[str, str] | None = None,
) -> dict[str, AssetMarketContext]:
    team_timelines = dict(team_timelines or {})
    players = getattr(state, "players", {}) or {}
    teams = getattr(state, "teams", {}) or {}

    contexts: dict[str, AssetMarketContext] = {}
    for team, team_state in teams.items():
        timeline = team_timelines.get(
            str(team).strip().upper(),
            "",
        )
        for raw_id in tuple(
            getattr(
                team_state,
                "roster_player_ids",
                (),
            )
            or ()
        ):
            player = players.get(raw_id)
            if player is None:
                continue
            player_id = _player_id(player) or str(raw_id)
            contexts[player_id] = build_asset_market_context(
                player,
                timeline=timeline,
                team=str(team).strip().upper(),
            )

    return calibrate_league_asset_tiers(contexts)


def build_trade_row_market_context(
    row: Mapping[str, Any],
    *,
    timeline: str = "",
    team: str = "",
) -> AssetMarketContext:
    # This adapter is intentionally public so Trade Finder can use the exact
    # same valuation context in the next integration slice.
    return build_asset_market_context(
        row,
        timeline=timeline,
        team=team,
    )


def trade_market_value_from_row(
    row: Mapping[str, Any],
    *,
    timeline: str = "",
    team: str = "",
) -> float:
    return build_trade_row_market_context(
        row,
        timeline=timeline,
        team=team,
    ).trade_value_score
