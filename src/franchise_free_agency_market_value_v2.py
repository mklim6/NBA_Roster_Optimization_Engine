from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass, asdict
from typing import Any, Iterable, Mapping

FREE_AGENCY_MARKET_VALUE_CALIBRATION_VERSION = (
    "franchise-free-agency-market-value-calibration-v2.3-veteran-star-balance-2026-09-12"
)

_BASE_ANCHORS = (
    (68.0, 0.008),
    (72.0, 0.012),
    (75.0, 0.022),
    (78.0, 0.040),
    (81.0, 0.070),
    (84.0, 0.115),
    (87.0, 0.175),
    (90.0, 0.245),
    (94.0, 0.305),
    (99.0, 0.350),
)

_EXPECTED_IMPACT_ANCHORS = (
    (68.0, 12.0),
    (72.0, 15.0),
    (75.0, 18.0),
    (78.0, 20.5),
    (81.0, 23.0),
    (84.0, 25.5),
    (87.0, 28.5),
    (90.0, 32.0),
    (94.0, 36.0),
    (99.0, 40.0),
)


@dataclass(frozen=True)
class MarketValueBreakdownV2:
    version: str
    player_id: str
    salary_cap: float
    overall: float
    age: float | None
    potential: float | None
    base_rating_reference: float
    young_upside_factor: float
    age_risk_factor: float
    medical_risk_factor: float
    medical_risk_tier: str
    availability_rating: float | None
    durability: float | None
    recent_injuries_suffered: int
    medical_games_missed: int
    multi_season_availability_rate: float | None
    production_factor: float
    efficiency_factor: float
    availability_factor: float
    recent_form_factor: float
    evidence_games: int
    evidence_minutes: float
    season_impact_per36: float | None
    recent_impact_per36: float | None
    true_shooting: float | None
    availability_rate: float | None
    performance_adjusted_reference: float
    prior_salary: float | None
    prior_salary_weight: float
    bounded_prior_salary: float | None
    pre_clip_reference: float
    minimum_salary_floor: float | None
    maximum_legal_salary: float | None
    final_reference: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _clamp(value: float, low: float, high: float) -> float:
    return max(float(low), min(float(high), float(value)))


def _interp(value: float, anchors: Iterable[tuple[float, float]]) -> float:
    rows = tuple((float(x), float(y)) for x, y in anchors)
    if value <= rows[0][0]:
        return rows[0][1]
    if value >= rows[-1][0]:
        return rows[-1][1]
    for (x0, y0), (x1, y1) in zip(rows, rows[1:]):
        if x0 <= value <= x1:
            share = (value - x0) / (x1 - x0)
            return y0 + share * (y1 - y0)
    return rows[-1][1]


def base_rating_reference_v1(player: Any, salary_cap: float) -> tuple[float, float]:
    """Return the original rating curve and its retained young-upside factor."""
    overall = _finite(getattr(player, "overall_rating", None)) or 72.0
    pct = _interp(overall, _BASE_ANCHORS)
    potential = _finite(getattr(player, "potential_rating", None))
    age = _finite(getattr(player, "age", None))
    upside = 1.0
    if potential is not None and age is not None and age <= 25 and potential > overall:
        upside = 1.0 + min(0.12, max(0.0, potential - overall) * 0.012)
    return float(salary_cap) * pct * upside, upside


def age_risk_factor_v2(player: Any) -> float:
    """Age discount with no superstar immunity.

    Talent already lives in the OVR-based reference. An elite rating should not
    erase the contract risk of being 35-40 years old in a long-term franchise.
    """
    age = _finite(getattr(player, "age", None))
    if age is None or age <= 30:
        base = 1.0
    elif age <= 31:
        base = 0.995
    elif age <= 32:
        base = 0.990
    elif age <= 33:
        base = 0.975
    elif age <= 34:
        base = 0.950
    elif age <= 35:
        base = 0.920
    elif age <= 36:
        base = 0.880
    elif age <= 37:
        base = 0.840
    elif age <= 38:
        base = 0.800
    elif age <= 39:
        base = 0.760
    elif age <= 40:
        base = 0.720
    else:
        base = 0.680
    return round(base, 6)


def _player_availability_rating(player: Any) -> float | None:
    ratings = getattr(player, "skill_ratings", {}) or {}
    value = None
    if isinstance(ratings, Mapping):
        value = _finite(ratings.get("availability_rating"))
    if value is None:
        value = _finite(getattr(player, "availability_rating", None))
    return _clamp(value, 0.0, 100.0) if value is not None else None


def _health_profile(state: Any, player_id: str) -> Any | None:
    profiles = getattr(state, "injury_fatigue_profiles", {}) or {}
    return profiles.get(player_id) if isinstance(profiles, Mapping) else None


def _season_availability_samples(state: Any, player_id: str, *, limit: int = 4) -> list[float]:
    """Return recent regular-season availability across current + archives.

    This survives long-term franchise play because completed SeasonArchive rows
    retain player totals and standings even after live health profiles reset.
    """
    samples: list[float] = []

    def add_sample(totals_map: Any, standings: Any) -> None:
        if not isinstance(totals_map, Mapping) or not isinstance(standings, Mapping):
            return
        totals = totals_map.get(player_id)
        if totals is None:
            return
        games = _games_played(totals)
        team_games = _league_team_games(standings)
        if team_games >= 40 and games >= 1:
            samples.append(_clamp(games / max(team_games, 1), 0.0, 1.0))

    add_sample(
        getattr(state, "player_season_totals", {}) or {},
        getattr(state, "standings", {}) or {},
    )
    for archive in reversed(list(getattr(state, "season_history", ()) or ())):
        if len(samples) >= max(1, int(limit)):
            break
        add_sample(
            getattr(archive, "player_season_totals", {}) or {},
            getattr(archive, "standings", {}) or {},
        )
    return samples[: max(1, int(limit))]


def medical_risk_adjustment_v2_1(state: Any, player: Any) -> dict[str, Any]:
    """Age-sensitive medical discount using persistent and simulated evidence.

    Evidence sources, in order of durability across a franchise save:
    - availability_rating: pre-franchise / player-profile availability signal,
    - archived multi-season games played,
    - current injury-fatigue durability and injury counters.

    The adjustment is intentionally meaningful after age 33, but V2.3 avoids
    charging the player twice for the same age risk. Age is handled by the
    separate age curve; this function prices the severity of durable medical
    evidence. A single minor injury still does not crush a young player's value.
    """
    player_id = _clean(getattr(player, "player_id", ""))
    age = _finite(getattr(player, "age", None))
    availability_rating = _player_availability_rating(player)
    profile = _health_profile(state, player_id)
    durability = _finite(getattr(profile, "durability", None)) if profile is not None else None
    injuries = int(max(0, _finite(getattr(profile, "injuries_suffered", 0)) or 0)) if profile is not None else 0
    missed = int(max(0, _finite(getattr(profile, "season_games_missed", 0)) or 0)) if profile is not None else 0

    samples = _season_availability_samples(state, player_id, limit=4)
    multi_rate = (sum(samples) / len(samples)) if samples else None

    # Risk strength is a 0-1 presentation/calibration score, not a medical
    # diagnosis. Each source can independently surface established risk.
    components: list[float] = []
    if availability_rating is not None:
        components.append(_clamp((82.0 - availability_rating) / 30.0, 0.0, 1.0))
    if durability is not None:
        components.append(_clamp((0.92 - durability) / 0.24, 0.0, 1.0))
    if multi_rate is not None:
        components.append(_clamp((0.90 - multi_rate) / 0.35, 0.0, 1.0))
    if missed > 0:
        components.append(_clamp(missed / 24.0, 0.0, 1.0))
    if injuries > 0:
        components.append(_clamp(injuries / 3.0, 0.0, 1.0))

    risk_strength = max(components) if components else 0.0
    # For veteran market pricing, persistent availability below 90 is treated
    # as meaningful history evidence. This is deliberately stricter than the
    # in-season injury engine: a 34+ free agent should not erase long-run
    # durability concern merely by surviving one healthy simulated season.
    veteran_profile_history = bool(
        age is not None
        and age >= 34.0
        and availability_rating is not None
        and availability_rating < 90.0
    )
    any_history = bool(
        injuries > 0
        or missed > 0
        or veteran_profile_history
        or (availability_rating is not None and availability_rating < 72.0)
        or (durability is not None and durability < 0.84)
        or (multi_rate is not None and multi_rate < 0.85)
    )

    # Younger players can recover market value. The aggressive interaction is
    # reserved for 34+ players, matching the long-term franchise objective.
    factor = 1.0
    tier = "none"
    if age is not None and age >= 34.0 and any_history:
        # Long-term franchise pricing: once a veteran has meaningful medical
        # history, downside risk compounds quickly with age. The player's OVR
        # still drives the starting reference, but teams no longer pay near-max
        # AAV simply because the current-season performance remained elite.
        # V2.3 balance pass:
        #
        # Age risk is already applied separately by age_risk_factor_v2(). The
        # V2.2 age-indexed medical table double-counted aging and pushed still-
        # productive veteran stars too far toward minimum/MLE territory.
        #
        # Medical history remains a major independent discount, but severity
        # now drives this multiplier. Age compounds naturally through the
        # separate age factor:
        #
        #   age 35 + history  -> 0.92 * 0.70 = 0.644 combined
        #   age 36 + severe   -> 0.88 * 0.54 = 0.475 combined
        #   age 38 + history  -> 0.80 * 0.70 = 0.560 combined
        #
        # That is still a substantial long-term franchise penalty while
        # preserving realistic value for elite veterans who remain productive.
        if risk_strength >= 0.55:
            tier = "severe"
            factor = 0.54
        elif risk_strength >= 0.35:
            tier = "moderate"
            factor = 0.62
        else:
            tier = "history"
            factor = 0.70
    elif age is not None and age >= 34.0 and risk_strength >= 0.25:
        # Some risk evidence without crossing the explicit history thresholds.
        tier = "watch"
        factor = 0.94
    elif age is not None and age < 34.0 and any_history and risk_strength >= 0.55:
        tier = "younger_high_risk"
        factor = 0.94

    return {
        "factor": round(_clamp(factor, 0.32, 1.0), 6),
        "tier": tier,
        "risk_strength": round(risk_strength, 6),
        "availability_rating": round(availability_rating, 3) if availability_rating is not None else None,
        "durability": round(durability, 4) if durability is not None else None,
        "injuries_suffered": injuries,
        "medical_games_missed": missed,
        "multi_season_availability_rate": round(multi_rate, 6) if multi_rate is not None else None,
    }


def _games_played(totals: Any) -> int:
    try:
        return max(0, int(getattr(totals, "games_played", 0) or 0))
    except (TypeError, ValueError):
        return 0


def _minutes(totals: Any) -> float:
    return max(0.0, _finite(getattr(totals, "minutes", 0.0)) or 0.0)


def _latest_season_context(state: Any, player_id: str) -> tuple[Any | None, Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    current_totals = getattr(state, "player_season_totals", {}) or {}
    totals = current_totals.get(player_id) if isinstance(current_totals, Mapping) else None
    if totals is not None and _games_played(totals) > 0:
        return (
            totals,
            getattr(state, "standings", {}) or {},
            getattr(state, "completed_games", {}) or {},
            getattr(state, "schedule", {}) or {},
        )

    history = list(getattr(state, "season_history", ()) or ())
    for archive in reversed(history):
        archive_totals = getattr(archive, "player_season_totals", {}) or {}
        candidate = archive_totals.get(player_id) if isinstance(archive_totals, Mapping) else None
        if candidate is not None and _games_played(candidate) > 0:
            return (
                candidate,
                getattr(archive, "standings", {}) or {},
                getattr(archive, "completed_games", {}) or {},
                getattr(archive, "schedule", {}) or {},
            )
    return None, {}, {}, {}


def _league_team_games(standings: Mapping[str, Any]) -> int:
    best = 0
    for standing in standings.values():
        wins = int(_finite(getattr(standing, "wins", 0)) or 0)
        losses = int(_finite(getattr(standing, "losses", 0)) or 0)
        best = max(best, wins + losses)
    return best


def _per36(totals: Any, field: str) -> float:
    minutes = _minutes(totals)
    if minutes <= 0:
        return 0.0
    value = _finite(getattr(totals, field, 0.0)) or 0.0
    return value * 36.0 / minutes


def _impact_per36(totals: Any) -> float | None:
    minutes = _minutes(totals)
    if minutes <= 0:
        return None
    return (
        _per36(totals, "points")
        + 0.55 * _per36(totals, "rebounds")
        + 0.70 * _per36(totals, "assists")
        + 1.40 * _per36(totals, "steals")
        + 1.35 * _per36(totals, "blocks")
        - 0.60 * _per36(totals, "turnovers")
    )


def _true_shooting(totals: Any) -> float | None:
    points = _finite(getattr(totals, "points", None))
    fga = _finite(getattr(totals, "field_goals_attempted", None))
    fta = _finite(getattr(totals, "free_throws_attempted", None))
    if points is None or fga is None or fta is None:
        return None
    denom = 2.0 * (fga + 0.44 * fta)
    if denom < 80.0:
        return None
    return points / denom


@dataclass
class _RecentTotals:
    games_played: int = 0
    minutes: float = 0.0
    points: float = 0.0
    rebounds: float = 0.0
    assists: float = 0.0
    steals: float = 0.0
    blocks: float = 0.0
    turnovers: float = 0.0
    field_goals_made: float = 0.0
    field_goals_attempted: float = 0.0
    three_pointers_made: float = 0.0
    three_pointers_attempted: float = 0.0
    free_throws_made: float = 0.0
    free_throws_attempted: float = 0.0


_RECENT_TOTAL_FIELDS = (
    "minutes", "points", "rebounds", "assists", "steals", "blocks",
    "turnovers", "field_goals_made", "field_goals_attempted",
    "three_pointers_made", "three_pointers_attempted",
    "free_throws_made", "free_throws_attempted",
)
_RECENT_CONTEXT_INDEX_CACHE_MAX = 16
_RECENT_CONTEXT_INDEX_CACHE: OrderedDict[
    tuple[int, int, int, int],
    tuple[
        Mapping[str, Any],
        Mapping[str, Any],
        dict[str, tuple[Any, ...]],
    ],
] = OrderedDict()
_RECENT_CONTEXT_INDEX_CACHE_BUILDS = 0
_RECENT_CONTEXT_INDEX_CACHE_HITS = 0


def _recent_context_cache_key(
    completed_games: Mapping[str, Any],
    schedule: Mapping[str, Any],
) -> tuple[int, int, int, int]:
    return (
        id(completed_games),
        len(completed_games),
        id(schedule),
        len(schedule),
    )


def _build_recent_box_index(
    completed_games: Mapping[str, Any],
    schedule: Mapping[str, Any],
) -> dict[str, tuple[Any, ...]]:
    """Index completed-game box scores once for repeated market valuation.

    The old implementation scanned the complete league game history once per
    player valuation. CPU Free Agency can value the same completed season tens
    of thousands of times, making that scan the dominant market-value cost.

    Preserve the exact old ordering semantics:
      * completed-game insertion order supplies the fallback day;
      * scheduled day_index wins when present/non-zero;
      * duplicate rows for one player in one game use the first box only;
      * recent rows sort by (day, game_id) descending.
    """
    rows_by_player: dict[str, list[tuple[int, str, Any]]] = {}

    for order, (game_id, game) in enumerate(completed_games.items()):
        day = order
        scheduled = schedule.get(game_id) if isinstance(schedule, Mapping) else None
        if scheduled is not None:
            try:
                day = int(getattr(scheduled, "day_index", order) or order)
            except (TypeError, ValueError):
                day = order

        seen_in_game: set[str] = set()
        for box in tuple(getattr(game, "player_box_scores", ()) or ()):
            player_id = _clean(getattr(box, "player_id", ""))
            if player_id in seen_in_game:
                continue
            seen_in_game.add(player_id)
            rows_by_player.setdefault(player_id, []).append(
                (day, str(game_id), box)
            )

    result: dict[str, tuple[Any, ...]] = {}
    for player_id, rows in rows_by_player.items():
        rows.sort(key=lambda item: (item[0], item[1]), reverse=True)
        result[player_id] = tuple(row[2] for row in rows)
    return result


def _recent_box_index(
    completed_games: Mapping[str, Any],
    schedule: Mapping[str, Any],
) -> dict[str, tuple[Any, ...]]:
    global _RECENT_CONTEXT_INDEX_CACHE_BUILDS
    global _RECENT_CONTEXT_INDEX_CACHE_HITS

    key = _recent_context_cache_key(completed_games, schedule)
    cached = _RECENT_CONTEXT_INDEX_CACHE.get(key)
    if cached is not None:
        cached_completed, cached_schedule, index = cached
        # Hold and verify strong object references so Python id reuse can never
        # make an unrelated game universe hit this cache entry.
        if (
            cached_completed is completed_games
            and cached_schedule is schedule
        ):
            _RECENT_CONTEXT_INDEX_CACHE.move_to_end(key)
            _RECENT_CONTEXT_INDEX_CACHE_HITS += 1
            return index
        _RECENT_CONTEXT_INDEX_CACHE.pop(key, None)

    index = _build_recent_box_index(completed_games, schedule)
    _RECENT_CONTEXT_INDEX_CACHE[key] = (
        completed_games,
        schedule,
        index,
    )
    _RECENT_CONTEXT_INDEX_CACHE.move_to_end(key)
    _RECENT_CONTEXT_INDEX_CACHE_BUILDS += 1

    while len(_RECENT_CONTEXT_INDEX_CACHE) > _RECENT_CONTEXT_INDEX_CACHE_MAX:
        _RECENT_CONTEXT_INDEX_CACHE.popitem(last=False)
    return index


def _recent_totals_cache_report() -> dict[str, int]:
    return {
        "entries": len(_RECENT_CONTEXT_INDEX_CACHE),
        "builds": int(_RECENT_CONTEXT_INDEX_CACHE_BUILDS),
        "hits": int(_RECENT_CONTEXT_INDEX_CACHE_HITS),
        "max_entries": int(_RECENT_CONTEXT_INDEX_CACHE_MAX),
    }


def _clear_recent_totals_cache() -> None:
    global _RECENT_CONTEXT_INDEX_CACHE_BUILDS
    global _RECENT_CONTEXT_INDEX_CACHE_HITS

    _RECENT_CONTEXT_INDEX_CACHE.clear()
    _RECENT_CONTEXT_INDEX_CACHE_BUILDS = 0
    _RECENT_CONTEXT_INDEX_CACHE_HITS = 0


def _recent_totals(
    player_id: str,
    completed_games: Mapping[str, Any],
    schedule: Mapping[str, Any],
    limit: int = 10,
) -> Any | None:
    boxes = _recent_box_index(completed_games, schedule).get(player_id, ())
    boxes = boxes[: max(1, int(limit))]
    if not boxes:
        return None

    result = _RecentTotals(games_played=len(boxes))
    for field in _RECENT_TOTAL_FIELDS:
        setattr(
            result,
            field,
            sum(float(getattr(box, field, 0) or 0) for box in boxes),
        )
    return result


def production_adjustments_v2(state: Any, player: Any) -> dict[str, Any]:
    player_id = _clean(getattr(player, "player_id", ""))
    totals, standings, completed, schedule = _latest_season_context(state, player_id)
    if totals is None:
        return {
            "production_factor": 1.0,
            "efficiency_factor": 1.0,
            "availability_factor": 1.0,
            "recent_form_factor": 1.0,
            "games": 0,
            "minutes": 0.0,
            "season_impact": None,
            "recent_impact": None,
            "true_shooting": None,
            "availability_rate": None,
        }

    games = _games_played(totals)
    minutes = _minutes(totals)
    overall = _finite(getattr(player, "overall_rating", None)) or 72.0
    impact = _impact_per36(totals)
    expected = _interp(overall, _EXPECTED_IMPACT_ANCHORS)

    if impact is None or minutes < 300.0 or games < 8:
        production_factor = 1.0
    else:
        relative = impact / max(expected, 1.0) - 1.0
        production_factor = 1.0 + _clamp(relative * 0.10, -0.040, 0.040)

    ts = _true_shooting(totals)
    efficiency_factor = 1.0
    if ts is not None and minutes >= 300.0:
        efficiency_factor = 1.0 + _clamp((ts - 0.575) * 0.18, -0.0125, 0.0125)

    team_games = _league_team_games(standings)
    availability_rate = games / team_games if team_games > 0 else None
    availability_factor = 1.0
    if availability_rate is not None and team_games >= 40 and games >= 8:
        if availability_rate < 0.35:
            availability_factor = 0.965
        elif availability_rate < 0.50:
            availability_factor = 0.980
        elif availability_rate < 0.70:
            availability_factor = 0.992
        elif availability_rate >= 0.90:
            availability_factor = 1.010

    recent = _recent_totals(player_id, completed, schedule, limit=10)
    recent_impact = _impact_per36(recent) if recent is not None else None
    recent_form_factor = 1.0
    if (
        recent is not None
        and _games_played(recent) >= 5
        and impact is not None
        and impact > 1.0
        and recent_impact is not None
    ):
        delta = recent_impact / impact - 1.0
        recent_form_factor = 1.0 + _clamp(delta * 0.035, -0.0125, 0.0125)

    combined = production_factor * efficiency_factor * availability_factor * recent_form_factor
    combined = _clamp(combined, 0.930, 1.060)
    # Preserve the components but ensure their product cannot dominate OVR.
    if combined > 0:
        rescale = combined / max(
            production_factor * efficiency_factor * availability_factor * recent_form_factor,
            1e-9,
        )
        recent_form_factor *= rescale

    return {
        "production_factor": round(production_factor, 6),
        "efficiency_factor": round(efficiency_factor, 6),
        "availability_factor": round(availability_factor, 6),
        "recent_form_factor": round(recent_form_factor, 6),
        "games": games,
        "minutes": round(minutes, 3),
        "season_impact": round(impact, 4) if impact is not None else None,
        "recent_impact": round(recent_impact, 4) if recent_impact is not None else None,
        "true_shooting": round(ts, 6) if ts is not None else None,
        "availability_rate": round(availability_rate, 6) if availability_rate is not None else None,
    }


def calibrated_market_value_v2(
    state: Any,
    player: Any,
    *,
    salary_cap: float,
    prior_salary: float | None,
    minimum_salary_floor: float | None,
    maximum_legal_salary: float | None,
) -> MarketValueBreakdownV2:
    cap = max(float(salary_cap), 1.0)
    player_id = _clean(getattr(player, "player_id", ""))
    overall = _finite(getattr(player, "overall_rating", None)) or 72.0
    age = _finite(getattr(player, "age", None))
    potential = _finite(getattr(player, "potential_rating", None))

    rating_ref, upside = base_rating_reference_v1(player, cap)
    age_factor = age_risk_factor_v2(player)
    medical = medical_risk_adjustment_v2_1(state, player)
    perf = production_adjustments_v2(state, player)

    adjusted = (
        rating_ref
        * age_factor
        * float(medical["factor"])
        * float(perf["production_factor"])
        * float(perf["efficiency_factor"])
        * float(perf["availability_factor"])
        * float(perf["recent_form_factor"])
    )

    prior = _finite(prior_salary)
    prior_weight = 0.12
    if age is not None and age <= 25 and upside >= 1.04:
        prior_weight = 0.08

    bounded_prior = None
    pre_clip = adjusted
    if prior is not None and prior > 0:
        bounded_prior = _clamp(prior, 0.70 * adjusted, 1.30 * adjusted)
        pre_clip = (1.0 - prior_weight) * adjusted + prior_weight * bounded_prior

    minimum = _finite(minimum_salary_floor)
    maximum = _finite(maximum_legal_salary)
    final = pre_clip
    if minimum is not None:
        final = max(final, minimum)
    if maximum is not None:
        final = min(final, maximum)
    final = max(final, 1.0)

    return MarketValueBreakdownV2(
        version=FREE_AGENCY_MARKET_VALUE_CALIBRATION_VERSION,
        player_id=player_id,
        salary_cap=round(cap, 2),
        overall=round(overall, 3),
        age=round(age, 3) if age is not None else None,
        potential=round(potential, 3) if potential is not None else None,
        base_rating_reference=round(rating_ref / max(upside, 1e-9), 2),
        young_upside_factor=round(upside, 6),
        age_risk_factor=round(age_factor, 6),
        medical_risk_factor=float(medical["factor"]),
        medical_risk_tier=str(medical["tier"]),
        availability_rating=medical["availability_rating"],
        durability=medical["durability"],
        recent_injuries_suffered=int(medical["injuries_suffered"]),
        medical_games_missed=int(medical["medical_games_missed"]),
        multi_season_availability_rate=medical["multi_season_availability_rate"],
        production_factor=float(perf["production_factor"]),
        efficiency_factor=float(perf["efficiency_factor"]),
        availability_factor=float(perf["availability_factor"]),
        recent_form_factor=float(perf["recent_form_factor"]),
        evidence_games=int(perf["games"]),
        evidence_minutes=float(perf["minutes"]),
        season_impact_per36=perf["season_impact"],
        recent_impact_per36=perf["recent_impact"],
        true_shooting=perf["true_shooting"],
        availability_rate=perf["availability_rate"],
        performance_adjusted_reference=round(adjusted, 2),
        prior_salary=round(prior, 2) if prior is not None else None,
        prior_salary_weight=prior_weight,
        bounded_prior_salary=round(bounded_prior, 2) if bounded_prior is not None else None,
        pre_clip_reference=round(pre_clip, 2),
        minimum_salary_floor=round(minimum, 2) if minimum is not None else None,
        maximum_legal_salary=round(maximum, 2) if maximum is not None else None,
        final_reference=round(final, 2),
    )


def legacy_market_value_v1(
    player: Any,
    *,
    salary_cap: float,
    prior_salary: float | None,
    minimum_salary_floor: float | None,
    maximum_legal_salary: float | None,
) -> float:
    rating_ref, _ = base_rating_reference_v1(player, salary_cap)
    prior = _finite(prior_salary)
    reference = 0.68 * rating_ref + 0.32 * prior if prior is not None and prior > 0 else rating_ref
    minimum = _finite(minimum_salary_floor)
    maximum = _finite(maximum_legal_salary)
    if minimum is not None:
        reference = max(reference, minimum)
    if maximum is not None:
        reference = min(reference, maximum)
    return round(max(reference, 1.0), 2)
