from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from franchise_financial_cba_bridge_v1 import (
    build_franchise_financial_snapshot,
    snapshot_to_dict as financial_snapshot_to_dict,
)
from franchise_player_contract_bridge_v1 import (
    build_franchise_player_contract_snapshot,
    snapshot_to_dict as contract_snapshot_to_dict,
)


POST_TRANSACTION_SNAPSHOT_REFRESH_VERSION = (
    "franchise-future-trade-post-transaction-snapshot-refresh-v1-2026-08-17"
)

FINANCIAL_ATTR = "franchise_active_financial_snapshot_v1"
CONTRACT_ATTR = "franchise_active_contract_snapshot_v1"
METADATA_ATTR = "franchise_financial_rights_boundary_metadata_v1"


class PostTransactionSnapshotRefreshError(RuntimeError):
    pass


@dataclass(frozen=True)
class PostTransactionSnapshotRefreshResult:
    version: str
    season_label: str
    applied: bool
    reason: str
    franchise_trade_revision: int
    transaction_history_count: int
    financial_snapshot_digest_before: str
    financial_snapshot_digest_after: str
    contract_snapshot_digest_before: str
    contract_snapshot_digest_after: str


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _normalize(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return _normalize(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {
            str(key): _normalize(item)
            for key, item in sorted(
                value.items(),
                key=lambda pair: str(pair[0]),
            )
        }
    if isinstance(value, (list, tuple, set)):
        return [_normalize(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "__dict__"):
        return _normalize(vars(value))
    return str(value)


def _digest(value: Any) -> str:
    raw = json.dumps(
        _normalize(value),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _season(state: Any) -> str:
    return _clean(
        getattr(
            getattr(state, "settings", None),
            "season_label",
            "",
        )
    )


def _anchor_season(runtime: Any) -> str:
    rules = getattr(runtime, "rules", {}) or {}
    return _clean(rules.get("league_year"))


def _revision(state: Any) -> int:
    return int(
        getattr(state, "franchise_trade_revision_v1", 0)
        or 0
    )


def _history_count(state: Any) -> int:
    return len(
        getattr(
            state,
            "franchise_transaction_history_v1",
            (),
        )
        or ()
    )


def refresh_persisted_future_snapshots_after_transaction(
    runtime: Any,
    state: Any,
    *,
    player_transaction: bool,
) -> PostTransactionSnapshotRefreshResult:
    """
    Refresh the persisted target-season financial + contract views after a
    Franchise player transaction.

    This intentionally does not touch TradeState.team_financials. Future-season
    trade legality continues to use the existing Simulation-native bridges.

    Anchor-season (2026-27) behavior is a hard no-op.
    Pick-only future transactions are also a no-op because player/roster
    financial and contract state did not change.
    """
    season = _season(state)
    anchor = _anchor_season(runtime)

    old_financial = copy.deepcopy(
        getattr(state, FINANCIAL_ATTR, None)
    )
    old_contract = copy.deepcopy(
        getattr(state, CONTRACT_ATTR, None)
    )
    old_fin_digest = _digest(old_financial)
    old_contract_digest = _digest(old_contract)

    if not player_transaction:
        return PostTransactionSnapshotRefreshResult(
            version=POST_TRANSACTION_SNAPSHOT_REFRESH_VERSION,
            season_label=season,
            applied=False,
            reason="no_player_transaction",
            franchise_trade_revision=_revision(state),
            transaction_history_count=_history_count(state),
            financial_snapshot_digest_before=old_fin_digest,
            financial_snapshot_digest_after=old_fin_digest,
            contract_snapshot_digest_before=old_contract_digest,
            contract_snapshot_digest_after=old_contract_digest,
        )

    if not season or not anchor:
        raise PostTransactionSnapshotRefreshError(
            "Could not resolve live or anchor season for snapshot refresh."
        )

    if season == anchor:
        return PostTransactionSnapshotRefreshResult(
            version=POST_TRANSACTION_SNAPSHOT_REFRESH_VERSION,
            season_label=season,
            applied=False,
            reason="anchor_season_preserves_deterministic_2026_27_authority",
            franchise_trade_revision=_revision(state),
            transaction_history_count=_history_count(state),
            financial_snapshot_digest_before=old_fin_digest,
            financial_snapshot_digest_after=old_fin_digest,
            contract_snapshot_digest_before=old_contract_digest,
            contract_snapshot_digest_after=old_contract_digest,
        )

    metadata = getattr(state, METADATA_ATTR, None)
    if not isinstance(old_financial, dict):
        raise PostTransactionSnapshotRefreshError(
            "Future Franchise player transaction has no persisted active financial snapshot."
        )
    if not isinstance(old_contract, dict):
        raise PostTransactionSnapshotRefreshError(
            "Future Franchise player transaction has no persisted active contract snapshot."
        )
    if not isinstance(metadata, dict):
        raise PostTransactionSnapshotRefreshError(
            "Future Franchise player transaction has no financial/rights boundary metadata."
        )
    if not bool(metadata.get("active_snapshots_installed")):
        raise PostTransactionSnapshotRefreshError(
            "Future Franchise active snapshots are not marked installed."
        )
    if _clean(metadata.get("target_season")) != season:
        raise PostTransactionSnapshotRefreshError(
            "Future Franchise snapshot metadata does not match the live season."
        )

    financial_snapshot = build_franchise_financial_snapshot(
        runtime,
        state,
    )
    contract_snapshot = build_franchise_player_contract_snapshot(
        runtime,
        state,
    )

    financial_payload = financial_snapshot_to_dict(
        financial_snapshot
    )
    contract_payload = contract_snapshot_to_dict(
        contract_snapshot
    )

    if _clean(financial_payload.get("season_label")) != season:
        raise PostTransactionSnapshotRefreshError(
            "Refreshed financial snapshot season does not match live Franchise season."
        )
    if _clean(contract_payload.get("season_label")) != season:
        raise PostTransactionSnapshotRefreshError(
            "Refreshed contract snapshot season does not match live Franchise season."
        )
    if len(financial_payload.get("team_financials", ()) or ()) != 30:
        raise PostTransactionSnapshotRefreshError(
            "Refreshed financial snapshot does not cover all 30 teams."
        )
    if len(contract_payload.get("profiles", ()) or ()) != len(
        getattr(state, "players", {}) or {}
    ):
        raise PostTransactionSnapshotRefreshError(
            "Refreshed contract snapshot does not cover the full player population."
        )

    new_fin_digest = _digest(financial_payload)
    new_contract_digest = _digest(contract_payload)

    setattr(
        state,
        FINANCIAL_ATTR,
        financial_payload,
    )
    setattr(
        state,
        CONTRACT_ATTR,
        contract_payload,
    )

    metadata_candidate = copy.deepcopy(metadata)
    metadata_candidate["financial_snapshot_digest"] = (
        new_fin_digest
    )
    metadata_candidate["contract_snapshot_digest"] = (
        new_contract_digest
    )
    metadata_candidate["last_transaction_snapshot_refresh"] = {
        "version": POST_TRANSACTION_SNAPSHOT_REFRESH_VERSION,
        "season_label": season,
        "franchise_trade_revision": _revision(state),
        "transaction_history_count": _history_count(state),
        "trade_financials_rebased": False,
        "scope": "post_player_transaction",
    }
    setattr(
        state,
        METADATA_ATTR,
        metadata_candidate,
    )

    return PostTransactionSnapshotRefreshResult(
        version=POST_TRANSACTION_SNAPSHOT_REFRESH_VERSION,
        season_label=season,
        applied=True,
        reason="future_player_transaction_snapshots_refreshed",
        franchise_trade_revision=_revision(state),
        transaction_history_count=_history_count(state),
        financial_snapshot_digest_before=old_fin_digest,
        financial_snapshot_digest_after=new_fin_digest,
        contract_snapshot_digest_before=old_contract_digest,
        contract_snapshot_digest_after=new_contract_digest,
    )
