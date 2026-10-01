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


def main() -> int:
    before = latest_trace()

    completed = subprocess.run(
        [
            sys.executable,
            str(SRC / "run_franchise_v2_roster_lifecycle_trace_v1.py"),
            "--seasons",
            "1",
        ],
        cwd=ROOT,
    )
    if completed.returncode != 0:
        print("CPU TWO-WAY FAIR-ALLOCATION RUNTIME VALIDATION FAILED")
        return completed.returncode

    after = latest_trace()
    if after is None or after == before:
        print("CPU TWO-WAY FAIR-ALLOCATION RUNTIME VALIDATION FAILED")
        print("No new trace directory was produced.")
        return 1

    summary = json.loads(
        (after / "roster_lifecycle_summary.json").read_text(encoding="utf-8")
    )
    with (after / "roster_lifecycle_team_stages.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))

    boundary_rows = [
        row for row in rows
        if str(row.get("stage") or "").strip().upper()
        in {"NEXT_SEASON_BOUNDARY", "NEXT_SEASON_ROUNDTRIP", "REGULAR_SEASON_OPEN"}
    ]
    if not boundary_rows:
        print("CPU TWO-WAY FAIR-ALLOCATION RUNTIME VALIDATION FAILED")
        print("No next-season boundary rows were captured.")
        return 1

    latest_sequence = max(int(row.get("sequence", 0) or 0) for row in boundary_rows)
    final_rows = [
        row for row in boundary_rows
        if int(row.get("sequence", 0) or 0) == latest_sequence
    ]

    two_way_counts = [int(row.get("two_way_contract_count", 0) or 0) for row in final_rows]
    standard_counts = [int(row.get("standard_contract_count", 0) or 0) for row in final_rows]

    teams_with_one = sum(1 for value in two_way_counts if value >= 1)
    teams_with_two = sum(1 for value in two_way_counts if value >= 2)
    teams_with_three = sum(1 for value in two_way_counts if value == 3)

    trace_passed = bool(summary.get("trace_passed"))
    active_unchanged = bool(summary.get("active_checkpoint_family_unchanged"))

    print("=" * 92)
    print("FRANCHISE V2 CPU TWO-WAY FAIR-ALLOCATION HOTFIX V1.0.1 RUNTIME VALIDATION")
    print("=" * 92)
    print(f"Trace passed: {'YES' if trace_passed else 'NO'}")
    print(f"Active checkpoint unchanged: {'YES' if active_unchanged else 'NO'}")
    print(f"Boundary team rows: {len(final_rows)}")
    print(f"Teams with >=1 two-way: {teams_with_one}")
    print(f"Teams with >=2 two-way: {teams_with_two}")
    print(f"Teams with exactly 3:    {teams_with_three}")
    print(f"Two-way range: {min(two_way_counts) if two_way_counts else 0}-{max(two_way_counts) if two_way_counts else 0}")
    print(f"Standard-contract range: {min(standard_counts) if standard_counts else 0}-{max(standard_counts) if standard_counts else 0}")
    print(f"Total two-way contracts: {sum(two_way_counts)}")
    print(f"Trace: {after}")

    passed = (
        trace_passed
        and active_unchanged
        and len(final_rows) == 30
        and teams_with_one >= 29
        and max(two_way_counts, default=0) <= 3
        and min(standard_counts, default=0) >= 14
        and max(standard_counts, default=99) <= 15
    )

    if passed:
        print("CPU TWO-WAY FAIR-ALLOCATION RUNTIME VALIDATION PASSED")
        return 0

    print("CPU TWO-WAY FAIR-ALLOCATION RUNTIME VALIDATION FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
