from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping

from simulation_league_state_v1 import (
    ContractState,
    InjuryState,
    PlayerSeasonTotals,
    SimulationPlayerState,
    validate_simulation_league_state,
)


UNDRAFTED_ROOKIE_FA_BRIDGE_VERSION = (
    "franchise-undrafted-rookie-free-agent-v1-2026-09-30"
)

DRAFT_STATE_ATTR = "franchise_draft_state_v1"
UNDRAFTED_FA_HISTORY_ATTR = "franchise_undrafted_rookie_fa_history_v1"
UNDRAFTED_FA_MARKER_ATTR = "franchise_undrafted_rookie_fa_bridge_v1"


@dataclass(frozen=True)
class UndraftedRookieFreeAgent:
    player_id: str
    player_name: str
    position: str
    age: float | None
    overall_rating: float
    potential_rating: float
    draft_year: int
    draft_class_rank: int | None


@dataclass(frozen=True)
class UndraftedRookieFreeAgentResult:
    version: str
    source_season: str
    target_season: str
    draft_year: int
    undrafted_prospects_available: int
    players_materialized: tuple[UndraftedRookieFreeAgent, ...]
    skipped_existing_player_ids: tuple[str, ...]
    simulation_state: Any


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _finite(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result


def _stat_factors_from_skills(skills: Mapping[str, Any]) -> dict[str, float]:
    def clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))

    scoring = _finite(skills.get("scoring_rating"), 60.0)
    shooting = _finite(skills.get("shooting_rating"), 60.0)
    playmaking = _finite(skills.get("playmaking_rating"), 60.0)
    defense = _finite(skills.get("defense_rating"), 60.0)
    rebounding = _finite(skills.get("rebounding_rating"), 60.0)

    return {
        "points": round(clamp(scoring / 75.0, 0.65, 1.35), 4),
        "rebounds": round(clamp(rebounding / 75.0, 0.65, 1.35), 4),
        "assists": round(clamp(playmaking / 75.0, 0.65, 1.35), 4),
        "steals": round(clamp(defense / 75.0, 0.65, 1.35), 4),
        "blocks": round(clamp(defense / 75.0, 0.65, 1.35), 4),
        "turnovers": round(clamp(1.12 - playmaking / 750.0, 0.8, 1.2), 4),
        "fouls": round(clamp(1.12 - defense / 800.0, 0.82, 1.18), 4),
        "three_attempts": round(clamp(shooting / 75.0, 0.65, 1.35), 4),
        "free_throw_attempts": round(clamp(scoring / 75.0, 0.65, 1.35), 4),
    }


def _raw_completed_draft(state: Any) -> dict[str, Any] | None:
    value = getattr(state, DRAFT_STATE_ATTR, None)
    if not isinstance(value, dict):
        return None
    if _clean(value.get("phase")).lower() != "draft_complete":
        return None

    target = _clean(value.get("target_season"))
    live_season = _clean(getattr(getattr(state, "settings", None), "season_label", ""))
    if not target or target != live_season:
        return None

    prospects = value.get("prospects")
    if not isinstance(prospects, list):
        return None
    return value


def _materialize_player(
    state: Any,
    *,
    prospect: Mapping[str, Any],
    draft_year: int,
    target_season: str,
) -> UndraftedRookieFreeAgent:
    player_id = _clean(prospect.get("prospect_id"))
    if not player_id:
        raise RuntimeError("Undrafted prospect is missing prospect_id.")

    player_name = _clean(prospect.get("player_name")) or player_id
    position = _clean(prospect.get("position")) or "UNK"
    overall = _finite(prospect.get("hidden_overall"), 55.0)
    potential = max(overall, _finite(prospect.get("hidden_potential"), overall))
    age_raw = prospect.get("age")
    age = None if age_raw is None else _finite(age_raw, 20.0)

    skills = dict(prospect.get("skills") or {})
    baseline_per_36 = dict(prospect.get("baseline_per_36") or {})
    confidence = max(0.0, min(100.0, _finite(prospect.get("scouting_confidence"), 50.0)))

    player = SimulationPlayerState(
        player_id=player_id,
        player_name=player_name,
        team_abbreviation="",
        roster_status="free_agent",
        overall_rating=overall,
        position=position,
        # Materialization occurs after the season transition, so this player
        # does not need the drafted-rookie synthetic guard used pre-transition.
        synthetic=False,
        rating_source="generated-undrafted-rookie-v1",
        two_way=False,
        contract=ContractState(
            status="free_agent_pool",
            salary=None,
            years_remaining=0,
            option_type="",
            guaranteed=None,
        ),
        age=age,
        potential_rating=potential,
        future_outlook_rating=potential,
        development_direction="Rising",
        profile_reliability=confidence / 100.0,
        skill_ratings=skills,
        stat_factors=_stat_factors_from_skills(skills),
        baseline_per_36=baseline_per_36,
        development_history=[
            {
                "event": "undrafted_rookie_entered_free_agency",
                "draft_year": int(draft_year),
                "target_season": target_season,
                "version": UNDRAFTED_ROOKIE_FA_BRIDGE_VERSION,
            }
        ],
    )

    setattr(player, "draft_year", int(draft_year))
    setattr(player, "draft_round", None)
    setattr(player, "draft_pick", None)
    setattr(player, "draft_round_pick", None)
    setattr(player, "drafted_by", "")
    setattr(player, "undrafted_rookie", True)
    setattr(player, "rookie_season", target_season)
    setattr(player, "rookie_season_start", int(draft_year))
    setattr(player, "years_of_service", 0)
    setattr(player, "rookie_eligible", True)
    setattr(player, "generated_prospect", True)
    setattr(player, "career_metadata_source", "generated_undrafted_rookie_v1")
    setattr(player, "draft_class_id", f"DRAFT-{int(draft_year)}")

    setattr(player, "live_contract_cap_hit", 0.0)
    setattr(player, "live_contract_guaranteed_amount", 0.0)
    setattr(player, "live_contract_total_value", None)
    setattr(player, "live_contract_guarantee_status", "not_under_contract")
    setattr(player, "live_contract_signing_method", "")
    setattr(player, "live_contract_evidence_status", "generated_undrafted_free_agent")

    state.players[player_id] = player
    state.player_season_totals.setdefault(
        player_id,
        PlayerSeasonTotals(player_id=player_id),
    )
    state.injuries[player_id] = InjuryState(player_id=player_id)

    from simulation_injury_fatigue_v1 import synchronize_injury_profile
    synchronize_injury_profile(state, player_id)

    free_agents = list(tuple(getattr(state, "free_agent_player_ids", ()) or ()))
    if player_id not in free_agents:
        free_agents.append(player_id)
    state.free_agent_player_ids = tuple(free_agents)

    rank_raw = prospect.get("big_board_rank")
    try:
        rank = int(rank_raw) if rank_raw is not None else None
    except (TypeError, ValueError):
        rank = None

    return UndraftedRookieFreeAgent(
        player_id=player_id,
        player_name=player_name,
        position=position,
        age=age,
        overall_rating=overall,
        potential_rating=potential,
        draft_year=int(draft_year),
        draft_class_rank=rank,
    )


def materialize_undrafted_rookie_free_agents_after_transition(
    state: Any,
) -> tuple[Any, UndraftedRookieFreeAgentResult]:
    """Create real free-agent player state for the undrafted draft-class tail.

    The Draft produces an 80-prospect class but only 60 draft selections.
    Previously, the undrafted 20 remained only inside archived Draft data and
    never entered the franchise player/free-agent universe.

    This runs only after the season transition so rookies do not receive a
    pre-rookie development cycle.
    """
    candidate = copy.deepcopy(state)
    current = _raw_completed_draft(candidate)

    target_season = _clean(
        getattr(getattr(candidate, "settings", None), "season_label", "")
    )
    if current is None:
        result = UndraftedRookieFreeAgentResult(
            version=UNDRAFTED_ROOKIE_FA_BRIDGE_VERSION,
            source_season="",
            target_season=target_season,
            draft_year=0,
            undrafted_prospects_available=0,
            players_materialized=(),
            skipped_existing_player_ids=(),
            simulation_state=candidate,
        )
        return candidate, result

    source_season = _clean(current.get("source_season"))
    try:
        draft_year = int(current.get("draft_year"))
    except (TypeError, ValueError):
        raise RuntimeError("Completed Draft is missing a valid draft_year.")

    undrafted = [
        row
        for row in current.get("prospects", [])
        if isinstance(row, Mapping)
        and not bool(row.get("drafted", False))
        and _clean(row.get("prospect_id"))
    ]

    materialized: list[UndraftedRookieFreeAgent] = []
    skipped_existing: list[str] = []

    for prospect in sorted(
        undrafted,
        key=lambda row: (
            int(row.get("big_board_rank", 9999) or 9999),
            _clean(row.get("prospect_id")),
        ),
    ):
        player_id = _clean(prospect.get("prospect_id"))
        if player_id in candidate.players:
            skipped_existing.append(player_id)
            continue

        materialized.append(
            _materialize_player(
                candidate,
                prospect=prospect,
                draft_year=draft_year,
                target_season=target_season,
            )
        )

    history = list(getattr(candidate, UNDRAFTED_FA_HISTORY_ATTR, []) or [])
    history.append(
        {
            "version": UNDRAFTED_ROOKIE_FA_BRIDGE_VERSION,
            "source_season": source_season,
            "target_season": target_season,
            "draft_year": draft_year,
            "undrafted_prospects_available": len(undrafted),
            "players_materialized": len(materialized),
            "player_ids": tuple(row.player_id for row in materialized),
        }
    )
    setattr(candidate, UNDRAFTED_FA_HISTORY_ATTR, history)
    setattr(
        candidate,
        UNDRAFTED_FA_MARKER_ATTR,
        {
            "version": UNDRAFTED_ROOKIE_FA_BRIDGE_VERSION,
            "draft_year": draft_year,
            "target_season": target_season,
            "undrafted_prospects_available": len(undrafted),
            "players_materialized": len(materialized),
            "skipped_existing_player_ids": tuple(sorted(skipped_existing)),
        },
    )

    validate_simulation_league_state(candidate)

    return candidate, UndraftedRookieFreeAgentResult(
        version=UNDRAFTED_ROOKIE_FA_BRIDGE_VERSION,
        source_season=source_season,
        target_season=target_season,
        draft_year=draft_year,
        undrafted_prospects_available=len(undrafted),
        players_materialized=tuple(materialized),
        skipped_existing_player_ids=tuple(sorted(skipped_existing)),
        simulation_state=candidate,
    )
