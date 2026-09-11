from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


CAREER_LIFECYCLE_VERSION = "franchise-career-lifecycle-v1.0.1-2026-08-11"
RETIREMENT_DECISION_NAMESPACE = "retirement-population-preview-v1-2026-08-11"
CAREER_INTENT_NAMESPACE = "franchise-career-intent-v1-2026-08-11"
RETIREMENT_MIN_AGE = 33
ABSOLUTE_MAX_ACTIVE_AGE = 46
MIN_TEAM_ROSTER_AFTER_RETIREMENTS = 12

STATUS_ACTIVE = "active"
STATUS_CONSIDERING = "considering_retirement"
STATUS_FAREWELL = "farewell_season"
STATUS_RETIRED = "retired"
VALID_STATUSES = {
    STATUS_ACTIVE,
    STATUS_CONSIDERING,
    STATUS_FAREWELL,
    STATUS_RETIRED,
}


@dataclass(frozen=True)
class RetirementDecisionRecord:
    player_id: str
    player_name: str
    team: str
    age: float
    overall: float
    games_played: int
    minutes_per_game: float
    previous_overall_delta: float
    contract_years_remaining: int
    free_agent: bool
    longevity_score: float
    longevity_tier: str
    status_before: str
    farewell_locked: bool
    base_retirement_probability: float
    return_offer_modifier: float
    final_retirement_probability: float
    retirement_roll: float
    would_retire_without_offer: bool
    raw_retire: bool
    roster_floor_protected: bool
    projected_retire: bool
    offer_saved_return: bool
    source_season: str
    target_season: str
    decision_reason: str


@dataclass(frozen=True)
class CareerIntentRecord:
    player_id: str
    player_name: str
    team: str
    season: str
    age: float
    overall: float
    retirement_risk: float
    status: str
    farewell_probability: float
    farewell_roll: float
    announced: bool
    announcement_text: str


@dataclass(frozen=True)
class CareerTransitionPlan:
    engine_version: str
    source_season: str
    target_season: str
    players_before: int
    candidates: tuple[RetirementDecisionRecord, ...]
    retirements: tuple[RetirementDecisionRecord, ...]
    rostered_retirements: int
    free_agent_retirements: int
    age_40_plus_before: int
    age_40_plus_after: int
    farewell_locked_retirements: int
    return_offer_cases: int
    offer_saved_returns: int
    skipped_because_no_completed_season: bool = False

    @property
    def retirement_player_ids(self) -> tuple[str, ...]:
        return tuple(record.player_id for record in self.retirements)

    def payload(self) -> dict[str, Any]:
        return {
            "engine_version": self.engine_version,
            "source_season": self.source_season,
            "target_season": self.target_season,
            "players_before": self.players_before,
            "players_after_retirements": self.players_before - len(self.retirements),
            "retirement_count": len(self.retirements),
            "rostered_retirements": self.rostered_retirements,
            "free_agent_retirements": self.free_agent_retirements,
            "age_40_plus_before": self.age_40_plus_before,
            "age_40_plus_after": self.age_40_plus_after,
            "farewell_locked_retirements": self.farewell_locked_retirements,
            "return_offer_cases": self.return_offer_cases,
            "offer_saved_returns": self.offer_saved_returns,
            "skipped_because_no_completed_season": self.skipped_because_no_completed_season,
            "retirement_player_ids": list(self.retirement_player_ids),
            "retirements": [asdict(record) for record in self.retirements],
            "offer_saved_return_records": [
                asdict(record)
                for record in self.candidates
                if record.offer_saved_return
            ],
        }


def clean(value: Any) -> str:
    return str(value or "").strip()


def number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def hash_unit(*parts: Any) -> float:
    text = "|".join(clean(part) for part in parts)
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], "big")
    return value / float((1 << 64) - 1)


def longevity_score(player_id: str) -> float:
    return hash_unit(RETIREMENT_DECISION_NAMESPACE, "longevity", player_id)


def longevity_tier(score: float) -> str:
    if score >= 0.992:
        return "historic_outlier"
    if score >= 0.965:
        return "elite_longevity"
    if score >= 0.900:
        return "above_average_longevity"
    return "normal_longevity"


def age_probability(age: float) -> float:
    if age < 33:
        return 0.0
    if age < 34:
        return 0.010
    if age < 35:
        return 0.025
    if age < 36:
        return 0.060
    if age < 37:
        return 0.120
    if age < 38:
        return 0.220
    if age < 39:
        return 0.360
    if age < 40:
        return 0.520
    if age < 41:
        return 0.690
    if age < 42:
        return 0.800
    if age < 43:
        return 0.875
    if age < 44:
        return 0.925
    if age < 45:
        return 0.960
    if age < 46:
        return 0.985
    return 1.0


def season_usage(state: Any, player_id: str) -> tuple[int, float]:
    totals = getattr(state, "player_season_totals", {}).get(player_id)
    if totals is None:
        return 0, 0.0
    gp = max(0, integer(getattr(totals, "games_played", 0), 0))
    minutes = max(0.0, number(getattr(totals, "minutes", 0.0), 0.0))
    mpg = minutes / gp if gp > 0 else 0.0
    return gp, mpg


def archived_usage(state: Any, player_id: str) -> tuple[int, float]:
    history = list(getattr(state, "season_history", []) or [])
    if not history:
        return season_usage(state, player_id)
    latest = history[-1]
    totals = getattr(latest, "player_season_totals", {}).get(player_id)
    if totals is None:
        return season_usage(state, player_id)
    gp = max(0, integer(getattr(totals, "games_played", 0), 0))
    minutes = max(0.0, number(getattr(totals, "minutes", 0.0), 0.0))
    mpg = minutes / gp if gp > 0 else 0.0
    return gp, mpg


def previous_overall_delta(player: Any) -> float:
    history = list(getattr(player, "development_history", []) or [])
    if not history:
        return 0.0
    latest = history[-1]
    if isinstance(latest, Mapping):
        return number(latest.get("overall_delta"), 0.0)
    return number(getattr(latest, "overall_delta", 0.0), 0.0)


def contract_years(player: Any) -> int:
    contract = getattr(player, "contract", None)
    if contract is None:
        return 0
    return max(0, integer(getattr(contract, "years_remaining", 0), 0))


def contract_salary(player: Any) -> float:
    contract = getattr(player, "contract", None)
    if contract is None:
        return 0.0
    return max(0.0, number(getattr(contract, "salary", 0.0), 0.0))


def retirement_probability(
    *,
    age: float,
    overall: float,
    gp: int,
    mpg: float,
    previous_delta: float,
    years_remaining: int,
    longevity: float,
    free_agent: bool,
) -> float:
    """Approved V1 retirement curve. Keep this stable for migration parity."""
    probability = age_probability(age)
    if probability <= 0.0:
        return 0.0

    if overall >= 90.0:
        probability -= 0.24
    elif overall >= 85.0:
        probability -= 0.18
    elif overall >= 80.0:
        probability -= 0.10
    elif overall < 68.0:
        probability += 0.16
    elif overall < 72.0:
        probability += 0.09

    if mpg >= 30.0:
        probability -= 0.12
    elif mpg >= 24.0:
        probability -= 0.08
    elif mpg < 6.0:
        probability += 0.12
    elif mpg < 12.0:
        probability += 0.07

    if gp >= 70:
        probability -= 0.04
    elif gp == 0:
        probability += 0.12
    elif gp < 25:
        probability += 0.07

    if previous_delta <= -5.0:
        probability += 0.10
    elif previous_delta <= -3.0:
        probability += 0.06
    elif previous_delta >= 2.0:
        probability -= 0.04

    if years_remaining >= 2:
        probability -= 0.06
    elif years_remaining == 1:
        probability -= 0.025

    if free_agent:
        probability += 0.08

    if longevity >= 0.992:
        probability -= 0.36
    elif longevity >= 0.965:
        probability -= 0.22
    elif longevity >= 0.900:
        probability -= 0.09

    if age >= ABSOLUTE_MAX_ACTIVE_AGE:
        probability = 1.0

    return round(clamp(probability, 0.0, 1.0), 6)


def ensure_lifecycle_state(state: Any) -> None:
    defaults = {
        "career_intent_by_player_id": {},
        "career_announcements": [],
        "career_decision_history": [],
        "retirement_history": [],
        "retirement_return_offers": {},
    }
    for name, default in defaults.items():
        if not hasattr(state, name) or getattr(state, name) is None:
            setattr(state, name, default.copy() if isinstance(default, dict) else list(default))
    setattr(state, "career_lifecycle_version", CAREER_LIFECYCLE_VERSION)


def lifecycle_source_payload(state: Any) -> dict[str, Any]:
    return {
        "career_lifecycle_version": clean(getattr(state, "career_lifecycle_version", "")),
        "career_intent_by_player_id": getattr(state, "career_intent_by_player_id", {}),
        "retirement_return_offers": getattr(state, "retirement_return_offers", {}),
        "retirement_history_count": len(getattr(state, "retirement_history", []) or []),
        "career_decision_history_count": len(getattr(state, "career_decision_history", []) or []),
    }


def register_return_offer(state: Any, player_id: str, offer: Mapping[str, Any]) -> None:
    """Future contract/re-signing hook. Stores an offseason offer context."""
    ensure_lifecycle_state(state)
    player_id = clean(player_id)
    if player_id not in getattr(state, "players", {}):
        raise ValueError(f"Unknown franchise player: {player_id}")
    normalized = {
        "season": clean(offer.get("season") or getattr(getattr(state, "settings", None), "season_label", "")),
        "salary": max(0.0, number(offer.get("salary"), 0.0)),
        "market_salary": max(0.0, number(offer.get("market_salary"), 0.0)),
        "years": max(1, integer(offer.get("years"), 1)),
        "guaranteed": bool(offer.get("guaranteed", True)),
        "role": clean(offer.get("role") or "rotation").lower(),
        "contender_score": clamp(number(offer.get("contender_score"), 0.5), 0.0, 1.0),
        "same_team": bool(offer.get("same_team", False)),
        "notes": clean(offer.get("notes")),
    }
    getattr(state, "retirement_return_offers")[player_id] = normalized


def _intent_status_for_source(state: Any, player_id: str, source_season: str) -> str:
    record = getattr(state, "career_intent_by_player_id", {}).get(player_id, {})
    if not isinstance(record, Mapping):
        return STATUS_ACTIVE
    if clean(record.get("season")) != clean(source_season):
        return STATUS_ACTIVE
    status = clean(record.get("status"))
    return status if status in VALID_STATUSES else STATUS_ACTIVE


def _offer_for_source(state: Any, player_id: str, source_season: str) -> Mapping[str, Any] | None:
    offer = getattr(state, "retirement_return_offers", {}).get(player_id)
    if not isinstance(offer, Mapping):
        return None
    offer_season = clean(offer.get("season"))
    if offer_season and offer_season != clean(source_season):
        return None
    return offer


def return_offer_modifier(
    *,
    player: Any,
    age: float,
    base_probability: float,
    status_before: str,
    offer: Mapping[str, Any] | None,
) -> float:
    if status_before != STATUS_CONSIDERING or offer is None:
        return 0.0
    if age >= ABSOLUTE_MAX_ACTIVE_AGE or base_probability >= 1.0:
        return 0.0

    salary = max(0.0, number(offer.get("salary"), 0.0))
    market = max(0.0, number(offer.get("market_salary"), 0.0))
    if market <= 0.0:
        market = max(contract_salary(player), 1.0)
    ratio = salary / max(market, 1.0)

    modifier = 0.0
    if ratio >= 1.75:
        modifier -= 0.18
    elif ratio >= 1.35:
        modifier -= 0.12
    elif ratio >= 1.10:
        modifier -= 0.06
    elif ratio < 0.75:
        modifier += 0.05

    years = max(1, integer(offer.get("years"), 1))
    if years >= 3:
        modifier -= 0.08
    elif years >= 2:
        modifier -= 0.05

    if bool(offer.get("guaranteed", True)):
        modifier -= 0.03

    role = clean(offer.get("role") or "rotation").lower()
    if role in {"starter", "starting", "star"}:
        modifier -= 0.08
    elif role in {"rotation", "sixth_man", "sixth man"}:
        modifier -= 0.04

    modifier -= 0.08 * clamp(number(offer.get("contender_score"), 0.5), 0.0, 1.0)
    if bool(offer.get("same_team", False)):
        modifier -= 0.03

    # Very old players can be persuaded only a little. Money cannot make
    # an effectively certain retirement disappear.
    lower_bound = -0.30
    if age >= 44.0:
        lower_bound = -0.06
    elif age >= 42.0:
        lower_bound = -0.15

    return round(clamp(modifier, lower_bound, 0.10), 6)


def _empty_plan(state: Any, target_season: str) -> CareerTransitionPlan:
    age_40 = sum(
        number(getattr(player, "age", 0.0), 0.0) >= 40.0
        for player in getattr(state, "players", {}).values()
        if not bool(getattr(player, "synthetic", False))
    )
    return CareerTransitionPlan(
        engine_version=CAREER_LIFECYCLE_VERSION,
        source_season=clean(getattr(getattr(state, "settings", None), "season_label", "")),
        target_season=clean(target_season),
        players_before=len(getattr(state, "players", {})),
        candidates=(),
        retirements=(),
        rostered_retirements=0,
        free_agent_retirements=0,
        age_40_plus_before=age_40,
        age_40_plus_after=age_40,
        farewell_locked_retirements=0,
        return_offer_cases=0,
        offer_saved_returns=0,
        skipped_because_no_completed_season=True,
    )


def build_retirement_plan(state: Any, *, target_season: str) -> CareerTransitionPlan:
    source = clean(getattr(getattr(state, "settings", None), "season_label", ""))
    target = clean(target_season)

    # The transactional controller self-test builds an empty season. Avoid
    # phantom career decisions when no completed regular-season games exist.
    if not getattr(state, "completed_games", {}):
        return _empty_plan(state, target)

    free_agents = set(getattr(state, "free_agent_player_ids", ()) or ())
    rows: list[dict[str, Any]] = []

    for player_id, player in sorted(getattr(state, "players", {}).items()):
        if bool(getattr(player, "synthetic", False)):
            continue
        age = number(getattr(player, "age", 0.0), 0.0)
        if age < RETIREMENT_MIN_AGE:
            continue

        overall = number(getattr(player, "overall_rating", 0.0), 0.0)
        gp, mpg = season_usage(state, player_id)
        previous_delta = previous_overall_delta(player)
        years = contract_years(player)
        long_score = longevity_score(str(player_id))
        base_probability = retirement_probability(
            age=age,
            overall=overall,
            gp=gp,
            mpg=mpg,
            previous_delta=previous_delta,
            years_remaining=years,
            longevity=long_score,
            free_agent=player_id in free_agents,
        )
        status_before = _intent_status_for_source(state, player_id, source)
        farewell_locked = status_before == STATUS_FAREWELL
        offer = _offer_for_source(state, player_id, source)
        modifier = return_offer_modifier(
            player=player,
            age=age,
            base_probability=base_probability,
            status_before=status_before,
            offer=offer,
        )
        final_probability = 1.0 if farewell_locked else round(
            clamp(base_probability + modifier, 0.0, 1.0), 6
        )
        roll = hash_unit(
            RETIREMENT_DECISION_NAMESPACE,
            source,
            target,
            "retirement-roll",
            player_id,
        )
        would_without_offer = bool(base_probability > 0.0 and roll < base_probability)
        raw_retire = bool(final_probability > 0.0 and roll < final_probability)
        offer_saved = bool(
            offer is not None
            and status_before == STATUS_CONSIDERING
            and would_without_offer
            and not raw_retire
        )

        reason = "probability_roll"
        if farewell_locked:
            reason = "farewell_season_locked"
        elif offer_saved:
            reason = "return_offer_convinced_player"
        elif offer is not None and status_before == STATUS_CONSIDERING:
            reason = "return_offer_considered"

        rows.append(
            {
                "player_id": str(player_id),
                "player_name": str(getattr(player, "player_name", player_id)),
                "team": str(getattr(player, "team_abbreviation", "") or "FA"),
                "age": round(age, 2),
                "overall": round(overall, 3),
                "games_played": gp,
                "minutes_per_game": round(mpg, 2),
                "previous_overall_delta": round(previous_delta, 3),
                "contract_years_remaining": years,
                "free_agent": player_id in free_agents,
                "longevity_score": round(long_score, 6),
                "longevity_tier": longevity_tier(long_score),
                "status_before": status_before,
                "farewell_locked": farewell_locked,
                "base_retirement_probability": base_probability,
                "return_offer_modifier": modifier,
                "final_retirement_probability": final_probability,
                "retirement_roll": round(roll, 6),
                "would_retire_without_offer": would_without_offer,
                "raw_retire": raw_retire,
                "roster_floor_protected": False,
                "projected_retire": False,
                "offer_saved_return": offer_saved,
                "source_season": source,
                "target_season": target,
                "decision_reason": reason,
            }
        )

    by_id = {row["player_id"]: row for row in rows}
    for team in getattr(state, "teams", {}).values():
        roster = list(getattr(team, "roster_player_ids", ()) or ())
        proposed = [
            by_id[player_id]
            for player_id in roster
            if player_id in by_id and by_id[player_id]["raw_retire"]
        ]
        allowed = max(0, len(roster) - MIN_TEAM_ROSTER_AFTER_RETIREMENTS)
        if len(proposed) <= allowed:
            continue
        protect_count = len(proposed) - allowed
        protectable = [row for row in proposed if not row["farewell_locked"]]
        protected = sorted(
            protectable,
            key=lambda row: (
                row["final_retirement_probability"],
                -row["overall"],
                row["player_name"],
            ),
        )[:protect_count]
        for row in protected:
            row["roster_floor_protected"] = True
            if row["decision_reason"] == "probability_roll":
                row["decision_reason"] = "temporary_roster_floor_protection"

    candidates: list[RetirementDecisionRecord] = []
    retirements: list[RetirementDecisionRecord] = []
    for row in rows:
        row["projected_retire"] = bool(
            row["raw_retire"] and not row["roster_floor_protected"]
        )
        record = RetirementDecisionRecord(**row)
        candidates.append(record)
        if record.projected_retire:
            retirements.append(record)

    retirements.sort(
        key=lambda record: (
            -record.age,
            -record.final_retirement_probability,
            record.player_name,
        )
    )
    retiring_ids = {record.player_id for record in retirements}
    real_players = {
        player_id: player
        for player_id, player in getattr(state, "players", {}).items()
        if not bool(getattr(player, "synthetic", False))
    }
    age_40_before = sum(
        number(getattr(player, "age", 0.0), 0.0) >= 40.0
        for player in real_players.values()
    )
    age_40_after = sum(
        number(getattr(player, "age", 0.0), 0.0) >= 40.0
        and str(player_id) not in retiring_ids
        for player_id, player in real_players.items()
    )

    return CareerTransitionPlan(
        engine_version=CAREER_LIFECYCLE_VERSION,
        source_season=source,
        target_season=target,
        players_before=len(getattr(state, "players", {})),
        candidates=tuple(candidates),
        retirements=tuple(retirements),
        rostered_retirements=sum(not record.free_agent for record in retirements),
        free_agent_retirements=sum(record.free_agent for record in retirements),
        age_40_plus_before=age_40_before,
        age_40_plus_after=age_40_after,
        farewell_locked_retirements=sum(record.farewell_locked for record in retirements),
        return_offer_cases=sum(
            _offer_for_source(state, record.player_id, source) is not None
            and record.status_before == STATUS_CONSIDERING
            for record in candidates
        ),
        offer_saved_returns=sum(record.offer_saved_return for record in candidates),
        skipped_because_no_completed_season=False,
    )


def _without(values: Iterable[str], retiring_ids: set[str]) -> tuple[str, ...]:
    return tuple(value for value in values if value not in retiring_ids)


def _minutes_targets(rotation_ids: tuple[str, ...], starter_ids: tuple[str, ...], regulation_minutes: int) -> dict[str, float]:
    if not rotation_ids:
        return {}
    team_minutes = regulation_minutes * 5
    starter_set = set(starter_ids)
    weights = {
        player_id: (1.25 if player_id in starter_set else 0.75)
        for player_id in rotation_ids
    }
    total = sum(weights.values())
    rounded = {
        player_id: round(team_minutes * weight / total, 1)
        for player_id, weight in weights.items()
    }
    difference = round(team_minutes - sum(rounded.values()), 1)
    if rounded and difference:
        first = rotation_ids[0]
        rounded[first] = round(rounded[first] + difference, 1)
    return rounded


def reconcile_rotations_after_retirement(state: Any) -> None:
    rotation_size = max(5, integer(getattr(getattr(state, "settings", None), "rotation_size", 10), 10))
    regulation_minutes = max(1, integer(getattr(getattr(state, "settings", None), "regulation_minutes", 48), 48))
    players = getattr(state, "players", {})
    for team in getattr(state, "teams", {}).values():
        roster = tuple(
            player_id
            for player_id in getattr(team, "roster_player_ids", ()) or ()
            if player_id in players
        )
        ordered = tuple(
            sorted(
                roster,
                key=lambda player_id: (
                    -number(getattr(players[player_id], "overall_rating", 0.0), 0.0),
                    clean(getattr(players[player_id], "player_name", player_id)),
                    player_id,
                ),
            )
        )
        if len(ordered) < 5:
            raise RuntimeError(
                f"{getattr(team, 'team_abbreviation', 'TEAM')} has fewer than five players after retirement."
            )
        rotation_ids = ordered[: min(rotation_size, len(ordered))]
        starter_ids = rotation_ids[:5]
        team.roster_player_ids = ordered
        team.active_player_ids = rotation_ids
        team.inactive_player_ids = tuple(
            player_id for player_id in ordered if player_id not in set(rotation_ids)
        )
        rotation = getattr(team, "rotation", None)
        if rotation is None:
            continue
        rotation.starter_ids = starter_ids
        rotation.rotation_player_ids = rotation_ids
        rotation.minutes_targets = _minutes_targets(
            rotation_ids, starter_ids, regulation_minutes
        )


def apply_retirement_plan(state: Any, plan: CareerTransitionPlan) -> tuple[dict[str, Any], ...]:
    ensure_lifecycle_state(state)
    current_season = clean(getattr(getattr(state, "settings", None), "season_label", ""))
    if current_season not in {plan.source_season, plan.target_season}:
        raise RuntimeError(
            "Retirement plan no longer matches the franchise season being transitioned."
        )

    retiring_ids = set(plan.retirement_player_ids)
    missing = sorted(retiring_ids.difference(getattr(state, "players", {})))
    if missing:
        raise RuntimeError(
            "Retirement plan references players no longer in the franchise state: "
            + ", ".join(missing[:8])
        )

    records = [asdict(record) for record in plan.retirements]
    getattr(state, "retirement_history").extend(records)

    # Preserve the effect of offseason return offers whether the player stayed
    # or retired. This becomes the audit trail for the future contract UI.
    for record in plan.candidates:
        if _offer_for_source(state, record.player_id, plan.source_season) is not None:
            getattr(state, "career_decision_history").append(
                {
                    "career_lifecycle_version": CAREER_LIFECYCLE_VERSION,
                    "source_season": plan.source_season,
                    "target_season": plan.target_season,
                    "player_id": record.player_id,
                    "player_name": record.player_name,
                    "status_before": record.status_before,
                    "base_retirement_probability": record.base_retirement_probability,
                    "return_offer_modifier": record.return_offer_modifier,
                    "final_retirement_probability": record.final_retirement_probability,
                    "offer_saved_return": record.offer_saved_return,
                    "projected_retire": record.projected_retire,
                }
            )

    for team in getattr(state, "teams", {}).values():
        team.roster_player_ids = _without(
            getattr(team, "roster_player_ids", ()) or (), retiring_ids
        )
        team.active_player_ids = _without(
            getattr(team, "active_player_ids", ()) or (), retiring_ids
        )
        team.inactive_player_ids = _without(
            getattr(team, "inactive_player_ids", ()) or (), retiring_ids
        )

    state.free_agent_player_ids = _without(
        getattr(state, "free_agent_player_ids", ()) or (), retiring_ids
    )
    for player_id in retiring_ids:
        getattr(state, "players", {}).pop(player_id, None)
        getattr(state, "injuries", {}).pop(player_id, None)
        getattr(state, "player_season_totals", {}).pop(player_id, None)

        # Medical / Injury V2 requires the optional current-player health
        # profile map to match the live player population exactly. Historical
        # injury/event records remain untouched; only the current profile for
        # a player who has actually retired is removed here.
        health_profiles = getattr(state, "injury_fatigue_profiles", None)
        if isinstance(health_profiles, dict):
            health_profiles.pop(player_id, None)

        getattr(state, "career_intent_by_player_id", {}).pop(player_id, None)
        getattr(state, "retirement_return_offers", {}).pop(player_id, None)

    # Return offers are one-off offseason contexts. Clear consumed offers for
    # players who returned too; the actual future contract system owns the
    # contract mutation itself.
    for player_id, offer in list(getattr(state, "retirement_return_offers", {}).items()):
        if not isinstance(offer, Mapping) or clean(offer.get("season")) in {"", plan.source_season}:
            getattr(state, "retirement_return_offers", {}).pop(player_id, None)

    if retiring_ids:
        reconcile_rotations_after_retirement(state)
    return tuple(records)


def _preseason_retirement_risk(state: Any, player_id: str, player: Any) -> float:
    age = number(getattr(player, "age", 0.0), 0.0)
    overall = number(getattr(player, "overall_rating", 0.0), 0.0)
    gp, mpg = archived_usage(state, player_id)
    return retirement_probability(
        age=age,
        overall=overall,
        gp=gp,
        mpg=mpg,
        previous_delta=previous_overall_delta(player),
        years_remaining=contract_years(player),
        longevity=longevity_score(str(player_id)),
        free_agent=player_id in set(getattr(state, "free_agent_player_ids", ()) or ()),
    )


def farewell_announcement_probability(*, age: float, overall: float, retirement_risk: float) -> float:
    if age < 37.0 or retirement_risk < 0.30:
        return 0.0
    probability = 0.04
    probability += max(0.0, age - 37.0) * 0.105
    probability += max(0.0, retirement_risk - 0.30) * 0.55
    if overall >= 80.0:
        probability += 0.08
    if age >= 43.0:
        probability += 0.15
    return round(clamp(probability, 0.0, 0.90), 6)


def initialize_career_intents_for_season(state: Any) -> dict[str, Any]:
    """Create preseason career intent and farewell announcements for the new year."""
    ensure_lifecycle_state(state)
    season = clean(getattr(getattr(state, "settings", None), "season_label", ""))
    intents: dict[str, dict[str, Any]] = {}
    announcements: list[dict[str, Any]] = []

    for player_id, player in sorted(getattr(state, "players", {}).items()):
        if bool(getattr(player, "synthetic", False)):
            continue
        age = number(getattr(player, "age", 0.0), 0.0)
        if age < RETIREMENT_MIN_AGE:
            continue
        overall = number(getattr(player, "overall_rating", 0.0), 0.0)
        risk = _preseason_retirement_risk(state, player_id, player)
        farewell_probability = farewell_announcement_probability(
            age=age,
            overall=overall,
            retirement_risk=risk,
        )
        farewell_roll = hash_unit(
            CAREER_INTENT_NAMESPACE,
            season,
            "farewell-announcement",
            player_id,
        )
        status = STATUS_ACTIVE
        if age >= 35.0 and risk >= 0.18:
            status = STATUS_CONSIDERING
        if farewell_probability > 0.0 and farewell_roll < farewell_probability:
            status = STATUS_FAREWELL

        announced = status == STATUS_FAREWELL
        player_name = clean(getattr(player, "player_name", player_id))
        team = clean(getattr(player, "team_abbreviation", "")) or "FA"
        announcement_text = (
            f"{player_name} announced that {season} will be the final season of his NBA career."
            if announced
            else ""
        )
        record = CareerIntentRecord(
            player_id=str(player_id),
            player_name=player_name,
            team=team,
            season=season,
            age=round(age, 2),
            overall=round(overall, 3),
            retirement_risk=round(risk, 6),
            status=status,
            farewell_probability=farewell_probability,
            farewell_roll=round(farewell_roll, 6),
            announced=announced,
            announcement_text=announcement_text,
        )
        intents[str(player_id)] = asdict(record)
        if announced:
            announcements.append(asdict(record))

    state.career_intent_by_player_id = intents
    existing = list(getattr(state, "career_announcements", []) or [])
    existing_keys = {
        (clean(item.get("player_id")), clean(item.get("season")))
        for item in existing
        if isinstance(item, Mapping)
    }
    for announcement in announcements:
        key = (announcement["player_id"], announcement["season"])
        if key not in existing_keys:
            existing.append(announcement)
            existing_keys.add(key)
    state.career_announcements = existing

    return {
        "career_lifecycle_version": CAREER_LIFECYCLE_VERSION,
        "season": season,
        "tracked_veterans": len(intents),
        "active": sum(record["status"] == STATUS_ACTIVE for record in intents.values()),
        "considering_retirement": sum(
            record["status"] == STATUS_CONSIDERING for record in intents.values()
        ),
        "farewell_seasons": sum(
            record["status"] == STATUS_FAREWELL for record in intents.values()
        ),
        "farewell_announcements": announcements,
        "intent_records": list(intents.values()),
    }


def payload_fingerprint(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
