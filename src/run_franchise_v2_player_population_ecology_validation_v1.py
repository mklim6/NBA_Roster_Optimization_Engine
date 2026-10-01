from __future__ import annotations

import copy
import hashlib
from pathlib import Path

from franchise_free_agent_population_ecology_v1 import (
    ECOLOGY_MARKER_ATTR,
    INACTIVE_POOL_ATTR,
    UNSIGNED_SEASONS_ATTR,
    apply_free_agent_population_ecology_at_boundary,
)
from simulation_franchise_checkpoint_v1 import (
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)
from simulation_league_state_v1 import validate_simulation_league_state


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def clean(value) -> str:
    return str(value or "").strip()


def main() -> int:
    active = Path(DEFAULT_CHECKPOINT_PATH)
    before_hash = sha(active) if active.is_file() else ""
    checkpoint = load_franchise_checkpoint(allow_backup=False)
    if checkpoint is None:
        raise RuntimeError("Active franchise checkpoint is unavailable.")

    source = checkpoint.simulation_state
    source_players = set(source.players)
    source_fas = set(source.free_agent_player_ids)
    source_rosters = {
        clean(pid)
        for team in source.teams.values()
        for pid in tuple(team.roster_player_ids or ())
        if clean(pid)
    }

    trial = copy.deepcopy(source)
    # Seed the protected clone as if current free agents had already spent
    # three unsuccessful NBA markets.  This tests the removal mechanics, not
    # the live save's historical unsigned counter initialization.
    setattr(
        trial,
        UNSIGNED_SEASONS_ATTR,
        {
            pid: 3
            for pid in trial.free_agent_player_ids
            if pid in trial.players
        },
    )

    free_count = len(trial.free_agent_player_ids)
    if free_count < 2:
        raise RuntimeError("Protected checkpoint has too few free agents to validate ecology.")

    # Force only a small protected-clone trim so the validation is independent
    # of the production 300/270 market band.
    target = max(1, free_count - min(8, max(1, free_count // 20)))
    candidate, result = apply_free_agent_population_ecology_at_boundary(
        trial,
        copy_payload=False,
        soft_max_active_free_agents=max(1, free_count - 1),
        target_active_free_agents=target,
        minimum_free_agent_reserve=0,
    )
    validate_simulation_league_state(candidate)

    departed = {record.player_id for record in result.departures}
    candidate_rosters = {
        clean(pid)
        for team in candidate.teams.values()
        for pid in tuple(team.roster_player_ids or ())
        if clean(pid)
    }

    checks = {
        "source_player_population_unchanged": set(source.players) == source_players,
        "source_free_agent_pool_unchanged": set(source.free_agent_player_ids) == source_fas,
        "source_rosters_unchanged": source_rosters == {
            clean(pid)
            for team in source.teams.values()
            for pid in tuple(team.roster_player_ids or ())
            if clean(pid)
        },
        "protected_candidate_valid": bool(validate_simulation_league_state(candidate)),
        "departures_occurred": len(departed) > 0,
        "departures_were_source_free_agents": departed.issubset(source_fas),
        "no_rostered_player_departed": not departed.intersection(source_rosters),
        "departed_removed_from_players": departed.isdisjoint(candidate.players),
        "departed_removed_from_free_agent_pool": departed.isdisjoint(candidate.free_agent_player_ids),
        "candidate_rosters_unchanged": candidate_rosters == source_rosters,
        "candidate_population_reduced_exactly": (
            len(candidate.players) == len(source.players) - len(departed) + len(result.reentries)
        ),
        "ecology_marker_written": isinstance(getattr(candidate, ECOLOGY_MARKER_ATTR, None), dict),
        "inactive_archive_bounded": len(getattr(candidate, INACTIVE_POOL_ATTR, {}) or {}) <= 72,
    }

    active_after = sha(active) if active.is_file() else ""
    checks["active_checkpoint_unchanged"] = before_hash == active_after

    print("FRANCHISE V2 PLAYER POPULATION ECOLOGY V1 RUNTIME VALIDATION")
    print(f"Source players: {len(source.players)}")
    print(f"Source free agents: {len(source.free_agent_player_ids)}")
    print(f"Protected departures: {len(result.departures)}")
    print(f"Protected reentries: {len(result.reentries)}")
    print(f"Candidate players: {len(candidate.players)}")
    print(f"Candidate free agents: {len(candidate.free_agent_player_ids)}")
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
