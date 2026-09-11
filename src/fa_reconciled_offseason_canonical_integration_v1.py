from __future__ import annotations

import argparse
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


VERSION = "fa-reconciled-offseason-canonical-integration-v1-2026-08-16"
SEASON_LABEL = "2026-27"
CONFIRMATION_TOKEN = "APPLY_RECONCILED_2026_27"
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
EXPECTED_CANDIDATE_DIGEST = (
    "e6dbb0fa628809cbf11bc039c1da89fa7474d8faa1f0cb54eeefe7613bb49240"
)
EXPECTED_COMPONENT_TOTAL = 6_257_630_520.0
EXPECTED_REHEARSAL_CHECKS = 28
RFA_LEDGER_ATTR = "offseason_rfa_rights_qo_decisions_v1"
NON_RFA_LEDGER_ATTR = "offseason_non_rfa_rights_decisions_v1"
OFFICIAL_SALARY_LEDGER_ATTR = "offseason_official_team_salary_components_v1"


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


def build_candidate(root: Path, checkpoint: Any, runtime: Any) -> tuple[Any, Any, Path, dict[str, Any], list[dict[str, str]]]:
    reconciliation_zip = find_passed(
        root,
        "fa_full_team_salary_component_reconciliation_clone_v1_2026-27_*.zip",
        "team_salary_component_reconciliation_summary.json",
    )
    rehearsal_zip = find_passed(
        root,
        "fa_reconciled_offseason_checkpoint_rehearsal_v1_2026-27_*.zip",
        "checkpoint_rehearsal_summary.json",
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

    with zipfile.ZipFile(rehearsal_zip) as archive:
        rehearsal_summary = json_suffix(archive, "checkpoint_rehearsal_summary.json")
        rehearsal_checks = csv_suffix(archive, "checkpoint_rehearsal_checks.csv")
        rehearsal_manifest = json_suffix(archive, "candidate_checkpoint_manifest.json")
    with zipfile.ZipFile(reconciliation_zip) as archive:
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

    if not (
        rehearsal_summary.get("passed") is True
        and rehearsal_summary.get("ready_for_controlled_canonical_integration") is True
        and len(rehearsal_checks) == EXPECTED_REHEARSAL_CHECKS
        and all(clean(row.get("status")) == "PASS" for row in rehearsal_checks)
        and rehearsal_summary.get("candidate_semantic_digest") == EXPECTED_CANDIDATE_DIGEST
        and rehearsal_manifest.get("candidate_semantic_digest") == EXPECTED_CANDIDATE_DIGEST
        and rehearsal_manifest.get("canonical_write_authorized") is False
    ):
        raise RuntimeError("The exact 28-check checkpoint rehearsal gate did not pass.")

    from fa_full_team_salary_component_reconciliation_clone_v1 import apply_component_ledger
    from fa_non_rfa_rights_default_preservation_clone_apply_v1 import apply_non_rfa_board
    from fa_rfa_rights_qo_recommended_branch_clone_apply_v1 import apply_rfa_board
    from franchise_offseason_transaction_application_v1 import build_offseason_transaction_candidates

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
    return (
        reconciled["simulation_candidate"],
        reconciled["trade_candidate"],
        rehearsal_zip,
        rehearsal_summary,
        rehearsal_checks,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirmation-token", default="")
    args = parser.parse_args()

    if args.apply and args.confirmation_token != CONFIRMATION_TOKEN:
        raise RuntimeError(
            f"Canonical apply requires --confirmation-token {CONFIRMATION_TOKEN}"
        )
    root = Path.cwd().resolve()
    src = root / "src"
    if not src.exists():
        raise RuntimeError("Run from the NBA_Roster_Optimization_Engine project root.")
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    import simulation_franchise_checkpoint_v1 as checkpoint_module
    from fa_full_team_salary_component_reconciliation_clone_v1 import candidate_semantic_digest
    from freeform_trade_machine_engine_v3 import load_runtime_data
    from franchise_offseason_transaction_application_v1 import validate_offseason_transition_state
    from mutable_league_state_v1 import validate_state

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    if not checkpoint_path.is_file():
        raise RuntimeError("Canonical checkpoint is missing.")
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint_before = checkpoint_module.load_franchise_checkpoint(
        path=checkpoint_path, allow_backup=False
    )
    if checkpoint_before is None:
        raise RuntimeError("Canonical checkpoint could not be loaded.")
    canonical_simulation_digest_before = object_digest(checkpoint_before.simulation_state)
    canonical_trade_digest_before = object_digest(checkpoint_before.trade_state)
    canonical_object_digest_before = object_digest(checkpoint_before)
    current_semantic_digest = candidate_semantic_digest(
        checkpoint_before.simulation_state, checkpoint_before.trade_state
    )
    already_integrated = current_semantic_digest == EXPECTED_CANDIDATE_DIGEST
    original_baseline = (
        checkpoint_hash_before == EXPECTED_CHECKPOINT_SHA256
        and canonical_simulation_digest_before == EXPECTED_SIMULATION_DIGEST
        and canonical_trade_digest_before == EXPECTED_TRADE_DIGEST
        and canonical_object_digest_before == EXPECTED_CHECKPOINT_OBJECT_DIGEST
    )
    if not original_baseline and not already_integrated:
        raise RuntimeError(
            "Canonical checkpoint is neither the frozen pre-integration baseline nor the exact rehearsed candidate."
        )

    overlay_path = root / "outputs" / "runtime" / "free_agency_rights_population_v1.json"
    overlay_existed_before = overlay_path.exists()
    overlay_hash_before = sha256_file(overlay_path) if overlay_existed_before else ""
    runtime = load_runtime_data()

    if already_integrated:
        simulation_candidate = checkpoint_before.simulation_state
        trade_candidate = checkpoint_before.trade_state
        rehearsal_zip = find_passed(
            root,
            "fa_reconciled_offseason_checkpoint_rehearsal_v1_2026-27_*.zip",
            "checkpoint_rehearsal_summary.json",
        )
        with zipfile.ZipFile(rehearsal_zip) as archive:
            rehearsal_summary = json_suffix(archive, "checkpoint_rehearsal_summary.json")
            rehearsal_checks = csv_suffix(archive, "checkpoint_rehearsal_checks.csv")
    else:
        (
            simulation_candidate,
            trade_candidate,
            rehearsal_zip,
            rehearsal_summary,
            rehearsal_checks,
        ) = build_candidate(root, checkpoint_before, runtime)

    candidate_simulation_checks = validate_offseason_transition_state(simulation_candidate)
    candidate_trade_checks = validate_state(trade_candidate, runtime)
    candidate_digest = candidate_semantic_digest(simulation_candidate, trade_candidate)
    rfa_count = len(getattr(simulation_candidate, RFA_LEDGER_ATTR, ()) or ())
    non_rfa_count = len(getattr(simulation_candidate, NON_RFA_LEDGER_ATTR, ()) or ())
    salary_rows = list(
        getattr(simulation_candidate, OFFICIAL_SALARY_LEDGER_ATTR, ()) or ()
    )
    official_total = sum(
        float(row["official_modeled_team_salary"]) for row in salary_rows
    )
    preferences_digest = object_digest(checkpoint_before.preferences)

    print("=" * 132)
    print("2026 RECONCILED OFFSEASON CANONICAL INTEGRATION V1")
    print("=" * 132)
    print("Validating the exact rehearsed candidate and controlled commit gates...")

    preflight_checks: list[dict[str, str]] = []

    def add(rows: list[dict[str, str]], check_id: str, passed: bool, detail: str) -> None:
        rows.append(
            {
                "check_id": check_id,
                "status": "PASS" if passed else "FAIL",
                "severity": "strict",
                "detail": detail,
            }
        )
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}")

    add(
        preflight_checks,
        "upstream_rehearsal_passed_all_28_checks",
        rehearsal_summary.get("passed") is True
        and rehearsal_summary.get("ready_for_controlled_canonical_integration") is True
        and len(rehearsal_checks) == EXPECTED_REHEARSAL_CHECKS
        and all(clean(row.get("status")) == "PASS" for row in rehearsal_checks),
        f"{len(rehearsal_checks)}/28",
    )
    add(preflight_checks, "canonical_source_is_known", original_baseline or already_integrated, "baseline" if original_baseline else "already integrated")
    add(preflight_checks, "candidate_digest_matches_rehearsal", candidate_digest == EXPECTED_CANDIDATE_DIGEST, candidate_digest)
    add(preflight_checks, "candidate_simulation_invariants_pass", all(candidate_simulation_checks.values()), f"{len(candidate_simulation_checks)}/{len(candidate_simulation_checks)}")
    add(preflight_checks, "candidate_trade_invariants_pass", all(candidate_trade_checks.values()), f"{len(candidate_trade_checks)}/{len(candidate_trade_checks)}")
    add(preflight_checks, "candidate_rights_population_is_exact", rfa_count == 64 and non_rfa_count == 162, f"{rfa_count}+{non_rfa_count}=226")
    add(preflight_checks, "candidate_salary_ledger_is_exactly_30_teams", len(salary_rows) == 30, f"{len(salary_rows)}/30")
    add(preflight_checks, "candidate_official_team_salary_is_exact", official_total == EXPECTED_COMPONENT_TOTAL, f"${official_total:,.0f}")
    add(preflight_checks, "candidate_revisions_are_exact", int(getattr(simulation_candidate, "offseason_transaction_application_v1_revision", 0) or 0) == 4 and int(getattr(trade_candidate, "state_revision", 0) or 0) == 4, "simulation=4 / trade=4")
    add(preflight_checks, "canonical_apply_requires_explicit_token", (not args.apply) or args.confirmation_token == CONFIRMATION_TOKEN, "confirmed" if args.apply else "dry run")
    add(preflight_checks, "rights_overlay_is_unchanged_before_commit", overlay_path.exists() == overlay_existed_before and (not overlay_existed_before or sha256_file(overlay_path) == overlay_hash_before), "absent" if not overlay_existed_before else overlay_hash_before)
    failed_preflight = [row["check_id"] for row in preflight_checks if row["status"] != "PASS"]
    if failed_preflight:
        raise RuntimeError("Canonical integration preflight failed: " + ", ".join(failed_preflight))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    audit_root = root / "outputs" / "audits"
    audit_root.mkdir(parents=True, exist_ok=True)

    if not args.apply:
        export_id = f"fa_reconciled_offseason_canonical_integration_preflight_v1_{SEASON_LABEL}_{stamp}"
        audit_zip = audit_root / f"{export_id}.zip"
        summary = {
            "version": VERSION,
            "season": SEASON_LABEL,
            "passed": True,
            "failed_checks": [],
            "mode": "preflight_only",
            "candidate_semantic_digest": candidate_digest,
            "official_modeled_team_salary_total": official_total,
            "canonical_checkpoint_sha256": checkpoint_hash_before,
            "canonical_write_performed": False,
            "ready_for_explicit_apply": not already_integrated,
            "already_integrated": already_integrated,
            "required_confirmation_token": CONFIRMATION_TOKEN,
            "source_rehearsal_audit": rehearsal_zip.name,
        }
        with tempfile.TemporaryDirectory(prefix="fa_canonical_preflight_export_") as temporary:
            export = Path(temporary) / export_id
            export.mkdir(parents=True)
            write_csv(export / "canonical_integration_preflight_checks.csv", preflight_checks, ["check_id", "status", "severity", "detail"])
            (export / "canonical_integration_preflight_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
            with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
                for item in sorted(export.iterdir()):
                    archive.write(item, arcname=f"{export_id}/{item.name}")
        print("")
        print("CANONICAL INTEGRATION PREFLIGHT PASSED")
        print("Canonical checkpoint write: NOT PERFORMED")
        print(f"To apply, rerun with --apply --confirmation-token {CONFIRMATION_TOKEN}")
        print(f"Audit ZIP: {audit_zip}")
        return 0

    if already_integrated:
        checkpoint_hash_after = checkpoint_hash_before
        loaded = checkpoint_before
        recovery_path = Path("")
        automatic_backup_path = checkpoint_module.checkpoint_backup_path(checkpoint_path)
        canonical_write_performed = False
        commit_status = "already_integrated_exact_candidate"
    else:
        if sha256_file(checkpoint_path) != EXPECTED_CHECKPOINT_SHA256:
            raise RuntimeError(
                "Canonical checkpoint changed during preflight. Stop all running app processes and retry."
            )
        recovery_dir = root / "backups" / f"fa_reconciled_offseason_canonical_integration_v1_{stamp}"
        recovery_dir.mkdir(parents=True, exist_ok=False)
        recovery_path = recovery_dir / "franchise_mode_checkpoint_v1.pre_integration.pkl.gz"
        recovery_manifest_path = recovery_dir / "recovery_manifest.json"
        shutil.copy2(checkpoint_path, recovery_path)
        if sha256_file(recovery_path) != EXPECTED_CHECKPOINT_SHA256:
            raise RuntimeError("Durable pre-integration recovery copy hash mismatch.")
        recovery_loaded = checkpoint_module.load_checkpoint_path(recovery_path)
        if (
            object_digest(recovery_loaded.simulation_state) != EXPECTED_SIMULATION_DIGEST
            or object_digest(recovery_loaded.trade_state) != EXPECTED_TRADE_DIGEST
        ):
            raise RuntimeError("Durable pre-integration recovery copy failed semantic verification.")
        if sha256_file(checkpoint_path) != EXPECTED_CHECKPOINT_SHA256:
            raise RuntimeError(
                "Canonical checkpoint changed after recovery creation. No integration write was performed."
            )
        recovery_manifest_path.write_text(
            json.dumps(
                {
                    "version": VERSION,
                    "created_at_utc": datetime.now(timezone.utc).isoformat(),
                    "canonical_path": str(checkpoint_path),
                    "recovery_path": str(recovery_path),
                    "pre_integration_sha256": EXPECTED_CHECKPOINT_SHA256,
                    "pre_integration_simulation_digest": EXPECTED_SIMULATION_DIGEST,
                    "pre_integration_trade_digest": EXPECTED_TRADE_DIGEST,
                    "candidate_semantic_digest": EXPECTED_CANDIDATE_DIGEST,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        try:
            checkpoint_module.save_franchise_checkpoint(
                simulation_candidate,
                trade_candidate,
                preferences=copy.deepcopy(checkpoint_before.preferences),
                reason="fa-reconciled-offseason-canonical-integration-v1",
                path=checkpoint_path,
                copy_payload=True,
            )
            loaded = checkpoint_module.load_franchise_checkpoint(
                path=checkpoint_path, allow_backup=False
            )
            if loaded is None:
                raise RuntimeError("Committed checkpoint could not be reloaded.")
            loaded_digest = candidate_semantic_digest(
                loaded.simulation_state, loaded.trade_state
            )
            if loaded_digest != EXPECTED_CANDIDATE_DIGEST:
                raise RuntimeError("Committed checkpoint did not reload as the exact rehearsed candidate.")
            if loaded.reason != "fa-reconciled-offseason-canonical-integration-v1":
                raise RuntimeError("Committed checkpoint reason did not round-trip.")
            if object_digest(loaded.preferences) != preferences_digest:
                raise RuntimeError("Committed checkpoint did not preserve preferences.")
            checkpoint_hash_after = sha256_file(checkpoint_path)
            if checkpoint_hash_after == EXPECTED_CHECKPOINT_SHA256:
                raise RuntimeError("Canonical checkpoint bytes did not advance.")
        except Exception as commit_error:
            try:
                shutil.copy2(recovery_path, checkpoint_path)
                restored = checkpoint_module.load_franchise_checkpoint(
                    path=checkpoint_path, allow_backup=False
                )
                if restored is None or sha256_file(checkpoint_path) != EXPECTED_CHECKPOINT_SHA256:
                    raise RuntimeError("Rollback did not restore the exact original file.")
                if (
                    object_digest(restored.simulation_state) != EXPECTED_SIMULATION_DIGEST
                    or object_digest(restored.trade_state) != EXPECTED_TRADE_DIGEST
                    or object_digest(restored) != EXPECTED_CHECKPOINT_OBJECT_DIGEST
                ):
                    raise RuntimeError("Rollback did not restore the exact original checkpoint object.")
            except Exception as rollback_error:
                raise RuntimeError(
                    f"Canonical commit failed and automatic rollback failed. Recovery remains at {recovery_path}. "
                    f"Commit error: {commit_error}. Rollback error: {rollback_error}"
                ) from rollback_error
            raise RuntimeError(
                f"Canonical commit failed and the original checkpoint was restored exactly. Recovery remains at {recovery_path}. {commit_error}"
            ) from commit_error

        automatic_backup_path = checkpoint_module.checkpoint_backup_path(checkpoint_path)
        canonical_write_performed = True
        commit_status = "committed_and_verified"

    loaded_digest = candidate_semantic_digest(loaded.simulation_state, loaded.trade_state)
    loaded_simulation_checks = validate_offseason_transition_state(loaded.simulation_state)
    loaded_trade_checks = validate_state(loaded.trade_state, runtime)
    loaded_salary_rows = list(getattr(loaded.simulation_state, OFFICIAL_SALARY_LEDGER_ATTR, ()) or ())
    loaded_official_total = sum(float(row["official_modeled_team_salary"]) for row in loaded_salary_rows)
    overlay_existed_after = overlay_path.exists()
    overlay_hash_after = sha256_file(overlay_path) if overlay_existed_after else ""

    commit_checks: list[dict[str, str]] = []
    add(commit_checks, "canonical_checkpoint_is_exact_rehearsed_candidate", loaded_digest == EXPECTED_CANDIDATE_DIGEST, loaded_digest)
    add(commit_checks, "canonical_simulation_invariants_pass", all(loaded_simulation_checks.values()), f"{len(loaded_simulation_checks)}/{len(loaded_simulation_checks)}")
    add(commit_checks, "canonical_trade_invariants_pass", all(loaded_trade_checks.values()), f"{len(loaded_trade_checks)}/{len(loaded_trade_checks)}")
    add(commit_checks, "canonical_rights_population_is_exact", len(getattr(loaded.simulation_state, RFA_LEDGER_ATTR, ()) or ()) == 64 and len(getattr(loaded.simulation_state, NON_RFA_LEDGER_ATTR, ()) or ()) == 162, "64+162=226")
    add(commit_checks, "canonical_salary_ledger_is_exactly_30_teams", len(loaded_salary_rows) == 30, f"{len(loaded_salary_rows)}/30")
    add(commit_checks, "canonical_official_team_salary_is_exact", loaded_official_total == EXPECTED_COMPONENT_TOTAL, f"${loaded_official_total:,.0f}")
    add(commit_checks, "canonical_preferences_are_preserved", object_digest(loaded.preferences) == preferences_digest, preferences_digest)
    add(commit_checks, "canonical_revisions_are_exact", int(getattr(loaded.simulation_state, "offseason_transaction_application_v1_revision", 0) or 0) == 4 and int(getattr(loaded.trade_state, "state_revision", 0) or 0) == 4, "simulation=4 / trade=4")
    add(commit_checks, "automatic_checkpoint_backup_exists", automatic_backup_path.is_file(), str(automatic_backup_path))
    add(commit_checks, "automatic_checkpoint_backup_is_original_baseline", sha256_file(automatic_backup_path) == EXPECTED_CHECKPOINT_SHA256 if canonical_write_performed else True, sha256_file(automatic_backup_path) if automatic_backup_path.is_file() else "missing")
    add(commit_checks, "durable_manual_recovery_exists", recovery_path.is_file() if canonical_write_performed else True, str(recovery_path) if canonical_write_performed else "already integrated")
    add(commit_checks, "durable_manual_recovery_is_original_baseline", sha256_file(recovery_path) == EXPECTED_CHECKPOINT_SHA256 if canonical_write_performed else True, sha256_file(recovery_path) if canonical_write_performed else "already integrated")
    add(commit_checks, "canonical_checkpoint_advanced", checkpoint_hash_after != EXPECTED_CHECKPOINT_SHA256 or already_integrated, checkpoint_hash_after)
    add(commit_checks, "rights_overlay_remains_unchanged", overlay_existed_before == overlay_existed_after and overlay_hash_before == overlay_hash_after, "absent" if not overlay_existed_after else overlay_hash_after)
    failed_commit = [row["check_id"] for row in commit_checks if row["status"] != "PASS"]
    if failed_commit:
        raise RuntimeError("Post-commit verification failed: " + ", ".join(failed_commit))

    export_id = f"fa_reconciled_offseason_canonical_integration_v1_{SEASON_LABEL}_{stamp}"
    audit_zip = audit_root / f"{export_id}.zip"
    summary = {
        "version": VERSION,
        "season": SEASON_LABEL,
        "passed": True,
        "failed_checks": [],
        "mode": "canonical_apply",
        "commit_status": commit_status,
        "canonical_write_performed": canonical_write_performed,
        "already_integrated": already_integrated,
        "candidate_semantic_digest": loaded_digest,
        "official_modeled_team_salary_total": loaded_official_total,
        "rights_decision_count": 226,
        "canonical_checkpoint_sha256_before": checkpoint_hash_before,
        "canonical_checkpoint_sha256_after": checkpoint_hash_after,
        "automatic_backup_path": str(automatic_backup_path),
        "manual_recovery_path": str(recovery_path) if canonical_write_performed else "",
        "manual_recovery_sha256": sha256_file(recovery_path) if canonical_write_performed else "",
        "rights_overlay_write_performed": False,
        "ready_for_live_offseason_free_agency": True,
        "next_slice": "Run a post-integration live-state readiness audit, then begin controlled free-agent offer and renouncement workflows.",
    }
    receipt = {
        "version": VERSION,
        "committed_at_utc": clean(getattr(loaded, "saved_at_utc", "")),
        "checkpoint_reason": clean(getattr(loaded, "reason", "")),
        "candidate_semantic_digest": loaded_digest,
        "checkpoint_sha256": checkpoint_hash_after,
        "simulation_revision": int(getattr(loaded.simulation_state, "offseason_transaction_application_v1_revision", 0) or 0),
        "trade_revision": int(getattr(loaded.trade_state, "state_revision", 0) or 0),
        "official_modeled_team_salary_total": loaded_official_total,
        "recovery_checkpoint": str(recovery_path) if canonical_write_performed else "",
    }
    readme = f"""2026 RECONCILED OFFSEASON CANONICAL INTEGRATION V1
==================================================

Result
------
- Status: {commit_status}
- Canonical write performed in this run: {canonical_write_performed}
- Candidate semantic digest: {loaded_digest}
- Official modeled Team Salary: ${loaded_official_total:,.0f}
- Rights decisions persisted: 226
- Canonical checkpoint SHA-256: {checkpoint_hash_after}

Recovery
--------
The exact pre-integration checkpoint remains at:
{str(recovery_path) if canonical_write_performed else 'A previous exact integration was detected; no new recovery copy was required.'}

The standard automatic checkpoint backup is:
{automatic_backup_path}
"""
    all_checks = preflight_checks + commit_checks
    with tempfile.TemporaryDirectory(prefix="fa_canonical_integration_export_") as temporary:
        export = Path(temporary) / export_id
        export.mkdir(parents=True)
        write_csv(export / "canonical_integration_checks.csv", all_checks, ["check_id", "status", "severity", "detail"])
        (export / "canonical_integration_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        (export / "canonical_integration_receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
        (export / "README.txt").write_text(readme, encoding="utf-8")
        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.iterdir()):
                archive.write(item, arcname=f"{export_id}/{item.name}")

    print("")
    print("=" * 132)
    print("2026 RECONCILED OFFSEASON CANONICAL INTEGRATION V1 PASSED")
    print("=" * 132)
    print(f"Commit status:                     {commit_status}")
    print(f"Canonical checkpoint SHA-256:      {checkpoint_hash_after}")
    print(f"Official modeled Team Salary:      ${loaded_official_total:,.0f}")
    print("Rights decisions persisted:        226/226")
    print("Simulation revision:               4")
    print("Trade revision:                    4")
    print("Automatic backup:                  VERIFIED")
    print("Durable recovery copy:             VERIFIED")
    print("Rights overlay write:              NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
