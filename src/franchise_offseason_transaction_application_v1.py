from __future__ import annotations

import copy
import hashlib
import json
import pickle
from collections import Counter
from typing import Any, Iterable, Mapping


VERSION = "franchise-offseason-transaction-application-v1.0.1-2026-08-16"
SIM_HISTORY_ATTR = "offseason_transaction_application_v1_history"
SIM_REVISION_ATTR = "offseason_transaction_application_v1_revision"
TRADE_HISTORY_ATTR = "offseason_transaction_application_v1_history"
TRADE_OVERRIDES_ATTR = "offseason_transaction_contract_overrides_v1"
MARKET_AMOUNT_ATTR = "offseason_free_agent_amount_candidates_v1"
USER_RESOLUTIONS = {
    "1631159": ("exercise", "CHI"),
    "1631338": ("decline", ""),
}
DEVELOPMENT_SKILL_FIELDS = (
    "scoring_rating", "shooting_rating", "playmaking_rating",
    "rebounding_rating", "defense_rating", "efficiency_rating",
    "availability_rating",
)
DEVELOPMENT_STAT_FACTORS = (
    "points", "rebounds", "assists", "steals", "blocks", "turnovers",
    "fouls", "three_attempts", "free_throw_attempts",
)
BASELINE_PER_36_FIELDS = tuple(
    f"{field}_per_36" for field in DEVELOPMENT_STAT_FACTORS
)

# Explicit audited bridge for the five players absent from every runtime
# identity/profile map. Ratings are conservative calibration inputs; production
# baselines and identity fields are derived from the cited official evidence.
POPULATION_SUPPLEMENT = {
    "1627832": {
        "player_name": "Fred VanVleet", "position": "G", "age": 32.0,
        "overall_rating": 83.0, "potential_rating": 83.0,
        "future_outlook_rating": 78.0, "profile_reliability": 0.80,
        "skill_ratings": (81.0, 82.0, 85.0, 67.0, 82.0, 79.0, 60.0),
        "baseline_per_36": (14.42045455, 3.78409091, 5.72727273, 1.63636364, 0.40909091, 1.53409091, 2.35227273, 7.87500000, 2.35227273),
        "initial_salary": 25_000_000.0,
        "evidence_method": "repository_historical_2024_25_nba_profile_bridge_v1",
        "source_url": "https://www.nba.com/stats/player/1627832/career",
    },
    "1642440": {
        "player_name": "Gabe McGlothan", "position": "F", "age": 27.0,
        "overall_rating": 67.0, "potential_rating": 70.0,
        "future_outlook_rating": 68.0, "profile_reliability": 0.60,
        "skill_ratings": (68.0, 70.0, 64.0, 73.0, 70.0, 71.0, 64.0),
        "baseline_per_36": (19.27659574, 8.80851064, 2.29787234, 1.02127660, 1.14893617, 2.17021277, 3.70212766, 5.36170213, 2.68085106),
        "initial_salary": None,
        "evidence_method": "official_gleague_2025_26_profile_bridge_v1",
        "source_url": "https://gleague.nba.com/player/1642440",
    },
    "1642850": {
        "player_name": "Thomas Sorber", "position": "F-C", "age": 20.0,
        "overall_rating": 70.0, "potential_rating": 87.0,
        "future_outlook_rating": 82.0, "profile_reliability": 0.65,
        "skill_ratings": (70.0, 64.0, 70.0, 76.0, 78.0, 74.0, 60.0),
        "baseline_per_36": (16.65957447, 9.71808511, 2.77659574, 1.67553191, 2.34574468, 2.58510638, 2.53723404, 1.77127660, 5.02659574),
        "initial_salary": 4_073_100.0,
        "evidence_method": "official_georgetown_2024_25_profile_bridge_v1",
        "source_url": "https://guhoyas.com/sports/mens-basketball/roster/thomas-sorber/16078",
    },
    "202681": {
        "player_name": "Kyrie Irving", "position": "G", "age": 34.0,
        "overall_rating": 85.5, "potential_rating": 85.5,
        "future_outlook_rating": 80.0, "profile_reliability": 0.85,
        "skill_ratings": (89.0, 89.0, 85.0, 66.0, 76.0, 88.0, 60.0),
        "baseline_per_36": (24.63157895, 4.78670360, 4.58725762, 1.29639889, 0.49861496, 2.19390582, 1.99445983, 7.18005540, 4.28808864),
        "initial_salary": 39_491_282.0,
        "evidence_method": "repository_historical_2024_25_nba_profile_bridge_v1",
        "source_url": "https://www.nba.com/stats/player/202681?SeasonType=Regular+Season",
    },
    "203081": {
        "player_name": "Damian Lillard", "position": "G", "age": 36.0,
        "overall_rating": 87.0, "potential_rating": 87.0,
        "future_outlook_rating": 78.0, "profile_reliability": 0.85,
        "skill_ratings": (88.0, 89.0, 87.0, 65.0, 69.0, 86.0, 60.0),
        "baseline_per_36": (24.83102493, 4.68698061, 7.08033241, 1.19667590, 0.19944598, 2.79224377, 1.69529086, 8.97506925, 6.78116343),
        "initial_salary": 13_398_800.0,
        "evidence_method": "repository_historical_2024_25_nba_profile_bridge_v1",
        "source_url": "https://www.nba.com/stats/player/203081/advanced?SeasonType=Regular+Season&Split=yoy",
    },
}


class OffseasonTransactionApplicationError(RuntimeError):
    pass


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def player_id(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text


def team(value: Any) -> str:
    text = clean(value).upper()
    return "" if text in {"", "FA", "FREE_AGENT", "NONE", "N/A"} else text


def number(value: Any) -> float | None:
    text = clean(value).replace("$", "").replace(",", "")
    if not text:
        return None
    try:
        result = float(text)
    except (TypeError, ValueError):
        return None
    return result


def object_digest(value: Any) -> str:
    try:
        payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        payload = repr(value).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def dedupe(values: Iterable[Any]) -> tuple[str, ...]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        normalized = player_id(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            output.append(normalized)
    return tuple(output)


def resolve_decisions(
    automatic_rows: list[dict[str, str]],
    pending_rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = [dict(row) for row in automatic_rows]
    for source in pending_rows:
        row: dict[str, Any] = dict(source)
        pid = player_id(row.get("player_id"))
        if pid not in USER_RESOLUTIONS:
            raise OffseasonTransactionApplicationError(f"Unexpected unresolved user decision: {pid}")
        recommendation, final_owner = USER_RESOLUTIONS[pid]
        row["recommendation"] = recommendation
        row["owner_before"] = team(row.get("owner_before") or row.get("team_abbreviation"))
        row["owner_after"] = final_owner or "FA"
        row["entered_market"] = recommendation in {"decline", "waive"}
        row["base_salary_2026_27"] = row.get("option_salary_2026_27")
        row["confidence"] = "user_resolved_recommended_branch"
        row["reason"] = "Controlled-team branch frozen by the validated final 226-player market."
        resolved.append(row)

    ids = [player_id(row.get("player_id")) for row in resolved]
    if len(resolved) != 111 or len(ids) != len(set(ids)):
        raise OffseasonTransactionApplicationError("Resolved decision board must contain exactly 111 unique players.")
    counts = Counter(clean(row.get("recommendation")).lower() for row in resolved)
    if counts != Counter({"exercise": 43, "decline": 30, "retain": 36, "waive": 2}):
        raise OffseasonTransactionApplicationError(f"Unexpected final decision distribution: {dict(counts)}")
    return resolved


def decision_salary(row: Mapping[str, Any]) -> float | None:
    return number(row.get("base_salary_2026_27") or row.get("option_salary_2026_27"))


def set_contract(player: Any, *, recommendation: str, salary: float | None, category: str) -> None:
    contract = getattr(player, "contract", None)
    if contract is None:
        raise OffseasonTransactionApplicationError(
            f"Player {clean(getattr(player, 'player_id', ''))} lacks a contract state."
        )
    if recommendation in {"exercise", "retain"}:
        if salary is None or salary <= 0:
            raise OffseasonTransactionApplicationError("Retained/exercised decision lacks an exact 2026-27 salary.")
        contract.status = "under_contract"
        contract.salary = float(salary)
        contract.years_remaining = 1
        contract.option_type = clean(category)
        contract.guaranteed = True
    else:
        contract.status = "free_agent_pool"
        contract.salary = None
        contract.years_remaining = None
        contract.option_type = ""
        contract.guaranteed = None


def roster_owner_map(state: Any) -> dict[str, str]:
    owners: dict[str, str] = {}
    duplicates: dict[str, list[str]] = {}
    for raw_team, team_state in getattr(state, "teams", {}).items():
        code = team(raw_team)
        for pid in getattr(team_state, "roster_player_ids", ()):
            normalized = player_id(pid)
            if normalized in owners:
                duplicates.setdefault(normalized, [owners[normalized]]).append(code)
            else:
                owners[normalized] = code
    if duplicates:
        raise OffseasonTransactionApplicationError(f"Duplicate roster ownership: {duplicates}")
    return owners


def repair_offseason_rotation(state: Any, code: str, incoming_ids: tuple[str, ...]) -> None:
    from simulation_league_state_v1 import RotationState

    team_state = state.teams[code]
    roster = list(dedupe(team_state.roster_player_ids))
    if len(roster) < 5:
        raise OffseasonTransactionApplicationError(
            f"{code} cannot form an offseason five-player lineup after lifecycle decisions."
        )
    roster_set = set(roster)
    prior = [
        player_id(value)
        for value in getattr(team_state.rotation, "rotation_player_ids", ())
        if player_id(value) in roster_set
    ]
    incoming = [pid for pid in incoming_ids if pid in roster_set]
    remaining = sorted(
        (pid for pid in roster if pid not in set(prior) and pid not in set(incoming)),
        key=lambda pid: (-float(getattr(state.players[pid], "overall_rating", 0) or 0), pid),
    )
    incoming = sorted(
        set(incoming),
        key=lambda pid: (-float(getattr(state.players[pid], "overall_rating", 0) or 0), pid),
    )
    ordered = list(dedupe((*prior, *incoming, *remaining)))
    target_size = min(
        len(roster),
        max(5, int(getattr(state.settings, "rotation_size", 10) or 10)),
    )
    rotation_ids = tuple(ordered[:target_size])
    prior_starters = [
        player_id(value)
        for value in getattr(team_state.rotation, "starter_ids", ())
        if player_id(value) in set(rotation_ids)
    ]
    starter_fill = sorted(
        (pid for pid in rotation_ids if pid not in set(prior_starters)),
        key=lambda pid: (-float(getattr(state.players[pid], "overall_rating", 0) or 0), pid),
    )
    starter_ids = tuple(dedupe((*prior_starters, *starter_fill))[:5])
    if len(starter_ids) != 5:
        raise OffseasonTransactionApplicationError(f"{code} could not retain five starters.")
    regulation = int(getattr(state.settings, "regulation_minutes", 48) or 48)
    total_minutes = float(regulation * 5)
    if len(rotation_ids) == 5:
        minutes = {pid: total_minutes / 5 for pid in rotation_ids}
    else:
        starter_minutes = min(36.0, total_minutes / 5)
        minutes = {pid: starter_minutes for pid in starter_ids}
        bench = [pid for pid in rotation_ids if pid not in set(starter_ids)]
        remaining_minutes = total_minutes - sum(minutes.values())
        minutes.update({pid: remaining_minutes / len(bench) for pid in bench})
    team_state.rotation = RotationState(
        starter_ids=starter_ids,
        rotation_player_ids=rotation_ids,
        minutes_targets=minutes,
    )
    team_state.active_player_ids = rotation_ids
    team_state.inactive_player_ids = tuple(pid for pid in roster if pid not in set(rotation_ids))


def validate_offseason_transition_state(state: Any) -> dict[str, bool]:
    teams = getattr(state, "teams", {})
    players = getattr(state, "players", {})
    roster = [pid for row in teams.values() for pid in row.roster_player_ids]
    free_agents = set(getattr(state, "free_agent_player_ids", ()))
    checks = {
        "exactly_30_teams": len(teams) == 30,
        "team_roster_ids_unique": len(roster) == len(set(roster)),
        "free_agents_not_on_rosters": not free_agents.intersection(roster),
        "all_players_accounted_for": set(roster).union(free_agents) == set(players),
        "offseason_rosters_between_5_and_21": all(5 <= len(row.roster_player_ids) <= 21 for row in teams.values()),
        "rotations_are_roster_subsets": all(set(row.rotation.rotation_player_ids).issubset(row.roster_player_ids) for row in teams.values()),
        "all_teams_have_five_starters": all(len(row.rotation.starter_ids) == 5 for row in teams.values()),
        "rotation_minutes_reconcile": all(abs(sum(row.rotation.minutes_targets.values()) - float(getattr(state.settings, "regulation_minutes", 48) * 5)) <= 0.1 for row in teams.values()),
    }
    failed = [key for key, passed in checks.items() if not passed]
    if failed:
        raise OffseasonTransactionApplicationError(
            "Offseason transition validation failed: " + ", ".join(failed)
        )
    return checks


def materialize_zero_game_population(
    state: Any,
    *,
    runtime: Any,
    final_owner: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Hydrate the exact audited five-player supplement on a cloned state."""
    players = getattr(state, "players", None)
    if not isinstance(players, dict):
        raise OffseasonTransactionApplicationError("Simulation state lacks a mutable player map.")

    missing = set(final_owner) - set(players)
    expected = set(POPULATION_SUPPLEMENT)
    if not missing:
        return []
    if missing != expected:
        raise OffseasonTransactionApplicationError(
            "Unexpected ownership/state population gap. "
            f"Expected either none or the exact audited five; found {sorted(missing)}"
        )

    import simulation_league_state_v1 as league_state_module

    ContractState = league_state_module.ContractState
    InjuryState = league_state_module.InjuryState
    PlayerSeasonTotals = league_state_module.PlayerSeasonTotals
    SimulationPlayerState = getattr(
        league_state_module,
        "SimulationPlayerState",
        getattr(league_state_module, "PlayerState", None),
    )
    if SimulationPlayerState is None:
        raise OffseasonTransactionApplicationError(
            "Simulation player-state class is unavailable."
        )
    injuries = getattr(state, "injuries", None)
    totals = getattr(state, "player_season_totals", None)
    if not isinstance(injuries, dict) or not isinstance(totals, dict):
        raise OffseasonTransactionApplicationError(
            "Simulation state lacks player-keyed injury or season-total maps."
        )

    materialized: list[dict[str, Any]] = []
    for pid in sorted(expected):
        owner = final_owner[pid]
        profile = POPULATION_SUPPLEMENT[pid]
        skill_ratings = dict(zip(DEVELOPMENT_SKILL_FIELDS, profile["skill_ratings"]))
        stat_factors = {field: 1.0 for field in DEVELOPMENT_STAT_FACTORS}
        baseline_per_36 = dict(zip(BASELINE_PER_36_FIELDS, profile["baseline_per_36"]))
        initial_salary = profile["initial_salary"]
        player = SimulationPlayerState(
            player_id=pid,
            player_name=profile["player_name"],
            team_abbreviation=owner,
            roster_status="active_roster" if owner else "free_agent",
            overall_rating=float(profile["overall_rating"]),
            position=profile["position"],
            synthetic=False,
            rating_source=profile["evidence_method"],
            two_way=False,
            contract=ContractState(
                status="under_contract" if owner else "free_agent_pool",
                salary=float(initial_salary) if initial_salary is not None else None,
                years_remaining=1 if owner else None,
                option_type="",
                guaranteed=True if owner else None,
            ),
            age=float(profile["age"]),
            potential_rating=float(profile["potential_rating"]),
            future_outlook_rating=float(profile["future_outlook_rating"]),
            development_direction="Stable",
            profile_reliability=float(profile["profile_reliability"]),
            skill_ratings=skill_ratings,
            stat_factors=stat_factors,
            baseline_per_36=baseline_per_36,
            development_history=[{
                "event": "zero_game_population_bridge",
                "season": "2026-27",
                "method": profile["evidence_method"],
                "source_url": profile["source_url"],
                "calibration": "explicit_conservative_bridge_v1",
                "canonical_mutation": False,
            }],
        )
        if clean(getattr(player, "position", "")).upper() in {"", "UNK"}:
            raise OffseasonTransactionApplicationError(
                f"Canonical position evidence is unresolved for zero-game supplement {pid}."
            )
        age = number(getattr(player, "age", None))
        if age is None or not 18 <= age <= 50:
            raise OffseasonTransactionApplicationError(
                f"Canonical development age is unresolved for zero-game supplement {pid}."
            )
        if (
            set(player.skill_ratings) != set(DEVELOPMENT_SKILL_FIELDS)
            or set(player.stat_factors) != set(DEVELOPMENT_STAT_FACTORS)
            or set(player.baseline_per_36) != set(BASELINE_PER_36_FIELDS)
        ):
            raise OffseasonTransactionApplicationError(
                f"Development profile schema is incomplete for zero-game supplement {pid}."
            )

        players[pid] = player
        injuries[pid] = InjuryState(player_id=pid)
        totals[pid] = PlayerSeasonTotals(player_id=pid)
        materialized.append({
            "player_id": pid,
            "player_name": profile["player_name"],
            "final_owner": owner or "FA",
            "position": clean(player.position),
            "age_2026_27": float(player.age),
            "overall_rating": float(player.overall_rating),
            "rating_source": clean(player.rating_source),
            "profile_reliability": float(player.profile_reliability),
            "potential_rating": float(player.potential_rating),
            "future_outlook_rating": float(player.future_outlook_rating),
            "initial_contract_salary_2026_27": initial_salary,
            "skill_ratings_json": json.dumps(skill_ratings, sort_keys=True),
            "stat_factors_json": json.dumps(stat_factors, sort_keys=True),
            "baseline_per_36_json": json.dumps(baseline_per_36, sort_keys=True),
            "evidence_method": profile["evidence_method"],
            "source_url": profile["source_url"],
            "calibration_label": "explicit_conservative_bridge_v1",
            "materialized_on_clone": True,
            "materialized_on_canonical": False,
        })

    try:
        from simulation_injury_fatigue_v1 import ensure_injury_fatigue_state
    except ImportError:
        ensure_injury_fatigue_state = None
    if ensure_injury_fatigue_state is not None:
        ensure_injury_fatigue_state(state)

    health_profiles = getattr(state, "injury_fatigue_profiles", None)
    if health_profiles is not None and set(health_profiles) != set(players):
        raise OffseasonTransactionApplicationError(
            "Optional injury/fatigue profiles do not cover the hydrated population."
        )

    if set(players) != set(final_owner):
        raise OffseasonTransactionApplicationError(
            f"Clone population did not reconcile to the exact 587-player ledger: {len(players)}"
        )
    return materialized


def _snapshot_team_rows(snapshot: Any) -> dict[str, Any]:
    return {
        team(getattr(row, "team", "")): row
        for row in getattr(snapshot, "team_financials", ())
    }


def build_offseason_transaction_candidates(
    simulation_state: Any,
    trade_state: Any,
    *,
    runtime: Any,
    owner_ledger_rows: list[dict[str, str]],
    market_rows: list[dict[str, str]],
    automatic_decisions: list[dict[str, str]],
    pending_decisions: list[dict[str, str]],
) -> dict[str, Any]:
    if simulation_state is None or trade_state is None:
        raise OffseasonTransactionApplicationError("Both durable state branches are required.")
    decisions = resolve_decisions(automatic_decisions, pending_decisions)
    decision_by_id = {player_id(row.get("player_id")): row for row in decisions}
    owner_rows = {player_id(row.get("player_id")): row for row in owner_ledger_rows}
    market_by_id = {player_id(row.get("player_id")): row for row in market_rows}
    if len(owner_rows) != 587 or len(market_by_id) != 226:
        raise OffseasonTransactionApplicationError(
            f"Expected 587 ownership rows and 226 market rows; got {len(owner_rows)} and {len(market_by_id)}."
        )

    final_owner: dict[str, str] = {}
    for pid, row in owner_rows.items():
        final_owner[pid] = team(row.get("owner_after_automatic"))
    final_owner["1631159"] = "CHI"
    final_owner["1631338"] = ""
    market_ids = set(market_by_id)
    if {pid for pid, owner in final_owner.items() if not owner} != market_ids:
        raise OffseasonTransactionApplicationError("Final ownership ledger does not exactly reproduce the 226-player market.")

    simulation_candidate = copy.deepcopy(simulation_state)
    players = getattr(simulation_candidate, "players", None)
    teams = getattr(simulation_candidate, "teams", None)
    if not isinstance(players, dict) or not isinstance(teams, dict):
        raise OffseasonTransactionApplicationError("Simulation state lacks mutable player/team maps.")
    source_population_count = len(players)
    materialized_players = materialize_zero_game_population(
        simulation_candidate,
        runtime=runtime,
        final_owner=final_owner,
    )
    players = simulation_candidate.players

    ledger_ids = set(final_owner)
    for team_state in teams.values():
        team_state.roster_player_ids = dedupe(
            pid for pid in getattr(team_state, "roster_player_ids", ()) if player_id(pid) not in ledger_ids
        )
        team_state.active_player_ids = dedupe(
            pid for pid in getattr(team_state, "active_player_ids", ()) if player_id(pid) not in ledger_ids
        )
        team_state.inactive_player_ids = dedupe(
            pid for pid in getattr(team_state, "inactive_player_ids", ()) if player_id(pid) not in ledger_ids
        )

    incoming_by_team: dict[str, list[str]] = {team(raw): [] for raw in teams}
    for pid in owner_rows:
        owner = final_owner[pid]
        player = players[pid]
        if owner:
            if owner not in teams:
                raise OffseasonTransactionApplicationError(f"Unknown final owner {owner} for {pid}.")
            teams[owner].roster_player_ids = dedupe((*teams[owner].roster_player_ids, pid))
            player.team_abbreviation = owner
            player.roster_status = "active_roster"
            incoming_by_team[owner].append(pid)
        else:
            player.team_abbreviation = ""
            player.roster_status = "free_agent"

        decision = decision_by_id.get(pid)
        if decision is not None:
            recommendation = clean(decision.get("recommendation")).lower()
            set_contract(
                player,
                recommendation=recommendation,
                salary=decision_salary(decision),
                category=clean(decision.get("decision_category")),
            )
        elif not owner:
            set_contract(player, recommendation="decline", salary=None, category="")

    simulation_candidate.free_agent_player_ids = tuple(
        pid for pid in owner_rows if pid in market_ids
    )

    for raw_team in sorted(teams):
        code = team(raw_team)
        repair_offseason_rotation(simulation_candidate, code, tuple(incoming_by_team.get(code, ())))

    market_amount_candidates: list[dict[str, Any]] = []
    for pid, row in market_by_id.items():
        amount = number(row.get("final_free_agent_amount_2026_27"))
        market_amount_candidates.append({
            "player_id": pid,
            "player_name": clean(row.get("player_name")),
            "prior_team": team(row.get("prior_team")),
            "rights_classification": clean(row.get("rights_classification")),
            "free_agent_amount_2026_27": amount,
            "amount_status": clean(row.get("amount_status")),
            "cap_hold_applied": False,
            "rights_decision_applied": False,
            "qo_decision_applied": False,
        })
    setattr(simulation_candidate, MARKET_AMOUNT_ATTR, copy.deepcopy(market_amount_candidates))

    validate_offseason_transition_state(simulation_candidate)

    from franchise_financial_cba_bridge_v1 import build_franchise_financial_snapshot
    source_financial = build_franchise_financial_snapshot(runtime, simulation_state)
    candidate_financial = build_franchise_financial_snapshot(runtime, simulation_candidate)
    source_teams = _snapshot_team_rows(source_financial)
    candidate_teams = _snapshot_team_rows(candidate_financial)

    trade_candidate = copy.deepcopy(trade_state)
    trade_owners = getattr(trade_candidate, "player_team_by_id", None)
    trade_financials = getattr(trade_candidate, "team_financials", None)
    if not isinstance(trade_owners, dict) or not isinstance(trade_financials, dict):
        raise OffseasonTransactionApplicationError("Trade state lacks ownership/financial maps.")
    missing_trade_players = sorted(set(final_owner) - set(trade_owners))
    missing_trade_set = set(missing_trade_players)
    if missing_trade_set and missing_trade_set != set(POPULATION_SUPPLEMENT):
        raise OffseasonTransactionApplicationError(
            "Unexpected Trade Machine population gap: " + repr(missing_trade_players)
        )
    for pid, owner in final_owner.items():
        trade_owners[pid] = owner

    financial_deltas: list[dict[str, Any]] = []
    for code in sorted(candidate_teams):
        if code not in trade_financials or code not in source_teams:
            raise OffseasonTransactionApplicationError(f"Missing financial state for {code}.")
        source_row = source_teams[code]
        candidate_row = candidate_teams[code]
        delta = round(float(candidate_row.modeled_team_salary) - float(source_row.modeled_team_salary), 2)
        financial = trade_financials[code]
        before_team_salary = number(getattr(financial, "team_salary", None))
        before_apron_salary = number(getattr(financial, "apron_salary", None))
        if before_team_salary is None or before_apron_salary is None:
            raise OffseasonTransactionApplicationError(f"Trade financial base is not deterministic for {code}.")
        financial.team_salary = round(before_team_salary + delta, 2)
        financial.apron_salary = round(before_apron_salary + delta, 2)
        financial.standard_contract_count = int(candidate_row.standard_contract_count)
        financial.two_way_contract_count = int(candidate_row.two_way_contract_count)
        financial_deltas.append({
            "team": code,
            "source_modeled_contract_payroll": float(source_row.modeled_team_salary),
            "candidate_modeled_contract_payroll": float(candidate_row.modeled_team_salary),
            "contract_payroll_delta": delta,
            "trade_team_salary_before": before_team_salary,
            "trade_team_salary_after": float(financial.team_salary),
            "standard_contract_count_after": int(financial.standard_contract_count),
            "two_way_contract_count_after": int(financial.two_way_contract_count),
            "free_agent_amounts_applied": 0,
        })

    snapshots = list(getattr(trade_candidate, "undo_stack", ()) or ())
    initial_snapshot = getattr(trade_candidate, "initial_snapshot", None)
    if initial_snapshot is not None:
        snapshots.append(initial_snapshot)
    for snapshot in snapshots:
        ownership = getattr(snapshot, "player_team_by_id", None)
        if not isinstance(ownership, dict):
            raise OffseasonTransactionApplicationError("Trade snapshot lacks player ownership map.")
        for pid, owner in final_owner.items():
            ownership[pid] = owner
        snapshot.team_financials = copy.deepcopy(trade_financials)

    revision_before = int(getattr(trade_candidate, "state_revision", 0) or 0)
    setattr(trade_candidate, "state_revision", revision_before + 1)
    overrides = {
        pid: {
            "player_id": pid,
            "recommendation": clean(row.get("recommendation")).lower(),
            "decision_category": clean(row.get("decision_category")),
            "owner_before": team(row.get("owner_before") or row.get("team_abbreviation")),
            "owner_after": final_owner[pid],
            "salary_2026_27": decision_salary(row),
        }
        for pid, row in decision_by_id.items()
    }
    setattr(trade_candidate, TRADE_OVERRIDES_ATTR, copy.deepcopy(overrides))
    setattr(trade_candidate, MARKET_AMOUNT_ATTR, copy.deepcopy(market_amount_candidates))

    event = {
        "transaction_id": "OFFSEASON-LIFECYCLE-2026-0001",
        "version": VERSION,
        "decision_count": 111,
        "market_count": 226,
        "owner_ledger_count": 587,
        "decision_distribution": dict(Counter(clean(row.get("recommendation")).lower() for row in decisions)),
        "cap_holds_applied": 0,
        "qo_decisions_applied": 0,
        "rights_decisions_applied": 0,
    }
    setattr(trade_candidate, TRADE_HISTORY_ATTR, [copy.deepcopy(event)])
    setattr(simulation_candidate, SIM_REVISION_ATTR, 1)
    setattr(simulation_candidate, SIM_HISTORY_ATTR, [copy.deepcopy(event)])
    if hasattr(simulation_candidate, "source_league_state_revision"):
        simulation_candidate.source_league_state_revision = int(getattr(trade_candidate, "state_revision", 0) or 0)
    if hasattr(simulation_candidate, "source_transaction_count"):
        simulation_candidate.source_transaction_count = len(list(getattr(trade_candidate, "transaction_history", ()) or ()))

    from freeform_trade_machine_engine_v3 import load_runtime_data
    from mutable_league_state_v1 import validate_state
    validate_state(trade_candidate, load_runtime_data())
    validate_offseason_transition_state(simulation_candidate)

    final_roster_owners = roster_owner_map(simulation_candidate)
    ownership_rows = [{
        "player_id": pid,
        "player_name": clean(getattr(players[pid], "player_name", "")),
        "owner_before_automatic": team(owner_rows[pid].get("owner_before_automatic")),
        "owner_after_automatic": team(owner_rows[pid].get("owner_after_automatic")),
        "final_owner": final_owner[pid] or "FA",
        "simulation_owner": final_roster_owners.get(pid, "") or "FA",
        "trade_state_owner": team(trade_owners.get(pid)) or "FA",
        "final_market_member": pid in market_ids,
    } for pid in owner_rows]

    transaction_rows: list[dict[str, Any]] = []
    for pid, row in decision_by_id.items():
        recommendation = clean(row.get("recommendation")).lower()
        transaction_rows.append({
            "transaction_id": f"OFFSEASON-2026-{len(transaction_rows) + 1:03d}",
            "player_id": pid,
            "player_name": clean(row.get("player_name")),
            "decision_category": clean(row.get("decision_category")),
            "recommendation": recommendation,
            "owner_before": team(row.get("owner_before") or row.get("team_abbreviation")) or "FA",
            "owner_after": final_owner[pid] or "FA",
            "salary_2026_27": decision_salary(row) if recommendation in {"exercise", "retain"} else None,
            "entered_final_market": pid in market_ids,
            "applied_to_clone": True,
            "applied_to_canonical": False,
        })

    return {
        "simulation_candidate": simulation_candidate,
        "trade_candidate": trade_candidate,
        "resolved_decisions": transaction_rows,
        "ownership_rows": ownership_rows,
        "financial_deltas": financial_deltas,
        "market_amount_candidates": market_amount_candidates,
        "final_owner": final_owner,
        "source_simulation_digest": object_digest(simulation_state),
        "candidate_simulation_digest": object_digest(simulation_candidate),
        "source_trade_digest": object_digest(trade_state),
        "candidate_trade_digest": object_digest(trade_candidate),
        "trade_revision_before": revision_before,
        "trade_revision_after": int(getattr(trade_candidate, "state_revision", 0) or 0),
        "undo_snapshots_rebased": len(list(getattr(trade_candidate, "undo_stack", ()) or ())),
        "initial_snapshot_rebased": initial_snapshot is not None,
        "source_population_count": source_population_count,
        "candidate_population_count": len(players),
        "materialized_population_supplement": materialized_players,
        "trade_population_supplement_ids": missing_trade_players,
    }
