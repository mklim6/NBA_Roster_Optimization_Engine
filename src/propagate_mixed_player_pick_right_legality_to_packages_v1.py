"""Propagate validated right-legality decisions into mixed package candidates.

Save this file in ``src``. It performs a non-destructive many-to-one join from
``attached_pick_right_id`` in each Stepien-evaluated package parquet to the
111-right decision release. Existing package fields remain unchanged and final
package legality deliberately remains unreleased pending full CBA validation.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_VERSION = "mixed-player-pick-package-right-legality-propagator-v1-2026-08-05"
RELEASE_NAME = "mixed_player_pick_package_right_legality_2026_27_v1"
RIGHT_EVIDENCE_RELEASE = "mixed_player_pick_right_legality_evidence_2026_27_v1"

DECISION_FILENAME = "mixed_player_pick_right_legality_decision_release_v1.csv"
INPUT_FILES = {
    "one_for_one": "one_for_one_mixed_player_pick_candidates_2026_27_v5_stepien_evaluated.parquet",
    "two_for_one": "two_for_one_mixed_player_pick_candidates_2026_27_v5_stepien_evaluated.parquet",
}
OUTPUT_FILES = {
    "one_for_one": "one_for_one_mixed_player_pick_candidates_2026_27_v6_right_legality_evaluated.parquet",
    "two_for_one": "two_for_one_mixed_player_pick_candidates_2026_27_v6_right_legality_evaluated.parquet",
}
EXPECTED_ROWS = {"one_for_one": 28_324, "two_for_one": 282_277}
EXPECTED_ORIGINAL_COLUMNS = {"one_for_one": 76, "two_for_one": 74}
EXPECTED_GLOBAL_STEPIEN_PASSING_PACKAGES = 155_456

SUMMARY_FILENAME = "mixed_player_pick_package_right_legality_summary_v1.csv"
EXCEPTION_FILENAME = "mixed_player_pick_package_right_legality_exception_summary_v1.csv"
VALIDATION_FILENAME = "mixed_player_pick_package_right_legality_validation_v1.csv"
METADATA_FILENAME = "mixed_player_pick_package_right_legality_metadata_v1.json"

DECISION_COUNTS = {
    "legal_with_conditions": 106,
    "manual_review_required": 3,
    "not_legal_as_modeled": 2,
}

DECISION_REQUIRED_COLUMNS = {
    "future_pick_right_id",
    "candidate_team",
    "evidence_group_key",
    "claim_id",
    "right_legality_determination",
    "right_legality_stage_passed",
    "right_legality_manual_review_required",
    "right_legality_blocked",
    "right_legality_release_status",
    "standalone_tradability_determination",
    "authoritative_source_as_of_date",
}

APPENDED_COLUMNS = [
    "right_evidence_candidate_team",
    "right_evidence_group_key",
    "right_evidence_claim_id",
    "right_evidence_determination",
    "right_evidence_stage_passed",
    "right_evidence_manual_review_required",
    "right_evidence_blocked",
    "right_evidence_release_status",
    "right_evidence_standalone_tradability_determination",
    "right_evidence_authoritative_source_as_of_date",
    "right_legality_decision_matched",
    "right_evidence_team_matches_attached_pick_team",
    "package_right_legality_stage_passed",
    "package_right_legality_manual_review_required",
    "package_right_legality_blocked",
    "package_right_legality_status",
    "right_legality_evidence_release",
    "right_legality_evaluator_release",
    "right_legality_evaluator_version",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run dependency-free decision and status tests without reading project files.",
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


def normalized_bool(value: str) -> bool | None:
    lowered = str(value).strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return None


def pure_status(
    stepien_passed: bool,
    decision_matched: bool,
    team_matched: bool,
    evidence_passed: bool,
    evidence_manual: bool,
    evidence_blocked: bool,
) -> tuple[bool, bool, bool, str]:
    if not stepien_passed:
        return False, False, True, "blocked_by_stepien_or_frozen_pick_screen"
    if not decision_matched:
        return False, True, False, "right_legality_decision_unmatched_internal_review"
    if not team_matched:
        return False, True, False, "right_legality_team_mismatch_internal_review"
    if evidence_manual:
        return False, True, False, "right_legality_manual_review_required"
    if evidence_blocked:
        return False, False, True, "blocked_by_right_legality_evidence"
    if evidence_passed:
        return (
            True,
            False,
            False,
            "passed_stepien_frozen_and_right_legality_evidence_remaining_full_cba_validation",
        )
    return False, True, False, "right_legality_inconsistent_decision_internal_review"


def read_decisions(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    return headers, rows


def validate_decision_rows(headers: list[str], rows: list[dict[str, str]]) -> dict[str, Any]:
    missing_columns = sorted(DECISION_REQUIRED_COLUMNS.difference(headers))
    ids = [row.get("future_pick_right_id", "") for row in rows]
    determinations = Counter(row.get("right_legality_determination", "") for row in rows)
    boolean_fields_parseable = all(
        normalized_bool(row.get(column, "")) is not None
        for row in rows
        for column in (
            "right_legality_stage_passed",
            "right_legality_manual_review_required",
            "right_legality_blocked",
        )
    )
    mutually_exclusive = all(
        sum(
            normalized_bool(row.get(column, "")) is True
            for column in (
                "right_legality_stage_passed",
                "right_legality_manual_review_required",
                "right_legality_blocked",
            )
        )
        == 1
        for row in rows
    )
    checks = {
        "required_columns_present": not missing_columns,
        "row_count_111": len(rows) == 111,
        "right_ids_nonblank": all(ids),
        "right_ids_unique": len(set(ids)) == 111,
        "determination_counts": determinations == Counter(DECISION_COUNTS),
        "decision_flags_parseable": boolean_fields_parseable,
        "decision_flags_mutually_exclusive": mutually_exclusive,
    }
    return {
        "valid": all(checks.values()),
        "checks": checks,
        "missing_columns": missing_columns,
        "rows": len(rows),
        "unique_right_ids": len(set(ids)),
        "determination_counts": dict(sorted(determinations.items())),
    }


def frames_equal(left: Any, right: Any) -> bool:
    if hasattr(left, "equals"):
        try:
            return bool(left.equals(right, null_equal=True))
        except TypeError:
            return bool(left.equals(right))
    if hasattr(left, "frame_equal"):
        try:
            return bool(left.frame_equal(right, null_equal=True))
        except TypeError:
            return bool(left.frame_equal(right))
    raise AttributeError("This Polars version exposes neither DataFrame.equals nor frame_equal")


def value_counts_map(frame: Any, column: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in frame.group_by(column).len().to_dicts():
        key = "<null>" if row[column] is None else str(row[column])
        result[key] = int(row["len"])
    return dict(sorted(result.items()))


def write_csv(path: Path, headers: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def build_decision_frame(pl: Any, path: Path) -> Any:
    string_dtype = getattr(pl, "String", pl.Utf8)
    raw = pl.read_csv(str(path), infer_schema_length=0)

    def bool_expr(column: str, alias: str) -> Any:
        return (
            (
                pl.col(column)
                .cast(string_dtype, strict=False)
                .str.to_lowercase()
                == "true"
            ).alias(alias)
        )

    return raw.select(
        [
            pl.col("future_pick_right_id"),
            pl.col("candidate_team").alias("right_evidence_candidate_team"),
            pl.col("evidence_group_key").alias("right_evidence_group_key"),
            pl.col("claim_id").alias("right_evidence_claim_id"),
            pl.col("right_legality_determination").alias("right_evidence_determination"),
            bool_expr("right_legality_stage_passed", "right_evidence_stage_passed"),
            bool_expr(
                "right_legality_manual_review_required",
                "right_evidence_manual_review_required",
            ),
            bool_expr("right_legality_blocked", "right_evidence_blocked"),
            pl.col("right_legality_release_status").alias("right_evidence_release_status"),
            pl.col("standalone_tradability_determination").alias(
                "right_evidence_standalone_tradability_determination"
            ),
            pl.col("authoritative_source_as_of_date").alias(
                "right_evidence_authoritative_source_as_of_date"
            ),
        ]
    )


def evaluate_packages(pl: Any, source: Any, decisions: Any) -> Any:
    joined = source.join(
        decisions,
        left_on="attached_pick_right_id",
        right_on="future_pick_right_id",
        how="left",
    )
    joined = joined.with_columns(
        [
            pl.col("right_evidence_determination")
            .is_not_null()
            .alias("right_legality_decision_matched"),
            (
                pl.col("right_evidence_determination").is_not_null()
                & (pl.col("attached_pick_team") == pl.col("right_evidence_candidate_team"))
            ).alias("right_evidence_team_matches_attached_pick_team"),
        ]
    )

    stepien_passed = pl.col("package_pick_legality_stage_passed").fill_null(False)
    matched = pl.col("right_legality_decision_matched")
    team_matched = pl.col("right_evidence_team_matches_attached_pick_team")
    evidence_passed = pl.col("right_evidence_stage_passed").fill_null(False)
    evidence_manual = pl.col("right_evidence_manual_review_required").fill_null(False)
    evidence_blocked = pl.col("right_evidence_blocked").fill_null(False)

    joined = joined.with_columns(
        [
            (stepien_passed & matched & team_matched & evidence_passed).alias(
                "package_right_legality_stage_passed"
            ),
            (
                stepien_passed
                & ((~matched) | (~team_matched) | evidence_manual)
            ).alias("package_right_legality_manual_review_required"),
            (
                (~stepien_passed) | (stepien_passed & matched & team_matched & evidence_blocked)
            ).alias("package_right_legality_blocked"),
        ]
    )

    joined = joined.with_columns(
        [
            pl.when(~stepien_passed)
            .then(pl.lit("blocked_by_stepien_or_frozen_pick_screen"))
            .when(~matched)
            .then(pl.lit("right_legality_decision_unmatched_internal_review"))
            .when(~team_matched)
            .then(pl.lit("right_legality_team_mismatch_internal_review"))
            .when(evidence_manual)
            .then(pl.lit("right_legality_manual_review_required"))
            .when(evidence_blocked)
            .then(pl.lit("blocked_by_right_legality_evidence"))
            .when(evidence_passed)
            .then(
                pl.lit(
                    "passed_stepien_frozen_and_right_legality_evidence_remaining_full_cba_validation"
                )
            )
            .otherwise(pl.lit("right_legality_inconsistent_decision_internal_review"))
            .alias("package_right_legality_status"),
            pl.lit(RIGHT_EVIDENCE_RELEASE).alias("right_legality_evidence_release"),
            pl.lit(RELEASE_NAME).alias("right_legality_evaluator_release"),
            pl.lit(SCRIPT_VERSION).alias("right_legality_evaluator_version"),
        ]
    )
    return joined


def run_self_test() -> int:
    status_cases = {
        "stepien_block": pure_status(False, False, False, False, False, False),
        "unmatched": pure_status(True, False, False, False, False, False),
        "team_mismatch": pure_status(True, True, False, True, False, False),
        "manual": pure_status(True, True, True, False, True, False),
        "evidence_block": pure_status(True, True, True, False, False, True),
        "pass": pure_status(True, True, True, True, False, False),
    }
    tests = {
        "stepien_blocked": status_cases["stepien_block"]
        == (False, False, True, "blocked_by_stepien_or_frozen_pick_screen"),
        "unmatched_is_manual": status_cases["unmatched"][1] is True,
        "team_mismatch_is_manual": status_cases["team_mismatch"][1] is True,
        "manual_is_not_blocked": status_cases["manual"][:3] == (False, True, False),
        "evidence_block_is_blocked": status_cases["evidence_block"][:3]
        == (False, False, True),
        "pass_is_stage_only": status_cases["pass"][:3] == (True, False, False),
        "appended_columns_unique": len(APPENDED_COLUMNS) == len(set(APPENDED_COLUMNS)),
        "final_legal_not_appended": "optimizer_package_final_legal" not in APPENDED_COLUMNS,
    }
    print(json.dumps({"tests": tests, "status_cases": status_cases}, indent=2))
    return 0 if all(tests.values()) else 1


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    try:
        import polars as pl
    except ImportError as exc:
        raise SystemExit(
            "Polars is required. Run this script in the nba-roster-optimizer "
            "environment used by the existing parquet pipeline."
        ) from exc

    root = project_root()
    outputs_dir = root / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("MIXED PLAYER-AND-PICK PACKAGE RIGHT-LEGALITY PROPAGATOR")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print(f"Release name: {RELEASE_NAME}")
    print()

    validation_rows: list[dict[str, str]] = []

    def check(scope: str, name: str, passed: bool, observed: Any, expected: Any) -> None:
        validation_rows.append(
            {
                "scope": scope,
                "check_name": name,
                "passed": str(bool(passed)),
                "observed": str(observed),
                "expected": str(expected),
            }
        )

    print("[1/8] Locating decision release and Stepien-evaluated package files")
    decision_path = locate_one(root, DECISION_FILENAME)
    input_paths = {label: locate_one(root, filename) for label, filename in INPUT_FILES.items()}

    print("[2/8] Validating the 111-right decision release")
    decision_headers, decision_rows = read_decisions(decision_path)
    decision_validation = validate_decision_rows(decision_headers, decision_rows)
    for name, passed in decision_validation["checks"].items():
        check("decision_release", name, passed, passed, True)
    if not decision_validation["valid"]:
        raise RuntimeError(
            "The right decision release failed validation:\n"
            + json.dumps(decision_validation, indent=2)
        )
    decisions = build_decision_frame(pl, decision_path)
    check(
        "decision_release",
        "decision_frame_unique_right_ids",
        decisions["future_pick_right_id"].n_unique() == 111,
        decisions["future_pick_right_id"].n_unique(),
        111,
    )

    evaluated_frames: dict[str, Any] = {}
    original_columns: dict[str, list[str]] = {}
    source_frames: dict[str, Any] = {}

    for step_number, label in ((3, "one_for_one"), (4, "two_for_one")):
        print(f"[{step_number}/8] Joining right evidence into {label.replace('_', '-')} packages")
        source = pl.read_parquet(str(input_paths[label]))
        source_frames[label] = source
        original_columns[label] = list(source.columns)

        check(label, "input_row_count", source.height == EXPECTED_ROWS[label], source.height, EXPECTED_ROWS[label])
        check(
            label,
            "input_column_count",
            source.width == EXPECTED_ORIGINAL_COLUMNS[label],
            source.width,
            EXPECTED_ORIGINAL_COLUMNS[label],
        )
        check(
            label,
            "attached_pick_right_id_present",
            "attached_pick_right_id" in source.columns,
            "attached_pick_right_id" in source.columns,
            True,
        )
        check(
            label,
            "candidate_ids_unique",
            source["optimizer_candidate_id"].n_unique() == source.height,
            source["optimizer_candidate_id"].n_unique(),
            source.height,
        )
        check(
            label,
            "no_preexisting_appended_columns",
            not set(APPENDED_COLUMNS).intersection(source.columns),
            sorted(set(APPENDED_COLUMNS).intersection(source.columns)),
            [],
        )

        evaluated = evaluate_packages(pl, source, decisions)
        evaluated_frames[label] = evaluated
        original_fields_preserved = frames_equal(source, evaluated.select(source.columns))

        check(label, "join_preserved_row_count", evaluated.height == source.height, evaluated.height, source.height)
        check(
            label,
            "join_preserved_original_columns",
            original_fields_preserved,
            original_fields_preserved,
            True,
        )
        check(
            label,
            "appended_column_count",
            evaluated.width == source.width + len(APPENDED_COLUMNS),
            evaluated.width - source.width,
            len(APPENDED_COLUMNS),
        )
        check(
            label,
            "all_appended_columns_present",
            set(APPENDED_COLUMNS).issubset(evaluated.columns),
            len(set(APPENDED_COLUMNS).intersection(evaluated.columns)),
            len(APPENDED_COLUMNS),
        )

        stepien_passed = evaluated.filter(pl.col("package_pick_legality_stage_passed")).height
        unmatched_after_stepien = evaluated.filter(
            pl.col("package_pick_legality_stage_passed")
            & (~pl.col("right_legality_decision_matched"))
        ).height
        team_mismatch_after_stepien = evaluated.filter(
            pl.col("package_pick_legality_stage_passed")
            & (~pl.col("right_evidence_team_matches_attached_pick_team"))
        ).height
        status_partition = sum(
            evaluated[column].sum()
            for column in (
                "package_right_legality_stage_passed",
                "package_right_legality_manual_review_required",
                "package_right_legality_blocked",
            )
        )
        final_legal_true = evaluated.filter(pl.col("optimizer_package_final_legal")).height

        check(label, "stepien_passing_packages_have_decisions", unmatched_after_stepien == 0, unmatched_after_stepien, 0)
        check(label, "stepien_passing_packages_match_owner_team", team_mismatch_after_stepien == 0, team_mismatch_after_stepien, 0)
        check(label, "combined_status_partition", status_partition == evaluated.height, status_partition, evaluated.height)
        check(label, "final_legal_remains_unreleased", final_legal_true == 0, final_legal_true, 0)
        check(label, "stepien_passing_count_recorded", stepien_passed >= 0, stepien_passed, ">=0")

    print("[5/8] Validating global propagation counts and exception coverage")
    global_stepien_passed = sum(
        frame.filter(pl.col("package_pick_legality_stage_passed")).height
        for frame in evaluated_frames.values()
    )
    matched_right_ids = set()
    stepien_passing_right_ids = set()
    matched_determinations: set[str] = set()
    for frame in evaluated_frames.values():
        matched = frame.filter(pl.col("right_legality_decision_matched"))
        stepien_passing = frame.filter(pl.col("package_pick_legality_stage_passed"))
        matched_right_ids.update(matched["attached_pick_right_id"].unique().to_list())
        stepien_passing_right_ids.update(
            stepien_passing["attached_pick_right_id"].unique().to_list()
        )
        matched_determinations.update(
            value
            for value in matched["right_evidence_determination"].unique().to_list()
            if value is not None
        )

    check(
        "global",
        "stepien_passing_package_count",
        global_stepien_passed == EXPECTED_GLOBAL_STEPIEN_PASSING_PACKAGES,
        global_stepien_passed,
        EXPECTED_GLOBAL_STEPIEN_PASSING_PACKAGES,
    )
    decision_right_id_set = {row["future_pick_right_id"] for row in decision_rows}
    check(
        "global",
        "matched_right_ids_within_decision_release",
        matched_right_ids.issubset(decision_right_id_set),
        len(matched_right_ids),
        "subset of 111",
    )
    check(
        "global",
        "all_stepien_passing_right_ids_matched",
        stepien_passing_right_ids.issubset(matched_right_ids),
        len(stepien_passing_right_ids),
        "all matched",
    )

    pre_save_valid = all(row["passed"] == "True" for row in validation_rows)
    check("global", "pre_save_validation_gate", pre_save_valid, pre_save_valid, True)
    pre_save_valid = all(row["passed"] == "True" for row in validation_rows)

    summary_rows: list[dict[str, Any]] = []
    exception_frames: list[Any] = []
    output_paths = {label: outputs_dir / filename for label, filename in OUTPUT_FILES.items()}

    if pre_save_valid:
        print("[6/8] Saving right-legality-evaluated package parquets")
        for label, frame in evaluated_frames.items():
            frame.write_parquet(str(output_paths[label]), compression="zstd", statistics=True)

            for metric, column in (
                ("stepien_stage_passed", "package_pick_legality_stage_passed"),
                ("right_decision_matched", "right_legality_decision_matched"),
                ("combined_stage_passed", "package_right_legality_stage_passed"),
                ("combined_manual_review", "package_right_legality_manual_review_required"),
                ("combined_blocked", "package_right_legality_blocked"),
                ("final_legal", "optimizer_package_final_legal"),
            ):
                summary_rows.append(
                    {
                        "package_file": label,
                        "metric": metric,
                        "category": "True",
                        "count": int(frame[column].sum()),
                    }
                )
            for category, count in value_counts_map(frame, "package_right_legality_status").items():
                summary_rows.append(
                    {
                        "package_file": label,
                        "metric": "package_right_legality_status",
                        "category": category,
                        "count": count,
                    }
                )

            exceptions = (
                frame.filter(
                    pl.col("right_evidence_determination").is_in(
                        ["manual_review_required", "not_legal_as_modeled"]
                    )
                )
                .group_by(
                    [
                        "attached_pick_right_id",
                        "attached_pick_team",
                        "right_evidence_determination",
                        "right_evidence_release_status",
                    ]
                )
                .len()
                .rename({"len": "package_count"})
                .with_columns(pl.lit(label).alias("package_file"))
                .select(
                    [
                        "package_file",
                        "attached_pick_right_id",
                        "attached_pick_team",
                        "right_evidence_determination",
                        "right_evidence_release_status",
                        "package_count",
                    ]
                )
            )
            exception_frames.append(exceptions)

        write_csv(
            outputs_dir / SUMMARY_FILENAME,
            ["package_file", "metric", "category", "count"],
            summary_rows,
        )
        exception_frame = pl.concat(exception_frames, how="vertical_relaxed")
        write_csv(
            outputs_dir / EXCEPTION_FILENAME,
            [
                "package_file",
                "attached_pick_right_id",
                "attached_pick_team",
                "right_evidence_determination",
                "right_evidence_release_status",
                "package_count",
            ],
            exception_frame.to_dicts(),
        )

        print("[7/8] Reloading outputs and confirming non-destructive preservation")
        for label, source in source_frames.items():
            output = pl.read_parquet(str(output_paths[label]))
            saved_original_fields_preserved = frames_equal(
                source, output.select(original_columns[label])
            )
            check(label, "saved_output_row_count", output.height == source.height, output.height, source.height)
            check(
                label,
                "saved_output_preserves_original_columns",
                saved_original_fields_preserved,
                saved_original_fields_preserved,
                True,
            )
            check(
                label,
                "saved_output_final_legal_unreleased",
                output.filter(pl.col("optimizer_package_final_legal")).height == 0,
                output.filter(pl.col("optimizer_package_final_legal")).height,
                0,
            )
    else:
        print("[6/8] Pre-save validation failed; package parquets were not written")
        print("[7/8] Output reload skipped")

    print("[8/8] Saving validation and metadata")
    release_valid = all(row["passed"] == "True" for row in validation_rows)
    write_csv(
        outputs_dir / VALIDATION_FILENAME,
        ["scope", "check_name", "passed", "observed", "expected"],
        validation_rows,
    )

    package_counts: dict[str, dict[str, Any]] = {}
    for label, frame in evaluated_frames.items():
        package_counts[label] = {
            "rows": frame.height,
            "columns_before": len(original_columns[label]),
            "columns_after": frame.width,
            "stepien_stage_passed": int(frame["package_pick_legality_stage_passed"].sum()),
            "right_decision_matched": int(frame["right_legality_decision_matched"].sum()),
            "combined_stage_passed": int(frame["package_right_legality_stage_passed"].sum()),
            "combined_manual_review": int(
                frame["package_right_legality_manual_review_required"].sum()
            ),
            "combined_blocked": int(frame["package_right_legality_blocked"].sum()),
            "final_legal": int(frame["optimizer_package_final_legal"].sum()),
            "status_counts": value_counts_map(frame, "package_right_legality_status"),
            "output_path": str(output_paths[label]) if output_paths[label].exists() else None,
        }

    metadata = {
        "script_version": SCRIPT_VERSION,
        "release_name": RELEASE_NAME,
        "right_evidence_release": RIGHT_EVIDENCE_RELEASE,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "release_valid": release_valid,
        "decision_release": {
            "path": str(decision_path),
            **decision_validation,
        },
        "packages": package_counts,
        "global_stepien_stage_passed": global_stepien_passed,
        "unique_decision_rights_used": len(matched_right_ids),
        "unique_stepien_passing_right_ids": len(stepien_passing_right_ids),
        "matched_determinations_represented": sorted(matched_determinations),
        "validation_checks_passed": sum(row["passed"] == "True" for row in validation_rows),
        "validation_checks_total": len(validation_rows),
        "package_final_legal_status_released": False,
        "package_final_legal_note": "Right-level evidence is propagated, but salary matching, aggregation, apron, roster, and remaining full CBA checks are not yet released.",
        "summary_file": str(outputs_dir / SUMMARY_FILENAME) if (outputs_dir / SUMMARY_FILENAME).exists() else None,
        "exception_summary_file": str(outputs_dir / EXCEPTION_FILENAME)
        if (outputs_dir / EXCEPTION_FILENAME).exists()
        else None,
        "validation_file": str(outputs_dir / VALIDATION_FILENAME),
    }
    (outputs_dir / METADATA_FILENAME).write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )

    print()
    print("=" * 80)
    print("PACKAGE RIGHT-LEGALITY PROPAGATION COMPLETE")
    print("=" * 80)
    print(f"One-for-one packages: {evaluated_frames['one_for_one'].height:,}")
    print(f"Two-for-one packages: {evaluated_frames['two_for_one'].height:,}")
    print(f"Stepien-stage passing packages: {global_stepien_passed:,}")
    print(
        "Combined right-legality passing packages: "
        f"{sum(frame['package_right_legality_stage_passed'].sum() for frame in evaluated_frames.values()):,}"
    )
    print(
        "Combined manual-review packages: "
        f"{sum(frame['package_right_legality_manual_review_required'].sum() for frame in evaluated_frames.values()):,}"
    )
    print(
        "Combined blocked packages: "
        f"{sum(frame['package_right_legality_blocked'].sum() for frame in evaluated_frames.values()):,}"
    )
    print(f"Validation checks passed: {sum(row['passed'] == 'True' for row in validation_rows)}/{len(validation_rows)}")
    print(f"Release valid: {release_valid}")
    print("Final-legal packages released: 0")
    print()
    print("SAVED FILES")
    if pre_save_valid:
        print(output_paths["one_for_one"])
        print(output_paths["two_for_one"])
        print(outputs_dir / SUMMARY_FILENAME)
        print(outputs_dir / EXCEPTION_FILENAME)
    print(outputs_dir / VALIDATION_FILENAME)
    print(outputs_dir / METADATA_FILENAME)

    return 0 if release_valid else 1


if __name__ == "__main__":
    sys.exit(main())