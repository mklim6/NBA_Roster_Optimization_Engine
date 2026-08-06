"""Propagate 30-team CBA evidence into mixed player-and-pick packages.

Save this file in ``src``. It performs two non-destructive joins from ``team_a``
and ``team_b`` in each V6 package parquet to the 30-team CBA decision release,
then writes V7 team-CBA-evidence-evaluated parquets. Every existing package
column is preserved in its original order.

This is an evidence propagation stage, not a final CBA legality evaluator.
Player restrictions, exact post-trade salary adjustments, transaction mechanics,
and roster outcomes remain unresolved. ``optimizer_package_final_legal`` always
remains false.
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


SCRIPT_VERSION = "mixed-player-pick-team-cba-evidence-propagator-v1-2026-08-05"
RELEASE_NAME = "mixed_player_pick_package_team_cba_evidence_2026_27_v1"
TEAM_EVIDENCE_RELEASE = "mixed_player_pick_team_cba_decision_release_v1"

DECISION_FILENAME = "mixed_player_pick_team_cba_decision_release_v1.csv"
INPUT_FILES = {
    "one_for_one": "one_for_one_mixed_player_pick_candidates_2026_27_v6_right_legality_evaluated.parquet",
    "two_for_one": "two_for_one_mixed_player_pick_candidates_2026_27_v6_right_legality_evaluated.parquet",
}
OUTPUT_FILES = {
    "one_for_one": "one_for_one_mixed_player_pick_candidates_2026_27_v7_team_cba_evidence_evaluated.parquet",
    "two_for_one": "two_for_one_mixed_player_pick_candidates_2026_27_v7_team_cba_evidence_evaluated.parquet",
}
EXPECTED_ROWS = {"one_for_one": 28_324, "two_for_one": 282_277}
EXPECTED_ORIGINAL_COLUMNS = {"one_for_one": 95, "two_for_one": 93}
EXPECTED_PRIOR_RESULTS = {
    "one_for_one": {"passed": 20_797, "manual": 805, "blocked": 6_722},
    "two_for_one": {"passed": 128_344, "manual": 2_946, "blocked": 150_987},
}
EXPECTED_TEAM_EVIDENCE_RESULTS = {
    "one_for_one": {"passed": 11_269, "new_team_manual": 9_528, "combined_manual": 10_333, "blocked": 6_722},
    "two_for_one": {"passed": 72_706, "new_team_manual": 55_638, "combined_manual": 58_584, "blocked": 150_987},
}
EXPECTED_GLOBAL = {"rows": 310_601, "passed": 83_975, "manual": 68_917, "blocked": 157_709}
EXPECTED_MANUAL_TEAMS = {"CHA", "IND", "LAL", "MEM", "MIN", "SAS"}

SUMMARY_FILENAME = "mixed_player_pick_package_team_cba_summary_v1.csv"
MANUAL_SUMMARY_FILENAME = "mixed_player_pick_package_team_cba_manual_review_summary_v1.csv"
VALIDATION_FILENAME = "mixed_player_pick_package_team_cba_validation_v1.csv"
METADATA_FILENAME = "mixed_player_pick_package_team_cba_metadata_v1.json"

DECISION_REQUIRED_COLUMNS = {
    "team_abbreviation",
    "evidence_as_of_date",
    "verified_team_salary_value",
    "verified_apron_team_salary_value",
    "verified_cap_room_value",
    "luxury_tax_status",
    "first_apron_status",
    "second_apron_status",
    "hard_cap_active",
    "hard_cap_level",
    "hard_cap_trigger",
    "aggregation_allowed",
    "incoming_salary_restriction_tier",
    "standard_contract_count",
    "two_way_contract_count",
    "sign_and_trade_receipt_allowed",
    "trade_exception_use_allowed",
    "cash_consideration_allowed",
    "team_salary_source_url",
    "team_cba_evidence_determination",
    "team_cba_manual_review_required",
    "team_cba_stage_pass",
    "team_cba_final_legal_status_released",
}

SIDE_SUFFIXES = [
    "cba_decision_matched",
    "cba_evidence_determination",
    "cba_manual_review_required",
    "cba_stage_pass",
    "verified_team_salary_value",
    "verified_apron_team_salary_value",
    "verified_cap_room_value",
    "luxury_tax_status",
    "first_apron_status",
    "second_apron_status",
    "hard_cap_active",
    "hard_cap_level",
    "hard_cap_trigger",
    "aggregation_allowed",
    "incoming_salary_restriction_tier",
    "standard_contract_count",
    "two_way_contract_count",
    "sign_and_trade_receipt_allowed",
    "trade_exception_use_allowed",
    "cash_consideration_allowed",
    "cba_evidence_as_of_date",
    "team_salary_source_url",
    "player_salary_delta_proxy",
    "posttrade_apron_team_salary_proxy",
]

PACKAGE_APPENDED_COLUMNS = [
    "team_cba_decisions_matched",
    "team_cba_posttrade_salary_values_are_proxies",
    "package_team_cba_evidence_stage_passed",
    "package_team_cba_evidence_manual_review_required",
    "package_team_cba_evidence_blocked",
    "package_team_cba_evidence_status",
    "team_cba_evidence_release",
    "team_cba_evaluator_release",
    "team_cba_evaluator_version",
    "team_cba_final_legal_status_released",
]
APPENDED_COLUMNS = [
    *(f"team_a_{suffix}" for suffix in SIDE_SUFFIXES),
    *(f"team_b_{suffix}" for suffix in SIDE_SUFFIXES),
    *PACKAGE_APPENDED_COLUMNS,
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run dependency-free status and schema tests without reading project files.",
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


def normalized_bool(value: Any) -> bool | None:
    lowered = str(value).strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return None


def pure_status(
    prior_passed: bool,
    prior_manual: bool,
    prior_blocked: bool,
    decisions_matched: bool,
    team_a_passed: bool,
    team_b_passed: bool,
    team_a_manual: bool,
    team_b_manual: bool,
) -> tuple[bool, bool, bool, str]:
    if prior_blocked:
        return False, False, True, "blocked_by_prior_right_legality_stage"
    if prior_manual:
        return False, True, False, "manual_review_from_prior_right_legality_stage"
    if not prior_passed:
        return False, True, False, "team_cba_prior_stage_inconsistent_internal_review"
    if not decisions_matched:
        return False, True, False, "team_cba_decision_unmatched_internal_review"
    if team_a_manual or team_b_manual:
        return False, True, False, "team_cba_manual_review_required"
    if team_a_passed and team_b_passed:
        return (
            True,
            False,
            False,
            "team_cba_evidence_join_passed_remaining_player_and_package_cba_validation",
        )
    return False, True, False, "team_cba_inconsistent_decision_internal_review"


def read_decisions(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def validate_decisions(headers: list[str], rows: list[dict[str, str]]) -> dict[str, Any]:
    missing = sorted(DECISION_REQUIRED_COLUMNS.difference(headers))
    teams = [row.get("team_abbreviation", "").strip().upper() for row in rows]
    determinations = Counter(row.get("team_cba_evidence_determination", "") for row in rows)
    manual_teams = {
        row.get("team_abbreviation", "").strip().upper()
        for row in rows
        if normalized_bool(row.get("team_cba_manual_review_required")) is True
    }
    flags_parseable = all(
        normalized_bool(row.get(column)) is not None
        for row in rows
        for column in (
            "hard_cap_active",
            "team_cba_manual_review_required",
            "team_cba_stage_pass",
            "team_cba_final_legal_status_released",
        )
    )
    stage_consistent = all(
        (normalized_bool(row.get("team_cba_stage_pass")) is True)
        == (row.get("team_cba_evidence_determination") == "verified_with_conditions")
        for row in rows
    )
    checks = {
        "required_columns_present": not missing,
        "row_count_30": len(rows) == 30,
        "team_codes_nonblank": all(teams),
        "team_codes_unique": len(set(teams)) == 30,
        "determination_counts_24_6": determinations == Counter({"verified_with_conditions": 24, "manual_review_required": 6}),
        "manual_team_set_exact": manual_teams == EXPECTED_MANUAL_TEAMS,
        "decision_flags_parseable": flags_parseable,
        "stage_flags_consistent": stage_consistent,
        "evidence_dates_consistent": all(row.get("evidence_as_of_date") == "2026-08-04" for row in rows),
        "final_legal_status_unreleased": all(normalized_bool(row.get("team_cba_final_legal_status_released")) is False for row in rows),
    }
    return {
        "valid": all(checks.values()),
        "checks": checks,
        "missing_columns": missing,
        "rows": len(rows),
        "columns": len(headers),
        "unique_teams": len(set(teams)),
        "determination_counts": dict(sorted(determinations.items())),
        "manual_teams": sorted(manual_teams),
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


def bool_expr(pl: Any, column: str, alias: str) -> Any:
    string_dtype = getattr(pl, "String", pl.Utf8)
    return (
        pl.col(column).cast(string_dtype, strict=False).str.to_lowercase() == "true"
    ).alias(alias)


def build_side_decisions(pl: Any, path: Path, side: str) -> Any:
    raw = pl.read_csv(str(path), infer_schema_length=0)
    prefix = f"team_{side}_"
    return raw.select(
        [
            pl.col("team_abbreviation").alias(f"__{side}_team_join_key"),
            pl.col("team_cba_evidence_determination").alias(prefix + "cba_evidence_determination"),
            bool_expr(pl, "team_cba_manual_review_required", prefix + "cba_manual_review_required"),
            bool_expr(pl, "team_cba_stage_pass", prefix + "cba_stage_pass"),
            pl.col("verified_team_salary_value").cast(pl.Float64, strict=False).alias(prefix + "verified_team_salary_value"),
            pl.col("verified_apron_team_salary_value").cast(pl.Float64, strict=False).alias(prefix + "verified_apron_team_salary_value"),
            pl.col("verified_cap_room_value").cast(pl.Float64, strict=False).alias(prefix + "verified_cap_room_value"),
            pl.col("luxury_tax_status").alias(prefix + "luxury_tax_status"),
            pl.col("first_apron_status").alias(prefix + "first_apron_status"),
            pl.col("second_apron_status").alias(prefix + "second_apron_status"),
            bool_expr(pl, "hard_cap_active", prefix + "hard_cap_active"),
            pl.col("hard_cap_level").alias(prefix + "hard_cap_level"),
            pl.col("hard_cap_trigger").alias(prefix + "hard_cap_trigger"),
            pl.col("aggregation_allowed").alias(prefix + "aggregation_allowed"),
            pl.col("incoming_salary_restriction_tier").alias(prefix + "incoming_salary_restriction_tier"),
            pl.col("standard_contract_count").cast(pl.Int64, strict=False).alias(prefix + "standard_contract_count"),
            pl.col("two_way_contract_count").cast(pl.Int64, strict=False).alias(prefix + "two_way_contract_count"),
            pl.col("sign_and_trade_receipt_allowed").alias(prefix + "sign_and_trade_receipt_allowed"),
            pl.col("trade_exception_use_allowed").alias(prefix + "trade_exception_use_allowed"),
            pl.col("cash_consideration_allowed").alias(prefix + "cash_consideration_allowed"),
            pl.col("evidence_as_of_date").alias(prefix + "cba_evidence_as_of_date"),
            pl.col("team_salary_source_url").alias(prefix + "team_salary_source_url"),
        ]
    )


def evaluate_packages(pl: Any, source: Any, decisions_a: Any, decisions_b: Any) -> Any:
    original_columns = list(source.columns)
    joined = source.with_row_count("__team_cba_row_order")
    joined = joined.join(decisions_a, left_on="team_a", right_on="__a_team_join_key", how="left")
    joined = joined.join(decisions_b, left_on="team_b", right_on="__b_team_join_key", how="left")
    joined = joined.sort("__team_cba_row_order")

    joined = joined.with_columns(
        [
            pl.col("team_a_cba_evidence_determination").is_not_null().alias("team_a_cba_decision_matched"),
            pl.col("team_b_cba_evidence_determination").is_not_null().alias("team_b_cba_decision_matched"),
            (pl.col("side_b_player_trade_salary") - pl.col("side_a_player_trade_salary")).alias("team_a_player_salary_delta_proxy"),
            (pl.col("side_a_player_trade_salary") - pl.col("side_b_player_trade_salary")).alias("team_b_player_salary_delta_proxy"),
        ]
    )
    joined = joined.with_columns(
        [
            (pl.col("team_a_verified_apron_team_salary_value") + pl.col("team_a_player_salary_delta_proxy")).alias("team_a_posttrade_apron_team_salary_proxy"),
            (pl.col("team_b_verified_apron_team_salary_value") + pl.col("team_b_player_salary_delta_proxy")).alias("team_b_posttrade_apron_team_salary_proxy"),
            (pl.col("team_a_cba_decision_matched") & pl.col("team_b_cba_decision_matched")).alias("team_cba_decisions_matched"),
            pl.lit(True).alias("team_cba_posttrade_salary_values_are_proxies"),
        ]
    )

    prior_passed = pl.col("package_right_legality_stage_passed").fill_null(False)
    prior_manual = pl.col("package_right_legality_manual_review_required").fill_null(False)
    prior_blocked = pl.col("package_right_legality_blocked").fill_null(False)
    matched = pl.col("team_cba_decisions_matched")
    a_passed = pl.col("team_a_cba_stage_pass").fill_null(False)
    b_passed = pl.col("team_b_cba_stage_pass").fill_null(False)
    a_manual = pl.col("team_a_cba_manual_review_required").fill_null(False)
    b_manual = pl.col("team_b_cba_manual_review_required").fill_null(False)
    prior_inconsistent = (~prior_passed) & (~prior_manual) & (~prior_blocked)

    joined = joined.with_columns(
        [
            (prior_passed & matched & a_passed & b_passed & (~a_manual) & (~b_manual)).alias("package_team_cba_evidence_stage_passed"),
            (
                prior_manual
                | prior_inconsistent
                | (prior_passed & ((~matched) | a_manual | b_manual | (~a_passed) | (~b_passed)))
            ).alias("package_team_cba_evidence_manual_review_required"),
            prior_blocked.alias("package_team_cba_evidence_blocked"),
        ]
    )
    joined = joined.with_columns(
        [
            pl.when(prior_blocked)
            .then(pl.lit("blocked_by_prior_right_legality_stage"))
            .when(prior_manual)
            .then(pl.lit("manual_review_from_prior_right_legality_stage"))
            .when(~prior_passed)
            .then(pl.lit("team_cba_prior_stage_inconsistent_internal_review"))
            .when(~matched)
            .then(pl.lit("team_cba_decision_unmatched_internal_review"))
            .when(a_manual | b_manual)
            .then(pl.lit("team_cba_manual_review_required"))
            .when(a_passed & b_passed)
            .then(pl.lit("team_cba_evidence_join_passed_remaining_player_and_package_cba_validation"))
            .otherwise(pl.lit("team_cba_inconsistent_decision_internal_review"))
            .alias("package_team_cba_evidence_status"),
            pl.lit(TEAM_EVIDENCE_RELEASE).alias("team_cba_evidence_release"),
            pl.lit(RELEASE_NAME).alias("team_cba_evaluator_release"),
            pl.lit(SCRIPT_VERSION).alias("team_cba_evaluator_version"),
            pl.lit(False).alias("team_cba_final_legal_status_released"),
        ]
    )
    return joined.select([*original_columns, *APPENDED_COLUMNS])


def run_self_test() -> int:
    status_cases = {
        "prior_block": pure_status(False, False, True, False, False, False, False, False),
        "prior_manual": pure_status(False, True, False, False, False, False, False, False),
        "prior_inconsistent": pure_status(False, False, False, False, False, False, False, False),
        "unmatched": pure_status(True, False, False, False, False, False, False, False),
        "team_manual": pure_status(True, False, False, True, True, False, False, True),
        "pass": pure_status(True, False, False, True, True, True, False, False),
    }
    tests = {
        "prior_block_preserved": status_cases["prior_block"][:3] == (False, False, True),
        "prior_manual_preserved": status_cases["prior_manual"][:3] == (False, True, False),
        "prior_inconsistent_is_manual": status_cases["prior_inconsistent"][1] is True,
        "unmatched_is_manual": status_cases["unmatched"][1] is True,
        "team_manual_is_manual": status_cases["team_manual"][:3] == (False, True, False),
        "pass_is_evidence_stage_only": status_cases["pass"][:3] == (True, False, False),
        "appended_columns_unique": len(APPENDED_COLUMNS) == len(set(APPENDED_COLUMNS)),
        "appended_column_count_58": len(APPENDED_COLUMNS) == 58,
        "final_legal_not_appended": "optimizer_package_final_legal" not in APPENDED_COLUMNS,
        "manual_team_set_six": len(EXPECTED_MANUAL_TEAMS) == 6,
        "global_partition": sum(EXPECTED_GLOBAL[key] for key in ("passed", "manual", "blocked")) == EXPECTED_GLOBAL["rows"],
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
            "Polars is required. Run this script in the nba-roster-optimizer environment used by the existing parquet pipeline."
        ) from exc

    root = project_root()
    outputs = root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    validation_rows: list[dict[str, str]] = []

    def check(scope: str, name: str, passed: bool, observed: Any, expected: Any) -> None:
        validation_rows.append({
            "scope": scope,
            "check_name": name,
            "passed": str(bool(passed)),
            "observed": str(observed),
            "expected": str(expected),
        })

    print("[1/8] Locating team decision release and V6 package parquets")
    decision_path = locate_one(root, DECISION_FILENAME)
    input_paths = {label: locate_one(root, filename) for label, filename in INPUT_FILES.items()}

    print("[2/8] Validating the 30-team decision release")
    decision_headers, decision_rows = read_decisions(decision_path)
    decision_validation = validate_decisions(decision_headers, decision_rows)
    for name, passed in decision_validation["checks"].items():
        check("decision_release", name, passed, passed, True)
    if not decision_validation["valid"]:
        raise RuntimeError("The team decision release failed validation:\n" + json.dumps(decision_validation, indent=2))
    decisions_a = build_side_decisions(pl, decision_path, "a")
    decisions_b = build_side_decisions(pl, decision_path, "b")

    evaluated_frames: dict[str, Any] = {}
    source_frames: dict[str, Any] = {}
    original_columns: dict[str, list[str]] = {}
    output_paths = {label: outputs / filename for label, filename in OUTPUT_FILES.items()}
    manual_summary_rows: list[dict[str, Any]] = []

    for step_number, label in ((3, "one_for_one"), (4, "two_for_one")):
        print(f"[{step_number}/8] Joining team evidence into {label.replace('_', '-')} packages")
        source = pl.read_parquet(str(input_paths[label]))
        source_frames[label] = source
        original_columns[label] = list(source.columns)
        check(label, "input_row_count", source.height == EXPECTED_ROWS[label], source.height, EXPECTED_ROWS[label])
        check(label, "input_column_count", source.width == EXPECTED_ORIGINAL_COLUMNS[label], source.width, EXPECTED_ORIGINAL_COLUMNS[label])
        check(label, "candidate_ids_unique", source["optimizer_candidate_id"].n_unique() == source.height, source["optimizer_candidate_id"].n_unique(), source.height)
        check(label, "team_keys_present", {"team_a", "team_b"}.issubset(source.columns), sorted({"team_a", "team_b"}.intersection(source.columns)), ["team_a", "team_b"])
        check(label, "salary_fields_present", {"side_a_player_trade_salary", "side_b_player_trade_salary"}.issubset(source.columns), sorted({"side_a_player_trade_salary", "side_b_player_trade_salary"}.intersection(source.columns)), ["side_a_player_trade_salary", "side_b_player_trade_salary"])
        check(label, "prior_status_fields_present", {"package_right_legality_stage_passed", "package_right_legality_manual_review_required", "package_right_legality_blocked"}.issubset(source.columns), "checked", True)
        check(label, "no_preexisting_appended_columns", not set(APPENDED_COLUMNS).intersection(source.columns), sorted(set(APPENDED_COLUMNS).intersection(source.columns)), [])

        evaluated = evaluate_packages(pl, source, decisions_a, decisions_b)
        evaluated_frames[label] = evaluated
        check(label, "join_preserved_row_count", evaluated.height == source.height, evaluated.height, source.height)
        preserved = frames_equal(source, evaluated.select(source.columns))
        check(label, "join_preserved_original_columns", preserved, preserved, True)
        check(label, "appended_column_count", evaluated.width == source.width + len(APPENDED_COLUMNS), evaluated.width - source.width, len(APPENDED_COLUMNS))
        check(label, "all_appended_columns_present", set(APPENDED_COLUMNS).issubset(evaluated.columns), len(set(APPENDED_COLUMNS).intersection(evaluated.columns)), len(APPENDED_COLUMNS))

        prior_counts = {
            "passed": int(evaluated["package_right_legality_stage_passed"].sum()),
            "manual": int(evaluated["package_right_legality_manual_review_required"].sum()),
            "blocked": int(evaluated["package_right_legality_blocked"].sum()),
        }
        combined_counts = {
            "passed": int(evaluated["package_team_cba_evidence_stage_passed"].sum()),
            "manual": int(evaluated["package_team_cba_evidence_manual_review_required"].sum()),
            "blocked": int(evaluated["package_team_cba_evidence_blocked"].sum()),
        }
        new_team_manual = evaluated.filter(
            pl.col("package_right_legality_stage_passed")
            & pl.col("package_team_cba_evidence_manual_review_required")
        ).height
        unmatched_after_prior_pass = evaluated.filter(
            pl.col("package_right_legality_stage_passed") & (~pl.col("team_cba_decisions_matched"))
        ).height
        proxy_nulls_after_prior_pass = evaluated.filter(
            pl.col("package_right_legality_stage_passed")
            & (
                pl.col("team_a_posttrade_apron_team_salary_proxy").is_null()
                | pl.col("team_b_posttrade_apron_team_salary_proxy").is_null()
            )
        ).height
        status_partition = sum(combined_counts.values())
        final_legal = int(evaluated["optimizer_package_final_legal"].sum())
        check(label, "prior_counts_unchanged", prior_counts == EXPECTED_PRIOR_RESULTS[label], prior_counts, EXPECTED_PRIOR_RESULTS[label])
        check(label, "team_evidence_pass_count", combined_counts["passed"] == EXPECTED_TEAM_EVIDENCE_RESULTS[label]["passed"], combined_counts["passed"], EXPECTED_TEAM_EVIDENCE_RESULTS[label]["passed"])
        check(label, "new_team_manual_count", new_team_manual == EXPECTED_TEAM_EVIDENCE_RESULTS[label]["new_team_manual"], new_team_manual, EXPECTED_TEAM_EVIDENCE_RESULTS[label]["new_team_manual"])
        check(label, "combined_manual_count", combined_counts["manual"] == EXPECTED_TEAM_EVIDENCE_RESULTS[label]["combined_manual"], combined_counts["manual"], EXPECTED_TEAM_EVIDENCE_RESULTS[label]["combined_manual"])
        check(label, "combined_blocked_count", combined_counts["blocked"] == EXPECTED_TEAM_EVIDENCE_RESULTS[label]["blocked"], combined_counts["blocked"], EXPECTED_TEAM_EVIDENCE_RESULTS[label]["blocked"])
        check(label, "combined_status_partition", status_partition == source.height, status_partition, source.height)
        check(label, "all_prior_passing_packages_match_two_team_decisions", unmatched_after_prior_pass == 0, unmatched_after_prior_pass, 0)
        check(label, "salary_proxies_populated_for_prior_pass", proxy_nulls_after_prior_pass == 0, proxy_nulls_after_prior_pass, 0)
        check(label, "final_legal_remains_zero", final_legal == 0, final_legal, 0)

        prior_queue = evaluated.filter(pl.col("package_right_legality_stage_passed"))
        counters = {
            team: {"team_a": 0, "team_b": 0, "unique_packages": set()}
            for team in EXPECTED_MANUAL_TEAMS
        }
        for candidate_id, team_a, a_manual, team_b, b_manual in prior_queue.select(
            [
                "optimizer_candidate_id",
                "team_a",
                "team_a_cba_manual_review_required",
                "team_b",
                "team_b_cba_manual_review_required",
            ]
        ).iter_rows():
            if a_manual and team_a in counters:
                counters[team_a]["team_a"] += 1
                counters[team_a]["unique_packages"].add(str(candidate_id))
            if b_manual and team_b in counters:
                counters[team_b]["team_b"] += 1
                counters[team_b]["unique_packages"].add(str(candidate_id))
        for team in sorted(EXPECTED_MANUAL_TEAMS):
            manual_summary_rows.append({
                "package_file": label,
                "manual_review_team": team,
                "team_a_package_count": counters[team]["team_a"],
                "team_b_package_count": counters[team]["team_b"],
                "unique_package_count": len(counters[team]["unique_packages"]),
            })

    print("[5/8] Validating global team-evidence propagation totals")
    global_counts = {
        "rows": sum(frame.height for frame in evaluated_frames.values()),
        "passed": sum(int(frame["package_team_cba_evidence_stage_passed"].sum()) for frame in evaluated_frames.values()),
        "manual": sum(int(frame["package_team_cba_evidence_manual_review_required"].sum()) for frame in evaluated_frames.values()),
        "blocked": sum(int(frame["package_team_cba_evidence_blocked"].sum()) for frame in evaluated_frames.values()),
    }
    check("global", "global_partition_matches_expected", global_counts == EXPECTED_GLOBAL, global_counts, EXPECTED_GLOBAL)
    check("global", "manual_summary_has_12_rows", len(manual_summary_rows) == 12, len(manual_summary_rows), 12)
    check("global", "manual_summary_teams_exact", {row["manual_review_team"] for row in manual_summary_rows} == EXPECTED_MANUAL_TEAMS, sorted({row["manual_review_team"] for row in manual_summary_rows}), sorted(EXPECTED_MANUAL_TEAMS))
    check("global", "final_legal_zero_globally", sum(int(frame["optimizer_package_final_legal"].sum()) for frame in evaluated_frames.values()) == 0, sum(int(frame["optimizer_package_final_legal"].sum()) for frame in evaluated_frames.values()), 0)

    pre_save_valid = all(row["passed"] == "True" for row in validation_rows)
    check("global", "pre_save_validation_gate", pre_save_valid, pre_save_valid, True)
    pre_save_valid = all(row["passed"] == "True" for row in validation_rows)

    summary_rows: list[dict[str, Any]] = []
    if pre_save_valid:
        print("[6/8] Saving V7 team-CBA-evidence-evaluated package parquets")
        for label, frame in evaluated_frames.items():
            frame.write_parquet(str(output_paths[label]), compression="zstd", statistics=True)
            for metric, column in (
                ("team_evidence_stage_passed", "package_team_cba_evidence_stage_passed"),
                ("team_evidence_manual_review", "package_team_cba_evidence_manual_review_required"),
                ("team_evidence_blocked", "package_team_cba_evidence_blocked"),
                ("team_decisions_matched", "team_cba_decisions_matched"),
                ("final_legal", "optimizer_package_final_legal"),
            ):
                summary_rows.append({
                    "package_file": label,
                    "metric": metric,
                    "category": "True",
                    "count": int(frame[column].sum()),
                })
            for category, count in value_counts_map(frame, "package_team_cba_evidence_status").items():
                summary_rows.append({
                    "package_file": label,
                    "metric": "package_team_cba_evidence_status",
                    "category": category,
                    "count": count,
                })
        write_csv(outputs / SUMMARY_FILENAME, ["package_file", "metric", "category", "count"], summary_rows)
        write_csv(
            outputs / MANUAL_SUMMARY_FILENAME,
            ["package_file", "manual_review_team", "team_a_package_count", "team_b_package_count", "unique_package_count"],
            manual_summary_rows,
        )

        print("[7/8] Reloading V7 outputs and confirming non-destructive preservation")
        for label, source in source_frames.items():
            saved = pl.read_parquet(str(output_paths[label]))
            preserved = frames_equal(source, saved.select(original_columns[label]))
            check(label, "saved_output_row_count", saved.height == source.height, saved.height, source.height)
            check(label, "saved_output_column_count", saved.width == source.width + len(APPENDED_COLUMNS), saved.width, source.width + len(APPENDED_COLUMNS))
            check(label, "saved_output_preserves_original_columns", preserved, preserved, True)
            check(label, "saved_output_final_legal_unreleased", int(saved["optimizer_package_final_legal"].sum()) == 0, int(saved["optimizer_package_final_legal"].sum()), 0)
    else:
        print("[6/8] Pre-save validation failed; V7 package parquets were not written")
        print("[7/8] Output reload skipped")

    print("[8/8] Saving validation and metadata")
    release_valid = all(row["passed"] == "True" for row in validation_rows)
    write_csv(outputs / VALIDATION_FILENAME, ["scope", "check_name", "passed", "observed", "expected"], validation_rows)

    packages: dict[str, dict[str, Any]] = {}
    for label, frame in evaluated_frames.items():
        packages[label] = {
            "rows": frame.height,
            "columns_before": len(original_columns[label]),
            "columns_after": frame.width,
            "prior_right_legality_passed": int(frame["package_right_legality_stage_passed"].sum()),
            "team_evidence_stage_passed": int(frame["package_team_cba_evidence_stage_passed"].sum()),
            "team_evidence_manual_review": int(frame["package_team_cba_evidence_manual_review_required"].sum()),
            "team_evidence_blocked": int(frame["package_team_cba_evidence_blocked"].sum()),
            "team_decisions_matched": int(frame["team_cba_decisions_matched"].sum()),
            "final_legal": int(frame["optimizer_package_final_legal"].sum()),
            "status_counts": value_counts_map(frame, "package_team_cba_evidence_status"),
            "output_path": str(output_paths[label]) if output_paths[label].exists() else None,
        }

    metadata = {
        "script_version": SCRIPT_VERSION,
        "release_name": RELEASE_NAME,
        "team_evidence_release": TEAM_EVIDENCE_RELEASE,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "release_valid": release_valid,
        "decision_release": {"path": str(decision_path), **decision_validation},
        "appended_columns": APPENDED_COLUMNS,
        "appended_column_count": len(APPENDED_COLUMNS),
        "packages": packages,
        "global_counts": global_counts,
        "manual_review_teams": sorted(EXPECTED_MANUAL_TEAMS),
        "manual_review_summary_file": str(outputs / MANUAL_SUMMARY_FILENAME) if (outputs / MANUAL_SUMMARY_FILENAME).exists() else None,
        "summary_file": str(outputs / SUMMARY_FILENAME) if (outputs / SUMMARY_FILENAME).exists() else None,
        "validation_file": str(outputs / VALIDATION_FILENAME),
        "validation_checks_passed": sum(row["passed"] == "True" for row in validation_rows),
        "validation_checks_total": len(validation_rows),
        "package_final_legal_status_released": False,
        "salary_proxy_note": (
            "Post-trade apron salary values are directional proxies computed from verified pre-trade Apron Team Salary plus the package player-salary delta. "
            "They do not account for trade bonuses, poison-pill treatment, BYC, sign-and-trade mechanics, exceptions, cash, or other adjustments and cannot release legality."
        ),
        "next_step": (
            "Validate player-level restrictions and exact outgoing/incoming matching salary treatment for the 83,975 team-evidence-passing packages, then evaluate package-specific apron, hard-cap, aggregation, roster, sign-and-trade, exception, and cash rules."
        ),
    }
    with (outputs / METADATA_FILENAME).open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, sort_keys=False)
        handle.write("\n")

    print()
    print("=" * 80)
    print("TEAM CBA EVIDENCE PROPAGATION COMPLETE")
    print("=" * 80)
    print(f"Packages processed: {global_counts['rows']:,}")
    print(f"Team-evidence stage passed: {global_counts['passed']:,}")
    print(f"Combined manual review: {global_counts['manual']:,}")
    print(f"Blocked by prior stages: {global_counts['blocked']:,}")
    print(f"Validation checks passed: {sum(row['passed'] == 'True' for row in validation_rows)}/{len(validation_rows)}")
    print(f"Release valid: {release_valid}")
    print("Final package legality released: False")
    print()
    print("NEXT REVIEW FILES")
    print(outputs / METADATA_FILENAME)
    print(outputs / MANUAL_SUMMARY_FILENAME)
    print()
    print("SAVED PACKAGE FILES")
    for path in output_paths.values():
        print(path)

    return 0 if release_valid else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise