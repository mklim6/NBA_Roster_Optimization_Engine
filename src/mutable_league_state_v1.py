from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import (  # noqa: E402
    VALIDATION_REVISION,
    RuntimeData,
    Status,
    TradeRequest,
    TradeSideRequest,
    evaluate_trade,
    load_runtime_data,
    normalize_player_id,
    normalize_team,
    split_player_ids,
    to_bool,
    to_float,
    to_int,
)


STATE_VERSION = "mutable-league-state-v1-2026-08-07"
SELF_TEST_REPORT = (
    OUTPUTS / "mutable_league_state_v1_self_test.json"
)


class StateMutationError(RuntimeError):
    """Raised when a league-state mutation would be unsafe."""


@dataclass
class TeamFinancialState:
    team_abbreviation: str
    team_salary: float | None
    apron_salary: float | None
    standard_contract_count: int | None
    two_way_contract_count: int | None
    hard_cap_active: bool | None
    hard_cap_level: str

    @property
    def total_contract_count(self) -> int | None:
        if (
            self.standard_contract_count is None
            or self.two_way_contract_count is None
        ):
            return None

        return (
            self.standard_contract_count
            + self.two_way_contract_count
        )


@dataclass
class StateSnapshot:
    player_team_by_id: dict[str, str]
    pick_team_by_id: dict[str, str]
    team_financials: dict[str, TeamFinancialState]
    acquired_player_ids: set[str]


@dataclass
class TransactionRecord:
    transaction_id: str
    state_revision: int
    trade_date: str
    team_a: str
    team_b: str
    team_a_player_ids: tuple[str, ...]
    team_b_player_ids: tuple[str, ...]
    team_a_pick_right_ids: tuple[str, ...]
    team_b_pick_right_ids: tuple[str, ...]
    team_a_before: TeamFinancialState
    team_a_after: TeamFinancialState
    team_b_before: TeamFinancialState
    team_b_after: TeamFinancialState
    evaluation_status: str


@dataclass
class LeagueState:
    state_version: str
    engine_validation_revision: str
    state_revision: int
    player_team_by_id: dict[str, str]
    pick_team_by_id: dict[str, str]
    team_financials: dict[str, TeamFinancialState]
    acquired_player_ids: set[str] = field(default_factory=set)
    transaction_history: list[TransactionRecord] = field(
        default_factory=list
    )
    undo_stack: list[StateSnapshot] = field(default_factory=list)
    initial_snapshot: StateSnapshot | None = None


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def copy_team_financial(
    value: TeamFinancialState,
) -> TeamFinancialState:
    return TeamFinancialState(**asdict(value))


def copy_financial_map(
    values: dict[str, TeamFinancialState],
) -> dict[str, TeamFinancialState]:
    return {
        team: copy_team_financial(value)
        for team, value in values.items()
    }


def capture_snapshot(state: LeagueState) -> StateSnapshot:
    return StateSnapshot(
        player_team_by_id=dict(state.player_team_by_id),
        pick_team_by_id=dict(state.pick_team_by_id),
        team_financials=copy_financial_map(
            state.team_financials
        ),
        acquired_player_ids=set(
            state.acquired_player_ids
        ),
    )


def restore_snapshot(
    state: LeagueState,
    snapshot: StateSnapshot,
) -> None:
    state.player_team_by_id = dict(
        snapshot.player_team_by_id
    )
    state.pick_team_by_id = dict(
        snapshot.pick_team_by_id
    )
    state.team_financials = copy_financial_map(
        snapshot.team_financials
    )
    state.acquired_player_ids = set(
        snapshot.acquired_player_ids
    )


def runtime_teams(runtime: RuntimeData) -> list[str]:
    return sorted(
        normalize_team(team)
        for team in runtime.team_salary_by_team
        if normalize_team(team)
    )


def initial_player_teams(
    runtime: RuntimeData,
) -> dict[str, str]:
    result: dict[str, str] = {}

    for player_id, record in runtime.financial_by_id.items():
        normalized_id = normalize_player_id(player_id)
        if not normalized_id:
            continue

        result[normalized_id] = normalize_team(
            record.get("current_team_2026_27")
        )

    for player_id, record in runtime.trade_by_id.items():
        normalized_id = normalize_player_id(player_id)
        if not normalized_id:
            continue

        team = normalize_team(
            record.get("current_team_2026_27")
        )
        if normalized_id not in result or team:
            result[normalized_id] = team

    return result


def initial_pick_teams(
    runtime: RuntimeData,
) -> dict[str, str]:
    return {
        clean_text(pick_right_id): normalize_team(
            record.get("candidate_team")
        )
        for pick_right_id, record in runtime.pick_by_id.items()
        if clean_text(pick_right_id)
    }


def initial_team_financials(
    runtime: RuntimeData,
) -> dict[str, TeamFinancialState]:
    result: dict[str, TeamFinancialState] = {}

    for team in runtime_teams(runtime):
        record = runtime.team_cba_by_team.get(team, {})

        result[team] = TeamFinancialState(
            team_abbreviation=team,
            team_salary=to_float(
                record.get("verified_team_salary_value")
            ),
            apron_salary=to_float(
                record.get(
                    "verified_apron_team_salary_value"
                )
            ),
            standard_contract_count=to_int(
                record.get("standard_contract_count")
            ),
            two_way_contract_count=to_int(
                record.get("two_way_contract_count")
            ),
            hard_cap_active=to_bool(
                record.get("hard_cap_active")
            ),
            hard_cap_level=clean_text(
                record.get("hard_cap_level")
            ).lower()
            or "none",
        )

    return result


def create_league_state(
    runtime: RuntimeData,
) -> LeagueState:
    state = LeagueState(
        state_version=STATE_VERSION,
        engine_validation_revision=VALIDATION_REVISION,
        state_revision=0,
        player_team_by_id=initial_player_teams(runtime),
        pick_team_by_id=initial_pick_teams(runtime),
        team_financials=initial_team_financials(runtime),
    )
    state.initial_snapshot = capture_snapshot(state)

    validate_state(state, runtime)
    return state


def player_is_two_way(
    runtime: RuntimeData,
    player_id: str,
) -> bool:
    decision = runtime.player_cba_by_id.get(
        normalize_player_id(player_id),
        {},
    )
    return (
        to_bool(
            decision.get("two_way_contract_active")
        )
        is True
    )


def normalized_player_ids(
    values: Any,
) -> tuple[str, ...]:
    return tuple(
        normalize_player_id(value)
        for value in values
        if normalize_player_id(value)
    )


def normalized_pick_ids(
    values: Any,
) -> tuple[str, ...]:
    return tuple(
        clean_text(value)
        for value in values
        if clean_text(value)
    )


def ensure_unique_assets(
    side_a_players: tuple[str, ...],
    side_b_players: tuple[str, ...],
    side_a_picks: tuple[str, ...],
    side_b_picks: tuple[str, ...],
) -> None:
    all_players = [
        *side_a_players,
        *side_b_players,
    ]
    all_picks = [
        *side_a_picks,
        *side_b_picks,
    ]

    if len(all_players) != len(set(all_players)):
        raise StateMutationError(
            "A player appears more than once in the trade request."
        )

    if len(all_picks) != len(set(all_picks)):
        raise StateMutationError(
            "A draft right appears more than once in the trade request."
        )


def assert_current_ownership(
    state: LeagueState,
    team: str,
    player_ids: tuple[str, ...],
    pick_right_ids: tuple[str, ...],
) -> None:
    for player_id in player_ids:
        if player_id not in state.player_team_by_id:
            raise StateMutationError(
                f"Player {player_id} is missing from league state."
            )

        observed_team = state.player_team_by_id[player_id]
        if observed_team != team:
            raise StateMutationError(
                f"Player {player_id} belongs to "
                f"{observed_team or '<unassigned>'}, not {team}, "
                "in the mutable league state."
            )

    for pick_right_id in pick_right_ids:
        if pick_right_id not in state.pick_team_by_id:
            raise StateMutationError(
                f"Draft right {pick_right_id} is missing "
                "from league state."
            )

        observed_team = state.pick_team_by_id[
            pick_right_id
        ]
        if observed_team != team:
            raise StateMutationError(
                f"Draft right {pick_right_id} belongs to "
                f"{observed_team or '<unassigned>'}, not {team}, "
                "in the mutable league state."
            )


def posttrade_financial_state(
    *,
    runtime: RuntimeData,
    before: TeamFinancialState,
    outgoing_player_ids: tuple[str, ...],
    incoming_player_ids: tuple[str, ...],
    evaluation_side: Any,
) -> TeamFinancialState:
    post_team_salary = to_float(
        evaluation_side.posttrade_team_salary
    )
    post_apron_salary = to_float(
        evaluation_side.posttrade_apron_team_salary
    )

    if post_team_salary is None or post_apron_salary is None:
        raise StateMutationError(
            f"{before.team_abbreviation} does not have "
            "deterministic post-trade salary values."
        )

    if (
        before.standard_contract_count is None
        or before.two_way_contract_count is None
    ):
        raise StateMutationError(
            f"{before.team_abbreviation} is missing "
            "deterministic roster counts."
        )

    outgoing_two_way = sum(
        player_is_two_way(runtime, player_id)
        for player_id in outgoing_player_ids
    )
    incoming_two_way = sum(
        player_is_two_way(runtime, player_id)
        for player_id in incoming_player_ids
    )

    outgoing_standard = (
        len(outgoing_player_ids) - outgoing_two_way
    )
    incoming_standard = (
        len(incoming_player_ids) - incoming_two_way
    )

    hard_cap_level = clean_text(
        evaluation_side.hard_cap_level_after_trade
    ).lower() or "none"

    return TeamFinancialState(
        team_abbreviation=before.team_abbreviation,
        team_salary=round(post_team_salary, 2),
        apron_salary=round(post_apron_salary, 2),
        standard_contract_count=(
            before.standard_contract_count
            - outgoing_standard
            + incoming_standard
        ),
        two_way_contract_count=(
            before.two_way_contract_count
            - outgoing_two_way
            + incoming_two_way
        ),
        hard_cap_active=hard_cap_level != "none",
        hard_cap_level=hard_cap_level,
    )


def apply_passed_trade(
    state: LeagueState,
    runtime: RuntimeData,
    request: TradeRequest,
    evaluation: Any,
) -> TransactionRecord:
    if evaluation.status != Status.PASS:
        raise StateMutationError(
            "Only a deterministic PASS trade can be applied "
            "to mutable league state."
        )

    team_a = normalize_team(
        request.side_a.team_abbreviation
    )
    team_b = normalize_team(
        request.side_b.team_abbreviation
    )

    if not team_a or not team_b or team_a == team_b:
        raise StateMutationError(
            "A mutable two-team transaction requires "
            "two different valid teams."
        )

    if (
        team_a not in state.team_financials
        or team_b not in state.team_financials
    ):
        raise StateMutationError(
            "One or both teams are missing from league state."
        )

    side_a_players = normalized_player_ids(
        request.side_a.player_ids
    )
    side_b_players = normalized_player_ids(
        request.side_b.player_ids
    )
    side_a_picks = normalized_pick_ids(
        request.side_a.pick_right_ids
    )
    side_b_picks = normalized_pick_ids(
        request.side_b.pick_right_ids
    )

    if not (side_a_players or side_a_picks):
        raise StateMutationError(
            f"{team_a} must send at least one asset."
        )

    if not (side_b_players or side_b_picks):
        raise StateMutationError(
            f"{team_b} must send at least one asset."
        )

    ensure_unique_assets(
        side_a_players,
        side_b_players,
        side_a_picks,
        side_b_picks,
    )
    assert_current_ownership(
        state,
        team_a,
        side_a_players,
        side_a_picks,
    )
    assert_current_ownership(
        state,
        team_b,
        side_b_players,
        side_b_picks,
    )

    evaluation_team_a = normalize_team(
        evaluation.side_a.team_abbreviation
    )
    evaluation_team_b = normalize_team(
        evaluation.side_b.team_abbreviation
    )
    if (
        evaluation_team_a != team_a
        or evaluation_team_b != team_b
    ):
        raise StateMutationError(
            "The evaluation teams do not match the "
            "requested transaction teams."
        )

    before_a = copy_team_financial(
        state.team_financials[team_a]
    )
    before_b = copy_team_financial(
        state.team_financials[team_b]
    )
    after_a = posttrade_financial_state(
        runtime=runtime,
        before=before_a,
        outgoing_player_ids=side_a_players,
        incoming_player_ids=side_b_players,
        evaluation_side=evaluation.side_a,
    )
    after_b = posttrade_financial_state(
        runtime=runtime,
        before=before_b,
        outgoing_player_ids=side_b_players,
        incoming_player_ids=side_a_players,
        evaluation_side=evaluation.side_b,
    )

    state.undo_stack.append(capture_snapshot(state))

    try:
        for player_id in side_a_players:
            state.player_team_by_id[player_id] = team_b
            state.acquired_player_ids.add(player_id)

        for player_id in side_b_players:
            state.player_team_by_id[player_id] = team_a
            state.acquired_player_ids.add(player_id)

        for pick_right_id in side_a_picks:
            state.pick_team_by_id[pick_right_id] = team_b

        for pick_right_id in side_b_picks:
            state.pick_team_by_id[pick_right_id] = team_a

        state.team_financials[team_a] = after_a
        state.team_financials[team_b] = after_b
        state.state_revision += 1

        record = TransactionRecord(
            transaction_id=(
                f"TXN-{len(state.transaction_history) + 1:04d}"
            ),
            state_revision=state.state_revision,
            trade_date=clean_text(
                getattr(evaluation, "trade_date", "")
            ),
            team_a=team_a,
            team_b=team_b,
            team_a_player_ids=side_a_players,
            team_b_player_ids=side_b_players,
            team_a_pick_right_ids=side_a_picks,
            team_b_pick_right_ids=side_b_picks,
            team_a_before=before_a,
            team_a_after=after_a,
            team_b_before=before_b,
            team_b_after=after_b,
            evaluation_status=evaluation.status.value,
        )
        state.transaction_history.append(record)

        validate_state(state, runtime)
        return record
    except Exception:
        snapshot = state.undo_stack.pop()
        restore_snapshot(state, snapshot)
        state.state_revision += 1
        raise


def undo_last_trade(
    state: LeagueState,
    runtime: RuntimeData,
) -> TransactionRecord:
    if not state.transaction_history or not state.undo_stack:
        raise StateMutationError(
            "There is no applied transaction to undo."
        )

    removed = state.transaction_history.pop()
    snapshot = state.undo_stack.pop()
    restore_snapshot(state, snapshot)
    state.state_revision += 1
    validate_state(state, runtime)
    return removed


def reset_league_state(
    state: LeagueState,
    runtime: RuntimeData,
) -> None:
    if state.initial_snapshot is None:
        raise StateMutationError(
            "League state does not contain an initial snapshot."
        )

    restore_snapshot(state, state.initial_snapshot)
    state.transaction_history.clear()
    state.undo_stack.clear()
    state.state_revision += 1
    validate_state(state, runtime)


def team_roster(
    state: LeagueState,
    team: str,
) -> list[str]:
    normalized_team = normalize_team(team)
    return sorted(
        player_id
        for player_id, owner in (
            state.player_team_by_id.items()
        )
        if owner == normalized_team
    )


def team_pick_rights(
    state: LeagueState,
    team: str,
) -> list[str]:
    normalized_team = normalize_team(team)
    return sorted(
        pick_right_id
        for pick_right_id, owner in (
            state.pick_team_by_id.items()
        )
        if owner == normalized_team
    )


def validate_state(
    state: LeagueState,
    runtime: RuntimeData,
) -> dict[str, bool]:
    valid_teams = set(runtime_teams(runtime))

    initial = state.initial_snapshot
    expected_player_ids = (
        set(initial.player_team_by_id)
        if initial is not None
        else set(state.player_team_by_id)
    )
    expected_pick_ids = (
        set(initial.pick_team_by_id)
        if initial is not None
        else set(state.pick_team_by_id)
    )

    checks = {
        "state_version_present": bool(state.state_version),
        "engine_revision_matches": (
            state.engine_validation_revision
            == VALIDATION_REVISION
        ),
        "all_initial_players_preserved": (
            set(state.player_team_by_id)
            == expected_player_ids
        ),
        "all_initial_picks_preserved": (
            set(state.pick_team_by_id)
            == expected_pick_ids
        ),
        "team_financials_cover_30_teams": (
            set(state.team_financials) == valid_teams
            and len(valid_teams) == 30
        ),
        "player_owners_valid_or_blank": all(
            owner in valid_teams or owner == ""
            for owner in state.player_team_by_id.values()
        ),
        "pick_owners_valid": all(
            owner in valid_teams
            for owner in state.pick_team_by_id.values()
        ),
        "financial_values_nonnegative_when_known": all(
            (
                financial.team_salary is None
                or (
                    math.isfinite(financial.team_salary)
                    and financial.team_salary >= 0
                )
            )
            and (
                financial.apron_salary is None
                or (
                    math.isfinite(financial.apron_salary)
                    and financial.apron_salary >= 0
                )
            )
            for financial in state.team_financials.values()
        ),
        "roster_counts_nonnegative_when_known": all(
            (
                financial.standard_contract_count is None
                or financial.standard_contract_count >= 0
            )
            and (
                financial.two_way_contract_count is None
                or financial.two_way_contract_count >= 0
            )
            for financial in state.team_financials.values()
        ),
        "history_and_undo_depth_match": (
            len(state.transaction_history)
            == len(state.undo_stack)
        ),
    }

    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]
    if failed:
        raise StateMutationError(
            "Mutable league-state validation failed: "
            + ", ".join(failed)
        )

    return checks


def find_pass_player_trade(
    runtime: RuntimeData,
    sample_size: int = 1000,
) -> tuple[TradeRequest, Any]:
    path = (
        OUTPUTS
        / "one_for_one_mixed_player_pick_candidates_2026_27_v9_final_full_cba_evaluated.parquet"
    )
    if not path.exists():
        raise FileNotFoundError(
            f"V9 validation file is missing: {path}"
        )

    columns = [
        "team_a",
        "team_b",
        "side_a_player_ids",
        "side_b_player_ids",
        "full_cba_evidence_complete",
        "player_cba_decisions_matched",
    ]
    frame = pd.read_parquet(path, columns=columns)
    frame = frame.loc[
        frame["full_cba_evidence_complete"].eq(True)
        & frame["player_cba_decisions_matched"].eq(True)
    ]

    selected = frame.sample(
        n=min(sample_size, len(frame)),
        random_state=20260807,
    )

    for row in selected.to_dict(orient="records"):
        request = TradeRequest(
            side_a=TradeSideRequest(
                team_abbreviation=row["team_a"],
                player_ids=tuple(
                    split_player_ids(
                        row["side_a_player_ids"]
                    )
                ),
            ),
            side_b=TradeSideRequest(
                team_abbreviation=row["team_b"],
                player_ids=tuple(
                    split_player_ids(
                        row["side_b_player_ids"]
                    )
                ),
            ),
        )
        result = evaluate_trade(runtime, request)

        if result.status == Status.PASS:
            return request, result

    raise AssertionError(
        "No deterministic PASS player trade was found "
        f"in a {len(selected)}-row V9 sample."
    )


def synthetic_pick_evaluation(
    state: LeagueState,
    team_a: str,
    team_b: str,
) -> Any:
    financial_a = state.team_financials[team_a]
    financial_b = state.team_financials[team_b]

    for financial in [financial_a, financial_b]:
        if (
            financial.team_salary is None
            or financial.apron_salary is None
        ):
            raise AssertionError(
                "Synthetic pick test selected a team with "
                "incomplete salary evidence."
            )

    def side(financial: TeamFinancialState) -> Any:
        return SimpleNamespace(
            team_abbreviation=(
                financial.team_abbreviation
            ),
            posttrade_team_salary=(
                financial.team_salary
            ),
            posttrade_apron_team_salary=(
                financial.apron_salary
            ),
            hard_cap_level_after_trade=(
                financial.hard_cap_level
            ),
        )

    return SimpleNamespace(
        status=Status.PASS,
        trade_date="2026-08-04",
        side_a=side(financial_a),
        side_b=side(financial_b),
    )


def run_self_test() -> dict[str, Any]:
    runtime = load_runtime_data()
    state = create_league_state(runtime)
    initial_checks = validate_state(state, runtime)

    request, result = find_pass_player_trade(runtime)
    team_a = normalize_team(
        request.side_a.team_abbreviation
    )
    team_b = normalize_team(
        request.side_b.team_abbreviation
    )
    side_a_players = normalized_player_ids(
        request.side_a.player_ids
    )
    side_b_players = normalized_player_ids(
        request.side_b.player_ids
    )

    record = apply_passed_trade(
        state,
        runtime,
        request,
        result,
    )

    player_apply_checks = {
        "pass_trade_recorded": (
            len(state.transaction_history) == 1
        ),
        "undo_snapshot_recorded": (
            len(state.undo_stack) == 1
        ),
        "side_a_players_moved_to_team_b": all(
            state.player_team_by_id[player_id]
            == team_b
            for player_id in side_a_players
        ),
        "side_b_players_moved_to_team_a": all(
            state.player_team_by_id[player_id]
            == team_a
            for player_id in side_b_players
        ),
        "team_a_salary_matches_evaluation": (
            math.isclose(
                state.team_financials[
                    team_a
                ].team_salary
                or 0.0,
                result.side_a.posttrade_team_salary
                or 0.0,
                abs_tol=0.01,
            )
        ),
        "team_b_salary_matches_evaluation": (
            math.isclose(
                state.team_financials[
                    team_b
                ].team_salary
                or 0.0,
                result.side_b.posttrade_team_salary
                or 0.0,
                abs_tol=0.01,
            )
        ),
        "transaction_id_created": (
            record.transaction_id == "TXN-0001"
        ),
    }

    undo_last_trade(state, runtime)
    player_undo_checks = {
        "history_cleared_after_undo": (
            len(state.transaction_history) == 0
        ),
        "undo_stack_cleared_after_undo": (
            len(state.undo_stack) == 0
        ),
        "side_a_players_restored": all(
            state.player_team_by_id[player_id]
            == team_a
            for player_id in side_a_players
        ),
        "side_b_players_restored": all(
            state.player_team_by_id[player_id]
            == team_b
            for player_id in side_b_players
        ),
    }

    eligible_pick_rows = runtime.picks.loc[
        runtime.picks[
            "standalone_trade_asset_flag"
        ].map(to_bool).eq(True)
    ]
    pick_records = eligible_pick_rows.to_dict(
        orient="records"
    )

    pick_pair: tuple[dict[str, Any], dict[str, Any]] | None = None
    for first in pick_records:
        first_team = normalize_team(
            first.get("candidate_team")
        )
        if (
            first_team not in state.team_financials
            or state.team_financials[
                first_team
            ].team_salary is None
        ):
            continue

        for second in pick_records:
            second_team = normalize_team(
                second.get("candidate_team")
            )
            if (
                second_team == first_team
                or second_team not in state.team_financials
                or state.team_financials[
                    second_team
                ].team_salary is None
            ):
                continue

            pick_pair = (first, second)
            break

        if pick_pair is not None:
            break

    if pick_pair is None:
        raise AssertionError(
            "Could not find two standalone rights for "
            "the pure pick-transfer test."
        )

    first, second = pick_pair
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
    pick_result = synthetic_pick_evaluation(
        state,
        pick_team_a,
        pick_team_b,
    )
    apply_passed_trade(
        state,
        runtime,
        pick_request,
        pick_result,
    )

    pick_apply_checks = {
        "side_a_pick_moved_to_team_b": (
            state.pick_team_by_id[pick_a]
            == pick_team_b
        ),
        "side_b_pick_moved_to_team_a": (
            state.pick_team_by_id[pick_b]
            == pick_team_a
        ),
    }

    reset_league_state(state, runtime)
    reset_checks = {
        "history_empty_after_reset": (
            len(state.transaction_history) == 0
        ),
        "undo_empty_after_reset": (
            len(state.undo_stack) == 0
        ),
        "pick_a_restored_after_reset": (
            state.pick_team_by_id[pick_a]
            == pick_team_a
        ),
        "pick_b_restored_after_reset": (
            state.pick_team_by_id[pick_b]
            == pick_team_b
        ),
        "state_valid_after_reset": all(
            validate_state(state, runtime).values()
        ),
    }

    checks = {
        **{
            f"initial_{name}": passed
            for name, passed in initial_checks.items()
        },
        **player_apply_checks,
        **player_undo_checks,
        **pick_apply_checks,
        **reset_checks,
    }
    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]

    report = {
        "script": STATE_VERSION,
        "engine_validation_revision": (
            VALIDATION_REVISION
        ),
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "players_in_state": len(
                state.player_team_by_id
            ),
            "picks_in_state": len(
                state.pick_team_by_id
            ),
            "teams_in_state": len(
                state.team_financials
            ),
            "pass_trade_team_a": team_a,
            "pass_trade_team_b": team_b,
            "pass_trade_side_a_players": (
                list(side_a_players)
            ),
            "pass_trade_side_b_players": (
                list(side_b_players)
            ),
            "pure_pick_test_team_a": pick_team_a,
            "pure_pick_test_team_b": pick_team_b,
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
            "Mutable league-state V1 self-test failed: "
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
        print(
            json.dumps(
                run_self_test(),
                indent=2,
            )
        )
        print(
            "\nMUTABLE LEAGUE STATE V1 SELF-TEST PASSED"
        )
        return 0

    runtime = load_runtime_data()
    state = create_league_state(runtime)
    print(
        json.dumps(
            {
                "script": STATE_VERSION,
                "engine_validation_revision": (
                    state.engine_validation_revision
                ),
                "state_revision": state.state_revision,
                "players": len(
                    state.player_team_by_id
                ),
                "draft_rights": len(
                    state.pick_team_by_id
                ),
                "teams": len(
                    state.team_financials
                ),
                "transactions": len(
                    state.transaction_history
                ),
                "status": "initialized",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())