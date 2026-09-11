from __future__ import annotations

import argparse
from pathlib import Path

from franchise_free_agency_cpu_minimum_exception_targeting_v1 import CPU_FREE_AGENCY_MINIMUM_EXCEPTION_TARGETING_VERSION
from franchise_free_agency_cpu_roster_construction_v1 import CPU_FREE_AGENCY_ROSTER_CONSTRUCTION_VERSION
from franchise_free_agency_cpu_offer_economic_intelligence_v1 import CPU_FREE_AGENCY_OFFER_ECONOMIC_INTELLIGENCE_VERSION

from franchise_free_agency_cpu_ai_audit_v1 import (
    FREE_AGENCY_CPU_AI_AUDIT_OFFER_QUALITY_VERSION,
    build_free_agency_cpu_ai_audit,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a read-only Free Agency / CPU AI audit ZIP from the durable franchise checkpoint."
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path("outputs") / "audits"),
        help="Directory for the generated audit ZIP.",
    )
    parser.add_argument(
        "--max-targets-per-team",
        type=int,
        default=5,
        help="Maximum credible CPU FA bids per team. Filtered targets may be replaced by lower target-board rows.",
    )
    args = parser.parse_args()

    print("=" * 112, flush=True)
    print("FREE AGENCY / CPU AI AUDIT V1.1 · OFFER QUALITY + PLAYER INTEREST", flush=True)
    print("=" * 112, flush=True)
    print(f"Extension: {FREE_AGENCY_CPU_AI_AUDIT_OFFER_QUALITY_VERSION}", flush=True)
    print(f"Minimum-exception targeting: {CPU_FREE_AGENCY_MINIMUM_EXCEPTION_TARGETING_VERSION}", flush=True)
    print(f"Roster construction: {CPU_FREE_AGENCY_ROSTER_CONSTRUCTION_VERSION}", flush=True)
    print(f"Offer economics: {CPU_FREE_AGENCY_OFFER_ECONOMIC_INTELLIGENCE_VERSION}", flush=True)
    print("Interest is deterministic player utility, not a signing probability.", flush=True)
    print("", flush=True)

    result = build_free_agency_cpu_ai_audit(
        output_dir=args.output_dir,
        max_targets_per_team=args.max_targets_per_team,
        progress_callback=lambda message: print(message, flush=True),
    )

    print("", flush=True)
    print("=" * 112, flush=True)
    print("FREE AGENCY / CPU AI AUDIT V1.1 RESULTS", flush=True)
    print("=" * 112, flush=True)
    print(f"Season: {result.season_label}", flush=True)
    print(f"Live phase: {result.live_phase}", flush=True)
    print(f"Analysis phase: {result.analysis_phase}", flush=True)
    print(f"Controlled teams: {', '.join(result.controlled_teams) or 'none'}", flush=True)
    print(f"Strict behavioral checks: {'PASS' if result.strict_pass else 'FAIL'}", flush=True)
    print(f"Checkpoint SHA256: {result.checkpoint_sha256}", flush=True)
    print(f"Audit ZIP: {result.output_zip}", flush=True)
    print(f"Audit ZIP SHA256: {result.zip_sha256}", flush=True)
    print("", flush=True)
    print("ROW COUNTS", flush=True)
    for name, count in sorted(result.row_counts.items()):
        print(f"  {name}: {count}", flush=True)
    if result.failed_checks:
        print("", flush=True)
        print("FAILED STRICT CHECKS", flush=True)
        for check in result.failed_checks:
            print(f"  {check}", flush=True)
        return 1
    print("", flush=True)
    print("FREE AGENCY / CPU AI AUDIT V1.1 PASSED", flush=True)
    print("READ-ONLY EXPORT: no signing, roster move, calendar advance, Trade Machine mutation, or checkpoint write was performed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
