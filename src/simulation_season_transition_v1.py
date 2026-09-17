from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import (  # noqa: E402
    load_runtime_data,
)
from mutable_league_state_v1 import (  # noqa: E402
    create_league_state,
)
from player_development_engine_v1 import (  # noqa: E402
    ENGINE_VERSION as DEVELOPMENT_ENGINE_VERSION,
    DevelopmentConfig,
    PlayerDevelopmentProjection,
    next_season_label,
    project_player_development,
)
from franchise_staff_system_v1 import (  # noqa: E402
    STAFF_SYSTEM_VERSION,
    team_development_modifier,
)
from simulation_league_state_v1 import (  # noqa: E402
    AvailabilityStatus,
    BASELINE_PER_36_FIELDS,
    DEVELOPMENT_SKILL_FIELDS,
    DEVELOPMENT_STAT_FACTORS,
    InjuryState,
    LeaguePhase,
    PlayerSeasonTotals,
    RotationState,
    SeasonArchive,
    SimulationLeagueState,
    SimulationLeagueStateError,
    TeamStanding,
    create_simulation_league_state,
    minutes_targets,
    validate_simulation_league_state,
)
from state_runtime_adapter_v1 import (  # noqa: E402
    build_state_runtime,
)


TRANSITION_VERSION = (
    "simulation-season-transition-v1.1-2026-08-09"
)
SELF_TEST_REPORT = (
    OUTPUTS
    / "simulation_season_transition_v1_self_test.json"
)

BASELINE_FIELD_BY_FACTOR = {
    "points": "points_per_36",
    "rebounds": "rebounds_per_36",
    "assists": "assists_per_36",
    "steals": "steals_per_36",
    "blocks": "blocks_per_36",
    "turnovers": "turnovers_per_36",
    "fouls": "fouls_per_36",
    "three_attempts": "three_attempts_per_36",
    "free_throw_attempts": (
        "free_throw_attempts_per_36"
    ),
}


class SimulationSeasonTransitionError(RuntimeError):
    """Raised when the simulation cannot advance a season."""


@dataclass(frozen=True)
class SeasonTransitionResult:
    transition_version: str
    development_engine_version: str
    source_season: str
    target_season: str
    players_projected: int
    synthetic_players_skipped: int
    performance_signals_used: int
    average_overall_delta: float
    improved_players: int
    stable_players: int
    declined_players: int
    biggest_risers: tuple[dict[str, Any], ...]
    biggest_fallers: tuple[dict[str, Any], ...]
    archived_seasons: int
    transition_count: int
    archived_champion: str = ""
    archived_runner_up: str = ""
    archived_postseason_games: int = 0


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def clamp(
    value: float,
    minimum: float,
    maximum: float,
) -> float:
    return max(minimum, min(maximum, value))


def player_development_profile(
    state: SimulationLeagueState,
    player_id: str,
) -> dict[str, Any]:
    player = state.players[player_id]

    if player.synthetic:
        raise SimulationSeasonTransitionError(
            "Synthetic replacement players do not receive "
            "career development projections."
        )

    totals = state.player_season_totals.get(player_id)
    games_played = int(
        getattr(totals, "games_played", 0) or 0
    )
    total_minutes = float(
        getattr(totals, "minutes", 0.0) or 0.0
    )
    minutes_per_game = (
        total_minutes / games_played
        if games_played > 0
        else 0.0
    )

    years_of_service = getattr(
        player,
        "years_of_service",
        None,
    )
    if years_of_service is None:
        years_of_service = len(
            getattr(
                player,
                "development_history",
                [],
            )
            or []
        )

    # Generated players need a season-clock fallback because older draft
    # checkpoints may still carry years_of_service=0 after the rookie year.
    if bool(getattr(player, "generated_prospect", False)):
        draft_year = getattr(player, "draft_year", None)
        try:
            source_start = int(
                str(state.settings.season_label).split("-", 1)[0]
            )
            derived_service = max(
                0,
                source_start - int(draft_year) + 1,
            )
        except (TypeError, ValueError):
            derived_service = 0
        try:
            years_of_service = max(
                int(years_of_service),
                derived_service,
            )
        except (TypeError, ValueError):
            years_of_service = derived_service

    return {
        "player_id": player.player_id,
        "player_name": player.player_name,
        "position": player.position,
        "age_2026_27": player.age,
        "overall_rating": player.overall_rating,
        "potential_rating": (
            player.potential_rating
            if player.potential_rating is not None
            else player.overall_rating
        ),
        "future_outlook_rating": (
            player.future_outlook_rating
            if player.future_outlook_rating is not None
            else player.overall_rating
        ),
        "development_direction": (
            player.development_direction
            or "Stable"
        ),
        "profile_reliability": (
            player.profile_reliability
        ),
        "games_played": games_played,
        "total_minutes": total_minutes,
        "minutes_per_game": minutes_per_game,
        "years_of_service": years_of_service,
        "development_history_count": len(
            getattr(
                player,
                "development_history",
                [],
            )
            or []
        ),
        "draft_year": getattr(
            player,
            "draft_year",
            None,
        ),
        "draft_round": getattr(
            player,
            "draft_round",
            None,
        ),
        "draft_pick": getattr(
            player,
            "draft_pick",
            None,
        ),
        "generated_prospect": bool(
            getattr(
                player,
                "generated_prospect",
                False,
            )
        ),
        **{
            field_name: player.skill_ratings[
                field_name
            ]
            for field_name
            in DEVELOPMENT_SKILL_FIELDS
        },
        "stat_factors": dict(
            player.stat_factors
        ),
    }


def actual_per_36(
    total: float,
    minutes: float,
) -> float:
    if minutes <= 0:
        return 0.0
    return 36.0 * float(total) / float(minutes)


def performance_signal_from_totals(
    state: SimulationLeagueState,
    player_id: str,
) -> float:
    """Translate simulated production into a bounded development signal.

    The signal compares a compact per-36 production index with the
    player's pre-season baseline. Small samples are strongly shrunk.
    """
    player = state.players[player_id]
    totals = state.player_season_totals[player_id]

    if (
        totals.games_played < 10
        or totals.minutes < 150.0
    ):
        return 0.0

    actual = {
        "points_per_36": actual_per_36(
            totals.points,
            totals.minutes,
        ),
        "rebounds_per_36": actual_per_36(
            totals.rebounds,
            totals.minutes,
        ),
        "assists_per_36": actual_per_36(
            totals.assists,
            totals.minutes,
        ),
        "steals_per_36": actual_per_36(
            totals.steals,
            totals.minutes,
        ),
        "blocks_per_36": actual_per_36(
            totals.blocks,
            totals.minutes,
        ),
        "turnovers_per_36": actual_per_36(
            totals.turnovers,
            totals.minutes,
        ),
    }
    baseline = player.baseline_per_36

    weights = {
        "points_per_36": 1.00,
        "rebounds_per_36": 1.05,
        "assists_per_36": 1.35,
        "steals_per_36": 2.00,
        "blocks_per_36": 2.00,
        "turnovers_per_36": -1.20,
    }
    actual_index = sum(
        actual[field_name] * weight
        for field_name, weight in weights.items()
    )
    expected_index = sum(
        float(baseline.get(field_name, 0.0))
        * weight
        for field_name, weight in weights.items()
    )

    if expected_index <= 1.0:
        return 0.0

    relative_change = (
        actual_index - expected_index
    ) / max(abs(expected_index) * 0.25, 1.0)
    sample_weight = clamp(
        totals.minutes / 1500.0,
        0.0,
        1.0,
    )
    reliability = clamp(
        player.profile_reliability,
        0.10,
        1.0,
    )
    return round(
        clamp(
            relative_change
            * sample_weight
            * (0.55 + 0.45 * reliability),
            -1.0,
            1.0,
        ),
        4,
    )


def resolve_performance_signals(
    state: SimulationLeagueState,
    explicit_signals: Mapping[
        str,
        float,
    ] | None,
) -> dict[str, float]:
    resolved: dict[str, float] = {}

    for player_id, player in state.players.items():
        if player.synthetic:
            continue

        if (
            explicit_signals is not None
            and player_id in explicit_signals
        ):
            resolved[player_id] = round(
                clamp(
                    float(
                        explicit_signals[player_id]
                    ),
                    -1.0,
                    1.0,
                ),
                4,
            )
        else:
            resolved[player_id] = (
                performance_signal_from_totals(
                    state,
                    player_id,
                )
            )

    return resolved


def transition_preconditions(
    state: SimulationLeagueState,
    target_season: str,
) -> None:
    validate_simulation_league_state(state)

    if state.phase != LeaguePhase.OFFSEASON:
        raise SimulationSeasonTransitionError(
            "A season transition requires OFFSEASON phase."
        )

    expected_target = next_season_label(
        state.settings.season_label
    )
    if clean_text(target_season) != expected_target:
        raise SimulationSeasonTransitionError(
            "The target season must be the immediate next "
            f"season ({expected_target})."
        )

    incomplete = [
        game_id
        for game_id, game in state.schedule.items()
        if game.status.value != "completed"
    ]
    if incomplete:
        raise SimulationSeasonTransitionError(
            "The season still has incomplete scheduled games: "
            + ", ".join(incomplete[:8])
        )


def projected_baseline_per_36(
    current_baseline: Mapping[str, float],
    current_factors: Mapping[str, float],
    projected_factors: Mapping[str, float],
) -> dict[str, float]:
    output: dict[str, float] = {}

    for factor_name, field_name in (
        BASELINE_FIELD_BY_FACTOR.items()
    ):
        baseline = float(
            current_baseline.get(field_name, 0.0)
        )
        old_factor = float(
            current_factors.get(
                factor_name,
                1.0,
            )
        )
        new_factor = float(
            projected_factors.get(
                factor_name,
                old_factor,
            )
        )
        ratio = (
            new_factor / old_factor
            if old_factor > 0
            else 1.0
        )
        output[field_name] = round(
            max(0.0, baseline * ratio),
            4,
        )

    # Preserve a complete canonical field set even when a future
    # development engine leaves one tendency unchanged.
    return {
        field_name: float(
            output.get(
                field_name,
                current_baseline.get(
                    field_name,
                    0.0,
                ),
            )
        )
        for field_name in BASELINE_PER_36_FIELDS
    }


def refresh_team_rotations(
    state: SimulationLeagueState,
    *,
    team_abbreviations: tuple[str, ...] | None = None,
) -> None:
    """Rebuild selected rotations with protected quality plus youth opportunity.

    ``team_abbreviations`` keeps transaction previews copy-on-write: callers may
    repair one cloned team without mutating the shared team objects belonging to
    the rest of the source league. Omitting it preserves the original league-wide
    transition behavior.
    """

    selected_teams = (
        None
        if team_abbreviations is None
        else {
            str(team_abbreviation).strip().upper()
            for team_abbreviation in team_abbreviations
        }
    )

    # CPU_ROOKIE_USAGE_REALISM_V1_ROTATION_POLICY
    current_season_label = str(state.settings.season_label)
    durable_draft_meta: dict[str, dict[str, Any]] = {}
    for draft in list(getattr(state, "franchise_draft_history_v1", ()) or ()):
        if not isinstance(draft, dict):
            continue
        target_season = str(draft.get("target_season", "") or "").strip()
        for pick_row in list(draft.get("draft_order", ()) or ()):
            if not isinstance(pick_row, dict):
                continue
            prospect_id = str(pick_row.get("prospect_id", "") or "").strip()
            if not prospect_id:
                continue
            durable_draft_meta[prospect_id] = {
                "target_season": target_season,
                "draft_pick": pick_row.get("overall_pick"),
            }

    def draft_pick_number(player_id: str) -> int:
        player = state.players[player_id]
        raw = getattr(player, "draft_pick", None)
        if raw is None:
            raw = durable_draft_meta.get(player_id, {}).get("draft_pick")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 999

    def is_current_rookie(player_id: str) -> bool:
        player = state.players[player_id]
        rookie_season = str(getattr(player, "rookie_season", "") or "").strip()
        if rookie_season == current_season_label:
            return True
        return str(
            durable_draft_meta.get(player_id, {}).get("target_season", "") or ""
        ).strip() == current_season_label

    def youth_priority(player_id: str) -> float:
        player = state.players[player_id]
        age = float(
            player.age
            if player.age is not None
            else 99.0
        )
        if age > 24.0:
            return 0.0

        overall = float(player.overall_rating)
        potential = float(
            player.potential_rating
            if player.potential_rating is not None
            else overall
        )
        gap = max(0.0, potential - overall)

        years = getattr(
            player,
            "years_of_service",
            None,
        )
        if years is None:
            years = len(
                getattr(
                    player,
                    "development_history",
                    [],
                )
                or []
            )
        try:
            years = int(years)
        except (TypeError, ValueError):
            years = 99

        if bool(getattr(player, "generated_prospect", False)):
            draft_year = getattr(player, "draft_year", None)
            try:
                current_start = int(
                    str(state.settings.season_label).split("-", 1)[0]
                )
                years = max(
                    years,
                    current_start - int(draft_year),
                )
            except (TypeError, ValueError):
                pass

        if years > 3:
            return 0.0

        if age <= 21:
            age_bonus = 0.80
        elif age <= 23:
            age_bonus = 0.45
        else:
            age_bonus = 0.20

        gap_bonus = min(3.10, 0.22 * gap)

        pick_number = draft_pick_number(player_id)

        if pick_number <= 5:
            pedigree_bonus = 5.50
        elif pick_number <= 14:
            pedigree_bonus = 4.00
        elif pick_number <= 30:
            pedigree_bonus = 1.75
        else:
            pedigree_bonus = 0.0

        experience_decay = {
            0: 1.00,
            1: 1.00,
            2: 0.70,
            3: 0.35,
        }.get(years, 0.0)

        return (
            age_bonus
            + gap_bonus
            + pedigree_bonus * experience_decay
        )

    for team in state.teams.values():
        if (
            selected_teams is not None
            and team.team_abbreviation not in selected_teams
        ):
            continue
        ordered_by_overall = tuple(
            sorted(
                team.roster_player_ids,
                key=lambda player_id: (
                    -state.players[
                        player_id
                    ].overall_rating,
                    state.players[
                        player_id
                    ].player_name,
                    player_id,
                ),
            )
        )
        rotation_size = min(
            state.settings.rotation_size,
            len(ordered_by_overall),
        )

        if rotation_size < 5:
            if state.phase == LeaguePhase.OFFSEASON:
                # A completed-season offseason may temporarily contain fewer
                # than five signed players. Preserve exact ownership without
                # inventing user-team or CPU signings. Game-playing phases
                # still require a complete five-man lineup.
                partial_ids = tuple(ordered_by_overall)
                team.rotation = RotationState(
                    starter_ids=partial_ids,
                    rotation_player_ids=partial_ids,
                    minutes_targets={},
                )
                team.active_player_ids = partial_ids
                team.inactive_player_ids = ()
                continue
            raise SimulationSeasonTransitionError(
                f"{team.team_abbreviation} does not have "
                "five players after development."
            )

        starter_ids = ordered_by_overall[:5]

        # Keep the top seven players by current ability protected when a
        # standard 10-man rotation is available. The final development
        # slots may then go to a young high-upside player who is close
        # enough to the NBA rotation on current ability.
        protected_count = min(
            rotation_size,
            max(5, rotation_size - 3),
        )
        protected = list(
            ordered_by_overall[:protected_count]
        )
        remaining = [
            player_id
            for player_id in ordered_by_overall
            if player_id not in set(protected)
        ]
        remaining.sort(
            key=lambda player_id: (
                -(
                    float(
                        state.players[
                            player_id
                        ].overall_rating
                    )
                    + youth_priority(player_id)
                ),
                -float(
                    state.players[
                        player_id
                    ].overall_rating
                ),
                state.players[
                    player_id
                ].player_name,
                player_id,
            )
        )

        fringe_rating = float(
            state.players[ordered_by_overall[rotation_size - 1]].overall_rating
        )
        lottery_priority: list[str] = []
        for player_id in remaining:
            if not is_current_rookie(player_id):
                continue
            pick_number = draft_pick_number(player_id)
            if pick_number > 14:
                continue
            overall = float(state.players[player_id].overall_rating)
            if pick_number <= 5:
                minimum_playable = max(64.0, fringe_rating - 10.0)
            else:
                minimum_playable = max(66.0, fringe_rating - 7.0)
            if overall >= minimum_playable:
                lottery_priority.append(player_id)

        lottery_priority.sort(
            key=lambda player_id: (
                draft_pick_number(player_id),
                -float(state.players[player_id].overall_rating),
                state.players[player_id].player_name,
                player_id,
            )
        )
        if lottery_priority:
            lottery_set = set(lottery_priority)
            remaining = lottery_priority + [
                player_id
                for player_id in remaining
                if player_id not in lottery_set
            ]

        selected = protected + remaining[
            : max(
                0,
                rotation_size - len(protected),
            )
        ]

        # Starters stay ordered first. Bench order follows opportunity-
        # adjusted value so the default minute allocator gives meaningful
        # development reps to selected prospects.
        bench = [
            player_id
            for player_id in selected
            if player_id not in set(starter_ids)
        ]
        bench.sort(
            key=lambda player_id: (
                -(
                    float(
                        state.players[
                            player_id
                        ].overall_rating
                    )
                    + youth_priority(player_id)
                ),
                -float(
                    state.players[
                        player_id
                    ].overall_rating
                ),
                state.players[
                    player_id
                ].player_name,
                player_id,
            )
        )
        rotation_ids = tuple(
            list(starter_ids) + bench
        )[:rotation_size]

        team.rotation = RotationState(
            starter_ids=tuple(starter_ids),
            rotation_player_ids=rotation_ids,
            minutes_targets=minutes_targets(
                rotation_ids,
                starter_ids,
                regulation_minutes=(
                    state.settings.regulation_minutes
                ),
            ),
        )
        team.active_player_ids = rotation_ids
        team.inactive_player_ids = tuple(
            player_id
            for player_id in ordered_by_overall
            if player_id not in set(rotation_ids)
        )


def reset_season_results(
    state: SimulationLeagueState,
) -> None:
    # A postseason belongs to the season being archived. Removing the live
    # dynamic attribute prevents the completed bracket from leaking into the
    # new preseason while the archive retains its complete deep copy.
    if hasattr(state, "postseason_state"):
        delattr(state, "postseason_state")

    state.phase = LeaguePhase.PRESEASON
    state.current_day_index = 0
    state.standings = {
        team: TeamStanding(
            team_abbreviation=team
        )
        for team in state.teams
    }
    state.injuries = {
        player_id: InjuryState(
            player_id=player_id,
            status=AvailabilityStatus.HEALTHY,
        )
        for player_id in state.players
    }
    state.player_season_totals = {
        player_id: PlayerSeasonTotals(
            player_id=player_id
        )
        for player_id in state.players
    }
    state.schedule = {}
    state.completed_games = {}


def projection_summary_row(
    projection: PlayerDevelopmentProjection,
) -> dict[str, Any]:
    return {
        "player_id": projection.player_id,
        "player_name": projection.player_name,
        "source_age": projection.source_age,
        "target_age": projection.target_age,
        "current_overall_rating": (
            projection.current_overall_rating
        ),
        "projected_overall_rating": (
            projection.projected_overall_rating
        ),
        "overall_delta": projection.overall_delta,
        "performance_signal": (
            projection.performance_signal
        ),
        "games_played": getattr(
            projection,
            "games_played",
            0,
        ),
        "minutes_per_game": getattr(
            projection,
            "minutes_per_game",
            0.0,
        ),
        "opportunity_score": getattr(
            projection,
            "opportunity_score",
            0.0,
        ),
        "opportunity_component": getattr(
            projection,
            "opportunity_component",
            0.0,
        ),
        "draft_pedigree_component": getattr(
            projection,
            "draft_pedigree_component",
            0.0,
        ),
        "breakout_component": getattr(
            projection,
            "breakout_component",
            0.0,
        ),
    }


# MULTI_YEAR_CONTRACT_CLOCK_V1
def advance_rostered_contract_clock_v1(
    state: SimulationLeagueState,
) -> dict[str, Any]:
    free_agents = {
        str(player_id).strip()
        for player_id
        in getattr(state, "free_agent_player_ids", ()) or ()
        if str(player_id).strip()
    }

    decremented: list[str] = []
    expired: list[str] = []
    synthetic_replacements_removed: list[str] = []

    for team_code in sorted(state.teams):
        team_state = state.teams[team_code]
        kept: list[str] = []

        for raw_player_id in tuple(
            getattr(team_state, "roster_player_ids", ()) or ()
        ):
            player_id = str(raw_player_id).strip()
            player = state.players.get(player_id)
            if player is None:
                kept.append(player_id)
                continue

            contract = getattr(player, "contract", None)
            if contract is None:
                kept.append(player_id)
                continue

            # FRANCHISE_SYNTHETIC_EMERGENCY_REPLACEMENT_CLEANUP_V4
            if (
                bool(getattr(player, "synthetic", False))
                and str(getattr(contract, "status", "") or "").strip().lower()
                == "simulation_replacement"
            ):
                synthetic_replacements_removed.append(player_id)
                continue

            # GENERATED_ROOKIE_PENDING_CONTRACT_CLOCK_GUARD_V1
            # A pending drafted-rookie placeholder has not played a contract year.
            if str(getattr(contract, "status", "") or "").strip().lower() == "rookie_scale_pending":
                kept.append(player_id)
                continue

            raw_years = getattr(contract, "years_remaining", None)
            try:
                years_remaining = (
                    int(raw_years)
                    if raw_years is not None
                    else None
                )
            except (TypeError, ValueError):
                years_remaining = None

            if years_remaining is None or years_remaining <= 0:
                kept.append(player_id)
                continue

            if years_remaining > 1:
                updated_contract = replace(
                    contract,
                    years_remaining=years_remaining - 1,
                )
                # dataclasses.replace() copies declared fields only. Preserve
                # dynamic contract-lineage metadata used by the multi-year
                # salary-schedule continuity bridge.
                for attr_name, attr_value in vars(contract).items():
                    if not hasattr(updated_contract, attr_name):
                        setattr(
                            updated_contract,
                            attr_name,
                            copy.deepcopy(attr_value),
                        )
                player.contract = updated_contract
                kept.append(player_id)
                decremented.append(player_id)
                continue

            updated_contract = replace(
                contract,
                status="free_agent_pool",
                years_remaining=0,
            )
            for attr_name, attr_value in vars(contract).items():
                if not hasattr(updated_contract, attr_name):
                    setattr(
                        updated_contract,
                        attr_name,
                        copy.deepcopy(attr_value),
                    )
            player.contract = updated_contract
            player.team_abbreviation = ""
            player.roster_status = "free_agent"
            free_agents.add(player_id)
            expired.append(player_id)

        team_state.roster_player_ids = tuple(kept)

    if synthetic_replacements_removed:
        removed = set(synthetic_replacements_removed)
        free_agents.difference_update(removed)
        for player_id in removed:
            state.players.pop(player_id, None)
            state.injuries.pop(player_id, None)
            state.player_season_totals.pop(player_id, None)
            profiles = getattr(state, "injury_fatigue_profiles", None)
            if isinstance(profiles, dict):
                profiles.pop(player_id, None)
            intents = getattr(state, "career_intent_by_player_id", None)
            if isinstance(intents, dict):
                intents.pop(player_id, None)

    state.free_agent_player_ids = tuple(
        sorted(
            free_agents,
            key=lambda player_id: (
                state.players[player_id].player_name
                if player_id in state.players
                else "",
                player_id,
            ),
        )
    )

    return {
        "version": "multi-year-contract-clock-v1-2026-08-17",
        "decremented_player_ids": tuple(sorted(decremented)),
        "expired_player_ids": tuple(sorted(expired)),
        "decremented_count": len(decremented),
        "expired_count": len(expired),
        "synthetic_replacements_removed": tuple(
            sorted(synthetic_replacements_removed)
        ),
        "synthetic_replacements_removed_count": len(
            synthetic_replacements_removed
        ),
    }


def advance_simulation_season(
    state: SimulationLeagueState,
    *,
    target_season: str | None = None,
    performance_signals: Mapping[
        str,
        float,
    ] | None = None,
    development_config: (
        DevelopmentConfig | None
    ) = None,
) -> SeasonTransitionResult:
    source_season = state.settings.season_label
    resolved_target = (
        clean_text(target_season)
        if target_season is not None
        else next_season_label(source_season)
    )
    transition_preconditions(
        state,
        resolved_target,
    )

    config = development_config or (
        DevelopmentConfig(
            random_seed=state.settings.random_seed
        )
    )
    signals = resolve_performance_signals(
        state,
        performance_signals,
    )

    projections: dict[
        str,
        PlayerDevelopmentProjection,
    ] = {}
    synthetic_players = 0

    # Compute every projection before mutating the permanent state.
    # Any projection error therefore leaves the state unchanged.
    for player_id, player in state.players.items():
        if player.synthetic:
            synthetic_players += 1
            continue

        projections[player_id] = (
            project_player_development(
                player_development_profile(
                    state,
                    player_id,
                ),
                source_season=source_season,
                target_season=resolved_target,
                performance_signal=signals[
                    player_id
                ],
                config=config,
                development_modifier=team_development_modifier(
                    state,
                    player.team_abbreviation,
                ),
            )
        )

    rows = [
        projection_summary_row(projection)
        for projection in projections.values()
    ]
    deltas = [
        projection.overall_delta
        for projection in projections.values()
    ]
    average_delta = (
        sum(deltas) / len(deltas)
        if deltas
        else 0.0
    )
    improved = sum(
        delta > 0.05
        for delta in deltas
    )
    stable = sum(
        abs(delta) <= 0.05
        for delta in deltas
    )
    declined = sum(
        delta < -0.05
        for delta in deltas
    )
    risers = tuple(
        sorted(
            rows,
            key=lambda row: (
                -float(row["overall_delta"]),
                str(row["player_name"]),
            ),
        )[:10]
    )
    fallers = tuple(
        sorted(
            rows,
            key=lambda row: (
                float(row["overall_delta"]),
                str(row["player_name"]),
            ),
        )[:10]
    )
    development_summary = {
        "transition_version": TRANSITION_VERSION,
        "development_engine_version": (
            DEVELOPMENT_ENGINE_VERSION
        ),
        "staff_system_version": STAFF_SYSTEM_VERSION,
        "staff_development_active": bool(
            getattr(state, "franchise_staff_state_v1", None)
        ),
        "source_season": source_season,
        "target_season": resolved_target,
        "players_projected": len(projections),
        "synthetic_players_skipped": (
            synthetic_players
        ),
        "performance_signals_used": sum(
            abs(signal) > 1e-9
            for signal in signals.values()
        ),
        "average_overall_delta": round(
            average_delta,
            4,
        ),
        "improved_players": improved,
        "stable_players": stable,
        "declined_players": declined,
        "biggest_risers": list(risers),
        "biggest_fallers": list(fallers),
    }

    source_postseason = getattr(
        state,
        "postseason_state",
        None,
    )
    archived_champion = str(
        getattr(
            source_postseason,
            "champion",
            "",
        )
        or ""
    )
    archived_runner_up = str(
        getattr(
            source_postseason,
            "runner_up",
            "",
        )
        or ""
    )
    archived_conference_champions = dict(
        getattr(
            source_postseason,
            "conference_champions",
            {},
        )
        or {}
    )
    archived_postseason_games = len(
        getattr(
            source_postseason,
            "completed_games",
            {},
        )
        or {}
    )

    archive = SeasonArchive(
        season_label=source_season,
        standings=copy.deepcopy(
            state.standings
        ),
        player_season_totals=copy.deepcopy(
            state.player_season_totals
        ),
        schedule=copy.deepcopy(
            state.schedule
        ),
        completed_games=copy.deepcopy(
            state.completed_games
        ),
        transition_engine_version=(
            TRANSITION_VERSION
        ),
        development_summary=copy.deepcopy(
            development_summary
        ),
        postseason_state=copy.deepcopy(
            source_postseason
        ),
        champion=archived_champion,
        runner_up=archived_runner_up,
        conference_champions=copy.deepcopy(
            archived_conference_champions
        ),
        postseason_games_completed=(
            archived_postseason_games
        ),
    )

    # FRANCHISE_HISTORY_AWARDS_ARCHIVE_HOOK_V1
    from franchise_history_awards_archive_v1 import attach_awards_archive_v1
    attach_awards_archive_v1(state, archive)

    for player_id, projection in (
        projections.items()
    ):
        player = state.players[player_id]
        old_factors = dict(player.stat_factors)
        old_baseline = dict(
            player.baseline_per_36
        )
        player.development_history.append(
            {
                "transition_version": (
                    TRANSITION_VERSION
                ),
                "development_engine_version": (
                    DEVELOPMENT_ENGINE_VERSION
                ),
                "source_season": source_season,
                "target_season": resolved_target,
                "source_age": projection.source_age,
                "target_age": projection.target_age,
                "current_overall_rating": (
                    projection
                    .current_overall_rating
                ),
                "projected_overall_rating": (
                    projection
                    .projected_overall_rating
                ),
                "overall_delta": (
                    projection.overall_delta
                ),
                "performance_signal": (
                    projection.performance_signal
                ),
                "skill_deltas": dict(
                    projection.skill_deltas
                ),
            }
        )
        player.age = projection.target_age
        player.overall_rating = (
            projection.projected_overall_rating
        )
        player.skill_ratings = dict(
            projection.projected_skill_ratings
        )
        player.stat_factors = dict(
            projection.projected_stat_factors
        )
        player.baseline_per_36 = (
            projected_baseline_per_36(
                old_baseline,
                old_factors,
                player.stat_factors,
            )
        )

    # COMPLETED_SEASON_CONTRACT_CLOSEOUT_V1
    # Normal Franchise flow now closes the contract clock immediately after the
    # postseason, before Free Agency and the Draft. Keep this transition-level
    # fallback for legacy/non-Franchise callers, but never decrement twice.
    from franchise_offseason_market_season_v1 import (
        completed_season_closeout_applied,
    )
    from franchise_legacy_contract_continuity_v1 import (
        LEGACY_CONTRACT_CONTINUITY_VERSION,
        prepare_legacy_contracts_for_closeout,
        roll_legacy_contracts_to_target_season,
    )

    preclosed_contract_clock = completed_season_closeout_applied(
        state,
        source_season,
    )
    if preclosed_contract_clock:
        continuity_prepare = None
        contract_clock = {
            "version": "multi-year-contract-clock-v1-preclosed-at-completed-season-boundary",
            "decremented_player_ids": (),
            "expired_player_ids": (),
            "decremented_count": 0,
            "expired_count": 0,
            "skipped_preclosed": True,
        }
    else:
        continuity_prepare = prepare_legacy_contracts_for_closeout(
            state,
            season_label=source_season,
        )
        contract_clock = advance_rostered_contract_clock_v1(
            state
        )
    development_summary[
        "contract_clock_version"
    ] = contract_clock["version"]
    development_summary[
        "contracts_decremented"
    ] = contract_clock["decremented_count"]
    development_summary[
        "contracts_expired"
    ] = contract_clock["expired_count"]
    development_summary[
        "contract_clock_preclosed"
    ] = bool(contract_clock.get("skipped_preclosed", False))
    development_summary[
        "legacy_contract_continuity_version"
    ] = LEGACY_CONTRACT_CONTINUITY_VERSION
    development_summary[
        "legacy_contracts_seeded_at_transition_fallback"
    ] = (
        int(continuity_prepare.seeded_count)
        if continuity_prepare is not None
        else 0
    )
    state.settings = replace(
        state.settings,
        season_label=resolved_target,
    )
    contract_rollover = roll_legacy_contracts_to_target_season(
        state,
        resolved_target,
    )
    development_summary[
        "legacy_contract_salary_rollovers"
    ] = int(contract_rollover.rolled_count)
    state.transition_count += 1
    state.season_history.append(archive)

    refresh_team_rotations(state)
    reset_season_results(state)
    validate_simulation_league_state(state)

    return SeasonTransitionResult(
        transition_version=TRANSITION_VERSION,
        development_engine_version=(
            DEVELOPMENT_ENGINE_VERSION
        ),
        source_season=source_season,
        target_season=resolved_target,
        players_projected=len(projections),
        synthetic_players_skipped=(
            synthetic_players
        ),
        performance_signals_used=sum(
            abs(signal) > 1e-9
            for signal in signals.values()
        ),
        average_overall_delta=round(
            average_delta,
            4,
        ),
        improved_players=improved,
        stable_players=stable,
        declined_players=declined,
        biggest_risers=risers,
        biggest_fallers=fallers,
        archived_seasons=len(
            state.season_history
        ),
        transition_count=state.transition_count,
        archived_champion=archived_champion,
        archived_runner_up=archived_runner_up,
        archived_postseason_games=(
            archived_postseason_games
        ),
    )


def transition_state_signature(
    state: SimulationLeagueState,
) -> dict[str, Any]:
    return {
        "season_label": (
            state.settings.season_label
        ),
        "phase": state.phase.value,
        "transition_count": (
            state.transition_count
        ),
        "season_history": len(
            state.season_history
        ),
        "players": tuple(
            sorted(
                (
                    player_id,
                    player.age,
                    player.overall_rating,
                    tuple(
                        sorted(
                            player.skill_ratings.items()
                        )
                    ),
                    tuple(
                        sorted(
                            player.stat_factors.items()
                        )
                    ),
                    len(
                        player.development_history
                    ),
                )
                for player_id, player
                in state.players.items()
            )
        ),
        "postseason": (
            str(
                getattr(
                    getattr(
                        state,
                        "postseason_state",
                        None,
                    ),
                    "stage",
                    "",
                )
            ),
            str(
                getattr(
                    getattr(
                        state,
                        "postseason_state",
                        None,
                    ),
                    "champion",
                    "",
                )
                or ""
            ),
            str(
                getattr(
                    getattr(
                        state,
                        "postseason_state",
                        None,
                    ),
                    "runner_up",
                    "",
                )
                or ""
            ),
            tuple(
                sorted(
                    (
                        getattr(
                            getattr(
                                state,
                                "postseason_state",
                                None,
                            ),
                            "completed_games",
                            {},
                        )
                        or {}
                    )
                )
            ),
        ),
        "standings": tuple(
            sorted(
                (
                    team,
                    standing.games_played,
                    standing.wins,
                    standing.losses,
                )
                for team, standing
                in state.standings.items()
            )
        ),
        "schedule": tuple(
            sorted(state.schedule)
        ),
        "completed_games": tuple(
            sorted(state.completed_games)
        ),
    }


def run_self_test() -> dict[str, Any]:
    runtime_base = load_runtime_data()
    trade_state = create_league_state(
        runtime_base
    )
    runtime = build_state_runtime(
        runtime_base,
        trade_state,
    )
    state = create_simulation_league_state(
        runtime,
        trade_state,
    )

    names = {
        player.player_name: player_id
        for player_id, player
        in state.players.items()
    }
    wemby_id = names.get(
        "Victor Wembanyama"
    )
    curry_id = names.get(
        "Stephen Curry"
    )
    if not wemby_id or not curry_id:
        raise AssertionError(
            "Self-test sample players were not found."
        )

    # Give two players enough simulated work to exercise the
    # production-derived signal while leaving the rest neutral.
    for player_id, multiplier in (
        (wemby_id, 1.15),
        (curry_id, 0.82),
    ):
        baseline = state.players[
            player_id
        ].baseline_per_36
        totals = state.player_season_totals[
            player_id
        ]
        totals.games_played = 60
        totals.games_started = 60
        totals.minutes = 1800.0
        totals.points = round(
            baseline["points_per_36"]
            * 50.0
            * multiplier
        )
        totals.rebounds = round(
            baseline["rebounds_per_36"]
            * 50.0
            * multiplier
        )
        totals.assists = round(
            baseline["assists_per_36"]
            * 50.0
            * multiplier
        )
        totals.steals = round(
            baseline["steals_per_36"]
            * 50.0
            * multiplier
        )
        totals.blocks = round(
            baseline["blocks_per_36"]
            * 50.0
            * multiplier
        )
        totals.turnovers = round(
            baseline["turnovers_per_36"]
            * 50.0
        )

    state.phase = LeaguePhase.OFFSEASON
    source_label = state.settings.season_label
    wemby_age = state.players[wemby_id].age
    curry_age = state.players[curry_id].age
    wemby_rating = (
        state.players[wemby_id].overall_rating
    )
    curry_rating = (
        state.players[curry_id].overall_rating
    )
    source_wemby_totals = copy.deepcopy(
        state.player_season_totals[
            wemby_id
        ]
    )

    # The production Franchise path closes the completed-season contract clock
    # before Free Agency and the Draft. This unit fixture is testing the season
    # transition/development boundary, so represent that modern precondition
    # instead of expiring the untouched baseline roster a second time here.
    from franchise_offseason_market_season_v1 import (
        COMPLETED_SEASON_CLOSEOUT_ATTR,
    )

    setattr(
        state,
        COMPLETED_SEASON_CLOSEOUT_ATTR,
        {
            "status": "applied",
            "source_season": source_label,
            "target_market_season": next_season_label(source_label),
            "fixture_scope": "simulation_season_transition_self_test",
        },
    )

    result = advance_simulation_season(
        state,
        development_config=DevelopmentConfig(
            random_seed=20260808,
            random_variance_scale=0.55,
        ),
    )

    checks = {
        "transition_engine_uses_development_v1_1": (
            DEVELOPMENT_ENGINE_VERSION
            == "player-development-engine-v2.0-2026-08-11"
        ),
        "season_advances_exactly_one_year": (
            result.source_season
            == source_label
            and result.target_season
            == next_season_label(source_label)
            and state.settings.season_label
            == result.target_season
        ),
        "all_582_real_players_projected": (
            result.players_projected == 582
        ),
        "state_returns_to_preseason": (
            state.phase == LeaguePhase.PRESEASON
            and state.current_day_index == 0
        ),
        "season_results_reset": (
            not state.schedule
            and not state.completed_games
            and all(
                standing.games_played == 0
                for standing
                in state.standings.values()
            )
            and all(
                totals.games_played == 0
                for totals
                in state.player_season_totals.values()
            )
        ),
        "source_season_archived": (
            len(state.season_history) == 1
            and state.transition_count == 1
            and state.season_history[
                0
            ].season_label
            == source_label
            and state.season_history[
                0
            ].player_season_totals[
                wemby_id
            ]
            == source_wemby_totals
        ),
        "player_ages_advance": (
            state.players[wemby_id].age
            == float(wemby_age) + 1.0
            and state.players[curry_id].age
            == float(curry_age) + 1.0
        ),
        "young_star_improves": (
            state.players[
                wemby_id
            ].overall_rating
            > wemby_rating
        ),
        "older_star_declines": (
            state.players[
                curry_id
            ].overall_rating
            < curry_rating
        ),
        "performance_signals_are_used": (
            result.performance_signals_used >= 2
        ),
        "skill_ratings_and_factors_persist": (
            len(
                state.players[
                    wemby_id
                ].skill_ratings
            )
            == len(DEVELOPMENT_SKILL_FIELDS)
            and len(
                state.players[
                    wemby_id
                ].stat_factors
            )
            == len(DEVELOPMENT_STAT_FACTORS)
            and len(
                state.players[
                    wemby_id
                ].development_history
            )
            == 1
        ),
        "rotations_reconcile_after_reranking": all(
            math.isclose(
                sum(
                    team.rotation
                    .minutes_targets.values()
                ),
                240.0,
                abs_tol=0.1,
            )
            for team in state.teams.values()
        ),
        "transitioned_state_is_valid": bool(
            validate_simulation_league_state(
                state
            )
        ),
    }

    duplicate_transition_blocked = False
    try:
        advance_simulation_season(state)
    except SimulationSeasonTransitionError:
        duplicate_transition_blocked = True
    checks[
        "preseason_cannot_transition_again"
    ] = duplicate_transition_blocked

    rollback_state = (
        create_simulation_league_state(
            runtime,
            trade_state,
        )
    )
    rollback_state.phase = LeaguePhase.OFFSEASON
    before_invalid = transition_state_signature(
        rollback_state
    )
    invalid_target_blocked = False
    try:
        advance_simulation_season(
            rollback_state,
            target_season="2029-30",
        )
    except SimulationSeasonTransitionError:
        invalid_target_blocked = True

    checks[
        "invalid_target_is_blocked_without_mutation"
    ] = bool(
        invalid_target_blocked
        and transition_state_signature(
            rollback_state
        )
        == before_invalid
    )

    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]
    report = {
        "script": TRANSITION_VERSION,
        "development_engine": (
            DEVELOPMENT_ENGINE_VERSION
        ),
        "checks": checks,
        "failed_checks": failed,
        "transition": asdict(result),
        "sample_players": {
            "Victor Wembanyama": {
                "before_overall": wemby_rating,
                "after_overall": state.players[
                    wemby_id
                ].overall_rating,
                "after_age": state.players[
                    wemby_id
                ].age,
            },
            "Stephen Curry": {
                "before_overall": curry_rating,
                "after_overall": state.players[
                    curry_id
                ].overall_rating,
                "after_age": state.players[
                    curry_id
                ].age,
            },
        },
        "passed": not failed,
    }

    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )
    SELF_TEST_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
        ),
        encoding="utf-8",
    )

    if failed:
        raise AssertionError(
            "Simulation season transition self-test "
            "failed: "
            + ", ".join(failed)
        )

    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    args = parser.parse_args()

    report = run_self_test()
    print(json.dumps(report, indent=2))
    print(
        "\nSIMULATION SEASON TRANSITION V1 "
        "SELF-TEST PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
