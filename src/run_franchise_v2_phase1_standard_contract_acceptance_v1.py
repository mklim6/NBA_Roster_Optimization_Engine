from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TRACE_ROOT = ROOT / "outputs" / "v2_roster_lifecycle_trace_v1"


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _latest_trace_dir() -> Path:
    if not TRACE_ROOT.is_dir():
        raise FileNotFoundError(f"Trace root not found: {TRACE_ROOT}")
    candidates = sorted(
        (path for path in TRACE_ROOT.iterdir() if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"No trace directories found under: {TRACE_ROOT}")
    return candidates[0]


def _load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate Phase 1 post-Draft sustainability using standard-contract "
            "counts, not the legacy total team-associated roster count."
        )
    )
    parser.add_argument("--trace-dir", type=Path, default=None)
    parser.add_argument("--expected-seasons", type=int, default=8)
    parser.add_argument("--expected-teams", type=int, default=30)
    parser.add_argument("--target-min", type=int, default=14)
    parser.add_argument("--target-max", type=int, default=15)
    args = parser.parse_args()

    trace_dir = (args.trace_dir or _latest_trace_dir()).resolve()
    team_path = trace_dir / "roster_lifecycle_team_stages.csv"
    summary_path = trace_dir / "roster_lifecycle_summary.json"

    if not team_path.is_file():
        raise FileNotFoundError(f"Missing team-stage CSV: {team_path}")
    if not summary_path.is_file():
        raise FileNotFoundError(f"Missing trace summary: {summary_path}")

    rows = _load_rows(team_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    required = {
        "season_label",
        "stage",
        "team",
        "roster_count",
        "standard_contract_count",
        "two_way_contract_count",
        "other_roster_count",
        "unclassified_roster_count",
        "contract_count_reconciles_to_total",
    }
    actual = set(rows[0].keys()) if rows else set()
    missing_columns = sorted(required - actual)
    if missing_columns:
        print("PHASE 1 STANDARD-CONTRACT SUSTAINABILITY ACCEPTANCE: FAIL")
        print(
            "Trace predates the corrected contract-count diagnostic. Missing: "
            + ", ".join(missing_columns)
        )
        return 1

    post_draft = [row for row in rows if row.get("stage") == "POST_DRAFT_TRIM"]
    by_season: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in post_draft:
        by_season[str(row.get("season_label") or "")].append(row)

    failures: list[str] = []
    details: list[dict[str, Any]] = []

    if len(by_season) != args.expected_seasons:
        failures.append(
            f"Expected {args.expected_seasons} post-Draft seasons but found "
            f"{len(by_season)}."
        )

    for season, season_rows in sorted(by_season.items()):
        teams = {str(row.get("team") or "").strip().upper() for row in season_rows}
        standards = [_to_int(row.get("standard_contract_count")) for row in season_rows]
        two_ways = [_to_int(row.get("two_way_contract_count")) for row in season_rows]
        others = [_to_int(row.get("other_roster_count")) for row in season_rows]
        unclassified = [
            _to_int(row.get("unclassified_roster_count"))
            for row in season_rows
        ]
        bad_standard = [
            row
            for row in season_rows
            if not (
                args.target_min
                <= _to_int(row.get("standard_contract_count"))
                <= args.target_max
            )
        ]
        unreconciled = [
            row
            for row in season_rows
            if not _to_bool(row.get("contract_count_reconciles_to_total"))
        ]
        bad_unclassified = [
            row
            for row in season_rows
            if _to_int(row.get("unclassified_roster_count")) != 0
        ]

        detail = {
            "season_label": season,
            "teams": len(teams),
            "min_standard_contracts": min(standards) if standards else None,
            "max_standard_contracts": max(standards) if standards else None,
            "teams_outside_standard_target": len(bad_standard),
            "total_two_way_contracts": sum(two_ways),
            "max_two_way_contracts": max(two_ways) if two_ways else None,
            "total_other_roster_players": sum(others),
            "total_unclassified_roster_players": sum(unclassified),
            "unreconciled_team_rows": len(unreconciled),
        }
        details.append(detail)

        if len(teams) != args.expected_teams:
            failures.append(
                f"{season} has {len(teams)} unique teams instead of "
                f"{args.expected_teams}."
            )
        if bad_standard:
            bad_teams = ",".join(
                sorted(str(row.get("team") or "") for row in bad_standard)
            )
            failures.append(
                f"{season} has {len(bad_standard)} team(s) outside the "
                f"{args.target_min}-{args.target_max} standard-contract target: "
                f"{bad_teams}"
            )
        if bad_unclassified:
            failures.append(
                f"{season} has {len(bad_unclassified)} team row(s) with "
                "unclassified roster ids."
            )
        if unreconciled:
            failures.append(
                f"{season} has {len(unreconciled)} team row(s) whose contract "
                "classification does not reconcile to total roster count."
            )

    if not bool(summary.get("trace_passed")):
        failures.append("Protected lifecycle trace did not pass.")
    if not bool(summary.get("active_checkpoint_family_unchanged")):
        failures.append("Active checkpoint family changed.")

    report = {
        "version": "franchise-v2-phase1-standard-contract-acceptance-v1",
        "trace_dir": str(trace_dir),
        "expected_seasons": args.expected_seasons,
        "expected_teams": args.expected_teams,
        "target_min": args.target_min,
        "target_max": args.target_max,
        "trace_passed": bool(summary.get("trace_passed")),
        "active_checkpoint_family_unchanged": bool(
            summary.get("active_checkpoint_family_unchanged")
        ),
        "season_details": details,
        "failures": failures,
        "passed": not failures,
    }
    report_path = trace_dir / "phase1_standard_contract_acceptance_v1.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=== PHASE 1 STANDARD-CONTRACT SUSTAINABILITY ACCEPTANCE ===")
    print(f"Trace directory: {trace_dir}")
    print(f"Trace passed: {report['trace_passed']}")
    print(
        "Active checkpoint unchanged: "
        f"{report['active_checkpoint_family_unchanged']}"
    )
    print(f"Post-Draft seasons found: {len(by_season)}")
    print()

    for row in details:
        print(
            f"{row['season_label']}: teams={row['teams']}, "
            f"standard={row['min_standard_contracts']}-"
            f"{row['max_standard_contracts']}, "
            f"outside_target={row['teams_outside_standard_target']}, "
            f"two_way_total={row['total_two_way_contracts']}, "
            f"two_way_max={row['max_two_way_contracts']}, "
            f"other={row['total_other_roster_players']}, "
            f"unclassified={row['total_unclassified_roster_players']}"
        )

    print()
    if failures:
        print("PHASE 1 STANDARD-CONTRACT SUSTAINABILITY ACCEPTANCE: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        print(f"Report: {report_path}")
        return 1

    print("PHASE 1 STANDARD-CONTRACT SUSTAINABILITY ACCEPTANCE: PASS")
    print(
        f"All {args.expected_seasons} post-Draft checkpoints contain "
        f"{args.expected_teams} teams with {args.target_min}-{args.target_max} "
        "standard contracts; two-way players were measured separately."
    )
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
