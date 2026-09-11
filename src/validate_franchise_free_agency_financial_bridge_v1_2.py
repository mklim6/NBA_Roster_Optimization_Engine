from __future__ import annotations

import copy
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_free_agency_transaction_v1 import (
    DEFAULT_MAX_ROSTER_SIZE,
    FreeAgencyOffer,
    free_agency_state_fingerprint,
)
from franchise_free_agency_transaction_v1_1 import (
    FREE_AGENCY_TRANSACTION_V1_1_VERSION,
    FreeAgencyCapSpaceGateConfig,
    build_cap_space_preview,
    evaluate_cap_space_gate,
)
from franchise_free_agency_financial_bridge_v1_2 import (
    FREE_AGENCY_CANONICAL_ANCHOR_SEASON,
    FREE_AGENCY_CANONICAL_RUNTIME_MODULE,
    FREE_AGENCY_CANONICAL_SOURCE,
    FREE_AGENCY_FINANCIAL_BRIDGE_VERSION,
    UNSUPPORTED_EXCEPTION_MECHANISMS,
    build_live_financial_free_agency_preview,
    evaluate_live_free_agency_financial_gate,
    resolve_free_agency_financial_environment,
)
from simulation_franchise_checkpoint_v1 import (
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)
from simulation_league_state_v1 import (
    LeaguePhase,
    validate_simulation_league_state,
)

VALIDATOR_VERSION = (
    "franchise-free-agency-financial-bridge-validator-v1.2-2026-08-14"
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def choose_test_pair(state: Any) -> tuple[str, str]:
    rostered = {
        str(player_id)
        for team_state in state.teams.values()
        for player_id in team_state.roster_player_ids
    }
    free_agents: list[str] = []
    for raw_id in getattr(state, "free_agent_player_ids", ()):
        player_id = str(raw_id)
        player = state.players.get(player_id)
        if player is None or player_id in rostered:
            continue
        if bool(getattr(player, "two_way", False)):
            continue
        if str(getattr(player, "team_abbreviation", "") or "").strip():
            continue
        status = str(getattr(player, "roster_status", "") or "").strip().lower()
        if status not in {"free_agent", "free_agent_pool"}:
            continue
        free_agents.append(player_id)

    teams = [
        team
        for team, team_state in sorted(state.teams.items())
        if len(team_state.roster_player_ids) < DEFAULT_MAX_ROSTER_SIZE
    ]
    if not free_agents or not teams:
        raise AssertionError("No read-only V1.2 free-agent/team sample is available.")
    return sorted(free_agents)[0], teams[0]


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
    season_label: str


@dataclass
class ToyState:
    settings: ToySettings
    phase: str
    players: dict[str, ToyPlayer]
    teams: dict[str, ToyTeam]
    free_agent_player_ids: tuple[str, ...]
    state_version: str = "toy-v1.2"
    source_league_state_revision: int = 1
    source_transaction_count: int = 0
    transition_count: int = 0
    franchise_transaction_revision: int = 0


def toy_state(*, season: str, payroll_salary: float) -> ToyState:
    roster = ("P1", "P2")
    players = {
        "P1": ToyPlayer(
            "P1", "Roster One", "ATL", "active_roster", False,
            ToyContract("under_contract", payroll_salary),
        ),
        "P2": ToyPlayer(
            "P2", "Roster Two", "ATL", "active_roster", False,
            ToyContract("under_contract", payroll_salary),
        ),
        "FA1": ToyPlayer(
            "FA1", "Test Free Agent", "", "free_agent", False,
            ToyContract("free_agent_pool", None),
        ),
    }
    return ToyState(
        settings=ToySettings(season),
        phase="offseason",
        players=players,
        teams={
            "ATL": ToyTeam(
                roster_player_ids=roster,
                active_player_ids=roster,
                inactive_player_ids=(),
            )
        },
        free_agent_player_ids=("FA1",),
    )


def toy_validator(state: ToyState) -> None:
    if "FA1" not in state.players:
        raise AssertionError("Toy free agent missing")
    if "ATL" not in state.teams:
        raise AssertionError("Toy team missing")


def main() -> int:
    checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    before_hash = sha256(checkpoint_path) if checkpoint_path.exists() else ""
    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise AssertionError("Durable franchise checkpoint is unavailable.")

    source_state = checkpoint.simulation_state
    validate_simulation_league_state(source_state)
    source_fp = free_agency_state_fingerprint(source_state)

    test_state = copy.deepcopy(source_state)
    test_state.phase = LeaguePhase.OFFSEASON
    validate_simulation_league_state(test_state)
    player_id, team = choose_test_pair(test_state)
    offer = FreeAgencyOffer(
        player_id=player_id,
        team_abbreviation=team,
        annual_salary=1_500_000.0,
        years=1,
        guaranteed=True,
    )

    environment = resolve_free_agency_financial_environment(test_state)

    canonical_module = __import__(FREE_AGENCY_CANONICAL_RUNTIME_MODULE)
    direct_runtime = canonical_module.load_runtime_data()
    direct_cap = float(canonical_module.rule_number(direct_runtime, "salary_cap"))

    automatic_gate = evaluate_live_free_agency_financial_gate(test_state, offer)
    explicit_gate = evaluate_cap_space_gate(
        test_state,
        offer,
        config=FreeAgencyCapSpaceGateConfig(
            salary_cap=direct_cap,
            season_label=FREE_AGENCY_CANONICAL_ANCHOR_SEASON,
            source=FREE_AGENCY_CANONICAL_SOURCE,
            allow_zero_salary_rows=False,
        ),
    )
    auto_preview = build_live_financial_free_agency_preview(
        test_state,
        offer,
        state_validator=validate_simulation_league_state,
    )
    explicit_preview = build_cap_space_preview(
        test_state,
        offer,
        config=FreeAgencyCapSpaceGateConfig(
            salary_cap=direct_cap,
            season_label=FREE_AGENCY_CANONICAL_ANCHOR_SEASON,
            source=FREE_AGENCY_CANONICAL_SOURCE,
            allow_zero_salary_rows=False,
        ),
        state_validator=validate_simulation_league_state,
    )

    cheap = toy_state(
        season=FREE_AGENCY_CANONICAL_ANCHOR_SEASON,
        payroll_salary=1_000_000.0,
    )
    cheap_offer = FreeAgencyOffer("FA1", "ATL", 1_000_000.0, 1)
    cheap_preview = build_live_financial_free_agency_preview(
        cheap,
        cheap_offer,
        state_validator=toy_validator,
    )

    expensive = toy_state(
        season=FREE_AGENCY_CANONICAL_ANCHOR_SEASON,
        payroll_salary=direct_cap,
    )
    expensive_gate = evaluate_live_free_agency_financial_gate(
        expensive,
        cheap_offer,
    )

    future = toy_state(season="2032-33", payroll_salary=1_000_000.0)
    future_gate = evaluate_live_free_agency_financial_gate(future, cheap_offer)
    future_preview = build_live_financial_free_agency_preview(
        future,
        cheap_offer,
        state_validator=toy_validator,
    )

    after_hash = sha256(checkpoint_path)
    checks = {
        "validator_version_is_current": VALIDATOR_VERSION.endswith("2026-08-14"),
        "financial_bridge_version_is_current": (
            FREE_AGENCY_FINANCIAL_BRIDGE_VERSION
            == "franchise-free-agency-financial-bridge-v1.3-modeled-future-market-2026-08-18"
        ),
        "v1_1_transaction_engine_is_preserved": (
            FREE_AGENCY_TRANSACTION_V1_1_VERSION
            == "franchise-free-agency-transaction-v1.1-2026-08-14"
        ),
        "durable_checkpoint_exists": checkpoint_path.exists(),
        "durable_source_state_is_valid": True,
        "validator_uses_isolated_offseason_copy": (
            str(getattr(getattr(test_state, "phase", ""), "value", test_state.phase))
            == "offseason"
        ),
        "canonical_runtime_module_is_v3": (
            environment.source_module == FREE_AGENCY_CANONICAL_RUNTIME_MODULE
        ),
        "canonical_anchor_environment_passes": environment.status == "pass",
        "canonical_anchor_season_matches": (
            environment.season_label == FREE_AGENCY_CANONICAL_ANCHOR_SEASON
        ),
        "canonical_salary_cap_auto_resolves": (
            environment.salary_cap is not None
            and abs(float(environment.salary_cap) - direct_cap) <= 0.01
        ),
        "automatic_gate_matches_explicit_cap_gate": (
            automatic_gate.status == explicit_gate.status
            and automatic_gate.reason == explicit_gate.reason
        ),
        "automatic_preview_matches_explicit_commit_eligibility": (
            auto_preview.status == explicit_preview.status
            and auto_preview.can_commit == explicit_preview.can_commit
        ),
        "pure_cap_space_toy_preview_passes": (
            cheap_preview.status == "pass" and cheap_preview.can_commit
        ),
        "pure_cap_space_route_is_recorded": (
            (cheap_preview.financial_gate.payload or {}).get("route")
            == "pure_cap_space_only"
        ),
        "over_cap_case_remains_manual_review": (
            expensive_gate.status == "manual_review"
        ),
        "future_season_remains_manual_review": future_gate.status == "manual_review",
        "future_season_preview_cannot_commit": not future_preview.can_commit,
        "no_exception_rights_are_inferred": (
            (cheap_preview.financial_gate.payload or {}).get("exceptions_inferred")
            is False
            and set((cheap_preview.financial_gate.payload or {}).get(
                "unsupported_exception_mechanisms", []
            )) == set(UNSUPPORTED_EXCEPTION_MECHANISMS)
        ),
        "source_state_is_unchanged": (
            source_fp == free_agency_state_fingerprint(source_state)
        ),
        "validator_did_not_write_checkpoint": before_hash == after_hash,
    }
    failed = [name for name, passed in checks.items() if not passed]

    print("=" * 108)
    print("FRANCHISE FREE AGENCY FINANCIAL / CBA BRIDGE V1.2 VALIDATION")
    print("=" * 108)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print()
    print("LIVE FINANCIAL SOURCE")
    print(f"  Season: {environment.season_label}")
    print(f"  Source: {environment.source}")
    print(f"  Runtime: {environment.source_module}")
    print(f"  Trade-date evidence: {environment.source_trade_date or '-'}")
    print(f"  Salary cap: ${float(environment.salary_cap or 0):,.0f}")
    print(f"  First apron: ${float(environment.first_apron or 0):,.0f}")
    print(f"  Second apron: ${float(environment.second_apron or 0):,.0f}")
    print()
    print("READ-ONLY LIVE PREVIEW SAMPLE")
    print(f"  Player: {test_state.players[player_id].player_name} ({player_id})")
    print(f"  Team: {team}")
    print(f"  Auto financial status: {automatic_gate.status}")
    print(f"  Auto preview status: {auto_preview.status}")
    print(f"  Auto commit eligible: {auto_preview.can_commit}")
    print("  Live signing: NOT PERFORMED")
    print()
    print(json.dumps({
        "validator": VALIDATOR_VERSION,
        "bridge": FREE_AGENCY_FINANCIAL_BRIDGE_VERSION,
        "environment": environment.__dict__,
        "checks": checks,
        "failed_checks": failed,
        "checkpoint_hash_before": before_hash,
        "checkpoint_hash_after": after_hash,
        "passed": not failed,
    }, indent=2, default=str))

    if failed:
        raise AssertionError(
            "Free Agency Financial Bridge V1.2 failed: " + ", ".join(failed)
        )

    print()
    print("FRANCHISE FREE AGENCY FINANCIAL / CBA BRIDGE V1.2 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no live signing or checkpoint write was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
