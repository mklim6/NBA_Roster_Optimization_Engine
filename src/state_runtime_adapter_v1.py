from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import (  # noqa: E402
    RuntimeData,
    Status,
    TradeRequest,
    TradeSideRequest,
    dataframe_index,
    deterministic_owner_team,
    evaluate_trade,
    load_runtime_data,
    normalize_player_id,
    normalize_status,
    normalize_team,
    parse_rounds,
    parse_tokens,
    source_asset_round,
    to_bool,
)
from mutable_league_state_v1 import (  # noqa: E402
    LeagueState,
    StateMutationError,
    apply_passed_trade,
    create_league_state,
    find_pass_player_trade,
    reset_league_state,
    synthetic_pick_evaluation,
    undo_last_trade,
    validate_state,
)


ADAPTER_VERSION = "state-runtime-adapter-v1-2026-08-07"
SELF_TEST_REPORT = (
    OUTPUTS / "state_runtime_adapter_v1_self_test.json"
)


class StateRuntimeAdapterError(RuntimeError):
    """Raised when mutable state cannot be adapted safely."""


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def update_player_team_column(
    frame: pd.DataFrame,
    state: LeagueState,
) -> pd.DataFrame:
    result = frame.copy(deep=True)

    if (
        "player_id" not in result.columns
        or "current_team_2026_27" not in result.columns
    ):
        return result

    normalized_ids = result["player_id"].map(
        normalize_player_id
    )
    mapped = normalized_ids.map(
        state.player_team_by_id
    )
    result.loc[
        mapped.notna(),
        "current_team_2026_27",
    ] = mapped.loc[mapped.notna()]

    return result


def update_pick_team_column(
    frame: pd.DataFrame,
    state: LeagueState,
) -> pd.DataFrame:
    result = frame.copy(deep=True)

    if (
        "future_pick_right_id" not in result.columns
        or "candidate_team" not in result.columns
    ):
        return result

    right_ids = (
        result["future_pick_right_id"]
        .astype(str)
        .str.strip()
    )
    mapped = right_ids.map(state.pick_team_by_id)
    result.loc[
        mapped.notna(),
        "candidate_team",
    ] = mapped.loc[mapped.notna()]

    return result


def update_team_financial_columns(
    frame: pd.DataFrame,
    state: LeagueState,
) -> pd.DataFrame:
    result = frame.copy(deep=True)

    if "team_abbreviation" not in result.columns:
        return result

    teams = result["team_abbreviation"].map(
        normalize_team
    )

    field_map = {
        "verified_team_salary_value": "team_salary",
        "verified_apron_team_salary_value": (
            "apron_salary"
        ),
        "standard_contract_count": (
            "standard_contract_count"
        ),
        "two_way_contract_count": (
            "two_way_contract_count"
        ),
        "hard_cap_active": "hard_cap_active",
        "hard_cap_level": "hard_cap_level",
    }

    for column, attribute in field_map.items():
        if column not in result.columns:
            continue

        values = teams.map(
            lambda team: (
                getattr(
                    state.team_financials[team],
                    attribute,
                )
                if team in state.team_financials
                else None
            )
        )
        result.loc[values.notna(), column] = (
            values.loc[values.notna()]
        )

    return result


def mark_acquired_player_restrictions(
    player_cba: pd.DataFrame,
    state: LeagueState,
) -> pd.DataFrame:
    result = player_cba.copy(deep=True)

    if (
        "player_id" not in result.columns
        or not state.acquired_player_ids
    ):
        return result

    acquired = result["player_id"].map(
        normalize_player_id
    ).isin(state.acquired_player_ids)

    if "aggregation_restricted_on_trade_date" in result.columns:
        result.loc[
            acquired,
            "aggregation_restricted_on_trade_date",
        ] = True

    if "player_cba_evidence_determination" in result.columns:
        current = (
            result.loc[
                acquired,
                "player_cba_evidence_determination",
            ]
            .astype(str)
            .str.strip()
            .str.lower()
        )
        promote = current.eq("verified_clear")
        result.loc[
            current.index[promote],
            "player_cba_evidence_determination",
        ] = "verified_with_conditions"

    return result


def changed_pick_owners(
    state: LeagueState,
) -> dict[str, tuple[str, str]]:
    if state.initial_snapshot is None:
        raise StateRuntimeAdapterError(
            "Mutable league state is missing its initial snapshot."
        )

    changed: dict[str, tuple[str, str]] = {}

    for pick_right_id, current_owner in (
        state.pick_team_by_id.items()
    ):
        initial_owner = (
            state.initial_snapshot.pick_team_by_id.get(
                pick_right_id
            )
        )
        if initial_owner is None:
            raise StateRuntimeAdapterError(
                f"Draft right {pick_right_id} did not exist "
                "in the initial state."
            )

        if current_owner != initial_owner:
            changed[pick_right_id] = (
                initial_owner,
                current_owner,
            )

    return changed


def first_round_source_ids(
    right: dict[str, Any],
) -> list[str]:
    if 1 not in parse_rounds(right.get("round_numbers")):
        return []

    return [
        source_id
        for source_id in parse_tokens(
            right.get("source_assets")
        )
        if source_asset_round(source_id) != 2
    ]


def apply_stepien_owner_overrides(
    stepien: pd.DataFrame,
    base_runtime: RuntimeData,
    state: LeagueState,
) -> pd.DataFrame:
    result = stepien.copy(deep=True)
    changed = changed_pick_owners(state)

    if not changed:
        return result

    required = {
        "team_abbreviation",
        "own_first_round_source_asset_id",
        "own_first_round_current_owner_team",
        "deterministic_first_round_availability",
        "own_first_round_control_status",
        "own_first_round_outgoing_obligation_status",
        "own_first_round_swap_status",
        "own_first_round_protection_status",
    }
    missing = sorted(required.difference(result.columns))
    if missing:
        raise StateRuntimeAdapterError(
            "The Stepien calendar is missing required columns: "
            + ", ".join(missing)
        )

    known_teams = set(
        result["team_abbreviation"]
        .map(normalize_team)
        .unique()
    )

    for pick_right_id, (
        initial_owner,
        current_owner,
    ) in changed.items():
        right = base_runtime.pick_by_id.get(pick_right_id)
        if right is None:
            raise StateRuntimeAdapterError(
                f"Draft right {pick_right_id} is missing "
                "from the base runtime."
            )

        source_ids = first_round_source_ids(right)
        if not source_ids:
            continue

        if len(source_ids) != 1:
            raise StateRuntimeAdapterError(
                f"Draft right {pick_right_id} uses "
                f"{len(source_ids)} first-round source assets. "
                "V1 only mutates exactly mapped single-source "
                "first-round rights."
            )

        source_id = source_ids[0]
        matching = (
            result[
                "own_first_round_source_asset_id"
            ]
            .astype(str)
            .str.strip()
            .eq(source_id)
        )
        indices = result.index[matching].tolist()

        if len(indices) != 1:
            raise StateRuntimeAdapterError(
                f"Draft right {pick_right_id} maps to "
                f"{len(indices)} Stepien rows for source "
                f"{source_id}; exactly one is required."
            )

        index = indices[0]
        original_row = result.loc[index].copy()
        deterministic_owner = deterministic_owner_team(
            original_row,
            known_teams,
        )

        if deterministic_owner != initial_owner:
            raise StateRuntimeAdapterError(
                f"Draft right {pick_right_id} was initially "
                f"assigned to {initial_owner}, but its exact "
                f"Stepien source resolves to "
                f"{deterministic_owner or '<unknown>'}."
            )

        origin_team = normalize_team(
            original_row.get("team_abbreviation")
        )

        result.at[
            index,
            "own_first_round_current_owner_team",
        ] = current_owner

        if current_owner == origin_team:
            result.at[
                index,
                "deterministic_first_round_availability",
            ] = "available"
        else:
            result.at[
                index,
                "deterministic_first_round_availability",
            ] = "not_available"
            result.at[
                index,
                "own_first_round_control_status",
            ] = "owed_out"
            result.at[
                index,
                (
                    "own_first_round_"
                    "outgoing_obligation_status"
                ),
            ] = "active"
            result.at[
                index,
                "own_first_round_swap_status",
            ] = "none"
            result.at[
                index,
                "own_first_round_protection_status",
            ] = "unprotected"

        observed_owner = deterministic_owner_team(
            result.loc[index],
            known_teams,
        )
        if observed_owner != current_owner:
            raise StateRuntimeAdapterError(
                f"Stepien owner override for "
                f"{pick_right_id} resolved to "
                f"{observed_owner or '<unknown>'}, "
                f"not {current_owner}."
            )

    return result


def build_state_runtime(
    base_runtime: RuntimeData,
    state: LeagueState,
) -> RuntimeData:
    validate_state(state, base_runtime)

    # TRADE_MACHINE_CANONICAL_HYDRATION_REPAIR_V1:
    # Capture immutable source ownership before adapting it. A rebased
    # LeagueState.initial_snapshot is valid durable state and is not evidence
    # that base_runtime itself was mutated.
    base_player_teams_before = {
        player_id: normalize_team(
            record.get("current_team_2026_27")
        )
        for player_id, record in base_runtime.trade_by_id.items()
    }

    trade_pool = update_player_team_column(
        base_runtime.trade_pool,
        state,
    )
    financial = update_player_team_column(
        base_runtime.financial,
        state,
    )
    market = update_player_team_column(
        base_runtime.market,
        state,
    )
    ratings = update_player_team_column(
        base_runtime.ratings,
        state,
    )
    player_cba = update_player_team_column(
        base_runtime.player_cba,
        state,
    )
    player_cba = mark_acquired_player_restrictions(
        player_cba,
        state,
    )

    team_salary = update_team_financial_columns(
        base_runtime.team_salary,
        state,
    )
    team_cba = update_team_financial_columns(
        base_runtime.team_cba,
        state,
    )

    picks = update_pick_team_column(
        base_runtime.picks,
        state,
    )
    right_legality = update_pick_team_column(
        base_runtime.right_legality,
        state,
    )
    stepien = apply_stepien_owner_overrides(
        base_runtime.stepien,
        base_runtime,
        state,
    )

    runtime = RuntimeData(
        trade_pool=trade_pool,
        financial=financial,
        market=market,
        team_salary=team_salary,
        team_cba=team_cba,
        picks=picks,
        stepien=stepien,
        ratings=ratings,
        player_cba=player_cba,
        right_legality=right_legality,
        rules=copy.deepcopy(base_runtime.rules),
        trade_by_id=dataframe_index(
            trade_pool,
            "player_id",
        ),
        financial_by_id=dataframe_index(
            financial,
            "player_id",
        ),
        market_by_id=dataframe_index(
            market,
            "player_id",
        ),
        ratings_by_id=dataframe_index(
            ratings,
            "player_id",
        ),
        player_cba_by_id=dataframe_index(
            player_cba,
            "player_id",
        ),
        team_salary_by_team=dataframe_index(
            team_salary,
            "team_abbreviation",
        ),
        team_cba_by_team=dataframe_index(
            team_cba,
            "team_abbreviation",
        ),
        pick_by_id=dataframe_index(
            picks,
            "future_pick_right_id",
        ),
        right_legality_by_id=dataframe_index(
            right_legality,
            "future_pick_right_id",
        ),
    )

    validate_state_runtime(
        base_runtime,
        runtime,
        state,
        expected_base_player_teams=base_player_teams_before,
    )
    return runtime


def validate_state_runtime(
    base_runtime: RuntimeData,
    runtime: RuntimeData,
    state: LeagueState,
    *,
    expected_base_player_teams: dict[str, str] | None = None,
) -> dict[str, bool]:
    if expected_base_player_teams is None:
        expected_base_player_teams = {
            player_id: normalize_team(
                record.get("current_team_2026_27")
            )
            for player_id, record in base_runtime.trade_by_id.items()
        }

    checks = {
        "trade_pool_player_ownership_matches_state": all(
            normalize_team(
                record.get("current_team_2026_27")
            )
            == state.player_team_by_id[player_id]
            for player_id, record in (
                runtime.trade_by_id.items()
            )
        ),
        "financial_player_ownership_matches_state": all(
            normalize_team(
                record.get("current_team_2026_27")
            )
            == state.player_team_by_id[player_id]
            for player_id, record in (
                runtime.financial_by_id.items()
            )
        ),
        "pick_ownership_matches_state": all(
            normalize_team(record.get("candidate_team"))
            == state.pick_team_by_id[pick_right_id]
            for pick_right_id, record in (
                runtime.pick_by_id.items()
            )
        ),
        "right_legality_ownership_matches_state": all(
            normalize_team(record.get("candidate_team"))
            == state.pick_team_by_id[pick_right_id]
            for pick_right_id, record in (
                runtime.right_legality_by_id.items()
            )
            if pick_right_id in state.pick_team_by_id
        ),
        "team_salary_matches_state": all(
            (
                state.team_financials[team].team_salary
                is None
                or abs(
                    float(
                        runtime.team_cba_by_team[team][
                            "verified_team_salary_value"
                        ]
                    )
                    - float(
                        state.team_financials[
                            team
                        ].team_salary
                    )
                )
                <= 0.01
            )
            for team in state.team_financials
        ),
        "team_apron_salary_matches_state": all(
            (
                state.team_financials[team].apron_salary
                is None
                or abs(
                    float(
                        runtime.team_cba_by_team[team][
                            (
                                "verified_apron_"
                                "team_salary_value"
                            )
                        ]
                    )
                    - float(
                        state.team_financials[
                            team
                        ].apron_salary
                    )
                )
                <= 0.01
            )
            for team in state.team_financials
        ),
        "base_runtime_not_mutated": (
            {
                player_id: normalize_team(
                    record.get("current_team_2026_27")
                )
                for player_id, record
                in base_runtime.trade_by_id.items()
            }
            == expected_base_player_teams
        ),
    }

    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]
    if failed:
        raise StateRuntimeAdapterError(
            "State-runtime validation failed: "
            + ", ".join(failed)
        )

    return checks


def request_check_codes(result: Any) -> set[str]:
    return {
        check.code
        for check in [
            *result.checks,
            *result.side_a.checks,
            *result.side_b.checks,
        ]
    }


def find_two_second_round_rights(
    runtime: RuntimeData,
) -> tuple[dict[str, Any], dict[str, Any]]:
    records = runtime.picks.loc[
        runtime.picks[
            "standalone_trade_asset_flag"
        ].map(to_bool).eq(True)
    ].to_dict(orient="records")

    second_round = [
        record
        for record in records
        if 1 not in parse_rounds(
            record.get("round_numbers")
        )
        and 2 in parse_rounds(
            record.get("round_numbers")
        )
    ]

    for first in second_round:
        first_team = normalize_team(
            first.get("candidate_team")
        )

        for second in second_round:
            second_team = normalize_team(
                second.get("candidate_team")
            )
            if first_team and second_team != first_team:
                return first, second

    raise AssertionError(
        "Could not find two standalone second-round rights "
        "owned by different teams."
    )


def run_self_test() -> dict[str, Any]:
    base_runtime = load_runtime_data()
    state = create_league_state(base_runtime)
    initial_runtime = build_state_runtime(
        base_runtime,
        state,
    )
    initial_checks = validate_state_runtime(
        base_runtime,
        initial_runtime,
        state,
    )

    player_request, player_result = (
        find_pass_player_trade(base_runtime)
    )
    team_a = normalize_team(
        player_request.side_a.team_abbreviation
    )
    team_b = normalize_team(
        player_request.side_b.team_abbreviation
    )
    player_a = normalize_player_id(
        player_request.side_a.player_ids[0]
    )
    player_b = normalize_player_id(
        player_request.side_b.player_ids[0]
    )

    apply_passed_trade(
        state,
        base_runtime,
        player_request,
        player_result,
    )
    adapted_after_player = build_state_runtime(
        base_runtime,
        state,
    )

    reverse_request = TradeRequest(
        side_a=TradeSideRequest(
            team_abbreviation=team_b,
            player_ids=(player_a,),
        ),
        side_b=TradeSideRequest(
            team_abbreviation=team_a,
            player_ids=(player_b,),
        ),
    )
    reverse_result = evaluate_trade(
        adapted_after_player,
        reverse_request,
    )
    reverse_codes = request_check_codes(reverse_result)

    old_owner_request = TradeRequest(
        side_a=TradeSideRequest(
            team_abbreviation=team_a,
            player_ids=(player_a,),
        ),
        side_b=TradeSideRequest(
            team_abbreviation=team_b,
            player_ids=(player_b,),
        ),
    )
    old_owner_result = evaluate_trade(
        adapted_after_player,
        old_owner_request,
    )
    old_owner_codes = request_check_codes(
        old_owner_result
    )

    player_checks = {
        "moved_player_a_visible_on_team_b": (
            normalize_team(
                adapted_after_player.trade_by_id[
                    player_a
                ].get("current_team_2026_27")
            )
            == team_b
        ),
        "moved_player_b_visible_on_team_a": (
            normalize_team(
                adapted_after_player.trade_by_id[
                    player_b
                ].get("current_team_2026_27")
            )
            == team_a
        ),
        "reverse_request_has_no_roster_mismatch": (
            "player_roster_mismatch"
            not in reverse_codes
        ),
        "old_owner_request_is_roster_mismatch": (
            "player_roster_mismatch"
            in old_owner_codes
        ),
        "acquired_player_a_is_aggregation_restricted": (
            to_bool(
                adapted_after_player.player_cba_by_id[
                    player_a
                ].get(
                    (
                        "aggregation_restricted_"
                        "on_trade_date"
                    )
                )
            )
            is True
        ),
        "team_a_salary_updated_in_runtime": (
            abs(
                float(
                    adapted_after_player.team_cba_by_team[
                        team_a
                    ][
                        "verified_team_salary_value"
                    ]
                )
                - float(
                    state.team_financials[
                        team_a
                    ].team_salary
                )
            )
            <= 0.01
        ),
        "team_b_salary_updated_in_runtime": (
            abs(
                float(
                    adapted_after_player.team_cba_by_team[
                        team_b
                    ][
                        "verified_team_salary_value"
                    ]
                )
                - float(
                    state.team_financials[
                        team_b
                    ].team_salary
                )
            )
            <= 0.01
        ),
    }

    undo_last_trade(state, base_runtime)
    adapted_after_undo = build_state_runtime(
        base_runtime,
        state,
    )
    undo_checks = {
        "player_a_restored_after_undo": (
            normalize_team(
                adapted_after_undo.trade_by_id[
                    player_a
                ].get("current_team_2026_27")
            )
            == team_a
        ),
        "player_b_restored_after_undo": (
            normalize_team(
                adapted_after_undo.trade_by_id[
                    player_b
                ].get("current_team_2026_27")
            )
            == team_b
        ),
        "acquired_player_set_restored_after_undo": (
            not state.acquired_player_ids
        ),
    }

    first, second = find_two_second_round_rights(
        base_runtime
    )
    pick_a = clean_text(
        first.get("future_pick_right_id")
    )
    pick_b = clean_text(
        second.get("future_pick_right_id")
    )
    pick_team_a = normalize_team(
        first.get("candidate_team")
    )
    pick_team_b = normalize_team(
        second.get("candidate_team")
    )

    pick_request = TradeRequest(
        side_a=TradeSideRequest(
            team_abbreviation=pick_team_a,
            pick_right_ids=(pick_a,),
        ),
        side_b=TradeSideRequest(
            team_abbreviation=pick_team_b,
            pick_right_ids=(pick_b,),
        ),
    )
    pick_evaluation = synthetic_pick_evaluation(
        state,
        pick_team_a,
        pick_team_b,
    )
    apply_passed_trade(
        state,
        base_runtime,
        pick_request,
        pick_evaluation,
    )
    adapted_after_pick = build_state_runtime(
        base_runtime,
        state,
    )

    reverse_pick_request = TradeRequest(
        side_a=TradeSideRequest(
            team_abbreviation=pick_team_b,
            pick_right_ids=(pick_a,),
        ),
        side_b=TradeSideRequest(
            team_abbreviation=pick_team_a,
            pick_right_ids=(pick_b,),
        ),
    )
    reverse_pick_result = evaluate_trade(
        adapted_after_pick,
        reverse_pick_request,
    )
    reverse_pick_codes = request_check_codes(
        reverse_pick_result
    )

    pick_checks = {
        "pick_a_visible_on_new_owner": (
            normalize_team(
                adapted_after_pick.pick_by_id[
                    pick_a
                ].get("candidate_team")
            )
            == pick_team_b
        ),
        "pick_b_visible_on_new_owner": (
            normalize_team(
                adapted_after_pick.pick_by_id[
                    pick_b
                ].get("candidate_team")
            )
            == pick_team_a
        ),
        "right_legality_a_visible_on_new_owner": (
            normalize_team(
                adapted_after_pick.right_legality_by_id[
                    pick_a
                ].get("candidate_team")
            )
            == pick_team_b
        ),
        "reverse_pick_request_has_no_ownership_mismatch": (
            "pick_ownership_mismatch"
            not in reverse_pick_codes
        ),
    }

    reset_league_state(state, base_runtime)
    adapted_after_reset = build_state_runtime(
        base_runtime,
        state,
    )
    reset_checks = {
        "player_a_original_after_reset": (
            normalize_team(
                adapted_after_reset.trade_by_id[
                    player_a
                ].get("current_team_2026_27")
            )
            == team_a
        ),
        "pick_a_original_after_reset": (
            normalize_team(
                adapted_after_reset.pick_by_id[
                    pick_a
                ].get("candidate_team")
            )
            == pick_team_a
        ),
        "state_runtime_valid_after_reset": all(
            validate_state_runtime(
                base_runtime,
                adapted_after_reset,
                state,
            ).values()
        ),
    }

    checks = {
        **{
            f"initial_{name}": passed
            for name, passed in initial_checks.items()
        },
        **player_checks,
        **undo_checks,
        **pick_checks,
        **reset_checks,
    }
    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]

    report = {
        "script": ADAPTER_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "player_trade_team_a": team_a,
            "player_trade_team_b": team_b,
            "player_a": player_a,
            "player_b": player_b,
            "second_round_pick_a": pick_a,
            "second_round_pick_b": pick_b,
            "reverse_player_result": (
                reverse_result.status.value
            ),
            "reverse_pick_result": (
                reverse_pick_result.status.value
            ),
            "state_revision_after_reset": (
                state.state_revision
            ),
        },
        "passed": not failed,
    }

    OUTPUTS.mkdir(parents=True, exist_ok=True)
    SELF_TEST_REPORT.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    if failed:
        raise AssertionError(
            "State-runtime adapter V1 self-test failed: "
            + ", ".join(failed)
        )

    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    args = parser.parse_args()

    if args.self_test:
        report = run_self_test()
        print(json.dumps(report, indent=2))
        print(
            "\nSTATE RUNTIME ADAPTER V1 SELF-TEST PASSED"
        )
        return 0

    base_runtime = load_runtime_data()
    state = create_league_state(base_runtime)
    runtime = build_state_runtime(
        base_runtime,
        state,
    )

    print(
        json.dumps(
            {
                "script": ADAPTER_VERSION,
                "state_revision": state.state_revision,
                "trade_pool_players": len(
                    runtime.trade_by_id
                ),
                "financial_players": len(
                    runtime.financial_by_id
                ),
                "draft_rights": len(
                    runtime.pick_by_id
                ),
                "teams": len(
                    runtime.team_cba_by_team
                ),
                "status": "initialized",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
