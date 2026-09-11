from __future__ import annotations

import argparse
from pathlib import Path

from franchise_free_agency_cpu_offseason_soak_v1 import (
    DEFAULT_SOAK_MAX_DAYS,
    DEFAULT_SOAK_MAX_SIGNINGS_PER_DAY,
    DEFAULT_SOAK_MAX_TARGETS_PER_TEAM,
    DEFAULT_SOAK_MAX_TOTAL_SIGNINGS,
    DEFAULT_SOAK_REPLAY_COUNT,
    build_cpu_offseason_soak_audit,
)



def _progress(event: dict) -> None:
    stage = str(event.get("stage", ""))
    if stage == "loading_checkpoint":
        print(f"[1/4] Loading canonical checkpoint for {event.get('replay_count')} pristine replay(s)...", flush=True)
    elif stage == "replay_start":
        print(f"[2/4] Replay {event.get('replay_number')}/{event.get('replay_count')} running...", flush=True)
    elif stage == "replay_complete":
        print(
            f"      Replay {event.get('replay_number')}/{event.get('replay_count')} complete · "
            f"{event.get('signing_count')} signing(s) · {event.get('days_used')} day(s) · "
            f"{event.get('terminal_reason')}",
            flush=True,
        )
    elif stage == "packaging":
        print(f"[3/4] Packaging audit exports · baseline signings: {event.get('baseline_signings')}...", flush=True)
    elif stage == "complete":
        print(f"[4/4] Final verification complete · strict checks: {'PASS' if event.get('strict_pass') else 'FAIL'}", flush=True)

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the read-only sequential CPU free-agency offseason replay soak."
    )
    parser.add_argument("--replays", type=int, default=DEFAULT_SOAK_REPLAY_COUNT)
    parser.add_argument("--max-days", type=int, default=DEFAULT_SOAK_MAX_DAYS)
    parser.add_argument("--max-signings-per-day", type=int, default=DEFAULT_SOAK_MAX_SIGNINGS_PER_DAY)
    parser.add_argument("--max-total-signings", type=int, default=DEFAULT_SOAK_MAX_TOTAL_SIGNINGS)
    parser.add_argument("--max-targets-per-team", type=int, default=DEFAULT_SOAK_MAX_TARGETS_PER_TEAM)
    parser.add_argument("--output-directory", default="outputs/audits")
    args = parser.parse_args()

    result = build_cpu_offseason_soak_audit(
        output_directory=Path(args.output_directory),
        replay_count=args.replays,
        max_days=args.max_days,
        max_signings_per_day=args.max_signings_per_day,
        max_total_signings=args.max_total_signings,
        max_targets_per_team=args.max_targets_per_team,
        progress_callback=_progress,
    )
    print("=" * 112)
    print("CPU FREE AGENCY MULTI-OFFSEASON REPLAY SOAK AUDIT V1")
    print("=" * 112)
    print(f"Season: {result.season_label}")
    print(f"Live phase: {result.live_phase}")
    print(f"Analysis phase: {result.analysis_phase}")
    print(f"Pristine replays: {result.replay_count}")
    print("Production randomness injected: False")
    print(f"Strict behavioral checks: {'PASS' if result.strict_pass else 'FAIL'}")
    print(f"Baseline signings: {result.baseline_signing_count}")
    print(f"Baseline days used: {result.baseline_days_used}")
    print(f"Baseline terminal reason: {result.baseline_terminal_reason}")
    print(f"Baseline outcome fingerprint: {result.baseline_outcome_fingerprint}")
    print(f"Checkpoint SHA256: {result.checkpoint_sha256}")
    print(f"Soak ZIP: {result.output_zip}")
    print(f"Soak ZIP SHA256: {result.zip_sha256}")
    print()
    print("ROW COUNTS")
    for name, count in sorted(result.row_counts.items()):
        print(f"  {name}: {count}")
    print()
    if result.failed_checks:
        print("FAILED CHECKS")
        for check in result.failed_checks:
            print(f"  {check}")
        return 1
    print("CPU FREE AGENCY MULTI-OFFSEASON REPLAY SOAK AUDIT V1 PASSED")
    print("READ-ONLY SOAK: no signing, roster move, calendar advance, Trade Machine mutation, or checkpoint write touched the live franchise.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
