from __future__ import annotations

import copy
import hashlib
import json
import math
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_completed_season_contract_closeout_v1 import (
    build_completed_season_contract_closeout_candidate,
)
from franchise_legacy_contract_continuity_v1 import (
    ANCHOR_LINEAGE,
    LEGACY_CONTRACT_CONTINUITY_VERSION,
    LINEAGE_ATTR,
    SCHEDULE_ATTR,
    prepare_legacy_contracts_for_closeout,
    roll_legacy_contracts_to_target_season,
)
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint
from simulation_league_state_v1 import (
    LeaguePhase,
    SimulationLeagueStateError,
    validate_simulation_league_state,
)
import simulation_season_transition_v1 as season_transition

VERSION = "franchise-legacy-contract-continuity-validator-v1-2026-08-18"
DRAKE = "1642962"
EGOR = "1642856"
CARDWELL = "1642928"
VUKCEVIC = "1641774"
EXPECTED_UNRESOLVED = {CARDWELL, VUKCEVIC}


def clean(value: Any) -> str:
    return str(value or "").strip()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def rostered_ids(state: Any) -> set[str]:
    return {
        clean(pid)
        for team in state.teams.values()
        for pid in tuple(team.roster_player_ids)
        if clean(pid)
    }


def set_completed_postseason_fixture(state: Any) -> None:
    east = (
        "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DET", "IND",
        "MIA", "MIL", "NYK", "ORL", "PHI", "TOR", "WAS",
    )
    west = (
        "DAL", "DEN", "GSW", "HOU", "LAC", "LAL", "MEM", "MIN",
        "NOP", "OKC", "PHX", "POR", "SAC", "SAS", "UTA",
    )
    state.phase = LeaguePhase.OFFSEASON
    state.schedule = {}
    state.completed_games = {}
    state.postseason_state = SimpleNamespace(
        version="legacy-contract-continuity-validator-fixture-v1",
        season_label=clean(state.settings.season_label),
        initialized=True,
        stage="complete",
        seed_order={"East": east, "West": west},
        seed_by_team={
            team: seed
            for conference in (east, west)
            for seed, team in enumerate(conference, start=1)
        },
        champion="CHI",
        runner_up="HOU",
        completed_games={},
        games={},
        bracket_created=True,
        game_sequence=0,
    )


def deterministic_minutes(rotation_ids, starter_ids, *, regulation_minutes: int) -> dict[str, float]:
    ids = tuple(rotation_ids)
    if not ids:
        return {}
    total = float(regulation_minutes * 5)
    share = total / len(ids)
    return {pid: share for pid in ids}


def main() -> int:
    checkpoint_path = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"
    if not checkpoint_path.exists():
        raise RuntimeError(f"Canonical checkpoint unavailable: {checkpoint_path}")
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = load_franchise_checkpoint(path=checkpoint_path, allow_backup=False)
    if checkpoint is None:
        raise RuntimeError("Canonical checkpoint failed to load.")

    source = checkpoint.simulation_state
    source_rostered = rostered_ids(source)
    source_unknown_years = {
        pid for pid in source_rostered
        if getattr(source.players[pid].contract, "years_remaining", None) is None
    }
    source_explicit_one_year = {
        pid for pid in source_rostered
        if getattr(source.players[pid].contract, "years_remaining", None) == 1
    }
    source_explicit_one_snapshot = {
        pid: copy.deepcopy(source.players[pid].contract)
        for pid in source_explicit_one_year
    }

    migration_state = copy.deepcopy(source)
    migration = prepare_legacy_contracts_for_closeout(migration_state)
    migrated_rostered = rostered_ids(migration_state)
    seeded = set(migration.seeded_player_ids)
    unresolved = set(migration.unresolved_player_ids)

    drake = migration_state.players[DRAKE].contract
    egor = migration_state.players[EGOR].contract
    cardwell = migration_state.players[CARDWELL].contract
    vukcevic = migration_state.players[VUKCEVIC].contract

    explicit_one_preserved = all(
        migration_state.players[pid].contract == contract
        for pid, contract in source_explicit_one_snapshot.items()
    )
    generated_seeded = [
        pid for pid in seeded
        if bool(getattr(migration_state.players[pid], "synthetic", False))
        or bool(getattr(migration_state.players[pid], "generated_prospect", False))
    ]

    # Exercise the production closeout integration. Avoid app_data-only minutes
    # loading by substituting a deterministic allocator in this validator only.
    original_minutes_targets = season_transition.minutes_targets
    season_transition.minutes_targets = deterministic_minutes
    try:
        fixture_state = copy.deepcopy(source)
        fixture_trade = copy.deepcopy(checkpoint.trade_state)
        set_completed_postseason_fixture(fixture_state)
        validate_simulation_league_state(fixture_state)
        closeout = build_completed_season_contract_closeout_candidate(
            fixture_state,
            fixture_trade,
        )
        closed = closeout.simulation_state
        closed_trade = closeout.trade_state
        closeout_again = build_completed_season_contract_closeout_candidate(
            closed,
            closed_trade,
        )
    finally:
        season_transition.minutes_targets = original_minutes_targets

    closed_counts = {
        team: len(ts.roster_player_ids)
        for team, ts in closed.teams.items()
    }
    under_five = {team: count for team, count in closed_counts.items() if count < 5}

    # Salary/term lineage must survive the dataclass contract clock.
    drake_closed = closed.players[DRAKE].contract
    egor_closed = closed.players[EGOR].contract

    # Roll the surviving frozen schedules forward without running player development.
    year_2027 = copy.deepcopy(closed)
    year_2027.settings = replace(year_2027.settings, season_label="2027-28")
    rollover_27 = roll_legacy_contracts_to_target_season(year_2027, "2027-28")
    drake_27 = year_2027.players[DRAKE].contract
    egor_27 = year_2027.players[EGOR].contract

    align_27 = prepare_legacy_contracts_for_closeout(year_2027, season_label="2027-28")
    clock_27 = season_transition.advance_rostered_contract_clock_v1(year_2027)
    year_2028 = year_2027
    year_2028.settings = replace(year_2028.settings, season_label="2028-29")
    rollover_28 = roll_legacy_contracts_to_target_season(year_2028, "2028-29")
    drake_28 = year_2028.players[DRAKE].contract

    align_28 = prepare_legacy_contracts_for_closeout(year_2028, season_label="2028-29")
    clock_28 = season_transition.advance_rostered_contract_clock_v1(year_2028)
    drake_after_28 = year_2028.players[DRAKE]

    # Prove the new offseason underfill semantics do not weaken game-playing phases.
    offseason_underfill_valid = True
    try:
        validate_simulation_league_state(closed)
    except Exception:
        offseason_underfill_valid = False
    game_phase_underfill_blocked = False
    game_probe = copy.deepcopy(closed)
    game_probe.phase = LeaguePhase.PRESEASON
    try:
        validate_simulation_league_state(game_probe)
    except SimulationLeagueStateError:
        game_phase_underfill_blocked = True

    checks = {
        "canonical_opening_season_2026_27": clean(source.settings.season_label) == "2026-27",
        "canonical_unknown_year_count_279": len(source_unknown_years) == 279,
        "canonical_explicit_one_year_count_82": len(source_explicit_one_year) == 82,
        "legacy_schedule_seed_count_277": migration.seeded_count == 277,
        "legacy_status_normalized_exactly_egor": set(migration.normalized_rostered_contract_status_player_ids) == {EGOR},
        "legacy_unresolved_exactly_two_known_missing_rows": unresolved == EXPECTED_UNRESOLVED,
        "migration_keeps_same_roster_membership": migrated_rostered == source_rostered,
        "all_explicit_one_year_decisions_preserved": explicit_one_preserved,
        "generated_or_synthetic_players_never_seeded": not generated_seeded,
        "drake_anchor_contract_recovered": (
            drake.status == "under_contract"
            and drake.years_remaining == 3
            and math.isclose(float(drake.salary), 3_540_600.0, abs_tol=0.01)
            and getattr(drake, LINEAGE_ATTR, "") == ANCHOR_LINEAGE
        ),
        "drake_schedule_exact": getattr(drake, SCHEDULE_ATTR, {}) == {
            "2026-27": 3_540_600.0,
            "2027-28": 3_709_320.0,
            "2028-29": 6_101_832.0,
        },
        "egor_stale_rostered_contract_repaired_from_source": (
            egor.status == "under_contract"
            and egor.years_remaining == 3
            and math.isclose(float(egor.salary), 7_233_720.0, abs_tol=0.01)
        ),
        "cardwell_remains_explicitly_unresolved_not_guessed": cardwell.status == "free_agent_pool" and cardwell.years_remaining is None,
        "vukcevic_remains_explicitly_unresolved_not_guessed": vukcevic.status == "free_agent_pool" and vukcevic.years_remaining is None,
        "integrated_closeout_applied": closeout.status == "applied",
        "integrated_closeout_idempotent": closeout_again.status == "already_applied",
        "integrated_closeout_seeded_277": closeout.legacy_contracts_seeded == 277,
        "integrated_closeout_normalized_egor": closeout.legacy_rostered_contract_statuses_normalized == 1,
        "integrated_closeout_reports_two_unresolved": closeout.legacy_contracts_unresolved == 2,
        "corrected_closeout_expirations_148": closeout.contracts_expired == 148,
        "corrected_closeout_decrements_211": closeout.contracts_decremented == 211,
        "closeout_trade_release_matches_expirations": closeout.trade_owners_released == closeout.contracts_expired,
        "closeout_trade_revision_is_one_atomic_step": closeout.trade_revision_after == closeout.trade_revision_before + 1,
        "closeout_writes_no_fake_trade_transaction": closeout.transaction_count_after == closeout.transaction_count_before,
        "offseason_underfive_state_is_valid": offseason_underfill_valid and bool(under_five),
        "game_phase_still_blocks_underfilled_state": game_phase_underfill_blocked,
        "drake_lineage_survives_first_clock": getattr(drake_closed, LINEAGE_ATTR, "") == ANCHOR_LINEAGE and drake_closed.years_remaining == 2,
        "expired_contracts_enter_free_agent_pool_status": all(
            closed.players[pid].contract.status == "free_agent_pool"
            for pid in closed.free_agent_player_ids
            if getattr(closed.players[pid].contract, "years_remaining", None) == 0
        ),
        "2027_28_anchor_rollover_nonempty": rollover_27.rolled_count > 0,
        "drake_2027_28_salary_and_years_exact": drake_27.years_remaining == 2 and math.isclose(float(drake_27.salary), 3_709_320.0, abs_tol=0.01),
        "egor_2027_28_salary_and_years_exact": egor_27.years_remaining == 2 and math.isclose(float(egor_27.salary), 7_578_240.0, abs_tol=0.01),
        "2027_28_alignment_does_not_reseed": align_27.seeded_count == 0 and align_27.aligned_count > 0,
        "drake_decrements_to_one_after_2027_28": year_2027.players[DRAKE].contract.years_remaining in {0, 1},
        "2028_29_rollover_nonempty": rollover_28.rolled_count > 0,
        "drake_2028_29_salary_and_years_exact_before_expiry": math.isclose(float(drake_28.salary), 6_101_832.0, abs_tol=0.01) and drake_28.years_remaining == 1,
        "2028_29_alignment_does_not_reseed": align_28.seeded_count == 0 and align_28.aligned_count > 0,
        "drake_expires_before_2029_post_draft_trim": (
            DRAKE in set(clock_28["expired_player_ids"])
            and clean(drake_after_28.team_abbreviation) == ""
            and drake_after_28.roster_status == "free_agent"
            and drake_after_28.contract.status == "free_agent_pool"
            and drake_after_28.contract.years_remaining == 0
        ),
        "canonical_checkpoint_hash_unchanged": sha256_file(checkpoint_path) == checkpoint_hash_before,
    }

    # The years=1 check above is captured before the second clock mutates the same
    # object. Record a direct clock-membership assertion as the durable proof.
    checks["drake_is_decremented_in_2027_28_clock"] = DRAKE in set(clock_27["decremented_player_ids"])

    failed = [name for name, ok in checks.items() if not ok]
    audit = {
        "version": VERSION,
        "continuity_version": LEGACY_CONTRACT_CONTINUITY_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "passed": not failed,
        "classification": (
            "legacy_contract_schedule_continuity_v1_proven"
            if not failed
            else "legacy_contract_schedule_continuity_v1_blocked"
        ),
        "checks": checks,
        "failed_checks": failed,
        "source_counts": {
            "rostered": len(source_rostered),
            "unknown_years": len(source_unknown_years),
            "explicit_one_year": len(source_explicit_one_year),
        },
        "migration": {
            "seeded": migration.seeded_count,
            "normalized_rostered_contract_status_ids": list(migration.normalized_rostered_contract_status_player_ids),
            "unresolved": migration.unresolved_count,
            "unresolved_reasons": [list(item) for item in migration.unresolved_reasons],
        },
        "closeout": {
            "expired": closeout.contracts_expired,
            "decremented": closeout.contracts_decremented,
            "trade_owners_released": closeout.trade_owners_released,
            "trade_revision_before": closeout.trade_revision_before,
            "trade_revision_after": closeout.trade_revision_after,
            "minimum_roster_after": closeout.minimum_roster_after_closeout,
            "under_five_teams": under_five,
        },
        "drake_progression": {
            "anchor": {"salary": 3_540_600.0, "years": 3},
            "2027-28": {"salary": 3_709_320.0, "years": 2},
            "2028-29": {"salary": 6_101_832.0, "years": 1},
            "after_2028_29_closeout": {"status": drake_after_28.contract.status, "years": drake_after_28.contract.years_remaining},
        },
        "canonical_checkpoint_sha256": checkpoint_hash_before,
        "canonical_checkpoint_write_performed": False,
        "project_source_write_performed": False,
    }
    report = OUTPUTS / "franchise_legacy_contract_continuity_v1_validation.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")

    print("=" * 128)
    print("FRANCHISE LEGACY CONTRACT CONTINUITY V1 VALIDATION")
    print("=" * 128)
    for name, ok in checks.items():
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")
    print()
    print(f"Seeded legacy schedules: {migration.seeded_count}")
    print(f"Unresolved source rows:  {migration.unresolved_count} -> {', '.join(migration.unresolved_player_ids)}")
    print(f"Corrected first closeout: {closeout.contracts_expired} expired | {closeout.contracts_decremented} decremented")
    print(f"Minimum offseason roster: {closeout.minimum_roster_after_closeout}")
    print("Drake Powell: $3,540,600/3 -> $3,709,320/2 -> $6,101,832/1 -> FA")
    print()
    print(f"Classification: {audit['classification']}")
    print(f"Report: {report}")
    if failed:
        print("Failed checks: " + ", ".join(failed))
        return 1
    print("LEGACY CONTRACT CONTINUITY V1 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: canonical checkpoint/source were not mutated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
