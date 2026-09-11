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
from simulation_season_transition_v1 import load_runtime_data


SEASON_BOUNDARY_FINANCIAL_RIGHTS_ROLLOVER_VERSION = (
    "season-boundary-financial-rights-rollover-v1-2026-08-17"
)

ARCHIVE_ATTR = "franchise_financial_rights_boundary_archive_v1"
ACTIVE_FINANCIAL_ATTR = "franchise_active_financial_snapshot_v1"
ACTIVE_CONTRACT_ATTR = "franchise_active_contract_snapshot_v1"
METADATA_ATTR = "franchise_financial_rights_boundary_metadata_v1"

ARCHIVED_SURFACES = (
    "offseason_official_team_salary_components_v1",
    "offseason_rfa_rights_qo_decisions_v1",
    "offseason_non_rfa_rights_decisions_v1",
    "offseason_free_agent_amount_candidates_v1",
)


class SeasonBoundaryFinancialRightsRolloverError(RuntimeError):
    pass


@dataclass(frozen=True)
class SeasonBoundaryFinancialRightsRolloverResult:
    version: str
    source_season: str
    target_season: str
    applied: bool
    archived_surface_count: int
    archived_row_count: int
    archived_surface_digests: dict[str, str]
    financial_snapshot_digest: str
    contract_snapshot_digest: str
    financial_team_count: int
    contract_profile_count: int
    trade_financials_digest_before: str
    trade_financials_digest_after: str


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


def _row_count(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    return 1


def _trade_financials_digest(trade_state: Any) -> str:
    return _digest(
        getattr(trade_state, "team_financials", {}) or {}
    )


def _target_season(state: Any) -> str:
    settings = getattr(state, "settings", None)
    return _clean(getattr(settings, "season_label", ""))


def _phase(state: Any) -> str:
    raw = getattr(state, "phase", "")
    return _clean(getattr(raw, "value", raw)).lower()


def _archive_list(state: Any) -> list[dict[str, Any]]:
    existing = getattr(state, ARCHIVE_ATTR, ()) or ()
    if not isinstance(existing, (list, tuple)):
        raise SeasonBoundaryFinancialRightsRolloverError(
            "The financial/rights boundary archive has an invalid shape."
        )
    return copy.deepcopy(list(existing))


def _marker_matches(
    state: Any,
    *,
    source_season: str,
    target_season: str,
) -> bool:
    marker = getattr(state, METADATA_ATTR, None)
    if not isinstance(marker, dict):
        return False
    return (
        _clean(marker.get("version"))
        == SEASON_BOUNDARY_FINANCIAL_RIGHTS_ROLLOVER_VERSION
        and _clean(marker.get("source_season")) == source_season
        and _clean(marker.get("target_season")) == target_season
        and bool(marker.get("active_snapshots_installed"))
        and bool(marker.get("old_offseason_surfaces_deactivated"))
    )


def _active_surfaces_are_empty(state: Any) -> bool:
    return all(
        _row_count(getattr(state, attr, ()) or ()) == 0
        for attr in ARCHIVED_SURFACES
    )


def _snapshot_result_from_existing(
    state: Any,
    trade_state: Any,
    *,
    source_season: str,
    target_season: str,
) -> SeasonBoundaryFinancialRightsRolloverResult:
    financial = getattr(state, ACTIVE_FINANCIAL_ATTR, None)
    contract = getattr(state, ACTIVE_CONTRACT_ATTR, None)
    if not isinstance(financial, dict) or not isinstance(contract, dict):
        raise SeasonBoundaryFinancialRightsRolloverError(
            "The season-boundary marker exists but the active snapshots are missing."
        )

    archive = _archive_list(state)
    event = archive[-1] if archive else {}
    digests = dict(event.get("surface_digests", {}) or {})
    trade_digest = _trade_financials_digest(trade_state)
    return SeasonBoundaryFinancialRightsRolloverResult(
        version=SEASON_BOUNDARY_FINANCIAL_RIGHTS_ROLLOVER_VERSION,
        source_season=source_season,
        target_season=target_season,
        applied=False,
        archived_surface_count=len(digests),
        archived_row_count=int(
            event.get("archived_row_count", 0) or 0
        ),
        archived_surface_digests=digests,
        financial_snapshot_digest=_digest(financial),
        contract_snapshot_digest=_digest(contract),
        financial_team_count=len(
            financial.get("team_financials", ()) or ()
        ),
        contract_profile_count=len(
            contract.get("profiles", ()) or ()
        ),
        trade_financials_digest_before=trade_digest,
        trade_financials_digest_after=trade_digest,
    )


def rollover_financial_rights_after_season_boundary(
    state: Any,
    trade_state: Any,
    *,
    source_season: str,
    target_season: str,
) -> tuple[Any, SeasonBoundaryFinancialRightsRolloverResult]:
    source = _clean(source_season)
    target = _clean(target_season)

    if not source or not target or source == target:
        raise SeasonBoundaryFinancialRightsRolloverError(
            "Financial/rights rollover requires distinct source and target seasons."
        )
    if _target_season(state) != target:
        raise SeasonBoundaryFinancialRightsRolloverError(
            "The transitioned SimulationState does not match the requested target season."
        )
    if _phase(state) != "regular_season":
        raise SeasonBoundaryFinancialRightsRolloverError(
            "Financial/rights rollover requires the activated target regular season."
        )

    if _marker_matches(
        state,
        source_season=source,
        target_season=target,
    ):
        if not _active_surfaces_are_empty(state):
            raise SeasonBoundaryFinancialRightsRolloverError(
                "The rollover marker is present but old offseason surfaces are active."
            )
        return (
            copy.deepcopy(state),
            _snapshot_result_from_existing(
                state,
                trade_state,
                source_season=source,
                target_season=target,
            ),
        )

    state_candidate = copy.deepcopy(state)
    trade_digest_before = _trade_financials_digest(trade_state)

    archived_payload: dict[str, Any] = {}
    surface_digests: dict[str, str] = {}
    row_counts: dict[str, int] = {}

    for attr in ARCHIVED_SURFACES:
        payload = copy.deepcopy(
            getattr(state_candidate, attr, ()) or ()
        )
        archived_payload[attr] = payload
        surface_digests[attr] = _digest(payload)
        row_counts[attr] = _row_count(payload)
        # These are prior-offseason active surfaces. Preserve them only in the
        # archive after the season changes; do not let old charges remain live.
        setattr(state_candidate, attr, [])

    runtime = load_runtime_data()
    financial_snapshot = build_franchise_financial_snapshot(
        runtime,
        state_candidate,
    )
    contract_snapshot = build_franchise_player_contract_snapshot(
        runtime,
        state_candidate,
    )

    financial_payload = financial_snapshot_to_dict(
        financial_snapshot
    )
    contract_payload = contract_snapshot_to_dict(
        contract_snapshot
    )

    if _clean(financial_payload.get("season_label")) != target:
        raise SeasonBoundaryFinancialRightsRolloverError(
            "The fresh financial snapshot does not match the target season."
        )
    if _clean(contract_payload.get("season_label")) != target:
        raise SeasonBoundaryFinancialRightsRolloverError(
            "The fresh contract snapshot does not match the target season."
        )

    team_count = len(
        financial_payload.get("team_financials", ()) or ()
    )
    profile_count = len(
        contract_payload.get("profiles", ()) or ()
    )
    player_count = len(
        getattr(state_candidate, "players", {}) or {}
    )

    if team_count != 30:
        raise SeasonBoundaryFinancialRightsRolloverError(
            "The fresh financial snapshot does not contain all 30 teams."
        )
    if profile_count != player_count:
        raise SeasonBoundaryFinancialRightsRolloverError(
            "The fresh contract snapshot does not cover the full player population."
        )

    archive = _archive_list(state_candidate)
    event = {
        "version":
            SEASON_BOUNDARY_FINANCIAL_RIGHTS_ROLLOVER_VERSION,
        "source_season": source,
        "target_season": target,
        "archived_surfaces": archived_payload,
        "surface_digests": surface_digests,
        "surface_row_counts": row_counts,
        "archived_row_count": sum(row_counts.values()),
        "trade_financials_digest_at_rollover":
            trade_digest_before,
        "trade_financials_rebased": False,
        "trade_financial_rebase_reason":
            (
                "future_financial_bridge_apron_ledger_incomplete;"
                "mutable_trade_financials_require_separate_authority"
            ),
    }
    archive.append(event)

    setattr(state_candidate, ARCHIVE_ATTR, archive)
    setattr(
        state_candidate,
        ACTIVE_FINANCIAL_ATTR,
        financial_payload,
    )
    setattr(
        state_candidate,
        ACTIVE_CONTRACT_ATTR,
        contract_payload,
    )
    setattr(
        state_candidate,
        METADATA_ATTR,
        {
            "version":
                SEASON_BOUNDARY_FINANCIAL_RIGHTS_ROLLOVER_VERSION,
            "source_season": source,
            "target_season": target,
            "active_snapshots_installed": True,
            "old_offseason_surfaces_deactivated": True,
            "trade_financials_rebased": False,
            "trade_financial_authority_status":
                "anchor_stale_pending_future_trade_financial_authority",
            "financial_snapshot_digest":
                _digest(financial_payload),
            "contract_snapshot_digest":
                _digest(contract_payload),
        },
    )

    if not _active_surfaces_are_empty(state_candidate):
        raise SeasonBoundaryFinancialRightsRolloverError(
            "Old offseason financial/rights surfaces remained active."
        )

    trade_digest_after = _trade_financials_digest(trade_state)
    if trade_digest_after != trade_digest_before:
        raise SeasonBoundaryFinancialRightsRolloverError(
            "Financial/rights rollover mutated TradeState.team_financials."
        )

    return (
        state_candidate,
        SeasonBoundaryFinancialRightsRolloverResult(
            version=
                SEASON_BOUNDARY_FINANCIAL_RIGHTS_ROLLOVER_VERSION,
            source_season=source,
            target_season=target,
            applied=True,
            archived_surface_count=len(ARCHIVED_SURFACES),
            archived_row_count=sum(row_counts.values()),
            archived_surface_digests=surface_digests,
            financial_snapshot_digest=_digest(
                financial_payload
            ),
            contract_snapshot_digest=_digest(
                contract_payload
            ),
            financial_team_count=team_count,
            contract_profile_count=profile_count,
            trade_financials_digest_before=
                trade_digest_before,
            trade_financials_digest_after=
                trade_digest_after,
        ),
    )
