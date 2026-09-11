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


VERSION = "fa-frozen-incentive-source-acquisition-hotfix-v1.0.3-2026-08-15"
SEASON_LABEL = "2026-27"
SPLIT_DATE = date(2026, 4, 12)
UPSTREAM_PATTERN = "fa_frozen_incentive_source_acquisition_hotfix_v1_0_2_2026-27_*.zip"
EXPECTED_CHECKPOINT_SHA256 = "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
EXPECTED_SIMULATION_DIGEST = "f92f03b4c54e53f8f017c3fca43e93ccd09c8b8ba0e5fe0323f418021baf268e"
EXPECTED_LIKELY_TOTAL = 10_691_125
EXPECTED_UNLIKELY_TOTAL = 42_079_384
EXPECTED_SORBER_LIKELY = 814_620
EXPECTED_UNRESOLVED = {
    "1628380": "unresolved_post_split_contract_only",
    "1628381": "unresolved_post_split_contract_only",
    "1629057": "unresolved_post_split_contract_only",
    "1630604": "unresolved_no_parseable_2026_27_contract_row",
    "1631117": "unresolved_post_split_contract_only",
    "1631127": "unresolved_post_split_contract_only",
    "1631131": "unresolved_post_split_contract_only",
    "1631132": "unresolved_post_split_contract_only",
    "203114": "unresolved_post_split_contract_only",
    "203468": "unresolved_post_split_contract_only",
    "204001": "unresolved_post_split_contract_only",
}
EXPECTED_RETRY_IDS = {
    "1626156", "1627827", "1628983", "1629004", "1629057", "1629631",
    "1629638", "1630545", "1630549", "1641765", "1641772", "1642266",
    "1642857", "1642867", "203484", "203507",
}


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"true", "1", "yes", "y"}


def money_int(value: Any) -> int:
    text = clean(value).replace("$", "").replace(",", "")
    if not text:
        return 0
    try:
        return int(round(float(text)))
    except ValueError:
        return 0


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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
        raise RuntimeError(f"Missing required V1.0.2 diagnostic audit: {pattern}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def member_suffix(archive: zipfile.ZipFile, suffix: str) -> str:
    member = next((name for name in archive.namelist() if name.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"V1.0.2 audit ZIP is missing: {suffix}")
    return member


def csv_suffix(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    payload = archive.read(member_suffix(archive, suffix))
    if not payload:
        return []
    return list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig", errors="replace"))))


def json_suffix(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    return json.loads(archive.read(member_suffix(archive, suffix)).decode("utf-8-sig"))


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


def main() -> int:
    root = Path.cwd().resolve()
    upstream_zip = latest(root, UPSTREAM_PATTERN)
    upstream_zip_sha256 = sha256_file(upstream_zip)

    with zipfile.ZipFile(upstream_zip) as archive:
        upstream_summary = json_suffix(archive, "frozen_incentive_source_acquisition_hotfix_summary.json")
        upstream_checks = csv_suffix(archive, "frozen_incentive_source_acquisition_hotfix_checks.csv")
        captures = csv_suffix(archive, "hotfixed_player_page_capture_331.csv")
        retry_attempts = csv_suffix(archive, "sequential_retry_attempts_16.csv")
        retry_errors = csv_suffix(archive, "sequential_retry_errors.csv")
        parsed_rows = csv_suffix(archive, "hotfixed_parsed_2026_27_contract_rows.csv")
        resolution_rows = csv_suffix(archive, "hotfixed_frozen_incentive_resolution_preview_331.csv")
        unresolved_rows = csv_suffix(archive, "hotfixed_unresolved_incentive_targets.csv")
        positive_rows = csv_suffix(archive, "hotfixed_resolved_positive_incentive_rows.csv")
        team_rows = csv_suffix(archive, "hotfixed_team_incentive_resolution_preview_30.csv")

        snapshot_fingerprints: list[dict[str, Any]] = []
        for capture in captures:
            relative_name = clean(capture.get("snapshot_filename"))
            member = member_suffix(archive, relative_name)
            payload = archive.read(member)
            actual_sha256 = sha256_bytes(payload)
            expected_sha256 = clean(capture.get("source_sha256"))
            snapshot_fingerprints.append({
                "player_id": clean(capture.get("player_id")),
                "player_name": clean(capture.get("player_name")),
                "snapshot_filename": relative_name,
                "source_byte_count": len(payload),
                "expected_sha256": expected_sha256,
                "actual_sha256": actual_sha256,
                "fingerprint_verified": actual_sha256 == expected_sha256,
                "upstream_audit_zip": upstream_zip.name,
            })

    if str(root / "src") not in sys.path:
        sys.path.insert(0, str(root / "src"))
    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    simulation_digest_before = object_digest(checkpoint.simulation_state)
    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError("Canonical checkpoint changed before V1.0.3 offline validation.")

    capture_by_id = {clean(row.get("player_id")): row for row in captures}
    resolution_by_id = {clean(row.get("player_id")): row for row in resolution_rows}
    resolved_rows = [row for row in resolution_rows if not clean(row.get("resolution_status")).startswith("unresolved_")]
    unresolved_map = {
        clean(row.get("player_id")): clean(row.get("resolution_status"))
        for row in unresolved_rows
    }
    post_split_rows = [row for row in parsed_rows if as_bool(row.get("signing_date_is_post_split"))]
    failed_upstream_checks = {
        clean(row.get("check_id")) for row in upstream_checks if clean(row.get("status")) == "FAIL"
    }
    expected_count_failures = {
        "resolution_coverage_is_exactly_321",
        "remaining_temporal_queue_is_exactly_10",
    }

    checks: list[dict[str, str]] = []

    def add(check_id: str, passed: bool, detail: str) -> None:
        checks.append({
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "severity": "strict",
            "detail": detail,
        })
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}")

    print("=" * 132)
    print("2026 FROZEN INCENTIVE SOURCE ACQUISITION HOTFIX V1.0.3")
    print("=" * 132)
    print("Validating the completed 331-page V1.0.2 acquisition entirely offline...")

    add(
        "v1_0_2_failed_only_two_overoptimistic_count_assertions",
        upstream_summary.get("passed") is False
        and set(upstream_summary.get("failed_checks", [])) == expected_count_failures
        and failed_upstream_checks == expected_count_failures,
        "two expected count-only failures",
    )
    add("all_331_player_pages_are_present_and_unique", len(captures) == 331 and len(capture_by_id) == 331, f"{len(captures)}/331")
    add("all_331_snapshot_fingerprints_are_exact", len(snapshot_fingerprints) == 331 and all(row["fingerprint_verified"] for row in snapshot_fingerprints), f"{sum(row['fingerprint_verified'] for row in snapshot_fingerprints)}/331")
    add("capture_origins_are_exactly_315_reused_and_16_recovered", sum(clean(row.get("capture_origin")) == "reused_upstream_snapshot" for row in captures) == 315 and sum(clean(row.get("capture_origin")) == "sequential_hotfix_retry" for row in captures) == 16, "315 reused / 16 recovered")
    add("all_16_recovery_requests_returned_verified_http_200_pages", len(retry_attempts) == 16 and not retry_errors and {clean(row.get("player_id")) for row in retry_attempts} == EXPECTED_RETRY_IDS and all(clean(row.get("http_status")) == "200" and as_bool(row.get("valid_contract_page")) for row in retry_attempts), "16/16")
    add("parsed_contract_row_count_is_exactly_361", len(parsed_rows) == 361, str(len(parsed_rows)))
    add("resolution_registry_is_exactly_331_unique", len(resolution_rows) == 331 and len(resolution_by_id) == 331, f"{len(resolution_rows)}/331")
    add("correct_pre_split_resolution_count_is_320", len(resolved_rows) == 320, f"{len(resolved_rows)}/331")
    add("correct_quarantined_queue_is_exactly_11", len(unresolved_rows) == 11 and unresolved_map == EXPECTED_UNRESOLVED, f"{len(unresolved_rows)}/331")
    add("quarantined_queue_is_10_post_split_and_1_no_parseable_row", sum(status == "unresolved_post_split_contract_only" for status in unresolved_map.values()) == 10 and sum(status == "unresolved_no_parseable_2026_27_contract_row" for status in unresolved_map.values()) == 1, "10 post-split / 1 no-row")
    robert_rows = [row for row in parsed_rows if clean(row.get("player_id")) == "1629057"]
    add("robert_williams_only_row_is_post_split_june_30", len(robert_rows) == 1 and clean(robert_rows[0].get("signing_date")) == "2026-06-30" and as_bool(robert_rows[0].get("signing_date_is_post_split")) and money_int(robert_rows[0].get("likely_incentive")) == 0 and money_int(robert_rows[0].get("unlikely_incentive")) == 0, "2026-06-30 / quarantined")
    add("all_320_selected_rows_are_on_or_before_april_12", all(clean(row.get("signing_date")) and date.fromisoformat(clean(row.get("signing_date"))) <= SPLIT_DATE for row in resolved_rows), "320/320")
    add("all_post_split_rows_remain_quarantined", len(post_split_rows) == 29 and all(not as_bool(row.get("imported_to_frozen_ledger")) for row in post_split_rows), f"{len(post_split_rows)} rows")
    add("positive_incentive_population_is_exactly_54", len(positive_rows) == 54, str(len(positive_rows)))
    likely_total = sum(money_int(row.get("likely_incentive")) for row in resolved_rows)
    unlikely_total = sum(money_int(row.get("unlikely_incentive")) for row in resolved_rows)
    add("resolved_incentive_totals_are_exact", likely_total == EXPECTED_LIKELY_TOTAL and unlikely_total == EXPECTED_UNLIKELY_TOTAL, f"${likely_total:,} likely / ${unlikely_total:,} unlikely")
    sorber = resolution_by_id.get("1642850")
    add("thomas_sorber_814620_likely_incentive_remains_exact", bool(sorber) and money_int(sorber.get("likely_incentive")) == EXPECTED_SORBER_LIKELY, "$814,620")
    add("team_preview_covers_exactly_30_teams", len(team_rows) == 30 and len({clean(row.get("team")) for row in team_rows}) == 30, "30/30")
    add("all_evidence_remains_preview_only", all(not as_bool(row.get("incentive_values_frozen")) and not as_bool(row.get("applied_to_team_salary")) and not as_bool(row.get("state_mutation_applied")) for row in resolution_rows), "0 frozen / 0 applied")

    simulation_digest_after = object_digest(checkpoint.simulation_state)
    checkpoint_hash_after = sha256_file(checkpoint_path)
    add("loaded_simulation_state_unchanged", simulation_digest_after == simulation_digest_before == EXPECTED_SIMULATION_DIGEST, simulation_digest_after)
    add("checkpoint_file_unchanged", checkpoint_hash_after == checkpoint_hash_before == EXPECTED_CHECKPOINT_SHA256, checkpoint_hash_after)

    failed = [row["check_id"] for row in checks if row["status"] == "FAIL"]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_frozen_incentive_source_acquisition_hotfix_v1_0_3_{SEASON_LABEL}_{timestamp}"
    output_dir = root / "outputs" / "audits"
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = output_dir / f"{export_id}.zip"
    summary = {
        "version": VERSION,
        "canonical_split_date": SPLIT_DATE.isoformat(),
        "upstream_v1_0_2_audit_zip": upstream_zip.name,
        "upstream_v1_0_2_audit_sha256": upstream_zip_sha256,
        "player_page_capture_count": len(captures),
        "verified_snapshot_fingerprint_count": sum(row["fingerprint_verified"] for row in snapshot_fingerprints),
        "parsed_2026_27_contract_row_count": len(parsed_rows),
        "correct_pre_split_resolution_count": len(resolved_rows),
        "correct_unresolved_resolution_count": len(unresolved_rows),
        "positive_incentive_player_count": len(positive_rows),
        "resolved_likely_incentive_total": likely_total,
        "resolved_unlikely_incentive_total": unlikely_total,
        "post_split_contract_row_exclusion_count": len(post_split_rows),
        "network_requests_performed": 0,
        "incentive_values_frozen": 0,
        "incentive_values_applied": 0,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "passed": not failed,
        "failed_checks": failed,
        "next_slice": "Resolve only the exact 11-player temporal evidence queue, then freeze the complete 331-player and 30-team incentive ledger.",
    }

    with tempfile.TemporaryDirectory(prefix="fa_frozen_incentive_hotfix_103_") as temporary_directory:
        export = Path(temporary_directory) / export_id
        export.mkdir(parents=True)
        write_csv(export / "validated_player_page_capture_331.csv", captures)
        write_csv(export / "validated_snapshot_fingerprints_331.csv", snapshot_fingerprints)
        write_csv(export / "validated_frozen_incentive_resolution_preview_331.csv", resolution_rows)
        write_csv(export / "validated_unresolved_incentive_targets_11.csv", unresolved_rows)
        write_csv(export / "validated_resolved_positive_incentive_rows_54.csv", positive_rows)
        write_csv(export / "validated_team_incentive_resolution_preview_30.csv", team_rows)
        write_csv(export / "frozen_incentive_source_acquisition_hotfix_v1_0_3_checks.csv", checks)
        (export / "frozen_incentive_source_acquisition_hotfix_v1_0_3_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        (export / "README.txt").write_text(
            """2026 FROZEN INCENTIVE SOURCE ACQUISITION HOTFIX V1.0.3
================================================================

This offline hotfix validates the complete 331-page V1.0.2 acquisition and
corrects only its over-optimistic expected resolution count. The evidence
supports 320 pre-split resolutions and an exact 11-player quarantine queue.
Robert Williams III is the additional case because his only retained 2026-27
contract row is dated June 30, 2026, after the April 12 frozen boundary.

No network request is performed. No incentive value is frozen or applied.
Team Salary, roster state, contracts, simulation state, overlays, and the
canonical checkpoint remain unchanged.
""",
            encoding="utf-8",
        )
        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.rglob("*")):
                if item.is_file():
                    archive.write(item, arcname=f"{export_id}/{item.relative_to(export)}")

    if failed:
        print("")
        print(f"Diagnostic audit ZIP: {audit_zip}")
        raise RuntimeError("Frozen Incentive Source Acquisition Hotfix V1.0.3 failed: " + ", ".join(failed))

    print("")
    print("=" * 132)
    print("2026 FROZEN INCENTIVE SOURCE ACQUISITION HOTFIX V1.0.3 PASSED")
    print("=" * 132)
    print("Player pages validated:          331/331")
    print("Snapshot hashes validated:       331/331")
    print("Pre-split contracts resolved:    320/331")
    print("Exact quarantine queue:           11/331")
    print("Positive incentive players:       54")
    print(f"Resolved likely incentives:      ${likely_total:,}")
    print(f"Resolved unlikely incentives:    ${unlikely_total:,}")
    print("Network requests:                    0")
    print("Incentive values frozen:             0")
    print("Incentive values applied:            0")
    print("Checkpoint write:                 NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
