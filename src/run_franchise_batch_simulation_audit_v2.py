from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_batch_simulation_audit_v2 import (
    run_batch_simulation_audit,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run isolated full-season + postseason "
            "Franchise Mode realism audits without "
            "mutating the durable checkpoint."
        )
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=10,
        help=(
            "Number of independent seasons. "
            "Default: 10. Max: 100."
        ),
    )
    parser.add_argument(
        "--seed-base",
        type=int,
        default=2026081300,
        help=(
            "First random seed. Each run adds 1."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
    )
    args = parser.parse_args()

    print("=" * 108)
    print(
        "FRANCHISE BATCH SIMULATION AUDIT V2.1 · CALIBRATION GRADE"
    )
    print("=" * 108)
    print(
        f"Runs: {args.runs} | "
        f"Seed base: {args.seed_base}"
    )
    print(
        "Mode: isolated deepcopy simulations; "
        "durable checkpoint is read-only"
    )
    print()

    result = run_batch_simulation_audit(
        runs=args.runs,
        seed_base=args.seed_base,
        quiet=args.quiet,
    )

    print()
    print("=" * 108)
    print(
        "BATCH SIMULATION AUDIT COMPLETE"
    )
    print("=" * 108)
    print(
        f"Batch ID: {result.batch_id}"
    )
    print(
        f"Season: {result.season_label}"
    )
    print(
        f"Runs: {result.runs}"
    )
    print(
        f"Unique champions: "
        f"{result.unique_champions}"
    )
    print(
        f"Calibration / structural review items: "
        f"{result.realism_warning_count}"
    )
    print(
        f"Elapsed: "
        f"{result.elapsed_seconds:.2f}s"
    )
    print(
        f"Output directory: "
        f"{result.output_directory}"
    )
    print(
        f"Batch ZIP: {result.zip_path}"
    )
    print(
        f"ZIP SHA256: "
        f"{result.zip_sha256}"
    )
    print(
        f"Checkpoint SHA256 unchanged: "
        f"{result.checkpoint_sha256}"
    )
    priority_path = (
        ROOT
        / result.output_directory
        / "batch_calibration_priorities.csv"
    )
    if priority_path.is_file():
        import csv
        with priority_path.open(
            "r",
            newline="",
            encoding="utf-8-sig",
        ) as handle:
            priorities = list(
                csv.DictReader(handle)
            )
        print()
        print("TOP CALIBRATION PRIORITIES")
        if priorities:
            for row in priorities[:8]:
                print(
                    "  "
                    f"#{row['priority_rank']} "
                    f"{row['label']}: "
                    f"sim={float(row['simulated_mean']):.3f} "
                    f"vs NBA={float(row['benchmark']):.3f} "
                    f"delta={float(row['delta']):+.3f} "
                    f"[{row['status']}]"
                )
        else:
            print("  None outside the diagnostic tolerance bands.")
    print()
    print(
        "READ-ONLY BATCH COMPLETE. No live roster, "
        "trade, draft-right, contract, FA, medical, "
        "schedule, season-history, or checkpoint "
        "mutation was performed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
