from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_free_agency_transaction_v1 import (
    DEFAULT_MAX_ROSTER_SIZE,
    FREE_AGENCY_TRANSACTION_VERSION,
    FreeAgencyOffer,
    free_agency_state_fingerprint,
)
from franchise_free_agency_transaction_v1_1 import (
    FREE_AGENCY_CAP_SPACE_GATE_VERSION,
    FREE_AGENCY_DURABLE_COMMIT_VERSION,
    FREE_AGENCY_HISTORY_ATTR,
    FREE_AGENCY_REVISION_ATTR,
    FREE_AGENCY_TRANSACTION_V1_1_VERSION,
    FreeAgencyCapSpaceGateConfig,
    build_cap_space_preview,
    build_free_agency_durable_candidate,
    cap_space_gate,
    checkpoint_contract_report,
    free_agency_durable_state_fingerprint,
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
    "franchise-free-agency-transaction-validator-v1.1.2-2026-08-14"
)
VALIDATOR_HOTFIX_VERSION = (
    "franchise-free-agency-transaction-validator-checkpoint-contract-hotfix-v1-2026-08-14"
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def choose_test_pair(state):
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
        status = str(
            getattr(player, "roster_status", "") or ""
        ).strip().lower()
        if status not in {"free_agent", "free_agent_pool"}:
            continue
        free_agents.append(player_id)

    teams = [
        team
        for team, team_state in sorted(state.teams.items())
        if len(team_state.roster_player_ids) < DEFAULT_MAX_ROSTER_SIZE
    ]
    if not free_agents:
        raise AssertionError(
            "No standard free agent exists in the durable checkpoint."
        )
    if not teams:
        raise AssertionError(
            "No team has an open V1.1 roster slot."
        )
    return sorted(free_agents)[0], teams[0]


def main() -> int:
    checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    before_hash = (
        sha256(checkpoint_path)
        if checkpoint_path.exists()
        else ""
    )
    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise AssertionError("Durable checkpoint is unavailable.")

    source_state = checkpoint.simulation_state
    validate_simulation_league_state(source_state)
    source_v1_fp_before = free_agency_state_fingerprint(source_state)
    source_durable_fp_before = (
        free_agency_durable_state_fingerprint(source_state)
    )
    source_history_before = copy.deepcopy(
        getattr(source_state, FREE_AGENCY_HISTORY_ATTR, []) or []
    )
    source_revision_before = int(
        getattr(source_state, FREE_AGENCY_REVISION_ATTR, 0) or 0
    )

    # V1.1.1 hotfix: validate free-agency mechanics on an isolated OFFSEASON
    # deepcopy, exactly like the already-passing V1 validator. Never mutate
    # the durable checkpoint merely to make a validator preview eligible.
    test_state = copy.deepcopy(source_state)
    source_phase = getattr(source_state, "phase", "")
    source_phase_value = getattr(source_phase, "value", source_phase)
    test_state.phase = LeaguePhase.OFFSEASON
    validate_simulation_league_state(test_state)

    player_id, team = choose_test_pair(test_state)
    player = test_state.players[player_id]
    player_name = player.player_name

    settings = getattr(test_state, "settings", None)
    season = str(getattr(settings, "season_label", ""))
    test_config = FreeAgencyCapSpaceGateConfig(
        salary_cap=10_000_000_000.0,
        season_label=season,
        source="validator_test_threshold_not_live_cba",
        allow_zero_salary_rows=True,
    )
    offer = FreeAgencyOffer(
        player_id=player_id,
        team_abbreviation=team,
        annual_salary=1_500_000.0,
        years=1,
        guaranteed=True,
    )

    preview = build_cap_space_preview(
        test_state,
        offer,
        config=test_config,
        state_validator=validate_simulation_league_state,
    )
    missing_threshold_preview = build_cap_space_preview(
        test_state,
        offer,
        config=FreeAgencyCapSpaceGateConfig(
            salary_cap=0,
            season_label=season,
            source="missing",
        ),
        state_validator=validate_simulation_league_state,
    )
    wrong_season_preview = build_cap_space_preview(
        test_state,
        offer,
        config=FreeAgencyCapSpaceGateConfig(
            salary_cap=10_000_000_000.0,
            season_label="1900-01",
            source="wrong-season-test",
            allow_zero_salary_rows=True,
        ),
        state_validator=validate_simulation_league_state,
    )

    if not preview.can_commit or preview.status != "pass":
        raise AssertionError(
            "Validator-only cap-space preview did not PASS on the isolated "
            "OFFSEASON copy. status="
            f"{preview.status!r}; message={preview.message!r}; "
            f"checks={preview.checks!r}; gate={preview.financial_gate!r}"
        )

    candidate, commit, revision, transaction_id = (
        build_free_agency_durable_candidate(
            test_state,
            preview,
            financial_gate=cap_space_gate(test_config),
            state_validator=validate_simulation_league_state,
        )
    )
    validate_simulation_league_state(candidate)

    stale_state = copy.deepcopy(test_state)
    stale_state.source_transaction_count = int(
        getattr(stale_state, "source_transaction_count", 0) or 0
    ) + 1
    stale_rejected = False
    try:
        build_free_agency_durable_candidate(
            stale_state,
            preview,
            financial_gate=cap_space_gate(test_config),
            state_validator=validate_simulation_league_state,
        )
    except Exception:
        stale_rejected = True

    contract_report = checkpoint_contract_report()
    after_hash = sha256(checkpoint_path)
    history = getattr(candidate, FREE_AGENCY_HISTORY_ATTR, []) or []
    test_source_revision = int(
        getattr(test_state, FREE_AGENCY_REVISION_ATTR, 0) or 0
    )
    test_source_history_len = len(
        getattr(test_state, FREE_AGENCY_HISTORY_ATTR, []) or []
    )
    expected_revision = test_source_revision + 1
    expected_transaction_id = f"FATX-{expected_revision:04d}"

    source_unchanged = (
        free_agency_state_fingerprint(source_state)
        == source_v1_fp_before
        and free_agency_durable_state_fingerprint(source_state)
        == source_durable_fp_before
        and copy.deepcopy(
            getattr(source_state, FREE_AGENCY_HISTORY_ATTR, []) or []
        )
        == source_history_before
        and int(
            getattr(source_state, FREE_AGENCY_REVISION_ATTR, 0) or 0
        )
        == source_revision_before
    )

    checks = {
        "validator_version_is_current": (
            VALIDATOR_VERSION
            == "franchise-free-agency-transaction-validator-v1.1.2-2026-08-14"
        ),
        "validator_hotfix_version_is_current": (
            VALIDATOR_HOTFIX_VERSION.endswith("2026-08-14")
        ),
        "base_v1_transaction_is_preserved": (
            FREE_AGENCY_TRANSACTION_VERSION
            == "franchise-free-agency-transaction-v1-2026-08-13"
        ),
        "v1_1_engine_is_preserved": (
            FREE_AGENCY_TRANSACTION_V1_1_VERSION
            == "franchise-free-agency-transaction-v1.1-2026-08-14"
        ),
        "cap_space_gate_version_is_current": (
            FREE_AGENCY_CAP_SPACE_GATE_VERSION.endswith("2026-08-14")
        ),
        "durable_commit_version_is_current": (
            FREE_AGENCY_DURABLE_COMMIT_VERSION.endswith("2026-08-14")
        ),
        "durable_checkpoint_exists": checkpoint_path.exists(),
        "durable_checkpoint_loads": checkpoint is not None,
        "durable_source_state_is_valid": True,
        "validator_uses_isolated_offseason_copy": (
            str(getattr(test_state.phase, "value", test_state.phase)).lower()
            == "offseason"
            and str(source_phase_value).lower()
            == str(getattr(source_state.phase, "value", source_state.phase)).lower()
        ),
        "cap_space_test_preview_passes": (
            preview.can_commit and preview.status == "pass"
        ),
        "cap_space_gate_records_pure_cap_space_route": (
            preview.financial_gate.payload.get("route")
            == "pure_cap_space_only"
        ),
        "missing_cap_threshold_never_commits": (
            not missing_threshold_preview.can_commit
        ),
        "wrong_season_threshold_never_commits": (
            not wrong_season_preview.can_commit
        ),
        "candidate_state_is_valid": True,
        "candidate_adds_free_agency_history": (
            len(history) == test_source_history_len + 1
        ),
        "candidate_free_agency_revision_increments": (
            revision == expected_revision
            and getattr(candidate, FREE_AGENCY_REVISION_ATTR, 0)
            == expected_revision
        ),
        "candidate_transaction_id_is_stable": (
            transaction_id == expected_transaction_id
            and history[-1]["transaction_id"] == transaction_id
        ),
        "candidate_history_records_financial_gate": (
            history[-1]["financial_gate_status"] == "pass"
        ),
        "durable_source_state_is_unchanged": source_unchanged,
        "durable_candidate_fingerprint_is_distinct": (
            free_agency_durable_state_fingerprint(candidate)
            != free_agency_durable_state_fingerprint(test_state)
        ),
        "stale_preview_is_rejected": stale_rejected,
        "checkpoint_loader_accepts_zero_argument_call": (
            contract_report["load_is_zero_argument"]
        ),
        "checkpoint_save_accepts_simulation_state": (
            contract_report["save_accepts_simulation_state"]
        ),
        "checkpoint_save_accepts_trade_state": (
            contract_report["save_accepts_trade_state"]
        ),
        "checkpoint_save_accepts_reason": (
            contract_report["save_accepts_reason"]
        ),
        "validator_did_not_write_checkpoint": before_hash == after_hash,
    }
    failed = [name for name, passed in checks.items() if not passed]

    print("=" * 108)
    print("FRANCHISE FREE AGENCY TRANSACTION V1.1.2 VALIDATION")
    print("=" * 108)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print()
    print("READ-ONLY LIVE CHECKPOINT")
    print(f"  Season: {season}")
    print(f"  Durable source phase: {source_phase_value}")
    print("  Validator test phase: offseason (isolated deepcopy)")
    print(f"  Player: {player_name} ({player_id})")
    print(f"  Team: {team}")
    print(f"  Candidate transaction: {transaction_id}")
    print("  Durable commit during validator: NOT PERFORMED")
    print()
    report = {
        "validator": VALIDATOR_VERSION,
        "validator_hotfix": VALIDATOR_HOTFIX_VERSION,
        "engine": FREE_AGENCY_TRANSACTION_V1_1_VERSION,
        "season": season,
        "source_phase": str(source_phase_value),
        "test_phase": "offseason",
        "test_player": player_name,
        "test_player_id": player_id,
        "test_team": team,
        "transaction_id": transaction_id,
        "checks": checks,
        "failed_checks": failed,
        "checkpoint_hash_before": before_hash,
        "checkpoint_hash_after": after_hash,
        "passed": not failed,
    }
    print(json.dumps(report, indent=2))
    if failed:
        raise AssertionError(
            "Free Agency Transaction V1.1.2 failed: "
            + ", ".join(failed)
        )
    print()
    print("FRANCHISE FREE AGENCY TRANSACTION V1.1.2 VALIDATION PASSED")
    print(
        "READ-ONLY VALIDATION: no live signing or durable checkpoint write "
        "was performed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
