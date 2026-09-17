from __future__ import annotations

import json
from dataclasses import dataclass

from franchise_cpu_morale_response_v1 import (
    run_cpu_morale_reactions_v1,
)
from franchise_morale_chemistry_v1 import (
    ensure_morale_state_v1,
)
from franchise_morale_trade_finder_terms_v1 import (
    build_morale_trade_finder_terms_v1,
    morale_trade_finder_target_available_v1,
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
    games_played: int = 4
    minutes: float = 72.0


@dataclass
class Standing:
    wins: int = 2
    losses: int = 8
    streak_type: str = "L"
    streak_length: int = 4


class State:
    pass


def make_state() -> State:
    state = State()
    state.settings = Settings()
    state.current_day_index = 30

    rows = [
        ("1", "User Star", 90, 92, 25),
        ("11", "CPU Core", 90, 94, 24),
        ("12", "CPU Requested Vet", 78, 79, 29),
        ("13", "CPU Quiet Vet", 78, 79, 29),
        ("14", "CPU Block Vet", 77, 78, 30),
        ("15", "CPU Rotation", 76, 77, 28),
        ("16", "CPU Rotation 2", 75, 76, 28),
        ("17", "CPU Rotation 3", 74, 75, 28),
        ("18", "CPU Rotation 4", 73, 74, 28),
        ("19", "CPU Rotation 5", 72, 73, 28),
        ("20", "CPU Rotation 6", 71, 72, 28),
    ]
    state.players = {
        pid: Player(
            pid,
            name,
            float(ovr),
            float(pot),
            float(age),
            Contract(),
        )
        for (
            pid,
            name,
            ovr,
            pot,
            age,
        )
        in rows
    }

    cpu_ids = tuple(
        str(value)
        for value
        in range(
            11,
            21,
        )
    )
    cpu_rotation_ids = cpu_ids[
        1:
    ]
    minutes = {
        pid: value
        for pid, value
        in zip(
            cpu_rotation_ids,
            [
                34, 32, 31, 30, 28,
                25, 22, 20, 18,
            ],
        )
    }
    minutes[
        cpu_rotation_ids[0]
    ] += (
        240
        - sum(
            minutes.values()
        )
    )

    state.teams = {
        "CHI": Team(
            ("1",),
            Rotation(
                ("1",),
                ("1",),
                {"1": 36.0},
            ),
            ("1",),
        ),
        "LAL": Team(
            cpu_ids,
            Rotation(
                cpu_rotation_ids[:5],
                cpu_rotation_ids,
                minutes,
            ),
            cpu_ids,
        ),
    }
    state.player_season_totals = {
        pid: Totals()
        for pid
        in state.players
    }
    state.standings = {
        "CHI": Standing(
            wins=7,
            losses=3,
            streak_type="W",
            streak_length=2,
        ),
        "LAL": Standing(),
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

    payload = ensure_morale_state_v1(
        state
    )

    # Core star: real trade request. V4 should listen, but V5B
    # must keep the seller ask premium rather than discounting him.
    payload["players"]["11"] = {
        "score": 34.0,
        "previous_score": 35.0,
        "low_morale_games": 8,
        "high_risk_games": 7,
        "trade_request_status": "Requested trade",
        "trade_request_active": True,
        "recent_games": [
            {
                "game_id": "LAL-030",
                "day": 30,
                "minutes": 0.0,
                "started": False,
                "won": False,
            }
        ],
    }

    # Non-core requested veteran should become easier to negotiate for.
    payload["players"]["12"] = {
        "score": 34.0,
        "previous_score": 35.0,
        "low_morale_games": 8,
        "high_risk_games": 7,
        "trade_request_status": "Requested trade",
        "trade_request_active": True,
        "recent_games": [
            {
                "game_id": "LAL-030",
                "day": 30,
                "minutes": 8.0,
                "started": False,
                "won": False,
            }
        ],
    }

    # Quiet control.
    payload["players"]["13"] = {
        "score": 72.0,
        "previous_score": 72.0,
        "low_morale_games": 0,
        "high_risk_games": 0,
        "trade_request_status": "None",
        "trade_request_active": False,
        "recent_games": [
            {
                "game_id": "LAL-030",
                "day": 30,
                "minutes": 26.0,
                "started": False,
                "won": False,
            }
        ],
    }

    # Force a legitimate trade-block posture in the persistent V4 state
    # for a non-core veteran so the stronger seller relaxation is tested.
    payload["players"]["14"] = {
        "score": 31.0,
        "previous_score": 32.0,
        "low_morale_games": 10,
        "high_risk_games": 9,
        "trade_request_status": "Requested trade",
        "trade_request_active": True,
        "recent_games": [
            {
                "game_id": "LAL-030",
                "day": 30,
                "minutes": 6.0,
                "started": False,
                "won": False,
            }
        ],
    }
    payload["trade_responses"]["14"] = "On trade block"

    for pid in cpu_ids:
        if pid not in payload["players"]:
            payload["players"][pid] = {
                "score": 70.0,
                "previous_score": 70.0,
                "recent_games": [
                    {
                        "game_id": "LAL-030",
                        "day": 30,
                        "minutes": 20.0,
                        "started": False,
                        "won": False,
                    }
                ],
            }

    run_cpu_morale_reactions_v1(
        state,
        controlled_teams=("CHI",),
    )

    # Pin two persistent V4 front-office postures so this regression
    # isolates V5B seller-term behavior rather than retesting V4's
    # escalation thresholds.
    payload["trade_responses"]["12"] = "Listening to offers"
    payload["trade_responses"]["14"] = "On trade block"

    return state


def row(
    player_id: str,
    name: str,
) -> dict:
    return {
        "player_id": player_id,
        "player_name": name,
    }


def main() -> int:
    state = make_state()

    neutral_floor = 3.0

    core = build_morale_trade_finder_terms_v1(
        state,
        "LAL",
        row("11", "CPU Core"),
        base_accept_floor=neutral_floor,
    )
    requested = build_morale_trade_finder_terms_v1(
        state,
        "LAL",
        row(
            "12",
            "CPU Requested Vet",
        ),
        base_accept_floor=neutral_floor,
    )
    quiet = build_morale_trade_finder_terms_v1(
        state,
        "LAL",
        row(
            "13",
            "CPU Quiet Vet",
        ),
        base_accept_floor=neutral_floor,
    )
    blocked = build_morale_trade_finder_terms_v1(
        state,
        "LAL",
        row(
            "14",
            "CPU Block Vet",
        ),
        base_accept_floor=neutral_floor,
    )

    core_available = (
        morale_trade_finder_target_available_v1(
            state,
            "LAL",
            row("11", "CPU Core"),
            base_untouchable=True,
        )
    )
    quiet_untouchable_available = (
        morale_trade_finder_target_available_v1(
            state,
            "LAL",
            row(
                "13",
                "CPU Quiet Vet",
            ),
            base_untouchable=True,
        )
    )

    checks = {
        "quiet_player_has_neutral_terms": (
            quiet.adjusted_accept_floor
            == neutral_floor
            and quiet.search_priority_bonus
            == 0.0
            and not quiet.override_untouchable
        ),
        "requested_noncore_lowers_seller_floor": (
            requested.adjusted_accept_floor
            < neutral_floor
        ),
        "requested_noncore_gets_search_priority": (
            requested.search_priority_bonus
            > 0.0
        ),
        "trade_block_is_stronger_than_listening": (
            blocked.adjusted_accept_floor
            < requested.adjusted_accept_floor
        ),
        "core_request_can_unlock_target_pool": (
            core_available
            and core.override_untouchable
        ),
        "quiet_untouchable_stays_hidden": (
            not quiet_untouchable_available
        ),
        "requested_core_keeps_premium_or_neutral_floor": (
            core.adjusted_accept_floor
            >= neutral_floor
        ),
        "requested_core_is_not_fire_sale": (
            core.seller_ask_multiplier
            >= 0.98
        ),
        "noncore_discount_is_bounded": (
            requested.floor_adjustment
            >= -2.5
            and blocked.floor_adjustment
            >= -2.5
        ),
        "ratings_are_untouched": (
            state.players["12"].overall_rating
            == 78.0
            and state.players["11"].overall_rating
            == 90.0
        ),
        "no_transaction_history_created": (
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
                "core": core.to_payload(),
                "requested_noncore": (
                    requested.to_payload()
                ),
                "trade_block": (
                    blocked.to_payload()
                ),
                "quiet": quiet.to_payload(),
            },
            indent=2,
            default=str,
        )
    )

    if failed:
        raise SystemExit(1)

    print(
        "FRANCHISE MORALE TRADE FINDER "
        "BRIDGE V5B REGRESSION PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
