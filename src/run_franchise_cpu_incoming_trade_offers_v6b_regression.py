from __future__ import annotations

import copy
import json
from dataclasses import dataclass

from franchise_cpu_incoming_trade_offers_v1 import (
    OFFER_COOLDOWN_DAYS,
    OFFER_LIFETIME_DAYS,
    STATE_ATTRIBUTE,
    pending_cpu_trade_offers_v1,
    run_cpu_incoming_trade_offer_tick_v1,
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
    overall_rating: float = 80.0


@dataclass
class Team:
    roster_player_ids: tuple[str, ...]


@dataclass
class Profile:
    timeline: str = "contender"
    need_scores: dict | None = None
    win_pct: float = 0.65

    def __post_init__(self):
        if self.need_scores is None:
            self.need_scores = {
                "Guard": 8.0,
                "Wing": 12.0,
                "Big": 5.0,
            }


@dataclass(frozen=True)
class Proposal:
    proposal_id: str
    active_team: str
    partner_team: str
    goal: str
    cpu_response: str
    response_label: str
    side_a_player_ids: tuple[str, ...]
    side_b_player_ids: tuple[str, ...]
    side_a_pick_asset_ids: tuple[str, ...]
    side_b_pick_asset_ids: tuple[str, ...]
    user_value_sent: float
    user_value_received: float
    user_value_delta: float
    cpu_value_sent: float
    cpu_value_received: float
    cpu_value_delta: float
    fit_score: float
    ranking_score: float
    target_player_id: str
    target_player_name: str
    rationale: str
    preview_payload: dict
    deal_type: str = "Player-centered"
    counter_sweetener: str = ""


@dataclass
class FinderResult:
    proposals: tuple[Proposal, ...]


class State:
    pass


def make_state(
    *,
    day: int = 40,
    games: int = 18,
) -> State:
    state = State()
    state.settings = Settings()
    state.phase = Phase()
    state.current_day_index = day
    state.players = {
        "1": Player("1", "User Star", "PG", "CHI", 88.0),
        "2": Player("2", "User Wing", "SF", "CHI", 80.0),
        "11": Player("11", "CPU Guard", "SG", "BOS", 79.0),
        "12": Player("12", "CPU Big", "C", "BOS", 76.0),
        "21": Player("21", "Other CPU", "PF", "NYK", 78.0),
    }
    state.teams = {
        "CHI": Team(("1", "2")),
        "BOS": Team(("11", "12")),
        "NYK": Team(("21",)),
    }
    state.standings = {
        "CHI": Standing(10, games - 10),
        "BOS": Standing(12, games - 12),
        "NYK": Standing(8, games - 8),
    }
    state.franchise_league_events_v1 = []
    state.franchise_event_settings_v1 = {}
    return state


def cpu_order_builder(
    state,
    runtime,
    trade_state,
    *,
    user_team,
    controlled_teams,
):
    return [
        (25.0, "BOS", Profile()),
        (20.0, "NYK", Profile(timeline="rebuild")),
    ]


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
    if active_team != "BOS":
        return FinderResult(())
    return FinderResult(
        (
            Proposal(
                proposal_id="INC-1",
                active_team="BOS",
                partner_team="CHI",
                goal=goal,
                cpu_response="accept",
                response_label="CPU accepts",
                side_a_player_ids=("11",),
                side_b_player_ids=("2",),
                side_a_pick_asset_ids=(),
                side_b_pick_asset_ids=(),
                user_value_sent=80.0,
                user_value_received=82.0,
                user_value_delta=2.0,
                cpu_value_sent=82.0,
                cpu_value_received=80.0,
                cpu_value_delta=-2.0,
                fit_score=75.0,
                ranking_score=110.0,
                target_player_id="2",
                target_player_name="User Wing",
                rationale="BOS needs a wing and is willing to move a guard.",
                preview_payload={
                    "package_fingerprint": "FP-INCOMING-1",
                },
            ),
            # Invalid target is not on CHI and must be ignored.
            Proposal(
                proposal_id="INC-2",
                active_team="BOS",
                partner_team="CHI",
                goal=goal,
                cpu_response="accept",
                response_label="CPU accepts",
                side_a_player_ids=("12",),
                side_b_player_ids=("21",),
                side_a_pick_asset_ids=(),
                side_b_pick_asset_ids=(),
                user_value_sent=81.0,
                user_value_received=82.0,
                user_value_delta=1.0,
                cpu_value_sent=82.0,
                cpu_value_received=81.0,
                cpu_value_delta=-1.0,
                fit_score=80.0,
                ranking_score=130.0,
                target_player_id="21",
                target_player_name="Other CPU",
                rationale="Wrong partner target.",
                preview_payload={
                    "package_fingerprint": "FP-WRONG",
                },
            ),
        )
    )


def fake_asset_maps(runtime, state, trade_state):
    # monkeypatch target helper by replacing module global during the test
    return (
        {
            "1": "User Star",
            "2": "User Wing",
            "11": "CPU Guard",
            "12": "CPU Big",
            "21": "Other CPU",
        },
        {},
    )


def main() -> int:
    import franchise_cpu_incoming_trade_offers_v1 as module

    original_maps = module._asset_name_maps
    module._asset_name_maps = fake_asset_maps

    try:
        source = make_state()
        result = run_cpu_incoming_trade_offer_tick_v1(
            runtime=object(),
            state=source,
            trade_state=object(),
            controlled_teams=("CHI",),
            proposal_generator=proposal_generator,
            cpu_team_order_builder=cpu_order_builder,
        )

        offers = pending_cpu_trade_offers_v1(result.state)
        payload = getattr(result.state, STATE_ATTRIBUTE)
        events = result.state.franchise_league_events_v1

        second = run_cpu_incoming_trade_offer_tick_v1(
            runtime=object(),
            state=result.state,
            trade_state=object(),
            controlled_teams=("CHI",),
            proposal_generator=proposal_generator,
            cpu_team_order_builder=cpu_order_builder,
        )

        expired_state = copy.deepcopy(result.state)
        expired_state.current_day_index = (
            result.current_day + OFFER_LIFETIME_DAYS + 1
        )
        expired_pending = pending_cpu_trade_offers_v1(expired_state)
        expired_offer = getattr(
            expired_state,
            STATE_ATTRIBUTE,
        )["offers"][0]

        checks = {
            "offer_created": (
                result.created_offer
                and len(offers) == 1
            ),
            "offer_targets_controlled_roster_player": (
                offers[0]["target_player_id"] == "2"
            ),
            "cpu_is_not_controlled_team": (
                offers[0]["cpu_team"] == "BOS"
                and offers[0]["user_team"] == "CHI"
            ),
            "fingerprint_is_persisted": (
                offers[0]["package_fingerprint"]
                == "FP-INCOMING-1"
            ),
            "exact_assets_are_persisted": (
                offers[0]["side_a_player_ids"] == ["11"]
                and offers[0]["side_b_player_ids"] == ["2"]
            ),
            "offer_is_nonblocking_inbox_decision": (
                len(events) == 1
                and events[0]["event_type"] == "cpu_trade_offer"
                and events[0]["blocking"] is False
                and events[0]["status"] == "unread"
            ),
            "one_pending_offer_prevents_spam": (
                not second.created_offer
                and "already waiting"
                in second.reason
            ),
            "source_state_not_mutated": (
                not hasattr(
                    source,
                    STATE_ATTRIBUTE,
                )
                and source.franchise_league_events_v1 == []
            ),
            "offer_expires": (
                expired_pending == []
                and expired_offer["status"] == "expired"
            ),
            "lifetime_is_reasonable": (
                3 <= OFFER_LIFETIME_DAYS <= 10
            ),
            "cooldown_is_at_least_weekly": (
                OFFER_COOLDOWN_DAYS >= 7
            ),
            "offer_history_records_creation": (
                payload["history"][0]["outcome"]
                == "created"
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
                    "offer": offers[0] if offers else {},
                },
                indent=2,
                default=str,
            )
        )

        if failed:
            raise SystemExit(1)

        print(
            "FRANCHISE CPU INCOMING TRADE OFFERS "
            "V6B REGRESSION PASSED"
        )
        return 0
    finally:
        module._asset_name_maps = original_maps


if __name__ == "__main__":
    raise SystemExit(main())
