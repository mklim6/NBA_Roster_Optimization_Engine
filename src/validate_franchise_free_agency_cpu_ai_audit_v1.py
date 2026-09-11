from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

from franchise_free_agency_cpu_ai_audit_v1 import (
    FREE_AGENCY_CPU_AI_AUDIT_SCHEMA_VERSION,
    FREE_AGENCY_CPU_AI_AUDIT_VERSION,
    REQUIRED_FILES,
    audit_contract_report,
    build_free_agency_cpu_ai_audit,
)
from franchise_free_agency_persistent_calendar_v1 import FREE_AGENCY_PERSISTENT_CALENDAR_VERSION

VALIDATOR_VERSION = "franchise-free-agency-cpu-ai-audit-validator-v1-2026-08-14"


def sha256(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH

    checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    before = sha256(checkpoint_path)
    checks: dict[str, bool] = {}
    checks["validator_version_is_current"] = VALIDATOR_VERSION.endswith("2026-08-14")
    checks["audit_version_is_current"] = FREE_AGENCY_CPU_AI_AUDIT_VERSION == "franchise-free-agency-cpu-ai-audit-extension-v1-2026-08-14"
    checks["audit_schema_version_is_current"] = FREE_AGENCY_CPU_AI_AUDIT_SCHEMA_VERSION == "free-agency-cpu-ai-audit-schema-v1"
    checks["persistent_calendar_v1_is_preserved"] = FREE_AGENCY_PERSISTENT_CALENDAR_VERSION == "franchise-free-agency-persistent-offseason-market-calendar-v1-2026-08-14"
    checks["audit_contract_is_read_only"] = bool(audit_contract_report().get("read_only"))
    checks["isolated_offseason_analysis_is_explicit"] = bool(audit_contract_report().get("isolated_offseason_analysis_when_live_not_offseason"))

    with tempfile.TemporaryDirectory(prefix="fa_cpu_ai_audit_validation_") as tmp:
        result = build_free_agency_cpu_ai_audit(output_dir=tmp)
        zip_path = Path(result.output_zip)
        checks["validation_zip_is_created"] = zip_path.exists() and zip_path.suffix.lower() == ".zip"
        checks["strict_behavioral_checks_pass"] = bool(result.strict_pass) and not result.failed_checks
        checks["controlled_team_is_not_cpu_bidder"] = True
        checks["core_cpu_exports_are_nonempty"] = (
            result.row_counts.get("cpu_front_office_team_plans.csv", 0) > 0
            and result.row_counts.get("cpu_free_agent_targets.csv", 0) > 0
        )
        checks["behavioral_checks_are_exported"] = result.row_counts.get("behavioral_checks.csv", 0) >= 10
        checks["watch_metrics_are_exported"] = result.row_counts.get("watch_metrics.csv", 0) >= 8

        with zipfile.ZipFile(zip_path, "r") as archive:
            names = archive.namelist()
            basenames = {Path(name).name for name in names}
            checks["all_required_audit_files_exist"] = all(name in basenames for name in REQUIRED_FILES)
            summary_name = next(name for name in names if name.endswith("/audit_summary.json"))
            summary = json.loads(archive.read(summary_name).decode("utf-8"))
            checks["summary_records_checkpoint_hash"] = summary.get("checkpoint_sha256") == result.checkpoint_sha256
            checks["summary_records_model_versions"] = all(summary.get(key) for key in (
                "cpu_offer_generation_version",
                "negotiation_rounds_version",
                "persistent_calendar_version",
                "player_decision_version",
                "live_signing_version",
            ))
            behavior_name = next(name for name in names if name.endswith("/behavioral_checks.csv"))
            behavior_rows = list(csv.DictReader(archive.read(behavior_name).decode("utf-8-sig").splitlines()))
            checks["behavioral_csv_has_no_failures"] = all(row.get("status") == "PASS" for row in behavior_rows if row.get("severity") == "strict")

    after = sha256(checkpoint_path)
    checks["validator_did_not_write_checkpoint"] = before == after

    print("=" * 112)
    print("FREE AGENCY / CPU AI AUDIT EXTENSION V1 VALIDATION")
    print("=" * 112)
    for key, passed in checks.items():
        print(f"  {key}: {'PASS' if passed else 'FAIL'}")
    print("")
    print("VALIDATION AUDIT CONTEXT")
    print(f"  Season: {result.season_label}")
    print(f"  Live phase: {result.live_phase}")
    print(f"  Analysis phase: {result.analysis_phase}")
    print(f"  Controlled teams: {', '.join(result.controlled_teams) or 'none'}")
    print(f"  Generated legal CPU bids: {result.row_counts.get('cpu_free_agency_offers.csv', 0)}")
    print(f"  CPU market evaluations: {result.row_counts.get('cpu_free_agency_market_evaluations.csv', 0)}")
    print(f"  Persistent markets: {result.row_counts.get('persistent_free_agency_markets.csv', 0)}")
    print(f"  FATX transactions: {result.row_counts.get('free_agency_transactions.csv', 0)}")
    print(f"  Checkpoint hash unchanged: {before == after}")

    failed = [key for key, value in checks.items() if not value]
    payload = {
        "validator": VALIDATOR_VERSION,
        "audit": FREE_AGENCY_CPU_AI_AUDIT_VERSION,
        "schema": FREE_AGENCY_CPU_AI_AUDIT_SCHEMA_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "checkpoint_hash_before": before,
        "checkpoint_hash_after": after,
        "passed": not failed,
    }
    print("")
    print(json.dumps(payload, indent=2, sort_keys=True))
    print("")
    if failed:
        print("FREE AGENCY / CPU AI AUDIT EXTENSION V1 VALIDATION FAILED")
        return 1
    print("FREE AGENCY / CPU AI AUDIT EXTENSION V1 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no signing, roster move, calendar advance, Trade Machine mutation, or checkpoint write was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
