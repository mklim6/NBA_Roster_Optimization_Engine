from __future__ import annotations

import copy
import json
from dataclasses import dataclass

from franchise_cpu_autonomous_trade_market_v1 import (
    MAX_MORALE_DRIVEN_CPU_TRADES_PER_SEASON,
    MIN_MEDIAN_GAMES,
    STATE_ATTRIBUTE,
    TICK_COOLDOWN_DAYS,
    TRADE_DEADLINE_MEDIAN_GAMES,
    run_cpu_autonomous_trade_market_v1,
)


@dataclass
class Settings:
    season_label: str = "2027-28"


@dataclass
class Phase:
    value: str = "regular_season"


@dataclass
class Standing:
    wins: int
    losses: int

    @property
    def games_played(self) -> int:
        return self.wins + self.losses


@dataclass
class Player:
    player_id: str
    player_name: str
    position: str
    team_abbreviation: str
    overall_rating: float = 78.0


@dataclass
class Team:
    roster_player_ids: tuple[str, ...]


@dataclass(frozen=True)
class Proposal:
    proposal_id: str
    active_team: str
    partner_team: str
    goal: str
    cpu_response: str
    side_a_player_ids: tuple[str, ...]
    side_b_player_ids: tuple[str, ...]
    side_a_pick_asset_ids: tuple[str, ...]
    side_b_pick_asset_ids: tuple[str, ...]
    user_value_delta: float
    cpu_value_delta: float
    fit_score: float
    ranking_score: float
    target_player_id: str
    target_player_name: str
    preview_payload: dict
    user_value_sent: float = 0.0
    user_value_received: float = 0.0
    cpu_value_sent: float = 0.0
    cpu_value_received: float = 0.0


@dataclass
class FinderResult:
    proposals: tuple[Proposal, ...]


@dataclass
class CommitResult:
    transaction_id: str
    committed_state: object


class State:
    pass


def make_state(
    *,
    games: int = 20,
    day: int = 50,
) -> State:
    state = State()
    state.settings = Settings()
    state.phase = Phase()
    state.current_day_index = day
    state.players = {
        "1": Player(
            "1",
            "User Player",
            "PG",
            "CHI",
        ),
        "11": Player(
            "11",
            "Unhappy Wing",
            "SF",
            "LAL",
        ),
        "12": Player(
            "12",
            "LAL Depth",
            "C",
            "LAL",
        ),
        "21": Player(
            "21",
            "Buyer Asset",
            "SG",
            "BOS",
        ),
        "31": Player(
            "31",
            "Other Asset",
            "PF",
            "NYK",
        ),
    }
    state.teams = {
        "CHI": Team(("1",)),
        "LAL": Team(("11", "12")),
        "BOS": Team(("21",)),
        "NYK": Team(("31",)),
    }
    state.standings = {
        "CHI": Standing(games // 2, games - games // 2),
        "LAL": Standing(7, max(0, games - 7)),
        "BOS": Standing(13, max(0, games - 13)),
        "NYK": Standing(11, max(0, games - 11)),
    }
    state.franchise_morale_chemistry_v1 = {
        "players": {
            "11": {
                "score": 34.0,
                "previous_score": 35.0,
                "low_morale_games": 8,
                "high_risk_games": 7,
                "trade_request_status": "Requested trade",
                "trade_request_active": True,
                "trade_request_risk": 58.0,
                "recent_games": [],
            }
        },
        "role_promises": {
            "11": {"role": "Starter"},
        },
        "trade_responses": {
            "11": "On trade block",
        },
        "meetings": {
            "11": {"last": "reassure"},
        },
        "event_history": [],
    }
    return state


def market_rows_builder(
    state,
    *,
    controlled_teams,
):
    return [
        {
            "Team": "LAL",
            "Player": "Unhappy Wing",
            "Risk %": 58.0,
            "Request": "Requested trade",
            "CPU response": "On trade block",
            "Market posture": "Actively market",
        }
    ]


def buyer_order_builder(
    state,
    *,
    seller_team,
    target_player_id,
    controlled_teams,
):
    # Deliberately include CHI first to prove the runner excludes it.
    return ["CHI", "BOS", "NYK"]


def proposal_generator(
    runtime,
    state,
    trade_state,
    *,
    active_team,
    goal,
    partner_team,
    **kwargs,
):
    if active_team == "BOS":
        return FinderResult(
            (
                Proposal(
                    proposal_id="P-1",
                    active_team="BOS",
                    partner_team="LAL",
                    goal=goal,
                    cpu_response="accept",
                    side_a_player_ids=("21",),
                    side_b_player_ids=("11",),
                    side_a_pick_asset_ids=(),
                    side_b_pick_asset_ids=(),
                    user_value_delta=1.5,
                    cpu_value_delta=2.0,
                    fit_score=70.0,
                    ranking_score=120.0,
                    target_player_id="11",
                    target_player_name="Unhappy Wing",
                    preview_payload={
                        "package_fingerprint": "FP-1",
                    },
                ),
                # Wrong target should never be committed.
                Proposal(
                    proposal_id="P-2",
                    active_team="BOS",
                    partner_team="LAL",
                    goal=goal,
                    cpu_response="accept",
                    side_a_player_ids=("21",),
                    side_b_player_ids=("12",),
                    side_a_pick_asset_ids=(),
                    side_b_pick_asset_ids=(),
                    user_value_delta=5.0,
                    cpu_value_delta=5.0,
                    fit_score=80.0,
                    ranking_score=140.0,
                    target_player_id="12",
                    target_player_name="LAL Depth",
                    preview_payload={
                        "package_fingerprint": "FP-2",
                    },
                ),
            )
        )
    return FinderResult(())


commit_calls = []


def trade_committer(
    runtime,
    state,
    trade_state,
    *,
    team_a,
    team_b,
    side_a_player_ids,
    side_b_player_ids,
    side_a_pick_asset_ids,
    side_b_pick_asset_ids,
    expected_fingerprint,
):
    commit_calls.append(
        {
            "team_a": team_a,
            "team_b": team_b,
            "side_a_player_ids": side_a_player_ids,
            "side_b_player_ids": side_b_player_ids,
            "fingerprint": expected_fingerprint,
        }
    )
    candidate = copy.deepcopy(state)
    candidate.players["11"].team_abbreviation = team_a
    candidate.teams["LAL"].roster_player_ids = ("12",)
    candidate.teams["BOS"].roster_player_ids = ("21", "11")
    return CommitResult(
        transaction_id="FTX-0099",
        committed_state=candidate,
    )


def main() -> int:
    commit_calls.clear()
    source = make_state()

    result = run_cpu_autonomous_trade_market_v1(
        runtime=object(),
        state=source,
        trade_state=object(),
        controlled_teams=("CHI",),
        proposal_generator=proposal_generator,
        trade_committer=trade_committer,
        market_rows_builder=market_rows_builder,
        buyer_order_builder=buyer_order_builder,
    )

    payload = getattr(
        result.state,
        STATE_ATTRIBUTE,
    )
    morale = (
        result.state
        .franchise_morale_chemistry_v1
    )
    player_morale = morale["players"]["11"]

    cooldown = run_cpu_autonomous_trade_market_v1(
        runtime=object(),
        state=result.state,
        trade_state=object(),
        controlled_teams=("CHI",),
        proposal_generator=proposal_generator,
        trade_committer=trade_committer,
        market_rows_builder=market_rows_builder,
        buyer_order_builder=buyer_order_builder,
    )

    too_early = run_cpu_autonomous_trade_market_v1(
        runtime=object(),
        state=make_state(games=MIN_MEDIAN_GAMES - 1),
        trade_state=object(),
        controlled_teams=("CHI",),
        proposal_generator=proposal_generator,
        trade_committer=trade_committer,
        market_rows_builder=market_rows_builder,
        buyer_order_builder=buyer_order_builder,
    )

    after_deadline = run_cpu_autonomous_trade_market_v1(
        runtime=object(),
        state=make_state(games=TRADE_DEADLINE_MEDIAN_GAMES),
        trade_state=object(),
        controlled_teams=("CHI",),
        proposal_generator=proposal_generator,
        trade_committer=trade_committer,
        market_rows_builder=market_rows_builder,
        buyer_order_builder=buyer_order_builder,
    )

    source_market_state = getattr(
        source,
        STATE_ATTRIBUTE,
        None,
    )

    checks = {
        "trade_committed": result.committed,
        "exact_target_committed": (
            len(commit_calls) == 1
            and commit_calls[0]["side_b_player_ids"]
            == ("11",)
        ),
        "controlled_team_never_used_as_buyer": (
            commit_calls[0]["team_a"] == "BOS"
        ),
        "seller_is_cpu_team": (
            commit_calls[0]["team_b"] == "LAL"
        ),
        "fingerprint_preserved": (
            commit_calls[0]["fingerprint"]
            == "FP-1"
        ),
        "one_trade_per_tick": (
            payload["trades_completed"] == 1
        ),
        "history_records_committed_trade": (
            payload["history"][-1]["outcome"]
            == "trade_committed"
            and payload["history"][-1]["transaction_id"]
            == "FTX-0099"
        ),
        "trade_request_resolved_after_trade": (
            player_morale["trade_request_active"] is False
            and player_morale["trade_request_status"]
            == "Resolved by trade"
            and player_morale["trade_request_risk"]
            == 0.0
        ),
        "old_team_role_promise_cleared": (
            "11" not in morale["role_promises"]
        ),
        "old_front_office_response_cleared": (
            "11" not in morale["trade_responses"]
        ),
        "fresh_start_morale_applied": (
            player_morale["score"] >= 55.0
        ),
        "source_state_not_mutated": (
            source.players["11"].team_abbreviation
            == "LAL"
            and (
                source_market_state is None
                or source_market_state.get(
                    "trades_completed",
                    0,
                )
                == 0
            )
        ),
        "same_day_second_tick_is_blocked": (
            not cooldown.ran
            and "cooldown"
            in cooldown.reason.lower()
        ),
        "trade_window_does_not_open_too_early": (
            not too_early.ran
        ),
        "trade_window_closes_at_deadline_guard": (
            not after_deadline.ran
        ),
        "season_cap_constant_is_bounded": (
            1
            <= MAX_MORALE_DRIVEN_CPU_TRADES_PER_SEASON
            <= 12
        ),
        "cooldown_is_at_least_weekly": (
            TICK_COOLDOWN_DAYS >= 7
        ),
    }

    failed = [
        name
        for name, passed
        in checks.items()
        if not passed
    ]

    print(
        json.dumps(
            {
                "checks": checks,
                "failed_checks": failed,
                "passed": not failed,
                "result": result.to_payload(),
                "cooldown": cooldown.to_payload(),
            },
            indent=2,
            default=str,
        )
    )

    if failed:
        raise SystemExit(1)

    print(
        "FRANCHISE CPU AUTONOMOUS TRADE MARKET "
        "V6A REGRESSION PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
