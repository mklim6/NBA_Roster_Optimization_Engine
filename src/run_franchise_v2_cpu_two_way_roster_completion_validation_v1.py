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

    command = [
        sys.executable,
        str(SRC / "run_franchise_v2_roster_lifecycle_trace_v1.py"),
        "--seasons",
        "1",
    ]
    completed = subprocess.run(command, cwd=ROOT)
    if completed.returncode != 0:
        print("CPU TWO-WAY ROSTER COMPLETION RUNTIME VALIDATION FAILED")
        print("The protected lifecycle trace returned a nonzero exit code.")
        return completed.returncode

    after = latest_trace()
    if after is None or after == before:
        print("CPU TWO-WAY ROSTER COMPLETION RUNTIME VALIDATION FAILED")
        print("A new protected trace directory was not produced.")
        return 1

    summary_path = after / "roster_lifecycle_summary.json"
    team_path = after / "roster_lifecycle_team_stages.csv"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    with team_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    boundary_rows = [
        row for row in rows
        if str(row.get("stage") or "").strip().upper()
        in {"NEXT_SEASON_BOUNDARY", "NEXT_SEASON_ROUNDTRIP", "REGULAR_SEASON_OPEN"}
    ]
    if not boundary_rows:
        print("CPU TWO-WAY ROSTER COMPLETION RUNTIME VALIDATION FAILED")
        print("No next-season boundary rows were captured.")
        return 1

    # Use the latest sequence because some trace variants capture both boundary
    # and the verified roundtrip.
    latest_sequence = max(int(row.get("sequence", 0) or 0) for row in boundary_rows)
    final_rows = [
        row for row in boundary_rows
        if int(row.get("sequence", 0) or 0) == latest_sequence
    ]

    two_way_counts = [int(row.get("two_way_contract_count", 0) or 0) for row in final_rows]
    standard_counts = [int(row.get("standard_contract_count", 0) or 0) for row in final_rows]
    teams_with_two_way = sum(1 for value in two_way_counts if value > 0)
    teams_at_three = sum(1 for value in two_way_counts if value == 3)
    max_two_way = max(two_way_counts) if two_way_counts else 0
    min_standard = min(standard_counts) if standard_counts else 0
    max_standard = max(standard_counts) if standard_counts else 0

    trace_passed = bool(summary.get("trace_passed"))
    active_unchanged = bool(summary.get("active_checkpoint_family_unchanged"))

    print("=" * 88)
    print("FRANCHISE V2 CPU TWO-WAY ROSTER COMPLETION V1 RUNTIME VALIDATION")
    print("=" * 88)
    print(f"Trace passed: YES" if trace_passed else "Trace passed: NO")
    print(f"Active checkpoint unchanged: YES" if active_unchanged else "Active checkpoint unchanged: NO")
    print(f"Boundary team rows: {len(final_rows)}")
    print(f"Teams with >=1 two-way: {teams_with_two_way}")
    print(f"Teams with exactly 3 two-way: {teams_at_three}")
    print(f"Two-way range: {min(two_way_counts) if two_way_counts else 0}-{max_two_way}")
    print(f"Standard-contract range: {min_standard}-{max_standard}")
    print(f"Trace: {after}")

    passed = (
        trace_passed
        and active_unchanged
        and len(final_rows) == 30
        and teams_with_two_way >= 29
        and max_two_way <= 3
        and 14 <= min_standard <= max_standard <= 15
    )

    if passed:
        print("CPU TWO-WAY ROSTER COMPLETION RUNTIME VALIDATION PASSED")
        return 0

    print("CPU TWO-WAY ROSTER COMPLETION RUNTIME VALIDATION FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
