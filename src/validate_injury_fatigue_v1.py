from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import (  # noqa: E402
    load_runtime_data,
)
from mutable_league_state_v1 import (  # noqa: E402
    create_league_state,
)
from regular_season_schedule_v1 import (  # noqa: E402
    generate_regular_season_schedule,
    install_regular_season_schedule,
)
from regular_season_simulation_controller_v1 import (  # noqa: E402
    SimulationScope,
    simulate_regular_season_scope,
)
from simulation_injury_fatigue_v1 import (  # noqa: E402
    HEALTH_NORMALIZATION_MARKER_ATTRIBUTE,
    HEALTH_PERSISTENCE_REPAIR_VERSION,
    HEALTH_STATE_ATTRIBUTE,
    INJURY_FATIGUE_VERSION,
    ensure_injury_fatigue_state,
    health_events,
    injury_status_is_unavailable,
    league_injury_summary,
    player_health_report_rows,
    player_risk_assessment,
    team_health_summary,
)
from simulation_league_state_v1 import (  # noqa: E402
    AvailabilityStatus,
    GameStatus,
    create_simulation_league_state,
    validate_simulation_league_state,
)
from single_game_simulator_v1 import (  # noqa: E402
    ENGINE_VERSION,
    simulate_scheduled_game,
)
from state_runtime_adapter_v1 import (  # noqa: E402
    build_state_runtime,
)


VALIDATOR_VERSION = (
    "injury-fatigue-validator-v1.2-2026-08-10"
)
REPORT_PATH = (
    OUTPUTS / "injury_fatigue_validation_v1.json"
)

PAGE_MARKERS = {
    "health_center": "Health & Load Center",
    "fatigue_explanation": (
        "How fatigue, rehab, and injury risk work"
    ),
    "pregame_health": "Pregame Health Brief",
    "load_management": (
        "Load-management suggestion"
    ),
    "what_if_medical_outcome": (
        "Sandbox medical outcome"
    ),
    "persistent_health_repair": (
        "HEALTH_PERSISTENCE_REPAIR_VERSION"
    ),
    "health_version": "INJURY_FATIGUE_VERSION",
}


def build_state(seed: int) -> Any:
    runtime_base = load_runtime_data()
    league_state = create_league_state(
        runtime_base
    )
    runtime = build_state_runtime(
        runtime_base,
        league_state,
    )
    state = create_simulation_league_state(
        runtime,
        league_state,
    )
    state.settings = replace(
        state.settings,
        injuries_enabled=True,
        random_seed=int(seed),
    )
    schedule = generate_regular_season_schedule(
        state,
        seed=seed,
    )
    install_regular_season_schedule(
        state,
        schedule,
    )
    ensure_injury_fatigue_state(
        state
    )
    return state


def deterministic_preview_check(
    state: Any,
) -> bool:
    game = min(
        (
            game
            for game in state.schedule.values()
            if game.status
            == GameStatus.SCHEDULED
        ),
        key=lambda item: (
            item.day_index,
            item.game_id,
        ),
    )
    first = simulate_scheduled_game(
        state,
        game.game_id,
        commit=False,
    )
    second = simulate_scheduled_game(
        state,
        game.game_id,
        commit=False,
    )
    return (
        asdict(first.game)
        == asdict(second.game)
        and asdict(
            first.health_update
        )
        == asdict(
            second.health_update
        )
        and not state.completed_games
    )


def unavailable_player_check(
    state: Any,
) -> bool:
    game = min(
        state.schedule.values(),
        key=lambda item: (
            item.day_index,
            item.game_id,
        ),
    )
    team = game.home_team
    player_id = (
        state.teams[
            team
        ].rotation.rotation_player_ids[0]
    )
    injury = state.injuries[player_id]
    injury.status = AvailabilityStatus.DOUBTFUL
    injury.injury_type = "validation restriction"
    injury.games_remaining = 1
    preview = simulate_scheduled_game(
        state,
        game.game_id,
        commit=False,
    )
    injury.status = AvailabilityStatus.HEALTHY
    injury.injury_type = ""
    injury.games_remaining = 0
    return player_id not in {
        line.player_id
        for line
        in preview.game.player_box_scores
    }


def run_validation(seed: int) -> dict[str, Any]:
    page_text = PAGE.read_text(
        encoding="utf-8"
    )
    state = build_state(seed)
    preview_source_signature = (
        len(state.completed_games),
        tuple(
            sorted(
                (
                    game_id,
                    game.status.value,
                )
                for game_id, game
                in state.schedule.items()
            )
        ),
    )
    preview_deterministic = (
        deterministic_preview_check(
            state
        )
    )
    preview_after_signature = (
        len(state.completed_games),
        tuple(
            sorted(
                (
                    game_id,
                    game.status.value,
                )
                for game_id, game
                in state.schedule.items()
            )
        ),
    )
    doubtful_excluded = (
        unavailable_player_check(
            copy.deepcopy(state)
        )
    )

    sample_player = next(
        player_id
        for player_id, player
        in state.players.items()
        if not player.synthetic
        and player.team_abbreviation
    )
    sample_team = state.players[
        sample_player
    ].team_abbreviation
    profiles = ensure_injury_fatigue_state(
        state
    )
    profiles[
        sample_player
    ].fatigue = 72.0
    profiles[
        sample_player
    ].last_game_day = 10
    profiles[
        sample_player
    ].recent_game_days = (
        7,
        9,
        10,
    )
    profiles[
        sample_player
    ].recent_minutes = (
        34.0,
        36.0,
        37.0,
    )
    back_to_back_risk = (
        player_risk_assessment(
            state,
            sample_player,
            day_index=11,
            planned_minutes=36.0,
        )
    )
    rested_risk = (
        player_risk_assessment(
            state,
            sample_player,
            day_index=13,
            planned_minutes=36.0,
        )
    )

    # Rebuild after the controlled risk comparison so the full-season
    # distribution starts from a clean health graph.
    state = build_state(seed)
    validation_started = (
        time.perf_counter()
    )

    def report_progress(
        completed: int,
        total: int,
        game_id: str,
        day_index: int,
    ) -> None:
        if (
            completed == 1
            or completed % 100 == 0
            or completed == total
        ):
            elapsed = (
                time.perf_counter()
                - validation_started
            )
            rate = (
                completed / elapsed
                if elapsed > 0.0
                else 0.0
            )
            remaining = (
                (total - completed) / rate
                if rate > 0.0
                else 0.0
            )
            print(
                "Injury validation progress: "
                f"{completed}/{total} games | "
                f"day {day_index} | "
                f"elapsed {elapsed:.1f}s | "
                f"ETA {remaining:.1f}s",
                flush=True,
            )

    simulated, result = (
        simulate_regular_season_scope(
            state,
            scope=SimulationScope.REMAINDER,
            progress_callback=(
                report_progress
            ),
        )
    )
    validation_runtime_seconds = round(
        time.perf_counter()
        - validation_started,
        3,
    )
    profiles = ensure_injury_fatigue_state(
        simulated
    )
    events = [
        event
        for event in health_events(
            simulated
        )
        if event.get(
            "season_label"
        )
        == simulated.settings.season_label
    ]
    summary = league_injury_summary(
        simulated
    )
    statuses = {
        event.get("status")
        for event in events
    }
    maximum_fatigue = max(
        (
            profile.fatigue
            for profile in profiles.values()
        ),
        default=0.0,
    )
    all_event_players_valid = all(
        event.get("player_id")
        in simulated.players
        for event in events
    )
    all_explanations_present = all(
        bool(
            str(
                event.get(
                    "explanation",
                    "",
                )
            ).strip()
        )
        for event in events
    )
    active_unavailable = {
        player_id
        for player_id, injury
        in simulated.injuries.items()
        if injury_status_is_unavailable(
            injury.status
        )
    }
    unavailable_absent_from_last_game = all(
        not (
            active_unavailable
            .intersection(
                line.player_id
                for line in game.player_box_scores
            )
        )
        for game in list(
            simulated.completed_games.values()
        )[-10:]
    )
    team_rows = player_health_report_rows(
        simulated,
        sample_team,
    )
    team_summary = team_health_summary(
        simulated,
        sample_team,
    )

    # Emulate a Streamlit hot reload: the persisted objects have every
    # expected field but no longer share the current class identity.
    stale_state = copy.deepcopy(simulated)
    stale_profiles = ensure_injury_fatigue_state(stale_state)
    sample_workload_player = max(
        stale_profiles,
        key=lambda player_id: (
            len(stale_profiles[player_id].recent_minutes),
            stale_profiles[player_id].fatigue,
        ),
    )
    expected_workload = (
        stale_profiles[sample_workload_player].fatigue,
        stale_profiles[sample_workload_player].recent_minutes,
        stale_profiles[sample_workload_player].recent_game_days,
    )
    setattr(
        stale_state,
        HEALTH_STATE_ATTRIBUTE,
        {
            player_id: SimpleNamespace(**asdict(profile))
            for player_id, profile in stale_profiles.items()
        },
    )
    setattr(
        stale_state,
        HEALTH_NORMALIZATION_MARKER_ATTRIBUTE,
        None,
    )
    migrated_profiles = ensure_injury_fatigue_state(stale_state)
    migrated_workload = (
        migrated_profiles[sample_workload_player].fatigue,
        migrated_profiles[sample_workload_player].recent_minutes,
        migrated_profiles[sample_workload_player].recent_game_days,
    )

    # Emulate the affected live save: completed box scores exist, but every
    # health profile was previously reset to an empty default.
    blank_state = copy.deepcopy(simulated)
    setattr(
        blank_state,
        HEALTH_STATE_ATTRIBUTE,
        {
            player_id: SimpleNamespace(
                player_id=player_id,
                season_label=blank_state.settings.season_label,
                fatigue=0.0,
                recent_minutes=(),
                recent_game_days=(),
                last_game_day=0,
                last_recovery_day=0,
                last_updated_game_id="",
            )
            for player_id in blank_state.players
        },
    )
    setattr(
        blank_state,
        HEALTH_NORMALIZATION_MARKER_ATTRIBUTE,
        None,
    )
    rebuilt_profiles = ensure_injury_fatigue_state(blank_state)
    reconstructed_workload = any(
        profile.recent_minutes
        and profile.last_updated_game_id
        for profile in rebuilt_profiles.values()
    )
    reconstructed_fatigue = max(
        (profile.fatigue for profile in rebuilt_profiles.values()),
        default=0.0,
    )

    checks = {
        "validator_version_is_current": (
            VALIDATOR_VERSION.endswith(
                "2026-08-10"
            )
        ),
        "injury_fatigue_version_is_current": (
            INJURY_FATIGUE_VERSION
            == (
                "simulation-injury-fatigue-"
                "v1-2026-08-09"
            )
        ),
        "health_persistence_repair_is_current": (
            HEALTH_PERSISTENCE_REPAIR_VERSION
            == (
                "franchise-health-persistence-"
                "repair-v1-2026-08-09"
            )
        ),
        "hot_reload_preserves_workload": (
            migrated_workload == expected_workload
        ),
        "blank_live_save_reconstructs_workload": (
            reconstructed_workload
            and reconstructed_fatigue > 0.0
        ),
        "game_engine_version_is_current": (
            ENGINE_VERSION
            == (
                "single-game-simulator-"
                "v1.6-2026-08-08"
            )
        ),
        "all_ui_markers_are_present": all(
            marker in page_text
            for marker
            in PAGE_MARKERS.values()
        ),
        "preview_is_deterministic": (
            preview_deterministic
        ),
        "preview_does_not_mutate_state": (
            preview_source_signature
            == preview_after_signature
        ),
        "doubtful_player_is_excluded": (
            doubtful_excluded
        ),
        "back_to_back_risk_exceeds_rested": (
            back_to_back_risk.probability
            > rested_risk.probability
        ),
        "back_to_back_explanation_is_visible": (
            "back-to-back"
            in back_to_back_risk.explanation
        ),
        "full_season_completes_1230_games": (
            result.games_simulated == 1230
            and len(
                simulated.completed_games
            )
            == 1230
        ),
        "health_profiles_cover_all_players": (
            set(profiles)
            == set(simulated.players)
        ),
        "fatigue_remains_bounded": all(
            0.0 <= profile.fatigue <= 100.0
            for profile in profiles.values()
        ),
        "fatigue_accumulates_during_season": (
            maximum_fatigue >= 30.0
        ),
        "injury_event_volume_is_plausible": (
            12 <= len(events) <= 180
        ),
        "injury_events_include_outcomes": (
            "out" in statuses
            and (
                "questionable" in statuses
                or "day_to_day"
                in statuses
            )
        ),
        "back_to_back_events_occur": (
            summary[
                "back_to_back_events"
            ]
            >= 1
        ),
        "event_players_are_valid": (
            all_event_players_valid
        ),
        "event_explanations_are_present": (
            all_explanations_present
        ),
        "unavailable_players_do_not_play": (
            unavailable_absent_from_last_game
        ),
        "health_report_covers_team": (
            len(team_rows)
            == len(
                simulated.teams[
                    sample_team
                ].roster_player_ids
            )
        ),
        "health_summary_reconciles": (
            team_summary["available"]
            + team_summary["out"]
            == len(team_rows)
        ),
        "completed_state_remains_valid": bool(
            validate_simulation_league_state(
                simulated
            )
        ),
    }
    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]
    report = {
        "script": VALIDATOR_VERSION,
        "engine": INJURY_FATIGUE_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            **summary,
            "full_season_runtime_seconds": (
                validation_runtime_seconds
            ),
            "maximum_fatigue": round(
                maximum_fatigue,
                2,
            ),
            "back_to_back_sample": asdict(
                back_to_back_risk
            ),
            "rested_sample": asdict(
                rested_risk
            ),
            "sample_team": sample_team,
            "sample_team_health": (
                team_summary
            ),
            "event_statuses": sorted(
                str(value)
                for value in statuses
                if value
            ),
            "first_events": events[:5],
        },
        "passed": not failed,
    }
    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )
    REPORT_PATH.write_text(
        json.dumps(
            report,
            indent=2,
        ),
        encoding="utf-8",
    )
    if failed:
        raise AssertionError(
            "Injury and fatigue validation failed: "
            + ", ".join(failed)
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--seed",
        type=int,
        default=20260808,
    )
    args = parser.parse_args()
    report = run_validation(
        args.seed
    )
    print(
        json.dumps(
            report,
            indent=2,
        )
    )
    print(
        "\nINJURY AND FATIGUE "
        "VALIDATION PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
