"""Audit package parquet schemas before propagating right-legality decisions.

Save this file in ``src``. It reads the package-ready 111-right decision CSV
and the two Stepien-evaluated candidate parquet files, then writes a compact
JSON audit and a column-level CSV. It never modifies the package parquets.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_VERSION = "mixed-player-pick-package-right-field-audit-v1-2026-08-05"
RELEASE_NAME = "mixed_player_pick_package_right_field_audit_2026_27_v1"

DECISION_FILENAME = "mixed_player_pick_right_legality_decision_release_v1.csv"
PACKAGE_FILES = {
    "one_for_one": "one_for_one_mixed_player_pick_candidates_2026_27_v5_stepien_evaluated.parquet",
    "two_for_one": "two_for_one_mixed_player_pick_candidates_2026_27_v5_stepien_evaluated.parquet",
}
EXPECTED_PACKAGE_ROWS = {"one_for_one": 28_324, "two_for_one": 282_277}

JSON_OUTPUT = "mixed_player_pick_package_right_field_audit_v1.json"
COLUMN_OUTPUT = "mixed_player_pick_package_right_field_audit_columns_v1.csv"

HIGH_PRIORITY_TOKENS = ("right", "pick", "asset", "claim", "source")
CONTEXT_TOKENS = (
    "package",
    "trade",
    "candidate",
    "outgoing",
    "incoming",
    "team",
    "inventory",
    "component",
    "stepien",
    "legality",
)

REQUIRED_DECISION_COLUMNS = {
    "future_pick_right_id",
    "candidate_team",
    "source_assets",
    "right_legality_determination",
    "right_legality_stage_passed",
    "right_legality_manual_review_required",
    "right_legality_blocked",
    "right_legality_release_status",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run dependency-free helper tests without reading project files.",
    )
    return parser.parse_args()


def project_root() -> Path:
    script_path = Path(__file__).resolve()
    if script_path.parent.name.lower() == "src":
        return script_path.parent.parent
    return script_path.parent


def locate_one(root: Path, filename: str) -> Path:
    preferred = root / "outputs" / filename
    if preferred.is_file():
        return preferred
    matches = sorted(path for path in root.rglob(filename) if path.is_file())
    if not matches:
        raise FileNotFoundError(f"Could not find {filename} beneath {root}")
    if len(matches) > 1:
        joined = "\n  ".join(str(path) for path in matches)
        raise RuntimeError(f"Found multiple copies of {filename}; keep exactly one:\n  {joined}")
    return matches[0]


def read_decisions(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    return headers, rows


def safe_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): safe_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [safe_json(item) for item in value]
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def field_reasons(column_name: str) -> list[str]:
    lowered = column_name.lower()
    reasons: list[str] = []
    for token in HIGH_PRIORITY_TOKENS:
        if token in lowered:
            reasons.append(f"high:{token}")
    for token in CONTEXT_TOKENS:
        if token in lowered:
            reasons.append(f"context:{token}")
    return reasons


def field_priority(reasons: list[str]) -> str:
    if any(reason.startswith("high:") for reason in reasons):
        return "high"
    if reasons:
        return "context"
    return "other"


def is_scalar_string_dtype(dtype_name: str) -> bool:
    normalized = dtype_name.lower().replace(" ", "")
    return normalized in {"string", "utf8", "categorical", "enum"}


def is_nested_dtype(dtype_name: str) -> bool:
    normalized = dtype_name.lower().replace(" ", "")
    return normalized.startswith(("list(", "array(", "struct(", "object"))


def validate_decisions(headers: list[str], rows: list[dict[str, str]]) -> dict[str, Any]:
    missing_columns = sorted(REQUIRED_DECISION_COLUMNS.difference(headers))
    ids = [row.get("future_pick_right_id", "") for row in rows]
    determinations = Counter(row.get("right_legality_determination", "") for row in rows)
    stage_flags = Counter(row.get("right_legality_stage_passed", "") for row in rows)
    manual_flags = Counter(row.get("right_legality_manual_review_required", "") for row in rows)
    blocked_flags = Counter(row.get("right_legality_blocked", "") for row in rows)
    checks = {
        "required_columns_present": not missing_columns,
        "row_count_111": len(rows) == 111,
        "right_ids_nonblank": all(ids),
        "right_ids_unique": len(set(ids)) == 111,
        "determination_counts": determinations
        == Counter(
            {
                "legal_with_conditions": 106,
                "manual_review_required": 3,
                "not_legal_as_modeled": 2,
            }
        ),
        "stage_flag_counts": stage_flags == Counter({"True": 106, "False": 5}),
        "manual_flag_counts": manual_flags == Counter({"False": 108, "True": 3}),
        "blocked_flag_counts": blocked_flags == Counter({"False": 109, "True": 2}),
    }
    return {
        "valid": all(checks.values()),
        "checks": checks,
        "missing_columns": missing_columns,
        "rows": len(rows),
        "unique_right_ids": len(set(ids)),
        "determination_counts": dict(sorted(determinations.items())),
        "stage_flag_counts": dict(sorted(stage_flags.items())),
        "manual_flag_counts": dict(sorted(manual_flags.items())),
        "blocked_flag_counts": dict(sorted(blocked_flags.items())),
    }


def profile_package(
    pl: Any,
    label: str,
    path: Path,
    known_right_ids: list[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    schema = pl.read_parquet_schema(str(path))
    lazy = pl.scan_parquet(str(path))
    row_count = int(lazy.select(pl.len().alias("row_count")).collect().item())

    schema_rows: list[dict[str, Any]] = []
    candidate_columns: list[str] = []
    scalar_string_candidates: list[str] = []
    for position, (name, dtype) in enumerate(schema.items(), start=1):
        dtype_name = str(dtype)
        reasons = field_reasons(name)
        priority = field_priority(reasons)
        if priority != "other":
            candidate_columns.append(name)
        if priority != "other" and is_scalar_string_dtype(dtype_name):
            scalar_string_candidates.append(name)
        schema_rows.append(
            {
                "package_file": label,
                "column_position": position,
                "column_name": name,
                "dtype": dtype_name,
                "semantic_priority": priority,
                "name_match_reasons": "|".join(reasons),
                "null_count": "",
                "unique_count": "",
                "rows_containing_fpr_token": "",
                "rows_exactly_matching_known_right_id": "",
                "sample_values": "",
            }
        )

    profile_expressions: list[Any] = []
    profile_aliases: dict[str, dict[str, str]] = {}
    dtype_by_name = {name: str(dtype) for name, dtype in schema.items()}
    string_dtype = getattr(pl, "String", pl.Utf8)
    for index, name in enumerate(candidate_columns):
        aliases = {"null": f"null__{index}"}
        profile_expressions.append(pl.col(name).null_count().alias(aliases["null"]))
        if not is_nested_dtype(dtype_by_name[name]):
            aliases["unique"] = f"unique__{index}"
            profile_expressions.append(pl.col(name).n_unique().alias(aliases["unique"]))
        if name in scalar_string_candidates:
            aliases["fpr"] = f"fpr__{index}"
            aliases["known"] = f"known__{index}"
            profile_expressions.extend(
                [
                    pl.col(name)
                    .cast(string_dtype, strict=False)
                    .str.contains("FPR_", literal=True)
                    .fill_null(False)
                    .sum()
                    .alias(aliases["fpr"]),
                    pl.col(name)
                    .cast(string_dtype, strict=False)
                    .is_in(known_right_ids)
                    .fill_null(False)
                    .sum()
                    .alias(aliases["known"]),
                ]
            )
        profile_aliases[name] = aliases

    profile_values: dict[str, Any] = {}
    if profile_expressions:
        profile_values = lazy.select(profile_expressions).collect().row(0, named=True)

    sample_values: dict[str, list[Any]] = {}
    if candidate_columns:
        sample_frame = lazy.select(candidate_columns).head(200).collect()
        for name in candidate_columns:
            values: list[Any] = []
            seen: set[str] = set()
            for value in sample_frame.get_column(name).to_list():
                if value is None:
                    continue
                safe_value = safe_json(value)
                marker = json.dumps(safe_value, sort_keys=True, ensure_ascii=False)
                if marker in seen:
                    continue
                seen.add(marker)
                values.append(safe_value)
                if len(values) == 5:
                    break
            sample_values[name] = values

    schema_by_name = {row["column_name"]: row for row in schema_rows}
    fpr_token_columns: list[str] = []
    exact_known_id_columns: list[str] = []
    for name in candidate_columns:
        aliases = profile_aliases[name]
        row = schema_by_name[name]
        row["null_count"] = int(profile_values.get(aliases["null"], 0))
        if "unique" in aliases:
            row["unique_count"] = int(profile_values.get(aliases["unique"], 0))
        row["sample_values"] = json.dumps(sample_values.get(name, []), ensure_ascii=False)
        if "fpr" in aliases:
            fpr_count = int(profile_values.get(aliases["fpr"], 0))
            known_count = int(profile_values.get(aliases["known"], 0))
            row["rows_containing_fpr_token"] = fpr_count
            row["rows_exactly_matching_known_right_id"] = known_count
            if fpr_count > 0:
                fpr_token_columns.append(name)
            if known_count > 0:
                exact_known_id_columns.append(name)

    package_report = {
        "label": label,
        "path": str(path),
        "row_count": row_count,
        "expected_row_count": EXPECTED_PACKAGE_ROWS[label],
        "row_count_matches_expected": row_count == EXPECTED_PACKAGE_ROWS[label],
        "column_count": len(schema),
        "candidate_columns": candidate_columns,
        "scalar_string_candidate_columns": scalar_string_candidates,
        "columns_containing_fpr_token": fpr_token_columns,
        "columns_exactly_matching_known_right_ids": exact_known_id_columns,
        "candidate_column_samples": sample_values,
        "schema": [
            {
                "position": row["column_position"],
                "name": row["column_name"],
                "dtype": row["dtype"],
            }
            for row in schema_rows
        ],
    }
    return package_report, schema_rows


def run_self_test() -> int:
    mock_headers = sorted(REQUIRED_DECISION_COLUMNS)
    mock_rows: list[dict[str, str]] = []
    for index in range(111):
        if index < 106:
            determination, passed, manual, blocked = (
                "legal_with_conditions",
                "True",
                "False",
                "False",
            )
        elif index < 109:
            determination, passed, manual, blocked = (
                "manual_review_required",
                "False",
                "True",
                "False",
            )
        else:
            determination, passed, manual, blocked = (
                "not_legal_as_modeled",
                "False",
                "False",
                "True",
            )
        mock_rows.append(
            {
                "future_pick_right_id": f"FPR_TEST_{index:03d}",
                "candidate_team": "TST",
                "source_assets": f"2029_R1_T{index:03d}",
                "right_legality_determination": determination,
                "right_legality_stage_passed": passed,
                "right_legality_manual_review_required": manual,
                "right_legality_blocked": blocked,
                "right_legality_release_status": "test_status",
            }
        )
    mock_one_schema = [
        "package_id",
        "outgoing_player_id",
        "outgoing_pick_right_id",
        "outgoing_pick_source_assets",
        "salary_match_status",
    ]
    mock_two_schema = [
        "candidate_id",
        "outgoing_pick_right_ids",
        "pick_right_count",
        "stepien_legality_status",
        "projected_value",
    ]
    tests = {
        "right_is_high": field_priority(field_reasons("outgoing_pick_right_id")) == "high",
        "package_is_context": field_priority(field_reasons("package_id")) == "context",
        "unrelated_is_other": field_priority(field_reasons("player_age")) == "other",
        "string_detection": is_scalar_string_dtype("String") and is_scalar_string_dtype("Utf8"),
        "list_not_scalar": not is_scalar_string_dtype("List(String)"),
        "nested_list_detection": is_nested_dtype("List(String)"),
        "nested_struct_detection": is_nested_dtype("Struct({'a': String})"),
        "safe_json_set": sorted(safe_json({"B", "A"})) == ["A", "B"],
        "mock_decision_release_valid": validate_decisions(mock_headers, mock_rows)["valid"],
        "mock_one_schema_finds_right_id": field_priority(
            field_reasons(mock_one_schema[2])
        )
        == "high",
        "mock_one_schema_finds_source_assets": field_priority(
            field_reasons(mock_one_schema[3])
        )
        == "high",
        "mock_two_schema_finds_right_ids": field_priority(
            field_reasons(mock_two_schema[1])
        )
        == "high",
        "mock_two_schema_finds_stepien_context": field_priority(
            field_reasons(mock_two_schema[3])
        )
        == "context",
    }
    print(json.dumps(tests, indent=2))
    return 0 if all(tests.values()) else 1


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    try:
        import polars as pl
    except ImportError as exc:
        raise SystemExit(
            "Polars is required to inspect the parquet files. Run this script in "
            "the nba-roster-optimizer environment used by the existing pipeline."
        ) from exc

    root = project_root()
    outputs_dir = root / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("MIXED PLAYER-AND-PICK PACKAGE RIGHT-FIELD AUDIT")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print(f"Release name: {RELEASE_NAME}")
    print()

    print("[1/5] Locating the right decision release and Stepien-evaluated packages")
    decision_path = locate_one(root, DECISION_FILENAME)
    package_paths = {label: locate_one(root, filename) for label, filename in PACKAGE_FILES.items()}

    print("[2/5] Validating the 111-right package decision map")
    decision_headers, decision_rows = read_decisions(decision_path)
    decision_validation = validate_decisions(decision_headers, decision_rows)
    if not decision_validation["valid"]:
        raise RuntimeError(
            "The right decision release failed validation:\n"
            + json.dumps(decision_validation, indent=2)
        )
    known_right_ids = [row["future_pick_right_id"] for row in decision_rows]

    print("[3/5] Auditing one-for-one package schema and right-bearing fields")
    one_report, one_columns = profile_package(
        pl, "one_for_one", package_paths["one_for_one"], known_right_ids
    )

    print("[4/5] Auditing two-for-one package schema and right-bearing fields")
    two_report, two_columns = profile_package(
        pl, "two_for_one", package_paths["two_for_one"], known_right_ids
    )

    print("[5/5] Saving the non-destructive schema audit")
    column_rows = one_columns + two_columns
    column_path = outputs_dir / COLUMN_OUTPUT
    with column_path.open("w", encoding="utf-8-sig", newline="") as handle:
        headers = [
            "package_file",
            "column_position",
            "column_name",
            "dtype",
            "semantic_priority",
            "name_match_reasons",
            "null_count",
            "unique_count",
            "rows_containing_fpr_token",
            "rows_exactly_matching_known_right_id",
            "sample_values",
        ]
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(column_rows)

    package_reports = {"one_for_one": one_report, "two_for_one": two_report}
    audit_checks = {
        "decision_release_valid": decision_validation["valid"],
        "one_for_one_row_count_matches": one_report["row_count_matches_expected"],
        "two_for_one_row_count_matches": two_report["row_count_matches_expected"],
        "one_for_one_candidate_fields_found": bool(one_report["candidate_columns"]),
        "two_for_one_candidate_fields_found": bool(two_report["candidate_columns"]),
    }
    audit_valid = all(audit_checks.values())
    report = {
        "script_version": SCRIPT_VERSION,
        "release_name": RELEASE_NAME,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "audit_valid": audit_valid,
        "audit_checks": audit_checks,
        "decision_release": {
            "path": str(decision_path),
            **decision_validation,
        },
        "packages": package_reports,
        "column_audit_csv": str(column_path),
        "non_destructive": True,
        "package_final_legal_status_released": False,
    }
    json_path = outputs_dir / JSON_OUTPUT
    json_path.write_text(json.dumps(safe_json(report), indent=2), encoding="utf-8")

    print()
    print("=" * 80)
    print("PACKAGE RIGHT-FIELD AUDIT COMPLETE")
    print("=" * 80)
    print(f"Decision rows: {decision_validation['rows']}")
    for label in ("one_for_one", "two_for_one"):
        package = package_reports[label]
        print(
            f"{label}: {package['row_count']:,} rows | {package['column_count']} columns | "
            f"{len(package['candidate_columns'])} candidate fields | "
            f"{len(package['columns_containing_fpr_token'])} FPR-bearing fields"
        )
    print(f"Audit valid: {audit_valid}")
    print("Package final-legal status released: False")
    print()
    print("SAVED FILES")
    print(json_path)
    print(column_path)
    return 0 if audit_valid else 1


if __name__ == "__main__":
    sys.exit(main())