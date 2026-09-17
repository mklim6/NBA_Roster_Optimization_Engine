from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from franchise_free_agency_cpu_execution_v1 import (
    _cpu_roster_floor_deficits,
    _minimum_game_player_floor,
    execute_cpu_free_agency_round_durably,
)
from franchise_free_agency_live_signing_v1 import (
    controlled_teams_from_durable_checkpoint,
)
from franchise_season_boundary_durable_transition_v1 import (
    checkpoint_boundary_fingerprint,
)
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint


PRESEASON_ROSTER_FLOOR_VERSION = (
    "franchise-preseason-roster-floor-live-v1.0-2026-09-15"
)


class PreseasonRosterFloorError(RuntimeError):
    """Raised when opening night cannot safely reach the playable roster floor."""


@dataclass(frozen=True)
class PreseasonRosterFloorResult:
    version: str
    status: str
    initial_cpu_deficits: tuple[tuple[str, int, int], ...]
    final_cpu_deficits: tuple[tuple[str, int, int], ...]
    committed_signing_count: int
    signing_summaries: tuple[str, ...]
    target_fingerprint: str


def _controlled_roster_deficits(
    state: Any,
    controlled_teams: tuple[str, ...],
) -> tuple[tuple[str, int, int], ...]:
    floor = _minimum_game_player_floor(state)
    rows: list[tuple[str, int, int]] = []
    teams = getattr(state, "teams", {}) or {}
    for team in controlled_teams:
        team_state = teams.get(team)
        if team_state is None:
            continue
        count = len(tuple(getattr(team_state, "roster_player_ids", ()) or ()))
        if count < floor:
            rows.append((team, count, floor - count))
    return tuple(sorted(rows))


def complete_preseason_roster_floors_durably(
    *,
    expected_source_fingerprint: str,
) -> PreseasonRosterFloorResult:
    """Fill CPU opening-night roster deficits through the canonical FA stack.

    User-controlled teams remain the user's responsibility. CPU teams receive
    only legal, player-accepted contracts, and every signing is committed by
    the existing byte-verified Free Agency transaction path. The number of
    attempts is derived from the actual deficits; no rescue limit is inflated.
    """
    checkpoint = load_franchise_checkpoint(allow_backup=False)
    if checkpoint is None:
        raise PreseasonRosterFloorError(
            "The durable Franchise checkpoint is unavailable."
        )
    observed = checkpoint_boundary_fingerprint(checkpoint)
    if observed != str(expected_source_fingerprint or ""):
        raise PreseasonRosterFloorError(
            "The Franchise checkpoint changed before the opening-night roster check."
        )

    state = checkpoint.simulation_state
    phase = str(getattr(state, "phase", "")).lower()
    if "offseason" not in phase:
        raise PreseasonRosterFloorError(
            "Opening-night roster completion can run only during the offseason."
        )
    controlled = tuple(controlled_teams_from_durable_checkpoint(checkpoint))
    user_deficits = _controlled_roster_deficits(state, controlled)
    if user_deficits:
        detail = ", ".join(
            f"{team} has {count} and needs {needed} more"
            for team, count, needed in user_deficits
        )
        raise PreseasonRosterFloorError(
            "A user-controlled roster is below the playable floor: " + detail + "."
        )

    initial = _cpu_roster_floor_deficits(state, controlled)
    if not initial:
        return PreseasonRosterFloorResult(
            version=PRESEASON_ROSTER_FLOOR_VERSION,
            status="already_playable",
            initial_cpu_deficits=(),
            final_cpu_deficits=(),
            committed_signing_count=0,
            signing_summaries=(),
            target_fingerprint=observed,
        )

    remaining = initial
    committed = 0
    summaries: list[str] = []
    while remaining:
        deficit_count = sum(row[2] for row in remaining)
        round_result = execute_cpu_free_agency_round_durably(
            max_signings=min(15, deficit_count),
        )
        committed += int(round_result.committed_signing_count)
        summaries.extend(
            f"{row.player_name} -> {row.team_abbreviation}"
            for row in round_result.signings
        )

        checkpoint = load_franchise_checkpoint(allow_backup=False)
        if checkpoint is None:
            raise PreseasonRosterFloorError(
                "The checkpoint could not be reloaded after CPU roster completion."
            )
        controlled = tuple(controlled_teams_from_durable_checkpoint(checkpoint))
        next_remaining = _cpu_roster_floor_deficits(
            checkpoint.simulation_state,
            controlled,
        )
        next_count = sum(row[2] for row in next_remaining)
        if next_count >= deficit_count:
            raise PreseasonRosterFloorError(
                "CPU roster completion made no progress. "
                f"Remaining deficits: {next_remaining or remaining}."
            )
        remaining = next_remaining

    return PreseasonRosterFloorResult(
        version=PRESEASON_ROSTER_FLOOR_VERSION,
        status="completed",
        initial_cpu_deficits=initial,
        final_cpu_deficits=remaining,
        committed_signing_count=committed,
        signing_summaries=tuple(summaries),
        target_fingerprint=checkpoint_boundary_fingerprint(checkpoint),
    )


__all__ = [
    "PRESEASON_ROSTER_FLOOR_VERSION",
    "PreseasonRosterFloorError",
    "PreseasonRosterFloorResult",
    "complete_preseason_roster_floors_durably",
]
