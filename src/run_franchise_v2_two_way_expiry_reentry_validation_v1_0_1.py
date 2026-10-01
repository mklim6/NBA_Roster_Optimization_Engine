from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TRACE_ROOT = ROOT / "outputs" / "v2_roster_lifecycle_trace_v1"


def latest_trace() -> Path | None:
    rows = [p for p in TRACE_ROOT.glob("trace_*") if p.is_dir()]
    return max(rows, key=lambda p: p.stat().st_mtime_ns) if rows else None


def _season_boundary(rows: list[dict[str, str]], season: str) -> list[dict[str, str]]:
    eligible = [
        row
        for row in rows
        if str(row.get("season_label") or "") == season
        and str(row.get("stage") or "").upper()
        in {"NEXT_SEASON_BOUNDARY", "NEXT_SEASON_ROUNDTRIP", "REGULAR_SEASON_OPEN"}
    ]
    if not eligible:
        return []
    latest_sequence = max(int(row.get("sequence", 0) or 0) for row in eligible)
    return [
        row
        for row in eligible
        if int(row.get("sequence", 0) or 0) == latest_sequence
    ]


def _summary(rows: list[dict[str, str]]) -> dict[str, int]:
    standard = [int(row.get("standard_contract_count", 0) or 0) for row in rows]
    two_way = [int(row.get("two_way_contract_count", 0) or 0) for row in rows]
    return {
        "teams": len(rows),
        "standard_min": min(standard) if standard else 0,
        "standard_max": max(standard) if standard else 0,
        "two_way_min": min(two_way) if two_way else 0,
        "two_way_max": max(two_way) if two_way else 0,
        "two_way_total": sum(two_way),
        "teams_with_two_way": sum(1 for value in two_way if value > 0),
        "teams_with_two_plus": sum(1 for value in two_way if value >= 2),
    }


def main() -> int:
    before = latest_trace()

    completed = subprocess.run(
        [
            sys.executable,
            str(SRC / "run_franchise_v2_roster_lifecycle_trace_v1.py"),
            "--seasons",
            "2",
        ],
        cwd=ROOT,
    )
    if completed.returncode != 0:
        print("TWO-WAY EXPIRY REENTRY RUNTIME VALIDATION FAILED")
        return completed.returncode

    after = latest_trace()
    if after is None or after == before:
        print("TWO-WAY EXPIRY REENTRY RUNTIME VALIDATION FAILED")
        print("No new protected trace directory was produced.")
        return 1

    summary = json.loads(
        (after / "roster_lifecycle_summary.json").read_text(encoding="utf-8")
    )
    with (after / "roster_lifecycle_team_stages.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))

    first_rows = _season_boundary(rows, "2027-28")
    second_rows = _season_boundary(rows, "2028-29")
    first = _summary(first_rows)
    second = _summary(second_rows)

    trace_passed = bool(summary.get("trace_passed"))
    active_unchanged = bool(summary.get("active_checkpoint_family_unchanged"))

    print("=" * 92)
    print("FRANCHISE V2 TWO-WAY EXPIRY REENTRY HOTFIX V1.0.1 RUNTIME VALIDATION")
    print("=" * 92)
    print(f"Trace passed: {'YES' if trace_passed else 'NO'}")
    print(f"Active checkpoint unchanged: {'YES' if active_unchanged else 'NO'}")
    print("")
    print("2027-28 boundary:")
    print(f"  Teams: {first['teams']}")
    print(f"  Standard range: {first['standard_min']}-{first['standard_max']}")
    print(f"  Two-way range: {first['two_way_min']}-{first['two_way_max']}")
    print(f"  Teams with >=2 two-way: {first['teams_with_two_plus']}")
    print(f"  Total two-way: {first['two_way_total']}")
    print("")
    print("2028-29 boundary:")
    print(f"  Teams: {second['teams']}")
    print(f"  Standard range: {second['standard_min']}-{second['standard_max']}")
    print(f"  Two-way range: {second['two_way_min']}-{second['two_way_max']}")
    print(f"  Teams with >=1 two-way: {second['teams_with_two_way']}")
    print(f"  Teams with >=2 two-way: {second['teams_with_two_plus']}")
    print(f"  Total two-way: {second['two_way_total']}")
    print(f"Trace: {after}")

    # The old defect collapsed the second boundary to only 16 total two-way
    # contracts. Require a broad league-wide replenishment, while allowing age
    # and developmental eligibility to change naturally from year to year.
    passed = (
        trace_passed
        and active_unchanged
        and first["teams"] == 30
        and second["teams"] == 30
        and 14 <= first["standard_min"] <= first["standard_max"] <= 15
        and 14 <= second["standard_min"] <= second["standard_max"] <= 15
        and first["two_way_max"] <= 3
        and second["two_way_max"] <= 3
        and first["two_way_total"] >= 50
        and second["two_way_total"] >= 45
        and second["teams_with_two_way"] >= 25
    )

    if passed:
        print("TWO-WAY EXPIRY REENTRY RUNTIME VALIDATION PASSED")
        return 0

    print("TWO-WAY EXPIRY REENTRY RUNTIME VALIDATION FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
