from __future__ import annotations

import copy
import hashlib
import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from franchise_financial_cba_bridge_v1 import TWO_WAY_MAX
from simulation_league_state_v1 import validate_simulation_league_state


CPU_TWO_WAY_ROSTER_COMPLETION_VERSION = (
    "franchise-cpu-two-way-roster-completion-v1-2026-09-30"
)

TWO_WAY_COMPLETION_ATTR = "franchise_cpu_two_way_roster_completion_v1"
TWO_WAY_HISTORY_ATTR = "franchise_two_way_signing_history_v1"


@dataclass(frozen=True)
class CPUTwoWaySigning:
    team: str
    player_id: str
    player_name: str
    age: float | None
    overall_rating: float
    potential_rating: float
    roster_count_after: int
    two_way_count_after: int


@dataclass(frozen=True)
class CPUTwoWayRosterCompletionResult:
    version: str
    target_slots_per_team: int
    controlled_teams: tuple[str, ...]
    eligible_free_agents_before: int
    teams_considered: int
    teams_filled_to_target: int
    signings: tuple[CPUTwoWaySigning, ...]
    unfilled_teams: tuple[str, ...]
    simulation_state: Any


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _finite(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _player_age(player: Any) -> float | None:
    try:
        value = float(getattr(player, "age", None))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _player_is_two_way(player: Any) -> bool:
    return bool(getattr(player, "two_way", False)) or (
        _clean(getattr(player, "roster_status", "")).lower() == "two_way"
    )


def _two_way_count(state: Any, team_code: str) -> int:
    team_state = state.teams[team_code]
    players = state.players
    return sum(
        1
        for player_id in tuple(getattr(team_state, "roster_player_ids", ()) or ())
        if player_id in players and _player_is_two_way(players[player_id])
    )


def _eligible_two_way_free_agent(player: Any) -> bool:
    if player is None:
        return False
    if bool(getattr(player, "synthetic", False)):
        return False
    if _player_is_two_way(player):
        return False
    if _team(getattr(player, "team_abbreviation", "")):
        return False

    roster_status = _clean(getattr(player, "roster_status", "")).lower()
    if roster_status not in {"free_agent", "free_agent_pool"}:
        return False

    contract = getattr(player, "contract", None)
    contract_status = _clean(getattr(contract, "status", "")).lower()
    if contract_status not in {"", "free_agent", "free_agent_pool"}:
        return False

    overall = _finite(getattr(player, "overall_rating", None), -1.0)
    potential = _finite(getattr(player, "potential_rating", None), overall)
    age = _player_age(player)

    # Two-way deals are a developmental path, not a way to warehouse stars or
    # established veterans. The simulator does not yet expose reliable NBA
    # service-year data for every generated player, so age/quality guardrails
    # provide a conservative franchise-era proxy.
    if overall < 55.0 or overall > 80.0:
        return False
    if age is not None and (age < 18.0 or age > 27.0):
        return False
    if age is None and overall > 74.0:
        return False
    if potential < 62.0:
        return False
    return True


def _position_bucket(value: Any) -> str:
    text = _clean(value).upper().replace("-", "/")
    for token in ("PG", "SG", "SF", "PF", "C"):
        if token in text:
            return token
    return "UNK"


def _team_position_counts(state: Any, team_code: str) -> dict[str, int]:
    counts = {key: 0 for key in ("PG", "SG", "SF", "PF", "C", "UNK")}
    team_state = state.teams[team_code]
    for player_id in tuple(getattr(team_state, "roster_player_ids", ()) or ()):
        player = state.players.get(player_id)
        if player is None or _player_is_two_way(player):
            continue
        bucket = _position_bucket(getattr(player, "position", ""))
        counts[bucket] = counts.get(bucket, 0) + 1
    return counts


def _stable_tiebreak(team_code: str, player_id: str) -> float:
    digest = hashlib.sha256(
        f"{team_code}|{player_id}".encode("utf-8")
    ).digest()
    raw = int.from_bytes(digest[:8], "big")
    return raw / float(2**64 - 1)


def _development_score(state: Any, team_code: str, player: Any) -> tuple[float, str]:
    overall = _finite(getattr(player, "overall_rating", None), 55.0)
    potential = _finite(getattr(player, "potential_rating", None), overall)
    future = _finite(getattr(player, "future_outlook_rating", None), potential)
    reliability = max(
        0.0,
        min(1.0, _finite(getattr(player, "profile_reliability", None), 0.5)),
    )
    age = _player_age(player)

    age_bonus = 0.0 if age is None else max(0.0, 27.0 - age) * 1.25
    upside = max(0.0, potential - overall)
    future_upside = max(0.0, future - overall)

    bucket = _position_bucket(getattr(player, "position", ""))
    position_counts = _team_position_counts(state, team_code)
    position_need_bonus = max(0.0, 3.0 - float(position_counts.get(bucket, 0))) * 1.5

    score = (
        overall * 0.45
        + potential * 0.35
        + future * 0.20
        + upside * 1.20
        + future_upside * 0.60
        + age_bonus
        + reliability * 1.5
        + position_need_bonus
        + _stable_tiebreak(team_code, _clean(getattr(player, "player_id", ""))) * 0.01
    )
    return score, _clean(getattr(player, "player_id", ""))


def _append_inactive(team_state: Any, player_id: str) -> None:
    current = list(tuple(getattr(team_state, "inactive_player_ids", ()) or ()))
    if player_id not in current:
        current.append(player_id)
    team_state.inactive_player_ids = tuple(current)


def _append_roster(team_state: Any, player_id: str) -> None:
    current = list(tuple(getattr(team_state, "roster_player_ids", ()) or ()))
    if player_id in current:
        raise RuntimeError(f"Two-way signing would duplicate rostered player {player_id}.")
    current.append(player_id)
    team_state.roster_player_ids = tuple(current)


def _convert_to_two_way(
    state: Any,
    *,
    team_code: str,
    player_id: str,
) -> CPUTwoWaySigning:
    player = state.players[player_id]
    team_state = state.teams[team_code]

    _append_roster(team_state, player_id)
    _append_inactive(team_state, player_id)

    player.team_abbreviation = team_code
    player.roster_status = "two_way"
    player.two_way = True

    contract = getattr(player, "contract", None)
    if contract is None:
        raise RuntimeError(f"Two-way target {player_id} lacks contract state.")
    contract.status = "two_way"
    contract.salary = 0.0
    contract.years_remaining = 1
    contract.option_type = ""
    contract.guaranteed = False

    setattr(player, "live_contract_cap_hit", 0.0)
    setattr(player, "live_contract_guaranteed_amount", 0.0)
    setattr(player, "live_contract_total_value", None)
    setattr(player, "live_contract_guarantee_status", "two_way")
    setattr(player, "live_contract_signing_method", "franchise_cpu_two_way")
    setattr(player, "live_contract_evidence_status", "franchise_generated_two_way")

    free_agents = [
        value
        for value in tuple(getattr(state, "free_agent_player_ids", ()) or ())
        if _clean(value) != player_id
    ]
    state.free_agent_player_ids = tuple(free_agents)

    history = list(getattr(player, "development_history", []) or [])
    history.append(
        {
            "event": "cpu_two_way_signing",
            "season": _clean(getattr(getattr(state, "settings", None), "season_label", "")),
            "team": team_code,
            "version": CPU_TWO_WAY_ROSTER_COMPLETION_VERSION,
            "canonical_mutation": True,
        }
    )
    player.development_history = history

    return CPUTwoWaySigning(
        team=team_code,
        player_id=player_id,
        player_name=_clean(getattr(player, "player_name", "")) or player_id,
        age=_player_age(player),
        overall_rating=_finite(getattr(player, "overall_rating", None), 0.0),
        potential_rating=_finite(
            getattr(player, "potential_rating", None),
            _finite(getattr(player, "overall_rating", None), 0.0),
        ),
        roster_count_after=len(tuple(getattr(team_state, "roster_player_ids", ()) or ())),
        two_way_count_after=_two_way_count(state, team_code),
    )


def complete_cpu_two_way_rosters_at_boundary(
    state: Any,
    *,
    controlled_teams: Iterable[str] = (),
    target_slots_per_team: int = TWO_WAY_MAX,
) -> tuple[Any, CPUTwoWayRosterCompletionResult]:
    """Fill separate CPU two-way slots on the regular-season boundary copy.

    This function is intentionally independent of standard Free Agency. It never
    changes standard-contract counts, salary matching, rotations, or user teams.
    The returned state is a deep copy so the approved transition preview remains
    unchanged until the atomic boundary candidate is built.
    """
    target = int(target_slots_per_team)
    if target < 0 or target > int(TWO_WAY_MAX):
        raise ValueError(
            f"target_slots_per_team must be between 0 and {int(TWO_WAY_MAX)}."
        )

    candidate = copy.deepcopy(state)
    controlled = tuple(
        sorted({_team(value) for value in controlled_teams if _team(value)})
    )
    controlled_set = set(controlled)

    players = getattr(candidate, "players", None)
    teams = getattr(candidate, "teams", None)
    if not isinstance(players, Mapping) or not isinstance(teams, Mapping):
        raise RuntimeError("Two-way completion requires player/team maps.")

    free_agent_ids = tuple(getattr(candidate, "free_agent_player_ids", ()) or ())
    eligible_ids = [
        _clean(player_id)
        for player_id in free_agent_ids
        if _clean(player_id)
        and _clean(player_id) in players
        and _eligible_two_way_free_agent(players[_clean(player_id)])
    ]

    available = set(eligible_ids)
    signings: list[CPUTwoWaySigning] = []
    unfilled: list[str] = []
    filled_to_target = 0

    cpu_teams = tuple(
        team_code
        for team_code in sorted(_team(value) for value in teams)
        if team_code and team_code not in controlled_set
    )
    teams_considered = len(cpu_teams)

    # Allocate fairly across the league. Fill everyone's first open slot before
    # anyone receives a second, and everyone's second before anyone receives a
    # third. This prevents sorted-team order from exhausting a finite
    # developmental free-agent pool on the first handful of franchises.
    for desired_count in range(1, target + 1):
        if not available:
            break
        for team_code in cpu_teams:
            if not available:
                break
            if _two_way_count(candidate, team_code) >= desired_count:
                continue

            ranked = sorted(
                (
                    (_development_score(candidate, team_code, players[player_id]), player_id)
                    for player_id in available
                ),
                key=lambda item: (-item[0][0], item[0][1]),
            )
            if not ranked:
                break

            chosen = ranked[0][1]
            signing = _convert_to_two_way(
                candidate,
                team_code=team_code,
                player_id=chosen,
            )
            signings.append(signing)
            available.remove(chosen)

    for team_code in cpu_teams:
        if _two_way_count(candidate, team_code) == target:
            filled_to_target += 1
        else:
            unfilled.append(team_code)

    history = list(getattr(candidate, TWO_WAY_HISTORY_ATTR, []) or [])
    history.extend(
        {
            "version": CPU_TWO_WAY_ROSTER_COMPLETION_VERSION,
            "season_label": _clean(
                getattr(getattr(candidate, "settings", None), "season_label", "")
            ),
            "team": row.team,
            "player_id": row.player_id,
            "player_name": row.player_name,
            "age": row.age,
            "overall_rating": row.overall_rating,
            "potential_rating": row.potential_rating,
        }
        for row in signings
    )
    setattr(candidate, TWO_WAY_HISTORY_ATTR, history)

    marker = {
        "version": CPU_TWO_WAY_ROSTER_COMPLETION_VERSION,
        "target_slots_per_team": target,
        "controlled_teams": controlled,
        "eligible_free_agents_before": len(eligible_ids),
        "teams_considered": teams_considered,
        "teams_filled_to_target": filled_to_target,
        "signings": len(signings),
        "unfilled_teams": tuple(unfilled),
    }
    setattr(candidate, TWO_WAY_COMPLETION_ATTR, marker)

    validate_simulation_league_state(candidate)

    return candidate, CPUTwoWayRosterCompletionResult(
        version=CPU_TWO_WAY_ROSTER_COMPLETION_VERSION,
        target_slots_per_team=target,
        controlled_teams=controlled,
        eligible_free_agents_before=len(eligible_ids),
        teams_considered=teams_considered,
        teams_filled_to_target=filled_to_target,
        signings=tuple(signings),
        unfilled_teams=tuple(unfilled),
        simulation_state=candidate,
    )
