from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from simulation_league_alignment_v1 import (  # noqa: E402
    apply_nba_team_alignment,
)
from simulation_league_state_v1 import (  # noqa: E402
    RotationState,
    SimulationLeagueState,
    minutes_targets,
    validate_simulation_league_state,
)


TRADE_SYNC_VERSION = (
    "simulation-trade-sync-v1.0.1-2026-08-08"
)
SELF_TEST_REPORT = (
    OUTPUTS
    / "simulation_trade_sync_v1_self_test.json"
)


class SimulationTradeSyncError(
    RuntimeError
):
    """Raised when a trade universe cannot be merged into a season."""


@dataclass(frozen=True)
class PlayerTeamMove:
    player_id: str
    player_name: str
    old_team: str
    new_team: str


@dataclass(frozen=True)
class TradeSyncPreview:
    version: str
    source_revision: int
    target_revision: int
    source_transaction_count: int
    target_transaction_count: int
    moves: tuple[PlayerTeamMove, ...]
    affected_teams: tuple[str, ...]
    free_agent_changes: int


@dataclass(frozen=True)
class TradeSyncResult:
    version: str
    source_revision: int
    target_revision: int
    source_transaction_count: int
    target_transaction_count: int
    moved_players: tuple[PlayerTeamMove, ...]
    affected_teams: tuple[str, ...]
    preserved_schedule_games: int
    preserved_completed_games: int
    preserved_current_day: int
    preserved_season_label: str
    pick_only_or_metadata_only: bool


def clean_team(value: Any) -> str:
    text = str(
        value or ""
    ).strip().upper()
    return text


def clean_player_id(value: Any) -> str:
    return str(
        value or ""
    ).strip()


def trade_player_team_map(
    trade_state: Any,
) -> Mapping[str, Any]:
    mapping = getattr(
        trade_state,
        "player_team_by_id",
        None,
    )

    if not isinstance(mapping, dict):
        raise SimulationTradeSyncError(
            "Trade state has no player-team mapping."
        )

    return mapping


def trade_revision(
    trade_state: Any,
) -> int:
    try:
        return int(
            trade_state.state_revision
        )
    except (
        AttributeError,
        TypeError,
        ValueError,
    ) as exc:
        raise SimulationTradeSyncError(
            "Trade state has no valid revision."
        ) from exc


def trade_transaction_count(
    trade_state: Any,
) -> int:
    try:
        return len(
            trade_state.transaction_history
        )
    except (
        AttributeError,
        TypeError,
    ) as exc:
        raise SimulationTradeSyncError(
            "Trade state has no transaction history."
        ) from exc


def _stable_value(value: Any) -> Any:
    if is_dataclass(value):
        return {
            key: _stable_value(item)
            for key, item
            in asdict(value).items()
        }

    if isinstance(value, dict):
        return {
            str(key): _stable_value(item)
            for key, item
            in sorted(
                value.items(),
                key=lambda pair: str(
                    pair[0]
                ),
            )
        }

    if isinstance(value, (list, tuple)):
        return [
            _stable_value(item)
            for item in value
        ]

    if hasattr(value, "value"):
        return value.value

    return value


def season_preservation_payload(
    state: SimulationLeagueState,
) -> dict[str, Any]:
    return {
        "phase": _stable_value(
            state.phase
        ),
        "current_day_index": int(
            state.current_day_index
        ),
        "season_label": (
            state.settings.season_label
        ),
        "schedule": _stable_value(
            state.schedule
        ),
        "completed_games": _stable_value(
            state.completed_games
        ),
        "standings": _stable_value(
            state.standings
        ),
        "injuries": _stable_value(
            state.injuries
        ),
        "player_season_totals": (
            _stable_value(
                state.player_season_totals
            )
        ),
        "season_history": _stable_value(
            state.season_history
        ),
        "season_transition_count": int(
            getattr(
                state,
                "season_transition_count",
                0,
            )
        ),
    }


def season_preservation_fingerprint(
    state: SimulationLeagueState,
) -> str:
    payload = json.dumps(
        season_preservation_payload(
            state
        ),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()


def desired_team_for_player(
    trade_state: Any,
    player_id: str,
) -> str:
    mapping = trade_player_team_map(
        trade_state
    )
    raw = mapping.get(
        clean_player_id(player_id)
    )
    return clean_team(raw)


def build_trade_sync_preview(
    state: SimulationLeagueState,
    trade_state: Any,
) -> TradeSyncPreview:
    moves: list[PlayerTeamMove] = []
    affected: set[str] = set()
    free_agent_changes = 0

    for player_id, player in (
        state.players.items()
    ):
        if player.synthetic:
            continue

        new_team = desired_team_for_player(
            trade_state,
            player_id,
        )
        old_team = clean_team(
            player.team_abbreviation
        )

        if new_team == old_team:
            continue

        if (
            new_team
            and new_team not in state.teams
        ):
            raise SimulationTradeSyncError(
                f"Trade state assigns "
                f"{player.player_name} to "
                f"unknown team {new_team}."
            )

        moves.append(
            PlayerTeamMove(
                player_id=player_id,
                player_name=(
                    player.player_name
                ),
                old_team=old_team,
                new_team=new_team,
            )
        )
        affected.update(
            team
            for team in (
                old_team,
                new_team,
            )
            if team
        )

        if not old_team or not new_team:
            free_agent_changes += 1

    moves.sort(
        key=lambda move: (
            move.old_team,
            move.new_team,
            move.player_name,
            move.player_id,
        )
    )

    return TradeSyncPreview(
        version=TRADE_SYNC_VERSION,
        source_revision=int(
            state.source_league_state_revision
        ),
        target_revision=trade_revision(
            trade_state
        ),
        source_transaction_count=int(
            state.source_transaction_count
        ),
        target_transaction_count=(
            trade_transaction_count(
                trade_state
            )
        ),
        moves=tuple(moves),
        affected_teams=tuple(
            sorted(affected)
        ),
        free_agent_changes=(
            free_agent_changes
        ),
    )


def _rebuild_affected_rotation(
    state: SimulationLeagueState,
    team: str,
) -> None:
    team_state = state.teams[team]
    ordered = tuple(
        sorted(
            team_state.roster_player_ids,
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
    rotation_ids = ordered[
        :rotation_size
    ]
    starter_ids = rotation_ids[:5]

    if len(starter_ids) < 5:
        raise SimulationTradeSyncError(
            f"{team} has fewer than five "
            "players after trade synchronization."
        )

    team_state.rotation = RotationState(
        starter_ids=starter_ids,
        rotation_player_ids=(
            rotation_ids
        ),
        minutes_targets=minutes_targets(
            rotation_ids,
            starter_ids,
            regulation_minutes=(
                state.settings
                .regulation_minutes
            ),
        ),
    )
    team_state.active_player_ids = (
        rotation_ids
    )
    rotation_set = set(rotation_ids)
    team_state.inactive_player_ids = (
        tuple(
            player_id
            for player_id in ordered
            if player_id
            not in rotation_set
        )
    )


def synchronize_simulation_with_trade_state(
    state: SimulationLeagueState,
    trade_state: Any,
) -> tuple[
    SimulationLeagueState,
    TradeSyncResult,
]:
    """Merge player ownership into an active season transactionally."""
    preview = build_trade_sync_preview(
        state,
        trade_state,
    )
    before_fingerprint = (
        season_preservation_fingerprint(
            state
        )
    )
    updated = copy.deepcopy(state)
    desired_map = (
        trade_player_team_map(
            trade_state
        )
    )

    # Player season totals are keyed by player ID, so they naturally retain
    # production earned for the player's previous team.
    for player_id, player in (
        updated.players.items()
    ):
        if player.synthetic:
            continue

        desired_team = clean_team(
            desired_map.get(
                clean_player_id(
                    player_id
                )
            )
        )
        player.team_abbreviation = (
            desired_team
        )
        player.roster_status = (
            "active_roster"
            if desired_team
            else "free_agent"
        )

    roster_by_team: dict[
        str,
        list[str],
    ] = {
        team: []
        for team in updated.teams
    }
    free_agents: list[str] = []

    for player_id, player in (
        updated.players.items()
    ):
        team = clean_team(
            player.team_abbreviation
        )

        if team:
            if team not in roster_by_team:
                raise SimulationTradeSyncError(
                    f"Player {player.player_name} "
                    f"has unknown team {team}."
                )
            roster_by_team[
                team
            ].append(player_id)
        else:
            free_agents.append(player_id)

    for team, player_ids in (
        roster_by_team.items()
    ):
        old_order = {
            player_id: index
            for index, player_id
            in enumerate(
                updated.teams[
                    team
                ].roster_player_ids
            )
        }
        ordered = tuple(
            sorted(
                player_ids,
                key=lambda player_id: (
                    old_order.get(
                        player_id,
                        10_000,
                    ),
                    -updated.players[
                        player_id
                    ].overall_rating,
                    updated.players[
                        player_id
                    ].player_name,
                ),
            )
        )
        updated.teams[
            team
        ].roster_player_ids = ordered

    updated.free_agent_player_ids = (
        tuple(
            sorted(
                free_agents,
                key=lambda player_id: (
                    updated.players[
                        player_id
                    ].player_name,
                    player_id,
                ),
            )
        )
    )

    for team in preview.affected_teams:
        _rebuild_affected_rotation(
            updated,
            team,
        )

    apply_nba_team_alignment(
        updated
    )
    updated.source_league_state_revision = (
        preview.target_revision
    )
    updated.source_transaction_count = (
        preview.target_transaction_count
    )

    validate_simulation_league_state(
        updated
    )

    after_fingerprint = (
        season_preservation_fingerprint(
            updated
        )
    )

    if after_fingerprint != before_fingerprint:
        raise SimulationTradeSyncError(
            "Trade synchronization changed "
            "season results or history."
        )

    if (
        season_preservation_fingerprint(
            state
        )
        != before_fingerprint
    ):
        raise SimulationTradeSyncError(
            "Trade synchronization mutated "
            "the source state."
        )

    result = TradeSyncResult(
        version=TRADE_SYNC_VERSION,
        source_revision=(
            preview.source_revision
        ),
        target_revision=(
            preview.target_revision
        ),
        source_transaction_count=(
            preview
            .source_transaction_count
        ),
        target_transaction_count=(
            preview
            .target_transaction_count
        ),
        moved_players=preview.moves,
        affected_teams=(
            preview.affected_teams
        ),
        preserved_schedule_games=len(
            updated.schedule
        ),
        preserved_completed_games=len(
            updated.completed_games
        ),
        preserved_current_day=int(
            updated.current_day_index
        ),
        preserved_season_label=(
            updated.settings.season_label
        ),
        pick_only_or_metadata_only=(
            not preview.moves
        ),
    )
    return updated, result


def run_self_test(
    *,
    seed: int = 20260808,
) -> dict[str, Any]:
    from regular_season_simulation_controller_v1 import (
        SimulationScope,
        build_installed_state,
        simulate_regular_season_scope,
    )

    state = build_installed_state(
        seed=seed
    )
    state, simulation = (
        simulate_regular_season_scope(
            state,
            scope=SimulationScope.NEXT_DAY,
        )
    )
    teams = sorted(state.teams)
    team_a = teams[0]
    team_b = teams[1]
    player_a = state.teams[
        team_a
    ].roster_player_ids[0]
    player_b = state.teams[
        team_b
    ].roster_player_ids[0]
    player_map = {
        player_id: (
            player.team_abbreviation
            or None
        )
        for player_id, player
        in state.players.items()
        if not player.synthetic
    }
    player_map[player_a] = team_b
    player_map[player_b] = team_a
    trade_state = SimpleNamespace(
        state_revision=(
            state
            .source_league_state_revision
            + 1
        ),
        transaction_history=[
            *range(
                state
                .source_transaction_count
            ),
            "trade",
        ],
        player_team_by_id=(
            player_map
        ),
    )
    before = (
        season_preservation_fingerprint(
            state
        )
    )
    preview = build_trade_sync_preview(
        state,
        trade_state,
    )
    updated, result = (
        synchronize_simulation_with_trade_state(
            state,
            trade_state,
        )
    )

    pick_only = SimpleNamespace(
        state_revision=(
            updated
            .source_league_state_revision
            + 1
        ),
        transaction_history=[
            *trade_state
            .transaction_history,
            "pick-only",
        ],
        player_team_by_id={
            player_id: (
                player.team_abbreviation
                or None
            )
            for player_id, player
            in updated.players.items()
            if not player.synthetic
        },
    )
    pick_updated, pick_result = (
        synchronize_simulation_with_trade_state(
            updated,
            pick_only,
        )
    )

    checks = {
        "trade_sync_version_is_current": (
            result.version
            == TRADE_SYNC_VERSION
        ),
        "preview_detects_two_moves": (
            len(preview.moves) == 2
        ),
        "preview_detects_affected_teams": (
            set(
                preview.affected_teams
            )
            == {team_a, team_b}
        ),
        "source_state_is_unchanged": (
            season_preservation_fingerprint(
                state
            )
            == before
            and state.players[
                player_a
            ].team_abbreviation
            == team_a
        ),
        "schedule_is_preserved": (
            len(updated.schedule)
            == len(state.schedule)
            and updated.schedule
            == state.schedule
        ),
        "completed_games_are_preserved": (
            len(
                updated.completed_games
            )
            == simulation.games_simulated
            and updated.completed_games
            == state.completed_games
        ),
        "standings_are_preserved": (
            updated.standings
            == state.standings
        ),
        "player_totals_are_preserved": (
            updated.player_season_totals
            == state.player_season_totals
        ),
        "current_day_is_preserved": (
            updated.current_day_index
            == state.current_day_index
        ),
        "players_move_to_new_teams": (
            updated.players[
                player_a
            ].team_abbreviation
            == team_b
            and updated.players[
                player_b
            ].team_abbreviation
            == team_a
        ),
        "rosters_reconcile_after_trade": (
            player_a
            in updated.teams[
                team_b
            ].roster_player_ids
            and player_a
            not in updated.teams[
                team_a
            ].roster_player_ids
        ),
        "affected_rotations_have_five_starters": all(
            len(
                updated.teams[
                    team
                ].rotation.starter_ids
            )
            == 5
            for team
            in result.affected_teams
        ),
        "source_revision_is_updated": (
            updated
            .source_league_state_revision
            == trade_state.state_revision
            and updated
            .source_transaction_count
            == len(
                trade_state
                .transaction_history
            )
        ),
        "pick_only_trade_preserves_season": (
            pick_result
            .pick_only_or_metadata_only
            and season_preservation_fingerprint(
                pick_updated
            )
            == season_preservation_fingerprint(
                updated
            )
        ),
    }
    failed = [
        name
        for name, passed
        in checks.items()
        if not passed
    ]
    report = {
        "script": TRADE_SYNC_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "simulation_games": (
                simulation.games_simulated
            ),
            "preview": asdict(preview),
            "result": asdict(result),
            "pick_only_result": asdict(
                pick_result
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
            default=str,
        ),
        encoding="utf-8",
    )

    if failed:
        raise AssertionError(
            "Simulation trade sync self-test "
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
    parser.add_argument(
        "--seed",
        type=int,
        default=20260808,
    )
    args = parser.parse_args()

    if args.self_test:
        report = run_self_test(
            seed=args.seed
        )
        print(
            json.dumps(
                report,
                indent=2,
                default=str,
            )
        )
        print(
            "\nSIMULATION TRADE SYNC "
            "V1 SELF-TEST PASSED"
        )
        return 0

    print(
        json.dumps(
            {
                "script": (
                    TRADE_SYNC_VERSION
                ),
                "message": (
                    "Use --self-test to validate "
                    "in-season trade synchronization."
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
