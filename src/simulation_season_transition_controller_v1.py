from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from dataclasses import asdict
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
    DevelopmentConfig,
    next_season_label,
)
from simulation_league_state_v1 import (  # noqa: E402
    GameStatus,
    LeaguePhase,
    ScheduledGame,
    SimulationLeagueState,
    add_scheduled_games,
    create_simulation_league_state,
    validate_simulation_league_state,
)
from simulation_season_transition_v1 import (  # noqa: E402
    SeasonTransitionResult,
    SimulationSeasonTransitionError,
    advance_simulation_season,
    transition_state_signature,
)
from state_runtime_adapter_v1 import (  # noqa: E402
    build_state_runtime,
)


CONTROLLER_VERSION = (
    "simulation-season-transition-controller-v1-2026-08-08"
)
SELF_TEST_REPORT = (
    OUTPUTS
    / "simulation_season_transition_controller_v1_self_test.json"
)


class SimulationSeasonTransitionControllerError(RuntimeError):
    """Raised when preview or commit safeguards reject a transition."""


def development_config_for_state(
    state: SimulationLeagueState,
) -> DevelopmentConfig:
    return DevelopmentConfig(
        random_seed=state.settings.random_seed,
        random_variance_scale=0.55,
    )


def next_target_season(
    state: SimulationLeagueState,
) -> str:
    return next_season_label(
        state.settings.season_label
    )


def incomplete_scheduled_game_ids(
    state: SimulationLeagueState,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            game_id
            for game_id, game
            in state.schedule.items()
            if game.status != GameStatus.COMPLETED
        )
    )


def transition_source_payload(
    state: SimulationLeagueState,
) -> dict[str, Any]:
    return {
        "transition_state": transition_state_signature(
            state
        ),
        "settings": asdict(state.settings),
        "teams": {
            team: {
                "roster_player_ids": list(
                    team_state.roster_player_ids
                ),
                "starter_ids": list(
                    team_state.rotation.starter_ids
                ),
                "rotation_player_ids": list(
                    team_state.rotation
                    .rotation_player_ids
                ),
                "minutes_targets": dict(
                    sorted(
                        team_state.rotation
                        .minutes_targets.items()
                    )
                ),
            }
            for team, team_state
            in sorted(state.teams.items())
        },
        "player_season_totals": {
            player_id: asdict(totals)
            for player_id, totals
            in sorted(
                state.player_season_totals.items()
            )
        },
        "injuries": {
            player_id: asdict(injury)
            for player_id, injury
            in sorted(state.injuries.items())
        },
        "schedule_records": {
            game_id: asdict(game)
            for game_id, game
            in sorted(state.schedule.items())
        },
        "completed_game_scores": {
            game_id: {
                "home_team": game.home_team,
                "away_team": game.away_team,
                "home_score": game.home_score,
                "away_score": game.away_score,
                "overtime_periods": (
                    game.overtime_periods
                ),
            }
            for game_id, game
            in sorted(state.completed_games.items())
        },
    }


def transition_source_fingerprint(
    state: SimulationLeagueState,
) -> str:
    payload = transition_source_payload(state)
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def result_payload(
    result: SeasonTransitionResult,
) -> dict[str, Any]:
    return asdict(result)


def validate_preview_payload(
    preview: Any,
) -> dict[str, Any]:
    if not isinstance(preview, dict):
        raise (
            SimulationSeasonTransitionControllerError(
                "The season-transition preview is not an object."
            )
        )

    required = {
        "controller_version",
        "source_fingerprint",
        "source_season",
        "target_season",
        "result",
    }
    missing = required.difference(preview)

    if missing:
        raise (
            SimulationSeasonTransitionControllerError(
                "The season-transition preview is missing: "
                + ", ".join(sorted(missing))
            )
        )

    if (
        preview["controller_version"]
        != CONTROLLER_VERSION
    ):
        raise (
            SimulationSeasonTransitionControllerError(
                "The season-transition preview was created by "
                "a different controller version."
            )
        )

    if not isinstance(preview["result"], dict):
        raise (
            SimulationSeasonTransitionControllerError(
                "The season-transition result is not an object."
            )
        )

    return preview


def build_season_transition_preview(
    state: SimulationLeagueState,
    *,
    performance_signals: Mapping[
        str,
        float,
    ] | None = None,
    development_config: (
        DevelopmentConfig | None
    ) = None,
) -> dict[str, Any]:
    validate_simulation_league_state(state)
    incomplete = incomplete_scheduled_game_ids(
        state
    )

    if incomplete:
        raise (
            SimulationSeasonTransitionControllerError(
                "Every scheduled game must be completed before "
                "the season can advance. Incomplete: "
                + ", ".join(incomplete[:8])
            )
        )

    before = transition_source_fingerprint(
        state
    )
    source_season = (
        state.settings.season_label
    )
    target_season = next_target_season(
        state
    )
    trial_state = copy.deepcopy(state)
    trial_state.phase = LeaguePhase.OFFSEASON

    try:
        result = advance_simulation_season(
            trial_state,
            target_season=target_season,
            performance_signals=(
                performance_signals
            ),
            development_config=(
                development_config
                or development_config_for_state(
                    state
                )
            ),
        )
    except SimulationSeasonTransitionError as exc:
        raise (
            SimulationSeasonTransitionControllerError(
                str(exc)
            )
        ) from exc

    after = transition_source_fingerprint(
        state
    )
    if after != before:
        raise (
            SimulationSeasonTransitionControllerError(
                "Building a preview unexpectedly mutated the "
                "live simulation state."
            )
        )

    return {
        "controller_version": (
            CONTROLLER_VERSION
        ),
        "source_fingerprint": before,
        "source_season": source_season,
        "target_season": target_season,
        "result": result_payload(result),
    }


def preview_matches_state(
    state: SimulationLeagueState,
    preview: Any,
) -> bool:
    try:
        resolved = validate_preview_payload(
            preview
        )
    except (
        SimulationSeasonTransitionControllerError
    ):
        return False

    return bool(
        resolved["source_season"]
        == state.settings.season_label
        and resolved["target_season"]
        == next_target_season(state)
        and resolved["source_fingerprint"]
        == transition_source_fingerprint(state)
        and not incomplete_scheduled_game_ids(
            state
        )
    )


def commit_season_transition_preview(
    state: SimulationLeagueState,
    preview: Any,
    *,
    performance_signals: Mapping[
        str,
        float,
    ] | None = None,
    development_config: (
        DevelopmentConfig | None
    ) = None,
) -> tuple[
    SimulationLeagueState,
    SeasonTransitionResult,
]:
    resolved = validate_preview_payload(
        preview
    )

    if not preview_matches_state(
        state,
        resolved,
    ):
        raise (
            SimulationSeasonTransitionControllerError(
                "The live season changed after this preview. "
                "Build a new preview before advancing."
            )
        )

    original_fingerprint = (
        transition_source_fingerprint(state)
    )
    committed_state = copy.deepcopy(state)
    committed_state.phase = LeaguePhase.OFFSEASON

    try:
        result = advance_simulation_season(
            committed_state,
            target_season=resolved[
                "target_season"
            ],
            performance_signals=(
                performance_signals
            ),
            development_config=(
                development_config
                or development_config_for_state(
                    state
                )
            ),
        )
    except SimulationSeasonTransitionError as exc:
        raise (
            SimulationSeasonTransitionControllerError(
                str(exc)
            )
        ) from exc

    if result_payload(result) != resolved["result"]:
        raise (
            SimulationSeasonTransitionControllerError(
                "The committed transition did not match the "
                "previewed deterministic result."
            )
        )

    validate_simulation_league_state(
        committed_state
    )

    if (
        transition_source_fingerprint(state)
        != original_fingerprint
    ):
        raise (
            SimulationSeasonTransitionControllerError(
                "The transactional commit mutated its source "
                "state instead of returning a replacement."
            )
        )

    return committed_state, result


def run_self_test() -> dict[str, Any]:
    base_runtime = load_runtime_data()
    trade_state = create_league_state(
        base_runtime
    )
    runtime = build_state_runtime(
        base_runtime,
        trade_state,
    )
    state = create_simulation_league_state(
        runtime,
        trade_state,
    )

    source_fingerprint = (
        transition_source_fingerprint(state)
    )
    preview = build_season_transition_preview(
        state
    )
    preview_result = preview["result"]

    blocked_state = copy.deepcopy(state)
    teams = sorted(blocked_state.teams)
    add_scheduled_games(
        blocked_state,
        [
            ScheduledGame(
                game_id="CONTROLLER-BLOCK-0001",
                day_index=1,
                home_team=teams[0],
                away_team=teams[1],
            )
        ],
    )
    incomplete_blocked = False
    try:
        build_season_transition_preview(
            blocked_state
        )
    except (
        SimulationSeasonTransitionControllerError
    ):
        incomplete_blocked = True

    stale_state = copy.deepcopy(state)
    first_player_id = sorted(
        stale_state.players
    )[0]
    stale_state.players[
        first_player_id
    ].overall_rating += 0.1
    stale_commit_blocked = False
    try:
        commit_season_transition_preview(
            stale_state,
            preview,
        )
    except (
        SimulationSeasonTransitionControllerError
    ):
        stale_commit_blocked = True

    committed_state, committed_result = (
        commit_season_transition_preview(
            state,
            preview,
        )
    )

    reused_preview_blocked = False
    try:
        commit_season_transition_preview(
            committed_state,
            preview,
        )
    except (
        SimulationSeasonTransitionControllerError
    ):
        reused_preview_blocked = True

    checks = {
        "controller_version_is_current": (
            preview["controller_version"]
            == CONTROLLER_VERSION
        ),
        "preview_projects_all_real_players": (
            preview_result[
                "players_projected"
            ]
            == 582
        ),
        "preview_targets_immediate_next_season": (
            preview["source_season"]
            == "2026-27"
            and preview["target_season"]
            == "2027-28"
        ),
        "preview_does_not_mutate_live_state": (
            transition_source_fingerprint(
                state
            )
            == source_fingerprint
            and state.settings.season_label
            == "2026-27"
        ),
        "preview_matches_unchanged_state": (
            preview_matches_state(
                state,
                preview,
            )
        ),
        "incomplete_schedule_blocks_preview": (
            incomplete_blocked
        ),
        "stale_state_is_detected": (
            not preview_matches_state(
                stale_state,
                preview,
            )
        ),
        "stale_preview_commit_is_blocked": (
            stale_commit_blocked
        ),
        "commit_returns_replacement_state": (
            committed_state is not state
        ),
        "commit_does_not_mutate_source_state": (
            state.settings.season_label
            == "2026-27"
            and transition_source_fingerprint(
                state
            )
            == source_fingerprint
        ),
        "commit_matches_preview_exactly": (
            result_payload(
                committed_result
            )
            == preview_result
        ),
        "commit_advances_and_archives": (
            committed_state.settings
            .season_label
            == "2027-28"
            and committed_state.phase
            == LeaguePhase.PRESEASON
            and len(
                committed_state.season_history
            )
            == 1
        ),
        "committed_state_is_valid": bool(
            validate_simulation_league_state(
                committed_state
            )
        ),
        "preview_cannot_be_reused": (
            reused_preview_blocked
        ),
    }

    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]
    report = {
        "script": CONTROLLER_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "source_season": (
                preview["source_season"]
            ),
            "target_season": (
                preview["target_season"]
            ),
            "players_projected": (
                preview_result[
                    "players_projected"
                ]
            ),
            "average_overall_delta": (
                preview_result[
                    "average_overall_delta"
                ]
            ),
            "archived_seasons": len(
                committed_state.season_history
            ),
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
            "Season transition controller self-test "
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

    if args.self_test:
        report = run_self_test()
        print(
            json.dumps(
                report,
                indent=2,
            )
        )
        print(
            "\nSIMULATION SEASON TRANSITION "
            "CONTROLLER V1 SELF-TEST PASSED"
        )
        return 0

    print(
        json.dumps(
            {
                "script": CONTROLLER_VERSION,
                "message": (
                    "Use --self-test to validate the "
                    "transactional preview and commit flow."
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())