from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_free_agency_cpu_execution_v1 import (  # noqa: E402
    CPU_FREE_AGENCY_CONFIRMATION_TOKEN,
    build_cpu_free_agency_execution_plan_from_checkpoint,
    execute_cpu_free_agency_round_durably,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preview or explicitly execute a bounded CPU free-agency round."
    )
    parser.add_argument("--commit", action="store_true", help="Allow durable CPU signings.")
    parser.add_argument(
        "--confirm",
        default="",
        help=f"Required with --commit: {CPU_FREE_AGENCY_CONFIRMATION_TOKEN}",
    )
    parser.add_argument("--max-signings", type=int, default=3)
    parser.add_argument("--max-targets-per-team", type=int, default=5)
    args = parser.parse_args()

    if not args.commit:
        plan = build_cpu_free_agency_execution_plan_from_checkpoint(
            max_targets_per_team=args.max_targets_per_team,
        )
        print("=" * 108)
        print("FRANCHISE FREE AGENCY CPU EXECUTION V1 PREVIEW")
        print("=" * 108)
        print(f"Season: {plan.season_label}")
        print(f"Phase: {plan.phase}")
        print(f"Controlled teams: {', '.join(plan.controlled_teams) if plan.controlled_teams else 'None'}")
        print(f"Generated legal CPU offers: {plan.generated_offer_count}")
        print(f"CPU player markets: {plan.market_count}")
        print(f"Accepted winner markets: {plan.winner_market_count}")
        for index, opportunity in enumerate(plan.opportunities[:10], start=1):
            print(
                f"  #{index} {opportunity.player_name} -> {opportunity.winner_team_abbreviation} "
                f"${opportunity.annual_salary:,.0f}/yr x {opportunity.years} "
                f"utility={opportunity.winner_utility_score:.1f}"
            )
        print("\nPREVIEW ONLY. No checkpoint write was performed.")
        print(
            "To execute later during the offseason, rerun with --commit --confirm "
            f"{CPU_FREE_AGENCY_CONFIRMATION_TOKEN}"
        )
        return 0

    if args.confirm != CPU_FREE_AGENCY_CONFIRMATION_TOKEN:
        raise SystemExit(
            "Durable CPU free-agency execution requires --confirm "
            + CPU_FREE_AGENCY_CONFIRMATION_TOKEN
        )

    result = execute_cpu_free_agency_round_durably(
        max_signings=args.max_signings,
        max_targets_per_team=args.max_targets_per_team,
    )
    print("=" * 108)
    print("FRANCHISE FREE AGENCY CPU EXECUTION V1 ROUND COMPLETE")
    print("=" * 108)
    print(json.dumps({
        "status": result.status,
        "committed_signings": result.committed_signing_count,
        "stop_reason": result.stop_reason,
        "checkpoint_hash_before": result.checkpoint_hash_before,
        "checkpoint_hash_after": result.checkpoint_hash_after,
        "signings": [
            {
                "transaction_id": item.transaction_id,
                "player": item.player_name,
                "team": item.team_abbreviation,
                "salary": item.annual_salary,
                "years": item.years,
            }
            for item in result.signings
        ],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
