from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from freeform_trade_machine_engine_v3 import normalize_status, normalize_team
from franchise_live_asset_ledger_v1 import FranchiseAssetLedger, build_live_asset_ledger


DRAFT_RIGHT_BRIDGE_VERSION = (
    "franchise-draft-right-stepien-bridge-v1.1-transaction-ownership-2026-08-12"
)


@dataclass(frozen=True)
class FranchiseDraftRightCheck:
    status: str
    code: str
    message: str
    team: str = ""
    asset_id: str = ""


@dataclass(frozen=True)
class FranchiseDraftRightProfile:
    asset_id: str
    draft_year: int
    round_number: int
    origin_team: str
    current_owner: str
    asset_type: str
    status: str
    bridge_ready: bool
    package_stepien_required: bool
    modeled_future_asset: bool
    reason: str


@dataclass(frozen=True)
class FranchiseDraftRightTradeEvaluation:
    version: str
    season_label: str
    status: str
    team_a: str
    team_b: str
    side_a_asset_ids: tuple[str, ...]
    side_b_asset_ids: tuple[str, ...]
    checks: tuple[FranchiseDraftRightCheck, ...] = field(default_factory=tuple)
    profiles: tuple[FranchiseDraftRightProfile, ...] = field(default_factory=tuple)
    retained_first_counts_after: dict[str, dict[int, int]] = field(default_factory=dict)


_PRIORITY = {"pass": 0, "manual_review": 1, "blocked": 2}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _status(value: Any) -> str:
    text = _clean(getattr(value, "value", value)).lower()
    return text if text in _PRIORITY else "manual_review"


def _combine(statuses: Iterable[str]) -> str:
    values = [_status(value) for value in statuses]
    if not values:
        return "pass"
    return max(values, key=lambda item: _PRIORITY[item])


def _season_label(state: Any) -> str:
    return _clean(getattr(getattr(state, "settings", None), "season_label", ""))


def _row_lookup(ledger: FranchiseAssetLedger) -> dict[str, dict[str, Any]]:
    return {str(row.get("asset_id")): dict(row) for row in ledger.draft_rows}


def _is_clear_text(value: Any, allowed: set[str]) -> bool:
    return normalize_status(value) in allowed


def _verified_first_is_clean(row: dict[str, Any]) -> bool:
    return all(
        [
            _is_clear_text(row.get("protection"), {"", "none", "unprotected", "not_applicable"}),
            _is_clear_text(row.get("swap_status"), {"", "none", "not_applicable"}),
            _is_clear_text(row.get("encumbrance"), {"", "clear", "none", "not_applicable"}),
            _is_clear_text(row.get("stepien_status"), {"available"}),
        ]
    )


def profile_draft_right(row: dict[str, Any]) -> FranchiseDraftRightProfile:
    asset_id = _clean(row.get("asset_id"))
    year = int(row.get("draft_year") or 0)
    round_number = int(row.get("round") or 0)
    origin = normalize_team(row.get("origin_team"))
    owner = normalize_team(row.get("current_owner"))
    asset_type = _clean(row.get("asset_type"))

    if not asset_id or year <= 0 or round_number not in {1, 2} or not owner:
        return FranchiseDraftRightProfile(
            asset_id=asset_id,
            draft_year=year,
            round_number=round_number,
            origin_team=origin,
            current_owner=owner,
            asset_type=asset_type,
            status="blocked",
            bridge_ready=False,
            package_stepien_required=False,
            modeled_future_asset=False,
            reason="Draft asset is missing a stable ID, owner, draft year, or supported round.",
        )

    if asset_type == "canonical_trade_right":
        ready = bool(row.get("engine_ready"))
        return FranchiseDraftRightProfile(
            asset_id=asset_id,
            draft_year=year,
            round_number=round_number,
            origin_team=origin,
            current_owner=owner,
            asset_type=asset_type,
            status="pass" if ready else "manual_review",
            bridge_ready=ready,
            package_stepien_required=bool(round_number == 1),
            modeled_future_asset=False,
            reason=(
                "Canonical right is already engine-ready; franchise package Stepien still applies."
                if ready
                else _clean(row.get("manual_review_reason"))
                or "Canonical right is not released by the existing right-legality evidence."
            ),
        )

    if asset_type == "verified_stepien_physical_first":
        clean = _verified_first_is_clean(row)
        return FranchiseDraftRightProfile(
            asset_id=asset_id,
            draft_year=year,
            round_number=1,
            origin_team=origin,
            current_owner=owner,
            asset_type=asset_type,
            status="pass" if clean else "manual_review",
            bridge_ready=clean,
            package_stepien_required=True,
            modeled_future_asset=False,
            reason=(
                "Verified physical first has clean ownership, no active protection/swap/encumbrance flag, and is available in the Stepien calendar."
                if clean
                else _clean(row.get("manual_review_reason"))
                or "Verified first has a complex protection, swap, obligation, availability, or frozen-pick condition."
            ),
        )

    if asset_type == "procedural_future_own_pick":
        # These rows are created only beyond the authoritative first-round horizon
        # (or for unreconciled future seconds). In the franchise universe, a new
        # own pick is generated as a clean future asset until a franchise transaction
        # changes its ownership or attaches a specific encumbrance.
        transactional_owner = bool(row.get("franchise_transactional_owner"))
        clean_owner = bool(
            origin
            and owner
            and (owner == origin or transactional_owner)
        )
        return FranchiseDraftRightProfile(
            asset_id=asset_id,
            draft_year=year,
            round_number=round_number,
            origin_team=origin,
            current_owner=owner,
            asset_type=asset_type,
            status="pass" if clean_owner else "manual_review",
            bridge_ready=clean_owner,
            package_stepien_required=bool(round_number == 1),
            modeled_future_asset=True,
            reason=(
                "Procedural future pick is a clean franchise-native asset whose current owner is established by committed franchise transaction history."
                if transactional_owner and clean_owner
                else (
                    "Procedural future own pick is activated as a clean franchise-native asset; future ownership becomes transactional after a committed trade."
                    if clean_owner
                    else "Procedural pick ownership is not backed by its origin team or committed franchise transaction history."
                )
            ),
        )

    return FranchiseDraftRightProfile(
        asset_id=asset_id,
        draft_year=year,
        round_number=round_number,
        origin_team=origin,
        current_owner=owner,
        asset_type=asset_type,
        status="manual_review",
        bridge_ready=False,
        package_stepien_required=bool(round_number == 1),
        modeled_future_asset=False,
        reason=f"Unsupported draft asset type: {asset_type or '<blank>'}.",
    )


def build_franchise_draft_right_profiles(
    ledger: FranchiseAssetLedger,
) -> tuple[FranchiseDraftRightProfile, ...]:
    return tuple(profile_draft_right(dict(row)) for row in ledger.draft_rows)


def _retained_first_counts(
    profiles: Iterable[FranchiseDraftRightProfile],
    *,
    outgoing_by_team: dict[str, set[str]] | None = None,
) -> dict[str, dict[int, int]]:
    outgoing_by_team = outgoing_by_team or {}
    result: dict[str, dict[int, int]] = {}
    for profile in profiles:
        if profile.round_number != 1:
            continue
        if not profile.bridge_ready:
            continue
        owner = normalize_team(profile.current_owner)
        if not owner:
            continue
        if profile.asset_id in outgoing_by_team.get(owner, set()):
            continue
        result.setdefault(owner, {})
        result[owner][profile.draft_year] = (
            result[owner].get(profile.draft_year, 0) + 1
        )
    return result


def _stepien_checks_for_team(
    *,
    team: str,
    ledger: FranchiseAssetLedger,
    profiles: tuple[FranchiseDraftRightProfile, ...],
    outgoing_ids: tuple[str, ...],
) -> tuple[list[FranchiseDraftRightCheck], dict[int, int]]:
    checks: list[FranchiseDraftRightCheck] = []
    resolved = normalize_team(team)
    outgoing = set(outgoing_ids)
    first_outgoing = {
        profile.asset_id
        for profile in profiles
        if profile.current_owner == resolved
        and profile.round_number == 1
        and profile.asset_id in outgoing
    }

    retained = _retained_first_counts(
        profiles,
        outgoing_by_team={resolved: first_outgoing},
    ).get(resolved, {})

    if not first_outgoing:
        checks.append(
            FranchiseDraftRightCheck(
                "pass",
                "stepien_not_applicable_no_first_outgoing",
                f"{resolved} is not sending a first-round pick, so Stepien is not triggered on this side.",
                resolved,
            )
        )
        return checks, retained

    years = list(range(int(ledger.next_draft_year), int(ledger.horizon_end_year) + 1))

    # If any year in the rolling horizon has unresolved first-round control,
    # a proposed first-round trade cannot be deterministically released.
    profile_by_year: dict[int, list[FranchiseDraftRightProfile]] = {}
    for profile in profiles:
        if profile.current_owner == resolved and profile.round_number == 1:
            profile_by_year.setdefault(profile.draft_year, []).append(profile)

    unresolved_years = []
    for year in years:
        candidates = profile_by_year.get(year, [])
        if candidates and not any(item.bridge_ready for item in candidates):
            unresolved_years.append(year)

    if unresolved_years:
        checks.append(
            FranchiseDraftRightCheck(
                "manual_review",
                "stepien_control_unresolved_in_horizon",
                f"{resolved} has unresolved first-round control in {', '.join(map(str, unresolved_years))}; package-level Stepien cannot be deterministically released.",
                resolved,
            )
        )
        return checks, retained

    violations = []
    for left, right in zip(years, years[1:]):
        if retained.get(left, 0) <= 0 and retained.get(right, 0) <= 0:
            violations.append((left, right))

    if violations:
        text = ", ".join(f"{a}-{b}" for a, b in violations)
        checks.append(
            FranchiseDraftRightCheck(
                "blocked",
                "stepien_consecutive_future_firsts_failed",
                f"{resolved} would be left without a controlled first-round pick in consecutive future drafts: {text}.",
                resolved,
            )
        )
    else:
        checks.append(
            FranchiseDraftRightCheck(
                "pass",
                "stepien_consecutive_future_firsts_preserved",
                f"{resolved} retains at least one first-round pick across every consecutive future-draft pair after the proposed outgoing rights.",
                resolved,
            )
        )
    return checks, retained


def evaluate_franchise_draft_right_trade(
    runtime: Any,
    state: Any,
    trade_state: Any,
    *,
    team_a: str,
    team_b: str,
    side_a_asset_ids: tuple[str, ...] = (),
    side_b_asset_ids: tuple[str, ...] = (),
    ledger: FranchiseAssetLedger | None = None,
) -> FranchiseDraftRightTradeEvaluation:
    del runtime  # The ledger has already reconciled canonical and Stepien source layers.
    resolved_a = normalize_team(team_a)
    resolved_b = normalize_team(team_b)
    live_ledger = ledger
    if live_ledger is None:
        # Caller normally supplies the ledger. Kept for direct validation use.
        raise RuntimeError(
            "Franchise Draft Right Bridge requires the already-built live asset ledger."
        )

    lookup = _row_lookup(live_ledger)
    all_profiles = build_franchise_draft_right_profiles(live_ledger)
    profile_lookup = {profile.asset_id: profile for profile in all_profiles}
    checks: list[FranchiseDraftRightCheck] = []
    selected_profiles: list[FranchiseDraftRightProfile] = []

    for team, asset_ids in (
        (resolved_a, tuple(side_a_asset_ids)),
        (resolved_b, tuple(side_b_asset_ids)),
    ):
        for asset_id in asset_ids:
            row = lookup.get(asset_id)
            if row is None:
                checks.append(
                    FranchiseDraftRightCheck(
                        "blocked",
                        "draft_asset_missing_from_live_ledger",
                        f"{asset_id} is not present in the live Draft Capital ledger.",
                        team,
                        asset_id,
                    )
                )
                continue
            if normalize_team(row.get("current_owner")) != team:
                checks.append(
                    FranchiseDraftRightCheck(
                        "blocked",
                        "draft_asset_owner_mismatch",
                        f"{row.get('display_name', asset_id)} is owned by {row.get('current_owner')}, not {team}.",
                        team,
                        asset_id,
                    )
                )
                continue
            profile = profile_lookup[asset_id]
            selected_profiles.append(profile)
            checks.append(
                FranchiseDraftRightCheck(
                    profile.status,
                    "draft_asset_bridge_profile",
                    profile.reason,
                    team,
                    asset_id,
                )
            )

    retained_after: dict[str, dict[int, int]] = {}
    if not any(check.status == "blocked" for check in checks):
        a_checks, a_retained = _stepien_checks_for_team(
            team=resolved_a,
            ledger=live_ledger,
            profiles=all_profiles,
            outgoing_ids=tuple(side_a_asset_ids),
        )
        b_checks, b_retained = _stepien_checks_for_team(
            team=resolved_b,
            ledger=live_ledger,
            profiles=all_profiles,
            outgoing_ids=tuple(side_b_asset_ids),
        )
        checks.extend(a_checks)
        checks.extend(b_checks)
        retained_after[resolved_a] = dict(sorted(a_retained.items()))
        retained_after[resolved_b] = dict(sorted(b_retained.items()))

    final_status = _combine(check.status for check in checks)
    return FranchiseDraftRightTradeEvaluation(
        version=DRAFT_RIGHT_BRIDGE_VERSION,
        season_label=_season_label(state),
        status=final_status,
        team_a=resolved_a,
        team_b=resolved_b,
        side_a_asset_ids=tuple(side_a_asset_ids),
        side_b_asset_ids=tuple(side_b_asset_ids),
        checks=tuple(checks),
        profiles=tuple(selected_profiles),
        retained_first_counts_after=copy.deepcopy(retained_after),
    )


def draft_right_trade_to_dict(
    evaluation: FranchiseDraftRightTradeEvaluation,
) -> dict[str, Any]:
    return asdict(evaluation)
