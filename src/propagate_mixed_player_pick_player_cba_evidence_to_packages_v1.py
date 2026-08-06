"""Propagate the consolidated player-CBA evidence release into V7 trade packages.

Place this file in the project's ``src`` directory and place
``mixed_player_pick_player_cba_decision_release_v1.csv`` in ``outputs``.

The script performs a non-destructive player-evidence join against the existing
V7 team-CBA-evaluated one-for-one and two-for-one package parquets. It preserves
every input package column in its original order, appends player-level salary
and restriction evidence, and writes V8 player-CBA-evaluated package parquets.

This is still an evidence stage. It deliberately leaves
``optimizer_package_final_legal`` false. Final package legality requires the
subsequent full-CBA package evaluator.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_VERSION = "mixed-player-pick-player-cba-evidence-propagator-v1-2026-08-05"
RELEASE_NAME = "mixed_player_pick_package_player_cba_evidence_2026_27_v1"
PLAYER_EVIDENCE_RELEASE = "mixed_player_pick_player_cba_decision_release_v1"

DECISION_FILENAME = "mixed_player_pick_player_cba_decision_release_v1.csv"
INPUT_FILES = {
    "one_for_one": "one_for_one_mixed_player_pick_candidates_2026_27_v7_team_cba_evidence_evaluated.parquet",
    "two_for_one": "two_for_one_mixed_player_pick_candidates_2026_27_v7_team_cba_evidence_evaluated.parquet",
}
OUTPUT_FILES = {
    "one_for_one": "one_for_one_mixed_player_pick_candidates_2026_27_v8_player_cba_evidence_evaluated.parquet",
    "two_for_one": "two_for_one_mixed_player_pick_candidates_2026_27_v8_player_cba_evidence_evaluated.parquet",
}

EXPECTED_ROWS = {"one_for_one": 28_324, "two_for_one": 282_277}
EXPECTED_INPUT_COLUMNS = {"one_for_one": 153, "two_for_one": 151}
EXPECTED_PRIOR_RESULTS = {
    "one_for_one": {"passed": 11_269, "manual": 10_333, "blocked": 6_722},
    "two_for_one": {"passed": 72_706, "manual": 58_584, "blocked": 150_987},
}
EXPECTED_DECISION_COUNTS = {
    "verified_clear": 180,
    "verified_with_conditions": 23,
    "manual_review_required": 27,
    "not_trade_eligible": 81,
}

SUMMARY_FILENAME = "mixed_player_pick_package_player_cba_summary_v1.csv"
ISSUE_SUMMARY_FILENAME = "mixed_player_pick_package_player_cba_issue_summary_v1.csv"
VALIDATION_FILENAME = "mixed_player_pick_package_player_cba_validation_v1.csv"
METADATA_FILENAME = "mixed_player_pick_package_player_cba_metadata_v1.json"

PACKAGE_REQUIRED_COLUMNS = {
    "optimizer_candidate_id",
    "team_a",
    "team_b",
    "side_a_player_ids",
    "side_b_player_ids",
    "side_a_player_trade_salary",
    "side_b_player_trade_salary",
    "package_team_cba_evidence_stage_passed",
    "package_team_cba_evidence_manual_review_required",
    "package_team_cba_evidence_blocked",
    "package_team_cba_evidence_status",
    "optimizer_package_final_legal",
}

DECISION_REQUIRED_COLUMNS = {
    "player_id",
    "player_name",
    "current_team_2026_27",
    "trade_salary_2026_27",
    "contract_type",
    "two_way_contract_active",
    "trade_eligible_on_trade_date",
    "aggregation_restricted_on_trade_date",
    "no_trade_clause_active",
    "trade_consent_required",
    "trade_bonus_percent",
    "remaining_trade_bonus_amount",
    "trade_bonus_adjusted_outgoing_salary",
    "poison_pill_active",
    "poison_pill_outgoing_salary",
    "poison_pill_incoming_salary",
    "base_year_compensation_active",
    "base_year_compensation_outgoing_salary",
    "sign_and_trade_player",
    "extend_and_trade_restriction_active",
    "restriction_end_date",
    "player_cba_evidence_determination",
    "manual_review_required",
    "player_cba_stage_pass",
    "research_complete",
}

SIDE_SUFFIXES = [
    "player_count",
    "decisions_matched_count",
    "decisions_matched",
    "verified_outgoing_salary",
    "verified_incoming_salary_for_opponent",
    "verified_outgoing_salary_delta",
    "not_trade_eligible_count",
    "manual_review_count",
    "conditional_count",
    "aggregation_restricted_count",
    "aggregation_blocked",
    "consent_required_count",
    "trade_bonus_active_count",
    "poison_pill_count",
    "base_year_compensation_count",
    "sign_and_trade_count",
    "extend_and_trade_restriction_count",
    "two_way_contract_count",
]

PACKAGE_APPENDED_COLUMNS = [
    "player_cba_decisions_expected",
    "player_cba_decisions_matched_count",
    "player_cba_decisions_matched",
    "player_cba_salary_refresh_required",
    "player_cba_asymmetric_salary_treatment_required",
    "package_player_cba_has_conditions",
    "package_player_cba_aggregation_blocked",
    "package_player_cba_consent_required",
    "package_player_cba_trade_bonus_review_required",
    "package_player_cba_stage_passed",
    "package_player_cba_manual_review_required",
    "package_player_cba_blocked",
    "package_player_cba_status",
    "player_cba_evidence_release",
    "player_cba_evaluator_release",
    "player_cba_evaluator_version",
    "player_cba_final_legal_status_released",
]
APPENDED_COLUMNS = [
    *(f"side_a_player_cba_{suffix}" for suffix in SIDE_SUFFIXES),
    *(f"side_b_player_cba_{suffix}" for suffix in SIDE_SUFFIXES),
    *PACKAGE_APPENDED_COLUMNS,
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run dependency-free status tests without reading project files.",
    )
    parser.add_argument(
        "--validate-decisions-only",
        action="store_true",
        help="Validate the consolidated decision release and stop before reading parquets.",
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
        raise RuntimeError(
            f"Found multiple copies of {filename}; keep exactly one:\n  {joined}"
        )
    return matches[0]


def normalize_id(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    return text


def split_player_ids(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [normalize_id(item) for item in value if normalize_id(item)]
    text = normalize_id(value)
    if not text:
        return []
    return [
        normalize_id(part)
        for part in re.split(r"\s*[|;,]\s*", text)
        if normalize_id(part)
    ]


def normalized_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in {"true", "1", "yes", "y"}:
        return True
    if lowered in {"false", "0", "no", "n"}:
        return False
    return None


def normalized_float(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def pure_status(
    prior_passed: bool,
    prior_manual: bool,
    prior_blocked: bool,
    decisions_matched: bool,
    player_not_eligible: bool,
    aggregation_blocked: bool,
    player_manual: bool,
    consent_required: bool,
    sign_and_trade_present: bool,
    has_conditions: bool,
) -> tuple[bool, bool, bool, str]:
    if prior_blocked:
        return False, False, True, "blocked_by_prior_team_cba_stage"
    if prior_manual:
        return False, True, False, "manual_review_from_prior_team_cba_stage"
    if not prior_passed:
        return False, True, False, "player_cba_prior_stage_inconsistent_internal_review"
    if not decisions_matched:
        return False, True, False, "player_cba_decision_unmatched_internal_review"
    if player_not_eligible:
        return False, False, True, "blocked_by_player_trade_ineligibility"
    if aggregation_blocked:
        return False, False, True, "blocked_by_player_aggregation_restriction"
    if player_manual:
        return False, True, False, "player_cba_manual_review_required"
    if consent_required:
        return False, True, False, "player_trade_consent_required"
    if sign_and_trade_present:
        return False, True, False, "sign_and_trade_mechanics_manual_review"
    if has_conditions:
        return (
            True,
            False,
            False,
            "player_cba_evidence_passed_with_conditions_remaining_full_cba_validation",
        )
    return (
        True,
        False,
        False,
        "player_cba_evidence_passed_clear_remaining_full_cba_validation",
    )


def run_self_test() -> int:
    cases = {
        "prior_block": pure_status(
            False, False, True, False, False, False, False, False, False, False
        ),
        "prior_manual": pure_status(
            False, True, False, False, False, False, False, False, False, False
        ),
        "unmatched": pure_status(
            True, False, False, False, False, False, False, False, False, False
        ),
        "not_eligible": pure_status(
            True, False, False, True, True, False, False, False, False, False
        ),
        "aggregation_block": pure_status(
            True, False, False, True, False, True, False, False, False, True
        ),
        "player_manual": pure_status(
            True, False, False, True, False, False, True, False, False, False
        ),
        "consent": pure_status(
            True, False, False, True, False, False, False, True, False, True
        ),
        "conditional_pass": pure_status(
            True, False, False, True, False, False, False, False, False, True
        ),
        "clear_pass": pure_status(
            True, False, False, True, False, False, False, False, False, False
        ),
    }
    tests = {
        "prior_block_preserved": cases["prior_block"][:3] == (False, False, True),
        "prior_manual_preserved": cases["prior_manual"][:3] == (False, True, False),
        "unmatched_is_manual": cases["unmatched"][1] is True,
        "not_eligible_is_blocked": cases["not_eligible"][2] is True,
        "aggregation_restriction_is_blocked_when_aggregated": (
            cases["aggregation_block"][2] is True
        ),
        "manual_player_is_manual": cases["player_manual"][1] is True,
        "consent_is_manual": cases["consent"][1] is True,
        "conditional_can_stage_pass": cases["conditional_pass"][:3]
        == (True, False, False),
        "clear_can_stage_pass": cases["clear_pass"][:3] == (True, False, False),
        "appended_columns_unique": len(APPENDED_COLUMNS) == len(set(APPENDED_COLUMNS)),
        "final_legal_not_overwritten": (
            "optimizer_package_final_legal" not in APPENDED_COLUMNS
        ),
    }
    print(json.dumps(tests, indent=2))
    return 0 if all(tests.values()) else 1


def write_csv(path: Path, headers: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, default=str)
        handle.write("\n")


def value_counts_map(frame: Any, column: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in frame.group_by(column).len().to_dicts():
        key = "<null>" if row[column] is None else str(row[column])
        result[key] = int(row["len"])
    return dict(sorted(result.items()))


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
    raise AttributeError(
        "This Polars version exposes neither DataFrame.equals nor frame_equal"
    )


def bool_expr(pl: Any, column: str, alias: str) -> Any:
    string_dtype = getattr(pl, "String", pl.Utf8)
    return (
        pl.col(column).cast(string_dtype, strict=False).str.to_lowercase()
        == "true"
    ).alias(alias)


def read_and_validate_decisions(pl: Any, path: Path) -> tuple[Any, dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        rows = list(reader)

    missing = sorted(DECISION_REQUIRED_COLUMNS.difference(headers))
    ids = [normalize_id(row.get("player_id")) for row in rows]
    determinations = Counter(
        str(row.get("player_cba_evidence_determination", "")).strip()
        for row in rows
    )

    flags_consistent = True
    for row in rows:
        determination = str(
            row.get("player_cba_evidence_determination", "")
        ).strip()
        stage_pass = normalized_bool(row.get("player_cba_stage_pass"))
        manual = normalized_bool(row.get("manual_review_required"))
        trade_eligible = normalized_bool(row.get("trade_eligible_on_trade_date"))
        research_complete = normalized_bool(row.get("research_complete"))

        expected = {
            "verified_clear": (True, False),
            "verified_with_conditions": (True, False),
            "manual_review_required": (False, True),
            "not_trade_eligible": (False, False),
        }.get(determination)

        if expected is None or (stage_pass, manual) != expected:
            flags_consistent = False
        if determination == "not_trade_eligible" and trade_eligible is not False:
            flags_consistent = False
        if research_complete is not True:
            flags_consistent = False

    checks = {
        "required_columns_present": not missing,
        "row_count_311": len(rows) == 311,
        "unique_player_ids": len(ids) == len(set(ids)) == 311,
        "no_blank_player_ids": all(ids),
        "determination_counts_exact": determinations
        == Counter(EXPECTED_DECISION_COUNTS),
        "stage_flags_consistent": flags_consistent,
        "evidence_dates_consistent": all(
            row.get("evidence_as_of_date") == "2026-08-04" for row in rows
        ),
    }

    string_dtype = getattr(pl, "String", pl.Utf8)
    raw = pl.read_csv(str(path), infer_schema_length=0)
    frame = raw.select(
        [
            pl.col("player_id")
            .cast(string_dtype, strict=False)
            .str.replace(r"\.0$", "")
            .alias("player_id"),
            pl.col("player_name"),
            pl.col("current_team_2026_27"),
            pl.col("contract_type"),
            bool_expr(pl, "two_way_contract_active", "two_way_contract_active"),
            bool_expr(
                pl,
                "trade_eligible_on_trade_date",
                "trade_eligible_on_trade_date",
            ),
            bool_expr(
                pl,
                "aggregation_restricted_on_trade_date",
                "aggregation_restricted_on_trade_date",
            ),
            bool_expr(pl, "no_trade_clause_active", "no_trade_clause_active"),
            bool_expr(pl, "trade_consent_required", "trade_consent_required"),
            pl.col("trade_bonus_percent")
            .cast(pl.Float64, strict=False)
            .fill_null(0.0)
            .alias("trade_bonus_percent"),
            pl.col("remaining_trade_bonus_amount")
            .cast(pl.Float64, strict=False)
            .fill_null(0.0)
            .alias("remaining_trade_bonus_amount"),
            pl.col("trade_bonus_adjusted_outgoing_salary")
            .cast(pl.Float64, strict=False)
            .alias("verified_outgoing_salary"),
            bool_expr(pl, "poison_pill_active", "poison_pill_active"),
            pl.col("poison_pill_incoming_salary")
            .cast(pl.Float64, strict=False)
            .alias("verified_incoming_salary_for_opponent"),
            bool_expr(
                pl,
                "base_year_compensation_active",
                "base_year_compensation_active",
            ),
            bool_expr(pl, "sign_and_trade_player", "sign_and_trade_player"),
            bool_expr(
                pl,
                "extend_and_trade_restriction_active",
                "extend_and_trade_restriction_active",
            ),
            pl.col("restriction_end_date"),
            pl.col("player_cba_evidence_determination"),
            bool_expr(pl, "manual_review_required", "manual_review_required"),
            bool_expr(pl, "player_cba_stage_pass", "player_cba_stage_pass"),
        ]
    )

    validation = {
        "valid": all(checks.values()),
        "checks": checks,
        "missing_columns": missing,
        "rows": len(rows),
        "columns": len(headers),
        "determination_counts": dict(sorted(determinations.items())),
    }
    return frame, validation


def build_side_profile(pl: Any, source: Any, decisions: Any, side: str) -> Any:
    string_dtype = getattr(pl, "String", pl.Utf8)
    ids_column = f"side_{side}_player_ids"
    salary_column = f"side_{side}_player_trade_salary"
    prefix = f"side_{side}_player_cba_"

    long = source.select(
        [
            "__player_cba_row_order",
            pl.col(salary_column)
            .cast(pl.Float64, strict=False)
            .alias("__input_side_salary"),
            pl.col(ids_column)
            .map_elements(
                split_player_ids,
                return_dtype=pl.List(string_dtype),
            )
            .alias("__player_ids"),
        ]
    )
    long = long.with_columns(
        pl.col("__player_ids").list.len().alias("__side_player_count")
    ).explode("__player_ids")
    long = long.rename({"__player_ids": "player_id"})
    long = long.join(decisions, on="player_id", how="left")

    long = long.with_columns(
        [
            pl.col("player_cba_evidence_determination")
            .is_not_null()
            .alias("__decision_matched"),
            (
                pl.col("player_cba_evidence_determination")
                == "not_trade_eligible"
            ).fill_null(False).alias("__not_trade_eligible"),
            (
                pl.col("player_cba_evidence_determination")
                == "verified_with_conditions"
            ).fill_null(False).alias("__conditional"),
            pl.col("manual_review_required")
            .fill_null(False)
            .alias("__manual"),
            (
                pl.col("aggregation_restricted_on_trade_date").fill_null(False)
                & (pl.col("__side_player_count") > 1)
            ).alias("__aggregation_blocked"),
            pl.col("trade_consent_required")
            .fill_null(False)
            .alias("__consent_required"),
            (
                (pl.col("trade_bonus_percent").fill_null(0.0) > 0)
                & (pl.col("remaining_trade_bonus_amount").fill_null(0.0) > 0)
            ).alias("__trade_bonus_active"),
            pl.col("poison_pill_active")
            .fill_null(False)
            .alias("__poison_pill"),
            pl.col("base_year_compensation_active")
            .fill_null(False)
            .alias("__byc"),
            pl.col("sign_and_trade_player")
            .fill_null(False)
            .alias("__sign_and_trade"),
            pl.col("extend_and_trade_restriction_active")
            .fill_null(False)
            .alias("__extend_restriction"),
            pl.col("two_way_contract_active")
            .fill_null(False)
            .alias("__two_way"),
        ]
    )

    grouped = long.group_by("__player_cba_row_order").agg(
        [
            pl.col("__side_player_count").max().alias(prefix + "player_count"),
            pl.col("__decision_matched")
            .cast(pl.Int64)
            .sum()
            .alias(prefix + "decisions_matched_count"),
            pl.col("verified_outgoing_salary")
            .sum()
            .alias(prefix + "verified_outgoing_salary"),
            pl.col("verified_incoming_salary_for_opponent")
            .sum()
            .alias(prefix + "verified_incoming_salary_for_opponent"),
            pl.col("__not_trade_eligible")
            .cast(pl.Int64)
            .sum()
            .alias(prefix + "not_trade_eligible_count"),
            pl.col("__manual")
            .cast(pl.Int64)
            .sum()
            .alias(prefix + "manual_review_count"),
            pl.col("__conditional")
            .cast(pl.Int64)
            .sum()
            .alias(prefix + "conditional_count"),
            pl.col("aggregation_restricted_on_trade_date")
            .fill_null(False)
            .cast(pl.Int64)
            .sum()
            .alias(prefix + "aggregation_restricted_count"),
            pl.col("__aggregation_blocked")
            .max()
            .alias(prefix + "aggregation_blocked"),
            pl.col("__consent_required")
            .cast(pl.Int64)
            .sum()
            .alias(prefix + "consent_required_count"),
            pl.col("__trade_bonus_active")
            .cast(pl.Int64)
            .sum()
            .alias(prefix + "trade_bonus_active_count"),
            pl.col("__poison_pill")
            .cast(pl.Int64)
            .sum()
            .alias(prefix + "poison_pill_count"),
            pl.col("__byc")
            .cast(pl.Int64)
            .sum()
            .alias(prefix + "base_year_compensation_count"),
            pl.col("__sign_and_trade")
            .cast(pl.Int64)
            .sum()
            .alias(prefix + "sign_and_trade_count"),
            pl.col("__extend_restriction")
            .cast(pl.Int64)
            .sum()
            .alias(prefix + "extend_and_trade_restriction_count"),
            pl.col("__two_way")
            .cast(pl.Int64)
            .sum()
            .alias(prefix + "two_way_contract_count"),
            pl.col("__input_side_salary").first().alias("__input_side_salary"),
        ]
    )

    grouped = grouped.with_columns(
        [
            (
                pl.col(prefix + "decisions_matched_count")
                == pl.col(prefix + "player_count")
            ).alias(prefix + "decisions_matched"),
            (
                pl.col(prefix + "verified_outgoing_salary")
                - pl.col("__input_side_salary")
            ).alias(prefix + "verified_outgoing_salary_delta"),
        ]
    ).drop("__input_side_salary")

    return grouped


def evaluate_packages(pl: Any, source: Any, decisions: Any) -> Any:
    original_columns = list(source.columns)
    joined = source.with_row_count("__player_cba_row_order")

    side_a = build_side_profile(pl, joined, decisions, "a")
    side_b = build_side_profile(pl, joined, decisions, "b")

    joined = joined.join(side_a, on="__player_cba_row_order", how="left")
    joined = joined.join(side_b, on="__player_cba_row_order", how="left")
    joined = joined.sort("__player_cba_row_order")

    a = "side_a_player_cba_"
    b = "side_b_player_cba_"

    prior_passed = pl.col("package_team_cba_evidence_stage_passed").fill_null(False)
    prior_manual = pl.col(
        "package_team_cba_evidence_manual_review_required"
    ).fill_null(False)
    prior_blocked = pl.col("package_team_cba_evidence_blocked").fill_null(False)

    decisions_matched = (
        pl.col(a + "decisions_matched").fill_null(False)
        & pl.col(b + "decisions_matched").fill_null(False)
    )
    player_not_eligible = (
        pl.col(a + "not_trade_eligible_count").fill_null(0)
        + pl.col(b + "not_trade_eligible_count").fill_null(0)
        > 0
    )
    aggregation_blocked = (
        pl.col(a + "aggregation_blocked").fill_null(False)
        | pl.col(b + "aggregation_blocked").fill_null(False)
    )
    player_manual = (
        pl.col(a + "manual_review_count").fill_null(0)
        + pl.col(b + "manual_review_count").fill_null(0)
        > 0
    )
    consent_required = (
        pl.col(a + "consent_required_count").fill_null(0)
        + pl.col(b + "consent_required_count").fill_null(0)
        > 0
    )
    sign_and_trade_present = (
        pl.col(a + "sign_and_trade_count").fill_null(0)
        + pl.col(b + "sign_and_trade_count").fill_null(0)
        > 0
    )
    has_conditions = (
        pl.col(a + "conditional_count").fill_null(0)
        + pl.col(b + "conditional_count").fill_null(0)
        > 0
    )
    trade_bonus_review = (
        pl.col(a + "trade_bonus_active_count").fill_null(0)
        + pl.col(b + "trade_bonus_active_count").fill_null(0)
        > 0
    ) & player_manual

    salary_refresh_required = (
        pl.col(a + "verified_outgoing_salary_delta").abs().fill_null(0.0) > 0.01
    ) | (
        pl.col(b + "verified_outgoing_salary_delta").abs().fill_null(0.0) > 0.01
    )
    asymmetric_salary = (
        pl.col(a + "poison_pill_count").fill_null(0)
        + pl.col(b + "poison_pill_count").fill_null(0)
        + pl.col(a + "base_year_compensation_count").fill_null(0)
        + pl.col(b + "base_year_compensation_count").fill_null(0)
        > 0
    )

    player_blocked = player_not_eligible | aggregation_blocked
    package_manual = (
        prior_manual
        | ((~prior_passed) & (~prior_blocked))
        | (
            prior_passed
            & (~player_blocked)
            & (
                (~decisions_matched)
                | player_manual
                | consent_required
                | sign_and_trade_present
            )
        )
    )
    package_blocked = prior_blocked | (prior_passed & player_blocked)
    package_passed = (
        prior_passed
        & decisions_matched
        & (~player_blocked)
        & (~player_manual)
        & (~consent_required)
        & (~sign_and_trade_present)
    )

    joined = joined.with_columns(
        [
            (
                pl.col(a + "player_count").fill_null(0)
                + pl.col(b + "player_count").fill_null(0)
            ).alias("player_cba_decisions_expected"),
            (
                pl.col(a + "decisions_matched_count").fill_null(0)
                + pl.col(b + "decisions_matched_count").fill_null(0)
            ).alias("player_cba_decisions_matched_count"),
            decisions_matched.alias("player_cba_decisions_matched"),
            salary_refresh_required.alias("player_cba_salary_refresh_required"),
            asymmetric_salary.alias(
                "player_cba_asymmetric_salary_treatment_required"
            ),
            has_conditions.alias("package_player_cba_has_conditions"),
            aggregation_blocked.alias(
                "package_player_cba_aggregation_blocked"
            ),
            consent_required.alias("package_player_cba_consent_required"),
            trade_bonus_review.alias(
                "package_player_cba_trade_bonus_review_required"
            ),
            package_passed.alias("package_player_cba_stage_passed"),
            package_manual.alias("package_player_cba_manual_review_required"),
            package_blocked.alias("package_player_cba_blocked"),
        ]
    )

    joined = joined.with_columns(
        [
            pl.when(prior_blocked)
            .then(pl.lit("blocked_by_prior_team_cba_stage"))
            .when(prior_manual)
            .then(pl.lit("manual_review_from_prior_team_cba_stage"))
            .when((~prior_passed) & (~prior_blocked))
            .then(pl.lit("player_cba_prior_stage_inconsistent_internal_review"))
            .when(~decisions_matched)
            .then(pl.lit("player_cba_decision_unmatched_internal_review"))
            .when(player_not_eligible)
            .then(pl.lit("blocked_by_player_trade_ineligibility"))
            .when(aggregation_blocked)
            .then(pl.lit("blocked_by_player_aggregation_restriction"))
            .when(player_manual)
            .then(pl.lit("player_cba_manual_review_required"))
            .when(consent_required)
            .then(pl.lit("player_trade_consent_required"))
            .when(sign_and_trade_present)
            .then(pl.lit("sign_and_trade_mechanics_manual_review"))
            .when(has_conditions)
            .then(
                pl.lit(
                    "player_cba_evidence_passed_with_conditions_remaining_full_cba_validation"
                )
            )
            .otherwise(
                pl.lit(
                    "player_cba_evidence_passed_clear_remaining_full_cba_validation"
                )
            )
            .alias("package_player_cba_status"),
            pl.lit(PLAYER_EVIDENCE_RELEASE).alias("player_cba_evidence_release"),
            pl.lit(RELEASE_NAME).alias("player_cba_evaluator_release"),
            pl.lit(SCRIPT_VERSION).alias("player_cba_evaluator_version"),
            pl.lit(False).alias("player_cba_final_legal_status_released"),
        ]
    )

    return joined.select([*original_columns, *APPENDED_COLUMNS])


def validate_package(
    pl: Any,
    label: str,
    source: Any,
    evaluated: Any,
    original_columns: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, observed: Any, expected: Any) -> None:
        checks.append(
            {
                "package_type": label,
                "check_name": name,
                "passed": bool(passed),
                "observed": observed,
                "expected": expected,
            }
        )

    expected = EXPECTED_PRIOR_RESULTS[label]
    prior_passed = int(source["package_team_cba_evidence_stage_passed"].sum())
    prior_manual = int(
        source["package_team_cba_evidence_manual_review_required"].sum()
    )
    prior_blocked = int(source["package_team_cba_evidence_blocked"].sum())

    output_passed = int(evaluated["package_player_cba_stage_passed"].sum())
    output_manual = int(
        evaluated["package_player_cba_manual_review_required"].sum()
    )
    output_blocked = int(evaluated["package_player_cba_blocked"].sum())

    check("row_count", source.height == EXPECTED_ROWS[label], source.height, EXPECTED_ROWS[label])
    check(
        "input_column_count",
        source.width == EXPECTED_INPUT_COLUMNS[label],
        source.width,
        EXPECTED_INPUT_COLUMNS[label],
    )
    check(
        "prior_partition_exact",
        (prior_passed, prior_manual, prior_blocked)
        == (expected["passed"], expected["manual"], expected["blocked"]),
        [prior_passed, prior_manual, prior_blocked],
        [expected["passed"], expected["manual"], expected["blocked"]],
    )
    check(
        "output_column_count",
        evaluated.width == source.width + len(APPENDED_COLUMNS),
        evaluated.width,
        source.width + len(APPENDED_COLUMNS),
    )
    check(
        "original_columns_preserved",
        frames_equal(
            source.select(original_columns),
            evaluated.select(original_columns),
        ),
        True,
        True,
    )
    check(
        "output_partition_complete",
        output_passed + output_manual + output_blocked == source.height,
        output_passed + output_manual + output_blocked,
        source.height,
    )
    check(
        "prior_blocked_preserved",
        output_blocked >= prior_blocked,
        output_blocked,
        f">={prior_blocked}",
    )
    check(
        "prior_manual_preserved",
        output_manual >= prior_manual,
        output_manual,
        f">={prior_manual}",
    )
    check(
        "player_pass_cannot_exceed_prior_pass",
        output_passed <= prior_passed,
        output_passed,
        f"<={prior_passed}",
    )

    advancing = evaluated.filter(
        pl.col("package_team_cba_evidence_stage_passed") == True  # noqa: E712
    )
    check(
        "all_prior_advancing_player_decisions_matched",
        int(advancing["player_cba_decisions_matched"].sum())
        == advancing.height,
        int(advancing["player_cba_decisions_matched"].sum()),
        advancing.height,
    )
    check(
        "expected_player_count_on_prior_advancing_rows",
        int(
            (
                advancing["player_cba_decisions_expected"]
                == (2 if label == "one_for_one" else 3)
            ).sum()
        )
        == advancing.height,
        int(
            (
                advancing["player_cba_decisions_expected"]
                == (2 if label == "one_for_one" else 3)
            ).sum()
        ),
        advancing.height,
    )
    check(
        "final_legal_status_unreleased",
        int(evaluated["optimizer_package_final_legal"].sum()) == 0
        and int(evaluated["player_cba_final_legal_status_released"].sum()) == 0,
        {
            "optimizer_package_final_legal": int(
                evaluated["optimizer_package_final_legal"].sum()
            ),
            "player_cba_final_legal_status_released": int(
                evaluated["player_cba_final_legal_status_released"].sum()
            ),
        },
        {"optimizer_package_final_legal": 0, "player_cba_final_legal_status_released": 0},
    )

    profile = {
        "rows": evaluated.height,
        "input_columns": source.width,
        "output_columns": evaluated.width,
        "prior": {
            "passed": prior_passed,
            "manual": prior_manual,
            "blocked": prior_blocked,
        },
        "player_evidence": {
            "passed": output_passed,
            "manual": output_manual,
            "blocked": output_blocked,
            "salary_refresh_required": int(
                evaluated["player_cba_salary_refresh_required"].sum()
            ),
            "aggregation_blocked": int(
                evaluated["package_player_cba_aggregation_blocked"].sum()
            ),
            "consent_required": int(
                evaluated["package_player_cba_consent_required"].sum()
            ),
            "trade_bonus_review": int(
                evaluated[
                    "package_player_cba_trade_bonus_review_required"
                ].sum()
            ),
            "status_counts": value_counts_map(
                evaluated, "package_player_cba_status"
            ),
        },
    }
    return checks, profile


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    try:
        import polars as pl
    except ImportError as exc:
        raise SystemExit(
            "Polars is required. Run this script in the nba-roster-optimizer "
            "environment used by the existing pipeline."
        ) from exc

    root = project_root()
    outputs = root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)

    print("=" * 88)
    print("MIXED PLAYER-AND-PICK PLAYER-CBA EVIDENCE PROPAGATION")
    print("=" * 88)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    print("[1/6] Locating and validating the 311-player decision release")
    decision_path = locate_one(root, DECISION_FILENAME)
    decisions, decision_validation = read_and_validate_decisions(
        pl, decision_path
    )
    if not decision_validation["valid"]:
        raise RuntimeError(
            "The player decision release failed validation:\n"
            + json.dumps(decision_validation, indent=2)
        )
    print(
        f"Decision release valid: {decision_validation['rows']} rows | "
        f"{decision_validation['columns']} columns"
    )

    if args.validate_decisions_only:
        print(json.dumps(decision_validation, indent=2))
        return 0

    print("[2/6] Locating the V7 team-CBA-evaluated package parquets")
    package_paths = {
        label: locate_one(root, filename)
        for label, filename in INPUT_FILES.items()
    }

    source_frames: dict[str, Any] = {}
    for label, path in package_paths.items():
        schema = pl.read_parquet_schema(str(path))
        missing = sorted(PACKAGE_REQUIRED_COLUMNS.difference(schema))
        if missing:
            raise RuntimeError(
                f"{path.name} is missing required package columns: {missing}"
            )
        preexisting = sorted(set(APPENDED_COLUMNS).intersection(schema))
        if preexisting:
            raise RuntimeError(
                f"{path.name} already contains player-CBA appended columns: "
                f"{preexisting}"
            )
        source_frames[label] = pl.read_parquet(str(path))
        print(
            f"  {label}: {source_frames[label].height:,} rows | "
            f"{source_frames[label].width:,} columns"
        )

    print("[3/6] Joining player decisions and calculating exact evidence fields")
    evaluated_frames = {
        label: evaluate_packages(pl, source, decisions)
        for label, source in source_frames.items()
    }

    print("[4/6] Validating non-destructive package propagation")
    validation_rows: list[dict[str, Any]] = []
    profiles: dict[str, Any] = {}
    for label in INPUT_FILES:
        checks, profile = validate_package(
            pl,
            label,
            source_frames[label],
            evaluated_frames[label],
            list(source_frames[label].columns),
        )
        validation_rows.extend(checks)
        profiles[label] = profile

    global_checks = [
        {
            "package_type": "global",
            "check_name": "appended_columns_unique",
            "passed": len(APPENDED_COLUMNS) == len(set(APPENDED_COLUMNS)),
            "observed": len(APPENDED_COLUMNS),
            "expected": len(set(APPENDED_COLUMNS)),
        },
        {
            "package_type": "global",
            "check_name": "decision_release_valid",
            "passed": decision_validation["valid"],
            "observed": decision_validation["valid"],
            "expected": True,
        },
    ]
    validation_rows.extend(global_checks)
    release_valid = all(row["passed"] for row in validation_rows)

    print("[5/6] Saving V8 package parquets and audit artifacts")
    output_paths = {
        label: outputs / filename for label, filename in OUTPUT_FILES.items()
    }
    if release_valid:
        for label, frame in evaluated_frames.items():
            frame.write_parquet(
                str(output_paths[label]),
                compression="zstd",
                statistics=True,
            )

    summary_rows: list[dict[str, Any]] = []
    issue_rows: list[dict[str, Any]] = []
    for label, frame in evaluated_frames.items():
        for metric, column in [
            ("player_evidence_stage_passed", "package_player_cba_stage_passed"),
            (
                "player_evidence_manual_review",
                "package_player_cba_manual_review_required",
            ),
            ("player_evidence_blocked", "package_player_cba_blocked"),
            ("salary_refresh_required", "player_cba_salary_refresh_required"),
            (
                "aggregation_blocked",
                "package_player_cba_aggregation_blocked",
            ),
            ("consent_required", "package_player_cba_consent_required"),
            (
                "trade_bonus_review",
                "package_player_cba_trade_bonus_review_required",
            ),
        ]:
            summary_rows.append(
                {
                    "package_type": label,
                    "metric": metric,
                    "count": int(frame[column].sum()),
                }
            )
        for status, count in value_counts_map(
            frame, "package_player_cba_status"
        ).items():
            issue_rows.append(
                {
                    "package_type": label,
                    "package_player_cba_status": status,
                    "count": count,
                }
            )

    write_csv(
        outputs / SUMMARY_FILENAME,
        ["package_type", "metric", "count"],
        summary_rows,
    )
    write_csv(
        outputs / ISSUE_SUMMARY_FILENAME,
        ["package_type", "package_player_cba_status", "count"],
        issue_rows,
    )
    write_csv(
        outputs / VALIDATION_FILENAME,
        ["package_type", "check_name", "passed", "observed", "expected"],
        validation_rows,
    )

    global_counts = {
        "rows": sum(frame.height for frame in evaluated_frames.values()),
        "passed": sum(
            int(frame["package_player_cba_stage_passed"].sum())
            for frame in evaluated_frames.values()
        ),
        "manual": sum(
            int(frame["package_player_cba_manual_review_required"].sum())
            for frame in evaluated_frames.values()
        ),
        "blocked": sum(
            int(frame["package_player_cba_blocked"].sum())
            for frame in evaluated_frames.values()
        ),
    }

    metadata = {
        "script_version": SCRIPT_VERSION,
        "release_name": RELEASE_NAME,
        "player_evidence_release": PLAYER_EVIDENCE_RELEASE,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "release_valid": release_valid,
        "decision_release": {
            "path": str(decision_path),
            **decision_validation,
        },
        "inputs": {label: str(path) for label, path in package_paths.items()},
        "outputs": {
            label: str(path) if path.exists() else None
            for label, path in output_paths.items()
        },
        "appended_columns": APPENDED_COLUMNS,
        "appended_column_count": len(APPENDED_COLUMNS),
        "packages": profiles,
        "global_counts": global_counts,
        "validation_checks_passed": sum(
            bool(row["passed"]) for row in validation_rows
        ),
        "validation_checks_total": len(validation_rows),
        "package_final_legal_status_released": False,
        "next_step": (
            "Run the final full-CBA package evaluator against the V8 player-CBA-"
            "evaluated parquets. Apply team apron and hard-cap rules, exact incoming "
            "salary matching, roster outcomes, trade exceptions, cash, and all "
            "transaction mechanics before releasing optimizer_package_final_legal."
        ),
    }
    write_json(outputs / METADATA_FILENAME, metadata)

    print("[6/6] Complete")
    print(
        f"Validation: {metadata['validation_checks_passed']}/"
        f"{metadata['validation_checks_total']}"
    )
    print(f"Release valid: {release_valid}")
    print(
        f"Player evidence partition: {global_counts['passed']:,} passed | "
        f"{global_counts['manual']:,} manual | "
        f"{global_counts['blocked']:,} blocked"
    )
    print("Final package legality released: False")

    if not release_valid:
        failed = [
            f"{row['package_type']}::{row['check_name']}"
            for row in validation_rows
            if not row["passed"]
        ]
        print("Failed checks:")
        for name in failed:
            print(f"  - {name}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())