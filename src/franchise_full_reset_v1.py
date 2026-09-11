from __future__ import annotations

import copy
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from freeform_trade_machine_engine_v3 import RuntimeData
from mutable_league_state_v1 import LeagueState, create_league_state
from regular_season_schedule_v1 import (
    LEAGUE_GAME_COUNT,
    generate_regular_season_schedule,
    install_regular_season_schedule,
)
import simulation_franchise_checkpoint_v1 as checkpoint_api
import simulation_roster_validator_v1 as roster_validator
from franchise_career_lifecycle_v1 import initialize_career_intents_for_season
from simulation_league_alignment_v1 import apply_nba_team_alignment
from simulation_league_state_v1 import (
    LeaguePhase,
    SimulationLeagueState,
    create_simulation_league_state,
    validate_simulation_league_state,
)


FULL_RESET_VERSION = "franchise-full-reset-v1-2026-08-11"
RESET_STARTING_SEASON = "2026-27"
RESET_CONFIRMATION_PHRASE = "RESET LEAGUE"


class FranchiseFullResetError(RuntimeError):
    pass


@dataclass(frozen=True)
class StartingFranchiseBuild:
    version: str
    simulation_state: SimulationLeagueState
    trade_state: LeagueState
    schedule_signature: str
    players: int
    rostered_players: int
    free_agents: int
    schedule_games: int
    career_considering: int
    farewell_announcements: int


@dataclass(frozen=True)
class FranchiseResetCommitResult:
    version: str
    backup_directory: str
    source_season: str
    target_season: str
    source_players: int
    target_players: int
    target_schedule_games: int
    saved_at_utc: str
    checkpoint_reason: str


def _count_container(value: Any) -> int:
    if value is None:
        return 0
    try:
        return len(value)
    except TypeError:
        return 0


def _postseason_games(state: SimulationLeagueState) -> int:
    postseason = getattr(state, "postseason_state", None)
    if postseason is None:
        return 0
    return _count_container(getattr(postseason, "completed_games", {}))


def _active_injuries(state: SimulationLeagueState) -> int:
    total = 0
    for injury in getattr(state, "injuries", {}).values():
        value = getattr(getattr(injury, "status", None), "value", getattr(injury, "status", ""))
        if str(value).lower() not in {"healthy", "available", ""}:
            total += 1
    return total


def build_full_reset_preview(
    state: SimulationLeagueState,
    trade_state: LeagueState | None = None,
) -> dict[str, Any]:
    players = getattr(state, "players", {})
    synthetic = sum(bool(getattr(player, "synthetic", False)) for player in players.values())
    completed_draft_history = 0
    for name in (
        "draft_history",
        "completed_draft_history",
        "completed_drafts",
        "franchise_draft_history",
    ):
        completed_draft_history = max(
            completed_draft_history,
            _count_container(getattr(state, name, None)),
        )

    transaction_count = 0
    if trade_state is not None:
        transaction_count = _count_container(getattr(trade_state, "transaction_history", ()))

    return {
        "version": FULL_RESET_VERSION,
        "season": str(state.settings.season_label),
        "phase": str(getattr(state.phase, "value", state.phase)),
        "players": len(players),
        "generated_or_synthetic_players": synthetic,
        "free_agents": _count_container(getattr(state, "free_agent_player_ids", ())),
        "schedule_games": _count_container(getattr(state, "schedule", {})),
        "completed_games": _count_container(getattr(state, "completed_games", {})),
        "postseason_games": _postseason_games(state),
        "archived_seasons": _count_container(getattr(state, "season_history", ())),
        "transition_count": int(getattr(state, "transition_count", 0) or 0),
        "retirement_history": _count_container(getattr(state, "retirement_history", ())),
        "career_intent_history": _count_container(getattr(state, "career_intent_history", ())),
        "draft_history": completed_draft_history,
        "active_injuries": _active_injuries(state),
        "trade_transactions": transaction_count,
    }


def _resolve_positions(state: SimulationLeagueState, runtime: RuntimeData) -> None:
    loader = getattr(roster_validator, "load_position_records", None)
    if loader is not None and hasattr(loader, "cache_clear"):
        loader.cache_clear()

    unresolved: list[str] = []
    for player_id, player in state.players.items():
        if bool(getattr(player, "synthetic", False)):
            continue
        position = roster_validator.player_position(runtime, player_id)
        if position == "UNK":
            unresolved.append(f"{player.player_name} ({player_id})")
        else:
            player.position = position

    if unresolved:
        sample = ", ".join(unresolved[:8])
        suffix = f" and {len(unresolved) - 8} more" if len(unresolved) > 8 else ""
        raise FranchiseFullResetError(
            "Fresh franchise position enrichment returned UNK for "
            f"{len(unresolved)} player(s): {sample}{suffix}."
        )


def build_starting_franchise(runtime: RuntimeData) -> StartingFranchiseBuild:
    trade_state = create_league_state(runtime)
    state = create_simulation_league_state(runtime, trade_state)
    apply_nba_team_alignment(state)
    _resolve_positions(state, runtime)

    if str(state.settings.season_label) != RESET_STARTING_SEASON:
        raise FranchiseFullResetError(
            f"Fresh league started in {state.settings.season_label}, not {RESET_STARTING_SEASON}."
        )

    if state.phase != LeaguePhase.PRESEASON:
        raise FranchiseFullResetError("Fresh league did not begin in preseason.")

    schedule = generate_regular_season_schedule(
        state,
        seed=int(state.settings.random_seed),
    )
    install_regular_season_schedule(state, schedule)

    career_summary = initialize_career_intents_for_season(state)
    validate_simulation_league_state(state)

    if len(state.schedule) != LEAGUE_GAME_COUNT:
        raise FranchiseFullResetError("Fresh league did not receive the full 1,230-game schedule.")
    if state.phase != LeaguePhase.REGULAR_SEASON:
        raise FranchiseFullResetError("Fresh league did not enter regular season after schedule installation.")
    if state.completed_games:
        raise FranchiseFullResetError("Fresh league unexpectedly contains completed games.")
    if getattr(state, "season_history", []):
        raise FranchiseFullResetError("Fresh league unexpectedly contains archived seasons.")
    if int(getattr(state, "transition_count", 0) or 0) != 0:
        raise FranchiseFullResetError("Fresh league transition count is not zero.")
    if getattr(trade_state, "transaction_history", []):
        raise FranchiseFullResetError("Fresh Trade Machine state unexpectedly contains transactions.")

    rostered = sum(len(team.roster_player_ids) for team in state.teams.values())
    return StartingFranchiseBuild(
        version=FULL_RESET_VERSION,
        simulation_state=state,
        trade_state=trade_state,
        schedule_signature=str(getattr(schedule, "signature", "")),
        players=len(state.players),
        rostered_players=rostered,
        free_agents=len(state.free_agent_player_ids),
        schedule_games=len(state.schedule),
        career_considering=int(career_summary.get("considering_retirement", 0) or 0),
        farewell_announcements=int(career_summary.get("farewell_seasons", 0) or 0),
    )


def _checkpoint_path() -> Path:
    return Path(checkpoint_api.DEFAULT_CHECKPOINT_PATH).resolve()


def _checkpoint_family(path: Path) -> list[Path]:
    if not path.parent.exists():
        return []
    prefix = path.name.split(".pkl", 1)[0]
    return sorted(
        [candidate for candidate in path.parent.iterdir() if candidate.is_file() and candidate.name.startswith(prefix)],
        key=lambda candidate: candidate.name,
    )


def _snapshot_checkpoint_family(backup_dir: Path, primary: Path) -> list[str]:
    checkpoint_dir = backup_dir / "checkpoint"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for source in _checkpoint_family(primary):
        target = checkpoint_dir / source.name
        shutil.copy2(source, target)
        copied.append(source.name)
    return copied


def _restore_checkpoint_family(backup_dir: Path, primary: Path) -> None:
    checkpoint_dir = backup_dir / "checkpoint"
    if not checkpoint_dir.exists():
        return
    prefix = primary.name.split(".pkl", 1)[0]
    primary.parent.mkdir(parents=True, exist_ok=True)
    for current in list(primary.parent.iterdir()):
        if current.is_file() and current.name.startswith(prefix):
            current.unlink()
    for source in checkpoint_dir.iterdir():
        if source.is_file():
            shutil.copy2(source, primary.parent / source.name)


def _write_reset_manifest(
    backup_dir: Path,
    *,
    source_preview: Mapping[str, Any],
    checkpoint_files: list[str],
) -> None:
    manifest = {
        "version": FULL_RESET_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": dict(source_preview),
        "checkpoint_files": checkpoint_files,
        "restore_note": (
            "This directory contains the durable franchise checkpoint immediately before "
            "the full reset. It is intentionally retained as a manual recovery point."
        ),
    }
    (backup_dir / "reset_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str),
        encoding="utf-8",
    )


def commit_full_franchise_reset(
    runtime: RuntimeData,
    current_state: SimulationLeagueState,
    current_trade_state: LeagueState,
    *,
    preferences: Mapping[str, Any] | None = None,
) -> FranchiseResetCommitResult:
    """Durably replace the live franchise with a clean starting universe.

    The current in-memory franchise is saved first, then copied into a timestamped
    recovery directory before the clean checkpoint is written. If the replacement
    checkpoint fails validation, the pre-reset checkpoint family is restored.
    """
    validate_simulation_league_state(current_state)
    source_preview = build_full_reset_preview(current_state, current_trade_state)

    # Force the current in-memory state to disk so the recovery checkpoint is current.
    checkpoint_api.save_franchise_checkpoint(
        current_state,
        current_trade_state,
        preferences=dict(preferences or {}),
        reason="pre-full-franchise-reset-v1",
        copy_payload=True,
    )

    primary = _checkpoint_path()
    if not primary.is_file():
        raise FranchiseFullResetError("Could not create the pre-reset durable checkpoint.")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # DEFAULT_CHECKPOINT_PATH normally lives in <project>/outputs/runtime. Use project
    # root rather than outputs/backups when that layout is present.
    project_root = primary.parent.parent.parent
    backup_dir = project_root / "backups" / f"full_franchise_reset_v1_{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    checkpoint_files = _snapshot_checkpoint_family(backup_dir, primary)
    _write_reset_manifest(
        backup_dir,
        source_preview=source_preview,
        checkpoint_files=checkpoint_files,
    )

    try:
        fresh = build_starting_franchise(runtime)
        checkpoint = checkpoint_api.save_franchise_checkpoint(
            fresh.simulation_state,
            fresh.trade_state,
            preferences={},
            reason="new-franchise-reset-v1",
            copy_payload=True,
            force_replace=True,
        )

        reloaded = checkpoint_api.load_franchise_checkpoint()
        if reloaded is None:
            raise FranchiseFullResetError("Fresh franchise checkpoint could not be reloaded.")

        validate_simulation_league_state(reloaded.simulation_state)
        if str(reloaded.simulation_state.settings.season_label) != RESET_STARTING_SEASON:
            raise FranchiseFullResetError("Reloaded reset checkpoint has the wrong season.")
        if len(reloaded.simulation_state.schedule) != LEAGUE_GAME_COUNT:
            raise FranchiseFullResetError("Reloaded reset checkpoint lost the starting schedule.")
        if reloaded.simulation_state.completed_games:
            raise FranchiseFullResetError("Reloaded reset checkpoint contains completed games.")
        if reloaded.simulation_state.season_history:
            raise FranchiseFullResetError("Reloaded reset checkpoint contains archived seasons.")
        if getattr(reloaded.trade_state, "transaction_history", []):
            raise FranchiseFullResetError("Reloaded reset Trade Machine contains transactions.")

        return FranchiseResetCommitResult(
            version=FULL_RESET_VERSION,
            backup_directory=str(backup_dir),
            source_season=str(source_preview["season"]),
            target_season=str(reloaded.simulation_state.settings.season_label),
            source_players=int(source_preview["players"]),
            target_players=len(reloaded.simulation_state.players),
            target_schedule_games=len(reloaded.simulation_state.schedule),
            saved_at_utc=str(checkpoint.saved_at_utc),
            checkpoint_reason=str(checkpoint.reason),
        )
    except Exception as exc:
        try:
            _restore_checkpoint_family(backup_dir, primary)
        except Exception as restore_exc:
            raise FranchiseFullResetError(
                f"Reset failed ({exc}) and automatic checkpoint restoration also failed ({restore_exc}). "
                f"Manual recovery copy: {backup_dir}"
            ) from exc
        raise FranchiseFullResetError(
            f"Reset failed and the pre-reset checkpoint was restored automatically: {exc}"
        ) from exc
