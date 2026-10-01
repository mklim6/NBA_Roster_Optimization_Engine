from __future__ import annotations

import copy
import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from simulation_league_state_v1 import (
    LeaguePhase,
    SimulationLeagueState,
    validate_simulation_league_state,
)
from simulation_season_boundary_trade_reconciliation_v1 import (
    SeasonBoundaryTradeReconciliationResult,
    reconcile_trade_state_after_season_boundary,
)
from simulation_season_boundary_financial_rights_rollover_v1 import (
    rollover_financial_rights_after_season_boundary,
)
from simulation_season_transition_controller_v1 import (
    transition_source_fingerprint,
)
from franchise_free_agency_live_signing_v1 import (
    controlled_teams_from_durable_checkpoint,
    trade_state_fingerprint,
)
from franchise_cpu_two_way_roster_completion_v1 import (
    complete_cpu_two_way_rosters_at_boundary,
)
from franchise_undrafted_rookie_free_agent_v1 import (
    materialize_undrafted_rookie_free_agents_after_transition,
)
from franchise_free_agent_population_ecology_v1 import (
    apply_free_agent_population_ecology_at_boundary,
)

SEASON_BOUNDARY_DURABLE_TRANSITION_VERSION = (
    "season-boundary-atomic-durable-transition-v1.1.0-2026-08-17"
)


class SeasonBoundaryDurableTransitionError(RuntimeError):
    pass


@dataclass(frozen=True)
class SeasonBoundaryDurableTransitionResult:
    version: str
    source_season: str
    target_season: str
    source_fingerprint: str
    target_fingerprint: str
    source_trade_revision: int
    target_trade_revision: int
    transaction_count: int
    released_player_ids: tuple[str, ...]
    affected_teams: tuple[str, ...]
    checkpoint_hash_before: str
    checkpoint_hash_after: str
    automatic_backup_hash_after: str | None
    recovery_primary_path: str
    recovery_backup_path: str | None


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _preferences_fingerprint(preferences: Any) -> str:
    encoded = json.dumps(
        copy.deepcopy(dict(preferences or {})),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def franchise_boundary_fingerprint(
    simulation_state: Any,
    trade_state: Any,
    preferences: Any,
) -> str:
    """
    Stable semantic durable-boundary fingerprint.

    Do not fingerprint raw pickle bytes here. The checkpoint loader deliberately
    rebinds the runtime graph after unpickling, so object serialization identity
    is not a valid reload-equality contract.

    Instead compose the project's existing stable semantic authorities:
    - season-transition SimulationState fingerprint
    - TradeState fingerprint
    - deterministic preferences fingerprint
    """
    payload = {
        "simulation":
            transition_source_fingerprint(simulation_state),
        "trade":
            trade_state_fingerprint(trade_state),
        "preferences":
            _preferences_fingerprint(preferences),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def checkpoint_boundary_fingerprint(checkpoint: Any) -> str:
    return franchise_boundary_fingerprint(
        checkpoint.simulation_state,
        checkpoint.trade_state,
        getattr(checkpoint, "preferences", {}) or {},
    )


def confirmation_token(
    source_season: str,
    target_season: str,
) -> str:
    return (
        "CONFIRM_FRANCHISE_SEASON_BOUNDARY::"
        + _clean(source_season)
        + "::"
        + _clean(target_season)
    )


def _phase(state: Any) -> str:
    raw = getattr(state, "phase", "")
    return _clean(getattr(raw, "value", raw)).lower()


def _validate_transitioned_candidate(
    *,
    source_checkpoint: Any,
    transitioned_state: SimulationLeagueState,
    expected_target_season: str,
) -> None:
    validate_simulation_league_state(transitioned_state)

    source_state = source_checkpoint.simulation_state
    trade_state = source_checkpoint.trade_state

    source_season = _clean(source_state.settings.season_label)
    target_season = _clean(transitioned_state.settings.season_label)

    if target_season != _clean(expected_target_season):
        raise SeasonBoundaryDurableTransitionError(
            "Transitioned season does not match the approved target season."
        )
    if source_season == target_season:
        raise SeasonBoundaryDurableTransitionError(
            "Late-offseason durable transition must advance the season label."
        )
    if _phase(transitioned_state) != "regular_season":
        raise SeasonBoundaryDurableTransitionError(
            "The transitioned candidate must have activated REGULAR_SEASON."
        )
    if len(getattr(transitioned_state, "schedule", {}) or {}) != 1230:
        raise SeasonBoundaryDurableTransitionError(
            "The transitioned candidate must contain the complete 1,230-game schedule."
        )

    try:
        trade_revision = int(getattr(trade_state, "state_revision"))
        transaction_count = len(getattr(trade_state, "transaction_history"))
    except (TypeError, ValueError, AttributeError) as exc:
        raise SeasonBoundaryDurableTransitionError(
            "Source TradeState revision/transaction metadata is invalid."
        ) from exc

    if int(
        getattr(
            transitioned_state,
            "source_league_state_revision",
            -1,
        )
        or -1
    ) != trade_revision:
        raise SeasonBoundaryDurableTransitionError(
            "Transitioned SimulationState is not aligned to the source TradeState revision."
        )

    if int(
        getattr(
            transitioned_state,
            "source_transaction_count",
            -1,
        )
        or 0
    ) != transaction_count:
        raise SeasonBoundaryDurableTransitionError(
            "Transitioned SimulationState is not aligned to the source TradeState transaction count."
        )


def build_atomic_season_boundary_candidate(
    checkpoint: Any,
    transitioned_state: SimulationLeagueState,
    *,
    expected_target_season: str,
) -> tuple[
    SimulationLeagueState,
    Any,
    SeasonBoundaryTradeReconciliationResult,
    str,
]:
    _validate_transitioned_candidate(
        source_checkpoint=checkpoint,
        transitioned_state=transitioned_state,
        expected_target_season=expected_target_season,
    )

    # FRANCHISE_V2_FREE_AGENT_POPULATION_ECOLOGY_V1
    # Career retirement already ran inside the transition adapter.  Before the
    # new undrafted class is materialized, bound only the genuine long-term
    # free-agent market so fringe unsigned players do not accumulate forever.
    # ``transitioned_state`` is already a disposable candidate owned by this
    # atomic boundary, so no extra whole-league deepcopy is needed here.
    ecology_state, _population_ecology = (
        apply_free_agent_population_ecology_at_boundary(
            transitioned_state,
            copy_payload=False,
        )
    )

    # The Draft engine generates a deeper 80-player class than the 60 selected
    # prospects. Materialize the undrafted remainder as real rookie free agents
    # only after the season transition and population ecology, so rookies do not
    # receive a pre-rookie development cycle and are protected from same-boundary
    # attrition. The two-way market can then evaluate this fresh supply normally.
    undrafted_state, _undrafted_completion = (
        materialize_undrafted_rookie_free_agents_after_transition(
            ecology_state,
        )
    )

    # Standard Free Agency and post-Draft trimming deliberately operate only on
    # standard contracts. Fill separate CPU two-way slots once that work is
    # complete, immediately before TradeState reconciliation so the financial
    # and ownership ledgers observe the final regular-season roster structure.
    two_way_state, _two_way_completion = complete_cpu_two_way_rosters_at_boundary(
        undrafted_state,
        controlled_teams=controlled_teams_from_durable_checkpoint(checkpoint),
    )

    reconciled_state, reconciled_trade, reconciliation = (
        reconcile_trade_state_after_season_boundary(
            two_way_state,
            checkpoint.trade_state,
        )
    )

    rolled_state, financial_rights_rollover = (
        rollover_financial_rights_after_season_boundary(
            reconciled_state,
            reconciled_trade,
            source_season=_clean(
                checkpoint.simulation_state.settings.season_label
            ),
            target_season=_clean(expected_target_season),
        )
    )

    validate_simulation_league_state(rolled_state)

    target_fingerprint = franchise_boundary_fingerprint(
        rolled_state,
        reconciled_trade,
        getattr(checkpoint, "preferences", {}) or {},
    )
    return (
        rolled_state,
        reconciled_trade,
        reconciliation,
        target_fingerprint,
    )


def _reload_written_checkpoint(
    checkpoint_module: Any,
    path: Path,
) -> Any:
    return checkpoint_module.load_franchise_checkpoint(
        path=path,
        allow_backup=False,
    )


def _verify_reloaded_candidate(
    reloaded: Any,
    expected_fingerprint: str,
) -> None:
    if reloaded is None:
        raise SeasonBoundaryDurableTransitionError(
            "Durable season-boundary checkpoint reload returned no state."
        )
    observed = checkpoint_boundary_fingerprint(reloaded)
    if observed != expected_fingerprint:
        raise SeasonBoundaryDurableTransitionError(
            "Reloaded season-boundary checkpoint does not exactly match the approved candidate."
        )


def commit_atomic_season_boundary_live(
    transitioned_state: SimulationLeagueState,
    *,
    expected_source_fingerprint: str,
    expected_target_season: str,
    confirmation: str,
    checkpoint_path: str | Path | None = None,
    recovery_directory: str | Path | None = None,
) -> SeasonBoundaryDurableTransitionResult:
    import simulation_franchise_checkpoint_v1 as checkpoint_module

    path = Path(
        checkpoint_module.DEFAULT_CHECKPOINT_PATH
        if checkpoint_path is None
        else checkpoint_path
    )
    backup_path = Path(
        checkpoint_module.checkpoint_backup_path(path)
    )

    checkpoint = checkpoint_module.load_franchise_checkpoint(
        path=path,
        allow_backup=False,
    )
    if checkpoint is None:
        raise SeasonBoundaryDurableTransitionError(
            "The durable Franchise checkpoint could not be loaded."
        )

    source_fingerprint = checkpoint_boundary_fingerprint(checkpoint)
    if source_fingerprint != _clean(expected_source_fingerprint):
        raise SeasonBoundaryDurableTransitionError(
            "The Franchise checkpoint changed after transition preparation."
        )

    source_season = _clean(
        checkpoint.simulation_state.settings.season_label
    )
    target_season = _clean(expected_target_season)
    expected_confirmation = confirmation_token(
        source_season,
        target_season,
    )
    if _clean(confirmation) != expected_confirmation:
        raise SeasonBoundaryDurableTransitionError(
            "The explicit season-boundary confirmation token does not match the approved transition."
        )

    (
        simulation_candidate,
        trade_candidate,
        reconciliation,
        target_fingerprint,
    ) = build_atomic_season_boundary_candidate(
        checkpoint,
        transitioned_state,
        expected_target_season=target_season,
    )

    checkpoint_hash_before = _sha256(path)
    backup_existed_before = backup_path.exists()
    backup_hash_before = (
        _sha256(backup_path)
        if backup_existed_before
        else None
    )

    root = Path(
        recovery_directory
        if recovery_directory is not None
        else path.parent / "season_boundary_transition_recovery"
    )
    stamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )
    root.mkdir(parents=True, exist_ok=True)

    recovery_primary = (
        root
        / f"pre_season_boundary_{stamp}_{path.name}"
    )
    shutil.copy2(path, recovery_primary)
    if _sha256(recovery_primary) != checkpoint_hash_before:
        raise SeasonBoundaryDurableTransitionError(
            "Could not create an exact pre-transition primary recovery copy."
        )

    recovery_backup: Path | None = None
    if backup_existed_before:
        recovery_backup = (
            root
            / f"pre_season_boundary_{stamp}_{backup_path.name}"
        )
        shutil.copy2(backup_path, recovery_backup)
        if _sha256(recovery_backup) != backup_hash_before:
            raise SeasonBoundaryDurableTransitionError(
                "Could not create an exact pre-transition automatic-backup recovery copy."
            )

    try:
        checkpoint_module.save_franchise_checkpoint(
            simulation_candidate,
            trade_candidate,
            preferences=copy.deepcopy(
                dict(getattr(checkpoint, "preferences", {}) or {})
            ),
            reason=(
                "franchise-season-boundary-atomic-transition-"
                + source_season
                + "-to-"
                + target_season
            ),
            path=path,
            copy_payload=True,
        )

        reloaded = _reload_written_checkpoint(
            checkpoint_module,
            path,
        )
        _verify_reloaded_candidate(
            reloaded,
            target_fingerprint,
        )

        if _clean(
            reloaded.simulation_state.settings.season_label
        ) != target_season:
            raise SeasonBoundaryDurableTransitionError(
                "Reloaded durable transition has the wrong season."
            )
        if _phase(reloaded.simulation_state) != "regular_season":
            raise SeasonBoundaryDurableTransitionError(
                "Reloaded durable transition did not preserve REGULAR_SEASON."
            )
        if len(
            getattr(reloaded.simulation_state, "schedule", {}) or {}
        ) != 1230:
            raise SeasonBoundaryDurableTransitionError(
                "Reloaded durable transition did not preserve the 1,230-game schedule."
            )

    except Exception as exc:
        shutil.copy2(recovery_primary, path)

        if backup_existed_before:
            assert recovery_backup is not None
            shutil.copy2(recovery_backup, backup_path)
        elif backup_path.exists():
            backup_path.unlink()

        restored = checkpoint_module.load_franchise_checkpoint(
            path=path,
            allow_backup=False,
        )
        if restored is None:
            raise SeasonBoundaryDurableTransitionError(
                "Season-boundary commit failed and the restored checkpoint could not be loaded."
            ) from exc

        if checkpoint_boundary_fingerprint(restored) != source_fingerprint:
            raise SeasonBoundaryDurableTransitionError(
                "Season-boundary commit failed and exact semantic recovery could not be verified."
            ) from exc
        if _sha256(path) != checkpoint_hash_before:
            raise SeasonBoundaryDurableTransitionError(
                "Season-boundary recovery did not restore the exact primary checkpoint bytes."
            ) from exc

        if backup_existed_before:
            if not backup_path.exists() or _sha256(backup_path) != backup_hash_before:
                raise SeasonBoundaryDurableTransitionError(
                    "Season-boundary recovery did not restore the exact automatic-backup bytes."
                ) from exc
        elif backup_path.exists():
            raise SeasonBoundaryDurableTransitionError(
                "Season-boundary recovery created an automatic backup that did not exist before."
            ) from exc

        raise SeasonBoundaryDurableTransitionError(
            "Season-boundary durable transition failed; exact pre-action "
            "checkpoint state was restored. Root cause: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    checkpoint_hash_after = _sha256(path)
    automatic_backup_hash_after = (
        _sha256(backup_path)
        if backup_path.exists()
        else None
    )

    return SeasonBoundaryDurableTransitionResult(
        version=SEASON_BOUNDARY_DURABLE_TRANSITION_VERSION,
        source_season=source_season,
        target_season=target_season,
        source_fingerprint=source_fingerprint,
        target_fingerprint=target_fingerprint,
        source_trade_revision=int(
            reconciliation.source_revision
        ),
        target_trade_revision=int(
            reconciliation.target_revision
        ),
        transaction_count=int(
            reconciliation.target_transaction_count
        ),
        released_player_ids=tuple(
            reconciliation.released_player_ids
        ),
        affected_teams=tuple(
            reconciliation.affected_teams
        ),
        checkpoint_hash_before=checkpoint_hash_before,
        checkpoint_hash_after=checkpoint_hash_after,
        automatic_backup_hash_after=automatic_backup_hash_after,
        recovery_primary_path=str(recovery_primary),
        recovery_backup_path=(
            str(recovery_backup)
            if recovery_backup is not None
            else None
        ),
    )
