from __future__ import annotations

import copy
import json
from dataclasses import dataclass

from franchise_cpu_morale_response_v1 import (
    run_cpu_morale_reactions_v1,
)
from franchise_morale_chemistry_v1 import (
    ensure_morale_state_v1,
)
from franchise_morale_trade_market_v1 import (
    apply_cpu_morale_trade_market_to_decisions_v1,
    morale_trade_market_context_v1,
)


@dataclass
class Settings:
    season_label: str = "2027-28"


@dataclass
class Contract:
    years_remaining: int = 2


@dataclass
class Player:
    player_id: str
    player_name: str
    overall_rating: float
    potential_rating: float
    age: float
    contract: Contract
    rookie_season: str = ""
    draft_pick: int = 0


@dataclass
class Rotation:
    starter_ids: tuple[str, ...]
    rotation_player_ids: tuple[str, ...]
    minutes_targets: dict[str, float]


@dataclass
class Team:
    roster_player_ids: tuple[str, ...]
    rotation: Rotation
    active_player_ids: tuple[str, ...]


@dataclass
class Totals:
    games_played: int = 3
    minutes: float = 60.0


@dataclass
class Standing:
    wins: int = 2
    losses: int = 8
    streak_type: str = "L"
    streak_length: int = 3


@dataclass(frozen=True)
class Decision:
    player_id: str
    player_name: str
    asset_policy: str
    asset_tier: str
    roster_fit: str


class State:
    pass


def make_team_players(
    prefix: int,
    ratings: list[int],
) -> dict[str, Player]:
    out: dict[str, Player] = {}
    for index, rating in enumerate(
        ratings
    ):
        pid = str(
            prefix + index
        )
        out[pid] = Player(
            pid,
            f"Player {pid}",
            float(rating),
            float(rating + 3),
            (
                24.0
                if index == 0
                else 27.0
            ),
            Contract(
                1
                if index >= 6
                else 2
            ),
        )
    return out


def build_state() -> State:
    state = State()
    state.settings = Settings()
    state.current_day_index = 20

    chi = make_team_players(
        1,
        [
            88, 85, 82, 80, 78,
            76, 74, 72, 70, 68,
        ],
    )
    lal = make_team_players(
        11,
        [
            87, 84, 82, 80, 78,
            76, 74, 72, 70, 68,
        ],
    )
    state.players = {
        **chi,
        **lal,
    }

    chi_ids = tuple(
        chi
    )
    lal_ids = tuple(
        lal
    )
    chi_minutes = {
        pid: mins
        for pid, mins
        in zip(
            chi_ids,
            [
                34, 32, 31, 30, 29,
                24, 22, 16, 12, 10,
            ],
        )
    }
    lal_rot = lal_ids[1:]
    lal_minutes = {
        pid: mins
        for pid, mins
        in zip(
            lal_rot,
            [
                34, 32, 31, 30, 29,
                25, 22, 20, 17,
            ],
        )
    }
    lal_minutes[
        lal_rot[0]
    ] += (
        240
        - sum(
            lal_minutes.values()
        )
    )

    state.teams = {
        "CHI": Team(
            chi_ids,
            Rotation(
                chi_ids[:5],
                chi_ids,
                chi_minutes,
            ),
            chi_ids,
        ),
        "LAL": Team(
            lal_ids,
            Rotation(
                lal_rot[:5],
                lal_rot,
                lal_minutes,
            ),
            lal_ids,
        ),
    }
    state.player_season_totals = {
        pid: Totals()
        for pid
        in state.players
    }
    state.standings = {
        "CHI": Standing(
            7,
            3,
            "W",
            2,
        ),
        "LAL": Standing(
            2,
            8,
            "L",
            4,
        ),
    }
    state.franchise_morale_chemistry_v1 = {
        "version": (
            "franchise-morale-chemistry-v1.3-2026-09-16"
        ),
        "season": "2027-28",
        "players": {},
        "teams": {},
        "processed_game_ids": [],
        "role_promises": {},
        "trade_request_history": [],
        "event_history": [],
        "rotation_emphasis": {},
        "meetings": {},
        "trade_responses": {},
    }

    payload = (
        ensure_morale_state_v1(
            state
        )
    )

    payload["players"]["1"] = {
        "score": 35.0,
        "previous_score": 36.0,
        "low_morale_games": 6,
        "high_risk_games": 5,
        "trade_request_status": (
            "Requested trade"
        ),
        "trade_request_active": True,
        "recent_games": [
            {
                "game_id": "CHI-020",
                "day": 20,
                "minutes": 5.0,
                "started": False,
                "won": False,
            }
        ],
    }

    # CPU core star with a real request. V4 should listen,
    # and V5A may make even an Untouchable designation
    # market-visible while keeping a premium seller ask.
    payload["players"]["11"] = {
        "score": 34.0,
        "previous_score": 35.0,
        "low_morale_games": 7,
        "high_risk_games": 6,
        "trade_request_status": (
            "Requested trade"
        ),
        "trade_request_active": True,
        "recent_games": [
            {
                "game_id": "LAL-020",
                "day": 20,
                "minutes": 0.0,
                "started": False,
                "won": False,
            }
        ],
    }

    # Non-core veteran with an active request should enter
    # the ordinary Market asset-policy lane.
    payload["players"]["18"] = {
        "score": 35.0,
        "previous_score": 36.0,
        "low_morale_games": 6,
        "high_risk_games": 5,
        "trade_request_status": (
            "Requested trade"
        ),
        "trade_request_active": True,
        "recent_games": [
            {
                "game_id": "LAL-020",
                "day": 20,
                "minutes": 8.0,
                "started": False,
                "won": False,
            }
        ],
    }

    for pid in lal_ids:
        if pid not in payload[
            "players"
        ]:
            payload[
                "players"
            ][pid] = {
                "score": 70.0,
                "previous_score": 70.0,
                "recent_games": [
                    {
                        "game_id": "LAL-020",
                        "day": 20,
                        "minutes": 20.0,
                        "started": False,
                        "won": False,
                    }
                ],
            }

    return state


def main() -> int:
    state = build_state()

    # Let V4 determine the persistent CPU response first.
    run_cpu_morale_reactions_v1(
        state,
        controlled_teams=("CHI",),
    )

    original = (
        Decision(
            "11",
            "CPU Core",
            "Untouchable",
            "Franchise",
            "Core",
        ),
        Decision(
            "18",
            "CPU Veteran",
            "Hold",
            "Rotation",
            "Neutral",
        ),
        Decision(
            "19",
            "Happy Player",
            "Hold",
            "Rotation",
            "Neutral",
        ),
    )

    before = copy.deepcopy(
        original
    )
    adjusted = (
        apply_cpu_morale_trade_market_to_decisions_v1(
            state,
            "LAL",
            original,
            controlled_teams=(
                "CHI",
            ),
        )
    )

    controlled = (
        Decision(
            "1",
            "User Star",
            "Untouchable",
            "Franchise",
            "Core",
        ),
    )
    controlled_adjusted = (
        apply_cpu_morale_trade_market_to_decisions_v1(
            state,
            "CHI",
            controlled,
            controlled_teams=(
                "CHI",
            ),
        )
    )

    core_context = (
        morale_trade_market_context_v1(
            state,
            "LAL",
            "11",
        )
    )
    veteran_context = (
        morale_trade_market_context_v1(
            state,
            "LAL",
            "18",
        )
    )
    happy_context = (
        morale_trade_market_context_v1(
            state,
            "LAL",
            "19",
        )
    )

    checks = {
        "input_decisions_not_mutated": (
            original == before
        ),
        "controlled_team_is_untouched": (
            controlled_adjusted
            == controlled
        ),
        "requested_noncore_moves_to_market": (
            adjusted[1].asset_policy
            == "Market"
        ),
        "requested_core_can_be_heard": (
            adjusted[0].asset_policy
            == "Market"
        ),
        "quiet_player_keeps_base_policy": (
            adjusted[2].asset_policy
            == "Hold"
        ),
        "core_keeps_premium_ask": (
            core_context
            .seller_ask_multiplier
            >= 0.98
        ),
        "noncore_request_is_not_fire_sale": (
            0.90
            <= veteran_context
            .seller_ask_multiplier
            < 1.0
        ),
        "request_increases_willingness": (
            veteran_context
            .willingness_modifier
            > 1.0
        ),
        "quiet_player_not_forced_to_market": (
            not happy_context
            .should_market
        ),
        "bridge_does_not_change_ratings": (
            state.players["18"]
            .overall_rating
            == 72.0
        ),
        "bridge_does_not_create_transaction_history": (
            not hasattr(
                state,
                "transaction_history",
            )
            and not hasattr(
                state,
                "franchise_transactions",
            )
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
                "core_context": (
                    core_context.__dict__
                ),
                "veteran_context": (
                    veteran_context.__dict__
                ),
                "adjusted_policies": [
                    {
                        "player_id": (
                            row.player_id
                        ),
                        "asset_policy": (
                            row.asset_policy
                        ),
                    }
                    for row
                    in adjusted
                ],
            },
            indent=2,
            default=str,
        )
    )

    if failed:
        raise SystemExit(1)

    print(
        "FRANCHISE MORALE TRADE MARKET "
        "BRIDGE V5A REGRESSION PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
