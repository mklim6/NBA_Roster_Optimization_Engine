from __future__ import annotations

import copy
import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from freeform_trade_machine_engine_v3 import normalize_player_id, normalize_team
from franchise_embedded_trade_center_v2 import (
    FranchiseTradePreview,
    build_franchise_trade_preview,
)
from franchise_live_asset_ledger_v1 import build_live_asset_ledger
from franchise_draft_right_stepien_bridge_v1 import build_franchise_draft_right_profiles
from simulation_franchise_checkpoint_v1 import (
    DEFAULT_CHECKPOINT_PATH,
    FranchiseCheckpointError,
    load_franchise_checkpoint,
    save_franchise_checkpoint,
)
from simulation_league_state_v1 import (
    RotationState,
    minutes_targets,
    validate_simulation_league_state,
)

from franchise_future_trade_snapshot_refresh_v1 import (
    refresh_persisted_future_snapshots_after_transaction,
)


FRANCHISE_TRADE_TRANSACTION_VERSION = (
    "franchise-trade-transaction-commit-rollback-v1.0.1-auto-reconcile-2026-08-12"
)
TRANSACTION_HISTORY_ATTR = "franchise_transaction_history_v1"
DRAFT_OWNERSHIP_ATTR = "franchise_draft_right_ownership_v1"
TRADE_REVISION_ATTR = "franchise_trade_revision_v1"


class FranchiseTradeTransactionError(RuntimeError):
    """Raised when a live franchise transaction cannot be safely committed."""


@dataclass(frozen=True)
class FranchiseTradeCandidate:
    version: str
    transaction_id: str
    preview: FranchiseTradePreview
    state: Any
    transaction_record: dict[str, Any]


@dataclass(frozen=True)
class FranchiseTradeCommitResult:
    version: str
    transaction_id: str
    committed_state: Any
    transaction_record: dict[str, Any]
    checkpoint_saved_at_utc: str
    recovery_checkpoint_path: str


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _history(state: Any) -> list[dict[str, Any]]:
    raw = getattr(state, TRANSACTION_HISTORY_ATTR, None)
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise FranchiseTradeTransactionError(
            f"{TRANSACTION_HISTORY_ATTR} must be a list."
        )
    return copy.deepcopy(raw)


def _revision(state: Any) -> int:
    return int(getattr(state, TRADE_REVISION_ATTR, 0) or 0)


def _history_ids(state: Any) -> tuple[str, ...]:
    return tuple(
        _clean(row.get("transaction_id"))
        for row in _history(state)
        if _clean(row.get("transaction_id"))
    )


def _history_is_prefix(older: Any, newer: Any) -> bool:
    older_ids = _history_ids(older)
    newer_ids = _history_ids(newer)
    return older_ids == newer_ids[: len(older_ids)]


def select_commit_base_state(
    live_state: Any,
    durable_state: Any,
) -> tuple[Any, str]:
    """Choose the newest coherent state on the same franchise-trade lineage.

    This avoids forcing the user to manually reload after a harmless Streamlit
    rerun while still rejecting true fork/conflict states.
    """
    live_revision = _revision(live_state)
    durable_revision = _revision(durable_state)

    if live_revision == durable_revision:
        return live_state, "aligned"

    if durable_revision > live_revision and _history_is_prefix(live_state, durable_state):
        return copy.deepcopy(durable_state), "durable_newer_same_lineage"

    if live_revision > durable_revision and _history_is_prefix(durable_state, live_state):
        return live_state, "live_newer_same_lineage"

    raise FranchiseTradeTransactionError(
        "The live browser state and durable checkpoint are on different franchise-trade "
        "lineages. Automatic reconciliation is unsafe, so the transaction was not committed."
    )


def _draft_ownership(state: Any) -> dict[str, str]:
    raw = getattr(state, DRAFT_OWNERSHIP_ATTR, None)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise FranchiseTradeTransactionError(
            f"{DRAFT_OWNERSHIP_ATTR} must be a dictionary."
        )
    return {
        str(asset_id): normalize_team(owner)
        for asset_id, owner in raw.items()
        if str(asset_id).strip()
    }


def _state_signature(state: Any) -> str:
    payload = {
        "season": _clean(getattr(getattr(state, "settings", None), "season_label", "")),
        "trade_revision": _revision(state),
        "history_count": len(_history(state)),
        "draft_ownership": sorted(_draft_ownership(state).items()),
        "players": sorted(
            (
                str(pid),
                normalize_team(getattr(player, "team_abbreviation", "")),
            )
            for pid, player in getattr(state, "players", {}).items()
        ),
        "rosters": sorted(
            (
                normalize_team(team),
                tuple(getattr(team_state, "roster_player_ids", ())),
            )
            for team, team_state in getattr(state, "teams", {}).items()
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output


def _player_rating(state: Any, player_id: str) -> float:
    player = getattr(state, "players", {}).get(player_id)
    try:
        return float(getattr(player, "overall_rating", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _repair_team_rotation(state: Any, team: str, incoming_ids: tuple[str, ...]) -> None:
    resolved = normalize_team(team)
    team_state = getattr(state, "teams", {}).get(resolved)
    if team_state is None:
        raise FranchiseTradeTransactionError(f"Unknown live franchise team: {resolved}.")
    roster = _dedupe([
        normalize_player_id(pid)
        for pid in getattr(team_state, "roster_player_ids", ())
        if normalize_player_id(pid)
    ])
    roster_set = set(roster)
    if len(roster) < int(getattr(getattr(state, "settings", None), "minimum_game_players", 8) or 8):
        raise FranchiseTradeTransactionError(
            f"{resolved} would not have enough playable roster players after the trade."
        )

    old_rotation = getattr(team_state, "rotation", None)
    prior_rotation = [
        normalize_player_id(pid)
        for pid in getattr(old_rotation, "rotation_player_ids", ())
        if normalize_player_id(pid) in roster_set
    ]
    incoming = [
        normalize_player_id(pid)
        for pid in incoming_ids
        if normalize_player_id(pid) in roster_set
    ]
    remaining = sorted(
        (pid for pid in roster if pid not in set(prior_rotation) and pid not in set(incoming)),
        key=lambda pid: (-_player_rating(state, pid), pid),
    )
    incoming_sorted = sorted(
        incoming,
        key=lambda pid: (-_player_rating(state, pid), pid),
    )
    ordered = _dedupe(prior_rotation + incoming_sorted + remaining)
    target_size = min(
        len(roster),
        max(5, int(getattr(getattr(state, "settings", None), "rotation_size", 10) or 10)),
    )
    rotation_ids = tuple(ordered[:target_size])

    prior_starters = [
        normalize_player_id(pid)
        for pid in getattr(old_rotation, "starter_ids", ())
        if normalize_player_id(pid) in set(rotation_ids)
    ]
    starter_fill = sorted(
        (pid for pid in rotation_ids if pid not in set(prior_starters)),
        key=lambda pid: (-_player_rating(state, pid), pid),
    )
    starter_ids = tuple(_dedupe(prior_starters + starter_fill)[:5])
    if len(starter_ids) != 5:
        raise FranchiseTradeTransactionError(
            f"{resolved} could not rebuild a five-player starting lineup."
        )
    regulation = int(getattr(getattr(state, "settings", None), "regulation_minutes", 48) or 48)
    team_state.rotation = RotationState(
        starter_ids=starter_ids,
        rotation_player_ids=rotation_ids,
        minutes_targets=minutes_targets(
            rotation_ids,
            starter_ids,
            regulation_minutes=regulation,
        ),
    )
    team_state.active_player_ids = rotation_ids
    team_state.inactive_player_ids = tuple(pid for pid in roster if pid not in set(rotation_ids))


def _apply_player_moves(
    state: Any,
    *,
    team_a: str,
    team_b: str,
    side_a_player_ids: tuple[str, ...],
    side_b_player_ids: tuple[str, ...],
) -> None:
    a = normalize_team(team_a)
    b = normalize_team(team_b)
    a_out = tuple(normalize_player_id(pid) for pid in side_a_player_ids if normalize_player_id(pid))
    b_out = tuple(normalize_player_id(pid) for pid in side_b_player_ids if normalize_player_id(pid))
    team_a_state = state.teams[a]
    team_b_state = state.teams[b]
    a_roster = [normalize_player_id(pid) for pid in team_a_state.roster_player_ids]
    b_roster = [normalize_player_id(pid) for pid in team_b_state.roster_player_ids]
    if not set(a_out).issubset(a_roster):
        raise FranchiseTradeTransactionError(f"{a} no longer owns every outgoing player.")
    if not set(b_out).issubset(b_roster):
        raise FranchiseTradeTransactionError(f"{b} no longer owns every outgoing player.")

    team_a_state.roster_player_ids = tuple(
        _dedupe([pid for pid in a_roster if pid not in set(a_out)] + list(b_out))
    )
    team_b_state.roster_player_ids = tuple(
        _dedupe([pid for pid in b_roster if pid not in set(b_out)] + list(a_out))
    )
    for player_id in a_out:
        state.players[player_id].team_abbreviation = b
    for player_id in b_out:
        state.players[player_id].team_abbreviation = a

    _repair_team_rotation(state, a, b_out)
    _repair_team_rotation(state, b, a_out)


def _apply_draft_moves(
    state: Any,
    *,
    team_a: str,
    team_b: str,
    side_a_pick_asset_ids: tuple[str, ...],
    side_b_pick_asset_ids: tuple[str, ...],
) -> None:
    a = normalize_team(team_a)
    b = normalize_team(team_b)
    ownership = _draft_ownership(state)
    for asset_id in side_a_pick_asset_ids:
        ownership[str(asset_id)] = b
    for asset_id in side_b_pick_asset_ids:
        ownership[str(asset_id)] = a
    setattr(state, DRAFT_OWNERSHIP_ATTR, ownership)


def _next_transaction_id(state: Any) -> str:
    return f"FTX-{_revision(state) + 1:04d}"


# RFA_OFFER_SHEET_TRADE_CAP_PROTECTION_V1
def _current_contract_salary(state: Any, player_id: str) -> float:
    pid = normalize_player_id(player_id)
    players = getattr(state, "players", {}) or {}
    player = players.get(pid)
    if player is None:
        raise FranchiseTradeTransactionError(
            f"Pending-offer-sheet trade guard could not resolve player {pid}."
        )
    contract = getattr(player, "contract", None)
    if contract is None:
        raise FranchiseTradeTransactionError(
            f"Pending-offer-sheet trade guard could not resolve the current contract for {pid}."
        )
    try:
        salary = float(getattr(contract, "salary"))
    except (TypeError, ValueError, AttributeError) as exc:
        raise FranchiseTradeTransactionError(
            f"Pending-offer-sheet trade guard could not resolve the current salary for {pid}."
        ) from exc
    if salary < 0:
        raise FranchiseTradeTransactionError(
            f"Pending-offer-sheet trade guard found an invalid salary for {pid}."
        )
    return salary


def pending_rfa_offer_sheet_trade_capacity_report(
    state: Any,
    *,
    team_a: str,
    team_b: str,
    side_a_player_ids: tuple[str, ...] = (),
    side_b_player_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    # Conservatively protect a signed offer sheet from salary-adding trades.
    from franchise_free_agency_rfa_offer_sheet_v1 import (
        pending_offer_sheet_for_team,
    )

    a = normalize_team(team_a)
    b = normalize_team(team_b)
    rows: list[dict[str, Any]] = []

    for team, outgoing_ids, incoming_ids in (
        (a, tuple(side_a_player_ids), tuple(side_b_player_ids)),
        (b, tuple(side_b_player_ids), tuple(side_a_player_ids)),
    ):
        pending = pending_offer_sheet_for_team(state, team)
        if pending is None:
            continue
        if normalize_team(pending.get("offering_team")) != team:
            continue

        reserved = float(
            pending.get("reserved_initial_salary")
            or pending.get("annual_salary")
            or 0.0
        )
        try:
            outgoing_salary = sum(
                _current_contract_salary(state, pid)
                for pid in outgoing_ids
            )
            incoming_salary = sum(
                _current_contract_salary(state, pid)
                for pid in incoming_ids
            )
        except FranchiseTradeTransactionError as exc:
            rows.append(
                {
                    "team": team,
                    "offer_sheet_id": str(pending.get("offer_sheet_id") or ""),
                    "status": "blocked",
                    "blocked": True,
                    "reason": str(exc),
                    "outgoing_salary": None,
                    "incoming_salary": None,
                    "salary_delta": None,
                    "reserved_initial_salary": reserved,
                    "mode": "fail_closed_unknown_trade_salary",
                }
            )
            continue

        delta = incoming_salary - outgoing_salary
        blocked = delta > 0.01
        rows.append(
            {
                "team": team,
                "offer_sheet_id": str(pending.get("offer_sheet_id") or ""),
                "player_id": str(pending.get("player_id") or ""),
                "player_name": str(pending.get("player_name") or ""),
                "status": "blocked" if blocked else "pass",
                "blocked": blocked,
                "outgoing_salary": outgoing_salary,
                "incoming_salary": incoming_salary,
                "salary_delta": delta,
                "reserved_initial_salary": reserved,
                "mode": "conservative_no_positive_salary_delta_while_sheet_pending",
                "reason": (
                    f"{team} has pending offer sheet {pending.get('offer_sheet_id')}. "
                    f"This trade would add ${delta:,.0f} of current player salary while "
                    f"${reserved:,.0f} remains committed to the signed RFA sheet."
                    if blocked
                    else
                    f"{team} has pending offer sheet {pending.get('offer_sheet_id')}, "
                    "but this package does not increase current player salary."
                ),
            }
        )

    blocked_rows = [row for row in rows if row["blocked"]]
    return {
        "version": "rfa-offer-sheet-trade-cap-protection-v1-2026-08-17",
        "status": "blocked" if blocked_rows else ("pass" if rows else "not_applicable"),
        "blocked": bool(blocked_rows),
        "teams": rows,
    }


def assert_pending_rfa_offer_sheet_trade_capacity(
    state: Any,
    *,
    team_a: str,
    team_b: str,
    side_a_player_ids: tuple[str, ...] = (),
    side_b_player_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    report = pending_rfa_offer_sheet_trade_capacity_report(
        state,
        team_a=team_a,
        team_b=team_b,
        side_a_player_ids=side_a_player_ids,
        side_b_player_ids=side_b_player_ids,
    )
    if report["blocked"]:
        reasons = "; ".join(
            str(row.get("reason") or "")
            for row in report["teams"]
            if row.get("blocked")
        )
        raise FranchiseTradeTransactionError(
            "Trade blocked by pending RFA offer-sheet capacity protection. "
            + reasons
        )
    return report


def build_franchise_trade_candidate(
    runtime: Any,
    state: Any,
    trade_state: Any,
    *,
    team_a: str,
    team_b: str,
    side_a_player_ids: tuple[str, ...] = (),
    side_b_player_ids: tuple[str, ...] = (),
    side_a_pick_asset_ids: tuple[str, ...] = (),
    side_b_pick_asset_ids: tuple[str, ...] = (),
    expected_fingerprint: str = "",
) -> FranchiseTradeCandidate:
    before_signature = _state_signature(state)
    preview = build_franchise_trade_preview(
        runtime,
        state,
        trade_state,
        team_a=team_a,
        team_b=team_b,
        side_a_player_ids=side_a_player_ids,
        side_b_player_ids=side_b_player_ids,
        side_a_pick_asset_ids=side_a_pick_asset_ids,
        side_b_pick_asset_ids=side_b_pick_asset_ids,
    )
    if expected_fingerprint and preview.package_fingerprint != expected_fingerprint:
        raise FranchiseTradeTransactionError(
            "The package changed after its legality preview. Re-evaluate before committing."
        )
    if preview.status != "pass" or not preview.can_commit:
        raise FranchiseTradeTransactionError(
            f"Only a deterministic PASS package can be committed; current status is {preview.status}."
        )

    assert_pending_rfa_offer_sheet_trade_capacity(
        state,
        team_a=team_a,
        team_b=team_b,
        side_a_player_ids=side_a_player_ids,
        side_b_player_ids=side_b_player_ids,
    )

    candidate = copy.deepcopy(state)
    a = normalize_team(team_a)
    b = normalize_team(team_b)
    roster_a_before = len(candidate.teams[a].roster_player_ids)
    roster_b_before = len(candidate.teams[b].roster_player_ids)
    _apply_player_moves(
        candidate,
        team_a=a,
        team_b=b,
        side_a_player_ids=side_a_player_ids,
        side_b_player_ids=side_b_player_ids,
    )
    _apply_draft_moves(
        candidate,
        team_a=a,
        team_b=b,
        side_a_pick_asset_ids=side_a_pick_asset_ids,
        side_b_pick_asset_ids=side_b_pick_asset_ids,
    )

    revision = _revision(candidate) + 1
    transaction_id = f"FTX-{revision:04d}"
    record = {
        "version": FRANCHISE_TRADE_TRANSACTION_VERSION,
        "transaction_id": transaction_id,
        "status": "committed",
        "committed_at_utc": datetime.now(timezone.utc).isoformat(),
        "season_label": _clean(getattr(getattr(candidate, "settings", None), "season_label", "")),
        "day_index": int(getattr(candidate, "current_day_index", 0) or 0),
        "team_a": a,
        "team_b": b,
        "side_a_player_ids": list(side_a_player_ids),
        "side_b_player_ids": list(side_b_player_ids),
        "side_a_pick_asset_ids": list(side_a_pick_asset_ids),
        "side_b_pick_asset_ids": list(side_b_pick_asset_ids),
        "package_fingerprint": preview.package_fingerprint,
        "financial_bridge_status": preview.financial_bridge_status,
        "player_contract_bridge_status": preview.player_contract_bridge_status,
        "draft_right_bridge_status": preview.draft_right_bridge_status,
        "canonical_engine_status": preview.canonical_engine_status,
        "roster_a_before": roster_a_before,
        "roster_a_after": len(candidate.teams[a].roster_player_ids),
        "roster_b_before": roster_b_before,
        "roster_b_after": len(candidate.teams[b].roster_player_ids),
    }
    history = _history(candidate)
    history.append(copy.deepcopy(record))
    setattr(candidate, TRANSACTION_HISTORY_ATTR, history)
    setattr(candidate, TRADE_REVISION_ATTR, revision)

    # FRANCHISE_FUTURE_TRADE_SNAPSHOT_REFRESH_V1
    refresh_persisted_future_snapshots_after_transaction(
        runtime,
        candidate,
        player_transaction=bool(
            side_a_player_ids or side_b_player_ids
        ),
    )
    validate_simulation_league_state(candidate)
    ledger = build_live_asset_ledger(runtime, candidate, trade_state)
    players = {row["player_id"]: row for row in ledger.player_rows}
    picks = {row["asset_id"]: row for row in ledger.draft_rows}
    for player_id in side_a_player_ids:
        if normalize_team(players[normalize_player_id(player_id)]["team"]) != b:
            raise FranchiseTradeTransactionError(
                f"Candidate ledger did not transfer player {player_id} to {b}."
            )
    for player_id in side_b_player_ids:
        if normalize_team(players[normalize_player_id(player_id)]["team"]) != a:
            raise FranchiseTradeTransactionError(
                f"Candidate ledger did not transfer player {player_id} to {a}."
            )
    for asset_id in side_a_pick_asset_ids:
        if normalize_team(picks[str(asset_id)]["current_owner"]) != b:
            raise FranchiseTradeTransactionError(
                f"Candidate ledger did not transfer draft asset {asset_id} to {b}."
            )
    for asset_id in side_b_pick_asset_ids:
        if normalize_team(picks[str(asset_id)]["current_owner"]) != a:
            raise FranchiseTradeTransactionError(
                f"Candidate ledger did not transfer draft asset {asset_id} to {a}."
            )
    # A transferred procedural pick must remain bridge-ready for its new owner.
    profile_by_id = {
        item.asset_id: item
        for item in build_franchise_draft_right_profiles(ledger)
    }
    for asset_id in (*side_a_pick_asset_ids, *side_b_pick_asset_ids):
        profile = profile_by_id.get(str(asset_id))
        if profile is not None and profile.asset_type == "procedural_future_own_pick" and not profile.bridge_ready:
            raise FranchiseTradeTransactionError(
                f"Transferred procedural draft asset {asset_id} did not remain franchise bridge-ready."
            )

    if _state_signature(state) != before_signature:
        raise FranchiseTradeTransactionError(
            "Candidate construction mutated the live source state."
        )
    return FranchiseTradeCandidate(
        version=FRANCHISE_TRADE_TRANSACTION_VERSION,
        transaction_id=transaction_id,
        preview=preview,
        state=candidate,
        transaction_record=record,
    )


def _checkpoint_path() -> Path:
    return Path(DEFAULT_CHECKPOINT_PATH)


def _checkpoint_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def commit_live_franchise_trade(
    runtime: Any,
    state: Any,
    trade_state: Any,
    *,
    team_a: str,
    team_b: str,
    side_a_player_ids: tuple[str, ...] = (),
    side_b_player_ids: tuple[str, ...] = (),
    side_a_pick_asset_ids: tuple[str, ...] = (),
    side_b_pick_asset_ids: tuple[str, ...] = (),
    expected_fingerprint: str,
    recovery_directory: Path | None = None,
) -> FranchiseTradeCommitResult:
    primary = _checkpoint_path()
    if not primary.is_file():
        raise FranchiseTradeTransactionError(
            "The durable franchise checkpoint is missing; live trade commit is disabled."
        )
    original_checkpoint = load_franchise_checkpoint()
    if original_checkpoint is None:
        raise FranchiseTradeTransactionError(
            "The durable franchise checkpoint could not be loaded."
        )
    # Streamlit widget interactions rerun the page. If the durable checkpoint
    # is one transaction revision ahead/behind but both states share the same
    # franchise-trade lineage, reconcile automatically instead of making the
    # user reload the entire page. A true fork still hard-fails.
    commit_state, reconciliation = select_commit_base_state(
        state,
        original_checkpoint.simulation_state,
    )

    commit_fingerprint = expected_fingerprint
    if reconciliation == "durable_newer_same_lineage":
        # Re-evaluate the exact selected assets against the newer durable state.
        # This prevents an old PASS preview from being force-applied after
        # ownership or legality changed.
        reconciled_preview = build_franchise_trade_preview(
            runtime,
            commit_state,
            trade_state,
            team_a=team_a,
            team_b=team_b,
            side_a_player_ids=side_a_player_ids,
            side_b_player_ids=side_b_player_ids,
            side_a_pick_asset_ids=side_a_pick_asset_ids,
            side_b_pick_asset_ids=side_b_pick_asset_ids,
        )
        if reconciled_preview.status != "pass" or not reconciled_preview.can_commit:
            raise FranchiseTradeTransactionError(
                "The durable franchise advanced since this preview and the same package "
                "no longer has a deterministic PASS. Nothing was committed."
            )
        commit_fingerprint = reconciled_preview.package_fingerprint

    candidate = build_franchise_trade_candidate(
        runtime,
        commit_state,
        trade_state,
        team_a=team_a,
        team_b=team_b,
        side_a_player_ids=side_a_player_ids,
        side_b_player_ids=side_b_player_ids,
        side_a_pick_asset_ids=side_a_pick_asset_ids,
        side_b_pick_asset_ids=side_b_pick_asset_ids,
        expected_fingerprint=commit_fingerprint,
    )

    try:
        pretrade_saved = save_franchise_checkpoint(
            commit_state,
            trade_state,
            preferences=copy.deepcopy(getattr(original_checkpoint, "preferences", {}) or {}),
            reason=f"franchise-pre-trade-{candidate.transaction_id}",
            copy_payload=True,
        )
        pretrade_reload = load_franchise_checkpoint()
        if pretrade_reload is None or _state_signature(pretrade_reload.simulation_state) != _state_signature(commit_state):
            raise FranchiseTradeTransactionError(
                "The forced pre-trade checkpoint did not round-trip the current live franchise state."
            )
    except Exception as exc:
        raise FranchiseTradeTransactionError(
            f"Could not create the required pre-trade durable save. No trade was committed. {exc}"
        ) from exc

    recovery_root = recovery_directory or (Path(__file__).resolve().parents[1] / "backups")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    recovery = recovery_root / (
        f"franchise_trade_pre_{candidate.transaction_id}_{stamp}.pkl.gz"
    )
    try:
        recovery_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(primary, recovery)
        original_hash = _checkpoint_sha(primary)
    except Exception as exc:
        raise FranchiseTradeTransactionError(
            f"Could not create the pre-trade recovery checkpoint. No trade was committed. {exc}"
        ) from exc

    try:
        saved = save_franchise_checkpoint(
            candidate.state,
            trade_state,
            preferences=copy.deepcopy(getattr(original_checkpoint, "preferences", {}) or {}),
            reason=f"franchise-live-trade-{candidate.transaction_id}",
            copy_payload=True,
        )
        reloaded = load_franchise_checkpoint()
        if reloaded is None:
            raise FranchiseTradeTransactionError(
                "Saved trade checkpoint could not be reloaded."
            )
        live_history = _history(reloaded.simulation_state)
        if not live_history or live_history[-1].get("transaction_id") != candidate.transaction_id:
            raise FranchiseTradeTransactionError(
                "Saved checkpoint did not round-trip the committed franchise transaction."
            )
        if _revision(reloaded.simulation_state) != _revision(candidate.state):
            raise FranchiseTradeTransactionError(
                "Saved checkpoint did not round-trip the live trade revision."
            )
        validate_simulation_league_state(reloaded.simulation_state)
        reloaded_ledger = build_live_asset_ledger(
            runtime, reloaded.simulation_state, reloaded.trade_state
        )
        player_map = {row["player_id"]: row for row in reloaded_ledger.player_rows}
        pick_map = {row["asset_id"]: row for row in reloaded_ledger.draft_rows}
        a = normalize_team(team_a)
        b = normalize_team(team_b)
        for pid in side_a_player_ids:
            if normalize_team(player_map[normalize_player_id(pid)]["team"]) != b:
                raise FranchiseTradeTransactionError("Reloaded checkpoint lost a Side A player transfer.")
        for pid in side_b_player_ids:
            if normalize_team(player_map[normalize_player_id(pid)]["team"]) != a:
                raise FranchiseTradeTransactionError("Reloaded checkpoint lost a Side B player transfer.")
        for aid in side_a_pick_asset_ids:
            if normalize_team(pick_map[str(aid)]["current_owner"]) != b:
                raise FranchiseTradeTransactionError("Reloaded checkpoint lost a Side A draft-right transfer.")
        for aid in side_b_pick_asset_ids:
            if normalize_team(pick_map[str(aid)]["current_owner"]) != a:
                raise FranchiseTradeTransactionError("Reloaded checkpoint lost a Side B draft-right transfer.")
        return FranchiseTradeCommitResult(
            version=FRANCHISE_TRADE_TRANSACTION_VERSION,
            transaction_id=candidate.transaction_id,
            committed_state=reloaded.simulation_state,
            transaction_record=copy.deepcopy(candidate.transaction_record),
            checkpoint_saved_at_utc=_clean(getattr(saved, "saved_at_utc", "")),
            recovery_checkpoint_path=str(recovery),
        )
    except Exception as exc:
        try:
            shutil.copy2(recovery, primary)
            restored = load_franchise_checkpoint()
            if restored is None or _checkpoint_sha(primary) != original_hash:
                raise FranchiseTradeTransactionError(
                    "Automatic checkpoint rollback verification failed."
                )
        except Exception as rollback_exc:
            raise FranchiseTradeTransactionError(
                "Trade commit failed and automatic durable-checkpoint rollback also failed. "
                f"Recovery file remains at {recovery}. Original error: {exc}. "
                f"Rollback error: {rollback_exc}."
            ) from rollback_exc
        raise FranchiseTradeTransactionError(
            f"Trade commit failed; the pre-trade durable checkpoint was restored automatically. {exc}"
        ) from exc
