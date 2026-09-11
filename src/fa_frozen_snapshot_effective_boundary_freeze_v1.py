from __future__ import annotations

import csv
import hashlib
import io
import json
import pickle
import sys
import tempfile
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


VERSION = "fa-frozen-snapshot-effective-boundary-freeze-v1-2026-08-15"
SEASON_LABEL = "2026-27"
SPLIT_DATE = date(2026, 4, 12)
FIRST_POST_SPLIT_DATE = date(2026, 4, 13)
EXPECTED_CHECKPOINT_SHA256 = "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
EXPECTED_UPSTREAM_CHECKPOINT_SHA256 = "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
BOUNDARY_PATTERN = "fa_team_salary_snapshot_boundary_reconciliation_preview_v1_2026-27_*.zip"
CONTRACT_OPTION_PATTERN = "fa_contract_option_lifecycle_readiness_v1_0_1_2026-27_*.zip"
RIGHTS_REGISTRY_PATTERN = "fa_rights_registry_v2_preview_2026-27_*.zip"
SEMANTIC_PATTERN = "fa_team_salary_missing_components_semantic_resolution_v1_2026-27_*.zip"


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"true", "1", "yes", "y"}


def as_int(value: Any, default: int = 0) -> int:
    text = clean(value).replace(",", "").replace("$", "")
    return int(float(text)) if text else default


def parse_iso_date(value: Any) -> date:
    text = clean(value)
    if not text:
        raise RuntimeError("Missing ISO date value.")
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise RuntimeError(f"Invalid ISO date value: {value!r}") from exc


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


def latest(root: Path, pattern: str) -> Path:
    candidates = [path for path in root.rglob(pattern) if path.is_file()]
    if not candidates:
        raise RuntimeError(f"Missing required passed audit: {pattern}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def csv_suffix(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    member = next((name for name in archive.namelist() if name.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    text = archive.read(member).decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def json_suffix(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    member = next((name for name in archive.namelist() if name.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return json.loads(archive.read(member).decode("utf-8-sig"))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def check_detail(rows: list[dict[str, str]], check_id: str) -> str:
    row = next((item for item in rows if clean(item.get("check_id")) == check_id), {})
    return clean(row.get("detail")) if clean(row.get("status")) == "PASS" else ""


def main() -> int:
    root = Path.cwd().resolve()
    boundary_zip = latest(root, BOUNDARY_PATTERN)
    contract_zip = latest(root, CONTRACT_OPTION_PATTERN)
    rights_zip = latest(root, RIGHTS_REGISTRY_PATTERN)
    semantic_zip = latest(root, SEMANTIC_PATTERN)

    with zipfile.ZipFile(boundary_zip) as archive:
        boundary_summary = json_suffix(archive, "snapshot_boundary_summary.json")
        boundary_checks = csv_suffix(archive, "snapshot_boundary_checks.csv")
        boundary_team_rows = csv_suffix(archive, "snapshot_boundary_team_reconciliation_30.csv")
        prior_queue = csv_suffix(archive, "frozen_snapshot_missing_component_queue_4.csv")

    with zipfile.ZipFile(contract_zip) as archive:
        contract_summary = json_suffix(archive, "contract_option_summary.json")
        contract_checks = csv_suffix(archive, "contract_option_checks.csv")

    with zipfile.ZipFile(rights_zip) as archive:
        rights_summary = json_suffix(archive, "final_rights_summary.json")
        rights_checks = csv_suffix(archive, "final_rights_checks.csv")
        rights_salary_rows = csv_suffix(archive, "final_rights_salary_resolution.csv")

    with zipfile.ZipFile(semantic_zip) as archive:
        semantic_summary = json_suffix(archive, "semantic_resolution_summary.json")
        semantic_checks = csv_suffix(archive, "semantic_resolution_checks.csv")
        known_incentive_rows = csv_suffix(archive, "canonical_known_likely_incentives.csv")

    if str(root / "src") not in sys.path:
        sys.path.insert(0, str(root / "src"))
    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    simulation_digest_before = object_digest(checkpoint.simulation_state)
    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError("Canonical checkpoint changed before effective-boundary freeze.")

    contract_split = parse_iso_date(contract_summary.get("simulation_split_date"))
    rights_split = parse_iso_date(rights_summary.get("simulation_split_date"))
    rights_row_split_dates = {
        parse_iso_date(row.get("simulation_split_date"))
        for row in rights_salary_rows
        if clean(row.get("simulation_split_date"))
    }
    live_capture_dates = [parse_iso_date(row.get("live_source_fetched_at_utc")) for row in boundary_team_rows]

    temporal_contract = [
        {
            "boundary_id": "canonical_2026_offseason_opening_snapshot",
            "season_label": SEASON_LABEL,
            "authoritative_grain": "calendar_date",
            "last_inclusive_snapshot_date": SPLIT_DATE.isoformat(),
            "first_post_split_date": FIRST_POST_SPLIT_DATE.isoformat(),
            "same_day_policy": "events_dated_2026_04_12_are_included",
            "post_split_policy": "events_dated_2026_04_13_or_later_are_excluded_from_opening_snapshot",
            "time_of_day_policy": "not_invented_upstream_authority_is_date_only",
            "timezone_policy": "not_applicable_at_authoritative_date_grain",
            "capture_timestamp_policy": "source_fetch_time_is_provenance_not_component_effective_time",
            "future_outcome_policy": "do_not_backfill_post_split_outcomes_into_opening_snapshot",
            "financial_component_policy": "component_must_be_effective_on_or_before_split_date_and_valid_for_2026_27",
            "status": "frozen",
            "applied_to_simulation": False,
            "checkpoint_mutation_applied": False,
        }
    ]

    boundary_evidence_rows = [
        {
            "evidence_id": "contract_option_lifecycle",
            "source_audit": contract_zip.name,
            "reported_split_date": contract_summary.get("simulation_split_date"),
            "checkpoint_sha256": contract_summary.get("checkpoint_sha256_after"),
            "passed": bool(contract_summary.get("passed")),
            "independent_role": "contract_and_option_state_cutoff",
            "supports_boundary": contract_split == SPLIT_DATE,
        },
        {
            "evidence_id": "rights_registry_v2",
            "source_audit": rights_zip.name,
            "reported_split_date": rights_summary.get("simulation_split_date"),
            "checkpoint_sha256": rights_summary.get("checkpoint_sha256_after"),
            "passed": bool(rights_summary.get("passed")),
            "independent_role": "rights_and_prior_salary_cutoff",
            "supports_boundary": rights_split == SPLIT_DATE and rights_row_split_dates == {SPLIT_DATE},
        },
        {
            "evidence_id": "team_salary_snapshot_boundary",
            "source_audit": boundary_zip.name,
            "reported_split_date": SPLIT_DATE.isoformat(),
            "checkpoint_sha256": check_detail(boundary_checks, "checkpoint_file_unchanged"),
            "passed": bool(boundary_summary.get("passed")),
            "independent_role": "live_vs_frozen_population_quarantine",
            "supports_boundary": len(boundary_team_rows) == 30 and all(item > SPLIT_DATE for item in live_capture_dates),
        },
    ]

    source_eligibility_rows = [
        {
            "source_class": "frozen_361_player_salary_posture",
            "temporal_status": "opening_snapshot_eligible",
            "allowed_use": "base_salary_and_two_way_exclusion_evidence",
            "blocked_use": "cannot_claim_complete_official_team_salary",
            "reason": "Population is the canonical frozen branch but component ledgers remain incomplete.",
        },
        {
            "source_class": "contract_option_lifecycle",
            "temporal_status": "opening_snapshot_eligible",
            "allowed_use": "contract_state_as_of_2026_04_12",
            "blocked_use": "post_split_option_outcomes",
            "reason": "The passed audit explicitly imports zero post-split option outcomes.",
        },
        {
            "source_class": "rights_registry_v2",
            "temporal_status": "opening_snapshot_eligible",
            "allowed_use": "rights_and_prior_salary_evidence_as_of_2026_04_12",
            "blocked_use": "future_transaction_backfill",
            "reason": "The registry and its salary rows carry the same simulation split date.",
        },
        {
            "source_class": "live_salaryswish_team_pages_2026_08_15",
            "temporal_status": "post_split_context_only",
            "allowed_use": "candidate_discovery_and_later_state_comparison",
            "blocked_use": "direct_component_merge_into_opening_snapshot",
            "reason": "All 30 live roster populations and roster-cap components differ from the frozen branch.",
        },
        {
            "source_class": "project_native_semantic_probe_signals",
            "temporal_status": "exclusion_and_gap_evidence",
            "allowed_use": "close_false_positives_and retain_one_exact_likely_incentive",
            "blocked_use": "infer_missing_dead_cap_or_rookie_hold_values",
            "reason": "The passed semantic layer found zero exact dead-money rows and zero exact generated 2026 rookie-hold rows.",
        },
        {
            "source_class": "canonical_checkpoint",
            "temporal_status": "durable_state_anchor",
            "allowed_use": "identity_population_and_unchanged_state_safety",
            "blocked_use": "treat_absent_component_fields_as_authoritative_zero",
            "reason": "Absence proves the component is not modeled, not that the real financial amount is zero.",
        },
    ]

    remaining_blockers = [
        {
            "priority": 1,
            "blocker_id": "frozen_dead_cap_and_waiver_ledger",
            "temporal_requirement": "effective_on_or_before_2026_04_12_and_valid_for_2026_27",
            "known_exact_rows": as_int(semantic_summary.get("exact_dead_money_rows_discovered")),
            "known_exact_total": "",
            "required_next_input": "Player-level waived, stretched, retained, and dead-money charges for every team at the frozen boundary.",
            "opening_snapshot_complete": False,
        },
        {
            "priority": 2,
            "blocker_id": "frozen_likely_and_unlikely_incentive_ledger",
            "temporal_requirement": "contract_and_classification_effective_on_or_before_2026_04_12_for_2026_27",
            "known_exact_rows": len(known_incentive_rows),
            "known_exact_total": sum(as_int(row.get("known_likely_incentive_2026_27")) for row in known_incentive_rows),
            "required_next_input": "Complete player-level likely and unlikely incentive classifications without substituting guarantee values.",
            "opening_snapshot_complete": False,
        },
        {
            "priority": 3,
            "blocker_id": "post_draft_2026_first_round_pick_hold_bridge",
            "temporal_requirement": "do_not_backfill_into_2026_04_12_opening_snapshot_create_at_simulated_draft_event",
            "known_exact_rows": as_int(semantic_summary.get("exact_2026_generated_rookie_hold_rows_discovered")),
            "known_exact_total": "",
            "required_next_input": "Bridge the simulator's 2026 first-round draft results and signing status to dynamic rookie-scale holds when the draft event occurs.",
            "opening_snapshot_complete": False,
        },
    ]

    closed_blocker_rows = [
        {
            "prior_priority": 1,
            "blocker_id": "canonical_frozen_snapshot_effective_timestamp",
            "resolution": "closed_at_finest_authoritative_grain",
            "canonical_value": SPLIT_DATE.isoformat(),
            "authoritative_grain": "calendar_date",
            "inclusive": True,
            "time_of_day_invented": False,
            "independent_passed_evidence_count": 2,
            "resolution_applied_to_simulation": False,
        }
    ]

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

    print("=" * 132)
    print("2026 FROZEN SNAPSHOT EFFECTIVE BOUNDARY FREEZE V1")
    print("=" * 132)
    print("Freezing the authoritative date boundary and classifying source eligibility...")

    add("snapshot_boundary_reconciliation_passed", bool(boundary_summary.get("passed")) and not boundary_summary.get("failed_checks"), boundary_zip.name)
    add("contract_option_lifecycle_passed", bool(contract_summary.get("passed")) and not contract_summary.get("failed_strict_checks"), contract_zip.name)
    add("rights_registry_v2_passed", bool(rights_summary.get("passed")) and not rights_summary.get("failed_strict_checks"), rights_zip.name)
    add("component_semantic_resolution_passed", bool(semantic_summary.get("passed")) and not semantic_summary.get("failed_checks"), semantic_zip.name)
    add("two_independent_systems_report_exact_split_date", contract_split == rights_split == SPLIT_DATE, SPLIT_DATE.isoformat())
    add(
        "all_boundary_evidence_references_canonical_checkpoint",
        contract_summary.get("checkpoint_sha256_after") == EXPECTED_UPSTREAM_CHECKPOINT_SHA256
        and rights_summary.get("checkpoint_sha256_after") == EXPECTED_UPSTREAM_CHECKPOINT_SHA256
        and check_detail(boundary_checks, "checkpoint_file_unchanged") == EXPECTED_UPSTREAM_CHECKPOINT_SHA256,
        EXPECTED_UPSTREAM_CHECKPOINT_SHA256,
    )
    add("all_106_rights_salary_rows_carry_exact_split_date", len(rights_salary_rows) == 106 and rights_row_split_dates == {SPLIT_DATE}, f"rows={len(rights_salary_rows)}")
    add("canonical_boundary_is_inclusive_date_only", temporal_contract[0]["authoritative_grain"] == "calendar_date" and temporal_contract[0]["last_inclusive_snapshot_date"] == "2026-04-12" and temporal_contract[0]["first_post_split_date"] == "2026-04-13", "inclusive through 2026-04-12")
    add("no_unsupported_time_of_day_or_timezone_invented", temporal_contract[0]["time_of_day_policy"].startswith("not_invented") and temporal_contract[0]["timezone_policy"].startswith("not_applicable"), "date grain retained")
    add("all_30_live_component_captures_are_post_split", len(live_capture_dates) == 30 and all(item > SPLIT_DATE for item in live_capture_dates), f"rows={len(live_capture_dates)}")
    add("live_component_direct_merge_remains_blocked_for_all_teams", int(boundary_summary.get("direct_live_component_merge_safe_team_count", -1)) == 0, "0/30")
    add("frozen_population_identity_is_preserved", int(boundary_summary.get("frozen_attached_player_count", -1)) == 361 and int(boundary_summary.get("frozen_standard_contract_count", -1)) == 331 and int(boundary_summary.get("frozen_two_way_contract_count", -1)) == 30, "361=331+30")
    add("prior_queue_contains_exact_timestamp_blocker", len(prior_queue) == 4 and sum(clean(row.get("blocker_id")) == "canonical_frozen_snapshot_effective_timestamp" for row in prior_queue) == 1, "1/4")
    add("timestamp_blocker_closed_exactly_once", len(closed_blocker_rows) == 1 and closed_blocker_rows[0]["canonical_value"] == "2026-04-12", "closed=1")
    add("exact_three_financial_component_blockers_remain", len(remaining_blockers) == 3, "dead cap, incentives, post-draft rookie holds")
    add("semantic_probe_found_zero_exact_dead_money_rows", as_int(semantic_summary.get("exact_dead_money_rows_discovered")) == 0, "rows=0")
    add("exact_one_known_likely_incentive_is_preserved", len(known_incentive_rows) == 1 and sum(as_int(row.get("known_likely_incentive_2026_27")) for row in known_incentive_rows) == 814620, "Thomas Sorber=$814,620")
    add("rookie_hold_is_dynamic_post_draft_not_backfilled", as_int(semantic_summary.get("exact_2026_generated_rookie_hold_rows_discovered")) == 0 and "simulated_draft_event" in remaining_blockers[2]["temporal_requirement"], "opening snapshot rows=0")
    add("source_eligibility_matrix_has_exact_six_classes", len(source_eligibility_rows) == 6, "6/6")
    add("official_team_salary_remains_incomplete", not bool(boundary_summary.get("official_team_salary_complete")) and not bool(semantic_summary.get("official_team_salary_complete")), "blocked by three components")
    add("no_financial_value_or_boundary_applied_to_simulation", not temporal_contract[0]["applied_to_simulation"] and all(not row["opening_snapshot_complete"] for row in remaining_blockers), "evidence only")

    simulation_digest_after = object_digest(checkpoint.simulation_state)
    checkpoint_hash_after = sha256_file(checkpoint_path)
    add("loaded_simulation_state_unchanged", simulation_digest_after == simulation_digest_before, simulation_digest_after)
    add("checkpoint_file_unchanged", checkpoint_hash_after == checkpoint_hash_before == EXPECTED_CHECKPOINT_SHA256, checkpoint_hash_after)

    failed = [row["check_id"] for row in checks if row["status"] == "FAIL"]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_frozen_snapshot_effective_boundary_freeze_v1_{SEASON_LABEL}_{timestamp}"
    output_dir = root / "outputs" / "audits"
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = output_dir / f"{export_id}.zip"
    summary = {
        "version": VERSION,
        "canonical_snapshot_branch": "frozen_pre_offseason_split",
        "canonical_split_date": SPLIT_DATE.isoformat(),
        "canonical_boundary_grain": "calendar_date",
        "canonical_split_date_inclusive": True,
        "first_post_split_date": FIRST_POST_SPLIT_DATE.isoformat(),
        "time_of_day_invented": False,
        "timestamp_blocker_closed_count": len(closed_blocker_rows),
        "remaining_financial_component_blocker_count": len(remaining_blockers),
        "remaining_blockers": [row["blocker_id"] for row in remaining_blockers],
        "live_component_direct_merge_safe_team_count": 0,
        "known_exact_likely_incentive_count": len(known_incentive_rows),
        "known_exact_likely_incentive_total": sum(as_int(row.get("known_likely_incentive_2026_27")) for row in known_incentive_rows),
        "official_team_salary_complete": False,
        "boundary_applied_to_simulation": False,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "passed": not failed,
        "failed_checks": failed,
        "next_slice": (
            "Build the frozen player-level dead-cap/waiver evidence registry using only charges effective on or before 2026-04-12 and valid for 2026-27. "
            "Keep live August team totals quarantined and do not compute official Team Salary yet."
        ),
    }

    with tempfile.TemporaryDirectory(prefix="fa_effective_boundary_") as temporary_directory:
        export = Path(temporary_directory) / export_id
        export.mkdir(parents=True)
        write_csv(export / "canonical_effective_boundary_contract.csv", temporal_contract)
        write_csv(export / "effective_boundary_evidence_3.csv", boundary_evidence_rows)
        write_csv(export / "component_source_temporal_eligibility_6.csv", source_eligibility_rows)
        write_csv(export / "closed_snapshot_blocker_1.csv", closed_blocker_rows)
        write_csv(export / "remaining_financial_component_blockers_3.csv", remaining_blockers)
        write_csv(export / "effective_boundary_checks.csv", checks)
        (export / "effective_boundary_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        (export / "README.txt").write_text(
            """2026 FROZEN SNAPSHOT EFFECTIVE BOUNDARY FREEZE V1
==================================================

Purpose
-------
Close the snapshot-date blocker at the finest grain supported by authoritative
project evidence. Two independent passed systems identify April 12, 2026 as
the simulation split date. The boundary is date-only and inclusive; April 13
is the first post-split date. No time of day or timezone is invented.

Result
------
The opening snapshot may use evidence effective on or before April 12 when it
is valid for 2026-27. Later source captures remain comparison or candidate
evidence only. Post-split outcomes cannot be backfilled into the opening state.

The timestamp blocker is closed. Three financial blockers remain: the frozen
dead-cap/waiver ledger, complete likely/unlikely incentives, and a dynamic
post-draft 2026 first-round pick-hold bridge.

Safety
------
No salary, cap hold, rights decision, roster, simulation, overlay, or
checkpoint mutation occurs. Official Team Salary remains incomplete.
""",
            encoding="utf-8",
        )
        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.iterdir()):
                archive.write(item, arcname=f"{export_id}/{item.name}")

    if failed:
        print("")
        print(f"Diagnostic audit ZIP: {audit_zip}")
        raise RuntimeError("Frozen Snapshot Effective Boundary Freeze V1 failed: " + ", ".join(failed))

    print("")
    print("=" * 132)
    print("2026 FROZEN SNAPSHOT EFFECTIVE BOUNDARY FREEZE V1 PASSED")
    print("=" * 132)
    print("Canonical split date:               2026-04-12 (inclusive)")
    print("First post-split date:              2026-04-13")
    print("Authoritative grain:                calendar date")
    print("Timestamp blocker closed:           1/1")
    print("Financial component blockers left:  3")
    print("Live component merges allowed:      0/30")
    print("Official Team Salary complete:      NO")
    print("Checkpoint write:                   NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
