from __future__ import annotations

import copy
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import franchise_free_agency_transaction_v1 as txn
import franchise_free_agency_cpu_offer_generation_v1 as offers


@dataclass
class Contract:
    status: str = "free_agent_pool"
    salary: float | None = None
    years_remaining: int | None = None
    option_type: str = ""
    guaranteed: bool | None = None


@dataclass
class Player:
    player_id: str
    player_name: str
    team_abbreviation: str = ""
    roster_status: str = "free_agent"
    two_way: bool = False
    contract: Contract = field(default_factory=Contract)


@dataclass
class Rotation:
    starter_ids: tuple[str, ...]
    rotation_player_ids: tuple[str, ...]
    minutes_targets: dict[str, float]


@dataclass
class Team:
    roster_player_ids: tuple[str, ...]
    active_player_ids: tuple[str, ...]
    inactive_player_ids: tuple[str, ...]
    rotation: Rotation


def main() -> int:
    report = offers.generation_contract_report()
    assert report["speculative_source_full_validation_once_per_board"] is True
    assert report["speculative_candidate_touched_surface_validation"] is True
    assert report["durable_winner_full_league_validation_preserved"] is True

    roster = tuple(f"P{i}" for i in range(1, 11))
    rotation = Rotation(
        starter_ids=roster[:5],
        rotation_player_ids=roster,
        minutes_targets={pid: 24.0 for pid in roster},
    )
    players = {
        pid: Player(
            player_id=pid,
            player_name=pid,
            team_abbreviation="CHI",
            roster_status="active_roster",
            contract=Contract(
                status="under_contract",
                salary=1_000_000.0,
                years_remaining=1,
                guaranteed=True,
            ),
        )
        for pid in roster
    }
    players["FA1"] = Player("FA1", "Free Agent")

    state = SimpleNamespace(
        phase="offseason",
        settings=SimpleNamespace(
            season_label="2030-31",
            regulation_minutes=48.0,
        ),
        players=players,
        teams={
            "CHI": Team(
                roster_player_ids=roster,
                active_player_ids=roster,
                inactive_player_ids=(),
                rotation=rotation,
            )
        },
        free_agent_player_ids=("FA1",),
    )

    offer = txn.normalized_offer(
        txn.FreeAgencyOffer(
            player_id="FA1",
            team_abbreviation="CHI",
            annual_salary=4_500_000.0,
            years=2,
            guaranteed=True,
        )
    )

    candidate = copy.copy(state)
    candidate.players = dict(state.players)
    candidate.teams = dict(state.teams)
    candidate.players["FA1"] = copy.deepcopy(state.players["FA1"])
    candidate.teams["CHI"] = copy.deepcopy(state.teams["CHI"])
    candidate.free_agent_player_ids = tuple(state.free_agent_player_ids)
    txn._apply_offer_to_candidate(candidate, offer)

    checks = txn._speculative_candidate_validator(
        candidate,
        offer,
        max_roster_size=18,
    )
    assert all(checks.values())

    broken = copy.deepcopy(candidate)
    broken.free_agent_player_ids = ("FA1",)
    try:
        txn._speculative_candidate_validator(
            broken,
            offer,
            max_roster_size=18,
        )
    except txn.FreeAgencyTransactionError:
        pass
    else:
        raise AssertionError("Fast validator failed to reject stale FA ownership.")

    full_calls = {"count": 0}
    fast_calls = {"count": 0}
    original_full = txn._default_state_validator
    original_fast = txn._speculative_candidate_validator

    def count_full(value):
        full_calls["count"] += 1
        return None

    def count_fast(value, resolved_offer, *, max_roster_size):
        fast_calls["count"] += 1
        return {}

    txn._default_state_validator = count_full
    txn._speculative_candidate_validator = count_fast
    try:
        pass_gate = lambda _state, _offer: {"status": "pass"}
        speculative = txn.build_free_agency_preview(
            state,
            offer,
            financial_gate=pass_gate,
            state_validator=None,
            _source_fingerprint="fixture-source",
            _defer_candidate_fingerprint=True,
        )
        assert speculative.can_commit
        assert fast_calls["count"] == 1
        assert full_calls["count"] == 0

        normal = txn.build_free_agency_preview(
            state,
            offer,
            financial_gate=pass_gate,
            state_validator=None,
            _source_fingerprint="fixture-source",
            _defer_candidate_fingerprint=False,
        )
        assert normal.can_commit
        assert full_calls["count"] == 1
    finally:
        txn._default_state_validator = original_full
        txn._speculative_candidate_validator = original_fast

    print("FRANCHISE V2 PHASE 1 SPECULATIVE PREVIEW VALIDATION CHECK PASSED")
    print("Touched-surface valid signing: PASS")
    print("Stale free-agent ownership rejection: PASS")
    print("Deferred speculative preview uses narrow validator: PASS")
    print("Normal/winning preview uses full validator: PASS")
    print("Production board validates complete source state once: CONTRACT LOCKED")
    print("Durable winner full league validation: PRESERVED")
    print("No franchise checkpoint was loaded or mutated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
