"""Build prioritized team-level full-CBA research packets.

Save this file in ``src``. It reads the validated 30-team source coverage file,
the full-CBA source-coverage metadata, and the two V6 package parquets. It
measures each team's exposure within the 149,141-package review queue, ranks
teams by apron risk and package impact, and writes three 10-row research batches.

The script is non-destructive. Evidence fields start blank and final package
legality remains unreleased.
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
from typing import Any, Iterable


SCRIPT_VERSION = "mixed-player-pick-team-cba-research-packets-v1-2026-08-05"
RELEASE_NAME = "mixed_player_pick_team_cba_research_2026_27_v1"
TRADE_DATE = "2026-08-04"
LEAGUE_YEAR = "2026-27"

SOURCE_COVERAGE_METADATA = "mixed_player_pick_full_cba_source_coverage_metadata_v1.json"
TEAM_COVERAGE_FILENAME = "mixed_player_pick_full_cba_team_source_coverage_v1.csv"
PACKAGE_FILES = {
    "one_for_one": "one_for_one_mixed_player_pick_candidates_2026_27_v6_right_legality_evaluated.parquet",
    "two_for_one": "two_for_one_mixed_player_pick_candidates_2026_27_v6_right_legality_evaluated.parquet",
}
EXPECTED_PACKAGE_ROWS = {"one_for_one": 28_324, "two_for_one": 282_277}
EXPECTED_PASSED_ROWS = {"one_for_one": 20_797, "two_for_one": 128_344}
EXPECTED_QUEUE_PACKAGES = 149_141
EXPECTED_TEAMS = 30
BATCH_SIZE = 10

BATCH_DIRECTORY = "team_cba_research_batches"
QUEUE_OUTPUT = "mixed_player_pick_team_cba_research_queue_v1.csv"
SUMMARY_OUTPUT = "mixed_player_pick_team_cba_research_priority_summary_v1.csv"
READINESS_OUTPUT = "mixed_player_pick_team_cba_research_readiness_v1.csv"
METADATA_OUTPUT = "mixed_player_pick_team_cba_research_metadata_v1.json"

PACKET_COLUMNS = [
    "team_cba_research_release",
    "team_cba_batch_id",
    "team_cba_row_in_batch",
    "team_cba_priority_rank",
    "team_cba_risk_rank",
    "team_cba_risk_reason",
    "one_for_one_passing_package_exposure",
    "two_for_one_passing_package_exposure",
    "total_passing_package_exposure",
    "closest_proxy_threshold_distance",
    "modeled_trade_date",
    "league_year",
]

EVIDENCE_COLUMNS = [
    "research_status",
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
    "post_trade_roster_limit_rule",
    "transaction_history_reviewed",
    "sign_and_trade_receipt_allowed",
    "trade_exception_use_allowed",
    "cash_consideration_allowed",
    "team_salary_source_url",
    "roster_source_url",
    "transaction_source_url",
    "source_authority_tier",
    "source_notes",
    "team_cba_evidence_determination",
    "team_cba_manual_review_required",
    "researcher_notes",
]

RISK_ORDER = {
    "above_second_apron_proxy": 1,
    "between_aprons_proxy": 2,
    "tax_to_first_apron_proxy": 3,
    "over_cap_below_tax_proxy": 4,
    "below_cap_proxy": 5,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="Project root override.")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run dependency-free helper tests without reading project files.",
    )
    return parser.parse_args()


def project_root(override: Path | None = None) -> Path:
    if override is not None:
        return override.resolve()
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


def parse_float(value: Any) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalized_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in {"true", "1", "yes", "y"}:
        return True
    if lowered in {"false", "0", "no", "n"}:
        return False
    return None


def risk_rank(tier: str) -> int:
    return RISK_ORDER.get(str(tier).strip(), 99)


def closest_threshold_distance(row: dict[str, Any]) -> float:
    values = [
        abs(number)
        for number in (
            parse_float(row.get("salary_cap_room_proxy")),
            parse_float(row.get("distance_to_first_apron_proxy")),
            parse_float(row.get("distance_to_second_apron_proxy")),
        )
        if number is not None
    ]
    return min(values) if values else math.inf


def risk_reason(row: dict[str, Any]) -> str:
    tier = str(row.get("salary_proxy_tier", "")).strip()
    distance = closest_threshold_distance(row)
    if tier == "above_second_apron_proxy":
        return "proxy_above_second_apron_highest_restriction_risk"
    if tier == "between_aprons_proxy":
        return "proxy_between_aprons_second_apron_boundary_relevant"
    if tier == "tax_to_first_apron_proxy":
        return "proxy_tax_to_first_apron_first_apron_boundary_relevant"
    if tier == "over_cap_below_tax_proxy":
        return "proxy_over_cap_salary_matching_required"
    if tier == "below_cap_proxy":
        return "proxy_below_cap_room_exception_path_relevant"
    if math.isfinite(distance):
        return "unclassified_proxy_tier_threshold_review_required"
    return "missing_proxy_tier_manual_priority"


def profile_package_exposure(pl: Any, path: Path) -> tuple[int, int, dict[str, int]]:
    frame = pl.read_parquet(
        str(path),
        columns=["package_right_legality_stage_passed", "team_a", "team_b"],
    )
    passed = frame.filter(pl.col("package_right_legality_stage_passed") == True)  # noqa: E712
    exposure: Counter[str] = Counter()
    for column in ("team_a", "team_b"):
        exposure.update(str(value) for value in passed.get_column(column).drop_nulls().to_list())
    return frame.height, passed.height, dict(sorted(exposure.items()))


def batch_id(index: int) -> str:
    return f"TCBA-T{index:02d}"


def build_queue(
    source_headers: list[str],
    source_rows: list[dict[str, str]],
    exposures: dict[str, dict[str, int]],
) -> list[dict[str, Any]]:
    ranked_rows: list[dict[str, Any]] = []
    for source_row in source_rows:
        team = str(source_row.get("team_abbreviation", "")).strip()
        one_count = int(exposures["one_for_one"].get(team, 0))
        two_count = int(exposures["two_for_one"].get(team, 0))
        distance = closest_threshold_distance(source_row)
        ranked_rows.append(
            {
                "source_row": source_row,
                "team": team,
                "one_count": one_count,
                "two_count": two_count,
                "total_count": one_count + two_count,
                "risk_rank": risk_rank(source_row.get("salary_proxy_tier", "")),
                "risk_reason": risk_reason(source_row),
                "distance": distance,
            }
        )
    ranked_rows.sort(
        key=lambda item: (
            item["risk_rank"],
            item["distance"],
            -item["total_count"],
            item["team"],
        )
    )

    queue: list[dict[str, Any]] = []
    for priority_rank, item in enumerate(ranked_rows, start=1):
        batch_number = (priority_rank - 1) // BATCH_SIZE + 1
        row_in_batch = (priority_rank - 1) % BATCH_SIZE + 1
        packet: dict[str, Any] = {
            "team_cba_research_release": RELEASE_NAME,
            "team_cba_batch_id": batch_id(batch_number),
            "team_cba_row_in_batch": row_in_batch,
            "team_cba_priority_rank": priority_rank,
            "team_cba_risk_rank": item["risk_rank"],
            "team_cba_risk_reason": item["risk_reason"],
            "one_for_one_passing_package_exposure": item["one_count"],
            "two_for_one_passing_package_exposure": item["two_count"],
            "total_passing_package_exposure": item["total_count"],
            "closest_proxy_threshold_distance": "" if not math.isfinite(item["distance"]) else item["distance"],
            "modeled_trade_date": TRADE_DATE,
            "league_year": LEAGUE_YEAR,
        }
        packet.update({header: item["source_row"].get(header, "") for header in source_headers})
        packet.update({column: "" for column in EVIDENCE_COLUMNS})
        queue.append(packet)
    return queue


def validate_release(
    metadata: dict[str, Any],
    source_headers: list[str],
    source_rows: list[dict[str, str]],
    package_profiles: dict[str, dict[str, Any]],
    queue: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, observed: Any, expected: Any) -> None:
        checks.append(
            {
                "check_name": name,
                "passed": bool(passed),
                "observed": json.dumps(safe_json(observed), sort_keys=True),
                "expected": json.dumps(safe_json(expected), sort_keys=True),
            }
        )

    add("source_coverage_audit_valid", metadata.get("audit_valid") is True,
        metadata.get("audit_valid"), True)
    add("source_coverage_integrity_14_of_14",
        metadata.get("integrity_checks_passed") == 14
        and metadata.get("integrity_checks_total") == 14,
        [metadata.get("integrity_checks_passed"), metadata.get("integrity_checks_total")], [14, 14])
    add("source_queue_149141", metadata.get("queue", {}).get("packages") == EXPECTED_QUEUE_PACKAGES,
        metadata.get("queue", {}).get("packages"), EXPECTED_QUEUE_PACKAGES)
    add("source_team_rows_30", len(source_rows) == EXPECTED_TEAMS, len(source_rows), EXPECTED_TEAMS)
    teams = [row.get("team_abbreviation", "") for row in source_rows]
    add("source_team_ids_complete_unique", len(set(teams)) == EXPECTED_TEAMS and all(teams),
        len(set(teams)), EXPECTED_TEAMS)
    add("source_headers_preserved", all(header in queue[0] for header in source_headers),
        [header for header in source_headers if header not in queue[0]], [])
    add("all_source_team_salaries_unverified",
        all(normalized_bool(row.get("official_team_salary_verified")) is False for row in source_rows),
        Counter(row.get("official_team_salary_verified", "") for row in source_rows), {"False": 30})
    for label, profile in package_profiles.items():
        add(f"{label}_rows", profile["rows"] == EXPECTED_PACKAGE_ROWS[label],
            profile["rows"], EXPECTED_PACKAGE_ROWS[label])
        add(f"{label}_passed_rows", profile["passed_rows"] == EXPECTED_PASSED_ROWS[label],
            profile["passed_rows"], EXPECTED_PASSED_ROWS[label])
        add(f"{label}_exposure_sum",
            sum(profile["exposures"].values()) == 2 * EXPECTED_PASSED_ROWS[label],
            sum(profile["exposures"].values()), 2 * EXPECTED_PASSED_ROWS[label])
        add(f"{label}_all_30_teams_exposed", len(profile["exposures"]) == EXPECTED_TEAMS,
            len(profile["exposures"]), EXPECTED_TEAMS)
    add("queue_rows_30", len(queue) == EXPECTED_TEAMS, len(queue), EXPECTED_TEAMS)
    queue_teams = [row["team_abbreviation"] for row in queue]
    add("queue_teams_unique", len(set(queue_teams)) == EXPECTED_TEAMS,
        len(set(queue_teams)), EXPECTED_TEAMS)
    batch_counts = Counter(row["team_cba_batch_id"] for row in queue)
    add("three_batches", len(batch_counts) == 3, len(batch_counts), 3)
    add("batch_sizes_10", sorted(batch_counts.values()) == [10, 10, 10],
        dict(sorted(batch_counts.items())), {batch_id(index): 10 for index in range(1, 4)})
    add("priority_ranks_complete", sorted(row["team_cba_priority_rank"] for row in queue) == list(range(1, 31)),
        sorted(row["team_cba_priority_rank"] for row in queue), list(range(1, 31)))
    add("evidence_fields_blank",
        all(not str(row[column]).strip() for row in queue for column in EVIDENCE_COLUMNS),
        sum(bool(str(row[column]).strip()) for row in queue for column in EVIDENCE_COLUMNS), 0)
    add("all_teams_have_package_exposure",
        all(int(row["total_passing_package_exposure"]) > 0 for row in queue),
        sum(int(row["total_passing_package_exposure"]) > 0 for row in queue), EXPECTED_TEAMS)
    add("highest_risk_tier_first",
        queue[0].get("salary_proxy_tier") == "above_second_apron_proxy",
        queue[0].get("salary_proxy_tier"), "above_second_apron_proxy")
    return checks


def run_self_tests() -> None:
    assert parse_float("12.5") == 12.5
    assert parse_float("") is None
    assert normalized_bool("False") is False
    assert risk_rank("above_second_apron_proxy") < risk_rank("below_cap_proxy")
    row = {
        "salary_cap_room_proxy": "-10",
        "distance_to_first_apron_proxy": "5",
        "distance_to_second_apron_proxy": "20",
    }
    assert closest_threshold_distance(row) == 5
    assert batch_id(1) == "TCBA-T01"
    print("Self-tests passed: 6/6")


def main() -> int:
    args = parse_args()
    if args.self_test:
        run_self_tests()
        return 0

    try:
        import polars as pl
    except ImportError as exc:
        raise RuntimeError(
            "Polars is required. Run this script in the nba-roster-optimizer environment."
        ) from exc

    root = project_root(args.root)
    outputs = root / "outputs"
    batch_dir = outputs / BATCH_DIRECTORY
    batch_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("MIXED PLAYER-AND-PICK TEAM CBA RESEARCH PACKETS")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print(f"Release name: {RELEASE_NAME}")
    print(f"Trade date: {TRADE_DATE}")
    print()

    print("[1/6] Loading source coverage, team profiles, and V6 packages")
    metadata_path = locate_one(root, SOURCE_COVERAGE_METADATA)
    with metadata_path.open("r", encoding="utf-8-sig") as handle:
        source_metadata = json.load(handle)
    team_path = locate_one(root, TEAM_COVERAGE_FILENAME)
    source_headers, source_rows = read_csv(team_path)
    package_paths = {label: locate_one(root, filename) for label, filename in PACKAGE_FILES.items()}

    print("[2/6] Measuring team exposure in the 149,141-package queue")
    package_profiles: dict[str, dict[str, Any]] = {}
    exposures: dict[str, dict[str, int]] = {}
    for label, path in package_paths.items():
        rows, passed_rows, exposure = profile_package_exposure(pl, path)
        exposures[label] = exposure
        package_profiles[label] = {
            "path": str(path),
            "rows": rows,
            "passed_rows": passed_rows,
            "exposures": exposure,
        }

    print("[3/6] Ranking teams by apron risk, threshold proximity, and package impact")
    queue = build_queue(source_headers, source_rows, exposures)
    output_headers = PACKET_COLUMNS + source_headers + EVIDENCE_COLUMNS

    print("[4/6] Writing three 10-team evidence batches")
    batch_paths: list[Path] = []
    for batch_number in range(1, 4):
        current_id = batch_id(batch_number)
        batch_rows = [row for row in queue if row["team_cba_batch_id"] == current_id]
        batch_path = batch_dir / f"mixed_player_pick_team_cba_t{batch_number:02d}_evidence_input_v1.csv"
        write_csv(batch_path, output_headers, batch_rows)
        batch_paths.append(batch_path)

    print("[5/6] Validating research release readiness")
    validation_rows = validate_release(
        source_metadata,
        source_headers,
        source_rows,
        package_profiles,
        queue,
    )
    release_valid = all(row["passed"] for row in validation_rows)
    checks_passed = sum(row["passed"] for row in validation_rows)

    summary_rows: list[dict[str, Any]] = []
    for row in queue:
        summary_rows.append(
            {
                "team_cba_priority_rank": row["team_cba_priority_rank"],
                "team_cba_batch_id": row["team_cba_batch_id"],
                "team_abbreviation": row["team_abbreviation"],
                "salary_proxy_tier": row["salary_proxy_tier"],
                "team_cba_risk_reason": row["team_cba_risk_reason"],
                "closest_proxy_threshold_distance": row["closest_proxy_threshold_distance"],
                "one_for_one_passing_package_exposure": row["one_for_one_passing_package_exposure"],
                "two_for_one_passing_package_exposure": row["two_for_one_passing_package_exposure"],
                "total_passing_package_exposure": row["total_passing_package_exposure"],
            }
        )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "release_name": RELEASE_NAME,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "trade_date": TRADE_DATE,
        "league_year": LEAGUE_YEAR,
        "release_valid": release_valid,
        "validation_checks_passed": checks_passed,
        "validation_checks_total": len(validation_rows),
        "source_coverage_release": source_metadata.get("release_name"),
        "teams_queued": len(queue),
        "research_batches": len(batch_paths),
        "batch_size": BATCH_SIZE,
        "passing_packages": sum(profile["passed_rows"] for profile in package_profiles.values()),
        "total_team_package_exposures": sum(
            sum(profile["exposures"].values()) for profile in package_profiles.values()
        ),
        "risk_tier_counts": dict(sorted(Counter(row["salary_proxy_tier"] for row in queue).items())),
        "package_profiles": package_profiles,
        "first_batch": str(batch_paths[0]),
        "batch_files": [str(path) for path in batch_paths],
        "queue_file": str(outputs / QUEUE_OUTPUT),
        "priority_summary_file": str(outputs / SUMMARY_OUTPUT),
        "readiness_file": str(outputs / READINESS_OUTPUT),
        "non_destructive": True,
        "final_package_legality_released": False,
        "player_cba_research_track_pending": True,
    }

    print("[6/6] Saving queue, priority summary, readiness, and metadata")
    write_csv(outputs / QUEUE_OUTPUT, output_headers, queue)
    write_csv(
        outputs / SUMMARY_OUTPUT,
        [
            "team_cba_priority_rank",
            "team_cba_batch_id",
            "team_abbreviation",
            "salary_proxy_tier",
            "team_cba_risk_reason",
            "closest_proxy_threshold_distance",
            "one_for_one_passing_package_exposure",
            "two_for_one_passing_package_exposure",
            "total_passing_package_exposure",
        ],
        summary_rows,
    )
    write_csv(
        outputs / READINESS_OUTPUT,
        ["check_name", "passed", "observed", "expected"],
        validation_rows,
    )
    with (outputs / METADATA_OUTPUT).open("w", encoding="utf-8") as handle:
        json.dump(safe_json(metadata), handle, indent=2)
        handle.write("\n")

    print()
    print("=" * 80)
    print("TEAM CBA RESEARCH PACKETS COMPLETE")
    print("=" * 80)
    print(f"Teams queued: {len(queue)}")
    print(f"Passing packages represented: {metadata['passing_packages']:,}")
    print(f"Team-package exposures: {metadata['total_team_package_exposures']:,}")
    print(f"Research batches: {len(batch_paths)}")
    print(f"Validation checks passed: {checks_passed}/{len(validation_rows)}")
    print(f"Release valid: {release_valid}")
    print(f"Final package legality released: {metadata['final_package_legality_released']}")
    print()
    print("FIRST BATCH")
    print(batch_paths[0])
    print()
    print("SAVED FILES")
    for path in (
        outputs / QUEUE_OUTPUT,
        outputs / SUMMARY_OUTPUT,
        outputs / READINESS_OUTPUT,
        outputs / METADATA_OUTPUT,
        *batch_paths,
    ):
        print(path)

    return 0 if release_valid else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
