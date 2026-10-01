from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import run_franchise_protected_offseason_continuation_v1 as continuation
from run_franchise_v2_protected_multi_season_soak_v1 import (
    _v2_provenance_preflight,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Continue the protected franchise soak from an isolated checkpoint "
            "on the V2 branch using lineage/provenance validation."
        )
    )
    parser.add_argument("--source-checkpoint", required=True)
    parser.add_argument("--seasons", type=int, default=1)
    parser.add_argument("--keep-artifacts", action="store_true")
    args = parser.parse_args()

    print("FRANCHISE V2 PROTECTED OFFSEASON CONTINUATION V1")
    print(f"Project root: {ROOT}")
    print("Active franchise mutation: FORBIDDEN")
    print(f"Requested continued seasons: {args.seasons}")
    print("V1 source-hash freeze: replaced by V2 lineage/provenance preflight")
    print("Checkpoint isolation/safety: unchanged")
    print()

    original = continuation._validate_release_freeze
    started = time.perf_counter()
    try:
        continuation._validate_release_freeze = _v2_provenance_preflight
        report = continuation.run_continuation(
            args.source_checkpoint,
            seasons=args.seasons,
            keep_artifacts=args.keep_artifacts,
        )
    finally:
        continuation._validate_release_freeze = original

    elapsed = time.perf_counter() - started
    print()
    print("V2 CONTINUATION SUMMARY")
    for season in report.get("season_reports", []):
        print(
            f"  {season.get('source_season')} -> "
            f"{season.get('target_season', '?')} - "
            f"champion={season.get('champion', '?')} - "
            f"draft={season.get('draft', {}).get('picks', '?')} picks - "
            f"{'PASS' if season.get('passed') else 'FAIL'}"
        )
    print(
        "Completed continued seasons: "
        f"{report.get('completed_continued_seasons', 0)}/"
        f"{report.get('requested_continued_seasons', args.seasons)}"
    )
    print(f"Elapsed: {elapsed:.3f}s")

    if report.get("passed"):
        print("FRANCHISE V2 PROTECTED OFFSEASON CONTINUATION V1 PASSED")
        return 0

    print("FRANCHISE V2 PROTECTED OFFSEASON CONTINUATION V1 FAILED")
    if report.get("error"):
        print(f"Error: {report['error']}")
    for name in report.get("failed_checks", []) or []:
        print(f"  - {name}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
