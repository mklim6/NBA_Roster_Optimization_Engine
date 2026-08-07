from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"
PAGES = ROOT / "pages"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import (  # noqa: E402
    RuntimeData,
    Status,
    TradeRequest,
    TradeSideRequest,
    evaluate_trade,
    load_runtime_data,
    normalize_player_id,
    normalize_status,
    normalize_team,
    parse_rounds,
    split_player_ids,
    to_bool,
    to_float,
)
from mutable_league_state_v1 import (  # noqa: E402
    LeagueState,
    StateMutationError,
    apply_passed_trade,
    create_league_state,
    reset_league_state,
    synthetic_pick_evaluation,
    undo_last_trade,
    validate_state,
)
from state_runtime_adapter_v1 import (  # noqa: E402
    StateRuntimeAdapterError,
    build_state_runtime,
    validate_state_runtime,
)


VALIDATOR_VERSION = (
    "mutable-league-state-integration-v1-2026-08-07"
)
REPORT_PATH = (
    OUTPUTS
    / "mutable_league_state_integration_validation_v1.json"
)
CASE_PATH = (
    OUTPUTS
    / "mutable_league_state_integration_cases_v1.csv"
)
V9_PATH = (
    OUTPUTS
    / (
        "one_for_one_mixed_player_pick_candidates_"
        "2026_27_v9_final_full_cba_evaluated.parquet"
    )
)


class IntegrationValidationError(RuntimeError):
    """Raised when the connected mutable-state suite fails."""


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def money_close(
    left: float | None,
    right: float | None,
    tolerance: float = 0.01,
) -> bool:
    if left is None or right is None:
        return left is None and right is None

    return math.isclose(
        float(left),
        float(right),
        abs_tol=tolerance,
    )


def player_name(
    runtime: RuntimeData,
    player_id: str,
) -> str:
    return clean_text(
        runtime.trade_by_id.get(
            normalize_player_id(player_id),
            {},
        ).get("player_name", player_id)
    )


def request_check_codes(result: Any) -> set[str]:
    return {
        check.code
        for check in [
            *result.checks,
            *result.side_a.checks,
            *result.side_b.checks,
        ]
    }


def financial_signature(
    state: LeagueState,
) -> tuple[tuple[Any, ...], ...]:
    rows: list[tuple[Any, ...]] = []

    for team, value in sorted(
        state.team_financials.items()
    ):
        rows.append(
            (
                team,
                value.team_salary,
                value.apron_salary,
                value.standard_contract_count,
                value.two_way_contract_count,
                value.hard_cap_active,
                value.hard_cap_level,
            )
        )

    return tuple(rows)


def transaction_signature(
    state: LeagueState,
) -> tuple[tuple[Any, ...], ...]:
    return tuple(
        (
            record.transaction_id,
            record.state_revision,
            record.trade_date,
            record.team_a,
            record.team_b,
            record.team_a_player_ids,
            record.team_b_player_ids,
            record.team_a_pick_right_ids,
            record.team_b_pick_right_ids,
            record.evaluation_status,
        )
        for record in state.transaction_history
    )


def operational_signature(
    state: LeagueState,
) -> dict[str, Any]:
    return {
        "player_team_by_id": tuple(
            sorted(state.player_team_by_id.items())
        ),
        "pick_team_by_id": tuple(
            sorted(state.pick_team_by_id.items())
        ),
        "team_financials": financial_signature(state),
        "acquired_player_ids": tuple(
            sorted(state.acquired_player_ids)
        ),
        "transaction_history": transaction_signature(
            state
        ),
        "undo_depth": len(state.undo_stack),
    }


def base_runtime_signature(
    runtime: RuntimeData,
) -> dict[str, Any]:
    return {
        "players": tuple(
            sorted(
                (
                    player_id,
                    normalize_team(
                        record.get(
                            "current_team_2026_27"
                        )
                    ),
                )
                for player_id, record in (
                    runtime.trade_by_id.items()
                )
            )
        ),
        "picks": tuple(
            sorted(
                (
                    pick_right_id,
                    normalize_team(
                        record.get("candidate_team")
                    ),
                )
                for pick_right_id, record in (
                    runtime.pick_by_id.items()
                )
            )
        ),
        "team_cba": tuple(
            sorted(
                (
                    team,
                    to_float(
                        record.get(
                            "verified_team_salary_value"
                        )
                    ),
                    to_float(
                        record.get(
                            (
                                "verified_apron_"
                                "team_salary_value"
                            )
                        )
                    ),
                    clean_text(
                        record.get("hard_cap_level")
                    ).lower(),
                )
                for team, record in (
                    runtime.team_cba_by_team.items()
                )
            )
        ),
    }


def record_case(
    cases: list[dict[str, Any]],
    phase: str,
    case_name: str,
    passed: bool,
    details: str = "",
) -> None:
    cases.append(
        {
            "phase": phase,
            "case_name": case_name,
            "passed": bool(passed),
            "details": details,
        }
    )


def require_pass(
    result: Any,
    label: str,
) -> None:
    if result.status != Status.PASS:
        codes = "|".join(
            sorted(request_check_codes(result))
        )
        raise IntegrationValidationError(
            f"{label} did not receive PASS. "
            f"status={result.status.value}; codes={codes}"
        )


def player_salary(
    runtime: RuntimeData,
    player_id: str,
) -> float:
    record = runtime.trade_by_id.get(
        normalize_player_id(player_id),
        {},
    )
    return (
        to_float(record.get("trade_salary_2026_27"))
        or 0.0
    )


def player_team(
    runtime: RuntimeData,
    player_id: str,
) -> str:
    return normalize_team(
        runtime.trade_by_id[
            normalize_player_id(player_id)
        ].get("current_team_2026_27")
    )


def build_request(
    *,
    team_a: str,
    team_b: str,
    players_a: Iterable[str] = (),
    players_b: Iterable[str] = (),
    picks_a: Iterable[str] = (),
    picks_b: Iterable[str] = (),
) -> TradeRequest:
    return TradeRequest(
        side_a=TradeSideRequest(
            team_abbreviation=team_a,
            player_ids=tuple(
                normalize_player_id(value)
                for value in players_a
                if normalize_player_id(value)
            ),
            pick_right_ids=tuple(
                clean_text(value)
                for value in picks_a
                if clean_text(value)
            ),
        ),
        side_b=TradeSideRequest(
            team_abbreviation=team_b,
            player_ids=tuple(
                normalize_player_id(value)
                for value in players_b
                if normalize_player_id(value)
            ),
            pick_right_ids=tuple(
                clean_text(value)
                for value in picks_b
                if clean_text(value)
            ),
        ),
    )


def candidate_v9_requests(
    sample_size: int,
) -> list[TradeRequest]:
    if not V9_PATH.exists():
        raise FileNotFoundError(
            f"V9 candidate file is missing: {V9_PATH}"
        )

    columns = [
        "team_a",
        "team_b",
        "side_a_player_ids",
        "side_b_player_ids",
        "full_cba_evidence_complete",
        "player_cba_decisions_matched",
    ]
    frame = pd.read_parquet(
        V9_PATH,
        columns=columns,
    )
    frame = frame.loc[
        frame["full_cba_evidence_complete"].eq(True)
        & frame["player_cba_decisions_matched"].eq(True)
    ]

    if len(frame) > sample_size:
        frame = frame.sample(
            n=sample_size,
            random_state=20260807,
        )

    requests: list[TradeRequest] = []

    for row in frame.to_dict(orient="records"):
        requests.append(
            build_request(
                team_a=row["team_a"],
                team_b=row["team_b"],
                players_a=split_player_ids(
                    row["side_a_player_ids"]
                ),
                players_b=split_player_ids(
                    row["side_b_player_ids"]
                ),
            )
        )

    return requests


def connected_trade_candidates(
    runtime: RuntimeData,
    acquired_player_id: str,
    excluded_teams: set[str],
    maximum_candidates: int,
) -> list[str]:
    acquired_player_id = normalize_player_id(
        acquired_player_id
    )
    owner = player_team(runtime, acquired_player_id)
    target_salary = player_salary(
        runtime,
        acquired_player_id,
    )

    candidates: list[tuple[float, str]] = []

    for player_id, record in runtime.trade_by_id.items():
        player_id = normalize_player_id(player_id)
        if player_id == acquired_player_id:
            continue

        candidate_team = normalize_team(
            record.get("current_team_2026_27")
        )
        if (
            not candidate_team
            or candidate_team == owner
            or candidate_team in excluded_teams
        ):
            continue

        if player_id not in runtime.player_cba_by_id:
            continue

        determination = normalize_status(
            runtime.player_cba_by_id[
                player_id
            ].get("player_cba_evidence_determination")
        )
        if determination == "manual_review_required":
            continue

        salary = (
            to_float(
                record.get("trade_salary_2026_27")
            )
            or 0.0
        )
        candidates.append(
            (
                abs(salary - target_salary),
                player_id,
            )
        )

    candidates.sort(key=lambda item: item[0])
    return [
        player_id
        for _, player_id in candidates[
            :maximum_candidates
        ]
    ]


def find_connected_pass_trade(
    runtime: RuntimeData,
    acquired_player_ids: Iterable[str],
    original_teams: set[str],
    maximum_candidates: int,
) -> tuple[TradeRequest, Any]:
    for acquired_player_id in acquired_player_ids:
        acquired_player_id = normalize_player_id(
            acquired_player_id
        )
        owner = player_team(
            runtime,
            acquired_player_id,
        )

        candidates = connected_trade_candidates(
            runtime,
            acquired_player_id,
            excluded_teams=original_teams,
            maximum_candidates=maximum_candidates,
        )

        for candidate_id in candidates:
            candidate_team = player_team(
                runtime,
                candidate_id,
            )
            request = build_request(
                team_a=owner,
                team_b=candidate_team,
                players_a=(acquired_player_id,),
                players_b=(candidate_id,),
            )
            result = evaluate_trade(runtime, request)

            if result.status == Status.PASS:
                return request, result

    raise IntegrationValidationError(
        "Could not find a deterministic PASS trade that "
        "re-trades a newly acquired player to a third team."
    )


def find_player_trade_chain(
    base_runtime: RuntimeData,
    initial_state: LeagueState,
    first_trade_sample: int,
    connected_candidates: int,
) -> tuple[
    TradeRequest,
    Any,
    TradeRequest,
    Any,
]:
    requests = candidate_v9_requests(
        first_trade_sample
    )

    for first_request in requests:
        first_result = evaluate_trade(
            base_runtime,
            first_request,
        )
        if first_result.status != Status.PASS:
            continue

        trial_state = copy.deepcopy(initial_state)

        try:
            apply_passed_trade(
                trial_state,
                base_runtime,
                first_request,
                first_result,
            )
            trial_runtime = build_state_runtime(
                base_runtime,
                trial_state,
            )

            acquired_ids = [
                *first_request.side_a.player_ids,
                *first_request.side_b.player_ids,
            ]
            original_teams = {
                normalize_team(
                    first_request.side_a.team_abbreviation
                ),
                normalize_team(
                    first_request.side_b.team_abbreviation
                ),
            }
            second_request, second_result = (
                find_connected_pass_trade(
                    trial_runtime,
                    acquired_ids,
                    original_teams,
                    connected_candidates,
                )
            )
        except (
            StateMutationError,
            StateRuntimeAdapterError,
            IntegrationValidationError,
        ):
            continue

        return (
            first_request,
            first_result,
            second_request,
            second_result,
        )

    raise IntegrationValidationError(
        "No connected two-trade player chain was found "
        f"inside {len(requests)} V9 candidate requests."
    )


def is_second_round_only(
    record: dict[str, Any],
) -> bool:
    rounds = parse_rounds(
        record.get("round_numbers")
    )
    return 2 in rounds and 1 not in rounds


def legal_second_round_rights(
    runtime: RuntimeData,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    for pick_right_id, right in runtime.pick_by_id.items():
        if (
            to_bool(
                right.get(
                    "standalone_trade_asset_flag"
                )
            )
            is not True
            or not is_second_round_only(right)
        ):
            continue

        decision = runtime.right_legality_by_id.get(
            pick_right_id
        )
        if decision is None:
            continue

        determination = normalize_status(
            decision.get(
                "right_legality_determination"
            )
        )
        if determination not in {
            "legal",
            "legal_with_conditions",
        }:
            continue

        records.append(right)

    return records


def find_pass_pick_trade(
    runtime: RuntimeData,
    already_involved_teams: set[str],
    maximum_pairs: int,
) -> tuple[TradeRequest, Any]:
    rights = legal_second_round_rights(runtime)
    preferred: list[
        tuple[int, dict[str, Any], dict[str, Any]]
    ] = []

    for first in rights:
        first_team = normalize_team(
            first.get("candidate_team")
        )
        first_id = clean_text(
            first.get("future_pick_right_id")
        )

        for second in rights:
            second_team = normalize_team(
                second.get("candidate_team")
            )
            second_id = clean_text(
                second.get("future_pick_right_id")
            )

            if (
                not first_team
                or not second_team
                or first_team == second_team
                or first_id == second_id
            ):
                continue

            union = {
                first_team,
                second_team,
            }
            new_team_count = len(
                union.difference(
                    already_involved_teams
                )
            )
            touches_existing = bool(
                union.intersection(
                    already_involved_teams
                )
            )

            preference = (
                0
                if new_team_count >= 1
                and touches_existing
                else 1
                if new_team_count >= 1
                else 2
            )
            preferred.append(
                (preference, first, second)
            )

    preferred.sort(key=lambda item: item[0])

    checked = 0
    for _, first, second in preferred:
        if checked >= maximum_pairs:
            break

        checked += 1
        request = build_request(
            team_a=normalize_team(
                first.get("candidate_team")
            ),
            team_b=normalize_team(
                second.get("candidate_team")
            ),
            picks_a=(
                clean_text(
                    first.get(
                        "future_pick_right_id"
                    )
                ),
            ),
            picks_b=(
                clean_text(
                    second.get(
                        "future_pick_right_id"
                    )
                ),
            ),
        )
        result = evaluate_trade(runtime, request)

        if result.status == Status.PASS:
            teams = {
                normalize_team(
                    request.side_a.team_abbreviation
                ),
                normalize_team(
                    request.side_b.team_abbreviation
                ),
            }
            if teams.difference(
                already_involved_teams
            ):
                return request, result

    raise IntegrationValidationError(
        "Could not find a deterministic PASS second-round "
        f"pick trade after checking {checked} pairs."
    )


def team_financials_match_result(
    state: LeagueState,
    request: TradeRequest,
    result: Any,
) -> bool:
    team_a = normalize_team(
        request.side_a.team_abbreviation
    )
    team_b = normalize_team(
        request.side_b.team_abbreviation
    )

    return bool(
        money_close(
            state.team_financials[
                team_a
            ].team_salary,
            result.side_a.posttrade_team_salary,
        )
        and money_close(
            state.team_financials[
                team_a
            ].apron_salary,
            result.side_a.posttrade_apron_team_salary,
        )
        and money_close(
            state.team_financials[
                team_b
            ].team_salary,
            result.side_b.posttrade_team_salary,
        )
        and money_close(
            state.team_financials[
                team_b
            ].apron_salary,
            result.side_b.posttrade_apron_team_salary,
        )
    )


def assert_assets_moved(
    state: LeagueState,
    request: TradeRequest,
) -> dict[str, bool]:
    team_a = normalize_team(
        request.side_a.team_abbreviation
    )
    team_b = normalize_team(
        request.side_b.team_abbreviation
    )

    return {
        "side_a_players_moved": all(
            state.player_team_by_id[
                normalize_player_id(player_id)
            ]
            == team_b
            for player_id in request.side_a.player_ids
        ),
        "side_b_players_moved": all(
            state.player_team_by_id[
                normalize_player_id(player_id)
            ]
            == team_a
            for player_id in request.side_b.player_ids
        ),
        "side_a_picks_moved": all(
            state.pick_team_by_id[
                clean_text(pick_right_id)
            ]
            == team_b
            for pick_right_id in (
                request.side_a.pick_right_ids
            )
        ),
        "side_b_picks_moved": all(
            state.pick_team_by_id[
                clean_text(pick_right_id)
            ]
            == team_a
            for pick_right_id in (
                request.side_b.pick_right_ids
            )
        ),
    }


def ui_contract_checks() -> dict[str, bool]:
    page_path = PAGES / "3_Trade_Machine.py"
    if not page_path.exists():
        return {
            "ui_page_exists": False,
            "ui_stale_audit_guard_present": False,
            "ui_trial_state_validation_present": False,
            "ui_same_team_guard_present": False,
            "ui_revision_scoped_widget_keys_present": False,
        }

    text = page_path.read_text(encoding="utf-8")
    return {
        "ui_page_exists": True,
        "ui_stale_audit_guard_present": (
            "audited_revision"
            in text
            and (
                "league_state.state_revision"
                in text
            )
        ),
        "ui_trial_state_validation_present": (
            "trial_state = copy.deepcopy"
            in text
            and "build_state_runtime"
            in text
        ),
        "ui_same_team_guard_present": (
            "disabled=(team_a == team_b)"
            in text
        ),
        "ui_revision_scoped_widget_keys_present": (
            "r{league_state.state_revision}"
            in text
            and "players_side_a"
            in text
            and "players_side_b"
            in text
        ),
    }


def run_validation(
    *,
    first_trade_sample: int,
    connected_candidates: int,
    maximum_pick_pairs: int,
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []

    base_runtime = load_runtime_data()
    base_signature_before = base_runtime_signature(
        base_runtime
    )
    state = create_league_state(base_runtime)
    initial_signature = operational_signature(state)
    initial_revision = state.state_revision

    initial_runtime = build_state_runtime(
        base_runtime,
        state,
    )
    initial_state_checks = validate_state(
        state,
        base_runtime,
    )
    initial_runtime_checks = validate_state_runtime(
        base_runtime,
        initial_runtime,
        state,
    )

    for name, passed in {
        **{
            f"state_{key}": value
            for key, value in (
                initial_state_checks.items()
            )
        },
        **{
            f"runtime_{key}": value
            for key, value in (
                initial_runtime_checks.items()
            )
        },
    }.items():
        record_case(
            cases,
            "initialization",
            name,
            passed,
        )

    (
        trade_a_request,
        trade_a_result,
        trade_b_request,
        _trade_b_trial_result,
    ) = find_player_trade_chain(
        base_runtime,
        state,
        first_trade_sample,
        connected_candidates,
    )
    require_pass(trade_a_result, "Trade A")

    record_a = apply_passed_trade(
        state,
        initial_runtime,
        trade_a_request,
        trade_a_result,
    )
    runtime_after_a = build_state_runtime(
        base_runtime,
        state,
    )
    signature_after_a = operational_signature(state)
    revision_after_a = state.state_revision

    moved_a = assert_assets_moved(
        state,
        trade_a_request,
    )
    for name, passed in moved_a.items():
        record_case(
            cases,
            "trade_a",
            name,
            passed,
        )

    record_case(
        cases,
        "trade_a",
        "transaction_id_is_txn_0001",
        record_a.transaction_id == "TXN-0001",
        record_a.transaction_id,
    )
    record_case(
        cases,
        "trade_a",
        "revision_incremented_once",
        revision_after_a == initial_revision + 1,
        (
            f"initial={initial_revision}; "
            f"after={revision_after_a}"
        ),
    )
    record_case(
        cases,
        "trade_a",
        "financials_match_evaluation",
        team_financials_match_result(
            state,
            trade_a_request,
            trade_a_result,
        ),
    )
    record_case(
        cases,
        "trade_a",
        "state_and_runtime_validate",
        all(validate_state(
            state,
            base_runtime,
        ).values())
        and all(validate_state_runtime(
            base_runtime,
            runtime_after_a,
            state,
        ).values()),
    )

    trade_b_result = evaluate_trade(
        runtime_after_a,
        trade_b_request,
    )
    require_pass(trade_b_result, "Trade B")

    trade_b_player_ids = {
        *trade_b_request.side_a.player_ids,
        *trade_b_request.side_b.player_ids,
    }
    trade_a_player_ids = {
        *trade_a_request.side_a.player_ids,
        *trade_a_request.side_b.player_ids,
    }
    connected_ids = (
        trade_b_player_ids.intersection(
            trade_a_player_ids
        )
    )
    original_teams = {
        normalize_team(
            trade_a_request.side_a.team_abbreviation
        ),
        normalize_team(
            trade_a_request.side_b.team_abbreviation
        ),
    }
    trade_b_teams = {
        normalize_team(
            trade_b_request.side_a.team_abbreviation
        ),
        normalize_team(
            trade_b_request.side_b.team_abbreviation
        ),
    }

    record_case(
        cases,
        "trade_b",
        "uses_player_acquired_in_trade_a",
        bool(connected_ids),
        ",".join(sorted(connected_ids)),
    )
    record_case(
        cases,
        "trade_b",
        "introduces_third_team",
        bool(
            trade_b_teams.difference(
                original_teams
            )
        ),
        ",".join(sorted(trade_b_teams)),
    )

    record_b = apply_passed_trade(
        state,
        runtime_after_a,
        trade_b_request,
        trade_b_result,
    )
    runtime_after_b = build_state_runtime(
        base_runtime,
        state,
    )
    signature_after_b = operational_signature(state)
    revision_after_b = state.state_revision

    moved_b = assert_assets_moved(
        state,
        trade_b_request,
    )
    for name, passed in moved_b.items():
        record_case(
            cases,
            "trade_b",
            name,
            passed,
        )

    record_case(
        cases,
        "trade_b",
        "transaction_id_is_txn_0002",
        record_b.transaction_id == "TXN-0002",
        record_b.transaction_id,
    )
    record_case(
        cases,
        "trade_b",
        "revision_incremented_once",
        revision_after_b == revision_after_a + 1,
        (
            f"before={revision_after_a}; "
            f"after={revision_after_b}"
        ),
    )
    record_case(
        cases,
        "trade_b",
        "financials_match_evaluation",
        team_financials_match_result(
            state,
            trade_b_request,
            trade_b_result,
        ),
    )
    record_case(
        cases,
        "trade_b",
        "state_and_runtime_validate",
        all(validate_state(
            state,
            base_runtime,
        ).values())
        and all(validate_state_runtime(
            base_runtime,
            runtime_after_b,
            state,
        ).values()),
    )

    duplicate_before = operational_signature(state)
    duplicate_revision_before = state.state_revision
    duplicate_blocked = False
    duplicate_error = ""

    try:
        apply_passed_trade(
            state,
            runtime_after_b,
            trade_b_request,
            trade_b_result,
        )
    except StateMutationError as exc:
        duplicate_blocked = True
        duplicate_error = str(exc)

    record_case(
        cases,
        "guardrails",
        "duplicate_apply_is_blocked",
        duplicate_blocked,
        duplicate_error,
    )
    record_case(
        cases,
        "guardrails",
        "duplicate_apply_does_not_mutate_state",
        operational_signature(state)
        == duplicate_before
        and state.state_revision
        == duplicate_revision_before,
    )

    involved_teams = (
        original_teams.union(trade_b_teams)
    )
    trade_c_request, trade_c_result = (
        find_pass_pick_trade(
            runtime_after_b,
            involved_teams,
            maximum_pick_pairs,
        )
    )
    require_pass(trade_c_result, "Trade C")

    trade_c_teams = {
        normalize_team(
            trade_c_request.side_a.team_abbreviation
        ),
        normalize_team(
            trade_c_request.side_b.team_abbreviation
        ),
    }
    all_involved_teams = (
        involved_teams.union(trade_c_teams)
    )
    record_case(
        cases,
        "trade_c",
        "introduces_at_least_fourth_team",
        len(all_involved_teams) >= 4,
        ",".join(sorted(all_involved_teams)),
    )

    # The V3 engine can deterministically approve a pick-only
    # transaction without populating salary-side post-trade values.
    # A pick-only move does not change either team's salary or roster
    # counts, so use an explicit no-financial-change evaluation for the
    # state mutation after the real V3 legality result has passed.
    trade_c_state_evaluation = synthetic_pick_evaluation(
        state,
        normalize_team(
            trade_c_request.side_a.team_abbreviation
        ),
        normalize_team(
            trade_c_request.side_b.team_abbreviation
        ),
    )

    record_c = apply_passed_trade(
        state,
        runtime_after_b,
        trade_c_request,
        trade_c_state_evaluation,
    )
    runtime_after_c = build_state_runtime(
        base_runtime,
        state,
    )
    revision_after_c = state.state_revision

    moved_c = assert_assets_moved(
        state,
        trade_c_request,
    )
    for name, passed in moved_c.items():
        record_case(
            cases,
            "trade_c",
            name,
            passed,
        )

    record_case(
        cases,
        "trade_c",
        "transaction_id_is_txn_0003",
        record_c.transaction_id == "TXN-0003",
        record_c.transaction_id,
    )
    record_case(
        cases,
        "trade_c",
        "revision_incremented_once",
        revision_after_c == revision_after_b + 1,
        (
            f"before={revision_after_b}; "
            f"after={revision_after_c}"
        ),
    )
    record_case(
        cases,
        "trade_c",
        "state_and_runtime_validate",
        all(validate_state(
            state,
            base_runtime,
        ).values())
        and all(validate_state_runtime(
            base_runtime,
            runtime_after_c,
            state,
        ).values()),
    )
    record_case(
        cases,
        "trade_c",
        "three_transactions_recorded",
        len(state.transaction_history) == 3
        and len(state.undo_stack) == 3,
    )

    removed_c = undo_last_trade(
        state,
        base_runtime,
    )
    runtime_after_undo_c = build_state_runtime(
        base_runtime,
        state,
    )
    record_case(
        cases,
        "partial_undo",
        "latest_trade_removed_first",
        removed_c.transaction_id == "TXN-0003",
        removed_c.transaction_id,
    )
    record_case(
        cases,
        "partial_undo",
        "state_restored_exactly_to_after_trade_b",
        operational_signature(state)
        == signature_after_b,
    )
    record_case(
        cases,
        "partial_undo",
        "runtime_valid_after_first_undo",
        all(validate_state_runtime(
            base_runtime,
            runtime_after_undo_c,
            state,
        ).values()),
    )

    removed_b = undo_last_trade(
        state,
        base_runtime,
    )
    runtime_after_undo_b = build_state_runtime(
        base_runtime,
        state,
    )
    record_case(
        cases,
        "partial_undo",
        "second_undo_removes_trade_b",
        removed_b.transaction_id == "TXN-0002",
        removed_b.transaction_id,
    )
    record_case(
        cases,
        "partial_undo",
        "trade_a_remains_active",
        operational_signature(state)
        == signature_after_a,
    )
    record_case(
        cases,
        "partial_undo",
        "runtime_valid_with_only_trade_a_active",
        all(validate_state_runtime(
            base_runtime,
            runtime_after_undo_b,
            state,
        ).values()),
    )

    fresh_trade_b_result = evaluate_trade(
        runtime_after_undo_b,
        trade_b_request,
    )
    require_pass(
        fresh_trade_b_result,
        "Fresh Trade B after undo",
    )
    record_b_reapplied = apply_passed_trade(
        state,
        runtime_after_undo_b,
        trade_b_request,
        fresh_trade_b_result,
    )
    runtime_after_reapply = build_state_runtime(
        base_runtime,
        state,
    )
    record_case(
        cases,
        "reapply",
        "fresh_audit_can_reapply_trade_b",
        record_b_reapplied.transaction_id
        == "TXN-0002",
        record_b_reapplied.transaction_id,
    )
    record_case(
        cases,
        "reapply",
        "state_valid_after_reapply",
        all(validate_state(
            state,
            base_runtime,
        ).values())
        and all(validate_state_runtime(
            base_runtime,
            runtime_after_reapply,
            state,
        ).values()),
    )

    before_reset_revision = state.state_revision
    reset_league_state(
        state,
        base_runtime,
    )
    runtime_after_reset = build_state_runtime(
        base_runtime,
        state,
    )
    record_case(
        cases,
        "reset",
        "full_operational_state_restored",
        operational_signature(state)
        == initial_signature,
    )
    record_case(
        cases,
        "reset",
        "revision_increments_on_reset",
        state.state_revision
        == before_reset_revision + 1,
        (
            f"before={before_reset_revision}; "
            f"after={state.state_revision}"
        ),
    )
    record_case(
        cases,
        "reset",
        "history_and_undo_are_empty",
        not state.transaction_history
        and not state.undo_stack,
    )
    record_case(
        cases,
        "reset",
        "state_and_runtime_validate_after_reset",
        all(validate_state(
            state,
            base_runtime,
        ).values())
        and all(validate_state_runtime(
            base_runtime,
            runtime_after_reset,
            state,
        ).values()),
    )

    base_signature_after = base_runtime_signature(
        base_runtime
    )
    record_case(
        cases,
        "immutability",
        "base_runtime_never_mutated",
        base_signature_before
        == base_signature_after,
    )

    for name, passed in ui_contract_checks().items():
        record_case(
            cases,
            "ui_contract",
            name,
            passed,
        )

    failed_cases = [
        row
        for row in cases
        if not row["passed"]
    ]

    summary = {
        "first_player_trade": {
            "transaction_id": record_a.transaction_id,
            "team_a": normalize_team(
                trade_a_request.side_a.team_abbreviation
            ),
            "team_b": normalize_team(
                trade_a_request.side_b.team_abbreviation
            ),
            "team_a_players": [
                {
                    "player_id": player_id,
                    "player_name": player_name(
                        base_runtime,
                        player_id,
                    ),
                }
                for player_id in (
                    trade_a_request.side_a.player_ids
                )
            ],
            "team_b_players": [
                {
                    "player_id": player_id,
                    "player_name": player_name(
                        base_runtime,
                        player_id,
                    ),
                }
                for player_id in (
                    trade_a_request.side_b.player_ids
                )
            ],
        },
        "connected_player_trade": {
            "transaction_id": record_b.transaction_id,
            "team_a": normalize_team(
                trade_b_request.side_a.team_abbreviation
            ),
            "team_b": normalize_team(
                trade_b_request.side_b.team_abbreviation
            ),
            "connected_player_ids": sorted(
                connected_ids
            ),
        },
        "pick_trade": {
            "transaction_id": record_c.transaction_id,
            "team_a": normalize_team(
                trade_c_request.side_a.team_abbreviation
            ),
            "team_b": normalize_team(
                trade_c_request.side_b.team_abbreviation
            ),
            "team_a_picks": list(
                trade_c_request.side_a.pick_right_ids
            ),
            "team_b_picks": list(
                trade_c_request.side_b.pick_right_ids
            ),
        },
        "all_involved_teams": sorted(
            all_involved_teams
        ),
        "final_state_revision": state.state_revision,
        "case_count": len(cases),
        "failed_case_count": len(failed_cases),
    }

    report = {
        "script": VALIDATOR_VERSION,
        "parameters": {
            "first_trade_sample": first_trade_sample,
            "connected_candidates": (
                connected_candidates
            ),
            "maximum_pick_pairs": maximum_pick_pairs,
        },
        "summary": summary,
        "cases": cases,
        "failed_cases": failed_cases,
        "passed": not failed_cases,
    }

    OUTPUTS.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )
    pd.DataFrame(cases).to_csv(
        CASE_PATH,
        index=False,
    )

    if failed_cases:
        names = ", ".join(
            row["case_name"]
            for row in failed_cases
        )
        raise IntegrationValidationError(
            "Mutable league-state integration validation "
            f"failed: {names}"
        )

    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--first-trade-sample",
        type=int,
        default=250,
    )
    parser.add_argument(
        "--connected-candidates",
        type=int,
        default=180,
    )
    parser.add_argument(
        "--maximum-pick-pairs",
        type=int,
        default=1000,
    )
    args = parser.parse_args()

    print("Loading base V3 runtime...")
    print(
        "Searching for a connected two-trade "
        "player sequence..."
    )
    print(
        "Searching for a deterministic second-round "
        "pick transaction..."
    )

    report = run_validation(
        first_trade_sample=max(
            args.first_trade_sample,
            1,
        ),
        connected_candidates=max(
            args.connected_candidates,
            1,
        ),
        maximum_pick_pairs=max(
            args.maximum_pick_pairs,
            1,
        ),
    )

    cases = pd.DataFrame(report["cases"])
    print("=" * 100)
    print(
        "MUTABLE LEAGUE STATE INTEGRATION VALIDATION"
    )
    print("=" * 100)
    print(
        cases.to_string(
            index=False,
        )
    )
    print("\nSUMMARY")
    print(
        json.dumps(
            report["summary"],
            indent=2,
        )
    )
    print("\nOUTPUTS")
    print(f"  {REPORT_PATH}")
    print(f"  {CASE_PATH}")
    print(
        "\nMUTABLE LEAGUE STATE INTEGRATION "
        "VALIDATION PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())