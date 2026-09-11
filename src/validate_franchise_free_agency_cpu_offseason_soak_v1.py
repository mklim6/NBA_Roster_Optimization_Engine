from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

from franchise_free_agency_cpu_execution_v1 import CPU_FREE_AGENCY_EXECUTION_VERSION
from franchise_free_agency_cpu_offer_generation_v1 import (
    CPU_FREE_AGENCY_DIRECTION_ADAPTER_VERSION,
    CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
    CPU_FREE_AGENCY_TERM_FEASIBILITY_VERSION,
)
from franchise_free_agency_cpu_offseason_soak_v1 import (
    CPU_FREE_AGENCY_OFFSEASON_SOAK_SCHEMA_VERSION,
    CPU_FREE_AGENCY_OFFSEASON_SOAK_SCOPE,
    CPU_FREE_AGENCY_OFFSEASON_SOAK_VERSION,
    REQUIRED_FILES,
    build_cpu_offseason_soak_audit,
    simulate_cpu_offseason_replay,
    soak_contract_report,
)
from franchise_free_agency_live_signing_v1 import trade_state_fingerprint
from franchise_free_agency_transaction_v1 import free_agency_state_fingerprint
from simulation_franchise_checkpoint_v1 import (
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)

VALIDATOR_VERSION = "franchise-free-agency-cpu-offseason-soak-validator-v1.0.2-2026-08-14"
EXPECTED_EXECUTION_VERSION = "franchise-free-agency-cpu-execution-v1-2026-08-14"
EXPECTED_OFFER_VERSION = "franchise-free-agency-cpu-offer-generation-v1-2026-08-14"
EXPECTED_DIRECTION_VERSION = "franchise-free-agency-cpu-direction-adapter-v1.0.1-2026-08-14"
EXPECTED_TERM_VERSION = "franchise-free-agency-cpu-term-feasibility-v1.0.2-2026-08-14"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    print("=" * 112, flush=True)
    print("CPU FREE AGENCY MULTI-OFFSEASON REPLAY SOAK AUDIT V1.0.2 VALIDATION", flush=True)
    print("=" * 112, flush=True)
    print("[1/4] Loading canonical checkpoint and dependency contracts...", flush=True)

    checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    before_hash = sha256(checkpoint_path)
    checkpoint = load_franchise_checkpoint()
    source_sim_fp = free_agency_state_fingerprint(checkpoint.simulation_state)
    source_trade_fp = trade_state_fingerprint(checkpoint.trade_state)

    checks: dict[str, bool] = {}
    checks["validator_version_is_current"] = VALIDATOR_VERSION == "franchise-free-agency-cpu-offseason-soak-validator-v1.0.2-2026-08-14"
    checks["soak_version_is_current"] = CPU_FREE_AGENCY_OFFSEASON_SOAK_VERSION == "franchise-free-agency-cpu-offseason-soak-audit-v1-2026-08-14"
    checks["soak_schema_version_is_current"] = CPU_FREE_AGENCY_OFFSEASON_SOAK_SCHEMA_VERSION == "free-agency-cpu-offseason-soak-schema-v1"
    checks["soak_scope_is_read_only"] = CPU_FREE_AGENCY_OFFSEASON_SOAK_SCOPE == "read_only_in_memory_sequential_cpu_free_agency_replay_soak_no_checkpoint_write"
    checks["cpu_execution_v1_is_preserved"] = CPU_FREE_AGENCY_EXECUTION_VERSION == EXPECTED_EXECUTION_VERSION
    checks["cpu_offer_generation_v1_is_preserved"] = CPU_FREE_AGENCY_OFFER_GENERATION_VERSION == EXPECTED_OFFER_VERSION
    checks["direction_adapter_v1_0_1_is_preserved"] = CPU_FREE_AGENCY_DIRECTION_ADAPTER_VERSION == EXPECTED_DIRECTION_VERSION
    checks["term_feasibility_v1_0_2_is_preserved"] = CPU_FREE_AGENCY_TERM_FEASIBILITY_VERSION == EXPECTED_TERM_VERSION

    contract = soak_contract_report()
    checks["contract_declares_no_checkpoint_write"] = contract.get("checkpoint_write_allowed") is False
    checks["contract_declares_no_fake_randomness"] = contract.get("production_randomness_injected") is False
    checks["contract_rebuilds_after_every_signing"] = contract.get("board_rebuilt_after_each_signing") is True
    checks["contract_advances_both_states_in_memory"] = contract.get("simulation_and_trade_candidates_both_advanced_in_memory") is True

    print("[2/4] Running exact-state production-path sequential probe (1 signing/day)...", flush=True)
    probe1 = simulate_cpu_offseason_replay(
        checkpoint.simulation_state,
        checkpoint.trade_state,
        controlled_teams=("CHI",),
        replay_number=1,
        max_days=6,
        max_signings_per_day=1,
        max_total_signings=3,
    )
    probe2 = simulate_cpu_offseason_replay(
        checkpoint.simulation_state,
        checkpoint.trade_state,
        controlled_teams=("CHI",),
        replay_number=2,
        max_days=6,
        max_signings_per_day=1,
        max_total_signings=3,
    )

    checks["production_probe_executes_multiple_sequential_signings"] = probe1.signing_count >= 3
    checks["production_probe_one_signing_per_day_is_respected"] = all(int(row["signings"]) <= 1 for row in probe1.day_rows)
    checks["production_probe_rebuilds_after_every_signing"] = (
        probe1.signing_count >= 2
        and len({row["source_simulation_fingerprint"] for row in probe1.signing_rows}) == probe1.signing_count
        and len({row["source_trade_fingerprint"] for row in probe1.signing_rows}) == probe1.signing_count
    )
    checks["production_probe_same_state_replay_is_exact"] = probe1.outcome_fingerprint == probe2.outcome_fingerprint
    checks["production_probe_final_state_is_exact"] = (
        probe1.final_simulation_fingerprint == probe2.final_simulation_fingerprint
        and probe1.final_trade_fingerprint == probe2.final_trade_fingerprint
    )
    checks["production_probe_controlled_team_never_signs"] = all(
        row["team_abbreviation"] != "CHI" for row in probe1.signing_rows
    )
    checks["production_probe_roster_limit_is_respected"] = all(
        int(row["roster_after"]) <= 18 for row in probe1.signing_rows
    )
    checks["production_probe_salary_delta_is_exact"] = all(
        abs((float(row["team_salary_after"]) - float(row["team_salary_before"])) - float(row["annual_salary"])) <= 0.01
        for row in probe1.signing_rows
    )
    checks["production_probe_does_not_require_all_free_agents_to_sign"] = (
        probe1.final_free_agent_count >= 0
        and bool(probe1.terminal_reason)
    )
    checks["production_probe_source_simulation_is_not_mutated"] = (
        free_agency_state_fingerprint(checkpoint.simulation_state) == source_sim_fp
    )
    checks["production_probe_source_trade_is_not_mutated"] = (
        trade_state_fingerprint(checkpoint.trade_state) == source_trade_fp
    )

    print(
        f"      Production probe: {probe1.signing_count} signings across {probe1.days_used} day(s) · terminal: {probe1.terminal_reason}",
        flush=True,
    )

    print("[3/4] Running 3-replay live-state read-only mini-soak...", flush=True)
    with tempfile.TemporaryDirectory(prefix="cpu_fa_soak_validator_") as tmp:
        live = build_cpu_offseason_soak_audit(
            output_directory=tmp,
            replay_count=3,
            max_days=15,
            max_signings_per_day=3,
            max_total_signings=60,
        )
        zip_path = Path(live.output_zip)
        checks["validation_soak_zip_is_created"] = zip_path.exists()
        checks["validation_soak_strict_checks_pass"] = live.strict_pass
        checks["validation_replays_are_exact"] = live.failed_checks == ()
        checks["live_mini_soak_executes_multiple_sequential_signings"] = live.baseline_signing_count >= 3
        with zipfile.ZipFile(zip_path) as archive:
            names = set(archive.namelist())
            checks["all_required_soak_files_exist"] = all(name in names for name in REQUIRED_FILES)
            summary = json.loads(archive.read("soak_summary.json").decode("utf-8"))
            checks["summary_records_model_versions"] = summary.get("model_versions", {}).get("term_feasibility") == EXPECTED_TERM_VERSION
            checks["summary_labels_replays_not_random_seeds"] = summary.get("production_randomness_injected") is False
            behavior_text = archive.read("soak_behavioral_checks.csv").decode("utf-8-sig")
            checks["behavioral_csv_has_no_failures"] = ",FAIL," not in behavior_text and "FAIL" not in [
                line.split(",")[1] if "," in line else ""
                for line in behavior_text.splitlines()[1:]
            ]

    print(
        f"      Live mini-soak baseline: {live.baseline_signing_count} signings across {live.baseline_days_used} day(s)",
        flush=True,
    )

    print("[4/4] Verifying canonical checkpoint/state remained untouched...", flush=True)
    after_checkpoint = load_franchise_checkpoint()
    after_hash = sha256(checkpoint_path)
    checks["validator_did_not_write_checkpoint"] = before_hash == after_hash
    checks["validator_did_not_mutate_live_simulation_state"] = (
        free_agency_state_fingerprint(after_checkpoint.simulation_state) == source_sim_fp
    )
    checks["validator_did_not_mutate_live_trade_state"] = (
        trade_state_fingerprint(after_checkpoint.trade_state) == source_trade_fp
    )

    failed = [name for name, passed in checks.items() if not passed]

    print()
    print("=" * 112)
    print("CPU FREE AGENCY MULTI-OFFSEASON REPLAY SOAK AUDIT V1.0.2 VALIDATION RESULTS")
    print("=" * 112)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    print("\nPRODUCTION-PATH SEQUENTIAL PROBE")
    print(f"  Signings: {probe1.signing_count}")
    print(f"  Days used: {probe1.days_used}")
    print(f"  Terminal reason: {probe1.terminal_reason}")
    print(f"  Remaining free agents: {probe1.final_free_agent_count}")
    print(f"  Same-state replay exact: {probe1.outcome_fingerprint == probe2.outcome_fingerprint}")

    print("\nLIVE READ-ONLY MINI-SOAK")
    print(f"  Season: {live.season_label}")
    print(f"  Live phase: {live.live_phase}")
    print(f"  Analysis phase: {live.analysis_phase}")
    print(f"  Replays: {live.replay_count}")
    print(f"  Baseline signings: {live.baseline_signing_count}")
    print(f"  Baseline days used: {live.baseline_days_used}")
    print(f"  Baseline terminal reason: {live.baseline_terminal_reason}")
    print(f"  Checkpoint hash unchanged: {before_hash == after_hash}")

    print("\n" + json.dumps({
        "validator": VALIDATOR_VERSION,
        "soak": CPU_FREE_AGENCY_OFFSEASON_SOAK_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "checkpoint_hash_before": before_hash,
        "checkpoint_hash_after": after_hash,
        "passed": not failed,
    }, indent=2, sort_keys=True))
    print()

    if failed:
        print("CPU FREE AGENCY MULTI-OFFSEASON REPLAY SOAK AUDIT V1.0.2 VALIDATION FAILED")
        return 1

    print("CPU FREE AGENCY MULTI-OFFSEASON REPLAY SOAK AUDIT V1.0.2 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: all signings occurred only on isolated in-memory copies. No checkpoint write was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
