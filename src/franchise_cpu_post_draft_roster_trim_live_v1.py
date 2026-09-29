from __future__ import annotations

import copy
import hashlib
import json
import shutil
from dataclasses import dataclass, replace, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

LIVE_TRIM_VERSION = "franchise-cpu-post-draft-roster-trim-atomic-live-v2-2026-09-25"
LIVE_TRIM_HISTORY_ATTR = "cpu_post_draft_roster_trim_batch_history_v1"


class CPUPostDraftRosterTrimLiveError(RuntimeError):
    pass


@dataclass(frozen=True)
class CPUPostDraftRosterTrimBatchCandidate:
    version: str
    status: str
    source_fingerprint: str
    target_fingerprint: str
    simulation_state: Any | None
    trade_state: Any | None
    preferences: dict[str, Any]
    controlled_teams: tuple[str, ...]
    cpu_overflow_teams_before: tuple[str, ...]
    user_controlled_overflow_teams: tuple[str, ...]
    manual_review_teams: tuple[str, ...]
    released_player_ids: tuple[str, ...]
    transaction_ids: tuple[str, ...]
    team_release_counts: dict[str, int]
    trade_revision_before: int
    trade_revision_after: int
    transaction_count_before: int
    transaction_count_after: int
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class CPUPostDraftRosterTrimDurableResult:
    version: str
    status: str
    checkpoint_path: str
    source_fingerprint: str
    target_fingerprint: str
    source_checkpoint_sha256: str
    committed_checkpoint_sha256: str
    released_player_ids: tuple[str, ...]
    transaction_ids: tuple[str, ...]
    team_release_counts: dict[str, int]
    trade_revision_before: int
    trade_revision_after: int
    transaction_count_before: int
    transaction_count_after: int
    recovery_primary_path: str | None
    recovery_backup_path: str | None
    rollback_performed: bool
    checkpoint_reason: str


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _phase(state: Any) -> str:
    raw = getattr(state, "phase", "")
    phase = _clean(getattr(raw, "value", raw)).lower()
    if phase:
        return phase
    return _clean(getattr(getattr(state, "settings", None), "phase", "")).lower()


def _checkpoint_like(source: Any, simulation_state: Any, trade_state: Any) -> Any:
    preferences = copy.deepcopy(dict(getattr(source, "preferences", {}) or {}))
    if is_dataclass(source):
        names = set(getattr(source, "__dataclass_fields__", {}))
        changes: dict[str, Any] = {}
        if "simulation_state" in names:
            changes["simulation_state"] = simulation_state
        if "trade_state" in names:
            changes["trade_state"] = trade_state
        if "preferences" in names:
            changes["preferences"] = preferences
        if changes:
            try:
                return replace(source, **changes)
            except Exception:
                pass
    return SimpleNamespace(
        simulation_state=simulation_state,
        trade_state=trade_state,
        preferences=preferences,
    )


def _roster_ids(state: Any, team: str) -> tuple[str, ...]:
    team_state = (getattr(state, "teams", {}) or {}).get(_team(team))
    if team_state is None:
        return ()
    return tuple(
        _clean(pid)
        for pid in getattr(team_state, "roster_player_ids", ()) or ()
        if _clean(pid)
    )


def _batch_history(obj: Any) -> list[dict[str, Any]]:
    raw = getattr(obj, LIVE_TRIM_HISTORY_ATTR, None)
    return copy.deepcopy(list(raw or [])) if isinstance(raw, (list, tuple)) else []


def _append_batch_history(
    simulation_state: Any,
    trade_state: Any,
    *,
    released_player_ids: tuple[str, ...],
    transaction_ids: tuple[str, ...],
    team_release_counts: dict[str, int],
) -> None:
    payload = {
        "version": LIVE_TRIM_VERSION,
        "event": "cpu_post_draft_roster_trim_batch",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "released_player_ids": list(released_player_ids),
        "transaction_ids": list(transaction_ids),
        "team_release_counts": dict(sorted(team_release_counts.items())),
        "release_count": len(released_player_ids),
        "trade_transaction_history_written": False,
    }
    for obj in (simulation_state, trade_state):
        history = _batch_history(obj)
        history.append(copy.deepcopy(payload))
        try:
            setattr(obj, LIVE_TRIM_HISTORY_ATTR, history)
        except Exception:
            object.__setattr__(obj, LIVE_TRIM_HISTORY_ATTR, history)


def confirmation_token(state: Any) -> str:
    import franchise_draft_engine_v1 as draft

    season = _clean(getattr(getattr(state, "settings", None), "season_label", ""))
    draft_year = int(draft.draft_year_for_state(state))
    return f"CONFIRM_CPU_POST_DRAFT_ROSTER_TRIM::{season}::{draft_year}"


def build_atomic_cpu_post_draft_trim_candidate(
    checkpoint: Any,
) -> CPUPostDraftRosterTrimBatchCandidate:
    import franchise_cpu_post_draft_roster_trim_orchestrator_v1 as orchestrator
    import franchise_cpu_post_draft_roster_trim_release_v1 as release
    import franchise_draft_engine_v1 as draft
    import franchise_season_boundary_durable_transition_v1 as durable
    from simulation_league_state_v1 import validate_simulation_league_state

    source_sim = getattr(checkpoint, "simulation_state", None)
    source_trade = getattr(checkpoint, "trade_state", None)
    preferences = copy.deepcopy(dict(getattr(checkpoint, "preferences", {}) or {}))
    if source_sim is None or source_trade is None:
        raise CPUPostDraftRosterTrimLiveError(
            "Durable checkpoint must expose SimulationState and TradeState."
        )

    source_fingerprint = durable.checkpoint_boundary_fingerprint(checkpoint)
    source_phase = _phase(source_sim)
    blockers: list[str] = []
    if "offseason" not in source_phase:
        blockers.append("CPU post-Draft roster trimming is offseason-only.")
    if not draft.draft_is_complete(source_sim):
        blockers.append("CPU post-Draft roster trimming requires a completed Draft.")

    initial_preview = orchestrator.build_cpu_post_draft_trim_league_preview(checkpoint)
    cpu_overflow = tuple(
        item.team
        for item in initial_preview.team_previews
        if item.cpu_managed and item.required_cut_count > 0
    )
    user_overflow = tuple(
        item.team
        for item in initial_preview.team_previews
        if (not item.cpu_managed) and item.required_cut_count > 0
    )
    manual = tuple(
        item.team
        for item in initial_preview.team_previews
        if item.cpu_managed
        and item.required_cut_count > 0
        and item.status != "cpu_trim_plan_executable_on_clone"
    )
    if user_overflow:
        blockers.append(
            "User-controlled teams require a post-Draft roster decision: "
            + ", ".join(user_overflow)
            + ". Resolve those rosters manually before opening the next season."
        )
    if manual:
        details = []
        by_team = {item.team: item for item in initial_preview.team_previews}
        for team in manual:
            item = by_team[team]
            details.append(f"{team}={item.status}")
        blockers.append(
            "At least one CPU overflow cannot be released through a certified exact "
            "financial route: " + ", ".join(details)
        )

    revision_before = int(getattr(source_trade, "state_revision", 0) or 0)
    tx_count_before = len(getattr(source_trade, "transaction_history", ()) or ())

    if blockers:
        return CPUPostDraftRosterTrimBatchCandidate(
            version=LIVE_TRIM_VERSION,
            status="blocked",
            source_fingerprint=source_fingerprint,
            target_fingerprint=source_fingerprint,
            simulation_state=None,
            trade_state=None,
            preferences=preferences,
            controlled_teams=tuple(initial_preview.controlled_teams),
            cpu_overflow_teams_before=cpu_overflow,
            user_controlled_overflow_teams=user_overflow,
            manual_review_teams=manual,
            released_player_ids=(),
            transaction_ids=(),
            team_release_counts={},
            trade_revision_before=revision_before,
            trade_revision_after=revision_before,
            transaction_count_before=tx_count_before,
            transaction_count_after=tx_count_before,
            blockers=tuple(blockers),
        )

    if not cpu_overflow:
        sim = copy.deepcopy(source_sim)
        trade = copy.deepcopy(source_trade)
        target_checkpoint = _checkpoint_like(checkpoint, sim, trade)
        target_fp = durable.checkpoint_boundary_fingerprint(target_checkpoint)
        return CPUPostDraftRosterTrimBatchCandidate(
            version=LIVE_TRIM_VERSION,
            status="no_trim_required",
            source_fingerprint=source_fingerprint,
            target_fingerprint=target_fp,
            simulation_state=sim,
            trade_state=trade,
            preferences=preferences,
            controlled_teams=tuple(initial_preview.controlled_teams),
            cpu_overflow_teams_before=(),
            user_controlled_overflow_teams=(),
            manual_review_teams=(),
            released_player_ids=(),
            transaction_ids=(),
            team_release_counts={},
            trade_revision_before=revision_before,
            trade_revision_after=revision_before,
            transaction_count_before=tx_count_before,
            transaction_count_after=tx_count_before,
            blockers=(),
        )

    working = _checkpoint_like(
        checkpoint,
        copy.deepcopy(source_sim),
        copy.deepcopy(source_trade),
    )
    released_ids: list[str] = []
    transaction_ids: list[str] = []
    team_release_counts: dict[str, int] = {}
    expected_release_count = sum(
        item.required_cut_count
        for item in initial_preview.team_previews
        if item.cpu_managed
    )

    # The initial preview already certifies the exact number of releases for
    # every overflowing CPU roster.  Rebuilding the complete 30-team front
    # office plan after every cut is redundant and caused deep-offseason trim
    # time to grow into several minutes.  Execute that deterministic plan on
    # the disposable working clone, while rebuilding each selected player's
    # narrow release preview against the current state immediately before the
    # mutation.  A final league-wide preview below remains mandatory.
    release_plan = [
        (item, selected)
        for item in sorted(initial_preview.team_previews, key=lambda row: row.team)
        if item.cpu_managed and item.required_cut_count > 0
        for selected in item.selected_releases
    ]
    if len(release_plan) != expected_release_count:
        raise CPUPostDraftRosterTrimLiveError(
            "Initial CPU trim plan does not contain the expected release count."
        )

    for item, selected in release_plan:
        release_preview = release.build_cpu_post_draft_release_preview(
            working,
            team=item.team,
            player_id=selected.player_id,
            rationale=selected.score_rationale,
            require_non_rotation=False,
        )
        if (
            release_preview.status != "pass"
            or not release_preview.can_commit_to_clone
            or release_preview.financial_treatment
            not in orchestrator.CERTIFIED_AUTOMATIC_FINANCIAL_ROUTES
        ):
            raise CPUPostDraftRosterTrimLiveError(
                "Final release gate rejected the orchestrator-selected CPU trim target."
            )
        player = working.simulation_state.players[selected.player_id]
        if release._current_or_unresolved_generated_rookie(
            working.simulation_state,
            player,
        ):
            raise CPUPostDraftRosterTrimLiveError(
                "Current/unresolved generated rookie protection was violated by the live batch builder."
            )
        candidate = release.build_cpu_post_draft_release_candidate(
            working,
            release_preview,
            copy_payload=False,
            # The atomic batch verifies its final combined boundary fingerprint
            # before persistence. Per-release candidate fingerprints are not
            # consumed here, so avoid two full mature-state scans per cut.
            _defer_candidate_fingerprints=True,
        )
        working = _checkpoint_like(
            working,
            candidate.simulation_candidate,
            candidate.trade_candidate,
        )
        released_ids.append(selected.player_id)
        transaction_ids.append(candidate.transaction_id)
        team_release_counts[item.team] = team_release_counts.get(item.team, 0) + 1

    if len(released_ids) != expected_release_count:
        raise CPUPostDraftRosterTrimLiveError(
            "Atomic batch release count does not match the initial league overflow count."
        )

    final_preview = orchestrator.build_cpu_post_draft_trim_league_preview(working)
    remaining_cpu_overflow = [
        item.team
        for item in final_preview.team_previews
        if item.cpu_managed and item.required_cut_count > 0
    ]
    if remaining_cpu_overflow:
        raise CPUPostDraftRosterTrimLiveError(
            "Atomic batch candidate finished with CPU teams still above a "
            "post-Draft roster ceiling: "
            + ", ".join(remaining_cpu_overflow)
        )

    validate_simulation_league_state(working.simulation_state)
    revision_after = int(getattr(working.trade_state, "state_revision", 0) or 0)
    tx_count_after = len(getattr(working.trade_state, "transaction_history", ()) or ())
    if revision_after != revision_before + len(released_ids):
        raise CPUPostDraftRosterTrimLiveError(
            "TradeState revision did not increment exactly once per approved CPU release."
        )
    if tx_count_after != tx_count_before:
        raise CPUPostDraftRosterTrimLiveError(
            "CPU waiver batch created fake Trade Machine transaction history."
        )

    _append_batch_history(
        working.simulation_state,
        working.trade_state,
        released_player_ids=tuple(released_ids),
        transaction_ids=tuple(transaction_ids),
        team_release_counts=team_release_counts,
    )
    target_checkpoint = _checkpoint_like(
        working,
        working.simulation_state,
        working.trade_state,
    )
    target_fp = durable.checkpoint_boundary_fingerprint(target_checkpoint)

    return CPUPostDraftRosterTrimBatchCandidate(
        version=LIVE_TRIM_VERSION,
        status="ready",
        source_fingerprint=source_fingerprint,
        target_fingerprint=target_fp,
        simulation_state=working.simulation_state,
        trade_state=working.trade_state,
        preferences=preferences,
        controlled_teams=tuple(initial_preview.controlled_teams),
        cpu_overflow_teams_before=cpu_overflow,
        user_controlled_overflow_teams=(),
        manual_review_teams=(),
        released_player_ids=tuple(released_ids),
        transaction_ids=tuple(transaction_ids),
        team_release_counts=dict(sorted(team_release_counts.items())),
        trade_revision_before=revision_before,
        trade_revision_after=revision_after,
        transaction_count_before=tx_count_before,
        transaction_count_after=tx_count_after,
        blockers=(),
    )


def commit_atomic_cpu_post_draft_trim_live(
    *,
    expected_source_fingerprint: str,
    confirmation: str,
    checkpoint_path: str | Path | None = None,
    recovery_directory: str | Path | None = None,
    inject_failure_after_verified_save: bool = False,
) -> CPUPostDraftRosterTrimDurableResult:
    import simulation_franchise_checkpoint_v1 as cp
    import franchise_season_boundary_durable_transition_v1 as durable

    path = Path(cp.DEFAULT_CHECKPOINT_PATH if checkpoint_path is None else checkpoint_path).resolve()
    backup_path = Path(cp.checkpoint_backup_path(path))
    if not path.exists():
        raise CPUPostDraftRosterTrimLiveError(f"Checkpoint does not exist: {path}")

    checkpoint = cp.load_franchise_checkpoint(path=path, allow_backup=False)
    if checkpoint is None:
        raise CPUPostDraftRosterTrimLiveError("Durable checkpoint could not be loaded.")
    source_fingerprint = durable.checkpoint_boundary_fingerprint(checkpoint)
    if source_fingerprint != _clean(expected_source_fingerprint):
        raise CPUPostDraftRosterTrimLiveError(
            "The Franchise checkpoint changed after the post-Draft trim was prepared."
        )
    expected_confirmation = confirmation_token(checkpoint.simulation_state)
    if _clean(confirmation) != expected_confirmation:
        raise CPUPostDraftRosterTrimLiveError(
            "The explicit post-Draft roster-trim confirmation token is invalid."
        )

    candidate = build_atomic_cpu_post_draft_trim_candidate(checkpoint)
    if candidate.status == "blocked":
        raise CPUPostDraftRosterTrimLiveError(
            "CPU post-Draft roster trim is blocked: " + "; ".join(candidate.blockers)
        )
    source_hash = _sha256(path)
    backup_existed = backup_path.exists()
    backup_hash = _sha256(backup_path) if backup_existed else None

    if candidate.status == "no_trim_required":
        return CPUPostDraftRosterTrimDurableResult(
            version=LIVE_TRIM_VERSION,
            status="no_trim_required",
            checkpoint_path=str(path),
            source_fingerprint=source_fingerprint,
            target_fingerprint=source_fingerprint,
            source_checkpoint_sha256=source_hash,
            committed_checkpoint_sha256=source_hash,
            released_player_ids=(),
            transaction_ids=(),
            team_release_counts={},
            trade_revision_before=candidate.trade_revision_before,
            trade_revision_after=candidate.trade_revision_after,
            transaction_count_before=candidate.transaction_count_before,
            transaction_count_after=candidate.transaction_count_after,
            recovery_primary_path=None,
            recovery_backup_path=None,
            rollback_performed=False,
            checkpoint_reason="cpu-post-draft-roster-trim-noop",
        )

    root = Path(
        recovery_directory
        if recovery_directory is not None
        else path.parent / "cpu_post_draft_roster_trim_batch_recovery"
    )
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    recovery_primary = root / f"pre_cpu_post_draft_trim_{stamp}_{path.name}"
    shutil.copy2(path, recovery_primary)
    if _sha256(recovery_primary) != source_hash:
        raise CPUPostDraftRosterTrimLiveError(
            "Could not create an exact pre-trim primary recovery copy."
        )
    recovery_backup: Path | None = None
    if backup_existed:
        recovery_backup = root / f"pre_cpu_post_draft_trim_{stamp}_{backup_path.name}"
        shutil.copy2(backup_path, recovery_backup)
        if _sha256(recovery_backup) != backup_hash:
            raise CPUPostDraftRosterTrimLiveError(
                "Could not create an exact pre-trim automatic-backup recovery copy."
            )

    reason = "cpu-post-draft-roster-trim-atomic-batch-" + str(len(candidate.released_player_ids))
    rollback = False
    try:
        cp.save_franchise_checkpoint(
            candidate.simulation_state,
            candidate.trade_state,
            preferences=candidate.preferences,
            reason=reason,
            path=path,
            # The batch candidate already owns a disposable, fully isolated
            # clone and is never mutated after this call. Re-copying years of
            # completed franchise history here adds no isolation; the atomic
            # writer and mandatory semantic reload below remain authoritative.
            copy_payload=False,
        )
        reloaded = cp.load_franchise_checkpoint(path=path, allow_backup=False)
        if reloaded is None:
            raise CPUPostDraftRosterTrimLiveError(
                "Post-Draft trim checkpoint reload returned no state."
            )
        observed_target = durable.checkpoint_boundary_fingerprint(reloaded)
        if observed_target != candidate.target_fingerprint:
            raise CPUPostDraftRosterTrimLiveError(
                "Reloaded post-Draft trim checkpoint does not match the approved batch candidate."
            )
        if len(getattr(reloaded.trade_state, "transaction_history", ()) or ()) != candidate.transaction_count_after:
            raise CPUPostDraftRosterTrimLiveError(
                "Reloaded post-Draft trim unexpectedly changed trade transaction history."
            )
        if inject_failure_after_verified_save:
            raise CPUPostDraftRosterTrimLiveError(
                "Regression-only injected failure after verified atomic batch save."
            )
    except Exception as exc:
        rollback = True
        shutil.copy2(recovery_primary, path)
        if backup_existed:
            assert recovery_backup is not None
            shutil.copy2(recovery_backup, backup_path)
        elif backup_path.exists():
            backup_path.unlink()
        restored = cp.load_franchise_checkpoint(path=path, allow_backup=False)
        if restored is None:
            raise CPUPostDraftRosterTrimLiveError(
                "Post-Draft trim failed and restored checkpoint could not be loaded."
            ) from exc
        if durable.checkpoint_boundary_fingerprint(restored) != source_fingerprint:
            raise CPUPostDraftRosterTrimLiveError(
                "Post-Draft trim rollback did not restore the exact source semantics."
            ) from exc
        if _sha256(path) != source_hash:
            raise CPUPostDraftRosterTrimLiveError(
                "Post-Draft trim rollback did not restore exact primary bytes."
            ) from exc
        if backup_existed:
            if not backup_path.exists() or _sha256(backup_path) != backup_hash:
                raise CPUPostDraftRosterTrimLiveError(
                    "Post-Draft trim rollback did not restore exact backup bytes."
                ) from exc
        elif backup_path.exists():
            raise CPUPostDraftRosterTrimLiveError(
                "Post-Draft trim rollback created a backup that did not exist before."
            ) from exc
        raise

    return CPUPostDraftRosterTrimDurableResult(
        version=LIVE_TRIM_VERSION,
        status="applied",
        checkpoint_path=str(path),
        source_fingerprint=source_fingerprint,
        target_fingerprint=candidate.target_fingerprint,
        source_checkpoint_sha256=source_hash,
        committed_checkpoint_sha256=_sha256(path),
        released_player_ids=candidate.released_player_ids,
        transaction_ids=candidate.transaction_ids,
        team_release_counts=candidate.team_release_counts,
        trade_revision_before=candidate.trade_revision_before,
        trade_revision_after=candidate.trade_revision_after,
        transaction_count_before=candidate.transaction_count_before,
        transaction_count_after=candidate.transaction_count_after,
        recovery_primary_path=str(recovery_primary),
        recovery_backup_path=str(recovery_backup) if recovery_backup is not None else None,
        rollback_performed=rollback,
        checkpoint_reason=reason,
    )


def live_trim_contract_report() -> dict[str, Any]:
    return {
        "version": LIVE_TRIM_VERSION,
        "offseason_roster_ceiling": 21,
        "standard_contract_ceiling": 15,
        "canonical_execution_enabled": True,
        "atomic_league_save": True,
        "controlled_team_auto_release_allowed": False,
        "unknown_guarantee_auto_release_allowed": False,
        "generated_or_synthetic_auto_release_allowed": False,
        "fake_trade_history_allowed": False,
        "atomic_candidate_defers_unused_per_release_fingerprints": True,
        "release_candidate_authority": (
            "franchise_cpu_post_draft_roster_trim_release_v1."
            "build_cpu_post_draft_release_candidate"
        ),
        "selection_authority": (
            "franchise_cpu_post_draft_roster_trim_orchestrator_v1."
            "build_cpu_post_draft_trim_league_preview"
        ),
    }
