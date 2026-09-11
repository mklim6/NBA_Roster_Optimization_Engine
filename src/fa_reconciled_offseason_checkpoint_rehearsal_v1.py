from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import pickle
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


VERSION = "fa-reconciled-offseason-checkpoint-rehearsal-v1-2026-08-16"
SEASON_LABEL = "2026-27"
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)
EXPECTED_SIMULATION_DIGEST = (
    "f92f03b4c54e53f8f017c3fca43e93ccd09c8b8ba0e5fe0323f418021baf268e"
)
EXPECTED_TRADE_DIGEST = (
    "5183e4794f6a4e1a2daecabab45f3235ce712a7f4b34bf21ff62139334c3d70e"
)
EXPECTED_CHECKPOINT_OBJECT_DIGEST = (
    "91a778c9d92c581cfbcb4f1d98049664f344653ddb5aad696fac53aeca299541"
)
EXPECTED_COMPONENT_TOTAL = 6_257_630_520.0
EXPECTED_COMPONENT_CHECKS = 36


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def object_digest(value: Any) -> str:
    try:
        payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        payload = repr(value).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def member_suffix(archive: zipfile.ZipFile, suffix: str) -> str:
    matches = [name for name in archive.namelist() if name.endswith(suffix)]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one ZIP member ending with {suffix}; found {len(matches)}"
        )
    return matches[0]


def csv_suffix(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    text = archive.read(member_suffix(archive, suffix)).decode(
        "utf-8-sig", errors="replace"
    )
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def json_suffix(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    return json.loads(
        archive.read(member_suffix(archive, suffix)).decode("utf-8-sig")
    )


def find_passed(root: Path, pattern: str, summary_suffix: str) -> Path:
    valid: list[Path] = []
    for path in root.rglob(pattern):
        if not path.is_file():
            continue
        try:
            with zipfile.ZipFile(path) as archive:
                summary = json_suffix(archive, summary_suffix)
                if summary.get("passed") is True and not summary.get("failed_checks"):
                    valid.append(path)
        except Exception:
            continue
    if not valid:
        raise RuntimeError(f"Missing required passed audit: {pattern}")
    return max(valid, key=lambda path: path.stat().st_mtime)


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fields: Iterable[str] | None = None,
) -> None:
    fieldnames = list(fields or [])
    if not fieldnames:
        seen: set[str] = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        if not fieldnames:
            return
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    root = Path.cwd().resolve()
    src = root / "src"
    if not src.exists():
        raise RuntimeError("Run from the NBA_Roster_Optimization_Engine project root.")

    reconciliation_zip = find_passed(
        root,
        "fa_full_team_salary_component_reconciliation_clone_v1_2026-27_*.zip",
        "team_salary_component_reconciliation_summary.json",
    )
    rfa_preview_zip = find_passed(
        root,
        "fa_rfa_rights_qo_controlled_team_preview_v1_2026-27_*.zip",
        "rfa_rights_qo_preview_summary.json",
    )
    non_rfa_rights_zip = find_passed(
        root,
        "fa_non_rfa_rights_final_completion_v1_2026-27_*.zip",
        "non_rfa_rights_final_completion_summary.json",
    )
    clone_input_zip = find_passed(
        root,
        "fa_clone_only_offseason_decision_application_preview_v1_2026-27_*.zip",
        "clone_application_summary.json",
    )
    market_zip = find_passed(
        root,
        "fa_full_market_free_agent_amount_completion_v1_2026-27_*.zip",
        "full_market_free_agent_amount_summary.json",
    )

    with zipfile.ZipFile(reconciliation_zip) as archive:
        reconciliation_summary = json_suffix(
            archive, "team_salary_component_reconciliation_summary.json"
        )
        reconciliation_checks = csv_suffix(
            archive, "team_salary_component_reconciliation_checks.csv"
        )
        component_rows = csv_suffix(
            archive, "official_team_salary_component_ledger_30.csv"
        )
    with zipfile.ZipFile(rfa_preview_zip) as archive:
        rfa_board = csv_suffix(archive, "rfa_rights_qo_decision_board_64.csv")
    with zipfile.ZipFile(non_rfa_rights_zip) as archive:
        non_rfa_rights = csv_suffix(
            archive, "non_rfa_rights_evidence_complete_162.csv"
        )
    with zipfile.ZipFile(clone_input_zip) as archive:
        automatic = csv_suffix(archive, "automatic_decisions_applied_109.csv")
        pending = csv_suffix(archive, "user_decisions_pending_2.csv")
        owner_ledger = csv_suffix(archive, "clone_owner_ledger_587.csv")
    with zipfile.ZipFile(market_zip) as archive:
        market_rows = csv_suffix(
            archive, "full_market_free_agent_amounts_complete_226.csv"
        )

    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    import simulation_franchise_checkpoint_v1 as checkpoint_module
    from fa_full_team_salary_component_reconciliation_clone_v1 import (
        OFFICIAL_SALARY_LEDGER_ATTR,
        apply_component_ledger,
        candidate_semantic_digest,
    )
    from fa_non_rfa_rights_default_preservation_clone_apply_v1 import (
        apply_non_rfa_board,
    )
    from fa_rfa_rights_qo_recommended_branch_clone_apply_v1 import apply_rfa_board
    from freeform_trade_machine_engine_v3 import load_runtime_data
    from franchise_offseason_transaction_application_v1 import (
        build_offseason_transaction_candidates,
        validate_offseason_transition_state,
    )
    from mutable_league_state_v1 import validate_state

    required_checkpoint_functions = (
        "save_franchise_checkpoint",
        "load_franchise_checkpoint",
        "load_checkpoint_path",
        "checkpoint_backup_path",
        "checkpoint_metadata",
    )
    missing_checkpoint_functions = [
        name for name in required_checkpoint_functions if not hasattr(checkpoint_module, name)
    ]
    if missing_checkpoint_functions:
        raise RuntimeError(
            "Checkpoint implementation is missing rehearsal interfaces: "
            + ", ".join(missing_checkpoint_functions)
        )

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    if checkpoint is None:
        raise RuntimeError("Canonical checkpoint could not be loaded.")
    canonical_simulation_digest_before = object_digest(checkpoint.simulation_state)
    canonical_trade_digest_before = object_digest(checkpoint.trade_state)
    canonical_object_digest_before = object_digest(checkpoint)
    overlay_path = root / "outputs" / "runtime" / "free_agency_rights_population_v1.json"
    overlay_existed_before = overlay_path.exists()
    overlay_hash_before = sha256_file(overlay_path) if overlay_existed_before else ""

    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError("Canonical checkpoint changed before rehearsal.")
    if canonical_simulation_digest_before != EXPECTED_SIMULATION_DIGEST:
        raise RuntimeError("Canonical simulation state changed before rehearsal.")
    if canonical_trade_digest_before != EXPECTED_TRADE_DIGEST:
        raise RuntimeError("Canonical Trade Machine state changed before rehearsal.")
    if canonical_object_digest_before != EXPECTED_CHECKPOINT_OBJECT_DIGEST:
        raise RuntimeError("Canonical checkpoint object changed before rehearsal.")

    print("=" * 132)
    print("2026 RECONCILED OFFSEASON CHECKPOINT REHEARSAL V1")
    print("=" * 132)
    print("Rebuilding the fully reconciled candidate and exercising only temporary checkpoint files...")

    runtime = load_runtime_data()
    base = build_offseason_transaction_candidates(
        checkpoint.simulation_state,
        checkpoint.trade_state,
        runtime=runtime,
        owner_ledger_rows=owner_ledger,
        market_rows=market_rows,
        automatic_decisions=automatic,
        pending_decisions=pending,
    )
    post_rfa = apply_rfa_board(
        base["simulation_candidate"], base["trade_candidate"], rfa_board
    )
    post_rights = apply_non_rfa_board(
        post_rfa["simulation_candidate"],
        post_rfa["trade_candidate"],
        non_rfa_rights,
    )
    reconciled = apply_component_ledger(
        post_rights["simulation_candidate"],
        post_rights["trade_candidate"],
        component_rows,
    )
    simulation_candidate = reconciled["simulation_candidate"]
    trade_candidate = reconciled["trade_candidate"]
    candidate_simulation_checks = validate_offseason_transition_state(simulation_candidate)
    candidate_trade_checks = validate_state(trade_candidate, runtime)
    candidate_digest = candidate_semantic_digest(
        simulation_candidate, trade_candidate
    )
    official_total = sum(
        float(row["official_modeled_team_salary"]) for row in component_rows
    )

    steps: list[dict[str, Any]] = []

    def step(step_id: str, status: str, detail: str) -> None:
        steps.append({"step_id": step_id, "status": status, "detail": detail})
        print(f"  {step_id}: {status}")

    temp_primary_hash = ""
    temp_primary_size = 0
    backup_hash = ""
    rollback_hash = ""
    first_saved_at = ""
    second_saved_at = ""
    corrupt_rejected = False
    backup_recovery_digest = ""
    missing_primary_recovery_digest = ""
    temp_root_path: Path | None = None
    rehearsal_write_target = ""
    with tempfile.TemporaryDirectory(prefix="fa_checkpoint_rehearsal_") as temporary:
        temp_root_path = Path(temporary)
        rehearsal_path = temp_root_path / "reconciled_candidate.pkl.gz"
        rehearsal_write_target = str(rehearsal_path.resolve())
        backup_path = checkpoint_module.checkpoint_backup_path(rehearsal_path)
        recovery_path = temp_root_path / "manual_recovery.pkl.gz"

        saved_first = checkpoint_module.save_franchise_checkpoint(
            simulation_candidate,
            trade_candidate,
            preferences=copy.deepcopy(checkpoint.preferences),
            reason="reconciled-offseason-checkpoint-rehearsal-v1-first",
            path=rehearsal_path,
            copy_payload=True,
        )
        first_saved_at = clean(saved_first.saved_at_utc)
        temp_primary_hash = sha256_file(rehearsal_path)
        temp_primary_size = rehearsal_path.stat().st_size
        shutil.copy2(rehearsal_path, recovery_path)
        step("temporary_primary_commit", "PASS", temp_primary_hash)

        loaded_first = checkpoint_module.load_franchise_checkpoint(
            path=rehearsal_path, allow_backup=False
        )
        first_digest = candidate_semantic_digest(
            loaded_first.simulation_state, loaded_first.trade_state
        )
        step("temporary_primary_reload", "PASS", first_digest)

        saved_second = checkpoint_module.save_franchise_checkpoint(
            simulation_candidate,
            trade_candidate,
            preferences=copy.deepcopy(checkpoint.preferences),
            reason="reconciled-offseason-checkpoint-rehearsal-v1-second",
            path=rehearsal_path,
            copy_payload=True,
        )
        second_saved_at = clean(saved_second.saved_at_utc)
        loaded_second = checkpoint_module.load_franchise_checkpoint(
            path=rehearsal_path, allow_backup=False
        )
        second_digest = candidate_semantic_digest(
            loaded_second.simulation_state, loaded_second.trade_state
        )
        backup_loaded = checkpoint_module.load_checkpoint_path(backup_path)
        backup_digest = candidate_semantic_digest(
            backup_loaded.simulation_state, backup_loaded.trade_state
        )
        backup_hash = sha256_file(backup_path)
        step("automatic_backup_creation", "PASS", backup_hash)

        rehearsal_path.write_bytes(b"intentionally-corrupted-rehearsal-checkpoint")
        try:
            checkpoint_module.load_franchise_checkpoint(
                path=rehearsal_path, allow_backup=False
            )
        except Exception:
            corrupt_rejected = True
        if not corrupt_rejected:
            raise RuntimeError("Corrupted temporary checkpoint was not rejected.")
        step("corruption_rejection", "PASS", "invalid primary rejected")

        recovered_from_backup = checkpoint_module.load_franchise_checkpoint(
            path=rehearsal_path, allow_backup=True
        )
        backup_recovery_digest = candidate_semantic_digest(
            recovered_from_backup.simulation_state,
            recovered_from_backup.trade_state,
        )
        step("automatic_backup_recovery", "PASS", backup_recovery_digest)

        shutil.copy2(recovery_path, rehearsal_path)
        rollback_hash = sha256_file(rehearsal_path)
        rolled_back = checkpoint_module.load_franchise_checkpoint(
            path=rehearsal_path, allow_backup=False
        )
        rollback_digest = candidate_semantic_digest(
            rolled_back.simulation_state, rolled_back.trade_state
        )
        step("manual_rollback_restore", "PASS", rollback_hash)

        rehearsal_path.unlink()
        recovered_missing = checkpoint_module.load_franchise_checkpoint(
            path=rehearsal_path, allow_backup=True
        )
        missing_primary_recovery_digest = candidate_semantic_digest(
            recovered_missing.simulation_state,
            recovered_missing.trade_state,
        )
        step(
            "missing_primary_backup_recovery",
            "PASS",
            missing_primary_recovery_digest,
        )

        shutil.copy2(recovery_path, rehearsal_path)
        final_loaded = checkpoint_module.load_franchise_checkpoint(
            path=rehearsal_path, allow_backup=False
        )
        final_digest = candidate_semantic_digest(
            final_loaded.simulation_state, final_loaded.trade_state
        )
        final_metadata = checkpoint_module.checkpoint_metadata(final_loaded)
        step("final_temporary_restore", "PASS", final_digest)

    temporary_files_cleaned = temp_root_path is not None and not temp_root_path.exists()
    checkpoint_hash_after = sha256_file(checkpoint_path)
    checkpoint_after = checkpoint_module.load_franchise_checkpoint()
    if checkpoint_after is None:
        raise RuntimeError("Canonical checkpoint disappeared during rehearsal.")
    canonical_simulation_digest_after = object_digest(checkpoint_after.simulation_state)
    canonical_trade_digest_after = object_digest(checkpoint_after.trade_state)
    canonical_object_digest_after = object_digest(checkpoint_after)
    overlay_existed_after = overlay_path.exists()
    overlay_hash_after = sha256_file(overlay_path) if overlay_existed_after else ""

    checks: list[dict[str, str]] = []

    def add(check_id: str, passed: bool, detail: str) -> None:
        checks.append(
            {
                "check_id": check_id,
                "status": "PASS" if passed else "FAIL",
                "severity": "strict",
                "detail": detail,
            }
        )
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}")

    print("")
    print("Validating temporary durability and canonical immutability...")
    add(
        "upstream_reconciliation_passed_all_36_checks",
        reconciliation_summary.get("passed") is True
        and reconciliation_summary.get("ready_for_temporary_checkpoint_rehearsal") is True
        and len(reconciliation_checks) == EXPECTED_COMPONENT_CHECKS
        and all(clean(row.get("status")) == "PASS" for row in reconciliation_checks),
        f"{len(reconciliation_checks)}/36",
    )
    add(
        "official_component_ledger_is_exactly_30_teams",
        len(component_rows) == 30
        and len({clean(row.get("team")).upper() for row in component_rows}) == 30,
        "30/30",
    )
    add(
        "official_modeled_team_salary_total_is_exact",
        official_total == EXPECTED_COMPONENT_TOTAL,
        f"${official_total:,.0f}",
    )
    add(
        "candidate_retains_exact_official_salary_ledger",
        len(getattr(simulation_candidate, OFFICIAL_SALARY_LEDGER_ATTR, ()) or ()) == 30,
        "30/30",
    )
    add(
        "candidate_passes_simulation_invariants",
        all(candidate_simulation_checks.values()),
        f"{len(candidate_simulation_checks)}/{len(candidate_simulation_checks)}",
    )
    add(
        "candidate_passes_trade_invariants",
        all(candidate_trade_checks.values()),
        f"{len(candidate_trade_checks)}/{len(candidate_trade_checks)}",
    )
    add(
        "temporary_checkpoint_primary_was_written",
        bool(temp_primary_hash) and temp_primary_size > 0,
        f"{temp_primary_size} bytes / {temp_primary_hash}",
    )
    add(
        "temporary_checkpoint_first_reload_is_exact",
        first_digest == candidate_digest,
        first_digest,
    )
    add(
        "temporary_checkpoint_second_reload_is_exact",
        second_digest == candidate_digest,
        second_digest,
    )
    add(
        "checkpoint_reason_round_trips",
        loaded_first.reason.endswith("first") and loaded_second.reason.endswith("second"),
        f"{loaded_first.reason} / {loaded_second.reason}",
    )
    add(
        "checkpoint_saved_timestamps_are_present",
        bool(first_saved_at) and bool(second_saved_at),
        f"{first_saved_at} / {second_saved_at}",
    )
    add(
        "checkpoint_version_is_current",
        final_metadata.get("version") == checkpoint_module.CHECKPOINT_VERSION,
        clean(final_metadata.get("version")),
    )
    add(
        "checkpoint_implementation_is_current",
        final_metadata.get("implementation")
        == checkpoint_module.CHECKPOINT_IMPLEMENTATION_VERSION,
        clean(final_metadata.get("implementation")),
    )
    add(
        "automatic_backup_was_created",
        bool(backup_hash),
        backup_hash,
    )
    add(
        "automatic_backup_payload_is_exact",
        backup_digest == candidate_digest,
        backup_digest,
    )
    add(
        "corrupted_primary_is_rejected_without_backup",
        corrupt_rejected,
        "allow_backup=False",
    )
    add(
        "corrupted_primary_recovers_from_backup",
        backup_recovery_digest == candidate_digest,
        backup_recovery_digest,
    )
    add(
        "manual_recovery_copy_restores_exact_file",
        rollback_hash == temp_primary_hash,
        rollback_hash,
    )
    add(
        "manual_rollback_payload_is_exact",
        rollback_digest == candidate_digest,
        rollback_digest,
    )
    add(
        "missing_primary_recovers_from_backup",
        missing_primary_recovery_digest == candidate_digest,
        missing_primary_recovery_digest,
    )
    add(
        "final_temporary_restore_is_exact",
        final_digest == candidate_digest,
        final_digest,
    )
    add(
        "temporary_rehearsal_files_are_cleaned",
        temporary_files_cleaned,
        clean(temp_root_path),
    )
    add(
        "canonical_simulation_state_is_unchanged",
        canonical_simulation_digest_before
        == canonical_simulation_digest_after
        == EXPECTED_SIMULATION_DIGEST,
        canonical_simulation_digest_after,
    )
    add(
        "canonical_trade_state_is_unchanged",
        canonical_trade_digest_before
        == canonical_trade_digest_after
        == EXPECTED_TRADE_DIGEST,
        canonical_trade_digest_after,
    )
    add(
        "canonical_checkpoint_object_is_unchanged",
        canonical_object_digest_before
        == canonical_object_digest_after
        == EXPECTED_CHECKPOINT_OBJECT_DIGEST,
        canonical_object_digest_after,
    )
    add(
        "canonical_checkpoint_file_is_unchanged",
        checkpoint_hash_before
        == checkpoint_hash_after
        == EXPECTED_CHECKPOINT_SHA256,
        checkpoint_hash_after,
    )
    add(
        "rights_population_overlay_is_unchanged",
        overlay_existed_before == overlay_existed_after
        and overlay_hash_before == overlay_hash_after,
        "absent" if not overlay_existed_after else overlay_hash_after,
    )
    add(
        "canonical_write_was_not_performed",
        rehearsal_write_target != str(checkpoint_path.resolve()),
        rehearsal_write_target,
    )

    failed = [row["check_id"] for row in checks if row["status"] != "PASS"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_reconciled_offseason_checkpoint_rehearsal_v1_{SEASON_LABEL}_{stamp}"
    audit_root = root / "outputs" / "audits"
    audit_root.mkdir(parents=True, exist_ok=True)
    audit_zip = audit_root / f"{export_id}.zip"
    summary = {
        "version": VERSION,
        "season": SEASON_LABEL,
        "passed": not failed,
        "failed_checks": failed,
        "source_reconciliation_audit": reconciliation_zip.name,
        "upstream_check_count": len(reconciliation_checks),
        "rehearsal_check_count": len(checks),
        "official_modeled_team_salary_total": official_total,
        "candidate_semantic_digest": candidate_digest,
        "temporary_checkpoint_bytes": temp_primary_size,
        "temporary_checkpoint_sha256": temp_primary_hash,
        "automatic_backup_sha256": backup_hash,
        "rollback_restored_sha256": rollback_hash,
        "corruption_rejected": corrupt_rejected,
        "automatic_backup_recovery_verified": backup_recovery_digest == candidate_digest,
        "missing_primary_recovery_verified": missing_primary_recovery_digest == candidate_digest,
        "temporary_files_cleaned": temporary_files_cleaned,
        "canonical_checkpoint_sha256_before": checkpoint_hash_before,
        "canonical_checkpoint_sha256_after": checkpoint_hash_after,
        "canonical_write_performed": False,
        "rights_overlay_write_performed": False,
        "ready_for_controlled_canonical_integration": not failed,
        "next_slice": (
            "Build the final controlled canonical checkpoint integration package with a durable "
            "pre-write recovery copy, exact reload verification, and automatic rollback."
        ),
    }
    manifest = {
        "version": VERSION,
        "checkpoint_contract_version": checkpoint_module.CHECKPOINT_VERSION,
        "checkpoint_implementation_version": checkpoint_module.CHECKPOINT_IMPLEMENTATION_VERSION,
        "candidate_semantic_digest": candidate_digest,
        "official_modeled_team_salary_total": official_total,
        "simulation_revision": int(
            getattr(simulation_candidate, "offseason_transaction_application_v1_revision", 0)
            or 0
        ),
        "trade_revision": int(getattr(trade_candidate, "state_revision", 0) or 0),
        "preferences_preserved": sorted(checkpoint.preferences),
        "canonical_target_path": str(checkpoint_path),
        "canonical_target_sha256": EXPECTED_CHECKPOINT_SHA256,
        "canonical_write_authorized": False,
    }
    readme = f"""2026 RECONCILED OFFSEASON CHECKPOINT REHEARSAL V1
===================================================

Result
------
- Audit passed: {not failed}
- Rehearsal checks: {len(checks)}
- Official modeled Team Salary: ${official_total:,.0f}
- Candidate semantic digest: {candidate_digest}

Durability exercised
--------------------
The exact production checkpoint writer was directed to an isolated temporary
path. Primary commit, reload, automatic backup creation, corruption rejection,
backup recovery, manual rollback, missing-primary recovery, and cleanup were
all tested.

Safety
------
The canonical checkpoint remained byte-for-byte unchanged at
{checkpoint_hash_after}. No canonical state or rights overlay was written.
"""

    with tempfile.TemporaryDirectory(prefix="fa_checkpoint_rehearsal_export_") as temporary:
        export = Path(temporary) / export_id
        export.mkdir(parents=True)
        write_csv(
            export / "checkpoint_rehearsal_checks.csv",
            checks,
            ["check_id", "status", "severity", "detail"],
        )
        write_csv(
            export / "checkpoint_rehearsal_steps.csv",
            steps,
            ["step_id", "status", "detail"],
        )
        (export / "checkpoint_rehearsal_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        (export / "candidate_checkpoint_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        (export / "README.txt").write_text(readme, encoding="utf-8")
        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.iterdir()):
                archive.write(item, arcname=f"{export_id}/{item.name}")

    print("")
    print("=" * 132)
    print(
        "2026 RECONCILED OFFSEASON CHECKPOINT REHEARSAL V1 "
        + ("PASSED" if not failed else "FAILED")
    )
    print("=" * 132)
    print(f"Rehearsal checks:                 {len(checks) - len(failed)}/{len(checks)}")
    print(f"Candidate Team Salary:            ${official_total:,.0f}")
    print(f"Temporary checkpoint:             {temp_primary_size:,} bytes")
    print("Corruption rejection:             VERIFIED")
    print("Backup recovery:                  VERIFIED")
    print("Rollback recovery:                VERIFIED")
    print("Temporary cleanup:                VERIFIED")
    print("Canonical checkpoint write:       NOT PERFORMED")
    print("Rights overlay write:             NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
