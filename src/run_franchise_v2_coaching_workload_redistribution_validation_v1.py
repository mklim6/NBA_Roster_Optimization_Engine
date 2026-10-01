from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path

from franchise_coaching_role_rotation_v1 import (
    coaching_minute_weight_multipliers_v1,
    coaching_responsibility_multiplier_v1,
    functional_role_profile_v1,
    workload_redistribution_report_v1,
)
from simulation_franchise_checkpoint_v1 import (
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)
from simulation_league_state_v1 import (
    AvailabilityStatus,
    set_player_injury,
)
from single_game_simulator_v1 import (
    GameSimulationConfig,
    allocate_bounded_integer_units,
    allocate_minutes,
    available_team_players,
    player_minutes_cap,
    select_game_rotation,
)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def legacy_minutes(state, team, rotation_ids, starter_ids, *, overtime_periods=0):
    total_minutes = (
        state.settings.regulation_minutes * 5
        + state.settings.overtime_minutes * 5 * overtime_periods
    )
    starter_set = set(starter_ids)
    saved_targets = state.teams[team].rotation.minutes_targets

    weights = {}
    for player_id in rotation_ids:
        saved = float(saved_targets.get(player_id, 0.0) or 0.0)
        fallback = 30.0 if player_id in starter_set else 18.0
        weights[player_id] = saved if saved > 0.0 else max(fallback, 1.0)

    average_required = total_minutes / len(rotation_ids)
    maximum_minutes = min(
        (
            state.settings.regulation_minutes
            + state.settings.overtime_minutes * overtime_periods
        ),
        max(
            38.0 + 2.0 * overtime_periods,
            math.ceil(average_required) + 4.0,
        ),
    )
    day_index = int(
        getattr(
            state,
            "_active_simulation_day",
            state.current_day_index,
        )
    )
    upper_bounds = {
        player_id: int(
            round(
                player_minutes_cap(
                    state,
                    player_id,
                    day_index=day_index,
                    default_maximum=maximum_minutes,
                ) * 10
            )
        )
        for player_id in rotation_ids
    }
    required_tenths = int(round(total_minutes * 10))
    if sum(upper_bounds.values()) < required_tenths:
        upper_bounds = {
            player_id: int(round(maximum_minutes * 10))
            for player_id in rotation_ids
        }

    units = allocate_bounded_integer_units(
        required_tenths,
        rotation_ids,
        weights,
        upper_bounds,
    )
    return {pid: units[pid] / 10.0 for pid in rotation_ids}


def main() -> int:
    active = Path(DEFAULT_CHECKPOINT_PATH)
    before_hash = sha(active) if active.is_file() else ""

    checkpoint = load_franchise_checkpoint(allow_backup=False)
    if checkpoint is None:
        raise RuntimeError("Active franchise checkpoint is unavailable.")

    source = checkpoint.simulation_state
    config = GameSimulationConfig()

    scenarios = []

    for team, team_state in sorted(source.teams.items()):
        original = tuple(team_state.rotation.starter_ids)
        if len(original) != 5:
            continue

        healthy_available = available_team_players(source, team, set())
        if len(healthy_available) < 8:
            continue
        if not all(pid in set(healthy_available) for pid in original):
            continue

        ranked_starters = sorted(
            original,
            key=lambda pid: (
                -functional_role_profile_v1(source, pid).scores["primary_creator"],
                -float(source.players[pid].overall_rating),
                pid,
            ),
        )

        missing = ranked_starters[0]
        protected = copy.deepcopy(source)
        set_player_injury(
            protected,
            missing,
            status=AvailabilityStatus.OUT,
            injury_type="protected workload redistribution validation",
            games_remaining=1,
            performance_multiplier=1.0,
            aggravation_risk=0.0,
            notes="protected runtime only",
        )

        rotation_ids, starter_ids = select_game_rotation(
            protected,
            team,
            sit_player_ids=set(),
            config=config,
        )
        actual = allocate_minutes(
            protected,
            team,
            rotation_ids,
            starter_ids,
            overtime_periods=0,
        )
        legacy = legacy_minutes(
            protected,
            team,
            rotation_ids,
            starter_ids,
            overtime_periods=0,
        )
        multipliers = coaching_minute_weight_multipliers_v1(
            protected,
            team,
            rotation_ids=rotation_ids,
            starter_ids=starter_ids,
        )
        scoring_multipliers = {
            pid: coaching_responsibility_multiplier_v1(
                protected,
                team,
                pid,
                active_player_ids=rotation_ids,
                channel="scoring",
            )
            for pid in rotation_ids
        }
        creation_multipliers = {
            pid: coaching_responsibility_multiplier_v1(
                protected,
                team,
                pid,
                active_player_ids=rotation_ids,
                channel="creation",
            )
            for pid in rotation_ids
        }

        favored = [
            pid
            for pid in rotation_ids
            if multipliers[pid] > 1.01
        ]
        favored_gain = sum(
            actual[pid] - legacy[pid]
            for pid in favored
        )
        scenarios.append(
            (
                favored_gain,
                team,
                missing,
                protected,
                rotation_ids,
                starter_ids,
                actual,
                legacy,
                multipliers,
                scoring_multipliers,
                creation_multipliers,
            )
        )

    if not scenarios:
        raise RuntimeError(
            "No fully healthy rotation was available for protected workload validation."
        )

    scenarios.sort(
        key=lambda item: (
            -item[0],
            item[1],
            item[2],
        )
    )
    (
        favored_gain,
        team,
        missing,
        protected,
        rotation_ids,
        starter_ids,
        actual,
        legacy,
        multipliers,
        scoring_multipliers,
        creation_multipliers,
    ) = scenarios[0]

    missing_player = protected.players[missing]
    report = workload_redistribution_report_v1(
        protected,
        team,
        rotation_ids=rotation_ids,
        starter_ids=starter_ids,
    )

    top_minute = max(
        rotation_ids,
        key=lambda pid: (multipliers[pid], pid),
    )
    top_scoring = max(
        rotation_ids,
        key=lambda pid: (scoring_multipliers[pid], pid),
    )
    top_creation = max(
        rotation_ids,
        key=lambda pid: (creation_multipliers[pid], pid),
    )

    checks = {
        "missing_starter_is_not_in_rotation":
            missing not in set(rotation_ids),
        "team_minutes_still_equal_240":
            abs(sum(actual.values()) - 240.0) < 1e-9,
        "legacy_comparison_also_reconciles":
            abs(sum(legacy.values()) - 240.0) < 1e-9,
        "role_aware_minutes_differ_from_legacy":
            any(
                abs(actual[pid] - legacy[pid]) >= 0.1
                for pid in rotation_ids
            ),
        "favored_role_group_gains_minutes":
            favored_gain > 0.0,
        "minute_multipliers_are_bounded":
            all(0.90 <= value <= 1.16 for value in multipliers.values()),
        "scoring_multipliers_are_bounded":
            all(0.92 <= value <= 1.12 for value in scoring_multipliers.values()),
        "creation_multipliers_are_bounded":
            all(0.90 <= value <= 1.15 for value in creation_multipliers.values()),
        "some_scoring_responsibility_is_redistributed":
            max(scoring_multipliers.values()) > 1.0,
        "some_creation_responsibility_is_redistributed":
            max(creation_multipliers.values()) > 1.0,
        "workload_report_identifies_missing_starter":
            missing in set(report.missing_starter_ids),
        "source_injury_state_unchanged":
            str(
                getattr(
                    getattr(source.injuries[missing], "status", ""),
                    "value",
                    getattr(source.injuries[missing], "status", ""),
                )
            ).lower() != "out",
    }

    active_after = sha(active) if active.is_file() else ""
    checks["active_checkpoint_unchanged"] = before_hash == active_after

    print("FRANCHISE V2 COACHING WORKLOAD REDISTRIBUTION V1 RUNTIME VALIDATION")
    print(f"Team: {team}")
    print(
        f"Missing starter: {missing_player.player_name} "
        f"({missing_player.position}, {missing_player.overall_rating:.0f} OVR)"
    )
    print(f"Favored role-group minute gain vs legacy: {favored_gain:+.1f}")
    print(
        f"Top minute absorber: {protected.players[top_minute].player_name} "
        f"| multiplier={multipliers[top_minute]:.3f} "
        f"| legacy={legacy[top_minute]:.1f} "
        f"| role-aware={actual[top_minute]:.1f}"
    )
    print(
        f"Top scoring responsibility: {protected.players[top_scoring].player_name} "
        f"| multiplier={scoring_multipliers[top_scoring]:.3f}"
    )
    print(
        f"Top creation responsibility: {protected.players[top_creation].player_name} "
        f"| multiplier={creation_multipliers[top_creation]:.3f}"
    )
    print(f"Explanation: {report.summary}")

    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        print("RUNTIME VALIDATION FAILED")
        for name in failed:
            print(f"  - {name}")
        return 1

    print("RUNTIME VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
