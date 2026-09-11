from __future__ import annotations

import argparse
import sys
from pathlib import Path

from franchise_audit_export_v1 import (
    DEFAULT_OUTPUT_DIR,
    build_franchise_audit_export,
)


def configure_utf8_console() -> None:
    for stream in (
        sys.stdout,
        sys.stderr,
    ):
        reconfigure = getattr(
            stream,
            "reconfigure",
            None,
        )
        if callable(reconfigure):
            try:
                reconfigure(
                    encoding="utf-8",
                    errors="replace",
                )
            except Exception:
                pass


def main() -> int:
    configure_utf8_console()

    parser = argparse.ArgumentParser(
        description=(
            "Create a read-only Franchise Audit Export V1 ZIP."
        )
    )
    parser.add_argument(
        "--output-dir",
        default=str(
            DEFAULT_OUTPUT_DIR
        ),
    )
    parser.add_argument(
        "--team",
        default="",
        help=(
            "Active team for the bounded Trade Finder audit. "
            "Defaults to a controlled team, then PHI."
        ),
    )
    parser.add_argument(
        "--skip-trade-finder",
        action="store_true",
        help=(
            "Export franchise state without running the bounded "
            "Trade Finder audit."
        ),
    )
    args = parser.parse_args()

    result = build_franchise_audit_export(
        output_dir=Path(
            args.output_dir
        ),
        include_trade_finder=(
            not args.skip_trade_finder
        ),
        active_trade_finder_team=args.team,
    )

    print("=" * 96)
    print("FRANCHISE AUDIT / SIMULATION EXPORT CENTER V1.1")
    print("=" * 96)
    print("Export ID:", result.export_id)
    print("Season:", result.season_label)
    print(
        "Trade Finder team:",
        result.active_trade_finder_team
        or "N/A",
    )
    print(
        "Trade Finder included:",
        result.include_trade_finder,
    )
    print(
        "Checkpoint SHA256:",
        result.checkpoint_sha256,
    )
    print(
        "State fingerprint:",
        result.state_fingerprint,
    )
    print()
    print("ROW COUNTS")
    for filename, count in sorted(
        result.row_counts.items()
    ):
        print(
            f"  {filename}: {count}"
        )
    print()
    print(
        "Audit ZIP:",
        result.zip_path,
    )
    print(
        "ZIP SHA256:",
        result.zip_sha256,
    )
    print()
    print(
        "READ-ONLY EXPORT COMPLETE. "
        "No live franchise state or checkpoint mutation was performed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
