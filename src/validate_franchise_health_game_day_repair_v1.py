from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import load_runtime_data  # noqa: E402
from mutable_league_state_v1 import create_league_state  # noqa: E402
from franchise_offseason_market_season_v1 import (  # noqa: E402
    COMPLETED_SEASON_CLOSEOUT_ATTR,
)
from player_development_engine_v1 import (  # noqa: E402
    DevelopmentConfig,
    next_season_label,
)
from regular_season_schedule_v1 import (  # noqa: E402
    generate_regular_season_schedule,
    install_regular_season_schedule,
)
from regular_season_simulation_controller_v1 import (  # noqa: E402
    SimulationScope,
    simulate_regular_season_scope,
)
from simulation_franchise_checkpoint_v1 import (  # noqa: E402
    load_franchise_checkpoint,
)
from simulation_injury_fatigue_v1 import (  # noqa: E402
    HEALTH_NORMALIZATION_MARKER_ATTRIBUTE,
    HEALTH_PERSISTENCE_REPAIR_VERSION,
    HEALTH_STATE_ATTRIBUTE,
    ensure_injury_fatigue_state,
    player_health_report_rows,
)
from simulation_league_state_v1 import (  # noqa: E402
    LeaguePhase,
    create_simulation_league_state,
    validate_simulation_league_state,
)
from simulation_season_transition_v1 import (  # noqa: E402
    advance_simulation_season,
)
from single_game_simulator_v1 import (  # noqa: E402
    simulate_scheduled_game,
)
from state_runtime_adapter_v1 import build_state_runtime  # noqa: E402


VALIDATOR_VERSION = (
    "franchise-health-game-day-repair-validator-v1.1-2026-08-09"
)
REPORT_PATH = (
    OUTPUTS / "franchise_health_game_day_repair_validation_v1.json"
)


def build_state(seed: int) -> Any:
    runtime_base = load_runtime_data()
    trade_state = create_league_state(runtime_base)
    runtime = build_state_runtime(runtime_base, trade_state)
    state = create_simulation_league_state(runtime, trade_state)
    schedule = generate_regular_season_schedule(state, seed=seed)
    install_regular_season_schedule(state, schedule)
    ensure_injury_fatigue_state(state)
    return state


def find_player_id(state: Any, name: str) -> str:
    target = " ".join(name.lower().split())
    for player_id, player in state.players.items():
        if " ".join(player.player_name.lower().split()) == target:
            return player_id
    return ""


def workload_signature(profile: Any) -> tuple[Any, ...]:
    return (
        round(float(profile.fatigue), 2),
        tuple(profile.recent_minutes),
        tuple(profile.recent_game_days),
        int(profile.last_game_day),
        str(profile.last_updated_game_id),
    )


def validate_hot_reload_and_rebuild(seed: int) -> dict[str, Any]:
    state = build_state(seed)
    simulated, result = simulate_regular_season_scope(
        state,
        scope=SimulationScope.NEXT_WEEK,
    )
    profiles = ensure_injury_fatigue_state(simulated)
    sample_player = max(
        profiles,
        key=lambda player_id: (
            len(profiles[player_id].recent_minutes),
            profiles[player_id].fatigue,
        ),
    )
    before = workload_signature(profiles[sample_player])

    stale_state = copy.deepcopy(simulated)
    stale_profiles = ensure_injury_fatigue_state(stale_state)
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
    migrated = ensure_injury_fatigue_state(stale_state)
    after_reload = workload_signature(migrated[sample_player])

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
    rebuilt = ensure_injury_fatigue_state(blank_state)
    rebuilt_profiles = [
        profile
        for profile in rebuilt.values()
        if profile.recent_minutes and profile.last_updated_game_id
    ]

    return {
        "games_simulated": result.games_simulated,
        "sample_player": sample_player,
        "before": before,
        "after_reload": after_reload,
        "reload_preserved": before == after_reload,
        "rebuilt_profile_count": len(rebuilt_profiles),
        "rebuild_has_fatigue": max(
            (profile.fatigue for profile in rebuilt.values()),
            default=0.0,
        )
        > 0.0,
    }


def validate_rest_decision(seed: int) -> dict[str, Any]:
    state = build_state(seed + 1)
    game = min(
        state.schedule.values(),
        key=lambda item: (item.day_index, item.game_id),
    )
    team = state.teams[game.home_team]
    star_id = team.rotation.rotation_player_ids[0]
    baseline = simulate_scheduled_game(
        state,
        game.game_id,
        seed=seed + 99,
        commit=False,
    )
    rested = simulate_scheduled_game(
        state,
        game.game_id,
        seed=seed + 99,
        commit=False,
        sit_player_ids=(star_id,),
    )
    baseline_ids = {
        line.player_id for line in baseline.game.player_box_scores
    }
    rested_ids = {
        line.player_id for line in rested.game.player_box_scores
    }
    if game.home_team == state.players[star_id].team_abbreviation:
        rating_changed = (
            baseline.metadata.home_team_rating
            != rested.metadata.home_team_rating
        )
        expectation_changed = (
            baseline.metadata.expected_home_score
            != rested.metadata.expected_home_score
        )
    else:
        rating_changed = (
            baseline.metadata.away_team_rating
            != rested.metadata.away_team_rating
        )
        expectation_changed = (
            baseline.metadata.expected_away_score
            != rested.metadata.expected_away_score
        )

    return {
        "game_id": game.game_id,
        "star_id": star_id,
        "star_name": state.players[star_id].player_name,
        "star_in_baseline": star_id in baseline_ids,
        "star_absent_when_rested": star_id not in rested_ids,
        "team_rating_changed": rating_changed,
        "expected_score_changed": expectation_changed,
        "baseline_score": (
            baseline.game.away_score,
            baseline.game.home_score,
        ),
        "rested_score": (
            rested.game.away_score,
            rested.game.home_score,
        ),
    }


def validate_two_year_age(seed: int) -> dict[str, Any]:
    state = build_state(seed + 2)
    lebron_id = find_player_id(state, "LeBron James")
    if not lebron_id:
        raise AssertionError("LeBron James was not found.")
    source_age = float(state.players[lebron_id].age)
    for offset in range(2):
        state.phase = LeaguePhase.OFFSEASON
        # The focused age check does not need a played season. It verifies
        # that permanent player state is cumulative across transitions.
        state.schedule = {}
        state.completed_games = {}
        source_label = state.settings.season_label
        setattr(
            state,
            COMPLETED_SEASON_CLOSEOUT_ATTR,
            {
                "status": "applied",
                "source_season": source_label,
                "target_market_season": next_season_label(source_label),
                "fixture_scope": "two_year_age_validation",
            },
        )
        advance_simulation_season(
            state,
            performance_signals={lebron_id: 0.0},
            development_config=DevelopmentConfig(
                random_seed=seed + 200 + offset,
                random_variance_scale=0.0,
            ),
        )
    return {
        "source_age": source_age,
        "final_age": float(state.players[lebron_id].age),
        "season_label": state.settings.season_label,
        "transition_count": state.transition_count,
        "development_history": len(
            state.players[lebron_id].development_history
        ),
    }


def validate_live_checkpoint() -> dict[str, Any]:
    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        return {
            "checkpoint_found": False,
            "passed": True,
        }
    state = checkpoint.simulation_state
    profiles = ensure_injury_fatigue_state(state)
    completed = len(state.completed_games)
    fatigue_rows = [
        row
        for team in sorted(state.teams)
        for row in player_health_report_rows(state, team)
    ]
    workload_profiles = sum(
        bool(profile.recent_minutes)
        for profile in profiles.values()
    )
    def age_matches_latest_development(player: Any) -> bool:
        target_ages = [
            entry.get("target_age")
            for entry in player.development_history
            if isinstance(entry, dict)
            and entry.get("target_age") is not None
        ]
        return (
            not target_ages
            or float(player.age) == float(target_ages[-1])
        )

    age_history_consistent = all(
        age_matches_latest_development(player)
        for player in state.players.values()
        if not player.synthetic
    )
    return {
        "checkpoint_found": True,
        "season_label": state.settings.season_label,
        "transition_count": state.transition_count,
        "completed_games": completed,
        "workload_profiles": workload_profiles,
        "maximum_fatigue": max(
            (profile.fatigue for profile in profiles.values()),
            default=0.0,
        ),
        "current_fatigue_visible": any(
            float(row["current_fatigue"]) > 0.0
            for row in fatigue_rows
        ) if completed else True,
        "projection_fields_present": all(
            "current_fatigue" in row
            and "projected_fatigue" in row
            for row in fatigue_rows
        ),
        "age_history_consistent": age_history_consistent,
        "state_valid": bool(validate_simulation_league_state(state)),
        "passed": bool(
            (completed == 0 or workload_profiles > 0)
            and age_history_consistent
            and all(
                "current_fatigue" in row
                and "projected_fatigue" in row
                for row in fatigue_rows
            )
            and validate_simulation_league_state(state)
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260809)
    args = parser.parse_args()

    page_text = PAGE.read_text(encoding="utf-8")
    health = validate_hot_reload_and_rebuild(args.seed)
    rest = validate_rest_decision(args.seed)
    age = validate_two_year_age(args.seed)
    checkpoint = validate_live_checkpoint()

    checks = {
        "repair_version_is_current": (
            HEALTH_PERSISTENCE_REPAIR_VERSION
            == "franchise-health-persistence-repair-v1-2026-08-09"
        ),
        "hot_reload_preserves_workload": health["reload_preserved"],
        "blank_profiles_rebuild_from_box_scores": (
            health["rebuilt_profile_count"] > 0
            and health["rebuild_has_fatigue"]
        ),
        "rested_player_is_removed": (
            rest["star_in_baseline"]
            and rest["star_absent_when_rested"]
        ),
        "rest_decision_changes_team_context": (
            rest["team_rating_changed"]
            and rest["expected_score_changed"]
        ),
        "age_advances_across_two_seasons": (
            age["season_label"] == "2028-29"
            and age["transition_count"] == 2
            and age["final_age"] == age["source_age"] + 2.0
            and age["development_history"] == 2
        ),
        "persistent_navigation_is_present": (
            "FRANCHISE_SECTION_KEY" in page_text
            and "franchise_pending_section" in page_text
        ),
        "normal_game_flow_commits_before_reveal": (
            "Simulate game" in page_text
            and "commit_game_transactionally(" in page_text
            and "then reveals the result" in page_text
            and "render_game_day_final_v1(" in page_text
        ),
        "what_if_lab_is_separate": (
            "Advanced What-If Lab" in page_text
            and "What-if result only" in page_text
            and "Commit previewed result" not in page_text
        ),
        "rest_change_invalidates_old_what_if": (
            "current_preview_request" in page_text
            and "stored_request" in page_text
        ),
        "live_checkpoint_is_repairable": checkpoint["passed"],
        "live_checkpoint_exposes_current_fatigue": (
            checkpoint.get("current_fatigue_visible", True)
        ),
        "fatigue_projection_fields_are_present": (
            checkpoint.get("projection_fields_present", True)
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "script": VALIDATOR_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "health": health,
        "rest": rest,
        "age": age,
        "checkpoint": checkpoint,
        "passed": not failed,
    }
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, indent=2, default=str),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, default=str))
    if failed:
        raise AssertionError(
            "Franchise health and Game Day repair validation failed: "
            + ", ".join(failed)
        )
    print("\nFRANCHISE HEALTH AND GAME DAY REPAIR VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
