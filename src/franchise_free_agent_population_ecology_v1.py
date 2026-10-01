from __future__ import annotations

import copy
import hashlib
import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from simulation_league_state_v1 import (
    InjuryState,
    PlayerSeasonTotals,
    validate_simulation_league_state,
)


FREE_AGENT_POPULATION_ECOLOGY_VERSION = (
    "franchise-free-agent-population-ecology-v1-2026-09-30"
)
UNSIGNED_SEASONS_ATTR = "franchise_free_agent_unsigned_seasons_v1"
INACTIVE_POOL_ATTR = "franchise_inactive_professional_pool_v1"
DEPARTURE_HISTORY_ATTR = "franchise_free_agent_departure_history_v1"
ECOLOGY_MARKER_ATTR = "franchise_free_agent_population_ecology_v1"

# This is intentionally a market-size band, not a hard player-population cap.
# The boundary runs before the annual undrafted-rookie bridge and before CPU
# two-way completion.  Keeping roughly 270 active free agents at this point
# leaves a healthy post-two-way market while stopping multi-season accumulation.
ACTIVE_FA_SOFT_MAX = 300
ACTIVE_FA_TARGET = 270
MINIMUM_FA_RESERVE = 150
MAX_INACTIVE_PROFESSIONAL_POOL = 72
MAX_REENTRIES_PER_BOUNDARY = 4
MAX_INACTIVE_YEARS = 5


@dataclass(frozen=True)
class FreeAgentDepartureRecord:
    player_id: str
    player_name: str
    age: float | None
    overall_rating: float
    potential_rating: float
    future_outlook_rating: float
    unsigned_seasons: int
    market_score: float
    exit_type: str
    archived_for_reentry: bool
    source_season: str


@dataclass(frozen=True)
class FreeAgentReentryRecord:
    player_id: str
    player_name: str
    age: float | None
    overall_rating: float
    potential_rating: float
    years_away: int
    source_season: str


@dataclass(frozen=True)
class FreeAgentPopulationEcologyResult:
    version: str
    season_label: str
    players_before: int
    players_after: int
    free_agents_before: int
    free_agents_after: int
    inactive_pool_before: int
    inactive_pool_after: int
    departures: tuple[FreeAgentDepartureRecord, ...]
    reentries: tuple[FreeAgentReentryRecord, ...]
    protected_candidate_count: int
    eligible_departure_count: int
    target_active_free_agents: int
    soft_max_active_free_agents: int


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _finite(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed if math.isfinite(parsed) else float(default)


def _age(player: Any) -> float | None:
    try:
        value = float(getattr(player, "age", None))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _season(state: Any) -> str:
    return _clean(getattr(getattr(state, "settings", None), "season_label", ""))


def _hash_unit(*parts: Any) -> float:
    raw = "|".join(_clean(part) for part in parts).encode("utf-8")
    digest = hashlib.sha256(raw).digest()
    return int.from_bytes(digest[:8], "big") / float((1 << 64) - 1)


def _free_agent_ids(state: Any) -> set[str]:
    return {
        _clean(value)
        for value in tuple(getattr(state, "free_agent_player_ids", ()) or ())
        if _clean(value)
    }


def _rostered_ids(state: Any) -> set[str]:
    return {
        _clean(value)
        for team in getattr(state, "teams", {}).values()
        for value in tuple(getattr(team, "roster_player_ids", ()) or ())
        if _clean(value)
    }


def _normalize_free_agent_order(state: Any) -> None:
    state.free_agent_player_ids = tuple(
        sorted(
            _free_agent_ids(state),
            key=lambda player_id: (
                _clean(getattr(getattr(state, "players", {}).get(player_id), "player_name", "")),
                player_id,
            ),
        )
    )


def _market_score(player: Any, unsigned_seasons: int) -> float:
    overall = _finite(getattr(player, "overall_rating", None), 55.0)
    potential = _finite(getattr(player, "potential_rating", None), overall)
    future = _finite(getattr(player, "future_outlook_rating", None), potential)
    age = _age(player)
    age_penalty = 0.0 if age is None else max(0.0, age - 27.0) * 0.85
    unsigned_penalty = max(0, int(unsigned_seasons) - 1) * 4.5
    reliability = max(0.0, min(1.0, _finite(getattr(player, "profile_reliability", None), 0.5)))
    return round(
        overall * 0.60
        + potential * 0.25
        + future * 0.15
        + reliability * 1.5
        - age_penalty
        - unsigned_penalty,
        6,
    )


def _fresh_two_way_expiry(player: Any, prior_unsigned: Mapping[str, int], player_id: str) -> bool:
    return (
        player_id not in prior_unsigned
        and _clean(getattr(player, "live_contract_evidence_status", "")).lower()
        == "expired_two_way_contract"
    )


def _next_unsigned_seasons(
    state: Any,
    *,
    reentered_ids: set[str],
) -> dict[str, int]:
    prior_raw = getattr(state, UNSIGNED_SEASONS_ATTR, {})
    prior = dict(prior_raw) if isinstance(prior_raw, Mapping) else {}
    free_agents = _free_agent_ids(state)
    players = getattr(state, "players", {}) or {}
    next_values: dict[str, int] = {}

    for player_id in sorted(free_agents):
        player = players.get(player_id)
        if player is None or bool(getattr(player, "synthetic", False)):
            continue
        if player_id in reentered_ids:
            next_values[player_id] = 0
            continue
        if _fresh_two_way_expiry(player, prior, player_id):
            next_values[player_id] = 0
            continue
        previous = max(0, int(prior.get(player_id, 0) or 0))
        next_values[player_id] = previous + 1

    return next_values


def _developmentally_protected(player: Any, unsigned_seasons: int) -> bool:
    age = _age(player)
    overall = _finite(getattr(player, "overall_rating", None), 55.0)
    potential = _finite(getattr(player, "potential_rating", None), overall)
    evidence = _clean(getattr(player, "live_contract_evidence_status", "")).lower()

    # A just-expired two-way player has not spent a full season out of the NBA.
    if evidence == "expired_two_way_contract" and unsigned_seasons <= 0:
        return True

    # Give undrafted rookies a full NBA-market year before attrition can touch them.
    if bool(getattr(player, "undrafted_rookie", False)) and unsigned_seasons <= 1:
        return True

    if age is not None and age <= 21.0 and unsigned_seasons <= 2:
        return True
    if age is not None and age <= 24.0 and potential >= 74.0 and unsigned_seasons <= 2:
        return True
    if age is not None and age <= 25.0 and potential >= 80.0 and unsigned_seasons <= 3:
        return True
    if overall >= 78.0 and unsigned_seasons <= 2:
        return True
    if potential >= 84.0 and unsigned_seasons <= 3:
        return True
    return False


def _departure_eligible(player: Any, unsigned_seasons: int) -> bool:
    if bool(getattr(player, "synthetic", False)):
        return False
    if _developmentally_protected(player, unsigned_seasons):
        return False

    age = _age(player)
    overall = _finite(getattr(player, "overall_rating", None), 55.0)
    potential = _finite(getattr(player, "potential_rating", None), overall)

    # Older fringe players can leave after one full unsigned market.
    if age is not None and age >= 30.0 and unsigned_seasons >= 1:
        return overall < 77.0 or potential < 79.0

    # Prime-age players need at least two unsuccessful NBA markets.
    if unsigned_seasons >= 2:
        return overall < 76.0 or potential < 78.0

    return False


def _archive_for_possible_reentry(
    player: Any,
    *,
    unsigned_seasons: int,
    season_label: str,
    player_id: str,
    archive_size: int,
) -> bool:
    if archive_size >= MAX_INACTIVE_PROFESSIONAL_POOL:
        return False
    age = _age(player)
    overall = _finite(getattr(player, "overall_rating", None), 55.0)
    potential = _finite(getattr(player, "potential_rating", None), overall)
    if age is None or age > 30.0 or overall < 66.0 or potential < 70.0:
        return False
    # Keep the re-entry archive bounded and deterministic rather than storing
    # every fringe player object indefinitely.
    return _hash_unit(
        FREE_AGENT_POPULATION_ECOLOGY_VERSION,
        "archive",
        season_label,
        player_id,
        unsigned_seasons,
    ) < 0.58


def _remove_current_player_state(state: Any, player_id: str) -> None:
    getattr(state, "players", {}).pop(player_id, None)
    getattr(state, "injuries", {}).pop(player_id, None)
    getattr(state, "player_season_totals", {}).pop(player_id, None)
    profiles = getattr(state, "injury_fatigue_profiles", None)
    if isinstance(profiles, dict):
        profiles.pop(player_id, None)
    intents = getattr(state, "career_intent_by_player_id", None)
    if isinstance(intents, dict):
        intents.pop(player_id, None)
    offers = getattr(state, "retirement_return_offers", None)
    if isinstance(offers, dict):
        offers.pop(player_id, None)


def _restore_archived_player(state: Any, entry: Mapping[str, Any], season_label: str) -> FreeAgentReentryRecord:
    player = copy.deepcopy(entry["player"])
    player_id = _clean(getattr(player, "player_id", ""))
    if not player_id:
        raise RuntimeError("Inactive-professional archive contains a player without an id.")

    years_away = max(1, int(entry.get("years_away", 1) or 1))
    departure_age = entry.get("age_at_departure")
    try:
        resolved_age = None if departure_age is None else float(departure_age) + years_away
    except (TypeError, ValueError):
        resolved_age = _age(player)

    if resolved_age is not None:
        player.age = round(resolved_age, 2)

    overall = _finite(getattr(player, "overall_rating", None), 55.0)
    decline = 0.15 * years_away
    if resolved_age is not None and resolved_age >= 28.0:
        decline += 0.30 * years_away
    player.overall_rating = round(max(50.0, overall - decline), 3)

    player.team_abbreviation = ""
    player.roster_status = "free_agent"
    player.two_way = False
    contract = getattr(player, "contract", None)
    if contract is None:
        raise RuntimeError(f"Archived player {player_id} has no contract state.")
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
    setattr(player, "live_contract_evidence_status", "returned_to_nba_market")

    history = list(getattr(player, "development_history", []) or [])
    history.append(
        {
            "event": "returned_from_inactive_professional_pool",
            "season_label": season_label,
            "years_away": years_away,
            "version": FREE_AGENT_POPULATION_ECOLOGY_VERSION,
        }
    )
    player.development_history = history

    state.players[player_id] = player
    state.injuries[player_id] = InjuryState(player_id=player_id)
    state.player_season_totals[player_id] = PlayerSeasonTotals(player_id=player_id)
    from simulation_injury_fatigue_v1 import synchronize_injury_profile
    synchronize_injury_profile(state, player_id)

    free_agents = _free_agent_ids(state)
    free_agents.add(player_id)
    state.free_agent_player_ids = tuple(free_agents)

    return FreeAgentReentryRecord(
        player_id=player_id,
        player_name=_clean(getattr(player, "player_name", player_id)) or player_id,
        age=_age(player),
        overall_rating=_finite(getattr(player, "overall_rating", None), 0.0),
        potential_rating=_finite(
            getattr(player, "potential_rating", None),
            _finite(getattr(player, "overall_rating", None), 0.0),
        ),
        years_away=years_away,
        source_season=season_label,
    )


def _advance_archive_and_reenter(state: Any) -> tuple[list[FreeAgentReentryRecord], set[str]]:
    season_label = _season(state)
    raw_archive = getattr(state, INACTIVE_POOL_ATTR, {})
    archive = dict(raw_archive) if isinstance(raw_archive, Mapping) else {}
    if not archive:
        setattr(state, INACTIVE_POOL_ATTR, {})
        return [], set()

    # Age the off-NBA archive by one boundary.  Permanently close records that
    # have been away too long or have aged out of a plausible NBA return.
    retained: dict[str, dict[str, Any]] = {}
    eligible_reentries: list[tuple[float, str, dict[str, Any]]] = []
    for player_id, raw_entry in sorted(archive.items()):
        if not isinstance(raw_entry, Mapping) or "player" not in raw_entry:
            continue
        entry = copy.deepcopy(dict(raw_entry))
        entry["years_away"] = max(0, int(entry.get("years_away", 0) or 0)) + 1
        years_away = int(entry["years_away"])
        age_at_departure = entry.get("age_at_departure")
        try:
            current_age = None if age_at_departure is None else float(age_at_departure) + years_away
        except (TypeError, ValueError):
            current_age = None

        player = entry["player"]
        overall = _finite(getattr(player, "overall_rating", None), 55.0)
        potential = _finite(getattr(player, "potential_rating", None), overall)
        if years_away > MAX_INACTIVE_YEARS or (current_age is not None and current_age > 32.0):
            continue

        retained[player_id] = entry
        if years_away < 1 or years_away > 4:
            continue
        if overall < 68.0 or potential < 72.0:
            continue
        if current_age is not None and current_age > 31.0:
            continue

        probability = min(
            0.30,
            0.07
            + max(0.0, overall - 68.0) * 0.008
            + max(0.0, potential - 72.0) * 0.006
            - max(0, years_away - 1) * 0.012,
        )
        roll = _hash_unit(
            FREE_AGENT_POPULATION_ECOLOGY_VERSION,
            "reentry",
            season_label,
            player_id,
            years_away,
        )
        if roll < probability:
            score = overall * 0.60 + potential * 0.40 - years_away
            eligible_reentries.append((-score, player_id, entry))

    reentries: list[FreeAgentReentryRecord] = []
    reentered_ids: set[str] = set()
    for _, player_id, entry in sorted(eligible_reentries)[:MAX_REENTRIES_PER_BOUNDARY]:
        if player_id in getattr(state, "players", {}):
            retained.pop(player_id, None)
            continue
        reentries.append(_restore_archived_player(state, entry, season_label))
        reentered_ids.add(player_id)
        retained.pop(player_id, None)

    # Hard bound the persisted full-player archive.  Keep the best/youngest
    # entries if prior versions or future tuning ever overfill it.
    if len(retained) > MAX_INACTIVE_PROFESSIONAL_POOL:
        ranked = sorted(
            retained.items(),
            key=lambda item: (
                -_finite(getattr(item[1]["player"], "potential_rating", None), 0.0),
                -_finite(getattr(item[1]["player"], "overall_rating", None), 0.0),
                int(item[1].get("years_away", 0) or 0),
                item[0],
            ),
        )[:MAX_INACTIVE_PROFESSIONAL_POOL]
        retained = dict(ranked)

    setattr(state, INACTIVE_POOL_ATTR, retained)
    return reentries, reentered_ids


def apply_free_agent_population_ecology_at_boundary(
    state: Any,
    *,
    copy_payload: bool = True,
    soft_max_active_free_agents: int = ACTIVE_FA_SOFT_MAX,
    target_active_free_agents: int = ACTIVE_FA_TARGET,
    minimum_free_agent_reserve: int = MINIMUM_FA_RESERVE,
) -> tuple[Any, FreeAgentPopulationEcologyResult]:
    """Bound the active NBA free-agent market after retirement/transition.

    This function may only remove players who are already genuine free agents.
    Rostered players, current two-way players, and synthetic emergency players
    are never population-attrition targets.

    The default path is conservative: attrition runs only when the market is
    above the soft ceiling, and only players who have spent enough time unsigned
    and fail developmental/quality protections are eligible.
    """
    candidate = copy.deepcopy(state) if copy_payload else state
    validate_simulation_league_state(candidate)

    soft_max = max(1, int(soft_max_active_free_agents))
    target = max(1, min(int(target_active_free_agents), soft_max))
    reserve = max(0, min(int(minimum_free_agent_reserve), target))
    season_label = _season(candidate)

    players_before = len(getattr(candidate, "players", {}) or {})
    free_before_set = _free_agent_ids(candidate)
    free_agents_before = len(free_before_set)
    archive_before_raw = getattr(candidate, INACTIVE_POOL_ATTR, {})
    inactive_pool_before = len(archive_before_raw) if isinstance(archive_before_raw, Mapping) else 0

    reentries, reentered_ids = _advance_archive_and_reenter(candidate)
    unsigned = _next_unsigned_seasons(candidate, reentered_ids=reentered_ids)
    setattr(candidate, UNSIGNED_SEASONS_ATTR, unsigned)

    free_agents = _free_agent_ids(candidate)
    players = getattr(candidate, "players", {}) or {}
    rostered = _rostered_ids(candidate)
    if free_agents.intersection(rostered):
        raise RuntimeError("Population ecology encountered a player who is both rostered and a free agent.")

    eligible: list[tuple[float, str, int]] = []
    protected = 0
    for player_id in sorted(free_agents):
        player = players.get(player_id)
        if player is None:
            continue
        years_unsigned = max(0, int(unsigned.get(player_id, 0) or 0))
        if _departure_eligible(player, years_unsigned):
            eligible.append((_market_score(player, years_unsigned), player_id, years_unsigned))
        else:
            protected += 1

    desired = 0
    if len(free_agents) > soft_max:
        desired = len(free_agents) - target
    desired = min(desired, max(0, len(free_agents) - reserve), len(eligible))

    # Lowest market score leaves first.  This keeps the top of the free-agent
    # market intact and naturally targets long-term fringe inventory.
    selected = sorted(
        eligible,
        key=lambda row: (row[0], -row[2], row[1]),
    )[:desired]

    archive_raw = getattr(candidate, INACTIVE_POOL_ATTR, {})
    archive = dict(archive_raw) if isinstance(archive_raw, Mapping) else {}
    history_raw = getattr(candidate, DEPARTURE_HISTORY_ATTR, [])
    history = list(history_raw) if isinstance(history_raw, list) else []
    departures: list[FreeAgentDepartureRecord] = []

    for score, player_id, years_unsigned in selected:
        player = candidate.players.get(player_id)
        if player is None or player_id not in free_agents:
            continue
        if player_id in rostered:
            raise RuntimeError("Population ecology attempted to remove a rostered player.")

        age = _age(player)
        overall = _finite(getattr(player, "overall_rating", None), 55.0)
        potential = _finite(getattr(player, "potential_rating", None), overall)
        future = _finite(getattr(player, "future_outlook_rating", None), potential)

        archived = _archive_for_possible_reentry(
            player,
            unsigned_seasons=years_unsigned,
            season_label=season_label,
            player_id=player_id,
            archive_size=len(archive),
        )
        exit_type = "overseas_or_inactive_professional" if archived else "left_nba_market"
        if archived:
            archive[player_id] = {
                "version": FREE_AGENT_POPULATION_ECOLOGY_VERSION,
                "player": copy.deepcopy(player),
                "departed_season": season_label,
                "years_away": 0,
                "age_at_departure": age,
                "unsigned_seasons_at_departure": years_unsigned,
                "exit_type": exit_type,
            }

        record = FreeAgentDepartureRecord(
            player_id=player_id,
            player_name=_clean(getattr(player, "player_name", player_id)) or player_id,
            age=age,
            overall_rating=overall,
            potential_rating=potential,
            future_outlook_rating=future,
            unsigned_seasons=years_unsigned,
            market_score=score,
            exit_type=exit_type,
            archived_for_reentry=archived,
            source_season=season_label,
        )
        departures.append(record)
        history.append(
            {
                "version": FREE_AGENT_POPULATION_ECOLOGY_VERSION,
                "action": "departed_active_nba_market",
                "season_label": season_label,
                "player_id": record.player_id,
                "player_name": record.player_name,
                "age": record.age,
                "overall_rating": record.overall_rating,
                "potential_rating": record.potential_rating,
                "unsigned_seasons": record.unsigned_seasons,
                "market_score": record.market_score,
                "exit_type": record.exit_type,
                "archived_for_reentry": record.archived_for_reentry,
            }
        )

        free_agents.discard(player_id)
        unsigned.pop(player_id, None)
        _remove_current_player_state(candidate, player_id)

    for record in reentries:
        history.append(
            {
                "version": FREE_AGENT_POPULATION_ECOLOGY_VERSION,
                "action": "returned_to_active_nba_market",
                "season_label": season_label,
                "player_id": record.player_id,
                "player_name": record.player_name,
                "age": record.age,
                "overall_rating": record.overall_rating,
                "potential_rating": record.potential_rating,
                "years_away": record.years_away,
            }
        )

    setattr(candidate, INACTIVE_POOL_ATTR, archive if departures else getattr(candidate, INACTIVE_POOL_ATTR, archive))
    # _advance_archive_and_reenter may have removed reentries from the archive;
    # merge only newly archived departures onto that already-updated dictionary.
    current_archive_raw = getattr(candidate, INACTIVE_POOL_ATTR, {})
    current_archive = dict(current_archive_raw) if isinstance(current_archive_raw, Mapping) else {}
    for player_id, value in archive.items():
        if player_id not in reentered_ids:
            current_archive[player_id] = value
    if len(current_archive) > MAX_INACTIVE_PROFESSIONAL_POOL:
        ranked = sorted(
            current_archive.items(),
            key=lambda item: (
                -_finite(getattr(item[1]["player"], "potential_rating", None), 0.0),
                -_finite(getattr(item[1]["player"], "overall_rating", None), 0.0),
                item[0],
            ),
        )[:MAX_INACTIVE_PROFESSIONAL_POOL]
        current_archive = dict(ranked)
    setattr(candidate, INACTIVE_POOL_ATTR, current_archive)
    setattr(candidate, UNSIGNED_SEASONS_ATTR, unsigned)
    setattr(candidate, DEPARTURE_HISTORY_ATTR, history)

    candidate.free_agent_player_ids = tuple(free_agents)
    _normalize_free_agent_order(candidate)

    marker = {
        "version": FREE_AGENT_POPULATION_ECOLOGY_VERSION,
        "season_label": season_label,
        "players_before": players_before,
        "players_after": len(candidate.players),
        "free_agents_before": free_agents_before,
        "free_agents_after": len(candidate.free_agent_player_ids),
        "inactive_pool_before": inactive_pool_before,
        "inactive_pool_after": len(current_archive),
        "departure_count": len(departures),
        "reentry_count": len(reentries),
        "protected_candidate_count": protected,
        "eligible_departure_count": len(eligible),
        "target_active_free_agents": target,
        "soft_max_active_free_agents": soft_max,
        "minimum_free_agent_reserve": reserve,
        "departed_player_ids": tuple(record.player_id for record in departures),
        "reentered_player_ids": tuple(record.player_id for record in reentries),
    }
    setattr(candidate, ECOLOGY_MARKER_ATTR, marker)

    validate_simulation_league_state(candidate)

    return candidate, FreeAgentPopulationEcologyResult(
        version=FREE_AGENT_POPULATION_ECOLOGY_VERSION,
        season_label=season_label,
        players_before=players_before,
        players_after=len(candidate.players),
        free_agents_before=free_agents_before,
        free_agents_after=len(candidate.free_agent_player_ids),
        inactive_pool_before=inactive_pool_before,
        inactive_pool_after=len(current_archive),
        departures=tuple(departures),
        reentries=tuple(reentries),
        protected_candidate_count=protected,
        eligible_departure_count=len(eligible),
        target_active_free_agents=target,
        soft_max_active_free_agents=soft_max,
    )
