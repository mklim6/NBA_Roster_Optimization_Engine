from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACE_ROOT = ROOT / "outputs" / "v2_roster_lifecycle_trace_v1"
FINAL_STAGES = {"NEXT_SEASON_BOUNDARY", "NEXT_SEASON_ROUNDTRIP", "REGULAR_SEASON_OPEN"}


def integer(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def main() -> int:
    traces = sorted(
        [path for path in TRACE_ROOT.iterdir() if path.is_dir()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    ) if TRACE_ROOT.is_dir() else []
    if not traces:
        raise RuntimeError("No V2 roster lifecycle trace output exists.")
    trace = traces[0]
    path = trace / "roster_lifecycle_population_stages.csv"
    if not path.is_file():
        raise RuntimeError(f"Population-stage CSV missing: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    grouped = {}
    for row in rows:
        if row.get("stage") not in FINAL_STAGES:
            continue
        season = row.get("season_label", "")
        seq = integer(row.get("sequence"), -1)
        current = grouped.get(season)
        if current is None or seq > integer(current.get("sequence"), -1):
            grouped[season] = row

    ordered = sorted(grouped.items())
    print("FRANCHISE V2 PLAYER POPULATION ECOLOGY TRACE AUDIT")
    print(f"Trace: {trace}")
    print()
    print(f"{'Season':<10} {'Players':>8} {'Rostered':>9} {'Free agents':>12} {'2-way':>7} {'Unassigned':>11}")
    print("-" * 64)
    for season, row in ordered:
        print(
            f"{season:<10} "
            f"{integer(row.get('players')):>8} "
            f"{integer(row.get('rostered_players')):>9} "
            f"{integer(row.get('free_agents')):>12} "
            f"{integer(row.get('total_two_way_contracts')):>7} "
            f"{integer(row.get('unassigned_players')):>11}"
        )

    future = [row for season, row in ordered if season != "2026-27"]
    checks = {
        "future_rows_present": len(future) >= 1,
        "no_unassigned_players": all(integer(row.get("unassigned_players")) == 0 for row in future),
        "free_agent_market_below_300_at_open_boundary": all(integer(row.get("free_agents")) <= 300 for row in future),
        "active_player_population_below_850": all(integer(row.get("players")) <= 850 for row in future),
        "two_way_limit_preserved": all(integer(row.get("maximum_two_way_contracts")) <= 3 for row in future),
    }
    print()
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        print("TRACE ECOLOGY AUDIT FAILED")
        for name in failed:
            print(f"  - {name}")
        return 1
    print("TRACE ECOLOGY AUDIT PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
