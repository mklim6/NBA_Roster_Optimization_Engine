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
    dirs = [p for p in TRACE_ROOT.glob("trace_*") if p.is_dir()]
    return max(dirs, key=lambda p: p.stat().st_mtime_ns) if dirs else None


def season_boundary(rows: list[dict[str, str]], season: str) -> list[dict[str, str]]:
    eligible = [
        row
        for row in rows
        if str(row.get("season_label") or "") == season
        and str(row.get("stage") or "").upper()
        in {"NEXT_SEASON_BOUNDARY", "NEXT_SEASON_ROUNDTRIP", "REGULAR_SEASON_OPEN"}
    ]
    if not eligible:
        return []
    seq = max(int(row.get("sequence", 0) or 0) for row in eligible)
    return [row for row in eligible if int(row.get("sequence", 0) or 0) == seq]


def summarize(rows: list[dict[str, str]]) -> dict[str, int]:
    std = [int(row.get("standard_contract_count", 0) or 0) for row in rows]
    tw = [int(row.get("two_way_contract_count", 0) or 0) for row in rows]
    return {
        "teams": len(rows),
        "standard_min": min(std) if std else 0,
        "standard_max": max(std) if std else 0,
        "two_way_min": min(tw) if tw else 0,
        "two_way_max": max(tw) if tw else 0,
        "two_way_total": sum(tw),
        "teams_with_two_way": sum(1 for value in tw if value > 0),
    }


def main() -> int:
    before = latest_trace()
    completed = subprocess.run(
        [
            sys.executable,
            str(SRC / "run_franchise_v2_roster_lifecycle_trace_v1.py"),
            "--seasons",
            "5",
        ],
        cwd=ROOT,
    )
    if completed.returncode != 0:
        print("UNDRAFTED ROOKIE FA BRIDGE RUNTIME VALIDATION FAILED")
        return completed.returncode

    after = latest_trace()
    if after is None or after == before:
        print("UNDRAFTED ROOKIE FA BRIDGE RUNTIME VALIDATION FAILED")
        print("No new protected trace directory was produced.")
        return 1

    summary = json.loads(
        (after / "roster_lifecycle_summary.json").read_text(encoding="utf-8")
    )
    with (after / "roster_lifecycle_team_stages.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))

    seasons = ("2027-28", "2028-29", "2029-30", "2030-31", "2031-32")
    results = {season: summarize(season_boundary(rows, season)) for season in seasons}

    print("=" * 92)
    print("FRANCHISE V2 UNDRAFTED ROOKIE FREE AGENT BRIDGE V1 RUNTIME VALIDATION")
    print("=" * 92)
    print(f"Trace passed: {'YES' if summary.get('trace_passed') else 'NO'}")
    print(
        "Active checkpoint unchanged: "
        + ("YES" if summary.get("active_checkpoint_family_unchanged") else "NO")
    )
    for season in seasons:
        row = results[season]
        print(
            f"{season}: teams={row['teams']} "
            f"standard={row['standard_min']}-{row['standard_max']} "
            f"two_way={row['two_way_min']}-{row['two_way_max']} "
            f"two_way_total={row['two_way_total']} "
            f"teams_with_two_way={row['teams_with_two_way']}"
        )
    print(f"Trace: {after}")

    passed = bool(
        summary.get("trace_passed")
        and summary.get("active_checkpoint_family_unchanged")
        and all(results[s]["teams"] == 30 for s in seasons)
        and all(
            14 <= results[s]["standard_min"] <= results[s]["standard_max"] <= 15
            for s in seasons
        )
        and all(results[s]["two_way_max"] <= 3 for s in seasons)
        # Before this bridge the 2031-32 boundary had only 29 total two-way
        # contracts. Fresh undrafted rookies should prevent that deep collapse.
        and results["2031-32"]["two_way_total"] >= 45
        and results["2031-32"]["teams_with_two_way"] >= 25
    )

    if passed:
        print("UNDRAFTED ROOKIE FA BRIDGE RUNTIME VALIDATION PASSED")
        return 0

    print("UNDRAFTED ROOKIE FA BRIDGE RUNTIME VALIDATION FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
