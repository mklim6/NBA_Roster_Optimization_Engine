from __future__ import annotations

import copy
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from franchise_morale_chemistry_v1 import (  # noqa: E402
    FRANCHISE_MORALE_CHEMISTRY_VERSION,
    clear_player_role_expectation_v1,
    ensure_morale_state_v1,
    hold_player_meeting_v1,
    morale_action_queue_v1,
    morale_snapshot_v1,
    role_expectation_v1,
    set_player_role_expectation_v1,
    set_player_trade_response_v1,
    trade_response_v1,
    update_morale_after_game_v1,
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


@dataclass
class Totals:
    games_played: int = 0
    minutes: float = 0.0


@dataclass
class Standing:
    wins: int = 0
    losses: int = 0
    streak_type: str = ""
    streak_length: int = 0


@dataclass
class Box:
    player_id: str
    team_abbreviation: str
    started: bool
    minutes: float


@dataclass
class Game:
    game_id: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    player_box_scores: tuple[Box, ...]


class State:
    pass


def build_state() -> State:
    state = State()
    state.settings = Settings()
    state.current_day_index = 0
    state.players = {}
    ratings = [88, 85, 82, 80, 78, 76, 74, 72, 70, 68]
    for index, rating in enumerate(ratings, start=1):
        pid = str(index)
        state.players[pid] = Player(
            player_id=pid,
            player_name=f"Player {index}",
            overall_rating=float(rating),
            potential_rating=float(rating + 2),
            age=26.0,
            contract=Contract(years_remaining=1 if index == 1 else 2),
        )
    minutes = {
        "1": 10.0,
        "2": 32.0,
        "3": 31.0,
        "4": 30.0,
        "5": 29.0,
        "6": 28.0,
        "7": 24.0,
        "8": 20.0,
        "9": 18.0,
        "10": 18.0,
    }
    state.teams = {
        "CHI": Team(
            roster_player_ids=tuple(state.players),
            rotation=Rotation(
                starter_ids=("2", "3", "4", "5", "6"),
                rotation_player_ids=tuple(state.players),
                minutes_targets=minutes,
            ),
        ),
        "LAL": Team(roster_player_ids=(), rotation=Rotation((), (), {})),
    }
    state.player_season_totals = {pid: Totals() for pid in state.players}
    state.standings = {"CHI": Standing(), "LAL": Standing()}
    state.franchise_morale_chemistry_v1 = {
        "version": "franchise-morale-chemistry-v1.2-2026-09-16",
        "season": "2027-28",
        "players": {},
        "teams": {},
        "processed_game_ids": [],
        "role_promises": {},
        "event_history": [],
        "rotation_emphasis": {"CHI": "Development"},
    }
    return state


def play_game(state: State, number: int, *, star_minutes: float, win: bool, player2_minutes: float = 32.0) -> Game:
    state.current_day_index = number
    standing = state.standings["CHI"]
    if win:
        standing.wins += 1
        standing.streak_type = "W"
    else:
        standing.losses += 1
        standing.streak_type = "L"
    standing.streak_length += 1

    boxes = []
    for pid in state.players:
        minutes = star_minutes if pid == "1" else (player2_minutes if pid == "2" else 20.0)
        totals = state.player_season_totals[pid]
        totals.games_played += 1
        totals.minutes += minutes
        boxes.append(
            Box(
                player_id=pid,
                team_abbreviation="CHI",
                started=(pid in {"1", "2", "3", "4", "5"} if star_minutes >= 30 else pid in {"2", "3", "4", "5", "6"}),
                minutes=minutes,
            )
        )
    return Game(
        game_id=f"REG-{number:03d}",
        home_team="CHI",
        away_team="LAL",
        home_score=120 if win else 90,
        away_score=100 if win else 110,
        player_box_scores=tuple(boxes),
    )


def row(snapshot: dict, pid: str) -> dict:
    return next(item for item in snapshot["players"] if item["player_id"] == pid)


def main() -> int:
    state = build_state()
    payload = ensure_morale_state_v1(state)
    checks: dict[str, bool] = {}
    checks["version_is_v1_3"] = FRANCHISE_MORALE_CHEMISTRY_VERSION.startswith("franchise-morale-chemistry-v1.3")
    checks["new_payload_keys_migrate"] = isinstance(payload.get("meetings"), dict) and isinstance(payload.get("trade_responses"), dict)

    # A five-game role commitment should be explicitly graded. Five severe
    # misses must be recorded as a broken promise and affect the visible state.
    set_player_role_expectation_v1(
        state,
        "CHI",
        "1",
        role="Featured starter",
        minutes=34.0,
        review_games=5,
    )
    for number in range(1, 6):
        update_morale_after_game_v1(state, play_game(state, number, star_minutes=10.0, win=False))
    exp = role_expectation_v1(state, "CHI", "1")
    snap = morale_snapshot_v1(state, "CHI")
    star = row(snap, "1")
    checks["promise_review_reaches_deadline"] = exp["games_since_set"] == 5 and exp["review_after_games"] == 5
    checks["broken_promise_is_persistent"] = exp["promise_status"] == "broken" and star["broken_promise_games"] > 0
    checks["broken_promise_explained"] = any("promise was broken" in reason.lower() for reason in star["reasons"])
    checks["broken_promise_or_request_enters_action_queue"] = any(
        item["player_id"] == "1"
        and ("broken" in item["action"].lower() or "request" in item["action"].lower())
        for item in morale_action_queue_v1(state, "CHI")
    )

    # Meeting actions are deliberately small and rate-limited.
    before_meeting = star["score"]
    meeting = hold_player_meeting_v1(state, "CHI", "1", action="Reassure and listen")
    post_meeting = row(morale_snapshot_v1(state, "CHI"), "1")
    checks["meeting_gives_small_relief"] = post_meeting["score"] > before_meeting and post_meeting["score"] <= before_meeting + 2.0
    checks["meeting_sets_cooldown"] = post_meeting["meeting_cooldown_games"] == 3
    try:
        hold_player_meeting_v1(state, "CHI", "1", action="Ask for patience")
        second_meeting_blocked = False
    except ValueError:
        second_meeting_blocked = True
    checks["meeting_cooldown_blocks_spam"] = second_meeting_blocked
    checks["meeting_is_audited"] = bool(meeting) and bool((payload.get("meetings") or {}).get("1"))

    # The front office can acknowledge trade pressure without forcing a trade.
    set_player_trade_response_v1(state, "CHI", "1", response="On trade block")
    trade_snap = row(morale_snapshot_v1(state, "CHI"), "1")
    checks["trade_response_persists"] = trade_response_v1(state, "CHI", "1") == "On trade block"
    checks["active_request_trade_block_is_visible"] = "trade block" in trade_snap["trade_availability"].lower()

    # A separate short commitment that is honored should receive the kept
    # verdict and a temporary positive memory.
    clear_player_role_expectation_v1(state, "CHI", "2")
    set_player_role_expectation_v1(state, "CHI", "2", role="Featured starter", minutes=30.0, review_games=3)
    for number in range(6, 9):
        update_morale_after_game_v1(state, play_game(state, number, star_minutes=36.0, player2_minutes=32.0, win=True))
    player2_exp = role_expectation_v1(state, "CHI", "2")
    player2 = row(morale_snapshot_v1(state, "CHI"), "2")
    checks["kept_promise_is_graded"] = player2_exp["promise_status"] == "kept"
    checks["kept_promise_has_positive_memory"] = player2["kept_promise_games"] > 0

    # Duplicate processing cannot advance a promise review twice.
    before_dup = copy.deepcopy(role_expectation_v1(state, "CHI", "2"))
    duplicate = Game(
        game_id="REG-008",
        home_team="CHI",
        away_team="LAL",
        home_score=120,
        away_score=100,
        player_box_scores=tuple(),
    )
    update_morale_after_game_v1(state, duplicate)
    after_dup = role_expectation_v1(state, "CHI", "2")
    checks["promise_review_is_idempotent"] = before_dup["games_since_set"] == after_dup["games_since_set"]

    # Season transition soft-resets morale but preserves a meaningful grievance
    # when a request/broken promise existed. Old-season promises do not carry.
    old_score = row(morale_snapshot_v1(state, "CHI"), "1")["score"]
    state.settings.season_label = "2028-29"
    new_payload = ensure_morale_state_v1(state)
    next_year = row(morale_snapshot_v1(state, "CHI"), "1")
    checks["offseason_soft_reset_moves_toward_neutral"] = next_year["score"] > old_score and next_year["score"] < 70.1
    checks["offseason_grievance_persists"] = next_year["offseason_grievance_games"] > 0
    checks["old_season_promise_expires"] = not role_expectation_v1(state, "CHI", "1")["promise_active"]
    checks["trade_request_not_auto_erased"] = new_payload["players"]["1"].get("trade_request_status") == "Requested trade"

    checks["chemistry_accounts_for_promise_consequences"] = 8.0 <= morale_snapshot_v1(state, "CHI")["chemistry"] <= 97.0

    failed = [name for name, passed in checks.items() if not passed]
    report = {"checks": checks, "failed_checks": failed, "passed": not failed}
    print(json.dumps(report, indent=2))
    if failed:
        raise SystemExit("FRANCHISE MORALE FRONT-OFFICE CONSEQUENCES V3 REGRESSION FAILED")
    print("FRANCHISE MORALE FRONT-OFFICE CONSEQUENCES V3 REGRESSION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
