from __future__ import annotations

import copy
import inspect
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import franchise_free_agency_transaction_v1 as tx

VALIDATOR_VERSION = "franchise-free-agency-preview-performance-hotfix-validator-v1.0-2026-09-10"
EXPECTED_CLONE_VERSION = "franchise-free-agency-preview-copy-on-write-v1-2026-09-10"


@dataclass
class ToyContract:
    status: str
    salary: float | None
    years_remaining: int | None = None
    option_type: str = ""
    guaranteed: bool | None = None


@dataclass
class ToyPlayer:
    player_id: str
    player_name: str
    team_abbreviation: str
    roster_status: str
    two_way: bool
    contract: ToyContract


@dataclass
class ToyRotation:
    starter_ids: tuple[str, ...] = ()
    rotation_player_ids: tuple[str, ...] = ()
    minutes_targets: dict[str, float] = field(default_factory=dict)


@dataclass
class ToyTeam:
    roster_player_ids: tuple[str, ...]
    active_player_ids: tuple[str, ...]
    inactive_player_ids: tuple[str, ...]
    rotation: ToyRotation = field(default_factory=ToyRotation)


@dataclass
class ToySettings:
    season_label: str = "2027-28"


@dataclass
class ToyState:
    state_version: str = "toy"
    source_league_state_revision: int = 1
    source_transaction_count: int = 0
    transition_count: int = 0
    franchise_transaction_revision: int = 0
    phase: str = "offseason"
    settings: ToySettings = field(default_factory=ToySettings)
    players: dict[str, ToyPlayer] = field(default_factory=dict)
    teams: dict[str, ToyTeam] = field(default_factory=dict)
    free_agent_player_ids: tuple[str, ...] = ()
    # This emulates mature-season payloads that are irrelevant to a signing
    # preview but expensive to recursively clone.
    completed_games: dict[str, Any] = field(default_factory=dict)
    season_history: list[Any] = field(default_factory=list)


def make_state() -> ToyState:
    roster = tuple(f"P{i}" for i in range(1, 11))
    players = {
        player_id: ToyPlayer(
            player_id=player_id,
            player_name=player_id,
            team_abbreviation="CHI",
            roster_status="active_roster",
            two_way=False,
            contract=ToyContract("under_contract", 1_000_000.0, 1, "", True),
        )
        for player_id in roster
    }
    players["FA1"] = ToyPlayer(
        player_id="FA1",
        player_name="Free Agent",
        team_abbreviation="",
        roster_status="free_agent",
        two_way=False,
        contract=ToyContract("free_agent_pool", None),
    )
    players["OTHER"] = ToyPlayer(
        player_id="OTHER",
        player_name="Other",
        team_abbreviation="BOS",
        roster_status="active_roster",
        two_way=False,
        contract=ToyContract("under_contract", 2_000_000.0, 2, "", True),
    )
    teams = {
        "CHI": ToyTeam(roster, roster, ()),
        "BOS": ToyTeam(("OTHER",), ("OTHER",), ()),
    }
    # Make the unrelated mature-state payload large enough that accidental
    # global deepcopy is obvious while keeping the validator quick.
    completed_games = {
        f"G{i:04d}": {
            "home": "CHI",
            "away": "BOS",
            "box": [i, i + 1, i + 2, "x" * 128],
        }
        for i in range(1500)
    }
    season_history = [
        {"season": f"20{i:02d}-{(i + 1) % 100:02d}", "payload": list(range(50))}
        for i in range(40)
    ]
    return ToyState(
        players=players,
        teams=teams,
        free_agent_player_ids=("FA1",),
        completed_games=completed_games,
        season_history=season_history,
    )


def noop_validator(candidate: Any) -> None:
    assert "FA1" not in candidate.free_agent_player_ids
    assert "FA1" in candidate.teams["CHI"].roster_player_ids
    assert candidate.players["FA1"].team_abbreviation == "CHI"


def pass_gate(_state: Any, _offer: tx.FreeAgencyOffer) -> dict[str, Any]:
    return {"status": "pass", "reason": "performance-hotfix-validator"}


def main() -> int:
    state = make_state()
    source_fp = tx.free_agency_state_fingerprint(state)
    offer = tx.normalized_offer(
        tx.FreeAgencyOffer(
            player_id="FA1",
            team_abbreviation="CHI",
            annual_salary=5_000_000.0,
            years=2,
            guaranteed=True,
        )
    )

    sparse = tx._build_preview_candidate_state(
        state,
        offer,
        state_validator=noop_validator,
    )
    deep = tx._build_candidate_state(
        state,
        offer,
        state_validator=noop_validator,
    )
    preview = tx.build_free_agency_preview(
        state,
        offer,
        financial_gate=pass_gate,
        state_validator=noop_validator,
    )
    committed, result = tx.commit_free_agency_preview(
        state,
        preview,
        financial_gate=pass_gate,
        state_validator=noop_validator,
    )

    preview_source = inspect.getsource(tx.build_free_agency_preview)
    deep_source = inspect.getsource(tx._build_candidate_state)
    sparse_source = inspect.getsource(tx._build_preview_candidate_state)

    checks = {
        "preview_clone_version_current": getattr(tx, "FREE_AGENCY_PREVIEW_CLONE_VERSION", "") == EXPECTED_CLONE_VERSION,
        "preview_uses_copy_on_write_builder": "_build_preview_candidate_state" in preview_source,
        "preview_builder_avoids_global_deepcopy": "copy.deepcopy(state)" not in sparse_source,
        "durable_builder_retains_full_defensive_copy": "copy.deepcopy(state)" in deep_source,
        "preview_passes": preview.can_commit and preview.status == "pass",
        "preview_and_deep_candidate_fingerprints_match": tx.free_agency_state_fingerprint(sparse) == tx.free_agency_state_fingerprint(deep),
        "preview_fingerprint_matches_approved_preview": tx.free_agency_state_fingerprint(sparse) == preview.candidate_fingerprint,
        "source_fingerprint_unchanged": tx.free_agency_state_fingerprint(state) == source_fp,
        "preview_clones_target_player": sparse.players["FA1"] is not state.players["FA1"],
        "preview_clones_target_contract": sparse.players["FA1"].contract is not state.players["FA1"].contract,
        "preview_clones_target_team": sparse.teams["CHI"] is not state.teams["CHI"],
        "preview_shares_untouched_player_read_only": sparse.players["OTHER"] is state.players["OTHER"],
        "preview_shares_untouched_team_read_only": sparse.teams["BOS"] is state.teams["BOS"],
        "preview_shares_completed_game_history_read_only": sparse.completed_games is state.completed_games,
        "preview_shares_season_history_read_only": sparse.season_history is state.season_history,
        "durable_commit_defensively_copies_completed_games": committed.completed_games is not state.completed_games,
        "durable_commit_defensively_copies_season_history": committed.season_history is not state.season_history,
        "durable_commit_matches_preview": result.committed_fingerprint == preview.candidate_fingerprint,
        "durable_commit_does_not_mutate_source": tx.free_agency_state_fingerprint(state) == source_fp,
        "transaction_protocol_version_unchanged": tx.FREE_AGENCY_TRANSACTION_VERSION == "franchise-free-agency-transaction-v1-2026-08-13",
    }

    failed = [name for name, ok in checks.items() if not ok]
    report = {
        "version": VALIDATOR_VERSION,
        "preview_clone_version": getattr(tx, "FREE_AGENCY_PREVIEW_CLONE_VERSION", ""),
        "checks": checks,
        "failed_checks": failed,
        "passed": not failed,
    }
    print(json.dumps(report, indent=2))
    print()
    if failed:
        print("FRANCHISE FREE AGENCY PREVIEW PERFORMANCE HOTFIX V1 FAILED")
        return 1
    print("FRANCHISE FREE AGENCY PREVIEW PERFORMANCE HOTFIX V1 PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
