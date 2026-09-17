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
    morale_action_queue_v1,
    morale_snapshot_v1,
    role_expectation_v1,
    set_player_role_expectation_v1,
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
    # Simulate an older V1 checkpoint payload. The V2 ensure function must add
    # all new keys without losing existing player morale.
    state.franchise_morale_chemistry_v1 = {
        "version": "franchise-morale-chemistry-v1.0-2026-09-16",
        "season": "2027-28",
        "players": {"2": {"score": 73.0, "player_id": "2", "team": "CHI"}},
        "teams": {},
        "processed_game_ids": [],
    }
    return state


def play_game(state: State, number: int, *, star_minutes: float, win: bool) -> Game:
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
        minutes = star_minutes if pid == "1" else 20.0
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
    original_score = state.franchise_morale_chemistry_v1["players"]["2"]["score"]
    payload = ensure_morale_state_v1(state)

    checks: dict[str, bool] = {}
    checks["version_supports_v1_1_contract"] = any(
        FRANCHISE_MORALE_CHEMISTRY_VERSION.startswith(
            f"franchise-morale-chemistry-v1.{minor}"
        )
        for minor in range(1, 100)
    )
    checks["old_payload_migrates_role_promises"] = isinstance(payload.get("role_promises"), dict)
    checks["old_payload_migrates_event_history"] = isinstance(payload.get("event_history"), list)
    checks["old_player_score_preserved"] = payload["players"]["2"]["score"] == original_score

    auto = role_expectation_v1(state, "CHI", "1")
    checks["star_auto_role_is_featured"] = auto["role"] == "Featured starter"
    set_player_role_expectation_v1(
        state,
        "CHI",
        "1",
        role="Featured starter",
        minutes=34.0,
    )
    promised = role_expectation_v1(state, "CHI", "1")
    checks["role_promise_persists"] = promised["promise_active"] and promised["minutes"] == 34.0

    # Four consecutive bad role games should escalate slowly to a request.
    statuses = []
    for game_number in range(1, 5):
        game = play_game(state, game_number, star_minutes=10.0, win=False)
        update_morale_after_game_v1(state, game)
        statuses.append(row(morale_snapshot_v1(state, "CHI"), "1")["trade_request_status"])
    star = row(morale_snapshot_v1(state, "CHI"), "1")
    checks["request_not_immediate"] = statuses[0] != "Requested trade" and statuses[1] != "Requested trade"
    checks["sustained_frustration_can_request_trade"] = statuses[-1] == "Requested trade" and star["trade_request_active"]
    checks["recent_game_minutes_are_tracked"] = star["recent_minutes"] is not None and star["recent_minutes"] <= 12.0
    checks["reasons_explain_role_failure"] = any("promised" in reason.lower() or "starting" in reason.lower() for reason in star["reasons"])
    checks["action_queue_surfaces_request"] = bool(morale_action_queue_v1(state, "CHI")) and morale_action_queue_v1(state, "CHI")[0]["player_id"] == "1"

    # Re-processing an already handled game must not move scores or counters.
    snapshot_before = copy.deepcopy(morale_snapshot_v1(state, "CHI"))
    duplicate = play_game(state, 4, star_minutes=10.0, win=False)
    # undo totals/standing mutations caused by constructing duplicate fixture;
    # update_morale_after_game_v1 itself must be a no-op for the repeated id.
    for pid in state.players:
        state.player_season_totals[pid].games_played -= 1
        state.player_season_totals[pid].minutes -= (10.0 if pid == "1" else 20.0)
    state.standings["CHI"].losses -= 1
    state.standings["CHI"].streak_length -= 1
    update_morale_after_game_v1(state, duplicate)
    snapshot_after = morale_snapshot_v1(state, "CHI")
    checks["game_processing_is_idempotent"] = row(snapshot_before, "1")["score"] == row(snapshot_after, "1")["score"]

    # Fix the role. Morale should recover over time rather than reset instantly.
    state.teams["CHI"].rotation = Rotation(
        starter_ids=("1", "2", "3", "4", "5"),
        rotation_player_ids=tuple(state.players),
        minutes_targets={**state.teams["CHI"].rotation.minutes_targets, "1": 36.0},
    )
    request_score = star["score"]
    for game_number in range(5, 15):
        game = play_game(state, game_number, star_minutes=36.0, win=True)
        update_morale_after_game_v1(state, game)
    recovered = row(morale_snapshot_v1(state, "CHI"), "1")
    checks["role_fix_recovers_morale_gradually"] = recovered["score"] > request_score + 20 and recovered["score"] < 90
    checks["trade_risk_falls_after_role_fix"] = recovered["trade_request_risk"] < star["trade_request_risk"]

    cleared = clear_player_role_expectation_v1(state, "CHI", "1")
    checks["promise_can_be_cleared"] = bool(cleared) and not role_expectation_v1(state, "CHI", "1")["promise_active"]

    team_snapshot = morale_snapshot_v1(state, "CHI")
    checks["chemistry_is_bounded"] = 8.0 <= team_snapshot["chemistry"] <= 97.0
    checks["role_alignment_is_bounded"] = 0.0 <= team_snapshot["role_alignment"] <= 100.0

    failed = [name for name, passed in checks.items() if not passed]
    report = {"checks": checks, "failed_checks": failed, "passed": not failed}
    print(json.dumps(report, indent=2))
    if failed:
        raise SystemExit("FRANCHISE MORALE / CHEMISTRY SPRINT V2 REGRESSION FAILED")
    print("FRANCHISE MORALE / CHEMISTRY SPRINT V2 REGRESSION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
