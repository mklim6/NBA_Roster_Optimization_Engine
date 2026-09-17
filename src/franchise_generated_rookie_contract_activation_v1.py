from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, ROUND_HALF_UP
import re
from typing import Any

from franchise_post_draft_first_round_pick_hold_bridge_v1 import (
    rookie_scale_schedule,
)

GENERATED_ROOKIE_CONTRACT_ACTIVATION_VERSION = (
    "franchise-generated-rookie-contract-activation-v1-2026-08-17"
)
ANCHOR_SEASON = "2026-27"
ANCHOR_SECOND_ROUND_TWO_YOS_MINIMUM = Decimal("2449421")
MODELED_ANNUAL_CAP_GROWTH = Decimal("0.08")
MAX_FUTURE_PROJECTION_YEARS = 10
FIRST_ROUND_OPTION_TYPE = "rookie_scale"
SECOND_ROUND_OPTION_TYPE = "second_round_exception_team_option"
ACTIVE_CONTRACT_STATUS = "under_contract"


class GeneratedRookieContractActivationError(RuntimeError):
    pass


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _season_start(label: str) -> int:
    match = re.fullmatch(r"(\d{4})-(\d{2}|\d{4})", _clean(label))
    if not match:
        raise GeneratedRookieContractActivationError(
            f"Unsupported season label: {label!r}."
        )
    start = int(match.group(1))
    suffix = match.group(2)
    end = int(suffix) if len(suffix) == 4 else (start // 100) * 100 + int(suffix)
    if end < start:
        end += 100
    if end != start + 1:
        raise GeneratedRookieContractActivationError(
            f"Season label is not a one-year NBA season: {label!r}."
        )
    return start


def _round_dollar(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def modeled_second_round_exception_first_year_salary(
    target_season: str,
) -> int:
    years = _season_start(target_season) - _season_start(ANCHOR_SEASON)
    if years < 0 or years > MAX_FUTURE_PROJECTION_YEARS:
        raise GeneratedRookieContractActivationError(
            "Generated rookie salary projection is outside the supported horizon."
        )
    amount = ANCHOR_SECOND_ROUND_TWO_YOS_MINIMUM
    for _ in range(years):
        amount *= Decimal("1") + MODELED_ANNUAL_CAP_GROWTH
    return _round_dollar(amount)


def _first_round_salary(
    *,
    target_season: str,
    draft_year: int,
    overall_pick: int,
) -> int:
    by_pick = {
        int(row["overall_pick"]): row
        for row in rookie_scale_schedule(target_season, draft_year)
    }
    row = by_pick.get(int(overall_pick))
    if row is None:
        raise GeneratedRookieContractActivationError(
            f"No rookie-scale row exists for overall pick {overall_pick}."
        )
    amount = _int(row.get("rookie_scale_cap_hold_amount"))
    if amount is None or amount <= 0:
        raise GeneratedRookieContractActivationError(
            f"Invalid first-round activation amount for pick {overall_pick}."
        )
    return amount



# GENERATED_ROOKIE_ACTIVATION_PEDIGREE_RECOVERY_V1
GENERATED_ROOKIE_PEDIGREE_RECOVERY_VERSION = (
    "generated-rookie-activation-pedigree-recovery-v1-2026-09-16"
)


def _generated_draft_pedigree_lookup(
    state: Any,
    *,
    target_season: str,
) -> dict[str, dict[str, Any]]:
    """Return authoritative generated-draft pedigree for one rookie class."""
    target = _clean(target_season)
    rows: dict[str, dict[str, Any]] = {}

    for draft in list(getattr(state, "franchise_draft_history_v1", ()) or ()):
        if not isinstance(draft, dict):
            continue
        archive_target = _clean(draft.get("target_season", ""))
        if archive_target != target:
            continue

        archive_year = _int(draft.get("draft_year"))
        for pick in list(draft.get("draft_order", ()) or ()):
            if not isinstance(pick, dict):
                continue
            player_id = _clean(pick.get("prospect_id", ""))
            if not player_id:
                continue

            rows[player_id] = {
                "target_season": archive_target,
                "draft_year": archive_year,
                "draft_round": _int(pick.get("round")),
                "draft_pick": _int(pick.get("overall_pick")),
                "draft_round_pick": _int(pick.get("round_pick")),
                "drafted_by": _clean(pick.get("owner_team", "")).upper(),
            }

    return rows


def _recover_generated_rookie_pedigree(
    state: Any,
    player: Any,
    *,
    target_season: str,
    pedigree_lookup: dict[str, dict[str, Any]],
) -> tuple[int | None, int | None, int | None]:
    """Restore draft pedigree erased from a generated rookie's live record.

    The durable completed-draft archive is authoritative for generated players.
    This mutates only the in-memory transition copy. It is persisted only if the
    existing atomic season-boundary commit succeeds.
    """
    player_id = _clean(getattr(player, "player_id", ""))
    pedigree = pedigree_lookup.get(player_id)

    live_year = _int(getattr(player, "draft_year", None))
    live_round = _int(getattr(player, "draft_round", None))
    live_pick = _int(getattr(player, "draft_pick", None))

    if pedigree is None:
        return live_year, live_round, live_pick

    archive_year = _int(pedigree.get("draft_year"))
    archive_round = _int(pedigree.get("draft_round"))
    archive_pick = _int(pedigree.get("draft_pick"))
    archive_round_pick = _int(pedigree.get("draft_round_pick"))
    archive_team = _clean(pedigree.get("drafted_by", "")).upper()

    # For generated players, the completed draft result outranks later generic
    # career-history enrichment. Restore missing or stale fields from it.
    if archive_year is not None:
        live_year = archive_year
        setattr(player, "draft_year", archive_year)
    if archive_round is not None:
        live_round = archive_round
        setattr(player, "draft_round", archive_round)
    if archive_pick is not None:
        live_pick = archive_pick
        setattr(player, "draft_pick", archive_pick)
    if archive_round_pick is not None:
        setattr(player, "draft_round_pick", archive_round_pick)
    if archive_team:
        setattr(player, "drafted_by", archive_team)

    if archive_year is not None:
        setattr(player, "draft_class_id", f"DRAFT-{archive_year}")
    setattr(
        player,
        "generated_rookie_pedigree_recovery_version_v1",
        GENERATED_ROOKIE_PEDIGREE_RECOVERY_VERSION,
    )

    return live_year, live_round, live_pick

def activate_generated_rookie_contracts(
    state: Any,
    target_season: str,
) -> int:
    target = _clean(target_season)
    target_start = _season_start(target)
    matched = 0
    pedigree_lookup = _generated_draft_pedigree_lookup(
        state,
        target_season=target,
    )

    for player in getattr(state, "players", {}).values():
        if not bool(getattr(player, "generated_prospect", False)):
            continue
        if _clean(getattr(player, "rookie_season", "")) != target:
            continue

        draft_year, draft_round, overall_pick = (
            _recover_generated_rookie_pedigree(
                state,
                player,
                target_season=target,
                pedigree_lookup=pedigree_lookup,
            )
        )
        contract = getattr(player, "contract", None)

        if draft_year != target_start:
            player_id = _clean(getattr(player, "player_id", ""))
            raise GeneratedRookieContractActivationError(
                "Generated rookie draft pedigree could not be reconciled: "
                f"player_id={player_id!r}, draft_year={draft_year!r}, "
                f"target={target!r}, archive_match={player_id in pedigree_lookup}."
            )
        if draft_round not in {1, 2}:
            raise GeneratedRookieContractActivationError(
                f"Unsupported draft round {draft_round!r}."
            )
        if overall_pick is None or not 1 <= overall_pick <= 60:
            raise GeneratedRookieContractActivationError(
                f"Invalid overall pick {overall_pick!r}."
            )
        if contract is None:
            raise GeneratedRookieContractActivationError(
                "Generated rookie lacks ContractState."
            )

        status = _clean(getattr(contract, "status", "")).lower()
        if status == "rookie_scale_pending":
            if draft_round == 1:
                annual_salary = _first_round_salary(
                    target_season=target,
                    draft_year=draft_year,
                    overall_pick=overall_pick,
                )
                option_type = FIRST_ROUND_OPTION_TYPE
                model = "first_round_120_percent_rookie_scale"
                source = "post_draft_first_round_pick_hold_bridge_v1"
            else:
                annual_salary = modeled_second_round_exception_first_year_salary(
                    target
                )
                option_type = SECOND_ROUND_OPTION_TYPE
                model = "second_round_pick_exception_3_plus_1_modeled"
                source = (
                    "project_2026_27_two_yos_minimum_plus_"
                    "franchise_future_economy_growth"
                )

            player.contract = replace(
                contract,
                status=ACTIVE_CONTRACT_STATUS,
                salary=float(annual_salary),
                years_remaining=4,
                option_type=option_type,
                guaranteed=True,
            )
            setattr(player, "rookie_contract_model_v1", model)
            setattr(player, "rookie_contract_salary_source_v1", source)
            setattr(player, "rookie_contract_activation_season_v1", target)
            setattr(
                player,
                "rookie_contract_activation_version_v1",
                GENERATED_ROOKIE_CONTRACT_ACTIVATION_VERSION,
            )
        else:
            live = getattr(player, "contract", None)
            years = _int(getattr(live, "years_remaining", None))
            try:
                salary = float(getattr(live, "salary", None))
            except (TypeError, ValueError):
                salary = -1.0
            if (
                _clean(getattr(live, "status", "")).lower()
                != ACTIVE_CONTRACT_STATUS
                or years is None
                or years <= 0
                or salary <= 0.0
            ):
                raise GeneratedRookieContractActivationError(
                    "Already-activated generated rookie has unusable contract state."
                )

        player.synthetic = False
        player.roster_status = "active_roster"
        setattr(player, "rookie_eligible", True)
        setattr(player, "years_of_service", 0)
        matched += 1

    return matched
