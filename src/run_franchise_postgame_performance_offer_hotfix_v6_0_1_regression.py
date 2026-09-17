from __future__ import annotations

import json
from dataclasses import dataclass

import franchise_cpu_autonomous_trade_market_v1 as v6a
import franchise_cpu_incoming_trade_offers_v1 as v6b


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
    def games_played(self):
        return self.wins + self.losses


@dataclass
class Player:
    player_id: str
    player_name: str
    position: str
    team_abbreviation: str


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
            self.need_scores = {"Guard": 10.0, "Wing": 12.0, "Big": 8.0}


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


def make_state(day=40):
    state = State()
    state.settings = Settings()
    state.phase = Phase()
    state.current_day_index = day
    state.players = {
        "1": Player("1", "User Wing", "SF", "CHI"),
        "11": Player("11", "BOS Guard", "SG", "BOS"),
        "21": Player("21", "NYK Big", "C", "NYK"),
        "31": Player("31", "MIA Guard", "PG", "MIA"),
        "41": Player("41", "DAL Wing", "SF", "DAL"),
    }
    state.teams = {
        "CHI": Team(("1",)), "BOS": Team(("11",)), "NYK": Team(("21",)),
        "MIA": Team(("31",)), "DAL": Team(("41",)),
    }
    state.standings = {team: Standing(10, 8) for team in state.teams}
    state.franchise_league_events_v1 = []
    state.franchise_event_settings_v1 = {}
    return state


def cpu_order_builder(state, runtime, trade_state, *, user_team, controlled_teams):
    return [
        (40.0, "BOS", Profile()), (35.0, "NYK", Profile()),
        (30.0, "MIA", Profile()), (25.0, "DAL", Profile()),
    ]


calls = []

def generator(runtime, state, trade_state, *, active_team, goal, partner_team, **kwargs):
    calls.append(active_team)
    if active_team in {"BOS", "NYK"}:
        return FinderResult(())
    if active_team == "MIA":
        return FinderResult((Proposal(
            proposal_id="PERF-1", active_team="MIA", partner_team="CHI", goal=goal,
            cpu_response="accept", response_label="CPU accepts",
            side_a_player_ids=("31",), side_b_player_ids=("1",),
            side_a_pick_asset_ids=(), side_b_pick_asset_ids=(),
            user_value_sent=80.0, user_value_received=82.0, user_value_delta=2.0,
            cpu_value_sent=82.0, cpu_value_received=80.0, cpu_value_delta=-2.0,
            fit_score=75.0, ranking_score=105.0, target_player_id="1",
            target_player_name="User Wing", rationale="MIA wants a wing.",
            preview_payload={"package_fingerprint": "PERF-FP-1"},
        ),))
    return FinderResult(())


def fake_asset_maps(runtime, state, trade_state):
    return ({"1": "User Wing", "11": "BOS Guard", "21": "NYK Big", "31": "MIA Guard", "41": "DAL Wing"}, {})


def main():
    checks = {}

    # V6A cooldown must return without deepcopy.
    a = make_state(40)
    setattr(a, v6a.STATE_ATTRIBUTE, {
        "version": v6a.CPU_AUTONOMOUS_TRADE_MARKET_VERSION,
        "season": "2027-28", "last_tick_day": 39,
        "trades_completed": 0, "history": [],
    })
    original_a = v6a.copy.deepcopy
    count_a = {"n": 0}
    def bomb_a(obj):
        count_a["n"] += 1
        raise AssertionError("deepcopy should not run")
    v6a.copy.deepcopy = bomb_a
    try:
        ra = v6a.run_cpu_autonomous_trade_market_v1(object(), a, object(), controlled_teams=("CHI",))
    finally:
        v6a.copy.deepcopy = original_a
    checks["v6a_cooldown_avoids_deepcopy"] = (not ra.ran and count_a["n"] == 0)

    original_maps = v6b._asset_name_maps
    v6b._asset_name_maps = fake_asset_maps
    try:
        calls.clear()
        b = make_state(40)
        first = v6b.run_cpu_incoming_trade_offer_tick_v1(
            object(), b, object(), controlled_teams=("CHI",),
            proposal_generator=generator, cpu_team_order_builder=cpu_order_builder,
        )
        checks["first_scan_bounded_to_two_teams"] = (
            first.ran and not first.created_offer and calls == ["BOS", "NYK"]
        )
        b1 = first.state
        checks["failed_scan_did_not_start_offer_cooldown"] = (
            b1.franchise_cpu_incoming_trade_offers_v1["last_offer_day"] == -10_000
        )

        original_b = v6b.copy.deepcopy
        count_b = {"n": 0}
        def bomb_b(obj):
            count_b["n"] += 1
            raise AssertionError("deepcopy should not run")
        v6b.copy.deepcopy = bomb_b
        try:
            b1.current_day_index = 41
            one_day = v6b.run_cpu_incoming_trade_offer_tick_v1(
                object(), b1, object(), controlled_teams=("CHI",),
                proposal_generator=generator, cpu_team_order_builder=cpu_order_builder,
            )
        finally:
            v6b.copy.deepcopy = original_b
        checks["one_day_later_avoids_deepcopy"] = (not one_day.ran and count_b["n"] == 0)

        calls.clear()
        b1.current_day_index = 42
        second = v6b.run_cpu_incoming_trade_offer_tick_v1(
            object(), b1, object(), controlled_teams=("CHI",),
            proposal_generator=generator, cpu_team_order_builder=cpu_order_builder,
        )
        checks["two_day_retry_rotates_to_new_teams"] = (
            second.created_offer and calls and calls[0] == "MIA"
        )
        checks["actual_offer_starts_seven_day_cooldown"] = (
            second.state.franchise_cpu_incoming_trade_offers_v1["last_offer_day"] == 42
        )
    finally:
        v6b._asset_name_maps = original_maps

    failed = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"checks": checks, "failed_checks": failed, "passed": not failed}, indent=2))
    if failed:
        raise SystemExit(1)
    print("FRANCHISE POSTGAME PERFORMANCE / OFFER HOTFIX V6.0.1 REGRESSION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
