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
    "simulation-season-transition-v1-2026-08-08"
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
        **{
            field_name: player.skill_ratings[
                field_name
            ]
            for field_name in DEVELOPMENT_SKILL_FIELDS
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
) -> None:
    for team in state.teams.values():
        ordered = tuple(
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
            len(ordered),
        )
        rotation_ids = ordered[:rotation_size]
        starter_ids = rotation_ids[:5]

        if len(starter_ids) != 5:
            raise SimulationSeasonTransitionError(
                f"{team.team_abbreviation} does not have "
                "five players after development."
            )

        team.rotation = RotationState(
            starter_ids=starter_ids,
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
            for player_id in ordered
            if player_id not in set(rotation_ids)
        )


def reset_season_results(
    state: SimulationLeagueState,
) -> None:
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
    )

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

    state.settings = replace(
        state.settings,
        season_label=resolved_target,
    )
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
            == "player-development-engine-v1.1-2026-08-08"
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