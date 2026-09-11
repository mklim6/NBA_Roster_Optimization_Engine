from __future__ import annotations

import copy
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

SRC = Path(__file__).resolve().parent
PROJECT = SRC.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_free_agency_transaction_v1 import (  # noqa: E402
    DEFAULT_MAX_ROSTER_SIZE,
    FREE_AGENCY_TRANSACTION_VERSION,
    FreeAgencyOffer,
    FreeAgencyTransactionError,
    build_free_agency_preview,
    commit_free_agency_preview,
    free_agency_state_fingerprint,
)
from simulation_league_state_v1 import (  # noqa: E402
    LeaguePhase,
    validate_simulation_league_state,
)

VALIDATOR_VERSION = (
    "franchise-free-agency-transaction-validator-v1-2026-08-13"
)
EXPECTED_ENGINE_VERSION = (
    "franchise-free-agency-transaction-v1-2026-08-13"
)
STANDARD_CHECKPOINT = (
    PROJECT
    / "outputs"
    / "runtime"
    / "franchise_mode_checkpoint_v1.pkl.gz"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_source_state() -> tuple[Any, str]:
    try:
        from simulation_franchise_checkpoint_v1 import (
            load_franchise_checkpoint,
        )

        checkpoint = load_franchise_checkpoint()
    except Exception:
        checkpoint = None

    if checkpoint is not None:
        state = getattr(checkpoint, "simulation_state", None)
        if state is not None:
            return state, "durable_checkpoint"

    from freeform_trade_machine_engine_v3 import load_runtime_data
    from mutable_league_state_v1 import create_league_state
    from simulation_league_state_v1 import create_simulation_league_state
    from state_runtime_adapter_v1 import build_state_runtime

    base_runtime = load_runtime_data()
    trade_state = create_league_state(base_runtime)
    runtime = build_state_runtime(base_runtime, trade_state)
    state = create_simulation_league_state(runtime, trade_state)
    return state, "fresh_read_only_state"


def choose_test_pair(state: Any) -> tuple[str, str]:
    rostered = {
        str(player_id)
        for team in state.teams.values()
        for player_id in team.roster_player_ids
    }
    free_agents = []
    for raw_id in state.free_agent_player_ids:
        player_id = str(raw_id)
        player = state.players.get(player_id)
        if player is None:
            continue
        if player_id in rostered:
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
    if not free_agents:
        raise AssertionError("No standard free agent is available for the read-only validator.")
    if not teams:
        raise AssertionError("No team has a structural V1 free-agency roster slot.")
    return sorted(free_agents)[0], teams[0]


def pass_gate(_state: Any, offer: FreeAgencyOffer) -> dict[str, Any]:
    return {
        "status": "pass",
        "reason": "validator-only explicit financial/CBA PASS",
        "payload": {
            "test_only": True,
            "annual_salary": offer.annual_salary,
        },
    }


def blocked_gate(_state: Any, _offer: FreeAgencyOffer) -> dict[str, Any]:
    return {
        "status": "blocked",
        "reason": "validator-only blocked financial route",
    }


def rotation_signature(state: Any, team: str) -> tuple[Any, ...]:
    rotation = state.teams[team].rotation
    return (
        tuple(rotation.starter_ids),
        tuple(rotation.rotation_player_ids),
        tuple(sorted(rotation.minutes_targets.items())),
        tuple(state.teams[team].active_player_ids),
    )


def main() -> int:
    checkpoint_hash_before = (
        sha256(STANDARD_CHECKPOINT)
        if STANDARD_CHECKPOINT.is_file()
        else ""
    )

    source_state, source_kind = load_source_state()
    source_hash_before = free_agency_state_fingerprint(source_state)

    test_state = copy.deepcopy(source_state)
    test_state.phase = LeaguePhase.OFFSEASON
    validate_simulation_league_state(test_state)

    player_id, team = choose_test_pair(test_state)
    player_name = str(test_state.players[player_id].player_name)
    roster_before = tuple(test_state.teams[team].roster_player_ids)
    free_agents_before = tuple(test_state.free_agent_player_ids)
    rotation_before = rotation_signature(test_state, team)
    contract_before = copy.deepcopy(test_state.players[player_id].contract)
    test_hash_before = free_agency_state_fingerprint(test_state)

    offer = FreeAgencyOffer(
        player_id=player_id,
        team_abbreviation=team,
        annual_salary=12_345_678.0,
        years=3,
        guaranteed=True,
    )

    no_gate = build_free_agency_preview(test_state, offer)
    blocked = build_free_agency_preview(
        test_state,
        offer,
        financial_gate=blocked_gate,
    )
    approved = build_free_agency_preview(
        test_state,
        offer,
        financial_gate=pass_gate,
    )

    candidate, result = commit_free_agency_preview(
        test_state,
        approved,
        financial_gate=pass_gate,
    )
    candidate_checks = validate_simulation_league_state(candidate)

    stale_state = copy.deepcopy(test_state)
    stale_state.source_transaction_count = int(
        getattr(stale_state, "source_transaction_count", 0)
    ) + 1
    stale_preview_rejected = False
    try:
        commit_free_agency_preview(
            stale_state,
            approved,
            financial_gate=pass_gate,
        )
    except FreeAgencyTransactionError:
        stale_preview_rejected = True

    blocked_commit_rejected = False
    try:
        commit_free_agency_preview(
            test_state,
            blocked,
            financial_gate=blocked_gate,
        )
    except FreeAgencyTransactionError:
        blocked_commit_rejected = True

    bad_salary = build_free_agency_preview(
        test_state,
        FreeAgencyOffer(
            player_id=player_id,
            team_abbreviation=team,
            annual_salary=-1.0,
            years=3,
        ),
        financial_gate=pass_gate,
    )
    bad_years = build_free_agency_preview(
        test_state,
        FreeAgencyOffer(
            player_id=player_id,
            team_abbreviation=team,
            annual_salary=1_000_000.0,
            years=6,
        ),
        financial_gate=pass_gate,
    )
    artificial_full_roster = build_free_agency_preview(
        test_state,
        offer,
        financial_gate=pass_gate,
        max_roster_size=len(roster_before),
    )

    source_hash_after = free_agency_state_fingerprint(source_state)
    test_hash_after = free_agency_state_fingerprint(test_state)
    checkpoint_hash_after = (
        sha256(STANDARD_CHECKPOINT)
        if STANDARD_CHECKPOINT.is_file()
        else ""
    )

    candidate_player = candidate.players[player_id]
    candidate_team = candidate.teams[team]
    candidate_contract = candidate_player.contract

    checks = {
        "validator_version_is_current": (
            VALIDATOR_VERSION
            == "franchise-free-agency-transaction-validator-v1-2026-08-13"
        ),
        "transaction_version_is_current": (
            FREE_AGENCY_TRANSACTION_VERSION == EXPECTED_ENGINE_VERSION
        ),
        "source_state_is_valid": bool(
            validate_simulation_league_state(test_state)
        ),
        "free_agent_and_team_pair_found": bool(player_id and team),
        "missing_financial_gate_cannot_commit": (
            no_gate.status == "manual_review" and not no_gate.can_commit
        ),
        "blocked_financial_gate_cannot_commit": (
            blocked.status == "blocked" and not blocked.can_commit
        ),
        "explicit_pass_gate_releases_preview": (
            approved.status == "pass" and approved.can_commit
        ),
        "approved_preview_is_non_mutating": (
            test_hash_before == free_agency_state_fingerprint(test_state)
        ),
        "candidate_state_is_valid": bool(candidate_checks),
        "candidate_removes_player_from_free_agents": (
            player_id not in candidate.free_agent_player_ids
        ),
        "candidate_adds_player_to_target_roster": (
            player_id in candidate_team.roster_player_ids
            and len(candidate_team.roster_player_ids)
            == len(roster_before) + 1
        ),
        "candidate_changes_player_ownership": (
            candidate_player.team_abbreviation == team
            and candidate_player.roster_status == "active_roster"
        ),
        "new_signing_starts_inactive": (
            player_id in candidate_team.inactive_player_ids
            and player_id not in candidate_team.active_player_ids
        ),
        "existing_rotation_is_untouched": (
            rotation_before == rotation_signature(candidate, team)
        ),
        "contract_terms_are_applied_exactly": (
            candidate_contract.status == "under_contract"
            and math.isclose(float(candidate_contract.salary), 12_345_678.0)
            and int(candidate_contract.years_remaining) == 3
            and candidate_contract.option_type == ""
            and candidate_contract.guaranteed is True
        ),
        "source_contract_is_unchanged": (
            test_state.players[player_id].contract == contract_before
        ),
        "source_roster_and_free_agents_are_unchanged": (
            tuple(test_state.teams[team].roster_player_ids) == roster_before
            and tuple(test_state.free_agent_player_ids) == free_agents_before
        ),
        "commit_exactly_matches_approved_preview": (
            result.committed_fingerprint == approved.candidate_fingerprint
            and free_agency_state_fingerprint(candidate)
            == approved.candidate_fingerprint
        ),
        "stale_preview_is_rejected": stale_preview_rejected,
        "blocked_preview_commit_is_rejected": blocked_commit_rejected,
        "negative_salary_is_rejected": not bad_salary.can_commit,
        "six_year_offer_is_rejected": not bad_years.can_commit,
        "full_roster_is_rejected": not artificial_full_roster.can_commit,
        "durable_source_state_is_unchanged": source_hash_before == source_hash_after,
        "test_source_state_is_unchanged": test_hash_before == test_hash_after,
        "checkpoint_hash_is_unchanged": (
            checkpoint_hash_before == checkpoint_hash_after
        ),
    }

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "validator": VALIDATOR_VERSION,
        "transaction_version": FREE_AGENCY_TRANSACTION_VERSION,
        "source_kind": source_kind,
        "season": str(test_state.settings.season_label),
        "test_player": player_name,
        "test_player_id": player_id,
        "test_team": team,
        "roster_before": len(roster_before),
        "roster_after": len(candidate_team.roster_player_ids),
        "checks": checks,
        "failed_checks": failed,
        "checkpoint_present": STANDARD_CHECKPOINT.is_file(),
        "passed": not failed,
    }

    print("=" * 104)
    print("FRANCHISE FREE AGENCY TRANSACTION V1 VALIDATION")
    print("=" * 104)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print()
    print("READ-ONLY TRANSACTION SAMPLE")
    print(f"  Source: {source_kind}")
    print(f"  Season: {test_state.settings.season_label}")
    print(f"  Player: {player_name} ({player_id})")
    print(f"  Team: {team}")
    print(f"  Roster: {len(roster_before)} -> {len(candidate_team.roster_player_ids)}")
    print("  Live checkpoint write: NOT PERFORMED")
    print()
    print(json.dumps(report, indent=2, default=str))

    if failed:
        raise AssertionError(
            "Franchise Free Agency Transaction V1 failed: "
            + ", ".join(failed)
        )

    print()
    print("FRANCHISE FREE AGENCY TRANSACTION V1 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no live roster, contract, free-agent, CPU, trade, or checkpoint mutation was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
