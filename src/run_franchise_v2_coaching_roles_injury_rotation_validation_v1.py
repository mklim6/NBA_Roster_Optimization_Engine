from __future__ import annotations

import copy
import hashlib
from pathlib import Path

from franchise_coaching_role_rotation_v1 import (
    functional_role_profile_v1,
    primary_roles_v1,
    replacement_candidate_score_v1,
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
    available_team_players,
    select_game_rotation,
)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def clean(value) -> str:
    return str(value or "").strip()


def legacy_starters(available, original):
    result = [pid for pid in original if pid in available]
    for pid in available:
        if len(result) >= 5:
            break
        if pid not in result:
            result.append(pid)
    return tuple(result[:5])


def main() -> int:
    active = Path(DEFAULT_CHECKPOINT_PATH)
    before_hash = sha(active) if active.is_file() else ""

    checkpoint = load_franchise_checkpoint(allow_backup=False)
    if checkpoint is None:
        raise RuntimeError("Active franchise checkpoint is unavailable.")

    source = checkpoint.simulation_state
    config = GameSimulationConfig()

    candidate_team = None
    candidate_starter = None

    for team, team_state in sorted(source.teams.items()):
        starters = tuple(team_state.rotation.starter_ids)
        if len(starters) != 5:
            continue
        available = available_team_players(source, team, set())
        healthy_starters = [pid for pid in starters if pid in available]
        if len(healthy_starters) < 5 or len(available) < 8:
            continue
        # Choose the starter with the strongest primary-creator signal so the
        # role-replacement test is difficult and basketball-relevant.
        ranked = sorted(
            healthy_starters,
            key=lambda pid: (
                -functional_role_profile_v1(source, pid).scores["primary_creator"],
                -float(source.players[pid].overall_rating),
                pid,
            ),
        )
        candidate_team = team
        candidate_starter = ranked[0]
        break

    if candidate_team is None or candidate_starter is None:
        raise RuntimeError("No fully healthy five-starter team is available for validation.")

    team = candidate_team
    missing = candidate_starter
    original_starters = tuple(source.teams[team].rotation.starter_ids)

    # Healthy behavior must remain identical to the historical starter-fill algorithm.
    healthy_available = available_team_players(source, team, set())
    healthy_rotation, healthy_starters = select_game_rotation(
        source,
        team,
        sit_player_ids=set(),
        config=config,
    )
    expected_healthy = legacy_starters(healthy_available, original_starters)

    protected = copy.deepcopy(source)
    set_player_injury(
        protected,
        missing,
        status=AvailabilityStatus.OUT,
        injury_type="protected coaching-intelligence validation",
        games_remaining=1,
        performance_multiplier=1.0,
        aggravation_risk=0.0,
        notes="protected runtime only",
    )

    injured_available = available_team_players(protected, team, set())
    legacy = legacy_starters(injured_available, original_starters)
    legacy_replacement = next(
        pid for pid in legacy
        if pid not in set(original_starters)
    )

    rotation, starters = select_game_rotation(
        protected,
        team,
        sit_player_ids=set(),
        config=config,
    )
    replacement = next(
        pid for pid in starters
        if pid not in set(original_starters)
    )

    replacement_metrics = replacement_candidate_score_v1(
        protected,
        team,
        missing,
        replacement,
        rotation_priority_index=injured_available.index(replacement),
    )
    legacy_metrics = replacement_candidate_score_v1(
        protected,
        team,
        missing,
        legacy_replacement,
        rotation_priority_index=injured_available.index(legacy_replacement),
    )

    missing_profile = functional_role_profile_v1(protected, missing)
    replacement_profile = functional_role_profile_v1(protected, replacement)
    top_roles = primary_roles_v1(protected, missing, limit=3)

    checks = {
        "healthy_saved_starters_are_identical":
            tuple(healthy_starters) == tuple(expected_healthy),
        "healthy_rotation_keeps_five_starters":
            len(healthy_starters) == 5,
        "injured_starter_is_removed":
            missing not in set(rotation) and missing not in set(starters),
        "injury_reconstruction_has_five_starters":
            len(starters) == 5 and len(set(starters)) == 5,
        "injury_rotation_has_at_least_five_players":
            len(rotation) >= 5,
        "replacement_is_available":
            replacement in set(injured_available),
        "replacement_model_beats_or_matches_legacy_combined_fit":
            float(replacement_metrics["combined"])
            + 1e-9
            >= float(legacy_metrics["combined"]),
        "missing_player_has_functional_roles":
            bool(top_roles),
        "replacement_has_functional_role_profile":
            len(replacement_profile.scores) >= 10,
        "source_injury_state_unchanged":
            clean(getattr(source.injuries[missing].status, "value", source.injuries[missing].status))
            != "out",
    }

    active_after = sha(active) if active.is_file() else ""
    checks["active_checkpoint_unchanged"] = before_hash == active_after

    print("FRANCHISE V2 COACHING ROLES / INJURY ROTATION V1 RUNTIME VALIDATION")
    print(f"Team: {team}")
    print(
        f"Missing starter: {missing_profile.player_name} "
        f"({missing_profile.position}, {source.players[missing].overall_rating:.0f} OVR)"
    )
    print(
        "Primary missing roles: "
        + ", ".join(f"{role}={score:.1f}" for role, score in top_roles)
    )
    print(
        f"Legacy replacement: {source.players[legacy_replacement].player_name} "
        f"| combined={legacy_metrics['combined']:.2f} "
        f"| role_fit={legacy_metrics['role_fit']:.2f}"
    )
    print(
        f"Role-aware replacement: {source.players[replacement].player_name} "
        f"| combined={replacement_metrics['combined']:.2f} "
        f"| role_fit={replacement_metrics['role_fit']:.2f}"
    )

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
