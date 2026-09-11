from __future__ import annotations

import copy
import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from franchise_draft_engine_v1 import draft_state
from franchise_offseason_market_season_v1 import (
    COMPLETED_SEASON_CLOSEOUT_ATTR,
    completed_season_closeout_applied,
    next_season_label,
)
from simulation_league_state_v1 import validate_simulation_league_state
from simulation_season_boundary_trade_reconciliation_v1 import (
    SeasonBoundaryTradeReconciliationResult,
    reconcile_trade_state_after_season_boundary,
)
from simulation_season_transition_v1 import (
    advance_rostered_contract_clock_v1,
    refresh_team_rotations,
)
from franchise_legacy_contract_continuity_v1 import (
    LEGACY_CONTRACT_CONTINUITY_VERSION,
    prepare_legacy_contracts_for_closeout,
)

COMPLETED_SEASON_CONTRACT_CLOSEOUT_VERSION = (
    "franchise-completed-season-contract-closeout-v1-2026-08-18"
)


class CompletedSeasonContractCloseoutError(RuntimeError):
    pass


@dataclass(frozen=True)
class CompletedSeasonContractCloseoutResult:
    version: str
    status: str
    source_season: str
    target_market_season: str
    contracts_decremented: int
    contracts_expired: int
    trade_owners_released: int
    trade_revision_before: int
    trade_revision_after: int
    transaction_count_before: int
    transaction_count_after: int
    minimum_roster_after_closeout: int
    affected_teams: tuple[str, ...]
    simulation_state: Any
    trade_state: Any
    checkpoint_path: str = ""
    recovery_primary_path: str = ""
    recovery_backup_path: str = ""
    legacy_contract_continuity_version: str = ""
    legacy_contracts_seeded: int = 0
    legacy_contracts_aligned: int = 0
    legacy_rostered_contract_statuses_normalized: int = 0
    legacy_contracts_unresolved: int = 0


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _phase(state: Any) -> str:
    raw = getattr(state, "phase", "")
    return _clean(getattr(raw, "value", raw)).lower()


def _postseason_complete(state: Any) -> bool:
    postseason = getattr(state, "postseason_state", None)
    if postseason is None:
        return False
    stage = getattr(postseason, "stage", "")
    return _clean(getattr(stage, "value", stage)).lower() == "complete"


def _roster_counts(state: Any) -> dict[str, int]:
    return {
        _clean(team).upper(): len(
            tuple(getattr(team_state, "roster_player_ids", ()) or ())
        )
        for team, team_state in (getattr(state, "teams", {}) or {}).items()
    }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def completed_season_contract_closeout_required(state: Any) -> bool:
    source = _clean(getattr(getattr(state, "settings", None), "season_label", ""))
    return bool(
        source
        and _phase(state) == "offseason"
        and _postseason_complete(state)
        and not completed_season_closeout_applied(state, source)
    )


def _result_from_existing(state: Any, trade_state: Any) -> CompletedSeasonContractCloseoutResult:
    marker = getattr(state, COMPLETED_SEASON_CLOSEOUT_ATTR, {}) or {}
    revision = int(getattr(trade_state, "state_revision", 0) or 0)
    tx_count = len(getattr(trade_state, "transaction_history", ()) or ())
    counts = _roster_counts(state)
    return CompletedSeasonContractCloseoutResult(
        version=COMPLETED_SEASON_CONTRACT_CLOSEOUT_VERSION,
        status="already_applied",
        source_season=_clean(marker.get("source_season")),
        target_market_season=_clean(marker.get("target_market_season")),
        contracts_decremented=int(marker.get("contracts_decremented", 0) or 0),
        contracts_expired=int(marker.get("contracts_expired", 0) or 0),
        trade_owners_released=int(marker.get("trade_owners_released", 0) or 0),
        trade_revision_before=int(marker.get("trade_revision_before", revision) or revision),
        trade_revision_after=revision,
        transaction_count_before=int(marker.get("transaction_count_before", tx_count) or tx_count),
        transaction_count_after=tx_count,
        minimum_roster_after_closeout=min(counts.values()) if counts else 0,
        affected_teams=tuple(sorted(marker.get("affected_teams", ()) or ())),
        simulation_state=copy.deepcopy(state),
        trade_state=copy.deepcopy(trade_state),
        legacy_contract_continuity_version=_clean(
            marker.get("legacy_contract_continuity_version")
        ),
        legacy_contracts_seeded=int(
            marker.get("legacy_contracts_seeded", 0) or 0
        ),
        legacy_contracts_aligned=int(
            marker.get("legacy_contracts_aligned", 0) or 0
        ),
        legacy_rostered_contract_statuses_normalized=int(
            marker.get("legacy_rostered_contract_statuses_normalized", 0) or 0
        ),
        legacy_contracts_unresolved=int(
            marker.get("legacy_contracts_unresolved", 0) or 0
        ),
    )


def build_completed_season_contract_closeout_candidate(
    state: Any,
    trade_state: Any,
) -> CompletedSeasonContractCloseoutResult:
    validate_simulation_league_state(state)
    source_season = _clean(
        getattr(getattr(state, "settings", None), "season_label", "")
    )
    if not source_season:
        raise CompletedSeasonContractCloseoutError("Franchise season label is unavailable.")
    if _phase(state) != "offseason" or not _postseason_complete(state):
        raise CompletedSeasonContractCloseoutError(
            "Completed-season contract closeout requires OFFSEASON with a completed postseason."
        )

    if completed_season_closeout_applied(state, source_season):
        return _result_from_existing(state, trade_state)

    # A historical prior Draft is filtered out by franchise_draft_engine_v1.draft_state().
    # Any remaining Draft is active for this offseason and must not precede contract expiry.
    if draft_state(state) is not None:
        raise CompletedSeasonContractCloseoutError(
            "Contract closeout must occur before the active offseason Draft begins."
        )

    candidate = copy.deepcopy(state)
    trade_candidate = copy.deepcopy(trade_state)

    contract_continuity = prepare_legacy_contracts_for_closeout(
        candidate,
        season_label=source_season,
    )
    clock = advance_rostered_contract_clock_v1(candidate)
    refresh_team_rotations(candidate)
    validate_simulation_league_state(candidate)

    reconciled_state, reconciled_trade, reconciliation = (
        reconcile_trade_state_after_season_boundary(candidate, trade_candidate)
    )

    target_market_season = next_season_label(source_season)
    marker = {
        "version": COMPLETED_SEASON_CONTRACT_CLOSEOUT_VERSION,
        "status": "applied",
        "source_season": source_season,
        "target_market_season": target_market_season,
        "contract_clock_version": _clean(clock.get("version")),
        "contracts_decremented": int(clock.get("decremented_count", 0) or 0),
        "contracts_expired": int(clock.get("expired_count", 0) or 0),
        "trade_reconciliation_version": reconciliation.version,
        "trade_owners_released": len(reconciliation.released_player_ids),
        "trade_revision_before": reconciliation.source_revision,
        "trade_revision_after": reconciliation.target_revision,
        "transaction_count_before": reconciliation.source_transaction_count,
        "transaction_count_after": reconciliation.target_transaction_count,
        "affected_teams": tuple(reconciliation.affected_teams),
        "legacy_contract_continuity_version": LEGACY_CONTRACT_CONTINUITY_VERSION,
        "legacy_contracts_seeded": contract_continuity.seeded_count,
        "legacy_contracts_aligned": contract_continuity.aligned_count,
        "legacy_rostered_contract_statuses_normalized": len(
            contract_continuity.normalized_rostered_contract_status_player_ids
        ),
        "legacy_contracts_unresolved": contract_continuity.unresolved_count,
        "legacy_contract_unresolved_player_ids": contract_continuity.unresolved_player_ids,
    }
    setattr(reconciled_state, COMPLETED_SEASON_CLOSEOUT_ATTR, marker)
    validate_simulation_league_state(reconciled_state)

    counts = _roster_counts(reconciled_state)

    return CompletedSeasonContractCloseoutResult(
        version=COMPLETED_SEASON_CONTRACT_CLOSEOUT_VERSION,
        status="applied",
        source_season=source_season,
        target_market_season=target_market_season,
        contracts_decremented=int(clock.get("decremented_count", 0) or 0),
        contracts_expired=int(clock.get("expired_count", 0) or 0),
        trade_owners_released=len(reconciliation.released_player_ids),
        trade_revision_before=reconciliation.source_revision,
        trade_revision_after=reconciliation.target_revision,
        transaction_count_before=reconciliation.source_transaction_count,
        transaction_count_after=reconciliation.target_transaction_count,
        minimum_roster_after_closeout=min(counts.values()) if counts else 0,
        affected_teams=tuple(reconciliation.affected_teams),
        simulation_state=reconciled_state,
        trade_state=reconciled_trade,
        legacy_contract_continuity_version=LEGACY_CONTRACT_CONTINUITY_VERSION,
        legacy_contracts_seeded=contract_continuity.seeded_count,
        legacy_contracts_aligned=contract_continuity.aligned_count,
        legacy_rostered_contract_statuses_normalized=len(
            contract_continuity.normalized_rostered_contract_status_player_ids
        ),
        legacy_contracts_unresolved=contract_continuity.unresolved_count,
    )


def commit_completed_season_contract_closeout_durably(
    state: Any,
    trade_state: Any,
    *,
    preferences: dict[str, Any] | None = None,
    checkpoint_path: str | Path | None = None,
    recovery_directory: str | Path | None = None,
) -> CompletedSeasonContractCloseoutResult:
    import simulation_franchise_checkpoint_v1 as checkpoint_module

    candidate = build_completed_season_contract_closeout_candidate(state, trade_state)
    if candidate.status == "already_applied":
        return candidate

    path = Path(
        checkpoint_module.DEFAULT_CHECKPOINT_PATH
        if checkpoint_path is None
        else checkpoint_path
    )
    backup_path = Path(checkpoint_module.checkpoint_backup_path(path))
    if not path.exists():
        raise CompletedSeasonContractCloseoutError(
            f"Durable Franchise checkpoint does not exist: {path}"
        )

    primary_hash = _sha256(path)
    backup_existed = backup_path.exists()
    backup_hash = _sha256(backup_path) if backup_existed else None

    recovery_root = Path(
        recovery_directory
        if recovery_directory is not None
        else path.parent / "completed_season_contract_closeout_recovery"
    )
    recovery_root.mkdir(parents=True, exist_ok=True)
    token = primary_hash[:16]
    recovery_primary = recovery_root / f"pre_closeout_{candidate.source_season}_{token}_{path.name}"
    shutil.copy2(path, recovery_primary)
    if _sha256(recovery_primary) != primary_hash:
        raise CompletedSeasonContractCloseoutError("Primary recovery copy verification failed.")

    recovery_backup: Path | None = None
    if backup_existed:
        recovery_backup = recovery_root / f"pre_closeout_{candidate.source_season}_{token}_{backup_path.name}"
        shutil.copy2(backup_path, recovery_backup)
        if _sha256(recovery_backup) != backup_hash:
            raise CompletedSeasonContractCloseoutError("Backup recovery copy verification failed.")

    try:
        checkpoint_module.save_franchise_checkpoint(
            candidate.simulation_state,
            candidate.trade_state,
            preferences=copy.deepcopy(dict(preferences or {})),
            reason=(
                "franchise-completed-season-contract-closeout-"
                + candidate.source_season
                + "-for-market-"
                + candidate.target_market_season
            ),
            path=path,
            copy_payload=True,
        )
        reloaded = checkpoint_module.load_franchise_checkpoint(
            path=path,
            allow_backup=False,
        )
        if reloaded is None or not completed_season_closeout_applied(
            reloaded.simulation_state,
            candidate.source_season,
        ):
            raise CompletedSeasonContractCloseoutError(
                "Reloaded checkpoint does not preserve the completed-season closeout marker."
            )
        if int(getattr(reloaded.trade_state, "state_revision", -1) or -1) != candidate.trade_revision_after:
            raise CompletedSeasonContractCloseoutError(
                "Reloaded TradeState revision does not match the closeout candidate."
            )
    except Exception:
        shutil.copy2(recovery_primary, path)
        if backup_existed and recovery_backup is not None:
            shutil.copy2(recovery_backup, backup_path)
        elif backup_path.exists():
            backup_path.unlink()
        raise

    return CompletedSeasonContractCloseoutResult(
        **{
            **candidate.__dict__,
            "checkpoint_path": str(path),
            "recovery_primary_path": str(recovery_primary),
            "recovery_backup_path": str(recovery_backup or ""),
        }
    )
