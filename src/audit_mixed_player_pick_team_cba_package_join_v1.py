"""Audit the team-CBA join path for mixed player-and-pick packages.

Save this file in ``src``. It reads the two V6 right-legality-evaluated
package parquets plus the 30-team CBA decision release, validates both team
keys on every package in the 149,141-row full-CBA queue, and writes compact
metadata, field inventory, team exposure, and validation outputs.

This script is read-only with respect to package parquets. It does not append
columns, change package statuses, or release final package legality.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCRIPT_VERSION = "mixed-player-pick-team-cba-package-join-audit-v1-2026-08-05"
RELEASE_NAME = "mixed_player_pick_team_cba_package_join_audit_2026_27_v1"

DECISION_FILENAME = "mixed_player_pick_team_cba_decision_release_v1.csv"
PACKAGE_FILES = {
    "one_for_one": "one_for_one_mixed_player_pick_candidates_2026_27_v6_right_legality_evaluated.parquet",
    "two_for_one": "two_for_one_mixed_player_pick_candidates_2026_27_v6_right_legality_evaluated.parquet",
}
EXPECTED_PACKAGE_ROWS = {"one_for_one": 28_324, "two_for_one": 282_277}
EXPECTED_PACKAGE_COLUMNS = {"one_for_one": 95, "two_for_one": 93}
EXPECTED_QUEUE_ROWS = {"one_for_one": 20_797, "two_for_one": 128_344}
EXPECTED_QUEUE_TOTAL = 149_141
EXPECTED_EXPOSURES = 298_282
EXPECTED_TEAMS = {
    "ATL", "BKN", "BOS", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
}
EXPECTED_MANUAL_TEAMS = {"CHA", "IND", "LAL", "MEM", "MIN", "SAS"}

METADATA_OUTPUT = "mixed_player_pick_team_cba_package_join_audit_metadata_v1.json"
FIELD_OUTPUT = "mixed_player_pick_team_cba_package_join_field_inventory_v1.csv"
EXPOSURE_OUTPUT = "mixed_player_pick_team_cba_package_join_team_exposure_v1.csv"
VALIDATION_OUTPUT = "mixed_player_pick_team_cba_package_join_validation_v1.csv"

PACKAGE_REQUIRED_COLUMNS = {
    "optimizer_candidate_id",
    "team_a",
    "team_b",
    "side_a_player_ids",
    "side_b_player_ids",
    "side_a_player_trade_salary",
    "side_b_player_trade_salary",
    "base_salary_precheck_passed",
    "base_final_trade_legality_verified",
    "pick_trade_date_legality_verified",
    "package_right_legality_stage_passed",
    "package_right_legality_manual_review_required",
    "package_right_legality_blocked",
    "package_right_legality_status",
    "optimizer_package_final_legal",
}

DECISION_REQUIRED_COLUMNS = {
    "team_cba_decision_release",
    "team_abbreviation",
    "team_cba_batch_id",
    "team_cba_priority_rank",
    "evidence_as_of_date",
    "modeled_trade_date",
    "league_year",
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
    "team_cba_evidence_determination",
    "team_cba_manual_review_required",
    "team_cba_stage_pass",
    "team_cba_stage_status",
    "team_cba_final_legal_status_released",
    "team_salary_source_url",
    "transaction_source_url",
    "researcher_notes",
}

PACKAGE_READ_COLUMNS = sorted(PACKAGE_REQUIRED_COLUMNS)


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
        raise FileNotFoundError(
            f"Could not find {filename} beneath {root}. Keep the exact filename in outputs."
        )
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


def safe_int(value: Any) -> int | None:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def normalized_team(value: Any) -> str:
    return "" if value is None else str(value).strip().upper()


def pure_team_join_status(
    team_a_found: bool,
    team_b_found: bool,
    team_a_pass: bool,
    team_b_pass: bool,
    team_a_manual: bool,
    team_b_manual: bool,
) -> str:
    if not team_a_found or not team_b_found:
        return "team_cba_decision_unmatched_internal_review"
    if team_a_manual or team_b_manual:
        return "team_cba_manual_review_required"
    if team_a_pass and team_b_pass:
        return "team_cba_evidence_passed_remaining_package_cba_validation"
    return "team_cba_inconsistent_decision_internal_review"


def classify_field(column: str) -> tuple[str, str, bool, str]:
    lowered = column.lower()
    exact_roles = {
        "team_a": ("package_team_key", "a", True, "Join to team decision release"),
        "team_b": ("package_team_key", "b", True, "Join to team decision release"),
        "side_a_player_ids": ("package_player_identity", "a", False, "Player restriction join input"),
        "side_b_player_ids": ("package_player_identity", "b", False, "Player restriction join input"),
        "side_a_player_trade_salary": ("package_trade_salary", "a", True, "Team A outgoing and Team B incoming salary input"),
        "side_b_player_trade_salary": ("package_trade_salary", "b", True, "Team B outgoing and Team A incoming salary input"),
        "base_salary_precheck_passed": ("package_salary_precheck", "both", True, "Existing preliminary salary screen"),
        "package_right_legality_stage_passed": ("queue_gate", "package", True, "Defines the 149,141-row full-CBA queue"),
        "optimizer_package_final_legal": ("final_release_guard", "package", True, "Must remain false during audit"),
    }
    if lowered in exact_roles:
        return exact_roles[lowered]
    if lowered.startswith("package_right_legality_"):
        return "prior_stage_status", "package", False, "Preserved right-evidence status"
    if any(token in lowered for token in ("apron", "hard_cap", "roster_count", "team_salary", "cap_room")):
        return "possible_team_cba_field", "unknown", False, "Review whether package-native or evidence-join field"
    if "salary" in lowered:
        return "other_salary_field", "unknown", False, "Salary-related package field"
    return "other_existing_field", "", False, "Preserved existing package field"


def read_decisions(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    return headers, rows


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def value_counts_map(frame: Any, column: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in frame.group_by(column).len().to_dicts():
        key = "<null>" if row[column] is None else str(row[column])
        counts[key] = int(row["len"])
    return dict(sorted(counts.items()))


def run_self_tests() -> None:
    assert pure_team_join_status(True, True, True, True, False, False).startswith("team_cba_evidence_passed")
    assert pure_team_join_status(True, True, True, False, False, True) == "team_cba_manual_review_required"
    assert pure_team_join_status(False, True, False, True, False, False) == "team_cba_decision_unmatched_internal_review"
    assert pure_team_join_status(True, True, False, False, False, False) == "team_cba_inconsistent_decision_internal_review"
    assert classify_field("team_a")[:3] == ("package_team_key", "a", True)
    assert classify_field("side_b_player_trade_salary")[:3] == ("package_trade_salary", "b", True)
    assert normalized_bool("True") is True
    assert normalized_bool("false") is False
    assert normalized_bool("unknown") is None
    assert safe_int("30.0") == 30
    assert normalized_team(" nop ") == "NOP"


def require_polars() -> Any:
    try:
        import polars as pl  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Polars is required to inspect the package parquets. Run this script in the "
            "nba-roster-optimizer environment used by the existing package pipeline."
        ) from exc
    return pl


def main() -> int:
    args = parse_args()
    if args.self_test:
        run_self_tests()
        print("Self-tests passed: 11/11")
        return 0

    pl = require_polars()
    root = project_root()
    outputs = root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)

    print("[1/6] Locating team decision release and V6 package parquets")
    decision_path = locate_one(root, DECISION_FILENAME)
    package_paths = {label: locate_one(root, filename) for label, filename in PACKAGE_FILES.items()}

    print("[2/6] Validating the 30-team decision release")
    decision_headers, decision_rows = read_decisions(decision_path)
    missing_decision_columns = sorted(DECISION_REQUIRED_COLUMNS.difference(decision_headers))
    decision_teams = [normalized_team(row.get("team_abbreviation")) for row in decision_rows]
    decision_team_set = set(decision_teams)
    determination_counts = Counter(row.get("team_cba_evidence_determination", "") for row in decision_rows)
    manual_teams = {
        normalized_team(row.get("team_abbreviation"))
        for row in decision_rows
        if normalized_bool(row.get("team_cba_manual_review_required")) is True
    }
    decision_map = {
        normalized_team(row.get("team_abbreviation")): {
            **row,
            "stage_pass_bool": normalized_bool(row.get("team_cba_stage_pass")) is True,
            "manual_bool": normalized_bool(row.get("team_cba_manual_review_required")) is True,
        }
        for row in decision_rows
    }

    field_rows: list[dict[str, Any]] = []
    for ordinal, column in enumerate(decision_headers, start=1):
        role = "decision_join_key" if column == "team_abbreviation" else (
            "decision_stage_status" if column.startswith("team_cba_") else (
                "verified_team_financial" if column.startswith("verified_") else "decision_evidence_field"
            )
        )
        field_rows.append({
            "dataset": "team_decision_release",
            "column_ordinal": ordinal,
            "column_name": column,
            "dtype": "csv_text",
            "field_role": role,
            "package_side": "team" if column == "team_abbreviation" else "",
            "needed_for_team_join": column in DECISION_REQUIRED_COLUMNS,
            "notes": "Package-ready 30-team evidence decision field",
        })

    print("[3/6] Profiling package schemas and the full-CBA queue")
    package_reports: dict[str, dict[str, Any]] = {}
    exposure_by_label: dict[str, Counter[str]] = {}
    combined_join_status = Counter()
    combined_teams: set[str] = set()
    combined_queue_rows = 0
    combined_exposures = 0
    for label, path in package_paths.items():
        schema = pl.read_parquet_schema(str(path))
        missing_package_columns = sorted(PACKAGE_REQUIRED_COLUMNS.difference(schema))
        if missing_package_columns:
            raise RuntimeError(f"{label} is missing required V6 columns: {missing_package_columns}")
        for ordinal, (column, dtype) in enumerate(schema.items(), start=1):
            role, side, needed, notes = classify_field(column)
            field_rows.append({
                "dataset": label,
                "column_ordinal": ordinal,
                "column_name": column,
                "dtype": str(dtype),
                "field_role": role,
                "package_side": side,
                "needed_for_team_join": needed,
                "notes": notes,
            })

        frame = pl.read_parquet(str(path), columns=PACKAGE_READ_COLUMNS)
        queue = frame.filter(pl.col("package_right_legality_stage_passed") == True)  # noqa: E712
        exposures: Counter[str] = Counter()
        join_status_counts: Counter[str] = Counter()
        queue_teams: set[str] = set()
        null_team_keys = 0
        for team_a_raw, team_b_raw in queue.select(["team_a", "team_b"]).iter_rows():
            team_a = normalized_team(team_a_raw)
            team_b = normalized_team(team_b_raw)
            if not team_a or not team_b:
                null_team_keys += 1
            if team_a:
                exposures[team_a] += 1
                queue_teams.add(team_a)
            if team_b:
                exposures[team_b] += 1
                queue_teams.add(team_b)
            decision_a = decision_map.get(team_a)
            decision_b = decision_map.get(team_b)
            status = pure_team_join_status(
                decision_a is not None,
                decision_b is not None,
                bool(decision_a and decision_a["stage_pass_bool"]),
                bool(decision_b and decision_b["stage_pass_bool"]),
                bool(decision_a and decision_a["manual_bool"]),
                bool(decision_b and decision_b["manual_bool"]),
            )
            join_status_counts[status] += 1

        salary_nulls = {
            column: int(queue.get_column(column).null_count())
            for column in ("side_a_player_trade_salary", "side_b_player_trade_salary")
        }
        final_legal_count = int(
            queue.get_column("optimizer_package_final_legal")
            .fill_null(False)
            .cast(pl.Int64)
            .sum()
        )
        report = {
            "label": label,
            "path": str(path),
            "rows": frame.height,
            "columns": len(schema),
            "expected_rows": EXPECTED_PACKAGE_ROWS[label],
            "expected_columns": EXPECTED_PACKAGE_COLUMNS[label],
            "missing_required_columns": missing_package_columns,
            "queue_rows": queue.height,
            "expected_queue_rows": EXPECTED_QUEUE_ROWS[label],
            "queue_teams": sorted(queue_teams),
            "queue_team_count": len(queue_teams),
            "queue_team_keys_missing": null_team_keys,
            "queue_salary_null_counts": salary_nulls,
            "queue_base_salary_precheck_counts": value_counts_map(queue, "base_salary_precheck_passed"),
            "queue_team_join_status_counts": dict(sorted(join_status_counts.items())),
            "queue_final_legal_count": final_legal_count,
            "queue_team_exposures": dict(sorted(exposures.items())),
        }
        package_reports[label] = report
        exposure_by_label[label] = exposures
        combined_join_status.update(join_status_counts)
        combined_teams.update(queue_teams)
        combined_queue_rows += queue.height
        combined_exposures += sum(exposures.values())

    print("[4/6] Building team exposure and validation outputs")
    exposure_rows: list[dict[str, Any]] = []
    for team in sorted(EXPECTED_TEAMS):
        decision = decision_map.get(team, {})
        one = exposure_by_label["one_for_one"].get(team, 0)
        two = exposure_by_label["two_for_one"].get(team, 0)
        exposure_rows.append({
            "team_abbreviation": team,
            "team_cba_evidence_determination": decision.get("team_cba_evidence_determination", ""),
            "team_cba_manual_review_required": decision.get("team_cba_manual_review_required", ""),
            "team_cba_stage_pass": decision.get("team_cba_stage_pass", ""),
            "hard_cap_active": decision.get("hard_cap_active", ""),
            "hard_cap_level": decision.get("hard_cap_level", ""),
            "verified_apron_team_salary_value": decision.get("verified_apron_team_salary_value", ""),
            "one_for_one_queue_exposure": one,
            "two_for_one_queue_exposure": two,
            "total_queue_exposure": one + two,
        })

    checks: list[dict[str, Any]] = []

    def add(check: str, passed: bool, observed: Any, expected: Any) -> None:
        checks.append({"check_name": check, "passed": bool(passed), "observed": observed, "expected": expected})

    add("decision_columns_complete", not missing_decision_columns, "|".join(missing_decision_columns), "none")
    add("decision_column_count_is_31", len(decision_headers) == 31, len(decision_headers), 31)
    add("decision_row_count_is_30", len(decision_rows) == 30, len(decision_rows), 30)
    add("decision_teams_unique", len(decision_team_set) == len(decision_teams), len(decision_team_set), 30)
    add("decision_team_set_exact", decision_team_set == EXPECTED_TEAMS, "|".join(sorted(decision_team_set)), "30 NBA teams")
    add("decision_counts_are_24_and_6", determination_counts == Counter({"verified_with_conditions": 24, "manual_review_required": 6}), dict(determination_counts), {"verified_with_conditions": 24, "manual_review_required": 6})
    add("manual_team_set_exact", manual_teams == EXPECTED_MANUAL_TEAMS, "|".join(sorted(manual_teams)), "|".join(sorted(EXPECTED_MANUAL_TEAMS)))
    add("decision_dates_are_2026_08_04", all(row.get("evidence_as_of_date") == "2026-08-04" and row.get("modeled_trade_date") == "2026-08-04" for row in decision_rows), sorted({(row.get("evidence_as_of_date"), row.get("modeled_trade_date")) for row in decision_rows}), "2026-08-04")
    add("decision_stage_flags_consistent", all((normalized_bool(row.get("team_cba_stage_pass")) is True) == (row.get("team_cba_evidence_determination") == "verified_with_conditions") for row in decision_rows), "checked", True)
    add("decision_final_legal_unreleased", all(normalized_bool(row.get("team_cba_final_legal_status_released")) is False for row in decision_rows), "checked", False)
    add("one_for_one_rows_match", package_reports["one_for_one"]["rows"] == EXPECTED_PACKAGE_ROWS["one_for_one"], package_reports["one_for_one"]["rows"], EXPECTED_PACKAGE_ROWS["one_for_one"])
    add("two_for_one_rows_match", package_reports["two_for_one"]["rows"] == EXPECTED_PACKAGE_ROWS["two_for_one"], package_reports["two_for_one"]["rows"], EXPECTED_PACKAGE_ROWS["two_for_one"])
    add("one_for_one_columns_match", package_reports["one_for_one"]["columns"] == EXPECTED_PACKAGE_COLUMNS["one_for_one"], package_reports["one_for_one"]["columns"], EXPECTED_PACKAGE_COLUMNS["one_for_one"])
    add("two_for_one_columns_match", package_reports["two_for_one"]["columns"] == EXPECTED_PACKAGE_COLUMNS["two_for_one"], package_reports["two_for_one"]["columns"], EXPECTED_PACKAGE_COLUMNS["two_for_one"])
    add("one_for_one_required_columns_present", not package_reports["one_for_one"]["missing_required_columns"], package_reports["one_for_one"]["missing_required_columns"], "none")
    add("two_for_one_required_columns_present", not package_reports["two_for_one"]["missing_required_columns"], package_reports["two_for_one"]["missing_required_columns"], "none")
    add("one_for_one_queue_count_matches", package_reports["one_for_one"]["queue_rows"] == EXPECTED_QUEUE_ROWS["one_for_one"], package_reports["one_for_one"]["queue_rows"], EXPECTED_QUEUE_ROWS["one_for_one"])
    add("two_for_one_queue_count_matches", package_reports["two_for_one"]["queue_rows"] == EXPECTED_QUEUE_ROWS["two_for_one"], package_reports["two_for_one"]["queue_rows"], EXPECTED_QUEUE_ROWS["two_for_one"])
    add("combined_queue_count_is_149141", combined_queue_rows == EXPECTED_QUEUE_TOTAL, combined_queue_rows, EXPECTED_QUEUE_TOTAL)
    add("combined_team_exposures_is_298282", combined_exposures == EXPECTED_EXPOSURES, combined_exposures, EXPECTED_EXPOSURES)
    add("queue_team_set_is_30_teams", combined_teams == EXPECTED_TEAMS, "|".join(sorted(combined_teams)), "30 NBA teams")
    add("queue_teams_all_match_decisions", combined_teams.issubset(decision_team_set), "|".join(sorted(combined_teams - decision_team_set)), "none")
    add("one_for_one_team_keys_nonnull", package_reports["one_for_one"]["queue_team_keys_missing"] == 0, package_reports["one_for_one"]["queue_team_keys_missing"], 0)
    add("two_for_one_team_keys_nonnull", package_reports["two_for_one"]["queue_team_keys_missing"] == 0, package_reports["two_for_one"]["queue_team_keys_missing"], 0)
    add("one_for_one_trade_salaries_nonnull", sum(package_reports["one_for_one"]["queue_salary_null_counts"].values()) == 0, package_reports["one_for_one"]["queue_salary_null_counts"], 0)
    add("two_for_one_trade_salaries_nonnull", sum(package_reports["two_for_one"]["queue_salary_null_counts"].values()) == 0, package_reports["two_for_one"]["queue_salary_null_counts"], 0)
    add("one_for_one_base_precheck_true", package_reports["one_for_one"]["queue_base_salary_precheck_counts"] == {"True": EXPECTED_QUEUE_ROWS["one_for_one"]}, package_reports["one_for_one"]["queue_base_salary_precheck_counts"], {"True": EXPECTED_QUEUE_ROWS["one_for_one"]})
    add("two_for_one_base_precheck_true", package_reports["two_for_one"]["queue_base_salary_precheck_counts"] == {"True": EXPECTED_QUEUE_ROWS["two_for_one"]}, package_reports["two_for_one"]["queue_base_salary_precheck_counts"], {"True": EXPECTED_QUEUE_ROWS["two_for_one"]})
    add("all_queue_packages_receive_team_status", sum(combined_join_status.values()) == EXPECTED_QUEUE_TOTAL, sum(combined_join_status.values()), EXPECTED_QUEUE_TOTAL)
    add("no_unmatched_team_decisions", combined_join_status.get("team_cba_decision_unmatched_internal_review", 0) == 0, combined_join_status.get("team_cba_decision_unmatched_internal_review", 0), 0)
    add("queue_final_legal_still_zero", sum(report["queue_final_legal_count"] for report in package_reports.values()) == 0, sum(report["queue_final_legal_count"] for report in package_reports.values()), 0)
    add("team_exposure_rows_is_30", len(exposure_rows) == 30, len(exposure_rows), 30)

    failed = [row for row in checks if not row["passed"]]
    audit_valid = not failed

    metadata = {
        "release": RELEASE_NAME,
        "script_version": SCRIPT_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "non_destructive": True,
        "decision_file": str(decision_path),
        "decision_rows": len(decision_rows),
        "decision_columns": len(decision_headers),
        "decision_determination_counts": dict(sorted(determination_counts.items())),
        "manual_review_teams": sorted(manual_teams),
        "package_reports": package_reports,
        "combined_queue_rows": combined_queue_rows,
        "combined_team_exposures": combined_exposures,
        "combined_queue_teams": sorted(combined_teams),
        "combined_team_join_status_counts": dict(sorted(combined_join_status.items())),
        "validation_checks_passed": len(checks) - len(failed),
        "validation_checks_total": len(checks),
        "audit_valid": audit_valid,
        "package_final_legal_status_released": False,
        "next_step": (
            "Use this audit to build a non-destructive team-CBA propagator. Join the team decision "
            "release twice, once through team_a and once through team_b, and retain package final "
            "legality as false pending player restrictions and exact post-trade CBA evaluation."
        ),
        "outputs": {
            "field_inventory": str(outputs / FIELD_OUTPUT),
            "team_exposure": str(outputs / EXPOSURE_OUTPUT),
            "validation": str(outputs / VALIDATION_OUTPUT),
        },
    }

    print("[5/6] Saving compact audit outputs")
    with (outputs / METADATA_OUTPUT).open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, sort_keys=False)
        handle.write("\n")
    write_csv(
        outputs / FIELD_OUTPUT,
        ["dataset", "column_ordinal", "column_name", "dtype", "field_role", "package_side", "needed_for_team_join", "notes"],
        field_rows,
    )
    write_csv(
        outputs / EXPOSURE_OUTPUT,
        [
            "team_abbreviation", "team_cba_evidence_determination", "team_cba_manual_review_required",
            "team_cba_stage_pass", "hard_cap_active", "hard_cap_level",
            "verified_apron_team_salary_value", "one_for_one_queue_exposure",
            "two_for_one_queue_exposure", "total_queue_exposure",
        ],
        exposure_rows,
    )
    write_csv(outputs / VALIDATION_OUTPUT, ["check_name", "passed", "observed", "expected"], checks)

    print("[6/6] Team-CBA package join audit complete")
    print()
    print("=" * 80)
    print("TEAM CBA PACKAGE JOIN AUDIT COMPLETE")
    print("=" * 80)
    print(f"Packages audited: {sum(report['rows'] for report in package_reports.values()):,}")
    print(f"Full-CBA queue: {combined_queue_rows:,}")
    print(f"Team-package exposures: {combined_exposures:,}")
    print(f"Team-evidence pass queue: {combined_join_status.get('team_cba_evidence_passed_remaining_package_cba_validation', 0):,}")
    print(f"Team manual-review queue: {combined_join_status.get('team_cba_manual_review_required', 0):,}")
    print(f"Unmatched team decisions: {combined_join_status.get('team_cba_decision_unmatched_internal_review', 0):,}")
    print(f"Validation checks passed: {len(checks) - len(failed)}/{len(checks)}")
    print(f"Audit valid: {audit_valid}")
    print("Final package legality released: False")
    print()
    print("NEXT REVIEW FILES")
    print(outputs / METADATA_OUTPUT)
    print(outputs / EXPOSURE_OUTPUT)
    print()
    print("SAVED FILES")
    for filename in (METADATA_OUTPUT, FIELD_OUTPUT, EXPOSURE_OUTPUT, VALIDATION_OUTPUT):
        print(outputs / filename)

    return 0 if audit_valid else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise