"""Consolidate RL-B01 through RL-B12 into a validated right-legality release.

This script is intentionally dependency-free. Save it in the project's ``src``
directory and run it from any working directory with the project's Python
environment. It discovers the completed research batches beneath ``outputs``.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCRIPT_VERSION = "mixed-player-pick-right-legality-consolidator-v1-2026-08-05"
RELEASE_NAME = "mixed_player_pick_right_legality_evidence_2026_27_v1"
EXPECTED_BATCHES = [f"RL-B{i:02d}" for i in range(1, 13)]
EXPECTED_ROWS_BY_BATCH = {batch: (1 if batch == "RL-B12" else 10) for batch in EXPECTED_BATCHES}
EXPECTED_TOTAL_ROWS = 111
EXPECTED_SCHEMA_COLUMNS = 73
EXPECTED_EVIDENCE_GROUPS = 89
EXPECTED_NONBLANK_CLAIM_IDS = 71
EXPECTED_UNIQUE_NONBLANK_CLAIM_IDS = 69
EXPECTED_DETERMINATIONS = {
    "legal_with_conditions": 106,
    "manual_review_required": 3,
    "not_legal_as_modeled": 2,
}
ALLOWED_DETERMINATIONS = set(EXPECTED_DETERMINATIONS)
IMMUTABLE_COLUMN_COUNT = 48

FULL_RELEASE_NAME = "mixed_player_pick_right_legality_evidence_release_v1.csv"
DECISION_RELEASE_NAME = "mixed_player_pick_right_legality_decision_release_v1.csv"
VALIDATION_NAME = "mixed_player_pick_right_legality_consolidation_validation_v1.csv"
METADATA_NAME = "mixed_player_pick_right_legality_consolidation_metadata_v1.json"

DECISION_COLUMNS = [
    "research_sequence",
    "research_batch_id",
    "research_row_in_batch",
    "future_pick_right_id",
    "candidate_team",
    "evidence_group_key",
    "claim_id",
    "right_structure",
    "source_assets",
    "right_legality_determination",
    "right_legality_stage_passed",
    "right_legality_manual_review_required",
    "right_legality_blocked",
    "right_legality_release_status",
    "standalone_tradability_determination",
    "right_terms_summary",
    "resolution_reason",
    "authoritative_source_name",
    "authoritative_source_url",
    "authoritative_source_as_of_date",
    "reviewer_notes",
]


def project_root() -> Path:
    script_path = Path(__file__).resolve()
    if script_path.parent.name.lower() == "src":
        return script_path.parent.parent
    return script_path.parent


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    return headers, rows


def write_csv(path: Path, headers: list[str], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_bool(value: str) -> bool | None:
    lowered = str(value).strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return None


def locate_one(outputs_dir: Path, filename: str) -> tuple[Path | None, list[Path]]:
    matches = sorted(path for path in outputs_dir.rglob(filename) if path.is_file())
    return (matches[0] if len(matches) == 1 else None), matches


def release_status(determination: str) -> tuple[str, str, str, str]:
    if determination == "legal_with_conditions":
        return "True", "False", "False", "right_legality_evidence_passed_with_conditions"
    if determination == "manual_review_required":
        return "False", "True", "False", "right_legality_manual_review_required"
    if determination == "not_legal_as_modeled":
        return "False", "False", "True", "right_legality_not_legal_as_modeled"
    raise ValueError(f"Unsupported determination: {determination!r}")


def main() -> int:
    root = project_root()
    outputs_dir = root / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    validation_path = outputs_dir / VALIDATION_NAME
    metadata_path = outputs_dir / METADATA_NAME
    full_release_path = outputs_dir / FULL_RELEASE_NAME
    decision_release_path = outputs_dir / DECISION_RELEASE_NAME

    print("=" * 80)
    print("MIXED PLAYER-AND-PICK RIGHT LEGALITY EVIDENCE CONSOLIDATOR")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print(f"Release name: {RELEASE_NAME}")
    print()

    validations: list[dict[str, str]] = []

    def check(name: str, passed: bool, observed: Any, expected: Any) -> None:
        validations.append(
            {
                "check_name": name,
                "passed": str(bool(passed)),
                "observed": str(observed),
                "expected": str(expected),
            }
        )

    print("[1/7] Locating completed research batches and original inputs")
    completed_paths: dict[str, Path] = {}
    input_paths: dict[str, Path] = {}
    duplicate_completed: dict[str, list[str]] = {}
    duplicate_inputs: dict[str, list[str]] = {}

    for batch in EXPECTED_BATCHES:
        token = batch.split("-")[1].lower()
        completed_name = f"mixed_player_pick_right_legality_rl_{token}_evidence_completed_v1.csv"
        input_name = f"mixed_player_pick_right_legality_rl_{token}_evidence_input_v1.csv"

        completed_path, completed_matches = locate_one(outputs_dir, completed_name)
        if completed_path is not None:
            completed_paths[batch] = completed_path
        elif len(completed_matches) > 1:
            duplicate_completed[batch] = [str(path) for path in completed_matches]

        input_path, input_matches = locate_one(outputs_dir, input_name)
        if input_path is not None:
            input_paths[batch] = input_path
        elif len(input_matches) > 1:
            duplicate_inputs[batch] = [str(path) for path in input_matches]

    missing_completed = [batch for batch in EXPECTED_BATCHES if batch not in completed_paths]
    missing_inputs = [batch for batch in EXPECTED_BATCHES if batch not in input_paths]
    check("completed_batch_file_count", len(completed_paths) == 12, len(completed_paths), 12)
    check("no_missing_completed_batches", not missing_completed, "|".join(missing_completed), "")
    check("no_duplicate_completed_batches", not duplicate_completed, json.dumps(duplicate_completed), "{}")
    check("original_input_file_count", len(input_paths) == 12, len(input_paths), 12)
    check("no_missing_original_inputs", not missing_inputs, "|".join(missing_inputs), "")
    check("no_duplicate_original_inputs", not duplicate_inputs, json.dumps(duplicate_inputs), "{}")

    if missing_completed or duplicate_completed or missing_inputs or duplicate_inputs:
        write_csv(validation_path, ["check_name", "passed", "observed", "expected"], validations)
        metadata = {
            "script_version": SCRIPT_VERSION,
            "release_name": RELEASE_NAME,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "release_valid": False,
            "missing_completed_batches": missing_completed,
            "missing_original_inputs": missing_inputs,
            "duplicate_completed_batches": duplicate_completed,
            "duplicate_original_inputs": duplicate_inputs,
            "validation_file": str(validation_path),
        }
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        print("\nCannot consolidate until every batch has exactly one completed file and one original input file.")
        print(f"Validation: {validation_path}")
        print(f"Metadata: {metadata_path}")
        return 1

    print("[2/7] Loading all 111 completed evidence rows")
    canonical_headers: list[str] | None = None
    completed_rows: list[dict[str, str]] = []
    headers_identical = True
    schema_column_counts: list[int] = []
    batch_row_counts: dict[str, int] = {}
    batch_ids_match = True
    row_numbers_match = True

    for batch in EXPECTED_BATCHES:
        headers, rows = read_csv(completed_paths[batch])
        schema_column_counts.append(len(headers))
        if canonical_headers is None:
            canonical_headers = headers
        elif headers != canonical_headers:
            headers_identical = False

        batch_row_counts[batch] = len(rows)
        if any(row.get("research_batch_id") != batch for row in rows):
            batch_ids_match = False
        observed_row_numbers = sorted(int(row["research_row_in_batch"]) for row in rows)
        if observed_row_numbers != list(range(1, len(rows) + 1)):
            row_numbers_match = False
        completed_rows.extend(rows)

    assert canonical_headers is not None
    check("schema_column_count", set(schema_column_counts) == {73}, sorted(set(schema_column_counts)), [73])
    check("batch_headers_identical", headers_identical, headers_identical, True)
    check("batch_row_counts", batch_row_counts == EXPECTED_ROWS_BY_BATCH, json.dumps(batch_row_counts, sort_keys=True), json.dumps(EXPECTED_ROWS_BY_BATCH, sort_keys=True))
    check("batch_ids_match_filenames", batch_ids_match, batch_ids_match, True)
    check("row_numbers_contiguous_within_batch", row_numbers_match, row_numbers_match, True)
    check("total_evidence_rows", len(completed_rows) == EXPECTED_TOTAL_ROWS, len(completed_rows), EXPECTED_TOTAL_ROWS)

    print("[3/7] Verifying immutable columns against the original research packets")
    input_by_right: dict[str, dict[str, str]] = {}
    input_headers_identical = True
    input_total_rows = 0
    for batch in EXPECTED_BATCHES:
        input_headers, input_rows = read_csv(input_paths[batch])
        if input_headers != canonical_headers:
            input_headers_identical = False
        input_total_rows += len(input_rows)
        for row in input_rows:
            right_id = row.get("future_pick_right_id", "")
            if right_id in input_by_right:
                raise ValueError(f"Duplicate right in original inputs: {right_id}")
            input_by_right[right_id] = row

    immutable_mismatches: list[str] = []
    missing_input_rights: list[str] = []
    for row in completed_rows:
        right_id = row.get("future_pick_right_id", "")
        original = input_by_right.get(right_id)
        if original is None:
            missing_input_rights.append(right_id)
            continue
        for column in canonical_headers[:IMMUTABLE_COLUMN_COUNT]:
            if row.get(column, "") != original.get(column, ""):
                immutable_mismatches.append(f"{right_id}:{column}")

    check("original_input_headers_match_completed", input_headers_identical, input_headers_identical, True)
    check("original_input_total_rows", input_total_rows == EXPECTED_TOTAL_ROWS, input_total_rows, EXPECTED_TOTAL_ROWS)
    check("all_completed_rights_found_in_original_inputs", not missing_input_rights, "|".join(missing_input_rights), "")
    check("immutable_columns_1_through_48_preserved", not immutable_mismatches, "|".join(immutable_mismatches[:20]), "")

    print("[4/7] Validating research completeness and decision consistency")
    sequences = [int(row["research_sequence"]) for row in completed_rows]
    right_ids = [row.get("future_pick_right_id", "") for row in completed_rows]
    claim_ids = [row.get("claim_id", "") for row in completed_rows]
    determinations = Counter(row.get("right_legality_determination", "") for row in completed_rows)
    manual_values = [normalized_bool(row.get("manual_review_required", "")) for row in completed_rows]

    required_fields_complete = True
    missing_required_fields: list[str] = []
    for row in completed_rows:
        required = [field for field in row.get("required_research_fields", "").split("|") if field]
        for field in required:
            if not row.get(field, "").strip():
                required_fields_complete = False
                missing_required_fields.append(f"{row.get('future_pick_right_id')}:{field}")

    manual_consistent = all(
        (row.get("right_legality_determination") == "manual_review_required")
        == (normalized_bool(row.get("manual_review_required", "")) is True)
        for row in completed_rows
    )
    blocked_not_manual = all(
        normalized_bool(row.get("manual_review_required", "")) is False
        for row in completed_rows
        if row.get("right_legality_determination") == "not_legal_as_modeled"
    )

    check("research_sequence_unique", len(set(sequences)) == EXPECTED_TOTAL_ROWS, len(set(sequences)), EXPECTED_TOTAL_ROWS)
    check("research_sequence_complete_1_to_111", sorted(sequences) == list(range(1, 112)), f"{min(sequences)}-{max(sequences)}", "1-111")
    check("future_pick_right_ids_nonblank", all(right_ids), sum(bool(value) for value in right_ids), EXPECTED_TOTAL_ROWS)
    check("future_pick_right_ids_unique", len(set(right_ids)) == EXPECTED_TOTAL_ROWS, len(set(right_ids)), EXPECTED_TOTAL_ROWS)
    evidence_group_keys = [row.get("evidence_group_key", "") for row in completed_rows]
    nonblank_claim_ids = [value for value in claim_ids if value]
    check("evidence_group_keys_nonblank", all(evidence_group_keys), sum(bool(value) for value in evidence_group_keys), EXPECTED_TOTAL_ROWS)
    check("unique_evidence_groups", len(set(evidence_group_keys)) == EXPECTED_EVIDENCE_GROUPS, len(set(evidence_group_keys)), EXPECTED_EVIDENCE_GROUPS)
    check("optional_claim_id_population", len(nonblank_claim_ids) == EXPECTED_NONBLANK_CLAIM_IDS, len(nonblank_claim_ids), EXPECTED_NONBLANK_CLAIM_IDS)
    check("unique_nonblank_claim_ids", len(set(nonblank_claim_ids)) == EXPECTED_UNIQUE_NONBLANK_CLAIM_IDS, len(set(nonblank_claim_ids)), EXPECTED_UNIQUE_NONBLANK_CLAIM_IDS)
    check("research_status_completed", all(row.get("research_status") == "completed" for row in completed_rows), Counter(row.get("research_status") for row in completed_rows), {"completed": 111})
    check("required_research_fields_populated", required_fields_complete, "|".join(missing_required_fields[:20]), "")
    check("determinations_allowed", set(determinations).issubset(ALLOWED_DETERMINATIONS), sorted(determinations), sorted(ALLOWED_DETERMINATIONS))
    check("determination_counts", dict(determinations) == EXPECTED_DETERMINATIONS, json.dumps(dict(determinations), sort_keys=True), json.dumps(EXPECTED_DETERMINATIONS, sort_keys=True))
    check("manual_review_flags_parseable", all(value is not None for value in manual_values), Counter(str(value) for value in manual_values), {"True": 3, "False": 108})
    check("manual_review_flag_count", sum(value is True for value in manual_values) == 3, sum(value is True for value in manual_values), 3)
    check("manual_review_determination_consistency", manual_consistent, manual_consistent, True)
    check("blocked_rights_not_marked_manual", blocked_not_manual, blocked_not_manual, True)
    check("source_authority_verified", all(normalized_bool(row.get("source_authority_verified", "")) is True for row in completed_rows), sum(normalized_bool(row.get("source_authority_verified", "")) is True for row in completed_rows), EXPECTED_TOTAL_ROWS)
    check("authoritative_source_urls_present", all(row.get("authoritative_source_url", "").strip() for row in completed_rows), sum(bool(row.get("authoritative_source_url", "").strip()) for row in completed_rows), EXPECTED_TOTAL_ROWS)
    check("authoritative_source_dates_present", all(row.get("authoritative_source_as_of_date", "").strip() for row in completed_rows), sum(bool(row.get("authoritative_source_as_of_date", "").strip()) for row in completed_rows), EXPECTED_TOTAL_ROWS)

    print("[5/7] Building full evidence and package-ready right decision releases")
    completed_rows.sort(key=lambda row: int(row["research_sequence"]))
    decision_rows: list[dict[str, str]] = []
    for row in completed_rows:
        passed, manual, blocked, status = release_status(row["right_legality_determination"])
        decision_rows.append(
            {
                "research_sequence": row["research_sequence"],
                "research_batch_id": row["research_batch_id"],
                "research_row_in_batch": row["research_row_in_batch"],
                "future_pick_right_id": row["future_pick_right_id"],
                "candidate_team": row["candidate_team"],
                "evidence_group_key": row["evidence_group_key"],
                "claim_id": row["claim_id"],
                "right_structure": row["right_structure"],
                "source_assets": row["source_assets"],
                "right_legality_determination": row["right_legality_determination"],
                "right_legality_stage_passed": passed,
                "right_legality_manual_review_required": manual,
                "right_legality_blocked": blocked,
                "right_legality_release_status": status,
                "standalone_tradability_determination": row["standalone_tradability_determination"],
                "right_terms_summary": row["right_terms_summary"],
                "resolution_reason": row["resolution_reason"],
                "authoritative_source_name": row["authoritative_source_name"],
                "authoritative_source_url": row["authoritative_source_url"],
                "authoritative_source_as_of_date": row["authoritative_source_as_of_date"],
                "reviewer_notes": row["reviewer_notes"],
            }
        )

    release_valid = all(row["passed"] == "True" for row in validations)
    check("pre_release_validation_gate", release_valid, release_valid, True)
    release_valid = all(row["passed"] == "True" for row in validations)

    print("[6/7] Saving releases, validation audit, and metadata")
    if release_valid:
        write_csv(full_release_path, canonical_headers, completed_rows)
        write_csv(decision_release_path, DECISION_COLUMNS, decision_rows)

    write_csv(validation_path, ["check_name", "passed", "observed", "expected"], validations)

    output_files: dict[str, dict[str, Any]] = {}
    for label, path in {
        "full_evidence_release": full_release_path,
        "decision_release": decision_release_path,
        "validation": validation_path,
    }.items():
        if path.exists():
            output_files[label] = {
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "sha256": sha256(path),
            }

    metadata = {
        "script_version": SCRIPT_VERSION,
        "release_name": RELEASE_NAME,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "research_as_of_date": "2026-08-04",
        "release_valid": release_valid,
        "input_batches": 12,
        "evidence_rows": len(completed_rows),
        "schema_columns": len(canonical_headers),
        "unique_future_pick_right_ids": len(set(right_ids)),
        "unique_evidence_groups": len(set(evidence_group_keys)),
        "nonblank_claim_ids": len(nonblank_claim_ids),
        "unique_nonblank_claim_ids": len(set(nonblank_claim_ids)),
        "candidate_teams": len(set(row["candidate_team"] for row in completed_rows)),
        "determination_counts": dict(sorted(determinations.items())),
        "right_legality_stage_passed": sum(row["right_legality_stage_passed"] == "True" for row in decision_rows),
        "right_legality_manual_review_required": sum(row["right_legality_manual_review_required"] == "True" for row in decision_rows),
        "right_legality_blocked": sum(row["right_legality_blocked"] == "True" for row in decision_rows),
        "validation_checks_passed": sum(row["passed"] == "True" for row in validations),
        "validation_checks_total": len(validations),
        "package_final_legal_status_released": False,
        "package_final_legal_note": "This release validates right-level ownership, encumbrance, trade-date evidence, and pick-rule treatment only. It does not mark any mixed player-and-pick package final-legal.",
        "input_files": {
            batch: {
                "completed_path": str(completed_paths[batch]),
                "completed_sha256": sha256(completed_paths[batch]),
                "original_input_path": str(input_paths[batch]),
                "original_input_sha256": sha256(input_paths[batch]),
            }
            for batch in EXPECTED_BATCHES
        },
        "output_files": output_files,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print("[7/7] Reporting release status")
    print()
    print("=" * 80)
    print("RIGHT LEGALITY EVIDENCE CONSOLIDATION COMPLETE")
    print("=" * 80)
    print(f"Batches consolidated: {len(completed_paths)}")
    print(f"Evidence rows: {len(completed_rows)}")
    print(f"Unique rights: {len(set(right_ids))}")
    print(f"Unique evidence groups: {len(set(evidence_group_keys))}")
    print(f"Legal with conditions: {determinations.get('legal_with_conditions', 0)}")
    print(f"Manual review required: {determinations.get('manual_review_required', 0)}")
    print(f"Not legal as modeled: {determinations.get('not_legal_as_modeled', 0)}")
    print(f"Validation checks passed: {sum(row['passed'] == 'True' for row in validations)}/{len(validations)}")
    print(f"Release valid: {release_valid}")
    print("Package final-legal status released: False")
    print()
    print("SAVED FILES")
    if release_valid:
        print(full_release_path)
        print(decision_release_path)
    print(validation_path)
    print(metadata_path)

    return 0 if release_valid else 1


if __name__ == "__main__":
    sys.exit(main())